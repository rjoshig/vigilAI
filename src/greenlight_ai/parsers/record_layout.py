"""The delivered file's record schema, read as a fourth artifact (Phase 6.22b).

Until this module the tool reconciled three things: the OSL, the config, and the
reports. It had no account of the *delivered file itself* — which fields it carries,
in what order, at what type and size — and so it had no way to answer the question a
reviewer asks first about a layout change: *is what we shipped shaped the way the
order asked for?*

A record layout is the answer, and it is the cheapest artifact in the product: one row
per delivered field, with the field's name, its data type and its size. Its field name
is **what appears as the DIRT column**, which is why it earns its place here rather
than in a document somebody reads. It turns a name the tool could not resolve into a
name it can look up.

Three rules shape the reading:

* **It is optional.** A delivery that uploads none behaves exactly as it did before
  this existed. Every caller is written so that path is the ordinary one.
* **Its own headers go up the ladder.** A layout workbook heading its columns
  ``Column Name``, ``Type`` and ``Length`` is the same document as one heading them
  ``Field name``, ``Data type`` and ``Size``, and a parser that insists on one spelling
  is the shape defect 6.21a exists to stop (ADR-054).
* **Names and shapes, never rows.** A record layout is a schema. It carries no
  customer data, and nothing here reads a delivered value (ADR-003).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, Sequence

from greenlight_ai.parsers.base import RECORD_LAYOUT_KIND, ParseError
from greenlight_ai.resolve import Resolution, present, resolve

__all__ = [
    "DATA_TYPE_HEADERS",
    "FIELD_NAME_HEADERS",
    "MAX_FIELDS",
    "RECORD_LAYOUT_KIND",
    "RecordLayoutDocument",
    "RecordLayoutField",
    "RecordLayoutParser",
    "SIZE_HEADERS",
    "XlsxRecordLayoutParser",
    "parse_record_layout",
]

_LOG: Final = logging.getLogger(__name__)

#: Rows past this are not read. A record layout describes a file's shape; one longer
#: than this is a data dump that has been uploaded into the wrong slot.
MAX_FIELDS: Final[int] = 5_000

#: What the field-name column may be called. The first is what the tool asks for; the
#: rest reach the ladder's fourth rung, because *Column* and *Attribute* are different
#: words rather than different spellings and no amount of normalising connects them.
FIELD_NAME_HEADERS: Final[tuple[str, ...]] = (
    "Field name",
    "Column name",
    "Attribute name",
    "Attribute",
    "Field",
    "Column",
    "Name",
)

#: What the data-type column may be called.
DATA_TYPE_HEADERS: Final[tuple[str, ...]] = (
    "Data type",
    "Type",
    "Datatype",
    "Format",
    "Field type",
)

#: What the size column may be called. ``Precision`` is deliberately absent: a column
#: headed precision is the decimal places, not the width, and reading one as the other
#: would make the tool assert a size nobody delivered.
SIZE_HEADERS: Final[tuple[str, ...]] = (
    "Size",
    "Length",
    "Width",
    "Field size",
    "Field length",
    "Max length",
)


@dataclass(frozen=True, slots=True)
class RecordLayoutField:
    """One field of the delivered record.

    Attributes:
        name: The field name, spelled as the layout spells it. This is what the DIRT
            column is expected to be called.
        data_type: The declared type, as written, e.g. ``"CHAR"`` or ``"DECIMAL"``.
            Empty when the layout does not say.
        size: The declared size, as written, e.g. ``"10"`` or ``"9,2"``. Empty when the
            layout does not say. Kept as text rather than a number because a real
            layout writes widths, precisions and ranges in the same column and turning
            all of them into one integer loses which was which.
        ordinal: Position in the record, starting at one.
    """

    name: str
    data_type: str = ""
    size: str = ""
    ordinal: int = 0

    @property
    def shape(self) -> str:
        """The type and size as one readable phrase.

        Returns:
            Something like ``"CHAR(10)"``, the type alone when there is no size, or an
            empty string when the layout declared neither.
        """
        if self.data_type and self.size:
            return f"{self.data_type}({self.size})"
        return self.data_type or (f"({self.size})" if self.size else "")


@dataclass(frozen=True, slots=True)
class RecordLayoutDocument:
    """A parsed record layout.

    Attributes:
        path: Where it was read from. Empty for a layout rebuilt from a stored
            snapshot, which is how a fallback layout arrives.
        fields: The fields in record order.
        source_run_id: Which run supplied it. Zero when this run uploaded it itself.
        source_date: When that run was finalized, ISO date. Empty when this run
            uploaded it itself.
    """

    path: Path | None = None
    fields: tuple[RecordLayoutField, ...] = ()
    source_run_id: int = 0
    source_date: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        """Every field name, in record order and spelled as the layout spells it.

        Returns:
            The names. This is the candidate list the ladder — and, where it fails, the
            model — is offered, exactly as a workbook's headers are.
        """
        return tuple(field.name for field in self.fields)

    @property
    def borrowed(self) -> bool:
        """Whether this layout came from an earlier run rather than this one.

        Returns:
            ``True`` when a previous delivery supplied it. Every finding that rests on
            a borrowed layout has to say so, because a layout that is one delivery out
            of date is exactly the thing a reviewer needs told (Phase 6.22b).
        """
        return self.source_run_id > 0

    @property
    def provenance(self) -> str:
        """Where this layout came from, as a sentence a finding can carry.

        Returns:
            A clause naming the run and the date for a borrowed layout, empty for one
            this run uploaded.
        """
        if not self.borrowed:
            return ""
        when = f" finalized {self.source_date}" if self.source_date else ""
        return f"from run {self.source_run_id}{when}"

    def field(self, name: str) -> RecordLayoutField | None:
        """The field a name refers to, resolved up the ladder.

        Args:
            name: The field as the OSL asks for it.

        Returns:
            The field, or ``None`` when no rung settles it. ``None`` is not "absent":
            :meth:`carries` is what tells absent from unproven.
        """
        match = present(name, self.names)
        if not match.resolved:
            return None
        return next((f for f in self.fields if f.name == match.found), None)

    def carries(self, name: str) -> bool:
        """Whether the layout declares a field of this name.

        Args:
            name: The field as the OSL asks for it.

        Returns:
            ``True`` when some rung reached one.
        """
        return self.field(name) is not None

    def as_rows(self) -> list[dict[str, object]]:
        """The layout as JSON, for storing on a run or a configuration.

        Returns:
            One dictionary per field, in record order.
        """
        return [
            {
                "name": field.name,
                "data_type": field.data_type,
                "size": field.size,
                "ordinal": field.ordinal,
            }
            for field in self.fields
        ]

    @classmethod
    def from_rows(
        cls,
        rows: object,
        *,
        source_run_id: int = 0,
        source_date: str = "",
    ) -> "RecordLayoutDocument":
        """Rebuild a layout from a stored snapshot.

        Tolerant on purpose: the snapshot comes out of a JSON column, and a row that
        is not a mapping or carries no name is skipped rather than raising. A stored
        layout that has gone strange must not fail a run — the run simply has no
        layout, which is the ordinary state (Phase 6.22b).

        Args:
            rows: What :meth:`as_rows` wrote, as read back from JSON.
            source_run_id: Which run supplied it.
            source_date: When that run was finalized, ISO date.

        Returns:
            The document, empty when nothing could be read.
        """
        fields: list[RecordLayoutField] = []
        if isinstance(rows, list):
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                ordinal = row.get("ordinal")
                fields.append(
                    RecordLayoutField(
                        name=name,
                        data_type=str(row.get("data_type") or "").strip(),
                        size=str(row.get("size") or "").strip(),
                        ordinal=int(ordinal) if isinstance(ordinal, int) else index,
                    )
                )
        return cls(
            path=None,
            fields=tuple(fields),
            source_run_id=source_run_id,
            source_date=source_date,
        )


class RecordLayoutParser(Protocol):
    """Reads a record layout into :class:`RecordLayoutDocument` (ADR-006)."""

    def parse(self, path: Path) -> RecordLayoutDocument:
        """Parse the layout at ``path``.

        Args:
            path: The file to read.

        Returns:
            The parsed document.

        Raises:
            ParseError: When the file cannot be read as a record layout.
        """
        ...


def _header_index(
    header: Sequence[str], wanted: str, alternates: Sequence[str]
) -> tuple[int, Resolution | None]:
    """Which column of the header row is the one asked for.

    Args:
        header: The header row as the workbook writes it.
        wanted: The heading the parser asks for.
        alternates: Other headings that also mean it.

    Returns:
        The zero-based index and the resolution, or ``(-1, None)`` when no rung
        settles it.
    """
    found = resolve(wanted, tuple(header), alternates)
    if found is None:
        return -1, None
    return list(header).index(found.value), found


class XlsxRecordLayoutParser:
    """Reads an ``.xlsx`` record layout.

    The first worksheet whose header row resolves a field-name column is the layout;
    a workbook that carries a cover sheet before it is therefore read correctly rather
    than rejected, which is what real layout workbooks look like.
    """

    def parse(self, path: Path) -> RecordLayoutDocument:
        """Parse the workbook at ``path``.

        Args:
            path: The ``.xlsx`` file to read.

        Returns:
            The parsed document, fields in record order.

        Raises:
            ParseError: When the file is missing, cannot be opened, or carries no
                sheet with a field-name column. The last is a real parse failure and
                not a finding: a workbook nothing in it names a field is not a record
                layout, and reading it as an empty one would silently answer "this
                delivery declares no fields".
        """
        try:
            import openpyxl  # noqa: PLC0415 - lazy so the package imports without it
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ParseError(path, "openpyxl is not installed") from exc

        if not path.exists():
            raise ParseError(path, "file does not exist")
        try:
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - openpyxl raises a variety of types
            raise ParseError(path, f"could not be opened as a workbook ({exc})") from exc

        try:
            for name in workbook.sheetnames:
                fields = self._read_sheet(workbook[name])
                if fields is not None:
                    _LOG.info(
                        "parsed record layout %s: %d field(s) from sheet %r",
                        path.name,
                        len(fields),
                        name,
                    )
                    return RecordLayoutDocument(path=path, fields=fields)
        finally:
            workbook.close()

        suggested = " or ".join(repr(h) for h in FIELD_NAME_HEADERS[:3])
        raise ParseError(
            path,
            "no sheet carries a field-name column; a record layout needs one row per "
            f"field, under a heading such as {suggested}",
        )

    def _read_sheet(self, worksheet: object) -> tuple[RecordLayoutField, ...] | None:
        """Read one worksheet, when it is the layout.

        Args:
            worksheet: The openpyxl read-only worksheet.

        Returns:
            The fields, or ``None`` when this sheet has no field-name column and so is
            not the layout.
        """
        rows_iter = worksheet.iter_rows(max_row=MAX_FIELDS + 1)  # type: ignore[attr-defined]
        try:
            first = next(rows_iter)
        except StopIteration:
            return None

        header = tuple("" if c.value is None else str(c.value).strip() for c in first)
        name_at, _ = _header_index(header, FIELD_NAME_HEADERS[0], FIELD_NAME_HEADERS[1:])
        if name_at < 0:
            return None
        type_at, _ = _header_index(header, DATA_TYPE_HEADERS[0], DATA_TYPE_HEADERS[1:])
        size_at, _ = _header_index(header, SIZE_HEADERS[0], SIZE_HEADERS[1:])

        def text(row: Sequence[object], index: int) -> str:
            """One cell as trimmed text, empty when the column is absent or blank."""
            if index < 0 or index >= len(row):
                return ""
            value = getattr(row[index], "value", None)
            if value is None:
                return ""
            # A size written as 10 in Excel arrives as 10.0; the layout said 10.
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value).strip()

        fields: list[RecordLayoutField] = []
        for row in rows_iter:
            name = text(row, name_at)
            if not name:
                continue
            fields.append(
                RecordLayoutField(
                    name=name,
                    data_type=text(row, type_at),
                    size=text(row, size_at),
                    ordinal=len(fields) + 1,
                )
            )
        return tuple(fields)


def parse_record_layout(path: Path) -> RecordLayoutDocument:
    """Parse a record layout, choosing the parser by file type.

    Args:
        path: The uploaded file.

    Returns:
        The parsed document.

    Raises:
        ParseError: When the file cannot be read as a record layout.
    """
    return XlsxRecordLayoutParser().parse(path)
