"""What a reviewer has stopped needing to see (Phase 6.18a).

The arithmetic, tested without a database. `tests/api/test_demotion_report.py` covers
the wiring and the one property that matters most: in 6.18a none of this changes what
a reviewer sees.
"""

from __future__ import annotations

import pytest

from greenlight_ai.training import demotion as d


def _verdicts(*pairs: tuple[str, str]) -> list[tuple[str, str, int]]:
    """Build ``(status, severity, run_id)`` triples with ascending run ids."""
    return [(status, severity, index + 1) for index, (status, severity) in enumerate(pairs)]


# --- the signature ------------------------------------------------------------------


def _sig(**over: str) -> str:
    base = dict(
        customer_name="Acme",
        scope="AS",
        rule_ref="r1",
        finding_type="missing_field",
        element_ref="score",
    )
    base.update(over)
    return d.signature(**base)  # type: ignore[arg-type]


def test_the_same_finding_again_is_the_same_signature() -> None:
    assert _sig() == _sig()


@pytest.mark.parametrize(
    "field,value",
    [
        ("customer_name", "Other Co"),
        ("scope", "AM"),
        ("rule_ref", "r2"),
        ("finding_type", "value_mismatch"),
        ("element_ref", "state"),
    ],
)
def test_every_part_of_the_signature_separates_it(field: str, value: str) -> None:
    """Change any one part and it is a different thing being learned about.

    ``element_ref`` is the one worth naming: a blank score column and a blank state
    column share a rule and are not the same finding. Pooling them would let evidence
    about a harmless case silence one that matters.
    """
    assert _sig(**{field: value}) != _sig()


def test_the_customer_and_programme_bound_what_is_shared() -> None:
    """Trust is learned per customer per programme, and crosses neither boundary."""
    assert _sig(customer_name="Other Co") != _sig()
    assert _sig(scope="ARCHIVE") != _sig()


def test_the_signature_ignores_case_and_surrounding_space_in_the_customer() -> None:
    """``Acme`` and ``ACME `` are one customer, and a stray space must not fork trust."""
    assert _sig(customer_name="  ACME ") == _sig()


# --- the tally ----------------------------------------------------------------------


def test_an_undecided_finding_is_not_evidence() -> None:
    """A finding nobody judged says nothing about whether it mattered."""
    counted = d.tally(_verdicts(("undecided", "low"), ("false_positive", "low")))
    assert counted.occurrences == 1
    assert counted.dismissed == 1


def test_accepted_risk_counts_as_upheld_not_dismissed() -> None:
    """The reviewer agreed the finding was true and chose to carry it.

    That is the opposite of saying it should never have been raised, so it must not
    push a signature toward being hidden.
    """
    counted = d.tally(_verdicts(("accepted_risk", "medium")))
    assert counted.upheld == 1
    assert counted.dismissed == 0


def test_the_tally_keeps_the_runs_its_evidence_came_from() -> None:
    counted = d.tally(_verdicts(("false_positive", "low"), ("false_positive", "low")))
    assert counted.run_ids == (1, 2)


# --- the decision -------------------------------------------------------------------


def test_ten_dismissals_and_nothing_else_earns_a_demotion() -> None:
    counted = d.tally(_verdicts(*[("false_positive", "low")] * 10))
    state, reason = d.decide(counted)
    assert state == d.WOULD_DEMOTE
    assert "10" in reason


def test_nine_is_not_ten() -> None:
    """A count, not a rate. The bar is the bar."""
    counted = d.tally(_verdicts(*[("false_positive", "low")] * 9))
    assert d.decide(counted)[0] == d.WATCHING


def test_one_upheld_finding_blocks_it_however_many_dismissals_follow() -> None:
    """The rule that matters most: one real escalation outranks any number of waves.

    Nine of ten is not evidence that the tenth did not matter — it is evidence that it
    did.
    """
    counted = d.tally(_verdicts(("confirmed", "low"), *[("false_positive", "low")] * 50))
    state, reason = d.decide(counted)
    assert state == d.BLOCKED
    assert "real" in reason


@pytest.mark.parametrize("severity", sorted(d.NEVER_DEMOTED))
def test_a_serious_finding_is_never_demoted_at_any_level_of_evidence(severity: str) -> None:
    """The floor under the whole phase.

    The goal is a reviewer who reads only the serious findings, not one who reads none.
    A hundred dismissals do not move this.
    """
    counted = d.tally(_verdicts(*[("false_positive", severity)] * 100))
    state, reason = d.decide(counted)
    assert state == d.BLOCKED
    assert "never demoted" in reason


def test_one_serious_occurrence_among_many_harmless_ones_still_blocks() -> None:
    """Severity is checked over everything the signature has ever fired at."""
    counted = d.tally(_verdicts(*[("false_positive", "low")] * 20, ("false_positive", "high")))
    assert d.decide(counted)[0] == d.BLOCKED


def test_the_bar_can_be_raised_but_not_evaded() -> None:
    """The console may demand more evidence; it cannot change what evidence means."""
    counted = d.tally(_verdicts(*[("false_positive", "low")] * 10))
    assert d.decide(counted, minimum=25)[0] == d.WATCHING
    blocked = d.tally(_verdicts(("confirmed", "low"), *[("false_positive", "low")] * 99))
    assert d.decide(blocked, minimum=1)[0] == d.BLOCKED


def test_every_decision_explains_itself() -> None:
    """A demotion nobody can explain is one nobody should trust."""
    for verdicts in (
        [("false_positive", "low")] * 10,
        [("false_positive", "low")] * 2,
        [("confirmed", "low")],
        [("false_positive", "high")] * 10,
    ):
        _, reason = d.decide(d.tally(_verdicts(*verdicts)))
        assert reason.strip() and reason.endswith(".")


# --- reporting ----------------------------------------------------------------------


def test_the_evidence_is_capped_at_the_most_recent() -> None:
    """Somebody checking a decision wants the runs they can still open."""
    counted = d.tally(_verdicts(*[("false_positive", "low")] * 50))
    runs = d.justifying_runs(counted, limit=20)
    assert len(runs) == 20
    assert runs[-1] == 50


def test_the_summary_names_every_state_including_the_empty_ones() -> None:
    """A report that omits a state reads as though nothing is in it."""
    assert d.summarize([d.WOULD_DEMOTE]) == {
        d.WATCHING: 0,
        d.WOULD_DEMOTE: 1,
        d.BLOCKED: 0,
    }
