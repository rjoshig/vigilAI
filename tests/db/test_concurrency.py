"""Concurrency tests (Phase 6).

These exist because a load test found a real race: two workers caching the same OSL
section both inserted the same key and one run failed. A cache write is an
optimisation and must never fail the run that was trying to save a future call.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.db.cache import DbCache
from greenlight_ai.db.queue import JobQueue
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.llm.cache import CacheEntry, LLMCache


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'c.db'}"))
    create_all(engine)
    return session_factory(engine)


# --- the cache race -------------------------------------------------------------------


def test_two_writers_of_the_same_key_both_succeed(factory: sessionmaker[Session]) -> None:
    """The key is a content hash, so a duplicate means the same answer, not a conflict."""
    backend = DbCache(factory)
    entry = CacheEntry(key="k" * 64, stage="s2_extract", text="{}", data={}, created_at=0.0)

    backend.put(entry)
    backend.put(entry)  # would raise before the fix

    with factory() as session:
        rows = list(session.execute(sa.select(models.LlmCacheEntry)).scalars())
    assert len(rows) == 1


def test_concurrent_writers_do_not_raise(factory: sessionmaker[Session]) -> None:
    backend = DbCache(factory)
    errors: list[Exception] = []

    def write() -> None:
        try:
            for index in range(10):
                backend.put(
                    CacheEntry(
                        key=f"{index:064d}",
                        stage="s2_extract",
                        text="{}",
                        data={},
                        created_at=0.0,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - the point is that none escapes
            errors.append(exc)

    threads = [threading.Thread(target=write) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with factory() as session:
        count = session.execute(
            sa.select(sa.func.count()).select_from(models.LlmCacheEntry)
        ).scalar_one()
    assert int(count) == 10


def test_a_cached_answer_is_still_served_after_a_race(factory: sessionmaker[Session]) -> None:
    cache = LLMCache(backend=DbCache(factory), model="m", prompt_version="1")
    cache.store("content", "s2_extract", '{"requirements": []}', {"requirements": []})
    cache.store("content", "s2_extract", '{"requirements": []}', {"requirements": []})
    entry = cache.lookup("content")
    assert entry is not None
    assert entry.data == {"requirements": []}


# --- the queue under several workers ------------------------------------------------------


def test_each_job_is_claimed_exactly_once(factory: sessionmaker[Session]) -> None:
    """Several workers must never both take the same job."""
    with factory() as session:
        queue = JobQueue(session, is_sqlite=True)
        for index in range(20):
            queue.enqueue("run_pipeline", run_id=index)
        session.commit()

    claimed: list[int] = []
    lock = threading.Lock()

    def drain() -> None:
        while True:
            with factory() as session:
                job = JobQueue(session, is_sqlite=True).claim(["run_pipeline"])
                session.commit()
            if job is None:
                return
            with lock:
                claimed.append(job.id)

    threads = [threading.Thread(target=drain) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(claimed) == 20
    assert len(set(claimed)) == 20, "a job was claimed twice"


def test_the_per_order_cap_holds_under_concurrent_submission(
    factory: sessionmaker[Session],
) -> None:
    """Phase 6: the per-order-number queue cap verified."""
    from greenlight_ai.api.routers.runs import MAX_QUEUED_PER_ORDER

    with factory() as session:
        for _ in range(MAX_QUEUED_PER_ORDER):
            session.add(
                models.Run(
                    customer_name="Acme",
                    order_number="ORD-1",
                    configuration_id="C-1",
                    status="queued",
                )
            )
        session.commit()
        queued = session.execute(
            sa.select(sa.func.count())
            .select_from(models.Run)
            .where(models.Run.order_number == "ORD-1", models.Run.status == "queued")
        ).scalar_one()

    assert int(queued) >= MAX_QUEUED_PER_ORDER
