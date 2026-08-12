"""Shared fixtures: tiny but *valid* audio files crafted at runtime.

We cannot depend on an audio encoder being present, so we synthesise the
smallest containers mutagen will happily open and tag:

* **FLAC** -- ``fLaC`` marker + a single STREAMINFO metadata block (no audio
  frames needed to read/write Vorbis comments and pictures).
* **WAV**  -- a real RIFF/PCM file via the stdlib ``wave`` module; mutagen
  stores ID3 tags in a ``id3 `` chunk.
* **MP3**  -- a handful of silent MPEG-1 Layer III frames.

Ogg Vorbis and M4A/MP4 need genuine encoded streams that can't be crafted
headlessly, so they are exercised only indirectly (via the shared code paths).
"""

from __future__ import annotations

import os
import struct
import wave

import pytest


def _write_min_flac(path):
    streaminfo = bytearray(34)
    struct.pack_into(">H", streaminfo, 0, 4096)      # min blocksize
    struct.pack_into(">H", streaminfo, 2, 4096)      # max blocksize
    sr, ch, bps, total = 44100, 1, 16, 44100         # 1 second, mono
    packed = (sr << 44) | ((ch - 1) << 41) | ((bps - 1) << 36) | total
    struct.pack_into(">Q", streaminfo, 10, packed)
    header = bytes([0x80]) + struct.pack(">I", 34)[1:]   # last-block, type 0, len 34
    with open(path, "wb") as fh:
        fh.write(b"fLaC" + header + bytes(streaminfo))
    return path


def _write_min_wav(path, seconds=1, rate=8000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<" + "h" * (rate * seconds),
                                  *([0] * (rate * seconds))))
    return path


def _write_min_mp3(path, frames=20):
    header = bytes([0xFF, 0xFB, 0x90, 0xC4])   # MPEG-1 L3, 128 kbps, 44.1 kHz
    framesize = int(144 * 128000 / 44100)
    frame = header + bytes(framesize - 4)
    with open(path, "wb") as fh:
        fh.write(frame * frames)
    return path


@pytest.fixture
def flac_file(tmp_path):
    return _write_min_flac(str(tmp_path / "sample.flac"))


@pytest.fixture
def wav_file(tmp_path):
    return _write_min_wav(str(tmp_path / "sample.wav"))


@pytest.fixture
def mp3_file(tmp_path):
    return _write_min_mp3(str(tmp_path / "sample.mp3"))


@pytest.fixture
def make_flac(tmp_path):
    """Factory: make_flac('name.flac') -> path to a fresh minimal FLAC."""
    def _factory(name):
        return _write_min_flac(str(tmp_path / name))
    return _factory


# A 1x1 PNG (valid) for cover-art round-trips.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


@pytest.fixture
def tiny_png():
    return TINY_PNG
