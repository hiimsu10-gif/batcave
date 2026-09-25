from lxml import etree

from suprm.ddex.package import build_package
from suprm.media import md5_file
from suprm.qc import check_release

from .factories import make_release, make_user

NS = {"ern": "http://ddex.net/xml/ern/43"}


def _pkg(session, tmp_path, **kw):
    release = make_release(session, make_user(session))
    return release, build_package(release, out_root=tmp_path, recipient_party_id="PADPIDA2011021601U",
                                  recipient_name="Test Store", test_message=True, **kw)


def test_release_passes_qc(session):
    release = make_release(session, make_user(session))
    report = check_release(release, require_codes=True)
    assert report.ok, report.errors


def test_package_layout_and_xml(session, tmp_path):
    release, pkg = _pkg(session, tmp_path)
    assert pkg.xml_path == tmp_path / pkg.batch_id / release.upc / f"{release.upc}.xml"
    assert pkg.batch_complete_path.name == f"BatchComplete_{pkg.batch_id}.xml"
    root = etree.parse(str(pkg.xml_path)).getroot()
    assert root.tag == "{http://ddex.net/xml/ern/43}NewReleaseMessage"

    assert root.findtext("MessageHeader/MessageControlType") == "TestMessage"
    assert root.findtext("MessageHeader/MessageRecipient/PartyId") == "PADPIDA2011021601U"
    assert root.findtext("ReleaseList/Release/ReleaseId/ICPN") == release.upc
    assert root.findtext("ReleaseList/Release/ReleaseType") == "EP"
    assert [e.text for e in root.findall("ResourceList/SoundRecording/SoundRecordingEdition/ResourceId/ISRC")] == [
        "USSU12600001", "USSU12600002"]
    assert root.findtext("ResourceList/SoundRecording/DisplayArtistName") == "Nova Kai feat. Jordan Lee"
    assert root.findtext("ResourceList/SoundRecording/Duration") == "PT0M3S"
    assert len(root.findall("ReleaseList/TrackRelease")) == 2
    assert len(root.findall("DealList/ReleaseDeal")) == 3  # main release + 2 tracks

    # Every party reference used is declared in PartyList
    declared = {p.findtext("PartyReference") for p in root.findall("PartyList/Party")}
    used = {e.text for e in root.iter("ArtistPartyReference", "ContributorPartyReference", "ReleaseLabelReference")}
    assert used <= declared

    # File hashes in the XML match the files in the package
    for f in root.iter("File"):
        path = pkg.release_dir / f.findtext("URI")
        assert path.exists()
        assert f.findtext("HashSum/HashSumValue") == md5_file(path)


def test_takedown_ends_deals_and_ships_no_files(session, tmp_path):
    _, pkg = _pkg(session, tmp_path, takedown=True)
    root = etree.parse(str(pkg.xml_path)).getroot()
    assert all(vp.findtext("EndDate") for vp in root.iter("ValidityPeriod"))
    assert not list(root.iter("File"))
    assert not any((pkg.release_dir / "resources").iterdir())
