"""Worked examples an administrator gives the model (Phase 6.13d, ADR-038).

Every prompt ships with worked examples written in Python, and they are the floor: they
teach a mid-size model the shape of a good answer. What an administrator could not do
was add one. They could give the model background prose and the guide and meaning maps,
but not a single *this wording means this requirement* pair drawn from the deliveries
they actually see.

This module is the shape of that library. A stored example names a stage, says what the
model would be shown (``given``) and what a good answer looks like (``answer``), and is
refused unless the answer validates against the stage's own schema — the same check the
prompt suite applies to the built-in examples. An example that the schema would reject
teaches the wrong shape, which is worse than no example at all.

Three rules keep the library honest:

- **Examples show, they never instruct.** They are rendered under a line that says so,
  after the built-in ones. Nothing in this module can make the model do anything; the
  rules the engine runs live in the rule tables and are evaluated by code (ADR-001).
- **At most four per stage**, most specific scope first. A prompt that is mostly
  examples stops being a prompt.
- **The rendered text is part of the cache key by itself.** Examples are inserted into
  the user prompt, and the cache key is the hash of what was sent (ADR-005), so adding
  an example refreshes exactly the calls it changes and nothing else.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Final, Iterable, Literal, Mapping, Sequence

from greenlight_ai import scopes

__all__ = [
    "EXAMPLE_STAGES",
    "ExampleError",
    "ExampleField",
    "LibraryExample",
    "MAX_PER_STAGE",
    "PREAMBLE",
    "STAGE_FIELDS",
    "fields_for",
    "render_block",
    "select",
    "validate_example",
]

#: How many library examples any one prompt may carry. Four is what fits beside the
#: built-ins without the task itself becoming the smallest part of the prompt.
MAX_PER_STAGE: Final[int] = 4

#: The line the library's examples are rendered under. It says what they are, because a
#: model shown an unlabelled block of text may read it as an instruction.
PREAMBLE: Final[str] = (
    "Worked examples from the administrator. They show the shape of a good answer; "
    "they are not rules."
)


@dataclass(frozen=True, slots=True)
class ExampleField:
    """One part of what a stage shows the model in an example.

    Attributes:
        name: The key in the example's ``given`` mapping.
        label: How the built-in examples label it, e.g. ``"Section"``.
        shape: ``line`` renders ``Label: value``; ``block`` renders ``Label:`` and the
            value on the next line; ``tag`` wraps the value in ``<label>`` markers, the
            way a stage that takes somebody's own words does.
    """

    name: str
    label: str
    shape: Literal["line", "block", "tag"] = "line"


#: The stages an administrator may add examples to, with the parts each one shows. It
#: is a closed set: a stage whose prompt has no worked examples has nowhere to put one,
#: and a stage that carries report values is not a place to put text by hand.
STAGE_FIELDS: Final[Mapping[str, tuple[ExampleField, ...]]] = {
    "s2_extract": (ExampleField("section", "Section", "block"),),
    "s3_describe": (ExampleField("block", "Block", "block"),),
    "s4_trace": (
        ExampleField("requirement", "Requirement"),
        ExampleField("element", "Element"),
    ),
    "admin_judgment": (
        ExampleField("instruction", "Rule"),
        ExampleField("values", "Values"),
    ),
    "admin_classify": (ExampleField("statement", "statement", "tag"),),
    "training_synthesize": (ExampleField("statements", "statements", "tag"),),
}

#: The stage names, for a closed-set check on the wire and in the database.
EXAMPLE_STAGES: Final[tuple[str, ...]] = tuple(sorted(STAGE_FIELDS))


class ExampleError(ValueError):
    """An example that would teach the model something wrong, and is not stored."""


@dataclass(frozen=True, slots=True)
class LibraryExample:
    """One stored example, as the prompt layer sees it.

    Attributes:
        id: The row it came from, for ordering and for saying which example is which.
        stage: Which prompt it belongs to.
        scope: Where it applies, as a scope token (:mod:`greenlight_ai.scopes`).
        given: What the model would be shown, keyed by the stage's field names.
        answer: A good answer, already validated against the stage's schema.
        note: Why it is here. Never rendered into the prompt; it is for the next
            administrator, not for the model.
        sort_order: The administrator's ordering within a scope.
    """

    id: int = 0
    stage: str = ""
    scope: str = scopes.EVERYWHERE
    given: Mapping[str, str] = field(default_factory=dict)
    answer: Mapping[str, object] = field(default_factory=dict)
    note: str = ""
    sort_order: int = 0


def fields_for(stage: str) -> tuple[ExampleField, ...]:
    """The parts one stage's examples are made of.

    Args:
        stage: The prompt stage.

    Returns:
        Its fields, in the order the prompt shows them.

    Raises:
        ExampleError: When the stage takes no library examples.
    """
    try:
        return STAGE_FIELDS[stage]
    except KeyError:
        raise ExampleError(
            f"{stage!r} takes no worked examples; choose one of {', '.join(EXAMPLE_STAGES)}"
        ) from None


def validate_example(
    stage: str, given: Mapping[str, object], answer: Mapping[str, object]
) -> tuple[dict[str, str], dict[str, object]]:
    """Check an example before it is stored, and return it in canonical form.

    The answer is validated against the stage's own Pydantic schema, which is the same
    check :mod:`tests.llm.test_prompts` applies to the built-in examples. An example the
    schema would reject teaches the model a shape the pipeline then refuses to parse.

    Args:
        stage: The prompt stage.
        given: What the model would be shown, keyed by the stage's field names.
        answer: The answer to teach.

    Returns:
        The given mapping with every field present as a string, and the answer as the
        schema itself dumps it, keeping only what was actually said, so a stored example
        reads as tersely as the built-in ones and still satisfies the schema.

    Raises:
        ExampleError: When the stage is unknown, a field is missing or empty, or the
            answer does not satisfy the stage's schema. The message names the field.
    """
    from greenlight_ai.llm.prompts.registry import get_prompt  # local: prompts import this

    parts = fields_for(stage)
    cleaned: dict[str, str] = {}
    for part in parts:
        value = str(given.get(part.name, "") or "").strip()
        if not value:
            raise ExampleError(f"an example for {stage} needs {part.name!r}")
        cleaned[part.name] = value

    try:
        schema = get_prompt(stage).schema
    except KeyError:  # pragma: no cover - a stage in the table is always registered
        raise ExampleError(f"{stage!r} has no prompt") from None
    try:
        validated = schema.model_validate(dict(answer))
    except Exception as exc:  # pydantic raises its own error type
        raise ExampleError(f"the answer is not a valid {stage} answer: {exc}") from exc

    return cleaned, validated.model_dump(mode="json", exclude_defaults=True)


def _rank(scope: str) -> int:
    """How specific a scope is; higher is shown first."""
    parsed = scopes.parse(scope)
    if parsed.kind == "configuration":
        return 3
    if parsed.kind in ("programme", "customer"):
        return 2
    return 0


def select(
    examples: Iterable[LibraryExample], limit: int = MAX_PER_STAGE
) -> tuple[LibraryExample, ...]:
    """Choose which examples a prompt carries, most specific scope first.

    Args:
        examples: Candidates, already scoped to the run.
        limit: How many to keep.

    Returns:
        At most ``limit`` examples: the narrowest scopes first, then the
        administrator's own order, then oldest first so the choice is stable.
    """
    ordered = sorted(examples, key=lambda ex: (-_rank(ex.scope), ex.sort_order, ex.id))
    return tuple(ordered[: max(0, limit)])


def _render_given(example: LibraryExample) -> str:
    """The shown part of one example, labelled the way its stage's built-ins are."""
    lines: list[str] = []
    for part in fields_for(example.stage):
        value = str(example.given.get(part.name, "")).strip()
        if part.shape == "tag":
            lines.append(f"<{part.label}>\n{value}\n</{part.label}>")
        elif part.shape == "block":
            lines.append(f"{part.label}:\n{value}")
        else:
            lines.append(f"{part.label}: {value}")
    return "\n".join(lines)


def render_block(examples: Sequence[LibraryExample], start: int = 1) -> str:
    """Render the library's examples in the shape the built-in ones use.

    Args:
        examples: The examples to show, already selected and ordered.
        start: The number to give the first one, so the numbering continues from the
            built-in examples rather than starting again at one.

    Returns:
        The block to insert into the user prompt, ending with a blank line. Empty when
        there is nothing to show.
    """
    if not examples:
        return ""
    parts = [PREAMBLE, ""]
    for offset, example in enumerate(examples):
        parts.append(f"Example {start + offset}")
        parts.append(_render_given(example))
        parts.append("Answer:")
        parts.append(json.dumps(example.answer, separators=(", ", ": ")))
        parts.append("")
    return "\n".join(parts) + "\n"


#: Matches the built-in examples' numbering, so the library's continue from it.
_NUMBERED: Final = re.compile(r"^Example (\d+)\b", re.MULTILINE)


def next_number(template: str) -> int:
    """The number to give the first library example in a template.

    Args:
        template: The prompt template, with its built-in examples.

    Returns:
        One past the highest ``Example N`` it already carries.
    """
    numbers = [int(match) for match in _NUMBERED.findall(template)]
    return (max(numbers) + 1) if numbers else 1
