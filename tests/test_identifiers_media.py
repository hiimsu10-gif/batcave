import pytest

from suprm.identifiers import gtin_check_digit, is_valid_isrc, is_valid_upc, next_isrc, next_upc
from suprm.media import MediaError, inspect_audio, inspect_image

from .conftest import make_png, make_wav


def test_gtin_check_digit_known_upc():
    assert gtin_check_digit("03600029145") == "2"
    assert is_valid_upc("036000291452")
    assert not is_valid_upc("036000291453")


def test_isrc_validation():
    assert is_valid_isrc("US-SU1-26-00001")
    assert not is_valid_isrc("US-SU1-26-0001")


def test_code_generation_is_sequential(session):
    upc = next_upc(session)
    assert upc.startswith("0123456") and len(upc) == 12 and is_valid_upc(upc)
    assert next_isrc(session, 2026) == "USSU12600001"


def test_audio_inspection(tmp_path):
    info = inspect_audio(make_wav(tmp_path / "a.wav", seconds=3))
    assert (info.codec, info.sample_rate, info.channels, info.duration_seconds) == ("WAV", 44100, 2, 3)
    with pytest.raises(MediaError, match="stereo"):
        inspect_audio(make_wav(tmp_path / "m.wav", channels=1))
    with pytest.raises(MediaError, match="44.1"):
        inspect_audio(make_wav(tmp_path / "l.wav", rate=22050))


def test_flac_streaminfo(tmp_path):
    # Hand-built STREAMINFO: 48 kHz, stereo, 24-bit, 480000 samples = 10 s
    packed = (48000 << 44) | (1 << 41) | (23 << 36) | 480000
    streaminfo = b"\x00" * 10 + packed.to_bytes(8, "big") + b"\x00" * 16
    f = tmp_path / "t.flac"
    f.write_bytes(b"fLaC" + b"\x80\x00\x00\x22" + streaminfo)
    info = inspect_audio(f)
    assert (info.codec, info.sample_rate, info.bits_per_sample, info.duration_seconds) == ("FLAC", 48000, 24, 10)


def test_artwork_rules(tmp_path):
    assert inspect_image(make_png(tmp_path / "ok.png")).width == 3000
    with pytest.raises(MediaError, match="3000"):
        inspect_image(make_png(tmp_path / "small.png", size=1000))
    with pytest.raises(MediaError, match="square"):
        inspect_image(make_png(tmp_path / "rect.png", size=3000, height=3001))
