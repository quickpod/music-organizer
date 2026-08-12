#!/usr/bin/env python3
r"""MusicOrganizer -- an Aura (QuickOpen design system) GUI on the ``musickit`` API.

A single Aura window: a sidebar of sections (Library, Tag Editor, Auto-Tag,
Rename / Organize, Duplicates, About) and a swappable main panel.  Every
operation calls the tested core library (never re-implements tag logic) and
long scans run on a background thread so the UI stays responsive; results
marshal back with ``self.after`` and are reported in the Aura status bar --
never a raw traceback (a :class:`MusicKitError` message instead).

Design goals baked in here (mirrors the QuickOpen house style):
  * built on the vendored ``musickit/aura.py`` design system, which layers the
    quickopen.ai look (deep space + light) over CustomTkinter.  Runtime deps:
    ``customtkinter`` (+ ``darkdetect``) -- declared in requirements.txt; the
    PyInstaller build adds ``--collect-all customtkinter``.
  * Importing this module does nothing.  Only :func:`main` builds a root
    window, and it degrades gracefully (prints a note, returns 0) with no
    display or with customtkinter missing.
  * Frozen-exe safe: bundled assets resolve via ``sys._MEIPASS`` / the exe
    directory when ``sys.frozen`` is set -- never ``__file__``.
  * Destructive steps (write tags, move files, delete duplicates) always
    confirm with a dialog first; everything else previews before applying.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import threading

# NOTE: tkinter/customtkinter are imported lazily inside main()/build_app so
# that merely importing this module (e.g. during packaging or on a headless CI
# box) never fails.

APP_NAME = "MusicOrganizer"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "MusicOrganizer — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"
ACCENT = "#cf2d3a"      # UI-accent registry (ui/aurakit/README.md §2)

IMAGE_TYPES = [
    ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
    ("All files", "*.*"),
]

# Columns shown in the library table (id, heading, width).
LIB_COLUMNS = [
    ("track", "#", 40),
    ("title", "Title", 175),
    ("artist", "Artist", 135),
    ("album", "Album", 135),
    ("year", "Year", 60),
    ("genre", "Genre", 95),
    ("duration_str", "Time", 56),
    ("bitrate", "kbps", 58),
    ("filename", "File", 130),
]


# ---------------------------------------------------------------------------
# Asset / frozen handling  +  small OS helpers
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
# The app (built lazily; tkinter/customtkinter imported only inside build_app)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to live GUI imports.

    Kept inside a function so this module imports cleanly without a display
    (and without customtkinter installed).
    """
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import customtkinter as ctk

    from . import aura, guiconfig
    from .errors import MusicKitError
    from . import tags as tagsmod
    from . import library as librarymod
    from . import autotag as autotagmod
    from . import dedupe as dedupemod
    from . import organize as organizemod
    from .tags import UNIFIED_FIELDS

    class PathRow(ctk.CTkFrame):
        """A path entry + Browse button (folder or file), Aura-styled."""

        def __init__(self, master, placeholder, mode="dir", filetypes=None,
                     browse_title=None):
            super().__init__(master, fg_color="transparent")
            self.mode = mode
            self.filetypes = filetypes
            self.browse_title = browse_title
            # no textvariable: CTkEntry placeholders only work without one
            self.entry = aura.AuraEntry(self, placeholder=placeholder)
            self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            aura.AuraButton(self, "Browse…", kind="secondary",
                            command=self._browse).pack(side="left")

        def _browse(self):
            if self.mode == "dir":
                p = filedialog.askdirectory(
                    title=self.browse_title or "Choose a folder")
            elif self.mode == "save":
                p = filedialog.asksaveasfilename(
                    title=self.browse_title or "Save as",
                    filetypes=self.filetypes or IMAGE_TYPES)
            else:
                p = filedialog.askopenfilename(
                    title=self.browse_title or "Choose a file",
                    filetypes=self.filetypes or IMAGE_TYPES)
            if p:
                self.set(p)

        def get(self):
            return self.entry.get().strip()

        def set(self, value):
            self.entry.delete(0, "end")
            if value:
                self.entry.insert(0, value)

    class App(aura.AuraApp):
        def __init__(self):
            super().__init__(
                title=WINDOW_TITLE, app_name=APP_NAME, accent=ACCENT,
                theme=guiconfig.get_theme(),
                icon_png=asset_path("music-organizer.png"),
                version=APP_VERSION, tagline="offline tagging",
                on_theme_change=guiconfig.set_theme,
                size=(1160, 720), min_size=(940, 600))

            self._busy = False
            self._img_refs_gui = []        # NOT _img_refs (owned by AuraApp)
            self._tracks = []              # scanned library rows (Library)
            self._lib_iid = {}             # tree iid -> track dict
            self._lib_sort = (None, False)
            self._autotag_plan = []
            self._organize_plan = []
            self._dupe_groups = []
            self._pending_cover = None     # (bytes, mime) staged in Tag Editor

            self._set_icon()
            self._build_menu()
            self.add_section("library", "Library", "♪", self._build_library)
            self.add_section("tageditor", "Tag Editor", "✎",
                             self._build_tageditor)
            self.add_section("autotag", "Auto-Tag", "✳", self._build_autotag)
            self.add_section("organize", "Rename / Organize", "⇄",
                             self._build_organize)
            self.add_section("duplicates", "Duplicates", "⊚",
                             self._build_duplicates)
            self.add_section("about", "About", "◉", self._build_about)
            self.show("library")
            self.set_status("Ready")
            self.protocol("WM_DELETE_WINDOW", self.destroy)

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("music-organizer.ico")
                if ico and os.name == "nt":
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("music-organizer.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs_gui.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- menu (native menus stay; theme lives in the sidebar switch too)
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
            viewm.add_command(
                label="Toggle dark mode",
                command=lambda: self.set_theme(
                    "light" if self.theme == "dark" else "dark"))
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=lambda: self.show("about"))
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
                self.show("library")
                self._scan_into_library(p)

        # ---- background operation runner
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            """Run ``work()`` off the UI thread; call ``on_ok(result)`` back on it.

            Errors are shown in the status bar (MusicKitError message, or a
            generic note), never as a traceback.  Refuses to start a second op
            concurrently.
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
            self.set_status(busy, kind="working")

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
                    self._show_error(err)
                    return
                try:
                    on_ok(res)
                except Exception as ex:
                    self._show_error(f"Post-processing error: {ex}")

            threading.Thread(target=run, daemon=True).start()

        # ---- status helpers (status bar is the voice of the app)
        def _show_error(self, message):
            self.set_error(message)

        def _show_ok(self, message):
            self.set_success(message)

        # =====================================================================
        # Shared table helper
        # =====================================================================
        def _make_table(self, parent, columns, selectmode="extended",
                        sort_cb=None):
            wrap = ctk.CTkFrame(parent, fg_color="transparent")
            wrap.pack(fill="both", expand=True)
            tree = ttk.Treeview(wrap, columns=[c[0] for c in columns],
                                show="headings", selectmode=selectmode)
            for i, (cid, heading, width) in enumerate(columns):
                if sort_cb:
                    tree.heading(cid, text=aura.spaced(heading), anchor="w",
                                 command=lambda c=cid: sort_cb(c))
                else:
                    tree.heading(cid, text=aura.spaced(heading), anchor="w")
                # last column absorbs spare width so tables fill their card
                tree.column(cid, width=width, anchor="w",
                            stretch=(i == len(columns) - 1))
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
        def _build_library(self, frame):
            bar = ctk.CTkFrame(frame, fg_color="transparent")
            bar.pack(fill="x", pady=(0, 8))
            self._lib_folder = PathRow(bar, "Music folder to scan…",
                                       browse_title="Scan a music folder")
            self._lib_folder.pack(side="left", fill="x", expand=True,
                                  padx=(0, 8))
            aura.AuraButton(bar, "Scan", command=self._do_scan).pack(
                side="left")

            ctrl = ctk.CTkFrame(frame, fg_color="transparent")
            ctrl.pack(fill="x", pady=(0, 10))
            self._lib_filter = aura.AuraEntry(
                ctrl, placeholder="Filter — title, artist, album…", width=300)
            self._lib_filter.pack(side="left")
            self._lib_filter.bind("<KeyRelease>",
                                  lambda _e: self._refresh_lib_table())
            aura.AuraButton(ctrl, "Edit selected →", kind="ghost",
                            command=lambda: self.show("tageditor")).pack(
                side="right")

            self._lib_tree = self._make_table(frame, LIB_COLUMNS,
                                              sort_cb=self._sort_library)
            self._lib_count = aura.Caption(frame, "No folder scanned yet.")
            self._lib_count.pack(anchor="w", pady=(8, 0))

        def _do_scan(self):
            folder = self._lib_folder.get()
            if not folder:
                self._show_error("Choose a music folder to scan.")
                return
            self._scan_into_library(folder)

        def _scan_into_library(self, folder):
            self.show("library")
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
            rows = librarymod.search_tracks(self._tracks,
                                            self._lib_filter.get().strip())
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
        def _build_tageditor(self, frame):
            top = ctk.CTkFrame(frame, fg_color="transparent")
            top.pack(fill="x", pady=(0, 10))
            aura.AuraButton(top, "↻ Load from Library selection",
                            kind="secondary",
                            command=self._tageditor_load).pack(side="left")
            self._te_count = aura.Caption(top, "Nothing selected.")
            self._te_count.pack(side="left", padx=12)

            fields_card = aura.Card(frame, title="Fields")
            fields_card.pack(fill="x")
            grid = fields_card.body
            self._te_vars = {}
            self._te_apply = {}
            for i, field in enumerate(UNIFIED_FIELDS):
                chk = tk.BooleanVar(value=False)
                self._te_apply[field] = chk
                ctk.CTkCheckBox(grid, text=field, variable=chk, width=120,
                                font=aura.font()).grid(
                    row=i, column=0, sticky="w", pady=2)
                var = tk.StringVar()
                self._te_vars[field] = var
                # no placeholder here, so a textvariable is safe
                ent = aura.AuraEntry(grid, textvariable=var)
                ent.grid(row=i, column=1, sticky="we", pady=2, padx=(8, 0))
                var.trace_add("write",
                              lambda *_a, f=field: self._te_apply[f].set(True))
            grid.columnconfigure(1, weight=1)
            aura.Caption(frame,
                         "Tick a field to include it when applying. A ticked "
                         "field with empty text CLEARS that tag on every "
                         "selected track.").pack(anchor="w", pady=(8, 10))

            cover = aura.Card(frame, title="Cover art")
            cover.pack(fill="x")
            row = ctk.CTkFrame(cover.body, fg_color="transparent")
            row.pack(fill="x")
            aura.AuraButton(row, "Load image…", kind="secondary",
                            command=self._te_load_cover).pack(side="left")
            aura.AuraButton(row, "Save cover from selection…", kind="secondary",
                            command=self._te_save_cover).pack(
                side="left", padx=8)
            self._te_cover_lbl = aura.Caption(row, "No image staged.")
            self._te_cover_lbl.pack(side="left", padx=12)

            aura.AuraButton(frame, "Apply to selection",
                            command=self._te_apply_now).pack(
                anchor="w", pady=(12, 0))

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
        def _build_autotag(self, frame):
            card = aura.Card(frame, title="Infer tags from filenames")
            card.pack(fill="x", pady=(0, 10))
            self._at_folder = PathRow(card.body, "Folder with audio files…")
            self._at_folder.pack(fill="x", pady=(0, 8))
            row = ctk.CTkFrame(card.body, fg_color="transparent")
            row.pack(fill="x", pady=(0, 8))
            self._at_pattern = tk.StringVar(value="{artist} - {title}")
            aura.AuraEntry(row, textvariable=self._at_pattern, width=340).pack(
                side="left")
            aura.Caption(row, "Pattern").pack(side="left", padx=8)
            opts = ctk.CTkFrame(card.body, fg_color="transparent")
            opts.pack(fill="x", pady=(0, 6))
            self._at_only_missing = tk.BooleanVar(value=True)
            self._at_use_folder = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(opts, text="Only fill missing tags",
                            variable=self._at_only_missing,
                            font=aura.font()).pack(side="left")
            ctk.CTkCheckBox(opts, text="Match parent folder too",
                            variable=self._at_use_folder,
                            font=aura.font()).pack(side="left", padx=14)
            aura.Caption(card.body,
                         "Fields: {title} {artist} {album} {albumartist} "
                         "{track} {disc} {year} {genre} {comment}").pack(
                anchor="w", pady=(0, 8))
            btns = ctk.CTkFrame(card.body, fg_color="transparent")
            btns.pack(fill="x")
            aura.AuraButton(btns, "Preview",
                            command=self._at_preview).pack(side="left")
            self._at_apply_btn = aura.AuraButton(btns, "Apply changes",
                                                 kind="secondary",
                                                 command=self._at_apply)
            self._at_apply_btn.pack(side="left", padx=8)

            self._at_tree = self._make_table(
                frame, [("file", "File", 260), ("changes", "Would set", 520)])

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
        def _build_organize(self, frame):
            card = aura.Card(frame, title="Rename / move by tag pattern")
            card.pack(fill="x", pady=(0, 10))
            self._org_folder = PathRow(card.body, "Source folder…")
            self._org_folder.pack(fill="x", pady=(0, 8))
            self._org_dest = PathRow(
                card.body, "Destination — blank renames in place…")
            self._org_dest.pack(fill="x", pady=(0, 8))
            row = ctk.CTkFrame(card.body, fg_color="transparent")
            row.pack(fill="x", pady=(0, 8))
            self._org_pattern = tk.StringVar(
                value="{albumartist}/{album}/{track:02d} - {title}")
            aura.AuraEntry(row, textvariable=self._org_pattern,
                           width=420).pack(side="left")
            aura.Caption(row, "Pattern").pack(side="left", padx=8)
            opts = ctk.CTkFrame(card.body, fg_color="transparent")
            opts.pack(fill="x", pady=(0, 6))
            self._org_copy = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(opts, text="Copy (leave originals in place)",
                            variable=self._org_copy,
                            font=aura.font()).pack(side="left")
            aura.Caption(card.body,
                         "Use '/' for subfolders and specs like {track:02d}. "
                         "Leave Destination blank to rename in place.").pack(
                anchor="w", pady=(0, 8))
            btns = ctk.CTkFrame(card.body, fg_color="transparent")
            btns.pack(fill="x")
            aura.AuraButton(btns, "Preview",
                            command=self._org_preview).pack(side="left")
            self._org_apply_btn = aura.AuraButton(btns, "Apply",
                                                  kind="secondary",
                                                  command=self._org_apply)
            self._org_apply_btn.pack(side="left", padx=8)

            self._org_tree = self._make_table(
                frame, [("src", "From", 320), ("target", "To", 460)])

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
        def _build_duplicates(self, frame):
            bar = ctk.CTkFrame(frame, fg_color="transparent")
            bar.pack(fill="x", pady=(0, 8))
            self._dup_folder = PathRow(bar, "Folder to check…")
            self._dup_folder.pack(side="left", fill="x", expand=True,
                                  padx=(0, 8))
            self._dup_by = tk.StringVar(value="tags")
            aura.AuraCombo(bar, variable=self._dup_by, state="readonly",
                           width=110,
                           values=["tags", "hash", "both"]).pack(side="left")
            aura.AuraButton(bar, "Find duplicates",
                            command=self._dup_find).pack(
                side="left", padx=(8, 0))

            body = ctk.CTkFrame(frame, fg_color="transparent")
            body.pack(fill="both", expand=True)
            self._dup_tree = ttk.Treeview(
                body, columns=["path", "time"], show="tree headings",
                selectmode="extended")
            self._dup_tree.heading("#0", text=aura.spaced("Group"), anchor="w")
            self._dup_tree.heading("path", text=aura.spaced("Path"), anchor="w")
            self._dup_tree.heading("time", text=aura.spaced("Time"), anchor="w")
            self._dup_tree.column("#0", width=200, stretch=False)
            self._dup_tree.column("path", width=520, stretch=True)
            self._dup_tree.column("time", width=70, stretch=False)
            sb = ttk.Scrollbar(body, orient="vertical",
                               command=self._dup_tree.yview)
            self._dup_tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._dup_tree.pack(side="left", fill="both", expand=True)

            actions = ctk.CTkFrame(frame, fg_color="transparent")
            actions.pack(fill="x", pady=(10, 0))
            aura.AuraButton(actions, "Delete selected files", kind="danger",
                            command=self._dup_delete).pack(side="left")
            aura.Caption(actions,
                         "Select the copies to remove (keeps whatever you "
                         "don't select). Deletion is permanent.").pack(
                side="left", padx=10)

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

        # =====================================================================
        # About
        # =====================================================================
        def _build_about(self, frame):
            card = aura.Card(frame, title="About MusicOrganizer")
            card.pack(fill="x")
            aura.Heading(card.body, APP_NAME).pack(anchor="w")
            aura.Caption(card.body, f"Version {APP_VERSION}").pack(
                anchor="w", pady=(0, 10))
            ctk.CTkLabel(
                card.body, font=aura.font(), justify="left", anchor="w",
                wraplength=520,
                text="A fast, fully-offline music tag & library manager — "
                     "edit tags and cover art, auto-tag from filenames, "
                     "find duplicates and organise by tag patterns.\n\n"
                     "100% AI-built, open source, published on QuickOpen. "
                     "Nothing is ever uploaded anywhere.").pack(anchor="w")
            aura.Caption(card.body,
                         "Licensed under Apache-2.0. Built on mutagen and "
                         "CustomTkinter (MIT).").pack(anchor="w", pady=(10, 4))
            aura.AuraButton(card.body, "Project page: quickopen.ai",
                            kind="ghost",
                            command=lambda: open_with_default_app(
                                PROJECT_URL)).pack(anchor="w", pady=(6, 0))

    return App


def main():
    """Entry point: build the root window and run.  Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display (e.g. a server) or without customtkinter installed, it
    prints a friendly note and returns 0 instead of raising.
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
    except ImportError as exc:
        print(f"{APP_NAME}: the GUI needs the 'customtkinter' package "
              f"({exc}). Install it with:  pip install customtkinter")
        return 0
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
