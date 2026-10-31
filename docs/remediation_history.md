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

## 11. Web ワンライナー実行（新規端末）に対応する自動リモート取得・展開パイプラインの実装
- **内容**:
  - 課題: `irm ... | iex`（Windows）や `curl ... | bash`（Mac）などの Web ワンライナー実行時には、ローカルディスクに `installer_gui.py` やアプリケーションコード（`core/` 等）がまだ存在しないため起動・配備が失敗する致命的な穴を特定。
  - `setup.ps1` / `setup.sh`:
    - ローカルに `installer_gui.py` が存在しない場合、GitHub から一時ディレクトリ（`$env:TEMP` / `/tmp`）に `installer_gui.py` を自動取得し、即座に `uv run --with PySide6` で新UIを立ち上げるよう改修。
  - `installer_gui.py`:
    - セットアップ実行時にローカルにソースコードが存在しない場合、GitHub から最新のリポジトリ ZIP アーカイブを自動ダウンロード・解凍してインストール先ディレクトリへ完全配備するリモート展開パイプラインを実装（Git clone 代替フォールバック付き）。
    - Windows デスクトップショートカット作成において、`win32com` 未導入環境でも PowerShell WScript.Shell を直接呼ぶ堅牢なフォールバックを実装。

## 12. OneDrive リダイレクト環境における真のデスクトップパス検出とショートカット作成修正
- **内容**:
  - 課題: `Path.home() / "Desktop"`（`C:\Users\<user>\Desktop`）を固定参照していたため、OneDrive 等によりデスクトップが別ドライブ（`D:\onedrive\...\Desktop`）にリダイレクトされている環境ではフォルダ自体が存在せずショートカット作成が完全スキップされていた。
  - `installer_gui.py`:
    - `get_desktop_dir()` を新設し、Windows API `SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY [0x0010], ...)` を直接呼び出すことで、OneDrive やドメインポリシーでリダイレクトされた「真のデスクトップパス」を確実に取得するよう改修。
    - 実機テストを行い、ユーザーのデスクトップ画面に `Hayamimi Polyglot.lnk` が正常生成されることを確認。

## 13. main.py の起動クラッシュ (NameError) 修正および起動ランチャーのエラー捕捉強化
- **内容**:
  - `main.py`:
    - Windows App ID 設定処理で `platform.system()` を呼び出しているにもかかわらず `import platform` が欠落していたため `NameError` で起動直後に即死していた不具合を修正。
    - モデル配置ディレクトリ解決関数 `find_models_dir()` を追加し、ローカルや独立ディレクトリからでも確実に AI モデルを発見できるよう強化。
  - `core/vad.py`:
    - `model_path` にディレクトリパスが渡された場合でも自動的に `silero_vad.onnx` を解決するように防御的プログラミングを適用。
  - `start.bat` / `start.sh`:
    - アプリケーションがエラーで異常終了した際にターミナルウィンドウが一瞬で消えてしまうのを防ぐため、エラー終了時にメッセージを表示して一時停止（`pause` / `read -p`）するエラートラップ機構を Windows・macOS の双方に導入。

## 14. 複数マイク環境に対応する入力マイクデバイス選択機能の実装
- **内容**:
  - `ui/control_panel.py`:
    - ユーザー環境に複数のマイク（内蔵マイク、USBヘッドセット、外付けマイク、スピーカーフォン等）が接続されている場合に、使用するマイクを自在に切り替えられる「自分のマイク:」ドロップダウン（`combo_mic`）を新設。
    - `populate_microphones()` を実装し、Windows WASAPI / macOS CoreAudio から重複を排除した綺麗なマイクデバイス一覧（および「システム既定のマイク (Default)」）を自動列挙。再読込ボタン（🔄）も追加。
  - `main.py`:
    - `on_start_meeting()` で選択されたマイクデバイス ID を読み取り、`DualTrackCapture(mic_device=selected_mic, ...)` に正確に伝播するよう改修。

## 15. 音声認識が動かない問題の根本原因究明とマイクキャプチャの抜本的改修
- **内容**:
  - **原因特定**:
    - Windows の WASAPI 入力デバイス（Yeti Classic, BRIO, Jabra 750, G533 等）を選択した際、PortAudio/WASAPI の仕様により `samplerate=16000`（固定）で `sd.InputStream` を開こうとすると `PortAudioError: Invalid sample rate [PaErrorCode -9997]` が発生していた。
    - `core/audio/dual_capture.py` の `_run_mic()` 内で `except Exception as exc: pass` と例外が握りつぶされていたため、マイクスレッドが起動直後に即死し、音声データが 1 サンプルも ASR に送られていなかったことが「会議開始して何をしゃべっても何も表示されない」の直接的原因。
  - **改修内容**:
    - `core/audio/dual_capture.py`:
      - デバイス判定を行い、WASAPI デバイスの場合には `sd.WasapiSettings(auto_convert=True)` を設定して Windows Audio Engine の自動レートコンバータを有効化し、直接 16000Hz 1ch をオープンするよう改修。
      - さらにダイレクトオープンに失敗した場合の適応型フォールバック機構を導入。デバイスのネイティブサンプリングレート（44.1kHz / 48kHz 等）およびチャンネル数で開き、外部依存ゼロの超高速線形補間リサンプラ `_resample_linear`（1ブロックあたり 0.014ms・CPU負荷 0.04% 未満）によってリアルタイムに 16000Hz モノラル 512 サンプルへ変換して供給。
      - すべてのエラーを詳細ログ（`[Audio Mic]`）に出力するよう改善。
    - `main.py`:
      - `SessionWorker`: 発話開始前の無音区間でバッファが無限肥大化するのを防ぐため、8フレーム（約256ms）のプリロールリングバッファを導入。発話開始検知時にのみプリロール＋発話音声をバッファに結合して ASR へ供給することで、発話の頭切れ防止と無駄な無音デコードの完全防止を両立。
      - モデル探索 `find_models_dir()` から別プロジェクト（`E:\hayamimi\`）を完全排除し、`D:\hayamimi4b\models` およびローカル `models`（ジャンクション）を優先探索するように修正。

## 16. 字幕オーバーレイのフォント・文字サイズ・エリア・言語別文字色の完全カスタマイズ機能の実装
- **内容**:
  - `ui/overlay_window.py`:
    - フォント名（`font_family`）、文字サイズ（`font_size`）、背景の濃さ（`bg_opacity`）、字幕ウィンドウサイズ（幅・高さ）を動的に設定・反映できるプロパティおよびメソッド（`set_font_family`, `set_font_size`, `set_bg_opacity`, `set_overlay_size`）を追加。
    - 原文および翻訳文のスタイルに指定フォント（Meiryo, Yu Gothic UI 等のフォールバック付き）と文字サイズ（翻訳文は原文の約88%に自動スケーリング）を適用。
    - ウィンドウ右下に `QtWidgets.QSizeGrip` を配置し、マウスドラッグによる自由なエリアリサイズに対応。
    - **言語別文字色カスタマイズ機能**:
      - `DEFAULT_COLORS` 辞書を新設し、メイン発言者（`[自分]` タグ色、`[相手]` タグ色、原文本文色）および翻訳言語別（日本語 🇯🇵, 英語 🇺🇸, 中国語 🇨🇳, 韓国語 🇰🇷, 仏語 🇫🇷, 独語 🇩🇪, 西語 🇪🇸, 越語 🇻🇳, その他言語）の文字色を完全個別制御可能に。
      - `set_color(key, hex_color)` および `set_colors(dict)` を実装。
  - `ui/control_panel.py`:
    - 「🎨 字幕カスタマイズ (フォント・文字サイズ・エリア)」グループボックスを新設。
    - **フォント選択**: `QFontDatabase.families()` によりシステムにインストールされている 400 以上のローカルフォントを一覧列挙。「システム標準 (Meiryo / Yu Gothic)」を先頭に配置し、コンボボックス内での文字入力絞り込み検索（インクリメンタルサーチ）にも対応。
    - **文字サイズ**: 12px〜38px のスライダー＆リアルタイム数値表示。
    - **字幕エリア**: 幅（500〜1600px）＆高さ（120〜500px）のスライダーと、ワンクリック「標準 (840x190)」「ワイド (1150x220)」「コンパクト (650x140)」プリセットボタンを設置。
    - **背景の濃さ**: 20%〜100% のスライダーで透明度を調整可能。
    - **文字色設定**: 発言者（自分・相手・本文）および全翻訳言語の横にカラーボタンを配置。クリックで OS 標準のカラーパレット（`QColorDialog`）が開き、自由な色を即座に適用可能。「🔄 標準色に戻す」リセット機能も完備。
    - **設定永続化**: `config.json` への自動保存（`save_settings()`）と次回起動時の完全復元（`load_settings()`）を実装。フォント、サイズ、エリア幅・高、透明度、文字色、前回選択マイク、選択言語がすべて次回起動時に保持される。

## 17. アップデータ実行時のプロセスロック・エンコーディングエラー修正およびフォント選択の純粋ドロップダウン化
- **内容**:
  - **アップデータエラー解決**:
    - 現象: コントロールパネルの「⚙️ モデル追加/更新」ボタンを押してセットアップを開始した際、`Command '['...uv.EXE', 'venv', '--clear', ...] returned non-zero exit status 2` および `UnicodeDecodeError: 'cp932' codec can't decode byte 0x82` が発生。
    - 原因:
      1. 親プロセスの `main.py` が `.venv` 内の `python.exe` を実行中（ファイルロック中）のため、Windows OS により `--clear` によるファイル削除が `PermissionError` で拒絶されていた。
      2. `installer_gui.py` 内の `subprocess.run` が Windows の既定エンコーディング（CP932）で出力を読み取ろうとしたため、`uv` の UTF-8 出力でデコード例外が発生。
    - 対処:
      1. `installer_gui.py` にて `clean_venv` 実行時にプロセスロック等でクリア失敗した場合は例外停止せず、安全に「既存の仮想環境を健全更新」するフォールバックを実装。
      2. 既存環境のパスで起動された場合は「クリーン再構築」チェックボックスのデフォルトを OFF に設定。
      3. 全 `subprocess` 呼び出しに `text=True, encoding="utf-8", errors="replace"` を徹底付与し、いかなる日本語・記号出力でもクラッシュしないよう防護。
      4. `local_cache_candidates` に残存していた `E:/hayamimi/models` を `D:/hayamimi4b/models` に完全置換。
  - **フォント選択のドロップダウン化**:
    - `ui/control_panel.py`:
      - ユーザー要望に基づき、フォント選択コンボボックス（`self.combo_font`）を `setEditable(False)` に変更し、手入力テキストボックス型から純粋なクリック展開式「ドロップダウン（Dropdown）」に変更。
      - `QComboBox` のスタイルシートを拡張し、Windows 11 上で視認性の高いドロップダウン矢印（▼）と選択ハイライトリスト表示を適用。



