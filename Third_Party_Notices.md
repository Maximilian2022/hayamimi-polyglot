# Third-Party Notices & Open Source Licenses

本ソフトウェア（**Hayamimi Polyglot**）には、多数のオープンソースソフトウェア、事前学習済みAIモデル、およびオープンデータが組み込まれています。  
本プロジェクトの実現に貢献してくださった原著作者・開発元・研究機関の皆様に深く感謝いたします。

---

## 1. 原案・ベースプロジェクト

### oboroge0/hayamimi
* **提供元**: [oboroge0/hayamimi](https://github.com/oboroge0/hayamimi)
* **ライセンス**: MIT License
* **著作権表示**: Copyright (c) 2026 oboroge0
* **ライセンス条文**:
  ```text
  MIT License

  Copyright (c) 2026 oboroge0

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.
  ```

---

## 2. 事前学習済み AI モデル (ASR / NMT / VAD)

### ① SenseVoice Small (アジア多言語・感情認識 ASR)
* **提供元**: Alibaba Group ([FunASR / SenseVoice](https://github.com/FunASR/SenseVoice))
* **モデル名**: `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` (`SenseVoiceSmall`)
* **ライセンス**: FunASR Model Open Source License Agreement (v1.1)
* **商用利用**: **許諾（Permitted）**（※要クレジット・モデル名表記）
* **著作権表示**: Copyright (C) 2023-2028 Alibaba Group. All rights reserved.
* **ライセンス条約抜粋**:
  ```text
  Section 2: License and Restrictions
  2.1 License: You are free to use, copy, modify, and share [FunASR Software] under the terms of this agreement.
  2.2 Restrictions: When using, copying, modifying, and sharing [FunASR Software], you must attribute the source and author information and retain relevant model names in [FunASR Software].
  ```

### ② NVIDIA NeMo Parakeet TDT 0.6B v3 (欧米多言語 ASR)
* **提供元**: NVIDIA Corporation ([NVIDIA NeMo](https://github.com/NVIDIA/NeMo))
* **モデル名**: `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` / `v2-int8`
* **ライセンス**: Creative Commons Attribution 4.0 International (CC-BY-4.0)
* **商用利用**: **許諾（Permitted）**（※要クレジット表記）
* **著作権表示**: Copyright (c) NVIDIA Corporation. All rights reserved.

### ③ ReazonSpeech (日本語高精度・リアルタイム ASR)
* **提供元**: 株式会社レアゾン・ホールディングス ([ReazonSpeech](https://github.com/reazon-research/ReazonSpeech))
* **モデル名**: `sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17`
* **ライセンス**: Apache License 2.0
* **商用利用**: **許諾（Permitted）**
* **著作権表示**: Copyright 2023 Reazon Holdings, inc.

### ④ Meta M2M-100 (100言語相互マルチキャスト翻訳)
* **提供元**: Meta AI / Facebook AI Research ([M2M-100](https://github.com/facebookresearch/fairseq/tree/main/examples/m2m_100))
* **モデル名**: `mojicast-m2m100-ct2` (418M INT8)
* **ライセンス**: MIT License
* **商用利用**: **許諾（Permitted）**
* **著作権表示**: Copyright (c) Meta Platforms, Inc. and affiliates.

### ⑤ FuguMT (日本語-英語 特化高速機械翻訳)
* **提供元**: Staircase / 京都大学 ([FuguMT](https://github.com/stair-lab/fugu-mt))
* **モデル名**: `mojicast-fugumt-ja-en-ct2`
* **ライセンス**: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
* **商用利用**: **許諾（Permitted）**

### ⑥ Silero VAD (音声区間検出)
* **提供元**: Silero Team ([silero-vad](https://github.com/snakers4/silero-vad))
* **モデル名**: `silero_vad.onnx`
* **ライセンス**: MIT License
* **商用利用**: **許諾（Permitted）**
* **著作権表示**: Copyright (c) 2021 Silero Team

---

## 3. 主要オープンソースライブラリ・ランタイム

### PySide6 / Qt6
* **ライセンス**: GNU Lesser General Public License version 3 (LGPLv3)
* **著作権表示**: Copyright (C) 2026 The Qt Company Ltd.
* **動的リンク**: 本プロジェクトでは PySide6 を独立した動的リンクライブラリとして使用しており、LGPLv3 のリバースエンジニアリング・再リンク条項に準拠しています。

### sherpa-onnx
* **ライセンス**: Apache License 2.0
* **著作権表示**: Copyright (c) 2022-2026 Next-gen Kaldi contributors

### ONNX Runtime
* **ライセンス**: MIT License
* **著作権表示**: Copyright (c) Microsoft Corporation. All rights reserved.

### CTranslate2
* **ライセンス**: MIT License
* **著作権表示**: Copyright (c) 2019-2026 Guillaume Klein, OpenNMT

### SudachiPy & SudachiDict
* **ライセンス**: Apache License 2.0
* **著作権表示**: Copyright (c) 2017-2026 Works Applications Co., Ltd.

### FastAPI / Starlette / Uvicorn
* **ライセンス**: MIT License / BSD-3-Clause
* **著作権表示**: Copyright (c) Sebastián Ramírez / Encode OSS

---

## 4. 辞書・オープンデータ

### 金融庁 EDINET 全上場企業名オープンデータ
* **提供元**: 金融庁 (Financial Services Agency, Japan)
* **ライセンス**: 金融庁オープンデータ利用規約（政府標準利用規約2.0準拠）
* **商用利用**: **許諾（Permitted）**
* **クレジット**: 金融庁 EDINET 提出者一覧オープンデータをもとに作成
