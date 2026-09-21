"""The FastAPI application and its wire models.

`api/` never imports a `pipeline/` **stage** (ADR-071): it writes rows and enqueues jobs,
and the worker does the work. It may read the pure leaves the allow-list in
``tests/test_architecture.py`` names, and nothing else under `pipeline/`.
"""

from greenlight_ai.api.app import API_PREFIX, create_app

__all__ = ["API_PREFIX", "create_app"]
