#!/usr/bin/env python3
r"""MusicOrganizer -- a pure-stdlib tkinter GUI on top of the ``musickit`` API.

A single main window: a left sidebar of tools (Library, Tag Editor, Auto-Tag,
Rename / Organize, Duplicates) and a main panel that swaps to the selected
tool.  Every operation calls the tested core library (never re-implements tag
logic) and long scans run on a background thread so the UI stays responsive;
results marshal back with ``self.after`` and are reported in an inline bar --
never a raw traceback (a :class:`MusicKitError` message instead).

Design goals baked in here:
  * pure standard-library tkinter/ttk -- NO third-party GUI deps.  Dark mode is
    a ttk-style + palette swap (the QuickOpen palette).
  * Importing this module does nothing.  Only :func:`main` builds a root window,
    and it degrades gracefully (prints a note, returns 0) with no display.
  * Frozen-exe safe: bundled assets resolve via ``sys._MEIPASS`` / the exe
    directory when ``sys.frozen`` is set -- never ``__file__``.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import threading

# NOTE: tkinter is imported lazily inside main()/build_app so that merely
# importing this module (e.g. during packaging or on a headless CI box) never
# fails.

APP_NAME = "MusicOrganizer"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "MusicOrganizer — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"

IMAGE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
    ("All files", "*.*"),
]

# (tool_id, label) -- tool_id maps to a _panel_<id> method.
TOOLS = [
    ("library", "Library"),
    ("tageditor", "Tag Editor"),
    ("autotag", "Auto-Tag"),
    ("organize", "Rename / Organize"),
    ("duplicates", "Duplicates"),
]

TOOL_DESCRIPTIONS = {
    "library": "Scan a folder into a sortable table of tracks. Select rows to "
               "edit them in the Tag Editor.",
    "tageditor": "Edit tags (and cover art) on the tracks selected in the "
                 "Library. Tick a field to batch-apply it to every selection.",
    "autotag": "Infer tags from filenames with a pattern like "
               "'{artist} - {title}'. Preview, then apply.",
    "organize": "Rename/move files into a tag-based tree, e.g. "
                "'{albumartist}/{album}/{track:02d} - {title}'. Preview first.",
    "duplicates": "Find duplicate tracks by tags or content hash; review "
                  "groups and remove the copies you don't want.",
}

# Columns shown in the library table (id, heading, width).
LIB_COLUMNS = [
    ("track", "#", 44),
    ("title", "Title", 210),
    ("artist", "Artist", 160),
    ("album", "Album", 160),
    ("year", "Year", 54),
    ("genre", "Genre", 110),
    ("duration_str", "Time", 60),
    ("bitrate", "kbps", 54),
    ("filename", "File", 200),
]

# ---- colour palettes (mirror the QuickOpen palette) -------------------------
PALETTES = {
    "light": {
        "bg": "#f5f7fa", "surface": "#ffffff", "text": "#141820",
        "muted": "#5b6472", "primary": "#2f5fe0", "primary_hi": "#2450c8",
        "entry": "#ffffff", "border": "#d5dae2", "sel": "#2f5fe0",
        "sel_fg": "#ffffff", "trough": "#e2e7ef", "ok": "#1f7a3d",
        "err": "#c0392b",
    },
    "dark": {
        "bg": "#0f1115", "surface": "#1a1e24", "text": "#f1f3f7",
        "muted": "#9aa4b2", "primary": "#5b86f7", "primary_hi": "#7098ff",
        "entry": "#1a1e24", "border": "#2a2f38", "sel": "#5b86f7",
        "sel_fg": "#0f1115", "trough": "#2a2f38", "ok": "#5bd68a",
        "err": "#ff6b5e",
    },
}


# ---------------------------------------------------------------------------
# Asset / frozen handling
# ---------------------------------------------------------------------------
def asset_path(name):
    """Locate a bundled asset from source OR a PyInstaller one-file build.

    For a frozen exe we look only at ``sys._MEIPASS`` and the executable's own
    directory (never ``__file__``).  From source we also consult the package
    dir, the repo root and the CWD.  Returns an absolute path or ``None``.
    """
    roots = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        roots += [here, os.path.dirname(here), os.getcwd()]
    for root in roots:
        candidate = os.path.join(root, name)
        if os.path.exists(candidate):
            return candidate
    return None


def open_in_file_manager(path):
    """Best-effort 'reveal in file manager', guarded on every platform."""
    try:
        folder = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        if hasattr(os, "startfile"):
            os.startfile(folder)              # noqa: S606 - intended
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", folder])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        return False


def open_with_default_app(path):
    """Open a file/URL with the OS default application, guarded."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)                # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The app (built lazily; tkinter imported only inside build_app/main)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to a live tkinter import.

    Kept inside a function so this module imports cleanly without a display.
    """
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    from . import guiconfig
    from .errors import MusicKitError
    from . import tags as tagsmod
    from . import library as librarymod
    from . import autotag as autotagmod
    from . import dedupe as dedupemod
    from . import organize as organizemod
    from .tags import UNIFIED_FIELDS

    FONT = "Segoe UI"

    # -- small reusable widgets ------------------------------------------
    class PathRow(ttk.Frame):
        """A labelled path field + Browse button (folder or file)."""

        def __init__(self, master, label, mode="dir", filetypes=None,
                     on_change=None):
            super().__init__(master, style="TFrame")
            self.mode = mode
            self.filetypes = filetypes
            self.var = tk.StringVar()
            ttk.Label(self, text=label, width=14, anchor="w").pack(side="left")
            ent = ttk.Entry(self, textvariable=self.var)
            ent.pack(side="left", fill="x", expand=True, padx=(0, 6))
            ttk.Button(self, text="Browse…", command=self._browse,
                       width=10).pack(side="left")
            if on_change:
                self.var.trace_add("write", lambda *_: on_change(self.var.get()))

        def _browse(self):
            if self.mode == "dir":
                p = filedialog.askdirectory(title="Choose a folder")
            elif self.mode == "save":
                p = filedialog.asksaveasfilename(
                    title="Save as", filetypes=self.filetypes or IMAGE_TYPES)
            else:
                p = filedialog.askopenfilename(
                    title="Choose a file", filetypes=self.filetypes or IMAGE_TYPES)
            if p:
                self.var.set(p)

        def get(self):
            return self.var.get().strip()

        def set(self, value):
            self.var.set(value or "")

    # -- the main window --------------------------------------------------
    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(WINDOW_TITLE)
            self.geometry("1160x720")
            self.minsize(940, 600)

            self.theme = guiconfig.get_theme()
            self._busy = False
            self._panels = {}
            self._current = None
            self._tracked = []
            self._img_refs = []
            self._tracks = []              # scanned library rows (Library panel)
            self._lib_iid = {}            # tree iid -> track dict
            self._lib_sort = (None, False)
            self._autotag_plan = []
            self._organize_plan = []
            self._dupe_groups = []
            self._pending_cover = None    # (bytes, mime) staged in Tag Editor

            self._set_icon()
            self._build_menu()
            self._build_layout()
            self._apply_theme()
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            self.after(50, self._select_first_tool)

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("music-organizer.ico")
                if ico:
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("music-organizer.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- theming
        def track(self, widget, role):
            self._tracked.append((widget, role))

        def _pal(self):
            return PALETTES[self.theme]

        def _apply_theme(self):
            p = self._pal()
            style = ttk.Style(self)
            try:
                style.theme_use("clam")
            except Exception:
                pass
            self.configure(bg=p["bg"])
            style.configure(".", background=p["bg"], foreground=p["text"],
                            fieldbackground=p["entry"], bordercolor=p["border"],
                            font=(FONT, 10))
            style.configure("TFrame", background=p["bg"])
            style.configure("Sidebar.TFrame", background=p["surface"])
            style.configure("TLabel", background=p["bg"], foreground=p["text"])
            style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
            style.configure("Header.TLabel", background=p["bg"], foreground=p["text"],
                            font=(FONT, 15, "bold"))
            style.configure("Sub.TLabel", background=p["bg"], foreground=p["muted"],
                            font=(FONT, 10))
            style.configure("Brand.TLabel", background=p["surface"],
                            foreground=p["text"], font=(FONT, 12, "bold"))
            style.configure("Status.TLabel", background=p["surface"],
                            foreground=p["muted"])
            style.configure("TButton", background=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], focuscolor=p["surface"],
                            padding=(10, 5))
            style.map("TButton",
                      background=[("active", p["trough"]), ("disabled", p["bg"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Accent.TButton", background=p["primary"],
                            foreground="#ffffff", padding=(12, 6))
            style.map("Accent.TButton",
                      background=[("active", p["primary_hi"]),
                                  ("disabled", p["border"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Danger.TButton", background=p["err"],
                            foreground="#ffffff", padding=(10, 5))
            style.map("Danger.TButton",
                      background=[("active", p["err"]), ("disabled", p["border"])])
            style.configure("Toggle.TButton", background=p["surface"],
                            foreground=p["text"], padding=(8, 4))
            style.configure("Nav.TButton", background=p["surface"],
                            foreground=p["text"], anchor="w", padding=(12, 9),
                            font=(FONT, 11))
            style.map("Nav.TButton", background=[("active", p["trough"])])
            style.configure("NavSel.TButton", background=p["primary"],
                            foreground="#ffffff", anchor="w", padding=(12, 9),
                            font=(FONT, 11, "bold"))
            style.map("NavSel.TButton", background=[("active", p["primary_hi"])])
            for name in ("TEntry", "TSpinbox"):
                style.configure(name, fieldbackground=p["entry"], foreground=p["text"],
                                insertcolor=p["text"], bordercolor=p["border"])
            style.configure("TCombobox", fieldbackground=p["entry"],
                            foreground=p["text"], background=p["surface"],
                            arrowcolor=p["text"])
            style.map("TCombobox", fieldbackground=[("readonly", p["entry"])],
                      foreground=[("readonly", p["text"])])
            style.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
            style.map("TCheckbutton", background=[("active", p["bg"])])
            style.configure("TRadiobutton", background=p["bg"], foreground=p["text"])
            style.map("TRadiobutton", background=[("active", p["bg"])])
            style.configure("TLabelframe", background=p["bg"], foreground=p["text"],
                            bordercolor=p["border"])
            style.configure("TLabelframe.Label", background=p["bg"],
                            foreground=p["muted"])
            style.configure("Treeview", background=p["surface"],
                            fieldbackground=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], rowheight=24)
            style.configure("Treeview.Heading", background=p["surface"],
                            foreground=p["muted"], font=(FONT, 9, "bold"))
            style.map("Treeview", background=[("selected", p["primary"])],
                      foreground=[("selected", p["sel_fg"])])
            style.configure("TScrollbar", background=p["surface"],
                            troughcolor=p["bg"], bordercolor=p["border"],
                            arrowcolor=p["text"])
            style.configure("TSeparator", background=p["border"])

            for widget, role in list(self._tracked):
                try:
                    if role == "text":
                        widget.configure(bg=p["surface"], fg=p["text"],
                                         insertbackground=p["text"],
                                         selectbackground=p["primary"],
                                         selectforeground=p["sel_fg"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"],
                                         borderwidth=0)
                    elif role == "canvas":
                        widget.configure(bg=p["surface"], highlightthickness=1,
                                         highlightbackground=p["border"])
                except Exception:
                    pass
            self._restyle_nav()

        def toggle_theme(self):
            self.theme = "dark" if self.theme == "light" else "light"
            guiconfig.set_theme(self.theme)
            self._apply_theme()
            self._theme_btn.configure(
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")

        # ---- menu
        def _build_menu(self):
            bar = tk.Menu(self)
            filem = tk.Menu(bar, tearoff=0)
            filem.add_command(label="Scan folder…", accelerator="Ctrl+O",
                              command=self._menu_scan)
            self._recent_menu = tk.Menu(filem, tearoff=0)
            filem.add_cascade(label="Recent folders", menu=self._recent_menu)
            self._fill_recent_menu()
            filem.add_separator()
            filem.add_command(label="Exit", command=self.destroy)
            bar.add_cascade(label="File", menu=filem)

            viewm = tk.Menu(bar, tearoff=0)
            viewm.add_command(label="Toggle dark mode", command=self.toggle_theme)
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=self._about)
            helpm.add_command(label="Open project page (quickopen.ai)",
                              command=lambda: open_with_default_app(PROJECT_URL))
            bar.add_cascade(label="Help", menu=helpm)
            self.configure(menu=bar)
            self.bind_all("<Control-o>", lambda e: self._menu_scan())

        def _fill_recent_menu(self):
            self._recent_menu.delete(0, "end")
            recent = guiconfig.get_recent()
            if not recent:
                self._recent_menu.add_command(label="(none)", state="disabled")
                return
            for path in recent:
                exists = os.path.isdir(path)
                label = path if exists else path + "   (missing)"
                self._recent_menu.add_command(
                    label=label, state="normal" if exists else "disabled",
                    command=(lambda pp=path: self._scan_into_library(pp)))
            self._recent_menu.add_separator()
            self._recent_menu.add_command(label="Clear list",
                                          command=self._clear_recent)

        def _clear_recent(self):
            guiconfig.clear_recent()
            self._fill_recent_menu()

        def _menu_scan(self):
            p = filedialog.askdirectory(title="Scan a music folder")
            if p:
                self._select_tool("library")
                self._scan_into_library(p)

        # ---- layout
        def _build_layout(self):
            top = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 8))
            top.pack(fill="x", side="top")
            ttk.Label(top, text="MusicOrganizer", style="Brand.TLabel").pack(side="left")
            ttk.Label(top, style="Status.TLabel",
                      text="  offline · open source · by QuickOpen").pack(side="left")
            self._theme_btn = ttk.Button(
                top, style="Toggle.TButton", command=self.toggle_theme,
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")
            self._theme_btn.pack(side="right")

            body = ttk.Frame(self, style="TFrame")
            body.pack(fill="both", expand=True)

            side = ttk.Frame(body, style="Sidebar.TFrame", width=210)
            side.pack(side="left", fill="y")
            side.pack_propagate(False)
            self._nav_btns = {}
            for tid, label in TOOLS:
                b = ttk.Button(side, text=label, style="Nav.TButton",
                               command=lambda t=tid: self._select_tool(t))
                b.pack(fill="x", padx=6, pady=(6, 0))
                self._nav_btns[tid] = b

            main = ttk.Frame(body, style="TFrame", padding=(16, 12))
            main.pack(side="left", fill="both", expand=True)
            head = ttk.Frame(main, style="TFrame")
            head.pack(fill="x")
            self.title_lbl = ttk.Label(head, text="Welcome", style="Header.TLabel")
            self.title_lbl.pack(anchor="w")
            self.desc_lbl = ttk.Label(head, text="", style="Sub.TLabel",
                                      wraplength=820, justify="left")
            self.desc_lbl.pack(anchor="w", pady=(2, 8))
            ttk.Separator(main).pack(fill="x")
            self.container = ttk.Frame(main, style="TFrame")
            self.container.pack(fill="both", expand=True, pady=(10, 8))

            bar = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 6))
            bar.pack(fill="x", side="bottom")
            self.status_lbl = ttk.Label(bar, text="Ready", style="Status.TLabel",
                                        width=16, anchor="w")
            self.status_lbl.pack(side="left")
            self.result_lbl = ttk.Label(bar, text="", style="Status.TLabel",
                                        anchor="w", wraplength=820, justify="left")
            self.result_lbl.pack(side="left", fill="x", expand=True, padx=8)

        def _restyle_nav(self):
            for tid, b in getattr(self, "_nav_btns", {}).items():
                b.configure(style="NavSel.TButton" if tid == self._current
                            else "Nav.TButton")

        def _select_first_tool(self):
            self._select_tool(TOOLS[0][0])

        def _select_tool(self, tool_id):
            if self._current == tool_id and self._panels.get(tool_id):
                return
            for panel in self._panels.values():
                panel.pack_forget()
            panel = self._panels.get(tool_id)
            if panel is None:
                panel = ttk.Frame(self.container, style="TFrame")
                builder = getattr(self, "_panel_" + tool_id, None)
                if builder:
                    builder(panel)
                else:
                    ttk.Label(panel, text="Not implemented.").pack()
                self._panels[tool_id] = panel
                self._apply_theme()
            panel.pack(fill="both", expand=True)
            self._current = tool_id
            self.title_lbl.configure(text=dict(TOOLS)[tool_id])
            self.desc_lbl.configure(text=TOOL_DESCRIPTIONS.get(tool_id, ""))
            self._clear_result()
            self._restyle_nav()

        # ---- background operation runner
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            """Run ``work()`` off the UI thread; call ``on_ok(result)`` back on it.

            Errors are shown inline (MusicKitError message, or a generic note),
            never as a traceback.  Refuses to start a second op concurrently.
            """
            if self._busy:
                self._show_error("Please wait — an operation is already running.")
                return
            self._busy = True
            if button is not None:
                try:
                    button.state(["disabled"])
                except Exception:
                    pass
            self._set_status(busy, kind="working")

            def run():
                try:
                    res, err = work(), None
                except MusicKitError as ex:
                    res, err = None, str(ex)
                except Exception as ex:
                    res, err = None, f"Unexpected error: {ex}"
                self.after(0, lambda: finish(res, err))

            def finish(res, err):
                self._busy = False
                if button is not None:
                    try:
                        button.state(["!disabled"])
                    except Exception:
                        pass
                if err is not None:
                    self._set_status("error", kind="err")
                    self._show_error(err)
                    return
                self._set_status("done", kind="ok")
                try:
                    on_ok(res)
                except Exception as ex:
                    self._show_error(f"Post-processing error: {ex}")

            threading.Thread(target=run, daemon=True).start()

        # ---- result bar helpers
        def _set_status(self, text, kind="idle"):
            p = self._pal()
            color = {"working": p["primary"], "ok": p["ok"], "err": p["err"]}.get(
                kind, p["muted"])
            self.status_lbl.configure(text=text, foreground=color)

        def _clear_result(self):
            self.result_lbl.configure(text="")
            self._set_status("Ready")

        def _show_error(self, message):
            self.result_lbl.configure(text="✕ " + message,
                                      foreground=self._pal()["err"])

        def _show_ok(self, message):
            self.result_lbl.configure(text="✓ " + message,
                                      foreground=self._pal()["ok"])
            self._set_status("done", kind="ok")

        # ---- About
        def _about(self):
            win = tk.Toplevel(self)
            win.title("About MusicOrganizer")
            win.configure(bg=self._pal()["bg"])
            win.resizable(False, False)
            frm = ttk.Frame(win, style="TFrame", padding=18)
            frm.pack(fill="both", expand=True)
            ttk.Label(frm, text="MusicOrganizer", style="Header.TLabel").pack(anchor="w")
            ttk.Label(frm, text=f"Version {APP_VERSION}",
                      style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
            ttk.Label(frm, style="TLabel", justify="left", wraplength=380,
                      text="A fast, fully-offline music tag & library manager — "
                           "edit tags and cover art, auto-tag from filenames, "
                           "find duplicates and organise by tag patterns.\n\n"
                           "100% AI-built, open source, published on QuickOpen.\n"
                           "Nothing is ever uploaded anywhere.").pack(anchor="w")
            ttk.Label(frm, style="Sub.TLabel", justify="left", wraplength=380,
                      text="Licensed under Apache-2.0. Built on mutagen.").pack(
                anchor="w", pady=(8, 4))
            link = ttk.Label(frm, text="Project page: quickopen.ai",
                             style="Sub.TLabel", cursor="hand2")
            link.pack(anchor="w", pady=(4, 10))
            link.bind("<Button-1>", lambda e: open_with_default_app(PROJECT_URL))
            ttk.Button(frm, text="Close", command=win.destroy).pack(anchor="e")
            win.transient(self)
            win.grab_set()

        # =====================================================================
        # Shared table helper
        # =====================================================================
        def _make_table(self, parent, columns, height=14, selectmode="extended"):
            wrap = ttk.Frame(parent, style="TFrame")
            wrap.pack(fill="both", expand=True)
            tree = ttk.Treeview(wrap, columns=[c[0] for c in columns],
                                 show="headings", selectmode=selectmode,
                                 height=height)
            for cid, heading, width in columns:
                tree.heading(cid, text=heading)
                tree.column(cid, width=width, anchor="w", stretch=False)
            sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
            xsb = ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=sb.set, xscrollcommand=xsb.set)
            sb.pack(side="right", fill="y")
            xsb.pack(side="bottom", fill="x")
            tree.pack(side="left", fill="both", expand=True)
            return tree

        # =====================================================================
        # Library
        # =====================================================================
        def _panel_library(self, parent):
            self._lib_folder = PathRow(parent, "Music folder", mode="dir")
            self._lib_folder.pack(fill="x", pady=4)
            ctrl = ttk.Frame(parent, style="TFrame")
            ctrl.pack(fill="x", pady=(0, 6))
            ttk.Button(ctrl, text="Scan", style="Accent.TButton",
                       command=self._do_scan).pack(side="left")
            ttk.Label(ctrl, text="Filter", style="Muted.TLabel").pack(
                side="left", padx=(14, 4))
            self._lib_filter = tk.StringVar()
            ent = ttk.Entry(ctrl, textvariable=self._lib_filter, width=24)
            ent.pack(side="left")
            ent.bind("<KeyRelease>", lambda e: self._refresh_lib_table())
            ttk.Button(ctrl, text="Edit selected →",
                       command=lambda: self._select_tool("tageditor")).pack(
                side="right")

            self._lib_tree = self._make_table(parent, LIB_COLUMNS, height=16)
            for cid, heading, _w in LIB_COLUMNS:
                self._lib_tree.heading(
                    cid, text=heading,
                    command=lambda c=cid: self._sort_library(c))
            self._lib_count = ttk.Label(parent, text="No folder scanned yet.",
                                        style="Muted.TLabel")
            self._lib_count.pack(anchor="w", pady=(6, 0))

        def _do_scan(self):
            folder = self._lib_folder.get()
            if not folder:
                self._show_error("Choose a music folder to scan.")
                return
            self._scan_into_library(folder)

        def _scan_into_library(self, folder):
            self._lib_folder.set(folder)
            guiconfig.add_recent(folder)
            self._fill_recent_menu()
            self._bg(lambda: librarymod.scan_folder(folder),
                     self._on_scanned, busy="Scanning…")

        def _on_scanned(self, tracks):
            self._tracks = tracks
            self._lib_sort = (None, False)
            self._refresh_lib_table()
            self._show_ok(f"Scanned {len(tracks)} track(s).")

        def _refresh_lib_table(self):
            tree = getattr(self, "_lib_tree", None)
            if tree is None:
                return
            rows = librarymod.search_tracks(self._tracks, self._lib_filter.get())
            field, rev = self._lib_sort
            if field:
                rows = librarymod.sort_tracks(rows, field, reverse=rev)
            tree.delete(*tree.get_children())
            self._lib_iid = {}
            for t in rows:
                vals = [t.get(cid, "") for cid, _h, _w in LIB_COLUMNS]
                iid = tree.insert("", "end", values=vals)
                self._lib_iid[iid] = t
            self._lib_count.configure(
                text=f"{len(rows)} track(s) shown"
                     + (f" of {len(self._tracks)}" if len(rows) != len(self._tracks)
                        else ""))

        def _sort_library(self, field):
            cur, rev = self._lib_sort
            rev = not rev if cur == field else False
            self._lib_sort = (field, rev)
            self._refresh_lib_table()

        def _selected_tracks(self):
            tree = getattr(self, "_lib_tree", None)
            if tree is None:
                return []
            return [self._lib_iid[i] for i in tree.selection() if i in self._lib_iid]

        # =====================================================================
        # Tag Editor
        # =====================================================================
        def _panel_tageditor(self, parent):
            top = ttk.Frame(parent, style="TFrame")
            top.pack(fill="x", pady=(0, 6))
            ttk.Button(top, text="↻ Load from Library selection",
                       command=self._tageditor_load).pack(side="left")
            self._te_count = ttk.Label(top, text="Nothing selected.",
                                       style="Muted.TLabel")
            self._te_count.pack(side="left", padx=10)

            grid = ttk.Frame(parent, style="TFrame")
            grid.pack(fill="x")
            self._te_vars = {}
            self._te_apply = {}
            for i, field in enumerate(UNIFIED_FIELDS):
                chk = tk.BooleanVar(value=False)
                self._te_apply[field] = chk
                ttk.Checkbutton(grid, variable=chk).grid(row=i, column=0, padx=(0, 4))
                ttk.Label(grid, text=field, width=12, anchor="w").grid(
                    row=i, column=1, sticky="w")
                var = tk.StringVar()
                self._te_vars[field] = var
                ent = ttk.Entry(grid, textvariable=var, width=52)
                ent.grid(row=i, column=2, sticky="we", pady=1)
                var.trace_add("write",
                              lambda *_a, f=field: self._te_apply[f].set(True))
            grid.columnconfigure(2, weight=1)
            ttk.Label(parent, style="Muted.TLabel", wraplength=760, justify="left",
                      text="Tick a field to include it when applying. A ticked "
                           "field with empty text CLEARS that tag on every "
                           "selected track.").pack(anchor="w", pady=(6, 6))

            cover = ttk.Labelframe(parent, text="Cover art", padding=8)
            cover.pack(fill="x", pady=4)
            ttk.Button(cover, text="Load image…",
                       command=self._te_load_cover).pack(side="left")
            ttk.Button(cover, text="Save cover from selection…",
                       command=self._te_save_cover).pack(side="left", padx=6)
            self._te_cover_lbl = ttk.Label(cover, text="No image staged.",
                                           style="Muted.TLabel")
            self._te_cover_lbl.pack(side="left", padx=10)

            run = ttk.Frame(parent, style="TFrame")
            run.pack(fill="x", pady=(8, 0))
            ttk.Button(run, text="Apply to selection", style="Accent.TButton",
                       command=self._te_apply_now).pack(side="left")

        def _tageditor_load(self):
            sel = self._selected_tracks()
            self._te_count.configure(
                text=(f"{len(sel)} track(s) selected." if sel
                      else "Nothing selected in Library."))
            if not sel:
                return
            for field in UNIFIED_FIELDS:
                values = {str(t.get(field, "")) for t in sel}
                self._te_vars[field].set(values.pop() if len(values) == 1 else "")
                self._te_apply[field].set(False)

        def _te_load_cover(self):
            p = filedialog.askopenfilename(title="Choose cover image",
                                           filetypes=IMAGE_TYPES)
            if not p:
                return
            try:
                with open(p, "rb") as fh:
                    data = fh.read()
            except OSError as exc:
                self._show_error(f"Could not read image: {exc}")
                return
            ext = os.path.splitext(p)[1].lower()
            mime = {".png": "image/png", ".gif": "image/gif",
                    ".webp": "image/webp"}.get(ext, "image/jpeg")
            self._pending_cover = (data, mime)
            self._te_cover_lbl.configure(
                text=f"Staged {os.path.basename(p)} ({len(data)} bytes).")

        def _te_save_cover(self):
            sel = self._selected_tracks()
            if not sel:
                self._show_error("Select a track in the Library first.")
                return
            data, mime = tagsmod.read_cover(sel[0]["path"])
            if not data:
                self._show_error("That track has no embedded cover art.")
                return
            ext = ".png" if "png" in (mime or "") else ".jpg"
            dest = filedialog.asksaveasfilename(
                title="Save cover", defaultextension=ext,
                filetypes=[("Image", "*" + ext), ("All files", "*.*")])
            if not dest:
                return
            try:
                with open(dest, "wb") as fh:
                    fh.write(data)
                self._show_ok(f"Saved cover → {dest}")
            except OSError as exc:
                self._show_error(f"Could not save: {exc}")

        def _te_apply_now(self):
            sel = self._selected_tracks()
            if not sel:
                self._show_error("Select one or more tracks in the Library first.")
                return
            fields = {f: self._te_vars[f].get() for f in UNIFIED_FIELDS
                      if self._te_apply[f].get()}
            cover = self._pending_cover
            if not fields and not cover:
                self._show_error("Tick at least one field, or stage a cover image.")
                return
            if not messagebox.askyesno(
                    "Apply tags",
                    f"Write {len(fields)} field(s)"
                    + (" + cover" if cover else "")
                    + f" to {len(sel)} file(s)?"):
                return
            paths = [t["path"] for t in sel]

            def work():
                for path in paths:
                    if fields:
                        tagsmod.write_tags(path, fields)
                    if cover:
                        tagsmod.write_cover(path, cover[0], cover[1])
                return len(paths)

            def done(n):
                self._rescan_current_tracks(paths)
                self._show_ok(f"Updated {n} file(s).")
            self._bg(work, done, busy="Writing tags…")

        def _rescan_current_tracks(self, paths):
            paths = set(paths)
            for i, t in enumerate(self._tracks):
                if t["path"] in paths:
                    try:
                        self._tracks[i] = librarymod.read_track(t["path"])
                    except Exception:
                        pass
            self._refresh_lib_table()

        # =====================================================================
        # Auto-Tag
        # =====================================================================
        def _panel_autotag(self, parent):
            self._at_folder = PathRow(parent, "Folder", mode="dir")
            self._at_folder.pack(fill="x", pady=4)
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="Pattern", width=14, anchor="w").pack(side="left")
            self._at_pattern = tk.StringVar(value="{artist} - {title}")
            ttk.Entry(row, textvariable=self._at_pattern).pack(
                side="left", fill="x", expand=True)
            opts = ttk.Frame(parent, style="TFrame")
            opts.pack(fill="x", pady=2)
            self._at_only_missing = tk.BooleanVar(value=True)
            self._at_use_folder = tk.BooleanVar(value=False)
            ttk.Checkbutton(opts, text="Only fill missing tags",
                            variable=self._at_only_missing).pack(side="left")
            ttk.Checkbutton(opts, text="Match parent folder too",
                            variable=self._at_use_folder).pack(side="left", padx=12)
            ttk.Label(parent, style="Muted.TLabel",
                      text="Fields: {title} {artist} {album} {albumartist} "
                           "{track} {disc} {year} {genre} {comment}").pack(
                anchor="w", pady=(2, 6))
            btns = ttk.Frame(parent, style="TFrame")
            btns.pack(fill="x")
            ttk.Button(btns, text="Preview", style="Accent.TButton",
                       command=self._at_preview).pack(side="left")
            self._at_apply_btn = ttk.Button(btns, text="Apply changes",
                                            command=self._at_apply)
            self._at_apply_btn.pack(side="left", padx=6)
            self._at_tree = self._make_table(
                parent, [("file", "File", 260), ("changes", "Would set", 520)],
                height=13)

        def _at_preview(self):
            folder = self._at_folder.get()
            if not folder:
                self._show_error("Choose a folder.")
                return
            pattern = self._at_pattern.get()

            def work():
                paths = librarymod.find_audio_files(folder)
                return autotagmod.plan_autotag(
                    paths, pattern, only_missing=self._at_only_missing.get(),
                    use_folder=self._at_use_folder.get())

            def done(plan):
                self._autotag_plan = plan
                self._at_tree.delete(*self._at_tree.get_children())
                nchg = 0
                for entry in plan:
                    if not entry["changes"]:
                        continue
                    nchg += 1
                    desc = ", ".join(f"{k}={v}" for k, v in entry["changes"].items())
                    self._at_tree.insert("", "end",
                                         values=[os.path.basename(entry["path"]), desc])
                self._show_ok(f"{nchg} of {len(plan)} file(s) would change "
                              f"(preview only).")
            self._bg(work, done, busy="Matching…")

        def _at_apply(self):
            if not self._autotag_plan:
                self._show_error("Preview first, then apply.")
                return
            n = sum(1 for e in self._autotag_plan if e["changes"])
            if not n:
                self._show_error("Nothing to apply.")
                return
            if not messagebox.askyesno("Apply auto-tags",
                                       f"Write inferred tags to {n} file(s)?"):
                return
            plan = self._autotag_plan

            def done(count):
                self._show_ok(f"Auto-tagged {count} file(s).")
                self._autotag_plan = []
                self._at_tree.delete(*self._at_tree.get_children())
            self._bg(lambda: autotagmod.apply_autotag(plan), done,
                     button=self._at_apply_btn, busy="Writing tags…")

        # =====================================================================
        # Rename / Organize
        # =====================================================================
        def _panel_organize(self, parent):
            self._org_folder = PathRow(parent, "Source folder", mode="dir")
            self._org_folder.pack(fill="x", pady=4)
            self._org_dest = PathRow(parent, "Destination", mode="dir")
            self._org_dest.pack(fill="x", pady=4)
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="Pattern", width=14, anchor="w").pack(side="left")
            self._org_pattern = tk.StringVar(
                value="{albumartist}/{album}/{track:02d} - {title}")
            ttk.Entry(row, textvariable=self._org_pattern).pack(
                side="left", fill="x", expand=True)
            opts = ttk.Frame(parent, style="TFrame")
            opts.pack(fill="x", pady=2)
            self._org_copy = tk.BooleanVar(value=True)
            ttk.Checkbutton(opts, text="Copy (leave originals in place)",
                            variable=self._org_copy).pack(side="left")
            ttk.Label(parent, style="Muted.TLabel",
                      text="Use '/' for subfolders and specs like {track:02d}. "
                           "Leave Destination blank to rename in place.").pack(
                anchor="w", pady=(2, 6))
            btns = ttk.Frame(parent, style="TFrame")
            btns.pack(fill="x")
            ttk.Button(btns, text="Preview", style="Accent.TButton",
                       command=self._org_preview).pack(side="left")
            self._org_apply_btn = ttk.Button(btns, text="Apply",
                                             command=self._org_apply)
            self._org_apply_btn.pack(side="left", padx=6)
            self._org_tree = self._make_table(
                parent, [("src", "From", 320), ("target", "To", 460)], height=13)

        def _org_preview(self):
            folder = self._org_folder.get()
            if not folder:
                self._show_error("Choose a source folder.")
                return
            pattern = self._org_pattern.get()
            dest = self._org_dest.get()

            def work():
                tracks = librarymod.scan_folder(folder)
                return organizemod.plan_rename(tracks, pattern, dest_root=dest)

            def done(plan):
                self._organize_plan = plan
                self._org_tree.delete(*self._org_tree.get_children())
                for entry in plan:
                    self._org_tree.insert(
                        "", "end",
                        values=[os.path.basename(entry["src"]), entry["target"]])
                self._show_ok(f"{len(plan)} file(s) planned (preview only).")
            self._bg(work, done, busy="Planning…")

        def _org_apply(self):
            if not self._organize_plan:
                self._show_error("Preview first, then apply.")
                return
            copy = self._org_copy.get()
            verb = "Copy" if copy else "Move"
            if not messagebox.askyesno(
                    f"{verb} files",
                    f"{verb} {len(self._organize_plan)} file(s) to their new "
                    f"locations?" + ("" if copy else "\n\nOriginals will be MOVED.")):
                return
            plan = self._organize_plan

            def done(written):
                self._show_ok(f"{verb}d {len(written)} file(s).")
                self._organize_plan = []
                self._org_tree.delete(*self._org_tree.get_children())
            self._bg(lambda: organizemod.apply_plan(plan, copy=copy), done,
                     button=self._org_apply_btn, busy=f"{verb}ing files…")

        # =====================================================================
        # Duplicates
        # =====================================================================
        def _panel_duplicates(self, parent):
            self._dup_folder = PathRow(parent, "Folder", mode="dir")
            self._dup_folder.pack(fill="x", pady=4)
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="Match by", width=14, anchor="w").pack(side="left")
            self._dup_by = tk.StringVar(value="tags")
            ttk.Combobox(row, textvariable=self._dup_by, state="readonly", width=10,
                         values=["tags", "hash", "both"]).pack(side="left")
            ttk.Button(row, text="Find duplicates", style="Accent.TButton",
                       command=self._dup_find).pack(side="left", padx=10)
            self._dup_tree = ttk.Treeview(
                parent, columns=["path", "time"], show="tree headings",
                selectmode="extended", height=15)
            self._dup_tree.heading("#0", text="Group")
            self._dup_tree.heading("path", text="Path")
            self._dup_tree.heading("time", text="Time")
            self._dup_tree.column("#0", width=180, stretch=False)
            self._dup_tree.column("path", width=520, stretch=False)
            self._dup_tree.column("time", width=70, stretch=False)
            sb = ttk.Scrollbar(parent, orient="vertical",
                               command=self._dup_tree.yview)
            self._dup_tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._dup_tree.pack(fill="both", expand=True, pady=(6, 0))
            actions = ttk.Frame(parent, style="TFrame")
            actions.pack(fill="x", pady=(6, 0))
            ttk.Button(actions, text="Delete selected files",
                       style="Danger.TButton",
                       command=self._dup_delete).pack(side="left")
            ttk.Label(actions, style="Muted.TLabel",
                      text="  Select the copies to remove (keeps whatever you "
                           "don't select). Deletion is permanent.").pack(side="left")

        def _dup_find(self):
            folder = self._dup_folder.get()
            if not folder:
                self._show_error("Choose a folder.")
                return
            by = self._dup_by.get()

            def work():
                return dedupemod.find_duplicates_in_folder(folder, by=by)

            def done(groups):
                self._dupe_groups = groups
                self._dup_tree.delete(*self._dup_tree.get_children())
                for i, group in enumerate(groups, 1):
                    head = group[0]
                    label = f"{head.get('artist', '')} - {head.get('title', '')}"
                    parent_iid = self._dup_tree.insert(
                        "", "end", text=f"Group {i}: {label.strip(' -') or '(untitled)'}",
                        open=True, values=["", ""])
                    for t in group:
                        self._dup_tree.insert(parent_iid, "end", text="",
                                              values=[t["path"], t.get("duration_str", "")])
                stats = dedupemod.summarize(groups)
                self._show_ok(f"{stats['groups']} group(s), "
                              f"{stats['duplicates']} redundant copy/copies.")
            self._bg(work, done, busy="Hashing…" if by != "tags" else "Comparing…")

        def _dup_delete(self):
            paths = []
            for iid in self._dup_tree.selection():
                vals = self._dup_tree.item(iid, "values")
                if vals and vals[0]:
                    paths.append(vals[0])
            if not paths:
                self._show_error("Select the file rows you want to delete.")
                return
            if not messagebox.askyesno(
                    "Delete files",
                    f"Permanently delete {len(paths)} file(s) from disk?"):
                return

            def work():
                removed = 0
                for p in paths:
                    try:
                        os.remove(p)
                        removed += 1
                    except OSError as exc:
                        raise MusicKitError(f"could not delete {p}: {exc}")
                return removed

            def done(n):
                self._show_ok(f"Deleted {n} file(s).")
                self._dup_find()
            self._bg(work, done, busy="Deleting…")

    return App


def main():
    """Entry point: build the root window and run.  Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display (e.g. a server), it prints a friendly note and returns 0
    instead of raising.
    """
    try:
        import tkinter as tk
    except Exception as exc:
        print(f"{APP_NAME}: a graphical environment with tkinter is required "
              f"to run the GUI ({exc}).")
        return 0

    try:
        App = build_app()
        app = App()
    except tk.TclError as exc:
        print(f"{APP_NAME}: no graphical display available — cannot start the "
              f"GUI here ({exc}). This app is intended for the Windows desktop.")
        return 0
    except Exception as exc:
        print(f"{APP_NAME}: could not start the GUI ({exc}).")
        return 1

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
