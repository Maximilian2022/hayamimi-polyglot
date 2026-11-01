# 長期記憶・設計決定事項 (memory.md) - Hayamimi Polyglot

## プロジェクト概要
- **リポジトリ名**: `hayamimi-polyglot`
- **GitHub**: `https://github.com/Maximilian2022/hayamimi-polyglot` (Public)
- **ベースプロジェクト**: [oboroge0/hayamimi](https://github.com/oboroge0/hayamimi) (MIT License) の多言語・多モデル拡張フォーク
- **ミッション**: 一般的なビジネスノートPC（Core i5 / Ryzen 5、内蔵GPUのみ、RAM 8〜16GB）の CPU のみで軽快に動作する、ビジネス会議・商談向けリアルタイム多言語同時通訳支援システム。
- **基本原則**: ローカル完結動作、音声データ非保存（メモリ内処理後破棄）、推論パイプライン外部通信なし、商用利用可能なライセンス構成（Apache 2.0 / MIT / BSD / CC-BY 4.0 等）。

---

## 1. コアアーキテクチャ & モジュール構成

```
hayamimi-polyglot/
├── core/
│   ├── asr_engine.py       # ReazonSpeech / Parakeet TDT v3 / SenseVoice Small (INT8 ASR)
│   ├── vad.py              # Silero VAD (ONNX, ヒステリシス付き発話区間検出)
│   ├── translator.py       # CTranslate2 INT8 (M2M-100 多言語相互翻訳 & FuguMT ja->en)
│   ├── dictionary.py       # Instant Hotwords 抽出 & SudachiPy 形態素・音韻照合後処理エンジン
│   └── audio/
│       ├── dsp.py          # 4段オーディオ DSP チェーン (Gate -> Mid-EQ -> De-Esser -> AGC Comp)
│       ├── dual_capture.py # デュアルトラック管理 (マイク + 相手アプリ音声の2スレッド並行処理)
│       ├── win_loopback.py # Windows WASAPI Process Loopback ラッパー
│       ├── _win_loopback_impl.py # WASAPI Process Loopback 実装 (AUTOCONVERTPCM 16kHz 優先)
│       └── mac_loopback.py # macOS CoreAudio / BlackHole 2ch 仮想オーディオ取得
├── ui/
│   ├── control_panel.py    # タスクトレイ常駐 + コントロールパネル (デバウンス・アトミック設定保存)
│   ├── overlay_window.py   # 最前面・クリックスルー・画面共有ステルス対応透過字幕
│   └── web_server.py       # 127.0.0.1 限定・ワンタイムトークン認証付き SSE 共有ビュー
├── dicts/                  # ビジネス用語・上場企業名・置換ルール辞書
├── models/                 # AIモデル配置ディレクトリ
├── scripts/
│   ├── download_models.py  # 必須 INT8 モデル一括ダウンロード・検証スクリプト
│   ├── build_portable_win.py # Windows ポータブル ZIP ビルド (CPython 3.14.10 同梱)
│   └── build_portable_mac.py # macOS ポータブル ZIP ビルド (CPython 3.14.10 & arm64 wheels 同梱)
├── docs/
│   ├── languages.md        # 言語・モデル相関仕様書
│   ├── memory.md           # 長期記憶・設計決定事項
│   ├── memo.md             # 一時作業メモ
│   └── remediation_history.md # 変更・改修履歴
├── main.py                 # アプリケーションエントリポイント
├── installer_gui.py        # クロスプラットフォーム (Win/Mac共通) PySide6 GUIインストーラー
├── setup.ps1               # Windows 11 向けセットアップランチャー (UTF-8 with BOM)
├── setup.sh                # macOS 向けセットアップランチャー (LF)
├── start.bat / start.sh    # 起動ランチャー
├── test_polyglot_suite.py  # 総合検証テストスイート (全8テスト)
└── version.txt             # セマンティックバージョニング (1.0.1)
```

---

## 2. 主要機能と設計決定事項

### ① 最大5言語の同時並行相互通訳（マルチキャスト翻訳）
- **翻訳エンジン**: Meta M2M-100 (418M INT8) ＋ FuguMT (`ja -> en`)。
- **FuguMT EOS トークン明示**: MarianMT 系 CTranslate2 モデルの仕様に合わせ、入力トークン末尾に `+ ["</s>"]` を付与し、`beam_size=1`（Greedy Decoding）で高速かつ繰り返し暴走のない安定した英文翻訳を生成。
- **マルチキャスト処理**: 1つの発言に対し、UIで選択された残り全言語（最大4言語）へ `translate_batch` により並行翻訳出力。

### ② 4段オーディオ DSP 前処理チェーン (`core/audio/dsp.py`)
- 音声が ASR エンジンに渡される前段で、追加外部ライブラリなし（ベクトル化 NumPy のみ、処理時間約 0.3ms）で以下の 4 段処理を実施：
  1. **ソフトニー・ノイズゲート**: `-48dBFS` 以下の空調・PCファン等の定常フロアノイズを減衰。
  2. **中音域イコライザー (Mid-range Presence EQ)**: 85Hz 未満の低域ハムノイズを減衰させ、子音・母音の明瞭度に関わる 1.8kHz 中心の中音域を `+2.0dB` ブースト、7.5kHz 以上をロールオフ。
  3. **スプリットバンド・ディエッサー (De-Esser)**: 4.2kHz〜7.6kHz 帯の歯擦音エネルギー突出を検出し、動的に最大 `-6dB` 抑制してマイク近接時の耳障りな高域ピークを緩和。
  4. **自動ゲイン制御 (AGC) コンプレッサー＆リミッター**: アクティブ音声の80パーセンタイルをターゲット `-17dBFS`（最大 `+12dB`）へ引き上げ、`-12dBFS` 以上の過大入力を 3:1 で圧縮、最後に `±0.95` ソフトニーリミッターでクリッピングを防止。

### ③ 画面共有ステルス表示と適用検証
- **Windows 11**: Win32 API `SetWindowDisplayAffinity(hWnd, WDA_EXCLUDEFROMCAPTURE [0x11])`
- **macOS (12〜15)**: Cocoa Objective-C ランタイム `NSWindow.sharingType = 0` (`NSWindowSharingNone`)
- `OverlayWindow.apply_stealth()` で戻り値を確認し、万が一 OS 側でステルス適用が失敗した場合はステータスに「⚠️ ステルス保護失敗」を表示。

### ④ デュアルトラックキャプチャとリサンプリング品質
- **Windows**: `sounddevice.WasapiSettings(auto_convert=True)` によるマイクキャプチャ（Track 1）と、WASAPI Process Loopback（`AUTOCONVERTPCM` で `16000Hz / 1ch` 直接取得を最優先、フォールバック時は移動平均アンチエイリアシングフィルタ付きリサンプル）による相手アプリ音声キャプチャ（Track 2）。
- **macOS**: 物理マイク（Track 1）と CoreAudio / BlackHole 2ch 仮想オーディオデバイス（Track 2）。
- **Silero VAD**: 無条件の RMS エネルギーフォールバックを廃し、Silero VAD 確率判定＋ヒステリシス（開始 `0.45`、継続 `0.30`）＋最小有声フレーム数ガード（4フレーム以上）により、打鍵音や定常雑音での誤発火を防止。長尺発話は 8 秒（250フレーム）で自動区切り。

### ⑤ Instant Hotwords ＆ ビジネス辞書（SudachiPy 確定後処理エンジン）
- **ASR探索と後処理の分離**:
  - ReazonSpeech は最速・脱落のない **Greedy Search** で動作させ、専門用語・表記ゆれ・同音異義語の補正は認識確定テキストに対して **SudachiPy（形態素解析・SudachiDict-Full）を用いた確定後処理エンジン** で実施。
- **単語境界保護と誤置換防止**:
  - `term_replacements.txt` から一般英語と衝突する短語（`rest`, `mom`, `teams`, `zoom`, `slack`, `cs`, `パース`）を除外。
  - ASCII ルールには `(?<![A-Za-z0-9])...(?![A-Za-z0-9])`、短いカタカナルールには `(?<![\u30a0-\u30ffー])...(?![\u30a0-\u30ffー])` の境界正規表現を事前コンパイルし、`agenda` ➔ `ageNDA` や `リソース` ➔ `リSaaS` のような部分一致破壊を防止。
  - アジェンダからのキーワード抽出は「固有名詞・カタカナ語・英数字」に限定し、音韻（読み）ファジーマッチもカタカナ語同士に限定することで、一般漢字語（「会議」「開発」等）の誤置換を防止。
  - SudachiPy の初期化・`tokenize()` は `threading.Lock()` で保護し、非日本語テキスト（欧文等）では形態素解析をスキップ。

### ⑥ クラウド同期フォルダ（OneDrive / iCloud）回避とアンインストール容易性
- ドキュメントフォルダが OneDrive や iCloud Drive の同期下にある場合、隠しフォルダ（`AppData` 等）ではなく、エクスプローラーや Finder からすぐ見えるユーザーホーム直下の **`C:\Users\<ユーザー名>\hayamimi-polyglot`（`$HOME/hayamimi-polyglot`）** に統一。
- レジストリ変更を行わないため、**「そのフォルダを削除するだけでアンインストールが完結する」** シンプルな運用を維持。

### ⑦ Python 3.14 完全統一 & Smart App Control (SAC) 対策
- `.python-version`、CI ワークフロー（`.github/workflows/ci-release-portable.yml`）、macOS ポータブル版（`scripts/build_portable_mac.py`）のすべてを **Python 3.14 (`3.14.10`)** に統一。
- **Windows ポータブル版の公式 PSF デジタル署名化 (SAC 対策)**:
  - Windows 11 の Smart App Control（SAC）によるブロックを防止するため、Windows ポータブル版（`scripts/build_portable_win.py`）の Python ランタイムを、未署名のビルドから **Python Software Foundation (PSF) 公式デジタル署名付き NuGet パッケージ（`python.3.14.10.nupkg`）** に刷新。
  - これにより、`python.exe`, `pythonw.exe`, `python314.dll`, および標準ライブラリの全 `.pyd` に PSF の Authenticode 署名が付与され、SAC を確実に通過。
  - 不要なアーキテクチャのバイナリ（PortAudio 32bit/ARM64 DLL）、NumPy テスト用 `.pyd`、pip 未署名スタブをビルド時に自動削除し、誤検知リスクを最小化。
  - ドキュメント（`README.md`）に Windows 11 の ZIP 展開前「セキュリティ: 許可する (Unblock)」手順を案内。
- ポータブル版で「⚙️ モデル追加/更新」ボタンを押した際は、バンドル環境保護のため案内ダイアログを表示し、`setup.ps1` の誤実行による環境破損を防止。

### ⑧ セッション世代管理とローカル Web サーバー保護
- **セッション世代管理 (`_session_id`)**: 会議停止・履歴クリア時に世代番号をインクリメントし、バックグラウンドキューに残っていた旧セッションの遅延認識・翻訳結果が停止後の画面や議事録に混入するのを防止。
- **Web サーバー (`127.0.0.1`)**:
  - ポート 8844 が使用中の場合は `8845〜8854` の空きポートへ自動フォールバック。
  - 起動ごとに `secrets.token_urlsafe(24)` でワンタイムトークンを生成し、`/view?token=...` で HttpOnly Cookie を発行して `/view` および `/events` を保護。
  - `clear_history()` により、コントロールパネルでの履歴クリア・会議停止時に Web サーバー内のメモリ履歴およびブラウザ画面の DOM も即時クリア。
