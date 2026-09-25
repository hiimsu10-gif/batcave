"""End to end: artist signs up, builds a release, admin approves and delivers
it, royalties come in, and the artist gets paid."""
import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from suprm.config import settings
from suprm.models import Delivery, Payout, Release, Role, User
from suprm.security import hash_password
from suprm.web import routes_payouts
from suprm.web.app import create_app

from .conftest import make_png, make_wav


def csrf(client, path):
    html = client.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def client():
    with TestClient(create_app(create_tables=False)) as c:
        yield c


class FakeGateway:
    def create_account(self, user):
        return "acct_test"

    def onboarding_link(self, account_id, return_url, refresh_url):
        return "https://connect.stripe.test/onboard"

    def payouts_enabled(self, account_id):
        return True

    def dashboard_link(self, account_id):
        return "https://connect.stripe.test/dash"

    def transfer(self, account_id, amount_cents, currency, idempotency_key, description):
        return "tr_test"


def test_full_artist_journey(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_payouts, "gateway", lambda: FakeGateway())

    # --- artist signs up
    token = csrf(client, "/signup")
    r = client.post("/signup", data={"csrf": token, "email": "nova@example.com", "password": "supersecret1",
                                     "artist_name": "Nova Kai", "country": "US"})
    assert r.status_code == 200 and "Hey Nova Kai" in r.text

    # --- creates a release
    token = csrf(client, "/releases/new")
    artist_id = session.scalar(select(User).where(User.email == "nova@example.com")).artists[0].id
    r = client.post("/releases/new", data={"csrf": token, "artist_id": artist_id, "title": "Midnight Drive",
                                           "release_type": "Single", "genre": "R&B/Soul",
                                           "release_date": "2026-11-06"})
    release_id = int(r.url.path.rsplit("/", 1)[1])
    assert "Cover art is required" in r.text

    # --- uploads bad artwork, then good artwork
    page = f"/releases/{release_id}"
    small = make_png(tmp_path / "small.png", size=500)
    r = client.post(f"{page}/artwork", data={"csrf": csrf(client, page)},
                    files={"file": ("small.png", small.read_bytes(), "image/png")})
    assert "at least 3000x3000" in r.text
    art = make_png(tmp_path / "cover.png")
    r = client.post(f"{page}/artwork", data={"csrf": csrf(client, page)},
                    files={"file": ("cover.png", art.read_bytes(), "image/png")})
    assert "Cover art uploaded" in r.text

    # --- uploads a track and adds a producer split
    wav = make_wav(tmp_path / "song.wav", seconds=4)
    r = client.post(f"{page}/tracks", data={"csrf": csrf(client, page), "title": "Midnight Drive",
                                           "songwriter": "Nova K. Smith"},
                    files={"file": ("song.wav", wav.read_bytes(), "audio/wav")})
    assert "WAV, 44100 Hz, 16-bit" in r.text
    release = session.get(Release, release_id)
    session.refresh(release)
    track = release.tracks[0]
    r = client.post(f"/tracks/{track.id}/splits", data={"csrf": csrf(client, page), "email": "nova@example.com",
                                                       "percent": "70"})
    r = client.post(f"/tracks/{track.id}/splits", data={"csrf": csrf(client, page), "email": "beats@example.com",
                                                       "percent": "30"})
    assert "beats@example.com" in r.text and "(invited)" in r.text

    # --- submits
    r = client.post(f"{page}/submit", data={"csrf": csrf(client, page)})
    assert "Submitted!" in r.text

    # --- CSRF is enforced
    assert client.post(f"{page}/submit", data={"csrf": "wrong"}).status_code == 403

    # --- artist can't reach admin
    assert client.get("/admin").status_code == 403

    # --- admin approves and delivers to a local target
    session.add(User(email="admin@suprm.test", password_hash=hash_password("adminpassword"),
                     display_name="Admin", role=Role.admin))
    session.commit()
    client.post("/logout", data={"csrf": csrf(client, "/dashboard")})
    client.post("/login", data={"csrf": csrf(client, "/login"), "email": "admin@suprm.test",
                                "password": "adminpassword"})
    assert "Waiting for review (1)" in client.get("/admin").text

    client.post("/admin/targets", data={"csrf": csrf(client, "/admin/targets"), "name": "Local test",
                                        "transport": "local", "recipient_party_id": "PADPIDA0000000000T",
                                        "recipient_party_name": "Test Store",
                                        "config_json": f'{{"path": "{tmp_path / "delivered"}"}}'})
    review = f"/admin/releases/{release_id}"
    r = client.post(f"{review}/approve", data={"csrf": csrf(client, review)})
    assert "Approved. UPC 0123456" in r.text
    target_id = re.search(r'name="target_ids" value="(\d+)"', r.text).group(1)
    r = client.post(f"{review}/deliver", data={"csrf": csrf(client, review), "target_ids": target_id,
                                               "kind": "insert"})
    assert "Local test: insert sent" in r.text
    delivery = session.scalar(select(Delivery))
    session.refresh(release)
    assert release.status.value == "delivered"
    delivered = tmp_path / "delivered" / delivery.batch_id
    assert (delivered / release.upc / f"{release.upc}.xml").exists()
    assert (delivered / f"BatchComplete_{delivery.batch_id}.xml").exists()

    # --- a royalty report arrives and is allocated
    isrc = session.get(type(track), track.id).isrc
    csv = f"ISRC,Store,Country,Streams,Earnings (USD)\n{isrc},Spotify,US,40000,160.00\n".encode()
    r = client.post("/admin/royalties", data={"csrf": csrf(client, "/admin/royalties"), "source": "Local test",
                                              "period": "2026-12"},
                    files={"file": ("dec.csv", csv, "text/csv")})
    assert "Imported 1 lines" in r.text
    st_id = re.search(r"/admin/royalties/(\d+)/allocate", r.text).group(1)
    r = client.post(f"/admin/royalties/{st_id}/allocate", data={"csrf": csrf(client, "/admin/royalties")})
    assert "Allocated 1 lines" in r.text

    # --- the artist connects Stripe and gets paid 70%
    client.post("/logout", data={"csrf": csrf(client, "/admin")})
    client.post("/login", data={"csrf": csrf(client, "/login"), "email": "nova@example.com",
                                "password": "supersecret1"})
    assert "$112.00" in client.get("/dashboard").text
    r = client.post("/payouts/connect", data={"csrf": csrf(client, "/payouts")}, follow_redirects=False)
    assert r.headers["location"] == "https://connect.stripe.test/onboard"
    assert "Payout account connected" in client.get("/payouts/return").text

    client.post("/logout", data={"csrf": csrf(client, "/dashboard")})
    client.post("/login", data={"csrf": csrf(client, "/login"), "email": "admin@suprm.test",
                                "password": "adminpassword"})
    r = client.post("/admin/payouts/run", data={"csrf": csrf(client, "/admin/payouts")})
    assert "Paid 1 artists ($112.00)" in r.text
    assert session.scalar(select(Payout)).amount == Decimal("112.00")

    # --- the producer signs up later and finds their 30% waiting
    client.post("/logout", data={"csrf": csrf(client, "/admin")})
    r = client.post("/signup", data={"csrf": csrf(client, "/signup"), "email": "beats@example.com",
                                     "password": "producerpass1", "artist_name": "Beatz"})
    assert "$48.00" in r.text


def test_media_is_private(client, session, tmp_path):
    from .factories import make_release, make_user

    owner = make_user(session)
    release = make_release(session, owner)
    stranger = User(email="x@example.com", password_hash=hash_password("strangerpass1"), display_name="X")
    session.add(stranger)
    session.commit()
    client.post("/login", data={"csrf": csrf(client, "/login"), "email": "x@example.com",
                                "password": "strangerpass1"})
    assert client.get(f"/files/artwork/{release.id}").status_code == 404
    assert client.get(f"/releases/{release.id}").status_code == 404
    assert settings.media_root.exists()
