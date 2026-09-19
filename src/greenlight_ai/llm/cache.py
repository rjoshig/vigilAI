"""The stage cache: the same content is never sent to the model twice (ADR-005).

The key is ``sha256(canonical content) + model + prompt version``, so changing the model
or a prompt refreshes results and nothing else does. The cache is checked before every
call, and a miss is the only path to the network.

Phase 2 stores entries in SQLite behind :class:`CacheBackend`; Phase 3 swaps in Postgres
without the pipeline noticing. Entries hold no sample rows, because prompts never carry
them in the first place (``docs/llm-privacy.md``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Protocol

__all__ = ["CacheEntry", "CacheBackend", "MemoryCache", "SqliteCache", "cache_key", "LLMCache"]

_LOG: Final = logging.getLogger(__name__)


def cache_key(content: str, model: str, prompt_version: str) -> str:
    """Compute the cache key for one call.

    Args:
        content: The canonical content of the call: the system and user prompts joined.
        model: The model name. Part of the key so switching models refreshes results.
        prompt_version: The prompt template's version. Part of the key so editing a
            prompt refreshes results.

    Returns:
        A hex digest. The model and version are hashed with the content rather than
        concatenated around it, so a model name containing the separator cannot collide
        with a different call.
    """
    payload = json.dumps(
        {"content": content, "model": model, "prompt_version": prompt_version},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """One cached result.

    Attributes:
        key: The cache key.
        stage: Which stage produced it, for the usage breakdown.
        text: The response text.
        data: The parsed JSON object, when there was one.
        created_at: Unix timestamp of first write.
        hits: How many times this entry has been served.
    """

    key: str
    stage: str
    text: str
    data: Mapping[str, object] | None
    created_at: float
    hits: int = 0


class CacheBackend(Protocol):
    """Storage for cached results.

    Phase 2 uses SQLite or memory; Phase 3 uses Postgres. The interface is deliberately
    small so the swap is mechanical.
    """

    def get(self, key: str) -> CacheEntry | None:
        """Look up an entry and count the hit.

        Args:
            key: The cache key.

        Returns:
            The entry, or ``None`` on a miss.
        """
        ...

    def put(self, entry: CacheEntry) -> None:
        """Store an entry, replacing any existing one for the same key.

        Args:
            entry: The entry to store.
        """
        ...


class MemoryCache:
    """An in-process cache, for tests and short-lived CLI runs."""

    def __init__(self) -> None:
        """Create an empty cache."""
        self._entries: dict[str, CacheEntry] = {}

    def get(self, key: str) -> CacheEntry | None:
        """Look up an entry and count the hit.

        Args:
            key: The cache key.

        Returns:
            The entry, or ``None`` on a miss.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        counted = CacheEntry(
            key=entry.key,
            stage=entry.stage,
            text=entry.text,
            data=entry.data,
            created_at=entry.created_at,
            hits=entry.hits + 1,
        )
        self._entries[key] = counted
        return counted

    def put(self, entry: CacheEntry) -> None:
        """Store an entry.

        Args:
            entry: The entry to store.
        """
        self._entries[entry.key] = entry

    def __len__(self) -> int:
        """Return how many entries are stored.

        Returns:
            The entry count.
        """
        return len(self._entries)


_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS llm_cache (
    key          TEXT PRIMARY KEY,
    stage        TEXT NOT NULL,
    text         TEXT NOT NULL,
    data         TEXT,
    created_at   REAL NOT NULL,
    hits         INTEGER NOT NULL DEFAULT 0
)
"""


class SqliteCache:
    """A file-backed cache, so repeated CLI runs reuse earlier work.

    Mirrors the ``llm_cache`` table that arrives in Phase 3, including the ``hits``
    counter the admin dashboard reports.
    """

    def __init__(self, path: Path) -> None:
        """Open or create the cache database.

        Args:
            path: The SQLite file. Its parent directory is created if needed.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._connection = sqlite3.connect(str(path))
        self._connection.execute(_SCHEMA)
        self._connection.commit()

    def get(self, key: str) -> CacheEntry | None:
        """Look up an entry and increment its hit counter.

        Args:
            key: The cache key.

        Returns:
            The entry, or ``None`` on a miss.
        """
        row = self._connection.execute(
            "SELECT key, stage, text, data, created_at, hits FROM llm_cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        self._connection.execute(
            "UPDATE llm_cache SET hits = hits + 1 WHERE key = ?",
            (key,),
        )
        self._connection.commit()
        return CacheEntry(
            key=row[0],
            stage=row[1],
            text=row[2],
            data=json.loads(row[3]) if row[3] else None,
            created_at=row[4],
            hits=row[5] + 1,
        )

    def put(self, entry: CacheEntry) -> None:
        """Store an entry, replacing any existing one for the same key.

        Args:
            entry: The entry to store.
        """
        self._connection.execute(
            "INSERT OR REPLACE INTO llm_cache (key, stage, text, data, created_at, hits) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry.key,
                entry.stage,
                entry.text,
                json.dumps(entry.data) if entry.data is not None else None,
                entry.created_at,
                entry.hits,
            ),
        )
        self._connection.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._connection.close()

    def __len__(self) -> int:
        """Return how many entries are stored.

        Returns:
            The entry count.
        """
        row = self._connection.execute("SELECT COUNT(*) FROM llm_cache").fetchone()
        return int(row[0])


@dataclass
class LLMCache:
    """The cache as the adapter uses it: key computation plus a backend.

    Attributes:
        backend: Where entries live.
        model: The model name, folded into every key.
        prompt_version: The prompt-set version, folded into every key.
    """

    backend: CacheBackend
    model: str
    prompt_version: str

    def lookup(self, content: str, prompt_version: str | None = None) -> CacheEntry | None:
        """Check the cache before a call.

        Args:
            content: The canonical content of the call.
            prompt_version: Overrides the default for a per-prompt version.

        Returns:
            The cached entry, or ``None``.
        """
        key = cache_key(content, self.model, prompt_version or self.prompt_version)
        entry = self.backend.get(key)
        if entry is not None:
            _LOG.debug("cache hit for stage=%s key=%s hits=%d", entry.stage, key[:12], entry.hits)
        return entry

    def store(
        self,
        content: str,
        stage: str,
        text: str,
        data: Mapping[str, object] | None,
        prompt_version: str | None = None,
    ) -> CacheEntry:
        """Record a fresh result.

        Args:
            content: The canonical content of the call.
            stage: Which stage produced it.
            text: The response text.
            data: The parsed JSON object, when there was one.
            prompt_version: Overrides the default for a per-prompt version.

        Returns:
            The stored entry.
        """
        key = cache_key(content, self.model, prompt_version or self.prompt_version)
        entry = CacheEntry(
            key=key, stage=stage, text=text, data=data, created_at=time.time(), hits=0
        )
        self.backend.put(entry)
        return entry
