"""Uvicorn import target."""

from brandpilot.settings import AppSettings

from .app import create_app


app = create_app(AppSettings.from_env())
