"""plan_rename / render_pattern -- pure, file-free path logic."""

import os

import pytest

from musickit import (
    MusicKitError, render_pattern, plan_rename, sanitize_component, apply_plan,
)


def _track(path, **fields):
    base = {"path": path, "title": "", "artist": "", "album": "",
            "albumartist": "", "track": "", "disc": "", "year": "",
            "genre": "", "comment": ""}
    base.update(fields)
    return base


def test_render_simple():
    t = _track("x.mp3", artist="Nova", title="Drift")
    assert render_pattern(t, "{artist} - {title}") == "Nova - Drift"


def test_render_zero_padded_track():
    t = _track("x.mp3", track="3", title="Drift")
    assert render_pattern(t, "{track:02d} {title}") == "03 Drift"


def test_render_track_with_total():
    t = _track("x.mp3", track="3/12", title="Drift")
    assert render_pattern(t, "{track:02d}") == "03"


def test_render_missing_text_field_is_unknown():
    t = _track("x.mp3", title="Drift")
    assert render_pattern(t, "{artist}/{title}") == "Unknown/Drift"


def test_render_unknown_field_rejected():
    with pytest.raises(MusicKitError):
        render_pattern(_track("x.mp3"), "{nope}")


def test_plan_rename_expected_targets():
    tracks = [
        _track("/in/a.mp3", albumartist="Nova", album="Aurora", track="1", title="One"),
        _track("/in/b.mp3", albumartist="Nova", album="Aurora", track="2", title="Two"),
    ]
    plan = plan_rename(tracks, "{albumartist}/{album}/{track:02d} - {title}",
                       dest_root="/lib")
    assert plan[0]["target"] == os.path.join(
        "/lib", "Nova", "Aurora", "01 - One.mp3")
    assert plan[1]["target"] == os.path.join(
        "/lib", "Nova", "Aurora", "02 - Two.mp3")


def test_plan_rename_collision_suffix():
    tracks = [
        _track("/in/a.mp3", artist="Nova", title="Same"),
        _track("/in/b.mp3", artist="Nova", title="Same"),
    ]
    plan = plan_rename(tracks, "{artist} - {title}", dest_root="/lib")
    assert plan[0]["target"] == os.path.join("/lib", "Nova - Same.mp3")
    assert plan[1]["target"] == os.path.join("/lib", "Nova - Same (2).mp3")


def test_plan_rename_preserves_extension():
    plan = plan_rename([_track("/in/song.FLAC", title="X")], "{title}", dest_root="/lib")
    assert plan[0]["target"].endswith(".FLAC")


def test_sanitize_strips_illegal():
    assert "/" not in sanitize_component("AC/DC")
    assert ":" not in sanitize_component("a:b")
    assert sanitize_component("   ") == "Unknown"


def test_apply_plan_moves_real_file(flac_file, tmp_path):
    from musickit import write_tags
    write_tags(flac_file, {"artist": "Nova", "title": "Drift"})
    dest = str(tmp_path / "out")
    plan = plan_rename([flac_file], "{artist} - {title}", dest_root=dest)
    written = apply_plan(plan, copy=False)
    assert len(written) == 1
    assert os.path.exists(written[0])
    assert os.path.basename(written[0]) == "Nova - Drift.flac"
    assert not os.path.exists(flac_file)


def test_apply_plan_copy_keeps_original(flac_file, tmp_path):
    from musickit import write_tags
    write_tags(flac_file, {"artist": "Nova", "title": "Keep"})
    dest = str(tmp_path / "out")
    plan = plan_rename([flac_file], "{artist} - {title}", dest_root=dest)
    written = apply_plan(plan, copy=True)
    assert os.path.exists(flac_file)
    assert os.path.exists(written[0])
