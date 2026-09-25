"""Settings loaded from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./suprm.db"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-insecure-secret"))
    media_root: Path = field(default_factory=lambda: Path(_env("MEDIA_ROOT", "./media")))
    outbox_root: Path = field(default_factory=lambda: Path(_env("OUTBOX_ROOT", "./outbox")))
    base_url: str = field(default_factory=lambda: _env("BASE_URL", "http://localhost:8000"))

    platform_commission_percent: Decimal = field(
        default_factory=lambda: Decimal(_env("PLATFORM_COMMISSION_PERCENT", "0"))
    )
    min_payout_usd: Decimal = field(default_factory=lambda: Decimal(_env("MIN_PAYOUT_USD", "10.00")))

    ddex_party_id: str = field(default_factory=lambda: _env("DDEX_PARTY_ID", "PADPIDA0000000000X"))
    ddex_party_name: str = field(default_factory=lambda: _env("DDEX_PARTY_NAME", "Suprm Sounds"))
    default_label_name: str = field(default_factory=lambda: _env("DEFAULT_LABEL_NAME", "Suprm Sounds"))

    upc_company_prefix: str = field(default_factory=lambda: _env("UPC_COMPANY_PREFIX"))
    isrc_country: str = field(default_factory=lambda: _env("ISRC_COUNTRY", "US"))
    isrc_registrant: str = field(default_factory=lambda: _env("ISRC_REGISTRANT"))

    stripe_secret_key: str = field(default_factory=lambda: _env("STRIPE_SECRET_KEY"))
    stripe_webhook_secret: str = field(default_factory=lambda: _env("STRIPE_WEBHOOK_SECRET"))

    # File storage: "local" (MEDIA_ROOT on disk) or "s3" (AWS S3, Cloudflare R2, Backblaze B2...)
    storage_backend: str = field(default_factory=lambda: _env("STORAGE_BACKEND", "local"))
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET"))
    s3_endpoint_url: str = field(default_factory=lambda: _env("S3_ENDPOINT_URL"))  # R2: https://<acct>.r2.cloudflarestorage.com
    s3_region: str = field(default_factory=lambda: _env("S3_REGION", "auto"))
    s3_access_key_id: str = field(default_factory=lambda: _env("S3_ACCESS_KEY_ID"))
    s3_secret_access_key: str = field(default_factory=lambda: _env("S3_SECRET_ACCESS_KEY"))

    # Email: "console" (prints to the log), "smtp", or "resend"
    email_backend: str = field(default_factory=lambda: _env("EMAIL_BACKEND", "console"))
    email_from: str = field(default_factory=lambda: _env("EMAIL_FROM", "Suprm Sounds <hello@suprmsounds.com>"))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "587")))
    smtp_username: str = field(default_factory=lambda: _env("SMTP_USERNAME"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    resend_api_key: str = field(default_factory=lambda: _env("RESEND_API_KEY"))

    # Jobs: run deliveries inside the web request (handy locally) or in `suprm worker`
    jobs_inline: bool = field(default_factory=lambda: _env("JOBS_INLINE", "false").lower() == "true")
    require_admin_2fa: bool = field(default_factory=lambda: _env("REQUIRE_ADMIN_2FA", "true").lower() == "true")

    # Legal pages: filled into the policy templates
    legal_entity_name: str = field(default_factory=lambda: _env("LEGAL_ENTITY_NAME", "Suprm Sounds LLC"))
    legal_state: str = field(default_factory=lambda: _env("LEGAL_STATE", "[STATE]"))
    legal_address: str = field(default_factory=lambda: _env("LEGAL_ADDRESS", "[BUSINESS ADDRESS]"))
    support_email: str = field(default_factory=lambda: _env("SUPPORT_EMAIL", "support@suprmsounds.com"))
    legal_version: str = field(default_factory=lambda: _env("LEGAL_VERSION", "2026-09-25"))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
