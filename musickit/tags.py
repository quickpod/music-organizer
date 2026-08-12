"""Read and write audio tags across formats through one **unified schema**.

Different container/tag formats spell the same idea differently -- ID3's
``TPE2`` is FLAC's ``albumartist`` is MP4's ``aART``.  This module hides that:
every reader returns, and every writer accepts, the same nine fields::

    title  artist  album  albumartist  track  disc  year  genre  comment

Values are always plain strings ("" when absent); ``track``/``disc`` keep any
"n/total" form as-is.  Cover art is handled separately as raw image bytes plus
a MIME type.

Supported today: MP3/WAV/AIFF (ID3), FLAC and Ogg Vorbis/Opus (Vorbis
comments), and M4A/MP4 (iTunes atoms).  Everything raises
:class:`MusicKitError` on failure -- never a bare mutagen exception.
"""

from __future__ import annotations

import os

from .errors import MusicKitError

# The unified field order used everywhere (tables, CLI, GUI).
UNIFIED_FIELDS = (
    "title", "artist", "album", "albumartist",
    "track", "disc", "year", "genre", "comment",
)

# Extension -> tag family.  Kept small and explicit so behaviour is predictable.
ID3_EXTS = {".mp3", ".wav", ".wave", ".aiff", ".aif", ".aifc"}
VORBIS_EXTS = {".flac", ".ogg", ".oga", ".opus", ".spx"}
MP4_EXTS = {".m4a", ".m4b", ".mp4", ".aac"}

AUDIO_EXTS = ID3_EXTS | VORBIS_EXTS | MP4_EXTS


def _ext(path):
    return os.path.splitext(path)[1].lower()


def kind(path):
    """Return the tag family for *path*: ``"id3"``, ``"vorbis"``, ``"mp4"`` or None."""
    e = _ext(path)
    if e in ID3_EXTS:
        return "id3"
    if e in VORBIS_EXTS:
        return "vorbis"
    if e in MP4_EXTS:
        return "mp4"
    return None


def is_audio(path):
    """True if *path* has a recognised audio extension."""
    return _ext(path) in AUDIO_EXTS


def _require_kind(path):
    k = kind(path)
    if k is None:
        raise MusicKitError(f"unsupported audio format: {os.path.basename(path)}")
    if not os.path.exists(path):
        raise MusicKitError(f"file not found: {path}")
    return k


def _empty():
    return {f: "" for f in UNIFIED_FIELDS}


# ---------------------------------------------------------------------------
# ID3 (MP3 / WAV / AIFF)
# ---------------------------------------------------------------------------
_ID3_TEXT = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB",
    "albumartist": "TPE2", "track": "TRCK", "disc": "TPOS",
    "genre": "TCON",
}


def _id3_open(path):
    from mutagen.id3 import ID3, ID3NoHeaderError
    try:
        return ID3(path)
    except ID3NoHeaderError:
        return ID3()
    except Exception as exc:
        raise MusicKitError(f"could not read tags from {os.path.basename(path)}: {exc}")


def _read_id3(path):
    tags = _id3_open(path)
    out = _empty()
    for field, fid in _ID3_TEXT.items():
        frame = tags.get(fid)
        if frame is not None and getattr(frame, "text", None):
            out[field] = str(frame.text[0])
    year = tags.getall("TDRC")
    if year and year[0].text:
        out["year"] = str(year[0].text[0])
    comm = tags.getall("COMM")
    if comm and comm[0].text:
        out["comment"] = str(comm[0].text[0])
    return out


def _write_id3(path, fields):
    from mutagen.id3 import (
        ID3, TIT2, TPE1, TALB, TPE2, TRCK, TPOS, TCON, TDRC, COMM,
    )
    classes = {
        "title": TIT2, "artist": TPE1, "album": TALB, "albumartist": TPE2,
        "track": TRCK, "disc": TPOS, "genre": TCON,
    }
    tags = _id3_open(path)
    for field, value in fields.items():
        value = "" if value is None else str(value)
        if field in classes:
            tags.delall(_ID3_TEXT[field])
            if value:
                tags.add(classes[field](encoding=3, text=[value]))
        elif field == "year":
            tags.delall("TDRC")
            if value:
                tags.add(TDRC(encoding=3, text=[value]))
        elif field == "comment":
            tags.delall("COMM")
            if value:
                tags.add(COMM(encoding=3, lang="eng", desc="", text=[value]))
    try:
        tags.save(path)
    except Exception as exc:
        raise MusicKitError(f"could not write tags to {os.path.basename(path)}: {exc}")


# ---------------------------------------------------------------------------
# Vorbis comments (FLAC / Ogg Vorbis / Opus)
# ---------------------------------------------------------------------------
_VORBIS_MAP = {
    "title": "title", "artist": "artist", "album": "album",
    "albumartist": "albumartist", "track": "tracknumber", "disc": "discnumber",
    "year": "date", "genre": "genre", "comment": "comment",
}


def _vorbis_open(path):
    e = _ext(path)
    try:
        if e == ".flac":
            from mutagen.flac import FLAC
            return FLAC(path)
        if e == ".opus":
            from mutagen.oggopus import OggOpus
            return OggOpus(path)
        if e == ".spx":
            from mutagen.oggspeex import OggSpeex
            return OggSpeex(path)
        from mutagen.oggvorbis import OggVorbis
        return OggVorbis(path)
    except Exception as exc:
        raise MusicKitError(f"could not read {os.path.basename(path)}: {exc}")


def _read_vorbis(path):
    obj = _vorbis_open(path)
    out = _empty()
    for field, key in _VORBIS_MAP.items():
        vals = obj.get(key)
        if vals:
            out[field] = str(vals[0])
    return out


def _write_vorbis(path, fields):
    obj = _vorbis_open(path)
    for field, value in fields.items():
        if field not in _VORBIS_MAP:
            continue
        key = _VORBIS_MAP[field]
        value = "" if value is None else str(value)
        if value:
            obj[key] = [value]
        elif key in obj:
            del obj[key]
    try:
        obj.save()
    except Exception as exc:
        raise MusicKitError(f"could not write tags to {os.path.basename(path)}: {exc}")


# ---------------------------------------------------------------------------
# MP4 / M4A (iTunes atoms)
# ---------------------------------------------------------------------------
_MP4_TEXT = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
    "albumartist": "aART", "year": "\xa9day", "genre": "\xa9gen",
    "comment": "\xa9cmt",
}
_MP4_PAIR = {"track": "trkn", "disc": "disk"}


def _mp4_open(path):
    from mutagen.mp4 import MP4
    try:
        return MP4(path)
    except Exception as exc:
        raise MusicKitError(f"could not read {os.path.basename(path)}: {exc}")


def _read_mp4(path):
    obj = _mp4_open(path)
    out = _empty()
    for field, key in _MP4_TEXT.items():
        vals = obj.get(key)
        if vals:
            out[field] = str(vals[0])
    for field, key in _MP4_PAIR.items():
        vals = obj.get(key)
        if vals:
            num, total = (list(vals[0]) + [0, 0])[:2]
            out[field] = f"{num}/{total}" if total else str(num)
    return out


def _write_mp4(path, fields):
    obj = _mp4_open(path)
    for field, value in fields.items():
        value = "" if value is None else str(value)
        if field in _MP4_TEXT:
            key = _MP4_TEXT[field]
            if value:
                obj[key] = [value]
            elif key in obj:
                del obj[key]
        elif field in _MP4_PAIR:
            key = _MP4_PAIR[field]
            if value:
                num, total = _split_pair(value)
                obj[key] = [(num, total)]
            elif key in obj:
                del obj[key]
    try:
        obj.save()
    except Exception as exc:
        raise MusicKitError(f"could not write tags to {os.path.basename(path)}: {exc}")


def _split_pair(value):
    """Parse a "n/total" (or "n") string into an ``(n, total)`` int pair."""
    parts = str(value).split("/")
    try:
        num = int(parts[0]) if parts[0].strip() else 0
    except ValueError:
        num = 0
    total = 0
    if len(parts) > 1:
        try:
            total = int(parts[1]) if parts[1].strip() else 0
        except ValueError:
            total = 0
    return num, total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def read_tags(path):
    """Return the unified tag dict for *path* (all nine keys always present)."""
    k = _require_kind(path)
    if k == "id3":
        return _read_id3(path)
    if k == "vorbis":
        return _read_vorbis(path)
    return _read_mp4(path)


def write_tags(path, fields):
    """Write *fields* (a subset of :data:`UNIFIED_FIELDS`) to *path*.

    A field mapped to a non-empty value is set; a field mapped to ``""``/``None``
    is removed.  Fields not present in *fields* are left untouched.  Returns the
    fresh tag dict after writing.
    """
    if not isinstance(fields, dict):
        raise MusicKitError("fields must be a mapping of field name -> value")
    unknown = set(fields) - set(UNIFIED_FIELDS)
    if unknown:
        raise MusicKitError(f"unknown tag field(s): {', '.join(sorted(unknown))}")
    k = _require_kind(path)
    if k == "id3":
        _write_id3(path, fields)
    elif k == "vorbis":
        _write_vorbis(path, fields)
    else:
        _write_mp4(path, fields)
    return read_tags(path)


def read_cover(path):
    """Return ``(image_bytes, mime)`` for the embedded cover, or ``(None, None)``."""
    k = _require_kind(path)
    try:
        if k == "id3":
            tags = _id3_open(path)
            pics = tags.getall("APIC")
            if pics:
                return bytes(pics[0].data), pics[0].mime or "image/jpeg"
        elif k == "vorbis":
            obj = _vorbis_open(path)
            pics = _vorbis_pictures(obj)
            if pics:
                return bytes(pics[0].data), pics[0].mime or "image/jpeg"
        else:
            obj = _mp4_open(path)
            covers = obj.get("covr")
            if covers:
                from mutagen.mp4 import MP4Cover
                fmt = getattr(covers[0], "imageformat", MP4Cover.FORMAT_JPEG)
                mime = "image/png" if fmt == MP4Cover.FORMAT_PNG else "image/jpeg"
                return bytes(covers[0]), mime
    except MusicKitError:
        raise
    except Exception as exc:
        raise MusicKitError(f"could not read cover from {os.path.basename(path)}: {exc}")
    return None, None


def _vorbis_pictures(obj):
    """Return embedded pictures for a FLAC or Ogg object (normalised list)."""
    if hasattr(obj, "pictures"):          # FLAC
        return list(obj.pictures)
    from mutagen.flac import Picture
    import base64
    out = []
    for b64 in obj.get("metadata_block_picture", []):
        try:
            out.append(Picture(base64.b64decode(b64)))
        except Exception:
            pass
    return out


def write_cover(path, image_bytes, mime="image/jpeg"):
    """Embed *image_bytes* (front cover) into *path*; replaces any existing art."""
    k = _require_kind(path)
    if not image_bytes:
        raise MusicKitError("no image data provided for cover art")
    try:
        if k == "id3":
            from mutagen.id3 import APIC
            tags = _id3_open(path)
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover",
                          data=bytes(image_bytes)))
            tags.save(path)
        elif k == "vorbis":
            _write_vorbis_cover(path, image_bytes, mime)
        else:
            from mutagen.mp4 import MP4Cover
            obj = _mp4_open(path)
            fmt = (MP4Cover.FORMAT_PNG if "png" in (mime or "").lower()
                   else MP4Cover.FORMAT_JPEG)
            obj["covr"] = [MP4Cover(bytes(image_bytes), imageformat=fmt)]
            obj.save()
    except MusicKitError:
        raise
    except Exception as exc:
        raise MusicKitError(f"could not write cover to {os.path.basename(path)}: {exc}")


def _write_vorbis_cover(path, image_bytes, mime):
    from mutagen.flac import Picture
    pic = Picture()
    pic.type = 3          # front cover
    pic.mime = mime or "image/jpeg"
    pic.desc = "Cover"
    pic.data = bytes(image_bytes)
    obj = _vorbis_open(path)
    if hasattr(obj, "clear_pictures"):     # FLAC
        obj.clear_pictures()
        obj.add_picture(pic)
    else:                                  # Ogg: base64 in a comment
        import base64
        obj["metadata_block_picture"] = [
            base64.b64encode(pic.write()).decode("ascii")]
    obj.save()


def read_audio_info(path):
    """Return ``{"length": seconds, "bitrate": bps, "sample_rate": hz}``.

    Best-effort: unknown values come back as ``0``.  Raises
    :class:`MusicKitError` only if the file cannot be opened at all.
    """
    _require_kind(path)
    from mutagen import File as MFile
    try:
        obj = MFile(path)
    except Exception as exc:
        raise MusicKitError(f"could not read {os.path.basename(path)}: {exc}")
    if obj is None or getattr(obj, "info", None) is None:
        return {"length": 0.0, "bitrate": 0, "sample_rate": 0}
    info = obj.info
    return {
        "length": float(getattr(info, "length", 0.0) or 0.0),
        "bitrate": int(getattr(info, "bitrate", 0) or 0),
        "sample_rate": int(getattr(info, "sample_rate", 0) or 0),
    }
