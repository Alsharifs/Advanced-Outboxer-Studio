# Advanced Outboxer Studio v4.0.1

Turns websites **and whole HTML/CSS/JS project folders** into Windows desktop apps.
Developed by Sayed Alsharif.

**[⬇ Download the ready-to-run version](https://github.com/Alsharifs/Advanced-Outboxer-Studio/releases/latest)** (portable, everything included, Windows 10/11 64-bit) or run `npx @alsharif/outboxer-studio` · **[📖 Full guide](docs/GUIDE.md)** · **[Toolbox command reference](docs/TOOLBOX-API.md)**

![Advanced Outboxer Studio building GitHub as a desktop app](docs/images/website-app.png)

* **Website (URL)** — everything Outboxer Studio v1.0 does, unchanged (Nativefier 53 / Electron, shared runtime, WebView2, local-server apps).
* **Project folder** — your own pages become a Windows app on Electron, with the **desktop toolbox** (`window.desktop`):
  hotkeys and hotstrings, sending keys, mouse, other programs' windows, files, clipboard, programs, tray, dialogs,
  screen capture and OCR, power, system, audio, registry, network, store, SQLite, printing, plus the master keys
  `desktop.exec`, `desktop.powershell`, `desktop.win32` and your own Node.js code in the project's `desktop` folder.
* **Electron app folder** — a finished Electron app (`package.json` with `"main"`, e.g. MasterKey-Electron) is packaged
  as it is, running its own main script. Its packages come from its `node_modules` or from Studio (koffi), so no npm
  is needed on the PC; electron-builder's icon, extraResources and extraFiles are honoured. Test Run works too.

## Screenshots

| Project folder: checked and ready to build | A project app using the desktop toolbox |
| --- | --- |
| ![Project folder mode](docs/images/project-project.png) | ![The Toolbox Demo app](docs/images/toolbox-demo.png) |
| **The Engines window** | **The built-in toolbox guide** |
| ![Engines window](docs/images/engines.png) | ![Desktop toolbox guide](docs/images/toolbox-guide.png) |

The **[full guide](docs/GUIDE.md)** walks through every option with more screenshots: app engines, website options, local-server apps, project folders, Electron app folders, React/Vue/Vite builds, the desktop toolbox, the Engines window, sharing apps and troubleshooting.

## Start

Double-click **Advanced_Outboxer_Studio.bat** (needs Python with PySide6 and Pillow: `python -m pip install PySide6 Pillow`).
On the first start, if Outboxer Studio v1.0 sits next to this folder, Studio offers to copy or share its Engines.

## Folder

| Path | What it is |
|---|---|
| `advanced_outboxer_studio.py` | The Studio: v1.0's source with the project mode wired in |
| `project_ui.py` | Project mode in the window: Source switch, options, Test Run, Check tab, templates, guide |
| `project_core.py` | Project mode logic (no UI): scan/check, settings, build bundled/shared, Electron app folders, templates, guide |
| `host\` | The app host copied into every project app (`main.js`, `preload.js`, `lib\`, `toolbox\`, `node_modules\koffi`) |
| `host\toolbox\*.js` | One file per `desktop.*` area — add a method there and it appears in pages, the guide and `desktop.d.ts` |
| `templates\` | Starting points for **File → New project from template** (each folder + `template.json`) |
| `examples\Toolbox Demo\` | Tries every toolbox area (**Help → Open the toolbox example project**) |
| `docs\toolbox-intro.html` | First part of the toolbox guide (the command list is read from `host\toolbox`) |
| `Engines\` | Node.js, Nativefier, Electron zips, shared runtimes, WebView2 SDK (created/filled by Studio) |
| `AdvancedOutboxerStudio.config.json` | Engine paths and the default Electron version |

Each project keeps its own settings in `outboxer.json` inside the project folder.

## Updating the toolbox

Toolbox modules return `const self = { … }`: a method with a `/** doc comment */` above it is documented automatically.
Inside a method, `this` is the calling page (`this.win`, `this.onDispose(fn)`), so call sibling methods through `self`.
