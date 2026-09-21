"""The layout map, and the loop that fills it (Phase 6.21b).

The fixed report checks named their sheets as Python constants, so adapting to a
customer's DIRT was an engineering deploy — the one thing this product was designed to
avoid. This is the other half of ADR-054: the ladder's fifth rung reads a name the
first four could not, the run says so, and an administrator accepting that reading
turns every later delivery from that customer into one code resolves.

What these pin down: an entry reaches the ladder's *fourth* rung and never overrules
the name actually asked for; a suggestion is a suggestion until somebody accepts it
(ADR-021); accepting it stops it being offered again; and a scope that does not cover
a run does not reach it.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.checks import layout
from greenlight_ai.db import models, repository
from greenlight_ai.resolve import resolve
from greenlight_ai.resolve.layout import LayoutResolver, alternates_key


def _entry(**fields: Any) -> dict[str, Any]:
    return layout.LayoutEntry(
        **{
            "scope": "",
            "kind": "sheet",
            "wanted": "Attributes",
            "names": ("Attribute Summary",),
            **fields,
        }
    ).model_dump()


# ------------------------------------------------------------------------ the map


def test_an_entry_resolves_a_name_no_deterministic_rung_reaches() -> None:
    """``Accepts`` and ``Accepted total`` share no token; only a person reaches that."""
    names = ("Accepted total", "Rejected total")
    assert resolve("Accepts", names) is None

    found = resolve("Accepts", names, ["Accepted total"])
    assert found is not None
    assert found.value == "Accepted total" and found.rung == "alternate"


def test_an_entry_never_overrules_the_name_actually_asked_for() -> None:
    """Which is why it is the fourth rung and not the first."""
    found = resolve("Accepts", ["Accepts", "Accepted total"], ["Accepted total"])
    assert found is not None and found.value == "Accepts" and found.rung == "exact"


def test_the_map_is_keyed_so_the_resolver_finds_it() -> None:
    built = layout.load_map([("dirt", [_entry()])])
    assert built == {alternates_key("dirt", "sheet", "Attributes"): ("Attribute Summary",)}


def test_spelling_the_wanted_name_differently_still_finds_the_entry() -> None:
    """An administrator who wrote ``attributes`` answers a check asking ``Attributes``."""
    built = layout.load_map([("dirt", [_entry(wanted="attributes")])])
    assert alternates_key("dirt", "sheet", "Attributes") in built


def test_a_scope_that_does_not_cover_the_run_is_left_out() -> None:
    entries = [_entry(scope="programme:AM"), _entry(wanted="States", names=("State Breakdown",))]

    for_am = layout.load_map([("dirt", entries)], programme_code="AM")
    assert len(for_am) == 2

    for_as = layout.load_map([("dirt", entries)], programme_code="AS")
    assert list(for_as) == [alternates_key("dirt", "sheet", "States")]


def test_several_spellings_of_one_name_are_all_offered() -> None:
    """One report type can be delivered by customers who each word it differently."""
    built = layout.load_map(
        [
            (
                "dirt",
                [
                    _entry(scope="programme:AM", names=("Attribute Summary",)),
                    _entry(scope="programme:AS", names=("Field Statistics",)),
                ],
            )
        ]
    )
    assert built == {}, "neither scope covers a run with no programme"

    built = layout.load_map([("dirt", [_entry(names=("Attribute Summary", "Field Statistics"))])])
    assert built[alternates_key("dirt", "sheet", "Attributes")] == (
        "Attribute Summary",
        "Field Statistics",
    )


def test_an_unreadable_entry_is_skipped_rather_than_failing_the_run() -> None:
    """A half-written row is not a reason a delivery cannot be validated."""
    built = layout.load_map([("dirt", [{"nonsense": True}, _entry()])])
    assert len(built) == 1


def test_an_entry_with_no_spellings_says_nothing() -> None:
    assert layout.load_map([("dirt", [_entry(names=())])]) == {}


# ---------------------------------------------------------------- the console loop


@pytest.fixture()
def session(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session against the same database the client uses."""
    from greenlight_ai.db import catalog

    with factory() as open_session:
        catalog.seed_defaults(open_session)
        open_session.commit()
        yield open_session


def test_an_administrator_can_write_the_map_by_hand(client: TestClient, api: str) -> None:
    response = client.put(
        f"{api}/admin/artifact-types/dirt/layout",
        json={
            "entries": [
                {"kind": "sheet", "wanted": "Attributes", "names": ["Attribute Summary"]},
                {"kind": "label", "wanted": "Accepts", "names": ["Accepted total"]},
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["layout"]) == 2
    assert response.json()["version"] >= 1, "a save is a version, like every definition"


def test_a_kind_nothing_reads_is_refused(client: TestClient, api: str) -> None:
    response = client.put(
        f"{api}/admin/artifact-types/dirt/layout",
        json={"entries": [{"kind": "worksheet", "wanted": "Attributes", "names": ["x"]}]},
    )
    assert response.status_code == 422
    assert "sheet" in response.text


def test_two_entries_for_the_same_thing_are_refused(client: TestClient, api: str) -> None:
    """Because the second would silently win and the first would look applied."""
    response = client.put(
        f"{api}/admin/artifact-types/dirt/layout",
        json={
            "entries": [
                {"kind": "sheet", "wanted": "Attributes", "names": ["One"]},
                {"kind": "sheet", "wanted": "attributes", "names": ["Two"]},
            ]
        },
    )
    assert response.status_code == 422
    assert "put the spellings in one" in response.text


def _run_with_suggestion(session: Session, **fields: Any) -> models.Run:
    run = models.Run(
        customer_name="Northwind Lending",
        order_number="ORD-1",
        configuration_id="CFG-1",
        status="needs_review",
        layout_suggestions=[
            layout.LayoutSuggestion(
                artifact="counts",
                kind="label",
                wanted="Accepts",
                found="Accepted total",
                confidence=0.88,
                reason="An accepted total is the count that passed every filter.",
                **fields,
            ).model_dump()
        ],
    )
    session.add(run)
    session.flush()
    return run


def test_what_the_model_read_is_offered_not_applied(
    client: TestClient, api: str, session: Session
) -> None:
    """ADR-021: nothing activates without a person approving it."""
    _run_with_suggestion(session)
    session.commit()

    listed = client.get(f"{api}/admin/layout-suggestions").json()["suggestions"]
    assert len(listed) == 1
    offered = listed[0]
    assert offered["wanted"] == "Accepts" and offered["found"] == "Accepted total"
    assert offered["already_listed"] is False
    assert offered["seen"] == 1
    assert "passed every filter" in offered["reason"]

    # And nothing is in force until it is accepted.
    assert client.get(f"{api}/admin/artifact-types").json()
    types = {row["key"]: row for row in client.get(f"{api}/admin/artifact-types").json()}
    assert types["counts"]["layout"] == []


def test_the_same_reading_on_two_runs_is_one_decision(
    client: TestClient, api: str, session: Session
) -> None:
    """An administrator should see what to decide, not how many runs met it."""
    _run_with_suggestion(session)
    _run_with_suggestion(session)
    session.commit()

    listed = client.get(f"{api}/admin/layout-suggestions").json()["suggestions"]
    assert len(listed) == 1
    assert listed[0]["seen"] == 2
    assert len(listed[0]["run_ids"]) == 2


def test_accepting_closes_the_loop(client: TestClient, api: str, session: Session) -> None:
    """From here the fourth rung resolves it in code and no call is made."""
    _run_with_suggestion(session)
    session.commit()

    accepted = client.post(
        f"{api}/admin/layout-suggestions/accept",
        json={
            "artifact": "counts",
            "kind": "label",
            "wanted": "Accepts",
            "found": "Accepted total",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["layout"] == [
        {
            "scope": "everywhere",
            "kind": "label",
            "wanted": "Accepts",
            "names": ["Accepted total"],
            "note": "accepted from what the AI read",
            "added_by": accepted.json()["layout"][0]["added_by"],
        }
    ]

    # It stops asking.
    listed = client.get(f"{api}/admin/layout-suggestions").json()["suggestions"]
    assert listed[0]["already_listed"] is True

    # And the map the pipeline loads now carries it, so the resolver needs no client.
    loaded = repository.load_admin_config(session).layout_map
    assert loaded[alternates_key("counts", "label", "Accepts")] == ("Accepted total",)
    resolver = LayoutResolver(alternates=loaded)
    found = resolver.name(
        "Accepts", ["Accepted total", "Rejected total"], kind="label", artifact="counts"
    )
    assert found is not None and found.rung == "alternate"
    assert resolver.reasoned == [], "nothing left for a person to confirm"


def test_accepting_a_second_spelling_joins_the_first(
    client: TestClient, api: str, session: Session
) -> None:
    for found in ("Accepted total", "Records accepted"):
        client.post(
            f"{api}/admin/layout-suggestions/accept",
            json={"artifact": "counts", "kind": "label", "wanted": "Accepts", "found": found},
        )

    types = {row["key"]: row for row in client.get(f"{api}/admin/artifact-types").json()}
    assert types["counts"]["layout"][0]["names"] == ["Accepted total", "Records accepted"]


def test_accepting_the_same_thing_twice_changes_nothing(
    client: TestClient, api: str, session: Session
) -> None:
    body = {"artifact": "counts", "kind": "label", "wanted": "Accepts", "found": "Accepted total"}
    client.post(f"{api}/admin/layout-suggestions/accept", json=body)
    second = client.post(f"{api}/admin/layout-suggestions/accept", json=body)

    assert second.status_code == 200
    assert len(second.json()["layout"]) == 1
    assert second.json()["layout"][0]["names"] == ["Accepted total"]


def test_accepting_for_one_programme_leaves_another_alone(
    client: TestClient, api: str, session: Session
) -> None:
    client.post(
        f"{api}/admin/layout-suggestions/accept",
        json={
            "artifact": "counts",
            "kind": "label",
            "wanted": "Accepts",
            "found": "Accepted total",
            "scope": "programme:AM",
        },
    )

    assert repository.load_admin_config(session, programme_code="AM").layout_map
    assert repository.load_admin_config(session, programme_code="AS").layout_map == {}


def test_accepting_onto_a_type_that_does_not_exist_is_a_404(client: TestClient, api: str) -> None:
    response = client.post(
        f"{api}/admin/layout-suggestions/accept",
        json={"artifact": "nope", "kind": "label", "wanted": "Accepts", "found": "x"},
    )
    assert response.status_code == 404
