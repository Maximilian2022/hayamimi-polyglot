# 一時作業メモ (memo.md)

## 現在のタスク
- [x] **ReazonSpeech ホットワード制約調査 & ベンチマーク検証**
  - [x] Byte-level BPE による sherpa-onnx FST トークン破棄の解明
  - [x] Greedy Search vs Modified Beam Search 実機性能測定（Greedy 174ms 脱落ゼロ vs Beam 277ms 中抜けCER 59%）
  - [x] 設計合意: ASR は最速 Greedy Search、補正は SudachiPy 形態素解析による確定後処理エンジンを採用
- [x] **SudachiPy による確定後処理エンジンの実装 (core/dictionary.py)**
  - [x] 読み (reading_form) を利用した音響類似誤認識の補正 (例: テック vs テッチリ を 0.5ms で高精度補正)
  - [x] 英略語・表記ゆれのケース正規化 (kpi -> KPI, saas -> SaaS, dx -> DX)
  - [x] 日常語ストップワード保護による誤爆防止
  - [x] Dictionary.tokenizer() への移行による非推奨警告解消
- [x] **デフォルト辞書の拡充 (2軸)**
  - [x] ① オフライン同梱: usiness_terms.txt (250語+), listed_companies.txt (250社+), 	erm_replacements.txt (116ルール新設)
  - [x] ② オンラインオプション: dicts/extensions/ カタログ枠組み (医療・製薬、法務・行政、EDINET 4000社、先端科学技術)
- [x] **ASR エンジン (core/asr_engine.py) の Greedy Search 統一**
- [x] **テストスイート (	est_polyglot_suite.py) の検証 (全7テスト 100% PASS)**
- [x] **改修履歴 (docs/remediation_history.md) の更新**
- [x] **設計決定事項 (docs/memory.md) の長期記憶更新**
- [x] **version.txt 連動の GitHub Release 自動作成 & 動的 Portable パッケージ CI/CD 構築**
- [x] **CI Release ワークフローの gh release edit API 連携修正 (Windows アップロード失敗解消)**
- [x] **破損キャッシュ破棄 & scripts/download_models.py による完全モデル同梱 (1.8GB) の復元**
