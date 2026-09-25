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
from .deps import LoginRequired, TwoFactorSetupRequired, csrf_token

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
templates.env.globals["settings"] = settings


def render(request: Request, name: str, **ctx):
    ctx.setdefault("user", getattr(request.state, "user", None))
    return templates.TemplateResponse(request, name, ctx)


def create_app(create_tables: bool | None = None) -> FastAPI:
    # SQLite (local dev) creates tables automatically; Postgres uses `suprm migrate`.
    if settings.is_sqlite if create_tables is None else create_tables:
        init_db()

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

    @app.exception_handler(TwoFactorSetupRequired)
    async def _2fa_redirect(request: Request, exc: TwoFactorSetupRequired):
        return RedirectResponse("/account?setup2fa=1", status_code=303)

    from . import routes_account, routes_admin, routes_artist, routes_auth, routes_legal, routes_payouts

    app.include_router(routes_auth.router)
    app.include_router(routes_account.router)
    app.include_router(routes_legal.router)
    app.include_router(routes_artist.router)
    app.include_router(routes_payouts.router)
    app.include_router(routes_admin.router, prefix="/admin")
    return app
