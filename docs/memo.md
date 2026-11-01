# 一時作業メモ (memo.md)

## 完了済みタスク (Report.md 精査・改修 & 追加要望反映)
- [x] **Phase 1: 翻訳・辞書・音声認識の品質直結バグ修正**
  - [x] FuguMT (`ja -> en`) の EOS トークン `</s>` 欠落修正と `beam_size=1` 高速化 (`core/translator.py`)
  - [x] 辞書部分一致破壊の解消（境界正規表現コンパイル、危険ルール削除、一般漢字語の誤抽出・誤マッチ防止、Sudachi スレッドロック保護） (`dicts/term_replacements.txt`, `core/dictionary.py`)
  - [x] 相手トラックの `hint_lang="en"` 固定撤廃と単一言語選択時の直接ルーティング (`main.py`, `core/asr_engine.py`)
  - [x] Silero VAD の無条件 RMS フォールバック撤去とヒステリシス・最小発話長ガード・8秒分割 (`core/vad.py`, `main.py`)
- [x] **Phase 2: 4段オーディオ DSP チェーン & セキュリティ・UIライフサイクル修正**
  - [x] 4段オーディオ DSP チェーン（ソフトニー・ノイズゲート、中音域EQ、スプリットバンド・ディエッサー、AGCコンプレッサー＆リミッター）の実装と統合 (`core/audio/dsp.py`, `main.py`)
  - [x] Web サーバーの履歴クリア同期 (`clear_history`)、ワンタイムトークン認証 (`HttpOnly Cookie`)、空きポート自動フォールバック、コピー機能・SSE 状態バッジ修正 (`ui/web_server.py`)
  - [x] セッション世代管理 (`_session_id`)、有界キュー (`maxsize=8`)、`on_stop_meeting` 個別例外保護 (`main.py`)
  - [x] 起動時のマイク設定上書きバグ修正、デバウンス・アトミック保存、ポータブル版でのアップデータ誤起動防止 (`ui/control_panel.py`, `ui/overlay_window.py`)
- [x] **Phase 3: インストーラー・ポータブルビルド (Python 3.14 統一)・CI・ドキュメント整備**
  - [x] OneDrive 回避先をユーザーホーム直下 `~/hayamimi-polyglot` に統一し、アンインストーラー不要（フォルダ削除のみで完結）を維持 (`installer_gui.py`, `setup.ps1`, `setup.sh`)
  - [x] Windows / macOS ポータブル版および CI の Python 3.14 (`3.14.10`) 完全統一 (`scripts/build_portable_win.py`, `scripts/build_portable_mac.py`, `.github/workflows/ci-release-portable.yml`)
  - [x] `Third_Party_Notices.md` の補完と、`README.md` / `SECURITY.md` / `languages.md` の上品で誠実な表現への統一
  - [x] `test_polyglot_suite.py` の拡充と全テスト検証
- [x] **Smart App Control (SAC) 対策・署名保護の強化**
  - [x] 案1: Windows ポータブル版を Python Software Foundation 公式デジタル署名付き Python 3.14 (NuGet) に刷新 (`scripts/build_portable_win.py`)
  - [x] 案2: 不要な未署名バイナリ（他アーキテクチャの PortAudio DLL、NumPy テスト用 .pyd、pip スタブ）の自動削除機構を実装 (`scripts/build_portable_win.py`)
  - [x] 案3-A: `README.md` に Windows 11 Smart App Control / SmartScreen 向けの ZIP プロパティ「許可する (Unblock)」手順を上品・明瞭に追記
  - [x] 再配布ライセンス要件 (PSFL v2) の確認と `Third_Party_Notices.md` への反映
