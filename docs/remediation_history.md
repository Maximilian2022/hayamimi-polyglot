# 修正・改修履歴 (remediation_history.md) - Hayamimi Polyglot

## 1. リポジトリの初期分離 & GitHub プッシュ
- **コミット**: `3d3bb3d` (Initial commit)
- **内容**:
  - `E:\hayamimi-polyglot` を独立リポジトリとして初期化。
  - GitHub Private リポジトリ `https://github.com/Maximilian2022/hayamimi-polyglot` に初期プッシュ。
  - コアエンジン、UI、辞書、インストーラー、テストスイートを配置。

## 2. インストーラー・アップデータのクリーン再構築機能の実装
- **コミット**: `7b3a38d`
- **内容**:
  - `setup.ps1`:
    - 既存環境検出時のモード自動切り替え。
    - 「🔄 Python仮想環境をクリーン再構築する (推奨)」チェックボックス新設（デフォルトON）。
    - `uv venv --clear` により、uv ローカルキャッシュを活用して再DLゼロ（1〜2秒）で無菌状態の環境を再構築。
    - `uv pip install -r requirements.txt --upgrade` で依存パッケージを最新同期。
    - SenseVoice Small 多言語モデルのダウンロードロジックを追加。
  - `setup.sh`:
    - 既存 `.venv` 検出時に `uv venv --clear` でクリーン再構築を実行するよう改修。

## 3. テストスイートのモデル解決パス強化
- **内容**:
  - `test_polyglot_suite.py`:
    - `find_models_dir()` を追加し、カレントディレクトリ配下の `models`、親ディレクトリの `models`、`E:\hayamimi\models` などを優先順に自動探索するように改善。
    - 独立実行時にも確実にモデルを発見できるように修正。

## 4. プロジェクト全体の Python 3.14 への統一と uv 隔離環境の検証
- **内容**:
  - `.python-version` をプロジェクトルートに新設し `3.14` を固定。
  - `requirements.txt`: NumPy 1.x が Python 3.14 向け pre-built wheel を持たず C コンパイラビルドエラーとなるのを防ぐため、`numpy>=1.26.0,<2.0.0` から `numpy>=1.26.0` に緩和。NumPy 2.x（`2.5.4`）が正常導入され全ライブラリと互換性を維持。
  - `setup.ps1` / `setup.sh`: 仮想環境構築時のターゲット Python バージョンを `3.12` から `3.14` に更新。
  - Python 3.14 環境（CPython 3.14.10）で `.venv` をクリーン再構築し、`test_polyglot_suite.py` の全5テスト（Hotwords, VAD/ASR, CTranslate2多言語翻訳, Windows Loopback, セキュリティ制約）が **100% PASS** することを確認。ホストOSの既存Python環境に干渉されない完全な隔離動作を実証。

## 5. setup.ps1 ローカル直接実行時のスクリプトパス解決エラー修正
- **内容**:
  - `setup.ps1`:
    - 関数 `Get-SmartInstallPath` や GUI イベントハンドラ内で `$MyInvocation.MyCommand.Path` を直接呼び出していたため、PowerShell の仕様により関数スコープでは `.Path` が `$null` となり `Split-Path` で引数バインド例外が発生していた問題を解消。
    - スクリプト最上位スコープにて `$ScriptDirectory`（`$PSScriptRoot` 優先、フォールバックとして `$PSCommandPath` / `Get-Location`）を確実に定義・保持する設計に変更。
    - ローカルからの直接実行（`.\setup.ps1`）および Web ワンライナー実行（`irm ... | iex`）の双方で例外なく安全にディレクトリ判定・ファイルコピーが行われるように改修。

