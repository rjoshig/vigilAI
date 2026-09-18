"""The stage cache and the call log, backed by the database.

Phase 2 kept these in SQLite or memory behind :class:`~vigilai.llm.cache.CacheBackend`;
this is the same interface over the ``llm_cache`` table, so the pipeline does not change
when the service starts (ADR-005). Entries hold no sample rows, because prompts never
carry them (ADR-003).
"""

from __future__ import annotations

import logging
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from vigilai.db.models import LlmCacheEntry, LlmCall
from vigilai.db.session import session_scope
from vigilai.llm.cache import CacheEntry
from vigilai.llm.client import CallLog

__all__ = ["DbCache", "record_calls"]

_LOG: Final = logging.getLogger(__name__)


class DbCache:
    """A :class:`~vigilai.llm.cache.CacheBackend` over the ``llm_cache`` table.

    Each operation takes its own short transaction rather than joining the caller's.
    A cache write must not be rolled back by an unrelated failure later in the run: the
    model was already called, and losing the entry would mean calling it again.
    """

    def __init__(self, factory: sessionmaker[Session]) -> None:
        """Initialise the backend.

        Args:
            factory: The session factory.
        """
        self._factory = factory

    def get(self, key: str) -> CacheEntry | None:
        """Look up an entry and count the hit.

        Args:
            key: The cache key.

        Returns:
            The entry, or ``None`` on a miss.
        """
        with session_scope(self._factory) as session:
            row = session.get(LlmCacheEntry, key)
            if row is None:
                return None
            row.hits += 1
            return CacheEntry(
                key=row.key,
                stage=row.stage,
                text=row.text,
                data=row.data,
                created_at=row.created_at.timestamp(),
                hits=row.hits,
            )

    def put(self, entry: CacheEntry) -> None:
        """Store an entry, replacing any existing one for the same key.

        Args:
            entry: The entry to store.
        """
        with session_scope(self._factory) as session:
            row = session.get(LlmCacheEntry, entry.key)
            if row is None:
                session.add(
                    LlmCacheEntry(
                        key=entry.key,
                        stage=entry.stage,
                        text=entry.text,
                        data=dict(entry.data) if entry.data is not None else None,
                        hits=entry.hits,
                    )
                )
            else:
                row.stage = entry.stage
                row.text = entry.text
                row.data = dict(entry.data) if entry.data is not None else None


def record_calls(session: Session, call_log: CallLog, run_id: int | None) -> int:
    """Persist a run's call statistics into ``llm_calls``.

    Args:
        session: An open session.
        call_log: The in-memory log the adapter filled.
        run_id: The run these calls belong to.

    Returns:
        How many rows were written. Ids and counts only; no prompt text (ADR-003).
    """
    for record in call_log.records:
        session.add(
            LlmCall(
                run_id=run_id,
                stage=record.stage,
                provider=record.provider,
                model=record.model,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                latency_ms=record.latency_ms,
                retries=record.retries,
                ok=record.ok,
                cached=record.cached,
                error=record.error,
            )
        )
    return len(call_log.records)


def purge_expired_cache(session: Session, older_than_days: int) -> int:
    """Delete cache entries past the retention window.

    Args:
        session: An open session.
        older_than_days: The window, matching ``runs.expires_at``.

    Returns:
        How many entries were deleted.
    """
    import datetime as dt

    from vigilai.db.types import utcnow

    cutoff = utcnow() - dt.timedelta(days=older_than_days)
    result = session.execute(sa.delete(LlmCacheEntry).where(LlmCacheEntry.created_at < cutoff))
    return int(result.rowcount)  # type: ignore[attr-defined]
