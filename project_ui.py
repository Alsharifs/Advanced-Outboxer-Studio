r"""
Advanced Outboxer Studio — project mode, the user interface.

ProjectMode(main_window) adds to the Studio window:
  * the "Source" switch (Website URL / Project folder) and the project folder field,
  * project folders are either HTML/CSS/JS pages (run on Studio's host + desktop toolbox) or a whole
    Electron app folder (package.json + its own main script, packaged as it is),
  * the project option tabs (shown instead of the website tabs in project mode),
  * Test Run, project builds, the Check report,
  * Help ▸ Toolbox guide / New project from template / Open the example project,
  * the first-start offer to bring over the Engines of Outboxer Studio v1.0.
The website (URL) mode is untouched: when "Website" is selected everything works as in v1.0.
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

import project_core as core

S = None  # main script globals (set by setup)


def setup(namespace):
    global S
    S = core._NS(namespace)
    core.setup(namespace)


# key, kind, label, tab, extra
FIELDS = [
    # --- Project
    ("app_type", "choice", "Project type", "Project", {"items": [
        ("auto", "Find out automatically"),
        ("web", "HTML/CSS/JS pages — run on Studio's app host with the desktop toolbox"),
        ("electron", "Electron app folder — package.json + its own main script, packaged as it is")],
        "tip": "An Electron app folder (e.g. MasterKey-Electron) brings its own back end; Studio packages it with "
               "Electron and the packages it needs — no npm on the PC."}),
    ("entry", "ecombo", "Start page", "Project", {"tip": "The first page the app opens (found automatically)."}),
    ("web_dir", "ecombo", "Web folder", "Project",
     {"tip": "Folder with the finished pages. Empty = the project folder itself. For React/Vue/Vite etc. use the build output (dist/build)."}),
    ("build_cmd", "text", "Build command", "Project", {"ph": "e.g. npm run build  (only for projects that need building)"}),
    ("run_build", "bool", "Run the build command before every build and Test Run", "Project", {}),
    ("exclude", "text", "Don't copy", "Project", {"ph": core.DEFAULT_EXCLUDE,
                                                   "tip": "Files/folders to leave out, separated by ; (wildcards * and ? work). "
                                                          ".git, node_modules, logs and outboxer.json are always left out."}),
    # --- App
    ("mode", "choice", "Electron", "App", {"items": [
        ("bundled", "Inside the app — self-contained, runs on any Windows PC (~250 MB)"),
        ("shared", "From this PC (shared runtime) — small app (~10 MB) that uses the Electron folder below")]}),
    ("runtime_dir", "dir", "Shared Electron folder", "App",
     {"ph": "auto: Engines\\runtime\\electron-v<version>-win32-x64 (unpacked once, used by all shared apps)"}),
    ("name", "text", "App name", "App", {"ph": "(from the page title / package.json)"}),
    ("version", "text", "App version", "App", {"ph": "(from package.json, or 1.0.0)"}),
    ("icon", "file", "Icon (.ico/.png)", "App", {"filter": "Images (*.ico *.png *.jpg *.jpeg *.webp *.bmp);;All files (*)",
                                                 "ph": "(found in the project automatically)"}),
    ("description", "text", "Description", "App", {}),
    ("copyright", "text", "Company / copyright", "App", {}),
    ("app_id", "text", "App ID", "App", {"ph": "(made from the name) — keep it the same between versions",
                                        "tip": "Identifies the app to Windows (taskbar, notifications) and names its data folder."}),
    ("electron_version", "text", "Electron version", "App", {"ph": "default from the Engines window"}),
    ("single_instance", "bool", "Only one copy can run (a second start shows the first)", "App", {"default": True}),
    ("portable", "bool", "Portable: keep settings and data next to the app", "App", {}),
    # --- Window
    ("width", "int", "Width", "Window", {"max": 10000, "default": 1100}),
    ("height", "int", "Height", "Window", {"max": 10000, "default": 750}),
    ("min_width", "int", "Min width", "Window", {"max": 10000}),
    ("min_height", "int", "Min height", "Window", {"max": 10000}),
    ("resizable", "bool", "Resizable", "Window", {"default": True}),
    ("remember_bounds", "bool", "Remember size and position", "Window", {"default": True}),
    ("maximized", "bool", "Start maximized", "Window", {}),
    ("fullscreen", "bool", "Start full screen", "Window", {}),
    ("kiosk", "bool", "Kiosk mode (full screen, can't be left)", "Window", {}),
    ("start_hidden", "bool", "Start hidden (show it from the tray or a hotkey)", "Window", {}),
    ("frameless", "bool", "No window frame (the page draws its own title bar)", "Window", {}),
    ("title_bar", "choice", "Title bar", "Window", {"items": [
        ("default", "Normal Windows title bar"), ("hidden", "Hidden — page fills the window, keeps Windows' buttons"),
        ("overlay", "Hidden with Windows' min/max/close buttons drawn over the page")]}),
    ("transparent", "bool", "Transparent window (for overlays/widgets)", "Window", {}),
    ("always_on_top", "bool", "Always on top", "Window", {}),
    ("skip_taskbar", "bool", "Hide from the taskbar", "Window", {}),
    ("background_color", "text", "Background colour", "Window", {"ph": "#ffffff (shown while the page loads)"}),
    ("zoom", "float", "Zoom", "Window", {"default": 1.0}),
    # --- Tray & start
    ("tray", "bool", "Tray icon (next to the clock)", "Tray && Start", {}),
    ("close_to_tray", "bool", "Closing the window keeps the app running in the tray", "Tray && Start", {}),
    ("minimize_to_tray", "bool", "Minimizing hides the window to the tray", "Tray && Start", {}),
    ("tray_tooltip", "text", "Tray tooltip", "Tray && Start", {"ph": "(the app name)"}),
    ("show_hotkey", "text", "Show/hide hotkey", "Tray && Start", {"ph": "e.g. Ctrl+Alt+Space — shows or hides the app from anywhere"}),
    ("autostart", "bool", "Start with Windows (set on the first run)", "Tray && Start", {}),
    ("hide_on_autostart", "bool", "When started with Windows, start in the tray", "Tray && Start", {"default": True}),
    # --- Behaviour
    ("links", "choice", "Links to websites", "Behavior", {"items": [
        ("browser", "Open in the default browser"), ("app", "Open inside the app")]}),
    ("spa", "bool", "Single-page app routes (unknown paths show the start page)", "Behavior", {}),
    ("devtools", "choice", "Developer tools (F12)", "Behavior", {"items": [
        ("dev", "Only in Test Run"), ("always", "Always"), ("never", "Never")]}),
    ("context_menu", "bool", "Right-click menu with Cut/Copy/Paste", "Behavior", {"default": True}),
    ("spellcheck", "bool", "Spell checking in text fields", "Behavior", {"default": True}),
    ("permissions", "bool", "Allow camera, microphone, notifications, clipboard", "Behavior", {"default": True}),
    ("allow_remote", "text", "Websites that may use the toolbox", "Behavior",
     {"ph": "normally empty — e.g. https://my-intranet.local (only sites you control!)"}),
    ("user_agent", "text", "User agent", "Behavior", {"ph": "(Electron's default)"}),
    # --- Output
    ("shortcut_desktop", "bool", "Create a desktop shortcut", "Output", {"default": True}),
    ("shortcut_start", "bool", "Add to the Start menu", "Output", {}),
    ("make_zip", "bool", "Also make a .zip of the app to share", "Output", {}),
    ("run_after", "bool", "Start the app when the build is done", "Output", {}),
]
TABS = ["Project", "App", "Window", "Tray && Start", "Behavior", "Output"]

# sidebar look of the project sections: (Lucide icon, tile colour, one-line description)
SECTION_META = {
    "Project": ("folder", "amber", "What kind of project this is, its start page and pages folder, what to leave out, "
                                   "and an optional build step."),
    "App": ("app-window", "indigo", "Where Electron comes from, and the app's name, version, icon and ID."),
    "Window": ("monitor", "blue", "Size, position and how the app's window looks."),
    "Tray & Start": ("power", "green", "Tray icon, a show/hide hotkey, and starting with Windows."),
    "Behavior": ("mouse-pointer-click", "purple", "Links, developer tools, right-click menu, permissions and "
                                                  "which websites may use the desktop toolbox."),
    "Output": ("package", "orange", "Shortcuts, a .zip to share, and what happens when the build is done."),
    "Check": ("list-checks", "teal", "What Studio found in the project, and anything to fix before building."),
}


class SectionTabs(QStackedWidget):
    """The tab API ProjectPanel uses (addTab, setTabText, setTabEnabled…), shown as sidebar sections
    (the main window's project list) plus stacked pages — the MasterKey look instead of tabs."""

    def __init__(self, nav, on_show):
        super().__init__()
        self.nav = nav
        self.on_show = on_show
        self._labels = []
        nav.currentRowChanged.connect(self._row)

    @staticmethod
    def _plain(label):
        return label.replace("&&", "&")

    def _meta(self, i):
        base = self._plain(self._labels[i]).split(" ")[0] if self._labels[i].startswith("Check") else self._plain(self._labels[i])
        return SECTION_META.get(base, ("square", "slate", ""))

    def addTab(self, widget, label):
        self.addWidget(widget)
        self._labels.append(label)
        icon, color, _d = self._meta(len(self._labels) - 1)
        it = QListWidgetItem(S.tile_icon(icon, color), "  " + self._plain(label))
        it.setSizeHint(QSize(180, 42))
        self.nav.addItem(it)
        self.nav.setFixedHeight(42 * self.nav.count() + 12)
        return self.count() - 1

    def tabText(self, i):
        return self._labels[i]

    def setTabText(self, i, text):
        self._labels[i] = text
        self.nav.item(i).setText("  " + self._plain(text))
        if i == self.currentIndex():
            self.show_current()

    def setTabEnabled(self, i, on):
        it = self.nav.item(i)
        it.setFlags((it.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable) if on
                    else (it.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable))
        it.setToolTip("" if on else "Not used: the Electron app controls this itself")
        if not on and self.nav.currentRow() == i:
            self.nav.setCurrentRow(0)

    def _row(self, r):
        if r >= 0:
            self.setCurrentIndex(r)
            self.show_current()

    def show_current(self):
        i = self.currentIndex()
        if 0 <= i < len(self._labels):
            self.on_show(self._plain(self._labels[i]), self._meta(i)[2])


class ProjectPanel(QWidget):
    changed = Signal()

    def __init__(self, mode, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.widgets = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        mw = mode.mw
        self.tabs = SectionTabs(mw.pnav, mw.show_section_text)  # sidebar sections + stacked pages
        lay.addWidget(self.tabs)
        forms = {}
        for tab in TABS:
            page = QWidget()
            page.setObjectName("page")
            form = QFormLayout(page)
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(9)
            form.setContentsMargins(0, 8, 10, 4)
            if tab == "Project":
                self.summary = QLabel("Choose a project folder above (or File ▸ New project from template).")
                self.summary.setObjectName("callout")
                self.summary.setWordWrap(True)
                self.summary.setTextFormat(Qt.RichText)
                form.addRow(self.summary)
            if tab == "App":
                row = QHBoxLayout()
                row.setSpacing(12)
                self.icon_preview = QLabel("No icon")
                self.icon_preview.setObjectName("iconPreview")
                self.icon_preview.setFixedSize(72, 72)
                self.icon_preview.setAlignment(Qt.AlignCenter)
                row.addWidget(self.icon_preview)
                self.icon_note = QLabel("")
                self.icon_note.setObjectName("muted")
                self.icon_note.setWordWrap(True)
                row.addWidget(self.icon_note, 1)
                form.addRow("Icon preview", row)
            scroll = QScrollArea()
            scroll.setObjectName("page")
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, tab)  # "&&" shows as "&" (a single & would underline the next letter)
            forms[tab] = form
        for key, kind, label, tab, extra in FIELDS:
            w = self._make(kind, extra)
            if extra.get("tip"):
                w.setToolTip(extra["tip"])
            self.widgets[key] = (w, kind, extra)
            if kind == "bool":
                forms[tab].addRow("", w)
                w.setText(label)
            else:
                forms[tab].addRow(label, w)
            self._connect(w, kind)
        self.check = QTextBrowser()
        self.check.setOpenExternalLinks(True)
        self.check.setObjectName("checkView")
        page = QWidget()
        page.setObjectName("page")
        cl = QVBoxLayout(page)
        cl.setContentsMargins(0, 8, 0, 0)
        top = QHBoxLayout()
        top.addStretch()
        rescan = QPushButton(S.glyph_icon("refresh-cw"), " Check again")
        rescan.clicked.connect(lambda: self.mode.rescan(force=True))
        top.addWidget(rescan)
        cl.addLayout(top)
        cl.addWidget(self.check, 1)
        self.check_index = self.tabs.addTab(page, "Check")
        self.widgets["icon"][0].edit.textChanged.connect(self.mode.update_icon_preview)
        self.widgets["mode"][0].currentIndexChanged.connect(self._mode_ui)
        self.widgets["frameless"][0].toggled.connect(self._mode_ui)
        self.widgets["transparent"][0].toggled.connect(self._mode_ui)
        self.widgets["tray"][0].toggled.connect(self._mode_ui)
        self._mode_ui()

    def _make(self, kind, extra):
        if kind == "text":
            w = QLineEdit()
            w.setPlaceholderText(extra.get("ph", ""))
        elif kind == "int":
            w = QSpinBox()
            w.setRange(0, extra.get("max", 100000))
            w.setSpecialValueText("—")
        elif kind == "float":
            w = QDoubleSpinBox()
            w.setRange(0.25, 5.0)
            w.setSingleStep(0.1)
        elif kind == "bool":
            w = QCheckBox()
        elif kind == "choice":
            w = QComboBox()
            for it in extra["items"]:
                if isinstance(it, tuple):
                    w.addItem(it[1], it[0])
                else:
                    w.addItem(it, it)
        elif kind == "ecombo":
            w = QComboBox()
            w.setEditable(True)
            w.setInsertPolicy(QComboBox.NoInsert)
        elif kind in ("file", "dir"):
            w = S.PathField(kind, extra.get("filter", "All files (*)"), extra.get("ph", ""))
        else:
            raise ValueError(kind)
        return w

    def _connect(self, w, kind):
        if kind == "text":
            w.textChanged.connect(self.changed)
        elif kind in ("int", "float"):
            w.valueChanged.connect(self.changed)
        elif kind == "bool":
            w.toggled.connect(self.changed)
        elif kind == "choice":
            w.currentIndexChanged.connect(self.changed)
        elif kind == "ecombo":
            w.currentTextChanged.connect(self.changed)
        elif kind in ("file", "dir"):
            w.edit.textChanged.connect(self.changed)

    def _mode_ui(self, *_):
        g = self.get
        self.widgets["runtime_dir"][0].setEnabled(g("mode") == "shared")
        for k in ("close_to_tray", "minimize_to_tray", "tray_tooltip"):
            self.widgets[k][0].setEnabled(bool(g("tray")))
        self.widgets["title_bar"][0].setEnabled(not g("frameless") and not g("transparent"))

    def get(self, key):
        w, kind, extra = self.widgets[key]
        if kind == "text":
            return w.text().strip()
        if kind == "int":
            return w.value()
        if kind == "float":
            return round(w.value(), 2)
        if kind == "bool":
            return w.isChecked()
        if kind == "choice":
            return w.currentData()
        if kind == "ecombo":
            return w.currentText().strip()
        if kind in ("file", "dir"):
            return w.text().strip()

    def set(self, key, val):
        w, kind, extra = self.widgets[key]
        w.blockSignals(True)
        try:
            if kind == "text":
                w.setText("" if val is None else str(val))
            elif kind == "int":
                w.setValue(int(val or 0))
            elif kind == "float":
                w.setValue(float(val or 1.0))
            elif kind == "bool":
                w.setChecked(bool(val))
            elif kind == "choice":
                i = w.findData(val)
                w.setCurrentIndex(i if i >= 0 else 0)
            elif kind == "ecombo":
                w.setEditText("" if val is None else str(val))
            elif kind in ("file", "dir"):
                w.setText(val or "")
        finally:
            w.blockSignals(False)
        if kind in ("file", "dir"):
            w.edit.textChanged.emit(w.text())

    def values(self):
        st = {k: self.get(k) for k in self.widgets}
        return st

    def apply(self, st):
        for k in self.widgets:
            if k in st:
                self.set(k, st[k] if st[k] is not None else "")
        self._mode_ui()


class ProjectMode:
    """Everything project-mode adds to the main window."""

    def __init__(self, mw):
        self.mw = mw
        self.rep = None
        self.project = ""
        self.test_proc = None
        self.job = None
        self._scan_timer = QTimer()
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(600)
        self._scan_timer.timeout.connect(lambda: self.rescan())
        self._manifest = None

    # ------------------------------------------------------------------ widgets
    def make_source_row(self):
        """'Website (URL)  ○ Project folder' + the project folder field; returned as one widget."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.rb_url = QPushButton(S.glyph_icon("globe"), " Website (URL)")
        self.rb_project = QPushButton(S.glyph_icon("folder"), " Project folder")
        self.rb_url.setToolTip("A website, or a web app with its own local server — everything Outboxer Studio v1.0 does")
        self.rb_project.setToolTip("Your own HTML/CSS/JS pages, or a whole Electron app folder → a Windows app")
        for b in (self.rb_url, self.rb_project):
            b.setCheckable(True)
            b.setObjectName("seg")
            b.setCursor(Qt.PointingHandCursor)
        self.rb_url.setStyleSheet("QPushButton { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }")
        self.rb_project.setStyleSheet("QPushButton { border-top-right-radius: 8px; border-bottom-right-radius: 8px;"
                                      " border-left: none; }")
        self.rb_url.setChecked(True)
        grp = QButtonGroup(w)
        grp.setExclusive(True)
        grp.addButton(self.rb_url)
        grp.addButton(self.rb_project)
        self._source_group = grp
        h.addWidget(self.rb_url)
        h.addWidget(self.rb_project)
        h.addSpacing(12)
        hint = QLabel("HTML/CSS/JS pages or an Electron app → a PC app")
        hint.setObjectName("hint")
        h.addWidget(hint)
        h.addStretch()
        self.rb_project.toggled.connect(self.switch)
        return w

    def make_project_row(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.folder = S.PathField("dir", placeholder="Folder with your index.html, or an Electron app's folder with package.json "
                                                     "(you can also drag the folder onto the window)")
        self.folder.edit.addAction(S.glyph_icon("folder"), QLineEdit.LeadingPosition)
        self.folder.edit.textChanged.connect(self._folder_changed)
        h.addWidget(self.folder, 1)
        b = QPushButton(S.glyph_icon("external-link"), " Open")
        b.setToolTip("Open the project folder in File Explorer")
        b.clicked.connect(lambda: self.project and QDesktopServices.openUrl(QUrl.fromLocalFile(self.project)))
        h.addWidget(b)
        b = QPushButton(S.glyph_icon("file-plus"), " New…")
        b.setToolTip("Start a new project from a template")
        b.clicked.connect(self.new_project)
        h.addWidget(b)
        return w

    def make_panel(self):
        self.panel = ProjectPanel(self)
        self.panel.changed.connect(self._changed)
        self.panel.hide()
        return self.panel

    def make_test_button(self):
        self.test_btn = QPushButton()
        self.test_btn.setObjectName("accent")
        self.test_btn.setMinimumHeight(34)
        self._test_label(False)
        self.test_btn.setToolTip("Run the project as an app right now, straight from its folder (no build).\n"
                                 "It reloads by itself when you save a file. F12 opens the developer tools.")
        self.test_btn.setMinimumWidth(130)
        self.test_btn.clicked.connect(self.test_run)
        self.test_btn.hide()
        return self.test_btn

    def _test_label(self, running):
        if running:
            self.test_btn.setIcon(S.glyph_icon("square", "#B91C1C"))
            self.test_btn.setText(" Stop Test")
        else:
            self.test_btn.setIcon(S.glyph_icon("play", "#4338CA"))
            self.test_btn.setText(" Test Run")

    # ------------------------------------------------------------------ state
    def active(self):
        return hasattr(self, "rb_project") and self.rb_project.isChecked()

    def switch(self, on=None):
        on = self.active()
        mw = self.mw
        mw.set_source_mode(on)
        self.test_btn.setVisible(on)
        mw.refresh_engine_status()

    def _folder_changed(self, text):
        self._scan_timer.start()

    def _changed(self):
        if self.project:
            self._scan_timer.start()
        self.mw.update_preview()

    def set_project(self, folder):
        self.rb_project.setChecked(True)
        self.folder.setText(str(folder))
        self.rescan(force=True)

    def manifest(self):
        if self._manifest is None:
            self._manifest = core.toolbox_manifest()
        return self._manifest

    def rescan(self, force=False):
        folder = self.folder.text().strip()
        if not folder:
            self.project = ""
            self.rep = None
            self.panel.summary.setText("Choose a project folder above (or click New… to start from a template).")
            self.mw.update_preview()
            return
        new_project = os.path.normcase(os.path.abspath(folder)) != os.path.normcase(os.path.abspath(self.project or "."))
        if new_project:
            self.project = str(Path(folder).resolve())
            st = core.load_settings(self.project) if (Path(self.project) / core.SETTINGS_FILE).is_file() else dict(core.DEFAULT_SETTINGS)
            self.panel.apply(st)
        st = self.panel.values()
        st["web_dir"] = None if not (Path(self.project) / core.SETTINGS_FILE).is_file() and new_project else st["web_dir"]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rep = core.scan_project(self.project, st, self.manifest())
        finally:
            QApplication.restoreOverrideCursor()
        self.rep = rep
        p = self.panel
        # fill the pickers with what was found; blank fields show the found values as hints
        entry_w = p.widgets["entry"][0]
        cur = p.get("entry")
        entry_w.blockSignals(True)
        entry_w.clear()
        entry_w.addItems(rep.get("entries", []))
        entry_w.setEditText(cur or ("" if rep.get("kind") == "electron" else rep.get("entry", "")))
        entry_w.blockSignals(False)
        web_w = p.widgets["web_dir"][0]
        curw = rep.get("web_dir", "")
        web_w.blockSignals(True)
        web_w.clear()
        opts = [""] + [d for d in core.OUTPUT_DIRS + ["src"] if (Path(self.project) / d).is_dir()]
        web_w.addItems(opts)
        web_w.setEditText(curw)
        web_w.blockSignals(False)
        fw = rep.get("framework") or {}
        if fw.get("build") and not p.get("build_cmd"):
            p.widgets["build_cmd"][0].setPlaceholderText(fw["build"] + "   (detected)")
        p.widgets["name"][0].setPlaceholderText(f"{rep.get('name', '')}   (found)" if rep.get("name") else "App name")
        p.widgets["version"][0].setPlaceholderText(f"{rep.get('version', '1.0.0')}   (found)")
        if rep.get("description"):
            p.widgets["description"][0].setPlaceholderText(rep["description"])
        name = p.get("name") or rep.get("name", "")
        p.widgets["app_id"][0].setPlaceholderText(core.app_id_for(name) + "   (made from the name)")
        icon_auto = rep["icons"][0][0] if rep.get("icons") else ""
        p.widgets["icon"][0].edit.setPlaceholderText((icon_auto + "   (found)") if icon_auto else "(no icon found — choose one)")
        self.update_icon_preview(p.get("icon"))
        n_prob, n_warn = len(rep["problems"]), len(rep["warnings"])
        state = "❌ " + rep["problems"][0] if n_prob else ("⚠️ Ready, with %d warning(s) — see the Check tab" % n_warn if n_warn else "✅ Ready to build")
        mods = rep.get("modules") or []
        calls = rep.get("known_calls") or {}
        self._kind_ui()
        if rep.get("kind") == "electron":
            deps = rep.get("deps") or {}
            if rep.get("copyright"):
                p.widgets["copyright"][0].setPlaceholderText(rep["copyright"])
            p.summary.setText(
                f"<b>{state}</b><br>Electron app · main script <b>{rep.get('entry') or '—'}</b> · "
                f"{len(rep.get('files', []))} files ({core.human_size(rep.get('size', 0))})"
                + (f" · packages: {', '.join(f'{n} ({w})' for n, w in deps.items())}" if deps else "")
                + "<br><span style='color:#64748B'>It runs its own back end, so the Window, Tray &amp; Start and "
                  "Behavior tabs are not used.</span>")
            p.check.setHtml(core.report_html(rep))
            p.tabs.setTabText(p.check_index, "Check ❌" if n_prob else ("Check ⚠️" if n_warn else "Check ✅"))
            self.mw.update_preview()
            return
        p.summary.setText(
            f"<b>{state}</b><br>"
            f"{len(rep.get('files', []))} files ({core.human_size(rep.get('size', 0))}) · start page "
            f"<b>{rep.get('entry') or '—'}</b> · {fw.get('label') or 'plain HTML/CSS/JS'}"
            + (f" · desktop modules: {', '.join(mods)}" if mods else "")
            + (f" · uses {len(calls)} toolbox command(s)" if calls else ""))
        p.check.setHtml(core.report_html(rep))
        p.tabs.setTabText(p.check_index, "Check ❌" if n_prob else ("Check ⚠️" if n_warn else "Check ✅"))
        self.mw.update_preview()

    def is_electron_app(self):
        return bool(self.rep and self.rep.get("kind") == "electron")

    def _kind_ui(self):
        """Electron app folders bring their own windows, tray and behaviour: grey out what does not apply."""
        p = self.panel
        ea = self.is_electron_app()
        for i in range(p.tabs.count()):
            if p.tabs.tabText(i).replace("&&", "&") in ("Window", "Tray & Start", "Behavior"):
                p.tabs.setTabEnabled(i, not ea)
        for k in ("entry", "web_dir", "app_id", "single_instance", "portable"):
            p.widgets[k][0].setEnabled(not ea)
        if ea and p.get("exclude") == core.DEFAULT_EXCLUDE:
            p.set("exclude", core.ELECTRON_EXCLUDE)
        elif not ea and p.get("exclude") == core.ELECTRON_EXCLUDE:
            p.set("exclude", core.DEFAULT_EXCLUDE)
        if ea and not p.get("build_cmd"):
            p.widgets["build_cmd"][0].setPlaceholderText("(not needed — Studio packages the app itself; only for code that must be compiled first)")
        elif not ea and not ((self.rep or {}).get("framework") or {}).get("build"):
            p.widgets["build_cmd"][0].setPlaceholderText("e.g. npm run build  (only for projects that need building)")
        p.widgets["electron_version"][0].setPlaceholderText(
            f"{self.electron_version()}   (the app's own major version)" if ea and (self.rep["electron"].get("electron_pin") or "")
            .split(".")[0] != str(self.mw.electron_default()).split(".")[0] else "default from the Engines window")

    def update_icon_preview(self, path=None):
        p = self.panel
        path = path if isinstance(path, str) and path else (self.rep["icons"][0][0] if self.rep and self.rep.get("icons") else "")
        pm = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        if pm.isNull():
            p.icon_preview.setPixmap(QPixmap())
            p.icon_preview.setText("No icon")
            p.icon_note.setText("No icon yet: choose one, or put icon.png / icon.ico in the project folder.")
        else:
            p.icon_preview.setPixmap(pm.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            others = len(self.rep.get("icons", [])) - 1 if self.rep else 0
            p.icon_note.setText(f"{path}" + (f"<br><span style='color:#64748B'>{others} other image(s) could also be used.</span>"
                                             if others > 0 and not p.get("icon") else ""))

    def settings(self):
        st = self.panel.values()
        if st.get("web_dir") == "" and self.rep:
            st["web_dir"] = self.rep.get("web_dir", "")
        return st

    def collect(self):
        return {"_source": "project" if self.active() else "url", "_project": self.project, "_project_settings": self.settings()}

    def apply(self, data):
        if data.get("_source") == "project":
            self.rb_project.setChecked(True)
            if data.get("_project"):
                self.folder.setText(data["_project"])
                self.project = str(Path(data["_project"]).resolve())
            if data.get("_project_settings"):
                self.panel.apply(data["_project_settings"])
            self.rescan(force=True)
        elif "_source" in data:
            self.rb_url.setChecked(True)

    def save_project_settings(self):
        if self.project and Path(self.project).is_dir():
            try:
                core.save_settings(self.project, self.settings())
            except OSError as ex:
                self.mw.log_line(f"(could not save {core.SETTINGS_FILE} in the project: {ex})\n")

    # ------------------------------------------------------------------ status / preview / validate
    def electron_version(self):
        return core.electron_version_for({"electron_version": self.panel.get("electron_version")}, self.rep,
                                         self.mw.electron_default())

    def status_html(self):
        v = self.electron_version()
        zips = S.electron_zips(self.mw.cfg.resolve("electron_dir"))
        have = any(z[0] == v and z[1] == S.HOST_PLATFORM for z in zips)
        rt = self.mw.cfg.resolve("runtime_dir") / S.runtime_name(v)
        rt_ok = (rt / ("electron.exe" if S.IS_WIN else "electron")).is_file()
        koffi = (core.HOST_DIR / "node_modules" / "koffi" / "build" / "koffi" / f"win32_{S.HOST_ARCH}" / "koffi.node").is_file()
        el = (f"Electron {v}" if have or rt_ok else f"Electron {v} on the first build")
        tb = self.manifest().get("version", "")
        return (f"{'✅' if (have or rt_ok) else '⬇'} <b>Project apps</b> · {el}" + (f" · toolbox {tb}" if tb else "")
                + ("" if koffi or not S.IS_WIN else " · ⚠️ host\\node_modules\\koffi is missing"))

    def preview_text(self):
        if not self.project:
            return "Project mode: choose the folder of your HTML/CSS/JS project above."
        st = self.settings()
        rep = self.rep or {}
        name = st.get("name") or rep.get("name") or "App"
        out = Path(self.mw.output_root()) / core.safe_name(name)
        mode = st.get("mode")
        v = self.electron_version()
        lines = [f"Build: {name} {st.get('version') or rep.get('version', '1.0.0')}  →  {out}\\{core.safe_name(name)}.exe",
                 ("Electron inside the app (self-contained)" if mode == "bundled" else
                  f"Shared Electron runtime: {st.get('runtime_dir') or self.mw.cfg.resolve('runtime_dir') / S.runtime_name(v)}")
                 + f" · Electron {v}",
                 (f"Electron app: runs its own main script {rep.get('entry', '?')} from {self.project}"
                  if self.is_electron_app() else
                  f"Pages from: {rep.get('web_root', self.project)} · start page {st.get('entry') or rep.get('entry', '?')}")
                 + (f" · runs “{st.get('build_cmd')}” first" if st.get("run_build") and st.get("build_cmd") else "")]
        return "\n".join(lines)

    def validate(self):
        if not self.project or not Path(self.project).is_dir():
            return "Choose your project folder first (the folder with index.html)."
        st = self.settings()
        if st.get("run_build") and not st.get("build_cmd"):
            return "Project tab: “Run the build command” is ticked but the build command is empty."
        if not (st.get("run_build") and st.get("build_cmd")):
            self.rescan(force=True)
            if self.rep and self.rep["problems"]:
                return "The project needs attention:\n\n" + "\n".join(self.rep["problems"])
        if st.get("icon") and not os.path.isfile(st["icon"]):
            return "The icon file does not exist."
        if st.get("show_hotkey") and not self.is_electron_app():
            try:
                _parse_hotkey_check(st["show_hotkey"])
            except ValueError as ex:
                return f"Show/hide hotkey: {ex}"
        if S.IS_WIN and not S.find_csc() and st.get("mode") == "shared":
            return "Shared Electron runtime apps need the C# compiler that comes with Windows (.NET Framework 4); it was not found."
        return None

    # ------------------------------------------------------------------ build
    def build(self):
        err = self.validate()
        if err:
            QMessageBox.warning(self.mw, S.APP_NAME, err)
            return
        mw = self.mw
        if mw.engines_page.busy or mw.build_running():
            QMessageBox.information(mw, S.APP_NAME, "Please wait for the current task to finish.")
            return
        self.save_project_settings()
        st = self.settings()
        out_root = Path(mw.output_root())
        mw.log_line(f"▶ Building the project {self.project}\n")

        def work(job):
            return core.build_project(st, self.project, mw.cfg, out_root, job)

        self._run_job(work, self._built)

    def _run_job(self, work, done):
        mw = self.mw
        job = S.Job(work, mw)
        job.message.connect(lambda t: mw.log_line(t + "\n"))
        job.progress.connect(lambda d, t: (mw.progress.setRange(0, t), mw.progress.setValue(min(d, t))) if t > 0 else mw.progress.setRange(0, 0))
        job.succeeded.connect(lambda r: (self._job_done(), done(r)))
        job.failed.connect(lambda m: (self._job_done(), mw.log_line(f"\n❌ {m}\n"), mw.statusBar().showMessage("Failed", 6000)))
        mw._post_job = job
        self.job = job
        mw._set_busy(True)
        job.start()

    def _job_done(self):
        mw = self.mw
        mw._set_busy(False)
        mw.engines_page.refresh()
        mw.refresh_engine_status()

    def _built(self, r):
        mw = self.mw
        mw.last_output_dir = r["dest"]
        mw.open_out_btn.setEnabled(True)
        mw.log_line(f"\n✅ Done! Your app is in: {r['dest']}  ({core.human_size(r['size'])})\n"
                    + (f"   Run: {r['exe']}\n" if r.get("exe") else "")
                    + (f"   Zip to share: {r['zip']}\n" if r.get("zip") else ""))
        if r.get("mode") == "shared":
            mw.log_line("   It needs the shared Electron folder named in electron-runtime.txt to run.\n")
        mw.statusBar().showMessage("Build succeeded", 6000)
        if self.panel.get("run_after") and r.get("exe"):
            QProcess.startDetached(r["exe"], [], r["dest"])

    # ------------------------------------------------------------------ Test Run
    def test_running(self):
        return bool(self.test_proc and self.test_proc.state() != QProcess.NotRunning)

    def test_run(self):
        if self.test_running():
            self.stop_test()
            return
        err = self.validate()
        if err:
            QMessageBox.warning(self.mw, S.APP_NAME, err)
            return
        if self.mw.engines_page.busy or self.mw.build_running():
            QMessageBox.information(self.mw, S.APP_NAME, "Please wait for the current task to finish.")
            return
        self.save_project_settings()
        st = self.settings()
        v = self.electron_version()
        cfg = self.mw.cfg
        runtime = cfg.resolve("runtime_dir") / S.runtime_name(v)
        exe = runtime / ("electron.exe" if S.IS_WIN else "electron")
        project = self.project
        rep0 = self.rep
        work_dir = Path(tempfile.gettempdir()) / "advanced-outboxer-testrun"

        def work(job):
            if st.get("run_build") and st.get("build_cmd"):
                node, _how = S.resolve_node(cfg)
                core.run_build_command(project, st["build_cmd"], node, job)
            if not exe.is_file():
                z = core.ensure_electron_zip(cfg, v, job)
                S.ensure_runtime(runtime, v, z.parent, job.say)
            if rep0 and rep0.get("kind") == "electron":
                return core.prepare_electron_test(rep0, work_dir / ("app-" + core.slug(rep0.get("name") or "app")), cfg, job, job.say)
            return {}

        self.mw.log_line(f"▶ Test Run of {project} (Electron {v})\n")
        self._run_job(work, lambda extra_env: self._start_test(exe, st, extra_env or {}))

    def _start_test(self, exe, st, extra_env=None):
        rep = core.scan_project(self.project, st, self.manifest())
        if rep["problems"]:
            self.mw.log_line("❌ " + "\n❌ ".join(rep["problems"]) + "\n")
            return
        work = Path(tempfile.gettempdir()) / "advanced-outboxer-testrun"
        work.mkdir(parents=True, exist_ok=True)
        if rep.get("kind") == "electron":
            args = [self.project]  # the app's own folder: Electron runs its package.json "main"
        else:
            cfg_file = core.test_run_config(st, rep, work)
            args = [str(core.HOST_DIR), f"--aos-config={cfg_file}", "--aos-dev"]
        if not S.IS_WIN:
            args.append("--no-sandbox")
        p = QProcess(self.mw)
        p.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.remove("ELECTRON_RUN_AS_NODE")
        for k, val in (extra_env or {}).items():
            env.insert(k, val)
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(self.project)
        p.readyReadStandardOutput.connect(lambda: self._test_output(p))
        p.finished.connect(lambda code, status: self._test_finished(code))
        self.test_proc = p
        p.start(str(exe), args)
        self._test_label(True)
        self.mw.stop_btn.setEnabled(True)
        if rep.get("kind") == "electron":
            self.mw.log_line("   The app is running from its own folder with its own main script "
                             "(Stop ends it; start Test Run again after changing main-process code).\n")
        else:
            self.mw.log_line("   The app is running from your project folder: save a file and it reloads. "
                             "F12 = developer tools, F5 = reload.\n")

    def _test_output(self, p):
        text = bytes(p.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            if not line.strip() or re.search(r"(dbus|gpu_|gpu/|command_buffer|viz_|Fontconfig|atom_cache)", line, re.I):
                continue
            self.mw.log_line("   │ " + line + "\n")

    def _test_finished(self, code):
        self._test_label(False)
        self.mw.stop_btn.setEnabled(self.mw.build_running())
        how = "stopped" if getattr(self, "_stopping", False) else ("ended" if code == 0 else f"ended (exit code {code})")
        self._stopping = False
        self.mw.log_line(f"   Test Run {how}.\n")
        self.test_proc = None

    def stop_test(self):
        if self.test_running():
            self._stopping = True
            self.test_proc.kill()
            self.test_proc.waitForFinished(3000)

    def stop(self):
        """Stop button: cancel a project job and/or the Test Run."""
        stopped = False
        if self.job and self.job.isRunning():
            self.job.cancelled = True
            self.mw.log_line("\n⏹ Cancelling…\n")
            stopped = True
        if self.test_running():
            self.stop_test()
            stopped = True
        return stopped

    # ------------------------------------------------------------------ menus & dialogs
    def open_project(self):
        d = QFileDialog.getExistingDirectory(self.mw, "Open project folder", self.project or str(Path.home()))
        if d:
            self.set_project(d)

    def new_project(self):
        dlg = NewProjectDialog(self.mw)
        if dlg.exec() == QDialog.Accepted and dlg.created:
            self.set_project(dlg.created)
            self.mw.log_line(f"✅ New project: {dlg.created}\n   Edit its files, then press ▶ Test Run.\n")

    def open_example(self):
        src = core.APP_DIR / "examples" / "Toolbox Demo"
        if not src.is_dir():
            QMessageBox.warning(self.mw, S.APP_NAME, f"The example project is missing: {src}")
            return
        # work on a copy so the original stays as a reference
        dest = Path(QStandard_documents()) / "Outboxer Projects" / "Toolbox Demo"
        if not dest.exists():
            shutil.copytree(src, dest)
        self.set_project(dest)
        self.mw.log_line(f"Example project: {dest}\n   Press ▶ Test Run to try every toolbox area.\n")

    def show_guide(self):
        dlg = QDialog(self.mw)
        dlg.setWindowTitle(f"Desktop toolbox guide — {S.APP_TITLE}")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint)
        dlg.resize(980, 800)
        lay = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.document().setDefaultStyleSheet(
            "body{color:#0F172A;} h1{font-size:20pt; color:#0F172A;} h2{font-size:14pt; color:#4F46E5; margin-top:18px;}"
            " code{font-family:Consolas;} .sig{font-weight:bold; color:#0F172A;} .doc{color:#475569;}"
            " pre{background:#F6F7FB; padding:8px;} a{color:#4F46E5;}")
        view.setHtml(core.toolbox_guide_html(self.manifest()))
        lay.addWidget(view)
        row = QHBoxLayout()
        b = QPushButton(S.glyph_icon("external-link"), " Open in browser")
        b.clicked.connect(self._guide_in_browser)
        row.addWidget(b)
        b = QPushButton(S.glyph_icon("file-code"), " Add desktop.d.ts to the project")
        b.setToolTip("Lets VS Code suggest every desktop.* command while you type")
        b.clicked.connect(self._write_dts)
        row.addWidget(b)
        row.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        row.addWidget(btns)
        lay.addLayout(row)
        dlg.show()

    def _guide_in_browser(self):
        p = Path(tempfile.gettempdir()) / "desktop-toolbox-guide.html"
        p.write_text(core.toolbox_guide_html(self.manifest(), for_browser=True), encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _write_dts(self):
        if not self.project:
            QMessageBox.information(self.mw, S.APP_NAME, "Choose a project folder first.")
            return
        p = Path(self.project) / "desktop.d.ts"
        p.write_text(core.toolbox_dts(self.manifest()), encoding="utf-8")
        self.mw.statusBar().showMessage(f"Saved {p}", 6000)
        S.toast(self.mw, "✅ desktop.d.ts added")

    def drop(self, path):
        """A folder dropped on the window."""
        if os.path.isdir(path):
            self.set_project(path)
            return True
        if os.path.isfile(path) and path.lower().endswith((".html", ".htm")):
            self.set_project(os.path.dirname(path))
            return True
        return False


def QStandard_documents():
    from PySide6.QtCore import QStandardPaths
    return QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home() / "Documents")


def _parse_hotkey_check(text):
    """A light check of hotkey text in Python (the app checks it fully)."""
    t = text.strip()
    if not t:
        raise ValueError("empty")
    names = {"ctrl", "control", "alt", "shift", "win", "space", "enter", "tab", "esc", "escape", "capslock", "insert",
             "delete", "home", "end", "pgup", "pgdn", "pageup", "pagedown", "up", "down", "left", "right", "pause",
             "printscreen", "appskey", "scrolllock", "numlock", "backspace", "xbutton1", "xbutton2", "mbutton",
             "wheelup", "wheeldown", "lwin", "rwin", "lctrl", "rctrl", "lalt", "ralt", "lshift", "rshift"}
    parts = [p for p in re.split(r"\s*\+\s*|\s+&\s+", t) if p]
    if len(parts) == 1 and re.match(r"^[~*$^!+#<>]+.+$", t):
        return True  # AutoHotkey style
    for p in parts:
        pl = p.lower()
        if not (pl in names or len(pl) == 1 or re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", pl) or re.fullmatch(r"numpad\d", pl)):
            raise ValueError(f"unknown key “{p}” (examples: Ctrl+Alt+Space, Win+F2, CapsLock+J)")
    return True


class NewProjectDialog(QDialog):
    def __init__(self, mw):
        super().__init__(mw)
        self.setWindowTitle("New project from template")
        self.resize(640, 460)
        self.created = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(10)
        t = QLabel("New project")
        t.setObjectName("title")
        lay.addWidget(t)
        d = QLabel("Choose a starting point. Studio makes the folder, and you can press Test Run right away.")
        d.setObjectName("muted")
        d.setWordWrap(True)
        lay.addWidget(d)
        self.list = QListWidget()
        for key, title, desc in core.templates():
            it = QListWidgetItem(f"{title}\n{desc}")
            it.setData(Qt.UserRole, key)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self.list.setWordWrap(True)
        self.list.setSpacing(4)
        lay.addWidget(self.list, 1)
        form = QFormLayout()
        self.name = QLineEdit("My Desktop App")
        form.addRow("App name", self.name)
        self.where = S.PathField("dir", placeholder="Parent folder")
        self.where.setText(str(Path(QStandard_documents()) / "Outboxer Projects"))
        form.addRow("Create in", self.where)
        self.path_label = QLabel()
        self.path_label.setObjectName("hint")
        form.addRow("", self.path_label)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = btns.button(QDialogButtonBox.Ok)
        ok.setText(" Create project")
        ok.setIcon(S.glyph_icon("plus", "#FFFFFF"))
        ok.setObjectName("primary")
        btns.accepted.connect(self.create)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self.name.textChanged.connect(self._update)
        self.where.edit.textChanged.connect(self._update)
        self._update()

    def target(self):
        return Path(self.where.text() or ".") / core.safe_name(self.name.text().strip() or "My App")

    def _update(self):
        self.path_label.setText(f"Folder: {self.target()}")

    def create(self):
        it = self.list.currentItem()
        if not it:
            return
        try:
            self.created = str(core.new_project(it.data(Qt.UserRole), self.target(), self.name.text().strip() or "My App"))
        except Exception as ex:
            QMessageBox.warning(self, S.APP_NAME, str(ex))
            return
        self.accept()


# ======================================================================= first start: Engines of v1.0
def find_v1_engines():
    """Engines folder of Outboxer Studio v1.0 next to this app (e.g. C:\\Tools\\Outboxer Studio v1.0\\Engines)."""
    here = core.APP_DIR
    cands = []
    for d in here.parent.iterdir() if here.parent.is_dir() else []:
        if d == here or not d.is_dir():
            continue
        if (d / "outboxer_studio.py").is_file() and (d / "Engines").is_dir():
            cands.append(d / "Engines")
    named = here.parent / "Outboxer Studio v1.0" / "Engines"
    if named.is_dir() and named not in cands:
        cands.insert(0, named)
    return cands[0] if cands else None


def engines_empty(engines_dir):
    d = Path(engines_dir)
    if not d.is_dir():
        return True
    return not any((d / sub).is_dir() and any((d / sub).iterdir()) for sub in ("node", "electron", "nativefier53", "runtime"))


def offer_engine_import(mw):
    """Called once at start: bring over v1.0's Node, Nativefier, Electron zips, runtimes and WebView2 SDK."""
    if mw.settings.value("engines_import_asked", False, type=bool):
        return
    src = find_v1_engines()
    if not src or not engines_empty(S.ENGINES_DIR):
        return
    mw.settings.setValue("engines_import_asked", True)
    size = 0
    try:
        size = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
    except OSError:
        pass
    box = QMessageBox(mw)
    box.setWindowTitle(S.APP_NAME)
    box.setIcon(QMessageBox.Question)
    box.setText(f"Outboxer Studio v1.0 is next to this app, with its engines:\n{src}\n\n"
                f"Copy them here ({core.human_size(size)}) so nothing has to be downloaded again?")
    box.setInformativeText("Copy: this Studio gets its own copy (the two stay independent).\n"
                           "Use in place: both Studios use the same Engines folder (no extra disk space).")
    copy_btn = box.addButton("Copy", QMessageBox.AcceptRole)
    share_btn = box.addButton("Use in place", QMessageBox.ActionRole)
    box.addButton("Not now", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() in (share_btn, copy_btn):
        # also use v1.0's default Electron version (its zips are for that version)
        try:
            v1cfg = json.loads((src.parent / "OutboxerStudio.config.json").read_text(encoding="utf-8-sig"))
            if v1cfg.get("electron_version"):
                mw.cfg.set("electron_version", v1cfg["electron_version"])
        except Exception:
            pass
    if box.clickedButton() is share_btn:
        for key, sub in (("node_path", "node/node.exe"), ("nativefier_dir", "nativefier53"), ("electron_dir", "electron"),
                         ("runtime_dir", "runtime"), ("webview2_dir", "webview2")):
            p = src / sub
            if p.exists():
                mw.cfg.set_path(key, str(p), save=False)
        mw.cfg.save()
        mw.engines_page.log(f"Using the engines of Outboxer Studio v1.0 in place: {src}")
        mw.refresh_engine_status()
    elif box.clickedButton() is copy_btn:
        dst = S.ENGINES_DIR

        def work(job):
            files = [f for f in src.rglob("*") if f.is_file() and "_downloads" not in f.parts]
            total = sum(f.stat().st_size for f in files) or 1
            done = 0
            for f in files:
                if job.cancelled:
                    raise S.Cancelled()
                t = dst / f.relative_to(src)
                t.parent.mkdir(parents=True, exist_ok=True)
                if not t.exists() or t.stat().st_size != f.stat().st_size:
                    shutil.copy2(f, t)
                done += f.stat().st_size
                job.report(done, total)
            return len(files)

        mw.engines_page._run(f"Copying the engines of Outboxer Studio v1.0 ({core.human_size(size)})…", work,
                             lambda n: (mw.engines_page.log(f"✅ Copied {n} files from {src}"), mw.engines_page.refresh(),
                                        mw.refresh_engine_status()))
        mw.open_engines()
