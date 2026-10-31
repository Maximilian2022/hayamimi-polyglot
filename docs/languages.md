# Hayamimi Polyglot - 言語・モデル相関仕様書 (`docs/languages.md`)

本書は、**Hayamimi Polyglot** における「音声の聞き取り（ASR: Speech-to-Text）」および「多言語機械翻訳（NMT: Text-to-Text）」の担当 AI モデル、推論ランタイム、言語カバー範囲、およびリソース管理設計をまとめた技術仕様書です。

---

## 1. 主要 8 言語 マッピング一覧（UI 提供言語）

UI（コントロールパネル）で選択可能な主要 8 言語における、**音声認識（入力）** と **翻訳（出力）** の担当モデル一覧です。

| 言語 | 国旗 | 音声聞き取り (ASR) 担当モデル | ASR 推論ランタイム | 翻訳 (NMT) 担当モデル | NMT 推論ランタイム |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **日本語** (`ja`) | 🇯🇵 | **ReazonSpeech Zipformer** (辞書・Hotwords特化) | sherpa-onnx (CPU) | **FuguMT** (対英) / **M2M-100** | CTranslate2 INT8 |
| **英語** (`en`) | 🇺🇸 | **Parakeet TDT 0.6B** (SOTA特化) | sherpa-onnx (CPU) | **M2M-100** (万能相互翻訳) | CTranslate2 INT8 |
| **中国語** (`zh`) | 🇨🇳 | **SenseVoice Small** (ネイティブ) | sherpa-onnx (CPU) | **M2M-100** (万能相互翻訳) | CTranslate2 INT8 |
| **韓国語** (`ko`) | 🇰🇷 | **SenseVoice Small** (ネイティブ) | sherpa-onnx (CPU) | **M2M-100** (万能相互翻訳) | CTranslate2 INT8 |
| **フランス語** (`fr`) | 🇫🇷 | **Parakeet TDT v3** (欧州25言語版) | sherpa-onnx (CPU) | **M2M-100** (万能相互翻訳) | CTranslate2 INT8 |
| **ドイツ語** (`de`) | 🇩🇪 | **Parakeet TDT v3** (欧州25言語版) | sherpa-onnx (CPU) | **M2M-100** (万能相互翻訳) | CTranslate2 INT8 |
| **スペイン語** (`es`) | 🇪🇸 | **Parakeet TDT v3** (欧州25言語版) | sherpa-onnx (CPU) | **M2M-100** (万能相互翻訳) | CTranslate2 INT8 |
| **ベトナム語** (`vi`) | 🇻🇳 | **Zipformer-vi** (ベトナム語特化) | sherpa-onnx (CPU) | **M2M-100** (万能相互翻訳) | CTranslate2 INT8 |

---

## 2. 音声聞き取り（ASR）モデル詳細

CPU のみで動作し、ノート PC のファンを回さない低負荷（INT8 量子化）モデルを言語特性に合わせて最適分担しています。

```
[マイク / 会議音声] ──> [Silero VAD (ONNX)]
                              │ (発声検知・無音時CPU停止)
                              ▼
                ┌─────────────┼─────────────┐
                ▼                           ▼                             ▼
         【日本語 (ja)】              【英語・欧米圏】              【中・韓・アジア圏】
      ReazonSpeech Zipformer        Parakeet TDT 0.6B              SenseVoice Small
     (Hotwords & 辞書固定)       (SOTA英語・欧州25言語)           (中国語・韓国語ネイティブ)
                                            │
                                            ▼
                                  【東南アジア (越語)】
                                      Zipformer-vi
                                    (ベトナム語声調特化)
```

### ① ReazonSpeech Zipformer (Reazon Human Interaction Lab) - 【日本語メイン固定】
- **担当言語**: 日本語 (`ja`) 固定
- **推論エンジン**: `sherpa-onnx` (`from_transducer`)
- **サイズ**: 約 250 MB (INT8)
- **特徴**:
  - 日本語のビジネス会議における **メイン固定モデル**。
  - アジェンダや資料から抽出した社内用語・プロジェクト名・人名をデコード時に動的注入する「**Instant Hotwords**（ホットワードバイアス）」に完全対応。
  - 金融庁EDINETの全上場企業名や SudachiDict によるビジネス辞書置換が最も相性良く機能。

### ② Parakeet TDT 0.6B (NVIDIA NeMo) - 【英語・欧米圏メイン】
- **担当言語**:
  - v2: 英語 (`en`) 特化
  - v3: 英語 (`en`), フランス語 (`fr`), ドイツ語 (`de`), スペイン語 (`es`), イタリア語 (`it`) など欧州 25 言語
- **推論エンジン**: `sherpa-onnx` (`from_transducer`, `model_type="nemo_transducer"`)
- **サイズ**: 約 460〜480 MB (INT8)
- **処理速度**: 1秒の音声を約80msでデコード
- **特徴**:
  - TDT (Token-and-Duration Transducer) アーキテクチャにより、従来の自己回帰モデル（Whisper等）より圧倒的に少ない推論ステップでデコード。
  - 英語ネイティブの早口会話、ビジネス略語、スラング、句読点、大文字小文字の再現性が世界最高水準（SOTA）。
  - **※完全 CPU 動作**: NVIDIA 製アーキテクチャですが、INT8 最適化により GPU/CUDA 不要・Intel Core i5 / AMD Ryzen CPU のみで軽快に動作。

### ③ SenseVoice Small (Alibaba Tongyi Lab) - 【中国語・韓国語・アジア圏】
- **担当言語**: 中国語 (`zh`: 普通話・広東語), 韓国語 (`ko`), アジア圏多言語
- **推論エンジン**: `sherpa-onnx` (`from_sense_voice`)
- **サイズ**: 約 240 MB (INT8)
- **処理速度**: RTF < 0.05 (1秒の音声を約20msでデコード)
- **特徴**:
  - 中国語・韓国語などアジア系言語の音声認識精度が極めて高く、漢字変換や数字正規化（ITN）が美しい。
  - 音声の言語判定（LID）プローブとしても機能。

### ④ Zipformer-vi 30M (Next-gen Kaldi / sherpa-onnx) - 【ベトナム語専用】
- **担当言語**: ベトナム語 (`vi`) 専用
- **推論エンジン**: `sherpa-onnx` (`from_transducer`)
- **サイズ**: 約 35 MB (INT8)
- **処理速度**: 1秒の音声を約15msでデコード
- **特徴**:
  - ベトナム語の複雑な 6 つの声調と母音を高精度に識別するために学習された超軽量モデル。
  - 容量がわずか 35MB 前後と極めて小さく、必要な時だけ即座に起動可能。

---

## 3. 機械翻訳（NMT）モデル詳細

入力言語から出力言語へのテキスト変換は、**CTranslate2 (高速 C++ Transformer ランタイム)** 上で INT8 量子化モデルが担当します。

### ① Meta M2M-100 (418M INT8)
- **担当言語**: 世界 100 言語の任意のペア（`en -> ja`, `zh -> ja`, `ko -> ja`, `fr -> ja`, `de -> ja`, `es -> ja`, `vi -> ja`, `ja -> zh`, `ja -> ko` 等）
- **推論エンジン**: `CTranslate2` (CPU INT8)
- **サイズ**: 約 380 MB
- **特徴**:
  - 100言語の語彙・重みを標準で内包しているため、**追加ダウンロード不要**で全言語間の双方向翻訳が可能。
  - 1つの発言に対し、選択されている残り全言語（最大4言語）へ並行して即座に同時翻訳（マルチキャスト翻訳）を出力。

### ② FuguMT (ja -> en 特化)
- **担当言語**: 日本語 ➔ 英語 (`ja -> en`) 専用
- **推論エンジン**: `CTranslate2` (CPU INT8)
- **サイズ**: 約 190 MB
- **特徴**:
  - 日英ペアに特化して蒸留・学習されたモデル。
  - 約 20〜40ms という圧倒的な超高速で、こなれた自然なビジネス英語を生成。

---

## 4. 遅延ロード（Lazy Loading / オンデマンド起動）設計

Hayamimi Polyglot の基本原則である **「3〜5年前のノートPCのCPUのみで軽快に動作する」** を実現するため、以下のリソース制御を採用しています。

1. **未選択モデルの非活性（メモリ消費ゼロ）**:
   - ディスク（`models/`）に全モデルが配置されていても、会議の対象言語としてチェックされていない言語のモデル（例: ベトナム語やフランス語）は、**RAM（メモリ）にはロードされません**。
2. **通常会議時の最小フットプリント**:
   - 日常的な「日本語 🇯🇵 ＋ 英語 🇺🇸」の会議中は、SenseVoice と Parakeet のみがメモリに常駐。RAM 消費は数百MB、CPU 使用率は 5% 未満に抑えられます。
3. **オンデマンド即時呼び出し**:
   - 会議設定で特定の言語（例: 越語 🇻🇳）がチェックされた瞬間、バックグラウンドで該当モデル（約35MB）がスッと起動し、通訳パイプラインに合流します。

