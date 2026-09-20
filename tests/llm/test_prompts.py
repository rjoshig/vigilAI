"""Tests for the versioned prompt templates.

These enforce the rules in ``docs/llm-privacy.md``: one narrow task, JSON-only output
validated by a schema, no arithmetic asked of the model, and no sample rows.
"""

from __future__ import annotations

import json
import re
from string import Template

import pytest

from greenlight_ai.llm import MockClient, extract_json
from greenlight_ai.llm.prompts import PROMPTS, Prompt, get_prompt, prompt_versions
from greenlight_ai.llm.prompts.registry import register

#: The pipeline stages that call a model (``docs/architecture.md`` "The pipeline").
PIPELINE_STAGES = {
    "s2_extract",
    "s3_describe",
    "s4_trace",
    "s8_programme",
    "s8_coverage",
    "s8_verify",
    "s8_lens_delivery",
    "s8_lens_compliance",
    "s8_lens_requirements",
    "s9_summarize",
}

#: The admin flow's prompts: drafting a check (once, at authoring time) and answering a
#: judgment check (``docs/design.md`` "Configurable checks").
ADMIN_STAGES = {
    "admin_classify",
    "admin_draft_check",
    "admin_judgment",
    "admin_map_requirement",
}

#: Turning what reviewers wrote into a candidate rule, once, when an administrator
#: asks for it (ADR-021). Like drafting, it is authoring-time rather than per-run.
TRAINING_STAGES = {"training_synthesize", "training_critique"}

#: Every registered prompt. The rules below apply to all of them equally.
LLM_STAGES = PIPELINE_STAGES | ADMIN_STAGES | TRAINING_STAGES

#: Anything shaped like a real identifier must never appear in a prompt (ADR-003).
_PII_TRIPWIRE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _placeholders(prompt: Prompt) -> set[str]:
    return {
        match[1] or match[2]
        for match in Template.pattern.findall(prompt.template)
        if match[1] or match[2]
    }


def test_every_llm_stage_has_a_prompt() -> None:
    assert set(PROMPTS) == LLM_STAGES


def test_the_admin_flow_registers_every_prompt_it_claims() -> None:
    """Each is authoring-time and happens once; everything else in the admin flow is code."""
    assert set(PROMPTS) & ADMIN_STAGES == ADMIN_STAGES


def test_every_prompt_declares_a_version() -> None:
    """The version is part of the cache key, so a prompt without one is unsafe."""
    for stage, version in prompt_versions().items():
        assert version, f"{stage} has no version"


def test_every_prompt_has_a_schema() -> None:
    for prompt in PROMPTS.values():
        assert prompt.schema is not None


@pytest.mark.parametrize("stage", sorted(LLM_STAGES))
def test_every_prompt_demands_json_only(stage: str) -> None:
    system = get_prompt(stage).system.lower()
    assert "json object" in system
    assert "no prose" in system


#: An instruction to compute, unless it is negated ("do not compute", "never compare").
#: Word boundaries keep "recompute" in "do not recompute them" from matching.
_UNNEGATED_COMPUTE = re.compile(
    r"(?<!do not )(?<!never )(?<!not )\b(calculate|compute|add up|sum|subtract|compare)\b"
)


@pytest.mark.parametrize("stage", sorted(LLM_STAGES))
def test_no_prompt_asks_the_model_to_compare_or_compute(stage: str) -> None:
    """ADR-001: the LLM reads and judges meaning; code does every comparison."""
    system = get_prompt(stage).system.lower()
    match = _UNNEGATED_COMPUTE.search(system)
    assert match is None, f"{stage} asks the model to {match.group()!r}"


@pytest.mark.parametrize("stage", sorted(LLM_STAGES))
def test_every_prompt_states_the_prohibition_explicitly(stage: str) -> None:
    """Saying what not to do is what keeps a mid-size model from volunteering it."""
    assert "do not" in get_prompt(stage).system.lower()


def test_extraction_prompts_tell_the_model_not_to_infer() -> None:
    assert "never infer" in get_prompt("s2_extract").system.lower()


def test_trace_prompt_states_that_differing_values_still_count_as_implemented() -> None:
    """The judge answers subject-matter, not equality; stage 5 compares the values."""
    system = get_prompt("s4_trace").system.lower()
    assert "even when the two thresholds differ" in system or "even if the values differ" in system


def test_verify_prompt_says_a_disagreement_does_not_delete_the_finding() -> None:
    assert "does not delete the finding" in get_prompt("s8_verify").system.lower()


def test_summarize_prompt_forbids_inventing_issues() -> None:
    system = get_prompt("s9_summarize").system.lower()
    assert "never introduce an issue that is not in the list" in system


@pytest.mark.parametrize("stage", sorted(LLM_STAGES))
def test_no_prompt_contains_anything_resembling_a_sample_row(stage: str) -> None:
    prompt = get_prompt(stage)
    text = prompt.system + prompt.template
    assert not _PII_TRIPWIRE.search(text)
    for banned in ("SSN", "first_name", "last_name", "date_of_birth"):
        assert banned.lower() not in text.lower()


@pytest.mark.parametrize("stage", sorted(LLM_STAGES))
def test_worked_examples_are_present_and_parse_as_json(stage: str) -> None:
    """Two to three worked examples per extraction prompt keep a mid-size model honest."""
    template = get_prompt(stage).template
    answers = re.findall(r"Answer:\n(\{.*?\})\n", template, re.DOTALL)
    assert len(answers) >= 2, f"{stage} has fewer than two worked examples"
    for answer in answers:
        assert isinstance(json.loads(answer), dict)


@pytest.mark.parametrize("stage", sorted(LLM_STAGES))
def test_worked_example_answers_validate_against_the_stage_schema(stage: str) -> None:
    """An example the schema would reject teaches the model the wrong shape."""
    prompt = get_prompt(stage)
    for answer in re.findall(r"Answer:\n(\{.*?\})\n", prompt.template, re.DOTALL):
        prompt.schema.model_validate(json.loads(answer))


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("s2_extract", {"section"}),
        ("s3_describe", {"block"}),
        ("s4_trace", {"requirement", "element"}),
        ("s8_programme", {"programme", "rules", "delivery"}),
        ("s8_verify", {"finding", "evidence"}),
        ("s8_coverage", {"requirements"}),
        ("s8_lens_delivery", {"finding", "evidence"}),
        ("s8_lens_compliance", {"finding", "evidence"}),
        ("s8_lens_requirements", {"finding", "evidence"}),
        ("s9_summarize", {"findings", "coverage"}),
        ("admin_classify", {"attributes", "report_types", "statement"}),
        ("admin_draft_check", {"description", "report_types"}),
        ("admin_judgment", {"instruction", "values"}),
        ("admin_map_requirement", {"section", "blocks", "cells"}),
        ("training_synthesize", {"attributes", "report_types", "statements"}),
        ("training_critique", {"statements", "existing", "draft"}),
    ],
)
def test_each_prompt_takes_exactly_the_inputs_its_stage_supplies(
    stage: str, expected: set[str]
) -> None:
    assert _placeholders(get_prompt(stage)) == expected


def test_rendering_fills_the_placeholders_and_leaves_examples_intact() -> None:
    prompt = get_prompt("s4_trace")
    rendered = prompt.render(requirement="score at least 755", element="score minimum 750")
    assert "score at least 755" in rendered
    assert "score minimum 750" in rendered
    assert '{"verdict": "implemented"' in rendered
    assert "$requirement" not in rendered


def test_a_missing_placeholder_fails_loudly_rather_than_rendering_a_hole() -> None:
    with pytest.raises(KeyError):
        get_prompt("s4_trace").render(requirement="only one given")


def test_registering_a_stage_twice_is_rejected() -> None:
    """Otherwise the effective prompt would depend on import order."""
    with pytest.raises(ValueError, match="already registered"):
        register(get_prompt("s2_extract"))


def test_the_drafting_prompt_lists_the_permitted_expression_grammar() -> None:
    """An admin check is untrusted input; the prompt must not invite anything else."""
    system = get_prompt("admin_draft_check").system.lower()
    assert "no attribute access" in system
    assert "abs, min, max, round" in system


def test_the_judgment_prompt_never_sees_the_reports() -> None:
    """It receives named values and reasoning only (docs/design.md)."""
    system = get_prompt("admin_judgment").system.lower()
    assert "you cannot see the reports" in system
    assert 'prefer "review" to a guess' in system


def test_a_prompt_round_trips_through_the_mock_client() -> None:
    client = MockClient()
    prompt = get_prompt("s2_extract")
    result = client.complete(
        prompt.system,
        prompt.render(section="3 Geography\nInclude only consumers in Illinois."),
        prompt.schema,
        stage=prompt.stage,
        prompt_version=prompt.version,
    )
    assert extract_json(result.text) == {"requirements": []}


def test_prompt_version_is_part_of_the_cache_key() -> None:
    """Editing a prompt must refresh results; leaving the version alone would not."""
    client = MockClient()
    prompt = get_prompt("s9_summarize")
    client.complete(prompt.system, "same", prompt.schema, stage=prompt.stage, prompt_version="1")
    second = client.complete(
        prompt.system, "same", prompt.schema, stage=prompt.stage, prompt_version="2"
    )
    assert second.cached is False
