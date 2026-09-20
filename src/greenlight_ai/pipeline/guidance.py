"""Turning admin-written guidance into the preamble a prompt carries (ADR-020).

Two kinds of context exist, and they answer different questions:

- **Artifact guidance** — what this document is and what to pay attention to in it.
- **Scope standing instructions** — which compliance regime the whole delivery sits
  under, which is usually not restated in the OSL.

Both are optional. With neither configured, :func:`preamble` returns an empty string
and every prompt is byte-for-byte what the pipeline sent before any of this existed.
That is deliberate: configuring nothing must change nothing.

The preamble is part of the rendered prompt, so it is part of the cache key
(ADR-005). Editing guidance therefore invalidates exactly the calls it affects,
without anyone having to remember to bump a version.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Sequence

__all__ = [
    "guide_block",
    "RunGuidance",
    "preamble",
    "MAX_BLOCK_CHARS",
    "MAX_CONTEXT_CHARS",
]

_LOG: Final = logging.getLogger(__name__)

#: Guidance longer than this is truncated. An administrator with a essay to add is
#: really describing a requirement, which belongs in the OSL or in a check, and a
#: prompt that is mostly preamble reads worse than one with none.
MAX_CONTEXT_CHARS: Final[int] = 1500

#: The ceiling on everything the administrator contributes to one prompt, across all
#: its fields (Phase 6.11e). ``MAX_CONTEXT_CHARS`` caps each field on its own, which
#: left the total unbounded in the number of configuration notes: ten notes were ten
#: times the cap. A prompt that is mostly preamble reads worse than one with none, so
#: the block is trimmed as a whole and the model is told what was left out.
MAX_BLOCK_CHARS: Final[int] = 6000


@dataclass(frozen=True, slots=True)
class RunGuidance:
    """Everything an administrator has said about this run's context.

    Attributes:
        scope_label: The programme's name, e.g. ``"Account Monitoring"``.
        scope_instructions: Compliance expectations true of every run in the scope.
        has_suppressions: Whether the submitter said suppressions were applied.
        deliverable_count: How many deliverables the campaign has, as stated. Zero
            means unstated.
        outputs_validated: How many of them this run covers. Zero means unstated.
        delivery_notes: Anything else the submitter said about the delivery.
        config_notes: Standing notes on the run's ETL configuration, written by
            whoever knows it (ADR-024). Background, never a requirement.
        scope_code: The programme's code.
        programme_rules: The programme's rules, each with its strictness.
        programme_keywords: Every programme's keywords, for the classification check.
        artifact_context: Per-artifact guidance, keyed by artifact key.
        validation_guides: One rendered guide per report type, each a tuple of lines
            (Phase 6.8b). Read by stages 4 and 8 as background.
    """

    scope_label: str = ""
    scope_instructions: str = ""
    has_suppressions: bool | None = None
    deliverable_count: int = 0
    outputs_validated: int = 0
    delivery_notes: str = ""
    config_notes: tuple[str, ...] = ()
    artifact_context: dict[str, str] | None = None
    #: The programme's code, and its rules as (id, title, text, strictness). The
    #: model reads for breaches of these; code sets the severity (ADR-026).
    #: The credit date the submitter gave, for the artifact check (ADR-027).
    credit_date: str = ""
    scope_code: str = ""
    programme_rules: tuple[tuple[int, str, str, str], ...] = ()
    #: Every programme's keywords, for the classification check: code to words.
    programme_keywords: dict[str, tuple[str, ...]] | None = None
    validation_guides: tuple[tuple[str, ...], ...] = ()

    @property
    def is_empty(self) -> bool:
        """Whether there is nothing to say.

        Returns:
            ``True`` when no scope, no instructions, and no artifact guidance are
            configured, which is the state a fresh install is in.
        """
        return not (
            self.scope_label
            or self.scope_instructions.strip()
            or self.deliverable_count
            or self.delivery_notes.strip()
            or any(note.strip() for note in self.config_notes)
            or any((self.artifact_context or {}).values())
        )

    def for_artifact(self, key: str) -> str:
        """The guidance written for one artifact.

        Args:
            key: The artifact key, e.g. ``"osl"`` or ``"dirt"``.

        Returns:
            The text, or an empty string.
        """
        return (self.artifact_context or {}).get(key, "").strip()


def _clip(text: str) -> str:
    """Trim guidance to a sensible prompt length.

    Args:
        text: The administrator's text.

    Returns:
        The text, truncated at a word boundary with an ellipsis when it is too long.
    """
    cleaned = " ".join(text.split())
    if len(cleaned) <= MAX_CONTEXT_CHARS:
        return cleaned
    cut = cleaned[:MAX_CONTEXT_CHARS].rsplit(" ", 1)[0]
    _LOG.info("guidance truncated from %d to %d characters", len(cleaned), len(cut))
    return f"{cut}…"


def _fit(lines: Sequence[str], what: str, bullet: bool = True) -> str:
    """Render lines within the whole-block ceiling.

    The oldest lines go first when there are too many, because the newest note is the
    one someone wrote most recently about this configuration. What was dropped is said
    out loud rather than silently omitted: a model told nine of ten notes should not
    believe it has ten.

    Args:
        lines: The lines to render, oldest first.
        what: What a dropped line is called, for the note that replaces it.
        bullet: Whether to prefix each line with a dash.

    Returns:
        The rendered block.
    """
    rendered = [f"- {line}" if bullet else line for line in lines]
    total = sum(len(line) + 1 for line in rendered)
    if total <= MAX_BLOCK_CHARS:
        return "\n".join(rendered)

    kept: list[str] = []
    used = 0
    for line in reversed(rendered):
        if used + len(line) + 1 > MAX_BLOCK_CHARS:
            break
        kept.append(line)
        used += len(line) + 1
    kept.reverse()
    dropped = len(rendered) - len(kept)
    _LOG.info("guidance block trimmed: %d of %d %s(s) dropped", dropped, len(rendered), what)
    marker = f"({dropped} older {what}(s) omitted to keep this prompt short.)"
    return "\n".join([f"- {marker}" if bullet else marker, *kept])


def preamble(guidance: RunGuidance | None, artifact_key: str = "") -> str:
    """Build the context block that goes above a prompt's task.

    Args:
        guidance: What the administrator configured, or ``None``.
        artifact_key: The artifact this prompt is about, when it is about one.

    Returns:
        A short block ending in a blank line, or an empty string when nothing is
        configured. The wording tells the model this is background, not a requirement:
        standing instructions are context for reading the OSL, never a substitute for
        what the OSL says.
    """
    if guidance is None or guidance.is_empty:
        return ""

    lines: list[str] = []
    if guidance.scope_label:
        lines.append(f"This delivery is {guidance.scope_label}.")
    if guidance.has_suppressions is not None:
        lines.append(
            "Suppressions were applied to it."
            if guidance.has_suppressions
            else "No suppressions were applied to it."
        )
    if guidance.deliverable_count:
        covered = guidance.outputs_validated or guidance.deliverable_count
        lines.append(
            f"The campaign has {guidance.deliverable_count} deliverable(s); this run "
            f"validates {covered} of them."
        )
    if guidance.delivery_notes.strip():
        lines.append(f"The submitter added: {_clip(guidance.delivery_notes)}")
    for note in guidance.config_notes:
        if note.strip():
            lines.append(f"A note on this configuration, as background: {_clip(note)}")
    if guidance.scope_instructions.strip():
        lines.append(
            "Standing instructions for this programme, as background: "
            f"{_clip(guidance.scope_instructions)}"
        )

    artifact = guidance.for_artifact(artifact_key) if artifact_key else ""
    if artifact:
        lines.append(f"About the document below: {_clip(artifact)}")

    if not lines:
        return ""

    return (
        "Context, which is background rather than a requirement. Requirements come only "
        "from the document itself.\n" + _fit(lines, "context line") + "\n\n"
    )


def guide_block(guidance: RunGuidance | None) -> str:
    """The validation guides as one block for a prompt, or nothing.

    Args:
        guidance: What was configured.

    Returns:
        The guides, one per report type, labelled as background, followed by a blank
        line; the empty string when no guide exists, so the prompt is byte-for-byte
        what it was before guides existed.
    """
    if guidance is None or not guidance.validation_guides:
        return ""
    header = "Background from the administrator. Read it for meaning; do not compare values."
    lines: list[str] = []
    for guide in guidance.validation_guides:
        lines.extend(guide)
    return header + "\n" + _fit(lines, "guide line", bullet=False) + "\n\n"
