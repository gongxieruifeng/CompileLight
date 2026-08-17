"""ASGI entry point for `uvicorn reduce_token_agent.main:app`."""

from pathlib import Path

from reduce_token_agent.api.app import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
app = create_app(PROJECT_ROOT)
