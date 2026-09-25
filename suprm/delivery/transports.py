"""Transports move a built DDEX batch to a delivery target.

    local  - copy into a folder (testing, or manual upload to a portal)
    sftp   - the standard for direct DSP feeds (Spotify, Apple, Amazon ...)
    s3     - stores that give you an S3 drop bucket (e.g. some YouTube / TikTok feeds)
    http   - white-label backends (FUGA, Revelator, SonoSuite ...) that take
             packages over an HTTP API. Each vendor's API differs; this
             generic adapter POSTs a zip, and a vendor-specific subclass
             can override `send`.

Every transport uploads BatchComplete_*.xml last.
"""
from __future__ import annotations

import base64
import posixpath
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from ..ddex.package import BuiltPackage


class TransportError(RuntimeError):
    pass


class Transport(Protocol):
    def send(self, package: BuiltPackage) -> str:
        """Deliver the package and return a remote reference (path/URL/id)."""


def _files_in_order(package: BuiltPackage) -> list[Path]:
    files = [p for p in sorted(package.batch_dir.rglob("*")) if p.is_file()]
    files.remove(package.batch_complete_path)
    files.append(package.batch_complete_path)
    return files


class LocalTransport:
    def __init__(self, path: str) -> None:
        self.root = Path(path)

    def send(self, package: BuiltPackage) -> str:
        dest = self.root / package.batch_id
        for f in _files_in_order(package):
            target = dest / f.relative_to(package.batch_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, target)
        return str(dest)


class SFTPTransport:
    def __init__(self, host: str, username: str, port: int = 22, password: str | None = None,
                 key_path: str | None = None, remote_dir: str = "/", host_key: str | None = None) -> None:
        self.host, self.port, self.username = host, int(port), username
        self.password, self.key_path = password, key_path
        self.remote_dir, self.host_key = remote_dir, host_key

    def send(self, package: BuiltPackage) -> str:
        import paramiko

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.host_key:
            # "ssh-ed25519 AAAA..." as given by the store's onboarding team
            key_type, key_b64 = self.host_key.split()[:2]
            key = paramiko.PKey.from_type_string(key_type, base64.b64decode(key_b64))
            name = self.host if self.port == 22 else f"[{self.host}]:{self.port}"
            client.get_host_keys().add(name, key_type, key)
        # Never trust an unknown server with release files.
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(self.host, port=self.port, username=self.username,
                           password=self.password, key_filename=self.key_path, timeout=30)
            sftp = client.open_sftp()
            base = posixpath.join(self.remote_dir, package.batch_id)
            for f in _files_in_order(package):
                rel = f.relative_to(package.batch_dir).as_posix()
                remote = posixpath.join(base, rel)
                _sftp_makedirs(sftp, posixpath.dirname(remote))
                sftp.put(str(f), remote)
            sftp.close()
            return f"sftp://{self.host}{base}"
        except Exception as exc:  # paramiko raises many types
            raise TransportError(f"SFTP delivery to {self.host} failed: {exc}") from exc
        finally:
            client.close()


def _sftp_makedirs(sftp, path: str) -> None:
    parts = []
    while path not in ("", "/"):
        parts.append(path)
        path = posixpath.dirname(path)
    for p in reversed(parts):
        try:
            sftp.stat(p)
        except OSError:
            sftp.mkdir(p)


class S3Transport:
    def __init__(self, bucket: str, prefix: str = "", region: str | None = None,
                 access_key_id: str | None = None, secret_access_key: str | None = None) -> None:
        self.bucket, self.prefix, self.region = bucket, prefix.strip("/"), region
        self.access_key_id, self.secret_access_key = access_key_id, secret_access_key

    def send(self, package: BuiltPackage) -> str:
        import boto3

        s3 = boto3.client("s3", region_name=self.region, aws_access_key_id=self.access_key_id,
                          aws_secret_access_key=self.secret_access_key)
        base = "/".join(p for p in (self.prefix, package.batch_id) if p)
        try:
            for f in _files_in_order(package):
                s3.upload_file(str(f), self.bucket, f"{base}/{f.relative_to(package.batch_dir).as_posix()}")
        except Exception as exc:
            raise TransportError(f"S3 delivery to {self.bucket} failed: {exc}") from exc
        return f"s3://{self.bucket}/{base}"


class HTTPTransport:
    """Generic white-label backend adapter: POST the batch as a zip."""

    def __init__(self, url: str, api_key: str, auth_header: str = "Authorization",
                 auth_scheme: str = "Bearer", timeout: int = 300) -> None:
        self.url, self.api_key = url, api_key
        self.auth_header, self.auth_scheme, self.timeout = auth_header, auth_scheme, timeout

    def send(self, package: BuiltPackage) -> str:
        import httpx

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = shutil.make_archive(str(Path(tmp) / package.batch_id), "zip", package.batch_dir)
            token = f"{self.auth_scheme} {self.api_key}".strip()
            with open(zip_path, "rb") as fh:
                try:
                    resp = httpx.post(
                        self.url,
                        headers={self.auth_header: token},
                        files={"package": (f"{package.batch_id}.zip", fh, "application/zip")},
                        data={"batch_id": package.batch_id, "message_id": package.message_id},
                        timeout=self.timeout,
                    )
                except httpx.HTTPError as exc:
                    raise TransportError(f"HTTP delivery failed: {exc}") from exc
        if resp.status_code >= 300:
            raise TransportError(f"HTTP delivery rejected ({resp.status_code}): {resp.text[:500]}")
        try:
            return str(resp.json().get("id") or resp.json().get("reference") or package.batch_id)
        except ValueError:
            return package.batch_id


TRANSPORTS = {
    "local": LocalTransport,
    "sftp": SFTPTransport,
    "s3": S3Transport,
    "http": HTTPTransport,
}


def make_transport(kind: str, config: dict) -> Transport:
    try:
        cls = TRANSPORTS[kind]
    except KeyError:
        raise TransportError(f"Unknown transport '{kind}'") from None
    return cls(**config)
