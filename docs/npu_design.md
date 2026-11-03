# NPU モード 設計書（Intel NPU / Windows 専用）

状態: **実装済み（feature/npu-mode ブランチ）** / 作成日: 2026-11-03

> 本書は設計書として書き、実装時に分かった事項を反映済み。設計から変わった点は末尾の「実装での確定事項」にまとめている。

PoC（Core Ultra 9 285K・OpenVINO 2026.4）で、全 ASR エンジンが Intel NPU 上で CPU 版と同等の精度で動くことを確認した。本書はそれを製品に組み込むための設計である。

## 1. 目的と非目的

**目的**

- 会議中の CPU 負荷を下げる。ASR の encoder を NPU に逃がし、Teams などと CPU を取り合わないようにする。
- 対応 7 言語（ja / en / zh / ko / fr / de / es）すべてで NPU を使えること。
- CPU モードは現状の使い勝手を一切変えない。NPU は **オプトイン** とする。

**非目的**

- AMD NPU、Apple Neural Engine、Qualcomm NPU への対応。
- 翻訳（CTranslate2）の NPU 化。翻訳は CPU のまま。
- NPU 前提の最適化。NPU が無い PC・古い PC での動作が常に第一である。

## 2. PoC の結果（設計の前提）

FLEURS test の各言語 40〜58 本。CER（ja / zh / ko）と WER（en / fr / de / es）。

| 言語 | エンジン | CPU int8（現行） | NPU fp16 |
|---|---|---|---|
| ja | ReazonSpeech | 11.3% | 11.5% |
| en | Parakeet TDT v3 | 6.0% | 5.7% |
| fr | Parakeet TDT v3 | 8.3% | 7.2% |
| de | Parakeet TDT v3 | 7.4% | 6.0% |
| es | Parakeet TDT v3 | 3.3% | 3.4% |
| zh | SenseVoice | 6.6% | 6.4%（LayerNorm 修正後） |
| ko | SenseVoice | 7.9% | 7.8%（LayerNorm 修正後） |

NPU で CPU を使わない部分: encoder のみ。decoder / joiner（transducer）、CTC の貪欲デコード、前処理（fbank）は CPU のまま。

### PoC で分かった制約（設計に直結）

| 制約 | 内容 | 設計上の扱い |
|---|---|---|
| 静的 shape | 動的 shape だと NPU コンパイルがクラッシュする（プロセスごと落ちる） | encoder を固定長窓にする。短い発話は無音で埋める |
| int8 不可 | 現行の int8 は動的量子化（`DynamicQuantizeLinear`）で NPU に使えない | fp16 用の別モデルを持つ |
| fp16 オーバーフロー | SenseVoice は LayerNorm の `Pow(x-mean,2)` が fp16 上限を超え、zh が壊れる | 入力を 1/256 に縮小する等価変換をモデルに焼き込む（§5） |
| 初回コンパイル | ReazonSpeech 約 22 秒 / Parakeet 約 29 秒 / SenseVoice 約 52 秒。キャッシュ後は数秒 | バックグラウンドコンパイル + CPU 先行（§4） |
| Parakeet 初回推論 | 初回のみ約 7.6 秒かかる | コンパイル直後にダミー推論でウォームアップ |

## 3. 全体構成

### 3.1 モジュール

```
core/
  asr_engine.py            既存。NPU バックエンドを呼び出す側に最小変更
  npu/
    __init__.py            公開 API: is_npu_available(), create_npu_recognizer(...)
    device.py              NPU 検出（OpenVINO → PnP のフォールバック）
    base.py                NpuRecognizer 基底 (sherpa の OfflineRecognizer と同じ呼び口)
    reazon.py              ReazonSpeech (zipformer2 transducer, fbank 80, byte-BPE 復号)
    parakeet.py            Parakeet TDT v3 (mel + encoder + decoder + joint, TDT 貪欲)
    sensevoice.py          SenseVoice (fbank 80 + LFR 7/6 + CMVN, CTC 貪欲)
    cache.py               OpenVINO CACHE_DIR の場所・掃除
    addons.py              アドオン ZIP の自動展開（§8.4）。openvino の import より前に実行
scripts/
  build_npu_models.py      NPU 用モデルの作成（固定長化・LN 修正・fp16 圧縮）※開発/CI 用
  eval_npu.py              CPU vs NPU の WER/CER 回帰比較（PoC の評価スクリプトを整理）
```

### 3.2 `asr_engine.py` との結合方針

`asr_engine.py` の `transcribe_pcm` には、sherpa の呼び出し
（`create_stream` → `accept_waveform` → `decode_stream` → `result.text`）が 6 か所に重複している。
NPU 側のクラスも**同じ 3 メソッドを持つ**ようにして、既存コードの分岐を増やさない。

- `NpuRecognizer` は `create_stream()` / `decode_stream()` / `stream.result.text` を持つ薄い互換層とする。
- 既存の重複ブロックは小さな `_decode(recognizer, pcm)` に畳む（リファクタ。NPU とは独立してテストできる）。
- `BusinessASREngine.__init__` に `device: str = "cpu"` を追加。`"npu"` のとき `_init_reazon/_init_parakeet/_init_sense_voice` は **まず NPU 版の生成を試み、失敗したら従来の sherpa（CPU）を作る**。
- 言語ルーティング（`transcribe_pcm` の Strategy A/B/C）には**一切手を入れない**。

### 3.3 フォールバックの粒度

**エンジン単位**で CPU にフォールバックする。例えば Parakeet のモデルが未ダウンロードなら、
en/fr/de/es だけ CPU で動き、ja と zh/ko は NPU で動く。ログとUIで「どの言語がNPUか」を見せる。

NPU モード時に CPU へ落とす条件:

1. `openvino` が import できない / NPU デバイスが無い
2. NPU 用モデルが models/npu/ に無い
3. コンパイル失敗（古いドライバなど）・推論時に例外
4. 例外が連続した場合、そのエンジンはそのセッション中 CPU 固定にして再試行しない

## 4. 起動・コンパイル・キャッシュ

### 4.1 CPU 先行 → NPU 切り替え

NPU モードを選んでも、初回は ASR のコンパイルに最大 50 秒かかる。会議の冒頭を欠かさないため:

1. 従来どおり CPU 版 recognizer をロードして**すぐ使える状態**にする。
2. バックグラウンドスレッドで NPU 版をコンパイル → ダミー推論でウォームアップ。
3. 完了したら、その言語のエンジンを NPU 版に**無停止で差し替える**（参照の入れ替えのみ。発話の処理中は古い方を使い切る）。
4. 差し替え後、CPU 版は解放する（NPU モードの意味はメモリ・CPU の節約でもあるため）。

メモリの一時的な二重持ちを避けたい場合は、設定で「NPU 準備中は待つ（CPU を使わない）」も選べるようにする（既定は CPU 先行）。

### 4.2 キャッシュ

- OpenVINO の `CACHE_DIR` を使う。保存先はユーザー領域（`~/hayamimi-polyglot/cache/openvino/`）。ポータブル版では実行フォルダ内 `cache/openvino/`。
- コンパイル済みバイナリは**同梱しない**（ドライバ・OpenVINO のバージョンに依存するため）。キャッシュキーは OpenVINO 側が管理する。
- 2 回目以降の起動は PoC 実測で数秒（ReazonSpeech 3.4 秒）。
- キャッシュが壊れた場合は削除して再コンパイル。ログに出す。

### 4.3 遅延ロード

既存の「選択言語のモデルだけロードする」方針（`sync_active_models`）をそのまま踏襲する。
NPU 版もアクティブ言語に応じてコンパイル・解放する。

## 5. モデル仕様（NPU 用）

すべて **OpenVINO IR（`.xml` + `.bin`、fp16）** で配布する。実行時に ONNX 変換をしない
（`onnx` パッケージ不要・起動時間短縮・再現性）。

| エンジン | 窓（固定長） | 入力 | NPU に載せる範囲 | 備考 |
|---|---|---|---|---|
| ReazonSpeech | 15 秒（1500 フレーム）の 1 窓 | fbank 80 | encoder | `x_lens` を定数化したグラフを変換。出力長は `((L-7)//2+1)//2` |
| Parakeet v3 | 15 秒 | mel（OV の mel モデル） | encoder（mel / decoder / joint は CPU） | FluidInference 版 IR をそのまま使用 |
| SenseVoice | 15 秒（250 LFR フレーム）の 1 窓 | fbank + LFR + CMVN | モデル全体 | **LayerNorm 入力を 1/256 に縮小、eps を (1/256)² にする等価変換**を 142 か所に適用 |

窓の選び方:

- 全エンジンとも窓は 1 つ（ReazonSpeech 15 秒 / SenseVoice 15 秒 / Parakeet 15 秒）。短い発話は末尾を埋める。LayerNorm 修正後は窓長による精度差が無いことを確認済み（SenseVoice zh 6.6% / ko 7.5% が 15 秒窓 1 つで CPU と同等）。
- 現行の VAD は連続発話を約 8 秒で分割するため、通常は 8 秒を超えない。超えた場合は窓長で分割して連結する（保険）。

### 5.1 モデルの作成と配布元

| モデル | 作り方 | 入手元（案） |
|---|---|---|
| Parakeet v3 | 既存 IR を利用 | `FluidInference/parakeet-tdt-0.6b-v3-ov`（Hugging Face、CC-BY-4.0）。無改変で取得 |
| ReazonSpeech | `build_npu_models.py` で fp32 ONNX → 固定長 → IR(fp16) | 本リポジトリの GitHub Release の NPU アセット |
| SenseVoice | 同上（LN 修正を適用） | 同上 |

> **ライセンス確認結果**: SenseVoice の FunASR Model Open Source License（v1.1）2.1 は「使用・複製・改変・共有が自由」で、2.2 は「提供元の表記とモデル名の保持」が条件。
> 改変（LayerNorm の等価変換・fp16 化）したモデルの再配布は可能。モデル名（SenseVoice）と提供元を保持し、変更点を `Third_Party_Notices.md` に明記した。
> ReazonSpeech は Apache-2.0、Parakeet は CC-BY-4.0（NVIDIA の表記 + 変換元 FluidInference を併記）。

## 6. 設定・UI・起動

- `config.json`: `asr.device`: `"cpu"`（既定）/ `"npu"`。
- CLI: `main.py --device {cpu,npu}`（`start.bat` / `start.sh` 経由でも渡せる）。
- コントロールパネル: 「推論デバイス」の選択を追加。
  - NPU が検出され、NPU 用モデルが存在する場合のみ選択可能。それ以外は**非表示**（hayamimi-live と同様）。
  - 切り替えは次回起動時に反映（ASR を再構築するため）。
  - 現在どの言語が NPU / CPU かをステータス表示（例: 「NPU: ja / en / fr / de / es / zh / ko」「CPU: —」）。
- 検出: `openvino.Core().available_devices` に `NPU` が含まれるか。OpenVINO が無い環境は `False`。

## 7. 依存関係

- `requirements-npu.txt`（新規）: `openvino>=2026.0`（Apache-2.0）、Windows のみ（`sys_platform == 'win32'`）。
- 既存の `requirements.txt` には**追加しない**。CPU 版の環境は一切変わらない。
- Smart App Control: 追加するネイティブバイナリは OpenVINO（全て Intel 署名）のみ。前処理は NumPy 実装で `kaldi-native-fbank` 等は使わない（§8.5）。
- `NetworkIsolationGuard` のテストが OpenVINO の import / 推論でも通ることを確認する（外部通信ゼロの保証を維持）。

## 8. 配布設計

### 8.1 CPU 版（現状維持）

Windows ポータブル ZIP（約 1.58GB）と macOS ZIP（約 1.90GiB、上限 2GiB まで約 109MB）は**変更しない**。

### 8.2 NPU アドオン（Windows のみ、別アセット）

CPU 版に上書き展開する追加パックとする。1 アセットの上限 2GiB を考慮し、2 つに分ける:

| アセット | 内容 | 概算サイズ |
|---|---|---|
| `…-windows-npu-addon-core.zip` | openvino ランタイム（`openvino/` のみ）、ReazonSpeech IR、SenseVoice IR | 約 0.66GB（実測 664MB） |
| `…-windows-npu-addon-euro.zip` | Parakeet v3 IR（en / fr / de / es） | 約 1.14GB（実測 1,166MB） |

- euro を入れなければ en/fr/de/es は CPU で動く（エンジン単位のフォールバック）。
- **ユーザーの操作は「ZIP を `addons/` フォルダに入れる」だけ**とする。展開はアプリが次回起動時に自動で行う（§8.4）。ユーザーが ZIP を自分で解凍する必要はなく、解凍ソフトによるフォルダ階層の違いも問題にならない。
- 展開先はアプリが決める（`addons/packages/`（openvino）と `models/npu/`）。`python/Lib/site-packages/` は書き換えない。
- ワンライナーセットアップ（`setup.ps1` / `installer_gui.py`）には「NPU 用を追加する」選択肢を設け、HF / GitHub Release から取得する。

### 8.4 アドオン ZIP の自動展開

**ユーザー体験**: ダウンロードした ZIP を、アプリフォルダ内の `addons/` に入れて（なければ初回起動時に自動作成）、アプリを起動するだけ。

**処理の流れ**（`core/npu/addons.py`。`main.py` の最初期、`openvino` など重いモジュールを import する前に実行）:

1. `addons/*.zip` を走査する。
2. **ダウンロード途中のファイルを避ける**: 拡張子が `.crdownload` / `.part` / `.tmp` のものは対象外。ZIP は排他的に開けること、最終更新から数秒経過していること、ZIP として読めること（中央ディレクトリが正常）を満たしたものだけ処理する。満たさないものは次回起動に回す（エラー扱いにしない）。
3. ZIP 内の `manifest.json` を読む（アドオン名・バージョン・必要なアプリのバージョン・ファイル一覧と SHA-256）。無い ZIP は無視する（無関係な ZIP を触らない）。
4. **検証**: アプリのバージョンとの互換性、ファイルごとの SHA-256。アプリ本体が持つ既知のアドオンハッシュ表（`core/npu/addons_known.json`）と ZIP 全体のハッシュを照合する。**コード（DLL）を自動展開するため、不明な ZIP は展開しない。**
5. **安全な展開**: Python の `zipfile` で自前展開する。パスは正規化し、`..` や絶対パス、アドオン用ディレクトリ外への書き込み（zip-slip）は拒否する。いったん一時ディレクトリ（`addons/.staging/`）に展開し、検証が通ってから所定の場所へ移動する（途中で止まっても中途半端な状態を残さない）。
6. 成功したら ZIP を削除する（容量が倍になるのを防ぐ。設定で残すことも可能）。失敗したら ZIP は残し、理由をログと UI に出す。

**ZIP の中身の階層に依存しない**:

- 展開はアプリが行うので、ユーザーの解凍ソフトの癖（ZIP 名のフォルダを作る / 作らない、二重フォルダなど）は発生しない。
- `manifest.json` の位置は、ZIP 直下でも 1 階層下でも見つける。
- ユーザーが誤って**自分で解凍**して `addons/` に置いた場合も、`manifest.json` を含むフォルダなら同じ検証を経て受け入れる。
- `addons/` 以外（アプリフォルダ直下）に置かれた場合も、初回は同様に拾う。

**openvino の置き場**: `addons/packages/` に展開し、起動時に `sys.path` の先頭付近へ追加する（`site-packages` を書き換えない）。ポータブル版でも venv 版でも同じ。OpenVINO の DLL 読み込み（`add_dll_directory`）がこの配置で、**SAC 有効環境でも**動くことは、実装フェーズ 1 で最初に確認する。

**進捗と通知**: 展開は数十秒〜1 分かかることがある（約 1.2GB）。コントロールパネルに「NPU アドオンを展開しています…」を表示し、完了後に「NPU モードが使えます」と通知する。展開中でも CPU モードでの通訳は使える（展開は別スレッド）。

**アンインストール**: `addons/packages/` と `models/npu/` を削除すれば元の CPU 版に戻る（アンインストーラ不要という現行方針と同じ）。

### 8.5 Smart App Control（SAC）対応方針

**前提（実測）**: 検証機は SAC が有効（enforce）。この環境で次を確認した。

| 対象 | 署名 | SAC での結果 |
|---|---|---|
| OpenVINO（`.dll` / `.pyd` 29 個） | **全て有効（Intel Corporation）** | 読み込み・NPU 推論とも成功 |
| onnxruntime | 有効（Microsoft） | 成功 |
| numpy / scipy / sherpa-onnx / kaldi-native-fbank | 署名なし | 成功（広く流通している公式 wheel と同一のため、評価で許可されたとみられる） |
| pyarrow | 署名なし | **ブロック**（「アプリケーション制御ポリシーによってブロックされました」） |

つまり SAC は「署名の有無」だけでなく、クラウド上のファイル評価でも判定している。署名なしでも通るバイナリはあるが、**評価が無い・低いバイナリは、人気のある配布物でも止まる**ことがある。アプリ側から予測できないため、次の原則で設計する。

**原則: NPU アドオンに入れるネイティブバイナリ（`.dll` / `.pyd` / `.exe` / `.sys`）は、有効な Authenticode 署名を持つものだけにする。**

1. **署名済みのみ**: OpenVINO は全バイナリが Intel 署名なので適合する。アドオンには署名なしバイナリを一切入れない。
2. **新しいネイティブ依存を増やさない**:
   - 前処理（fbank / LFR / CMVN / mel）は **NumPy のみの実装**にする。PoC で使った `kaldi-native-fbank`（署名なし）は製品では使わない。
   - `onnx` / `scipy` / `pyarrow` などもアドオンの実行時依存にしない（モデルは事前変換済み IR なので不要）。
3. **自作のネイティブコードを作らない**: 独自ビルドの `.pyd` / `.exe` / ランチャーは、署名も評価も無く止まる。全て Python と既存の署名済み/既存依存で実現する。
4. **アドオンのビルド時に機械検査する**（CI）: アドオン ZIP 内の全バイナリについて `Get-AuthenticodeSignature` が `Valid` であり、発行元が許可リスト（Intel Corporation）にあることを確認する。1 つでも外れたらビルドを失敗させる。既存の `build_portable_win.py` が「未署名バイナリを削除する」考え方を踏襲する。
5. **展開後・読み込み前の再検査**（`addons.py`）: 展開したバイナリの署名を `WinVerifyTrust`（ctypes）で検証し、無効なら **openvino を import せず** NPU モードを無効化して CPU で起動する。理由を UI とログに出す（「署名を確認できないため NPU を無効にしました」）。SAC にブロックされて import が例外になった場合も同様に CPU へフォールバックする（アプリを落とさない）。
6. **例外の扱い**: SAC のブロックは `ImportError` / `OSError`（DLL load failed）として現れる。`import openvino` と `Core()` 生成を try/except で包み、失敗理由を分類して記録する。
7. **Mark of the Web（MOTW）**: アプリが Python で展開したファイルには MOTW が付かない。ユーザーがエクスプローラーで解凍した場合は継承されるが、上記のとおり署名済みなので影響しない。ZIP のプロパティ「許可する」手順は、既存の README 記載をアドオン向けにも踏襲する。
8. **OpenVINO のバージョン更新時**: 新しい wheel でも全バイナリが Intel 署名であることを CI で確認してから採用する（署名が外れた版は採用しない）。
9. **NPU ドライバ**: ドライバ側のユーザーモード DLL（`System32` 等）は OS / Intel 署名済みで、アドオンとは別管理。

**テスト**: SAC 有効（enforce）の実機で、アドオン展開 → NPU 起動 → 推論までを毎回確認する。SAC 無効の環境だけで通っても合格にしない。

### 8.3 CI

- NPU モデルのビルド（`build_npu_models.py`）は CI で実行し、アセットとして添付する。
- CI には NPU が無いため、**CI ではモデルのビルドと形式チェックのみ**。NPU 実機テストは手元の実機で行う（§9）。

## 9. テスト計画

| 種別 | 内容 | 実行場所 |
|---|---|---|
| 単体 | 前処理（fbank / LFR / mel）、窓の選択、ReazonSpeech 復号、TDT 復号、CTC 復号を、固定入力で期待値と比較 | CI（NPU 不要） |
| フォールバック | openvino 無し・NPU 無し・モデル無し・コンパイル失敗の各ケースで CPU 版が起動すること（モック） | CI |
| 実機 | `scripts/eval_npu.py` で言語別 CER/WER を CPU と比較。差が ±2pt を超えたら失敗 | NPU 実機（ローカル） |
| アドオン展開 | 正常な ZIP / 途中の ZIP / 壊れた ZIP / zip-slip を含む ZIP / ハッシュ不一致 / manifest 無しの ZIP / 解凍済みフォルダ / 展開中断後の再実行 | CI（NPU 不要） |
| SAC | SAC 有効（enforce）の実機で、アドオン展開 → openvino の import → NPU 推論が通ること。署名検査（CI）と、ブロック/署名不正時の CPU フォールバック（モック） | 実機 + CI |
| 外部通信 | `NetworkIsolationGuard` 下で NPU 推論が通ること | 実機 |

## 10. リスクと未確認事項

| リスク | 内容 | 対応 |
|---|---|---|
| **NPU 世代差** | 検証は Arrow Lake（Core Ultra 200 系）のみ。3〜5 年前の主力は Meteor Lake（Core Ultra 100 系）で、NPU の世代が古く、ドライバ・演算サポートが異なる可能性がある | **Meteor Lake / Lunar Lake の実機で同じ PoC を再実行する**（PoC スクリプトはそのまま動く）。失敗時は CPU フォールバックで影響を限定 |
| NPU ドライバ | 古いドライバではコンパイルが失敗する | 失敗検出 → CPU 固定。必要ドライバ版数を README に明記 |
| NPU の競合 | Teams の背景ノイズ除去などが NPU を使う場合、遅延が増える可能性 | 実機で並行計測。遅延が悪化する場合は CPU に戻せる導線を用意 |
| メモリ | Parakeet fp16 IR は約 1.2GB。CPU 先行中は一時的に二重持ち | CPU 先行は設定で無効化可能。解放を確実にする |
| 固定長の限界 | 15 秒（Parakeet）を超える発話は分割が必要 | 窓長で分割して連結（現行の VAD 8 秒分割で通常は発生しない） |
| 配布サイズ | euro アドオンが約 1.14GB | 2 分割済み（§8.2）。どちらも 2GiB に十分な余裕あり（ビルドスクリプトが 1.95GiB 超で失敗させる） |
| アドオンの安全性 | コードを自動展開・読み込みするため、不正な ZIP を入れられると危険 | 既知ハッシュ表との照合、zip-slip 防止（§8.4）。ハッシュ表はアプリ本体に同梱し、アドオンの更新にはアプリの更新が要る |
| **Smart App Control** | 署名・評価の無いバイナリは SAC にブロックされる（実測: pyarrow がブロック）。アドオンの展開物が止まるとアプリが NPU を使えない | 署名済みバイナリのみ同梱、CI で署名検査、展開後に署名を再検証、ブロック時は CPU フォールバック（§8.5） |
| ライセンス | SenseVoice の改変モデル再配布の可否 | 条文 2.1 が改変・共有を許諾。モデル名保持と変更点の明記で対応済み（§5.1） |
| OpenVINO のバージョン | 動作確認は 2026.4.1 のみ | requirements でバージョン範囲を絞り、更新時に実機回帰を回す |

## 11. 実装フェーズ

1. **基盤**: まず `addons/packages/` 配置の openvino が SAC 有効環境で動くことを確認。`core/npu/device.py`、`asr_engine.py` の `_decode` 抽出（リファクタ）、`device` 引数、CPU フォールバック。NPU 実装なしでも既存テストが通ること。
2. **ReazonSpeech**: `reazon.py` + `build_npu_models.py`（ReazonSpeech 分）。日本語の回帰を CPU と比較。
3. **SenseVoice**: `sensevoice.py` + LN 修正。zh / ko の回帰。
4. **Parakeet**: `parakeet.py`。en / fr / de / es の回帰。
5. **UI・設定・起動**: コントロールパネル、`--device`、ステータス表示、バックグラウンドコンパイルと差し替え。
6. **配布**: NPU アドオン ZIP と自動展開（`addons.py`）、セットアップスクリプトの「NPU 追加」、README / Third_Party_Notices 更新、CI。
7. **実機検証**: Meteor Lake を含む複数世代で回帰。遅延・CPU 負荷・メモリを計測してリリース判断。

各フェーズの完了条件は「CPU モードの既存テストが全て通る」ことと、「そのフェーズの言語で CER/WER が CPU と ±2pt 以内」。

## 12. 実装での確定事項（設計からの変更・追加）

実機（Core Ultra 9 285K / Smart App Control 有効）での E2E 検証で確定・変更した点。

| 項目 | 設計時 | 確定 |
|---|---|---|
| 窓 | SenseVoice は 6/10/15 秒の 3 窓 | **15 秒 1 窓**。LayerNorm 修正後は窓長による精度差が無く、コンパイル時間（約 126 秒/窓）も節約できる |
| ReazonSpeech の窓 | 8 秒 | **15 秒**（10 秒窓では 10〜15 秒の発話が分割されて日本語 CER が +4.1pt 悪化したため。15 秒窓で +0.2pt） |
| 前処理 | NumPy 実装（方針） | **`core/npu/features.py`**。`kaldi-native-fbank` との最大差は 1e-4 程度。SAC 対策としてネイティブ依存を増やさない |
| 信頼の固定 | アドオン ZIP 全体のハッシュ | **manifest.json の SHA-256 を `core/npu/addons_known.json` に固定**。manifest が全ファイルのハッシュを持つので、ZIP でも展開済みフォルダでも同じ検証になる |
| openvino の同梱範囲 | wheel の中身 | **`openvino/` ディレクトリのみ**（248MB・29 個のバイナリ全て Intel 署名）。pip が作る `bin/benchmark_app.exe` `ovc.exe` は署名なしなので除外 |
| 別ドライブ | 未考慮 | `models/` がジャンクションで別ドライブを指していても導入できる（`os.replace` が失敗した場合は copy + delete）。E2E で発見した不具合の修正 |
| 展開の順序 | — | パッケージの `__init__.py` と IR の `.xml`、`meta.json` を最後に配置し、中断してもコンポーネントが「揃って見える」状態にならない |
| 起動時間 | — | 初回コンパイル: ReazonSpeech 約 26 秒 / SenseVoice 約 126 秒 / Parakeet 約 55 秒。キャッシュ後は 3 エンジンとも約 2 秒で NPU に切り替わる |
| 導入時間 | — | 2 つのアドオン ZIP（約 1.8GB）の展開・ハッシュ・署名検証で約 27 秒 |
| 韓国語の空白 | — | NPU 版（fp16/fp32 系）は CPU の int8 版より語間のスペースが不自然になる場合がある（文字誤り率は同等）。README に注記 |

### 実装ファイル一覧

| 区分 | ファイル |
|---|---|
| NPU バックエンド | `core/npu/{__init__,device,base,features,reazon,sensevoice,parakeet}.py` |
| アドオン導入 | `core/npu/addons.py`、`core/npu/addons_known.json` |
| 既存コードの変更 | `core/asr_engine.py`（`device` 引数、CPU 先行→NPU 切り替え）、`main.py`（`--device`、アドオン展開の起動）、`ui/control_panel.py`（推論デバイス欄）、`config.default.json`（`asr.device`） |
| ビルド・配布 | `scripts/build_npu_models.py`、`scripts/build_npu_addon.py`、`scripts/fetch_npu_addon.py`、`scripts/build_portable_win.py`（`addons/` 同梱）、`setup.ps1 -WithNpu`、`requirements-npu.txt` |
| テスト | `test_npu_suite.py`（8 項目。NPU 実機テストは NPU が無い環境では自動で skip）、`tests_data/npu_fbank_golden.npz` |

### リリース手順（NPU アドオン）

1. `python scripts/build_npu_models.py --out models/npu --with-parakeet`（要 onnx, openvino）
2. `python -m pip install --no-deps --target addons/packages openvino==<版>`（アプリと同じ Python）
3. `python scripts/build_npu_addon.py --addon-version <ver> --release-tag v<app版>`
   * 全ネイティブバイナリの Authenticode 署名（発行元 Intel Corporation）を検査。1 つでも外れたら失敗。
   * `core/npu/addons_known.json` を更新（**アプリ本体と一緒にコミットする**）。
4. 生成された 2 つの ZIP を GitHub Release に添付。
5. SAC 有効の実機で `addons/` に入れて起動 → `python test_npu_suite.py` が全項目 pass することを確認。
