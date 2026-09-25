"""Time-based one-time passwords (RFC 6238) for admin two-factor login.

Works with Google Authenticator, 1Password, Authy, etc.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from urllib.parse import quote


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def current_code(secret: str, at: float | None = None) -> str:
    return _code(secret, int((at or time.time()) // 30))


def verify(secret: str, code: str, at: float | None = None, window: int = 1) -> bool:
    code = (code or "").replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return False
    step = int((at or time.time()) // 30)
    return any(hmac.compare_digest(_code(secret, step + d), code) for d in range(-window, window + 1))


def provisioning_uri(secret: str, email: str, issuer: str = "Suprm Sounds") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}"


def qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    return svg[svg.index("<svg"):]
