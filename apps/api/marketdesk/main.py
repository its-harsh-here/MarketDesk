"""ASGI entry point: ``uvicorn marketdesk.main:app``."""

from marketdesk.api.app import create_app

app = create_app()
