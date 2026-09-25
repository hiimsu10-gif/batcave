"""DDEX ERN 4.3 NewReleaseMessage builder (Audio release profile).

DDEX ERN is the XML format every major store ingests: Spotify, Apple Music,
Amazon, YouTube Music, Deezer, TIDAL, TikTok/SoundOn and the rest. One
message describes one release: its parties (artists, label), resources
(audio files, cover art), the release and its track releases, and the deals
(where and how it can be sold or streamed, and from when).

Before a store switches you to live deliveries, check your output with the
DDEX validator (https://ddex.net -> Workbench) and the store's own ingestion
spec. Stores often require extra fields on top of the standard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from lxml import etree

from ..models import Release, Track

ERN_NS = "http://ddex.net/xml/ern/43"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = f"{ERN_NS} http://service.ddex.net/xml/ern/43/release-notification.xsd"

# The deal set most distributors send by default: streaming + downloads.
DEFAULT_DEALS: list[tuple[str, str]] = [
    ("SubscriptionModel", "OnDemandStream"),
    ("AdvertisementSupportedModel", "OnDemandStream"),
    ("SubscriptionModel", "NonInteractiveStream"),
    ("PayAsYouGoModel", "PermanentDownload"),
]


@dataclass
class ResourceFile:
    uri: str    # path relative to the XML file, e.g. "resources/0123_01_001.flac"
    md5: str


@dataclass
class MessageContext:
    message_id: str
    thread_id: str
    sender_party_id: str
    sender_name: str
    recipient_party_id: str
    recipient_name: str
    test_message: bool = True
    takedown: bool = False
    created: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deals: list[tuple[str, str]] = field(default_factory=lambda: list(DEFAULT_DEALS))


def iso_duration(seconds: int | None) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"PT{h}H{m}M{s}S" if h else f"PT{m}M{s}S"


def _sub(parent: etree._Element, tag: str, text: str | None = None, **attrib) -> etree._Element:
    el = etree.SubElement(parent, tag, {k: str(v) for k, v in attrib.items()})
    if text is not None:
        el.text = str(text)
    return el


def _full_title(title: str, version: str | None) -> str:
    return f"{title} ({version})" if version else title


class _Parties:
    """Assigns stable PartyReferences to every name mentioned in the release."""

    def __init__(self) -> None:
        self._refs: dict[str, str] = {}

    def ref(self, name: str) -> str:
        if name not in self._refs:
            self._refs[name] = f"P{len(self._refs) + 1}"
        return self._refs[name]

    def items(self):
        return self._refs.items()


DISPLAY_ROLES = {"MainArtist", "FeaturedArtist"}


def _track_artists(track: Track, release: Release) -> list[tuple[str, str]]:
    artists = [(c.name, c.role) for c in track.contributors if c.role in DISPLAY_ROLES]
    if not any(role == "MainArtist" for _, role in artists):
        artists.insert(0, (release.artist.name, "MainArtist"))
    return artists


def _display_artist_name(artists: list[tuple[str, str]]) -> str:
    main = [n for n, r in artists if r == "MainArtist"]
    feat = [n for n, r in artists if r == "FeaturedArtist"]
    text = " & ".join(main)
    if feat:
        text += " feat. " + " & ".join(feat)
    return text


def _add_display_artists(el, artists, parties: _Parties) -> None:
    for seq, (name, role) in enumerate(artists, start=1):
        da = _sub(el, "DisplayArtist", SequenceNumber=seq)
        _sub(da, "ArtistPartyReference", parties.ref(name))
        _sub(da, "DisplayArtistRole", role)


def _parental(explicit: bool) -> str:
    return "Explicit" if explicit else "NotExplicit"


def _hash(parent, md5: str) -> None:
    hs = _sub(parent, "HashSum")
    _sub(hs, "Algorithm", "MD5")
    _sub(hs, "HashSumValue", md5)


def build_new_release_message(
    release: Release,
    ctx: MessageContext,
    audio_files: dict[int, ResourceFile],
    artwork: ResourceFile,
) -> bytes:
    """Return the ERN XML for `release`. `audio_files` is keyed by Track.id."""
    if not release.upc:
        raise ValueError("Release has no UPC")
    tracks = list(release.tracks)
    if not tracks:
        raise ValueError("Release has no tracks")

    parties = _Parties()
    label_ref = parties.ref(release.label_name)
    release_artists = [(release.artist.name, "MainArtist")]

    root = etree.Element(
        f"{{{ERN_NS}}}NewReleaseMessage",
        nsmap={"ern": ERN_NS, "xsi": XSI_NS},
        attrib={
            f"{{{XSI_NS}}}schemaLocation": SCHEMA_LOCATION,
            "LanguageAndScriptCode": release.language or "en",
            "AvsVersionId": "4",
        },
    )

    # --- MessageHeader -------------------------------------------------------
    header = _sub(root, "MessageHeader")
    _sub(header, "MessageThreadId", ctx.thread_id)
    _sub(header, "MessageId", ctx.message_id)
    sender = _sub(header, "MessageSender")
    _sub(sender, "PartyId", ctx.sender_party_id)
    _sub(_sub(sender, "PartyName"), "FullName", ctx.sender_name)
    recipient = _sub(header, "MessageRecipient")
    _sub(recipient, "PartyId", ctx.recipient_party_id)
    _sub(_sub(recipient, "PartyName"), "FullName", ctx.recipient_name)
    _sub(header, "MessageCreatedDateTime", ctx.created.strftime("%Y-%m-%dT%H:%M:%SZ"))
    _sub(header, "MessageControlType", "TestMessage" if ctx.test_message else "LiveMessage")

    # Parties are referenced before PartyList is written, so build the
    # resource/release sections first and insert PartyList afterwards.
    resource_list = etree.Element("ResourceList")
    release_list = etree.Element("ReleaseList")
    deal_list = etree.Element("DealList")

    # --- ResourceList: sound recordings -------------------------------------
    for idx, track in enumerate(tracks, start=1):
        if track.id not in audio_files:
            raise ValueError(f"Track {track.track_number} has no audio file")
        if not track.isrc:
            raise ValueError(f"Track {track.track_number} has no ISRC")
        artists = _track_artists(track, release)
        sr = _sub(resource_list, "SoundRecording")
        _sub(sr, "ResourceReference", f"A{idx}")
        _sub(sr, "Type", "MusicalWorkSoundRecording")
        edition = _sub(sr, "SoundRecordingEdition")
        _sub(_sub(edition, "ResourceId"), "ISRC", track.isrc)
        pline = _sub(edition, "PLine")
        _sub(pline, "Year", release.p_line_year)
        _sub(pline, "PLineText", f"℗ {release.p_line_year} {release.p_line}")
        if audio_files[track.id].uri:  # takedowns carry no files
            tech = _sub(edition, "TechnicalDetails")
            _sub(tech, "TechnicalResourceDetailsReference", f"T{idx}")
            dfile = _sub(tech, "DeliveryFile")
            _sub(dfile, "Type", "AudioFile")
            _sub(dfile, "AudioCodecType", track.audio_codec or "FLAC")
            f = _sub(dfile, "File")
            _sub(f, "URI", audio_files[track.id].uri)
            _hash(f, audio_files[track.id].md5)

        _sub(sr, "DisplayTitleText", _full_title(track.title, track.version))
        dt = _sub(sr, "DisplayTitle")
        _sub(dt, "TitleText", track.title)
        if track.version:
            _sub(dt, "SubTitle", track.version)
        _sub(sr, "DisplayArtistName", _display_artist_name(artists))
        _add_display_artists(sr, artists, parties)
        seq = 1
        for c in track.contributors:
            if c.role in DISPLAY_ROLES:
                continue
            ce = _sub(sr, "Contributor", SequenceNumber=seq)
            _sub(ce, "ContributorPartyReference", parties.ref(c.name))
            _sub(ce, "Role", c.role)
            seq += 1
        _sub(sr, "Duration", iso_duration(track.duration_seconds))
        _sub(sr, "ParentalWarningType", _parental(track.explicit))
        _sub(sr, "LanguageOfPerformance", release.language or "en")

    # --- ResourceList: cover art ---------------------------------------------
    img_ref = f"A{len(tracks) + 1}"
    img = _sub(resource_list, "Image")
    _sub(img, "ResourceReference", img_ref)
    _sub(img, "Type", "FrontCoverImage")
    _sub(_sub(img, "ResourceId"), "ProprietaryId", f"{release.upc}_cover", Namespace=f"DPID:{ctx.sender_party_id}")
    _sub(img, "ParentalWarningType", _parental(release.explicit))
    if artwork.uri:
        itech = _sub(img, "TechnicalDetails")
        _sub(itech, "TechnicalResourceDetailsReference", f"T{len(tracks) + 1}")
        ifile = _sub(itech, "File")
        _sub(ifile, "URI", artwork.uri)
        _hash(ifile, artwork.md5)

    # --- ReleaseList: main release -------------------------------------------
    rel = _sub(release_list, "Release")
    _sub(rel, "ReleaseReference", "R0")
    _sub(rel, "ReleaseType", release.release_type.value)
    _sub(_sub(rel, "ReleaseId"), "ICPN", release.upc)
    _sub(rel, "DisplayTitleText", _full_title(release.title, release.version))
    rdt = _sub(rel, "DisplayTitle")
    _sub(rdt, "TitleText", release.title)
    if release.version:
        _sub(rdt, "SubTitle", release.version)
    _sub(rel, "DisplayArtistName", _display_artist_name(release_artists))
    _add_display_artists(rel, release_artists, parties)
    _sub(rel, "ReleaseLabelReference", label_ref)
    pline = _sub(rel, "PLine")
    _sub(pline, "Year", release.p_line_year)
    _sub(pline, "PLineText", f"℗ {release.p_line_year} {release.p_line}")
    cline = _sub(rel, "CLine")
    _sub(cline, "Year", release.c_line_year)
    _sub(cline, "CLineText", f"© {release.c_line_year} {release.c_line}")
    _sub(rel, "Duration", iso_duration(sum(t.duration_seconds or 0 for t in tracks)))
    genre = _sub(rel, "Genre")
    _sub(genre, "GenreText", release.genre)
    if release.subgenre:
        _sub(genre, "SubGenre", release.subgenre)
    _sub(rel, "OriginalReleaseDate", (release.original_release_date or release.release_date).isoformat())
    _sub(rel, "ParentalWarningType", _parental(release.explicit or any(t.explicit for t in tracks)))
    group = _sub(rel, "ResourceGroup")
    _sub(group, "SequenceNumber", 1)
    for idx, _track in enumerate(tracks, start=1):
        item = _sub(group, "ResourceGroupContentItem")
        _sub(item, "SequenceNumber", idx)
        _sub(item, "ReleaseResourceReference", f"A{idx}")
    _sub(group, "LinkedReleaseResourceReference", img_ref)

    # --- ReleaseList: one TrackRelease per recording -------------------------
    for idx, track in enumerate(tracks, start=1):
        tr = _sub(release_list, "TrackRelease")
        _sub(tr, "ReleaseReference", f"R{idx}")
        _sub(_sub(tr, "ReleaseId"), "ISRC", track.isrc)
        _sub(tr, "ReleaseResourceReference", f"A{idx}")
        _sub(tr, "ReleaseLabelReference", label_ref)
        _sub(_sub(tr, "Genre"), "GenreText", release.genre)

    # --- DealList ------------------------------------------------------------
    territories = _territories(release.territories)
    today = date.today()
    for idx in range(len(tracks) + 1):
        rd = _sub(deal_list, "ReleaseDeal")
        _sub(rd, "DealReleaseReference", f"R{idx}")
        for model, use in ctx.deals:
            terms = _sub(_sub(rd, "Deal"), "DealTerms")
            _sub(terms, "CommercialModelType", model)
            _sub(terms, "UseType", use)
            for code in territories:
                _sub(terms, "TerritoryCode", code)
            vp = _sub(terms, "ValidityPeriod")
            _sub(vp, "StartDate", release.release_date.isoformat())
            if ctx.takedown:
                # Ending every deal is the standard way to pull a release.
                _sub(vp, "EndDate", today.isoformat())

    # --- PartyList (after collecting every reference) ------------------------
    party_list = _sub(root, "PartyList")
    for name, ref in parties.items():
        p = _sub(party_list, "Party")
        _sub(p, "PartyReference", ref)
        _sub(_sub(p, "PartyName"), "FullName", name)

    root.append(resource_list)
    root.append(release_list)
    root.append(deal_list)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _territories(raw: str) -> list[str]:
    codes = [c.strip().upper() for c in (raw or "").replace(";", ",").split(",") if c.strip()]
    if not codes or "WORLDWIDE" in codes:
        return ["Worldwide"]
    return codes
