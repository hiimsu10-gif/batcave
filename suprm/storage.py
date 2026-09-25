"""Where uploaded audio and artwork live.

    local - files under MEDIA_ROOT (development, or a single server with a disk)
    s3    - any S3-compatible bucket: AWS S3, Cloudflare R2 (no egress fees,
            recommended for large WAVs), Backblaze B2, DigitalOcean Spaces

Keys look like "<user_id>/<uuid>.wav" and are what the database stores.
"""
from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from fastapi.responses import FileResponse, RedirectResponse, Response

from .config import settings


class Storage(Protocol):
    def put(self, local_path: Path, key: str) -> None: ...
    def fetch(self, key: str, dest: Path) -> None: ...
    def delete(self, key: str) -> None: ...
    def serve(self, key: str) -> Response: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Invalid storage key")
        return path

    def put(self, local_path: Path, key: str) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(local_path), dest)

    def fetch(self, key: str, dest: Path) -> None:
        shutil.copyfile(self._path(key), dest)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def serve(self, key: str) -> Response:
        return FileResponse(self._path(key))


class S3Storage:
    def __init__(self, bucket: str, endpoint_url: str | None, region: str | None,
                 access_key_id: str | None, secret_access_key: str | None) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region or None,
                                   aws_access_key_id=access_key_id or None,
                                   aws_secret_access_key=secret_access_key or None)

    def put(self, local_path: Path, key: str) -> None:
        self.client.upload_file(str(local_path), self.bucket, key)
        local_path.unlink(missing_ok=True)

    def fetch(self, key: str, dest: Path) -> None:
        self.client.download_file(self.bucket, key, str(dest))

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def serve(self, key: str) -> Response:
        # Short-lived signed link, so files stay private to their owner and admins
        url = self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key},
                                                 ExpiresIn=300)
        return RedirectResponse(url, status_code=302)


@lru_cache
def get_storage() -> Storage:
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 needs S3_BUCKET")
        return S3Storage(settings.s3_bucket, settings.s3_endpoint_url, settings.s3_region,
                         settings.s3_access_key_id, settings.s3_secret_access_key)
    settings.media_root.mkdir(parents=True, exist_ok=True)
    return LocalStorage(settings.media_root)
