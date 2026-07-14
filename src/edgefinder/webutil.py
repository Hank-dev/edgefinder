from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .config import get_settings

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

# Regenerated on every process start; the feedback form only needs to prove the
# request came from a page this instance rendered, never from a stored secret.
CSRF_TOKEN = secrets.token_hex(32)


def template_context(request: Request, **items: Any) -> dict[str, Any]:
    return {"request": request, "app_name": get_settings().app_name, "csrf_token": CSRF_TOKEN, **items}
