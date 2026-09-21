"""The nine switches the report chat reads, resolved per request (Phase 8f).

Every one is an administrator's decision rather than a deployment's, so they all live in
`config/registry.py` as ordinary `SettingSpec` rows in a **Chat** group and resolve
through the three layers of ADR-023: the console over `.env` over the built-in default.
Nothing bespoke is built for them — the console renders the group and the existing
settings screen gains a section.

**Resolved where they are used, never read into a module constant** (`CLAUDE.md`). A
conversation that started before an administrator lowered a cap obeys the new cap on its
next question, which is what an administrator expects of a lever they just pulled.

**The model defaults to the pipeline's.** Unset, `chat.model` follows whatever the
Model section says, so a deployment that upgrades gains nothing it did not have. Because
the model name is already part of every cache key, the two can never serve each other's
answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from greenlight_ai.config.store import resolve

__all__ = ["ChatSettings", "chat_settings"]

#: Temperature is stored as whole percent because the console renders integers with a
#: minimum and a maximum, and a float field would need a kind of its own for one row.
_PERCENT: Final[int] = 100


@dataclass(frozen=True, slots=True)
class ChatSettings:
    """What the chat may do, as an administrator has set it.

    Attributes:
        enabled: Whether the feature exists at all for this deployment.
        model: Which model answers. Empty means the pipeline's.
        max_tokens: The ceiling on one answer.
        temperature: 0.0–1.0, derived from the whole-percent row.
        max_questions_per_run: How long one conversation may go.
        max_questions_per_day: The per-person daily ceiling. Zero denies the feature,
            which is the lever for a staged rollout.
        max_turns: How much transcript is re-sent with each question — the main cost
            lever, because every turn re-sends the ones before it.
        timeout_s: How long one answer may take before it is abandoned.
        report_aggregates: Whether the pack may carry code-computed per-column figures
            (Phase 8g). **This one changes what leaves the building.**
    """

    enabled: bool = False
    model: str = ""
    max_tokens: int = 800
    temperature: float = 0.0
    max_questions_per_run: int = 20
    max_questions_per_day: int = 50
    max_turns: int = 8
    timeout_s: int = 60
    report_aggregates: bool = False


def chat_settings(session: Session) -> ChatSettings:
    """Resolve every chat setting for this request.

    Args:
        session: An open session.

    Returns:
        The effective settings, each through the console / environment / default
        layers (ADR-023).
    """
    return ChatSettings(
        enabled=bool(resolve(session, "chat.enabled").value),
        model=str(resolve(session, "chat.model").value or ""),
        max_tokens=int(resolve(session, "chat.max_tokens").value),
        temperature=int(resolve(session, "chat.temperature_pct").value) / _PERCENT,
        max_questions_per_run=int(resolve(session, "chat.max_questions_per_run").value),
        max_questions_per_day=int(resolve(session, "chat.max_questions_per_day").value),
        max_turns=int(resolve(session, "chat.max_turns").value),
        timeout_s=int(resolve(session, "chat.timeout_s").value),
        report_aggregates=bool(resolve(session, "chat.report_aggregates").value),
    )
