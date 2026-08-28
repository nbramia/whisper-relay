"""Test-only environment defaults, imported first by conftest.py.

LIFEOS_BASE_URL is required with no default (#49). `voice_gateway.main` builds
a module-level `app` on import (the uvicorn entrypoint `voice_gateway.main:app`
needs a ready ASGI instance), so importing it — as conftest.py does — needs
LIFEOS_BASE_URL present in the environment *before* that import runs. This sets
a test-only fallback so `pytest` doesn't require every invocation to export it;
per-test behavior is governed by the `_lifeos_base_url_default` fixture in
conftest.py, not this module.
"""

from __future__ import annotations

import os

os.environ.setdefault("LIFEOS_BASE_URL", "http://127.0.0.1:8000")
