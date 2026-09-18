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
from typing import Final

__all__ = ["RunGuidance", "preamble", "MAX_CONTEXT_CHARS"]

_LOG: Final = logging.getLogger(__name__)

#: Guidance longer than this is truncated. An administrator with a essay to add is
#: really describing a requirement, which belongs in the OSL or in a check, and a
#: prompt that is mostly preamble reads worse than one with none.
MAX_CONTEXT_CHARS: Final[int] = 1500


@dataclass(frozen=True, slots=True)
class RunGuidance:
    """Everything an administrator has said about this run's context.

    Attributes:
        scope_label: The programme's name, e.g. ``"Account Monitoring"``.
        scope_instructions: Compliance expectations true of every run in the scope.
        has_suppressions: Whether the submitter said suppressions were applied.
        artifact_context: Per-artifact guidance, keyed by artifact key.
    """

    scope_label: str = ""
    scope_instructions: str = ""
    has_suppressions: bool | None = None
    artifact_context: dict[str, str] | None = None

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
        "from the document itself.\n" + "\n".join(f"- {line}" for line in lines) + "\n\n"
    )
