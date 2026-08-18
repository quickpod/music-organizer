"""musickit -- an offline, permissively-licensed audio tag & library toolkit.

Built on `mutagen`.  Everything is offline: no network lookups, ever.  The
public API works in one **unified tag schema** across MP3/ID3, FLAC, Ogg Vorbis
and M4A/MP4, and every operation raises :class:`MusicKitError` (and only that)
on failure so the CLI and GUI have a single exception to catch::

    from musickit import read_tags, write_tags, scan_folder
    write_tags("song.flac", {"artist": "Nova", "title": "Drift"})
    tags = read_tags("song.flac")

See the GUI (``musickit.gui``) and CLI (``python -m musickit``) for tools built
on this module.
"""

from __future__ import annotations

from .errors import MusicKitError
from .tags import (
    UNIFIED_FIELDS,
    AUDIO_EXTS,
    is_audio,
    read_tags,
    write_tags,
    read_cover,
    write_cover,
    read_audio_info,
)
from .library import (
    scan_folder,
    find_audio_files,
    read_track,
    search_tracks,
    filter_tracks,
    sort_tracks,
    duration_str,
)
from .autotag import (
    parse_pattern,
    compile_pattern,
    suggest_tags,
    plan_autotag,
    apply_autotag,
    title_case,
    guess_track_number,
)
from .dedupe import (
    find_duplicates,
    find_duplicates_in_folder,
    tag_signature,
    content_hash,
    summarize,
)
from .organize import (
    render_pattern,
    plan_rename,
    apply_plan,
    sanitize_component,
)

__version__ = "1.0.5"

__all__ = [
    "MusicKitError",
    "UNIFIED_FIELDS",
    "AUDIO_EXTS",
    "is_audio",
    "read_tags",
    "write_tags",
    "read_cover",
    "write_cover",
    "read_audio_info",
    "scan_folder",
    "find_audio_files",
    "read_track",
    "search_tracks",
    "filter_tracks",
    "sort_tracks",
    "duration_str",
    "parse_pattern",
    "compile_pattern",
    "suggest_tags",
    "plan_autotag",
    "apply_autotag",
    "title_case",
    "guess_track_number",
    "find_duplicates",
    "find_duplicates_in_folder",
    "tag_signature",
    "content_hash",
    "summarize",
    "render_pattern",
    "plan_rename",
    "apply_plan",
    "sanitize_component",
]
