# MusicOrganizer

A fast, **offline**, **100% open-source** music tag & library manager for Windows. Nothing is uploaded anywhere. Built entirely by AI with human testing and guidance, and published on [QuickOpen](https://quickopen.ai/projects/music-organizer).

> **100% AI-built and open source.** Apache-2.0.

## What it does

Manage a music library: edit ID3/Vorbis/FLAC tags and album art, auto-tag from filenames or fill missing fields, find duplicate tracks, and bulk-rename/organize files by tag patterns (Artist/Album/Track). An open-source Mp3tag-style toolkit — works entirely offline.

## Install

Download **`MusicOrganizer-Setup.exe`** from the [QuickOpen page](https://quickopen.ai/projects/music-organizer) or the [GitHub release](https://github.com/quickpod/music-organizer/releases/latest) and double-click it. It installs per-user, adds Desktop and Start Menu shortcuts, and can optionally trust the QuickOpen Root CA. Authenticode-signed by the QuickOpen Code Signing CA — verify at [quickopen.ai/trust](https://quickopen.ai/trust).

## Run from source

```sh
pip install -r requirements.txt
python music_organizer_app.py          # GUI
python -m musickit --help    # CLI
```


## Features

Everything works **offline** on one **unified tag schema** — `title`, `artist`,
`album`, `albumartist`, `track`, `disc`, `year`, `genre`, `comment` — normalised
across MP3/ID3, FLAC, Ogg Vorbis/Opus and M4A/MP4 (and ID3-in-WAV/AIFF).

- **Tag editor** — read/write tags and embedded cover art on single tracks or
  batch-apply a field across a whole selection.
- **Library** — scan a folder into a sortable, searchable table (tags plus
  duration and bitrate); scans run on a background thread.
- **Auto-Tag** — infer missing tags from filenames/folders with a pattern such
  as `{artist} - {album} - {track} {title}`, with a gentle title-case cleanup and
  track-number guessing. Preview before applying; no online lookups, ever.
- **Rename / Organize** — preview and then move or copy files into a tag-based
  tree like `{albumartist}/{album}/{track:02d} - {title}`, with filesystem-safe
  names and automatic collision handling.
- **Duplicates** — group duplicate tracks by normalised artist+title+duration
  and/or an audio content hash (which ignores ID3 tag blocks), then remove the
  copies you don't want.
- A **dark/light** QuickOpen theme that persists, plus recent-folder history.

## CLI examples

```sh
# Show a file's tags (and cover size, if any)
python -m musickit read "song.flac"

# Set tags and embed cover art
python -m musickit write "song.flac" --title "Aurora" --artist "Nova" \
    --album "Skylines" --track 4 --year 2023 --cover cover.jpg

# List every track under a folder, sorted by artist
python -m musickit scan ~/Music --sort artist

# Fill missing tags from filenames (preview first)
python -m musickit autotag ~/Music --pattern "{artist} - {title}" --preview
python -m musickit autotag ~/Music --pattern "{artist} - {title}"

# Find duplicate tracks (by tags, or by audio content hash)
python -m musickit dedupe ~/Music --by both

# Organize a library into an Artist/Album tree (preview, then copy)
python -m musickit organize ~/Music --dest ~/Library \
    --pattern "{albumartist}/{album}/{track:02d} - {title}" --preview
python -m musickit organize ~/Music --dest ~/Library \
    --pattern "{albumartist}/{album}/{track:02d} - {title}" --copy
```

## License

Apache-2.0 — see [LICENSE](LICENSE). A 100% AI-built project published on QuickOpen.
