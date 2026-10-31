# 作業メモ (memo.md) - Hayamimi Polyglot

## 現在のステータス
- **リポジトリ分離**: `E:\hayamimi-polyglot` として新設。
- **リモート接続**: `https://github.com/Maximilian2022/hayamimi-polyglot.git` (Private)
- **現在のブランチ**: `main`
- **現在のバージョン**: `1.0.0`
- **総合検証**: `test_polyglot_suite.py` による全5テスト（Hotwords、VAD/ASR、CTranslate2多言語翻訳、Windows音声セッション列挙、セキュリティ制約）が **100% PASS** を確認済み。

---

## 完了した実装項目
1. **コアエンジン**:
   - `core/asr_engine.py`: ReazonSpeech Zipformer INT8 (sherpa-onnx)
   - `core/vad.py`: Silero VAD (ONNX)
   - `core/translator.py`: CTranslate2 INT8 (M2M-100 103言語 & FuguMT)
   - `core/dictionary.py`: Instant Hotwords & SudachiDict / 上場企業辞書
   - `core/audio/dual_capture.py`: マイク ＋ アプリ音声の2トラック分離
   - `core/audio/win_loopback.py`: WASAPI Process Loopback（macOS安全フォールバック付き）
   - `core/audio/mac_loopback.py`: macOS ScreenCaptureKit 音声フォールバック
2. **UI & プレゼンテーション**:
   - `ui/control_panel.py`: タスクトレイ常駐 + ミニポップアップ（ピン留め固定、Max5言語ピルセレクター、「⚙️ モデル追加/更新」ボタン）
   - `ui/overlay_window.py`: 最前面・クリックスルー・WDA/Cocoa画面共有ステルス保護透過字幕
   - `ui/web_server.py`: 127.0.0.1:8844 SSE 画面共有ビュー（サニタイズ・CORS遮断）
3. **インストーラー & アップデータ**:
   - `setup.ps1`: Windows 11 WPF ダークテーマGUI。OneDrive自動検知・退避、モデル選択DL、uv自走構築、アップデート時クリーン再構築（`uv venv --clear`）。
   - `setup.sh`: macOS 向けスマートインストーラー。iCloud Drive自動検知・退避、アップデート時クリーン再構築。
   - `start.bat` / `start.sh`: ワンクリック起動ランチャー。

---

## 次のタスク・引き継ぎ事項
1. **GitHub ワンライナー公開用スクリプトの整備**:
   - リポジトリが Private のため、非公開リポジトリからワンライナーを実行する場合（`irm ... | iex`）に GitHub Personal Access Token や Releases アセットの公開手順を詰める。
   - または将来的に Public リリースするか、ワンクリック配布パッケージ（ポータブルZIP）化を検討。
2. **モデル配布の最適化**:
   - 現在ローカルの `models` フォルダからシンボリックリンクまたはコピーで配置する構成。
   - 初回ユーザーが完全新規マシンで実行した際の自動ダウンロードURL（HuggingFace / sherpa-onnx リリース）のフォールバック動作の検証。
3. **macOS 実機での ScreenCaptureKit Audio 動作検証**:
   - Windows (WASAPI Loopback) は動作検証完了。macOS 実機でのマイク＋相手音声の結合テスト。
