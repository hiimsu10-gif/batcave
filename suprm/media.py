"""Inspect uploaded audio and artwork without heavy dependencies.

Store requirements this enforces (the common denominator across DSPs):
  * Audio: FLAC or WAV, 16/24-bit, 44.1 kHz or higher, stereo.
  * Artwork: JPEG or PNG, square, at least 3000x3000 px.
"""
from __future__ import annotations

import hashlib
import struct
import wave
from dataclasses import dataclass
from pathlib import Path


class MediaError(ValueError):
    pass


@dataclass
class AudioInfo:
    codec: str
    sample_rate: int
    bits_per_sample: int
    channels: int
    duration_seconds: int


@dataclass
class ImageInfo:
    format: str
    width: int
    height: int


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_audio(path: Path) -> AudioInfo:
    with open(path, "rb") as fh:
        head = fh.read(12)
    if head[:4] == b"fLaC":
        info = _inspect_flac(path)
    elif head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        info = _inspect_wav(path)
    else:
        raise MediaError("Audio must be a FLAC or WAV file")
    if info.sample_rate < 44100:
        raise MediaError(f"Sample rate {info.sample_rate} Hz is below the 44.1 kHz minimum")
    if info.bits_per_sample not in (16, 24, 32):
        raise MediaError(f"Unsupported bit depth {info.bits_per_sample}")
    if info.channels != 2:
        raise MediaError("Audio must be stereo (2 channels)")
    if info.duration_seconds < 1:
        raise MediaError("Audio is empty")
    return info


def _inspect_flac(path: Path) -> AudioInfo:
    with open(path, "rb") as fh:
        fh.read(4)
        header = fh.read(4)
        if len(header) < 4 or header[0] & 0x7F != 0:
            raise MediaError("FLAC file is missing its STREAMINFO block")
        data = fh.read(34)
    if len(data) < 18:
        raise MediaError("FLAC STREAMINFO is truncated")
    packed = int.from_bytes(data[10:18], "big")
    sample_rate = packed >> 44
    channels = ((packed >> 41) & 0x7) + 1
    bits = ((packed >> 36) & 0x1F) + 1
    total_samples = packed & 0xFFFFFFFFF
    duration = round(total_samples / sample_rate) if sample_rate else 0
    return AudioInfo("FLAC", sample_rate, bits, channels, duration)


def _inspect_wav(path: Path) -> AudioInfo:
    try:
        with wave.open(str(path), "rb") as w:
            rate, frames = w.getframerate(), w.getnframes()
            return AudioInfo("WAV", rate, w.getsampwidth() * 8, w.getnchannels(), round(frames / rate))
    except wave.Error as exc:
        raise MediaError(f"Unreadable WAV file: {exc}") from exc


def inspect_image(path: Path) -> ImageInfo:
    with open(path, "rb") as fh:
        data = fh.read(64 * 1024)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        info = ImageInfo("PNG", width, height)
    elif data[:2] == b"\xff\xd8":
        info = _jpeg_size(data)
    else:
        raise MediaError("Artwork must be a JPEG or PNG image")
    if info.width != info.height:
        raise MediaError(f"Artwork must be square (got {info.width}x{info.height})")
    if info.width < 3000:
        raise MediaError(f"Artwork must be at least 3000x3000 px (got {info.width}x{info.height})")
    return info


def _jpeg_size(data: bytes) -> ImageInfo:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return ImageInfo("JPEG", width, height)
        i += 2 + length
    raise MediaError("Could not read JPEG dimensions")
