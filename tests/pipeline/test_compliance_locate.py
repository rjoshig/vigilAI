"""The model locates a compliance control; code decides what that means (6.15A).

The call happens only where the deterministic matcher has already failed, so these
tests are about the narrow question and — more importantly — about the four things code
refuses to believe: an answer that is not "found", a path nobody offered, an answer the
model itself is not confident in, and a model that did not answer at all.

A located control is never a pass. It is a review-severity finding asking a person to
confirm, because deciding compliance is a comparison and comparisons are code's
(ADR-001).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


from greenlight_ai.checks.definitions import AdminConfig, ComplianceRule
from greenlight_ai.llm.client import LLMError
from greenlight_ai.parsers.config_json import JsonConfigParser
from greenlight_ai.pipeline import s6_reverse
from greenlight_ai.pipeline.context import RunContext

CONFIG = {
    "configuration_id": "CFG-T",
    "suppressions": {"sdn_screening": True, "deceased": True},
    "output": {"format": "csv"},
}

RULE = ComplianceRule(
    id=1,
    name="Opt-out list applied",
    json_path_contains="suppressions.optout",
    reasoning="Every delivery must suppress the customer's opt-out file.",
)


class _Client:
    """A stand-in that answers the locator with whatever a test needs."""

    def __init__(self, answer: Any = None, raises: bool = False) -> None:
        self.answer = answer
        self.raises = raises
        self.calls = 0

    def complete(self, system: str, user: str, schema: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.system = system
        self.user = user
        if self.raises:
            raise LLMError("no answer")

        class _Result:
            def __init__(self, parsed: Any) -> None:
                self._parsed = parsed

            def parsed(self, _schema: Any) -> Any:
                return self._parsed

        return _Result(self.answer)


def _context(client: Any, guidance: Any = None) -> RunContext:
    """A context carrying only what stage 6's compliance check reads."""
    context = RunContext(
        run_id="TEST-LOCATE",
        osl_path=Path("osl.docx"),
        config_path=Path("config.json"),
        report_paths={},
        client=client,
        admin=AdminConfig(compliance_rules=(RULE,)),
        **({"guidance": guidance} if guidance is not None else {}),
    )
    context.config = JsonConfigParser().parse_mapping(CONFIG, Path("config.json"))
    return context


def _answer(**fields: Any) -> Any:
    """A ComplianceLocation with sensible defaults."""
    from greenlight_ai.llm.prompts.schemas import ComplianceLocation

    return ComplianceLocation(
        **{
            "verdict": "found",
            "json_path": "suppressions.sdn_screening",
            "reason": "SDN screening is the vendor's name for it.",
            "confidence": 0.9,
            **fields,
        }
    )


class TestWhatCodeBelieves:
    """A located control becomes a question for a person, never a pass."""

    def test_a_located_control_is_a_review_finding_not_a_high_miss(self) -> None:
        """The whole point: the false HIGH becomes a question."""
        context = _context(_Client(_answer()))
        s6_reverse._check_compliance(context, context.admin, "Acme")

        assert len(context.findings) == 1
        finding = context.findings[0]
        assert finding.severity == "review"
        assert finding.type != "rule_missing_in_config"
        assert "suppressions.sdn_screening" in finding.title
        assert "add the path to the rule as an alternate" in finding.detail

    def test_the_high_miss_is_unchanged_when_nothing_is_there(self) -> None:
        """The common case must cost nothing and say the same thing it always did."""
        context = _context(_Client(_answer(verdict="absent", json_path="")))
        s6_reverse._check_compliance(context, context.admin, "Acme")

        assert len(context.findings) == 1
        assert context.findings[0].type == "rule_missing_in_config"
        assert context.findings[0].severity == "high"


class TestWhatCodeRefusesToBelieve:
    """Four ways an answer is discarded, each falling back to the old behaviour."""

    def test_a_path_nobody_offered_is_ignored(self) -> None:
        """A hallucinated path must not clear a compliance rule."""
        context = _context(_Client(_answer(json_path="suppressions.invented_by_the_model")))
        s6_reverse._check_compliance(context, context.admin, "Acme")
        assert context.findings[0].type == "rule_missing_in_config"

    def test_an_answer_below_the_confidence_floor_is_ignored(self) -> None:
        """A locator that is unsure has told us nothing the matcher had not."""
        context = _context(_Client(_answer(confidence=0.2)))
        s6_reverse._check_compliance(context, context.admin, "Acme")
        assert context.findings[0].type == "rule_missing_in_config"

    def test_unsure_is_not_found(self) -> None:
        """Only "found" counts; the schema's other verdicts fall through."""
        context = _context(_Client(_answer(verdict="unsure")))
        s6_reverse._check_compliance(context, context.admin, "Acme")
        assert context.findings[0].type == "rule_missing_in_config"

    def test_a_model_that_does_not_answer_falls_back(self) -> None:
        """An unavailable model must never turn a miss into a pass."""
        context = _context(_Client(raises=True))
        s6_reverse._check_compliance(context, context.admin, "Acme")
        assert context.findings[0].type == "rule_missing_in_config"


class TestWhenItAsksAtAll:
    """The call is on the exception, not on every run."""

    def test_no_call_when_the_matcher_finds_the_control(self) -> None:
        """The common case stays free."""
        client = _Client(_answer())
        context = _context(client)
        context.admin = AdminConfig(
            compliance_rules=(
                ComplianceRule(
                    id=2,
                    name="Deceased suppression",
                    json_path_contains="suppressions.deceased",
                    reasoning="Required.",
                ),
            )
        )
        s6_reverse._check_compliance(context, context.admin, "Acme")
        assert client.calls == 0
        assert context.findings == []

    def test_one_call_per_rule_that_could_not_be_found(self) -> None:
        """Bounded by the number of misses, not by the size of the configuration."""
        client = _Client(_answer(verdict="absent", json_path=""))
        context = _context(client)
        s6_reverse._check_compliance(context, context.admin, "Acme")
        assert client.calls == 1


class TestWhatTheLocatorIsTold:
    """What reaches this prompt, pinned (Phase 6.17c, ADR-044).

    The locator receives the run's delivery programme and that programme's standing
    instructions, through the same preamble every other stage gets. Nothing asserted
    it, so a refactor could have dropped it — or doubled it — with every test still
    green. These are that assertion.

    It is worth pinning here rather than anywhere else because this is the one call
    whose answer can soften a high-severity compliance finding into a question.
    """

    def test_the_programme_and_its_standing_instructions_reach_the_prompt(self) -> None:
        from greenlight_ai.pipeline.guidance import RunGuidance

        client = _Client(_answer(verdict="absent", json_path=""))
        context = _context(
            client,
            RunGuidance(
                scope_code="AS",
                scope_label="Account Solicitation",
                scope_instructions="Screening is performed by the service bureau upstream.",
            ),
        )
        s6_reverse._check_compliance(context, context.admin, "Acme")

        assert client.calls == 1
        assert "Account Solicitation" in client.user
        assert "service bureau upstream" in client.user

    def test_they_arrive_labelled_as_background_not_as_a_requirement(self) -> None:
        """An administrator's prose must never read to the model as an instruction.

        The preamble says so in words, and this is the one prompt where it matters
        most: a standing instruction about the very control being located is exactly
        the sentence that could steer an answer.
        """
        from greenlight_ai.pipeline.guidance import RunGuidance

        client = _Client(_answer(verdict="absent", json_path=""))
        context = _context(
            client,
            RunGuidance(scope_code="AS", scope_label="Account Solicitation"),
        )
        s6_reverse._check_compliance(context, context.admin, "Acme")

        assert "background rather than a requirement" in client.user

    def test_it_is_sent_once_not_twice(self) -> None:
        """A doubled preamble would spend the cap and read as emphasis."""
        from greenlight_ai.pipeline.guidance import RunGuidance

        client = _Client(_answer(verdict="absent", json_path=""))
        context = _context(
            client,
            RunGuidance(scope_code="AS", scope_label="Account Solicitation"),
        )
        s6_reverse._check_compliance(context, context.admin, "Acme")

        assert client.user.count("This delivery is Account Solicitation.") == 1

    def test_a_run_with_no_programme_sends_no_preamble_at_all(self) -> None:
        """Nothing configured means the prompt is what it was before any of this."""
        client = _Client(_answer(verdict="absent", json_path=""))
        context = _context(client)
        s6_reverse._check_compliance(context, context.admin, "Acme")

        assert "background rather than a requirement" not in client.user
