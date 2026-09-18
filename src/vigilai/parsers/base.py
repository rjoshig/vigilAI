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
from typing import Literal, Mapping, Protocol, Sequence

__all__ = [
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

#: Report types the pipeline knows how to check. Admin-defined templates map an uploaded
#: workbook onto one of these (``docs/design.md`` "Configurable checks").
ReportKind = Literal[
    "dirt",
    "field_distribution",
    "state_distribution",
    "score_distribution",
    "counts",
    "cross_tab",
    "billing",
]


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
        last_modified: The ``last_modified`` value carried in the file, verbatim.
        blocks: Logical blocks in document order.
        raw: The whole decoded document, for evidence rendering.
    """

    path: Path
    configuration_id: str
    last_modified: str | None
    blocks: tuple[ConfigBlock, ...]
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

    def column(self, name: str) -> tuple[ReportCell, ...]:
        """Return every cell in a named column.

        Args:
            name: The header text, matched case-insensitively.

        Returns:
            The column's cells in row order, empty when the header is absent.
        """
        lowered = name.strip().lower()
        try:
            index = [h.strip().lower() for h in self.header].index(lowered)
        except ValueError:
            return ()
        return tuple(row[index] for row in self.rows if index < len(row))

    def lookup(self, label: str, value_column: int = 1, label_column: int = 0) -> ReportCell | None:
        """Find a value by the label in another column (a "label lookup" locator).

        Preferred over a fixed cell address because it survives inserted rows
        (``docs/design.md`` "Configurable checks").

        Args:
            label: The label text to find, matched case-insensitively and stripped.
            value_column: Zero-based index of the column holding the value.
            label_column: Zero-based index of the column holding the label.

        Returns:
            The value cell, or ``None`` when the label is not found.
        """
        wanted = label.strip().lower()
        for row in self.rows:
            if label_column >= len(row) or value_column >= len(row):
                continue
            cell = row[label_column]
            if isinstance(cell.value, str) and cell.value.strip().lower() == wanted:
                return row[value_column]
        return None


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

    def sheet(self, name: str) -> ReportSheet | None:
        """Look up a sheet by name.

        Args:
            name: The sheet name, matched case-insensitively.

        Returns:
            The sheet, or ``None`` when the workbook has no such sheet.
        """
        lowered = name.strip().lower()
        for sheet in self.sheets:
            if sheet.name.strip().lower() == lowered:
                return sheet
        return None


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
