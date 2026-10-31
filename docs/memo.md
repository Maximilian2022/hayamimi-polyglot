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

## 直近の検証結果
- **8 言語 ASR 実音声デコードテスト（100% 成功）**:
  - `JA`: `うちの中学は弁当制で持っていけない場合は五十円の学校販売のパンを買う` (ReazonSpeech Zipformer)
  - `EN`: `Ask not what your country can do for you. Ask what you can do for your country.` (Parakeet TDT v3)
  - `ZH`: `开饭时间早上9点至下午5点。` (SenseVoice Small)
  - `KO`: `조금만 생각을 하면서 살면 훨씬 편할 거야.` (SenseVoice Small)
  - `FR`: `Ne vous demandez pas ce que votre pays peut faire pour vous. Demandez-vous plutôt ce que vous pouvez faire pour lui.` (Parakeet TDT v3)
  - `DE`: `Alles hat ein Ende, nur die Wurst zwei.` (Parakeet TDT v3)
  - `ES`: `No preguntes que puede hacer tu país por ti, pregunta que puedes hacer tú por tu país.` (Parakeet TDT v3)
  - `VI`: `RỒI CŨNG HỖ TRỢ CHO LÂU LÂU CŨNG CHO GẠO CHO NÀY KIA` (Zipformer-vi 30M)
- **遅延ロード（Lazy Loading）＆ メモリ解放の完全実証**:
  - `['ja', 'en']` 時: ReazonSpeech と Parakeet のみが RAM に常駐し、Zipformer-vi はメモリ消費 0MB。
  - `['ja', 'vi']` 切り替え時: Parakeet TDT を即座にアンロード（`gc.collect()` で RAM 解放）し、Zipformer-vi（約35MB）をオンデマンドで即時起動。
  - `['ja', 'zh', 'ko']` 切り替え時: Zipformer-vi をアンロード（RAM 解放）し、SenseVoice Small を起動。
- **8 言語相互同時翻訳（M2M-100 & FuguMT）**:
  - `ja -> en` (FuguMT), `en/zh/ko/fr/de/es/vi -> ja` (M2M-100), `ja -> zh/ko/vi` (M2M-100) すべて正常完了。
- **総合テストスイート（`test_polyglot_suite.py`）**:
  - 全 7 テスト（辞書、VAD、8言語ASR、遅延ロード、8言語NMT、LID言語判定、セキュリティ制約）が 100% PASS。
