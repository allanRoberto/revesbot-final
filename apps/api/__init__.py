from __future__ import annotations

from typing import Any

__all__ = ["app", "create_app"]


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from api.app import create_app

        return create_app
    if name == "app":
        from api.main import app

        return app
    raise AttributeError(name)
