"""Tests for the PII tripwire (ADR-003, Phase 6).

Two things matter equally: it must catch personal data, and it must not fire on
ordinary requirement text. A tripwire that cries wolf gets switched off.
"""

from __future__ import annotations

import pickle

import pytest

from vigilai.llm import LLMSettings, MockClient
from vigilai.llm.tripwire import PATTERNS, PiiDetected, assert_clean, scan

#: Text the pipeline legitimately sends: OSL prose, config blocks, aggregate values.
LEGITIMATE = [
    "Include only consumers whose current address is in Illinois or Arizona.",
    "Applicants must have a score of at least 755 on the V3 model as of the pull date.",
    "The input population is 1,000,000 consumer records drawn from the prescreen universe.",
    'filters[0] = {"field": "ST", "op": "in", "value": ["IL", "AZ", "TX"]}',
    "SCORE_V3 delivered minimum is 750; the OSL requires >= 755.",
    "Revolving utilization below 60 percent, accepts 178,636 and rejects 821,364.",
    "Process in this order: geography, then score, then age, then exclusions, then dedupe.",
    "DIRT · Attributes!D14 shows 750 against a required 755.",
    "accepts_count + rejects_count == input_count",
    "Configuration CFG-ACME-PRESCREEN-07 v3, run 2026-09-18, order ORD-24177.",
]

#: Text that must never reach a model.
PERSONAL = [
    ("ssn", "sample row: 123-45-6789"),
    ("ssn", "SSN 123 45 6789 appears in the file"),
    ("email", "contact jane.doe@example.com for details"),
    ("phone", "call 555-123-4567 to confirm"),
    ("phone", "(555) 123-4567"),
    ("street_address", "delivered to 123 Main Street"),
    ("date_of_birth", "date_of_birth: 1984-02-11"),
    ("card_number", "4111 1111 1111 1111"),
]


@pytest.mark.parametrize("text", LEGITIMATE)
def test_legitimate_pipeline_text_passes(text: str) -> None:
    """A tripwire that fires on ordinary content gets disabled, which is worse."""
    assert scan(text) == []


@pytest.mark.parametrize(("kind", "text"), PERSONAL)
def test_personal_data_is_caught(kind: str, text: str) -> None:
    kinds = {match.kind for match in scan(text)}
    assert kind in kinds, f"{text!r} was not caught as {kind}"


def test_the_match_never_carries_the_value() -> None:
    """The match ends up in an exception message, and messages reach logs."""
    match = scan("ssn 123-45-6789")[0]
    assert "123" not in match.sample
    assert match.sample == "***-**-****"


def test_the_error_names_the_pattern_and_the_stage_but_not_the_value() -> None:
    with pytest.raises(PiiDetected) as excinfo:
        assert_clean("row: 123-45-6789", stage="s2_extract")
    message = str(excinfo.value)
    assert "ssn" in message
    assert "s2_extract" in message
    assert "123-45-6789" not in message


def test_the_error_survives_pickling() -> None:
    """The worker carries a failure across a process boundary."""
    error = PiiDetected(scan("ssn 123-45-6789"), "s2_extract")
    restored = pickle.loads(pickle.dumps(error))
    assert restored.stage == "s2_extract"
    assert str(restored) == str(error)


def test_clean_text_raises_nothing() -> None:
    assert_clean("Score must be at least 755.", stage="s2_extract")


def test_a_pattern_can_be_switched_off_individually() -> None:
    """A deployment whose data trips one rule narrows that rule, not the whole tripwire."""
    text = "call 555-123-4567"
    assert scan(text) != []
    assert scan(text, enabled=set(PATTERNS) - {"phone"}) == []


# --- wired into the adapter -----------------------------------------------------------


def test_the_adapter_refuses_to_send_a_prompt_with_personal_data() -> None:
    client = MockClient(LLMSettings())
    with pytest.raises(PiiDetected):
        client.complete("system", "the row is 123-45-6789", stage="s2_extract")
    assert client.prompts == [], "nothing may reach the provider"


def test_the_adapter_sends_a_clean_prompt() -> None:
    client = MockClient(LLMSettings())
    client.complete("system", "score at least 755", stage="s9_summarize")
    assert len(client.prompts) == 1


def test_the_tripwire_runs_before_the_cache() -> None:
    """Otherwise the answer would depend on whether this content was seen before."""
    client = MockClient(LLMSettings())
    client.complete("system", "clean text", stage="s9_summarize")
    with pytest.raises(PiiDetected):
        client.complete("system", "clean text 123-45-6789", stage="s9_summarize")


def test_the_tripwire_can_be_disabled_for_a_deployment_that_must() -> None:
    """It is on by default and documented as something to leave on."""
    assert LLMSettings().pii_tripwire is True
    client = MockClient(LLMSettings(pii_tripwire=False))
    client.complete("system", "123-45-6789", stage="s9_summarize")
    assert len(client.prompts) == 1


def test_the_setting_is_read_from_the_environment() -> None:
    assert LLMSettings.from_env({"LLM_PII_TRIPWIRE": "false"}).pii_tripwire is False
    assert LLMSettings.from_env({}).pii_tripwire is True
