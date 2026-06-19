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

# Generate placeholder icon if missing
$IconPath = "$Root\assets\icon.ico"
if (-not (Test-Path $IconPath)) {
    Write-Host "==> Generating placeholder icon.ico..."
    python -c @"
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), (30, 30, 30, 255))
draw = ImageDraw.Draw(img)
draw.ellipse([20, 20, 236, 236], fill=(9, 105, 218, 255))
draw.ellipse([80, 80, 176, 176], fill=(30, 30, 30, 255))
img.save(r'$IconPath', format='ICO', sizes=[(16,16),(32,32),(256,256)])
print('Generated placeholder icon.ico — replace with final artwork before release.')
"@
}

Write-Host "==> Running PyInstaller..."
pyinstaller --noconfirm `
    --onefile `
    --windowed `
    --name "CopilotUsage" `
    --icon "$IconPath" `
    --add-binary "C:\Windows\System32\curl.exe;." `
    --distpath "$Root\dist" `
    --workpath "$Root\build" `
    "$Root\src\widget.pyw"

Write-Host "==> Running Inno Setup..."
iscc "$Root\installer\setup.iss"

Write-Host "==> Done. Installer at $Root\releases\CopilotUsage-Setup.exe"
