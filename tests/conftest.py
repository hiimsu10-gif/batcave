import os
import struct
import tempfile
import wave
import zlib
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="suprm-test-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "MEDIA_ROOT": str(_TMP / "media"),
    "OUTBOX_ROOT": str(_TMP / "outbox"),
    "SECRET_KEY": "test-secret",
    "UPC_COMPANY_PREFIX": "0123456",
    "ISRC_COUNTRY": "US",
    "ISRC_REGISTRANT": "SU1",
    "DDEX_PARTY_ID": "PADPIDA2026SUPRM01",
    "PLATFORM_COMMISSION_PERCENT": "0",
    "MIN_PAYOUT_USD": "10.00",
})

import pytest  # noqa: E402

from suprm.db import Base, SessionLocal, engine  # noqa: E402
from suprm import models  # noqa: E402,F401


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def session():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def tmp_root():
    return _TMP


def make_wav(path: Path, seconds: float = 2.0, rate: int = 44100, channels: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * channels * int(rate * seconds))
    return path


def make_png(path: Path, size: int = 3000, height: int | None = None) -> Path:
    height = height or size
    path.parent.mkdir(parents=True, exist_ok=True)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = (b"\x00" + b"\x00" * size * 3) * height
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    return path
