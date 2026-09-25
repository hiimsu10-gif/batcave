"""Build a DDEX delivery batch on disk.

Layout (DDEX ERN Choreography, SFTP/S3 "batched" profile, which most
stores use):

    <batch_id>/
        <UPC>/
            <UPC>.xml
            resources/
                <UPC>_01_001.flac
                <UPC>.jpg
        BatchComplete_<batch_id>.xml

A transport uploads the whole folder and writes BatchComplete last, which
tells the store the batch is fully uploaded and safe to ingest.
"""
from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from ..media import md5_file
from ..models import Release
from .ern import MessageContext, ResourceFile, build_new_release_message


@dataclass
class BuiltPackage:
    batch_id: str
    message_id: str
    batch_dir: Path
    release_dir: Path
    xml_path: Path
    batch_complete_path: Path


def new_batch_id() -> str:
    # 17-digit timestamp, the de facto convention for batch folder names
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"


def build_package(
    release: Release,
    *,
    out_root: Path,
    recipient_party_id: str,
    recipient_name: str,
    test_message: bool,
    takedown: bool = False,
    media_root: Path | None = None,
) -> BuiltPackage:
    media_root = media_root or settings.media_root
    batch_id = new_batch_id()
    message_id = uuid.uuid4().hex
    batch_dir = out_root / batch_id
    release_dir = batch_dir / release.upc
    res_dir = release_dir / "resources"
    res_dir.mkdir(parents=True, exist_ok=True)

    audio: dict[int, ResourceFile] = {}
    artwork = ResourceFile(uri="", md5="")
    if not takedown:
        for track in release.tracks:
            if not track.audio_path:
                raise ValueError(f"Track {track.track_number} has no audio")
            src = media_root / track.audio_path
            ext = src.suffix.lower() or ".flac"
            name = f"{release.upc}_01_{track.track_number:03d}{ext}"
            shutil.copyfile(src, res_dir / name)
            audio[track.id] = ResourceFile(uri=f"resources/{name}", md5=md5_file(res_dir / name))
        if not release.artwork_path:
            raise ValueError("Release has no artwork")
        art_src = media_root / release.artwork_path
        art_name = f"{release.upc}{art_src.suffix.lower() or '.jpg'}"
        shutil.copyfile(art_src, res_dir / art_name)
        artwork = ResourceFile(uri=f"resources/{art_name}", md5=md5_file(res_dir / art_name))
    else:
        # Takedowns carry metadata only; stores match on UPC/ISRC.
        for track in release.tracks:
            audio[track.id] = ResourceFile(uri="", md5="")

    ctx = MessageContext(
        message_id=message_id,
        thread_id=message_id,
        sender_party_id=settings.ddex_party_id,
        sender_name=settings.ddex_party_name,
        recipient_party_id=recipient_party_id,
        recipient_name=recipient_name,
        test_message=test_message,
        takedown=takedown,
    )
    xml = build_new_release_message(release, ctx, audio, artwork)
    xml_path = release_dir / f"{release.upc}.xml"
    xml_path.write_bytes(xml)

    batch_complete = batch_dir / f"BatchComplete_{batch_id}.xml"
    batch_complete.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<BatchComplete><BatchId>{batch_id}</BatchId>"
        f"<MessageSender>{settings.ddex_party_id}</MessageSender>"
        f"<NumberOfMessages>1</NumberOfMessages></BatchComplete>\n"
    )
    return BuiltPackage(batch_id, message_id, batch_dir, release_dir, xml_path, batch_complete)
