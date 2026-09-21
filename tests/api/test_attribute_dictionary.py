"""The dictionary end to end, and what a run spends reaching for a name (6.22d).

Two of this phase's acceptance criteria are numbers, and they are asserted here by
**counting calls** rather than claimed in prose:

* criterion 7 — with a record layout uploaded and an empty dictionary, a run makes at
  most the configured cap of attribute locate calls;
* criterion 8 — the second run of the same configuration, after one accepted spelling,
  makes **zero**.

The second is the one that says whether any of this was worth building. A dictionary
that does not reduce what the next run costs is a table somebody maintains for nothing.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]

#: The case whose DIRT spells every attribute the long way. Without a dictionary the
#: tool is honest and cannot resolve them, which is exactly what 6.22a settled.
CASE = "attribute_renamed"


def _calls(factory: sessionmaker[Session], run_id: int) -> int:
    """How many attribute lookups a run spent."""
    with factory() as session:
        run = session.get(models.Run, run_id)
        assert run is not None
        return int(run.attribute_locate_calls)


def _term(client: TestClient, api: str, canonical: str, *spellings: str, **extra: Any) -> Any:
    """Record one attribute term through the admin endpoint."""
    return client.post(
        f"{api}/admin/attribute-terms",
        json={
            "canonical": canonical,
            "spellings": [{"spelling": s, "origin": "admin"} for s in spellings],
            **extra,
        },
    )


class TestTheConsole:
    """Recording a term, and the one invariant it enforces."""

    def test_a_term_and_its_spellings_round_trip(self, client: TestClient, api: str) -> None:
        body = _term(client, api, "AT01", "debsc_burs_atyrt_at01_1").json()
        assert body["canonical"] == "AT01"
        assert body["spelling_count"] == 1
        assert body["scope"] == "everywhere"

    def test_saving_a_term_again_replaces_its_spellings(self, client: TestClient, api: str) -> None:
        """A term *is* its spellings.

        Keeping a stale one would go on offering a name this delivery no longer uses.
        """
        _term(client, api, "AT01", "old_at01")
        body = _term(client, api, "AT01", "new_at01").json()
        assert [s["spelling"] for s in body["spellings"]] == ["new_at01"]

    def test_a_spelling_claimed_by_another_term_is_refused(
        self, client: TestClient, api: str
    ) -> None:
        """One name means one attribute.

        Two terms claiming it would leave the ladder unable to say which was meant —
        which is the question the dictionary exists to settle, not to complicate.
        """
        _term(client, api, "AT01", "shared_column")
        response = _term(client, api, "AT02", "shared_column")
        assert response.status_code == 422
        assert "already belongs to" in response.json()["detail"]

    def test_deleting_a_term_needs_the_confirmation_word(
        self, client: TestClient, api: str
    ) -> None:
        term_id = _term(client, api, "AT01", "long_at01").json()["id"]
        # 400 and not 422: the word is a query parameter the caller failed to type, the
        # same refusal every other admin delete makes (ADR-032).
        assert client.delete(f"{api}/admin/attribute-terms/{term_id}").status_code == 400
        assert (
            client.delete(f"{api}/admin/attribute-terms/{term_id}?confirm=delete").status_code
            == 204
        )


class TestTheLegacyAliases:
    """Read alongside the dictionary, and copied only when somebody asks (ADR-062)."""

    def test_the_copy_is_previewed_before_anything_is_written(
        self, client: TestClient, api: str, seed_aliases: None, factory: sessionmaker[Session]
    ) -> None:
        del seed_aliases
        preview = client.get(f"{api}/admin/attribute-terms/alias-copy").json()
        assert preview["creates"]
        assert preview["written"] == 0
        with factory() as session:
            assert session.query(models.AttributeTerm).count() == 0

    def test_applying_the_copy_writes_the_terms(
        self, client: TestClient, api: str, seed_aliases: None
    ) -> None:
        del seed_aliases
        wanted = len(client.get(f"{api}/admin/attribute-terms/alias-copy").json()["creates"])
        applied = client.post(f"{api}/admin/attribute-terms/alias-copy").json()
        assert applied["written"] > 0
        assert len(client.get(f"{api}/admin/attribute-terms").json()) == wanted

    def test_copying_twice_writes_nothing_the_second_time(
        self, client: TestClient, api: str, seed_aliases: None
    ) -> None:
        del seed_aliases
        client.post(f"{api}/admin/attribute-terms/alias-copy")
        assert client.post(f"{api}/admin/attribute-terms/alias-copy").json()["written"] == 0

    def test_an_alias_resolves_whether_or_not_it_was_copied(
        self, submit: Submit, worker: Worker, seed_aliases: None, factory: sessionmaker[Session]
    ) -> None:
        """Nothing that matched before stops matching.

        ``baseline_match`` needs the alias table to line up *revolving utilization* with
        ``REV_UTIL``, and it does so with the dictionary empty.
        """
        del seed_aliases
        run_id = int(submit("baseline_match").json()["run_id"])
        worker.run_once()
        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None and run.status == "needs_review"


class TestWhatARunSpends:
    """Criteria 7 and 8, asserted by counting."""

    def test_a_run_with_an_empty_dictionary_stays_within_the_cap(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        worker: Worker,
        factory: sessionmaker[Session],
    ) -> None:
        """Criterion 7. The cap is configured, and the run respects it."""
        client.post(
            f"{api}/admin/settings",
            json={"key": "llm.max_attribute_calls_per_run", "value": 2},
        )
        run_id = int(submit(CASE).json()["run_id"])
        worker.run_once()
        assert _calls(factory, run_id) <= 2

    def test_a_cap_of_zero_spends_nothing_and_the_run_says_what_it_skipped(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        worker: Worker,
        factory: sessionmaker[Session],
    ) -> None:
        """A soft limit: the run finishes, and names what it did not look for."""
        client.post(
            f"{api}/admin/settings",
            json={"key": "llm.max_attribute_calls_per_run", "value": 0},
        )
        run_id = int(submit(CASE).json()["run_id"])
        worker.run_once()

        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            assert run.status == "needs_review"
            assert run.attribute_locate_calls == 0
            assert any("attribute lookup" in notice for notice in run.notices)

    def test_the_second_run_after_the_spellings_are_recorded_spends_nothing(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        worker: Worker,
        factory: sessionmaker[Session],
        cases: dict[str, Any],
    ) -> None:
        """Criterion 8, and the one that says whether this was worth building.

        The spellings go into the dictionary, rung 4 answers, and rung 5 is never
        reached. Asserted by counting the calls, not by claiming it.
        """
        del cases
        first = int(submit(CASE).json()["run_id"])
        worker.run_once()

        # An administrator records what the delivery calls each attribute — which is
        # what 6.22f will offer them automatically from this very run.
        for attribute in ("SCORE_V3", "AGE", "ST", "REV_UTIL"):
            _term(client, api, attribute, f"debsc_burs_atyrt_{attribute.lower()}_1")

        second = int(submit(CASE, rerun_reason="the same order again").json()["run_id"])
        worker.run_once()

        assert _calls(factory, second) == 0
        # And the names now resolve, so the review records the first run raised are gone.
        after = [f["type"] for f in client.get(f"{api}/runs/{second}/findings").json()]
        before = [f["type"] for f in client.get(f"{api}/runs/{first}/findings").json()]
        assert after.count("attribute_not_resolved") < before.count("attribute_not_resolved")
