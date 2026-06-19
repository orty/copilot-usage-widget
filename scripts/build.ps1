<#
.SYNOPSIS
    Build CopilotUsage-Setup.exe from source.
.PREREQUISITES
    Python 3.11+, PyInstaller, Inno Setup 6+ (iscc in PATH)
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

Write-Host "==> Installing Python dependencies..."
pip install -r "$Root\requirements.txt" --quiet

Write-Host "==> Running PyInstaller..."
pyinstaller --noconfirm `
    --onefile `
    --windowed `
    --name "CopilotUsage" `
    --icon "$Root\assets\icon.ico" `
    --add-binary "C:\Windows\System32\curl.exe;." `
    --distpath "$Root\dist" `
    --workpath "$Root\build" `
    "$Root\src\widget.pyw"

Write-Host "==> Running Inno Setup..."
iscc "$Root\installer\setup.iss"

Write-Host "==> Done. Installer at $Root\releases\CopilotUsage-Setup.exe"
