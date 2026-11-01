# ==============================================================================
# Hayamimi Polyglot - Setup & Updater Launcher (Windows 11)
# Non-Admin Setup. Launches Unified PySide6 GUI via uv.
# ==============================================================================

#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Cli,
    [switch]$Unattended,
    [switch]$WithParakeet,
    [switch]$WithSenseVoice,
    [string]$InstallPath = ""
)

# Set UTF-8 encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Enterprise Proxy / SSL Inspection compatibility
if (-not $env:UV_SYSTEM_CERTS) { $env:UV_SYSTEM_CERTS = "true" }
if (-not $env:PIP_USE_FEATURE) { $env:PIP_USE_FEATURE = "truststore" }

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  🎙️🌐 Hayamimi Polyglot - Setup & Updater (Windows)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Verify / Install uv
$uvExe = (Get-Command uv.exe -ErrorAction SilentlyContinue).Source
if (-not $uvExe) {
    $localUv = "$env:USERPROFILE\.local\bin\uv.exe"
    if (Test-Path $localUv) {
        $uvExe = $localUv
    } else {
        Write-Host "⬇️ uv (Python環境マネージャー) をインストール中..." -ForegroundColor Cyan
        irm https://astral.sh/uv/install.ps1 | iex
        $uvExe = $localUv
    }
}

if (-not (Test-Path $uvExe)) {
    Write-Error "uv のインストールに失敗しました。"
    exit 1
}

Write-Host "✓ uv 検出完了: $uvExe" -ForegroundColor Green

# 2. Determine Script Directory & installer_gui.py safely (avoid untrusted CWD when piped)
$ScriptDirectory = $null
if ($PSScriptRoot) {
    $ScriptDirectory = $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    $ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$guiScript = if ($ScriptDirectory) { Join-Path $ScriptDirectory "installer_gui.py" } else { "" }

# If running via Web one-liner (irm ... | iex), fetch installer_gui.py to isolated TEMP dir
if (-not $guiScript -or -not (Test-Path $guiScript)) {
    Write-Host "⬇️ リモートから最新の GUI インストーラーを取得中..." -ForegroundColor Cyan
    $randSuffix = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    $tempDir = Join-Path $env:TEMP "hayamimi-setup-$randSuffix"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $ScriptDirectory = $tempDir
    $guiScript = Join-Path $tempDir "installer_gui.py"
    $remoteGuiUrl = if ($env:HAYAMIMI_GUI_URL) { $env:HAYAMIMI_GUI_URL } else { "https://raw.githubusercontent.com/Maximilian2022/hayamimi-polyglot/main/installer_gui.py" }
    try {
        Invoke-WebRequest -Uri $remoteGuiUrl -OutFile $guiScript -UseBasicParsing
    } catch {
        Write-Warning "GUI インストーラーのリモート取得に失敗しました: $_"
    }
}

# 3. Launch Unified PySide6 GUI Installer
if (-not $Cli -and -not $Unattended -and (Test-Path $guiScript)) {
    Write-Host "🚀 GUI インストーラー (PySide6) を起動しています..." -ForegroundColor Cyan
    & $uvExe run --python 3.14 --with PySide6 python $guiScript
    exit $LASTEXITCODE
}

# ------------------------------------------------------------------------------
# 4. CLI Fallback Mode (for headless / --cli / --unattended)
# ------------------------------------------------------------------------------
Write-Host "📋 CLIモードでセットアップを継続します..." -ForegroundColor Yellow

$docsDir = [Environment]::GetFolderPath("MyDocuments")
$isCloud = $false
if ($env:OneDrive -and $docsDir.ToLower().StartsWith($env:OneDrive.ToLower())) {
    $isCloud = $true
} elseif ($docsDir -match "(?i)(onedrive|google drive|dropbox|icloud)") {
    $isCloud = $true
}

$defaultTarget = if ($isCloud) {
    Join-Path $env:USERPROFILE "hayamimi-polyglot"
} else {
    Join-Path $docsDir "hayamimi-polyglot"
}

$targetDir = if ($InstallPath) { $InstallPath } else { $defaultTarget }
Write-Host "📁 インストール先: $targetDir" -ForegroundColor Cyan

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$venvDir = Join-Path $targetDir ".venv"
$pyExe = Join-Path $venvDir "Scripts\python.exe"

Write-Host "🐍 Python 3.14 仮想環境を構築中..." -ForegroundColor Cyan
& $uvExe venv --clear $venvDir --python 3.14 | Out-Null

if ($ScriptDirectory -and ($ScriptDirectory -ne $targetDir) -and (Test-Path (Join-Path $ScriptDirectory "main.py"))) {
    Write-Host "📋 アプリケーションファイルを配置中..." -ForegroundColor Cyan
    Copy-Item -Path (Join-Path $ScriptDirectory "core") -Destination (Join-Path $targetDir "core") -Recurse -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "ui") -Destination (Join-Path $targetDir "ui") -Recurse -Force
    if (Test-Path (Join-Path $ScriptDirectory "scripts")) {
        Copy-Item -Path (Join-Path $ScriptDirectory "scripts") -Destination (Join-Path $targetDir "scripts") -Recurse -Force
    }
    Copy-Item -Path (Join-Path $ScriptDirectory "dicts") -Destination (Join-Path $targetDir "dicts") -Recurse -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "main.py") -Destination (Join-Path $targetDir "main.py") -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "config.default.json") -Destination (Join-Path $targetDir "config.default.json") -Force -ErrorAction SilentlyContinue
    $targetConfig = Join-Path $targetDir "config.json"
    if (-not (Test-Path $targetConfig)) {
        $srcConfig = Join-Path $ScriptDirectory "config.json"
        if (Test-Path $srcConfig) {
            Copy-Item -Path $srcConfig -Destination $targetConfig -Force
        } else {
            Copy-Item -Path (Join-Path $ScriptDirectory "config.default.json") -Destination $targetConfig -Force -ErrorAction SilentlyContinue
        }
    }
    Copy-Item -Path (Join-Path $ScriptDirectory "requirements.txt") -Destination (Join-Path $targetDir "requirements.txt") -Force
    Copy-Item -Path (Join-Path $ScriptDirectory ".python-version") -Destination (Join-Path $targetDir ".python-version") -Force -ErrorAction SilentlyContinue
    Copy-Item -Path (Join-Path $ScriptDirectory "installer_gui.py") -Destination (Join-Path $targetDir "installer_gui.py") -Force -ErrorAction SilentlyContinue
    Copy-Item -Path (Join-Path $ScriptDirectory "test_polyglot_suite.py") -Destination (Join-Path $targetDir "test_polyglot_suite.py") -Force -ErrorAction SilentlyContinue
    Copy-Item -Path (Join-Path $ScriptDirectory "start.bat") -Destination (Join-Path $targetDir "start.bat") -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "version.txt") -Destination (Join-Path $targetDir "version.txt") -Force
}

Write-Host "📦 依存パッケージを同期中..." -ForegroundColor Cyan
& $uvExe pip install -r (Join-Path $targetDir "requirements.txt") --python $pyExe --upgrade | Out-Null

# Ensure AI Models via download_models.py
$dlScript = Join-Path $targetDir "scripts\download_models.py"
if (Test-Path $dlScript) {
    Write-Host "⬇️ 必須 AI モデルを確認・取得中..." -ForegroundColor Cyan
    & $pyExe $dlScript --models-dir (Join-Path $targetDir "models")
}

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "🎉 セットアップが正常に完了しました。" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
