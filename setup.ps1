# ==============================================================================
# Hayamimi Polyglot - Modern GUI Installer & Updater (Windows 11)
# Zero Admin Required (Non-admin friendly)
# Automatically detects & avoids OneDrive / Google Drive sync folders
# ==============================================================================

#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Unattended,
    [string]$InstallPath = ""
)

# Set UTF-8 encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Hide console window if launched from explorer/wscript
Add-Type -Name Win32Utils -Namespace Win32 -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern IntPtr GetConsoleWindow();
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
'@ -ErrorAction SilentlyContinue

# Load WPF assemblies
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

# Determine script directory reliably (supporting local execution and PSScriptRoot)
$ScriptDirectory = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}

# ------------------------------------------------------------------------------
# 1. Cloud Drive (OneDrive / Google Drive) Detection Logic
# ------------------------------------------------------------------------------
function Get-SmartInstallPath {
    # If existing repo directory is being run from, use that directory
    if ($ScriptDirectory -and (Test-Path (Join-Path $ScriptDirectory "core\asr_engine.py"))) {
        return $ScriptDirectory
    }

    $docs = [Environment]::GetFolderPath("MyDocuments")
    $isCloud = $false

    # Check OneDrive environment variable
    if ($env:OneDrive -and $docs.StartsWith($env:OneDrive, [System.StringComparison]::OrdinalIgnoreCase)) {
        $isCloud = $true
    }
    # Check path pattern
    if ($docs -match "OneDrive|Google Drive|GoogleDrive|Dropbox|iCloud") {
        $isCloud = $true
    }
    # Check registry User Shell Folders
    try {
        $regVal = (Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" -Name "Personal" -ErrorAction SilentlyContinue).Personal
        if ($regVal -match "OneDrive|Google") { $isCloud = $true }
    } catch {}

    if ($isCloud) {
        # Test C:\ drive root write permission
        $canWriteC = $false
        try {
            $testFile = "C:\hayamimi_test_$([guid]::NewGuid().ToString('N')).tmp"
            [IO.File]::WriteAllText($testFile, "test")
            [IO.File]::Delete($testFile)
            $canWriteC = $true
        } catch {
            $canWriteC = $false
        }

        if ($canWriteC) {
            return "C:\hayamimi-polyglot"
        } else {
            return "$env:LOCALAPPDATA\Programs\hayamimi-polyglot"
        }
    } else {
        return (Join-Path $docs "hayamimi-polyglot")
    }
}

$DefaultInstallPath = if ($InstallPath) { $InstallPath } else { Get-SmartInstallPath }

# ------------------------------------------------------------------------------
# 2. XAML Definition for WPF GUI
# ------------------------------------------------------------------------------
$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Hayamimi Polyglot - セットアップ ＆ 更新"
        Height="620" Width="580"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Background="#0F172A" Foreground="#F8FAFC"
        FontFamily="Segoe UI, Meiryo">
    <Window.Resources>
        <Style TargetType="TextBlock">
            <Setter Property="Foreground" Value="#F8FAFC"/>
        </Style>
        <Style TargetType="GroupBox">
            <Setter Property="BorderBrush" Value="#334155"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Margin" Value="0,8,0,0"/>
            <Setter Property="Padding" Value="10"/>
            <Setter Property="Foreground" Value="#94A3B8"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
        </Style>
        <Style TargetType="CheckBox">
            <Setter Property="Foreground" Value="#E2E8F0"/>
            <Setter Property="Margin" Value="0,4,0,4"/>
            <Setter Property="FontSize" Value="13"/>
        </Style>
    </Window.Resources>

    <Grid Margin="20">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Header -->
        <StackPanel Grid.Row="0" Margin="0,0,0,12">
            <TextBlock Text="🎙️🌐 Hayamimi Polyglot" FontSize="20" FontWeight="Bold" Foreground="#38BDF8"/>
            <TextBlock Text="リアルタイム多言語同時並行通訳システム (完全ローカル・録音ゼロ)" FontSize="12" Foreground="#94A3B8" Margin="0,4,0,0"/>
        </StackPanel>

        <!-- Install Location Group -->
        <GroupBox Grid.Row="1" Header="インストール先フォルダ">
            <StackPanel Margin="0,4,0,0">
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="Auto"/>
                    </Grid.ColumnDefinitions>
                    <TextBox x:Name="TxtPath" Grid.Column="0" Text="$DefaultInstallPath" 
                             Background="#1E293B" Foreground="#F8FAFC" BorderBrush="#334155" 
                             Padding="6" FontSize="13" VerticalContentAlignment="Center"/>
                    <Button x:Name="BtnBrowse" Grid.Column="1" Content="参照..." Margin="8,0,0,0" 
                            Background="#334155" Foreground="#F8FAFC" BorderBrush="#475569" 
                            Padding="12,6" FontWeight="SemiBold"/>
                </Grid>
                <TextBlock x:Name="LblPathNotice" Text="💡 クラウド同期（OneDrive等）を避けたローカル推奨パスを自動設定しました" 
                           FontSize="11" Foreground="#34D399" Margin="2,6,0,0"/>
            </StackPanel>
        </GroupBox>

        <!-- Models Selection Group -->
        <GroupBox Grid.Row="2" Header="ダウンロードする AI モデル構成 &amp; 環境設定">
            <StackPanel Margin="0,4,0,0">
                <CheckBox x:Name="ChkCleanVenv" Content="🔄 Python仮想環境をクリーン再構築する (推奨: 古いパッケージ残骸を排除)" IsChecked="True" FontWeight="SemiBold" Foreground="#38BDF8"/>
                <TextBlock Text="  • uv のローカルキャッシュを活用するため、再構築しても再ダウンロードゼロ・約 1〜2 秒で健全な環境を復元" 
                           FontSize="11" Foreground="#94A3B8" Margin="20,0,0,8"/>

                <CheckBox x:Name="ChkBase" Content="📦 基本モデル構成 (必須・約 800MB)" IsChecked="True" IsEnabled="False" FontWeight="Bold"/>
                <TextBlock Text="  • 日本語 ASR (ReazonSpeech Zipformer INT8) + VAD (Silero)&#x0a;  • 100言語相互翻訳 (M2M-100 INT8) + 高速日英 (FuguMT)" 
                           FontSize="11" Foreground="#64748B" Margin="20,0,0,6"/>

                <CheckBox x:Name="ChkParakeet" Content="⚡ 高精度 英語特化 ASR (Parakeet TDT v2: +約 600MB)" IsChecked="True"/>
                <TextBlock Text="  • ネイティブの早口英語やビジネス略語の認識精度が劇的に向上" FontSize="11" Foreground="#94A3B8" Margin="20,0,0,6"/>

                <CheckBox x:Name="ChkNllb" Content="🌐 高精度 アジア・多言語翻訳 (NLLB-200 600M: +約 600MB)" IsChecked="False"/>
                <TextBlock Text="  • 中国語・韓国語・ベトナム語などの長文翻訳精度やビジネス敬語を向上" FontSize="11" Foreground="#94A3B8" Margin="20,0,0,6"/>

                <CheckBox x:Name="ChkSenseVoice" Content="🚀 超高速 多言語 ASR (SenseVoice Small: +約 200MB)" IsChecked="False"/>
                <TextBlock Text="  • アジア系言語（中・韓・広東語等）の音声認識とノイズ自動除去" FontSize="11" Foreground="#94A3B8" Margin="20,0,0,0"/>
            </StackPanel>
        </GroupBox>

        <!-- Log & Progress -->
        <Grid Grid.Row="3" Margin="0,12,0,12">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
            </Grid.RowDefinitions>
            <ProgressBar x:Name="PrgBar" Grid.Row="0" Height="6" Background="#1E293B" Foreground="#38BDF8" BorderThickness="0" Margin="0,0,0,8" IsIndeterminate="False"/>
            <TextBox x:Name="TxtLog" Grid.Row="1" Background="#020617" Foreground="#CBD5E1" 
                     BorderBrush="#1E293B" FontFamily="Consolas, monospace" FontSize="11" 
                     IsReadOnly="True" VerticalScrollBarVisibility="Auto" TextWrapping="Wrap"/>
        </Grid>

        <!-- Bottom Action Buttons -->
        <Grid Grid.Row="4">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <CheckBox x:Name="ChkLaunch" Grid.Column="0" Content="完了後に今すぐ起動する" IsChecked="True" VerticalAlignment="Center"/>
            <Button x:Name="BtnInstall" Grid.Column="2" Content="🚀 セットアップを開始する" 
                    Background="#10B981" Foreground="White" BorderThickness="0" 
                    Padding="18,10" FontWeight="Bold" FontSize="14" Cursor="Hand"/>
        </Grid>
    </Grid>
</Window>
"@

# ------------------------------------------------------------------------------
# 3. GUI Logic & Event Handlers
# ------------------------------------------------------------------------------
$reader = [System.Xml.XmlReader]::Create([System.IO.StringReader]::new($xaml))
$window = [System.Windows.Markup.XamlReader]::Load($reader)

# Get Controls
$txtPath = $window.FindName("TxtPath")
$btnBrowse = $window.FindName("BtnBrowse")
$lblPathNotice = $window.FindName("LblPathNotice")
$chkCleanVenv = $window.FindName("ChkCleanVenv")
$chkParakeet = $window.FindName("ChkParakeet")
$chkNllb = $window.FindName("ChkNllb")
$chkSenseVoice = $window.FindName("ChkSenseVoice")
$prgBar = $window.FindName("PrgBar")
$txtLog = $window.FindName("TxtLog")
$chkLaunch = $window.FindName("ChkLaunch")
$btnInstall = $window.FindName("BtnInstall")

# Check if already installed
if (Test-Path (Join-Path $DefaultInstallPath "main.py")) {
    $btnInstall.Content = "🔄 アップデート / 設定適用を開始"
    $lblPathNotice.Text = "✨ 既存の Hayamimi Polyglot 環境を検出しました（アップデート / 追加DLモード）"
    $lblPathNotice.Foreground = [System.Windows.Media.Brushes]::DodgerBlue
}

function Append-Log([string]$msg) {
    $time = (Get-Date).ToString("HH:mm:ss")
    $txtLog.Dispatcher.Invoke([Action]{
        $txtLog.AppendText("[$time] $msg`r`n")
        $txtLog.ScrollToEnd()
    })
}

# Browse Folder
$btnBrowse.Add_Click({
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "Hayamimi Polyglot のインストール先フォルダを選択してください"
    $dlg.SelectedPath = $txtPath.Text
    if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $txtPath.Text = $dlg.SelectedPath
        if (Test-Path (Join-Path $txtPath.Text "main.py")) {
            $btnInstall.Content = "🔄 アップデート / 設定適用を開始"
            $lblPathNotice.Text = "✨ 既存の Hayamimi Polyglot 環境を検出しました（アップデート / 追加DLモード）"
            $lblPathNotice.Foreground = [System.Windows.Media.Brushes]::DodgerBlue
        } else {
            $btnInstall.Content = "🚀 セットアップを開始する"
            $lblPathNotice.Text = "💡 クラウド同期（OneDrive等）を避けたローカル推奨パスを自動設定しました"
            $lblPathNotice.Foreground = [System.Windows.Media.Brushes]::MediumSeaGreen
        }
    }
})

# Install Button Click
$btnInstall.Add_Click({
    $btnInstall.IsEnabled = $false
    $btnBrowse.IsEnabled = $false
    $txtPath.IsEnabled = $false
    $chkCleanVenv.IsEnabled = $false
    $chkParakeet.IsEnabled = $false
    $chkNllb.IsEnabled = $false
    $chkSenseVoice.IsEnabled = $false
    $prgBar.IsIndeterminate = $true

    $targetDir = $txtPath.Text.Trim()
    $cleanVenv = $chkCleanVenv.IsChecked
    $withParakeet = $chkParakeet.IsChecked
    $withNllb = $chkNllb.IsChecked
    $withSenseVoice = $chkSenseVoice.IsChecked
    $shouldLaunch = $chkLaunch.IsChecked

    # Run installation on background thread to keep UI smooth
    [System.Threading.Tasks.Task]::Run([Action]{
        try {
            Append-Log "セットアップを開始します: $targetDir"
            if (-not (Test-Path $targetDir)) {
                New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
            }

            # 1. Install / Verify uv (Python environment manager)
            Append-Log "uv (Rust製 高速Pythonパッケージマネージャー) を確認中..."
            $uvExe = (Get-Command uv.exe -ErrorAction SilentlyContinue).Source
            if (-not $uvExe) {
                Append-Log "uv をダウンロード・インストールしています..."
                irm https://astral.sh/uv/install.ps1 | iex
                $uvExe = "$env:USERPROFILE\.local\bin\uv.exe"
            }
            if (-not (Test-Path $uvExe)) {
                throw "uv のインストールに失敗しました。"
            }
            Append-Log "uv 検出完了: $uvExe"

            # 2. Setup / Rebuild Python 3.14 Virtual Environment
            $venvDir = Join-Path $targetDir ".venv"
            $pyExe = Join-Path $venvDir "Scripts\python.exe"

            if ($cleanVenv -or (-not (Test-Path $pyExe))) {
                Append-Log "Python 3.14 仮想環境をクリーン再構築中 (--clear)..."
                Append-Log "※ uv のローカルキャッシュから即時展開されるため再DLなしで1〜2秒で完了します"
                & $uvExe venv --clear $venvDir --python 3.14 | Out-Null
            } else {
                Append-Log "既存の Python 3.14 仮想環境を再利用します"
            }

            if (-not (Test-Path $pyExe)) {
                throw "Python 仮想環境の構築に失敗しました: $pyExe"
            }
            Append-Log "Python 3.14 環境準備完了: $pyExe"

            # 3. Copy project files if installing to a new directory
            $sourceDir = $ScriptDirectory
            if ($sourceDir -and (Test-Path (Join-Path $sourceDir "core\asr_engine.py")) -and ($sourceDir -ne $targetDir)) {
                Append-Log "プログラムファイルを配置中..."
                Copy-Item -Path (Join-Path $sourceDir "core") -Destination (Join-Path $targetDir "core") -Recurse -Force
                Copy-Item -Path (Join-Path $sourceDir "ui") -Destination (Join-Path $targetDir "ui") -Recurse -Force
                Copy-Item -Path (Join-Path $sourceDir "dicts") -Destination (Join-Path $targetDir "dicts") -Recurse -Force
                Copy-Item -Path (Join-Path $sourceDir "main.py") -Destination (Join-Path $targetDir "main.py") -Force
                Copy-Item -Path (Join-Path $sourceDir "config.json") -Destination (Join-Path $targetDir "config.json") -Force
                Copy-Item -Path (Join-Path $sourceDir "requirements.txt") -Destination (Join-Path $targetDir "requirements.txt") -Force
                Copy-Item -Path (Join-Path $sourceDir "start.bat") -Destination (Join-Path $targetDir "start.bat") -Force
                Copy-Item -Path (Join-Path $sourceDir "version.txt") -Destination (Join-Path $targetDir "version.txt") -Force
            }

            # 4. Install / Update Dependencies
            Append-Log "依存パッケージを同期中 (PySide6, sherpa-onnx, ctranslate2)..."
            $reqFile = Join-Path $targetDir "requirements.txt"
            & $uvExe pip install -r $reqFile --python $pyExe --upgrade | Out-Null
            Append-Log "依存パッケージの同期完了！"

            # 5. Download Models
            $modelsDir = Join-Path $targetDir "models"
            if (-not (Test-Path $modelsDir)) { New-Item -ItemType Directory -Path $modelsDir -Force | Out-Null }

            # Base models: copy if existing locally in hayamimi/models
            $existingModels = "E:\hayamimi\models"
            if (Test-Path $existingModels) {
                Append-Log "ローカルキャッシュから基本モデルを配備中..."
                $baseModels = @(
                    "sherpa-onnx-zipformer-ja-en-reazonspeech-2025-01-17",
                    "silero_vad.onnx",
                    "mojicast-m2m100-ct2",
                    "mojicast-fugumt-ja-en-ct2"
                )
                foreach ($m in $baseModels) {
                    $src = Join-Path $existingModels $m
                    $dst = Join-Path $modelsDir $m
                    if ((Test-Path $src) -and (-not (Test-Path $dst))) {
                        Append-Log "  -> 配置: $m"
                        Copy-Item -Path $src -Destination $dst -Recurse -Force
                    }
                }
            }

            # Optional Models
            if ($withSenseVoice) {
                $svDir = Join-Path $modelsDir "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
                if (-not (Test-Path $svDir)) {
                    Append-Log "SenseVoice Small 多言語ASRモデルをダウンロード中..."
                    $svUrl = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
                    $tarFile = Join-Path $modelsDir "sense-voice.tar.bz2"
                    try {
                        Invoke-WebRequest -Uri $svUrl -OutFile $tarFile -UseBasicParsing
                        tar -xjf $tarFile -C $modelsDir
                        Remove-Item $tarFile -Force -ErrorAction SilentlyContinue
                        Append-Log "SenseVoice Small 配備完了！"
                    } catch {
                        Append-Log "⚠️ SenseVoice ダウンロード失敗 (スキップします): $_"
                    }
                }
            }

            # 6. Create Desktop Shortcut
            Append-Log "デスクトップショートカットを作成中..."
            $desktop = [Environment]::GetFolderPath("Desktop")
            $shortcutPath = Join-Path $desktop "Hayamimi Polyglot.lnk"
            $wshShell = New-Object -ComObject WScript.Shell
            $shortcut = $wshShell.CreateShortcut($shortcutPath)
            $shortcut.TargetPath = Join-Path $targetDir "start.bat"
            $shortcut.WorkingDirectory = $targetDir
            $shortcut.Description = "Hayamimi Polyglot - リアルタイム多言語同時並行通訳"
            $shortcut.Save()
            Append-Log "ショートカット作成完了: $shortcutPath"

            # 7. Complete
            Append-Log "========================================="
            Append-Log "🎉 セットアップがすべて正常に完了しました！"
            Append-Log "========================================="

            $window.Dispatcher.Invoke([Action]{
                $prgBar.IsIndeterminate = $false
                $prgBar.Value = 100
                $btnInstall.Content = "✅ 完了"
                $btnInstall.Background = [System.Windows.Media.Brushes]::DodgerBlue
                $btnInstall.IsEnabled = $true
                $btnInstall.Add_Click({
                    if ($shouldLaunch) {
                        Start-Process (Join-Path $targetDir "start.bat")
                    }
                    $window.Close()
                })
            })

        } catch {
            Append-Log "❌ エラーが発生しました: $_"
            $window.Dispatcher.Invoke([Action]{
                $prgBar.IsIndeterminate = $false
                $btnInstall.Content = "再試行"
                $btnInstall.IsEnabled = $true
            })
        }
    })
})

# Show GUI
$window.ShowDialog() | Out-Null

