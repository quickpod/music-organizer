"""Scan a folder of audio files into a searchable, sortable library table.

Each track is a plain ``dict`` with the unified tag fields plus a few derived
columns (``path``, ``filename``, ``ext``, ``duration``, ``duration_str``,
``bitrate``).  Kept as dicts (not a class) so the GUI table, the CLI and the
tests can all treat rows the same way.
"""

from __future__ import annotations

import os

from .errors import MusicKitError
from . import tags as _tags

# Columns the GUI/CLI show, in order.  ``duration``/``bitrate`` are derived.
COLUMNS = (
    "title", "artist", "album", "albumartist", "track", "disc",
    "year", "genre", "duration_str", "bitrate", "filename",
)


def find_audio_files(folder, recursive=True):
    """Return a sorted list of audio file paths under *folder*."""
    if not os.path.isdir(folder):
        raise MusicKitError(f"not a folder: {folder}")
    found = []
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if _tags.is_audio(name):
                    found.append(os.path.join(root, name))
    else:
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            if os.path.isfile(full) and _tags.is_audio(name):
                found.append(full)
    return sorted(found, key=lambda p: p.lower())


def duration_str(seconds):
    """Format a duration in seconds as ``M:SS`` (or ``H:MM:SS``)."""
    seconds = int(round(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def read_track(path):
    """Read one file into a library row dict (tags + derived columns).

    Never raises for a single unreadable file's *tags*; instead the row carries
    an ``error`` key so a scan of a mixed folder is not aborted by one bad file.
    """
    row = {"path": os.path.abspath(path),
           "filename": os.path.basename(path),
           "ext": os.path.splitext(path)[1].lower().lstrip("."),
           "error": ""}
    for field in _tags.UNIFIED_FIELDS:
        row[field] = ""
    row["duration"] = 0.0
    row["duration_str"] = ""
    row["bitrate"] = 0
    try:
        row.update(_tags.read_tags(path))
        info = _tags.read_audio_info(path)
        row["duration"] = info["length"]
        row["duration_str"] = duration_str(info["length"])
        row["bitrate"] = info["bitrate"] // 1000 if info["bitrate"] else 0
    except MusicKitError as exc:
        row["error"] = str(exc)
    return row


def scan_folder(folder, recursive=True, progress=None):
    """Scan *folder* and return a list of track row dicts.

    *progress*, if given, is called as ``progress(done, total, path)`` after each
    file -- handy for a threaded GUI scan.
    """
    paths = find_audio_files(folder, recursive=recursive)
    total = len(paths)
    rows = []
    for i, path in enumerate(paths, 1):
        rows.append(read_track(path))
        if progress:
            try:
                progress(i, total, path)
            except Exception:
                pass
    return rows


def search_tracks(tracks, query):
    """Return the subset of *tracks* matching *query* (case-insensitive substring).

    Matches across title/artist/album/albumartist/genre/filename.
    """
    q = (query or "").strip().lower()
    if not q:
        return list(tracks)
    fields = ("title", "artist", "album", "albumartist", "genre", "filename")
    out = []
    for t in tracks:
        hay = " ".join(str(t.get(f, "")) for f in fields).lower()
        if q in hay:
            out.append(t)
    return out


def filter_tracks(tracks, field, value):
    """Return tracks whose *field* equals *value* (case-insensitive, exact)."""
    if field not in COLUMNS and field not in _tags.UNIFIED_FIELDS:
        raise MusicKitError(f"cannot filter on unknown field: {field}")
    want = (value or "").strip().lower()
    return [t for t in tracks if str(t.get(field, "")).strip().lower() == want]


def _sort_key(field):
    numeric = {"track", "disc", "year", "bitrate", "duration"}

    def key(t):
        raw = t.get("duration") if field == "duration_str" else t.get(field, "")
        if field in numeric or field == "duration_str":
            return (_num(raw), )
        return (str(raw).lower(), )
    return key


def _num(value):
    try:
        return float(str(value).split("/")[0])
    except (ValueError, AttributeError):
        return 0.0


def sort_tracks(tracks, field="artist", reverse=False):
    """Return *tracks* sorted by *field* (numeric-aware for numeric columns)."""
    if field not in COLUMNS and field not in _tags.UNIFIED_FIELDS \
            and field not in ("duration", "path"):
        raise MusicKitError(f"cannot sort on unknown field: {field}")
    return sorted(tracks, key=_sort_key(field), reverse=reverse)
