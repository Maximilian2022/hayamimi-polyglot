[CmdletBinding()]
param(
    [switch]$Cli,
    [switch]$Unattended,
    [switch]$WithParakeet,
    [switch]$WithSenseVoice,
    [switch]$WithNpu,
    [string]$InstallPath = ""
)

# ==============================================================================
# Hayamimi Polyglot - Setup & Updater Launcher (Windows 11)
# Non-Admin Setup. Launches Unified PySide6 GUI via uv.
# ==============================================================================

#Requires -Version 5.1

# Set UTF-8 encoding
# Pure 7-bit ASCII source for Windows PowerShell 5.1 & 7 compatibility:
# Avoids both UTF-8 BOM errors in `irm ... | iex` and CP932 syntax corruption in local `.\setup.ps1`.
function Invoke-DecodeMsg([string]$Escaped) {
    return [regex]::Unescape($Escaped)
}

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Enterprise Proxy / SSL Inspection compatibility
if (-not $env:UV_SYSTEM_CERTS) { $env:UV_SYSTEM_CERTS = "true" }
if (-not $env:PIP_USE_FEATURE) { $env:PIP_USE_FEATURE = "truststore" }

Write-Host "=======================================================" -ForegroundColor Cyan
# Banner: Hayamimi Polyglot - Setup & Updater (Windows)
Write-Host (Invoke-DecodeMsg '  \ud83c\udf99\ufe0f\ud83c\udf10 Hayamimi Polyglot - Setup & Updater (Windows)') -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Verify / Install uv
$uvExe = (Get-Command uv.exe -ErrorAction SilentlyContinue).Source
if (-not $uvExe) {
    $localUv = "$env:USERPROFILE\.local\bin\uv.exe"
    if (Test-Path $localUv) {
        $uvExe = $localUv
    } else {
        # Installing uv (Python environment manager)...
        Write-Host (Invoke-DecodeMsg '\u2b07\ufe0f uv (Python\u74b0\u5883\u30de\u30cd\u30fc\u30b8\u30e3\u30fc) \u3092\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u4e2d...') -ForegroundColor Cyan
        irm https://astral.sh/uv/install.ps1 | iex
        $uvExe = $localUv
    }
}

if (-not (Test-Path $uvExe)) {
    # Failed to install uv.
    Write-Error (Invoke-DecodeMsg 'uv \u306e\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u306b\u5931\u6557\u3057\u307e\u3057\u305f\u3002')
    exit 1
}

# uv detected
Write-Host "$(Invoke-DecodeMsg '\u2713 uv \u691c\u51fa\u5b8c\u4e86: ')$uvExe" -ForegroundColor Green

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
    # Fetching latest GUI installer from remote...
    Write-Host (Invoke-DecodeMsg '\u2b07\ufe0f \u30ea\u30e2\u30fc\u30c8\u304b\u3089\u6700\u65b0\u306e GUI \u30a4\u30f3\u30b9\u30c8\u30fc\u30e9\u30fc\u3092\u53d6\u5f97\u4e2d...') -ForegroundColor Cyan
    $randSuffix = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    $tempDir = Join-Path $env:TEMP "hayamimi-setup-$randSuffix"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $ScriptDirectory = $tempDir
    $guiScript = Join-Path $tempDir "installer_gui.py"
    $remoteGuiUrl = if ($env:HAYAMIMI_GUI_URL) { $env:HAYAMIMI_GUI_URL } else { "https://raw.githubusercontent.com/Maximilian2022/hayamimi-polyglot/main/installer_gui.py" }
    try {
        Invoke-WebRequest -Uri $remoteGuiUrl -OutFile $guiScript -UseBasicParsing
    } catch {
        # Failed to fetch GUI installer from remote
        Write-Warning "$(Invoke-DecodeMsg 'GUI \u30a4\u30f3\u30b9\u30c8\u30fc\u30e9\u30fc\u306e\u30ea\u30e2\u30fc\u30c8\u53d6\u5f97\u306b\u5931\u6557\u3057\u307e\u3057\u305f: ')$_"
    }
}

# 3. Launch Unified PySide6 GUI Installer
if (-not $Cli -and -not $Unattended -and (Test-Path $guiScript)) {
    # Launching GUI installer (PySide6)...
    Write-Host (Invoke-DecodeMsg '\ud83d\ude80 GUI \u30a4\u30f3\u30b9\u30c8\u30fc\u30e9\u30fc (PySide6) \u3092\u8d77\u52d5\u3057\u3066\u3044\u307e\u3059...') -ForegroundColor Cyan
    & $uvExe run --python 3.14 --with PySide6 python $guiScript
    exit $LASTEXITCODE
}

# ------------------------------------------------------------------------------
# 4. CLI Fallback Mode (for headless / --cli / --unattended)
# ------------------------------------------------------------------------------
# Continuing setup in CLI mode...
Write-Host (Invoke-DecodeMsg '\ud83d\udccb CLI\u30e2\u30fc\u30c9\u3067\u30bb\u30c3\u30c8\u30a2\u30c3\u30d7\u3092\u7d99\u7d9a\u3057\u307e\u3059...') -ForegroundColor Yellow

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
# Install destination
Write-Host "$(Invoke-DecodeMsg '\ud83d\udcc1 \u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u5148: ')$targetDir" -ForegroundColor Cyan

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$venvDir = Join-Path $targetDir ".venv"
$pyExe = Join-Path $venvDir "Scripts\python.exe"

# Creating Python 3.14 virtual environment...
Write-Host (Invoke-DecodeMsg '\ud83d\udc0d Python 3.14 \u4eee\u60f3\u74b0\u5883\u3092\u69cb\u7bc9\u4e2d...') -ForegroundColor Cyan
& $uvExe venv --clear $venvDir --python 3.14 | Out-Null

if ($ScriptDirectory -and ($ScriptDirectory -ne $targetDir) -and (Test-Path (Join-Path $ScriptDirectory "main.py"))) {
    # Deploying application files...
    Write-Host (Invoke-DecodeMsg '\ud83d\udccb \u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u30d5\u30a1\u30a4\u30eb\u3092\u914d\u7f6e\u4e2d...') -ForegroundColor Cyan
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
    Copy-Item -Path (Join-Path $ScriptDirectory "test_npu_suite.py") -Destination (Join-Path $targetDir "test_npu_suite.py") -Force -ErrorAction SilentlyContinue
    if (Test-Path (Join-Path $ScriptDirectory "tests_data")) {
        Copy-Item -Path (Join-Path $ScriptDirectory "tests_data") -Destination (Join-Path $targetDir "tests_data") -Recurse -Force
    }
    Copy-Item -Path (Join-Path $ScriptDirectory "start.bat") -Destination (Join-Path $targetDir "start.bat") -Force
    Copy-Item -Path (Join-Path $ScriptDirectory "version.txt") -Destination (Join-Path $targetDir "version.txt") -Force
} elseif (-not (Test-Path (Join-Path $targetDir "main.py"))) {
    # Downloading application source from GitHub...
    Write-Host (Invoke-DecodeMsg '\ud83c\udf10 GitHub \u304b\u3089\u30d7\u30ed\u30b0\u30e9\u30e0\u30d5\u30a1\u30a4\u30eb\u3092\u53d6\u5f97\u4e2d...') -ForegroundColor Cyan
    $repoZipUrl = if ($env:HAYAMIMI_REPO_ZIP) { $env:HAYAMIMI_REPO_ZIP } else { "https://github.com/Maximilian2022/hayamimi-polyglot/archive/refs/heads/main.zip" }
    $zipPath = Join-Path $targetDir "repo_download.zip"
    $extractTemp = Join-Path $targetDir "_temp_extract"
    Invoke-WebRequest -Uri $repoZipUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $extractTemp -Force
    $extractedRoot = Get-ChildItem -Path $extractTemp -Directory | Select-Object -First 1
    if ($extractedRoot) {
        Get-ChildItem -Path $extractedRoot.FullName -Force | ForEach-Object {
            if ($_.Name -notin @("config.json", "models", ".venv")) {
                $dstItem = Join-Path $targetDir $_.Name
                if (Test-Path $dstItem) { Remove-Item $dstItem -Recurse -Force }
                Move-Item -Path $_.FullName -Destination $dstItem -Force
            }
        }
    }
    Remove-Item $extractTemp -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    $targetConfig = Join-Path $targetDir "config.json"
    if (-not (Test-Path $targetConfig) -and (Test-Path (Join-Path $targetDir "config.default.json"))) {
        Copy-Item -Path (Join-Path $targetDir "config.default.json") -Destination $targetConfig -Force
    }
}

# Synchronizing Python dependencies...
Write-Host (Invoke-DecodeMsg '\ud83d\udce6 \u4f9d\u5b58\u30d1\u30c3\u30b1\u30fc\u30b8\u3092\u540c\u671f\u4e2d...') -ForegroundColor Cyan
& $uvExe pip install -r (Join-Path $targetDir "requirements.txt") --python $pyExe --upgrade | Out-Null

# Ensure AI Models via download_models.py
$dlScript = Join-Path $targetDir "scripts\download_models.py"
if (Test-Path $dlScript) {
    # Verifying / downloading required AI models...
    Write-Host (Invoke-DecodeMsg '\u2b07\ufe0f \u5fc5\u9808 AI \u30e2\u30c7\u30eb\u3092\u78ba\u8a8d\u30fb\u53d6\u5f97\u4e2d...') -ForegroundColor Cyan
    & $pyExe $dlScript --models-dir (Join-Path $targetDir "models")
}

# Optional: Intel NPU add-on (ZIPs are dropped into addons\ and extracted by the app on its next start)
if ($WithNpu) {
    $npuScript = Join-Path $targetDir "scripts\fetch_npu_addon.py"
    if (Test-Path $npuScript) {
        # Fetching optional Intel NPU add-on...
        Write-Host (Invoke-DecodeMsg '\u2b07\ufe0f NPU \u30a2\u30c9\u30aa\u30f3\u3092\u53d6\u5f97\u4e2d\uff08\u521d\u56de\u306e\u307f\u30fb\u7d04 1.8GB\uff09...') -ForegroundColor Cyan
        & $pyExe $npuScript
    }
}

Write-Host "=======================================================" -ForegroundColor Cyan
# Setup completed successfully.
Write-Host (Invoke-DecodeMsg '\ud83c\udf89 \u30bb\u30c3\u30c8\u30a2\u30c3\u30d7\u304c\u6b63\u5e38\u306b\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002') -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
