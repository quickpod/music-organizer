"""Find duplicate tracks by tag signature and/or audio content hash.

Two notions of "duplicate":

* **tag signature** -- normalised ``artist`` + ``title`` (+ rounded duration
  when available).  Catches the same song across different files/formats.
* **content hash** -- a hash of the decoded-ish audio payload (the file with
  its tag blocks skipped where cheap), so re-tagged copies of the *same* file
  still collide.

Both return *groups* (lists of 2+ tracks).  Nothing is deleted here; removal is
the caller's decision.
"""

from __future__ import annotations

import hashlib
import os
import re

from .errors import MusicKitError
from . import tags as _tags
from . import library as _library


def _norm(text):
    text = str(text or "").lower()
    text = re.sub(r"[\(\[].*?[\)\]]", " ", text)      # drop (remix) [live] etc.
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split()).strip()


def tag_signature(track, use_duration=True):
    """Return a normalised ``(artist, title, dur)`` signature, or None if unusable."""
    artist = _norm(track.get("artist") or track.get("albumartist"))
    title = _norm(track.get("title"))
    if not title:
        return None
    dur = ""
    if use_duration and track.get("duration"):
        dur = str(int(round(float(track["duration"]))))
    return (artist, title, dur)


def content_hash(path, chunk=1 << 16):
    """Return a SHA-1 over the file's audio payload (tags excluded where known).

    For MP3 the leading ID3v2 block and trailing ID3v1 tag are skipped so that
    two identically-encoded files with different tags still hash the same.  For
    other formats it falls back to hashing the whole file.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise MusicKitError(f"could not read {os.path.basename(path)}: {exc}")
    start, end = 0, len(data)
    if data[:3] == b"ID3" and len(data) > 10:
        size = data[6:10]
        # ID3v2 size is a 28-bit sync-safe integer.
        total = (size[0] << 21) | (size[1] << 14) | (size[2] << 7) | size[3]
        start = min(10 + total, end)
    if data[-128:-125] == b"TAG":
        end -= 128
    h = hashlib.sha1()
    h.update(data[start:end])
    return h.hexdigest()


def find_duplicates(tracks, by="tags", use_duration=True):
    """Group *tracks* that are duplicates of one another.

    *by* is ``"tags"`` (default), ``"hash"``, or ``"both"`` (must match on both
    signals).  Returns a list of groups, each a list of the original track
    dicts, ordered largest group first.
    """
    if by not in ("tags", "hash", "both"):
        raise MusicKitError("by must be 'tags', 'hash', or 'both'")
    buckets = {}
    for t in tracks:
        key = _key_for(t, by, use_duration)
        if key is None:
            continue
        buckets.setdefault(key, []).append(t)
    groups = [g for g in buckets.values() if len(g) > 1]
    groups.sort(key=len, reverse=True)
    return groups


def _key_for(track, by, use_duration):
    if by == "tags":
        return tag_signature(track, use_duration=use_duration)
    path = track.get("path")
    if not path:
        return None
    if by == "hash":
        return ("h", content_hash(path))
    sig = tag_signature(track, use_duration=use_duration)
    if sig is None:
        return None
    return sig + ("h:" + content_hash(path), )


def find_duplicates_in_folder(folder, by="tags", recursive=True, use_duration=True):
    """Scan *folder* and return duplicate groups (convenience wrapper)."""
    tracks = _library.scan_folder(folder, recursive=recursive)
    return find_duplicates(tracks, by=by, use_duration=use_duration)


def summarize(groups):
    """Return ``{"groups": n, "duplicates": extra_copies}`` for a group list."""
    return {
        "groups": len(groups),
        "duplicates": sum(len(g) - 1 for g in groups),
    }
