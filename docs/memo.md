# 一時作業メモ (memo.md)

## 現在のタスク
- [x] **8 言語（日・英・中・韓・仏・独・西・越）ASR & NMT の完全実物実装 (`languages.md` 準拠)**
- [x] **遅延ロード（Lazy Loading / オンデマンド起動）＆ 動的メモリ解放の実装**
- [x] **日本語 ASR の ReazonSpeech Zipformer 固定（Instant Hotwords ＆ 辞書機能完全維持）**
- [x] **Parakeet TDT 0.6B v3 による欧州25言語（英・仏・独・西）SOTA ASR 実装**
- [x] **Zipformer-vi 30M によるベトナム語声調特化 ASR 実装**
- [x] **SenseVoice Small によるアジア圏（中国語・韓国語）ASR 実装**
- [x] **インストーラー群（`installer_gui.py`, `setup.ps1`, `setup.sh`）への全モデル自動配備実装**
- [x] **包括的総合テストスイート（`test_polyglot_suite.py` 7/7 テスト）の 100% PASS**
- [x] **タスクバー＆システムトレイアイコンの動的ステータス色切り替え（待機中: スレート＆シアン、聞き取り中: エメラルドグリーン＆赤色LIVEバッジ）**
- [x] **コントロールパネルの画面共有ステルス保護対応（起動時 showEvent から完全自動適用）**
- [x] **GitHub リポジトリの Description、トピック、および README.md への oboroge0/hayamimi Fork クレジット・バッジ明記**
- [x] **GitHub コミュニティドキュメント整備（Code of Conduct, Contributing, Security Policy 各日本語版）**
- [x] **Dependabot エラー解消 ＆ 最新構文（`groups` による PR まとめ機能）導入**
- [x] **Dependabot PR 10 件の動作検証・安全マージ・最新統合**

## 直近の検証結果
- **Dependabot 設定 & PR 処理**:
  - `github-actions` エラー除去、最新構文 `groups: python-dependencies: patterns: ["*"]` 導入完了。
  - GitHub ラベル `dependencies`, `python` 新設完了。
  - PR #1〜#10（全10件）は Python 3.14 環境で実動検証済み。全件問題なし。
  - PR #1〜#4 をマージ、PR #5〜#10 は Dependabot のグループ化により自動クローズ。
  - `requirements.txt` を全件の検証済み最新バージョン（NumPy 2.5.4, sherpa-onnx 2.0.1, CTranslate2 4.8.4, PySide6 6.12.0 等）へ一括最新化完了。
- **総合テストスイート（`test_polyglot_suite.py`）**:
  - 全 7 テスト（辞書、VAD、8言語ASR、遅延ロード、8言語NMT、LID言語判定、セキュリティ制約）が 100% PASS。
