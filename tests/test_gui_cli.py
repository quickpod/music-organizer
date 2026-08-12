"""GUI import is side-effect-free / headless-safe, and the CLI exits cleanly."""

import os

from musickit import __main__ as cli


def test_gui_import_side_effect_free():
    from musickit import gui
    assert hasattr(gui, "main")
    assert callable(gui.main)


def test_gui_main_headless_returns_zero(monkeypatch):
    # No $DISPLAY -> should print a note and return 0, never raise.
    monkeypatch.delenv("DISPLAY", raising=False)
    from musickit import gui
    assert gui.main() == 0


def test_cli_read_write_roundtrip(flac_file, capsys):
    rc = cli.main(["write", flac_file, "--artist", "Nova", "--title", "Drift"])
    assert rc == 0
    rc = cli.main(["read", flac_file])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Nova" in out and "Drift" in out


def test_cli_error_clean_exit(capsys):
    rc = cli.main(["read", "/no/such/file.flac"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")


def test_cli_organize_preview(make_flac, tmp_path, capsys):
    from musickit import write_tags
    a = make_flac("a.flac")
    write_tags(a, {"albumartist": "Nova", "album": "Aurora",
                   "track": "1", "title": "One"})
    rc = cli.main(["organize", str(tmp_path), "--pattern",
                   "{albumartist}/{album}/{track:02d} - {title}",
                   "--dest", str(tmp_path / "lib"), "--preview"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "01 - One.flac" in out
    # preview must not have moved anything
    assert os.path.exists(a)
