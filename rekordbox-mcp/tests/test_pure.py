from rekordbox_mcp.camelot import compatible_keys, to_camelot, to_classic, transition_cost
from rekordbox_mcp.setbuilder import build_set
from rekordbox_mcp.textmatch import best_matches, normalize_title, split_artist_title


def test_key_parsing():
    assert to_camelot("Am") == "8A"
    assert to_camelot("A minor") == "8A"
    assert to_camelot("08a") == "8A"
    assert to_camelot("F#m") == to_camelot("Gbm") == "11A"
    assert to_camelot("Bb") == "6B"
    assert to_camelot("C") == "8B"
    assert to_camelot("nonsense") is None
    assert to_classic("8A") == "Am"


def test_harmonic_rules():
    assert set(compatible_keys("8A")) == {"8A", "9A", "7A", "8B"}
    assert set(compatible_keys("12B")) == {"12B", "1B", "11B", "12A"}
    assert transition_cost("8A", "8A") == 0
    assert transition_cost("12A", "1A") == 1
    assert transition_cost("8A", "8B") == 1
    assert transition_cost("8A", "10A") == 2
    assert transition_cost("8A", "3A") == 4
    assert transition_cost(None, "3A") == 3


def test_text_matching():
    assert normalize_title("Sunrise (Original Mix)") == normalize_title("sunrise")
    assert normalize_title("Café feat. Someone") == "cafe"
    assert split_artist_title("01 - Alpha - Sunrise") == ("Alpha", "Sunrise")
    assert split_artist_title("Just A Title") == ("", "Just A Title")
    lib = [{"id": "1", "artist": "Alpha & Beta", "title": "Sunrise (Extended Mix)"},
           {"id": "2", "artist": "Gamma", "title": "Sunset"}]
    hits = best_matches("Alpha", "Sunrise", lib)
    assert hits and hits[0][1]["id"] == "1"
    assert not best_matches("Nobody", "Totally Different", lib)


def _t(i, bpm, key, artist="A", length=300, rating=3):
    return {"id": str(i), "bpm": bpm, "camelot": key, "artist": artist, "length_sec": length, "rating": rating}


def test_build_set_ramps_and_stays_harmonic():
    pool = [
        _t(1, 120, "8A", "a"), _t(2, 121, "9A", "b"), _t(3, 122, "9A", "c"),
        _t(4, 124, "10A", "d"), _t(5, 125, "10A", "e"), _t(6, 126, "11A", "f"),
        _t(7, 126, "3B", "g"),  # clashes with everything around it
    ]
    result = build_set(pool, duration_minutes=30, bpm_start=120, bpm_end=126)
    ids = [t["id"] for t in result["tracks"]]
    assert ids[0] == "1"
    assert len(ids) == 6 and "7" not in ids
    bpms = [t["bpm"] for t in result["tracks"]]
    assert bpms == sorted(bpms)
    assert not result["warnings"]
    assert "harmonic" in result["tracks"][1]["transition"]


def test_build_set_reports_short_pool():
    result = build_set([_t(1, 120, "8A")], duration_minutes=60)
    assert result["total_minutes"] == 5.0
    assert "Only" in result["warnings"][0]
    assert build_set([], 60)["tracks"] == []
