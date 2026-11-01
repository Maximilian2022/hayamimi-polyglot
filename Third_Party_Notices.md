# Third-Party Notices & Open Source Licenses

本ソフトウェア（**Hayamimi Polyglot**）には、オープンソースソフトウェア、事前学習済みAIモデル、およびオープンデータが組み込まれています。  
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

### ① SenseVoice Small (アジア多言語 ASR)
* **提供元**: Alibaba Group ([FunASR / SenseVoice](https://github.com/FunASR/SenseVoice))
* **モデル名**: `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` (`SenseVoiceSmall`)
* **ライセンス**: FunASR Model Open Source License Agreement (v1.1)
* **商用利用**: 許諾（Permitted）（※要クレジット・モデル名表記）
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
* **商用利用**: 許諾（Permitted）（※要クレジット表記）
* **著作権表示**: Copyright (c) NVIDIA Corporation. All rights reserved.

### ③ ReazonSpeech (日本語リアルタイム ASR)
* **提供元**: 株式会社レアゾン・ホールディングス ([ReazonSpeech](https://github.com/reazon-research/ReazonSpeech))
* **モデル名**: `sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17`
* **ライセンス**: Apache License 2.0
* **商用利用**: 許諾（Permitted）
* **著作権表示**: Copyright 2023 Reazon Holdings, inc.

### ④ Meta M2M-100 (100言語相互翻訳) & CTranslate2 変換モデル
* **原モデル提供元**: Meta AI / Facebook AI Research ([M2M-100](https://github.com/facebookresearch/fairseq/tree/main/examples/m2m_100))
* **CTranslate2 量子化モデル提供元**: [mojicast/mojicast-m2m100-ct2](https://huggingface.co/mojicast/mojicast-m2m100-ct2)
* **モデル名**: `mojicast-m2m100-ct2` (418M INT8)
* **ライセンス**: MIT License
* **商用利用**: 許諾（Permitted）
* **著作権表示**: Copyright (c) Meta Platforms, Inc. and affiliates.

### ⑤ FuguMT (日本語-英語 機械翻訳) & CTranslate2 変換モデル
* **原モデル提供元**: Takuya Shibata (staka) / Staircase ([FuguMT](https://github.com/staka/fugumt))
* **CTranslate2 量子化モデル提供元**: [mojicast/mojicast-fugumt-ja-en-ct2](https://huggingface.co/mojicast/mojicast-fugumt-ja-en-ct2)
* **モデル名**: `mojicast-fugumt-ja-en-ct2`
* **ライセンス**: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
* **商用利用**: 許諾（Permitted）
* **著作権表示**: Copyright (c) Takuya Shibata (staka)

### ⑥ Silero VAD (音声区間検出)
* **提供元**: Silero Team ([silero-vad](https://github.com/snakers4/silero-vad))
* **モデル名**: `silero_vad.onnx`
* **ライセンス**: MIT License
* **商用利用**: 許諾（Permitted）
* **著作権表示**: Copyright (c) 2021 Silero Team

---

## 3. 主要オープンソースライブラリ・ランタイム

### PySide6 / Qt6 (PySide6-Essentials)
* **提供元**: [The Qt Company](https://www.qt.io/qt-for-python)
* **ライセンス**: GNU Lesser General Public License version 3 (LGPLv3)
* **著作権表示**: Copyright (C) 2026 The Qt Company Ltd.
* **動的リンク**: 本プロジェクトでは PySide6 を独立した動的リンクライブラリ（共有ライブラリ / wheel）として使用しており、LGPLv3 のリバースエンジニアリング・ライブラリ差し替え条項に準拠しています。

### sherpa-onnx
* **提供元**: [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
* **ライセンス**: Apache License 2.0
* **著作権表示**: Copyright (c) 2022-2026 Next-gen Kaldi contributors

### ONNX Runtime
* **提供元**: [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime)
* **ライセンス**: MIT License
* **著作権表示**: Copyright (c) Microsoft Corporation. All rights reserved.

### CTranslate2
* **提供元**: [OpenNMT/CTranslate2](https://github.com/OpenNMT/CTranslate2)
* **ライセンス**: MIT License
* **著作権表示**: Copyright (c) 2019-2026 Guillaume Klein, OpenNMT

### SentencePiece
* **提供元**: [google/sentencepiece](https://github.com/google/sentencepiece)
* **ライセンス**: Apache License 2.0
* **著作権表示**: Copyright (c) 2018 Google Inc.

### SudachiPy & SudachiDict
* **提供元**: [WorksApplications/SudachiPy](https://github.com/WorksApplications/SudachiPy) / [SudachiDict](https://github.com/WorksApplications/SudachiDict)
* **ライセンス**: Apache License 2.0
* **著作権表示**: Copyright (c) 2017-2026 Works Applications Co., Ltd.

### NumPy
* **提供元**: [numpy/numpy](https://github.com/numpy/numpy)
* **ライセンス**: BSD 3-Clause License
* **著作権表示**: Copyright (c) 2005-2026, NumPy Developers. All rights reserved.

### python-sounddevice & PortAudio
* **提供元**: [spatialaudio/python-sounddevice](https://github.com/spatialaudio/python-sounddevice) / [PortAudio](https://www.portaudio.com/)
* **ライセンス**: MIT License
* **著作権表示**: Copyright (c) 2015-2026 Matthias Geier / Copyright (c) 1999-2026 Ross Bencina and Phil Burk

### python-soundfile & libsndfile
* **提供元**: [bastibe/python-soundfile](https://github.com/bastibe/python-soundfile) / [libsndfile](https://github.com/libsndfile/libsndfile)
* **ライセンス**: BSD 3-Clause License (python-soundfile) / LGPL-2.1-or-later (libsndfile, 動的リンク)
* **著作権表示**: Copyright (c) 2013-2026 Bastian Bechtold / Copyright (c) 1999-2026 Erik de Castro Lopo

### comtypes & pycaw (Windows Audio Session API COM Bindings)
* **提供元**: [enthought/comtypes](https://github.com/enthought/comtypes) / [AndreMiras/pycaw](https://github.com/AndreMiras/pycaw)
* **ライセンス**: MIT License
* **著作権表示**: Copyright (c) 2006-2026 Thomas Heller, Enthought, Inc. / Copyright (c) 2016-2026 Andre Miras

### FastAPI / Starlette / Uvicorn / Pydantic
* **提供元**: [fastapi/fastapi](https://github.com/fastapi/fastapi) / [encode/starlette](https://github.com/encode/starlette) / [encode/uvicorn](https://github.com/encode/uvicorn)
* **ライセンス**: MIT License / BSD 3-Clause License
* **著作権表示**: Copyright (c) Sebastián Ramírez / Copyright (c) Encode OSS Ltd. / Copyright (c) Samuel Colvin and contributors

### Stand-alone Python Runtime & Package Manager (Portable Packages)
* **CPython Windows Runtime (Official PSF NuGet Package)**:
  * **提供元**: [Python Software Foundation](https://www.python.org/) / [python (NuGet)](https://www.nuget.org/packages/python)
  * **ライセンス**: [Python Software Foundation License Version 2 (PSFL)](https://docs.python.org/3/license.html)
  * **商用利用**: 許諾（Permitted）
  * **著作権表示**: Copyright (c) 2001-2026 Python Software Foundation; All Rights Reserved.
  * **署名**: Python Software Foundation による公式デジタル署名（Authenticode）付き正規バイナリ
* **CPython macOS Runtime (python-build-standalone)**:
  * **提供元**: [Python Software Foundation](https://www.python.org/) / [astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone)
  * **ライセンス**: PSF License Version 2 / MPL 2.0 (build scripts)
  * **商用利用**: 許諾（Permitted）
  * **著作権表示**: Copyright (c) 2001-2026 Python Software Foundation; All Rights Reserved. / Copyright (c) Gregory Szorc, Astral Software Inc.
* **uv**:
  * **提供元**: [astral-sh/uv](https://github.com/astral-sh/uv)
  * **ライセンス**: Apache License 2.0 / MIT License
  * **著作権表示**: Copyright (c) 2024-2026 Astral Software Inc.
* **Microsoft Visual C++ Redistributable Runtime (Windows Portable Package)**:
  * Windows ポータブル版には、C++ 拡張モジュール（ONNX Runtime / PySide6 / CTranslate2）の実行に必要な Microsoft Visual C++ 再頒布可能ランタイム DLL が Microsoft Software License Terms（再頒布条項）に基づき同梱されています。

---

## 4. 辞書・オープンデータ

### 金融庁 EDINET 全上場企業名オープンデータ
* **提供元**: [金融庁 (Financial Services Agency, Japan)](https://www.fsa.go.jp/) / [EDINET 閲覧（提出）サイト](https://disclosure2.edinet-fsa.go.jp/)
* **ライセンス**: [EDINET 利用規約](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0030.html) / [金融庁ウェブサイト利用規約](https://www.fsa.go.jp/site/term.html)（[政府標準利用規約2.0準拠](https://www.digital.go.jp/terms-of-use)）
* **商用利用**: 許諾（Permitted）
* **クレジット**: 金融庁 EDINET 提出者一覧オープンデータをもとに作成

### 日本取引所グループ (JPX) 東証上場銘柄一覧オープンデータ
* **提供元**: [株式会社日本取引所グループ (Japan Exchange Group, Inc.)](https://www.jpx.co.jp/) / [東証上場銘柄一覧（その他統計資料）](https://www.jpx.co.jp/markets/statistics-equities/misc/01.html)
* **ライセンス**: [JPX サイトのご利用条件（サイトポリシー）](https://www.jpx.co.jp/site-policy/)
* **商用利用**: 許諾（Permitted）

### Hayamimi ビジネス用語・英略語・表記補正ルール辞書
* **提供元**: Hayamimi Polyglot Project（本プロジェクトによる独自作成）
* **対象ファイル**: `dicts/business_terms.txt`, `dicts/term_replacements.txt`
* **ライセンス**: [Creative Commons Zero v1.0 Universal (CC0-1.0 / Public Domain)](https://creativecommons.org/publicdomain/zero/1.0/deed.ja)
* **商用利用**: 許諾（Permitted）
* **備考**: 外部の著作権保護された辞書からの転載ではなく、ビジネス現場で頻出する一般的な用語・略語・音声認識補正ルールを独自に整理・作成したデータセットです。

---

## 5. オンラインオプション拡張辞書（追加ダウンロードデータ）

### 万病辞書 (Manbyo Dictionary) & MEDIS 標準病名マスター
* **対象機能**: 医療・製薬・ライフサイエンス専門辞書 (`medical_pharma.txt`)
* **提供元**: [奈良先端科学技術大学院大学 (NAIST) ソーシャル・コンピューティング研究室 (万病辞書)](https://sociocom.naist.jp/manbyo-dic/) / [一般財団法人 医療情報システム開発センター (MEDIS-DC)](https://www.medis.or.jp/)
* **ライセンス**: [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/deed.ja) / [MEDIS 病名マスター利用条件](https://www.medis.or.jp/master/byomei/)
* **商用利用**: 許諾（Permitted）
* **著作権表示**: Copyright (c) 2017-2026 Social Computing Lab, NAIST.

### デジタル庁 e-Gov 法令オープンデータ
* **対象機能**: 法務・知財・行政・コンプライアンス辞書 (`legal_compliance.txt`)
* **提供元**: [デジタル庁 (Digital Agency, Japan) e-Gov法令検索](https://elaws.e-gov.go.jp/)
* **ライセンス**: [e-Gov利用規約](https://elaws.e-gov.go.jp/terms/) / [デジタル庁ウェブサイト利用規約（政府標準利用規約2.0準拠）](https://www.digital.go.jp/terms-of-use)
* **商用利用**: 許諾（Permitted）
