"""Working out which artifact type a workbook is, from its shape alone.

A user should not have to know that the file they have is a "field distribution". This
module fingerprints an uploaded workbook — normalized sheet names and header-row tokens
— and scores that fingerprint against the stored samples of every active report type.
The scoring is ordinary set arithmetic, not a model: ADR-001 keeps every comparison in
code, and a similarity a person can recompute by hand is one they can argue with.

Detection never assigns silently. The result carries a verdict of ``confident``,
``ambiguous``, or ``unknown``, so the caller can pre-select a type the user may correct
rather than pretend to know.

The phase doc allows a model to break a tie on sheet and column *names* only. That is
deliberately not implemented here: the tiebreak would attach in :func:`detect`, after
the candidates are sorted and the verdict comes out ``ambiguous``, and it would choose
between the shortlist code already produced. What ships is the deterministic pass.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable, Sequence

from sqlalchemy.orm import Session

from vigilai.db import catalog, models
from vigilai.parsers.base import ParseError, ReportSheet
from vigilai.parsers.reports.xlsx import GenericReportParser

__all__ = [
    "Fingerprint",
    "Candidate",
    "DetectionResult",
    "CONFIDENT_SCORE",
    "CONFIDENT_MARGIN",
    "SCORE_FLOOR",
    "fingerprint_workbook",
    "fingerprint_sheet",
    "fingerprint_samples",
    "score",
    "detect",
    "detect_sheets",
]

_LOG: Final = logging.getLogger(__name__)

#: A best score at or above this is strong enough to pre-select a type. Two workbooks
#: of the same report type share their sheet names and most of their header row, so
#: matching layouts land well above this; a little over half the tokens in common is
#: more than any unrelated pair of the shipped types reaches.
CONFIDENT_SCORE: Final[float] = 0.55

#: The best score must beat the runner-up by at least this much. Without a margin a
#: 0.60/0.59 pair would be reported as certain, and the two types it is choosing
#: between are exactly the case where asking the user is cheap and guessing is not.
CONFIDENT_MARGIN: Final[float] = 0.15

#: Below this nothing is offered at all. A handful of generic tokens ("summary",
#: "value", "count") coincide between unrelated workbooks, and a candidate built only
#: out of those is noise rather than a weak signal.
SCORE_FLOOR: Final[float] = 0.20

#: Anything that is not a letter or a digit separates tokens, so "Field Distribution ",
#: "field_distribution", and "FIELD-DISTRIBUTION" normalize to the same string.
_SEPARATORS: Final = re.compile(r"[^0-9a-z]+")


def _normalize(text: str) -> str:
    """Reduce a label to its comparable form.

    Args:
        text: A sheet name or a header cell, as the workbook spells it.

    Returns:
        Lowercased, punctuation replaced by single spaces, ends trimmed. Empty when
        the label carried no letters or digits.
    """
    return _SEPARATORS.sub(" ", text.casefold()).strip()


def _normalized_set(labels: Iterable[str]) -> frozenset[str]:
    """Normalize a group of labels, dropping the ones that reduce to nothing.

    Args:
        labels: Raw sheet names or header cells.

    Returns:
        The distinct normalized labels.
    """
    return frozenset(filter(None, (_normalize(label) for label in labels)))


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """What a workbook looks like, stripped of its values.

    Values are deliberately absent: a fingerprint is compared, logged, and held in
    memory, and customer data belongs in none of those (ADR-003).

    Attributes:
        sheets: Normalized sheet names.
        headers: Normalized header-row tokens, pooled across every sheet.
    """

    sheets: frozenset[str] = frozenset()
    headers: frozenset[str] = frozenset()

    @property
    def tokens(self) -> frozenset[str]:
        """The comparable token set.

        Sheet names and header tokens are kept apart by a prefix, because a sheet
        called "State" and a column called "State" are different evidence and
        merging them would inflate the score of a type that only has one of them.

        Returns:
            Every token, namespaced by where it came from.
        """
        return frozenset(f"sheet:{name}" for name in self.sheets) | frozenset(
            f"header:{token}" for token in self.headers
        )

    def merge(self, other: "Fingerprint") -> "Fingerprint":
        """Combine two fingerprints of the same type.

        Args:
            other: The fingerprint to absorb.

        Returns:
            A fingerprint holding the union. Merging the samples of one type rather
            than scoring them separately is what lets a type whose layout varies
            between customers still match either variant.
        """
        return Fingerprint(sheets=self.sheets | other.sheets, headers=self.headers | other.headers)

    def __bool__(self) -> bool:
        """Whether the fingerprint carries any evidence.

        Returns:
            True when at least one token was found.
        """
        return bool(self.sheets or self.headers)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One artifact type the workbook might be.

    Attributes:
        key: The artifact type's key.
        label: What a person calls it.
        score: Similarity to that type's stored samples, 0.0 to 1.0.
    """

    key: str
    label: str
    score: float


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """What detection concluded, and why.

    Attributes:
        verdict: ``confident``, ``ambiguous``, or ``unknown``.
        candidates: Every scored type, best first.
        reason: One sentence a person can read on the upload form.
    """

    verdict: str
    candidates: tuple[Candidate, ...]
    reason: str

    @property
    def best(self) -> Candidate | None:
        """The leading candidate.

        Returns:
            The highest-scoring type, or ``None`` when nothing scored above the floor.
        """
        return self.candidates[0] if self.candidates else None


def fingerprint_sheet(sheet: ReportSheet) -> Fingerprint:
    """Fingerprint one worksheet.

    Args:
        sheet: A parsed worksheet.

    Returns:
        Its normalized name and header tokens.
    """
    return Fingerprint(
        sheets=_normalized_set([sheet.name]),
        headers=_normalized_set(sheet.header),
    )


def fingerprint_workbook(path: Path) -> Fingerprint:
    """Fingerprint a whole workbook.

    The generic parser is used rather than a type-specific one, because which type
    this is happens to be the question being asked.

    Args:
        path: The ``.xlsx`` file.

    Returns:
        The pooled fingerprint of every sheet.

    Raises:
        ParseError: When the file cannot be opened as a workbook.
    """
    document = GenericReportParser("unknown").parse(path)
    result = Fingerprint()
    for sheet in document.sheets:
        result = result.merge(fingerprint_sheet(sheet))
    return result


def _sheet_fingerprints(path: Path) -> list[Fingerprint]:
    """Fingerprint each sheet of a workbook separately.

    Args:
        path: The ``.xlsx`` file.

    Returns:
        One fingerprint per sheet, in workbook order.

    Raises:
        ParseError: When the file cannot be opened as a workbook.
    """
    return [fingerprint_sheet(sheet) for sheet in GenericReportParser("unknown").parse(path).sheets]


@dataclass(frozen=True, slots=True)
class _Reference:
    """The stored evidence for one artifact type.

    Attributes:
        key: The artifact type's key.
        label: What a person calls it.
        merged: Every sample's sheets and headers pooled.
        per_sheet: One fingerprint per sample sheet, for matching a single tab.
    """

    key: str
    label: str
    merged: Fingerprint
    per_sheet: tuple[Fingerprint, ...]


def _references(session: Session, data_dir: Path, with_headers: bool = True) -> list[_Reference]:
    """Build the reference fingerprints from the stored samples.

    Sheet names come from the ``sheets`` column on the sample row, which is filled in
    at upload precisely so detection does not have to open the file. The file is
    opened only for the header tokens, which are not stored anywhere and are what
    separates two types that happen to name their tabs alike. A sample whose file has
    gone missing still contributes its sheet names.

    Args:
        session: An open session.
        data_dir: The shared volume the samples live under.
        with_headers: Whether to open each sample for its header row.

    Returns:
        One reference per active report type that has at least one usable sample.
    """
    specs = {
        spec.key: spec
        for spec in catalog.load_artifacts(session, active_only=True)
        if spec.kind == "report"
    }
    references: list[_Reference] = []

    for row in session.query(models.ArtifactType).all():
        spec = specs.get(row.key)
        if spec is None:
            continue

        merged = Fingerprint()
        per_sheet: list[Fingerprint] = []
        for sample in row.samples:
            stored_sheets = sample.sheets if isinstance(sample.sheets, list) else []
            merged = merged.merge(
                Fingerprint(sheets=_normalized_set(str(s) for s in stored_sheets))
            )
            if not with_headers:
                continue
            path = data_dir / sample.storage_path if sample.storage_path else None
            if path is None or not path.exists():
                continue
            try:
                sheets = _sheet_fingerprints(path)
            except ParseError:
                _LOG.warning("sample %d of %r could not be read for detection", sample.id, row.key)
                continue
            per_sheet.extend(sheets)
            for fingerprint in sheets:
                merged = merged.merge(fingerprint)

        if merged:
            references.append(
                _Reference(key=row.key, label=spec.label, merged=merged, per_sheet=tuple(per_sheet))
            )

    return references


def fingerprint_samples(session: Session, data_dir: Path) -> dict[str, Fingerprint]:
    """Fingerprint the stored samples of every active report type.

    Args:
        session: An open session.
        data_dir: The shared volume the samples live under.

    Returns:
        Artifact key to the merged fingerprint of all of its samples. A type with no
        usable sample is absent, because there is nothing to match it against.
    """
    return {reference.key: reference.merged for reference in _references(session, data_dir)}


def score(candidate: Fingerprint, reference: Fingerprint) -> float:
    """Measure how alike two fingerprints are.

    Jaccard similarity over the union of sheet-name and header tokens. It is
    symmetric, bounded, and needs no training data, and every part of it is
    recomputable by hand — which is the point, because this decides what a user is
    shown (ADR-001).

    Args:
        candidate: The uploaded workbook's fingerprint.
        reference: A stored type's fingerprint.

    Returns:
        A value from 0.0 (nothing in common) to 1.0 (identical), and 0.0 when either
        side is empty.
    """
    left, right = candidate.tokens, reference.tokens
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _verdict(candidates: Sequence[Candidate], subject: str) -> DetectionResult:
    """Turn scored candidates into a verdict with a reason.

    Args:
        candidates: Every scored type, best first.
        subject: What was scored, named in the reason sentence.

    Returns:
        The result. Candidates below the floor are dropped rather than shown, so an
        "I am not sure" answer is not padded out with noise.
    """
    kept = tuple(c for c in candidates if c.score >= SCORE_FLOOR)
    if not kept:
        return DetectionResult(
            verdict="unknown",
            candidates=(),
            reason=f"{subject} does not resemble any stored sample.",
        )

    best = kept[0]
    runner_up = kept[1].score if len(kept) > 1 else 0.0
    if best.score >= CONFIDENT_SCORE and best.score - runner_up >= CONFIDENT_MARGIN:
        return DetectionResult(
            verdict="confident",
            candidates=kept,
            reason=(
                f"{subject} matches the stored samples of {best.label} "
                f"({best.score:.0%} of its sheet and column labels)."
            ),
        )
    if len(kept) > 1 and best.score - runner_up < CONFIDENT_MARGIN:
        return DetectionResult(
            verdict="ambiguous",
            candidates=kept,
            reason=(
                f"{subject} matches {best.label} and {kept[1].label} about equally; "
                "please pick the right one."
            ),
        )
    return DetectionResult(
        verdict="ambiguous",
        candidates=kept,
        reason=(
            f"{subject} looks somewhat like {best.label} ({best.score:.0%}), "
            "but not closely enough to be sure."
        ),
    )


def _scored(
    candidate: Fingerprint, references: Sequence[_Reference], per_sheet: bool
) -> list[Candidate]:
    """Score one fingerprint against every reference.

    Args:
        candidate: The fingerprint to place.
        references: The stored types.
        per_sheet: Whether to score against each sample sheet on its own and keep the
            best. One tab of a multi-tab file can never resemble a whole reference
            workbook, so a per-sheet question has to be asked per-sheet.

    Returns:
        The candidates, best first.
    """
    results: list[Candidate] = []
    for reference in references:
        if per_sheet:
            pool = reference.per_sheet or (reference.merged,)
            value = max(score(candidate, sheet) for sheet in pool)
        else:
            value = score(candidate, reference.merged)
        results.append(Candidate(key=reference.key, label=reference.label, score=round(value, 4)))
    results.sort(key=lambda c: (-c.score, c.key))
    return results


def detect(session: Session, path: Path, data_dir: Path) -> DetectionResult:
    """Work out which artifact type a workbook is.

    Args:
        session: An open session.
        path: The workbook to identify.
        data_dir: The shared volume the samples live under.

    Returns:
        The scored candidates and a verdict. ``unknown`` when no type is stored with
        a sample, because with nothing to compare against there is no honest guess.

    Raises:
        ParseError: When the file cannot be opened as a workbook.
    """
    references = _references(session, data_dir)
    if not references:
        return DetectionResult(
            verdict="unknown",
            candidates=(),
            reason="no artifact type has a stored sample to compare against.",
        )

    fingerprint = fingerprint_workbook(path)
    result = _verdict(_scored(fingerprint, references, per_sheet=False), "this workbook")
    _LOG.info(
        "detected %s for %s (best %s)",
        result.verdict,
        path.name,
        result.best.key if result.best else "-",
    )
    return result


def detect_sheets(session: Session, path: Path, data_dir: Path) -> dict[str, DetectionResult]:
    """Work out what each tab of a workbook is.

    One file can hold several report types — a field distribution arriving as several
    tabs is the case this exists for — so each sheet is placed on its own and the file
    can end up registered once per detected type.

    Args:
        session: An open session.
        path: The workbook to identify.
        data_dir: The shared volume the samples live under.

    Returns:
        Sheet name to its own result, in workbook order. Empty when no type has a
        stored sample.

    Raises:
        ParseError: When the file cannot be opened as a workbook.
    """
    references = _references(session, data_dir)
    if not references:
        return {}

    results: dict[str, DetectionResult] = {}
    for sheet in GenericReportParser("unknown").parse(path).sheets:
        fingerprint = fingerprint_sheet(sheet)
        results[sheet.name] = _verdict(
            _scored(fingerprint, references, per_sheet=True), f"sheet {sheet.name!r}"
        )
    return results
