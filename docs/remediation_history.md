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

## 6. setup.ps1 フォルダ参照ダイアログのアセンブリ未読込エラー修正
- **内容**:
  - `setup.ps1`:
    - インストール先「参照」ボタン押下時に `[System.Windows.Forms.FolderBrowserDialog]` のアセンブリが読み込まれておらず例外となっていた問題を解消。
    - スクリプト先頭に `Add-Type -AssemblyName System.Windows.Forms` を追加。
    - さらに例外発生時のフォールバックとして Windows 標準 COM オブジェクト `Shell.Application` によるフォルダ参照ダイアログを実装し、いかなる Windows / PowerShell 環境でも確実にフォルダ選択ができるよう二重化。

## 7. setup.ps1 インストーラー GUI レイアウト・ログ表示領域およびボタンスタイルの大幅改善
- **内容**:
  - `setup.ps1`:
    - モデル選択グループの高さによりログ表示用テキストボックス（`TxtLog`）が数ピクセル程度に押し潰され見えなくなっていた問題を解決。
    - ウィンドウサイズを `Height="620" Width="580"` から `Height="780" Width="640" (MinHeight="680")` に拡大。
    - `ResizeMode="CanResizeWithGrip"` を設定し、ユーザーが手動でウィンドウサイズを伸縮できるように改善。
    - ログ表示領域（`TxtLog`）に最低 `MinHeight="140"` を保証し、スクロールバーを常時表示（`Visible`）して進行状況が8行以上はっきり視認できるように改修。
    - Windows 11 の標準 Aero テーマで「参照...」ボタンや「セットアップ開始」ボタンの背景・文字が白飛び/グレー化してコントラストが低下していた現象を防ぐため、WPF `ControlTemplate` によるカスタムボタンスタイルを導入。マウスポインタのホバー・クリック効果も美しくダークテーマに統一。

## 8. setup.sh (macOS) のモデル自動配備・カラーログ視認性および設定同期の強化
- **内容**:
  - `setup.sh`:
    - macOS 版は現在ターミナル（CLI）実行型スクリプトのため、Windows のような「小枠でログが潰れる」現象は発生しないが、ログの見やすさ・進捗把握を大幅に向上させるため ANSI カラーエスケープによるモダンなターミナル表示を導入。
    - 新設した `.python-version` およびテストスイート `test_polyglot_suite.py` の同期コピーを追加。
    - ローカルモデルキャッシュ（`models`）からの自動配備ロジックおよび SenseVoice Small 多言語モデル（`--with-sense-voice`）の自動ダウンロードロジックを実装し、Windows インストーラーと同等の機能を確保。

## 9. macOS 向け PySide6 クロスプラットフォーム統一 GUI インストーラーの実装
- **内容**:
  - `installer_gui.py` を新設:
    - Windows 版と完全に同一のダークテーマデザイン、モデル構成チェックボックス、プログレスバー、140px以上の広々とした等幅フォントログエリア、フォルダ参照ピッカー、自動起動オプションを PySide6 で構築。
    - macOS（iCloud Drive 自動検知・退避）、Windows（OneDrive 自動検知・退避）の双方に対応。
    - マルチスレッド（QThread）による非同期セットアップ実行で、UI のフリーズゼロ・リアルタイム進行表示を実現。
  - `setup.sh`:
    - macOS ユーザーが `./setup.sh` を実行した際、`uv run --python 3.14 --with PySide6 python installer_gui.py` を自動起動し、システムに Python や PySide6 が無くても一瞬で Windows と全く同じモダン GUI ウィンドウが立ち上がるように改修。
    - `--cli` や `--unattended` 引数、またはヘッドレス環境では自動的に CLI モードへフォールバックするハイブリッド設計を確立。

## 10. setup.ps1 を installer_gui.py (PySide6) 呼び出しへ全面刷新・完全統一
- **内容**:
  - `setup.ps1`:
    - Windows と macOS の GUI インストーラーを `installer_gui.py`（PySide6）に完全一本化。
    - PowerShell 独自の WPF/XAML コードを撤廃し、`uv run --python 3.14 --with PySide6 python installer_gui.py` を直接呼び出すスマートブートストラップに刷新。
    - これにより、PowerShell のファイルエンコーディング差異、Runspace スレッド競合、ボタン描画崩れのリスクが根本的に解消され、Windows でも Mac でも 100% 同一の高品質なダークテーマ GUI が起動するように改修。
    - `--cli` / `--unattended` 引数によるコマンドライン自動セットアップ機能も維持。

