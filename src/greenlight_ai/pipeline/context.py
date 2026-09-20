"""The run context and per-stage bookkeeping.

Each stage writes status, duration, and token use, so a failed run resumes from the last
good stage (``docs/design.md`` "Processing pipeline"). The context is the single mutable
object a run threads through its stages; the stage functions themselves are pure in the
sense that matters here: they read the context and return their outputs, and the
orchestrator is the only thing that mutates it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, Mapping, Sequence

from greenlight_ai.checks.definitions import AdminConfig
from greenlight_ai.llm.client import LLMClient
from greenlight_ai.pipeline.guidance import RunGuidance
from greenlight_ai.parsers.base import ConfigDocument, OslDocument, ReportDocument, ReportKind
from greenlight_ai.rules.normalize import AliasTable
from greenlight_ai.rules.schema import ConfigElement, Finding, Rule, Trace

if TYPE_CHECKING:  # pragma: no cover - the import exists for the annotation only
    from greenlight_ai.pipeline.coverage import Coverage

__all__ = [
    "CoverageRecord",
    "StageName",
    "StageStatus",
    "StageRecord",
    "RunContext",
    "STAGE_ORDER",
    "RECHECK_STAGES",
]

_LOG: Final = logging.getLogger(__name__)

StageName = Literal[
    "s1_parse",
    "s2_extract",
    "s3_describe",
    "s4_trace",
    "s5_compare",
    "s6_reverse",
    "s7_reports",
    "s8_verify",
    "s9_summarize",
]

StageStatus = Literal["pending", "running", "done", "failed", "skipped"]

#: The nine stages in order.
STAGE_ORDER: Final[tuple[StageName, ...]] = (
    "s1_parse",
    "s2_extract",
    "s3_describe",
    "s4_trace",
    "s5_compare",
    "s6_reverse",
    "s7_reports",
    "s8_verify",
    "s9_summarize",
)

#: Editing a requirement or a trace link reruns only these, and none of them calls a
#: model (``docs/design.md`` "Re-check path").
RECHECK_STAGES: Final[tuple[StageName, ...]] = ("s5_compare", "s6_reverse", "s7_reports")


@dataclass(frozen=True, slots=True)
class ReportPart:
    """One uploaded file of a report kind (ADR-021).

    A campaign can deliver the same report type several times: one field distribution
    per segment, per state, or per deliverable. The label is what the submitter called
    it, and it is what a finding names so "the field distribution is wrong" is not the
    only thing a reviewer is told.

    Attributes:
        label: What the submitter called this file. Empty when they gave no label,
            in which case a finding falls back to the ordinal.
        ordinal: Its position within its kind, starting at one.
        path: Where the file is on the shared volume.
        document: The parsed workbook, set by stage 1.
    """

    label: str
    ordinal: int
    path: Path
    document: ReportDocument | None = None

    @property
    def name(self) -> str:
        """How to refer to this part in a finding.

        Returns:
            The label when there is one, otherwise "part N".
        """
        return self.label or f"part {self.ordinal}"


@dataclass
class StageRecord:
    """Status and timing for one stage (the ``run_stages`` table).

    Attributes:
        stage: Which stage.
        status: Where it got to.
        duration_ms: Wall-clock duration.
        error: The failure, as a short message with no file content.
        llm_calls: How many model calls the stage made.
        cache_hits: How many of those the cache served.
        tokens: Tokens the stage consumed.
    """

    stage: StageName
    status: StageStatus = "pending"
    duration_ms: int = 0
    error: str = ""
    llm_calls: int = 0
    cache_hits: int = 0
    tokens: int = 0


@dataclass
class CoverageRecord:
    """What stage 7 evaluated, tallied as it works (Phase 6.11c).

    It lives here rather than in :mod:`greenlight_ai.pipeline.coverage` because the
    context carries it and coverage reads it; the other way round would be a cycle.

    Attributes:
        checked_rule_ids: Requirements a report check gave a verdict on.
        unevaluated_rule_ids: Requirements whose report check could not be evaluated.
        checks_by_report: How many checks produced a verdict against each report kind.
    """

    checked_rule_ids: set[str] = field(default_factory=set)
    unevaluated_rule_ids: set[str] = field(default_factory=set)
    checks_by_report: dict[str, int] = field(default_factory=dict)

    def clear(self) -> None:
        """Forget everything, so a re-check starts from nothing."""
        self.checked_rule_ids.clear()
        self.unevaluated_rule_ids.clear()
        self.checks_by_report.clear()

    def checked(self, rule_id: str, report_kind: str = "") -> None:
        """Record a check that produced a verdict.

        Args:
            rule_id: The requirement behind it, empty for a check with none (an admin
                expression check, a field constraint).
            report_kind: The report it read, empty when it read none.
        """
        if rule_id:
            self.checked_rule_ids.add(rule_id)
        if report_kind:
            self.checks_by_report[report_kind] = self.checks_by_report.get(report_kind, 0) + 1

    def unevaluated(self, rule_id: str) -> None:
        """Record a check that could not be evaluated.

        Args:
            rule_id: The requirement behind it.
        """
        if rule_id:
            self.unevaluated_rule_ids.add(rule_id)


@dataclass
class RunContext:
    """Everything one run accumulates as it moves through the stages.

    Attributes:
        run_id: Identifier for the run.
        osl_path: The requirement spec.
        config_path: The ETL config.
        report_paths: Report kind to its first file, kept because most checks want
            exactly one workbook.
        report_parts: Report kind to every uploaded file of that kind, each with its
            label. One entry per kind is the ordinary case.
        client: The LLM adapter. The only route to a model (ADR-004).
        customer: The customer this run is for, used to scope admin checks and
            compliance rules.
        admin: What the admin-ui contributes: cross-report checks, compliance rules,
            reverse-pass categories, and named values. Phase 3 loads it from the
            database; until then the shipped defaults apply.
        guidance: What an administrator configured about this run's context: the
            delivery programme, its standing instructions, and per-artifact guidance
            (ADR-020). Empty by default, in which case prompts are unchanged.
        aliases: The attribute alias table, from the admin-ui in later phases.
        masked_columns: Header patterns masked at parse time (ADR-003).
        osl: The parsed OSL, set by stage 1.
        config: The parsed config, set by stage 1.
        reports: The parsed reports, set by stage 1.
        rules: Canonical requirements from the OSL, set by stage 2.
        elements: Config elements in requirement vocabulary, set by stage 3.
        traces: Requirement-to-element links, set by stage 4.
        findings: Everything found so far, appended by stages 5 to 8.
        summary: The plain-English summary, set by stage 9.
        top_issues: The headline issues, set by stage 9.
        stages: Per-stage records.
        rules_version: Increments when a user edits a rule; recorded on findings.
    """

    run_id: str
    osl_path: Path
    config_path: Path
    report_paths: Mapping[ReportKind, Path]
    client: LLMClient
    customer: str = ""
    admin: AdminConfig = field(default_factory=AdminConfig)
    guidance: RunGuidance = field(default_factory=RunGuidance)
    aliases: AliasTable = field(default_factory=lambda: AliasTable.from_mapping({}))
    masked_columns: tuple[str, ...] = ()

    osl: OslDocument | None = None
    config: ConfigDocument | None = None
    reports: dict[ReportKind, ReportDocument] = field(default_factory=dict)
    #: Every uploaded file per report kind, in upload order, with the label the
    #: submitter gave it. A campaign can deliver the same report type several times,
    #: one per segment or per deliverable (ADR-021). ``reports`` stays the first part
    #: of each kind, so a check that does not care about parts is unchanged.
    report_parts: dict[ReportKind, list[ReportPart]] = field(default_factory=dict)

    rules: list[Rule] = field(default_factory=list)
    elements: list[ConfigElement] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""
    top_issues: tuple[str, ...] = ()

    stages: dict[StageName, StageRecord] = field(default_factory=dict)
    rules_version: int = 1

    #: What stage 7 evaluated, which :mod:`greenlight_ai.pipeline.coverage` turns into
    #: the run's coverage. Stage 7 clears it before it starts, so a re-check counts
    #: this pass and not the last one.
    coverage_record: CoverageRecord = field(default_factory=lambda: CoverageRecord())
    #: What the run checked and what it did not, computed by stage 7 from the record
    #: above (Phase 6.11c). ``None`` before stage 7 has run.
    coverage: "Coverage | None" = None
    #: Run-level things a reviewer must be told that are not findings: a verification
    #: that could not run, a stage that stopped early. Appended by the stages,
    #: surfaced beside the coverage panel and recorded in the attestation (6.11c).
    notices: list[str] = field(default_factory=list)

    def record(self, stage: StageName) -> StageRecord:
        """Get or create the record for a stage.

        Args:
            stage: The stage name.

        Returns:
            The record, created as pending when absent.
        """
        if stage not in self.stages:
            self.stages[stage] = StageRecord(stage=stage)
        return self.stages[stage]

    def rule(self, rule_id: str) -> Rule | None:
        """Look up a requirement by id.

        Args:
            rule_id: The requirement id.

        Returns:
            The rule, or ``None``.
        """
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def element(self, element_id: str) -> ConfigElement | None:
        """Look up a config element by id.

        Args:
            element_id: The element id.

        Returns:
            The element, or ``None``.
        """
        for element in self.elements:
            if element.element_id == element_id:
                return element
        return None

    def trace_for(self, rule_id: str) -> Trace | None:
        """Find the trace for a requirement.

        Args:
            rule_id: The requirement id.

        Returns:
            The trace, or ``None`` when stage 4 has not run.
        """
        for trace in self.traces:
            if trace.rule_id == rule_id:
                return trace
        return None

    def next_finding_id(self) -> str:
        """Allocate the next finding id.

        Returns:
            An id of the form ``"F-01"``, numbered from the findings already present so
            a re-check that rebuilds stages 5 to 7 does not reuse an id.
        """
        return f"F-{len(self.findings) + 1:02d}"

    def add_finding(self, finding: Finding) -> Finding:
        """Append a finding, stamping it with the current rules version.

        Args:
            finding: The finding to add.

        Returns:
            The stored finding.
        """
        stamped = finding.model_copy(update={"rules_version": self.rules_version})
        self.findings.append(stamped)
        return stamped

    def resume_from(self) -> StageName:
        """Decide where a retried run should restart.

        Returns:
            The first stage that is not ``done``; the last stage when everything is
            done, so a completed run does not silently restart from the beginning.
        """
        for stage in STAGE_ORDER:
            if self.stages.get(stage, StageRecord(stage=stage)).status != "done":
                return stage
        return STAGE_ORDER[-1]

    @property
    def high_severity_findings(self) -> Sequence[Finding]:
        """Findings that must be decided before the report can be generated.

        Returns:
            Every high-severity finding (ADR-015).
        """
        return [f for f in self.findings if f.severity == "high"]

    @property
    def can_finalize(self) -> bool:
        """Whether the finalize gate is satisfied.

        Returns:
            ``True`` when every high-severity finding has a review decision (ADR-015).
        """
        return not any(f.needs_decision for f in self.findings)
