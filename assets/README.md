# Assets

This directory contains build assets for the Windows installer.

## Required Files

### icon.ico

**Status:** Must be provided before building.

A 32×32 pixel `.ico` file must be placed in this directory as `icon.ico` before running the build pipeline (`scripts/build.ps1`). The build will fail without it.

The icon should represent the Copilot Usage widget application. You can create one using:
- An online ICO converter (e.g., convertio.co)
- ImageMagick: `magick -size 32x32 xc:blue icon.ico`
- PyQt5's built-in icon tools
- Professional icon design tools (Adobe Illustrator, Figma)

Example placeholder generation (requires ImageMagick):
```powershell
magick -size 32x32 xc:blue -fill white -pointsize 16 -gravity center -annotate +0+0 "C" icon.ico
```

## Build Process

The `build.ps1` script references `assets/icon.ico`. If the file is missing, either:
1. Provide a valid `.ico` file (recommended)
2. Temporarily remove the `--icon` flag from `build.ps1`
