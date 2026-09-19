"""The FastAPI application and its wire models.

`api/` never imports `pipeline/` (``docs/architecture.md``): it writes rows and enqueues
jobs, and the worker does the work.
"""

from greenlight_ai.api.app import API_PREFIX, create_app

__all__ = ["API_PREFIX", "create_app"]
