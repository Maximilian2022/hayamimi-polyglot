# 長期記憶・設計決定事項 (memory.md) - Hayamimi Polyglot

## プロジェクト概要
- **リポジトリ名**: `hayamimi-polyglot`
- **GitHub**: `https://github.com/Maximilian2022/hayamimi-polyglot` (Private)
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
├── main.py                 # アプリケーションエントリポイント
├── installer_gui.py        # クロスプラットフォーム (Win/Mac共通) PySide6 モダンGUIインストーラー
├── setup.ps1               # Windows 11 向け WPF ダークテーマGUIインストーラー & アップデータ
├── setup.sh                # macOS 向けスマートインストーラー (uv経由でinstaller_gui.pyを即時起動)
├── start.bat / start.sh    # ワンクリック起動ランチャー
├── test_polyglot_suite.py  # 全機能総合検証テストスイート
└── version.txt             # セマンティックバージョニング (1.0.0)
```

---

## 2. 主要機能と設計決定事項

### ① 最大5言語の同時並行相互通訳（マルチキャスト翻訳）
- **翻訳エンジン**: Meta M2M-100 (418M INT8) ＋ FuguMT (ja->en)。
- **103言語追加DLゼロ**: M2M-100 は標準で日本語、英語、中国語、韓国語、フランス語、ドイツ語、スペイン語、ベトナム語、タイ語など 103 言語の重みを内包。
- **マルチキャスト処理**: 1つの発言（例: 日本語）に対し、UIで選択された残り全言語（例: 英語、中国語、韓国語）へ並行して即座に翻訳出力（CPUで1文 30〜50ms）。
- **人間工学上限**: UIでは最大5言語まで選択可能に制限。最も視認性が高く実用的な黄金比は 3言語（日・英・中など）。

### ② 画面共有ステルス保護（カンペ・翻訳が相手に見えない）
- **Windows 11**:
  - Win32 API `SetWindowDisplayAffinity(hWnd, WDA_EXCLUDEFROMCAPTURE [0x11])`
  - 自分には透過字幕が見えるが、Zoom、Teams、Google Meet の「画面共有」「ウィンドウ共有」、および PrintScreen などのキャプチャから完全に透明除外される。
- **macOS (12〜15)**:
  - Cocoa Objective-C ランタイム `NSWindow.sharingType = 0` (`NSWindowSharingNone`)
  - 標準ライブラリ `ctypes` から OS標準の `/usr/lib/libobjc.A.dylib` を直接呼び出し、管理者権限なし・追加依存なしで同様のステルス保護を実現。

### ③ 仮想ミキサー不要の直デバイス・デュアルトラックキャプチャ
- 外部仮想オーディオドライバ（VB-CABLE、VoiceMeeter等）を一切不要化。
- **自分**: `sounddevice` / PyAudio で物理マイクを直接キャプチャ（Track 1）。
- **相手**: OS標準の **WASAPI Process Loopback** を利用し、「Zoom.exe」「Teams.exe」「Slack.exe」のプロセスPIDを特定して音声のみを直接ループバック取得（Track 2）。
- **計算負荷ゼロの話者分離**: 最初から物理的に音声ストリームが2系統に分かれているため、話者ダイアライゼーション（重いAI計算）を行わずに「自分」「相手」を100%正確に識別。

### ④ Instant Hotwords ＆ クリーンビジネス辞書
- 会議直前にアジェンダやスライドのテキストをコピペするだけで、形態素解析・パターンマッチにより固有名詞、社内プロジェクト名、英字略語（ARR, KPI, DX等）を自動抽出。
- ASRデコード時に Hotwords として注入し、未知語や専門用語の誤認識を劇的に防止。
- 金融庁EDINETの全上場企業名オープンデータおよび SudachiDict (Full, Apache 2.0) を内包。

### ⑤ クラウド同期フォルダ自動検知・退避
- 企業の PC 環境では `My Documents` が OneDrive や Google Drive に同期されているケースが多いため、大量の AI モデルや Python 仮想環境がクラウド同期によって同期負荷・企業セキュリティ警告を引き起こすのを防止。
- `setup.ps1` (Win): OneDrive/GoogleDrive を検知した場合は `C:\hayamimi-polyglot`（権限あれば）または `%LOCALAPPDATA%\Programs\hayamimi-polyglot` へ自動退避。
- `setup.sh` (Mac): iCloud Drive 同期を検知した場合は `~/hayamimi-polyglot` へ自動退避。

### ⑥ uv による自走環境構築 ＆ アップデート時のクリーン再構築
- **Python 3.14 への統一と環境隔離**:
  - 本プロジェクト内の Python 実行基盤は **Python 3.14** で統一管理（`.python-version` に `3.14` を明記）。
  - **ホスト環境との完全隔離**: ユーザー端末のシステム側に Python 3.10 や 3.11、3.12 など既存の別バージョンがインストールされている場合でも、`uv` の隔離 venv 機構により、ホスト側の PATH や環境変数・グローバル site-packages に一切影響を受けることなく、プロジェクト専用の健全な Python 3.14 仮想環境（`.venv`）を自律構築・運用する。
  - **uv の自己完結性**: スタンドアロンRustバイナリであり、OSにPython 3.14がインストールされていなくても公式 CPython 3.14 を安全に自動ダウンロード・隔離展開。
- **クリーン再構築方針**:
  - 一般的な pip では再構築に数分〜十数分かかるため上書き更新しがちだが、旧バージョンの残骸パッケージ（orphan dependencies）が残り、バージョンの競合や DLL ロードエラーを引き起こす。
  - `uv` はダウンロード済み wheel をローカルキャッシュ（`%LOCALAPPDATA%\uv\cache` や `~/.cache/uv`）に保持するため、仮想環境（`.venv`）を削除・再作成（`uv venv --clear`）しても**再ダウンロード時間ゼロ（0バイト）、わずか 1〜2 秒で健全な環境が復元**される。
  - そのため、アップデート時や再セットアップ時は常にクリーン再構築を行う設計を採用。

---

## 3. 企業コンプライアンス 7原則 (Zero Telemetry)
1. **音声ゼロトレース**: 音声波形（PCM/WAV）はディスクに一切保存せず、メモリ上のリングバッファで処理後即破棄。
2. **外部通信ゼロ**: テレメトリ、アナリティクス、外部API通信は完全遮断。
3. **ローカル厳格バインド**: Webサーバーは `127.0.0.1:8844` のみにバインドし、LAN内盗聴・DNS Rebindingを防止。
4. **ログ保護**: デバッグログに音声内容や会議文字起こしテキストを出力しない。
5. **DOM XSS対策**: ブラウザ共有ビュー (`/view`) ではテキスト描画時に HTML サニタイズを徹底。
6. **CORSロック**: 外部サイトからの WebSocket / SSE 読み取りを遮断。
7. **クリーンライセンス**: 全てのライブラリ・モデルが商用フリー（Apache 2.0 / MIT）。

