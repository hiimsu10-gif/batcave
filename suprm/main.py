"""ASGI entry point: `uvicorn suprm.main:app`."""
from .web.app import create_app

app = create_app()
