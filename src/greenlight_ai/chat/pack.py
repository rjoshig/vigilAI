"""The context pack: everything the chat may see about one frozen run (Phase 8b).

The pack is the feature. Everything else is plumbing around it.

**It is built on the server from a run id and nothing else, on every turn.** The client
sends a question and a transcript; neither can add a fact, because facts come only from
here. That single sentence is what makes 8d's isolation true rather than asserted.

**Seven sections, none of them a new category of data leaving the building.** Every one
is either already in a prompt during a run or is derived counts and titles. The
tripwire (`llm/tripwire.py`) still scans the assembled prompt and still fails closed
(ADR-018), so this module's job is to be *obviously* within the rule rather than to rely
on being caught:

1. The global rules in force — titles, texts and strictness, never a value.
2. The previous finalized run of this configuration id.
3. The findings of the last three finalized runs — type, severity, title, the decision
   a person made, and which engine produced it.
4. This run's findings with their evidence, which is masked at parse time. **Shadow
   findings are excluded**, exactly as the frozen report excludes them: a rule nobody
   has activated must not start answering questions either.
5. The artifacts, as an **inventory** — kind, part label, filename, size and checksum.
   What arrived, not what is in it.
6. This run's own guidance — the configuration notes snapshot (ADR-024), the delivery
   notes, the programme and its rules — all of which already reached the model during
   the run.
7. The verdict and the gaps — coverage, notices, and the attestation the reviewer
   confirmed at freeze, read from the stored row rather than recomputed.

The frozen report's own rendered text is in the pack too. It is the document the person
is already looking at, so quoting it back adds no exposure, and it is what makes *"what
does this report actually say about X"* answerable at all.

**Capped as a whole, and it says what it trimmed.** A pack that silently dropped the
findings section would produce an answer that is wrong for a reason nobody can see, so
`trimmed` is carried on the pack, stated in the prompt, and shown in the panel.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai import scopes, textfit
from greenlight_ai.chat.settings import ChatSettings
from greenlight_ai.db import models

__all__ = [
    "MAX_PACK_CHARS",
    "MAX_REPORT_CHARS",
    "PREVIOUS_RUNS",
    "Citable",
    "RunPack",
    "build_pack",
    "greeting",
    "starters",
]

_LOG: Final = logging.getLogger(__name__)

#: The ceiling on the whole pack. Generous next to a run preamble's 6,000, because this
#: is one call rather than one per stage and the person is asking about a document they
#: already have open — but a ceiling, because an answer assembled from forty thousand
#: characters of context is not more accurate, only slower and dearer.
MAX_PACK_CHARS: Final[int] = 24_000

#: The share of that the frozen report's own text may take. It is the largest single
#: section and the least surprising one to trim, since the person is looking at it.
MAX_REPORT_CHARS: Final[int] = 8_000

#: How many earlier finalized runs of this configuration the history covers. The user
#: asked for three, and three is also where "what usually happens" starts to mean
#: something without the section dominating the pack.
PREVIOUS_RUNS: Final[int] = 3

#: Strips tags, script and style from the frozen report so its prose can be quoted.
#: The report is a stored self-contained HTML file; nothing about it is regenerated
#: (ADR-005) and this never writes to it.
_TAG_RE: Final = re.compile(r"<[^>]+>")
_DROP_RE: Final = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Citable:
    """One thing an answer may cite, and what it points at.

    A citation is only shown when it resolves to one of these (Phase 8c), so this is
    the whole vocabulary of what the chat is allowed to claim it read.

    Attributes:
        cite_id: What the model must write to cite it, e.g. ``F-003`` or ``R-012``.
        kind: ``finding``, ``requirement``, ``rule``, ``artifact`` or ``report``.
        label: One line a person can read on the chip.
        anchor: Where the panel links to, relative to the run.
    """

    cite_id: str
    kind: str
    label: str
    anchor: str = ""


@dataclass(frozen=True, slots=True)
class RunPack:
    """Everything the chat may see about one run, and its fingerprint.

    Attributes:
        run_id: The run this is about. The chat can see no other.
        customer: For the greeting, which code writes rather than the model.
        configuration_id: Likewise.
        verdict: The frozen report's own verdict, ``ok`` or ``not_ok``.
        finding_count: How many findings the run has, shadow excluded.
        sections: The rendered pack, section name to text, in prompt order.
        citable: Everything an answer is allowed to cite, by id.
        trimmed: What was dropped to fit, as sentences. Empty when nothing was.
        sha256: The fingerprint of the rendered sections. Part of the cache key, so a
            hit requires the same run *and* the same data the asker was entitled to.
        aggregates_included: Whether 8g's switch was on when this was built, so the
            panel and the prompt can both say so.
    """

    run_id: int
    customer: str = ""
    configuration_id: str = ""
    verdict: str = ""
    finding_count: int = 0
    sections: dict[str, str] = field(default_factory=dict)
    citable: dict[str, Citable] = field(default_factory=dict)
    trimmed: tuple[str, ...] = ()
    sha256: str = ""
    aggregates_included: bool = False

    def rendered(self) -> str:
        """The pack as the prompt carries it.

        Returns:
            Every non-empty section under its heading, in order, with what was trimmed
            stated at the end rather than left silent.
        """
        parts = [f"## {name}\n{body}" for name, body in self.sections.items() if body.strip()]
        if self.trimmed:
            parts.append("## What was left out of this context\n" + "\n".join(self.trimmed))
        return "\n\n".join(parts)

    def resolve(self, cite_id: str) -> Citable | None:
        """Look up a citation the model wrote.

        Args:
            cite_id: The id as the model wrote it. Case and surrounding punctuation are
                forgiven; a wrong id is not.

        Returns:
            The citable, or ``None`` when nothing in the pack has that id — which is
            what stops a fabricated id ever being shown as a citation.
        """
        return self.citable.get(cite_id.strip().strip(".,;:()[]").upper())


# --- the sections -------------------------------------------------------------------


def _is_global(raw: str) -> bool:
    """Whether a stored scope is the ``everywhere`` one.

    Asked rather than `scopes.covers(...)` because the question here is about the rule,
    not about a run: *is this one of the rules that apply to everything*. A rule scoped
    to this run's programme is already in the programme section, and listing it twice
    would let an answer cite it as global when it is not.

    Args:
        raw: Any stored scope form (ADR-037 and its legacy spellings).

    Returns:
        ``True`` for the everywhere scope.
    """
    return scopes.parse(raw).kind == scopes.EVERYWHERE


def _global_rules(session: Session) -> tuple[list[str], list[Citable]]:
    """The active rules scoped everywhere, across all four rule surfaces.

    Args:
        session: An open session.

    Returns:
        The lines and what they may be cited as. Titles, texts and strictness only —
        never a value a rule compares against, because a value is the thing a model
        must not be handed and then asked about.
    """
    lines: list[str] = []
    citable: list[Citable] = []

    checks = session.execute(
        sa.select(models.CheckDefinitionRow).where(
            models.CheckDefinitionRow.state == "active",
            models.CheckDefinitionRow.deleted_at.is_(None),
        )
    ).scalars()
    for row in checks:
        if not _is_global(row.scope):
            continue
        cite = f"C-{row.id:03d}"
        lines.append(f"[{cite}] Check '{row.name}' ({row.kind}, {row.severity}): {row.reasoning}")
        citable.append(Citable(cite, "rule", f"Check: {row.name}", "/checks"))

    compliance = session.execute(
        sa.select(models.ComplianceRuleRow).where(
            models.ComplianceRuleRow.state == "active",
            models.ComplianceRuleRow.deleted_at.is_(None),
        )
    ).scalars()
    for compliance_row in compliance:
        if not _is_global(compliance_row.scope):
            continue
        cite = f"K-{compliance_row.id:03d}"
        lines.append(
            f"[{cite}] Compliance rule '{compliance_row.name}': {compliance_row.reasoning}"
        )
        citable.append(Citable(cite, "rule", f"Compliance: {compliance_row.name}", "/compliance"))

    constraints = session.execute(
        sa.select(models.FieldConstraint).where(
            models.FieldConstraint.state == "active",
            models.FieldConstraint.deleted_at.is_(None),
        )
    ).scalars()
    for constraint_row in constraints:
        if not _is_global(constraint_row.scope):
            continue
        cite = f"N-{constraint_row.id:03d}"
        lines.append(
            f"[{cite}] Field rule on {constraint_row.field}: {constraint_row.constraint} "
            f"({constraint_row.severity}). {constraint_row.reasoning}"
        )
        citable.append(Citable(cite, "rule", f"Field rule: {constraint_row.field}", "/rules"))

    return lines, citable


def _programme_rules(session: Session, scope_code: str) -> tuple[list[str], list[Citable]]:
    """The rules of the programme this run was submitted as.

    Args:
        session: An open session.
        scope_code: The run's programme code. Empty returns nothing.

    Returns:
        The lines and their citables, with the strictness the model must not grade —
        code does that (ADR-001).
    """
    if not scope_code.strip():
        return [], []
    rows = session.execute(
        sa.select(models.ProgrammeRule)
        .where(
            models.ProgrammeRule.scope_code == scope_code,
            models.ProgrammeRule.state == "active",
            models.ProgrammeRule.deleted_at.is_(None),
        )
        .order_by(models.ProgrammeRule.sort_order, models.ProgrammeRule.id)
    ).scalars()
    lines: list[str] = []
    citable: list[Citable] = []
    for row in rows:
        cite = f"P-{row.id:03d}"
        lines.append(f"[{cite}] {row.strictness.upper()}: {row.title} — {row.text}")
        citable.append(Citable(cite, "rule", f"Programme rule: {row.title}", "/scopes"))
    return lines, citable


def _findings(session: Session, run_id: int) -> tuple[list[str], list[Citable], int]:
    """This run's findings, shadow excluded, with the evidence the report shows.

    Args:
        session: An open session.
        run_id: The run.

    Returns:
        The lines, their citables, and the count — which the greeting quotes, so the
        number a person is told is the number the model was given.
    """
    rows = list(
        session.execute(
            sa.select(models.Finding)
            .where(models.Finding.run_id == run_id, models.Finding.shadow.is_(False))
            .order_by(models.Finding.id)
        ).scalars()
    )
    lines: list[str] = []
    citable: list[Citable] = []
    for row in rows:
        evidence = row.evidence if isinstance(row.evidence, dict) else {}
        where = " ".join(
            str(evidence.get(key, "")).strip()
            for key in ("osl_ref", "config_path", "report_name", "report_sheet", "report_cell")
            if str(evidence.get(key, "")).strip()
        )
        decision = row.review_status if row.review_status != "undecided" else "undecided"
        lines.append(
            f"[{row.finding_id}] {row.severity} · {row.type} · decided {decision} · "
            f"found by {row.engine}: {row.title}. {textfit.clip(row.detail, 400, 'finding')}"
            + (f" Evidence: {where}." if where else "")
        )
        citable.append(
            Citable(row.finding_id, "finding", f"{row.severity}: {row.title}", "#findings")
        )
    return lines, citable, len(rows)


def _history(session: Session, run: models.Run) -> list[str]:
    """What the last three finalized runs of this configuration found.

    Args:
        session: An open session.
        run: The current run.

    Returns:
        One line per earlier run with its verdict, then its findings by type and
        severity with the decisions people made. Earlier runs are **not** citable:
        the chat may say what happened before, and a chip linking into a run the
        person may not be looking at would invite them to treat it as this one's.
    """
    if not run.configuration_id.strip():
        return []
    earlier = list(
        session.execute(
            sa.select(models.Run)
            .where(
                models.Run.id != run.id,
                models.Run.configuration_id == run.configuration_id,
                models.Run.customer_name == run.customer_name,
                models.Run.status == "finalized",
                models.Run.created_at < run.created_at,
            )
            .order_by(models.Run.created_at.desc())
            .limit(PREVIOUS_RUNS)
        ).scalars()
    )
    lines: list[str] = []
    for index, previous in enumerate(earlier):
        when = previous.created_at.date().isoformat() if previous.created_at else "unknown date"
        marker = "the previous run" if index == 0 else f"{index + 1} runs ago"
        report = session.execute(
            sa.select(models.FinalReport.verdict).where(models.FinalReport.run_id == previous.id)
        ).scalar_one_or_none()
        lines.append(f"VR-{previous.id:04d} ({marker}, {when}), verdict {report or 'unknown'}:")
        findings = session.execute(
            sa.select(models.Finding)
            .where(models.Finding.run_id == previous.id, models.Finding.shadow.is_(False))
            .order_by(models.Finding.id)
        ).scalars()
        for row in findings:
            lines.append(
                f"  · {row.severity} {row.type} — {row.title} "
                f"(decided {row.review_status}, found by {row.engine})"
            )
    return lines


def _inventory(run: models.Run) -> tuple[list[str], list[Citable]]:
    """What arrived, not what is in it.

    Args:
        run: The run.

    Returns:
        One line per uploaded artifact with its kind, part label, filename and size.
        No sheet is opened and no cell is read: by the time anybody chats about a run
        the workbooks are parsed and gone, and this is the record of what they were.
    """
    lines: list[str] = []
    citable: list[Citable] = []
    for stored in sorted(run.files, key=lambda f: (f.kind, f.part)):
        cite = f"A-{stored.id:03d}"
        part = f" part {stored.part}" if stored.part > 1 else ""
        label = f" ({stored.part_label})" if stored.part_label else ""
        size = f"{stored.size_bytes:,} bytes" if stored.size_bytes else "size unrecorded"
        lines.append(f"[{cite}] {stored.kind}{part}{label}: {stored.filename}, {size}")
        citable.append(Citable(cite, "artifact", f"{stored.kind}: {stored.filename}"))
    return lines, citable


def _guidance(session: Session, run: models.Run) -> list[str]:
    """What this run was told, which the model already read during the run.

    Args:
        session: An open session.
        run: The run.

    Returns:
        The programme, the configuration notes snapshot (ADR-024) and the delivery
        notes. Nothing here is new exposure: every line reached a prompt while the run
        was validated.
    """
    lines: list[str] = []
    if run.scope:
        lines.append(f"Delivery programme: {scopes.label(run.scope) or run.scope}.")
    if run.credit_date:
        lines.append(f"Credit date: {run.credit_date.isoformat()}.")
    lines.append(
        "Suppressions were applied to this delivery."
        if run.has_suppressions
        else "The submitter said no suppressions were applied to this delivery."
    )
    for note in run.config_notes_snapshot or []:
        lines.append(f"Standing note on this configuration: {textfit.clip(str(note), 600)}")
    if run.notes:
        lines.append(f"The submitter wrote: {textfit.clip(run.notes, 600)}")
    if run.rerun_reason:
        lines.append(f"Re-run reason given: {textfit.clip(run.rerun_reason, 300)}")
    return lines


def _coverage(session: Session, run: models.Run) -> tuple[list[str], list[Citable]]:
    """What was checked, what was not, and what the reviewer attested to.

    Args:
        session: An open session.
        run: The run.

    Returns:
        The lines and the requirement citables. "Nobody checked this" is the question
        the report page answers worst and the one reviewers most often ask, so the
        gaps are in the pack as first-class lines rather than as a count.
    """
    lines: list[str] = []
    citable: list[Citable] = []
    for entry in run.coverage or []:
        if not isinstance(entry, dict):
            continue
        rule_id = str(entry.get("rule_id", ""))
        state = str(entry.get("state", ""))
        if not rule_id:
            continue
        cite = rule_id.upper()
        lines.append(
            f"[{cite}] {state}: {entry.get('summary', '')}"
            + (f" ({entry.get('reason')})" if entry.get("reason") else "")
        )
        citable.append(Citable(cite, "requirement", f"{state}: {entry.get('summary', '')}"))
    for entry in run.report_coverage or []:
        if isinstance(entry, dict):
            lines.append(
                f"Report {entry.get('kind', '')}: {entry.get('checks_applied', 0)} check(s) ran."
            )
    for notice in run.notices or []:
        lines.append(f"Notice: {notice}")

    stored = session.execute(
        sa.select(models.FinalReport).where(models.FinalReport.run_id == run.id)
    ).scalar_one_or_none()
    if stored is not None:
        lines.append(f"Frozen by {stored.generated_by or 'unknown'}, verdict {stored.verdict}.")
        attestation = stored.attestation if isinstance(stored.attestation, dict) else {}
        if attestation:
            lines.append(
                "The reviewer confirmed at freeze: "
                + textfit.clip(json.dumps(attestation, sort_keys=True), 1200, "attestation")
            )
    return lines, citable


def _aggregates(run: models.Run) -> list[str]:
    """Per-column figures code computed, when 8g's switch is on.

    Nothing new is measured here. `run.attribute_profile` has held exactly these
    numbers since Phase 6.21c, computed by code at stage 7 and used as the baseline a
    later delivery is compared against. `llm-privacy.md` already lists aggregates as
    allowed in a prompt; a row and a non-aggregate cell are not, and neither is here.

    Args:
        run: The run.

    Returns:
        One line per attribute, or nothing when the run has no profile.
    """
    profile = run.attribute_profile if isinstance(run.attribute_profile, dict) else {}
    lines: list[str] = []
    for name, measures in sorted(profile.items()):
        if not isinstance(measures, dict):
            continue
        stated = ", ".join(
            f"{key} {value}" for key, value in sorted(measures.items()) if value is not None
        )
        if stated:
            lines.append(f"{name}: {stated}")
    return lines


def _report_text(data_dir: Path | None, stored: models.FinalReport | None) -> str:
    """The frozen report's own prose, so it can be quoted back.

    The file is **read, never written**. It is the artifact somebody attested to and
    ADR-005 says it is never regenerated; the chat is a sibling overlay on the page and
    changes nothing about the document.

    Args:
        data_dir: The shared volume, or ``None`` when the caller has no path — in which
            case the section is simply absent and the chat says so when asked.
        stored: The frozen report row.

    Returns:
        The visible text, tags stripped and whitespace collapsed, within
        :data:`MAX_REPORT_CHARS`.
    """
    if stored is None or data_dir is None or not stored.html_path:
        return ""
    path = Path(stored.html_path)
    if not path.is_absolute():
        path = data_dir / path
    try:
        html = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - a report whose file is gone
        _LOG.info("chat: the frozen report for run %s could not be read (%s)", stored.run_id, exc)
        return ""
    visible = _TAG_RE.sub(" ", _DROP_RE.sub(" ", html))
    return textfit.clip(visible, MAX_REPORT_CHARS, "the frozen report")


# --- assembly -----------------------------------------------------------------------


def build_pack(
    session: Session,
    run_id: int,
    settings: ChatSettings | None = None,
    data_dir: Path | None = None,
) -> RunPack:
    """Assemble everything the chat may see about one run.

    Rebuilt on every turn from the run id alone. Nothing about it comes from the
    client, which is why a forged transcript or a forged context field cannot change
    what the model is shown (Phase 8d).

    Args:
        session: An open session.
        run_id: The run to build for.
        settings: The chat settings, which decide only whether 8g's aggregates are
            included. Omitted, they are not.
        data_dir: The shared volume, so the frozen report's own text can be quoted.

    Returns:
        The pack, capped as a whole and carrying its own fingerprint.

    Raises:
        ValueError: When the run does not exist. The caller has already checked, so
            this is a programming error rather than a 404.
    """
    run = session.get(models.Run, run_id)
    if run is None:
        raise ValueError(f"run {run_id} does not exist")

    chat = settings or ChatSettings()
    stored = session.execute(
        sa.select(models.FinalReport).where(models.FinalReport.run_id == run.id)
    ).scalar_one_or_none()

    rules, rule_cites = _global_rules(session)
    programme, programme_cites = _programme_rules(session, run.scope)
    findings, finding_cites, count = _findings(session, run.id)
    artifacts, artifact_cites = _inventory(run)
    coverage, coverage_cites = _coverage(session, run)

    citable = {c.cite_id: c for c in (*rule_cites, *programme_cites, *artifact_cites)}
    citable.update({c.cite_id: c for c in coverage_cites})
    # Findings last so a finding id always wins a collision with a requirement id:
    # a finding is what somebody is asking about.
    citable.update({c.cite_id: c for c in finding_cites})
    if stored is not None:
        citable["REPORT"] = Citable("REPORT", "report", "The frozen report", "")

    sections: dict[str, str] = {}
    trimmed: list[str] = []

    def add(name: str, lines: Sequence[str], what: str, cap: int) -> None:
        """Render one section within its share and note what it lost."""
        if not lines:
            return
        block = textfit.fit(lines, what, cap)
        sections[name] = str(block)
        if block.dropped:
            trimmed.append(
                f"- {block.dropped} of {block.total} {what}(s) were omitted from "
                f"'{name}' to keep this context short."
            )

    # Order matters: what is most often asked about goes first, so that if a later
    # section is trimmed the answer is still built on the material the question is
    # usually about.
    share = MAX_PACK_CHARS // 6
    add("This run's findings", findings, "finding", share)
    add("What was checked, what was not, and what was attested", coverage, "line", share)
    add("The global rules in force", rules, "rule", share)
    add("The rules of this delivery programme", programme, "programme rule", share // 2)
    add("What this run was told", _guidance(session, run), "note", share // 2)
    add(
        f"The last {PREVIOUS_RUNS} finalized runs of this configuration",
        _history(session, run),
        "line",
        share,
    )
    add("The artifacts that arrived", artifacts, "artifact", share // 2)
    if chat.report_aggregates:
        add(
            "Per-column figures code computed for this delivery",
            _aggregates(run),
            "attribute",
            share,
        )

    report_text = _report_text(data_dir, stored)
    if report_text:
        sections["What the frozen report itself says"] = report_text

    rendered = "\n\n".join(f"## {name}\n{body}" for name, body in sections.items())
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    return RunPack(
        run_id=run.id,
        customer=run.customer_name,
        configuration_id=run.configuration_id,
        verdict=stored.verdict if stored is not None else "",
        finding_count=count,
        sections=sections,
        citable=citable,
        trimmed=tuple(trimmed),
        sha256=digest,
        aggregates_included=chat.report_aggregates,
    )


# --- what the panel says before it is asked anything --------------------------------


def greeting(pack: RunPack) -> str:
    """What the panel says on opening, written by code from the pack.

    It costs no tokens, it cannot hallucinate, and it is the same every time. A
    greeting produced by the model would be the first thing a person read and the one
    sentence nothing had checked.

    Args:
        pack: The pack the answers will be built from.

    Returns:
        Two short paragraphs naming the run, the configuration and the finding count.
    """
    findings = (
        "no findings"
        if pack.finding_count == 0
        else f"its {pack.finding_count} finding{'s' if pack.finding_count != 1 else ''} "
        "and the decisions made on them"
    )
    return (
        f"I can see this frozen report — run VR-{pack.run_id:04d}, configuration "
        f"{pack.configuration_id or 'unstated'}, {findings}, the global rules in force, "
        f"and what changed against the last {PREVIOUS_RUNS} runs of this configuration.\n\n"
        "What would you like to know about this report, this run, or this configuration?"
    )


def starters(pack: RunPack) -> list[str]:
    """Four questions built by code from what this pack actually contains.

    A blank box beneath a two-line greeting is the most reliable way a chat feature
    goes unused: people cannot tell what it knows, so they do not ask. These cost no
    model call, and a question is never offered when there is nothing to answer with —
    which is also how the panel tells somebody what it has, without claiming it.

    Args:
        pack: The pack.

    Returns:
        Up to four questions, most specific first.
    """
    out: list[str] = []
    worst = next(
        (
            cite
            for cite, item in pack.citable.items()
            if item.kind == "finding" and item.label.startswith("high")
        ),
        "",
    )
    if worst:
        out.append(f"Why is finding {worst} high?")
    if pack.sections.get(f"The last {PREVIOUS_RUNS} finalized runs of this configuration"):
        out.append("What changed since the last run of this configuration?")
    if any(item.kind == "requirement" for item in pack.citable.values()):
        out.append("What did nobody check?")
    if pack.sections.get("The global rules in force"):
        out.append("Which global rules applied here?")
    if pack.sections.get("What the frozen report itself says") and len(out) < 4:
        out.append("Summarise what this report concluded.")
    return out[:4]


def context_facts(pack: RunPack) -> dict[str, Any]:
    """The pack's shape, for the panel's "what I can and cannot see" line.

    Args:
        pack: The pack.

    Returns:
        Counts and flags only — never the content, which the panel has no business
        rendering and which belongs in the prompt or nowhere.
    """
    return {
        "sections": list(pack.sections),
        "citable": len(pack.citable),
        "trimmed": list(pack.trimmed),
        "aggregates_included": pack.aggregates_included,
    }
