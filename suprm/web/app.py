from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ..config import settings
from ..db import init_db
from .deps import LoginRequired, csrf_token

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))


def _money(value) -> str:
    value = Decimal(value or 0)
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _pct(value) -> str:
    text = f"{Decimal(value or 0):f}"
    return (text.rstrip("0").rstrip(".") if "." in text else text) + "%"


def _pop_flash(request: Request) -> list:
    return request.session.pop("flash", [])


templates.env.filters["money"] = _money
templates.env.filters["pct"] = _pct
templates.env.globals["csrf_token"] = csrf_token
templates.env.globals["pop_flash"] = _pop_flash


def render(request: Request, name: str, **ctx):
    ctx.setdefault("user", getattr(request.state, "user", None))
    return templates.TemplateResponse(request, name, ctx)


def create_app(create_tables: bool = True) -> FastAPI:
    if create_tables:
        init_db()
    settings.media_root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Suprm Sounds", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=settings.base_url.startswith("https"),
        max_age=60 * 60 * 24 * 14,
    )
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.exception_handler(LoginRequired)
    async def _login_redirect(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

    from . import routes_admin, routes_artist, routes_auth, routes_payouts

    app.include_router(routes_auth.router)
    app.include_router(routes_artist.router)
    app.include_router(routes_payouts.router)
    app.include_router(routes_admin.router, prefix="/admin")
    return app
