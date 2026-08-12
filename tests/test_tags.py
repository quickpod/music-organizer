"""Real-file tag round-trips across the formats we can craft headless."""

import os

import pytest

from musickit import (
    MusicKitError, UNIFIED_FIELDS, read_tags, write_tags,
    read_cover, write_cover, read_audio_info,
)

FULL = {
    "title": "Drift", "artist": "Nova", "album": "Aurora",
    "albumartist": "Nova & Friends", "track": "3", "disc": "1",
    "year": "2021", "genre": "Ambient", "comment": "hello world",
}


def test_flac_roundtrip_all_fields(flac_file):
    write_tags(flac_file, FULL)
    got = read_tags(flac_file)
    for field in UNIFIED_FIELDS:
        assert got[field] == FULL[field], field


def test_wav_id3_roundtrip(wav_file):
    fields = {"title": "Sine", "artist": "Tester", "album": "PCM", "year": "1999"}
    write_tags(wav_file, fields)
    got = read_tags(wav_file)
    for k, v in fields.items():
        assert got[k] == v


def test_mp3_id3_roundtrip(mp3_file):
    write_tags(mp3_file, FULL)
    got = read_tags(mp3_file)
    for field in UNIFIED_FIELDS:
        assert got[field] == FULL[field], field


def test_write_clears_field_with_empty_string(flac_file):
    write_tags(flac_file, {"artist": "Someone"})
    assert read_tags(flac_file)["artist"] == "Someone"
    write_tags(flac_file, {"artist": ""})
    assert read_tags(flac_file)["artist"] == ""


def test_partial_write_leaves_others(flac_file):
    write_tags(flac_file, {"title": "One", "artist": "Two"})
    write_tags(flac_file, {"album": "Three"})
    got = read_tags(flac_file)
    assert got["title"] == "One" and got["artist"] == "Two"
    assert got["album"] == "Three"


def test_unknown_field_rejected(flac_file):
    with pytest.raises(MusicKitError):
        write_tags(flac_file, {"bpm": "120"})


def test_unsupported_format_rejected(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("nope")
    with pytest.raises(MusicKitError):
        read_tags(str(p))


def test_cover_roundtrip_flac(flac_file, tiny_png):
    assert read_cover(flac_file) == (None, None)
    write_cover(flac_file, tiny_png, "image/png")
    data, mime = read_cover(flac_file)
    assert data == tiny_png
    assert mime == "image/png"


def test_cover_roundtrip_mp3(mp3_file, tiny_png):
    write_cover(mp3_file, tiny_png, "image/png")
    data, mime = read_cover(mp3_file)
    assert data == tiny_png
    assert "png" in mime


def test_audio_info(flac_file):
    info = read_audio_info(flac_file)
    assert info["sample_rate"] == 44100
    assert info["length"] == pytest.approx(1.0, abs=0.01)


def test_read_all_keys_present_on_blank(flac_file):
    got = read_tags(flac_file)
    assert set(got) == set(UNIFIED_FIELDS)
    assert all(v == "" for v in got.values())
