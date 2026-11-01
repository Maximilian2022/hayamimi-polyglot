# Hayamimi Polyglot - 言語・モデル相関仕様書 (`docs/languages.md`)

本書は、**Hayamimi Polyglot** における「音声の聞き取り（ASR: Speech-to-Text）」、「音声前処理（DSP）」、および「多言語機械翻訳（NMT: Text-to-Text）」の担当 AI モデル、推論ランタイム、言語カバー範囲、およびリソース管理設計をまとめた技術仕様書です。

---

## 1. 主要 7 言語 マッピング一覧（UI 提供言語）

UI（コントロールパネル）で選択可能な主要 7 言語における、**音声認識（入力）** と **翻訳（出力）** の担当モデル一覧です。  
※本プロジェクトでは商用利用時のライセンス安全性を確保するため、非商用ライセンス（CC-BY-NC 等）のモデルを除外しています。

| 言語 | 国旗 | 音声聞き取り (ASR) 担当モデル | ASR 推論ランタイム | 翻訳 (NMT) 担当モデル | NMT 推論ランタイム |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **日本語** (`ja`) | 🇯🇵 | **ReazonSpeech Zipformer** (+ SudachiPy 後処理) | sherpa-onnx (CPU) | **FuguMT** (対英) / **M2M-100** | CTranslate2 INT8 |
| **英語** (`en`) | 🇺🇸 | **Parakeet TDT 0.6B v3** | sherpa-onnx (CPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **中国語** (`zh`) | 🇨🇳 | **SenseVoice Small** | sherpa-onnx (CPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **韓国語** (`ko`) | 🇰🇷 | **SenseVoice Small** | sherpa-onnx (CPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **フランス語** (`fr`) | 🇫🇷 | **Parakeet TDT 0.6B v3** (欧州25言語版) | sherpa-onnx (CPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **ドイツ語** (`de`) | 🇩🇪 | **Parakeet TDT 0.6B v3** (欧州25言語版) | sherpa-onnx (CPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **スペイン語** (`es`) | 🇪🇸 | **Parakeet TDT 0.6B v3** (欧州25言語版) | sherpa-onnx (CPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |

---

## 2. 音声前処理（DSP）＆ 音声聞き取り（ASR）モデル詳細

CPU のみで軽快に動作する INT8 量子化モデルを言語特性に合わせて分担しています。また、発話区間が ASR に渡される直前に 4 段のオーディオ DSP チェーンを通過することで、マイク環境や音量差による認識劣化を抑えています。

```
[マイク / 会議音声] ──> [Silero VAD (ONNX)]
                              │ (発話区間検知・ヒステリシス制御)
                              ▼
                  [4段オーディオ DSP チェーン]
        (1. ノイズゲート ➔ 2. 中音域EQ ➔ 3. ディエッサー ➔ 4. AGCコンプレッサー)
                              │
                ┌─────────────┼─────────────┐
                ▼                           ▼                             ▼
         【日本語 (ja)】              【英語・欧米圏】              【中・韓・アジア圏】
      ReazonSpeech Zipformer        Parakeet TDT 0.6B v3           SenseVoice Small
     (+ SudachiPy 辞書後処理)      (英語・欧州25言語対応)          (中国語・韓国語対応)
```

### ① ReazonSpeech Zipformer (Reazon Human Interaction Lab) - 【日本語メイン】
- **担当言語**: 日本語 (`ja`)
- **推論エンジン**: `sherpa-onnx` (`from_transducer`, `greedy_search`)
- **ライセンス**: Apache License 2.0（商用利用可）
- **サイズ**: 約 180 MB (INT8)
- **特徴**:
  - 日本語のビジネス会議におけるメインモデルとして常駐稼働します。
  - 発話脱落のない高速な Greedy Search で音声認識を行った後、`SudachiPy`（`SudachiDict-Full`）による形態素解析・音韻（読み）照合を用いた確定後処理エンジンにより、アジェンダから抽出した固有名詞（Instant Hotwords）や上場企業名、ビジネス略語を高精度に補正します。

### ② Parakeet TDT 0.6B v3 (NVIDIA NeMo) - 【英語・欧米圏メイン】
- **担当言語**: 英語 (`en`), フランス語 (`fr`), ドイツ語 (`de`), スペイン語 (`es`) など欧州 25 言語（v2 環境では英語特化）
- **推論エンジン**: `sherpa-onnx` (`from_transducer`, `model_type="nemo_transducer"`)
- **ライセンス**: Creative Commons Attribution 4.0 International (CC-BY-4.0)（商用利用可）
- **サイズ**: 約 460〜640 MB (INT8)
- **特徴**:
  - TDT (Token-and-Duration Transducer) アーキテクチャにより、少ない推論ステップで高速にデコードします。
  - 英語および主要欧州言語の自然な会話、ビジネス用語、句読点、大文字小文字の再現性に優れています。
  - INT8 量子化により、GPU（CUDA）を必要とせず一般的なノート PC の CPU のみで動作します。

### ③ SenseVoice Small (Alibaba Tongyi Lab) - 【中国語・韓国語・アジア圏】
- **担当言語**: 中国語 (`zh`: 普通話・広東語), 韓国語 (`ko`), アジア圏多言語
- **推論エンジン**: `sherpa-onnx` (`from_sense_voice`)
- **ライセンス**: FunASR Model Open Source License Agreement v1.1（商用利用許諾・要クレジット表示）
- **サイズ**: 約 240 MB (INT8)
- **特徴**:
  - 中国語・韓国語などアジア系言語の音声認識と数字正規化（ITN）を担当します。
  - 多言語会議時の言語判定（LID）プローブとしても機能します。

---

## 3. 機械翻訳（NMT）モデル詳細

入力言語から出力言語へのテキスト変換は、**CTranslate2 (高速 C++ Transformer ランタイム)** 上で INT8 量子化モデルが担当します。

### ① Meta M2M-100 (418M INT8)
- **担当言語**: 100 言語の任意のペア（`en -> ja`, `zh -> ja`, `ko -> ja`, `fr -> ja`, `de -> ja`, `es -> ja`, `ja -> zh`, `ja -> ko` 等）
- **推論エンジン**: `CTranslate2` (CPU INT8, `beam_size=1`)
- **ライセンス**: MIT License（商用利用可）
- **サイズ**: 約 480 MB
- **特徴**:
  - 多言語の語彙・重みを内包しており、追加ダウンロードなしで選択言語間の双方向翻訳を行います。
  - 1つの発言に対し、選択されている残り全言語（最大4言語）へ `translate_batch` により並行翻訳を出力します。

### ② FuguMT (ja -> en 特化)
- **担当言語**: 日本語 ➔ 英語 (`ja -> en`) 専用
- **推論エンジン**: `CTranslate2` (CPU INT8, `beam_size=1`)
- **ライセンス**: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)（商用利用可）
- **サイズ**: 約 135 MB
- **特徴**:
  - 日英ペアに特化した軽量翻訳モデルで、日本語から英語への翻訳を低遅延で処理します。

---

## 4. 遅延ロード（Lazy Loading / オンデマンド起動）設計

一般的なビジネスノート PC のメモリと CPU リソースを節約するため、以下のリソース制御を採用しています。

1. **未選択モデルの非活性**:
   - ディスク（`models/`）に全モデルが配置されていても、会議の対象言語として選択されていない言語のモデル（例: 中国語・韓国語、または欧州言語）は、初期状態では RAM にロードされません。
2. **単一言語選択時の直接ルーティング**:
   - 会議設定で 1 言語のみを選択している場合（文字起こし専念モード等）、言語判定用の複数モデルデコードを省略し、対象言語の ASR モデルのみを直接実行して CPU 負荷を抑えます。
3. **オンデマンド起動とメモリ解放**:
   - 会議設定で特定の言語がチェックされた際に該当モデルをロードし、チェックが外れたモデルの参照は解放してガベージコレクション（`gc.collect()`）を実行します。
