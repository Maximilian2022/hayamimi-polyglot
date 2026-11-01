# 貢献ガイドライン (Contributing Guide)

**Hayamimi Polyglot** への貢献をご検討いただき、誠にありがとうございます。  
本プロジェクトは、ビジネス会議や商談における「ローカル動作・低遅延・プライバシー配慮型の多言語同時通訳支援ツール」を手軽に利用できるようにすることを目指しています。

バグ報告、新機能の提案、辞書データの追加、ドキュメントの改善、プルリクエストなど、あらゆる貢献を歓迎いたします。

---

## 1. 貢献の進め方

### ① バグ報告 (Bug Reports)
不具合や予期せぬ挙動を発見した場合は、GitHub の [Issues](https://github.com/Maximilian2022/hayamimi-polyglot/issues) からご報告ください。
以下の情報を含めていただくと迅速に調査できます：
- OS環境（Windows 11 のビルドバージョン、または macOS のバージョン）
- 使用したマイクデバイス（型番、内蔵マイク等）
- 選択していた言語構成（例: 日・英・中）
- 再現手順とエラーログ（コンソールまたはインストーラーのログ）

### ② 機能提案・アイデア (Feature Requests)
「新しい言語の追加」「UIの改善」「特定ツールとの連携」などのアイデアは、Issue にてお気軽にご提案ください。

### ③ 辞書データ・専門用語の拡充
`dicts/` フォルダ配下のビジネス用語・専門用語辞書に対する単語追加や誤認識補正ルールの提案も歓迎しています。

---

## 2. コア設計制約 (Must-Follow Principles)

コードを変更・追加する際は、以下の設計原則を遵守してください：

1. **音声データの非保存 (In-Memory Audio Processing)**:
   - 音声波形（PCM/WAV）をローカルディスクや一時ファイルに書き込む処理は導入しないでください。すべての音声処理はメモリ上の揮発性バッファ内でのみ行い、処理完了後に破棄します。
2. **推論パイプラインのオフライン完結 (No Telemetry)**:
   - クラウド API への音声送信、外部トラッキング・アナリティクス、外部 CDN への依存は行いません。推論はローカルの CPU で完結させます。
3. **ローカルホスト限定バインド**:
   - 内部 Web サーバー（ブラウザ共有ビュー用）は、`127.0.0.1` にのみバインドし、ワンタイムトークン認証を維持してください。
4. **商用利用可能なライセンスの維持**:
   - 導入するライブラリやモデルは、商用利用が許諾されたオープンソースライセンス（Apache 2.0 / MIT / BSD / CC-BY 4.0 等）に限ります。

---

## 3. ローカル開発環境のセットアップ

本プロジェクトは **Python 3.14** およびパッケージマネージャー **uv** を標準採用しています。

### 必要なツール
- [uv](https://astral.sh/uv)
- Git

### 開発環境の構築手順
```bash
# 1. リポジトリのクローン
git clone https://github.com/Maximilian2022/hayamimi-polyglot.git
cd hayamimi-polyglot

# 2. Python 3.14 仮想環境の構築 (uv)
uv venv .venv --python 3.14

# 3. 依存ライブラリのインストール
# Windows
uv pip install -r requirements.txt --python .venv/Scripts/python.exe
# macOS / Linux
uv pip install -r requirements.txt --python .venv/bin/python

# 4. 推論モデルのダウンロード
uv run python scripts/download_models.py
```

---

## 4. テストの実行と検証

コードを変更した後は、総合検証テストスイートを実行し、すべてのテストがパスすることを確認してください。

```bash
# Windows
$env:PYTHONIOENCODING="utf-8"
.venv/Scripts/python test_polyglot_suite.py

# macOS / Linux
PYTHONIOENCODING="utf-8" .venv/bin/python test_polyglot_suite.py
```

### 検証項目一覧:
- [TEST 1/8] ビジネス辞書 ＆ Instant Hotwords 抽出・境界保護
- [TEST 2/8] Silero VAD (音声区間検出)
- [TEST 3/8] 4段オーディオ DSP チェーン (Noise Gate / Mid-EQ / De-Esser / AGC)
- [TEST 4/8] 主要 7 言語 (日・英・中・韓・仏・独・西) ASR 音声デコード
- [TEST 5/8] 遅延ロード (Lazy Loading) ＆ 動的メモリ解放
- [TEST 6/8] 主要 7 言語 M2M-100 / FuguMT 相互同時翻訳
- [TEST 7/8] 多言語自動判定 (LID: Language Identification)
- [TEST 8/8] セキュリティ制約 (録音ファイル非保存、127.0.0.1 バインド、トークン認証、履歴クリア同期)

---

## 5. プルリクエスト (PR) の提出手順

1. 本リポジトリを Fork（またはブランチ作成）します。
2. 作業用のフィーチャーブランチを作成します：
   ```bash
   git checkout -b feature/awesome-feature
   ```
3. 変更をコミットします。コミットメッセージは [Conventional Commits](https://www.conventionalcommits.org/) の形式を推奨します：
   - `feat: ...` (新機能)
   - `fix: ...` (バグ修正)
   - `docs: ...` (ドキュメント更新)
   - `test: ...` (テスト追加・修正)
   - `refactor: ...` (リファクタリング)
4. ブランチをリモートにプッシュします：
   ```bash
   git push origin feature/awesome-feature
   ```
5. GitHub 上で Pull Request を作成し、変更内容の概要とテスト結果を記載してください。

---

ご不明な点がありましたら、お気軽に Issue にてご質問ください。
