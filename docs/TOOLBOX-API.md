# Desktop toolbox: command reference

Every `desktop.*` command available to the pages of a project app, generated from the toolbox source (`host\toolbox`). See the [guide](GUIDE.md#11-the-desktop-toolbox-windowdesktop) for how to use them. All commands return a Promise.

_Toolbox 1.0.0: 14 top-level commands and 280 in 19 areas._

### Top level

| Command | What it does |
| --- | --- |
| `desktop.exec(command, args, opts)` | Run a command line: exec('dir C:\\', {cwd, timeout, env, onOutput: fn(text, stream)}) or a program with arguments: exec('git', ['status'], {cwd}). -> {code, stdout, stderr} |
| `desktop.powershell(script, opts = {})` | PowerShell script -> {code, stdout, stderr}; {json: true} also gives `value` (the result as data). |
| `desktop.win32(dll, prototype, ...args)` | Call a function in any Windows DLL with a C prototype (koffi syntax): win32('user32.dll', 'int MessageBoxW(void *hwnd, str16 text, str16 title, uint type)', null, 'Hi', 'Title', 0) Types: int, uint, int64, double, bool, str (UTF-8), str16 (UTF-16), void *, intptr… Prototypes with _Out_/_Inout_ parameters return {result, args} so you can read them back. |
| `desktop.node(code, ...args)` | Run JavaScript in the app's back end (Node.js, full access). The code is the body of an async function with: require, desktop (the toolbox), electron, args (the extra arguments). await desktop.node('const fs = require("fs"); return fs.readdirSync(args[0])', 'C:\\') |
| `desktop.call(name, ...args)` | Call a function from the project's desktop folder: call('mail.send', to, subject). |
| `desktop.modules()` | Names of all functions in the desktop folder. |
| `desktop.emit(event, data)` | Send an event to every window of the app (and desktop-folder modules): they get it with desktop.on(event, fn). |
| `desktop.log(...parts)` | Write to the app's log file (logs\\app.log in the data folder) and the developer console. |
| `desktop.status()` | Is the toolbox fully working here (Windows, native bindings loaded)? |
| `desktop.sleep(ms)` | Wait ms milliseconds (await desktop.sleep(500)). |
| `desktop.notify(title, body = '', opts = {})` | notify('Title', 'Body', {icon, silent, urgency, timeout: 'never', actions: ['Open', 'Later'], onClick: fn, onAction: fn(index), onClose: fn, reply: true, onReply: fn(text)}) |
| `desktop.on(event, fn)` | Listen to app events: 'power', 'theme', 'store', 'second-instance', 'displays', 'suspend', 'hidden-to-tray' and your own desktop.emit() events ('*' = all). Returns a function that stops listening. |
| `desktop.once(event, fn)` | Like on(), for the next event only. |
| `desktop.off(event, fn)` | Stop listening. |

### desktop.keys — Keyboard: send keys, type, hotkeys, hotstrings, remaps

desktop.keys — send keys, type text, and catch keys anywhere in Windows: hotkeys (any combination, prefix keys like 'CapsLock+J', mouse buttons), hotstrings, remaps, blocking keys and a raw key listener. Registrations belong to the page that made them and are removed automatically when that page reloads or closes.

| Command | What it does |
| --- | --- |
| `desktop.keys.send(keys, opts = {})` | Send keys in AutoHotkey style: 'Hello{Enter}', '^v', '{Ctrl down}a{Ctrl up}', '{Tab 3}'. |
| `desktop.keys.type(text, opts = {})` | Type text exactly as written (any language, emoji). opts.delay = ms between characters. |
| `desktop.keys.press(combo, opts = {})` | Press a combination: 'Ctrl+Shift+Esc', 'Win+D', 'Alt+Tab', '^c'. opts: {count, holdMs} |
| `desktop.keys.down(keyName)` |  |
| `desktop.keys.up(keyName)` |  |
| `desktop.keys.backspace(n = 1)` |  |
| `desktop.keys.hotkey(combo, fn, opts = {})` | Run fn when a key combination is pressed anywhere in Windows. The key is swallowed (the active program does not get it) unless opts.pass is true or the text starts with '~'. fn may also be a send string: hotkey('Ctrl+Alt+M', '{Text}my@email.com'). Returns the hotkey id. Pass fn = null to just block the key. |
| `desktop.keys.unhotkey(comboOrId)` | Remove a hotkey by its text or by the id hotkey() returned. |
| `desktop.keys.block(keyName)` | Swallow a key everywhere (e.g. block('Win') stops the Start menu, block('Insert')). |
| `desktop.keys.unblock(keyName)` |  |
| `desktop.keys.hotstring(abbreviation, replacement, opts = {})` | Text expansion: type the abbreviation followed by space/enter/punctuation and it is replaced. replacement: text, or a function(info) that runs instead. opts: immediate (no ending key needed), inWord (also inside words), caseSensitive, omitEnd (do not type the ending key), keep (do not erase what was typed), raw: false (treat replacement as a send string with {Enter} etc.) |
| `desktop.keys.unhotstring(abbrOrId)` |  |
| `desktop.keys.remap(fromKey, toKey)` | Make one key act as another everywhere: remap('CapsLock', 'Ctrl'), remap('F1', 'Esc'). |
| `desktop.keys.unremap(fromKey)` |  |
| `desktop.keys.listen(fn)` | Get every key press and release anywhere: fn({key, vk, down}). Returns an id for unlisten(). |
| `desktop.keys.unlisten(id)` |  |
| `desktop.keys.list()` | Everything this app has registered, for showing in its own UI. |
| `desktop.keys.clear()` |  |
| `desktop.keys.suspend(on = 'toggle')` | Pause all hotkeys/hotstrings/remaps of this app (true/false, or 'toggle'). Returns the new state. |
| `desktop.keys.isSuspended()` |  |
| `desktop.keys.isDown(keyName)` | Is the key held down right now? |
| `desktop.keys.isOn(keyName)` | CapsLock / NumLock / ScrollLock on? |
| `desktop.keys.setOn(keyName, on)` |  |
| `desktop.keys.waitFor(keyNames = null, timeoutMs = 0)` | Wait until a key is pressed (resolves with its name) — e.g. "press any key". timeoutMs 0 = forever. |
| `desktop.keys.names()` | All key names the toolbox understands. |
| `desktop.keys.describe(combo)` | 'Ctrl+Shift+K' style text for any hotkey text ('^+k'). |

### desktop.mouse — Mouse

desktop.mouse — move, click, scroll and drag anywhere on the screen. Mouse buttons can also be hotkeys: desktop.keys.hotkey('XButton1', fn), ('Ctrl+WheelUp', fn).

| Command | What it does |
| --- | --- |
| `desktop.mouse.position()` | Pointer position in screen pixels: {x, y}. |
| `desktop.mouse.move(x, y, opts = {})` | Move to x, y. opts: {relative: true} moves by x/y, {speed: 5} glides (ms per step). |
| `desktop.mouse.click(button = 'left', opts = {})` | click('left' \| 'right' \| 'middle' \| 'x1' \| 'x2', {x, y, count}). count 2 = double click. |
| `desktop.mouse.doubleClick(button = 'left', opts = {})` |  |
| `desktop.mouse.rightClick(opts = {})` |  |
| `desktop.mouse.down(button = 'left')` |  |
| `desktop.mouse.up(button = 'left')` |  |
| `desktop.mouse.scroll(amount = 1, horizontal = false)` | Wheel notches: positive scrolls up, negative down. horizontal: true scrolls sideways. |
| `desktop.mouse.drag(x1, y1, x2, y2, opts = {})` |  |
| `desktop.mouse.isDown(button = 'left')` | Is a mouse button held right now? |

### desktop.windows — Windows of every program

desktop.windows — every window of every program: find, activate, move, resize, hide, close, keep on top, make transparent. A window is chosen by: a number (its id), 'active', or a description: 'Notepad' title contains "Notepad" (not case sensitive) 'ahk_exe chrome.exe' program name {title: 'Report', exe: 'excel'} object form; add regex: true for a regular expression title

| Command | What it does |
| --- | --- |
| `desktop.windows.list(spec = null, opts = {})` | All visible top-level windows, front to back, with title, exe, position, state… |
| `desktop.windows.active()` | The window you are typing in. |
| `desktop.windows.find(spec)` | First window matching the description, or null. |
| `desktop.windows.exists(spec)` |  |
| `desktop.windows.isActive(spec)` |  |
| `desktop.windows.wait(spec, timeoutMs = 10000, opts = {})` | Wait until a matching window appears (opts.active: until it is active). Resolves with it, or null on timeout. |
| `desktop.windows.waitClose(spec, timeoutMs = 10000)` | Wait until no matching window is left. |
| `desktop.windows.activate(spec)` | Bring to the front and focus. |
| `desktop.windows.minimize(spec)` |  |
| `desktop.windows.maximize(spec)` |  |
| `desktop.windows.restore(spec)` |  |
| `desktop.windows.hide(spec)` |  |
| `desktop.windows.show(spec)` |  |
| `desktop.windows.close(spec)` | Politely close (like clicking X). |
| `desktop.windows.kill(spec)` | End the program that owns the window. |
| `desktop.windows.move(spec, rect = {})` | move(spec, {x, y, width, height}) — any of them may be left out. |
| `desktop.windows.center(spec, size = {})` | Center on its screen (optionally resize first). |
| `desktop.windows.setTopmost(spec, on = 'toggle')` | Always on top: true, false or 'toggle'. Returns the new state. |
| `desktop.windows.setOpacity(spec, percent)` | 0-100 percent visible. |
| `desktop.windows.setClickThrough(spec, on = true)` | Clicks go through the window to what is behind it. |
| `desktop.windows.setTitle(spec, title)` |  |
| `desktop.windows.atPoint(x, y)` | The window under a screen point (default: under the mouse). |
| `desktop.windows.info(spec)` |  |

### desktop.window — This app's own windows

desktop.window — this app's own windows: the page's window, and extra windows the app opens (popups, floating toolbars, transparent click-through overlays, HUDs). Functions act on the calling page's window; those with an `id` argument can target another one.

| Command | What it does |
| --- | --- |
| `desktop.window.id()` | Id of the calling window (use it with send/close/show… from other pages). |
| `desktop.window.open(page, opts = {})` | Open another page of the app in a new window: open('settings.html', {width, height, frame, transparent, alwaysOnTop, clickThrough, x, y, center, modal, resizable, skipTaskbar, show, title, focus, data}). `data` is given to the new page via desktop.window.data(). Returns the new window id. A page that is already open is focused instead if opts.single. |
| `desktop.window.data()` | The `data` the window was opened with. |
| `desktop.window.list()` | Every window of this app: [{id, page, title, visible, focused}]. |
| `desktop.window.close(id)` |  |
| `desktop.window.show(id)` |  |
| `desktop.window.showInactive(id)` | Show without taking focus (for overlays). |
| `desktop.window.hide(id)` |  |
| `desktop.window.focus(id)` |  |
| `desktop.window.minimize(id)` |  |
| `desktop.window.maximize(id)` |  |
| `desktop.window.toggleMaximize(id)` |  |
| `desktop.window.restore(id)` |  |
| `desktop.window.isVisible(id)` |  |
| `desktop.window.isMaximized(id)` |  |
| `desktop.window.isMinimized(id)` |  |
| `desktop.window.isFocused(id)` |  |
| `desktop.window.toggle(id)` | Show if hidden or behind, hide if in front: the classic tray-app toggle. |
| `desktop.window.getBounds(id)` |  |
| `desktop.window.setBounds(bounds, id)` | {x, y, width, height}: any may be left out. |
| `desktop.window.setSize(width, height, id)` |  |
| `desktop.window.setPosition(x, y, id)` |  |
| `desktop.window.setMinSize(width, height, id)` |  |
| `desktop.window.center(id)` |  |
| `desktop.window.dock(where = 'bottom-right', margin = 12, id)` | Put the window at a screen corner/edge: 'top-right', 'bottom-left', 'center', 'cursor'… margin in px. |
| `desktop.window.setTitle(title, id)` |  |
| `desktop.window.setAlwaysOnTop(on = true, level = 'floating', id)` | true, false or 'toggle'; level 'screen-saver' floats above full-screen apps. |
| `desktop.window.setOpacity(percent, id)` | 0-100 percent visible. |
| `desktop.window.setClickThrough(on = true, id)` | Mouse clicks pass through to what is behind (for overlays). |
| `desktop.window.setFullScreen(on = true, id)` |  |
| `desktop.window.setResizable(on = true, id)` |  |
| `desktop.window.setSkipTaskbar(on = true, id)` |  |
| `desktop.window.setContentProtection(on = true, id)` | Exclude from screenshots and screen sharing. |
| `desktop.window.setProgress(value, mode = 'normal', id)` | Taskbar progress: 0-1, -1 to remove; mode 'normal' \| 'paused' \| 'error' \| 'indeterminate'. |
| `desktop.window.flash(on = true, id)` | Flash the taskbar button until the window is focused. |
| `desktop.window.setBadge(text, id)` | Small badge over the taskbar icon: a number/text (drawn for you) or null to clear. |
| `desktop.window.setBackgroundColor(color, id)` |  |
| `desktop.window.zoom(factor, id)` |  |
| `desktop.window.reload(id)` |  |
| `desktop.window.devTools(id)` |  |
| `desktop.window.send(id, event, data)` | Send an event to another app window; it receives it with desktop.on(event, fn). |
| `desktop.window.handle(id)` | Windows id (HWND) of the window, for use with desktop.windows.* |
| `desktop.window.capture(file, id)` | PNG data URL of the window's page (or save it: capture('C:\\shot.png')). |

### desktop.files — Files and folders

desktop.files — read, write, list, copy, move, delete (to the Recycle Bin), watch, zip, open and pick files and folders. Paths may use %VARIABLES%, ~ (your user folder) and the names in desktop.files.paths(); relative paths start in the app's data folder.

| Command | What it does |
| --- | --- |
| `desktop.files.paths()` | Known folders: home, desktop, documents, downloads, pictures, music, videos, appData, localAppData, temp, startMenu, startup, programFiles, windows, appDir (this app), data (its data folder), exe. |
| `desktop.files.resolve(p)` | Full path for a relative one (relative to the app's data folder). |
| `desktop.files.read(p, encoding = 'utf8')` | read(path, 'utf8' \| 'base64' \| 'dataurl' \| 'lines' \| 'json') |
| `desktop.files.write(p, data, opts = {})` | write(path, text \| object (saved as JSON) \| data URL, {encoding: 'base64', append, bom}) — folders are created. |
| `desktop.files.append(p, text)` |  |
| `desktop.files.exists(p)` |  |
| `desktop.files.stat(p)` |  |
| `desktop.files.list(dir = '.', opts = {})` | list(folder, {pattern: '*.txt' \| '**\/*.js', recursive, type: 'file'\|'dir', details, hidden, limit}) |
| `desktop.files.mkdir(p)` |  |
| `desktop.files.copy(from, to, opts = {})` |  |
| `desktop.files.move(from, to, opts = {})` |  |
| `desktop.files.rename(p, newName)` |  |
| `desktop.files.delete(p, opts = {})` | Delete to the Recycle Bin; {permanent: true} deletes for good. |
| `desktop.files.open(p)` | Open with its default program (documents, folders, URLs too). |
| `desktop.files.reveal(p)` | Show in File Explorer with the file selected. |
| `desktop.files.watch(p, fn, opts = {})` | Watch a file or folder: fn({event: 'change' \| 'rename', path}). Returns an id for unwatch(). |
| `desktop.files.unwatch(id)` |  |
| `desktop.files.hash(p, algorithm = 'sha256')` | md5 / sha1 / sha256 (default) of a file. |
| `desktop.files.size(p)` |  |
| `desktop.files.zip(sources, zipFile)` | zip(fileOrFolderOrList, 'out.zip') / unzip('a.zip', 'folder') — Windows' built-in zip. |
| `desktop.files.unzip(zipFile, folder)` |  |
| `desktop.files.icon(p, size = 'normal')` | The file's icon as a PNG data URL ('small' \| 'normal' \| 'large'). |
| `desktop.files.shortcut(lnk, targetPath, opts = {})` | Create a Windows shortcut (.lnk). opts: {args, cwd, icon, description} |
| `desktop.files.readShortcut(lnk)` |  |
| `desktop.files.pickFile(opts = {})` | Pick files: {title, filters: ['txt', 'csv'] or [{name, extensions}], multiple, defaultPath}. Returns path(s) or null. |
| `desktop.files.pickFolder(opts = {})` |  |
| `desktop.files.pickSave(opts = {})` |  |
| `desktop.files.image(p, resize)` | Image file -> {width, height, dataUrl} (PNG/JPG/ICO/BMP…), optionally resized. |

### desktop.clipboard — Clipboard

desktop.clipboard — text, HTML, RTF, images and files on the clipboard, plus change events.

| Command | What it does |
| --- | --- |
| `desktop.clipboard.read()` |  |
| `desktop.clipboard.write(text)` |  |
| `desktop.clipboard.readHTML()` |  |
| `desktop.clipboard.writeHTML(html, text)` | HTML with a plain-text fallback for programs that do not take HTML. |
| `desktop.clipboard.readRTF()` |  |
| `desktop.clipboard.writeRTF(rtf, text)` |  |
| `desktop.clipboard.readImage()` | Image on the clipboard as a PNG data URL, or null. |
| `desktop.clipboard.writeImage(src)` | Put an image (data URL or image file path) on the clipboard. |
| `desktop.clipboard.readFiles()` | Files copied in File Explorer: [paths]. |
| `desktop.clipboard.writeFiles(paths)` | Copy files so they can be pasted in File Explorer. |
| `desktop.clipboard.clear()` |  |
| `desktop.clipboard.formats()` |  |
| `desktop.clipboard.has(format)` |  |
| `desktop.clipboard.isPrivate()` | True when a password manager marked the content as secret (do not store or show it). |
| `desktop.clipboard.onChange(fn)` | fn({text, formats, hasImage, private}) on every clipboard change. Returns an id for offChange(). |
| `desktop.clipboard.offChange(id)` |  |
| `desktop.clipboard.copySelection(timeoutMs = 800)` | Copy the selection of the active program and return it (sends Ctrl+C, waits for the change). |
| `desktop.clipboard.paste(text, opts = {})` | Paste text into the active program (keeps your clipboard as it was by default). |

### desktop.programs — Programs and processes

desktop.programs — start programs, open documents and links, list and end processes.

| Command | What it does |
| --- | --- |
| `desktop.programs.run(file, args = [], opts = {})` | Start a program: run('notepad'), run('C:\\Tools\\x.exe', ['--a', 'b'], {cwd, hidden, admin, wait}). Without wait it returns at once with {pid}; with wait it waits for it to exit: {code, stdout, stderr}. admin: true asks Windows for administrator rights (UAC prompt). |
| `desktop.programs.open(target, verb = 'open')` | Open a document, folder or link with its default program. verb: 'open' \| 'edit' \| 'print' \| 'runas' \| 'explore' |
| `desktop.programs.list(filter)` | Running processes: [{pid, name, path, memory (bytes), title}]. filter: name like 'chrome' (optional). |
| `desktop.programs.isRunning(nameOrPid)` | Is a program running? isRunning('notepad') or isRunning(1234). |
| `desktop.programs.kill(nameOrPid, opts = {})` | End a program by name ('notepad.exe') or pid. force: also its child processes, no questions. |
| `desktop.programs.wait(name, timeoutMs = 30000, opts = {})` | Wait until a program is running (or closed: {closed: true}). |
| `desktop.programs.installed()` | Installed programs (from the registry): [{name, version, publisher, location, uninstall}]. |
| `desktop.programs.isAdmin()` | Is this app running with administrator rights? |
| `desktop.programs.relaunchAsAdmin()` | Restart this app with administrator rights (asks with UAC). |
| `desktop.programs.self()` | Name of the exe of this app's process. |

### desktop.tray — Tray icon

desktop.tray — an icon next to the clock with a tooltip, a right-click menu and click actions. The app may already have one from its settings (Studio's "Tray icon" option); these calls change that one, or create it.

| Command | What it does |
| --- | --- |
| `desktop.tray.create(opts = {})` | Show the tray icon: create({icon, tooltip, menu: [...], onClick, onDoubleClick}). Without onClick, a click shows/hides the main window. |
| `desktop.tray.setMenu(items)` |  |
| `desktop.tray.setIcon(src)` |  |
| `desktop.tray.setTooltip(text)` |  |
| `desktop.tray.balloon(title, text, icon = 'info')` | Windows balloon notification from the tray icon. icon: 'info' \| 'warning' \| 'error' \| 'none' |
| `desktop.tray.popUp()` | Open the tray menu (e.g. from a hotkey). |
| `desktop.tray.exists()` |  |
| `desktop.tray.remove()` |  |

### desktop.dialog — Message boxes and questions

desktop.dialog — Windows message boxes and quick questions.

| Command | What it does |
| --- | --- |
| `desktop.dialog.message(text, opts = {})` | message(text, {title, type: 'info'\|'warning'\|'error'\|'question', buttons: ['OK'], detail, checkbox}) -> button index (and checked). |
| `desktop.dialog.info(text, title)` |  |
| `desktop.dialog.warning(text, title)` |  |
| `desktop.dialog.error(text, title)` |  |
| `desktop.dialog.confirm(text, opts = {})` | Yes/No question -> true/false. |
| `desktop.dialog.prompt(text, opts = {})` | Ask for a line of text -> string, or null when cancelled. opts: {title, value, password, placeholder} |
| `desktop.dialog.errorBox(title, text)` | Blocking error box that works even before the app is ready. |

### desktop.screen — Screen, screenshots, OCR

desktop.screen — monitors, screenshots, pixel colours and text recognition (OCR).

| Command | What it does |
| --- | --- |
| `desktop.screen.displays()` | All monitors: [{id, primary, bounds, workArea, scaleFactor, rotation}]. |
| `desktop.screen.primary()` |  |
| `desktop.screen.cursor()` | Mouse position in screen coordinates. |
| `desktop.screen.capture(opts = {})` | Screenshot -> PNG data URL, or saved to a file when opts.file is given (returns the path). opts: {display: index, rect: {x, y, width, height}, file, format: 'png' \| 'jpg', quality} |
| `desktop.screen.pixel(x, y)` | Colour of one screen pixel: '#rrggbb'. Default: under the mouse. |
| `desktop.screen.ocr(source, lang = '')` | Read text with Windows' built-in OCR. source: a rect {x,y,width,height} of the screen, an image file path, a data URL, or nothing (whole screen under the mouse). lang e.g. 'en-US', 'ar'. Returns the recognised text (lines joined with \n). |
| `desktop.screen.waitPixel(x, y, color, { timeout = 10000, tolerance = 8, interval = 100 } = {})` | Wait until a pixel has a colour (e.g. a button turned green). tolerance 0-255 per channel. |
| `desktop.screen.select(opts = {})` | Let the user drag a rectangle on the screen; resolves {x, y, width, height} or null (Esc). |

### desktop.power — Power

desktop.power — shut down, restart, sleep, lock, screen off, keep awake, battery, idle time, and events: desktop.on('power', e => e.type) with suspend, resume, lock-screen, unlock-screen, on-ac, on-battery, shutdown.

| Command | What it does |
| --- | --- |
| `desktop.power.shutdown(opts = {})` | Shut down the PC. opts: {delay: seconds, force: close apps without asking, message} |
| `desktop.power.restart(opts = {})` |  |
| `desktop.power.cancelShutdown()` | Cancel a shutdown/restart that has a delay. |
| `desktop.power.logoff()` |  |
| `desktop.power.lock()` |  |
| `desktop.power.sleep()` |  |
| `desktop.power.hibernate()` |  |
| `desktop.power.screenOff()` | Turn the monitors off (they wake on mouse/keyboard). |
| `desktop.power.keepAwake(on = true, display = false)` | Keep the PC (and with display: true, the screen) awake while on. |
| `desktop.power.idleTime()` | Seconds since the last keyboard/mouse input. |
| `desktop.power.idleState(seconds = 60)` | 'active' \| 'idle' \| 'locked' \| 'unknown' after `seconds` of no input. |
| `desktop.power.onBattery()` |  |
| `desktop.power.battery()` | {present, percent, charging, minutesLeft} |
| `desktop.power.plan()` | Active power plan name. |

### desktop.system — System and Windows settings

desktop.system — information about the PC and Windows settings: environment variables, wallpaper, dark mode, drives, network adapters, start with Windows, theme colours.

| Command | What it does |
| --- | --- |
| `desktop.system.info()` | {os, version, build, arch, hostname, user, domain, cpu, cores, memory, freeMemory, uptime, locale, admin} |
| `desktop.system.usage(sampleMs = 500)` | CPU load 0-100 over a short sample, and memory use. |
| `desktop.system.env(name)` | Environment variable (this app's view). |
| `desktop.system.setEnv(name, value, permanent = false)` | Set a variable; permanent: 'user' or 'machine' also saves it in Windows (machine needs admin). |
| `desktop.system.drives()` | Drives: [{name, label, type, fileSystem, size, free}] |
| `desktop.system.setWallpaper(file)` | Set the desktop wallpaper from an image file. |
| `desktop.system.wallpaper()` |  |
| `desktop.system.isDark()` | Is Windows in dark mode? |
| `desktop.system.setAppTheme(mode = 'system')` | This app's own look: 'system' \| 'light' \| 'dark'. |
| `desktop.system.setWindowsDark(on = true)` | Windows dark mode for apps on/off (the Settings switch). |
| `desktop.system.accentColor()` | Windows accent colour '#rrggbb'. |
| `desktop.system.startWithWindows(on, args = [])` | Start this app when you sign in to Windows (true/false), or read the setting (no argument). |
| `desktop.system.startedAtLogin()` | Was this run started by Windows at sign-in? |
| `desktop.system.network()` | Network adapters with their addresses. |
| `desktop.system.brightness(level)` | Display brightness 0-100 (laptop screens), or set it. |
| `desktop.system.openSettings(page = '')` | Open a Windows Settings page: 'display', 'sound', 'network', 'bluetooth', 'apps', 'windowsupdate', … |
| `desktop.system.emptyRecycleBin()` | Empty the Recycle Bin. |
| `desktop.system.hostname()` |  |
| `desktop.system.run(cmd)` |  |

### desktop.audio — Sound, volume, speech

desktop.audio — master volume and mute, beeps, sounds and text-to-speech.

| Command | What it does |
| --- | --- |
| `desktop.audio.volume(level)` | Master volume 0-100 (no argument = read it). |
| `desktop.audio.mute(on)` | Mute on/off/'toggle' (no argument = read it). |
| `desktop.audio.up(steps = 1)` | Volume keys: instant, shows the Windows volume flyout. steps: number of presses (2% each). |
| `desktop.audio.down(steps = 1)` |  |
| `desktop.audio.toggleMute()` |  |
| `desktop.audio.media(action = 'playpause')` | Media keys: 'playpause' \| 'next' \| 'previous' \| 'stop'. |
| `desktop.audio.beep(frequency = 750, duration = 150)` | Beep from the PC speaker / sound card: frequency (Hz), duration (ms). |
| `desktop.audio.systemSound(name = 'asterisk')` | Windows sound: 'asterisk' \| 'beep' \| 'exclamation' \| 'hand' \| 'question'. |
| `desktop.audio.playWav(file)` | Play a .wav file and wait until it ends (pages can also play any audio with new Audio()). |
| `desktop.audio.speak(text, opts = {})` | Speak text with a Windows voice. opts: {voice, rate: -10..10, volume: 0-100, file: save as .wav} |
| `desktop.audio.voices()` | Installed voices: [{name, culture, gender}] |
| `desktop.audio.devices()` | Audio devices (sound cards, speakers, microphones). |

### desktop.registry — Registry

desktop.registry — read and write the Windows registry (through reg.exe). Keys look like 'HKCU\\Software\\MyApp' (HKLM, HKCR, HKU, HKCC and the long names work too).

| Command | What it does |
| --- | --- |
| `desktop.registry.read(key, name = '')` | Read one value ('' = the default value). Returns null when missing. |
| `desktop.registry.readTyped(key, name = '')` | Value with its type: {name, type, value} or null. |
| `desktop.registry.write(key, name, value, type)` | write(key, name, value, type = auto) — numbers become REG_DWORD, arrays REG_MULTI_SZ, else REG_SZ. |
| `desktop.registry.delete(key, name)` | Delete a value, or the whole key (with its subkeys) when name is left out. |
| `desktop.registry.createKey(key)` |  |
| `desktop.registry.exists(key, name)` |  |
| `desktop.registry.list(key)` | Subkeys and values of a key: {keys: [full paths], values: [{name, type, value}]} |
| `desktop.registry.exportKey(key, file)` | Export a key to a .reg file / import a .reg file. |
| `desktop.registry.importFile(file)` |  |

### desktop.net — Internet and network

desktop.net — internet and network from the app's back end: requests to any site (no CORS limits), downloads with progress, ping, ports, local IPs, online state.

| Command | What it does |
| --- | --- |
| `desktop.net.request(url, opts = {})` | HTTP request: request(url, {method, headers, body (text or object -> JSON), as: 'text'\|'json'\|'base64', timeout}) -> {ok, status, headers, body} |
| `desktop.net.download(url, file, onProgress, opts = {})` | Download to a file with optional progress callback fn({received, total, percent}). Returns the path. |
| `desktop.net.online()` | Is there a working internet connection? |
| `desktop.net.localIPs()` | Local IPv4 addresses of this PC. |
| `desktop.net.publicIP()` | Your public IP address (asks api.ipify.org). |
| `desktop.net.ping(host, timeoutMs = 2000)` | Ping a host: {alive, ms} |
| `desktop.net.portOpen(host, port, timeoutMs = 2000)` | Can a TCP connection be made to host:port? |
| `desktop.net.lookup(host)` |  |
| `desktop.net.openUrl(url)` | Open a link in the default browser. |
| `desktop.net.wifi()` | Wi-Fi networks in range (netsh). |

### desktop.store — Saved settings

desktop.store — simple saved settings (key -> any JSON value), kept in the app's data folder. Shared by all windows of the app; desktop.on('store', e => …) tells other windows about changes.

| Command | What it does |
| --- | --- |
| `desktop.store.get(key, fallback = null)` |  |
| `desktop.store.set(key, value)` |  |
| `desktop.store.setMany(values)` | Merge many values at once: setMany({a: 1, b: 2}) |
| `desktop.store.has(key)` |  |
| `desktop.store.delete(key)` |  |
| `desktop.store.all()` |  |
| `desktop.store.clear()` |  |
| `desktop.store.file()` | Where the file is (for backups). |

### desktop.db — SQL database

desktop.db — real SQL databases (SQLite, built into Electron 33+, nothing to install). const db = desktop.db.open('notes'); // file notes.db in the app's data folder await db.run('CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, text TEXT)'); await db.run('INSERT INTO notes(text) VALUES (?)', ['hello']); const rows = await db.all('SELECT * FROM notes WHERE text LIKE ?', ['%he%']); In the toolbox itself every call takes the database name first: desktop.db.all('notes', sql, params).

| Command | What it does |
| --- | --- |
| `desktop.db.run(name, sql, p)` | Statements that change data: -> {changes, lastId} |
| `desktop.db.all(name, sql, p)` | All rows: [{column: value}] |
| `desktop.db.get(name, sql, p)` | First row or null. |
| `desktop.db.exec(name, sql)` | Several statements separated by ; (no parameters). |
| `desktop.db.transaction(name, steps)` | Run many statements as one all-or-nothing transaction: [[sql, params], …] |
| `desktop.db.tables(name)` |  |
| `desktop.db.close(name)` |  |
| `desktop.db.file(name)` | Full path of the database file. |
| `desktop.db.open(name)` | An object for one database whose run/all/get/exec/transaction/tables/close need no name. |

### desktop.print — Printing and PDF

desktop.print — print the page, any HTML or a document file; save as PDF; list printers.

| Command | What it does |
| --- | --- |
| `desktop.print.printers()` | Printers: [{name, displayName, isDefault, status}] |
| `desktop.print.page(opts = {})` | Print the calling page. opts: {silent (no dialog), printer, copies, landscape, color, pageSize, background} |
| `desktop.print.html(html, opts = {})` | Print an HTML string (a receipt, a label…). |
| `desktop.print.pdf(file, opts = {})` | Save the calling page (or html when given) as a PDF file. opts: {landscape, pageSize, background, html} |
| `desktop.print.file(p, printer)` | Print a document (PDF, DOCX, TXT, image…) with its own program; printer: name for a specific printer. |

### desktop.app — This application

desktop.app — this application: name, version, folders, start options, quit/restart.

| Command | What it does |
| --- | --- |
| `desktop.app.info()` | {name, version, id, dev, portable, electron, exe, dataDir, appDir, startedAtLogin, args} |
| `desktop.app.args()` | Command-line arguments the app was started with (without Electron's own). |
| `desktop.app.version()` |  |
| `desktop.app.name()` |  |
| `desktop.app.quit()` | Quit completely (also from the tray). |
| `desktop.app.restart()` | Restart the app (e.g. after changing settings). |
| `desktop.app.openDataFolder()` | Open the app's data folder (settings, databases, logs) in File Explorer. |
| `desktop.app.focus()` | Bring the main window to the front. |
| `desktop.app.hide()` | Hide all windows (keeps running in the tray, if it has one). |
| `desktop.app.startWithWindows(on)` | Start with Windows on/off (no argument: read it). |
| `desktop.app.config()` | The settings the app was built with (app.config.json). |
| `desktop.app.readLog(lines = 200)` | Read the app's log file (last `lines` lines). |
| `desktop.app.setBadge(count)` | Badge number on the taskbar button (0 / null clears it). |
