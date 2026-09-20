"""Wire models for the training loop (ADR-021).

An observation is what a person wrote and what they pointed at. A candidate is what
the model made of it. Neither runs; a rule does, and only after someone approves it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Anchor",
    "ObservationIn",
    "ObservationOut",
    "ObservationDecision",
    "SynthesizeIn",
    "CandidateOut",
    "CandidateDecision",
    "RuleOut",
    "RuleAction",
    "RuleStateChangeOut",
    "TrainingConfigOut",
    "ConfigNoteIn",
]

AnchorKind = Literal["report_cell", "report_field", "osl_section", "config_path", "finding"]


class Anchor(BaseModel):
    """What an observation points at.

    The anchor is the difference between a rule the model can synthesize reliably and
    one it has to guess at, which is why the form collects a selection rather than
    prose alone.
    """

    model_config = ConfigDict(extra="forbid")

    kind: AnchorKind
    #: The artifact key for a report anchor, e.g. ``"dirt"``.
    artifact: str = ""
    sheet: str = ""
    cell: str = ""
    field: str = ""
    #: The OSL section id or the config JSON path.
    reference: str = ""
    #: What the person saw there, for the administrator reading the queue later.
    value: str = ""


class ObservationIn(BaseModel):
    """Something a reviewer knows, in their own words."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["reconciliation", "field_constraint", "correction", "note", "config_note"] = (
        "reconciliation"
    )
    anchors: list[Anchor] = Field(default_factory=list)
    statement: str = Field(min_length=3, max_length=4000)
    expectation: str = ""
    severity_hint: Literal["high", "medium", "low", "review"] = "medium"
    #: The narrowest scope that fits is the default, because the most common cause of
    #: a noisy rule is an assumption that holds for most records and not all.
    scope_hint: Literal["global", "customer", "programme"] = "customer"
    run_id: int | None = None
    finding_id: int | None = None


class ObservationOut(ObservationIn):
    """A stored observation."""

    id: int
    author: str = ""
    status: str = "new"
    status_note: str = ""
    candidate_id: int | None = None
    customer_name: str = ""
    scope_code: str = ""
    version: int = 1
    #: Whether the author may still edit it. False once an administrator queues it,
    #: except for a configuration note, which stays editable so it can be kept true.
    editable: bool = True
    #: For a configuration note: which configuration it follows and whether it still
    #: applies (ADR-024).
    configuration_id: str = ""
    is_active: bool = True
    revisions: list[dict[str, Any]] = Field(default_factory=list)
    #: Active rules that already cover what this points at, each marked when the
    #: statement reads as the opposite of it (Phase 6.1e). Shown to the author while
    #: they can still reconsider; nothing is blocked.
    covered_by: list[dict[str, Any]] = Field(default_factory=list)
    created_at: dt.datetime
    synthesized_at: dt.datetime | None = None


class ObservationDecision(BaseModel):
    """An administrator rejecting an observation, with the reason the author sees."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class SynthesizeIn(BaseModel):
    """Which observations to turn into candidate rules."""

    model_config = ConfigDict(extra="forbid")

    observation_ids: list[int] = Field(min_length=1)


class CandidateOut(BaseModel):
    """A rule the model drafted, waiting for a person."""

    id: int
    name: str = ""
    target_kind: str = "check"
    body: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    severity: str = "medium"
    scope: str = "all"
    status: str = "draft"
    admin_note: str = ""
    source_observation_ids: list[int] = Field(default_factory=list)
    model_used: str = ""
    prompt_version: str = ""
    #: Overlaps with an active rule, found by fingerprint. Two rules quietly saying
    #: nearly the same thing is how a findings list becomes noise.
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    #: What this rule would have changed on the golden set and recent runs.
    replay: dict[str, Any] = Field(default_factory=dict)
    #: What the critique pass said about the first draft (Phase 6.11g).
    critique: dict[str, Any] = Field(default_factory=dict)
    #: The rule after one redraft, when the critique asked for one.
    redraft: dict[str, Any] = Field(default_factory=dict)
    created_by: str = ""
    decided_by: str = ""
    created_at: dt.datetime


class CandidateDecision(BaseModel):
    """Approving or rejecting a candidate."""

    model_config = ConfigDict(extra="forbid")

    note: str = ""
    #: Narrower than the candidate proposed, when the administrator wants it so.
    scope: str | None = None
    #: Approve straight to active rather than into shadow. Rarely the right answer.
    activate_now: bool = False
    #: What to do about an overlap with an existing rule: ``supersede`` disables the
    #: rule it overlaps, ``keep_both`` says they cover different ground. Required when
    #: the candidate has conflicts (Phase 6.11g).
    resolution: Literal["", "supersede", "keep_both"] = ""


class RuleOut(BaseModel):
    """One rule on the rules screen, whatever its origin."""

    id: int
    rule_kind: str
    name: str
    summary: str = ""
    reasoning: str = ""
    severity: str = "medium"
    scope: str = "all"
    state: str = "active"
    origin: str = "admin"
    #: Statistics that say whether the rule is earning its place.
    fired: int = 0
    dismissed: int = 0
    dismissal_rate: float = 0.0
    last_fired_at: dt.datetime | None = None
    source_observation_ids: list[int] = Field(default_factory=list)
    deleted_at: dt.datetime | None = None
    restorable_until: dt.datetime | None = None


class RuleAction(BaseModel):
    """A state change on a rule, which the console asks the administrator to type."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["enable", "disable", "delete", "restore", "activate"]
    #: The word typed to confirm. A rule change reaches every future run.
    confirm: str = ""
    note: str = ""


class RuleStateChangeOut(BaseModel):
    """One move a rule made between states."""

    id: int
    from_state: str = ""
    to_state: str = ""
    note: str = ""
    actor: str = ""
    at: dt.datetime


class TrainingConfigOut(BaseModel):
    """What the user app needs to know about Train AI mode."""

    enabled: bool = False


class ConfigNoteIn(BaseModel):
    """A standing note on an ETL configuration (ADR-024).

    Guidance for every future run of that configuration, and an observation in the
    admin queue at the same time. It never enforces anything on its own.
    """

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=3, max_length=4000)
    severity_hint: Literal["high", "medium", "low", "review"] = "medium"


class RuleRef(BaseModel):
    """One rule on the Rules screen, by kind and id."""

    model_config = ConfigDict(extra="forbid")

    rule_kind: str = Field(min_length=1, max_length=40)
    id: int


class RulesBulkAction(BaseModel):
    """One state change applied to several rules under one typed word (ADR-032)."""

    model_config = ConfigDict(extra="forbid")

    items: list[RuleRef] = Field(min_length=1, max_length=500)
    action: Literal["enable", "disable", "delete", "restore", "activate"]
    confirm: str = ""
    note: str = ""


class RulesBulkResult(BaseModel):
    """What a bulk rule action did."""

    changed: int = 0
    failed: list[str] = Field(default_factory=list)
