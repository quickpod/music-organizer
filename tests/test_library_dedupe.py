"""Library scan/search/sort and duplicate detection."""

import os

import pytest

from musickit import (
    scan_folder, search_tracks, sort_tracks, write_tags,
    find_duplicates, tag_signature, content_hash,
)
from musickit.library import duration_str


def _tag(row=None, **kw):
    base = {"path": "", "artist": "", "title": "", "album": "", "duration": 0.0}
    base.update(row or {})
    base.update(kw)
    return base


def test_duration_str():
    assert duration_str(0) == "0:00"
    assert duration_str(65) == "1:05"
    assert duration_str(3661) == "1:01:01"


def test_scan_folder(make_flac, tmp_path):
    a = make_flac("a.flac")
    b = make_flac("b.flac")
    write_tags(a, {"artist": "Nova", "title": "One"})
    write_tags(b, {"artist": "Zed", "title": "Two"})
    tracks = scan_folder(str(tmp_path))
    assert len(tracks) == 2
    titles = sorted(t["title"] for t in tracks)
    assert titles == ["One", "Two"]
    assert all(t["duration"] > 0 for t in tracks)


def test_scan_ignores_non_audio(make_flac, tmp_path):
    make_flac("a.flac")
    (tmp_path / "readme.txt").write_text("hi")
    assert len(scan_folder(str(tmp_path))) == 1


def test_search_tracks():
    tracks = [_tag({}, artist="Nova", title="Drift"),
              _tag({}, artist="Zed", title="Falling")]
    got = search_tracks(tracks, "nova")
    assert len(got) == 1 and got[0]["artist"] == "Nova"


def test_sort_tracks_numeric():
    tracks = [_tag({}, track="10", title="Ten"),
              _tag({}, track="2", title="Two")]
    got = sort_tracks(tracks, "track")
    assert [t["title"] for t in got] == ["Two", "Ten"]


def test_dedupe_by_tags():
    tracks = [
        _tag({}, path="a.mp3", artist="Nova", title="Drift", duration=100.0),
        _tag({}, path="b.flac", artist="NOVA", title="drift", duration=100.4),
        _tag({}, path="c.mp3", artist="Zed", title="Other", duration=50.0),
    ]
    groups = find_duplicates(tracks, by="tags")
    assert len(groups) == 1
    assert {t["path"] for t in groups[0]} == {"a.mp3", "b.flac"}


def test_dedupe_ignores_bracket_suffix():
    a = _tag({}, path="a.mp3", artist="Nova", title="Drift (Remix)", duration=100.0)
    b = _tag({}, path="b.mp3", artist="Nova", title="Drift", duration=100.0)
    assert tag_signature(a) == tag_signature(b)


def test_content_hash_ignores_id3(mp3_file, tmp_path):
    import shutil
    other = str(tmp_path / "copy.mp3")
    shutil.copy(mp3_file, other)
    write_tags(mp3_file, {"title": "Tagged A"})
    write_tags(other, {"title": "Different B"})
    # Same audio payload, different tags -> identical content hash.
    assert content_hash(mp3_file) == content_hash(other)


def test_dedupe_by_hash(mp3_file, tmp_path):
    import shutil
    other = str(tmp_path / "copy.mp3")
    shutil.copy(mp3_file, other)
    write_tags(mp3_file, {"title": "A"})
    write_tags(other, {"title": "B"})
    tracks = scan_folder(str(tmp_path))
    groups = find_duplicates(tracks, by="hash")
    assert len(groups) == 1 and len(groups[0]) == 2
