# ==============================================================================
# Hayamimi Polyglot - Setup & Updater Launcher (Windows 11)
# Zero Admin Required. Automatically launches Unified PySide6 GUI via uv.
# ==============================================================================

#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Cli,
    [switch]$Unattended,
    [string]$InstallPath = ""
)

# Set UTF-8 encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

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
        Write-Host "⬇️ uv (Rust製 高速Python環境マネージャー) をインストール中..." -ForegroundColor Cyan
        irm https://astral.sh/uv/install.ps1 | iex
        $uvExe = $localUv
    }
}

if (-not (Test-Path $uvExe)) {
    Write-Error "uv のインストールに失敗しました。"
    exit 1
}

Write-Host "✓ uv 検出完了: $uvExe" -ForegroundColor Green

# 2. Determine Script Directory & installer_gui.py
$ScriptDirectory = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}

$guiScript = Join-Path $ScriptDirectory "installer_gui.py"

# If running via Web one-liner (irm ... | iex), fetch installer_gui.py to TEMP
if (-not (Test-Path $guiScript)) {
    Write-Host "⬇️ リモートから最新の GUI インストーラーを取得中..." -ForegroundColor Cyan
    $tempDir = Join-Path $env:TEMP "hayamimi-setup"
    if (-not (Test-Path $tempDir)) { New-Item -ItemType Directory -Path $tempDir -Force | Out-Null }
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
    Write-Host "🚀 統一 GUI インストーラー (PySide6) を起動しています..." -ForegroundColor Cyan
    & $uvExe run --python 3.14 --with PySide6 python $guiScript
    exit $LASTEXITCODE
}

# ------------------------------------------------------------------------------
# 4. CLI Fallback Mode (for headless / --cli / --unattended)
# ------------------------------------------------------------------------------
Write-Host "📋 CLIモードでセットアップを継続します..." -ForegroundColor Yellow

$targetDir = if ($InstallPath) { $InstallPath } else { Join-Path [Environment]::GetFolderPath("MyDocuments") "hayamimi-polyglot" }
Write-Host "📁 インストール先: $targetDir" -ForegroundColor Cyan

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$venvDir = Join-Path $targetDir ".venv"
$pyExe = Join-Path $venvDir "Scripts\python.exe"

Write-Host "🐍 Python 3.14 仮想環境を構築中..." -ForegroundColor Cyan
& $uvExe venv --clear $venvDir --python 3.14 | Out-Null

if ($ScriptDirectory -ne $targetDir) {
    Write-Host "📋 アプリケーションファイルを配置中..." -ForegroundColor Cyan
    Copy-Item -Path (Join-Path $ScriptDirectory "core") -Destination (Join-Path $targetDir "core") -Recurse -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "ui") -Destination (Join-Path $targetDir "ui") -Recurse -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "dicts") -Destination (Join-Path $targetDir "dicts") -Recurse -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "main.py") -Destination (Join-Path $targetDir "main.py") -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "config.json") -Destination (Join-Path $targetDir "config.json") -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "requirements.txt") -Destination (Join-Path $targetDir "requirements.txt") -Force
    Copy-Item -Path (Join-Path $ScriptDirectory ".python-version") -Destination (Join-Path $targetDir ".python-version") -Force -ErrorAction SilentlyContinue
    Copy-Item -Path (Join-Path $ScriptDirectory "installer_gui.py") -Destination (Join-Path $targetDir "installer_gui.py") -Force -ErrorAction SilentlyContinue
    Copy-Item -Path (Join-Path $ScriptDirectory "start.bat") -Destination (Join-Path $targetDir "start.bat") -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "version.txt") -Destination (Join-Path $targetDir "version.txt") -Force
}

Write-Host "📦 依存パッケージを同期中..." -ForegroundColor Cyan
& $uvExe pip install -r (Join-Path $targetDir "requirements.txt") --python $pyExe --upgrade | Out-Null

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "🎉 セットアップが正常に完了しました！" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
