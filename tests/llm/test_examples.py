"""The administrator's library of worked examples (Phase 6.13d, ADR-038).

Every prompt's examples lived in Python. An administrator could give the model
background prose and the guide and meaning maps, and not one "this wording means this
requirement" pair. These tests hold the library to the discipline that makes that safe:
an answer the stage's schema rejects is refused, examples are capped and ordered by how
specific their scope is, and nothing an administrator wrote is ever read as a template.
"""

from __future__ import annotations

import json

import pytest

from greenlight_ai import scopes
from greenlight_ai.llm import examples as library
from greenlight_ai.llm.prompts import get_prompt


def _extract(
    given: str = "9 Channel\nDeliver the file by SFTP only.",
    scope: str = scopes.EVERYWHERE,
    example_id: int = 1,
    sort_order: int = 0,
) -> library.LibraryExample:
    return library.LibraryExample(
        id=example_id,
        stage="s2_extract",
        scope=scope,
        given={"section": given},
        answer={
            "requirements": [{"req_type": "other", "source_text": "Deliver the file by SFTP only."}]
        },
        sort_order=sort_order,
    )


# --- what may be stored ------------------------------------------------------------------


def test_an_answer_the_stage_schema_rejects_is_refused() -> None:
    """An example the schema would reject teaches a shape the pipeline cannot parse."""
    with pytest.raises(library.ExampleError) as raised:
        library.validate_example(
            "s2_extract",
            {"section": "3 Geography\nIllinois only."},
            {"requirements": [{"req_type": "not_a_type"}]},
        )
    assert "req_type" in str(raised.value), "the refusal names the field"


def test_an_example_that_shows_nothing_is_refused() -> None:
    with pytest.raises(library.ExampleError) as raised:
        library.validate_example("s4_trace", {"requirement": "score at least 755"}, {})
    assert "element" in str(raised.value)


def test_a_stage_that_takes_no_examples_is_refused() -> None:
    with pytest.raises(library.ExampleError) as raised:
        library.validate_example("s9_summarize", {}, {})
    assert "s2_extract" in str(raised.value), "the refusal lists the stages that do"


def test_a_stored_example_is_the_schema_own_dump() -> None:
    """What is stored is what the model will be shown, not what was typed."""
    given, answer = library.validate_example(
        "s4_trace",
        {"requirement": "  score at least 755  ", "element": "rules.score_v3"},
        {"verdict": "implemented", "reason": "Same threshold.", "confidence": 0.9},
    )
    assert given["requirement"] == "score at least 755"
    assert answer == {"verdict": "implemented", "reason": "Same threshold.", "confidence": 0.9}
    get_prompt("s4_trace").schema.model_validate(answer)


@pytest.mark.parametrize("stage", library.EXAMPLE_STAGES)
def test_every_stage_in_the_table_has_a_prompt_and_a_seam(stage: str) -> None:
    """A stage with nowhere to put an example must not be offered as a place to put one."""
    template = get_prompt(stage).template
    assert template.count("\nNow ") == 1, f"{stage} has no single seam"
    assert library.fields_for(stage), f"{stage} names no fields"


# --- which examples a prompt carries -------------------------------------------------------


def test_the_narrowest_scope_is_shown_first() -> None:
    chosen = library.select(
        [
            _extract(scope=scopes.EVERYWHERE, example_id=1),
            _extract(scope="config:CFG-1", example_id=2),
            _extract(scope="programme:AM", example_id=3),
        ]
    )
    assert [example.id for example in chosen] == [2, 3, 1]


def test_no_more_than_four_examples_reach_a_prompt() -> None:
    chosen = library.select([_extract(example_id=n, sort_order=n) for n in range(1, 9)])
    assert len(chosen) == library.MAX_PER_STAGE


# --- how they are rendered ------------------------------------------------------------------


def test_the_library_is_labelled_as_examples_and_not_as_rules() -> None:
    block = library.render_block([_extract()])
    assert library.PREAMBLE in block
    assert "they are not rules" in block


def test_numbering_continues_from_the_built_in_examples() -> None:
    template = get_prompt("s2_extract").template
    block = library.render_block([_extract()], start=library.next_number(template))
    assert "Example 7" in block, "the prompt ships six, so the library starts at seven"


def test_each_stage_labels_its_example_the_way_its_built_ins_do() -> None:
    trace = library.LibraryExample(
        stage="s4_trace",
        given={"requirement": "score at least 755", "element": "rules.score_v3"},
        answer={"verdict": "implemented"},
    )
    statement = library.LibraryExample(
        stage="admin_classify",
        given={"statement": "The origination date is never blank."},
        answer={"surface": "field_constraint"},
    )
    assert "Requirement: score at least 755" in library.render_block([trace])
    assert "Element: rules.score_v3" in library.render_block([trace])
    assert (
        "<statement>\nThe origination date is never blank.\n</statement>"
        in library.render_block([statement])
    )


def test_an_example_lands_after_the_built_ins_and_before_the_task() -> None:
    prompt = get_prompt("s2_extract")
    rendered = prompt.render_with_examples([_extract()], section="4 Credit criteria")

    library_at = rendered.index(library.PREAMBLE)
    assert library_at > rendered.index("Example 1"), "the built-in examples stay first"
    assert library_at < rendered.index("Now do the same"), "the task stays last"
    assert rendered.endswith("4 Credit criteria\n\nAnswer:"), "the task is intact"


def test_the_prompt_text_changes_which_is_what_changes_the_cache_key() -> None:
    prompt = get_prompt("s3_describe")
    plain = prompt.render(block="rules.score_v3")
    with_example = prompt.render_with_examples(
        [
            library.LibraryExample(
                stage="s3_describe",
                given={"block": "rules.state_filter"},
                answer={"elements": []},
            )
        ],
        block="rules.score_v3",
    )
    assert with_example != plain, "an added example refreshes exactly the calls it changes"
    assert prompt.render_with_examples([], block="rules.score_v3") == plain


def test_nothing_an_administrator_wrote_is_read_as_a_placeholder() -> None:
    """An example is inserted into the rendered prompt, never substituted into it."""
    dollars = _extract(given="9 Fees\nA $section fee of $5 applies. $$")
    rendered = get_prompt("s2_extract").render_with_examples([dollars], section="4 Criteria")
    assert "A $section fee of $5 applies. $$" in rendered


def test_an_example_is_shown_as_the_json_the_stage_returns() -> None:
    rendered = get_prompt("s2_extract").render_with_examples([_extract()], section="4 Criteria")
    answer = rendered.split(library.PREAMBLE)[1].split("Answer:\n")[1].split("\n")[0]
    assert json.loads(answer) == _extract().answer
