# Advanced Outboxer Studio

Turns websites **and whole HTML/CSS/JS project folders** into Windows desktop apps. Developed by Sayed Alsharif.

**[⬇ Download the latest version](https://github.com/Alsharifs/Advanced-Outboxer-Studio/releases/latest)**: portable, nothing to install, Windows 10/11 64-bit.

## What it does

- **Website (URL):** a website becomes a desktop app, on Nativefier 53 / Electron, a shared Electron runtime or WebView2. Local-server web apps are supported too: the server starts and stops with the app.
- **Project folder:** your own pages become a Windows app on Electron, with the **desktop toolbox** (`window.desktop`). It covers hotkeys and hotstrings, sending keys, mouse, other programs' windows, files, clipboard, programs, tray, dialogs, screen capture and OCR, power, system, audio, registry, network, storage, SQLite and printing, plus `desktop.exec`, `desktop.powershell`, `desktop.win32` and your own Node.js code.
- **Electron app folder:** a finished Electron app (a `package.json` with `"main"`) is packaged as it is. No npm is needed on the PC.

## Getting started

1. Download `Advanced-Outboxer-Studio-v4.0-win64.zip` (about 405 MB) from the [latest release](https://github.com/Alsharifs/Advanced-Outboxer-Studio/releases/latest).
2. Extract it to a folder (for example `C:\Tools\Advanced Outboxer Studio`). Don't run it from inside the zip.
3. Double-click **Advanced_Outboxer_Studio.bat**.

**Have Node.js?** Run `npx @alsharif/outboxer-studio` instead. It downloads the release, checks its checksum and starts Studio.

Everything Studio needs comes in the download and works offline. **Engines** gives you newer Node.js and Electron versions when you want them:

| Included in `Engines\` | Version |
| --- | --- |
| Python (runs Studio) with PySide6 and Pillow | 3.14.8 |
| Node.js | 26.12.0 |
| Nativefier | 53.0.0 |
| Electron (for building apps) | 44.9.1 |
| Shared Electron runtime | 44.7.2 |
| WebView2 SDK | 1.0.4258.31 |

## Good to know

- Each project keeps its own settings in `outboxer.json` inside the project folder. Studio's own settings are in `AdvancedOutboxerStudio.config.json`.
- Studio goes online to check for newer Node.js and Electron versions when it starts (you can turn that off with `auto_check_updates` in the settings file). It also goes online when you download engines and when you build an app from a website.
- Windows SmartScreen may warn about apps you build, because they aren't code-signed.

## Checking your download

Each release includes a `.sha256` file. In PowerShell:

```powershell
Get-FileHash .\Advanced-Outboxer-Studio-v4.0-win64.zip -Algorithm SHA256
```

The result should match the hash in the `.sha256` file.

---

The download includes third-party software under its own licenses (Python, Node.js, Electron, Nativefier, Qt/PySide6, Pillow, WebView2 SDK). Their license files are inside the `Engines` folder.
