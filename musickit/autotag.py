"""Fill missing tags from the file's name/folder using a placeholder pattern.

Entirely **offline** -- no online lookups, ever.  A pattern such as::

    {artist} - {album} - {track} {title}

is compiled into a regex, matched against the filename (and optionally the
parent folder path), and the captured groups become tag values.  Values are
tidied (whitespace collapsed, underscores -> spaces, gentle title-casing) and a
track number is guessed from a leading number when the pattern omits one.
"""

from __future__ import annotations

import os
import re

from .errors import MusicKitError
from . import tags as _tags

# Fields a pattern may reference.  ``track``/``disc``/``year`` are numeric-ish.
PATTERN_FIELDS = set(_tags.UNIFIED_FIELDS)

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_]+)\}")

# Words kept lower-case in title mode unless first/last.
_SMALL_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of",
    "on", "or", "the", "to", "vs", "via", "with",
}


def _group_pattern(field):
    # Numeric fields grab digits only; the rest grab as little as possible.
    if field in ("track", "disc", "year"):
        return r"(?P<%s>\d+)" % field
    return r"(?P<%s>.+?)" % field


def compile_pattern(pattern):
    """Compile a placeholder *pattern* into an anchored ``re.Pattern``.

    Raises :class:`MusicKitError` for an empty pattern, an unknown ``{field}``,
    or a duplicated field.
    """
    if not pattern or not pattern.strip():
        raise MusicKitError("empty auto-tag pattern")
    seen = []
    regex = []
    last = 0
    for m in _PLACEHOLDER.finditer(pattern):
        regex.append(re.escape(pattern[last:m.start()]))
        field = m.group(1)
        if field not in PATTERN_FIELDS:
            raise MusicKitError(
                f"unknown pattern field '{{{field}}}' "
                f"(valid: {', '.join(sorted(PATTERN_FIELDS))})")
        if field in seen:
            raise MusicKitError(f"field '{{{field}}}' used more than once")
        seen.append(field)
        regex.append(_group_pattern(field))
        last = m.end()
    regex.append(re.escape(pattern[last:]))
    if not seen:
        raise MusicKitError("pattern contains no {fields}")
    # Allow the final group to run greedily to the end.
    compiled = re.compile(r"^\s*" + "".join(regex) + r"\s*$")
    return compiled


def parse_pattern(text, pattern):
    """Match *text* against *pattern*; return a dict of raw (untidied) fields.

    Returns ``{}`` when the text does not match.  Pure and file-free -- this is
    the testable heart of auto-tagging.
    """
    compiled = compile_pattern(pattern)
    m = compiled.match(text)
    if not m:
        return {}
    return {k: (v if v is not None else "") for k, v in m.groupdict().items()}


def title_case(value):
    """Gentle title-casing that keeps small words lower unless first/last."""
    value = clean_value(value)
    if not value:
        return value
    words = value.split(" ")
    out = []
    for i, w in enumerate(words):
        if not w:
            continue
        low = w.lower()
        if i not in (0, len(words) - 1) and low in _SMALL_WORDS:
            out.append(low)
        elif w.isupper() and len(w) <= 4:
            out.append(w)            # keep acronyms like DNA, USA
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out)


def clean_value(value):
    """Collapse whitespace and turn underscores/dots into spaces."""
    value = str(value or "").replace("_", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def guess_track_number(filename):
    """Return a leading track number in *filename* (e.g. ``"03 - x.mp3"``) or ""."""
    base = os.path.splitext(os.path.basename(filename))[0]
    m = re.match(r"\s*(\d{1,3})\b", base)
    if m:
        return str(int(m.group(1)))
    return ""


def suggest_tags(path, pattern, use_folder=False, do_title_case=True):
    """Return unified tag values inferred for *path* from *pattern*.

    Only the fields the pattern captures are returned (others omitted).  When
    *use_folder* is set the pattern is matched against ``parent/filename`` so
    patterns like ``{artist}/{album}/{track} {title}`` work.
    """
    base = os.path.splitext(os.path.basename(path))[0]
    if use_folder:
        parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
        subject = f"{parent}/{base}" if "/" in pattern or "\\" in pattern else base
    else:
        subject = base
    raw = parse_pattern(subject, pattern)
    if not raw:
        return {}
    fields = {}
    for key, value in raw.items():
        if key in ("track", "disc", "year"):
            fields[key] = str(int(value)) if str(value).isdigit() else clean_value(value)
        elif do_title_case and key in ("title", "artist", "album", "albumartist", "genre"):
            fields[key] = title_case(value)
        else:
            fields[key] = clean_value(value)
    return fields


def plan_autotag(paths, pattern, only_missing=True, use_folder=False):
    """Preview auto-tagging for *paths*.

    Returns a list of dicts: ``{path, matched, current, suggested, changes}``
    where ``changes`` is the subset of ``suggested`` that would actually be
    written (respecting *only_missing*).  Reads current tags but writes nothing.
    """
    plan = []
    for path in paths:
        suggested = suggest_tags(path, pattern, use_folder=use_folder)
        if not suggested and pattern:
            tn = guess_track_number(path)
            suggested = {"track": tn} if tn else {}
        try:
            current = _tags.read_tags(path)
        except MusicKitError:
            current = {f: "" for f in _tags.UNIFIED_FIELDS}
        changes = {}
        for field, value in suggested.items():
            if not value:
                continue
            if only_missing and str(current.get(field, "")).strip():
                continue
            if str(current.get(field, "")) != str(value):
                changes[field] = value
        plan.append({
            "path": os.path.abspath(path),
            "matched": bool(suggested),
            "current": current,
            "suggested": suggested,
            "changes": changes,
        })
    return plan


def apply_autotag(plan):
    """Write the ``changes`` of each entry in *plan*; return the count changed."""
    changed = 0
    for entry in plan:
        changes = entry.get("changes") or {}
        if changes:
            _tags.write_tags(entry["path"], changes)
            changed += 1
    return changed
