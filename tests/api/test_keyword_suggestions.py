"""The loop closes in the console (Phase 6.18f, ADR-045).

The model quoted words that would have matched a delivery's declared programme. This
is where an administrator sees them and — if they agree — adds one to the word list,
after which the keyword check matches in code and the model is not asked again.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models


def _run_suggesting(
    factory: sessionmaker[Session], phrases: dict[str, list[str]], customer: str = "Acme"
) -> int:
    with factory() as session:
        run = models.Run(
            customer_name=customer,
            order_number="ORD-1",
            configuration_id="CFG-1",
            scope="AS",
            status="needs_review",
            keyword_suggestions=phrases,
        )
        session.add(run)
        session.commit()
        return int(run.id)


def _suggestions(client: TestClient, api: str) -> list[dict[str, Any]]:
    response = client.get(f"{api}/admin/keyword-suggestions")
    assert response.status_code == 200
    return list(response.json()["suggestions"])


def test_a_suggestion_appears_with_the_run_it_came_from(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    client.get(f"{api}/admin/scopes")
    run_id = _run_suggesting(factory, {"AS": ["promotional acquisition mailing"]})

    rows = _suggestions(client, api)
    assert len(rows) == 1
    assert rows[0]["scope_code"] == "AS"
    assert rows[0]["phrase"] == "promotional acquisition mailing"
    assert rows[0]["run_ids"] == [run_id]
    assert rows[0]["already_listed"] is False


def test_a_phrase_seen_on_several_deliveries_is_counted_and_ranked_first(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """A phrase seen repeatedly is the customer's vocabulary; one seen once may not be."""
    client.get(f"{api}/admin/scopes")
    for _ in range(3):
        _run_suggesting(factory, {"AS": ["promotional acquisition mailing"]})
    _run_suggesting(factory, {"AS": ["a one-off turn of phrase"]})

    rows = _suggestions(client, api)
    assert rows[0]["phrase"] == "promotional acquisition mailing"
    assert rows[0]["seen"] == 3
    assert rows[1]["seen"] == 1


def test_accepting_a_suggestion_adds_it_to_the_programmes_words(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """The act that closes the loop."""
    client.get(f"{api}/admin/scopes")
    _run_suggesting(factory, {"AS": ["promotional acquisition mailing"]})

    accepted = client.post(
        f"{api}/admin/keyword-suggestions/accept",
        json={"scope_code": "AS", "phrase": "promotional acquisition mailing"},
    )
    assert accepted.status_code == 200
    assert "promotional acquisition mailing" in accepted.json()["keywords"]

    # And the screen now says so, rather than offering it again as though it were new.
    rows = _suggestions(client, api)
    assert rows[0]["already_listed"] is True


def test_accepting_twice_does_not_duplicate_the_word(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    client.get(f"{api}/admin/scopes")
    _run_suggesting(factory, {"AS": ["promotional acquisition mailing"]})
    body = {"scope_code": "AS", "phrase": "promotional acquisition mailing"}

    client.post(f"{api}/admin/keyword-suggestions/accept", json=body)
    second = client.post(f"{api}/admin/keyword-suggestions/accept", json=body)

    assert second.status_code == 200
    assert second.json()["keywords"].count("promotional acquisition mailing") == 1


def test_a_word_the_programme_already_has_in_another_spelling_is_not_added_again(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Spellings are compared the way the check compares them."""
    client.get(f"{api}/admin/scopes")
    _run_suggesting(factory, {"AS": ["Firm-Offer"]})

    response = client.post(
        f"{api}/admin/keyword-suggestions/accept",
        json={"scope_code": "AS", "phrase": "Firm-Offer"},
    )
    assert response.status_code == 200
    keywords = [word.lower() for word in response.json()["keywords"]]
    assert "firm offer" in keywords
    assert "firm-offer" not in keywords


def test_accepting_for_an_unknown_programme_is_refused(client: TestClient, api: str) -> None:
    client.get(f"{api}/admin/scopes")
    response = client.post(
        f"{api}/admin/keyword-suggestions/accept",
        json={"scope_code": "NOPE", "phrase": "anything"},
    )
    assert response.status_code == 404


def test_accepting_is_recorded_in_the_audit_log(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """A word that changes what the tool believes is not added anonymously."""
    client.get(f"{api}/admin/scopes")
    _run_suggesting(factory, {"AS": ["promotional acquisition mailing"]})
    client.post(
        f"{api}/admin/keyword-suggestions/accept",
        json={"scope_code": "AS", "phrase": "promotional acquisition mailing"},
    )

    with factory() as session:
        actions = [row.action for row in session.query(models.AuditLog).all()]
    assert "scope.keyword_accepted" in actions


def test_no_suggestions_is_an_empty_list_not_an_error(client: TestClient, api: str) -> None:
    assert _suggestions(client, api) == []
