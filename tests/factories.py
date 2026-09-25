from datetime import date
from decimal import Decimal

from suprm.config import settings
from suprm.models import Artist, Contributor, Release, ReleaseStatus, ReleaseType, Split, Track, User
from suprm.security import hash_password

from .conftest import make_png, make_wav


def make_user(session, email="artist@example.com", name="Nova Kai"):
    user = User(email=email, password_hash=hash_password("password1234"), display_name=name)
    session.add(user)
    session.flush()
    return user


def make_release(session, user, *, tracks=2, status=ReleaseStatus.approved):
    artist = Artist(owner_id=user.id, name=user.display_name)
    session.add(artist)
    make_png(settings.media_root / "art.png")
    release = Release(
        artist=artist, title="Midnight Drive", release_type=ReleaseType.EP if tracks > 1 else ReleaseType.Single,
        upc=None, label_name="Suprm Sounds", genre="R&B/Soul", release_date=date(2026, 11, 6),
        p_line_year=2026, p_line="Nova Kai", c_line_year=2026, c_line="Nova Kai",
        artwork_path="art.png", status=status,
    )
    session.add(release)
    for n in range(1, tracks + 1):
        make_wav(settings.media_root / f"t{n}.wav", seconds=3)
        t = Track(release=release, track_number=n, title=f"Song {n}", isrc=f"USSU1260000{n}",
                  audio_path=f"t{n}.wav", audio_codec="WAV", duration_seconds=3)
        t.contributors = [Contributor(name="Nova Kai", role="MainArtist"),
                          Contributor(name="Jordan Lee", role="FeaturedArtist"),
                          Contributor(name="Nova K. Smith", role="ComposerLyricist")]
        t.splits = [Split(user_id=user.id, email=user.email, percent=Decimal(100))]
        session.add(t)
    session.flush()
    from suprm.identifiers import next_upc
    release.upc = next_upc(session)
    session.commit()
    return release
