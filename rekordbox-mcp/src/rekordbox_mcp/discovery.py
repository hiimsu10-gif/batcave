"""Where to find (and legitimately buy or download) tracks: Bandcamp, SoundCloud, Beatport."""

from __future__ import annotations

from urllib.parse import quote_plus


def store_links(artist: str = "", title: str = "") -> dict[str, str]:
    """Search links for a specific track on the stores/platforms DJs buy from."""
    q = quote_plus(" ".join(p for p in (artist, title) if p).strip())
    return {
        "bandcamp": f"https://bandcamp.com/search?q={q}&item_type=t",
        "soundcloud": f"https://soundcloud.com/search/sounds?q={q}",
        "beatport": f"https://www.beatport.com/search/tracks?q={q}",
    }


def artist_links(artist: str) -> dict[str, str]:
    """Links to an artist's pages, for checking new releases."""
    q = quote_plus(artist.strip())
    return {
        "bandcamp": f"https://bandcamp.com/search?q={q}&item_type=b",
        "soundcloud": f"https://soundcloud.com/search/people?q={q}",
        "beatport": f"https://www.beatport.com/search/artists?q={q}",
    }


def genre_links(genre: str) -> dict[str, str]:
    """Links to browse new releases for a genre / tag."""
    slug = "-".join(genre.lower().split())
    q = quote_plus(genre.strip())
    return {
        "bandcamp": f"https://bandcamp.com/discover/{slug}?s=new",
        "soundcloud": f"https://soundcloud.com/tags/{slug}",
        "beatport": f"https://www.beatport.com/search?q={q}",
    }
