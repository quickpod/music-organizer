"""Auto-tag pattern parsing -- mostly pure, plus one real-file apply."""

import pytest

from musickit import (
    MusicKitError, parse_pattern, suggest_tags, title_case,
    guess_track_number, plan_autotag, apply_autotag, read_tags,
)


def test_parse_artist_title():
    got = parse_pattern("Nova - Drift", "{artist} - {title}")
    assert got == {"artist": "Nova", "title": "Drift"}


def test_parse_full_pattern():
    got = parse_pattern("Nova - Aurora - 03 Drift Away",
                        "{artist} - {album} - {track} {title}")
    assert got["artist"] == "Nova"
    assert got["album"] == "Aurora"
    assert got["track"] == "03"
    assert got["title"] == "Drift Away"


def test_parse_no_match_returns_empty():
    assert parse_pattern("no separators here", "{artist} - {title}") == {}


def test_track_only_captures_digits():
    got = parse_pattern("07 Something", "{track} {title}")
    assert got == {"track": "07", "title": "Something"}


def test_unknown_field_rejected():
    with pytest.raises(MusicKitError):
        parse_pattern("x", "{bogus}")


def test_duplicate_field_rejected():
    with pytest.raises(MusicKitError):
        parse_pattern("x", "{title} {title}")


def test_empty_pattern_rejected():
    with pytest.raises(MusicKitError):
        parse_pattern("x", "   ")


def test_title_case_keeps_small_words():
    assert title_case("the lord of the rings") == "The Lord of the Rings"


def test_title_case_underscores():
    assert title_case("hello_world_song") == "Hello World Song"


def test_guess_track_number():
    assert guess_track_number("03 - My Song.mp3") == "3"
    assert guess_track_number("No Number.flac") == ""


def test_suggest_tags_titlecases(tmp_path):
    p = tmp_path / "nova - drift away.flac"
    p.write_bytes(b"")
    got = suggest_tags(str(p), "{artist} - {title}")
    assert got == {"artist": "Nova", "title": "Drift Away"}


def test_suggest_numeric_normalised(tmp_path):
    p = tmp_path / "nova - 007 song.flac"
    p.write_bytes(b"")
    got = suggest_tags(str(p), "{artist} - {track} {title}")
    assert got["track"] == "7"


def test_plan_and_apply_only_missing(flac_file, tmp_path):
    import os
    named = os.path.join(os.path.dirname(flac_file), "Nova - Drift.flac")
    os.rename(flac_file, named)
    plan = plan_autotag([named], "{artist} - {title}", only_missing=True)
    assert plan[0]["changes"] == {"artist": "Nova", "title": "Drift"}
    n = apply_autotag(plan)
    assert n == 1
    got = read_tags(named)
    assert got["artist"] == "Nova" and got["title"] == "Drift"


def test_plan_respects_existing_when_only_missing(flac_file, tmp_path):
    import os
    from musickit import write_tags
    write_tags(flac_file, {"artist": "Keep Me"})
    named = os.path.join(os.path.dirname(flac_file), "Other - Song.flac")
    os.rename(flac_file, named)
    plan = plan_autotag([named], "{artist} - {title}", only_missing=True)
    # artist already present -> not in changes; title was missing -> in changes
    assert "artist" not in plan[0]["changes"]
    assert plan[0]["changes"].get("title") == "Song"
