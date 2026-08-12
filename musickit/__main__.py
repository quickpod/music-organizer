"""Command-line interface: ``python -m musickit <command> ...``.

Commands: ``read``, ``write``, ``scan``, ``autotag``, ``dedupe``, ``organize``.
Every command exits cleanly (code 1, a one-line ``error:`` message) on a
:class:`MusicKitError` -- never a traceback.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import (
    MusicKitError,
    UNIFIED_FIELDS,
    read_tags,
    write_tags,
    read_cover,
    write_cover,
    scan_folder,
    plan_autotag,
    apply_autotag,
    find_duplicates_in_folder,
    summarize,
    plan_rename,
    apply_plan,
)
from . import library as _library


# --- helpers ----------------------------------------------------------------
def _print_tags(path, fields):
    print(f"File: {path}")
    for name in UNIFIED_FIELDS:
        value = fields.get(name, "")
        if value != "":
            print(f"  {name:<12} {value}")


def _guess_mime(path):
    ext = os.path.splitext(path)[1].lower()
    return {".png": "image/png", ".gif": "image/gif",
            ".webp": "image/webp"}.get(ext, "image/jpeg")


# --- command handlers -------------------------------------------------------
def cmd_read(a):
    fields = read_tags(a.file)
    _print_tags(a.file, fields)
    data, mime = read_cover(a.file)
    if data:
        print(f"  cover        {len(data)} bytes ({mime})")


def cmd_write(a):
    fields = {}
    for name in UNIFIED_FIELDS:
        value = getattr(a, name, None)
        if value is not None:
            fields[name] = value
    if a.cover:
        with open(a.cover, "rb") as fh:
            write_cover(a.file, fh.read(), _guess_mime(a.cover))
    if fields:
        fresh = write_tags(a.file, fields)
    else:
        fresh = read_tags(a.file)
    if not fields and not a.cover:
        raise MusicKitError("nothing to write -- pass at least one --field or --cover")
    if a.extract_cover:
        data, _mime = read_cover(a.file)
        if not data:
            raise MusicKitError("no cover art to extract")
        with open(a.extract_cover, "wb") as fh:
            fh.write(data)
        print(f"Extracted cover -> {a.extract_cover} ({len(data)} bytes)")
    print(f"Wrote {len(fields)} field(s)" + (" + cover" if a.cover else "")
          + f" -> {a.file}")
    _print_tags(a.file, fresh)


def cmd_scan(a):
    tracks = scan_folder(a.folder, recursive=not a.no_recursive)
    if a.sort:
        tracks = _library.sort_tracks(tracks, a.sort, reverse=a.reverse)
    if not tracks:
        print(f"No audio files found in {a.folder}")
        return
    print(f"{'#':>3}  {'TRACK':<5} {'TITLE':<26} {'ARTIST':<20} "
          f"{'ALBUM':<20} {'TIME':>6}  {'KBPS':>4}")
    for i, t in enumerate(tracks, 1):
        print(f"{i:>3}  {str(t['track']):<5} {t['title'][:26]:<26} "
              f"{t['artist'][:20]:<20} {t['album'][:20]:<20} "
              f"{t['duration_str']:>6}  {t['bitrate'] or '':>4}")
    print(f"\n{len(tracks)} track(s).")


def cmd_autotag(a):
    paths = _library.find_audio_files(a.folder, recursive=not a.no_recursive)
    if not paths:
        print(f"No audio files found in {a.folder}")
        return
    plan = plan_autotag(paths, a.pattern, only_missing=not a.all,
                        use_folder=a.use_folder)
    matched = [p for p in plan if p["matched"]]
    changed = [p for p in plan if p["changes"]]
    print(f"Pattern: {a.pattern}")
    print(f"Matched {len(matched)}/{len(plan)} file(s); "
          f"{len(changed)} would change.\n")
    for entry in plan:
        name = os.path.basename(entry["path"])
        if not entry["changes"]:
            continue
        pairs = ", ".join(f"{k}={v!r}" for k, v in entry["changes"].items())
        print(f"  {name}\n      {pairs}")
    if a.preview:
        print("\n(preview only -- nothing written)")
        return
    n = apply_autotag(plan)
    print(f"\nApplied auto-tags to {n} file(s).")


def cmd_dedupe(a):
    groups = find_duplicates_in_folder(a.folder, by=a.by,
                                       recursive=not a.no_recursive)
    stats = summarize(groups)
    if not groups:
        print("No duplicates found.")
        return
    print(f"Found {stats['groups']} duplicate group(s), "
          f"{stats['duplicates']} redundant copy/copies:\n")
    for i, group in enumerate(groups, 1):
        head = group[0]
        label = f"{head.get('artist', '')} - {head.get('title', '')}".strip(" -")
        print(f"Group {i}: {label or '(untitled)'} ({len(group)} files)")
        for t in group:
            print(f"    {t['path']}  [{t.get('duration_str', '')}]")
        print()


def cmd_organize(a):
    tracks = scan_folder(a.folder, recursive=not a.no_recursive)
    if not tracks:
        print(f"No audio files found in {a.folder}")
        return
    plan = plan_rename(tracks, a.pattern, dest_root=a.dest or "")
    verb = "COPY" if a.copy else "MOVE"
    print(f"Pattern: {a.pattern}   ({verb} into {a.dest or '(in place)'})\n")
    for entry in plan:
        print(f"  {os.path.basename(entry['src'])}")
        print(f"      -> {entry['target']}")
    if a.preview:
        print(f"\n{len(plan)} file(s) planned (preview only -- nothing moved).")
        return
    written = apply_plan(plan, copy=a.copy, overwrite=a.overwrite)
    print(f"\n{verb.title()}d {len(written)} file(s) -> {a.dest or '(in place)'}")


# --- parser -----------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="musickit",
        description="Offline audio tag & library manager. Unified tag schema "
                    "across MP3/FLAC/Ogg/M4A.")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, help, handler):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(func=handler)
        return sp

    s = add("read", "Show a file's tags", cmd_read)
    s.add_argument("file")

    s = add("write", "Set tags (and/or cover) on a file", cmd_write)
    s.add_argument("file")
    for name in UNIFIED_FIELDS:
        s.add_argument(f"--{name}", help=f"set {name}")
    s.add_argument("--cover", metavar="IMG", help="embed this image as cover art")
    s.add_argument("--extract-cover", metavar="IMG",
                   help="write the existing cover art to this file")

    s = add("scan", "List tracks under a folder", cmd_scan)
    s.add_argument("folder")
    s.add_argument("--no-recursive", action="store_true")
    s.add_argument("--sort", help="sort by a column (e.g. artist, track, year)")
    s.add_argument("--reverse", action="store_true")

    s = add("autotag", "Fill tags from filenames via a pattern", cmd_autotag)
    s.add_argument("folder")
    s.add_argument("--pattern", required=True,
                   help='e.g. "{artist} - {album} - {track} {title}"')
    s.add_argument("--preview", action="store_true", help="show changes, write nothing")
    s.add_argument("--all", action="store_true",
                   help="overwrite existing tags too (default: only fill missing)")
    s.add_argument("--use-folder", action="store_true",
                   help="match parent folder name too")
    s.add_argument("--no-recursive", action="store_true")

    s = add("dedupe", "Find duplicate tracks", cmd_dedupe)
    s.add_argument("folder")
    s.add_argument("--by", choices=["tags", "hash", "both"], default="tags")
    s.add_argument("--no-recursive", action="store_true")

    s = add("organize", "Rename/move files by a tag pattern", cmd_organize)
    s.add_argument("folder")
    s.add_argument("--pattern", required=True,
                   help='e.g. "{albumartist}/{album}/{track:02d} - {title}"')
    s.add_argument("--dest", help="destination library root (default: in place)")
    s.add_argument("--preview", action="store_true", help="show plan, move nothing")
    s.add_argument("--copy", action="store_true", help="copy instead of move")
    s.add_argument("--overwrite", action="store_true",
                   help="allow overwriting existing targets")
    s.add_argument("--no-recursive", action="store_true")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except MusicKitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
