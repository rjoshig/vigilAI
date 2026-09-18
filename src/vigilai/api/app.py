"""The FastAPI application.

`api` accepts requests, validates uploads, writes rows, and enqueues jobs. It never
parses a file and never calls the model: that is the worker's job, and keeping the split
means a slow model can never make the UI unresponsive (``docs/architecture.md``).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vigilai.api.deps import get_db_settings, get_llm_settings
from vigilai.api.routers import admin, configs, findings, runs
from vigilai.db.cache import DbCache
from vigilai.db.session import create_all, create_engine, healthcheck, session_factory
from vigilai.db.settings import DbSettings
from vigilai.llm.settings import LLMSettings

__all__ = ["create_app", "API_PREFIX"]

_LOG: Final = logging.getLogger(__name__)

API_PREFIX: Final[str] = "/api/v1"


def create_app(
    settings: DbSettings | None = None, llm_settings: LLMSettings | None = None
) -> FastAPI:
    """Build the application.

    Args:
        settings: Database settings; read from the environment when omitted. Injectable
            so tests get their own SQLite file without touching the environment.
        llm_settings: Adapter settings, used only by the admin check-drafting endpoint.
            The api makes no other model call.

    Returns:
        The configured app.
    """
    resolved = settings or get_db_settings()
    resolved_llm = llm_settings or get_llm_settings()
    engine = create_engine(resolved)
    factory = session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Ensure the schema exists, then serve.

        Args:
            app: The application.

        Yields:
            Control, for the lifetime of the process.
        """
        create_all(engine)
        _LOG.info("api ready (database=%s)", resolved.backend)
        yield
        engine.dispose()

    app = FastAPI(
        title="vigilAI",
        version="0.1.0",
        description=(
            "QC validation for a credit-data fulfillment process: the OSL requirement "
            "spec, the ETL config, and the output reports, reconciled."
        ),
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.is_sqlite = resolved.is_sqlite
    app.state.data_dir = resolved.data_dir
    app.state.llm_settings = resolved_llm
    app.state.llm_cache_backend = DbCache(factory)

    origins = [
        origin.strip()
        for origin in "http://localhost:3000,http://localhost:3001".split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (runs.router, findings.router, configs.router, admin.router):
        app.include_router(router, prefix=API_PREFIX)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, object]:
        """Report whether the service can reach its database.

        Returns:
            The service status and which backend it is using.
        """
        ok = healthcheck(engine)
        return {"status": "ok" if ok else "degraded", "database": resolved.backend}

    return app


app = None  # set by the ASGI entry point below


def get_app() -> FastAPI:
    """Build the app for an ASGI server.

    Returns:
        The application, created once per process.
    """
    global app  # noqa: PLW0603 - the ASGI contract wants a module-level app
    if app is None:
        app = create_app()
    return app
