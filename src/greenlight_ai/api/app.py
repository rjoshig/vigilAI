"""The FastAPI application.

`api` accepts requests, validates uploads, writes rows, and enqueues jobs. It never
parses a file and never calls the model: that is the worker's job, and keeping the split
means a slow model can never make the UI unresponsive (``docs/architecture.md``).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Final, Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from greenlight_ai.api.deps import get_db_settings, get_llm_settings
from greenlight_ai.api.routers import (
    admin,
    appearance,
    chat,
    coverage,
    explore,
    meaning,
    auth,
    configs,
    findings,
    reports,
    runs,
    settings as settings_router,
    training,
    users,
)
from greenlight_ai.auth.accounts import (
    DefaultPasswordInUse,
    bootstrap_admin_uses_default_password,
    ensure_bootstrap,
    ensure_placeholder,
)
from greenlight_ai.auth.settings import AuthSettings
from greenlight_ai.db.cache import DbCache
from greenlight_ai.db.session import create_all, create_engine, healthcheck, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.llm.settings import LLMSettings

__all__ = ["create_app", "API_PREFIX"]

_LOG: Final = logging.getLogger(__name__)

API_PREFIX: Final[str] = "/api/v1"


#: The pair a checkout serves on, so `npm run dev` in both UIs works with no `.env`
#: at all. A deployment on any real hostname replaces them.
_DEV_ORIGINS: Final[tuple[str, ...]] = ("http://localhost:3000", "http://localhost:3001")


def cors_origins(environ: Mapping[str, str] | None = None) -> list[str]:
    """Which origins a browser may call this API from.

    Read from the environment and **not** from the settings table, for the reason the
    bind address is not: this middleware is added when the app is built, so a value the
    console could change at runtime would be one the running process could not honour
    (ADR-023).

    It was read from nowhere at all. The list was a string literal that was then split
    on commas — the shape a value takes when an environment read has been inlined —
    while `docs/deployment.md` went on telling a deployment to set
    ``GREENLIGHT_AI_CORS_ORIGINS``. Anything served from a real hostname, which is what
    that document's own reverse-proxy section describes, therefore set the variable,
    restarted, and watched the API refuse its own two UIs.

    Args:
        environ: The environment to read, defaulting to the real one. Injectable so a
            test never has to mutate the process environment.

    Returns:
        The origins in the order given, or the development pair when nothing is set.
    """
    source = os.environ if environ is None else environ
    raw = source.get("GREENLIGHT_AI_CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEV_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(
    settings: DbSettings | None = None,
    llm_settings: LLMSettings | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastAPI:
    """Build the application.

    Args:
        settings: Database settings; read from the environment when omitted. Injectable
            so tests get their own SQLite file without touching the environment.
        llm_settings: Adapter settings, used only by the admin check-drafting endpoint.
            The api makes no other model call.
        auth_settings: The authentication switches, both off when omitted (ADR-022).

    Returns:
        The configured app.
    """
    resolved = settings or get_db_settings()
    resolved_llm = llm_settings or get_llm_settings()
    resolved_auth = auth_settings or AuthSettings.from_env()
    engine = create_engine(resolved)
    factory = session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Ensure the schema exists, then serve.

        Args:
            app: The application.

        Yields:
            Control, for the lifetime of the process.

        Raises:
            DefaultPasswordInUse: When admin login is on, the bootstrap password is
                still the documented default, and the server is not on loopback. A
                warning is easy to miss and this is the one credential everybody
                knows, so a real deployment refuses to serve until it is changed
                (ADR-022).
        """
        create_all(engine)
        with factory() as bootstrap_session:
            ensure_placeholder(bootstrap_session)
            if resolved_auth.admin_auth:
                ensure_bootstrap(bootstrap_session)
            bootstrap_session.commit()

            if resolved_auth.admin_auth and bootstrap_admin_uses_default_password(
                bootstrap_session
            ):
                if resolved_auth.is_loopback:
                    _LOG.warning(
                        "the bootstrap administrator still has the default password; "
                        "change it at first sign-in"
                    )
                else:
                    raise DefaultPasswordInUse(
                        "refusing to serve: admin login is on, the bootstrap password "
                        f"is unchanged, and the bind address {resolved_auth.bind_host!r} "
                        "is not loopback. Sign in locally and change it first."
                    )

        _LOG.info("api ready (database=%s)", resolved.backend)
        yield
        engine.dispose()

    app = FastAPI(
        title="Greenlight AI",
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
    app.state.auth_settings = resolved_auth
    # Whether the admin console's stored overrides apply on top of the environment
    # (ADR-023). A test that wants a fixed environment turns it off.
    app.state.runtime_settings = True
    app.state.llm_cache_backend = DbCache(factory)
    # Injectable so a test can render a PDF without launching a browser; None means
    # the default Playwright renderer (greenlight_ai/report/pdf.py).
    app.state.pdf_renderer = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        auth.router,
        runs.router,
        findings.router,
        configs.router,
        reports.router,
        admin.router,
        users.router,
        settings_router.router,
        training.router,
        appearance.router,
        appearance.notices_router,
        meaning.router,
        coverage.router,
        explore.router,
        chat.router,
    ):
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
