# 長期記憶・設計決定事項 (memory.md) - Hayamimi Polyglot

## プロジェクト概要
- **リポジトリ名**: `hayamimi-polyglot`
- **GitHub**: `https://github.com/Maximilian2022/hayamimi-polyglot` (Public)
- **ベースプロジェクト**: [oboroge0/hayamimi](https://github.com/oboroge0/hayamimi) (MIT License) の多言語・多モデル拡張フォーク
- **ミッション**: 3〜5年前の一般的なビジネスノートPC（Core i5 8〜11世代/Ryzen 5、内蔵GPUのみ、RAM 8〜16GB）のCPUのみで軽快に動作する、ビジネス会議・商談向けリアルタイム多言語同時並行通訳システム。
- **基本原則**: 完全ローカル動作、音声データ録音ゼロ（メモリ内即時破棄）、外部通信ゼロ（Zero Telemetry）、商用クリーンライセンス（Apache 2.0 / MIT）。

---

## 1. コアアーキテクチャ & モジュール構成

```
hayamimi-polyglot/
├── core/
│   ├── asr_engine.py       # ReazonSpeech INT8 Zipformer ASR (CPU超高速音声認識)
│   ├── vad.py              # Silero VAD (ONNX, 音声区間検出, メモリ上チャンク判定)
│   ├── translator.py       # CTranslate2 INT8 (M2M-100 103言語相互マルチキャスト & FuguMT ja->en)
│   ├── dictionary.py       # Instant Hotwords 自動抽出 (TF-IDF類似) & SudachiDict / 上場企業辞書
│   └── audio/
│       ├── dual_capture.py # デュアルトラック管理 (マイク + 相手アプリ音声の2スレッド並行処理)
│       ├── win_loopback.py # WASAPI Process Loopback (Zoom/Teams音声分離, リサンプラー内包)
│       └── mac_loopback.py # macOS ScreenCaptureKit / BlackHole 音声フォールバック
├── ui/
│   ├── control_panel.py    # タスクトレイ常駐 + ミニポップアップ (ピン留めフローティング, Max5言語ピル選択)
│   ├── overlay_window.py   # 最前面・クリックスルー・画面共有ステルス保護付き透過字幕
│   └── web_server.py       # 127.0.0.1:8844 自マシン限定 SSE リアルタイム共有ビュー
├── dicts/                  # ビジネス用語・上場企業名辞書
├── models/                 # AIモデル配置ディレクトリ
├── docs/
│   ├── languages.md        # 言語・モデル相関仕様書 (ASR/NMT/推論エンジン完全マップ)
│   ├── memory.md           # 長期記憶・設計決定事項
│   ├── memo.md             # 一時作業メモ
│   └── remediation_history.md # 変更・改修履歴
├── main.py                 # アプリケーションエントリポイント
├── installer_gui.py        # クロスプラットフォーム (Win/Mac共通) PySide6 モダンGUIインストーラー
├── setup.ps1               # Windows 11 向けランチャー (uv経由でinstaller_gui.pyを即時起動)
├── setup.sh                # macOS 向けランチャー (uv経由でinstaller_gui.pyを即時起動)
├── start.bat / start.sh    # ワンクリック起動ランチャー
├── test_polyglot_suite.py  # 全機能総合検証テストスイート
└── version.txt             # セマンティックバージョニング (1.0.1)
```

---

## 2. 主要機能と設計決定事項

### ① 最大5言語の同時並行相互通訳（マルチキャスト翻訳）
- **翻訳エンジン**: Meta M2M-100 (418M INT8) ＋ FuguMT (ja->en)。
- **103言語追加DLゼロ**: M2M-100 は標準で日本語、英語、中国語、韓国語、フランス語、ドイツ語、スペイン語、ベトナム語、タイ語など 103 言語の重みを内包。
- **マルチキャスト処理**: 1つの発言（例: 日本語）に対し、UIで選択された残り全言語（例: 英語、中国語、韓国語）へ並行して即座に翻訳出力（CPUで1文 30〜50ms）。
- **人間工学上限**: UIでは最大5言語まで選択可能に制限。最も視認性が高く実用的な黄金比は 3言語（日・英・中など）。

### ② 画面共有ステルス保護（カンペ・翻訳・設定パネルが相手に見えない）
- **Windows 11**:
  - Win32 API `SetWindowDisplayAffinity(hWnd, WDA_EXCLUDEFROMCAPTURE [0x11])`
  - 自分には透過字幕およびコントロールパネルが見えるが、Zoom、Teams、Google Meet の「画面共有」「ウィンドウ共有」、および PrintScreen などのキャプチャから**字幕オーバーレイとコントロールパネルの双方が完全に透明除外**される（起動時の `showEvent` から自動適用）。
- **macOS (12〜15)**:
  - Cocoa Objective-C ランタイム `NSWindow.sharingType = 0` (`NSWindowSharingNone`)
  - 標準ライブラリ `ctypes` から OS標準の `/usr/lib/libobjc.A.dylib` を直接呼び出し、管理者権限なし・追加依存なしで同様のステルス保護を実現。

### ②-2 タスクバー＆システムトレイの動的ステータスアイコン切り替え
- **通常時（待機中・会議停止中）**:
  - 落ち着いたスレートブルー＆シアン（`#1E293B` / `#38BDF8`）のクリアなマイクシルエット。
- **聞き取り中（会議実行中・リアルタイム通訳中）**:
  - 鮮やかなエメラルドグリーン（`#10B981`）のライブサークル ＋ **右上に 🔴（赤色）の LIVE / REC バッジ** を動的描画。
  - Windows のタスクバーアイコン（`QApplication.setWindowIcon`）およびタスクトレイ（`QSystemTrayIcon`）が瞬時に切り替わり、一目で聞き取り稼働中であることが判別可能。

### ③ 仮想ミキサー不要の直デバイス・デュアルトラックキャプチャ
- 外部仮想オーディオドライバ（VB-CABLE、VoiceMeeter等）を一切不要化。
- **自分**: `sounddevice` / PyAudio で物理マイクを直接キャプチャ（Track 1）。
- **相手**: OS標準の **WASAPI Process Loopback** を利用し、「Zoom.exe」「Teams.exe」「Slack.exe」のプロセスPIDを特定して音声のみを直接ループバック取得（Track 2）。
- **計算負荷ゼロの話者分離**: 最初から物理的に音声ストリームが2系統に分かれているため、話者ダイアライゼーション（重いAI計算）を行わずに「自分」「相手」を100%正確に識別。

### ④ Instant Hotwords ＆ クリーンビジネス辞書（SudachiPy 確定後処理アーキテクチャ）
- **ASR探索と後処理の分離決定（2026-11 実機ベンチマークにより確定）**:
  - ReazonSpeech は Byte-level BPE を採用しており、sherpa-onnx の --hotwords（FSTグラフ）に渡すと日本語トークンが 100% 破棄される仕様上の制約がある。
  - 特殊バイトトークン列（▁+3文字）へ事前分解して Modified Beam Search で FST グラフを強制構築・実行可能にしたものの、実機検証の結果：
    1. **探索パス枝刈りによる発話脱落**: 会話中央が大きく消える致命的な中抜けが発生（CER 16.3% -> 59.2% へ大幅悪化）。
    2. **推論遅延の増大**: 処理時間が 174ms から 277ms（+60%増）へ増加。
    3. **同音異義語の限界**: 音響・言語結合（Joiner）の確率バイアスが強固なため、FST スコア加算でも「機会」⇄「機械」等の同音異義語を覆せない。
  - 一方、**Greedy Search は 174ms（RTF 1.3%）で脱落ゼロ、圧倒的な最高速と高い認識精度**を発揮。
  - **結論**: ASR は最速・高安定な **Greedy Search** で動作させ、専門用語・表記ゆれ・同音異義語の補正は認識確定テキストに対して **SudachiPy（形態素解析・SudachiDict-Full）を用いた確定後処理エンジン（1ms以内）で補正するハイブリッドアーキテクチャ** を採用。

- **Instant Hotwords & 確定後処理エンジンの機能**:
  - 会議直前にアジェンダやスライドのテキストをコピペするだけで、SudachiPy により固有名詞、社内プロジェクト名、英字略語（ARR, KPI, DX等）を自動抽出（Instant Hotwords）。
  - **読み（reading_form）に基づく誤認識補正**: ASR 出力テキストを SudachiPy で形態素解析し、各形態素の「読み」と Instant Hotwords の音韻類似度・編集距離を比較して、音響的な誤認識（例: 「テック」⇄「テッチリ」）を高精度に文脈補正。
  - **英略語・カタカナ用語の自動正規化**: saas -> SaaS, kpi -> KPI, dx -> DX, 2b -> B2B 等の大文字小文字や記号を自動統一。
  - **Zero Telemetry ＆ データハイジーン**: 会議終了時に Instant Hotwords はメモリ上から完全消去（ディスク永続化ゼロ）。ユーザーの機密ワードや議事録ログを一切残さない。

- **デフォルト辞書の2軸構成**:
  - **① オフライン同梱辞書**: Apache-2.0 / CC0 / パブリックドメインの商用安全ライセンス。数MB以内でポータブル版に内包。現代ビジネス用語（300語以上）、英略語・財務指標（150語以上）、IT/AI/クラウド用語（200語以上）、主要上場企業名・グローバルTech企業名。
  - **② オンラインオプション拡張辞書**: 医療・薬学（MEDIS/万病辞書）、法務・行政用語（e-Gov）、全上場企業EDINET完全版（約4,000社）など、大容量または特定業種向け辞書を設定/インストーラーから1クリックで追加可能（GitHub Releases からの安全な静的DL、外部への通信送信ゼロ）。

### ⑤ クラウド同期フォルダ自動検知・退避
- 企業の PC 環境では `My Documents` が OneDrive や Google Drive に同期されているケースが多いため、大量の AI モデルや Python 仮想環境がクラウド同期によって同期負荷・企業セキュリティ警告を引き起こすのを防止。
- `setup.ps1` (Win): OneDrive/GoogleDrive を検知した場合は `C:\hayamimi-polyglot`（権限あれば）または `%LOCALAPPDATA%\Programs\hayamimi-polyglot` へ自動退避。
- `setup.sh` (Mac): iCloud Drive 同期を検知した場合は `~/hayamimi-polyglot` へ自動退避。

### ⑥ uv による自走環境構築 ＆ アップデート時のクリーン再構築
- **Python 3.14 への統一と環境隔離**:
  - 本プロジェクト内の Python 実行基盤は **Python 3.14** で統一管理（`.python-version` に `3.14` を明記）。
  - **ホスト環境との完全隔離**: ユーザー端末のシステム側に Python 3.10 や 3.11、3.12 など既存の別バージョンがインストールされている場合でも、`uv` の隔離 venv 機構により、ホスト側の PATH や環境変数・グローバル site-packages に一切影響を受けることなく、プロジェクト専用の健全な Python 3.14 仮想環境（`.venv`）を自律構築・運用する。
  - **uv の自己完結性**: スタンドアロンRustバイナリであり、OSにPython 3.14がインストールされていなくても公式 CPython 3.14 を安全に自動ダウンロード・隔離展開。
- **Web ワンライナー完全対応アーキテクチャ**:
  - `irm ... | iex`（Win）や `curl ... | bash`（Mac）など、手元にリポジトリコードが一切ない完全新規マシンでも、`setup.ps1` / `setup.sh` が一時領域（`TEMP`）に `installer_gui.py` を自動取得し `uv run --with PySide6` で新UIを即座に立ち上げる。
  - GUI 側では、ローカルにソースコードが存在しない場合に GitHub から最新のリポジトリ ZIP を自動ダウンロード・解凍して配備するパイプラインを完備。
- **クリーン再構築方針**:
  - 一般的な pip では再構築に数分〜十数分かかるため上書き更新しがちだが、旧バージョンの残骸パッケージ（orphan dependencies）が残り、バージョンの競合や DLL ロードエラーを引き起こす。
  - `uv` はダウンロード済み wheel をローカルキャッシュ（`%LOCALAPPDATA%\uv\cache` や `~/.cache/uv`）に保持するため、仮想環境（`.venv`）を削除・再作成（`uv venv --clear`）しても**再ダウンロード時間ゼロ（0バイト）、わずか 1〜2 秒で健全な環境が復元**される。
  - そのため、アップデート時や再セットアップ時は常にクリーン再構築を行う設計を採用。

### ⑦ マイクキャプチャの自動適応（WASAPI auto_convert & ネイティブレートリサンプリング）
- **WASAPI 16kHz 制約の克服**:
  - Windows の WASAPI 入力デバイス（Yeti, BRIO, Jabra 750, ヘッドセット等）はハードウェア既定レート（44.1kHz / 48kHz）でのアクセスを基本とし、直接 `samplerate=16000` を要求すると `PortAudioError: Invalid sample rate (-9997)` で失敗する。
  - `sounddevice.WasapiSettings(auto_convert=True)` を渡すことで Windows Audio Engine の自動リサンプルを有効化し、直接 16000Hz 1ch をオープン。
  - さらに万が一ダイレクトオープンに失敗した場合でも、デバイスのネイティブサンプリングレート・チャンネル数でオープンし、高速線形補間リサンプラ（0.014ms / 負荷0.04%未満）によりリアルタイムに 16000Hz 512 サンプルへダウンサンプリングする2段階フォールバック機構を採用。
- **VAD プリロールリングバッファ**:
  - 発話前の無音区間では最新 8フレーム（約256ms）のプリロールのみを保持し、発話開始（`is_speech == True`）時に結合して ASR へ供給。発話頭切れの防止と、無音区間の無限バッファ蓄積・誤デコードを完全防止。

### ⑧ 字幕オーバーレイの高度なカスタマイズ（ローカルフォント・文字サイズ・エリア・言語別文字色）
- **ローカルフォント読み込み**: `QFontDatabase.families()` により OS にインストールされている全ローカルフォント（400+）を自動列挙。コンボボックスでのインクリメンタル検索に対応。
- **文字サイズ & エリア**: 文字サイズ（12〜38px）、エリア幅（500〜1600px）、エリア高（120〜500px）、標準/ワイド/コンパクトのプリセット、および `QSizeGrip` マウスドラッグリサイズ。
- **メイン言語・翻訳言語別文字色**:
  - 発言者（自分タグ、相手タグ、本文）および全翻訳対象言語（日、英、中、韓、仏、独、西、越）の文字色をカラーピッカー（`QColorDialog`）で個別指定可能。標準色リセット機能も完備。
- **設定永続化**: `config.json` に UI 設定および前回マイク・言語設定を自動保存・次回起動時に完全復元。


### ⑨ 多言語インテリジェント言語自動判定（Unicode & 文字種比率解析）
- **話者トラック固定判定の撤廃**:
  - 従来は「マイク（`self`）＝日本語」「相手（`remote`）＝英語」という固定フォールバックが存在したため、ユーザーが英語を話した際に `ja` と誤判定され、英語へ再翻訳されて出力が壊れる（ハルシネーション）問題が発生していた。
  - テキスト内の Unicode スクリプト（ひらがな・カタカナ、ハングル、ラテン文字、漢字）および選択言語リストに基づく高精度な自動言語判定（LID）エンジンを確立。
- **判定優先アルゴリズム**:
  1. ひらがな・カタカナ（`[\u3040-\u309F\u30A0-\u30FF]`）を含む → 100% 日本語（`ja`）。英語略語混じり（「OKです」等）も確実に日本語判定。
  2. ハングル（`[\uAC00-\uD7AF\u1100-\u11FF]`）を含む → 100% 韓国語（`ko`）。
  3. ラテン文字主体の文 → 英語（`en`）または選択言語に含まれる欧州言語（`fr`, `de`, `es`, `vi` のダイアクリティカルマーク判定）。
  4. 漢字のみの文 → 選択言語および中国語特有機能語に基づき `zh` または `ja`。
  5. 自分が英語を話した場合でも、相手が日本語を話した場合でも、発言内容に基づき 100% 正確にソース言語が判定され、選択されている他言語（日本語など）へ即座に並行翻訳される。

### ⑩ AIモデル構成 & 推論エンジン相関一覧 (languages.md 準拠)
Hayamimi Polyglot で稼働する全 8 言語対応モデル群と推論エンジンの相関関係：

| 機能区分 | モデル名 | 推論エンジン (Runtime) | 役割・特徴 | 状態 |
| :--- | :--- | :--- | :--- | :--- |
| **VAD (音声区間検出)** | `silero_vad.onnx` | ONNX Runtime (CPU) | 32ms音声チャンクの無音/発話判定。無音時ASR停止による超低負荷化 | **常駐稼働** (必須) |
| **ASR (日本語メイン固定)** | `sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17` | sherpa-onnx (INT8 Transducer) | 日本語固定。Instant Hotwords 注入（アジェンダ固有名詞）＆ビジネス辞書置換 | **常駐稼働** (日本語固定) |
| **ASR (欧米圏メインSOTA)** | `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` | sherpa-onnx (NeMo Transducer INT8) | 英語・欧州25言語版。英語(en), 仏(fr), 独(de), 西(es)ネイティブ会話をCPUのみで高速認識 (RTF 0.08) | **遅延ロード** (en/fr/de/es 選択時) |
| **ASR (アジア圏多言語)** | `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | sherpa-onnx (SenseVoice Small INT8) | 中国語(zh)・韓国語(ko)・広東語ネイティブ音声認識 ＆ 超高速ITN数字正規化 | **遅延ロード** (zh/ko 選択時) |
| **ASR (東南アジア特化)** | `sherpa-onnx-zipformer-vi-30M-int8-2026-02-09` | sherpa-onnx (INT8 Transducer) | ベトナム語専用 6声調特化モデル。わずか約35MBで超低CPU負荷 (15msデコード) | **遅延ロード** (vi 選択時) |
| **NMT (日英特化翻訳)** | `mojicast-fugumt-ja-en-ct2` | CTranslate2 INT8 | `ja -> en` 専用。自然なビジネス英語を 20〜40ms で生成 | **常駐稼働** (日英ペア) |
| **NMT (万能相互翻訳)** | `mojicast-m2m100-ct2` (418M) | CTranslate2 INT8 | 100言語間（`en->ja`, `zh->ja`, `ko->ja`, `fr->ja`, `de->ja`, `es->ja`, `vi->ja`, `ja->zh` 等）のマルチキャスト並行翻訳 | **常駐稼働** (相互翻訳) |

### ⑪ 遅延ロード（Lazy Loading / オンデマンド起動）アーキテクチャ
- **未選択モデルの非活性（メモリ消費ゼロ）**:
  ディスク（`models/`）に全モデルが配置されていても、会議の対象言語としてチェックされていない言語のモデル（例: 中国語・韓国語やフランス語）は、**RAM（メモリ）にはロードされません**。
- **動的アンロード & ガベージコレクション**:
  会議中に言語のチェックが外れた場合、該当モデルのスロットを即座に破棄し、Python の `gc.collect()` により RAM を即座に OS へ返還。
- **通常会議時の最小フットプリント**:
  日常的な「日本語 🇯🇵 ＋ 英語 🇺🇸」の会議中は、ReazonSpeech と Parakeet のみがメモリに常駐。RAM 消費は数百MB、CPU 使用率は 5% 未満に抑えられます。
- **オンデマンド即時呼び出し**:
  会議設定で特定の言語（例: 中・韓 🇨🇳🇰🇷）がチェックされた瞬間、バックグラウンドで該当モデルがスッと起動し、通訳パイプラインに合流します。
- **未選択言語発話時のハンドリング仕様 (確定設計)**:
  - **欧州系言語（仏・独・西）**: 英語用としてロード中の Parakeet TDT v3 が欧州25言語を内包しているため、未選択であっても原語のまま高精度に文字起こしされ、選択言語へ翻訳される。
  - **アジア圏言語（中国語・韓国語）**: SenseVoice Small がチェックボックス連動でオンデマンド起動。未選択時はメモリを消費しない省エネ設計。

---

## 3. 企業コンプライアンス 7原則 (Zero Telemetry)
1. **音声ゼロトレース**: 音声波形（PCM/WAV）はディスクに一切保存せず、メモリ上のリングバッファで処理後即破棄。
2. **外部通信ゼロ**: テレメトリ、アナリティクス、外部API通信は完全遮断。
3. **ローカル厳格バインド**: Webサーバーは `127.0.0.1:8844` のみにバインドし、LAN内盗聴・DNS Rebindingを防止。
4. **ログ保護**: デバッグログに音声内容や会議文字起こしテキストを出力しない。
5. **DOM XSS対策**: ブラウザ共有ビュー (`/view`) ではテキスト描画時に HTML サニタイズを徹底。
6. **CORSロック**: 外部サイトからの WebSocket / SSE 読み取りを遮断。
7. **クリーンライセンス**: 全てのライブラリ・モデルが商用利用可能（Apache 2.0 / MIT / CC-BY 4.0 / FunASR Model License 等。詳細は Third_Party_Notices.md 参照）。

---

## 4. 依存関係管理・CI/CD 保守ポリシー (Dependabot)
- **Grouped Updates（グループ化更新）の厳格適用**:
  - `requirements.txt` の個別更新による PR 乱立（通知スパム）およびマージコンフリクトを回避するため、`.github/dependabot.yml` では最新の `groups: python-dependencies: patterns: ["*"]` を採用。
  - すべての pip パッケージ更新は 1 つのまとまった PR として定期配信（毎週月曜 09:00 JST）。
- **Python 3.14 互換性・Zero Telemetry 検証必須**:
  - 依存ライブラリの更新にあたっては、Python 3.14 上での動作検証および `test_polyglot_suite.py` の全テスト（ASR/NMT/VAD/辞書/セキュリティ制約）が 100% PASS することを必須要件とする。



---

## 5. 企業プロキシ・完全オフラインポータブル配布アーキテクチャ
- **企業プロキシ (Zscaler / Palo Alto / BlueCoat) 自動突破**:
  - `setup.ps1` および `setup.sh` に `UV_SYSTEM_CERTS=true` / `PIP_USE_FEATURE=truststore` を標準組込み。
  - OSネイティブの信頼されたルート証明書ストア（Windows Root CA / macOS Keychain）を直接参照し、SSLインスペクション環境における証明書検証エラー（`CERTIFICATE_VERIFY_FAILED`）および PyPI ダウンロード拒否（HTTP 403）を回避。
- **Windows Standalone Portable ZIP (`hayamimi-polyglot-v1.0.1-windows-portable.zip`)**:
  - Python 3.12 仮想環境（`.venv`）、INT8最適化モデル群、ビジネス辞書、UIを全内包。
  - 解凍して `start.bat` ダブルクリックで即起動。
- **macOS Standalone Portable ZIP (`hayamimi-polyglot-v1.0.1-macos-portable.zip`)**:
  - macOS 特有の仮想環境パス不整合（`bad interpreter`）を回避するため、全依存 wheel（macOS arm64/universal2 向け 39 個, 487MB）＋最適化モデル群を ZIP に内包。
  - 初回起動時、同梱の `wheels/` から `uv pip install --no-index --find-links ./wheels` により、その Mac のローカル環境に完全適合した `.venv` を外部通信ゼロで自律構築し即起動。
  - Finder ダブルクリック用 `Hayamimi Polyglot.command`（実行権限 0o755 同梱）で実行可能。
