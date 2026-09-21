"""The migration chain is single, linear, and applies to an empty database.

Written after a duplicate revision id shipped and every other test stayed green:
the suite builds its schema from the models with ``create_all``, so nothing exercised
alembic at all. A broken chain would first be discovered by whoever ran an upgrade.

These are cheap and they cover the three ways the chain breaks in practice: two files
claiming one revision, two heads because a `down_revision` was not repointed, and a
migration that does not actually run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[2] / "src/greenlight_ai/db/migrations/versions"

_REVISION = re.compile(r'^revision: str = "(.+?)"', re.M)
_DOWN = re.compile(r'^down_revision: Union\[str, None\] = (?:"(.+?)"|None)', re.M)


def _chain() -> tuple[dict[str, str], dict[str, str | None]]:
    """Every migration's revision and the one it follows.

    Returns:
        Revision to filename, and revision to its parent (``None`` for the first).
    """
    revisions: dict[str, str] = {}
    parents: dict[str, str | None] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text()
        found = _REVISION.search(text)
        if not found:
            continue
        revision = found.group(1)
        assert revision not in revisions, (
            f"revision {revision} is claimed by both {revisions[revision]} and {path.name}. "
            "Alembic reports this as a cycle and refuses to upgrade at all."
        )
        revisions[revision] = path.name
        down = _DOWN.search(text)
        parents[revision] = down.group(1) if down else None
    return revisions, parents


def test_no_two_migrations_claim_the_same_revision() -> None:
    """The failure that prompted this file. The assertion is in the helper."""
    revisions, _ = _chain()
    assert revisions


def test_there_is_exactly_one_head() -> None:
    """Two heads mean somebody added a migration without repointing the last one."""
    revisions, parents = _chain()
    claimed = {parent for parent in parents.values() if parent}
    heads = sorted(set(revisions) - claimed)
    assert len(heads) == 1, f"expected one head, found {[revisions[h] for h in heads]}"


def test_every_parent_exists() -> None:
    """A `down_revision` naming a file nobody has is an unrunnable chain."""
    revisions, parents = _chain()
    for revision, parent in parents.items():
        if parent is not None:
            assert (
                parent in revisions
            ), f"{revisions[revision]} follows {parent}, which no migration defines"


def test_the_chain_reaches_the_first_migration_from_the_head() -> None:
    """Walking back from the head visits every migration exactly once."""
    revisions, parents = _chain()
    claimed = {parent for parent in parents.values() if parent}
    head = next(iter(set(revisions) - claimed))

    seen: list[str] = []
    current: str | None = head
    while current is not None:
        assert current not in seen, f"cycle at {revisions[current]}"
        seen.append(current)
        current = parents[current]
    assert len(seen) == len(revisions)


# Alembic 1.20 warns that `alembic.ini` predates its `path_separator` key. The repo
# pins `alembic>=1.13`, where that key does not exist, so the file is correct for the
# floor it supports and the warning is about this environment rather than this project.
# Scoped here rather than added to the project's filters, which would hide it
# everywhere including where it might one day matter.
@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_migrations_apply_to_an_empty_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one that would have caught it, by doing what an operator does.

    Runs the real upgrade against a fresh SQLite file and asserts the schema that
    comes out matches the models the application actually uses.

    ``DATABASE_URL`` rather than alembic's own ``sqlalchemy.url``, because that is
    where `migrations/env.py` reads it from and so is what an operator actually sets.
    """
    alembic = pytest.importorskip("alembic.command")
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    database = tmp_path / "chain.db"
    url = f"sqlite+pysqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)

    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "src/greenlight_ai/db/migrations"))
    alembic.upgrade(config, "head")

    engine = sa.create_engine(url)
    tables = set(sa.inspect(engine).get_table_names())
    engine.dispose()

    from greenlight_ai.db import models

    expected = {table.name for table in models.Base.metadata.sorted_tables}
    assert expected - tables == set(), f"migrations do not create {sorted(expected - tables)}"
