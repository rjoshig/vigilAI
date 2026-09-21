"""Parser Protocols and the parsed-document value objects.

Real OSL, config, and report layouts arrive last and only in-house, so every parser
sits behind a Protocol and the pipeline imports the Protocol, never a concrete class
(ADR-006). The first implementations are driven by the synthetic fixtures in
``tests/fixtures/``.

All value objects here are frozen dataclasses: parsing produces immutable facts about a
document, and every later stage reads them without being able to mutate shared state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Mapping, Protocol, Sequence

from greenlight_ai.resolve import Resolution, resolve, squashed

__all__ = [
    "BUILTIN_REPORT_KINDS",
    "CONFIG_KIND",
    "OSL_KIND",
    "ParseError",
    "ReportKind",
    "OslTable",
    "OslSection",
    "OslDocument",
    "ConfigBlock",
    "ConfigDocument",
    "ReportCell",
    "ReportSheet",
    "ReportDocument",
    "OslParser",
    "ConfigParser",
    "ReportParser",
]

#: A report type's key. An open string rather than a closed set, because an
#: administrator can define new report types without a code change (ADR-020). The
#: built-in keys below are the ones the *fixed* report checks in
#: :mod:`greenlight_ai.checks.reports` know how to interpret; anything else is parsed,
#: stored, and available to admin-defined checks, but has no built-in check of its own.
ReportKind = str

#: The report types the pipeline has built-in checks for. Keep these keys stable: the
#: checks in :mod:`greenlight_ai.checks.reports` look for them by name.
BUILTIN_REPORT_KINDS: tuple[str, ...] = (
    "dirt",
    "field_distribution",
    "state_distribution",
    "score_distribution",
    "counts",
    "cross_tab",
    "billing",
)

#: The two inputs that are not reports. Their keys are fixed because the pipeline
#: reads them with dedicated parsers.
OSL_KIND: str = "osl"
CONFIG_KIND: str = "config"


class ParseError(Exception):
    """A document could not be parsed into the canonical shape.

    Raised with the file path and the reason. Never raised for merely unexpected values:
    a document that parses but disagrees with the OSL produces findings, not exceptions.
    """

    # B042 wants every argument forwarded to ``super().__init__`` so that pickle and
    # copy can rebuild the instance. Forwarding alone does not achieve that here,
    # because the constructor signature differs from the stored args; ``__reduce__``
    # below is what makes the round-trip work, and a test asserts it.
    def __init__(self, path: Path, reason: str) -> None:  # noqa: B042
        """Initialise the error.

        Args:
            path: The file that failed to parse.
            reason: Why it failed, in terms a reviewer can act on.
        """
        super().__init__(f"{path.name}: {reason}")
        self.path = path
        self.reason = reason

    def __reduce__(self) -> tuple[type[ParseError], tuple[Path, str]]:
        """Support pickling and copying.

        The worker may carry an exception across a process boundary when a job fails, so
        the error has to survive a round-trip with its path and reason intact.

        Returns:
            The callable and arguments needed to rebuild an equivalent error.
        """
        return (type(self), (self.path, self.reason))


# --------------------------------------------------------------------------------------
# OSL (the requirement spec, a Word document)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OslTable:
    """One table inside an OSL section.

    Attributes:
        index: Position of the table within its section, starting at 1.
        header: The header row, already stripped.
        rows: Body rows. Ragged rows are padded to the header width by the parser.
    """

    index: int
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def as_text(self) -> str:
        """Render the table as pipe-delimited text for an LLM prompt.

        Returns:
            One line per row, header first. Used by stage 2, which reads meaning from the
            table; no comparison happens here (ADR-001).
        """
        lines = [" | ".join(self.header)]
        lines.extend(" | ".join(row) for row in self.rows)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class OslSection:
    """One heading-delimited section of the OSL.

    Attributes:
        number: The section number as written in the document, e.g. ``"3.1"``.
        heading: The heading text without the number.
        level: Heading depth, 1 for a top-level heading.
        paragraphs: Body paragraphs, blank ones removed.
        tables: Tables that appear under this heading.
    """

    number: str
    heading: str
    level: int
    paragraphs: tuple[str, ...]
    tables: tuple[OslTable, ...] = ()

    @property
    def ref(self) -> str:
        """A human-readable source reference for evidence panels.

        Returns:
            E.g. ``"OSL section 3.1 Geography"``. A section with no number renders as
            ``"OSL section Notes"`` rather than inventing a number for it.
        """
        return " ".join(part for part in ("OSL section", self.number, self.heading) if part)

    def as_text(self) -> str:
        """Render the whole section as text for an LLM prompt.

        Returns:
            Heading, paragraphs, then each table, separated by blank lines.
        """
        parts = [f"{self.number} {self.heading}".strip()]
        parts.extend(self.paragraphs)
        parts.extend(table.as_text() for table in self.tables)
        return "\n\n".join(p for p in parts if p)


@dataclass(frozen=True, slots=True)
class OslDocument:
    """A parsed OSL.

    Attributes:
        path: Where the document was read from.
        title: The document title, or the file stem when it has no title.
        sections: Sections in document order.
    """

    path: Path
    title: str
    sections: tuple[OslSection, ...]

    def section(self, number: str) -> OslSection | None:
        """Look up a section by its number.

        Args:
            number: The section number as written, e.g. ``"3.1"``.

        Returns:
            The section, or ``None`` when the document has no such section.
        """
        for section in self.sections:
            if section.number == number:
                return section
        return None


# --------------------------------------------------------------------------------------
# ETL config (JSON)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfigBlock:
    """One logical block of the ETL config, with the JSON path that located it.

    A block is the unit stage 3 describes and stage 4 traces to a requirement, so it is
    deliberately coarse: one filter, one rule, one suppression, the output field list.

    Attributes:
        json_path: JSONPath-ish locator, e.g. ``"filters[2]"`` or ``"rules.score"``.
        kind: The config key family the block came from, e.g. ``"filters"``.
        content: The raw JSON value at that path.
    """

    json_path: str
    kind: str
    content: object

    def as_text(self) -> str:
        """Render the block for an LLM prompt.

        Returns:
            The JSON path followed by the compact JSON value.
        """
        import json

        return f"{self.json_path} = {json.dumps(self.content, sort_keys=True)}"


@dataclass(frozen=True, slots=True)
class ConfigDocument:
    """A parsed ETL config.

    Attributes:
        path: Where the config was read from.
        configuration_id: The config's own identifier, used to version captured configs.
        customer: The customer the configuration names, verbatim, or empty when it names
            none. Compared with the customer the submitter chose before the run starts
            (ADR-041); absence is absence, never a parse error.
        last_modified: The ``last_modified`` value carried in the file, verbatim.
        blocks: Logical blocks in document order.
        raw: The whole decoded document, for evidence rendering.
    """

    path: Path
    configuration_id: str
    last_modified: str | None
    blocks: tuple[ConfigBlock, ...]
    customer: str = ""
    raw: Mapping[str, object] = field(default_factory=dict)

    def block(self, json_path: str) -> ConfigBlock | None:
        """Look up a block by its JSON path.

        Args:
            json_path: The locator, exactly as stored.

        Returns:
            The block, or ``None`` when no block sits at that path.
        """
        for block in self.blocks:
            if block.json_path == json_path:
                return block
        return None


# --------------------------------------------------------------------------------------
# Output reports (Excel)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportCell:
    """One cell, with its address, so a finding can point at it.

    Attributes:
        address: The A1-style address within the sheet, e.g. ``"D14"``.
        value: The cell value as read, already masked when the column is masked.
    """

    address: str
    value: object


#: Reducing a name to a comparable form is one job with one implementation
#: (Phase 6.21a). This module used to carry its own, subtly different from the three
#: others in the codebase; it now uses the shared one and keeps the old name as a local
#: alias so the call sites below read the way they always did.
_normalise_label: Final = squashed


@dataclass(frozen=True, slots=True)
class ReportSheet:
    """One worksheet of a report.

    Attributes:
        name: The sheet name.
        header: The header row, stripped; empty when the sheet has no header.
        rows: Body rows as cells, so every value keeps its address.
        masked_columns: Header names whose values were replaced at parse time (ADR-003).
    """

    name: str
    header: tuple[str, ...]
    rows: tuple[tuple[ReportCell, ...], ...]
    masked_columns: frozenset[str] = frozenset()

    def column(self, name: str, alternates: Sequence[str] = ()) -> tuple[ReportCell, ...]:
        """Return every cell in a named column.

        Args:
            name: The header text. Matched up the deterministic ladder (Phase 6.21a):
                exact, then separators-as-noise, then the same words, then an
                administrator's alternates — so a report heading its field column
                ``Attribute Name`` answers a lookup for ``Attribute``.
            alternates: Other headings that also mean this one.

        Returns:
            The column's cells in row order, empty when no heading resolves.
        """
        found = self.resolve_column(name, alternates)
        if found is None:
            return ()
        index = list(self.header).index(found.value)
        return tuple(row[index] for row in self.rows if index < len(row))

    def resolve_column(self, name: str, alternates: Sequence[str] = ()) -> Resolution | None:
        """Which header, if any, is the one asked for.

        Separated from :meth:`column` so a caller that needs to *say* how a header was
        recognised — because the answer was not exact and a reviewer should know — can
        ask without reading the cells (Phase 6.21a).

        Args:
            name: The header text being looked for.
            alternates: Other headings that also mean this one.

        Returns:
            The resolution, or ``None`` when no deterministic rung settles it.
        """
        return resolve(name, self.header, alternates)

    def lookup(
        self,
        label: str,
        value_column: int = 1,
        label_column: int = 0,
        alternates: Sequence[str] = (),
    ) -> ReportCell | None:
        """Find a value by the label in another column (a "label lookup" locator).

        Preferred over a fixed cell address because it survives inserted rows
        (``docs/design.md`` "Configurable checks").

        Matching normalises case, whitespace, underscores and hyphens, so a report
        writing ``Delivered_count`` or ``Delivered  count`` answers a pointer configured
        as ``Delivered count``. Measured in Phase 6.15: those two spellings did not
        resolve before, and a pointer that does not resolve becomes a "could not check
        this" finding — honest, but a check nobody gets the benefit of.

        Args:
            label: The label text to find.
            value_column: Zero-based index of the column holding the value.
            label_column: Zero-based index of the column holding the label.
            alternates: Other labels that also count, for a report that words it
                differently rather than spelling it differently. Normalising reaches
                ``Delivered_count``; only a person reaches ``Records delivered``.

        Returns:
            The value cell, or ``None`` when no label matches.
        """
        found = self.resolve_label(label, label_column=label_column, alternates=alternates)
        if found is None:
            return None
        for row in self.rows:
            if label_column >= len(row) or value_column >= len(row):
                continue
            cell = row[label_column]
            if isinstance(cell.value, str) and cell.value == found.value:
                return row[value_column]
        return None

    def labels(self, label_column: int = 0) -> tuple[str, ...]:
        """Every label a column carries, in row order.

        Args:
            label_column: Zero-based index of the column holding the labels.

        Returns:
            The distinct non-empty text values, spelled as the workbook spells them.
            This is the candidate list the ladder — and, where it fails, the model —
            is offered (Phase 6.21a).
        """
        seen: list[str] = []
        for row in self.rows:
            if label_column >= len(row):
                continue
            value = row[label_column].value
            if isinstance(value, str) and value.strip() and value not in seen:
                seen.append(value)
        return tuple(seen)

    def resolve_label(
        self,
        label: str,
        label_column: int = 0,
        alternates: Sequence[str] = (),
    ) -> Resolution | None:
        """Which label in a column, if any, is the one asked for.

        Args:
            label: The label text being looked for.
            label_column: Zero-based index of the column holding the labels.
            alternates: Other labels that also count.

        Returns:
            The resolution, or ``None`` when no deterministic rung settles it.
        """
        return resolve(label, self.labels(label_column), alternates)


@dataclass(frozen=True, slots=True)
class ReportDocument:
    """A parsed output report.

    Attributes:
        path: Where the workbook was read from.
        kind: Which report type this is.
        sheets: Sheets in workbook order.
    """

    path: Path
    kind: ReportKind
    sheets: tuple[ReportSheet, ...]

    @property
    def sheet_names(self) -> tuple[str, ...]:
        """Every sheet's name, in workbook order and spelled as the workbook spells it.

        Returns:
            The names. This is the candidate list the ladder — and, where it fails, the
            model — is offered (Phase 6.21a).
        """
        return tuple(sheet.name for sheet in self.sheets)

    def named(self, name: str) -> ReportSheet | None:
        """The sheet whose name is exactly ``name``.

        Args:
            name: A name taken from :attr:`sheet_names`, so it matches verbatim.

        Returns:
            The sheet, or ``None`` when the workbook has no sheet of that name.
        """
        return next((sheet for sheet in self.sheets if sheet.name == name), None)

    def resolve_sheet(self, name: str, alternates: Sequence[str] = ()) -> Resolution | None:
        """Which sheet, if any, is the one asked for.

        Separated from :meth:`sheet` so a caller that needs to *say* how a sheet was
        recognised can ask without reading it (Phase 6.21a).

        Args:
            name: The sheet name being looked for.
            alternates: Other names that also mean this sheet.

        Returns:
            The resolution, or ``None`` when no deterministic rung settles it.
        """
        return resolve(name, self.sheet_names, alternates)

    def sheet(self, name: str, alternates: Sequence[str] = ()) -> ReportSheet | None:
        """Look up a sheet by name.

        Args:
            name: The sheet name. Matched up the deterministic ladder (Phase 6.21a):
                exact, then separators-as-noise, then the same words, then an
                administrator's alternates — so a workbook naming its per-field sheet
                ``Attribute Summary`` answers a lookup for ``Attributes``.
            alternates: Other names that also mean this sheet.

        Returns:
            The sheet, or ``None`` when no name resolves.
        """
        found = self.resolve_sheet(name, alternates)
        return None if found is None else self.named(found.value)


# --------------------------------------------------------------------------------------
# Protocols (ADR-006)
# --------------------------------------------------------------------------------------


class OslParser(Protocol):
    """Reads a requirement spec into :class:`OslDocument`."""

    def parse(self, path: Path) -> OslDocument:
        """Parse the OSL at ``path``.

        Args:
            path: The document to read.

        Returns:
            The parsed document.

        Raises:
            ParseError: When the file cannot be read as an OSL.
        """
        ...


class ConfigParser(Protocol):
    """Reads an ETL config into :class:`ConfigDocument`."""

    def parse(self, path: Path) -> ConfigDocument:
        """Parse the config at ``path``.

        Args:
            path: The document to read.

        Returns:
            The parsed document.

        Raises:
            ParseError: When the file is not valid JSON or lacks a configuration id.
        """
        ...


class ReportParser(Protocol):
    """Reads one report type into :class:`ReportDocument`.

    One implementation per :data:`ReportKind`; the pipeline selects by kind.
    """

    kind: ReportKind

    def parse(self, path: Path, masked_columns: Sequence[str] = ()) -> ReportDocument:
        """Parse the workbook at ``path``.

        Args:
            path: The workbook to read.
            masked_columns: Header names whose values must be masked at parse time, before
                anything is logged or sent to a model (ADR-003).

        Returns:
            The parsed document.

        Raises:
            ParseError: When the workbook cannot be read as this report type.
        """
        ...
