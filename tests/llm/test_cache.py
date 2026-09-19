"""Tests for the stage cache (ADR-005)."""

from __future__ import annotations

from pathlib import Path

from greenlight_ai.llm import LLMCache, MemoryCache, SqliteCache, cache_key


def test_the_same_content_gives_the_same_key() -> None:
    assert cache_key("content", "model", "1") == cache_key("content", "model", "1")


def test_changing_the_model_refreshes_results() -> None:
    assert cache_key("content", "model-a", "1") != cache_key("content", "model-b", "1")


def test_changing_the_prompt_version_refreshes_results() -> None:
    assert cache_key("content", "model", "1") != cache_key("content", "model", "2")


def test_changing_the_content_changes_the_key() -> None:
    assert cache_key("a", "model", "1") != cache_key("b", "model", "1")


def test_fields_cannot_collide_across_the_separator() -> None:
    """A model name containing the content must not produce another call's key."""
    assert cache_key("a", "b", "1") != cache_key("", "ab", "1")


def test_memory_cache_misses_then_hits() -> None:
    cache = LLMCache(backend=MemoryCache(), model="m", prompt_version="1")
    assert cache.lookup("content") is None
    cache.store("content", "s2_extract", '{"requirements": []}', {"requirements": []})
    entry = cache.lookup("content")
    assert entry is not None
    assert entry.stage == "s2_extract"
    assert entry.data == {"requirements": []}


def test_hits_are_counted_for_the_usage_dashboard() -> None:
    cache = LLMCache(backend=MemoryCache(), model="m", prompt_version="1")
    cache.store("content", "s2_extract", "{}", {})
    assert cache.lookup("content").hits == 1  # type: ignore[union-attr]
    assert cache.lookup("content").hits == 2  # type: ignore[union-attr]


def test_a_different_prompt_version_misses() -> None:
    cache = LLMCache(backend=MemoryCache(), model="m", prompt_version="1")
    cache.store("content", "s2_extract", "{}", {})
    assert cache.lookup("content", prompt_version="2") is None


def test_sqlite_cache_survives_reopening(tmp_path: Path) -> None:
    """A second CLI run reuses the first run's work."""
    path = tmp_path / "cache.sqlite"
    first = SqliteCache(path)
    LLMCache(backend=first, model="m", prompt_version="1").store("c", "s2", "text", {"a": 1})
    first.close()

    second = SqliteCache(path)
    entry = LLMCache(backend=second, model="m", prompt_version="1").lookup("c")
    assert entry is not None
    assert entry.text == "text"
    assert entry.data == {"a": 1}
    second.close()


def test_sqlite_cache_counts_hits_across_processes(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite"
    backend = SqliteCache(path)
    cache = LLMCache(backend=backend, model="m", prompt_version="1")
    cache.store("c", "s2", "text", None)
    assert cache.lookup("c").hits == 1  # type: ignore[union-attr]
    backend.close()

    reopened = SqliteCache(path)
    entry = LLMCache(backend=reopened, model="m", prompt_version="1").lookup("c")
    assert entry is not None and entry.hits == 2
    reopened.close()


def test_sqlite_cache_creates_its_parent_directory(tmp_path: Path) -> None:
    backend = SqliteCache(tmp_path / "nested" / "dir" / "cache.sqlite")
    assert len(backend) == 0
    backend.close()


def test_storing_the_same_key_twice_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    backend = SqliteCache(tmp_path / "cache.sqlite")
    cache = LLMCache(backend=backend, model="m", prompt_version="1")
    cache.store("c", "s2", "first", None)
    cache.store("c", "s2", "second", None)
    assert len(backend) == 1
    assert cache.lookup("c").text == "second"  # type: ignore[union-attr]
    backend.close()


def test_entries_hold_no_row_contents() -> None:
    """Prompts never carry sample rows, so cached entries cannot either (ADR-003)."""
    cache = LLMCache(backend=MemoryCache(), model="m", prompt_version="1")
    entry = cache.store("c", "s2", "{}", {})
    assert set(type(entry).__slots__) == {"key", "stage", "text", "data", "created_at", "hits"}
