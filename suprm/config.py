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


settings = Settings()
