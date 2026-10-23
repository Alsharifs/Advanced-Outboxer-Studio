r"""
Advanced Outboxer Studio v2.0 — turns websites, local web apps and whole HTML/CSS/JS project folders
into desktop apps. Websites: Electron via the modernised Nativefier 53 engine, or Microsoft Edge WebView2
(everything Outboxer Studio v1.0 does). Project folders: a Windows app on Electron with the "desktop
toolbox" (window.desktop) that controls the PC — hotkeys, keys, mouse, windows, files, programs, tray,
screen, audio, registry and more (see project_core.py, project_ui.py and the host folder).
Developed by Sayed Alsharif.

Requirements:
    pip install PySide6

Everything else lives in the Engines folder next to this script (paths can be changed in the
Engines window and are saved in AdvancedOutboxerStudio.config.json):
    Engines\node\           Node.js (node.exe + npm)
    Engines\nativefier53\   the Nativefier 53 engine (works on current Node.js)
    Engines\electron\       Electron zips, e.g. electron-v44.7.0-win32-x64.zip
    Engines\packages\       nativefier-53.x.tgz, to install or repair the engine
    Engines\runtime\        unpacked Electron for "shared runtime" apps
    Engines\webview2\       the WebView2 SDK (2 small DLLs) for "WebView2" apps
    host\                   the app host + desktop toolbox copied into every project app
    templates\, examples\   starting points for new projects

App engines: Electron inside the app (self-contained) · Electron shared runtime (small app folder) ·
WebView2 (tiny app that uses the Edge engine built into Windows 10/11).
"""

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import (QByteArray, QPoint, QProcess, QProcessEnvironment, QRect, QRectF, QSettings,
                            QSize, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal)
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QFont, QIcon, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox, QDialog, QTextBrowser, QDialogButtonBox,
    QSizePolicy, QSplitter, QStackedWidget, QStatusBar, QTabWidget, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

APP_NAME = "Advanced Outboxer Studio"
APP_VERSION = "2.0"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"
APP_RELEASED = "October 2026"
APP_DEVELOPER = "Sayed Alsharif"
IS_WIN = os.name == "nt"
APP_DIR = Path(__file__).resolve().parent
APP_ICON = APP_DIR / "advanced_outboxer_studio.ico"
if not APP_ICON.is_file():
    APP_ICON = APP_DIR / "outboxer_studio.ico"
DEFAULT_APP_VERSION = "1.0.0"
# Electron for new builds until changed in the Engines window (Nativefier 53 was tested with it)
DEFAULT_ELECTRON_VERSION = "44.7.0"


def desktop_dir():
    """The user's real Desktop (also works when it is redirected to OneDrive)."""
    p = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation) or str(Path.home() / "Desktop")
    return os.path.normpath(p)


# "Start <App>.vbs", written into an app folder when the Server tab bundles a local server.
LAUNCHER_VBS = r'''Option Explicit
' Start {APP_NAME} - made by Outboxer Studio.
' Starts the app's own server (from the "{SERVER_DIR}" folder next to this file) if it is not running yet,
' waits until it answers, then opens {APP_EXE}. Everything lives in this one folder.
Const APP_EXE = "{APP_EXE}"
Const SERVER_DIR = "{SERVER_DIR}"
Const SERVER_SCRIPT = "{SERVER_SCRIPT}"
Const URL = "{URL}"
Const NODE_MODE = "{NODE_MODE}"          ' builtin = the app's own Node (ELECTRON_RUN_AS_NODE); installed = node.exe; path = NODE_EXE
Const NODE_EXE = "{NODE_EXE}"
Const STOP_ON_CLOSE = {STOP_ON_CLOSE}    ' stop the server again when the app window is closed

Dim fso, sh, appDir, exePath, srvDir, script, logFile, startedHere
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
exePath = appDir & "\" & APP_EXE
srvDir = appDir & "\" & SERVER_DIR
script = srvDir & "\" & SERVER_SCRIPT
logFile = srvDir & "\server.log"
startedHere = False

If Not fso.FileExists(exePath) Then Fail "The app was not found:" & vbCrLf & exePath

If Not ServerUp() Then
  If Not fso.FileExists(script) Then Fail "The server script was not found:" & vbCrLf & script
  sh.CurrentDirectory = srvDir
  If NODE_MODE = "builtin" Then startedHere = StartServer(exePath, True)
  If NODE_MODE = "path" Then startedHere = StartServer(NODE_EXE, False)
  If Not startedHere Then
    StopServer   ' clean up a half-started attempt before trying installed Node
    startedHere = StartServer("node", False)
  End If
  If Not startedHere Then
    StopServer
    Fail "The server did not start." & vbCrLf & vbCrLf & "Details are in:" & vbCrLf & logFile
  End If
End If

sh.CurrentDirectory = appDir
If STOP_ON_CLOSE And startedHere Then
  sh.Run Quote(exePath), 1, True    ' wait here until the app is closed ...
  StopServer                        ' ... then stop the server this launcher started
Else
  sh.Run Quote(exePath), 1, False
End If
WScript.Quit 0

' ---- helpers ----
Function StartServer(nodeExe, asApp)
  Dim env
  Set env = sh.Environment("Process")
  If asApp Then env("ELECTRON_RUN_AS_NODE") = "1"   ' the app's .exe then runs as plain Node
  sh.Run "cmd /s /c """ & Quote(nodeExe) & " " & Quote(script) & " >> " & Quote(logFile) & " 2>&1""", 0, False
  If asApp Then env.Remove "ELECTRON_RUN_AS_NODE"   ' so the app window itself starts normally
  StartServer = WaitUp(80)   ' up to 20 seconds
End Function

Sub StopServer()   ' every process whose command line runs this app's server script
  Dim p, cl
  On Error Resume Next
  For Each p In GetObject("winmgmts:\\.\root\cimv2").ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process")
    cl = LCase("" & p.CommandLine)
    If InStr(cl, LCase(script)) > 0 And InStr(cl, "wscript") = 0 Then p.Terminate
  Next
  On Error GoTo 0
End Sub

Function WaitUp(times)
  Dim i
  WaitUp = False
  For i = 1 To times
    WScript.Sleep 250
    If ServerUp() Then
      WaitUp = True
      Exit Function
    End If
  Next
End Function

Function ServerUp()   ' any HTTP answer means the server is running
  Dim http
  ServerUp = False
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  http.setTimeouts 500, 500, 500, 500
  http.Open "GET", URL, False
  http.Send
  If Err.Number = 0 Then
    If http.Status > 0 Then ServerUp = True
  End If
  On Error GoTo 0
End Function

Sub Fail(msg)
  MsgBox msg, vbExclamation, "Start {APP_NAME}"
  WScript.Quit 1
End Sub

Function Quote(s)
  If s = "node" Then Quote = s Else Quote = """" & s & """"
End Function
'''

# ---------------------------------------------------------------------------
# Option specs: (key, cli_flag, kind, label, tab, extra)
# kinds: text, int, float, bool, choice, ecombo (editable combo), file, dir, files
# ---------------------------------------------------------------------------
OPTIONS = [
    # --- App ---
    ("electron_mode", None, "choice", "App engine", "App",
     {"items": [("bundled", "Electron inside the app — self-contained, works on any PC (~370 MB)"),
                ("shared", "Electron shared runtime — small app (~2 MB) using the folder below"),
                ("webview2", "WebView2 (Edge, built into Windows) — tiny app (~1 MB), no Electron")]}),
    ("runtime_dir", None, "dir", "Shared runtime folder", "App",
     {"ph": "auto: Engines\\runtime\\electron-v<version>-win32-x64 (unpacked once, used by all shared apps)"}),
    ("name", "--name", "text", "App name", "App", {"ph": "e.g. WhatsApp"}),
    ("platform", "--platform", "choice", "Platform", "App",
     {"items": ["", "windows", "linux", "mac", "mas"]}),
    ("arch", "--arch", "choice", "Architecture", "App",
     {"items": ["", "x64", "ia32", "arm64", "armv7l", "universal"]}),
    ("icon", "--icon", "file", "Icon (.ico/.png/.icns)", "App",
     {"filter": "Icons (*.ico *.png *.icns);;All files (*)"}),
    ("app_version", "--app-version", "text", "App version", "App", {"ph": "1.0.0 (default)"}),
    ("build_version", "--build-version", "text", "Build version", "App", {}),
    ("app_copyright", "--app-copyright", "text", "Copyright", "App", {}),
    ("electron_version", "--electron-version", "text", "Electron version", "App",
     {"ph": "default from the Engines window"}),
    ("portable", "--portable", "bool", "Portable (keep data next to app)", "App", {}),
    ("single_instance", "--single-instance", "bool", "Single instance only", "App", {}),
    ("conceal", "--conceal", "bool", "Pack app source into asar archive", "App", {}),

    # --- Window ---
    ("width", "--width", "int", "Width", "Window", {"max": 10000}),
    ("height", "--height", "int", "Height", "Window", {"max": 10000}),
    ("min_width", "--min-width", "int", "Min width", "Window", {"max": 10000}),
    ("min_height", "--min-height", "int", "Min height", "Window", {"max": 10000}),
    ("max_width", "--max-width", "int", "Max width", "Window", {"max": 10000}),
    ("max_height", "--max-height", "int", "Max height", "Window", {"max": 10000}),
    ("x", "--x", "int", "X position", "Window", {"max": 10000}),
    ("y", "--y", "int", "Y position", "Window", {"max": 10000}),
    ("full_screen", "--full-screen", "bool", "Start full screen", "Window", {}),
    ("maximize", "--maximize", "bool", "Start maximized", "Window", {}),
    ("hide_window_frame", "--hide-window-frame", "bool", "Hide window frame", "Window", {}),
    ("always_on_top", "--always-on-top", "bool", "Always on top", "Window", {}),
    ("show_menu_bar", "--show-menu-bar", "bool", "Show menu bar", "Window", {}),
    ("tray", "--tray", "choice", "System tray", "Window",
     {"items": ["", "true", "false", "start-in-tray"]}),
    ("title_bar_style", "--title-bar-style", "choice", "Title bar style (macOS)", "Window",
     {"items": ["", "hidden", "hiddenInset"]}),
    ("background_color", "--background-color", "text", "Background color", "Window",
     {"ph": "#2e2c29"}),

    # --- Behavior ---
    ("internal_urls", "--internal-urls", "text", "Internal URLs (regex)", "Behavior",
     {"ph": r".*?\.google\.com.*?"}),
    ("strict_internal_urls", "--strict-internal-urls", "bool", "Strict internal URLs", "Behavior", {}),
    ("block_external_urls", "--block-external-urls", "bool", "Block external URLs", "Behavior", {}),
    ("user_agent", "--user-agent", "ecombo", "User agent", "Behavior",
     {"items": ["", "chrome", "edge", "firefox", "safari"]}),
    ("zoom", "--zoom", "float", "Zoom factor", "Behavior", {}),
    ("counter", "--counter", "bool", "Show unread counter from title", "Behavior", {}),
    ("bounce", "--bounce", "bool", "Bounce dock on counter (macOS)", "Behavior", {}),
    ("fast_quit", "--fast-quit", "bool", "Quit when window closes (macOS)", "Behavior", {}),
    ("disable_context_menu", "--disable-context-menu", "bool", "Disable context menu", "Behavior", {}),
    ("disable_dev_tools", "--disable-dev-tools", "bool", "Disable DevTools", "Behavior", {}),
    ("clear_cache", "--clear-cache", "bool", "Clear cache on start", "Behavior", {}),
    ("inject", "--inject", "files", "Inject CSS / JS files", "Behavior",
     {"filter": "CSS/JS (*.css *.js);;All files (*)"}),

    # --- Advanced ---
    ("proxy_rules", "--proxy-rules", "text", "Proxy rules", "Advanced", {"ph": "http://proxy:8080"}),
    ("basic_auth_username", "--basic-auth-username", "text", "Basic auth user", "Advanced", {}),
    ("basic_auth_password", "--basic-auth-password", "text", "Basic auth password", "Advanced",
     {"password": True}),
    ("disk_cache_size", "--disk-cache-size", "int", "Disk cache size (bytes)", "Advanced",
     {"max": 2_000_000_000}),
    ("lang", "--lang", "text", "Language", "Advanced", {"ph": "en-US"}),
    ("file_download_options", "--file-download-options", "text", "File download options (JSON)",
     "Advanced", {"ph": '{"saveAs": true}'}),
    ("browserwindow_options", "--browserwindow-options", "text", "BrowserWindow options (JSON)",
     "Advanced", {"ph": 'e.g. {"webPreferences": {"spellcheck": false}}'}),
    ("global_shortcuts", "--global-shortcuts", "file", "Global shortcuts (JSON)", "Advanced",
     {"filter": "JSON (*.json)"}),
    ("ignore_certificate", "--ignore-certificate", "bool", "Ignore certificate errors", "Advanced", {}),
    ("insecure", "--insecure", "bool", "Allow insecure content", "Advanced", {}),
    ("disable_gpu", "--disable-gpu", "bool", "Disable GPU", "Advanced", {}),
    ("ignore_gpu_blacklist", "--ignore-gpu-blacklist", "bool", "Ignore GPU blacklist", "Advanced", {}),
    ("enable_es3_apis", "--enable-es3-apis", "bool", "Enable WebGL 2 (ES3) APIs", "Advanced", {}),
    ("honest", "--honest", "bool", "Honest user agent", "Advanced", {}),
    ("widevine", "--widevine", "bool", "Widevine DRM (castlabs Electron)", "Advanced", {}),
    ("verbose", "--verbose", "bool", "Verbose log", "Advanced", {}),
    ("quiet", "--quiet", "bool", "Quiet", "Advanced", {}),
    ("extra_args", None, "text", "Extra raw arguments", "Advanced",
     {"ph": '--some-flag value --another'}),

    # --- Server: bundle a local web server (e.g. server.js on localhost) into the app folder ---
    # These are not Nativefier flags (cli_flag None); Outboxer Studio handles them after the build.
    ("server_dir", None, "dir", "Folder to bundle", "Server",
     {"ph": "Folder with the server script and site files — copied into <App>\\server"}),
    ("server_script", None, "text", "Server script", "Server", {"ph": "server.js"}),
    ("server_node", None, "choice", "Run the server with", "Server",
     {"items": [("builtin", "The app's own Node (Electron) / a copy of Studio's node.exe (WebView2)"),
                ("installed", "Node.js installed on the PC"),
                ("path", "This node.exe (choose below), e.g. C:\\Z\\Z.exe")]}),
    ("server_node_path", None, "file", "node.exe to use", "Server",
     {"filter": "Programs (*.exe);;All files (*)", "ph": "Only for 'This node.exe'"}),
    ("server_stop", None, "bool", "Stop the server when the app closes", "Server", {"default": True}),
    ("server_shortcut", None, "bool", "Create a desktop shortcut", "Server", {"default": True}),
    ("server_exclude", None, "text", "Don't copy", "Server",
     {"ph": "node_modules; tests; .git; playwright.config.js; *.log"}),
]
SERVER_EXCLUDE_DEFAULT = "node_modules; tests; .git; playwright.config.js; *.log"
SERVER_SUBDIR = "server"

# ---------------------------------------------------------------------------
# Look & feel: the "MasterKey modern" style — Windows 11 / Spotlight feel, white rounded cards on
# #F6F7FB, indigo accent, Segoe UI, Lucide line icons drawn white on rounded colour tiles.
# Icons: Lucide (https://lucide.dev), ISC License, Copyright (c) Lucide Contributors.
# ---------------------------------------------------------------------------
TILE = {"blue": "#2563EB", "indigo": "#4F46E5", "purple": "#7C3AED", "pink": "#DB2777", "red": "#DC2626",
        "orange": "#EA580C", "amber": "#D97706", "green": "#16A34A", "teal": "#0D9488", "slate": "#475569"}
GLYPH = "#334155"   # plain line icons inside buttons and inputs
ACCENT = "#4F46E5"

LUCIDE = json.loads(r'''{"globe": "<circle cx=\"12\" cy=\"12\" r=\"10\" /> <path d=\"M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20\" /> <path d=\"M2 12h20\" />", "app-window": "<rect x=\"2\" y=\"4\" width=\"20\" height=\"16\" rx=\"2\" /> <path d=\"M10 4v4\" /> <path d=\"M2 8h20\" /> <path d=\"M6 4v4\" />", "monitor": "<rect width=\"20\" height=\"14\" x=\"2\" y=\"3\" rx=\"2\" /> <line x1=\"8\" x2=\"16\" y1=\"21\" y2=\"21\" /> <line x1=\"12\" x2=\"12\" y1=\"17\" y2=\"21\" />", "mouse-pointer-click": "<path d=\"M14 4.1 12 6\" /> <path d=\"m5.1 8-2.9-.8\" /> <path d=\"m6 12-1.9 2\" /> <path d=\"M7.2 2.2 8 5.1\" /> <path d=\"M9.037 9.69a.498.498 0 0 1 .653-.653l11 4.5a.5.5 0 0 1-.074.949l-4.349 1.041a1 1 0 0 0-.74.739l-1.04 4.35a.5.5 0 0 1-.95.074z\" />", "sliders-horizontal": "<line x1=\"21\" x2=\"14\" y1=\"4\" y2=\"4\" /> <line x1=\"10\" x2=\"3\" y1=\"4\" y2=\"4\" /> <line x1=\"21\" x2=\"12\" y1=\"12\" y2=\"12\" /> <line x1=\"8\" x2=\"3\" y1=\"12\" y2=\"12\" /> <line x1=\"21\" x2=\"16\" y1=\"20\" y2=\"20\" /> <line x1=\"12\" x2=\"3\" y1=\"20\" y2=\"20\" /> <line x1=\"14\" x2=\"14\" y1=\"2\" y2=\"6\" /> <line x1=\"8\" x2=\"8\" y1=\"10\" y2=\"14\" /> <line x1=\"16\" x2=\"16\" y1=\"18\" y2=\"22\" />", "server": "<rect width=\"20\" height=\"8\" x=\"2\" y=\"2\" rx=\"2\" ry=\"2\" /> <rect width=\"20\" height=\"8\" x=\"2\" y=\"14\" rx=\"2\" ry=\"2\" /> <line x1=\"6\" x2=\"6.01\" y1=\"6\" y2=\"6\" /> <line x1=\"6\" x2=\"6.01\" y1=\"18\" y2=\"18\" />", "cpu": "<rect width=\"16\" height=\"16\" x=\"4\" y=\"4\" rx=\"2\" /> <rect width=\"6\" height=\"6\" x=\"9\" y=\"9\" rx=\"1\" /> <path d=\"M15 2v2\" /> <path d=\"M15 20v2\" /> <path d=\"M2 15h2\" /> <path d=\"M2 9h2\" /> <path d=\"M20 15h2\" /> <path d=\"M20 9h2\" /> <path d=\"M9 2v2\" /> <path d=\"M9 20v2\" />", "hammer": "<path d=\"m15 12-8.373 8.373a1 1 0 1 1-3-3L12 9\" /> <path d=\"m18 15 4-4\" /> <path d=\"m21.5 11.5-1.914-1.914A2 2 0 0 1 19 8.172V7l-2.26-2.26a6 6 0 0 0-4.202-1.756L9 2.96l.92.82A6.18 6.18 0 0 1 12 8.4V10l2 2h1.172a2 2 0 0 1 1.414.586L18.5 14.5\" />", "square": "<rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\" />", "folder-open": "<path d=\"m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2\" />", "copy": "<rect width=\"14\" height=\"14\" x=\"8\" y=\"8\" rx=\"2\" ry=\"2\" /> <path d=\"M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2\" />", "eraser": "<path d=\"m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21\" /> <path d=\"M22 21H7\" /> <path d=\"m5 11 9 9\" />", "book-open": "<path d=\"M12 7v14\" /> <path d=\"M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z\" />", "info": "<circle cx=\"12\" cy=\"12\" r=\"10\" /> <path d=\"M12 16v-4\" /> <path d=\"M12 8h.01\" />", "save": "<path d=\"M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z\" /> <path d=\"M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7\" /> <path d=\"M7 3v4a1 1 0 0 0 1 1h7\" />", "folder-input": "<path d=\"M2 9V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-1\" /> <path d=\"M2 13h10\" /> <path d=\"m9 16 3-3-3-3\" />", "rotate-ccw": "<path d=\"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8\" /> <path d=\"M3 3v5h5\" />", "external-link": "<path d=\"M15 3h6v6\" /> <path d=\"M10 14 21 3\" /> <path d=\"M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6\" />", "log-out": "<path d=\"M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4\" /> <polyline points=\"16 17 21 12 16 7\" /> <line x1=\"21\" x2=\"9\" y1=\"12\" y2=\"12\" />", "settings-2": "<path d=\"M20 7h-9\" /> <path d=\"M14 17H5\" /> <circle cx=\"17\" cy=\"17\" r=\"3\" /> <circle cx=\"7\" cy=\"7\" r=\"3\" />", "package": "<path d=\"M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z\" /> <path d=\"M12 22V12\" /> <path d=\"m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7\" /> <path d=\"m7.5 4.27 9 5.15\" />", "download": "<path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\" /> <polyline points=\"7 10 12 15 17 10\" /> <line x1=\"12\" x2=\"12\" y1=\"15\" y2=\"3\" />", "refresh-cw": "<path d=\"M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8\" /> <path d=\"M21 3v5h-5\" /> <path d=\"M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16\" /> <path d=\"M8 16H3v5\" />", "check": "<path d=\"M20 6 9 17l-5-5\" />", "chevron-down": "<path d=\"m6 9 6 6 6-6\" />", "box": "<path d=\"M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z\" /> <path d=\"m3.3 7 8.7 5 8.7-5\" /> <path d=\"M12 22V12\" />", "terminal": "<polyline points=\"4 17 10 11 4 5\" /> <line x1=\"12\" x2=\"20\" y1=\"19\" y2=\"19\" />", "hard-drive": "<line x1=\"22\" x2=\"2\" y1=\"12\" y2=\"12\" /> <path d=\"M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z\" /> <line x1=\"6\" x2=\"6.01\" y1=\"16\" y2=\"16\" /> <line x1=\"10\" x2=\"10.01\" y1=\"16\" y2=\"16\" />", "layers": "<path d=\"m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z\" /> <path d=\"m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65\" /> <path d=\"m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65\" />", "zap": "<path d=\"M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z\" />", "x": "<path d=\"M18 6 6 18\" /> <path d=\"m6 6 12 12\" />"}''')
LUCIDE.update(json.loads(r'''{"file-plus": "<path d=\"M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z\" /> <path d=\"M14 2v4a2 2 0 0 0 2 2h4\" /> <path d=\"M9 15h6\" /> <path d=\"M12 18v-6\" />", "code": "<polyline points=\"16 18 22 12 16 6\" /> <polyline points=\"8 6 2 12 8 18\" />", "flask-conical": "<path d=\"M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2\" /> <path d=\"M8.5 2h7\" /> <path d=\"M7 16h10\" />", "play": "<polygon points=\"6 3 20 12 6 21 6 3\" />", "folder": "<path d=\"M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z\" />", "file-code": "<path d=\"M10 12.5 8 15l2 2.5\" /> <path d=\"m14 12.5 2 2.5-2 2.5\" /> <path d=\"M14 2v4a2 2 0 0 0 2 2h4\" /> <path d=\"M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z\" />", "power": "<path d=\"M12 2v10\" /> <path d=\"M18.4 6.6a9 9 0 1 1-12.77.04\" />", "list-checks": "<path d=\"m3 17 2 2 4-4\" /> <path d=\"m3 7 2 2 4-4\" /> <path d=\"M13 6h8\" /> <path d=\"M13 12h8\" /> <path d=\"M13 18h8\" />", "plus": "<path d=\"M5 12h14\" /> <path d=\"M12 5v14\" />", "search": "<circle cx=\"11\" cy=\"11\" r=\"8\" /> <path d=\"m21 21-4.3-4.3\" />", "app-window-mac": "<rect width=\"20\" height=\"16\" x=\"2\" y=\"4\" rx=\"2\" /> <path d=\"M6 8h.01\" /> <path d=\"M10 8h.01\" /> <path d=\"M14 8h.01\" />", "circle-check": "<circle cx=\"12\" cy=\"12\" r=\"10\" /> <path d=\"m9 12 2 2 4-4\" />", "panel-top": "<rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\" /> <path d=\"M3 9h18\" />", "folder-tree": "<path d=\"M20 10a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-2.5a1 1 0 0 1-.8-.4l-.9-1.2A1 1 0 0 0 15 3h-2a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1Z\" /> <path d=\"M20 21a1 1 0 0 0 1-1v-3a1 1 0 0 0-1-1h-2.9a1 1 0 0 1-.88-.55l-.42-.85a1 1 0 0 0-.92-.6H13a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1Z\" /> <path d=\"M3 5a2 2 0 0 0 2 2h3\" /> <path d=\"M3 3v13a2 2 0 0 0 2 2h3\" />", "rocket": "<path d=\"M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z\" /> <path d=\"m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z\" /> <path d=\"M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0\" /> <path d=\"M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5\" />"}'''))


def _svg(name, color, width=2.0):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{LUCIDE[name]}</svg>')


_ICON_CACHE = {}


def _render(name, color, size, tile=None, width=2.0):
    from PySide6.QtSvg import QSvgRenderer
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if tile:  # rounded colour square, radius 24 %, glyph white and inset 20 %
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(tile))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
        inset = size * 0.2
        QSvgRenderer(QByteArray(_svg(name, "#FFFFFF", 2.2).encode())).render(
            p, QRectF(inset, inset, size - 2 * inset, size - 2 * inset))
    else:
        QSvgRenderer(QByteArray(_svg(name, color, width).encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def tile_icon(name, color="indigo"):
    """The signature icon: white Lucide glyph on a rounded colour tile."""
    key = ("tile", name, color)
    if key not in _ICON_CACHE:
        ic = QIcon()
        for s in (16, 20, 24, 32, 48, 64):
            pm = _render(name, None, s, TILE.get(color, color))
            for mode in (QIcon.Normal, QIcon.Active, QIcon.Selected):  # no tint on selected rows
                ic.addPixmap(pm, mode)
        _ICON_CACHE[key] = ic
    return _ICON_CACHE[key]


def glyph_icon(name, color=GLYPH):
    """Plain line icon for buttons and inputs."""
    key = ("glyph", name, color)
    if key not in _ICON_CACHE:
        ic = QIcon()
        for s in (16, 20, 24, 32):
            pm = _render(name, color, s)
            for mode in (QIcon.Normal, QIcon.Active, QIcon.Selected):
                ic.addPixmap(pm, mode)
        ic.addPixmap(_render(name, "#94A3B8", 16), QIcon.Disabled)
        _ICON_CACHE[key] = ic
    return _ICON_CACHE[key]


def ui_asset_dir():
    """Small SVGs the stylesheet points at (check mark, combo arrow)."""
    d = Path(tempfile.gettempdir()) / "advanced-outboxer-studio-ui"
    d.mkdir(exist_ok=True)
    for fname, svg in (("check.svg", _svg("check", "#FFFFFF", 3)),
                       ("chevron.svg", _svg("chevron-down", "#475569", 2.2)),
                       ("chevron-off.svg", _svg("chevron-down", "#94A3B8", 2.2))):
        f = d / fname
        if not f.exists() or f.read_text(encoding="utf-8") != svg:
            f.write_text(svg, encoding="utf-8")
    return d.as_posix()


def modern_qss():
    a = ui_asset_dir()
    return MODERN_QSS.replace("{ASSETS}", a)


MODERN_QSS = """
* { font-family: 'Segoe UI'; font-size: 10pt; font-weight: normal; color: #0F172A; }
QMainWindow, QDialog { background: #F6F7FB; }
QWidget#page, QScrollArea#page > QWidget > QWidget { background: transparent; }
QScrollArea { border: none; background: transparent; }
QToolTip { background: #0F172A; color: #FFFFFF; border: none; border-radius: 6px; padding: 5px 8px; }

/* cards */
QFrame#card, QGroupBox { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px; }
QGroupBox { margin-top: 26px; padding: 14px 14px 12px 14px; font-size: 11pt; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 4px; top: 2px;
    padding: 0 2px; color: #0F172A; }
QLabel#title { font-size: 16pt; font-weight: bold; }
QLabel#section { font-size: 12pt; font-weight: bold; }
QLabel#brand { font-size: 12pt; font-weight: bold; }
QLabel#muted, QLabel#hint { color: #64748B; }
QLabel#hint { font-size: 8.5pt; }
QLabel#caption { font-size: 9pt; font-weight: bold; color: #475569; }
QLabel#pillOk { background: #EEF2FF; color: #3730A3; border-radius: 10px; padding: 4px 10px; }
QLabel#pillWarn { background: #FEF2F2; color: #B91C1C; border-radius: 10px; padding: 4px 10px; }
QLabel#iconPreview { background: #F8FAFC; border: 1px dashed #CBD5E1; border-radius: 12px; color: #94A3B8; }

/* sidebar */
QFrame#side { background: #FFFFFF; border: none; border-right: 1px solid #E5E7EB; }
QListWidget#nav { border: none; outline: 0; background: transparent; font-size: 10.5pt; }
QListWidget#nav::item { padding: 8px 8px; margin: 1px 0; border-radius: 8px; color: #0F172A; }
QListWidget#nav::item:hover { background: #F3F4F6; }
QListWidget#nav::item:selected { background: #E8EEFF; color: #1E3A8A; }
QListWidget#nav::item:disabled { color: #94A3B8; background: transparent; }
QLabel#callout { background: #F8FAFC; border: 1px solid #E5E7EB; border-radius: 8px; padding: 10px 12px; }
QPushButton#seg { border: 1px solid #CBD5E1; border-radius: 0; padding: 6px 16px; background: #FFFFFF; color: #475569; }
QPushButton#seg:hover { background: #F1F5F9; }
QPushButton#seg:checked { background: #E8EEFF; color: #1E3A8A; border-color: #A5B4FC; font-weight: bold; }
QPushButton#segL { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#accent { color: #4338CA; border-color: #A5B4FC; font-weight: bold; }
QPushButton#accent:hover { background: #EEF2FF; }
QToolButton#sideLink { border: none; border-radius: 8px; padding: 8px 8px; text-align: left; font-size: 10.5pt; }
QToolButton#sideLink:hover { background: #F3F4F6; }

/* inputs */
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget {
    border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 6px; background: #FFFFFF;
    selection-background-color: #C7D2FE; selection-color: #0F172A; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #4F46E5; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QPlainTextEdit:disabled {
    background: #F1F5F9; color: #94A3B8; border-color: #E2E8F0; }
QPlainTextEdit#console { font-family: 'Consolas'; font-size: 9pt; background: #F8FAFC; border-color: #E5E7EB; }
QTextBrowser { border: none; padding: 10px 14px; }
QComboBox { padding-right: 24px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url({ASSETS}/chevron.svg); width: 14px; height: 14px; }
QComboBox::down-arrow:disabled { image: url({ASSETS}/chevron-off.svg); }
QComboBox QAbstractItemView { border: 1px solid #D9DEE7; border-radius: 8px; background: #FFFFFF; padding: 4px;
    outline: 0; selection-background-color: #E8EEFF; selection-color: #1E3A8A; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #CBD5E1; border-radius: 4px; background: #FFFFFF; }
QCheckBox::indicator:hover { border-color: #4F46E5; }
QCheckBox::indicator:checked { background: #4F46E5; border-color: #4F46E5; image: url({ASSETS}/check.svg); }
QCheckBox::indicator:disabled { background: #F1F5F9; border-color: #E2E8F0; }
QCheckBox:disabled { color: #94A3B8; }

/* buttons */
QPushButton { border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 14px; background: #FFFFFF; }
QPushButton:hover { background: #F1F5F9; }
QPushButton:pressed { background: #E2E8F0; }
QPushButton:disabled { color: #94A3B8; background: #F8FAFC; border-color: #E2E8F0; }
QPushButton#primary { background: #4F46E5; color: #FFFFFF; border: 1px solid #4338CA; font-weight: bold; }
QPushButton#primary:hover { background: #4338CA; }
QPushButton#primary:disabled { background: #A5B4FC; border-color: #A5B4FC; color: #FFFFFF; }
QPushButton#danger { color: #B91C1C; }
QPushButton#danger:hover { background: #FEF2F2; border-color: #FCA5A5; }
QToolButton { border: none; border-radius: 6px; padding: 4px; background: transparent; }
QToolButton:hover { background: #EEF2FF; }

/* lists, progress, menus, scrollbars */
QListWidget::item { padding: 4px 6px; border-radius: 6px; }
QListWidget::item:selected { background: #E8EEFF; color: #1E3A8A; }
QProgressBar { border: none; background: #E5E7EB; border-radius: 3px; max-height: 6px; color: transparent; }
QProgressBar::chunk { background: #4F46E5; border-radius: 3px; }
QProgressBar#withText { max-height: 18px; border-radius: 6px; color: #0F172A; text-align: center; }
QMenuBar { background: #FFFFFF; border-bottom: 1px solid #E5E7EB; padding: 2px 6px; }
QMenuBar::item { padding: 5px 10px; border-radius: 6px; background: transparent; }
QMenuBar::item:selected { background: #E8EEFF; color: #1E3A8A; }
QMenu { background: #FFFFFF; border: 1px solid #D9DEE7; border-radius: 10px; padding: 6px; icon-size: 24px; }
QMenu::item { padding: 6px 30px 6px 8px; border-radius: 6px; margin: 1px 0; }
QMenu::item:selected { background: #E8EEFF; color: #1E3A8A; }
QMenu::separator { height: 1px; background: #E5E7EB; margin: 5px 10px; }
QMenu::icon { padding-left: 4px; }
QStatusBar { background: #FFFFFF; border-top: 1px solid #E5E7EB; color: #475569; }
QStatusBar::item { border: none; }
QSplitter::handle { background: transparent; height: 10px; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 0 4px; }
QScrollBar::handle:horizontal { background: #CBD5E1; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { width: 0; height: 0; background: none; }
"""


def round_menu(menu):
    """Rounded, frameless menu (the stylesheet draws the white rounded panel)."""
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground)
    return menu


def toast(widget, text, ms=1600):
    """Small tooltip-style confirmation near the cursor instead of a message box."""
    QToolTip.showText(QCursor.pos() + QPoint(14, 10), text, widget, QRect(), ms)


def card(title=None, desc=None):
    """A white rounded card; returns (frame, body layout)."""
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    if title:
        t = QLabel(title)
        t.setObjectName("section")
        lay.addWidget(t)
    if desc:
        d = QLabel(desc)
        d.setObjectName("muted")
        d.setWordWrap(True)
        lay.addWidget(d)
    return f, lay



# ---------------------------------------------------------------------------
# Engines: Node.js, the Nativefier engine and Electron zips, by default all in <Studio>\Engines.
# Their paths and the default Electron version are kept in AdvancedOutboxerStudio.config.json.
# ---------------------------------------------------------------------------
ENGINES_DIR = APP_DIR / "Engines"
PACKAGES_DIR = ENGINES_DIR / "packages"      # nativefier-53.x.tgz, used to (re)install the engine
DOWNLOADS_DIR = ENGINES_DIR / "_downloads"   # temporary, emptied after each update
DEFAULT_ENGINE_PATHS = {
    "node_path": ENGINES_DIR / "node" / ("node.exe" if IS_WIN else "bin/node"),
    "nativefier_dir": ENGINES_DIR / "nativefier53",
    "electron_dir": ENGINES_DIR / "electron",
    "runtime_dir": ENGINES_DIR / "runtime",       # unpacked Electron folders for shared-runtime apps
    "webview2_dir": ENGINES_DIR / "webview2",     # WebView2 SDK versions for WebView2 apps
}
CONFIG_NAME = "AdvancedOutboxerStudio.config.json"
OLD_CONFIG_NAMES = ("NativefierStudio.config.json",)  # renamed automatically on first start
TESTED_ELECTRON_MAJOR = 44        # Nativefier 53 was tested with this Electron major
FALLBACK_MIN_NODE = (22, 13, 0)   # used when the engine's package.json can't be read
UPDATE_CHECK_EVERY = 12 * 3600    # seconds between automatic checks at start-up
NODE_INDEX_URL = "https://nodejs.org/dist/index.json"
NODE_DIST_URL = "https://nodejs.org/dist/v{v}/"
ELECTRON_LATEST_URL = "https://registry.npmjs.org/electron/latest"
ELECTRON_RELEASE_URL = "https://github.com/electron/electron/releases/download/v{v}/"
HTTP_HEADERS = {"User-Agent": "AdvancedOutboxerStudio/2.0"}


def host_arch():
    m = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64",
            "x86": "ia32", "i386": "ia32", "i686": "ia32"}.get(m, "x64")


HOST_PLATFORM = "win32" if IS_WIN else ("darwin" if sys.platform == "darwin" else "linux")
HOST_ARCH = host_arch()


def version_tuple(v):
    """'v26.11.1' / '44.7.0+wvcus' / '45.0.0-beta.2' -> (26, 11, 1); unknown -> ()."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", str(v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else ()


def is_newer(latest, current):
    lt, ct = version_tuple(latest), version_tuple(current)
    return bool(lt) and (not ct or lt > ct)


def short_path(p, n=70):
    """Long paths shortened in the middle for labels (the full path goes in the tooltip)."""
    s = str(p)
    return s if len(s) <= n else s[:22] + "…" + s[-(n - 23):]


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


_NODE_VERSION_CACHE = {}


def node_version_of(exe):
    """'v26.11.1' for a node executable, cached per file + mtime; '' if it doesn't run."""
    try:
        p = Path(exe)
        key = (str(p), p.stat().st_mtime)
    except OSError:
        return ""
    if key not in _NODE_VERSION_CACHE:
        try:
            out = subprocess.run([str(p), "-v"], capture_output=True, text=True, timeout=15,
                                 creationflags=_no_window()).stdout.strip()
            _NODE_VERSION_CACHE[key] = out if out.startswith("v") else ""
        except Exception:
            _NODE_VERSION_CACHE[key] = ""
    return _NODE_VERSION_CACHE[key]


def npm_cli_for(node_exe):
    """npm ships next to node.exe (Windows zip) or in ../lib (Linux/macOS tarballs)."""
    d = Path(node_exe).parent
    for c in (d / "node_modules" / "npm" / "bin" / "npm-cli.js",
              d.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"):
        if c.is_file():
            return c
    return None


def nativefier_cli_in(folder):
    """cli.js of an engine folder: an npm --prefix install, or a built source checkout."""
    f = Path(folder)
    for c in (f / "node_modules" / "nativefier" / "lib" / "cli.js", f / "lib" / "cli.js"):
        if c.is_file():
            return c
    return None


def nativefier_info(folder):
    """{'cli', 'version', 'min_node'} for an engine folder, or None."""
    cli = nativefier_cli_in(folder)
    if not cli:
        return None
    info = {"cli": cli, "version": "", "min_node": FALLBACK_MIN_NODE}
    try:
        pkg = json.loads((cli.parent.parent / "package.json").read_text(encoding="utf-8"))
        info["version"] = pkg.get("version", "")
        req = version_tuple(re.sub(r"[^\d.]", "", (pkg.get("engines") or {}).get("node", "")))
        if req:
            info["min_node"] = req
    except Exception:
        pass
    return info


ELECTRON_ZIP_RE = re.compile(r"^electron-v(.+)-([a-z0-9]+)-([a-z0-9]+)\.zip$", re.I)


def electron_zips(folder):
    """[(version, platform, arch, path, size)] for Electron zips in a folder, newest first."""
    res = []
    try:
        for p in Path(folder).iterdir():
            m = ELECTRON_ZIP_RE.match(p.name)
            if m and p.is_file():
                res.append((m.group(1), m.group(2), m.group(3), p, p.stat().st_size))
    except OSError:
        pass
    return sorted(res, key=lambda r: (version_tuple(r[0]), r[0]), reverse=True)


class StudioConfig:
    """Engine settings in AdvancedOutboxerStudio.config.json, next to the script.

    Paths inside the Studio folder are stored relative to it, so the whole folder can be moved
    or copied to another PC and keep working. An empty path means "the default in Engines".
    """
    DEFAULTS = {
        "node_path": "",
        "nativefier_dir": "",
        "electron_dir": "",
        "runtime_dir": "",
        "webview2_dir": "",
        "electron_version": DEFAULT_ELECTRON_VERSION,
        "node_channel": "current",       # "current" (newest) or "lts"
        "auto_check_updates": True,
        "latest": {},                    # last check: node_current, node_lts, electron, checked
    }

    def __init__(self, path=None):
        self.path = Path(path) if path else APP_DIR / CONFIG_NAME
        if not path and not self.path.exists():  # settings file from before the rename
            for old in OLD_CONFIG_NAMES:
                if (APP_DIR / old).is_file():
                    try:
                        os.replace(APP_DIR / old, self.path)
                    except OSError:
                        pass
                    break
        self.data = dict(self.DEFAULTS)
        self.load_error = None
        self.load()

    def load(self):
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                self.data.update({k: v for k, v in raw.items() if k in self.DEFAULTS})
        except Exception as ex:  # keep the broken file for the user, start from defaults
            self.load_error = str(ex)
            try:
                shutil.copy2(self.path, self.path.with_suffix(".json.bad"))
            except OSError:
                pass

    def save(self):
        out = {"_about": f"{APP_TITLE} settings. Empty paths mean the default inside the Engines folder; "
                         "relative paths are relative to the Studio folder."}
        out.update(self.data)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, key):
        return self.data.get(key, self.DEFAULTS.get(key))

    def set(self, key, value, save=True):
        self.data[key] = value
        if save:
            try:
                self.save()
            except OSError:
                pass

    def resolve(self, key):
        """Absolute Path for node_path / nativefier_dir / electron_dir."""
        v = (self.get(key) or "").strip()
        if not v:
            return DEFAULT_ENGINE_PATHS[key]
        p = Path(os.path.expandvars(v))
        return p if p.is_absolute() else (APP_DIR / p)

    def is_default(self, key):
        return not (self.get(key) or "").strip()

    def set_path(self, key, path, save=True):
        p = Path(path).resolve() if path else None
        if not p or p == DEFAULT_ENGINE_PATHS[key].resolve():
            value = ""
        else:
            try:
                value = str(p.relative_to(APP_DIR.resolve()))
            except ValueError:
                value = str(p)
        self.set(key, value, save)


def resolve_node(cfg):
    """(path or None, how) — the configured node, else the default in Engines, else system Node."""
    p = cfg.resolve("node_path")
    if p.is_file():
        return p, "custom" if not cfg.is_default("node_path") else "engines"
    if cfg.is_default("node_path"):
        sysnode = shutil.which("node")
        if sysnode:
            return Path(sysnode), "system"
    return None, "missing"


def migrate_old_layout(log=None):
    """Earlier Studio versions kept Electron zips in <Studio>\\electron: move them into Engines."""
    old = APP_DIR / "electron"
    new = DEFAULT_ENGINE_PATHS["electron_dir"]
    for d in (new, PACKAGES_DIR, DEFAULT_ENGINE_PATHS["runtime_dir"]):
        d.mkdir(parents=True, exist_ok=True)
    if old.is_dir():
        for z in old.glob("electron-v*.zip"):
            if not (new / z.name).exists():
                shutil.move(str(z), str(new / z.name))
                if log:
                    log(f"Moved {z.name} into {new}")
        try:
            old.rmdir()  # only if now empty
        except OSError:
            pass


# ---- network (runs in a worker thread) -------------------------------------
class Cancelled(Exception):
    pass


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url, timeout=30):
    return json.loads(http_get(url, timeout).decode("utf-8"))


def download_file(url, dest, job=None, timeout=60):
    """Stream url to dest (via dest.part), reporting progress to job; returns dest."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if job and job.cancelled:
                f.close()
                part.unlink(missing_ok=True)
                raise Cancelled()
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if job:
                job.report(done, total)
    os.replace(part, dest)
    return dest


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_sha256(shasums_text, filename):
    for line in shasums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    return None


def fetch_latest_versions():
    """{'node_current', 'node_lts', 'node_lts_name', 'electron', 'checked'} — errors per item."""
    res = {"checked": int(time.time())}
    errors = []
    try:
        index = http_json(NODE_INDEX_URL)
        want = f"win-{HOST_ARCH}-zip" if IS_WIN else None
        usable = [r for r in index if not want or want in r.get("files", [])]
        if usable:
            res["node_current"] = usable[0]["version"].lstrip("v")
            lts = next((r for r in usable if r.get("lts")), None)
            if lts:
                res["node_lts"] = lts["version"].lstrip("v")
                res["node_lts_name"] = lts["lts"]
    except Exception as ex:
        errors.append(f"Node.js: {ex}")
    try:
        res["electron"] = http_json(ELECTRON_LATEST_URL)["version"]
    except Exception as ex:
        errors.append(f"Electron: {ex}")
    try:
        res["webview2_sdk"] = latest_webview2_sdk()
    except Exception as ex:
        errors.append(f"WebView2 SDK: {ex}")
    res["errors"] = errors
    return res


def install_node(version, job):
    """Download the official Node.js zip, verify it, and swap it in as Engines\\node."""
    if not IS_WIN:
        raise RuntimeError("Automatic Node.js updates are only supported on Windows. "
                           "Install Node with your package manager and pick its path here.")
    name = f"node-v{version}-win-{HOST_ARCH}"
    base = NODE_DIST_URL.format(v=version)
    job.say(f"Downloading Node.js {version}…")
    zpath = download_file(base + name + ".zip", DOWNLOADS_DIR / (name + ".zip"), job)
    job.say("Verifying checksum…")
    want = expected_sha256(http_get(base + "SHASUMS256.txt").decode(), name + ".zip")
    got = sha256_of(zpath)
    if not want or want != got:
        zpath.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch for {name}.zip — the download was not used.")
    job.say("Unpacking…")
    target = DEFAULT_ENGINE_PATHS["node_path"].parent
    staging = target.with_name("node.new")
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        prefix = name + "/"
        for m in z.infolist():
            if job.cancelled:
                raise Cancelled()
            if not m.filename.startswith(prefix) or m.is_dir():
                continue
            rel = m.filename[len(prefix):]
            out = (staging / rel).resolve()
            if staging.resolve() not in out.parents:  # zip-slip guard
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    new_exe = staging / "node.exe"
    if node_version_of(new_exe) != f"v{version}":
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("The new node.exe did not start correctly — kept the current Node.")
    job.say("Switching to the new version…")
    old = target.with_name(f"node.old-{int(time.time())}")
    if target.exists():
        os.replace(target, old)
    os.replace(staging, target)
    shutil.rmtree(old, ignore_errors=True)
    zpath.unlink(missing_ok=True)
    _tidy_downloads()
    return target / "node.exe"


def download_electron(version, folder, job, plat=HOST_PLATFORM, arch=HOST_ARCH):
    """Download electron-v<version>-<plat>-<arch>.zip into folder, verified with SHASUMS256.txt."""
    name = f"electron-v{version}-{plat}-{arch}.zip"
    dest = Path(folder) / name
    if dest.is_file():
        job.say(f"{name} is already in the folder.")
        return dest
    base = ELECTRON_RELEASE_URL.format(v=version)
    job.say(f"Downloading {name}…")
    tmp = download_file(base + name, DOWNLOADS_DIR / name, job, timeout=120)
    job.say("Verifying checksum…")
    want = expected_sha256(http_get(base + "SHASUMS256.txt").decode(), name)
    if not want or want != sha256_of(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch for {name} — the download was not used.")
    Path(folder).mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp), str(dest))
    _tidy_downloads()
    return dest


def _tidy_downloads():
    try:
        DOWNLOADS_DIR.rmdir()  # only when empty
    except OSError:
        pass


class Job(QThread):
    """Runs fn(job) off the UI thread. fn may call job.say(text) and job.report(done, total)."""
    message = Signal(str)
    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.cancelled = False
        self._last = 0.0

    def say(self, text):
        self.message.emit(text)

    def report(self, done, total):
        now = time.monotonic()
        if now - self._last > 0.1 or (total and done >= total):
            self._last = now
            self.progress.emit(int(done >> 10), int(total >> 10))  # KB: fits in a Qt int

    def run(self):
        try:
            self.succeeded.emit(self.fn(self))
        except Cancelled:
            self.failed.emit("Cancelled.")
        except urllib.error.URLError as ex:
            self.failed.emit(f"Network error: {getattr(ex, 'reason', ex)}")
        except Exception as ex:
            self.failed.emit(str(ex) or ex.__class__.__name__)


# ---------------------------------------------------------------------------
# Shared Electron runtime: the app folder only holds its own code (app\) and a tiny launcher .exe;
# Electron itself is one unpacked folder that many apps use (path in electron-runtime.txt).
# ---------------------------------------------------------------------------
RUNTIME_FILE = "electron-runtime.txt"

LAUNCHER_CS = r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("{TITLE}")]
[assembly: AssemblyProduct("{TITLE}")]
[assembly: AssemblyDescription("{TITLE} - made by Outboxer Studio (shared Electron runtime)")]
[assembly: AssemblyFileVersion("{VERSION}")]
[assembly: AssemblyVersion("{VERSION}")]

static class Launcher
{
    const string Title = "{TITLE}";

    [STAThread]
    static int Main(string[] args)
    {
        string dir = Path.GetDirectoryName(Application.ExecutablePath);
        string cfg = Path.Combine(dir, "{RUNTIME_FILE}");
        string runtime = ReadRuntime(cfg, dir);
        string electron = runtime == null ? null : Path.Combine(runtime, "electron.exe");
        if (electron == null || !File.Exists(electron))
        {
            MessageBox.Show(Title + " can't start: the shared Electron runtime was not found.\n\n" +
                "Looked for:\n" + (electron ?? "(no path set)") + "\n\n" +
                "Open this file in Notepad and put the folder that contains electron.exe on its first line:\n" + cfg,
                Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        // ELECTRON_RUN_AS_NODE=1 (used by the bundled-server launcher): behave like node.exe
        bool asNode = Environment.GetEnvironmentVariable("ELECTRON_RUN_AS_NODE") == "1";
        string app = Path.Combine(dir, "app");
        if (!Directory.Exists(app) && File.Exists(app + ".asar")) app += ".asar";
        StringBuilder sb = new StringBuilder();
        if (!asNode) sb.Append(Quote(app));
        foreach (string a in args) { if (sb.Length > 0) sb.Append(' '); sb.Append(Quote(a)); }
        ProcessStartInfo psi = new ProcessStartInfo(electron, sb.ToString());
        psi.UseShellExecute = false;   // inherit the environment
        psi.WorkingDirectory = Environment.CurrentDirectory;
        if (asNode)                    // forward a server's console output (e.g. to its log file)
        {
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
        }
        try
        {
            using (Process p = Process.Start(psi))
            {
                TieToLauncher(p);
                Thread o = null, e = null;
                if (asNode)
                {
                    o = Pump(p.StandardOutput.BaseStream, Console.OpenStandardOutput());
                    e = Pump(p.StandardError.BaseStream, Console.OpenStandardError());
                }
                p.WaitForExit();       // so "wait until the app is closed" keeps working
                if (o != null) { o.Join(3000); e.Join(3000); }
                return p.ExitCode;
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(Title + " could not start Electron:\n" + electron + "\n\n" + ex.Message,
                Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    // ---- Electron ends together with this launcher (a Windows job object with kill-on-close).
    // Only Electron's main process is in the job (silent breakaway), so e.g. a browser opened from
    // a link is not closed with the app.
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters { public ulong R, W, O, RB, WB, OB; }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits
    {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll")]
    static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref ExtendedLimits info, int length);
    [DllImport("kernel32.dll")]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    static IntPtr job;   // stays open while the launcher runs

    static void TieToLauncher(Process p)
    {
        try
        {
            job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) return;
            ExtendedLimits info = new ExtendedLimits();
            info.Basic.LimitFlags = 0x2000 | 0x1000;   // KILL_ON_JOB_CLOSE | SILENT_BREAKAWAY_OK
            SetInformationJobObject(job, 9, ref info, Marshal.SizeOf(typeof(ExtendedLimits)));
            AssignProcessToJobObject(job, p.Handle);
        }
        catch { }   // best effort: without it the app still works normally
    }

    static Thread Pump(Stream from, Stream to)
    {
        Thread t = new Thread(delegate ()
        {
            byte[] buf = new byte[8192];
            int n;
            try
            {
                while ((n = from.Read(buf, 0, buf.Length)) > 0)
                {
                    try { to.Write(buf, 0, n); to.Flush(); } catch { }
                }
            }
            catch { }
        });
        t.IsBackground = true;
        t.Start();
        return t;
    }

    static string ReadRuntime(string cfg, string dir)
    {
        if (!File.Exists(cfg)) return null;
        foreach (string raw in File.ReadAllLines(cfg))
        {
            string line = raw.Trim().Trim('"');
            if (line.Length == 0 || line.StartsWith("#")) continue;
            line = Environment.ExpandEnvironmentVariables(line);
            return Path.IsPathRooted(line) ? line : Path.GetFullPath(Path.Combine(dir, line));
        }
        return null;
    }

    // Windows command-line quoting (CommandLineToArgvW rules)
    static string Quote(string s)
    {
        if (s.Length > 0 && s.IndexOfAny(new char[] { ' ', '\t', '"' }) < 0) return s;
        StringBuilder b = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in s)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') b.Append('\\', slashes * 2 + 1);
            else b.Append('\\', slashes);
            slashes = 0;
            b.Append(c);
        }
        b.Append('\\', slashes * 2);
        b.Append('"');
        return b.ToString();
    }
}
'''


def find_csc():
    """The C# compiler that ships with Windows (.NET Framework 4.x)."""
    win = os.environ.get("WINDIR", r"C:\Windows")
    for fw in ("Framework64", "Framework"):
        c = Path(win) / "Microsoft.NET" / fw / "v4.0.30319" / "csc.exe"
        if c.is_file():
            return c
    return None


def runtime_name(version, plat=HOST_PLATFORM, arch=HOST_ARCH):
    return f"electron-v{version}-{plat}-{arch}"


def runtime_version(folder):
    try:
        return (Path(folder) / "version").read_text(encoding="utf-8").strip().lstrip("v")
    except OSError:
        return ""


def runtimes_in(folder):
    """[(version, path, size)] of unpacked runtimes (folders with electron.exe) in folder."""
    res = []
    try:
        for p in Path(folder).iterdir():
            if p.is_dir() and (p / ("electron.exe" if IS_WIN else "electron")).is_file():
                size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                res.append((runtime_version(p) or "?", p, size))
    except OSError:
        pass
    return sorted(res, key=lambda r: version_tuple(r[0]), reverse=True)


def ensure_runtime(runtime_dir, version, zip_dir, log=print):
    """Make sure runtime_dir holds Electron (electron.exe); unpack it from the zip if needed."""
    runtime_dir = Path(runtime_dir)
    exe = runtime_dir / ("electron.exe" if IS_WIN else "electron")
    if exe.is_file():
        have = runtime_version(runtime_dir)
        if have and have != version:
            log(f"   note: this runtime is Electron {have}; the app was prepared for {version}")
        return runtime_dir
    if runtime_dir.exists() and any(runtime_dir.iterdir()):
        raise RuntimeError(f"{runtime_dir} is not empty but has no electron.exe — choose an empty folder "
                           "or a folder that already holds Electron.")
    z = Path(zip_dir) / f"{runtime_name(version)}.zip"
    if not z.is_file():
        raise RuntimeError(f"The Electron zip is missing: {z}")
    log(f"   unpacking Electron {version} into the shared runtime folder (once)…")
    staging = runtime_dir.with_name(runtime_dir.name + ".unpacking")
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(z) as zf:
        root = staging.resolve()
        for m in zf.infolist():
            out = (staging / m.filename).resolve()
            if root != out and root not in out.parents:  # zip-slip guard
                continue
            if m.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if not IS_WIN and (m.external_attr >> 16) & 0o111:
                out.chmod(0o755)
    runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    if runtime_dir.exists():
        runtime_dir.rmdir()
    os.replace(staging, runtime_dir)
    return runtime_dir


def compile_launcher(out_exe, title, version, icon=None, log=print):
    csc = find_csc()
    if not csc:
        raise RuntimeError("The Windows C# compiler (csc.exe, part of .NET Framework 4) was not found.")
    safe = title.replace("\\", "\\\\").replace('"', '\\"')
    ver = ".".join((list(map(str, version_tuple(version))) or ["1", "0", "0"]) + ["0"])
    src = (LAUNCHER_CS.replace("{TITLE}", safe).replace("{VERSION}", ver)
           .replace("{RUNTIME_FILE}", RUNTIME_FILE))
    work = Path(tempfile.mkdtemp(prefix="outboxer-launcher-"))
    try:
        cs = work / "launcher.cs"
        cs.write_text(src, encoding="utf-8")
        cmd = [str(csc), "/nologo", "/target:winexe", "/optimize+", "/platform:anycpu",
               "/r:System.Windows.Forms.dll", f"/out:{work / 'app.exe'}"]
        if icon and Path(icon).is_file():
            cmd.append(f"/win32icon:{icon}")
        cmd.append(str(cs))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=_no_window())
        if r.returncode != 0:
            raise RuntimeError("Compiling the launcher failed:\n" + (r.stdout + r.stderr).strip()[:1500])
        shutil.move(str(work / "app.exe"), str(out_exe))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return Path(out_exe)


def icon_for_launcher(app_dir, work_dir):
    """An .ico for the launcher: the app's icon.ico, or its icon.png converted (needs Pillow)."""
    ico = Path(app_dir) / "icon.ico"
    if ico.is_file():
        return ico
    png = Path(app_dir) / "icon.png"
    if png.is_file():
        try:
            from PIL import Image
            out = Path(work_dir) / "icon.ico"
            Image.open(png).convert("RGBA").save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                                          (64, 64), (128, 128), (256, 256)])
            return out
        except Exception:
            return None
    return None


def make_shared_app(built_dir, runtime_dir, title, app_version, log=print):
    """Turn a normal Nativefier build (Name-win32-x64) into a small shared-runtime app, in place."""
    built = Path(built_dir)
    res = built / "resources"
    src_app = res / "app" if (res / "app").is_dir() else res / "app.asar"
    if not src_app.exists():
        raise RuntimeError(f"No app code found in {res}")
    small = built.with_name(built.name + ".shared")
    shutil.rmtree(small, ignore_errors=True)
    small.mkdir()
    if src_app.is_dir():
        shutil.copytree(src_app, small / "app")
    else:
        shutil.copy2(src_app, small / "app.asar")
    icon = icon_for_launcher(src_app if src_app.is_dir() else res, small)
    exe_name = next((p.name for p in built.glob("*.exe")), f"{title}.exe")
    compile_launcher(small / exe_name, title, app_version, icon, log)
    if icon and icon.parent == small:
        icon.unlink(missing_ok=True)
    (small / RUNTIME_FILE).write_text(
        f"{runtime_dir}\n"
        "# The first line is the folder with electron.exe that this app runs on (the shared Electron runtime).\n"
        "# You can change it, e.g. to another Electron version or a network folder. Relative paths start\n"
        "# from this app folder; %VARIABLES% like %LOCALAPPDATA% are allowed.\n", encoding="utf-8")
    shutil.rmtree(built)
    os.replace(small, built)
    return built


WEBVIEW2_APP_CS = r'''// Outboxer Studio — WebView2 app host. One generic program; everything app-specific is in app.json.
// C# 5 (compiles with the csc.exe that ships with Windows / .NET Framework 4.x).
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("{TITLE}")]
[assembly: AssemblyProduct("{TITLE}")]
[assembly: AssemblyDescription("{TITLE}")]
[assembly: AssemblyCompany("{COMPANY}")]
[assembly: AssemblyCopyright("{COPYRIGHT}")]
[assembly: AssemblyFileVersion("{VERSION}")]
[assembly: AssemblyVersion("{VERSION}")]

static class Cfg
{
    static Dictionary<string, object> d = new Dictionary<string, object>();

    public static void Load(string path)
    {
        var js = new JavaScriptSerializer();
        js.MaxJsonLength = int.MaxValue;
        d = js.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8));
    }
    public static object Raw(string k) { object v; return d.TryGetValue(k, out v) ? v : null; }
    public static string Str(string k, string def = "") { object v = Raw(k); return v == null ? def : Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture); }
    public static bool Bool(string k) { object v = Raw(k); return v is bool ? (bool)v : false; }
    public static int Int(string k, int def = 0) { object v = Raw(k); if (v == null) return def; try { return Convert.ToInt32(v); } catch { return def; } }
    public static double Num(string k, double def) { object v = Raw(k); if (v == null) return def; try { return Convert.ToDouble(v, System.Globalization.CultureInfo.InvariantCulture); } catch { return def; } }
    public static Dictionary<string, object> Obj(string k) { return Raw(k) as Dictionary<string, object>; }
    public static ArrayList List(string k) { return ToList(Raw(k)); }
    public static ArrayList ToList(object v) { return v as ArrayList ?? (v is object[] ? new ArrayList((object[])v) : null); }
}

static class Native
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)] public static extern int SetCurrentProcessExplicitAppUserModelID(string id);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int RegisterWindowMessage(string msg);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, int msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint mods, uint vk);
    [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr h);
    [DllImport("user32.dll")] public static extern bool FlashWindowEx(ref FLASHWINFO fi);
    [StructLayout(LayoutKind.Sequential)]
    public struct FLASHWINFO { public uint cbSize; public IntPtr hwnd; public uint dwFlags; public uint uCount; public uint dwTimeout; }
    public static readonly IntPtr HWND_BROADCAST = new IntPtr(0xffff);

    // ---- job object: a child (the bundled server) ends together with this app
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit; public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize; public uint ActiveProcessLimit;
        public UIntPtr Affinity; public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong R, W, O, RB, WB, OB; }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits { public BasicLimits Basic; public IoCounters Io; public UIntPtr A, B, C, D; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr a, string n);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr j, int c, ref ExtendedLimits i, int l);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr j, IntPtr p);
    static IntPtr job;
    public static void TieToApp(Process p)
    {
        try
        {
            if (job == IntPtr.Zero)
            {
                job = CreateJobObject(IntPtr.Zero, null);
                var info = new ExtendedLimits();
                info.Basic.LimitFlags = 0x2000; // KILL_ON_JOB_CLOSE
                SetInformationJobObject(job, 9, ref info, Marshal.SizeOf(typeof(ExtendedLimits)));
            }
            AssignProcessToJobObject(job, p.Handle);
        }
        catch { }
    }
}

// Taskbar overlay badge (unread counter)
[ComImport, Guid("ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface ITaskbarList3
{
    void HrInit(); void AddTab(IntPtr h); void DeleteTab(IntPtr h); void ActivateTab(IntPtr h); void SetActiveAlt(IntPtr h);
    void MarkFullscreenWindow(IntPtr h, [MarshalAs(UnmanagedType.Bool)] bool f);
    void SetProgressValue(IntPtr h, ulong done, ulong total); void SetProgressState(IntPtr h, int flags);
    void RegisterTab(IntPtr t, IntPtr m); void UnregisterTab(IntPtr t); void SetTabOrder(IntPtr t, IntPtr b);
    void SetTabActive(IntPtr t, IntPtr m, uint r); void ThumbBarAddButtons(IntPtr h, uint c, IntPtr b);
    void ThumbBarUpdateButtons(IntPtr h, uint c, IntPtr b); void ThumbBarSetImageList(IntPtr h, IntPtr l);
    void SetOverlayIcon(IntPtr h, IntPtr icon, [MarshalAs(UnmanagedType.LPWStr)] string desc);
}
[ComImport, Guid("56FDF344-FD6D-11d0-958A-006097C9A090"), ClassInterface(ClassInterfaceType.None)]
class TaskbarListClass { }

static class App
{
    public static string Dir, DataDir, Name, Home, AppId;
    public static Icon AppIcon;
    public static int ShowMsg;
    public static MainForm MainWindow;
    public static readonly List<MainForm> Windows = new List<MainForm>();
    static Task<CoreWebView2Environment> envTask;
    static Process server;
    static Mutex mutex;

    [STAThread]
    static int Main(string[] args)
    {
        Dir = Path.GetDirectoryName(Application.ExecutablePath);
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        try { Cfg.Load(Path.Combine(Dir, "app.json")); }
        catch (Exception ex)
        {
            MessageBox.Show("app.json next to this program is missing or damaged:\n\n" + ex.Message,
                Path.GetFileNameWithoutExtension(Application.ExecutablePath), MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        Name = Cfg.Str("name", Path.GetFileNameWithoutExtension(Application.ExecutablePath));
        Home = Cfg.Str("targetUrl");
        foreach (string a in args) if (a.StartsWith("http://") || a.StartsWith("https://")) Home = a;
        AppId = "OutboxerStudio." + Regex.Replace(Name, "[^A-Za-z0-9]", "");
        try { Native.SetCurrentProcessExplicitAppUserModelID(AppId); } catch { }
        ShowMsg = Native.RegisterWindowMessage("NFS_SHOW_" + AppId);

        if (Cfg.Bool("singleInstance"))
        {
            bool created;
            mutex = new Mutex(true, "Local\\" + AppId, out created);
            if (!created)
            {
                Native.PostMessage(Native.HWND_BROADCAST, ShowMsg, IntPtr.Zero, IntPtr.Zero);
                return 0;
            }
        }

        string runtime = null;
        try { runtime = CoreWebView2Environment.GetAvailableBrowserVersionString(); } catch { }
        if (string.IsNullOrEmpty(runtime))
        {
            if (MessageBox.Show(Name + " needs the Microsoft Edge WebView2 Runtime, which is not installed on this PC.\n\n" +
                "It is free and comes with Windows 10/11 — open the download page now?", Name,
                MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes)
                Process.Start("https://go.microsoft.com/fwlink/p/?LinkId=2124703");
            return 1;
        }

        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        DataDir = Cfg.Bool("portable") ? Path.Combine(Dir, "Data")
            : Path.Combine(local, "OutboxerStudio", "Apps", SafeName(Name));
        if (!Cfg.Bool("portable") && !Directory.Exists(DataDir))
        {   // apps built before the rename kept their data under NativefierStudio\Apps: bring it along
            string old = Path.Combine(local, "NativefierStudio", "Apps", SafeName(Name));
            try
            {
                if (Directory.Exists(old)) { Directory.CreateDirectory(Path.GetDirectoryName(DataDir)); Directory.Move(old, DataDir); }
            }
            catch { }
        }
        Directory.CreateDirectory(DataDir);
        try { AppIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

        MainWindow = new MainForm(Home, null, null);
        Application.Run(MainWindow);
        StopServer();
        return 0;
    }

    public static string SafeName(string s)
    {
        foreach (char c in Path.GetInvalidFileNameChars()) s = s.Replace(c, '_');
        return s.Trim().Length == 0 ? "App" : s.Trim();
    }

    public static Task<CoreWebView2Environment> Env()
    {
        if (envTask == null)
        {
            var o = new CoreWebView2EnvironmentOptions();
            string extra = Cfg.Str("browserArguments");
            string fromEnv = Environment.GetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS");
            if (!string.IsNullOrEmpty(fromEnv)) extra = (extra + " " + fromEnv).Trim();
            if (extra.Length > 0) o.AdditionalBrowserArguments = extra;
            if (Cfg.Str("lang").Length > 0) o.Language = Cfg.Str("lang");
            o.AllowSingleSignOnUsingOSPrimaryAccount = true;
            envTask = CoreWebView2Environment.CreateAsync(null, Path.Combine(DataDir, "WebView2"), o);
        }
        return envTask;
    }

    // ---- URL rules (same idea as Nativefier's linkIsInternal)
    static readonly string[] LoginHosts = {
        "accounts.google.com", "accounts.youtube.com", "login.microsoftonline.com", "login.live.com",
        "login.microsoft.com", "account.microsoft.com", "appleid.apple.com", "idmsa.apple.com",
        "github.com/login", "github.com/session", "www.facebook.com/login", "m.facebook.com/login",
        "twitter.com/i/flow/login", "x.com/i/flow/login", "auth0.com", "okta.com", "login.yahoo.com" };

    public static string BaseDomain(string host)
    {
        host = (host ?? "").ToLowerInvariant();
        if (host.StartsWith("www.")) host = host.Substring(4);
        string[] p = host.Split('.');
        if (p.Length <= 2) return host;
        int keep = (p[p.Length - 1].Length == 2 && p[p.Length - 2].Length <= 3) ? 3 : 2;  // e.g. co.uk, com.eg
        return string.Join(".", p, p.Length - keep, keep);
    }

    public static bool IsInternal(string url)
    {
        Uri u, h;
        if (!Uri.TryCreate(url, UriKind.Absolute, out u)) return false;
        if (u.Scheme == "about" || u.Scheme == "blob" || u.Scheme == "data" || u.Scheme == "javascript") return true;
        if (u.Scheme != "http" && u.Scheme != "https" && u.Scheme != "file") return false;
        string rx = Cfg.Str("internalUrls");
        if (rx.Length > 0)
        {
            try { if (Regex.IsMatch(url, rx)) return true; } catch { }
        }
        if (!Uri.TryCreate(Home, UriKind.Absolute, out h)) return false;
        if (Cfg.Bool("strictInternalUrls")) return u.Host == h.Host && u.Port == h.Port;
        if (BaseDomain(u.Host) == BaseDomain(h.Host)) return true;
        string hp = (u.Host + u.AbsolutePath).ToLowerInvariant();
        foreach (string l in LoginHosts) if (hp.StartsWith(l) || u.Host.EndsWith("." + l) || u.Host == l) return true;
        return false;
    }

    public static void OpenExternal(string url)
    {
        if (Cfg.Bool("blockExternalUrls")) return;
        Uri u;
        if (!Uri.TryCreate(url, UriKind.Absolute, out u)) return;
        string s = u.Scheme.ToLowerInvariant();
        if (s == "file" || s == "javascript" || s == "data" || s == "vbscript") return;  // never hand these to the shell
        try { Process.Start(u.AbsoluteUri); } catch { }
    }

    // ---- bundled local server (Server tab)
    public static bool StartServerIfNeeded()
    {
        var srv = Cfg.Obj("server");
        if (srv == null) return true;
        if (Answers(Home)) return true;
        string script = Path.Combine(Dir, Convert.ToString(srv["script"]));
        string node = srv.ContainsKey("node") ? Convert.ToString(srv["node"]) : "node";
        if (node != "node" && !Path.IsPathRooted(node)) node = Path.Combine(Dir, node);
        node = Environment.ExpandEnvironmentVariables(node);
        string log = Path.Combine(Path.GetDirectoryName(script), "server.log");
        try
        {
            var psi = new ProcessStartInfo(node, "\"" + script + "\"");
            psi.UseShellExecute = false; psi.CreateNoWindow = true;
            psi.WorkingDirectory = Path.GetDirectoryName(script);
            psi.RedirectStandardOutput = true; psi.RedirectStandardError = true;
            server = Process.Start(psi);
            if (!(srv.ContainsKey("stopOnClose") && srv["stopOnClose"] is bool && !(bool)srv["stopOnClose"])) Native.TieToApp(server);
            var w = new StreamWriter(log, true, Encoding.UTF8); w.AutoFlush = true;
            w.WriteLine("---- " + DateTime.Now + " started " + node);
            server.OutputDataReceived += (s, e) => { if (e.Data != null) lock (w) w.WriteLine(e.Data); };
            server.ErrorDataReceived += (s, e) => { if (e.Data != null) lock (w) w.WriteLine(e.Data); };
            server.BeginOutputReadLine(); server.BeginErrorReadLine();
        }
        catch (Exception ex)
        {
            MessageBox.Show("Could not start the app's server with:\n" + node + "\n\n" + ex.Message, Name,
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
        var until = DateTime.Now.AddSeconds(30);
        while (DateTime.Now < until)
        {
            if (Answers(Home)) return true;
            if (server.HasExited)
            {   // e.g. "address already in use": another copy may be serving the port already
                Thread.Sleep(500);
                if (Answers(Home)) return true;
                break;
            }
            Thread.Sleep(250);
        }
        string tail = "";
        try
        {
            string[] lines = File.ReadAllLines(log);
            tail = string.Join("\n", lines, Math.Max(0, lines.Length - 8), Math.Min(8, lines.Length));
        }
        catch { }
        MessageBox.Show("The app's server did not start.\n\nLast lines of " + log + ":\n\n" + tail, Name,
            MessageBoxButtons.OK, MessageBoxIcon.Error);
        return false;
    }

    // Is something accepting connections at the URL's host:port? For "localhost" both 127.0.0.1 and ::1
    // are tried directly (Windows takes ~2 s to refuse a connection, so trying ::1 first is too slow).
    static bool Answers(string url)
    {
        Uri u;
        if (!Uri.TryCreate(url, UriKind.Absolute, out u)) return false;
        var hosts = new List<string>();
        if (u.IsLoopback || u.Host == "localhost") { hosts.Add("127.0.0.1"); hosts.Add("::1"); }
        else hosts.Add(u.DnsSafeHost);
        foreach (string h in hosts)
        {
            try
            {
                using (var c = new System.Net.Sockets.TcpClient(h.Contains(":") ? System.Net.Sockets.AddressFamily.InterNetworkV6
                                                                               : System.Net.Sockets.AddressFamily.InterNetwork))
                {
                    var ar = c.BeginConnect(h, u.Port, null, null);
                    if (ar.AsyncWaitHandle.WaitOne(1500) && c.Connected) { c.EndConnect(ar); return true; }
                }
            }
            catch { }
        }
        return false;
    }

    static void StopServer()
    {
        var srv = Cfg.Obj("server");
        if (server == null || srv == null) return;
        bool stop = !(srv.ContainsKey("stopOnClose") && srv["stopOnClose"] is bool && !(bool)srv["stopOnClose"]);
        try { if (stop && !server.HasExited) server.Kill(); } catch { }
    }
}

class MainForm : Form
{
    readonly WebView2 web = new WebView2();
    readonly MenuStrip menu = new MenuStrip();
    readonly bool isMain;
    readonly string startUrl;
    CoreWebView2NewWindowRequestedEventArgs pending;
    CoreWebView2Deferral pendingDeferral;
    NotifyIcon tray;
    bool quitting, fullScreen, startHidden;
    bool ownNav;   // the next navigation was started by the app itself (home, back, reload…), not by the page
    FormBorderStyle savedBorder; FormWindowState savedState;
    int lastCount;
    readonly Dictionary<Keys, Action> shortcuts = new Dictionary<Keys, Action>();
    readonly List<Dictionary<string, object>> hotkeys = new List<Dictionary<string, object>>();

    public MainForm(string url, CoreWebView2NewWindowRequestedEventArgs pendingArgs, CoreWebView2Deferral deferral)
    {
        isMain = pendingArgs == null;
        startUrl = url; pending = pendingArgs; pendingDeferral = deferral;
        ownNav = true;   // the first page of a window (incl. a sign-in pop-up) is always allowed
        App.Windows.Add(this);
        Text = App.Name;
        if (App.AppIcon != null) Icon = App.AppIcon;
        StartPosition = FormStartPosition.WindowsDefaultLocation;
        KeyPreview = true;

        int w = Cfg.Int("width", 1280), h = Cfg.Int("height", 800);
        if (!isMain && pending != null && pending.WindowFeatures != null && pending.WindowFeatures.HasSize)
        {
            w = (int)pending.WindowFeatures.Width; h = (int)pending.WindowFeatures.Height;
        }
        Size = new Size(Math.Max(w, 200), Math.Max(h, 150));
        int minW = Cfg.Int("minWidth"), minH = Cfg.Int("minHeight"), maxW = Cfg.Int("maxWidth"), maxH = Cfg.Int("maxHeight");
        if (minW > 0 || minH > 0) MinimumSize = new Size(minW, minH);
        if (maxW > 0 || maxH > 0) MaximumSize = new Size(maxW > 0 ? maxW : 100000, maxH > 0 ? maxH : 100000);
        if (isMain)
        {
            if (Cfg.Raw("x") != null && Cfg.Raw("y") != null && (Cfg.Int("x") > 0 || Cfg.Int("y") > 0))
            {
                StartPosition = FormStartPosition.Manual; Location = new Point(Cfg.Int("x"), Cfg.Int("y"));
            }
            RestoreWindowState();
            if (Cfg.Bool("maximize")) WindowState = FormWindowState.Maximized;
            if (Cfg.Bool("hideWindowFrame")) FormBorderStyle = FormBorderStyle.None;
            TopMost = Cfg.Bool("alwaysOnTop");
            startHidden = Cfg.Str("tray") == "start-in-tray";
        }
        string bg = Cfg.Str("backgroundColor");
        if (bg.Length > 0) { try { BackColor = ColorTranslator.FromHtml(bg); web.DefaultBackgroundColor = BackColor; } catch { } }

        web.Dock = DockStyle.Fill;
        Controls.Add(web);
        BuildMenu();
        menu.Visible = Cfg.Bool("showMenuBar");
        Controls.Add(menu);
        MainMenuStrip = menu;
        if (isMain && (Cfg.Str("tray") == "true" || startHidden)) SetupTray();
        Load += async (s, e) => await InitAsync();
        if (isMain && Cfg.Bool("fullScreen")) Shown += (s, e) => SetFullScreen(true);
        if (isMain) Shown += (s, e) => RegisterGlobalShortcuts();
        if (startHidden)
        {   // start in the tray: the page still loads (for notifications/counter), the window stays hidden
            Opacity = 0; ShowInTaskbar = false;
            Shown += (s, e) => BeginInvoke(new Action(() => { Hide(); Opacity = 1; ShowInTaskbar = true; }));
        }
    }

    async Task InitAsync()
    {
        try
        {
            var env = await App.Env();
            await web.EnsureCoreWebView2Async(env);
        }
        catch (Exception ex)
        {
            MessageBox.Show("WebView2 could not start:\n\n" + ex.Message, App.Name, MessageBoxButtons.OK, MessageBoxIcon.Error);
            if (isMain) Application.Exit(); else Close();
            return;
        }
        var core = web.CoreWebView2;
        var st = core.Settings;
        st.AreDefaultContextMenusEnabled = !Cfg.Bool("disableContextMenu");
        st.AreDevToolsEnabled = !Cfg.Bool("disableDevTools");
        st.IsStatusBarEnabled = true;
        st.IsZoomControlEnabled = true;
        if (Cfg.Str("userAgent").Length > 0) st.UserAgent = Cfg.Str("userAgent");

        await AddInjections(core);
        core.NavigationStarting += OnNavigationStarting;
        core.NewWindowRequested += OnNewWindowRequested;
        core.DocumentTitleChanged += (s, e) => OnTitle(core.DocumentTitle);
        core.ContainsFullScreenElementChanged += (s, e) => SetFullScreen(core.ContainsFullScreenElement);
        core.WindowCloseRequested += (s, e) => { if (!isMain) Close(); };
        core.PermissionRequested += OnPermission;
        core.BasicAuthenticationRequested += OnBasicAuth;
        core.DownloadStarting += OnDownload;
        core.ProcessFailed += (s, e) =>
        {
            if (e.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited) return;
            if (MessageBox.Show(this, "The page stopped working. Reload it?", App.Name, MessageBoxButtons.YesNo) == DialogResult.Yes)
                try { ownNav = true; web.Reload(); } catch { }
        };

        if (pending != null)
        {
            pending.NewWindow = core;   // keeps window.opener, e.g. for sign-in pop-ups
            pending.Handled = true;
            pendingDeferral.Complete();
            pending = null;
            return;
        }
        if (isMain && Cfg.Bool("clearCache"))
        {
            try { await core.Profile.ClearBrowsingDataAsync(); } catch { }
        }
        double zoom = Cfg.Num("zoom", 1.0);
        if (zoom > 0 && Math.Abs(zoom - 1.0) > 0.001) web.ZoomFactor = zoom;
        if (isMain && Cfg.Obj("server") != null)
        {
            Text = App.Name + " — starting…";
            bool ok = await Task.Run(() => App.StartServerIfNeeded());
            Text = App.Name;
            if (!ok) { Application.Exit(); return; }
        }
        try { ownNav = true; core.Navigate(startUrl); }
        catch (Exception ex) { MessageBox.Show("Cannot open " + startUrl + "\n\n" + ex.Message, App.Name); }
    }

    async Task AddInjections(CoreWebView2 core)
    {
        var list = Cfg.List("inject");
        if (list == null) return;
        var js = new JavaScriptSerializer();
        foreach (object o in list)
        {
            string file = Path.Combine(App.Dir, Convert.ToString(o));
            if (!File.Exists(file)) continue;
            string text = File.ReadAllText(file, Encoding.UTF8);
            string code;
            if (file.EndsWith(".css", StringComparison.OrdinalIgnoreCase))
                code = "(function(){var css=" + js.Serialize(text) + ";function add(){var s=document.createElement('style');" +
                       "s.setAttribute('data-outboxer-studio','');s.textContent=css;(document.head||document.documentElement).appendChild(s);}" +
                       "if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',add);else add();})();";
            else
                code = "(function(){function run(){try{(0,eval)(" + js.Serialize(text + "\n//# sourceURL=" + Path.GetFileName(file)) +
                       ");}catch(e){console.error('inject " + Path.GetFileName(file) + "',e);}}" +
                       "if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',run);else run();})();";
            try { await core.AddScriptToExecuteOnDocumentCreatedAsync(code); } catch { }
        }
    }

    void OnNavigationStarting(object sender, CoreWebView2NavigationStartingEventArgs e)
    {
        // like Nativefier: when the page leaves for another site (link or script), that site opens in the
        // default browser (or is blocked). Server redirects (e.g. during sign-in) are followed in the app.
        if (e.IsRedirected) return;
        if (ownNav) { ownNav = false; return; }
        if (App.IsInternal(e.Uri)) return;
        e.Cancel = true;
        App.OpenExternal(e.Uri);
    }

    void OnNewWindowRequested(object sender, CoreWebView2NewWindowRequestedEventArgs e)
    {
        if (App.IsInternal(e.Uri) || e.Uri == "about:blank" || e.Uri == "")
        {
            var d = e.GetDeferral();
            var f = new MainForm(e.Uri, e, d);
            f.Show();
        }
        else
        {
            e.Handled = true;
            App.OpenExternal(e.Uri);
        }
    }

    void OnPermission(object sender, CoreWebView2PermissionRequestedEventArgs e)
    {
        var k = e.PermissionKind;
        bool sensitive = k == CoreWebView2PermissionKind.Microphone || k == CoreWebView2PermissionKind.Camera ||
                         k == CoreWebView2PermissionKind.Geolocation || k == CoreWebView2PermissionKind.Notifications ||
                         k == CoreWebView2PermissionKind.ClipboardRead || k == CoreWebView2PermissionKind.OtherSensors;
        if (!sensitive) return;   // leave the rest to WebView2's own prompt
        e.State = App.IsInternal(e.Uri) ? CoreWebView2PermissionState.Allow : CoreWebView2PermissionState.Deny;
    }

    void OnBasicAuth(object sender, CoreWebView2BasicAuthenticationRequestedEventArgs e)
    {
        // saved credentials are only given to the app's own site, never to other hosts
        string user = Cfg.Str("basicAuthUsername");
        if (user.Length == 0 || !App.IsInternal(e.Uri)) return;
        e.Response.UserName = user;
        e.Response.Password = Cfg.Str("basicAuthPassword");
    }

    void OnDownload(object sender, CoreWebView2DownloadStartingEventArgs e)
    {
        var opt = Cfg.Obj("fileDownloadOptions");
        if (opt == null) return;
        if (opt.ContainsKey("directory"))
        {
            string dir = Environment.ExpandEnvironmentVariables(Convert.ToString(opt["directory"]));
            try { Directory.CreateDirectory(dir); e.ResultFilePath = Path.Combine(dir, Path.GetFileName(e.ResultFilePath)); } catch { }
        }
        if (opt.ContainsKey("saveAs") && opt["saveAs"] is bool && (bool)opt["saveAs"])
        {
            var dlg = new SaveFileDialog();
            dlg.FileName = Path.GetFileName(e.ResultFilePath);
            dlg.InitialDirectory = Path.GetDirectoryName(e.ResultFilePath);
            if (dlg.ShowDialog(this) == DialogResult.OK) e.ResultFilePath = dlg.FileName;
            else e.Cancel = true;
        }
    }

    void OnTitle(string title)
    {
        Text = string.IsNullOrEmpty(title) ? App.Name : title;
        if (tray != null) tray.Text = Truncate(Text, 63);
        if (!isMain || !Cfg.Bool("counter")) return;
        var m = Regex.Match(title ?? "", @"[\(\[]\s*(\d+)\+?\s*[\)\]]");
        int n = m.Success ? int.Parse(m.Groups[1].Value) : 0;
        SetBadge(n);
        if (n > lastCount && !Focused && !ContainsFocus) Flash();
        lastCount = n;
    }

    static string Truncate(string s, int n) { return s.Length <= n ? s : s.Substring(0, n - 1) + "…"; }

    void SetBadge(int n)
    {
        try
        {
            var tb = (ITaskbarList3)new TaskbarListClass();
            tb.HrInit();
            if (n <= 0) { tb.SetOverlayIcon(Handle, IntPtr.Zero, ""); return; }
            using (var bmp = new Bitmap(16, 16))
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
                g.FillEllipse(Brushes.Red, 0, 0, 15, 15);
                string t = n > 99 ? "99" : n.ToString();
                using (var f = new Font("Segoe UI", t.Length > 1 ? 6.5f : 8f, FontStyle.Bold, GraphicsUnit.Point))
                {
                    var sz = g.MeasureString(t, f);
                    g.DrawString(t, f, Brushes.White, (16 - sz.Width) / 2 + 0.5f, (16 - sz.Height) / 2 + 0.5f);
                }
                IntPtr h = bmp.GetHicon();
                tb.SetOverlayIcon(Handle, h, n + " unread");
                Native.DestroyIcon(h);
            }
        }
        catch { }
    }

    void Flash()
    {
        var fi = new Native.FLASHWINFO();
        fi.cbSize = (uint)Marshal.SizeOf(fi); fi.hwnd = Handle; fi.dwFlags = 3 | 12; fi.uCount = 3;
        try { Native.FlashWindowEx(ref fi); } catch { }
    }

    void SetFullScreen(bool on)
    {
        if (on == fullScreen) return;
        fullScreen = on;
        if (on)
        {
            savedBorder = FormBorderStyle; savedState = WindowState;
            menu.Visible = false;
            FormBorderStyle = FormBorderStyle.None;
            if (WindowState == FormWindowState.Maximized) WindowState = FormWindowState.Normal;
            WindowState = FormWindowState.Maximized;
        }
        else
        {
            FormBorderStyle = savedBorder;
            WindowState = savedState;
            menu.Visible = Cfg.Bool("showMenuBar");
        }
    }

    // ---- menu & keyboard shortcuts
    void BuildMenu()
    {
        var edit = new ToolStripMenuItem("&Edit");
        edit.DropDownItems.Add(Item("Undo", Keys.Control | Keys.Z, () => Exec("undo"), false));
        edit.DropDownItems.Add(Item("Redo", Keys.Control | Keys.Y, () => Exec("redo"), false));
        edit.DropDownItems.Add(new ToolStripSeparator());
        edit.DropDownItems.Add(Item("Cut", Keys.Control | Keys.X, () => Exec("cut"), false));
        edit.DropDownItems.Add(Item("Copy", Keys.Control | Keys.C, () => Exec("copy"), false));
        edit.DropDownItems.Add(Item("Paste", Keys.Control | Keys.V, () => Exec("paste"), false));
        edit.DropDownItems.Add(Item("Select All", Keys.Control | Keys.A, () => Exec("selectAll"), false));
        edit.DropDownItems.Add(new ToolStripSeparator());
        edit.DropDownItems.Add(Item("Copy Current URL", Keys.Control | Keys.L, CopyUrl, true));
        edit.DropDownItems.Add(Item("Clear App Data…", Keys.None, ClearData, true));

        var view = new ToolStripMenuItem("&View");
        view.DropDownItems.Add(Item("Back", Keys.Alt | Keys.Left, () => { if (web.CanGoBack) { ownNav = true; web.GoBack(); } }, true));
        view.DropDownItems.Add(Item("Forward", Keys.Alt | Keys.Right, () => { if (web.CanGoForward) { ownNav = true; web.GoForward(); } }, true));
        view.DropDownItems.Add(Item("Home", Keys.Alt | Keys.Home, () => Go(App.Home), true));
        view.DropDownItems.Add(Item("Reload", Keys.Control | Keys.R, () => { ownNav = true; web.Reload(); }, true));
        shortcuts[Keys.F5] = () => { ownNav = true; web.Reload(); };
        view.DropDownItems.Add(new ToolStripSeparator());
        view.DropDownItems.Add(Item("Zoom In", Keys.Control | Keys.Oemplus, () => web.ZoomFactor = Math.Min(5, web.ZoomFactor + 0.1), false));
        view.DropDownItems.Add(Item("Zoom Out", Keys.Control | Keys.OemMinus, () => web.ZoomFactor = Math.Max(0.25, web.ZoomFactor - 0.1), false));
        view.DropDownItems.Add(Item("Actual Size", Keys.Control | Keys.D0, () => web.ZoomFactor = 1.0, false));
        view.DropDownItems.Add(new ToolStripSeparator());
        view.DropDownItems.Add(Item("Toggle Full Screen", Keys.F11, () => SetFullScreen(!fullScreen), true));
        if (!Cfg.Bool("disableDevTools"))
            view.DropDownItems.Add(Item("Developer Tools", Keys.Control | Keys.Shift | Keys.I,
                () => { if (web.CoreWebView2 != null) web.CoreWebView2.OpenDevToolsWindow(); }, true));

        var win = new ToolStripMenuItem("&Window");
        win.DropDownItems.Add(Item("Open in Default Browser", Keys.None, () => App.OpenExternal(CurrentUrl()), true));
        win.DropDownItems.Add(Item("Print…", Keys.Control | Keys.P, () => { if (web.CoreWebView2 != null) web.CoreWebView2.ShowPrintUI(); }, false));
        win.DropDownItems.Add(Item("Minimize", Keys.Control | Keys.M, () => WindowState = FormWindowState.Minimized, true));
        win.DropDownItems.Add(Item("Close Window", Keys.Control | Keys.W, Close, true));
        win.DropDownItems.Add(Item("Quit " + App.Name, Keys.Control | Keys.Q, Quit, true));

        var help = new ToolStripMenuItem("&Help");
        help.DropDownItems.Add(Item("About " + App.Name, Keys.None, About, true));

        menu.Items.AddRange(new ToolStripItem[] { edit, view, win, help });
        menu.MenuDeactivate += (s, e) => { if (!Cfg.Bool("showMenuBar")) menu.Visible = false; };
    }

    ToolStripMenuItem Item(string text, Keys keys, Action act, bool ownShortcut)
    {
        var it = new ToolStripMenuItem(text);
        it.Click += (s, e) => { try { act(); } catch { } };
        if (keys != Keys.None)
        {
            it.ShortcutKeyDisplayString = new KeysConverter().ConvertToString(keys).Replace("Oemplus", "+").Replace("OemMinus", "-").Replace("D0", "0");
            if (ownShortcut) shortcuts[keys] = act;   // others are handled by the page/WebView2 itself
        }
        return it;
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        Action a;
        if (shortcuts.TryGetValue(keyData, out a)) { try { a(); } catch { } return true; }
        if (keyData == (Keys.Menu | Keys.Alt) || keyData == Keys.F10)
        {
            if (!Cfg.Bool("showMenuBar") && !fullScreen) { menu.Visible = !menu.Visible; if (menu.Visible) menu.Focus(); }
            return true;
        }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    // Edit menu: send the real key press (Ctrl+V…) so the browser does it, like a keyboard would
    void Exec(string cmd)
    {
        if (web.CoreWebView2 == null) return;
        string k = cmd == "undo" ? "z" : cmd == "redo" ? "y" : cmd == "cut" ? "x" : cmd == "copy" ? "c" : cmd == "paste" ? "v" : "a";
        var js = new JavaScriptSerializer();
        foreach (string t in new[] { "keyDown", "keyUp" })
        {
            var p = new Dictionary<string, object> { { "type", t }, { "modifiers", 2 }, { "key", k }, { "code", "Key" + k.ToUpperInvariant() },
                { "windowsVirtualKeyCode", (int)char.ToUpperInvariant(k[0]) } };
            if (t == "keyDown") p["commands"] = new[] { cmd };
            try { web.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchKeyEvent", js.Serialize(p)); } catch { }
        }
        web.Focus();
    }
    void Go(string url) { if (web.CoreWebView2 != null) { ownNav = true; web.CoreWebView2.Navigate(url); } }
    string CurrentUrl() { return web.Source != null ? web.Source.AbsoluteUri : App.Home; }
    void CopyUrl() { try { Clipboard.SetText(CurrentUrl()); } catch { } }

    async void ClearData()
    {
        if (MessageBox.Show(this, "Clear all data of " + App.Name + " (logins, cookies, cache) and reload?", App.Name,
            MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) != DialogResult.OK) return;
        try { await web.CoreWebView2.Profile.ClearBrowsingDataAsync(); } catch { }
        Go(App.Home);
    }

    void About()
    {
        string rt = "";
        try { rt = CoreWebView2Environment.GetAvailableBrowserVersionString(); } catch { }
        MessageBox.Show(this, App.Name + "\nVersion " + Application.ProductVersion + "\n\n" + App.Home +
            "\n\nMade with Outboxer Studio · Microsoft Edge WebView2 " + rt, "About " + App.Name,
            MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    // ---- tray
    void SetupTray()
    {
        tray = new NotifyIcon();
        tray.Icon = App.AppIcon ?? SystemIcons.Application;
        tray.Text = Truncate(App.Name, 63);
        tray.Visible = true;
        var m = new ContextMenuStrip();
        m.Items.Add("Show " + App.Name, null, (s, e) => ShowAndFocus());
        m.Items.Add("Quit", null, (s, e) => Quit());
        tray.ContextMenuStrip = m;
        tray.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) { if (Visible && WindowState != FormWindowState.Minimized) Hide(); else ShowAndFocus(); } };
    }

    public void ShowAndFocus()
    {
        startHidden = false;
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
        Native.SetForegroundWindow(Handle);
    }

    void Quit()
    {
        quitting = true;
        foreach (var f in App.Windows.ToArray()) if (f != this) f.Close();
        if (isMain) Close(); else if (App.MainWindow != null) App.MainWindow.Quit();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (isMain && tray != null && !quitting && e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true; Hide();   // keep running in the tray
            return;
        }
        if (isMain)
        {
            SaveWindowState();
            foreach (var f in App.Windows.ToArray()) if (f != this) f.Close();
        }
        base.OnFormClosing(e);
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        App.Windows.Remove(this);
        if (tray != null) { tray.Visible = false; tray.Dispose(); }
        if (isMain) foreach (var hk in hotkeys) Native.UnregisterHotKey(Handle, (int)hk["id"]);
        base.OnFormClosed(e);
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == App.ShowMsg && isMain) { ShowAndFocus(); return; }
        if (m.Msg == 0x0312 && isMain) { OnHotkey(m.WParam.ToInt32()); return; }
        base.WndProc(ref m);
    }

    // ---- window size/position remembered between runs (like Nativefier)
    string StateFile { get { return Path.Combine(App.DataDir, "window-state.json"); } }
    void RestoreWindowState()
    {
        try
        {
            if (!File.Exists(StateFile)) return;
            var s = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(StateFile));
            var r = new Rectangle(Convert.ToInt32(s["x"]), Convert.ToInt32(s["y"]), Convert.ToInt32(s["w"]), Convert.ToInt32(s["h"]));
            bool visible = false;
            foreach (var sc in Screen.AllScreens) if (sc.WorkingArea.IntersectsWith(r)) visible = true;
            if (!visible || r.Width < 200 || r.Height < 150) return;
            StartPosition = FormStartPosition.Manual; Bounds = r;
            if (s.ContainsKey("max") && (bool)s["max"]) WindowState = FormWindowState.Maximized;
        }
        catch { }
    }
    void SaveWindowState()
    {
        try
        {
            if (fullScreen) return;
            var r = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
            var s = new Dictionary<string, object> { { "x", r.X }, { "y", r.Y }, { "w", r.Width }, { "h", r.Height },
                { "max", WindowState == FormWindowState.Maximized } };
            File.WriteAllText(StateFile, new JavaScriptSerializer().Serialize(s));
        }
        catch { }
    }

    // ---- global shortcuts (same JSON format as Nativefier's --global-shortcuts)
    void RegisterGlobalShortcuts()
    {
        var list = Cfg.List("globalShortcuts");
        if (list == null) return;
        int id = 1;
        foreach (object o in list)
        {
            var sc = o as Dictionary<string, object>;
            if (sc == null || !sc.ContainsKey("key")) continue;
            uint mods, vk;
            if (!ParseAccelerator(Convert.ToString(sc["key"]), out mods, out vk)) continue;
            if (Native.RegisterHotKey(Handle, id, mods | 0x4000 /* MOD_NOREPEAT */, vk))
            {
                sc["id"] = id; hotkeys.Add(sc); id++;
            }
        }
    }

    void OnHotkey(int id)
    {
        foreach (var sc in hotkeys)
        {
            if ((int)sc["id"] != id || web.CoreWebView2 == null) continue;
            var events = sc.ContainsKey("inputEvents") ? Cfg.ToList(sc["inputEvents"]) : null;
            if (events == null) continue;
            foreach (object eo in events)
            {
                var ev = eo as Dictionary<string, object>;
                if (ev == null) continue;
                string type = ev.ContainsKey("type") ? Convert.ToString(ev["type"]) : "keyDown";
                string code = ev.ContainsKey("keyCode") ? Convert.ToString(ev["keyCode"]) : "";
                SendKey(type, code);
            }
        }
    }

    void SendKey(string type, string keyCode)
    {
        string key, code; int vk;
        KeyInfo(keyCode, out key, out code, out vk);
        string t = type == "keyUp" ? "keyUp" : (type == "char" ? "char" : "keyDown");
        var p = new Dictionary<string, object> { { "type", t }, { "key", key }, { "code", code },
            { "windowsVirtualKeyCode", vk }, { "nativeVirtualKeyCode", vk } };
        if (t == "keyDown" && key.Length == 1) p["text"] = key;
        try { web.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchKeyEvent", new JavaScriptSerializer().Serialize(p)); } catch { }
    }

    static void KeyInfo(string k, out string key, out string code, out int vk)
    {
        key = k; code = k; vk = 0;
        if (k.Length == 1 && char.IsLetter(k[0])) { key = k.ToLowerInvariant(); code = "Key" + k.ToUpperInvariant(); vk = char.ToUpperInvariant(k[0]); return; }
        if (k.Length == 1 && char.IsDigit(k[0])) { key = k; code = "Digit" + k; vk = k[0]; return; }
        switch (k.ToLowerInvariant())
        {
            case "space": key = " "; code = "Space"; vk = 32; return;
            case "enter": case "return": key = "Enter"; code = "Enter"; vk = 13; return;
            case "tab": key = "Tab"; code = "Tab"; vk = 9; return;
            case "escape": case "esc": key = "Escape"; code = "Escape"; vk = 27; return;
            case "backspace": key = "Backspace"; code = "Backspace"; vk = 8; return;
            case "delete": key = "Delete"; code = "Delete"; vk = 46; return;
            case "up": key = "ArrowUp"; code = "ArrowUp"; vk = 38; return;
            case "down": key = "ArrowDown"; code = "ArrowDown"; vk = 40; return;
            case "left": key = "ArrowLeft"; code = "ArrowLeft"; vk = 37; return;
            case "right": key = "ArrowRight"; code = "ArrowRight"; vk = 39; return;
            case "home": key = "Home"; code = "Home"; vk = 36; return;
            case "end": key = "End"; code = "End"; vk = 35; return;
            case "pageup": key = "PageUp"; code = "PageUp"; vk = 33; return;
            case "pagedown": key = "PageDown"; code = "PageDown"; vk = 34; return;
            case "mediaplaypause": key = "MediaPlayPause"; code = "MediaPlayPause"; vk = 0xB3; return;
            case "medianexttrack": key = "MediaTrackNext"; code = "MediaTrackNext"; vk = 0xB0; return;
            case "mediaprevioustrack": key = "MediaTrackPrevious"; code = "MediaTrackPrevious"; vk = 0xB1; return;
            case "mediastop": key = "MediaStop"; code = "MediaStop"; vk = 0xB2; return;
        }
        var fm = Regex.Match(k, @"^[Ff](\d{1,2})$");
        if (fm.Success) { key = "F" + fm.Groups[1].Value; code = key; vk = 0x6F + int.Parse(fm.Groups[1].Value); }
    }

    static bool ParseAccelerator(string acc, out uint mods, out uint vk)
    {
        mods = 0; vk = 0;
        foreach (string raw in acc.Split('+'))
        {
            string p = raw.Trim().ToLowerInvariant();
            if (p == "commandorcontrol" || p == "cmdorctrl" || p == "control" || p == "ctrl" || p == "command" || p == "cmd") mods |= 2;
            else if (p == "alt" || p == "option") mods |= 1;
            else if (p == "shift") mods |= 4;
            else if (p == "super" || p == "meta") mods |= 8;
            else
            {
                string key, code; int v;
                KeyInfo(raw.Trim(), out key, out code, out v);
                if (p == "plus") v = 0xBB;
                if (p == "volumeup") v = 0xAF; else if (p == "volumedown") v = 0xAE; else if (p == "volumemute") v = 0xAD;
                if (v == 0) return false;
                vk = (uint)v;
            }
        }
        return vk != 0;
    }
}
'''

# ---------------------------------------------------------------------------
# WebView2 apps: a small Windows program (compiled here with Windows' own C# compiler) that shows the
# site with Microsoft Edge WebView2, which is part of Windows 10/11. No Electron, no Nativefier, no Node.
# All app settings live in app.json next to the .exe (editable later without rebuilding).
# ---------------------------------------------------------------------------
WEBVIEW2_NUGET = "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/"
WEBVIEW2_RUNTIME_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_DLLS = ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll")
WEBVIEW2_ARCHES = {"x64": ("win-x64", "x64"), "ia32": ("win-x86", "x86"), "arm64": ("win-arm64", "anycpu")}
USER_AGENTS = {  # same browsers/versions as Nativefier 53's presets
    "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/152.0.0.0 Safari/537.36",
    "edge": "",  # WebView2's own user agent already is Edge's
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0",
    "safari": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/27.0 Safari/605.1.15",
}
# Studio options that only exist for Electron apps (greyed out for WebView2)
UPDATE_NAMES = {"node": "Node.js", "electron": "Electron", "webview2": "WebView2 SDK"}
ELECTRON_ONLY_OPTIONS = {"electron_version", "conceal", "title_bar_style", "bounce", "fast_quit",
                         "browserwindow_options", "widevine", "honest", "extra_args", "verbose", "quiet",
                         "build_version"}


def full_version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "")))


def webview2_runtime_version():
    """Version of the Edge WebView2 Runtime installed in Windows, or ''."""
    if not IS_WIN:
        return ""
    import winreg
    keys = [(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}"),
            (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}")]
    for hive, path in keys:
        try:
            with winreg.OpenKey(hive, path) as k:
                v = winreg.QueryValueEx(k, "pv")[0]
                if v and v != "0.0.0.0":
                    return v
        except OSError:
            continue
    return ""


def webview2_sdks(folder):
    """[(version, path)] of WebView2 SDKs in folder, newest first."""
    res = []
    try:
        for p in Path(folder).iterdir():
            if p.is_dir() and all((p / d).is_file() for d in WEBVIEW2_DLLS):
                res.append((p.name, p))
    except OSError:
        pass
    return sorted(res, key=lambda r: full_version_tuple(r[0]), reverse=True)


def latest_webview2_sdk():
    versions = http_json(WEBVIEW2_NUGET + "index.json")["versions"]
    stable = [v for v in versions if "-" not in v]
    return max(stable, key=full_version_tuple)


def _signed_by_microsoft(path):
    """Authenticode check with PowerShell: valid signature from Microsoft Corporation."""
    ps = ("$s=Get-AuthenticodeSignature -LiteralPath $env:NFS_FILE; "
          "[string]$s.Status + '|' + [string]$s.SignerCertificate.Subject")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       env={**os.environ, "NFS_FILE": str(path)}, capture_output=True, text=True,
                       timeout=60, creationflags=_no_window())
    out = (r.stdout or "").strip()
    return out.startswith("Valid|") and "O=Microsoft Corporation" in out


def download_webview2_sdk(version, folder, job):
    """Get the WebView2 SDK from NuGet into folder\\<version> (only the 2 .NET DLLs and the loaders)."""
    target = Path(folder) / version
    if all((target / d).is_file() for d in WEBVIEW2_DLLS):
        return target
    url = f"{WEBVIEW2_NUGET}{version}/microsoft.web.webview2.{version}.nupkg"
    job.say(f"Downloading the WebView2 SDK {version} from NuGet…")
    pkg = download_file(url, DOWNLOADS_DIR / f"microsoft.web.webview2.{version}.nupkg", job)
    staging = target.with_name(version + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(pkg) as z:
        names = z.namelist()
        lib = next((d for d in ("lib/net462/", "lib/net45/") if d + WEBVIEW2_DLLS[0] in names), None)
        if not lib:
            raise RuntimeError("Unexpected WebView2 package layout (no .NET Framework DLLs).")
        for d in WEBVIEW2_DLLS:
            (staging / d).write_bytes(z.read(lib + d))
        for rid, _plat in WEBVIEW2_ARCHES.values():
            n = f"runtimes/{rid}/native/WebView2Loader.dll"
            if n in names:
                (staging / rid).mkdir(exist_ok=True)
                (staging / rid / "WebView2Loader.dll").write_bytes(z.read(n))
    if IS_WIN:
        job.say("Checking Microsoft's signatures on the SDK files…")
        for f in [staging / d for d in WEBVIEW2_DLLS] + list(staging.glob("*/WebView2Loader.dll")):
            if not _signed_by_microsoft(f):
                shutil.rmtree(staging, ignore_errors=True)
                pkg.unlink(missing_ok=True)
                raise RuntimeError(f"{f.name} is not signed by Microsoft — the download was not used.")
    shutil.rmtree(target, ignore_errors=True)
    os.replace(staging, target)
    pkg.unlink(missing_ok=True)
    _tidy_downloads()
    return target


# ---- reading the site: title and icon (like Nativefier's inference) --------
def _fetch(url, limit=5 << 20, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENTS["chrome"], "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError("too large")
        return data, r.geturl(), r.headers.get_content_charset() or ""


def infer_site(url, log=print):
    """(title, [(icon_url, size_hint)]) read from the page; never raises."""
    import html as htmlmod
    from urllib.parse import urljoin
    try:
        raw, final, cs = _fetch(url)
    except Exception as ex:
        log(f"   (could not read the page for its title/icon: {ex})")
        return "", []
    m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:4096], re.I)
    text = raw.decode((cs or (m.group(1).decode() if m else "") or "utf-8"), "replace")
    title = ""
    for pat in (r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+name=["\']application-name["\'][^>]+content=["\']([^"\']+)',
                r"<title[^>]*>(.*?)</title>"):
        mt = re.search(pat, text, re.I | re.S)
        if mt and mt.group(1).strip():
            title = htmlmod.unescape(re.sub(r"\s+", " ", mt.group(1))).strip()
            break
    icons = []
    for tag in re.findall(r"<link\b[^>]*>", text, re.I):
        rel = re.search(r'rel=["\']([^"\']+)', tag, re.I)
        href = re.search(r'href=["\']([^"\']+)', tag, re.I)
        if not rel or not href or "icon" not in rel.group(1).lower() or "mask" in rel.group(1).lower():
            continue
        sizes = re.search(r'sizes=["\'](\d+)x\d+', tag, re.I)
        size = int(sizes.group(1)) if sizes else (180 if "apple" in rel.group(1).lower() else 32)
        icons.append((urljoin(final, htmlmod.unescape(href.group(1))), size))
    mf = re.search(r'<link[^>]+rel=["\']manifest["\'][^>]*href=["\']([^"\']+)', text, re.I) or \
        re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\']manifest', text, re.I)
    if mf:
        try:
            murl = urljoin(final, htmlmod.unescape(mf.group(1)))
            for ic in json.loads(_fetch(murl, 1 << 20)[0]).get("icons", []):
                s = re.match(r"(\d+)", str(ic.get("sizes", "")))
                if "monochrome" in str(ic.get("purpose", "")).lower():
                    continue  # single-colour silhouettes for system badges, not app icons
                if ic.get("src"):
                    icons.append((urljoin(murl, ic["src"]), int(s.group(1)) if s else 64))
        except Exception:
            pass
    icons.append((urljoin(final, "/favicon.ico"), 16))
    icons = [i for i in icons if not i[0].lower().split("?")[0].endswith(".svg") and "monochrome" not in i[0].lower()]
    icons.sort(key=lambda i: (min(i[1], 512) if i[1] <= 512 else 0), reverse=True)
    return title, icons


def make_ico(src_bytes, out_path):
    """Any image (PNG/ICO/JPG…) -> multi-size .ico. Needs Pillow unless it already is an .ico."""
    if src_bytes[:4] == b"\x00\x00\x01\x00":
        try:
            from PIL import Image
        except ImportError:
            Path(out_path).write_bytes(src_bytes)
            return Path(out_path)
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(src_bytes))
    try:  # ICO files: take the biggest frame
        if getattr(img, "ico", None):
            img = img.ico.getimage(max(img.ico.sizes()))
    except Exception:
        pass
    img = img.convert("RGBA")
    side = max(img.size)
    if img.size[0] != img.size[1]:  # pad to square
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(img, ((side - img.size[0]) // 2, (side - img.size[1]) // 2))
        img = sq
    sizes = [s for s in (16, 20, 24, 32, 40, 48, 64, 128, 256) if s <= max(side, 16)] or [16]
    img.save(out_path, format="ICO", sizes=[(s, s) for s in sizes])
    return Path(out_path)


def webview2_app_config(opts, url, name):
    """app.json for a WebView2 app from Studio's form values (opts: key -> value)."""
    g = opts.get
    ua = g("user_agent") or ""
    ua = USER_AGENTS.get(ua.lower(), ua)
    args = []
    if g("proxy_rules"):
        args.append(f"--proxy-server={g('proxy_rules')}")
    if g("disk_cache_size"):
        args.append(f"--disk-cache-size={int(g('disk_cache_size'))}")
    if g("ignore_certificate"):
        args.append("--ignore-certificate-errors")
    if g("insecure"):
        args += ["--disable-web-security", "--allow-running-insecure-content"]
    if g("disable_gpu"):
        args.append("--disable-gpu")
    if g("ignore_gpu_blacklist"):
        args.append("--ignore-gpu-blocklist")
    if g("enable_es3_apis"):
        args.append("--enable-es3-apis")
    cfg = {
        "builtBy": APP_TITLE, "engine": "webview2", "name": name, "targetUrl": url,
        "version": g("app_version") or DEFAULT_APP_VERSION,
        "portable": bool(g("portable")), "singleInstance": bool(g("single_instance")),
        "width": g("width") or 1280, "height": g("height") or 800,
        "minWidth": g("min_width") or 0, "minHeight": g("min_height") or 0,
        "maxWidth": g("max_width") or 0, "maxHeight": g("max_height") or 0,
        "x": g("x") or 0, "y": g("y") or 0,
        "fullScreen": bool(g("full_screen")), "maximize": bool(g("maximize")),
        "hideWindowFrame": bool(g("hide_window_frame")), "alwaysOnTop": bool(g("always_on_top")),
        "showMenuBar": bool(g("show_menu_bar")), "tray": g("tray") or "false",
        "backgroundColor": g("background_color") or "",
        "internalUrls": g("internal_urls") or "", "strictInternalUrls": bool(g("strict_internal_urls")),
        "blockExternalUrls": bool(g("block_external_urls")), "userAgent": ua,
        "zoom": g("zoom") or 1.0, "counter": bool(g("counter")),
        "disableContextMenu": bool(g("disable_context_menu")), "disableDevTools": bool(g("disable_dev_tools")),
        "clearCache": bool(g("clear_cache")), "inject": [],
        "basicAuthUsername": g("basic_auth_username") or "", "basicAuthPassword": g("basic_auth_password") or "",
        "lang": g("lang") or "", "browserArguments": " ".join(args),
    }
    if g("file_download_options"):
        cfg["fileDownloadOptions"] = json.loads(g("file_download_options"))
    if g("global_shortcuts"):
        cfg["globalShortcuts"] = json.loads(Path(g("global_shortcuts")).read_text(encoding="utf-8-sig"))
    return cfg


def build_webview2_app(opts, url, out_dir, sdk_dir, job):
    """Build <out_dir>\\<Name> with <Name>.exe, app.json and the WebView2 DLLs. Returns the folder."""
    arch = opts.get("arch") or HOST_ARCH
    if arch not in WEBVIEW2_ARCHES:
        raise RuntimeError(f"WebView2 apps can be built for x64, ia32 or arm64 — not '{arch}'.")
    rid, plat = WEBVIEW2_ARCHES[arch]
    sdk_dir = Path(sdk_dir)
    loader = sdk_dir / rid / "WebView2Loader.dll"
    if not loader.is_file():
        raise RuntimeError(f"The WebView2 SDK has no loader for {arch} ({loader}).")

    name = opts.get("name") or ""
    icon_src = opts.get("icon") or ""
    title, icons = ("", [])
    if opts.get("server_dir"):
        if not icon_src:
            job.say("   (local-server app: its site isn't running during the build, so no icon is read from it — "
                    "choose one in the App tab's Icon field)")
    elif not name or not icon_src:
        job.say("   reading the site for its name and icon…")
        title, icons = infer_site(url, log=job.say)
    if not name:
        name = re.split(r"\s[-|–—·:]\s", title)[0].strip()[:60] if title else ""
        name = name or (urllib.parse.urlparse(url).hostname or "App").replace("www.", "").split(".")[0].title()
        job.say(f"   app name: {name}")
    folder_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "App"
    app = Path(out_dir) / folder_name
    shutil.rmtree(app, ignore_errors=True)
    app.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="outboxer-wv2-"))
    try:
        ico = None
        if icon_src:
            try:
                ico = make_ico(Path(icon_src).read_bytes(), work / "app.ico")
            except Exception as ex:
                job.say(f"   (icon could not be converted: {ex}; install Pillow: python -m pip install pillow)")
        else:
            for iurl, _size in icons:
                try:
                    data, _final, _cs = _fetch(iurl, 2 << 20, 10)
                    ico = make_ico(data, work / "app.ico")
                    job.say(f"   icon: {iurl}")
                    break
                except ImportError:
                    job.say("   (install Pillow for site icons: python -m pip install pillow)")
                    break
                except Exception:
                    continue

        cfg = webview2_app_config(opts, url, name)
        inject = []
        if opts.get("inject"):
            (app / "inject").mkdir()
            for i, f in enumerate(opts["inject"]):
                dst = app / "inject" / f"{i + 1:02d}-{Path(f).name}"
                shutil.copy2(f, dst)
                inject.append(f"inject\\{dst.name}")
        cfg["inject"] = inject
        (app / "app.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

        for d in WEBVIEW2_DLLS:
            shutil.copy2(sdk_dir / d, app / d)
        shutil.copy2(loader, app / "WebView2Loader.dll")

        def cs_str(s):
            return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        ver = ".".join((list(map(str, version_tuple(cfg["version"]))) or ["1", "0", "0"]) + ["0"])
        src = (WEBVIEW2_APP_CS.replace("{TITLE}", cs_str(name)).replace("{VERSION}", ver)
               .replace("{COPYRIGHT}", cs_str(opts.get("app_copyright") or ""))
               .replace("{COMPANY}", cs_str(opts.get("app_copyright") or name)))
        (work / "app.cs").write_text(src, encoding="utf-8")
        csc = find_csc()
        if not csc:
            raise RuntimeError("The Windows C# compiler (csc.exe, part of .NET Framework 4) was not found.")
        exe = app / f"{folder_name}.exe"
        cmd = [str(csc), "/nologo", "/target:winexe", "/optimize+", f"/platform:{plat}", f"/out:{exe}",
               "/r:System.dll", "/r:System.Core.dll", "/r:System.Drawing.dll", "/r:System.Windows.Forms.dll",
               "/r:System.Web.Extensions.dll", f"/r:{sdk_dir / WEBVIEW2_DLLS[0]}", f"/r:{sdk_dir / WEBVIEW2_DLLS[1]}"]
        if ico:
            cmd.append(f"/win32icon:{ico}")
        cmd.append(str(work / "app.cs"))
        job.say("   compiling the app…")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, creationflags=_no_window())
        if r.returncode != 0:
            raise RuntimeError("Compiling the WebView2 app failed:\n" + (r.stdout + r.stderr).strip()[:3000])
        return app
    except Exception:
        shutil.rmtree(app, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


USER_MANUAL_HTML = r'''<h1>Advanced Outboxer Studio v2.0 — User Manual</h1>
<p>Advanced Outboxer Studio turns any website, a web app that runs on your own PC (with its own local server), or a
whole <b>HTML/CSS/JS project folder</b> into a desktop application with its own window, icon, taskbar entry and
shortcut. You fill in a form, press <b>Build App</b>, and the finished app appears on your Desktop.</p>
<p>Choose the <b>Source</b> at the top: <b>Website (URL)</b> works exactly like Outboxer Studio v1.0 (sections 1–12);
<b>Project folder</b> builds your own pages into a Windows app that can control the PC through the
<b>desktop toolbox</b> (section 13 and <b>Help → Desktop toolbox guide</b>).</p>

<p><b>Contents:</b>
<a href="#quick">1. Quick start</a> · <a href="#engines-choice">2. Choosing an app engine</a> ·
<a href="#window">3. The main window</a> · <a href="#options">4. Options, tab by tab</a> ·
<a href="#server">5. Apps with their own local server</a> · <a href="#presets">6. Presets</a> ·
<a href="#engineswin">7. The Engines window</a> · <a href="#files">8. Where things are</a> ·
<a href="#inapp">9. Using the apps you build</a> · <a href="#sharing">10. Sharing apps</a> ·
<a href="#trouble">11. Troubleshooting</a> · <a href="#security">12. Safety notes</a> ·
<a href="#project">13. Project folders, Electron app folders and the desktop toolbox</a></p>

<h2 id="quick"><a name="quick"></a>1. Quick start</h2>
<ol>
<li>Type or paste the website address in <b>URL</b> (you can also drag a link onto the window).</li>
<li>Optional: give the app a <b>name</b> and an <b>icon</b> on the <b>App</b> tab. If you leave them empty, Studio
reads the name and icon from the website.</li>
<li>Choose the <b>App engine</b> at the top of the App tab (see section 2). If unsure, keep the first one.</li>
<li>Click <b>Build App</b>. Progress appears in the <b>Build log</b>.</li>
<li>When the log says <b>Done!</b>, the app is in a folder with the app's name on your Desktop (or in the
<b>Output folder</b> you chose). Click <b>Open output folder</b> and double-click the app.</li>
</ol>
<p>Building the same app again replaces the older build (its saved data and logins are kept).</p>

<h2 id="engines-choice"><a name="engines-choice"></a>2. Choosing an app engine</h2>
<table border="1" cellspacing="0" cellpadding="5">
<tr><th>App engine</th><th>App size</th><th>Best for</th></tr>
<tr><td><b>Electron inside the app</b></td><td>about 370 MB</td><td>Apps you give to other people. Works the same on
every Windows PC; nothing else needed.</td></tr>
<tr><td><b>Electron shared runtime</b></td><td>about 2 MB</td><td>Many apps on your own PC. All of them use one
shared copy of Electron (set in <b>Shared runtime folder</b>).</td></tr>
<tr><td><b>WebView2</b></td><td>about 1 MB</td><td>Small, fast apps for Windows 10/11. They use the Microsoft Edge
engine that is part of Windows and is kept up to date by Windows.</td></tr>
</table>
<p>Options that the chosen engine does not use are greyed out automatically.</p>
<ul>
<li><b>Electron</b> carries its own browser (Chromium), so apps look and behave the same everywhere.</li>
<li><b>Shared runtime</b> apps contain a small launcher, an <i>app</i> folder and a file
<i>electron-runtime.txt</i> whose first line is the Electron folder the app runs on. Edit that line in Notepad to
point the app to another Electron without rebuilding. Keep the runtime folder as long as any app uses it.</li>
<li><b>WebView2</b> apps are built by Studio itself (no Nativefier, Node.js or Electron is used). Their settings are
in <i>app.json</i> next to the .exe — you can edit it (for example the address) without rebuilding. If a PC does
not have the WebView2 Runtime, the app offers to open Microsoft's download page.</li>
</ul>

<h2 id="window"><a name="window"></a>3. The main window</h2>
<ul>
<li><b>Engine line</b> (top): shows what will build the app — e.g. the Nativefier version, Node.js and Electron
versions, or the WebView2 runtime and SDK. A red ❌ tells you what is missing.</li>
<li><b>Engines…</b> button: opens the Engines window (section 7). It shows <b>⬆</b> when updates are available.</li>
<li><b>URL</b>: the website or local address (http:// or https://). <b>Open in browser</b> checks it first.</li>
<li><b>Output folder</b>: where the app folder is created. Empty = your Desktop.</li>
<li><b>Option tabs</b>: App, Window, Behavior, Advanced, Server (section 4).</li>
<li><b>Command preview</b>: the exact Nativefier command (Electron engines) or the <i>app.json</i> settings
(WebView2) that will be used. <b>Copy</b> copies it.</li>
<li><b>Build log</b>: everything that happens during the build. <b>Clear</b> empties it.</li>
<li><b>Build App</b> starts, <b>Stop</b> cancels, <b>Open output folder</b> opens the finished app's folder.</li>
</ul>

<h2 id="options"><a name="options"></a>4. Options, tab by tab</h2>
<p>Empty or "(default)" means: use the normal behaviour. Hover over any field to see the exact Nativefier
option it sets.</p>
<h3>App</h3>
<ul>
<li><b>App engine</b> and <b>Shared runtime folder</b> — see section 2. Empty runtime folder = automatic
(<i>Engines\runtime\electron-v&lt;version&gt;-win32-x64</i>).</li>
<li><b>App name</b> — window title, folder and .exe name. Empty = taken from the website.</li>
<li><b>Platform / Architecture</b> — Windows/x64 by default (your PC). WebView2 apps are Windows only.</li>
<li><b>Icon</b> — .ico or .png (.icns for Mac). Empty = the website's icon (not possible for local-server apps,
because their site isn't running during the build).</li>
<li><b>App version</b> (default 1.0.0), <b>Build version</b>, <b>Copyright</b> — shown in the .exe's properties.</li>
<li><b>Electron version</b> — overrides the default set in the Engines window for this app.</li>
<li><b>Portable</b> — keeps the app's data (logins, cache) inside the app folder. Careful: whoever gets a copy of
the folder also gets those logins. Portable apps are never replaced by a rebuild (a new folder "(2)" is made).</li>
<li><b>Single instance</b> — opening the app again brings the existing window to the front.</li>
<li><b>Pack app source into asar</b> (Electron) — hides the app's code in one archive file.</li>
</ul>
<h3>Window</h3>
<ul>
<li><b>Width/Height</b>, <b>Min/Max width/height</b>, <b>X/Y position</b> — 0 = default. Apps remember the size and
position you leave them at.</li>
<li><b>Start full screen</b>, <b>Start maximized</b>, <b>Hide window frame</b>, <b>Always on top</b>.</li>
<li><b>Show menu bar</b> — otherwise the menu is hidden and appears when you press <b>Alt</b>.</li>
<li><b>System tray</b> — <i>true</i>: closing the window keeps the app running in the tray;
<i>start-in-tray</i>: the app starts hidden in the tray.</li>
<li><b>Title bar style</b> (Mac only), <b>Background color</b> (e.g. #1e1f24, shown while pages load).</li>
</ul>
<h3>Behavior</h3>
<ul>
<li><b>Internal URLs</b> — a pattern (regular expression) of addresses that should open <i>inside</i> the app.
By default the site's own domain and common sign-in pages (Google, Microsoft, Apple…) stay inside; other sites
open in your normal browser.</li>
<li><b>Strict internal URLs</b> — only the exact same host stays inside. <b>Block external URLs</b> — other sites
do not open at all.</li>
<li><b>User agent</b> — how the app introduces itself to websites: chrome, edge, firefox, safari, or your own text.
Use it when a site says your browser is not supported.</li>
<li><b>Zoom factor</b> — e.g. 1.25 for 125 %.</li>
<li><b>Show unread counter</b> — a number like "(3)" in the page title becomes a badge on the taskbar icon.</li>
<li><b>Bounce dock</b>, <b>Quit when window closes</b> — Mac only.</li>
<li><b>Disable context menu</b> (right-click menu), <b>Disable DevTools</b> (developer tools, F12/Ctrl+Shift+I).</li>
<li><b>Clear cache on start</b> — the app forgets its data on every start (you will be signed out each time).</li>
<li><b>Inject CSS / JS files</b> — your own style sheets or scripts added to every page (e.g. to hide an element:
<i>#banner { display: none !important; }</i>).</li>
</ul>
<h3>Advanced</h3>
<ul>
<li><b>Proxy rules</b> — e.g. http://proxy:8080.</li>
<li><b>Basic auth user / password</b> — for sites protected by a browser sign-in box. They are given only to the
app's own site.</li>
<li><b>Disk cache size</b> (bytes), <b>Language</b> (e.g. en-US, ar).</li>
<li><b>File download options</b> — JSON, e.g. {"saveAs": true} to ask where to save every download.</li>
<li><b>BrowserWindow options</b> (Electron) — advanced Electron window settings in JSON.</li>
<li><b>Global shortcuts</b> — a JSON file of keyboard shortcuts that work even when the app is in the background,
e.g. a media key that presses Space in the app.</li>
<li><b>Ignore certificate errors</b>, <b>Allow insecure content</b> — only for trusted internal sites; they reduce
security.</li>
<li><b>Disable GPU</b>, <b>Ignore GPU blacklist</b>, <b>Enable WebGL 2</b> — for display problems.</li>
<li><b>Honest user agent</b>, <b>Widevine DRM</b>, <b>Verbose</b>, <b>Quiet</b>, <b>Extra raw arguments</b> —
Electron only.</li>
</ul>

<h2 id="server"><a name="server"></a>5. Apps with their own local server (Server tab)</h2>
<p>Some web apps (like UMA) need a small server running on your PC, e.g. <i>server.js</i> on
http://localhost:8080. The Server tab puts that server <b>inside</b> the app folder and starts it automatically, so
users only need one folder.</p>
<ul>
<li><b>Folder to bundle</b> — the folder that contains the server script and the site files. It is copied into
<i>&lt;App&gt;\server</i>.</li>
<li><b>Server script</b> — default <i>server.js</i>.</li>
<li><b>Run the server with</b>:
  <ul><li><i>The app's own Node</i> — Electron apps run the server with their own built-in Node (nothing to install);
  WebView2 apps get a copy of Studio's node.exe inside the app.</li>
  <li><i>Node.js installed on the PC</i>.</li>
  <li><i>This node.exe</i> — any node.exe you choose, e.g. <i>C:\Z\Z.exe</i>.</li></ul></li>
<li><b>Stop the server when the app closes</b> — recommended. The app then also becomes single-instance.</li>
<li><b>Create a desktop shortcut</b>, <b>Don't copy</b> (files and folders left out, separated by ;).</li>
</ul>
<p><b>How it starts:</b> Electron apps get a launcher <i>Start &lt;App&gt;.vbs</i> (the desktop shortcut points to it).
WebView2 apps start and stop their server themselves — just open the .exe. If a server is already running on that
address, the app uses it. The server's messages are written to <i>server\server.log</i>.</p>
<p><b>Your data is kept:</b> files the server saved inside the app's server folder are carried over when you rebuild.</p>

<h2 id="presets"><a name="presets"></a>6. Presets</h2>
<p>Studio always starts with fresh, default settings. To keep the settings of an app, use
<b>File → Save preset…</b> (Ctrl+S); later <b>File → Load preset…</b> (Ctrl+O) fills in everything again.
<b>File → Reset all fields</b> goes back to the defaults.</p>

<h2 id="engineswin"><a name="engineswin"></a>7. The Engines window</h2>
<p>Open it with <b>Engines…</b>. Everything Studio uses lives in the <i>Engines</i> folder next to Studio by default;
any path can be changed, and your choices are saved in <i>AdvancedOutboxerStudio.config.json</i>.</p>
<ul>
<li><b>Node.js</b> — runs Nativefier for Electron builds. <b>Update Node.js</b> downloads the newest release (or the
long-term-support one) from nodejs.org, verifies it and switches to it.</li>
<li><b>Nativefier engine</b> — the modernised Nativefier 53. <b>Install / repair engine</b> reinstalls it from the
package in <i>Engines\packages</i> (needs internet for its libraries).</li>
<li><b>Electron</b> — the zip files Electron apps are made from, and the version used for new builds.
<b>Download latest Electron</b> gets and verifies the newest one. Double-click a version in the list to use it.</li>
<li><b>Shared Electron runtimes</b> — the unpacked Electron folders used by shared-runtime apps.</li>
<li><b>WebView2</b> — the Edge WebView2 Runtime on this PC (part of Windows) and the WebView2 SDK (two small
Microsoft files put into each WebView2 app). Downloads are checked for Microsoft's signature.</li>
<li><b>Updates</b> — Studio checks for new versions at most every 12 hours when it starts (can be turned off), or
use <b>Check for updates now</b>. The activity log at the bottom shows what happened.</li>
</ul>

<h2 id="files"><a name="files"></a>8. Where things are</h2>
<table border="1" cellspacing="0" cellpadding="5">
<tr><td>Finished apps</td><td>Desktop\&lt;App name&gt; (or your Output folder)</td></tr>
<tr><td>Studio's engines</td><td>&lt;Studio folder&gt;\Engines\ — node, nativefier53, electron, runtime, webview2, packages</td></tr>
<tr><td>Studio settings</td><td>&lt;Studio folder&gt;\AdvancedOutboxerStudio.config.json</td></tr>
<tr><td>Settings of a project</td><td>&lt;project folder&gt;\outboxer.json (saved on every Build / Test Run)</td></tr>
<tr><td>Data of project apps</td><td>%APPDATA%\&lt;App ID&gt; — store, db, logs (or the app's <i>data</i> folder when portable)</td></tr>
<tr><td>Data of Electron apps</td><td>%APPDATA%\&lt;App name&gt; (logins, cache)</td></tr>
<tr><td>Data of WebView2 apps</td><td>%LOCALAPPDATA%\OutboxerStudio\Apps\&lt;App name&gt;</td></tr>
<tr><td>Data of portable apps</td><td>inside the app folder</td></tr>
<tr><td>Server log</td><td>&lt;App&gt;\server\server.log</td></tr>
</table>

<h2 id="inapp"><a name="inapp"></a>9. Using the apps you build</h2>
<p>Press <b>Alt</b> to show the menu (if it is hidden). Useful shortcuts in WebView2 apps:</p>
<table border="1" cellspacing="0" cellpadding="5">
<tr><td>Ctrl+R / F5</td><td>Reload</td><td>Alt+Left / Alt+Right</td><td>Back / Forward</td></tr>
<tr><td>Alt+Home</td><td>Go to the app's home page</td><td>F11</td><td>Full screen</td></tr>
<tr><td>Ctrl + / Ctrl − / Ctrl+0</td><td>Zoom in / out / reset</td><td>Ctrl+L</td><td>Copy current address</td></tr>
<tr><td>Ctrl+P</td><td>Print</td><td>Ctrl+Shift+I</td><td>Developer tools (unless disabled)</td></tr>
<tr><td>Ctrl+W</td><td>Close window</td><td>Ctrl+Q</td><td>Quit</td></tr>
</table>
<p>The menu also has <b>Open in Default Browser</b>, <b>Clear App Data…</b> (signs out and clears the cache) and
<b>About</b>. Electron apps have a similar menu.</p>

<h2 id="sharing"><a name="sharing"></a>10. Sharing apps</h2>
<ul>
<li>Share the <b>whole app folder</b> (e.g. as a zip), not just the .exe.</li>
<li><b>Electron inside the app</b> is the safest choice for other people's PCs.</li>
<li><b>WebView2</b> apps work on Windows 10/11 PCs that have the WebView2 Runtime (almost all do). A server app also
needs its node.exe — use "The app's own Node" so a copy is included.</li>
<li><b>Shared runtime</b> apps need the runtime folder too; send it along and edit <i>electron-runtime.txt</i>.</li>
<li>Never share a <b>portable</b> app after signing in with it — the logins travel with the folder.</li>
</ul>

<h2 id="trouble"><a name="trouble"></a>11. Troubleshooting</h2>
<ul>
<li><b>❌ in the engine line</b> — open <b>Engines…</b>: install Node.js or repair the engine as shown there.</li>
<li><b>"Nativefier finished, but no app folder was created"</b> — read the log above it (often a failed download);
try <b>Install / repair engine</b>.</li>
<li><b>A site says the browser is not supported</b> — set <b>User agent</b> to chrome or edge.</li>
<li><b>Links open in my browser instead of the app</b> — add their address to <b>Internal URLs</b>, e.g.
<i>.*example\.com.*</i>.</li>
<li><b>A local-server app shows "The app's server did not start"</b> — the message shows the last lines of
<i>server\server.log</i>. Common causes: the node.exe path is wrong, a file is missing from the bundled folder
(check <b>Don't copy</b>), or another program uses the same port.</li>
<li><b>WebView2 app says the runtime is missing</b> — click Yes to open Microsoft's page and install the
"Evergreen" runtime.</li>
<li><b>Studio does not open</b> — <i>Advanced_Outboxer_Studio.bat</i> looks for a Python that has PySide6. Install it with
<i>python -m pip install PySide6</i>.</li>
<li><b>An app was rebuilt but looks old</b> — close the app completely (also from the tray) before rebuilding.</li>
</ul>

<h2 id="security"><a name="security"></a>12. Safety notes</h2>
<ul>
<li>Pages in your apps cannot reach your PC's files or Studio's internals.</li>
<li>Camera, microphone, location, notifications and clipboard reading are allowed only for the app's own site.</li>
<li>Downloads of Node.js, Electron and WebView2 are verified (checksums / Microsoft signatures) before use.</li>
<li>Only use <b>Ignore certificate errors</b> and <b>Allow insecure content</b> for sites you trust.</li>
<li><b>Project apps are different:</b> their pages <i>can</i> control the PC (that is the point of the toolbox).
Build only projects you wrote or trust, and keep <b>Websites that may use the toolbox</b> empty unless the site is
yours.</li>
</ul>

<h2 id="project"><a name="project"></a>13. Project folders, Electron app folders and the desktop toolbox</h2>
<h3>Quick start</h3>
<ol>
<li>Select <b>Source → Project folder</b>, then choose (or drag onto the window) the folder that has your
<i>index.html</i>. No folder yet? <b>File → New project from template…</b> (Ctrl+N).</li>
<li>Studio checks the project at once: start page, name, version, icon, broken links, wrong letter case in file names
(Windows ignores case, a web server does not), and every <i>desktop.*</i> command the pages use. The <b>Check</b> tab
shows the details; anything marked ❌ must be fixed before building.</li>
<li>Press <b>▶ Test Run</b>: the project runs as an app straight from its folder. Save a file and the app reloads by
itself. F12 opens the developer tools, F5 reloads.</li>
<li>Press <b>Build App</b>. The finished app is in <i>&lt;Output folder&gt;\&lt;App name&gt;</i>.</li>
</ol>
<h3>Electron: inside the app, or from this PC</h3>
<ul>
<li><b>Inside the app</b> — the app folder contains Electron (~250 MB) and runs on any Windows 10/11 PC.</li>
<li><b>From this PC (shared runtime)</b> — the app is only your pages plus a small launcher; it runs on the
Electron folder named in <i>electron-runtime.txt</i> (by default <i>Engines\runtime\electron-v&lt;version&gt;-win32-x64</i>).
Many apps can share one runtime.</li>
</ul>
<h3>What the pages can do</h3>
<p>Every page of the app gets <b>window.desktop</b>: keys and hotkeys (including AutoHotkey-style hotkeys,
hotstrings, remaps and CapsLock layers), mouse, windows of other programs, files and folders, clipboard, programs and
processes, tray icon and menu, dialogs and notifications, screen capture and OCR, power and system information,
audio volume and devices, the registry, network, a key/value <i>store</i> and SQLite <i>db</i>, printing, and
app control (windows, auto-start, single instance…). For anything not covered there are three master keys:
<b>desktop.exec</b> (run any program), <b>desktop.powershell</b> (run any PowerShell) and <b>desktop.win32</b> (call
any Windows API function). Code that must run in the background goes in the project's <b>desktop</b> folder and is
called with <b>desktop.call('file.function', …)</b>. <b>Help → Desktop toolbox guide</b> lists every command;
its <b>Add desktop.d.ts</b> button makes VS Code suggest them while you type.</p>
<h3>Electron app folders (e.g. MasterKey-Electron)</h3>
<p>A folder that is already a complete Electron app — it has <i>package.json</i> whose <b>"main"</b> names its own
main script, and uses Electron — is recognised automatically (<b>Project type</b> on the Project tab can force it).
Studio then packages the app <b>as it is</b>: its own main script runs instead of Studio's host, so its own
windows, tray, hotkeys and <i>preload</i> bridge (e.g. <i>window.mk</i>) work. Pick the app's whole source folder,
not only its HTML pages — pages alone cannot work without their back end.</p>
<ul>
<li><b>No npm needed.</b> Runtime packages come from the app's <i>node_modules</i>, else from Studio (koffi is
built in); only packages found in neither are installed once with Studio's own Node/npm (needs internet).</li>
<li>electron-builder settings in package.json are used where they make sense: productName, version, copyright,
<b>build.icon</b>, <b>extraResources</b> (put in the app's <i>resources</i> folder) and <b>extraFiles</b>
(next to the exe). node_modules, tests, the build and dist folders are left out.</li>
<li>When the app's Electron major version differs from Studio's, the app's own version is used.</li>
<li>Through the small launcher exe (shared runtime, or Electron in the <i>runtime</i> folder) the app still sees
itself as an installed app: <i>app.isPackaged</i> is true and <i>process.execPath</i> is the launcher, so
"Start with Windows" and files next to the exe work.</li>
<li><b>▶ Test Run</b> runs the app straight from its folder with its own main script (like <i>npm start</i>).
It does not reload by itself: press Stop and Test Run again after a change.</li>
<li>The Window, Tray &amp; Start and Behavior tabs are greyed out: the app controls those itself.</li>
</ul>
<h3>Projects that need building</h3>
<p>React, Vue, Svelte, Angular, Vite… projects: set the <b>Build command</b> (Studio fills in the one it detects,
e.g. <i>npm run build</i>) and tick <b>Run the build command</b>; the <b>Web folder</b> is then the build output
(dist, build…). Node.js comes from the Engines window.</p>
<h3>Engines of Outboxer Studio v1.0</h3>
<p>When Outboxer Studio v1.0 is next to this Studio (e.g. <i>C:\Tools\Outboxer Studio v1.0</i>) and this Studio's
Engines folder is empty, Studio offers once to <b>Copy</b> its engines or to <b>Use them in place</b>. You can
change the paths later in <b>Engines…</b>.</p>
'''


def wrap_exe(exe, args):
    """On Windows, .cmd/.bat shims must run through cmd.exe."""
    if IS_WIN and exe.lower().endswith((".cmd", ".bat")):
        return "cmd.exe", ["/c", exe, *args]
    return exe, list(args)


class PathField(QWidget):
    changed = Signal(str)  # after Browse, or when editing is finished

    def __init__(self, mode="file", file_filter="All files (*)", placeholder=""):
        super().__init__()
        self.mode, self.file_filter = mode, file_filter
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(lambda: self.edit.isModified() and self._emit())
        btn = QPushButton(glyph_icon("folder-open"), " Browse…")
        btn.clicked.connect(self.browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def browse(self):
        start = self.edit.text() or str(Path.home())
        if self.mode == "dir":
            p = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Choose file", start, self.file_filter)
        if p:
            self.edit.setText(os.path.normpath(p))
            self._emit()

    def _emit(self):
        self.edit.setModified(False)
        self.changed.emit(self.text())

    def text(self):
        return self.edit.text().strip()

    def setText(self, t):
        self.edit.setText(t)


class FileListField(QWidget):
    def __init__(self, file_filter):
        super().__init__()
        self.file_filter = file_filter
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(90)
        btns = QVBoxLayout()
        add, rem = QPushButton(glyph_icon("folder-open"), " Add…"), QPushButton(glyph_icon("x"), " Remove")
        add.clicked.connect(self.add)
        rem.clicked.connect(lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch()
        lay.addWidget(self.list, 1)
        lay.addLayout(btns)

    def add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files", str(Path.home()), self.file_filter)
        for f in files:
            self.list.addItem(os.path.normpath(f))

    def values(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def setValues(self, vals):
        self.list.clear()
        for v in vals or []:
            self.list.addItem(v)


class EnginesPage(QWidget):
    """The Engines window: where Node.js, the Nativefier engine and Electron come from, and updates."""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.cfg = mw.cfg
        self.job = None
        self.proc = None
        self.updates = {}   # what the last check found newer: {"node": "26.12.0", "electron": "45.1.0"}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        body.setObjectName("page")
        scroll.setObjectName("page")
        intro = QLabel(
            f"Everything Studio needs to build apps lives in <b>{short_path(ENGINES_DIR, 60)}</b> by default. "
            "You can point any engine somewhere else; your choices are saved in "
            f"<b>{self.cfg.path.name}</b> and used every time Studio starts.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)

        # --- Node.js
        g = QGroupBox("Node.js — runs Nativefier")
        f = QFormLayout(g)
        self.node_path = PathField("file", "Node (node.exe node);;All files (*)",
                                   f"Default: {DEFAULT_ENGINE_PATHS['node_path']}")
        self.node_path.changed.connect(lambda p: self._set_path("node_path", p))
        f.addRow("node.exe", self._with_default(self.node_path, "node_path"))
        self.node_info = QLabel()
        f.addRow("In use", self.node_info)
        self.node_channel = QComboBox()
        self.node_channel.addItem("Newest release (Current)", "current")
        self.node_channel.addItem("Long-term support (LTS)", "lts")
        self.node_channel.currentIndexChanged.connect(self._channel_changed)
        f.addRow("Update to", self.node_channel)
        self.node_latest = QLabel("—")
        f.addRow("Latest", self.node_latest)
        row = QHBoxLayout()
        self.node_update_btn = QPushButton(glyph_icon("download", "#FFFFFF"), " Update Node.js")
        self.node_update_btn.setObjectName("primary")
        self.node_update_btn.clicked.connect(self.update_node)
        row.addWidget(self.node_update_btn)
        row.addStretch()
        f.addRow("", row)
        lay.addWidget(g)

        # --- Nativefier engine
        g = QGroupBox("Nativefier engine")
        f = QFormLayout(g)
        self.nf_dir = PathField("dir", placeholder=f"Default: {short_path(DEFAULT_ENGINE_PATHS['nativefier_dir'], 60)}")
        self.nf_dir.changed.connect(lambda p: self._set_path("nativefier_dir", p))
        f.addRow("Folder", self._with_default(self.nf_dir, "nativefier_dir"))
        self.nf_info = QLabel()
        f.addRow("Installed", self.nf_info)
        self.nf_pkg = PathField("file", "Nativefier package (nativefier-*.tgz);;All files (*)",
                                f"A nativefier-*.tgz package (kept in {short_path(PACKAGES_DIR, 50)})")
        f.addRow("Package", self.nf_pkg)
        row = QHBoxLayout()
        self.nf_install_btn = QPushButton(glyph_icon("package"), " Install / repair engine")
        self.nf_install_btn.setToolTip("Installs the package into the engine folder with this Node's npm.\n"
                                       "Run it after moving Studio, or if the engine is damaged.")
        self.nf_install_btn.clicked.connect(self.install_engine)
        row.addWidget(self.nf_install_btn)
        row.addStretch()
        f.addRow("", row)
        lay.addWidget(g)

        # --- Electron
        g = QGroupBox("Electron — the browser inside every app")
        f = QFormLayout(g)
        self.el_dir = PathField("dir", placeholder=f"Default: {short_path(DEFAULT_ENGINE_PATHS['electron_dir'], 60)}")
        self.el_dir.changed.connect(lambda p: self._set_path("electron_dir", p))
        f.addRow("Zip folder", self._with_default(self.el_dir, "electron_dir"))
        self.el_version = QComboBox()
        self.el_version.setEditable(True)
        self.el_version.setToolTip("Electron version for new builds (the App tab can still override it per app).\n"
                                   "If its zip isn't in the folder yet, it is downloaded once on the first build.")
        self.el_version.lineEdit().editingFinished.connect(self._el_version_changed)
        self.el_version.activated.connect(lambda _i: self._el_version_changed())
        f.addRow("Use for builds", self.el_version)
        self.el_list = QListWidget()
        self.el_list.setMaximumHeight(96)
        self.el_list.itemDoubleClicked.connect(self._el_pick_from_list)
        self.el_list.setToolTip("Double-click a version to use it for builds")
        f.addRow("In the folder", self.el_list)
        self.el_latest = QLabel("—")
        f.addRow("Latest", self.el_latest)
        row = QHBoxLayout()
        self.el_update_btn = QPushButton(glyph_icon("download", "#FFFFFF"), " Download latest Electron")
        self.el_update_btn.setObjectName("primary")
        self.el_update_btn.clicked.connect(self.update_electron)
        open_el = QPushButton(glyph_icon("folder-open"), " Open folder")
        open_el.clicked.connect(lambda: self._open_dir(self.cfg.resolve("electron_dir")))
        row.addWidget(self.el_update_btn)
        row.addWidget(open_el)
        row.addStretch()
        f.addRow("", row)
        lay.addWidget(g)

        # --- Shared runtimes
        g = QGroupBox("Shared Electron runtimes — for apps built with “Electron: Shared runtime”")
        f = QFormLayout(g)
        self.rt_dir = PathField("dir", placeholder=f"Default: {short_path(DEFAULT_ENGINE_PATHS['runtime_dir'], 60)}")
        self.rt_dir.changed.connect(lambda p: self._set_path("runtime_dir", p))
        f.addRow("Folder", self._with_default(self.rt_dir, "runtime_dir"))
        self.rt_list = QListWidget()
        self.rt_list.setMaximumHeight(80)
        f.addRow("Unpacked", self.rt_list)
        note = QLabel("Each shared app has an <b>electron-runtime.txt</b> next to its .exe naming the runtime it uses. "
                      "Keep a runtime while any app points to it.")
        note.setWordWrap(True)
        f.addRow("", note)
        row = QHBoxLayout()
        open_rt = QPushButton(glyph_icon("folder-open"), " Open folder")
        open_rt.clicked.connect(lambda: self._open_dir(self.cfg.resolve("runtime_dir")))
        row.addWidget(open_rt)
        row.addStretch()
        f.addRow("", row)
        lay.addWidget(g)

        # --- WebView2
        g = QGroupBox("WebView2 — for apps built with “App engine: WebView2”")
        f = QFormLayout(g)
        rt_row = QHBoxLayout()
        self.wv_runtime = QLabel()
        get_rt = QPushButton(glyph_icon("external-link"), " Get the runtime")
        get_rt.setToolTip("Opens Microsoft's download page (it normally comes with Windows 10/11)")
        get_rt.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBVIEW2_RUNTIME_URL)))
        rt_row.addWidget(self.wv_runtime, 1)
        rt_row.addWidget(get_rt)
        self.wv_get_rt = get_rt
        f.addRow("Edge runtime", rt_row)
        self.wv_dir = PathField("dir", placeholder=f"Default: {short_path(DEFAULT_ENGINE_PATHS['webview2_dir'], 60)}")
        self.wv_dir.changed.connect(lambda p: self._set_path("webview2_dir", p))
        f.addRow("SDK folder", self._with_default(self.wv_dir, "webview2_dir"))
        self.wv_sdk = QLabel()
        f.addRow("SDK", self.wv_sdk)
        self.wv_latest = QLabel("—")
        f.addRow("Latest SDK", self.wv_latest)
        row = QHBoxLayout()
        self.wv_update_btn = QPushButton(glyph_icon("download", "#FFFFFF"), " Download latest WebView2 SDK")
        self.wv_update_btn.setObjectName("primary")
        self.wv_update_btn.clicked.connect(self.update_webview2_sdk)
        row.addWidget(self.wv_update_btn)
        row.addStretch()
        f.addRow("", row)
        note = QLabel("The <b>runtime</b> (the Edge engine that shows the pages) is part of Windows and updates itself. "
                      "The <b>SDK</b> is 2 small Microsoft DLLs that go into each WebView2 app.")
        note.setWordWrap(True)
        f.addRow("", note)
        lay.addWidget(g)

        # --- Updates
        g = QGroupBox("Updates")
        f = QVBoxLayout(g)
        row = QHBoxLayout()
        self.check_btn = QPushButton(glyph_icon("refresh-cw"), " Check for updates now")
        self.check_btn.clicked.connect(lambda: self.check_updates(silent=False))
        self.auto_check = QCheckBox("Check automatically when Studio starts")
        self.auto_check.setChecked(bool(self.cfg.get("auto_check_updates")))
        self.auto_check.toggled.connect(lambda on: self.cfg.set("auto_check_updates", on))
        open_cfg = QPushButton(glyph_icon("settings-2"), " Open config file")
        open_cfg.clicked.connect(lambda: self.cfg.path.is_file() and
                                 QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.cfg.path))))
        row.addWidget(self.check_btn)
        row.addWidget(self.auto_check)
        row.addStretch()
        row.addWidget(open_cfg)
        f.addLayout(row)
        self.last_check = QLabel()
        f.addWidget(self.last_check)
        lay.addWidget(g)
        lay.addStretch()

        # --- activity (progress + log for downloads and installs)
        act = QHBoxLayout()
        self.act_label = QLabel("")
        self.act_bar = QProgressBar()
        self.act_bar.setRange(0, 1)
        self.act_bar.setFormat("%p%")
        self.act_bar.setObjectName("withText")
        self.cancel_btn = QPushButton(glyph_icon("x"), " Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        act.addWidget(self.act_label)
        act.addWidget(self.act_bar, 1)
        act.addWidget(self.cancel_btn)
        outer.addLayout(act)
        self.act_log = QPlainTextEdit(readOnly=True)
        self.act_log.setObjectName("console")
        self.act_log.setMaximumHeight(110)
        self.act_log.setPlaceholderText("Engine activity appears here.")
        outer.addWidget(self.act_log)

        i = self.node_channel.findData(self.cfg.get("node_channel"))
        self.node_channel.blockSignals(True)
        self.node_channel.setCurrentIndex(max(i, 0))
        self.node_channel.blockSignals(False)
        self.refresh()

    # ------------------------------------------------------------------ helpers
    def _with_default(self, field, key):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(field, 1)
        b = QPushButton(glyph_icon("rotate-ccw"), " Use default")
        b.setToolTip(f"Use {DEFAULT_ENGINE_PATHS[key]}")
        b.clicked.connect(lambda: self._set_path(key, ""))
        h.addWidget(b)
        return w

    def _set_path(self, key, path):
        self.cfg.set_path(key, path.strip() if path else "")
        self.log(f"Saved: {key.replace('_', ' ')} = {self.cfg.resolve(key)}")
        self.refresh()
        self.mw.refresh_engine_status()

    def _channel_changed(self):
        self.cfg.set("node_channel", self.node_channel.currentData())
        self.refresh()

    def _el_version_changed(self):
        v = self.el_version.currentText().strip().split()[0] if self.el_version.currentText().strip() else ""
        v = v.lstrip("v")
        if not v or v == self.cfg.get("electron_version"):
            return
        if not version_tuple(v):
            QMessageBox.warning(self, APP_NAME, f"'{v}' is not an Electron version (e.g. 44.7.0).")
            self.refresh()
            return
        if not self._confirm_electron_major(v):
            self.refresh()
            return
        self.cfg.set("electron_version", v)
        self.log(f"Saved: new builds use Electron {v}")
        self.refresh()
        self.mw.refresh_engine_status()

    def _el_pick_from_list(self, item):
        v = item.data(Qt.UserRole)
        if v:
            self.el_version.setEditText(v)
            self._el_version_changed()

    def _confirm_electron_major(self, v):
        major = (version_tuple(v) or (0,))[0]
        if major <= TESTED_ELECTRON_MAJOR:
            return True
        return QMessageBox.question(
            self, APP_NAME,
            f"Electron {v} is newer than the version this Nativefier engine was tested with "
            f"(Electron {TESTED_ELECTRON_MAJOR}).\n\nIt will most likely work. If a built app misbehaves, "
            f"switch back to {DEFAULT_ELECTRON_VERSION} here.\n\nUse Electron {v} for new builds?") == QMessageBox.Yes

    @staticmethod
    def _open_dir(p):
        p = Path(p)
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def log(self, text):
        self.act_log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {text}")

    @property
    def busy(self):
        return bool((self.job and self.job.isRunning()) or
                    (self.proc and self.proc.state() != QProcess.NotRunning))

    def _set_busy(self, busy, label=""):
        for b in (self.node_update_btn, self.el_update_btn, self.nf_install_btn, self.check_btn, self.wv_update_btn):
            b.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.act_label.setText(label)
        self.act_bar.setRange(0, 0 if busy else 1)
        self.act_bar.setValue(0 if busy else 1)
        self.mw.on_engines_busy(busy)

    # ------------------------------------------------------------------ state
    def node_state(self):
        exe, how = resolve_node(self.cfg)
        ver = node_version_of(exe) if exe else ""
        return exe, how, ver

    def refresh(self):
        cfg = self.cfg
        latest = cfg.get("latest") or {}
        for field, key in ((self.node_path, "node_path"), (self.nf_dir, "nativefier_dir"),
                           (self.el_dir, "electron_dir"), (self.rt_dir, "runtime_dir"),
                           (self.wv_dir, "webview2_dir")):
            field.blockSignals(True)
            field.setText("" if cfg.is_default(key) else str(cfg.resolve(key)))
            field.blockSignals(False)

        # Node
        exe, how, ver = self.node_state()
        nf = nativefier_info(cfg.resolve("nativefier_dir"))
        need = nf["min_node"] if nf else FALLBACK_MIN_NODE
        where = {"engines": "Engines folder", "custom": "your path", "system": "Node installed on this PC"}.get(how, "")
        if not exe:
            self.node_info.setText("❌ Not found — click <b>Update Node.js</b> to download it into Engines.")
        elif not ver:
            self.node_info.setText(f"❌ {exe} does not run.")
        elif version_tuple(ver) < need:
            self.node_info.setText(f"⚠️ {ver} ({where}) — this engine needs Node {'.'.join(map(str, need))} or newer.")
        else:
            self.node_info.setText(f"✅ {ver} — {where}<br><span style='color:gray'>{short_path(exe)}</span>")
            self.node_info.setToolTip(str(exe))
        chan = self.node_channel.currentData()
        lv = latest.get("node_lts" if chan == "lts" else "node_current")
        self.updates.pop("node", None)
        if lv:
            lts = f" (LTS “{latest.get('node_lts_name')}”)" if chan == "lts" and latest.get("node_lts_name") else ""
            if how != "engines":
                self.node_latest.setText(f"v{lv}{lts} — update downloads it into Engines and switches to it.")
                self.updates["node"] = lv if (not ver or is_newer(lv, ver)) else None
            elif is_newer(lv, ver):
                self.node_latest.setText(f"⬆ v{lv}{lts} is available")
                self.updates["node"] = lv
            else:
                self.node_latest.setText(f"✅ v{lv}{lts} — up to date")
        else:
            self.node_latest.setText("— (not checked yet)")
        self.node_update_btn.setEnabled(IS_WIN and not self.busy)
        if not IS_WIN:
            self.node_update_btn.setToolTip("Automatic Node updates are Windows-only; pick a node path instead.")

        # Nativefier
        if nf:
            ok = bool(ver) and version_tuple(ver) >= nf["min_node"]
            self.nf_info.setText(f"{'✅' if ok else '⚠️'} Nativefier {nf['version'] or '?'} — needs Node "
                                 f"{'.'.join(map(str, nf['min_node']))}+<br><span style='color:gray'>{short_path(nf['cli'])}</span>")
            self.nf_info.setToolTip(str(nf["cli"]))
        else:
            self.nf_info.setText("❌ No engine in this folder — click <b>Install / repair engine</b>.")
        if not self.nf_pkg.text():
            pkgs = sorted(PACKAGES_DIR.glob("nativefier-*.tgz"), key=lambda p: version_tuple(p.name), reverse=True)
            if pkgs:
                self.nf_pkg.setText(str(pkgs[0]))

        # Electron
        zips = electron_zips(cfg.resolve("electron_dir"))
        cur = cfg.get("electron_version") or DEFAULT_ELECTRON_VERSION
        self.el_list.clear()
        for v, plat, arch, p, size in zips:
            mark = "  ← used for builds" if v == cur and plat == HOST_PLATFORM else ""
            it = QListWidgetItem(f"{v}   {plat}-{arch}   {human_size(size)}{mark}")
            it.setData(Qt.UserRole, v)
            self.el_list.addItem(it)
        if not zips:
            self.el_list.addItem("(no Electron zips yet — the first build downloads one)")
        self.el_version.blockSignals(True)
        self.el_version.clear()
        seen = []
        for v in [cur, DEFAULT_ELECTRON_VERSION, latest.get("electron")] + [z[0] for z in zips]:
            if v and v not in seen:
                seen.append(v)
                self.el_version.addItem(v)
        self.el_version.setEditText(cur)
        self.el_version.blockSignals(False)
        le = latest.get("electron")
        have_latest = any(z[0] == le and z[1] == HOST_PLATFORM for z in zips)
        self.updates.pop("electron", None)
        if le:
            if is_newer(le, cur) and not have_latest:
                self.el_latest.setText(f"⬆ {le} is available")
                self.updates["electron"] = le
            elif is_newer(le, cur):
                self.el_latest.setText(f"{le} is downloaded — pick it above to use it")
            else:
                self.el_latest.setText(f"✅ {le} — up to date")
        else:
            self.el_latest.setText("— (not checked yet)")

        self.rt_list.clear()
        rts = runtimes_in(cfg.resolve("runtime_dir"))
        for v, p, size in rts:
            self.rt_list.addItem(f"Electron {v}   {human_size(size)}   {p.name}")
        if not rts:
            self.rt_list.addItem("(none yet — the first shared-runtime build unpacks one)")

        # WebView2
        rtv = webview2_runtime_version()
        self.wv_runtime.setText(f"✅ {rtv} — part of Windows, updates itself" if rtv else
                                ("❌ Not installed — WebView2 apps will offer to install it" if IS_WIN else
                                 "— (Windows only)"))
        self.wv_get_rt.setVisible(IS_WIN and not rtv)
        sdks = webview2_sdks(cfg.resolve("webview2_dir"))
        self.wv_sdk.setText(("✅ " + ", ".join(v for v, _p in sdks)) if sdks else
                            "Not downloaded yet — the first WebView2 build gets it automatically")
        lw = latest.get("webview2_sdk")
        self.updates.pop("webview2", None)
        if lw:
            if not sdks or full_version_tuple(lw) > full_version_tuple(sdks[0][0]):
                self.wv_latest.setText(f"⬆ {lw} is available" if sdks else f"{lw}")
                if sdks:
                    self.updates["webview2"] = lw
            else:
                self.wv_latest.setText(f"✅ {lw} — up to date")
        else:
            self.wv_latest.setText("— (not checked yet)")

        checked = latest.get("checked")
        self.last_check.setText("Last checked: " + (time.strftime("%Y-%m-%d %H:%M", time.localtime(checked))
                                                    if checked else "never"))
        self.updates = {k: v for k, v in self.updates.items() if v}
        self.mw.on_updates_found(self.updates)

    # ------------------------------------------------------------------ actions
    def _run(self, label, fn, on_ok):
        if self.busy or self.mw.build_running():
            QMessageBox.information(self, APP_NAME, "Please wait for the current task to finish.")
            return
        self.job = Job(fn, self)
        self.job.message.connect(lambda t: (self.act_label.setText(t), self.log(t)))
        self.job.progress.connect(self._progress)
        self.job.succeeded.connect(lambda r: (self._set_busy(False), on_ok(r)))
        self.job.failed.connect(self._job_failed)
        self._set_busy(True, label)
        self.log(label)
        self.job.start()

    def _progress(self, done_kb, total_kb):
        if total_kb > 0:
            self.act_bar.setRange(0, total_kb)
            self.act_bar.setValue(min(done_kb, total_kb))
            self.act_bar.setFormat(f"%p%  ({human_size(done_kb * 1024)} of {human_size(total_kb * 1024)})")
        else:
            self.act_bar.setRange(0, 0)

    def _job_failed(self, msg, silent=False):
        self._set_busy(False)
        self.act_bar.setFormat("%p%")
        self.log(f"❌ {msg}")
        if not silent:
            QMessageBox.warning(self, APP_NAME, msg)

    def cancel(self):
        if self.job and self.job.isRunning():
            self.job.cancelled = True
            self.log("Cancelling…")
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()

    def check_updates(self, silent=True):
        def done(res):
            latest = {k: v for k, v in res.items() if k != "errors"}
            merged = dict(self.cfg.get("latest") or {})
            merged.update(latest)
            self.cfg.set("latest", merged)
            for e in res.get("errors", []):
                self.log(f"⚠️ Could not check {e}")
            self.refresh()
            found = ", ".join(f"{UPDATE_NAMES.get(k, k)} {v}" for k, v in self.updates.items())
            msg = f"Updates available: {found}" if found else "Everything is up to date."
            self.log(msg)
            self.mw.statusBar().showMessage(msg, 8000)
            if not silent and res.get("errors") and len(res["errors"]) >= 3:
                QMessageBox.warning(self, APP_NAME, "Could not check for updates:\n\n" + "\n".join(res["errors"]))
        if silent:  # start-up check: no dialogs, no interrupting a build
            if self.busy or self.mw.build_running():
                return
            self.job = Job(lambda j: fetch_latest_versions(), self)
            self.job.succeeded.connect(done)
            self.job.failed.connect(lambda m: self.log(f"Update check skipped: {m}"))
            self.job.start()
        else:
            self._run("Checking for updates…", lambda j: fetch_latest_versions(), done)

    def auto_check_if_due(self):
        last = (self.cfg.get("latest") or {}).get("checked") or 0
        if self.cfg.get("auto_check_updates") and time.time() - last > UPDATE_CHECK_EVERY:
            self.check_updates(silent=True)

    def update_node(self):
        latest = self.cfg.get("latest") or {}
        chan = self.node_channel.currentData()
        target = latest.get("node_lts" if chan == "lts" else "node_current")
        exe, how, ver = self.node_state()

        def go(v):
            if how == "engines" and ver and not is_newer(v, ver):
                QMessageBox.information(self, APP_NAME, f"Node.js {ver} is already the latest ({v}).")
                return
            if QMessageBox.question(
                    self, APP_NAME,
                    f"Download Node.js {v} (about 30 MB, from nodejs.org) into\n{ENGINES_DIR / 'node'}\n\n"
                    "Its checksum is verified before it replaces the current one."
                    + ("\n\nStudio will then use it instead of your current Node path." if how != "engines" else "")
            ) != QMessageBox.Yes:
                return
            self._run(f"Updating Node.js to {v}…", lambda j: install_node(v, j), self._node_installed)

        if target:
            go(target)
        else:  # never checked: check first, then continue
            def after(res):
                merged = dict(self.cfg.get("latest") or {})
                merged.update({k: v for k, v in res.items() if k != "errors"})
                self.cfg.set("latest", merged)
                self.refresh()
                v = res.get("node_lts" if chan == "lts" else "node_current")
                if v:
                    go(v)
                else:
                    QMessageBox.warning(self, APP_NAME, "Could not find the latest Node.js:\n" +
                                        "\n".join(res.get("errors") or ["unknown error"]))
            self._run("Checking the latest Node.js…", lambda j: fetch_latest_versions(), after)

    def _node_installed(self, exe):
        self.cfg.set_path("node_path", "")  # use the Engines copy from now on
        self.log(f"✅ Node.js {node_version_of(exe)} installed: {exe}")
        self.act_label.setText("Node.js updated")
        self.refresh()
        self.mw.refresh_engine_status()

    def update_electron(self):
        latest = (self.cfg.get("latest") or {}).get("electron")

        def go(v):
            folder = self.cfg.resolve("electron_dir")
            name = f"electron-v{v}-{HOST_PLATFORM}-{HOST_ARCH}.zip"
            if not (folder / name).is_file() and QMessageBox.question(
                    self, APP_NAME, f"Download Electron {v} ({name}, about 110–160 MB, from GitHub) into\n"
                                    f"{folder}?\n\nIts checksum is verified before it is used.") != QMessageBox.Yes:
                return
            self._run(f"Getting Electron {v}…", lambda j: download_electron(v, folder, j),
                      lambda p: self._electron_ready(v, p))

        if latest:
            go(latest)
        else:
            def after(res):
                merged = dict(self.cfg.get("latest") or {})
                merged.update({k: v for k, v in res.items() if k != "errors"})
                self.cfg.set("latest", merged)
                self.refresh()
                if res.get("electron"):
                    go(res["electron"])
                else:
                    QMessageBox.warning(self, APP_NAME, "Could not find the latest Electron:\n" +
                                        "\n".join(res.get("errors") or ["unknown error"]))
            self._run("Checking the latest Electron…", lambda j: fetch_latest_versions(), after)

    def _electron_ready(self, v, path):
        self.log(f"✅ Electron {v} ready: {path}")
        self.act_label.setText(f"Electron {v} ready")
        if v != self.cfg.get("electron_version") and self._confirm_electron_major(v):
            self.cfg.set("electron_version", v)
            self.log(f"Saved: new builds use Electron {v}")
        self.refresh()
        self.mw.refresh_engine_status()

    def update_webview2_sdk(self):
        latest = (self.cfg.get("latest") or {}).get("webview2_sdk")
        folder = self.cfg.resolve("webview2_dir")

        def go(v):
            self._run(f"Getting the WebView2 SDK {v}…", lambda j: download_webview2_sdk(v, folder, j),
                      lambda p: (self.log(f"✅ WebView2 SDK {v} ready: {p} (new WebView2 builds use the newest)"),
                                 self.act_label.setText(f"WebView2 SDK {v} ready"), self.refresh(),
                                 self.mw.refresh_engine_status()))
        if latest:
            go(latest)
        else:
            def after(res):
                merged = dict(self.cfg.get("latest") or {})
                merged.update({k: v for k, v in res.items() if k != "errors"})
                self.cfg.set("latest", merged)
                self.refresh()
                if res.get("webview2_sdk"):
                    go(res["webview2_sdk"])
                else:
                    QMessageBox.warning(self, APP_NAME, "Could not find the latest WebView2 SDK:\n" +
                                        "\n".join(res.get("errors") or ["unknown error"]))
            self._run("Checking the latest WebView2 SDK…", lambda j: fetch_latest_versions(), after)

    def install_engine(self):
        if self.busy or self.mw.build_running():
            QMessageBox.information(self, APP_NAME, "Please wait for the current task to finish.")
            return
        exe, how, ver = self.node_state()
        if not exe or not ver:
            QMessageBox.warning(self, APP_NAME, "Node.js is needed first — click 'Update Node.js'.")
            return
        npm = npm_cli_for(exe)
        if not npm:
            QMessageBox.warning(self, APP_NAME, f"npm was not found next to {exe}.\n"
                                                "Click 'Update Node.js' to get a complete Node.js in Engines.")
            return
        pkg = Path(self.nf_pkg.text()) if self.nf_pkg.text() else None
        if not pkg or not pkg.is_file():
            QMessageBox.warning(self, APP_NAME, "Choose the Nativefier package (nativefier-53.x.tgz) first.")
            return
        # keep the package inside Engines\packages, so the engine can be repaired later
        PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
        if pkg.parent.resolve() != PACKAGES_DIR.resolve():
            shutil.copy2(pkg, PACKAGES_DIR / pkg.name)
            pkg = PACKAGES_DIR / pkg.name
            self.nf_pkg.setText(str(pkg))
        target = self.cfg.resolve("nativefier_dir")
        target.mkdir(parents=True, exist_ok=True)
        args = [str(npm), "install", "--prefix", str(target), str(pkg),
                "--omit=dev", "--no-audit", "--no-fund", "--loglevel=error"]
        self.log(f"Installing {pkg.name} into {target} (needs internet for its dependencies)…")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.setWorkingDirectory(str(target))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PATH", str(Path(exe).parent) + os.pathsep + env.value("PATH", ""))
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(lambda: [
            self.log(l) for l in bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace").splitlines()
            if l.strip()])
        self.proc.finished.connect(self._engine_installed)
        self._set_busy(True, "Installing the Nativefier engine…")
        self.proc.start(str(exe), args)

    def _engine_installed(self, code, status):
        self._set_busy(False)
        nf = nativefier_info(self.cfg.resolve("nativefier_dir"))
        if code == 0 and status == QProcess.NormalExit and nf:
            self.log(f"✅ Nativefier {nf['version']} engine installed.")
            self.act_label.setText("Engine installed")
        else:
            self.log("❌ Engine install failed — see the lines above.")
            QMessageBox.warning(self, APP_NAME, "Installing the engine failed. Details are in the activity log.")
        self.refresh()
        self.mw.refresh_engine_status()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1150, 780)
        self.setAcceptDrops(True)
        self.settings = QSettings("SayedTools", "AdvancedOutboxerStudio")
        old = QSettings("SayedTools", "NativefierStudio")   # bring over window size/theme once, then tidy up
        if old.allKeys():
            for k in ("dark", "geometry"):
                if old.contains(k) and not self.settings.contains(k):
                    self.settings.setValue(k, old.value(k))
            old.clear()
        self.widgets = {}
        self.defaults = {}
        self.proc = None
        self.last_output_dir = None
        self.engine = None
        self.cfg = StudioConfig()
        self.project_mode = project_ui.ProjectMode(self)
        try:
            migrate_old_layout()
        except OSError:
            pass

        self._build_menu()
        self._build_ui()
        self._restore_state()
        self.refresh_engine_status()
        self.update_preview()
        if self.cfg.load_error:
            self.engines_page.log(f"⚠️ {CONFIG_NAME} could not be read ({self.cfg.load_error}); "
                                  "defaults are used and the old file was kept as .json.bad")
        if not self.cfg.path.is_file():
            try:
                self.cfg.save()
            except OSError as ex:
                self.engines_page.log(f"⚠️ Could not write {self.cfg.path}: {ex}")
        QTimer.singleShot(2000, self.engines_page.auto_check_if_due)
        QTimer.singleShot(800, lambda: project_ui.offer_engine_import(self))

    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        m = round_menu(self.menuBar().addMenu("&File"))
        for text, slot, sc, icon in [("Load preset…", self.load_preset, "Ctrl+O", ("folder-input", "indigo")),
                                     ("Save preset…", self.save_preset, "Ctrl+S", ("save", "indigo")),
                                     ("Reset all fields", self.reset_fields, None, ("rotate-ccw", "slate"))]:
            a = QAction(tile_icon(*icon), text, self)
            if sc:
                a.setShortcut(sc)
            a.triggered.connect(slot)
            m.addAction(a)
        m.addSeparator()
        for text, slot, sc, icon in [("New project from template…", lambda: self.project_mode.new_project(), "Ctrl+N",
                                      ("file-plus", "green")),
                                     ("Open project folder…", lambda: self.project_mode.open_project(), "Ctrl+Shift+O",
                                      ("folder-open", "amber"))]:
            a = QAction(tile_icon(*icon), text, self)
            a.setShortcut(sc)
            a.triggered.connect(slot)
            m.addAction(a)
        m.addSeparator()
        q = QAction(tile_icon("log-out", "red"), "Quit", self)
        q.triggered.connect(self.close)
        m.addAction(q)

        t = round_menu(self.menuBar().addMenu("&Tools"))
        a = QAction(tile_icon("cpu", "orange"), "Engines…", self)
        a.setShortcut("Ctrl+E")
        a.triggered.connect(self.open_engines)
        t.addAction(a)

        h = round_menu(self.menuBar().addMenu("&Help"))
        a = QAction(tile_icon("book-open", "green"), "User Manual", self)
        a.setShortcut("F1")
        a.triggered.connect(self.show_manual)
        h.addAction(a)
        a = QAction(tile_icon("code", "purple"), "Desktop toolbox guide", self)
        a.setShortcut("Shift+F1")
        a.triggered.connect(lambda: self.project_mode.show_guide())
        h.addAction(a)
        a = QAction(tile_icon("flask-conical", "teal"), "Open the toolbox example project", self)
        a.triggered.connect(lambda: self.project_mode.open_example())
        h.addAction(a)
        h.addSeparator()
        a = QAction(tile_icon("info", "slate"), f"About {APP_NAME}", self)
        a.triggered.connect(self.show_about)
        h.addAction(a)

    SECTIONS = [  # (option tab, sidebar label, icon, tile colour, description)
        ("App", "App", "app-window", "indigo", "Engine, name, icon and version of the app."),
        ("Window", "Window", "monitor", "blue", "Size, position and how the app's window looks."),
        ("Behavior", "Behavior", "mouse-pointer-click", "purple",
         "Which links stay inside the app, how it introduces itself, zoom and your own CSS/JS."),
        ("Advanced", "Advanced", "sliders-horizontal", "slate",
         "Proxy, sign-in, downloads, shortcuts and browser flags."),
        ("Server", "Server", "server", "teal",
         "For web apps that need their own local server (like UMA): the server goes inside the app "
         "and starts and stops with it."),
    ]

    def _build_ui(self):
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- sidebar: brand + sections + links
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 16, 12, 12)
        sl.setSpacing(6)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(tile_icon("package", "purple").pixmap(32, 32))
        brand.addWidget(logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        bn = QLabel(APP_NAME)
        bn.setObjectName("brand")
        bn.setWordWrap(True)
        bv = QLabel(f"v{APP_VERSION}")
        bv.setObjectName("hint")
        bt.addWidget(bn)
        bt.addWidget(bv)
        brand.addLayout(bt, 1)
        sl.addLayout(brand)
        sl.addSpacing(10)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(24, 24))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for _tab, label, icon, color, _desc in self.SECTIONS:
            it = QListWidgetItem(tile_icon(icon, color), "  " + label)
            it.setSizeHint(QSize(180, 42))
            self.nav.addItem(it)
        self.nav.setFixedHeight(42 * len(self.SECTIONS) + 12)
        sl.addWidget(self.nav)
        self.pnav = QListWidget()           # filled by project mode (its sections)
        self.pnav.setObjectName("nav")
        self.pnav.setIconSize(QSize(24, 24))
        self.pnav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pnav.hide()
        sl.addWidget(self.pnav)
        sl.addStretch()

        def side_link(icon, color, text, slot, tip=""):
            b = QToolButton()
            b.setObjectName("sideLink")
            b.setIcon(tile_icon(icon, color))
            b.setIconSize(QSize(24, 24))
            b.setText("  " + text)
            b.setToolTip(tip)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            sl.addWidget(b)
            return b

        self.engines_btn = side_link("cpu", "orange", "Engines", self.open_engines,
                                     "Node.js, the Nativefier engine, Electron and WebView2: paths and updates")
        side_link("book-open", "green", "User Manual", self.show_manual, "F1")
        side_link("info", "slate", "About", self.show_about)
        outer.addWidget(side)

        # ---- content
        content = QWidget()
        content.setObjectName("page")
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(12)

        head = QHBoxLayout()
        ht = QVBoxLayout()
        ht.setSpacing(2)
        title = QLabel("Build an app")
        title.setObjectName("title")
        sub = QLabel("Turn a website, a local web app or your own project folder into a desktop app.")
        sub.setObjectName("muted")
        ht.addWidget(title)
        ht.addWidget(sub)
        head.addLayout(ht, 1)
        self.engine_status = QLabel()
        self.engine_status.setTextFormat(Qt.RichText)
        self.engine_status.setObjectName("pillOk")
        self.engine_status.setCursor(Qt.PointingHandCursor)
        self.engine_status.mousePressEvent = lambda e: self.open_engines()
        head.addWidget(self.engine_status, 0, Qt.AlignTop)
        root.addLayout(head)

        # target card
        tgt, tl = card()
        tf = QFormLayout()
        tf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tf.setHorizontalSpacing(12)
        self.target_form = tf
        tf.addRow("Source", self.project_mode.make_source_row())
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://web.whatsapp.com   (you can also drag a link onto the window)")
        self.url_edit.addAction(glyph_icon("globe"), QLineEdit.LeadingPosition)
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.textChanged.connect(self.update_preview)
        open_btn = QPushButton(glyph_icon("external-link"), " Open in browser")
        open_btn.clicked.connect(lambda: self.url_edit.text() and QDesktopServices.openUrl(QUrl(self.url_edit.text())))
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(open_btn)
        tf.addRow("URL", url_row)
        self.url_row_index = tf.rowCount() - 1
        tf.addRow("Project", self.project_mode.make_project_row())
        self.project_mode.folder_row_index = tf.rowCount() - 1
        tf.setRowVisible(self.project_mode.folder_row_index, False)
        self.out_dir = PathField("dir", placeholder="Your Desktop (default) — apps go to <folder>\\<App name>")
        self.out_dir.edit.addAction(glyph_icon("folder-open"), QLineEdit.LeadingPosition)
        self.out_dir.edit.textChanged.connect(self.update_preview)
        tf.addRow("Output folder", self.out_dir)
        tl.addLayout(tf)
        root.addWidget(tgt)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # options card: section title + stacked pages (one per sidebar entry)
        opt, ol = card()
        self.sec_title = QLabel()
        self.sec_title.setObjectName("section")
        self.sec_desc = QLabel()
        self.sec_desc.setObjectName("muted")
        self.sec_desc.setWordWrap(True)
        ol.addWidget(self.sec_title)
        ol.addWidget(self.sec_desc)
        self.pages = QStackedWidget()
        tab_forms = {}
        for tab, *_rest in self.SECTIONS:
            page = QWidget()
            page.setObjectName("page")
            form = QFormLayout(page)
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(9)
            form.setContentsMargins(0, 8, 10, 4)
            if tab == "App":
                self.icon_preview = QLabel("No icon")
                self.icon_preview.setObjectName("iconPreview")
                self.icon_preview.setFixedSize(72, 72)
                self.icon_preview.setAlignment(Qt.AlignCenter)
                form.addRow("Icon preview", self.icon_preview)
            scroll = QScrollArea()
            scroll.setObjectName("page")
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
            tab_forms[tab] = form
        ol.addWidget(self.pages, 1)
        ol.addWidget(self.project_mode.make_panel(), 1)
        self.nav.currentRowChanged.connect(self._show_section)

        for key, flag, kind, label, tab, extra in OPTIONS:
            w = self._make_widget(kind, extra)
            self.widgets[key] = (w, kind, flag)
            self.defaults[key] = extra.get("default")
            tip = flag or ("Appended verbatim to the command" if key == "extra_args"
                           else "Handled by Outboxer Studio after the build")
            w.setToolTip(tip)
            tab_forms[tab].addRow(label, w)
            self._connect_change(w, kind)
        self.widgets["icon"][0].edit.textChanged.connect(self.update_icon_preview)
        self.widgets["electron_mode"][0].currentIndexChanged.connect(self.update_mode_ui)
        self.widgets["server_node"][0].currentIndexChanged.connect(self.update_mode_ui)
        splitter.addWidget(opt)

        # preview + log card
        bottom, bl = card()
        prev_row = QHBoxLayout()
        self.preview_label = QLabel("COMMAND PREVIEW")
        self.preview_label.setObjectName("caption")
        prev_row.addWidget(self.preview_label)
        prev_row.addStretch()
        copy_btn = QToolButton()
        copy_btn.setIcon(glyph_icon("copy"))
        copy_btn.setToolTip("Copy")
        copy_btn.clicked.connect(lambda: (QApplication.clipboard().setText(self.preview.toPlainText()),
                                          toast(copy_btn, "✅ Copied")))
        prev_row.addWidget(copy_btn)
        bl.addLayout(prev_row)
        self.preview = QPlainTextEdit(readOnly=True)
        self.preview.setObjectName("console")
        self.preview.setMaximumHeight(74)
        bl.addWidget(self.preview)
        log_row = QHBoxLayout()
        cap = QLabel("BUILD LOG")
        cap.setObjectName("caption")
        log_row.addWidget(cap)
        log_row.addStretch()
        clr = QToolButton()
        clr.setIcon(glyph_icon("eraser"))
        clr.setToolTip("Clear the log")
        clr.clicked.connect(lambda: self.log.clear())
        log_row.addWidget(clr)
        bl.addLayout(log_row)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setObjectName("console")
        self.log.setPlaceholderText("Build progress appears here.")
        bl.addWidget(self.log, 1)
        splitter.addWidget(bottom)
        splitter.setSizes([440, 260])
        root.addWidget(splitter, 1)

        # action bar
        act = QHBoxLayout()
        act.setSpacing(8)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(False)
        self.open_out_btn = QPushButton(glyph_icon("folder-open"), " Open output folder")
        self.open_out_btn.setEnabled(False)
        self.open_out_btn.clicked.connect(self.open_output)
        self.stop_btn = QPushButton(glyph_icon("square", "#B91C1C"), " Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.build_btn = QPushButton(glyph_icon("hammer", "#FFFFFF"), " Build App")
        self.build_btn.setObjectName("primary")
        self.build_btn.setMinimumWidth(150)
        self.build_btn.setMinimumHeight(34)
        self.build_btn.clicked.connect(self.build_app)
        act.addWidget(self.progress, 1)
        act.addWidget(self.open_out_btn)
        act.addWidget(self.stop_btn)
        act.addWidget(self.project_mode.make_test_button())
        act.addWidget(self.build_btn)
        root.addLayout(act)
        outer.addWidget(content, 1)

        self.engines_page = EnginesPage(self)
        self.engines_win = QDialog(self)
        self.engines_win.setWindowTitle(f"Engines — {APP_TITLE}")
        self.engines_win.setWindowFlags(self.engines_win.windowFlags() | Qt.WindowMaximizeButtonHint
                                        | Qt.WindowMinimizeButtonHint)
        self.engines_win.resize(980, 880)
        ew = QVBoxLayout(self.engines_win)
        ew.setContentsMargins(20, 16, 20, 14)
        eh = QVBoxLayout()
        eh.setSpacing(2)
        et = QLabel("Engines")
        et.setObjectName("title")
        ed = QLabel("Where Node.js, the Nativefier engine, Electron and WebView2 come from — and their updates. "
                    "Project apps use the same Electron zips and runtimes.")
        ed.setObjectName("muted")
        eh.addWidget(et)
        eh.addWidget(ed)
        ew.addLayout(eh)
        ew.addWidget(self.engines_page)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.nav.setCurrentRow(0)

        self.apply({k: None for k in self.widgets})

    def _show_section(self, row):
        if row < 0:
            return
        _tab, label, _icon, _color, desc = self.SECTIONS[row]
        self.pages.setCurrentIndex(row)
        self.sec_title.setText(label)
        self.sec_desc.setText(desc)

    def show_section_text(self, title, desc):
        self.sec_title.setText(title)
        self.sec_desc.setText(desc)

    def set_source_mode(self, project):
        """Website ⇄ Project folder: swap the sidebar sections, option pages and target rows."""
        self.nav.setVisible(not project)
        self.pnav.setVisible(project)
        self.pages.setVisible(not project)
        self.project_mode.panel.setVisible(project)
        self.target_form.setRowVisible(self.url_row_index, not project)
        self.target_form.setRowVisible(self.project_mode.folder_row_index, project)
        if project:
            if self.pnav.currentRow() < 0:
                self.pnav.setCurrentRow(0)
            self.project_mode.panel.tabs.show_current()
        else:
            self._show_section(max(self.nav.currentRow(), 0))

    def _make_widget(self, kind, extra):
        if kind == "text":
            w = QLineEdit()
            w.setPlaceholderText(extra.get("ph", ""))
            if extra.get("password"):
                w.setEchoMode(QLineEdit.Password)
        elif kind == "int":
            w = QSpinBox()
            w.setRange(0, extra.get("max", 100000))
            w.setSpecialValueText("default")
        elif kind == "float":
            w = QDoubleSpinBox()
            w.setRange(0.0, 5.0)
            w.setSingleStep(0.1)
            w.setDecimals(2)
            w.setSpecialValueText("default")
        elif kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(extra.get("default")))
        elif kind in ("choice", "ecombo"):
            w = QComboBox()
            w.setEditable(kind == "ecombo")
            for it in extra["items"]:
                if isinstance(it, tuple):  # (value, label)
                    w.addItem(it[1], it[0])
                else:
                    w.addItem(it if it else "(default)", it)
        elif kind in ("file", "dir"):
            w = PathField(kind, extra.get("filter", "All files (*)"), extra.get("ph", ""))
        elif kind == "files":
            w = FileListField(extra.get("filter", "All files (*)"))
        else:
            raise ValueError(kind)
        return w

    def _connect_change(self, w, kind):
        u = self.update_preview
        if kind == "text":
            w.textChanged.connect(u)
        elif kind in ("int", "float"):
            w.valueChanged.connect(u)
        elif kind == "bool":
            w.toggled.connect(u)
        elif kind == "choice":
            w.currentIndexChanged.connect(u)
        elif kind == "ecombo":
            w.currentTextChanged.connect(u)
        elif kind in ("file", "dir"):
            w.edit.textChanged.connect(u)
        elif kind == "files":
            m = w.list.model()
            m.rowsInserted.connect(u)
            m.rowsRemoved.connect(u)

    # ------------------------------------------------------- values / state
    def _get(self, key):
        w, kind, _ = self.widgets[key]
        if kind == "text":
            return w.text().strip()
        if kind in ("int", "float"):
            return w.value()
        if kind == "bool":
            return w.isChecked()
        if kind == "choice":
            return w.currentData() or ""
        if kind == "ecombo":
            t = w.currentText().strip()
            return "" if t == "(default)" else t
        if kind in ("file", "dir"):
            return w.text()
        if kind == "files":
            return w.values()

    def _set(self, key, val):
        w, kind, _ = self.widgets[key]
        if val is None:
            val = self.defaults.get(key)
        if kind == "text":
            w.setText(val or "")
        elif kind == "int":
            w.setValue(int(val or 0))
        elif kind == "float":
            w.setValue(float(val or 0))
        elif kind == "bool":
            w.setChecked(bool(val))
        elif kind == "choice":
            i = w.findData(val or "")
            w.setCurrentIndex(max(i, 0))
        elif kind == "ecombo":
            i = w.findData(val or "")
            if i >= 0:
                w.setCurrentIndex(i)
            else:
                w.setEditText(val or "")
        elif kind in ("file", "dir"):
            w.setText(val or "")
        elif kind == "files":
            w.setValues(val)

    def collect(self):
        data = {k: self._get(k) for k in self.widgets}
        data["_url"] = self.url_edit.text().strip()
        data["_out"] = self.out_dir.text()
        data.update(self.project_mode.collect())
        return data

    def apply(self, data):
        for k in self.widgets:
            if k in data:
                self._set(k, data[k])
        self.url_edit.setText(data.get("_url", ""))
        self.out_dir.setText(data.get("_out", ""))
        self.project_mode.apply(data)

    def reset_fields(self):
        self.apply({k: None for k in self.widgets})

    def _restore_state(self):
        # The form always starts fresh with default settings (use File → Save/Load preset to keep an app's
        # settings). Only window size and theme are remembered.
        self.settings.remove("last_form")
        self.update_mode_ui()
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        # project mode: reopen the last project (its settings live in its own outboxer.json)
        last = self.settings.value("last_project", "") or ""
        if self.settings.value("last_source", "url") == "project":
            self.project_mode.rb_project.setChecked(True)
            if last and os.path.isdir(last):
                try:
                    self.project_mode.set_project(last)
                except Exception as ex:  # a broken project must never stop Studio from opening
                    self.log_line(f"(could not reopen the last project {last}: {ex})\n")

    def closeEvent(self, e):
        pm = self.project_mode
        if pm.job and pm.job.isRunning():
            if QMessageBox.question(self, APP_NAME, "A project build is running. Stop it and quit?") != QMessageBox.Yes:
                e.ignore()
                return
            pm.job.cancelled = True
            pm.job.wait(10000)
        pm.stop_test()
        if pm.active():
            pm.save_project_settings()
        self.settings.setValue("last_source", "project" if pm.active() else "url")
        self.settings.setValue("last_project", pm.project or "")
        if self.proc and self.proc.state() != QProcess.NotRunning:
            if QMessageBox.question(self, APP_NAME, "A build is running. Stop it and quit?") != QMessageBox.Yes:
                e.ignore()
                return
            self.proc.kill()
        if self.engines_page.busy:
            if QMessageBox.question(self, APP_NAME, "An engine download/install is running. Cancel it and quit?") \
                    != QMessageBox.Yes:
                e.ignore()
                return
            self.engines_page.cancel()
            if self.engines_page.job:
                self.engines_page.job.wait(5000)
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(e)

    def save_preset(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save preset", str(Path.home() / "preset.json"), "JSON (*.json)")
        if p:
            Path(p).write_text(json.dumps(self.collect(), indent=2), encoding="utf-8")
            self.statusBar().showMessage(f"Preset saved: {p}", 4000)
            toast(self, "✅ Preset saved")

    def load_preset(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load preset", str(Path.home()), "JSON (*.json)")
        if p:
            try:
                self.apply(json.loads(Path(p).read_text(encoding="utf-8")))
                self.statusBar().showMessage(f"Preset loaded: {p}", 4000)
                toast(self, "✅ Preset loaded")
            except Exception as ex:
                QMessageBox.warning(self, APP_NAME, f"Could not load preset:\n{ex}")

    def update_icon_preview(self, path):
        pm = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        if pm.isNull():
            self.icon_preview.setPixmap(QPixmap())
            self.icon_preview.setText("No icon")
        else:
            self.icon_preview.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # drag & drop a URL onto the window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() and md.urls()[0].isLocalFile() and self.project_mode.drop(md.urls()[0].toLocalFile()):
            return
        url = md.urls()[0].toString() if md.hasUrls() else md.text()
        if url.startswith(("http://", "https://")):
            self.project_mode.rb_url.setChecked(True)
            self.url_edit.setText(url.strip())

    # ------------------------------------------------------------- engine
    def resolve_engine(self):
        """(program, base_args, description) for running Nativefier, or None.

        Also sets self.engine = {node, node_version, how, nf, problem} for the status line.
        """
        node, how = resolve_node(self.cfg)
        ver = node_version_of(node) if node else ""
        nf = nativefier_info(self.cfg.resolve("nativefier_dir"))
        problem = None
        if not node:
            problem = "Node.js not found"
        elif not ver:
            problem = f"Node.js does not run ({node})"
        elif not nf:
            problem = "Nativefier engine not installed"
        elif version_tuple(ver) < nf["min_node"]:
            problem = f"Node {ver} is too old (needs {'.'.join(map(str, nf['min_node']))}+)"
        self.engine = {"node": node, "node_version": ver, "how": how, "nf": nf, "problem": problem}
        if problem:
            return None
        return str(node), [str(nf["cli"])], f"Nativefier {nf['version']} on Node {ver} ({node})"

    def update_mode_ui(self):
        """Grey out what the chosen app engine doesn't use."""
        mode = self._get("electron_mode")
        for key, (w, kind, flag) in self.widgets.items():
            tip = w.toolTip().split("\n")[0]
            if key in ELECTRON_ONLY_OPTIONS:
                w.setEnabled(mode != "webview2")
                w.setToolTip(tip + ("\nElectron apps only" if mode == "webview2" else ""))
        self.widgets["runtime_dir"][0].setEnabled(mode == "shared")
        self.widgets["server_node_path"][0].setEnabled(self._get("server_node") == "path")
        self.refresh_engine_status()

    def electron_default(self):
        return self.cfg.get("electron_version") or DEFAULT_ELECTRON_VERSION

    def _pill(self, ok):
        self.engine_status.setObjectName("pillOk" if ok else "pillWarn")
        self.engine_status.style().unpolish(self.engine_status)
        self.engine_status.style().polish(self.engine_status)

    def refresh_engine_status(self):
        if hasattr(self, "project_mode") and self.project_mode.active():
            html = self.project_mode.status_html()
            self.engine_status.setText(html)
            self.engine_status.setToolTip("Project apps run on Electron with the desktop toolbox; "
                                          "Nativefier is not used. Node.js is only needed for a build command.")
            self._pill("⚠️" not in html)
            if hasattr(self, "engines_page"):
                self.engines_page.refresh()
            self.update_preview()
            return
        eng = self.resolve_engine()
        e = self.engine
        el = self.electron_default()
        if "electron_mode" in self.widgets and self._get("electron_mode") == "webview2":
            rt = webview2_runtime_version()
            sdks = webview2_sdks(self.cfg.resolve("webview2_dir"))
            sdk = sdks[0][0] if sdks else "downloaded on first build"
            self.engine_status.setText(
                (f"✅ <b>WebView2</b> · Edge runtime {rt}" if rt or not IS_WIN else
                 "⚠️ <b>WebView2</b> · runtime not found on this PC (apps will offer to install it)")
                + f" · SDK {sdk}")
            self.engine_status.setToolTip("WebView2 apps are built by Studio itself; Node.js and Electron are not used.")
            self._pill(bool(rt) or not IS_WIN)
            if hasattr(self, "engines_page"):
                self.engines_page.refresh()
            self.update_preview()
            return
        if eng:
            where = " (system)" if e["how"] == "system" else ""
            self.engine_status.setText(
                f"✅ <b>Nativefier {e['nf']['version']}</b> · Node {e['node_version']}{where} · Electron {el}")
            self.engine_status.setToolTip(eng[2])
            self._pill(True)
        else:
            self.engine_status.setText(f"❌ {e['problem']} — click to fix it in <b>Engines</b>")
            self.engine_status.setToolTip("")
            self._pill(False)
        if "electron_version" in self.widgets:
            self.widgets["electron_version"][0].setPlaceholderText(f"{el} (default — change it in Engines…)")
        if hasattr(self, "engines_page"):
            self.engines_page.refresh()
        self.update_preview()

    def on_updates_found(self, updates):
        if not hasattr(self, "engines_btn"):  # still being created
            return
        self.engines_btn.setText("  Engines   ⬆" if updates else "  Engines")
        self.engines_btn.setToolTip(("Updates available: " + ", ".join(
            f"{UPDATE_NAMES.get(k, k)} {v}" for k, v in updates.items())) if updates else
            "Node.js, the Nativefier engine, Electron and WebView2: paths and updates")

    def open_engines(self):
        self.engines_page.refresh()
        self.engines_win.show()
        self.engines_win.raise_()
        self.engines_win.activateWindow()

    def show_manual(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"User Manual — {APP_TITLE}")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint)
        dlg.resize(900, 760)
        lay = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.document().setDefaultStyleSheet(
            "h1{font-size:20pt; color:#0F172A;} h2{font-size:14pt; color:#4F46E5; margin-top:18px;}"
            " h3{font-size:11pt; color:#0F172A;} td,th{padding:5px; border-color:#E5E7EB;} th{background:#F8FAFC;}"
            " a{color:#4F46E5;} body{color:#0F172A;}")
        view.setHtml(USER_MANUAL_HTML)
        lay.addWidget(view)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        dlg.show()

    def show_about(self):
        self.resolve_engine()
        e = self.engine or {}
        nf = e.get("nf")
        how = {"engines": "Engines folder", "custom": "your path", "system": "installed on this PC"}.get(e.get("how"), "")
        zips = electron_zips(self.cfg.resolve("electron_dir"))
        rts = runtimes_in(self.cfg.resolve("runtime_dir"))
        sdks = webview2_sdks(self.cfg.resolve("webview2_dir"))
        rt = webview2_runtime_version()
        try:
            import PySide6
            qt = PySide6.__version__
        except Exception:
            qt = "?"
        rows = [
            ("Nativefier engine", (f"{nf['version']} (modernised, works on current Node.js)" if nf else "not installed")),
            ("Node.js", (f"{e.get('node_version')} — {how}" if e.get("node_version") else "not found")),
            ("Electron for new builds", f"{self.electron_default()}"
                                         + (f"  ·  {len(zips)} zip(s) in Engines" if zips else "")),
            ("Shared Electron runtimes", ", ".join(v for v, _p, _s in rts) or "none yet"),
            ("Edge WebView2 Runtime", rt or ("not installed" if IS_WIN else "Windows only")),
            ("WebView2 SDK", ", ".join(v for v, _p in sdks) or "downloaded on first WebView2 build"),
            ("Desktop toolbox", f"{self.project_mode.manifest().get('version', '?')} · "
                                f"{sum(len(d['fns']) for d in self.project_mode.manifest()['ns'].values()) + len(self.project_mode.manifest()['top'])} commands"),
            ("Python / PySide6", f"{platform.python_version()} / {qt}"),
            ("Settings file", str(self.cfg.path)),
        ]
        table = "".join(f"<tr><td style='padding:3px 14px 3px 0; color:#64748B'>{k}</td><td style='padding:3px 0'>{v}</td></tr>"
                        for k, v in rows)
        html = (f"<h2 style='margin-bottom:2px'>{APP_TITLE}</h2>"
                f"<div>Version {APP_VERSION} · {APP_RELEASED}</div>"
                "<p>Turns websites, local web apps and HTML/CSS/JS project folders into desktop applications — "
                "with Electron (self-contained or shared runtime) or Microsoft Edge WebView2. Project apps get the "
                f"desktop toolbox {self.project_mode.manifest().get('version', '')}, which lets them control the PC.</p>"
                f"<h3 style='margin-bottom:4px'>Engines in use</h3><table>{table}</table>"
                f"<h3 style='margin-bottom:4px'>Developer</h3><div><b>{APP_DEVELOPER}</b></div>"
                "<p style='color:#64748B; font-size:9pt'>Icons: Lucide (ISC License).</p>"
                "<p style='color:#64748B; font-size:9pt'>Built on the open-source Nativefier project (MIT License), "
                "Electron, and Microsoft Edge WebView2. Their names belong to their respective owners.</p>")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"About {APP_NAME}")
        lay = QVBoxLayout(dlg)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(tile_icon("package", "purple").pixmap(64, 64))
        ic.setAlignment(Qt.AlignTop)
        top.addWidget(ic)
        top.addSpacing(14)
        text = QLabel(html)
        text.setTextFormat(Qt.RichText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.setMinimumWidth(560)
        top.addWidget(text, 1)
        lay.addLayout(top)
        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.adjustSize()
        dlg.exec()

    def on_engines_busy(self, busy):
        self.build_btn.setEnabled(not busy and not self.build_running())

    def build_running(self):
        job = getattr(self, "_post_job", None)
        return bool((self.proc and self.proc.state() != QProcess.NotRunning) or (job and job.isRunning()))

    # ---------------------------------------------------------- command
    def output_root(self):
        """Where finished apps go: the Output folder field, or the Desktop by default."""
        return self.out_dir.text() or desktop_dir()

    def build_args(self, out=None):
        d = self.collect()
        if not d["app_version"]:
            d["app_version"] = DEFAULT_APP_VERSION
        if not d["electron_version"]:
            d["electron_version"] = self.electron_default()
        args = []
        if d["_url"]:
            args.append(d["_url"])
        for key, flag, kind, *_ in OPTIONS:
            v = d[key]
            if flag is None:
                continue
            if kind == "bool":
                if v:
                    args.append(flag)
            elif kind == "files":
                for f in v:
                    args += [flag, f]
            elif kind in ("int", "float"):
                if v:
                    args += [flag, str(int(v) if kind == "int" else round(v, 2))]
            elif v:
                args += [flag, v]
        if d["server_dir"] and d["server_stop"] and "--single-instance" not in args:
            # one window per server: a 2nd launch must not start (or stop) a 2nd copy of the server
            args.append("--single-instance")
        if d["extra_args"]:
            try:
                args += shlex.split(d["extra_args"], posix=not IS_WIN)
            except ValueError:
                pass
        # Electron zips are taken from (and downloaded once into) the Engines Electron folder
        args += ["--electron-zip-dir", str(self.cfg.resolve("electron_dir"))]
        args.append(out or self.output_root())
        return args

    def update_preview(self):
        if not hasattr(self, "preview"):
            return
        if hasattr(self, "project_mode") and self.project_mode.active():
            self.preview_label.setText("BUILD PREVIEW")
            self.preview.setPlainText(self.project_mode.preview_text())
            return
        self.preview_label.setText("COMMAND PREVIEW")
        if hasattr(self, "widgets") and "electron_mode" in self.widgets and self._get("electron_mode") == "webview2":
            opts = {k: self._get(k) for k in self.widgets}
            try:
                cfg = webview2_app_config(opts, self.url_edit.text().strip(), opts.get("name") or "(from the site)")
            except Exception as ex:
                cfg = {"error": str(ex)}
            if cfg.get("basicAuthPassword"):
                cfg["basicAuthPassword"] = "••••"
            if opts.get("inject"):
                cfg["inject"] = [f"inject\\{Path(f).name}" for f in opts["inject"]]
            self.preview.setPlainText("WebView2 app — built by Studio, no Nativefier/Electron. "
                                      "Its settings (app.json, editable later):\n" + json.dumps(cfg, indent=1))
            return
        eng = self.resolve_engine()
        head = [eng[0], *eng[1]] if eng else ["node", "nativefier"]
        self.preview.setPlainText(subprocess.list2cmdline(head + self.build_args()))

    def validate(self):
        if self.project_mode.active():
            return self.project_mode.validate()
        url = self.url_edit.text().strip()
        if not url:
            return "Please enter a URL."
        if not url.startswith(("http://", "https://")):
            self.url_edit.setText("https://" + url)
        for key in ("file_download_options", "browserwindow_options"):
            v = self._get(key)
            if v:
                try:
                    json.loads(v)
                except json.JSONDecodeError as ex:
                    return f"{key.replace('_', ' ')} is not valid JSON:\n{ex}"
        icon = self._get("icon")
        if icon and not os.path.isfile(icon):
            return "Icon file does not exist."
        if self._get("full_screen") and self._get("maximize"):
            return "Choose either full screen or maximize, not both."
        if self._get("electron_mode") == "webview2":
            if not IS_WIN:
                return "WebView2 apps are Windows programs: build them on Windows."
            if self._get("platform") not in ("", "windows"):
                return "WebView2 apps run on Windows only — set Platform to Windows (or default)."
            if (self._get("arch") or HOST_ARCH) not in WEBVIEW2_ARCHES:
                return "WebView2 apps can be built for x64, ia32 or arm64."
            if not find_csc():
                return "WebView2 apps need the C# compiler that comes with Windows (.NET Framework 4); it was not found."
            gs = self._get("global_shortcuts")
            if gs:
                try:
                    json.loads(Path(gs).read_text(encoding="utf-8-sig"))
                except Exception as ex:
                    return f"Global shortcuts file is not valid JSON:\n{ex}"
            if self._get("server_dir") and self._get("server_node") == "path" and \
                    not Path(self._get("server_node_path") or "").is_file():
                return "Server tab: choose the node.exe to use (or pick another 'Run the server with')."
        if self._get("electron_mode") == "shared":
            if not IS_WIN:
                return "Shared Electron runtime apps are only supported on Windows."
            if self._get("platform") not in ("", "windows"):
                return "Shared Electron runtime: the platform must be Windows."
            if not find_csc():
                return ("Shared Electron runtime needs the C# compiler that comes with Windows "
                        "(.NET Framework 4), and it was not found.")
            rd = self._get("runtime_dir")
            if rd and Path(rd).exists() and not Path(rd).is_dir():
                return "Shared runtime folder: that path is a file, not a folder."
        sdir = self._get("server_dir")
        if sdir:
            script = self._get("server_script") or "server.js"
            if not os.path.isdir(sdir):
                return f"Server tab: the folder to bundle does not exist:\n{sdir}"
            if not os.path.isfile(os.path.join(sdir, script)):
                return f"Server tab: '{script}' was not found in:\n{sdir}"
            if not IS_WIN:
                return "Server tab: bundling a server (with a .vbs launcher) is only supported on Windows."
        return None

    def build_app(self):
        err = self.validate()
        if err:
            QMessageBox.warning(self, APP_NAME, err)
            return
        if self.engines_page.busy:
            QMessageBox.information(self, APP_NAME, "Please wait until the engine update in the Engines window finishes.")
            return
        if self.project_mode.active():
            self.project_mode.build()
            return
        if self._get("electron_mode") == "webview2":
            self._build_webview2()
            return
        eng = self.resolve_engine()
        if not eng:
            QMessageBox.warning(self, APP_NAME, f"The engine is not ready: {self.engine['problem']}.\n\n"
                                                "Click Engines… to fix it.")
            self.open_engines()
            return
        prog, base, desc = eng
        # Build into a private staging folder, then move the finished app to
        # <Output folder>\<App name> (no "-win32-x64" suffix, no template leftovers).
        self.final_root = Path(self.output_root())
        out = Path(tempfile.gettempdir()) / "outboxer-studio-build"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True, exist_ok=True)
        self.final_root.mkdir(parents=True, exist_ok=True)
        self.stage_dir = str(out)
        self.last_output_dir = None
        self._old_server = None
        self._before = {}
        args = base + self.build_args(out=str(out))
        try:
            self.cfg.resolve("electron_dir").mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            self.log_line(f"(could not create the Electron folder: {ex})\n")
        self.log_line(f"▶ Using {desc}\n▶ {subprocess.list2cmdline([prog, *args])}\n\n")
        self._start(prog, args, cwd=str(out), on_done=self._app_built)

    def shared_runtime_dir(self):
        """Where a shared-runtime build gets Electron from: the field, or Engines\\runtime\\<version>."""
        custom = self._get("runtime_dir")
        if custom:
            return Path(custom)
        version = self._get("electron_version") or self.electron_default()
        return self.cfg.resolve("runtime_dir") / runtime_name(version)

    def _app_built(self, ok):
        built = list(self._app_dirs(self.stage_dir)) if ok else []
        if ok and not built:
            self.log_line("\n⚠️ Nativefier finished, but no app folder was created.\n"
                          "Check the log above for an error (e.g. a failed Electron download).\n"
                          "If there is no error at all, try 'Install / repair engine' in the Engines window.\n")
            ok = False
        if ok and self._get("electron_mode") == "shared":
            self._make_shared(Path(self.stage_dir) / built[0])
            return
        self._finish_build(ok, built)

    def _prepare_stage(self):
        self.final_root = Path(self.output_root())
        out = Path(tempfile.gettempdir()) / "outboxer-studio-build"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True, exist_ok=True)
        self.final_root.mkdir(parents=True, exist_ok=True)
        self.stage_dir = str(out)
        self.last_output_dir = None
        self._old_server = None
        return out

    def _build_webview2(self):
        """WebView2 apps are built by Studio itself (no Nativefier, Node or Electron involved)."""
        out = self._prepare_stage()
        url = self.url_edit.text().strip()
        opts = {k: self._get(k) for k in self.widgets}
        if opts.get("server_dir") and opts.get("server_stop"):
            opts["single_instance"] = True  # one window per server
        sdk_root = self.cfg.resolve("webview2_dir")
        rt = webview2_runtime_version()
        self.log_line(f"▶ WebView2 app for {url}\n   Edge WebView2 Runtime on this PC: "
                      f"{rt or 'NOT INSTALLED — the app will offer to install it'}\n")

        def work(job):
            sdks = webview2_sdks(sdk_root)
            if sdks:
                sdk = sdks[0][1]
            else:
                job.say("   the WebView2 SDK is not in Engines yet — getting it once (a few MB)…")
                sdk = download_webview2_sdk(latest_webview2_sdk(), sdk_root, job)
            job.say(f"   WebView2 SDK {sdk.name}")
            return build_webview2_app(opts, url, out, sdk, job)

        self._post_job = Job(work, self)
        self._post_job.message.connect(lambda t: self.log_line(t + "\n"))
        self._post_job.succeeded.connect(lambda app: (self._set_busy(False), self._finish_build(True, [Path(app).name])))
        self._post_job.failed.connect(lambda m: (self._set_busy(False), self.log_line(f"\n❌ {m}\n"),
                                                 self._finish_build(False, [])))
        self._set_busy(True)
        self._post_job.start()

    def _make_shared(self, built_path):
        """Shrink the build to app code + launcher, using a shared Electron folder (in a worker thread)."""
        runtime = self.shared_runtime_dir()
        version = self._get("electron_version") or self.electron_default()
        zips = self.cfg.resolve("electron_dir")
        title = re.sub(r"-(win32|linux|darwin|mas)-[^-]+$", "", built_path.name) or built_path.name
        app_version = self._get("app_version") or DEFAULT_APP_VERSION
        self.log_line(f"\n▶ Shared Electron runtime: {runtime}\n")

        def work(job):
            ensure_runtime(runtime, version, zips, log=job.say)
            job.say("   making the small app folder and its launcher…")
            make_shared_app(built_path, runtime, title, app_version, log=job.say)
            return built_path

        self._post_job = Job(work, self)
        self._post_job.message.connect(lambda t: self.log_line(t + "\n"))
        self._post_job.succeeded.connect(lambda _p: (self._set_busy(False), self._finish_build(True, [built_path.name])))
        self._post_job.failed.connect(lambda m: (self._set_busy(False), self.log_line(f"\n❌ Shared runtime step failed: {m}\n"),
                                                   self._finish_build(False, [])))
        self._set_busy(True)
        self._post_job.start()

    def _finish_build(self, ok, built):
        if ok:
            try:
                dest = self._move_to_final(Path(self.stage_dir) / built[0])
            except Exception as ex:  # keep the staged build if the move fails
                self.log_line(f"\n⚠️ Built, but could not move it to {self.final_root}: {ex}\n"
                              f"The app is here instead: {Path(self.stage_dir) / built[0]}\n")
                dest = Path(self.stage_dir) / built[0]
            self.last_output_dir = str(dest)
            exe = next(dest.glob("*.exe"), None)
            launcher = None
            if self._get("server_dir") and exe and dest != Path(self.stage_dir) / built[0]:
                try:
                    launcher = self._bundle_server(dest, exe)
                except Exception as ex:
                    self.log_line(f"\n⚠️ App built, but bundling the server failed: {ex}\n")
            run = launcher or exe
            try:
                size = human_size(sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()))
            except OSError:
                size = "?"
            self.log_line(f"\n✅ Done! Your app is in: {dest}  ({size})\n" + (f"   Run: {run}\n" if run else ""))
            if (dest / RUNTIME_FILE).is_file():
                self.log_line(f"   Runs on the shared Electron in: {self.shared_runtime_dir()}\n")
            self.engines_page.refresh()
            self.open_out_btn.setEnabled(True)
            self.statusBar().showMessage("Build succeeded", 6000)
        else:
            self.log_line("\n❌ Build failed — check the log above.\n")
            self.statusBar().showMessage("Build failed", 6000)

    @staticmethod
    def _app_dirs(out):
        """Map of finished Nativefier app folders (e.g. 'Test-win32-x64') to their mtime."""
        res = {}
        try:
            for p in Path(out).iterdir():
                if p.is_dir() and "-template-" not in p.name and any(
                        t in p.name for t in ("-win32-", "-linux-", "-darwin-", "-mas-")):
                    res[p.name] = p.stat().st_mtime
        except OSError:
            pass
        return res

    # ------------------------------------------------------ bundled server
    def _bundle_server(self, dest, exe):
        """Copy the server folder into <dest>\\server, add 'Start <App>.vbs' and a desktop shortcut."""
        src = Path(self._get("server_dir"))
        script = self._get("server_script") or "server.js"
        patterns = [p.strip() for p in re.split(r"[;,]", self._get("server_exclude") or SERVER_EXCLUDE_DEFAULT)
                    if p.strip()]
        target = dest / SERVER_SUBDIR
        self.log_line(f"\n▶ Bundling server: {src} → {target}\n   (not copied: {', '.join(patterns)})\n")
        shutil.copytree(src, target, ignore=shutil.ignore_patterns(*patterns))

        old = getattr(self, "_old_server", None)
        if old and Path(old).is_dir():  # data the server wrote into the previous build (records, config…)
            restored = 0
            for f in Path(old).rglob("*"):
                rel = f.relative_to(old)
                if f.is_file() and not (target / rel).exists():
                    (target / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target / rel)
                    restored += 1
            shutil.rmtree(old, ignore_errors=True)
            self._old_server = None
            if restored:
                self.log_line(f"   kept {restored} file(s) the server had saved in the previous build\n")

        if (dest / "app.json").is_file() and self._get("electron_mode") == "webview2":
            return self._bundle_server_webview2(dest, exe, script)

        app_name = exe.stem
        launcher = dest / f"Start {app_name}.vbs"
        vbs = (LAUNCHER_VBS
               .replace("{APP_EXE}", exe.name)
               .replace("{SERVER_DIR}", SERVER_SUBDIR)
               .replace("{SERVER_SCRIPT}", script.replace("/", "\\"))
               .replace("{URL}", self.url_edit.text().strip())
               .replace("{NODE_MODE}", self._get("server_node") or "builtin")
               .replace("{NODE_EXE}", (self._get("server_node_path") or "node").replace('"', ''))
               .replace("{STOP_ON_CLOSE}", "True" if self._get("server_stop") else "False")
               .replace("{APP_NAME}", app_name))
        # UTF-16 with BOM: Windows Script Host reads it, and any app name/path characters survive
        launcher.write_text(vbs.replace("\r\n", "\n").replace("\n", "\r\n"), encoding="utf-16")
        self.log_line(f"   launcher: {launcher}\n")

        if self._get("server_shortcut"):
            self._desktop_shortcut(app_name, str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"),
                                   f'"{launcher}"', dest, exe)
        return launcher

    def _bundle_server_webview2(self, dest, exe, script):
        """WebView2 apps start (and stop) their server themselves: it goes into app.json, no .vbs needed."""
        mode = self._get("server_node") or "builtin"
        if mode == "path":
            node = self._get("server_node_path") or "node"
        elif mode == "installed":
            node = "node"
        else:  # a private copy of Studio's node.exe inside the app folder
            src = Path(self.engine["node"]) if self.engine and self.engine.get("node") else None
            src = src or (Path(shutil.which("node")) if shutil.which("node") else None)
            if src and src.is_file():
                (dest / "node").mkdir(exist_ok=True)
                shutil.copy2(src, dest / "node" / "node.exe")
                node = "node\\node.exe"
                self.log_line(f"   node: copied {src} into the app (node\\node.exe)\n")
            else:
                node = "node"
                self.log_line("   (no node.exe found to copy — the app will use Node.js installed on the PC)\n")
        cfg_path = dest / "app.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["server"] = {"script": f"{SERVER_SUBDIR}\\{script.replace('/', chr(92))}", "node": node,
                         "stopOnClose": bool(self._get("server_stop"))}
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        self.log_line(f"   the app starts its server itself (node: {node})\n")
        if self._get("server_shortcut"):
            self._desktop_shortcut(exe.stem, str(exe), "", dest, exe)
        return exe

    def _desktop_shortcut(self, name, target, args, workdir, icon_exe):
        lnk = Path(desktop_dir()) / f"{name}.lnk"
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:NF_LNK);"
              "$s.TargetPath=$env:NF_TARGET;$s.Arguments=$env:NF_ARGS;$s.WorkingDirectory=$env:NF_DIR;"
              "$s.IconLocation=$env:NF_EXE+',0';$s.Description='Start '+$env:NF_NAME;$s.Save()")
        env = {**os.environ, "NF_LNK": str(lnk), "NF_TARGET": target, "NF_ARGS": args, "NF_DIR": str(workdir),
               "NF_EXE": str(icon_exe), "NF_NAME": name}
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           env=env, capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and lnk.exists():
            self.log_line(f"   desktop shortcut: {lnk}\n")
        else:
            self.log_line(f"   (could not create the desktop shortcut: {(r.stderr or '').strip()[:200]})\n")

    @staticmethod
    def _stop_processes_under(folder):
        """Stop processes started from inside `folder` (e.g. a bundled server) so it can be replaced."""
        if not IS_WIN:
            return
        ps = ("$f=$env:NF_DIR.ToLower().TrimEnd('\\')+'\\';Get-CimInstance Win32_Process | Where-Object { "
              "(\"$($_.ExecutablePath) $($_.CommandLine)\").ToLower().Contains($f) } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           env={**os.environ, "NF_DIR": str(folder)}, capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass

    def _found_new_app(self):
        return bool(self.last_output_dir) and Path(self.last_output_dir).is_dir()

    def _move_to_final(self, built):
        """Move 'Name-win32-x64' from staging to <final_root>\\Name."""
        name = re.sub(r"-(win32|linux|darwin|mas)-[^-]+$", "", built.name) or built.name
        dest = self.final_root / name
        if dest.exists():
            cfg = dest / "resources" / "app" / "nativefier.json"
            if not cfg.exists():
                cfg = dest / "app" / "nativefier.json"  # shared-runtime layout
            if not cfg.exists():
                cfg = dest / "app.json"                  # WebView2 layout
            portable = False
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                portable = data.get("portable", False)
                if cfg.name == "app.json" and not any(n in str(data.get("builtBy", ""))
                                                      for n in ("Outboxer", "NativefierStudio")):
                    cfg = None  # someone else's app.json: not ours to replace
            except Exception:
                cfg = None
            if cfg and cfg.exists() and not portable:
                # an earlier build of this app: replace it (same as Nativefier's own overwrite).
                # A bundled server may be running from it (files locked): stop it first, and keep
                # its folder aside so data the server saved there survives the rebuild.
                self._stop_processes_under(dest)
                old_srv = dest / SERVER_SUBDIR
                self._old_server = None
                if old_srv.is_dir():
                    keep = Path(tempfile.gettempdir()) / f"outboxer-studio-oldserver-{os.getpid()}"
                    shutil.rmtree(keep, ignore_errors=True)
                    shutil.move(str(old_srv), str(keep))
                    self._old_server = keep
                shutil.rmtree(dest)
            else:  # not ours, or a portable app holding user data: keep it, pick a new name
                i = 2
                while (self.final_root / f"{name} ({i})").exists():
                    i += 1
                dest = self.final_root / f"{name} ({i})"
        shutil.move(str(built), str(dest))
        shutil.rmtree(self.stage_dir, ignore_errors=True)
        return dest

    # ---------------------------------------------------------- process
    def _start(self, prog, args, cwd, on_done, extra_env=None):
        if self.build_running() or self.engines_page.busy:
            return
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.setWorkingDirectory(cwd)
        env = QProcessEnvironment.systemEnvironment()
        if self.engine and self.engine.get("node"):  # child tools use the same Node
            env.insert("PATH", str(Path(self.engine["node"]).parent) + os.pathsep + env.value("PATH", ""))
        for k, v in (extra_env or {}).items():
            env.insert(k, v)
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(
            lambda: self.log_line(bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")))
        self.proc.errorOccurred.connect(lambda e: self.log_line(f"\n[process error: {e}]\n"))
        self.proc.finished.connect(lambda code, status: self._finished(code, status, on_done))
        self._set_busy(True)
        self.proc.start(prog, args)

    def _finished(self, code, status, on_done):
        self._set_busy(False)
        on_done(code == 0 and status == QProcess.NormalExit)

    def stop(self):
        if self.project_mode.stop():
            return
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
            self.log_line("\n⏹ Stopped by user.\n")

    def _set_busy(self, busy):
        self.build_btn.setEnabled(not busy)
        for b in (self.engines_page.node_update_btn, self.engines_page.el_update_btn,
                  self.engines_page.nf_install_btn):
            b.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        if hasattr(self.project_mode, "test_btn"):
            self.project_mode.test_btn.setEnabled(not busy)
        self.progress.setRange(0, 0 if busy else 1)
        if busy:
            self.open_out_btn.setEnabled(False)
            self.statusBar().showMessage("Working…")

    def log_line(self, text):
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def open_output(self):
        if self.last_output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output_dir))


import project_ui  # noqa: E402  (project mode: needs the names above)
project_ui.setup(globals())


def main():
    if IS_WIN:  # own taskbar identity, so Windows shows our icon instead of Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SayedTools.AdvancedOutboxerStudio")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(modern_qss())
    if APP_ICON.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
