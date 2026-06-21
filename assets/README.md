# Assets

Icons and images for the Electron app, consumed by `electron-builder` (see the `build`
field in `package.json`) and the renderer.

| File | Used for |
| --- | --- |
| `icon.ico` | Windows app icon (NSIS + portable) |
| `icon.png` | macOS icon master (1024×1024; electron-builder converts to `.icns`) |
| `logo.png` | Linux app icon + in‑app logo |
| `copilot-logo.svg` | Title‑bar logo in the renderer |
| `tray-icon.png` | Windows tray base image |
| `tray-icon-mac.png` | macOS tray base image (template‑style) |
| `tray-icon-linux.png` | Linux tray base image |

The live usage percentage is drawn onto the tray icons at runtime (see
`src/tray-icon.js`), so the tray base images are just the unbadged starting point.

These were generated with Pillow; regenerate them with a similar script if you re‑brand.
