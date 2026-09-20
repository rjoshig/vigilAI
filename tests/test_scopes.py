"""One scope vocabulary (Phase 6.12a).

Four shapes have been stored over the product's life, and until this module existed
each reader recognised some of them. These tests hold the two things that matter: every
shape that has ever been written still parses to the scope it meant, and a scope that
names a programme, a customer or a configuration never covers a run that is not that
one. Nothing rewrites the stored columns (ADR-037), so "still parses" is not a
transitional courtesy — it is the contract.
"""

from __future__ import annotations

import pytest

from greenlight_ai import scopes


@pytest.mark.parametrize(
    ("raw", "kind", "value"),
    [
        ("", "everywhere", ""),
        ("all", "everywhere", ""),
        ("ALL", "everywhere", ""),
        ("everywhere", "everywhere", ""),
        ("  all  ", "everywhere", ""),
        ("programme:AS", "programme", "AS"),
        ("programme: as ", "programme", "AS"),
        ("config:CFG-7", "configuration", "CFG-7"),
        ("configuration:CFG-7", "configuration", "CFG-7"),
        ("customer:Acme Card Services", "customer", "Acme Card Services"),
        ("Acme Card Services", "customer", "Acme Card Services"),
    ],
)
def test_every_stored_form_parses(raw: str, kind: str, value: str) -> None:
    parsed = scopes.parse(raw)

    assert (parsed.kind, parsed.value) == (kind, value)


def test_none_is_everywhere() -> None:
    """An unset column has always meant everywhere; it still does."""
    assert scopes.parse(None) == scopes.everywhere()


@pytest.mark.parametrize(
    ("raw", "token"),
    [
        ("all", "everywhere"),
        ("programme:as", "programme:AS"),
        ("Acme", "customer:Acme"),
        ("customer:Acme", "customer:Acme"),
        ("config:CFG-7", "config:CFG-7"),
    ],
)
def test_the_canonical_token_is_what_goes_back_out(raw: str, token: str) -> None:
    assert scopes.token(raw) == token


def test_the_canonical_token_round_trips() -> None:
    for scope in (
        scopes.everywhere(),
        scopes.for_programme("AS"),
        scopes.for_customer("Acme Card Services"),
        scopes.for_configuration("CFG-7"),
    ):
        assert scopes.parse(scope.token) == scope


def test_everywhere_covers_anything() -> None:
    assert scopes.everywhere().covers("Acme", "AS", "CFG-7")
    assert scopes.everywhere().covers()


def test_a_programme_scope_covers_only_that_programme() -> None:
    scope = scopes.for_programme("AS")

    assert scope.covers("Acme", "AS")
    assert scope.covers("Any other customer", "as"), "a code is an identifier, not a name"
    assert not scope.covers("Acme", "AM")
    assert not scope.covers("Acme", ""), "a run with no programme is not in every programme"


def test_a_customer_scope_covers_only_that_customer() -> None:
    scope = scopes.for_customer("Acme Card Services")

    assert scope.covers("Acme Card Services", "AS")
    assert not scope.covers("Acme Card Service")
    assert not scope.covers("acme card services"), "a customer name is matched as entered"
    assert not scope.covers("")


def test_a_configuration_scope_covers_only_that_configuration() -> None:
    scope = scopes.for_configuration("CFG-7")

    assert scope.covers("Acme", "AS", "CFG-7")
    assert not scope.covers("Acme", "AS", "CFG-8")
    assert not scope.covers("Acme", "AS", "")


def test_a_scope_that_names_nothing_covers_nothing() -> None:
    """A half-written row must not quietly become a rule that runs everywhere."""
    assert not scopes.parse("programme:").covers("Acme", "AS")
    assert not scopes.parse("customer:").covers("Acme", "AS")
    assert not scopes.parse("config:").covers("Acme", "AS", "CFG-7")


def test_legacy_and_canonical_forms_are_the_same_scope() -> None:
    assert scopes.parse("all") == scopes.parse("everywhere")
    assert scopes.parse("Acme") == scopes.parse("customer:Acme")
    assert scopes.parse("config:C1") == scopes.parse("configuration:C1")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("all", "Everywhere"),
        ("programme:AS", "Programme · AS"),
        ("customer:Acme", "Customer · Acme"),
        ("config:CFG-7", "Configuration · CFG-7"),
    ],
)
def test_a_screen_never_shows_a_raw_token(raw: str, expected: str) -> None:
    assert scopes.label(raw) == expected


def test_a_programme_label_is_preferred_when_the_caller_has_it() -> None:
    assert scopes.label("programme:AS", "Account Solicitation") == (
        "Programme · Account Solicitation"
    )


def test_checks_do_not_interpret_a_scope_themselves() -> None:
    """``in_scope`` is kept as the name the pipeline calls, but it decides nothing."""
    from greenlight_ai.checks.definitions import in_scope

    assert in_scope("everywhere", "Acme", "AS")
    assert in_scope("all", "Acme", "AS")
    assert in_scope("customer:Acme", "Acme")
    assert in_scope("Acme", "Acme"), "the form every row written before 6.12 uses"
    assert not in_scope("programme:AM", "Acme", "AS")
