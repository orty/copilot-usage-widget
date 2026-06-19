<#
.SYNOPSIS
    Build CopilotUsage-Setup.exe from source.
.DESCRIPTION
    Reads APP_VERSION from src/widget.pyw, patches installer/setup.iss,
    runs PyInstaller (onedir) then Inno Setup.
.PREREQUISITES
    Python 3.11+, PyInstaller, Inno Setup 6+
#>
param(
    [string]$Version = ""   # Override version (default: read from widget.pyw)
)
$ErrorActionPreference = "Stop"
$Root      = Split-Path $PSScriptRoot -Parent
$Src       = Join-Path $Root "src"
$Assets    = Join-Path $Root "assets"
$Installer = Join-Path $Root "installer"
$Build     = Join-Path $Root "build"
$Dist      = Join-Path $Build "dist"
$Work      = Join-Path $Build "pyi-work"
$Releases  = Join-Path $Root "releases"

# ── 0. Resolve version ────────────────────────────────────────────────────────
if (-not $Version) {
    $Version = python -c "
import re, sys
m = re.search(r'APP_VERSION\s*=\s*[''\"]([\d.]+)[''\""]', open('$Src/widget.pyw').read())
print(m.group(1) if m else '0.0.0')
"
}
Write-Host "[0/5] Version: $Version"

# ── 1. Kill any running instance ──────────────────────────────────────────────
Write-Host "[1/5] Stopping running widget..."
Get-Process -Name "CopilotUsage" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# ── 2. Install Python dependencies ────────────────────────────────────────────
Write-Host "[2/5] Installing Python dependencies..."
pip install -r "$Root\requirements.txt" --quiet

# ── 3. PyInstaller onedir build ───────────────────────────────────────────────
Write-Host "[3/5] Running PyInstaller (onedir)..."
New-Item -ItemType Directory -Force -Path $Build, $Releases | Out-Null

$PyiArgs = @(
    "--noconfirm", "--clean", "--windowed",
    "--name", "CopilotUsage",
    "--icon", "$Assets\icon.ico",
    "--exclude-module", "numpy",
    "--distpath", $Dist,
    "--workpath", $Work,
    "--specpath", $Build,
    "$Src\widget.pyw"
)
python -m PyInstaller @PyiArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# ── 4. Inject version into setup.iss and run Inno Setup ───────────────────────
Write-Host "[4/5] Patching setup.iss and running Inno Setup..."
$IssPath = Join-Path $Installer "setup.iss"
(Get-Content $IssPath) -replace '#define MyAppVersion ".*"', "#define MyAppVersion `"$Version`"" |
    Set-Content $IssPath

$Iscc = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "ISCC.exe not found. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php" }
& $Iscc $IssPath
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

# ── 5. Report ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[5/5] Done. Artifacts in $Releases :"
Get-ChildItem $Releases | ForEach-Object {
    Write-Host "  $($_.Name)  ($([math]::Round($_.Length / 1MB, 2)) MB)"
}
