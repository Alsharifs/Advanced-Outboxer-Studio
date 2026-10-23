r"""
Advanced Outboxer Studio — project mode, the logic (no user interface here).

Turns a folder of HTML/CSS/JS into a Windows desktop app that runs on the app host in .\host
(Electron + the desktop.* PC toolbox):

    scan_project(folder)            what is in the project: start page, name, icon, version,
                                    framework, desktop modules, toolbox calls, broken links…
    load_settings / save_settings   the project's own settings file (outboxer.json)
    app_config(...)                 the app.config.json the host reads
    stage_app(...)                  host + the project's pages + its desktop folder -> one "app" folder
    electron_app_info / stage_electron_app   a finished Electron app folder (package.json "main"):
                                    packaged as it is, running its own main script, no npm needed
    build_project(...)              finished app: Electron inside (bundled) or shared runtime
    toolbox_manifest / toolbox_guide_html / toolbox_dts   read straight from the host's source,
                                    so the guide always matches the toolbox

Engine helpers (Electron zips, the shared runtime, the C# launcher compiler…) come from the main
Studio script through setup(), so both share one implementation.
"""

import fnmatch
import html as htmlmod
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
HOST_DIR = APP_DIR / "host"
TEMPLATES_DIR = APP_DIR / "templates"
DOCS_DIR = APP_DIR / "docs"
SETTINGS_FILE = "outboxer.json"
BUILT_BY = "Advanced Outboxer Studio"

# Never copied into the app's web folder
ALWAYS_EXCLUDE = [".git", ".svn", ".hg", ".vscode", ".idea", "node_modules", "__pycache__", ".DS_Store", "Thumbs.db",
                  SETTINGS_FILE, "*.log", "*.tmp", "*.bak", "~$*", ".env", ".env.*", "*.pem", "*.key"]
DEFAULT_EXCLUDE = "tests; *.md; package-lock.json"

WEB_EXT = {".html", ".htm"}
TEXT_EXT = {".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".json", ".svg", ".txt", ".md", ".jsx", ".ts", ".tsx", ".vue"}

S = None  # the main Studio script's globals (set by setup)


class _NS:
    def __init__(self, ns):
        self._ns = ns

    def __getattr__(self, name):
        try:
            return self._ns[name]
        except KeyError:
            raise AttributeError(name) from None


def setup(namespace):
    """Called by the main script with its globals(): engine helpers are shared, not copied."""
    global S
    S = _NS(namespace)


# ======================================================================= helpers
def slug(text, sep="-"):
    s = re.sub(r"[^A-Za-z0-9]+", sep, str(text)).strip(sep).lower()
    return s or "app"


def safe_name(name):
    """A name that is valid as a Windows file/folder name."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return s or "App"


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def read_text(p, limit=4 << 20):
    try:
        data = Path(p).read_bytes()[:limit]
    except OSError:
        return ""
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def excluded(rel, patterns):
    """rel: path relative to the web folder, with / separators."""
    parts = rel.split("/")
    for pat in patterns:
        pat = pat.strip().replace("\\", "/").strip("/")
        if not pat:
            continue
        if "/" in pat:
            if fnmatch.fnmatch(rel, pat) or rel.startswith(pat + "/"):
                return True
        elif any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
    return False


def split_patterns(text):
    return [p.strip() for p in re.split(r"[;,\n]", text or "") if p.strip()]


def walk_files(root, patterns=(), skip_dirs=()):
    """Files under root (relative, '/'-separated), skipping excluded ones and skip_dirs (absolute)."""
    root = Path(root)
    skip = {Path(d).resolve() for d in skip_dirs if d}
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        keep = []
        for d in dirnames:
            full = (dp / d)
            rel = full.relative_to(root).as_posix()
            if full.resolve() in skip or excluded(rel, list(ALWAYS_EXCLUDE) + list(patterns)):
                continue
            keep.append(d)
        dirnames[:] = sorted(keep)
        for f in sorted(filenames):
            rel = (dp / f).relative_to(root).as_posix()
            if not excluded(rel, list(ALWAYS_EXCLUDE) + list(patterns)):
                out.append(rel)
    return out


# ======================================================================= toolbox (read from the host source)
_METHOD_RE = re.compile(
    r"(?:/\*\*((?:(?!\*/)[\s\S])*?)\*/\s*\n)?^( {2}| {4})(?:async\s+)?([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{", re.M)
_HEADER_RE = re.compile(r"^/\*([\s\S]*?)\*/", re.M)

NAMESPACE_TITLES = {
    "keys": "Keyboard: send keys, type, hotkeys, hotstrings, remaps", "mouse": "Mouse",
    "windows": "Windows of every program", "window": "This app's own windows",
    "files": "Files and folders", "clipboard": "Clipboard", "programs": "Programs and processes",
    "tray": "Tray icon", "dialog": "Message boxes and questions", "screen": "Screen, screenshots, OCR",
    "power": "Power", "system": "System and Windows settings", "audio": "Sound, volume, speech",
    "registry": "Registry", "net": "Internet and network", "store": "Saved settings",
    "db": "SQL database", "print": "Printing and PDF", "app": "This application",
}


def _clean_doc(doc):
    lines = [re.sub(r"^\s*\* ?", "", l).rstrip() for l in (doc or "").splitlines()]
    return "\n".join(lines).strip()


def toolbox_manifest(host_dir=None):
    """{'top': {name: {args, doc}}, 'ns': {ns: {'doc': str, 'fns': {name: {args, doc}}}}} parsed from the host."""
    tdir = Path(host_dir or HOST_DIR) / "toolbox"
    out = {"top": {}, "ns": {}, "version": ""}
    idx = read_text(tdir / "index.js")
    m = re.search(r"const NAMESPACES = \[([^\]]*)\]", idx)
    names = re.findall(r"'(\w+)'", m.group(1)) if m else []
    v = re.search(r"const VERSION = '([^']+)'", idx)
    out["version"] = v.group(1) if v else ""

    def methods(src):
        fns = {}
        for mm in _METHOD_RE.finditer(src):
            name = mm.group(3)
            if name in ("if", "for", "while", "switch", "catch", "function", "return") or name.startswith("_"):
                continue
            fns[name] = {"args": " ".join(mm.group(4).split()), "doc": _clean_doc(mm.group(1))}
        return fns

    for ns in names:
        src = read_text(tdir / f"{ns}.js")
        head = _HEADER_RE.search(src)
        out["ns"][ns] = {"doc": _clean_doc(head.group(1)) if head else "", "fns": methods(src)}
    core = read_text(tdir / "core.js")
    out["top"] = methods(core)
    nsrc = read_text(tdir / "notify.js")
    nd = re.search(r"/\*\*([\s\S]*?)\*/\s*\n\s*return function notify\(([^)]*)\)", nsrc)
    out["top"]["notify"] = {"args": nd.group(2) if nd else "title, body, opts", "doc": _clean_doc(nd.group(1)) if nd else ""}
    out["top"]["on"] = {"args": "event, fn", "doc": "Listen to app events: 'power', 'theme', 'store', 'second-instance', 'displays', "
                                                    "'suspend', 'hidden-to-tray' and your own desktop.emit() events ('*' = all). "
                                                    "Returns a function that stops listening."}
    out["top"]["once"] = {"args": "event, fn", "doc": "Like on(), for the next event only."}
    out["top"]["off"] = {"args": "event, fn", "doc": "Stop listening."}
    out["ns"].setdefault("db", {"doc": "", "fns": {}})["fns"]["open"] = {
        "args": "name", "doc": "An object for one database whose run/all/get/exec/transaction/tables/close need no name."}
    return out


def toolbox_calls(text):
    """desktop.x / desktop.ns.fn calls in source text -> {'ns.fn' or 'fn': count}."""
    calls = {}
    for m in re.finditer(r"\bdesktop\.([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?\s*\(", text):
        key = m.group(1) + ("." + m.group(2) if m.group(2) else "")
        calls[key] = calls.get(key, 0) + 1
    return calls


def check_calls(calls, manifest):
    """Split calls into (known, unknown) using the toolbox manifest."""
    known, unknown = {}, {}
    for key, n in calls.items():
        if "." in key:
            ns, fn = key.split(".", 1)
            ok = ns in manifest["ns"] and fn in manifest["ns"][ns]["fns"]
        else:
            ok = key in manifest["top"]
        (known if ok else unknown)[key] = n
    return known, unknown


# ======================================================================= scanning a project
FRAMEWORKS = [  # (dependency, label, usual output folder)
    ("next", "Next.js", "out"), ("nuxt", "Nuxt", ".output/public"), ("@angular/core", "Angular", "dist"),
    ("@sveltejs/kit", "SvelteKit", "build"), ("svelte", "Svelte", "dist"), ("vue", "Vue", "dist"),
    ("react-scripts", "Create React App", "build"), ("react", "React", "dist"), ("solid-js", "Solid", "dist"),
    ("preact", "Preact", "dist"), ("astro", "Astro", "dist"), ("vite", "Vite", "dist"), ("parcel", "Parcel", "dist"),
    ("webpack", "webpack", "dist"),
]
OUTPUT_DIRS = ["dist", "build", "out", "public", "www", "docs", ".output/public", "_site"]


def _title_of(html_text):
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    return htmlmod.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""


def _refs_in_html(text):
    """Local files referenced by an HTML page: src/href/srcset/poster/data, inline url()."""
    refs = []
    for m in re.finditer(r"""<(?:script|img|link|source|video|audio|iframe|embed|track|a|object|input)\b[^>]*?\b(?:src|href|poster|data)\s*=\s*(["'])(.*?)\1""",
                         text, re.I | re.S):
        refs.append(m.group(2))
    for m in re.finditer(r"""\bsrcset\s*=\s*(["'])(.*?)\1""", text, re.I | re.S):
        refs += [p.strip().split(" ")[0] for p in m.group(2).split(",") if p.strip()]
    refs += [m.group(2) for m in re.finditer(r"""url\(\s*(["']?)([^"')]+)\1\s*\)""", text)]
    return refs


def _refs_in_css(text):
    refs = [m.group(2) for m in re.finditer(r"""url\(\s*(["']?)([^"')]+)\1\s*\)""", text)]
    refs += [m.group(2) for m in re.finditer(r"""@import\s+(["'])([^"']+)\1""", text)]
    return refs


def _refs_in_js(text):
    refs = [m.group(2) for m in re.finditer(r"""(?:^|[\s;}])import\s+(?:[\w*{}\s,$]+from\s+)?(["'])(\.{1,2}/[^"']+)\1""", text, re.M)]
    refs += [m.group(2) for m in re.finditer(r"""\bimport\(\s*(["'])(\.{1,2}/[^"']+)\1\s*\)""", text)]
    refs += [m.group(2) for m in re.finditer(r"""new\s+(?:Worker|SharedWorker)\(\s*(["'])([^"']+)\1""", text)]
    return refs


def _is_local(ref):
    r = ref.strip()
    return bool(r) and not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#|\{\{|\$\{|<%)", r, re.I) and "${" not in r


def _resolve_ref(web_root, from_rel, ref):
    """-> path relative to the web root ('/'-separated), '../…' if it leaves the web folder, or None."""
    from urllib.parse import unquote
    r = unquote(ref.split("#")[0].split("?")[0].strip())
    if not r:
        return None
    rel = r.lstrip("/") if r.startswith("/") else (Path(from_rel).parent / r).as_posix()
    norm = os.path.normpath(rel).replace("\\", "/")
    if norm == ".":
        return ""
    return "../" + r if norm.startswith("..") else norm


def detect_framework(project):
    pkg_file = Path(project) / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        pkg = json.loads(read_text(pkg_file))
    except Exception:
        return {"label": "package.json (could not be read)", "build": "", "out": "", "pkg": {}}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    label, out = None, ""
    for dep, name, outdir in FRAMEWORKS:
        if dep in deps:
            label, out = name, outdir
            break
    scripts = pkg.get("scripts", {})
    build = "npm run build" if "build" in scripts else ""
    if not label and not build:
        return {"label": "", "build": "", "out": "", "pkg": pkg}
    # vite.config base / outDir hints
    for cfg in ("vite.config.js", "vite.config.ts", "vite.config.mjs"):
        t = read_text(Path(project) / cfg)
        m = re.search(r"outDir\s*:\s*['\"]([^'\"]+)", t)
        if m:
            out = m.group(1)
    return {"label": label or "npm project", "build": build, "out": out, "pkg": pkg}


def find_entries(web_root, files):
    pages = [f for f in files if Path(f).suffix.lower() in WEB_EXT]
    pref = ["index.html", "index.htm", "main.html", "home.html", "app.html", "default.html", "start.html"]
    ordered = [p for p in pref if p in pages]
    ordered += sorted([p for p in pages if p not in ordered], key=lambda p: (p.count("/"), Path(p).name != "index.html", p))
    return ordered


def find_icons(project, web_root, files, entry_html=""):
    """Icon candidates, best first: (path, why)."""
    cands = []
    seen = set()

    def add(p, why):
        p = Path(p)
        if p.is_file() and p.suffix.lower() in (".ico", ".png", ".jpg", ".jpeg", ".webp", ".bmp") and str(p).lower() not in seen:
            seen.add(str(p).lower())
            cands.append((str(p), why))

    for n in ("icon.ico", "icon.png", "app.ico", "app.png", "logo.png", "favicon.ico", "favicon.png"):
        add(Path(project) / n, "in the project folder")
        add(Path(web_root) / n, "in the web folder")
    for n in ("icons/icon.png", "assets/icon.png", "assets/icon.ico", "img/icon.png", "images/icon.png", "public/favicon.ico",
              "build/icon.ico", "build/icon.png", "assets/logo.png", "img/logo.png", "images/logo.png"):
        add(Path(project) / n, "common icon location")
    # <link rel=icon> and the web manifest
    if entry_html:
        for tag in re.findall(r"<link\b[^>]*>", entry_html, re.I):
            rel = re.search(r'rel=["\']([^"\']+)', tag, re.I)
            href = re.search(r'href=["\']([^"\']+)', tag, re.I)
            if rel and href and "icon" in rel.group(1).lower() and _is_local(href.group(1)):
                add(Path(web_root) / href.group(1).lstrip("/"), "linked by the start page")
            if rel and href and rel.group(1).lower() == "manifest" and _is_local(href.group(1)):
                try:
                    mf = Path(web_root) / href.group(1).lstrip("/")
                    icons = json.loads(read_text(mf)).get("icons", [])
                    icons.sort(key=lambda i: int((re.match(r"(\d+)", str(i.get("sizes", "0"))) or [0, 0])[1] or 0), reverse=True)
                    for ic in icons:
                        if ic.get("src") and "monochrome" not in str(ic.get("purpose", "")):
                            add(mf.parent / ic["src"].lstrip("/"), "from the web manifest")
                except Exception:
                    pass
    for f in files:  # anything named like an icon
        if re.search(r"(^|/)(app-?icon|icon|logo)[-_]?(\d+)?\.(png|ico)$", f, re.I):
            add(Path(web_root) / f, "found in the project")
    # prefer bigger PNG/ICO files
    def score(c):
        try:
            size = Path(c[0]).stat().st_size
        except OSError:
            size = 0
        return (0 if Path(c[0]).suffix.lower() == ".ico" else 1, -size)
    if len(cands) > 1:
        head = cands[:1]
        tail = sorted(cands[1:], key=score)
        cands = head + tail
    return cands


def scan_project(folder, settings=None, manifest=None):
    """Everything Studio needs to know about a project folder. Never raises for a readable folder."""
    project = Path(folder).resolve()
    settings = settings or {}
    rep = {"project": str(project), "problems": [], "warnings": [], "notes": []}
    if not project.is_dir():
        rep["problems"].append(f"The folder does not exist: {project}")
        return rep
    fw = detect_framework(project)
    rep["framework"] = fw
    ea = electron_app_info(project, settings)
    if ea is not None:
        return _scan_electron_app(project, rep, ea, settings)
    rep["kind"] = "web"
    web_dir = settings.get("web_dir", None)
    if web_dir is None:  # guess: a built framework project serves its output folder
        web_dir = ""
        if fw and fw.get("out") and (project / fw["out"]).is_dir() and any((project / fw["out"]).glob("*.htm*")):
            web_dir = fw["out"]
        elif not any(project.glob("*.htm*")):
            for d in OUTPUT_DIRS + ["src"]:
                if (project / d).is_dir() and any((project / d).glob("*.htm*")):
                    web_dir = d
                    break
    rep["web_dir"] = web_dir
    web_root = (project / web_dir).resolve() if web_dir else project
    rep["web_root"] = str(web_root)
    desktop_dir = project / "desktop"
    rep["desktop_dir"] = str(desktop_dir) if desktop_dir.is_dir() else ""
    patterns = split_patterns(settings.get("exclude", DEFAULT_EXCLUDE))
    if not web_root.is_dir():
        rep["problems"].append(f"The web folder does not exist yet: {web_root}" +
                               (f" — run “{fw['build']}” first (or tick “Run the build command”)." if fw and fw.get("build") else ""))
        files = []
    else:
        files = walk_files(web_root, patterns, skip_dirs=[desktop_dir])
    rep["files"] = files
    total = 0
    for f in files:
        try:
            total += (web_root / f).stat().st_size
        except OSError:
            pass
    rep["size"] = total
    entries = find_entries(web_root, files)
    rep["entries"] = entries
    entry = settings.get("entry") or (entries[0] if entries else "")
    rep["entry"] = entry
    if not entries:
        rep["problems"].append("No .html page was found" + (f" in {web_dir}" if web_dir else "") + ". A project needs at least an index.html.")
    elif entry not in files:
        rep["problems"].append(f"The start page “{entry}” is not in the web folder.")
    entry_html = read_text(web_root / entry) if entry else ""
    pkg = (fw or {}).get("pkg") or {}
    title = _title_of(entry_html)
    rep["name"] = (pkg.get("productName") or (re.split(r"\s[-|–—·:]\s", title)[0].strip() if title else "")
                   or pkg.get("name", "").replace("-", " ").title() or project.name).strip()[:60]
    rep["version"] = pkg.get("version") or "1.0.0"
    rep["description"] = pkg.get("description", "")
    author = pkg.get("author", "")
    rep["author"] = author.get("name", "") if isinstance(author, dict) else str(author)
    rep["icons"] = find_icons(project, web_root, files, entry_html)

    # desktop folder modules
    mods = []
    if desktop_dir.is_dir():
        for p in sorted(desktop_dir.iterdir()):
            if p.name.startswith((".", "_")) or p.name == "node_modules":
                continue
            if p.is_file() and p.suffix.lower() in (".js", ".cjs"):
                mods.append(p.stem)
            elif p.is_dir() and (p / "index.js").is_file():
                mods.append(p.name)
        if (desktop_dir / "package.json").is_file() and not (desktop_dir / "node_modules").is_dir():
            rep["warnings"].append("desktop\\package.json lists packages but desktop\\node_modules is missing — "
                                   "run “npm install” inside the desktop folder.")
    rep["modules"] = mods

    # links, toolbox calls, offline problems
    missing = {}
    calls = {}
    remote = set()
    fileset = set(files)
    lower = {f.lower(): f for f in files}
    case_issues = {}
    for f in files:
        ext = Path(f).suffix.lower()
        if ext not in TEXT_EXT or ext in (".json", ".md", ".txt"):
            continue
        text = read_text(web_root / f, 2 << 20)
        if ext in WEB_EXT:
            refs = _refs_in_html(text)
            for m in re.finditer(r"<script\b[^>]*>([\s\S]*?)</script>", text, re.I):
                refs += _refs_in_js(m.group(1))
        elif ext == ".css":
            refs = _refs_in_css(text)
        elif ext in (".js", ".mjs", ".jsx", ".ts", ".tsx", ".vue"):
            refs = _refs_in_js(text)
        else:
            refs = []
        for c, n in toolbox_calls(text).items():
            calls[c] = calls.get(c, 0) + n
        for ref in refs:
            if re.match(r"^(https?:)?//", ref.strip(), re.I):
                host = re.sub(r"^(https?:)?//", "", ref.strip()).split("/")[0]
                if ext in WEB_EXT and re.search(r"\.(js|css|woff2?)(\?|$)", ref, re.I):
                    remote.add(host)
                continue
            if not _is_local(ref):
                continue
            target = _resolve_ref(web_root, f, ref)
            if not target or target.startswith("../"):
                if target:
                    missing.setdefault(f, []).append(f"{ref}  (outside the web folder)")
                continue
            if target in fileset or (web_root / target).is_dir() and (target + "/index.html") in fileset:
                continue
            if target.lower() in lower:
                case_issues.setdefault(f, []).append(f"{ref} → the file is “{lower[target.lower()]}”")
                continue
            if Path(target).suffix == "" and (target + ".js") in fileset:
                continue
            missing.setdefault(f, []).append(ref)
    rep["missing"] = missing
    rep["case_issues"] = case_issues
    rep["remote_hosts"] = sorted(remote)
    for c, n in toolbox_calls("\n".join(read_text(desktop_dir / (m + ".js"), 1 << 20) for m in mods)).items():
        calls[c] = calls.get(c, 0) + n
    rep["calls"] = calls
    manifest = manifest or toolbox_manifest()
    known, unknown = check_calls(calls, manifest)
    rep["known_calls"], rep["unknown_calls"] = known, unknown
    if missing:
        n = sum(len(v) for v in missing.values())
        rep["warnings"].append(f"{n} link(s) point to files that are not in the project (see the Check tab).")
    if case_issues:
        rep["warnings"].append("Some links use different upper/lower case than the file name — fine on Windows, "
                               "but worth fixing (see the Check tab).")
    if unknown:
        rep["warnings"].append("Toolbox calls that do not exist: " + ", ".join(f"desktop.{k}()" for k in sorted(unknown)))
    if remote:
        rep["notes"].append("Loads scripts/styles/fonts from the internet (" + ", ".join(sorted(remote)[:4]) +
                            ("…" if len(remote) > 4 else "") + "): the app needs internet for them. "
                            "Download them into the project to make it work offline.")
    bridges = _foreign_bridges(web_root, files)
    if bridges:
        rep["warnings"].append(
            "The pages call " + ", ".join(f"window.{b}" for b in bridges) + ", which nothing in this folder provides: "
            "they were written for another app's own back end (its Electron main script). Open that app's whole "
            "source folder (the one with package.json) instead — Studio then builds it as an Electron app.")
    if any(c == "call" for c in calls) and not mods:
        rep["warnings"].append("The pages use desktop.call(…) but the project has no desktop folder with modules.")
    if fw and fw.get("build") and web_dir == "":
        rep["notes"].append(f"{fw['label']} project: its finished pages usually come from “{fw['build']}” "
                            f"into “{fw.get('out') or 'dist'}”. Choose that as the web folder.")
    big = sorted(((web_root / f).stat().st_size, f) for f in files if (web_root / f).is_file())[-3:]
    if big and big[-1][0] > 50 << 20:
        rep["notes"].append(f"Large file: {big[-1][1]} ({human_size(big[-1][0])}).")
    return rep


# ======================================================================= Electron app folders
# A finished Electron app (package.json with "main" + Electron) is packaged as it is: its own main
# script runs instead of Studio's host, its runtime dependencies come from its node_modules, from
# Studio's host (koffi) or — only if missing — from a one-off npm install with Studio's Node.

ELECTRON_EXCLUDE = "test; tests; *.md; package-lock.json; *.map; .gitignore; .npmrc; .editorconfig; .eslintrc*; .prettierrc*"
_NOT_RUNTIME_DEPS = {"electron", "electron-builder", "electron-packager", "@electron/packager", "electron-forge"}
_BRIDGE_RE = re.compile(r"\bwindow\.([A-Za-z_$][\w$]*)\.(?:invoke|send|on|receive)\s*\(")
_BRIDGE_DEF_RE = r"window\.{0}\s*=|exposeInMainWorld\(\s*['\"]{0}['\"]"
BOOT_FILE = "aos-boot.cjs"


def read_pkg(project):
    try:
        pkg = json.loads(read_text(Path(project) / "package.json"))
        return pkg if isinstance(pkg, dict) else {}
    except Exception:
        return {}


def _main_file(project, main):
    """The real file behind package.json "main" (Node's rules: as is, +.js, folder/index.js)."""
    project = Path(project)
    main = (main or "index.js").strip().lstrip("./") or "index.js"
    for c in (main, main + ".js", main + ".cjs", main + ".mjs", main.rstrip("/") + "/index.js"):
        if (project / c).is_file():
            return c.replace("\\", "/")
    return ""


def electron_app_info(project, settings=None):
    """None for an HTML/CSS/JS project; for an Electron app folder: what the build needs."""
    app_type = (settings or {}).get("app_type") or "auto"
    if app_type == "web":
        return None
    project = Path(project)
    if not (project / "package.json").is_file():
        return {"error": "No package.json in the folder: an Electron app folder has one, with \"main\" naming its main script."} \
            if app_type == "electron" else None
    pkg = read_pkg(project)
    deps_all = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    main = _main_file(project, pkg.get("main"))
    uses_electron = "electron" in deps_all or (main and re.search(r"""(require\(\s*|from\s+)['"]electron['"]""",
                                                                  read_text(project / main, 1 << 20)))
    if not (pkg.get("main") and main and uses_electron):
        if app_type != "electron":
            return None
        why = ("package.json has no \"main\"" if not pkg.get("main") else
               f"the main script “{pkg.get('main')}” does not exist" if not main else "it does not use Electron")
        return {"error": f"This is not an Electron app folder: {why}."}
    build = pkg.get("build") if isinstance(pkg.get("build"), dict) else {}
    dirs = build.get("directories") or {}
    pin = re.sub(r"^[\^~=v\s]+", "", str(deps_all.get("electron", "")))
    return {
        "main": main, "pkg": pkg, "build": build,
        "electron_pin": pin if re.fullmatch(r"\d+\.\d+\.\d+", pin) else "",
        "out_dir": dirs.get("output") or "dist", "res_dir": dirs.get("buildResources") or "build",
        "esm": main.endswith(".mjs") or (pkg.get("type") == "module" and not main.endswith(".cjs")),
    }


def runtime_dependencies(project, pkg, extra_roots=()):
    """{name: folder or None} for the app's runtime dependencies and theirs (Electron itself excluded)."""
    roots = [Path(project) / "node_modules", *[Path(r) for r in extra_roots], HOST_DIR / "node_modules"]
    found = {}
    todo = list((pkg.get("dependencies") or {}).keys()) + list((pkg.get("optionalDependencies") or {}).keys())
    while todo:
        name = todo.pop()
        if name in found or name in _NOT_RUNTIME_DEPS:
            continue
        src = next((r / name for r in roots if (r / name / "package.json").is_file()), None)
        found[name] = src
        if src:
            sub = read_pkg(src)
            todo += list((sub.get("dependencies") or {}).keys()) + list((sub.get("optionalDependencies") or {}).keys())
    return found


def _dep_source_label(project, src):
    if src is None:
        return "missing"
    try:
        Path(src).resolve().relative_to(HOST_DIR.resolve())
        return "Studio"
    except ValueError:
        return "project"


def _icon_candidates_electron(project, ea, files):
    project = Path(project)
    cands, seen = [], set()

    def add(p, why):
        p = Path(p)
        if p.is_file() and p.suffix.lower() in (".ico", ".png", ".jpg", ".jpeg", ".webp", ".bmp") and str(p).lower() not in seen:
            seen.add(str(p).lower())
            cands.append((str(p), why))

    b = ea.get("build") or {}
    for spec in ((b.get("win") or {}).get("icon"), b.get("icon")):
        if spec:
            base = project / spec if (project / spec).suffix else None
            for c in ([base] if base else []) + [project / (spec + ".ico"), project / (spec + ".png"),
                                                 project / ea["res_dir"] / spec, project / ea["res_dir"] / (spec + ".ico")]:
                add(c, "from package.json (build.icon)")
    for n in ("icon.ico", "icon.png", "icons/icon.ico", "icons/256x256.png", "icons/icon.png"):
        add(project / ea["res_dir"] / n, "electron-builder's build folder")
    for c in find_icons(project, project, files):
        add(*c)
    return cands


def _scan_electron_app(project, rep, ea, settings):
    rep["kind"] = "electron"
    rep["electron"] = ea
    for k, v in (("web_dir", ""), ("web_root", str(project)), ("desktop_dir", ""), ("entries", []), ("entry", ""),
                 ("modules", []), ("missing", {}), ("case_issues", {}), ("remote_hosts", []), ("calls", {}),
                 ("known_calls", {}), ("unknown_calls", {}), ("files", []), ("size", 0), ("icons", [])):
        rep[k] = v
    if ea.get("error"):
        rep["problems"].append(ea["error"])
        return rep
    pkg = ea["pkg"]
    main = ea["main"]
    excl = settings.get("exclude")
    patterns = split_patterns(ELECTRON_EXCLUDE if excl in (None, "", DEFAULT_EXCLUDE) else excl)
    # electron-builder's output and build-resources folders (and a "release" folder) are not part of the app
    skip = [project / d for d in {ea["out_dir"], ea["res_dir"], "release"}
            if (project / d).is_dir() and not main.startswith(d.strip("/") + "/")]
    files = walk_files(project, patterns, skip_dirs=skip)
    rep["files"] = files
    rep["size"] = sum((project / f).stat().st_size for f in files if (project / f).is_file())
    b = ea["build"]
    rep["name"] = str(pkg.get("productName") or b.get("productName") or
                      str(pkg.get("name", "")).replace("-", " ").title() or project.name).strip()[:60]
    rep["version"] = pkg.get("version") or "1.0.0"
    rep["description"] = pkg.get("description", "")
    author = pkg.get("author", "")
    rep["author"] = author.get("name", "") if isinstance(author, dict) else str(author)
    rep["copyright"] = b.get("copyright", "")
    rep["icons"] = _icon_candidates_electron(project, ea, files)
    rep["entry"] = main
    if main not in files:
        rep["problems"].append(f"The main script “{main}” is left out by the “Don't copy” list.")
    deps = runtime_dependencies(project, pkg)
    rep["deps"] = {n: _dep_source_label(project, s) for n, s in sorted(deps.items())}
    missing = [n for n, w in rep["deps"].items() if w == "missing"]
    if missing:
        rep["warnings"].append("Not installed in the project: " + ", ".join(missing) + ". Studio installs "
                               "them once into the app with its own Node/npm while building (needs internet).")
    native = [n for n, s in deps.items() if s and n != "koffi" and (any(Path(s).rglob("*.node")) or (Path(s) / "binding.gyp").is_file())]
    if native:
        rep["notes"].append("Native modules (" + ", ".join(native) + ") must be built for Electron " +
                            (ea["electron_pin"] or "your version") + " (electron-rebuild) or they fail to load.")
    if ea["electron_pin"]:
        rep["notes"].append(f"The app was made for Electron {ea['electron_pin']} (package.json).")
    rep["notes"].append(f"Electron app: it runs its own main script {main} and makes its own windows, tray and "
                        "settings, so the Window, Tray & Start and Behavior tabs are not used.")
    extra = b.get("extraResources") or []
    rep["extra_resources"] = _copy_specs(project, extra)
    rep["extra_files"] = _copy_specs(project, b.get("extraFiles") or [])
    gone = [s["from"] for s in rep["extra_resources"] + rep["extra_files"] if not (project / s["from"]).exists()]
    if gone:
        rep["warnings"].append("package.json build.extraResources/extraFiles name missing files: " + ", ".join(gone))
    if (pkg.get("scripts") or {}).get("build") and re.search(r"\b(tsc|webpack|vite|rollup|esbuild|parcel)\b",
                                                             (pkg.get("scripts") or {}).get("build", "")):
        rep["notes"].append(f"Its build script (“{pkg['scripts']['build']}”) compiles code first: tick “Run the build "
                            "command” with e.g. “npm run compile” if the main script comes from that step.")
    return rep


def _copy_specs(project, specs):
    """electron-builder extraResources / extraFiles → [{'from', 'to'}] (strings or {from, to})."""
    out = []
    for s in specs if isinstance(specs, list) else [specs]:
        if isinstance(s, str):
            out.append({"from": s, "to": s})
        elif isinstance(s, dict) and s.get("from"):
            out.append({"from": s["from"], "to": s.get("to") or s["from"]})
    return out


def _foreign_bridges(web_root, files):
    """Names like window.mk.invoke(…) used by the pages but defined nowhere in them (another app's preload)."""
    names, texts = set(), []
    for f in files:
        if Path(f).suffix.lower() in (".js", ".mjs", ".html", ".htm"):
            t = read_text(Path(web_root) / f, 2 << 20)
            texts.append(t)
            names.update(_BRIDGE_RE.findall(t))
    names -= {"desktop", "electron", "location", "history", "localStorage", "parent", "top", "opener"}
    joined = "\n".join(texts)
    return sorted(n for n in names if not re.search(_BRIDGE_DEF_RE.format(re.escape(n)), joined))


def _dep_ignore(arch):
    def ignore(dirpath, names):
        skip = {"test", "tests", "__tests__", ".github"} & set(names)
        d = Path(dirpath)
        if d.name == "koffi" and d.parent.name == "build":
            skip |= {n for n in names if n != f"win32_{arch}" and re.match(r"(win32|linux|darwin|freebsd|openbsd|musl)_", n)}
        if d.name == "koffi" and (d / "package.json").is_file():
            skip |= {"src", "doc", "vendor"} & set(names)
        return skip
    return ignore


def npm_install_into(app_dir, names, pkg, cfg_obj, job, say):
    """Install only the missing runtime packages into app_dir/node_modules (a throwaway package.json)."""
    node, _how = S.resolve_node(cfg_obj)
    if not node:
        raise RuntimeError("These packages are not installed in the project: " + ", ".join(names) +
                           ". Run “npm install” in the project, or set up Node in the Engines tab.")
    want = {**(pkg.get("optionalDependencies") or {}), **(pkg.get("dependencies") or {})}
    tmp = Path(tempfile.mkdtemp(prefix="aos-npm-"))
    try:
        (tmp / "package.json").write_text(json.dumps({"name": "aos-deps", "private": True,
                                                      "dependencies": {n: want.get(n, "latest") for n in names}}), encoding="utf-8")
        env = dict(os.environ)
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        say("   installing " + ", ".join(names) + " with npm…")
        _stream([*_shell(), "npm install --omit=dev --no-audit --no-fund --no-package-lock"], tmp, env, job)
        nm = tmp / "node_modules"
        for d in nm.iterdir() if nm.is_dir() else []:
            if d.name.startswith("."):
                continue
            targets = [d] if not d.name.startswith("@") else [x for x in d.iterdir()]
            for t in targets:
                dst = Path(app_dir) / "node_modules" / t.relative_to(nm)
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(t, dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


BOOT_JS = """/* Written by Advanced Outboxer Studio — starts this app's own main script ({main}).
 * When the app runs through its small launcher exe (shared Electron, or Electron in the 'runtime'
 * folder), Electron itself is electron.exe, so the app would think it is not installed. This makes it
 * see the launcher as its exe: app.isPackaged is true, "Start with Windows" and files next to the exe
 * use the launcher, and process.resourcesPath is the app's own 'resources' folder (extraResources). */
'use strict';
const fs = require('fs');
const path = require('path');
const boot = require('./aos-boot.json');
const launcher = boot.exeName ? path.join(__dirname, '..', boot.exeName) : '';
if (launcher && /^electron(\\.exe)?$/i.test(path.basename(process.execPath)) && fs.existsSync(launcher)) {
  const { app } = require('electron');
  try { Object.defineProperty(app, 'isPackaged', { get: () => true, configurable: true }); } catch (_) { /* keep Electron's */ }
  process.execPath = launcher;
  const res = path.join(__dirname, '..', 'resources');
  if (fs.existsSync(res)) {
    try { Object.defineProperty(process, 'resourcesPath', { value: res, enumerable: true, configurable: true }); } catch (_) { /* keep */ }
  }
}
const main = path.join(__dirname, boot.main);
if (boot.esm) import(require('url').pathToFileURL(main).href);
else require(main);
"""


def stage_electron_app(st, rep, app_dir, exe_name, cfg_obj, job=None, say=print, arch="x64", res_dir=None, files_dir=None):
    """Copy an Electron app folder into app_dir (+ its runtime dependencies) and put the boot script in front.
    res_dir: where extraResources go (process.resourcesPath of the built app); files_dir: extraFiles (next to the exe)."""
    project = Path(rep["project"])
    ea = rep["electron"]
    app_dir = Path(app_dir)
    if app_dir.exists():
        shutil.rmtree(app_dir)
    files = rep.get("files") or []
    say(f"   copying {len(files)} app file(s) ({human_size(rep.get('size', 0))})…")
    copy_tree_files(project, files, app_dir, job)
    deps = runtime_dependencies(project, ea["pkg"])
    missing = sorted(n for n, s in deps.items() if s is None)
    present = {n: s for n, s in deps.items() if s is not None}
    if present:
        say("   dependencies: " + ", ".join(f"{n} ({_dep_source_label(project, s)})" for n, s in sorted(present.items())))
    for name, src in present.items():
        dst = app_dir / "node_modules" / name
        if not dst.exists():
            shutil.copytree(src, dst, ignore=_dep_ignore(arch), symlinks=False)
    if missing:
        npm_install_into(app_dir, missing, ea["pkg"], cfg_obj, job, say)
        still = [n for n in missing if not (app_dir / "node_modules" / n / "package.json").is_file()]
        if still:
            raise RuntimeError("npm could not install: " + ", ".join(still))
    pkg = dict(ea["pkg"])
    pkg["aosMain"] = ea["main"]
    pkg["main"] = BOOT_FILE
    (app_dir / "package.json").write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
    (app_dir / BOOT_FILE).write_text(BOOT_JS.replace("{main}", ea["main"]), encoding="utf-8")
    (app_dir / "aos-boot.json").write_text(json.dumps({"main": ea["main"], "exeName": exe_name, "esm": ea["esm"]}),
                                           encoding="utf-8")
    name = st.get("name") or rep["name"]
    cfg = {"builtBy": BUILT_BY, "builtAt": time.strftime("%Y-%m-%d %H:%M"), "kind": "electron", "name": name,
           "version": st.get("version") or rep["version"], "description": st.get("description") or rep.get("description", ""),
           "author": st.get("copyright") or rep.get("copyright") or rep.get("author", ""), "exeName": exe_name, "main": ea["main"]}
    (app_dir / "app.config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    for specs, base in ((rep.get("extra_resources") or [], res_dir), (rep.get("extra_files") or [], files_dir)):
        for spec in specs if base else []:
            src, dst = project / spec["from"], Path(base) / spec["to"]
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif src.is_file():
                dst = dst / src.name if spec["to"].endswith(("/", "\\")) else dst
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            say(f"   extra: {spec['from']} → {Path(base).name}\\{spec['to']}")
    icon_src = st.get("icon") or (rep["icons"][0][0] if rep.get("icons") else "")
    png = ico = None
    if icon_src:
        (app_dir / ".aos").mkdir(exist_ok=True)
        png, ico = prepare_icons(icon_src, app_dir / ".aos", say)
        say(f"   icon: {icon_src}")
    return cfg, png, ico


TEST_PATHS_JS = """/* Advanced Outboxer Studio Test Run: lets the app find packages its folder lacks (e.g. koffi from Studio). */
'use strict';
const Module = require('module');
process.env.NODE_PATH = [process.env.AOS_NODE_PATH, process.env.NODE_PATH].filter(Boolean).join(require('path').delimiter);
Module._initPaths();
"""


def prepare_electron_test(rep, work_dir, cfg_obj, job, say=print):
    """Test Run of an Electron app straight from its own folder. Packages it lacks come from Studio's host
    or a one-off npm install into work_dir, found through a tiny --require script. Returns extra env vars."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    pkg = rep["electron"]["pkg"]
    cache = work / "deps"
    deps = runtime_dependencies(rep["project"], pkg, extra_roots=[cache / "node_modules"])
    missing = sorted(n for n, s in deps.items() if s is None)
    if missing:
        cache.mkdir(exist_ok=True)
        npm_install_into(cache, missing, pkg, cfg_obj, job, say)
    borrowed = sorted(n for n, s in deps.items() if s is not None and _dep_source_label(rep["project"], s) == "Studio")
    if borrowed:
        say("   from Studio: " + ", ".join(borrowed))
    js = work / "aos-paths.cjs"
    js.write_text(TEST_PATHS_JS, encoding="utf-8")
    # forward slashes: inside NODE_OPTIONS quotes a backslash is an escape character
    opts = (os.environ.get("NODE_OPTIONS", "") + f' --require "{js.as_posix()}"').strip()
    return {"NODE_OPTIONS": opts,
            "AOS_NODE_PATH": os.pathsep.join([str(cache / "node_modules"), str(HOST_DIR / "node_modules")])}


def electron_version_for(st, rep, default):
    """The Electron to build with: the project setting, else the app's own major version if Studio's differs."""
    if st.get("electron_version"):
        return st["electron_version"]
    pin = ((rep or {}).get("electron") or {}).get("electron_pin", "")
    if pin and pin.split(".")[0] != str(default).split(".")[0]:
        return pin
    return default


def report_html(rep):
    """The Check tab: a readable report."""
    e = htmlmod.escape
    out = []
    ok = not rep.get("problems")
    out.append(f"<h3>{'✅ Ready to build' if ok else '❌ Needs attention'}</h3>")
    for p in rep.get("problems", []):
        out.append(f"<p style='color:#DC2626'>❌ {e(p)}</p>")
    for w in rep.get("warnings", []):
        out.append(f"<p style='color:#D97706'>⚠️ {e(w)}</p>")
    for n in rep.get("notes", []):
        out.append(f"<p>ℹ️ {e(n)}</p>")
    if rep.get("kind") == "electron":
        ea = rep.get("electron") or {}
        deps = rep.get("deps") or {}
        rows = [("Project folder", rep.get("project", "")),
                ("Type", "Electron app (runs its own main script)"),
                ("Main script", rep.get("entry") or "—"),
                ("App", f"{rep.get('name', '')} {rep.get('version', '')}"),
                ("Made for", f"Electron {ea.get('electron_pin')}" if ea.get("electron_pin") else "—"),
                ("Files", f"{len(rep.get('files', []))} ({human_size(rep.get('size', 0))})"),
                ("Dependencies", ", ".join(f"{n} ({w})" for n, w in deps.items()) or "none"),
                ("Extra files", ", ".join(x["from"] for x in rep.get("extra_resources", []) + rep.get("extra_files", [])) or "none"),
                ("Icon", rep["icons"][0][0] if rep.get("icons") else "none found — the app gets a default icon")]
        out.append("<table>" + "".join(f"<tr><td style='color:#64748B;padding-right:14px'>{e(k)}</td><td>{e(str(v))}</td></tr>"
                                       for k, v in rows) + "</table>")
        top = sorted({f.split("/")[0] + ("/" if "/" in f else "") for f in rep.get("files", [])})
        out.append("<p style='color:#64748B'>Copied into the app: " + e(", ".join(top[:20])) + (" …" if len(top) > 20 else "") +
                   " — plus its dependencies. node_modules, tests, the build/dist folders and outboxer.json are left out.</p>")
        return "\n".join(out)
    fw = rep.get("framework") or {}
    rows = [("Project folder", rep.get("project", "")),
            ("Web folder", rep.get("web_root", "")),
            ("Start page", rep.get("entry") or "—"),
            ("Pages", ", ".join(rep.get("entries", [])[:12]) + (" …" if len(rep.get("entries", [])) > 12 else "") or "—"),
            ("Files", f"{len(rep.get('files', []))} ({human_size(rep.get('size', 0))})"),
            ("Framework", fw.get("label") or "plain HTML/CSS/JS"),
            ("desktop folder", ", ".join(rep.get("modules", [])) or "none"),
            ("Icon", rep["icons"][0][0] if rep.get("icons") else "none found — the app gets a default icon")]
    out.append("<table>" + "".join(f"<tr><td style='color:#64748B;padding-right:14px'>{e(k)}</td><td>{e(str(v))}</td></tr>"
                                   for k, v in rows) + "</table>")
    calls = rep.get("known_calls", {})
    if calls or rep.get("unknown_calls"):
        out.append("<h4>Toolbox commands used</h4><p>")
        out.append(", ".join(f"<code>desktop.{e(k)}</code>×{n}" for k, n in sorted(calls.items())))
        if rep.get("unknown_calls"):
            out.append("<br><span style='color:#DC2626'>Unknown: " +
                       ", ".join(f"<code>desktop.{e(k)}</code>" for k in sorted(rep['unknown_calls'])) + "</span>")
        out.append("</p>")
    else:
        out.append("<p style='color:#64748B'>The pages do not use the desktop toolbox yet (that's fine).</p>")
    if rep.get("missing"):
        out.append("<h4>Links to missing files</h4><ul>")
        for f, refs in sorted(rep["missing"].items()):
            out.append(f"<li><b>{e(f)}</b>: " + ", ".join(e(r) for r in refs[:8]) + (" …" if len(refs) > 8 else "") + "</li>")
        out.append("</ul>")
    if rep.get("case_issues"):
        out.append("<h4>Upper/lower case differences</h4><ul>")
        for f, refs in sorted(rep["case_issues"].items()):
            out.append(f"<li><b>{e(f)}</b>: " + ", ".join(e(r) for r in refs[:8]) + "</li>")
        out.append("</ul>")
    return "\n".join(out)


# ======================================================================= settings
DEFAULT_SETTINGS = {
    # project
    "app_type": "auto", "entry": "", "web_dir": None, "build_cmd": "", "run_build": False, "exclude": DEFAULT_EXCLUDE,
    # app
    "mode": "bundled", "runtime_dir": "", "name": "", "version": "", "app_id": "", "icon": "",
    "description": "", "copyright": "", "electron_version": "", "portable": False, "single_instance": True,
    # window
    "width": 1100, "height": 750, "min_width": 0, "min_height": 0, "resizable": True, "maximized": False,
    "fullscreen": False, "kiosk": False, "frameless": False, "transparent": False, "always_on_top": False,
    "remember_bounds": True, "background_color": "", "title_bar": "default", "zoom": 1.0, "skip_taskbar": False,
    "start_hidden": False,
    # tray & start-up
    "tray": False, "close_to_tray": False, "minimize_to_tray": False, "tray_tooltip": "", "show_hotkey": "",
    "autostart": False, "hide_on_autostart": True,
    # behaviour
    "links": "browser", "spa": False, "devtools": "dev", "context_menu": True, "spellcheck": True,
    "permissions": True, "allow_remote": "", "user_agent": "",
    # output
    "shortcut_desktop": True, "shortcut_start": False, "make_zip": False, "run_after": False,
}


def load_settings(project):
    p = Path(project) / SETTINGS_FILE
    data = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(read_text(p))
        if isinstance(saved, dict):
            data.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except Exception:
        pass
    return data


def save_settings(project, settings):
    p = Path(project) / SETTINGS_FILE
    data = {k: settings.get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    data["_about"] = f"Settings of this project in {BUILT_BY}. Safe to delete; safe to commit."
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def app_id_for(name, explicit=""):
    if explicit:
        return re.sub(r"[^A-Za-z0-9._-]", "", explicit) or "outboxer.app"
    return "outboxer." + slug(name, "")


def app_config(st, rep, mode, dev=False, exe_name=""):
    """app.config.json for the host. st: settings, rep: scan report."""
    name = st.get("name") or rep.get("name") or "App"
    remote = [u.strip() for u in re.split(r"[;,\s]+", st.get("allow_remote") or "") if u.strip()]
    cfg = {
        "builtBy": BUILT_BY, "builtAt": time.strftime("%Y-%m-%d %H:%M"),
        "name": name, "appId": app_id_for(name, st.get("app_id", "")), "version": st.get("version") or rep.get("version") or "1.0.0",
        "description": st.get("description") or rep.get("description", ""), "author": st.get("copyright", ""),
        "entry": st.get("entry") or rep.get("entry") or "index.html",
        "webRoot": rep["web_root"] if dev else "www", "desktopDir": (rep.get("desktop_dir") or "") if dev else "desktop",
        "mode": "dev" if dev else mode, "exeName": exe_name,
        "window": {
            "width": int(st.get("width") or 1100), "height": int(st.get("height") or 750),
            "minWidth": int(st.get("min_width") or 0), "minHeight": int(st.get("min_height") or 0),
            "resizable": bool(st.get("resizable", True)), "startMaximized": bool(st.get("maximized")),
            "fullscreen": bool(st.get("fullscreen")), "kiosk": bool(st.get("kiosk")),
            "frame": not st.get("frameless") and not st.get("transparent"), "transparent": bool(st.get("transparent")),
            "alwaysOnTop": bool(st.get("always_on_top")), "rememberBounds": bool(st.get("remember_bounds", True)),
            "backgroundColor": st.get("background_color") or "", "titleBarStyle": "hidden" if st.get("title_bar") in ("hidden", "overlay") else "default",
            "titleBarOverlay": st.get("title_bar") == "overlay", "zoom": float(st.get("zoom") or 1.0),
            "skipTaskbar": bool(st.get("skip_taskbar")), "startHidden": bool(st.get("start_hidden")),
            "hideOnAutostart": bool(st.get("hide_on_autostart", True)),
        },
        "tray": {"enabled": bool(st.get("tray") or st.get("close_to_tray") or st.get("minimize_to_tray")),
                 "tooltip": st.get("tray_tooltip") or "", "closeToTray": bool(st.get("close_to_tray")),
                 "minimizeToTray": bool(st.get("minimize_to_tray")), "menu": True},
        "showHotkey": st.get("show_hotkey") or "",
        "singleInstance": bool(st.get("single_instance", True)),
        "devTools": {"dev": "dev", "always": True, "never": False}.get(st.get("devtools", "dev"), "dev"),
        "links": st.get("links") or "browser", "spaFallback": bool(st.get("spa")),
        "portable": bool(st.get("portable")), "allowRemote": remote, "userAgent": st.get("user_agent") or "",
        "permissions": bool(st.get("permissions", True)), "contextMenu": bool(st.get("context_menu", True)),
        "spellcheck": bool(st.get("spellcheck", True)), "autoStart": bool(st.get("autostart")),
    }
    if dev and st.get("icon"):
        cfg["icon"] = st["icon"]
    elif dev and rep.get("icons"):
        cfg["icon"] = rep["icons"][0][0]
    return cfg


# ======================================================================= icons
def prepare_icons(src, out_dir, log=print):
    """From any image: icon.png (256 px, window/tray) and icon.ico (multi-size, exe). Returns (png, ico) or Nones."""
    out_dir = Path(out_dir)
    if not src or not Path(src).is_file():
        return None, None
    data = Path(src).read_bytes()
    png = ico = None
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data))
        try:
            if getattr(img, "ico", None):
                img = img.ico.getimage(max(img.ico.sizes()))
        except Exception:
            pass
        img = img.convert("RGBA")
        side = max(img.size)
        if img.size[0] != img.size[1]:
            sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            sq.paste(img, ((side - img.size[0]) // 2, (side - img.size[1]) // 2))
            img = sq
        big = img.resize((256, 256), Image.LANCZOS) if side != 256 else img
        png = out_dir / "icon.png"
        big.save(png, format="PNG")
        ico = out_dir / "icon.ico"
        sizes = [s for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
        big.save(ico, format="ICO", sizes=[(s, s) for s in sizes])
    except ImportError:
        if data[:4] == b"\x00\x00\x01\x00":
            ico = out_dir / "icon.ico"
            ico.write_bytes(data)
        elif data[:8] == b"\x89PNG\r\n\x1a\n":
            png = out_dir / "icon.png"
            png.write_bytes(data)
        log("   (install Pillow for full icon support: python -m pip install pillow)")
    except Exception as ex:
        log(f"   (the icon could not be converted: {ex})")
    return png, ico


# ======================================================================= staging & building
def copy_tree_files(src_root, rel_files, dst_root, job=None):
    dst_root = Path(dst_root)
    for i, rel in enumerate(rel_files):
        if job is not None and getattr(job, "cancelled", False):
            raise S.Cancelled()
        d = dst_root / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(src_root) / rel, d)


def copy_host(dst, include_arch=("win32_x64", "win32_arm64", "win32_ia32"), arch="x64"):
    """The app host (main.js, preload, toolbox, koffi…) -> dst. Only the koffi build for `arch` is kept."""
    dst = Path(dst)

    def ignore(dirpath, names):
        skip = {"test", "tests", "__pycache__"} & set(names)
        if Path(dirpath).name == "koffi" and Path(dirpath).parent.name == "build":
            skip |= {n for n in names if n != f"win32_{arch}" and n.startswith(("win32_", "linux_", "darwin_", "freebsd_", "openbsd_", "musl_"))}
        return skip
    shutil.copytree(HOST_DIR, dst, ignore=ignore, dirs_exist_ok=True)
    return dst


def stage_app(st, rep, app_dir, mode, exe_name, job=None, say=print, arch="x64"):
    """Assemble the complete 'app' folder (host + www + desktop + config + icons)."""
    app_dir = Path(app_dir)
    if app_dir.exists():
        shutil.rmtree(app_dir)
    copy_host(app_dir, arch=arch)
    web_root = Path(rep["web_root"])
    files = rep.get("files") or []
    say(f"   copying {len(files)} project file(s) ({human_size(rep.get('size', 0))})…")
    copy_tree_files(web_root, files, app_dir / "www", job)
    if rep.get("desktop_dir"):
        dd = Path(rep["desktop_dir"])
        # the desktop folder is copied whole, including its node_modules (its npm packages)
        shutil.copytree(dd, app_dir / "desktop", ignore=shutil.ignore_patterns(".git", "*.log", ".vscode", ".idea"))
        say(f"   desktop modules: {', '.join(rep.get('modules', [])) or '(none)'}")
    cfg = app_config(st, rep, mode, dev=False, exe_name=exe_name)
    (app_dir / "app.config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    pkg = {"name": slug(cfg["name"]), "productName": cfg["name"], "version": norm_version(cfg["version"]),
           "description": cfg["description"] or cfg["name"], "main": "main.js", "private": True,
           "author": cfg["author"] or "", "builtBy": BUILT_BY}
    (app_dir / "package.json").write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
    icon_src = st.get("icon") or (rep["icons"][0][0] if rep.get("icons") else "")
    png, ico = prepare_icons(icon_src, app_dir, say) if icon_src else (None, None)
    if icon_src:
        say(f"   icon: {icon_src}")
    return cfg, png, ico


def norm_version(v):
    nums = re.findall(r"\d+", str(v or ""))[:3]
    while len(nums) < 3:
        nums.append("0")
    return ".".join(str(int(n)) for n in nums)


def find_rcedit(engines_dir):
    """rcedit-x64.exe (sets an exe's icon and version text). Nativefier's engine ships one."""
    cands = []
    for base in (Path(engines_dir) / "tools", Path(engines_dir) / "nativefier53", Path(engines_dir)):
        if base.is_dir():
            cands += list(base.glob("rcedit*.exe")) + list(base.glob("node_modules/rcedit/bin/rcedit*.exe")) + \
                list(base.glob("node_modules/**/rcedit/bin/rcedit-x64.exe"))
    cands.sort(key=lambda p: ("x64" not in p.name, len(str(p))))
    return cands[0] if cands else None


def run_rcedit(rcedit, exe, cfg, ico, copyright_text=""):
    ver = norm_version(cfg["version"])
    args = [str(rcedit), str(exe), "--set-file-version", ver, "--set-product-version", ver,
            "--set-version-string", "FileDescription", cfg["name"], "--set-version-string", "ProductName", cfg["name"],
            "--set-version-string", "InternalName", cfg["name"], "--set-version-string", "OriginalFilename", Path(exe).name,
            "--set-version-string", "CompanyName", cfg.get("author") or cfg["name"],
            "--set-version-string", "LegalCopyright", copyright_text or cfg.get("author") or ""]
    if ico:
        args += ["--set-icon", str(ico)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=120, creationflags=S._no_window())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "rcedit failed").strip()[:500])


def unzip_into(zip_path, dest, job=None):
    dest = Path(dest)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for m in zf.infolist():
            if job is not None and getattr(job, "cancelled", False):
                raise S.Cancelled()
            out = (dest / m.filename).resolve()
            if root != out and root not in out.parents:
                continue
            if m.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if os.name != "nt" and (m.external_attr >> 16) & 0o111:
                out.chmod(0o755)


def ensure_electron_zip(cfg_obj, version, job, arch=None):
    folder = cfg_obj.resolve("electron_dir")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"electron-v{version}-{S.HOST_PLATFORM}-{arch or S.HOST_ARCH}.zip"
    z = folder / name
    if z.is_file():
        return z
    job.say(f"   Electron {version} is not in Engines yet — downloading it once (about 110–160 MB)…")
    return S.download_electron(version, folder, job, S.HOST_PLATFORM, arch or S.HOST_ARCH)


def is_our_app(folder):
    for c in (Path(folder) / "resources" / "app" / "app.config.json", Path(folder) / "app" / "app.config.json"):
        try:
            if BUILT_BY in json.loads(read_text(c)).get("builtBy", ""):
                return True
        except Exception:
            continue
    return False


def make_shortcut(lnk, target, workdir, description="", icon=None):
    """Windows .lnk through PowerShell (WScript.Shell)."""
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:AOS_LNK);"
          "$s.TargetPath=$env:AOS_TARGET;$s.WorkingDirectory=$env:AOS_DIR;$s.Description=$env:AOS_DESC;"
          "if ($env:AOS_ICON) { $s.IconLocation=$env:AOS_ICON+',0' };$s.Save()")
    env = {**os.environ, "AOS_LNK": str(lnk), "AOS_TARGET": str(target), "AOS_DIR": str(workdir),
           "AOS_DESC": description, "AOS_ICON": str(icon or "")}
    Path(lnk).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                       capture_output=True, text=True, timeout=30, creationflags=S._no_window())
    return r.returncode == 0 and Path(lnk).exists()


def run_build_command(project, command, node_exe, job):
    """npm run build (or any command) in the project folder, with Studio's Node first on PATH."""
    env = dict(os.environ)
    if node_exe:
        env["PATH"] = str(Path(node_exe).parent) + os.pathsep + env.get("PATH", "")
    job.say(f"   running “{command}” in {project}…")
    if not (Path(project) / "node_modules").is_dir() and (Path(project) / "package.json").is_file() and command.startswith("npm"):
        job.say("   node_modules is missing — running “npm install” first…")
        _stream([*_shell(), "npm install --no-audit --no-fund"], project, env, job)
    _stream([*_shell(), command], project, env, job)


def _shell():
    return ["cmd.exe", "/d", "/s", "/c"] if os.name == "nt" else ["/bin/sh", "-c"]


def _stream(cmd, cwd, env, job):
    p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=S._no_window())
    for raw in iter(p.stdout.readline, b""):
        if getattr(job, "cancelled", False):
            p.kill()
            raise S.Cancelled()
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            job.say("     " + line)
    code = p.wait()
    if code != 0:
        raise RuntimeError(f"“{' '.join(cmd[-1:])}” failed (exit code {code}) — see the lines above.")


def build_project(st, project, cfg_obj, out_root, job, arch=None):
    """Build the app. Returns {'dest': folder, 'exe': path, 'mode': …}. Runs in a worker thread (job)."""
    arch = arch or S.HOST_ARCH
    say = job.say
    project = Path(project)
    if st.get("run_build") and st.get("build_cmd"):
        node, _how = S.resolve_node(cfg_obj)
        run_build_command(project, st["build_cmd"], node, job)
    rep = scan_project(project, st)
    if rep["problems"]:
        raise RuntimeError("\n".join(rep["problems"]))
    for w in rep["warnings"]:
        say(f"   ⚠️ {w}")
    name = st.get("name") or rep["name"]
    folder_name = safe_name(name)
    exe_name = folder_name + ".exe"
    mode = st.get("mode") or "bundled"
    version = electron_version_for(st, rep, cfg_obj.get("electron_version") or S.DEFAULT_ELECTRON_VERSION)
    electron_app = rep.get("kind") == "electron"
    if electron_app:
        say(f"   Electron app: runs its own main script {rep['entry']} (Electron {version})")
    work = Path(tempfile.mkdtemp(prefix="aos-build-"))
    stage = work / folder_name

    def stage_into(app_dir, smode, exe):
        if electron_app:  # extraResources -> <app>\resources (process.resourcesPath), extraFiles -> next to the exe
            return stage_electron_app(st, rep, app_dir, exe, cfg_obj, job, say, arch=arch,
                                      res_dir=stage / "resources", files_dir=stage)
        return stage_app(st, rep, app_dir, smode, exe, job, say, arch=arch)

    try:
        if mode == "shared":
            runtime = Path(st["runtime_dir"]) if st.get("runtime_dir") else cfg_obj.resolve("runtime_dir") / S.runtime_name(version, arch=arch)
            if not (runtime / "electron.exe").is_file() and not (runtime / "electron").is_file():
                z = ensure_electron_zip(cfg_obj, version, job, arch)
                S.ensure_runtime(runtime, version, z.parent, say)
            stage.mkdir(parents=True)
            cfg, png, ico = stage_into(stage / "app", "shared", exe_name)
            say("   compiling the small launcher exe…")
            S.compile_launcher(stage / exe_name, cfg["name"], cfg["version"], ico, say)
            (stage / S.RUNTIME_FILE).write_text(
                f"{runtime}\n"
                "# The first line is the folder with electron.exe that this app runs on (the shared Electron runtime).\n"
                "# You can change it, e.g. to another Electron version or a network folder. Relative paths start\n"
                "# from this app folder; %VARIABLES% like %LOCALAPPDATA% are allowed.\n", encoding="utf-8")
            say(f"   runs on the shared Electron in: {runtime}")
        else:
            z = ensure_electron_zip(cfg_obj, version, job, arch)
            say(f"   unpacking Electron {version}…")
            rcedit = find_rcedit(S.ENGINES_DIR)
            if rcedit or os.name != "nt":
                unzip_into(z, stage, job)
                for junk in ("default_app.asar",):
                    (stage / "resources" / junk).unlink(missing_ok=True)
                src_exe = stage / ("electron.exe" if (stage / "electron.exe").exists() else "electron")
                exe = stage / (exe_name if src_exe.suffix == ".exe" else folder_name)
                os.replace(src_exe, exe)
                cfg, png, ico = stage_into(stage / "resources" / "app", "bundled", exe.name)
                if rcedit:
                    say("   setting the exe's icon and details…")
                    try:
                        run_rcedit(rcedit, exe, cfg, ico, st.get("copyright", ""))
                    except Exception as ex:
                        say(f"   (could not set the exe icon: {ex})")
            else:
                # No rcedit: Electron goes in a 'runtime' subfolder and a small launcher with the app's
                # icon starts it — the same proven launcher as shared-runtime apps.
                say("   (rcedit not found: using a launcher exe with your icon, Electron in the 'runtime' subfolder)")
                unzip_into(z, stage / "runtime", job)
                # keep resources\default_app.asar: it is what loads the app folder the launcher passes
                cfg, png, ico = stage_into(stage / "app", "shared", exe_name)
                S.compile_launcher(stage / exe_name, cfg["name"], cfg["version"], ico, say)
                (stage / S.RUNTIME_FILE).write_text("runtime\n# Electron is inside this app, in the 'runtime' folder.\n", encoding="utf-8")
        ico_rel = Path(ico).relative_to(stage) if ico else None
        dest = move_into_place(stage, Path(out_root), folder_name, say)
        exe = next((p for p in (dest / exe_name, dest / folder_name) if p.is_file()), None) or next(dest.glob("*.exe"), None)
        result = {"dest": str(dest), "exe": str(exe) if exe else "", "mode": mode, "name": name,
                  "size": sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())}
        if os.name == "nt" and exe:
            icon = dest / ico_rel if ico_rel else (dest / "app" / "icon.ico" if (dest / "app" / "icon.ico").exists()
                                                   else dest / "resources" / "app" / "icon.ico")
            if st.get("shortcut_desktop"):
                lnk = Path(S.desktop_dir()) / f"{folder_name}.lnk"
                if make_shortcut(lnk, exe, dest, cfg["description"] or name, icon if icon.exists() else exe):
                    say(f"   desktop shortcut: {lnk}")
            if st.get("shortcut_start"):
                lnk = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{folder_name}.lnk"
                if make_shortcut(lnk, exe, dest, cfg["description"] or name, icon if icon.exists() else exe):
                    say(f"   Start menu shortcut: {lnk}")
        if st.get("make_zip"):
            zpath = Path(out_root) / f"{folder_name} {norm_version(cfg['version'])}.zip"
            say(f"   making {zpath.name} to share…")
            zip_folder(dest, zpath, job, exclude_top={"data"})
            result["zip"] = str(zpath)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def zip_folder(folder, zpath, job=None, exclude_top=()):
    folder = Path(folder)
    tmp = Path(str(zpath) + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in folder.rglob("*"):
            rel = f.relative_to(folder)
            if rel.parts and rel.parts[0] in exclude_top:
                continue
            if job is not None and getattr(job, "cancelled", False):
                raise S.Cancelled()
            if f.is_file():
                zf.write(f, Path(folder.name) / rel)
    os.replace(tmp, zpath)


def move_into_place(stage, out_root, folder_name, say=print):
    """stage -> out_root\\folder_name, replacing an earlier build of ours (keeping its portable data)."""
    out_root.mkdir(parents=True, exist_ok=True)
    dest = out_root / folder_name
    kept = None
    if dest.exists():
        if is_our_app(dest):
            if os.name == "nt":
                S.MainWindow._stop_processes_under(dest)
            if (dest / "data").is_dir():  # portable app: keep the user's data
                kept = Path(tempfile.mkdtemp(prefix="aos-keep-")) / "data"
                shutil.move(str(dest / "data"), str(kept))
            for attempt in range(5):
                try:
                    shutil.rmtree(dest)
                    break
                except OSError:
                    if attempt == 4:
                        raise RuntimeError(f"{dest} is in use — close the app (also from the tray) and build again.")
                    time.sleep(1)
            say("   replaced the earlier build")
        else:
            i = 2
            while (out_root / f"{folder_name} ({i})").exists():
                i += 1
            dest = out_root / f"{folder_name} ({i})"
            say(f"   “{folder_name}” already exists and was not made by Studio — saving as “{dest.name}”")
    shutil.move(str(stage), str(dest))
    if kept:
        shutil.move(str(kept), str(dest / "data"))
        shutil.rmtree(kept.parent, ignore_errors=True)
    return dest


def test_run_config(st, rep, work_dir):
    """Write the config for Test Run (pages served straight from the project folder)."""
    cfg = app_config(st, rep, "dev", dev=True)
    p = Path(work_dir) / "test-run.config.json"
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


# ======================================================================= templates
def templates():
    """[(folder name, title, description)]"""
    out = []
    if TEMPLATES_DIR.is_dir():
        for d in sorted(TEMPLATES_DIR.iterdir()):
            if d.is_dir():
                info = {}
                try:
                    info = json.loads(read_text(d / "template.json"))
                except Exception:
                    pass
                out.append((d.name, info.get("title", d.name), info.get("description", ""), info.get("order", 50)))
    out.sort(key=lambda t: (t[3], t[1]))
    return [(a, b, c) for a, b, c, _ in out]


def new_project(template, dest, name):
    src = TEMPLATES_DIR / template
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f"{dest} is not empty — choose a new or empty folder.")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("template.json"), dirs_exist_ok=True)
    for f in dest.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".html", ".js", ".json", ".css", ".md"):
            t = f.read_text(encoding="utf-8")
            if "{{APP_NAME}}" in t:
                f.write_text(t.replace("{{APP_NAME}}", name), encoding="utf-8")
    st = load_settings(dest)
    st["name"] = name
    save_settings(dest, st)
    (dest / "desktop.d.ts").write_text(toolbox_dts(), encoding="utf-8")
    return dest


# ======================================================================= guide & types
def toolbox_guide_html(manifest=None, for_browser=False):
    m = manifest or toolbox_manifest()
    e = htmlmod.escape
    intro = read_text(DOCS_DIR / "toolbox-intro.html")
    parts = []
    toc = ["<a href='#master'>Master keys</a>"] + [f"<a href='#ns-{ns}'>{e(NAMESPACE_TITLES.get(ns, ns))}</a>" for ns in m["ns"]]
    parts.append("<p class='toc'>" + " · ".join(toc) + "</p>")

    def fn_html(prefix, name, info):
        doc = e(info.get("doc", "")).replace("\n", "<br>")
        return (f"<div class='fn'><code class='sig'>{prefix}{e(name)}({e(info.get('args', ''))})</code>"
                + (f"<div class='doc'>{doc}</div>" if doc else "") + "</div>")

    parts.append("<h2 id='master'><a name='master'></a>Master keys and events</h2>")
    for name, info in m["top"].items():
        parts.append(fn_html("desktop.", name, info))
    for ns, data in m["ns"].items():
        parts.append(f"<h2 id='ns-{ns}'><a name='ns-{ns}'></a>desktop.{ns} — {e(NAMESPACE_TITLES.get(ns, ''))}</h2>")
        if data.get("doc"):
            parts.append(f"<p class='nsdoc'>{e(data['doc']).replace(chr(10), '<br>')}</p>")
        for name, info in data["fns"].items():
            parts.append(fn_html(f"desktop.{ns}.", name, info))
    body = intro + "\n".join(parts)
    css = ("body{font-family:'Segoe UI',sans-serif;font-size:10.5pt;line-height:1.45;max-width:1000px;margin:auto;padding:0 18px}"
           "h1{font-size:20pt} h2{font-size:14pt;color:#4F46E5;margin-top:26px;border-bottom:1px solid #E5E7EB;padding-bottom:4px}"
           "code{font-family:Consolas,monospace;font-size:9.5pt} .sig{font-weight:bold;color:#0F172A}"
           "pre{background:#F6F7FB;border:1px solid #E5E7EB;border-radius:8px;padding:10px;font-family:Consolas,monospace;font-size:9.5pt;white-space:pre-wrap}"
           ".fn{margin:8px 0 12px} .doc{color:#475569;margin:2px 0 0 14px} .nsdoc{color:#475569;white-space:normal}"
           ".toc a{color:#4F46E5;text-decoration:none} @media (prefers-color-scheme: dark){body{background:#111827;color:#E5E7EB}"
           ".sig{color:#E5E7EB} .doc,.nsdoc{color:#94A3B8} pre{background:#1F2937;border-color:#374151}}")
    if for_browser:
        return (f"<!doctype html><html><head><meta charset='utf-8'><title>Desktop toolbox guide</title><style>{css}</style>"
                f"</head><body>{body}</body></html>")
    return body


def toolbox_dts(manifest=None):
    """desktop.d.ts: lets VS Code suggest and explain every desktop.* command while you type."""
    m = manifest or toolbox_manifest()

    def args_ts(args):
        out = []
        for a in [x.strip() for x in re.split(r",(?![^{]*\})", args) if x.strip()]:
            if a.startswith("..."):
                out.append(f"{a.split('=')[0].strip()}: any[]")
                continue
            nm = re.split(r"\s*=\s*", a, 1)[0].strip()
            if nm.startswith("{"):
                nm = "options"
            out.append(f"{nm}{'?' if '=' in a else ''}: any")
        # optional params must come after required ones in TS
        seen_opt = False
        fixed = []
        for p in out:
            if "?:" in p:
                seen_opt = True
            elif seen_opt and not p.startswith("..."):
                p = p.replace(": any", "?: any")
            fixed.append(p)
        return ", ".join(fixed)

    def doc(t, indent):
        if not t:
            return ""
        lines = t.replace("*/", "* /").splitlines()
        return f"{indent}/**\n" + "".join(f"{indent} * {l}\n" for l in lines) + f"{indent} */\n"

    out = ["// desktop.d.ts — made by Advanced Outboxer Studio. Lets your editor (e.g. VS Code) suggest the",
           "// desktop.* toolbox commands while you type. Keep it in the project folder; it is not copied into the app.",
           "export {};", "declare global {", "  interface DesktopToolbox {",
           "    /** true inside an app made by Advanced Outboxer Studio */", "    isDesktop: boolean;", "    version: string;"]
    for name, info in m["top"].items():
        out.append(doc(info.get("doc", ""), "    ").rstrip("\n"))
        out.append(f"    {name}({args_ts(info.get('args', ''))}): Promise<any>;")
    for ns, data in m["ns"].items():
        out.append(doc(data.get("doc", "") + ("\n" if data.get("doc") else "") + NAMESPACE_TITLES.get(ns, ""), "    ").rstrip("\n"))
        out.append(f"    {ns}: {{")
        for name, info in data["fns"].items():
            out.append(doc(info.get("doc", ""), "      ").rstrip("\n"))
            ret = "any" if (ns == "db" and name == "open") else "Promise<any>"
            out.append(f"      {name}({args_ts(info.get('args', ''))}): {ret};")
        out.append("    };")
    out += ["  }", "  interface Window { desktop: DesktopToolbox; }", "  const desktop: DesktopToolbox;", "}", ""]
    return "\n".join(l for l in out if l != "")
