# Hayamimi Polyglot - 言語・モデル相関仕様書 (`docs/languages.md`)

本書は、**Hayamimi Polyglot** における「音声の聞き取り（ASR: Speech-to-Text）」、「音声前処理（DSP）」、および「多言語機械翻訳（NMT: Text-to-Text）」の担当 AI モデル、推論ランタイム、言語カバー範囲、およびリソース管理設計をまとめた技術仕様書です。

---

## 1. 主要 7 言語 マッピング一覧（UI 提供言語）

UI（コントロールパネル）で選択可能な主要 7 言語における、**音声認識（入力）** と **翻訳（出力）** の担当モデル一覧です。  
※本プロジェクトでは商用利用時のライセンス安全性およびサプライチェーン方針に基づき、非商用ライセンス（CC-BY-NC 等）および中華系モデルを除外し、商用利用可能な非中華系モデルのみで構成しています。

| 言語 | 国旗 | 音声聞き取り (ASR) 担当モデル | ASR 推論ランタイム | 翻訳 (NMT) 担当モデル | NMT 推論ランタイム |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **日本語** (`ja`) | 🇯🇵 | **ReazonSpeech Zipformer** (+ SudachiPy 後処理) | sherpa-onnx (CPU) / OpenVINO (NPU) | **FuguMT** (対英) / **M2M-100** | CTranslate2 INT8 |
| **英語** (`en`) | 🇺🇸 | **Parakeet TDT 0.6B v3** | sherpa-onnx (CPU) / OpenVINO (NPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **中国語** (`zh`) | 🇨🇳 | **Moonshine Streaming Tiny Zh** | onnxruntime (CPU INT8) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **韓国語** (`ko`) | 🇰🇷 | **NVIDIA Nemotron 3.5 ASR Streaming 0.6B** *(※1)* | sherpa-onnx (CPU INT8) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **フランス語** (`fr`) | 🇫🇷 | **Parakeet TDT 0.6B v3** (欧州25言語版) | sherpa-onnx (CPU) / OpenVINO (NPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **ドイツ語** (`de`) | 🇩🇪 | **Parakeet TDT 0.6B v3** (欧州25言語版) | sherpa-onnx (CPU) / OpenVINO (NPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |
| **スペイン語** (`es`) | 🇪🇸 | **Parakeet TDT 0.6B v3** (欧州25言語版) | sherpa-onnx (CPU) / OpenVINO (NPU) | **M2M-100** (多言語相互翻訳) | CTranslate2 INT8 |

> *(※1) 韓国語 ASR は、将来 **Moonshine Streaming KO（MIT License）** が公開されモデルディレクトリへ配置された場合、自動的に Moonshine へ優先切替できる互換構成を備えています。*

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
       ┌──────────────────────┼──────────────────────┬──────────────────────┐
       ▼                      ▼                      ▼                      ▼
  【日本語 (ja)】        【欧米圏 (en/fr/de/es)】   【中国語 (zh)】         【韓国語 (ko)】
ReazonSpeech Zipformer   Parakeet TDT 0.6B v3   Moonshine Streaming   Nemotron 3.5 ASR 0.6B
 (+ SudachiPy 辞書)       (欧州25言語対応)         Tiny Zh (MIT)       (Moonshine KO 切替対応)
```

### ① ReazonSpeech Zipformer (Reazon Human Interaction Lab) - 【日本語メイン】
- **担当言語**: 日本語 (`ja`)
- **推論エンジン**: `sherpa-onnx` (`from_transducer`, `greedy_search`) / NPU モード時は OpenVINO
- **ライセンス**: Apache License 2.0（商用利用可）
- **サイズ**: 約 180 MB (INT8)
- **特徴**:
  - 日本語のビジネス会議におけるメインモデルとして常駐稼働します。
  - 発話脱落のない高速な Greedy Search で音声認識を行った後、`SudachiPy`（`SudachiDict-Full`）による形態素解析・音韻（読み）照合を用いた確定後処理エンジンにより、アジェンダから抽出した固有名詞（Instant Hotwords）や上場企業名、ビジネス略語を高精度に補正します。

### ② Parakeet TDT 0.6B v3 (NVIDIA NeMo) - 【英語・欧米圏メイン】
- **担当言語**: 英語 (`en`), フランス語 (`fr`), ドイツ語 (`de`), スペイン語 (`es`) など欧州 25 言語（v2 環境では英語特化）
- **推論エンジン**: `sherpa-onnx` (`from_transducer`, `model_type="nemo_transducer"`) / NPU モード時は OpenVINO
- **ライセンス**: Creative Commons Attribution 4.0 International (CC-BY-4.0)（商用利用可）
- **サイズ**: 約 460〜640 MB (INT8)
- **特徴**:
  - TDT (Token-and-Duration Transducer) アーキテクチャにより、少ない推論ステップで高速にデコードします。
  - 英語および主要欧州言語の自然な会話、ビジネス用語、句読点、大文字小文字の再現性に優れています。

### ③ Moonshine Streaming Tiny Zh (Moonshine AI) - 【中国語】
- **担当言語**: 中国語 (`zh`: 普通話)
- **推論エンジン**: `onnxruntime` 5-graph 増分ランナー (`core/moonshine_asr.py`, CPU INT8)
- **ライセンス**: MIT License（商用利用可）
- **サイズ**: 約 48 MB (INT8)
- **特徴**:
  - Moonshine v2（Sliding-Window Streaming Attention）ベースの超軽量・超高速モデル（CPU RTF ~0.019）。
  - メモリ増分が約 83 MB と非常に小さく、低スペックノート PC でも軽快に動作します。

### ④ NVIDIA Nemotron 3.5 ASR Streaming 0.6B (NVIDIA) - 【韓国語】
- **担当言語**: 韓国語 (`ko`)
- **推論エンジン**: `sherpa-onnx` (`OnlineRecognizer.from_transducer`, Cache-Aware FastConformer-RNNT, CPU INT8)
- **ライセンス**: OpenMDW-1.1（商用利用可）
- **サイズ**: 約 651 MB (INT8)
- **特徴**:
  - 韓国語（`ko-KR`）が Transcription-ready ティアに指定された高精度ストリーミングモデルです。
  - 発話末チャンクの欠落を防ぐため、終了時に 1.2 秒の無音パディングを付与してデコードします。多言語混在ルーティング時は `auto` 言語プロンプトで他言語（日本語・中国語）への誤ハングル出力を抑制します。
  - 将来 Moonshine Streaming KO（MIT）が公開された際は、`models/moonshine-streaming-*-ko*`（5-graph または sherpa-onnx `from_moonshine_v2` 形式）を配置するだけで自動優先切替されます。

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
  - 1つの発言に対し、選択されている残り全言語（最大4言語）へ `translate_batch` により並行翻訳出力します。

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
   - ディスク（`models/`）に全モデルが配置されていても、会議の対象言語として選択されていない言語のモデル（英語/欧米・中国語・韓国語）は、初期状態では RAM にロードされません。
   - 中国語（`zh`）と韓国語（`ko`）は個別のオンデマンドスロットに分離されているため、中国語のみの会議で Nemotron（約 700MB RAM）が読み込まれることはありません。
2. **単一言語選択時の直接ルーティング**:
   - 会議設定で 1 言語のみを選択している場合（文字起こし専念モード等）、言語判定用の複数モデルデコードを省略し、対象言語の ASR モデルのみを直接実行して CPU 負荷を抑えます。
3. **オンデマンド起動とメモリ解放**:
   - 会議設定で特定の言語がチェックされた際に該当モデルをロードし、チェックが外れたモデルの参照は解放してガベージコレクション（`gc.collect()`）を実行します。
