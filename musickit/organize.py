"""Rename/organise files into a tag-based folder tree -- preview then apply.

``plan_rename`` is **pure**: give it track dicts and a pattern like
``{albumartist}/{album}/{track:02d} - {title}`` and it returns the source ->
target mapping, with filesystem-unsafe characters sanitised and name
collisions resolved by a `` (2)`` suffix.  ``apply_plan`` then performs the
moves/copies, creating directories and refusing to clobber existing files.
"""

from __future__ import annotations

import os
import shutil
import string

from .errors import MusicKitError
from . import tags as _tags

_FORMATTER = string.Formatter()
_NUMERIC = {"track", "disc", "year"}
_ILLEGAL = '<>:"|?*\0'


def sanitize_component(name):
    """Make *name* safe as a single path component (no separators)."""
    name = str(name or "")
    out = []
    for ch in name:
        if ch in _ILLEGAL or ord(ch) < 32:
            out.append("_")
        elif ch in "/\\":
            out.append("-")
        else:
            out.append(ch)
    cleaned = "".join(out).strip().strip(".")
    cleaned = " ".join(cleaned.split())
    # Reserved Windows device names.
    if cleaned.upper() in {"CON", "PRN", "AUX", "NUL"} or \
            cleaned.upper().rstrip("0123456789") in {"COM", "LPT"} and cleaned[-1:].isdigit():
        cleaned = "_" + cleaned
    return cleaned or "Unknown"


def _field_value(fields, name, spec):
    raw = fields.get(name, "")
    if name in _NUMERIC or (spec and (spec.endswith("d") or "d" in spec)):
        try:
            return int(str(raw).split("/")[0].strip())
        except (ValueError, AttributeError):
            return 0
    text = str(raw).strip()
    return text or "Unknown"


def render_pattern(fields, pattern):
    """Render *pattern* using *fields* -- honours format specs like ``{track:02d}``.

    Missing text fields become ``"Unknown"``; missing numeric fields become 0.
    ``/`` in the pattern is preserved as a subfolder separator.  Returns a
    relative path string (no extension).
    """
    if not pattern or not pattern.strip():
        raise MusicKitError("empty rename pattern")
    parts = []
    try:
        for literal, field, spec, _conv in _FORMATTER.parse(pattern):
            parts.append(literal)
            if field is None:
                continue
            base = field.split(".")[0].split("[")[0]
            if base not in _tags.UNIFIED_FIELDS:
                raise MusicKitError(
                    f"unknown pattern field '{{{field}}}' "
                    f"(valid: {', '.join(_tags.UNIFIED_FIELDS)})")
            value = _field_value(fields, base, spec)
            try:
                parts.append(format(value, spec or ""))
            except (ValueError, TypeError) as exc:
                raise MusicKitError(f"bad format spec '{{{field}:{spec}}}': {exc}")
    except MusicKitError:
        raise
    except Exception as exc:
        raise MusicKitError(f"invalid rename pattern: {exc}")
    rendered = "".join(parts)
    rendered = rendered.replace("\\", "/")
    components = [sanitize_component(c) for c in rendered.split("/") if c.strip()]
    if not components:
        raise MusicKitError("pattern produced an empty path")
    return "/".join(components)


def _as_fields(track):
    """Accept either a full track dict or a path string; return a tag dict + path."""
    if isinstance(track, str):
        return _tags.read_tags(track), track
    if isinstance(track, dict):
        path = track.get("path", "")
        fields = {f: track.get(f, "") for f in _tags.UNIFIED_FIELDS}
        return fields, path
    raise MusicKitError("each track must be a path string or a tag dict")


def plan_rename(tracks, pattern, dest_root=""):
    """Return a rename/organise plan for *tracks* (pure; no filesystem writes).

    Each entry: ``{src, target, rel}``.  ``target`` is joined onto *dest_root*
    (default: relative).  The source file's extension is preserved.  Duplicate
    targets get a `` (2)``, `` (3)`` suffix so no two rows collide.
    """
    plan = []
    used = {}
    for track in tracks:
        fields, src = _as_fields(track)
        rel = render_pattern(fields, pattern)
        ext = os.path.splitext(src)[1] if src else ""
        rel_with_ext = rel + ext
        target = os.path.join(dest_root, *rel_with_ext.split("/")) if dest_root \
            else os.path.normpath(rel_with_ext.replace("/", os.sep))
        target = _dedupe_target(target, used)
        plan.append({"src": src, "target": target, "rel": rel_with_ext})
    return plan


def _dedupe_target(target, used):
    key = os.path.normcase(os.path.abspath(target)) if os.path.isabs(target) \
        else os.path.normcase(target)
    if key not in used:
        used[key] = 1
        return target
    used[key] += 1
    root, ext = os.path.splitext(target)
    while True:
        candidate = f"{root} ({used[key]}){ext}"
        ck = os.path.normcase(os.path.abspath(candidate)) if os.path.isabs(candidate) \
            else os.path.normcase(candidate)
        if ck not in used:
            used[ck] = 1
            return candidate
        used[key] += 1


def apply_plan(plan, copy=False, overwrite=False, progress=None):
    """Execute a *plan* from :func:`plan_rename` (move by default, or *copy*).

    Creates parent directories, skips no-op rows where src == target, and
    refuses to overwrite an existing different file unless *overwrite*.  Returns
    a list of the ``target`` paths actually written.
    """
    written = []
    total = len(plan)
    for i, entry in enumerate(plan, 1):
        src, target = entry.get("src"), entry.get("target")
        if not src:
            raise MusicKitError("plan entry has no source path (need real files to apply)")
        if not os.path.exists(src):
            raise MusicKitError(f"source no longer exists: {src}")
        if os.path.abspath(src) == os.path.abspath(target):
            if progress:
                _safe_progress(progress, i, total, target)
            continue
        parent = os.path.dirname(os.path.abspath(target))
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.exists(target) and not overwrite:
            if os.path.abspath(target) != os.path.abspath(src):
                raise MusicKitError(f"target already exists: {target}")
        try:
            if copy:
                shutil.copy2(src, target)
            else:
                shutil.move(src, target)
        except OSError as exc:
            raise MusicKitError(f"could not place {os.path.basename(src)}: {exc}")
        written.append(target)
        if progress:
            _safe_progress(progress, i, total, target)
    return written


def _safe_progress(progress, i, total, path):
    try:
        progress(i, total, path)
    except Exception:
        pass
