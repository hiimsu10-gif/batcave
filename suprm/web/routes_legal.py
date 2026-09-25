"""Legal pages rendered from suprm/legal/*.md with the company details filled in."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import markdown
from fastapi import APIRouter, HTTPException, Request
from jinja2 import Template
from markupsafe import Markup

from ..config import settings
from .app import render

router = APIRouter()

LEGAL_DIR = Path(__file__).resolve().parent.parent / "legal"
PAGES = {
    "terms": "Terms of Service",
    "artist-agreement": "Artist Distribution Agreement",
    "privacy": "Privacy Policy",
    "content-policy": "Content & Fraud Policy",
}


@lru_cache
def legal_html(slug: str) -> str:
    source = (LEGAL_DIR / f"{slug}.md").read_text()
    filled = Template(source).render(
        entity=settings.legal_entity_name, state=settings.legal_state, address=settings.legal_address,
        email=settings.support_email, version=settings.legal_version,
    )
    return markdown.markdown(filled, extensions=["tables"])


@router.get("/legal/{slug}")
def legal_page(slug: str, request: Request):
    if slug not in PAGES:
        raise HTTPException(404)
    return render(request, "legal.html", title=PAGES[slug], body=Markup(legal_html(slug)), pages=PAGES, slug=slug)
