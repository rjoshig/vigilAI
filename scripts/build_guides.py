#!/usr/bin/env python3
"""Build each app's in-product Guide from that audience's training document.

**One source per audience** (Phase 6.19b). The Guide is not a second document: it is the
sections of `docs/user-training.md` and `docs/admin-training.md` that change what
somebody does, in the order a person needs them, rendered on a screen they already have
open. A session that edits the training document and forgets to run this is caught by
``scripts/check_docs.sh``, which runs it with ``--check`` — because a Guide that can
drift from the training document is two documents, and the second one is the one nobody
maintains.

**What is included, and in what order,** is declared in the documents themselves. A
marker line immediately before a heading says the section belongs in the Guide, at which
position, and under what title:

    <!-- guide 4: How to read a finding, and how to decide -->
    ## Reviewing findings

The title is stated separately on purpose. A document heading is written for somebody
reading a document front to back; a Guide heading is written for somebody who arrived
with a question.

**Why blocks rather than markdown.** The output is a typed list of already-parsed blocks
— headings, paragraphs, lists, tables, quotes — with inline emphasis resolved into spans.
Neither app carries a markdown renderer, and a regex one written in the browser would be
a new class of bug in a screen whose whole job is to be trustworthy. Parsing once, here,
in a script that is checked, is cheaper and safer.

Mermaid diagrams are dropped. They are the training document explaining a flow to
somebody studying it; the Guide's job is the few sentences that change what a person
does.

Usage::

    python scripts/build_guides.py            # write both generated files
    python scripts/build_guides.py --check    # fail if either is out of date
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterator, Sequence

ROOT: Final = Path(__file__).resolve().parents[1]

#: Which document feeds which app, and where the generated file lands.
TARGETS: Final[tuple[tuple[str, str, str], ...]] = (
    ("docs/user-training.md", "user-ui/lib/guide.generated.ts", "user app"),
    ("docs/admin-training.md", "admin-ui/lib/guide.generated.ts", "admin console"),
)

#: ``<!-- guide 4: How to read a finding -->`` — position, then the Guide's own title.
MARKER: Final = re.compile(r"^<!--\s*guide\s+(\d+):\s*(.+?)\s*-->$")

#: Inline emphasis the training documents use: ``**bold**``, ``*italic*`` and ``code``.
#: Bold is first in the alternation so ``**x**`` is never read as an empty italic.
_INLINE: Final = re.compile(r"(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`)")

#: ``[text](target)`` becomes its text. A Guide is read inside the product, and a link
#: into the repository is no use to the person reading it.
_LINK: Final = re.compile(r"\[([^\]]+)\]\([^)]+\)")


@dataclass
class Section:
    """One Guide section, ready for a screen.

    Attributes:
        order: Where it sits in the Guide.
        title: The heading the Guide shows, from the marker.
        source: The document heading it came from, so a reader of the code can find it.
        blocks: The parsed content.
    """

    order: int
    title: str
    source: str
    blocks: list[dict[str, object]] = field(default_factory=list)


def _spans(text: str) -> list[dict[str, object]]:
    """Resolve inline emphasis into spans a component can render without parsing.

    Args:
        text: One line of markdown, already stripped of links.

    Returns:
        Spans in order, each with its text and, where it applies, ``bold``, ``italic``
        or ``code``. Nothing is left as markdown for a browser to interpret: a
        ``**`` that reached the screen would be a parser gap rendered as punctuation,
        which is why ``guide-view.test.tsx`` asserts none survives.
    """
    spans: list[dict[str, object]] = []
    for piece in _INLINE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            spans.append({"text": piece[2:-2], "bold": True})
        elif piece.startswith("*") and piece.endswith("*"):
            spans.append({"text": piece[1:-1], "italic": True})
        elif piece.startswith("`") and piece.endswith("`"):
            spans.append({"text": piece[1:-1], "code": True})
        else:
            spans.append({"text": piece})
    return spans


def _clean(line: str) -> str:
    """Strip what a Guide should not carry.

    Args:
        line: A source line.

    Returns:
        The line with markdown links reduced to their text.
    """
    return _LINK.sub(r"\1", line).rstrip()


def _row(line: str) -> list[list[dict[str, object]]]:
    """Split one table row into its cells.

    Args:
        line: A ``| a | b |`` line.

    Returns:
        Each cell as spans. Cells carry emphasis as often as paragraphs do — a role name
        in a table is bold in every one of these documents — so they go through the same
        resolution rather than reaching the screen as markdown.
    """
    return [_spans(cell.strip()) for cell in line.strip().strip("|").split("|")]


def _blocks(lines: Sequence[str]) -> list[dict[str, object]]:
    """Parse one section's lines into blocks.

    Args:
        lines: The section's body, without its own heading.

    Returns:
        Blocks in order. A paragraph's lines are joined, because a hard-wrapped
        document reflows on a screen of unknown width.
    """
    blocks: list[dict[str, object]] = []
    paragraph: list[str] = []
    items: list[str] = []
    ordered = False
    rows: list[list[list[dict[str, object]]]] = []
    fenced = False

    def flush() -> None:
        """Close whatever is open."""
        nonlocal paragraph, items, rows
        if paragraph:
            blocks.append({"kind": "text", "spans": _spans(" ".join(paragraph))})
            paragraph = []
        if items:
            blocks.append(
                {
                    "kind": "ordered" if ordered else "list",
                    "items": [_spans(item) for item in items],
                }
            )
            items = []
        if rows:
            blocks.append({"kind": "table", "head": rows[0], "rows": rows[1:]})
            rows = []

    for raw in lines:
        line = _clean(raw)
        if line.startswith("```"):
            # Diagrams and code samples belong to the document, not to the Guide.
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        if not line.strip():
            flush()
            continue
        if line.startswith("### "):
            flush()
            blocks.append({"kind": "heading", "spans": _spans(line[4:])})
            continue
        if line.startswith("|"):
            raw_cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            # The `| --- |` separator says nothing a renderer needs.
            if all(set(cell) <= {"-", ":"} and cell for cell in raw_cells):
                continue
            cells = _row(line)
            if not rows and (paragraph or items):
                flush()
            rows.append(cells)
            continue
        bullet = re.match(r"^([-*])\s+(.*)$", line)
        number = re.match(r"^(\d+)\.\s+(.*)$", line)
        if bullet or number:
            if paragraph:
                flush()
            if items and ordered is not bool(number):
                flush()
            ordered = bool(number)
            items.append((number or bullet).group(2))  # type: ignore[union-attr]
            continue
        if items:
            # A wrapped continuation of the item above, indented in the source.
            if raw.startswith(("  ", "\t")):
                items[-1] = f"{items[-1]} {line.strip()}"
                continue
            flush()
        paragraph.append(line.strip())

    flush()
    return blocks


def _sections(markdown: str) -> list[Section]:
    """Pull the marked sections out of one training document.

    Args:
        markdown: The document.

    Returns:
        The sections, in the order the markers ask for.

    Raises:
        SystemExit: When a marker is not followed by a heading, or two markers claim the
            same position — both of which would otherwise produce a Guide that silently
            lost a section.
    """
    lines = markdown.splitlines()
    found: list[Section] = []
    for index, line in enumerate(lines):
        match = MARKER.match(line.strip())
        if match is None:
            continue
        heading = lines[index + 1] if index + 1 < len(lines) else ""
        if not heading.startswith("## "):
            raise SystemExit(f"guide marker on line {index + 1} is not followed by a '## ' heading")
        end = next(
            (
                later
                for later in range(index + 2, len(lines))
                if lines[later].startswith("## ") or MARKER.match(lines[later].strip())
            ),
            len(lines),
        )
        found.append(
            Section(
                order=int(match.group(1)),
                title=match.group(2),
                source=heading[3:].strip(),
                blocks=_blocks(lines[index + 2 : end]),
            )
        )

    positions = [section.order for section in found]
    if len(set(positions)) != len(positions):
        raise SystemExit(f"two guide markers claim the same position: {sorted(positions)}")
    return sorted(found, key=lambda section: section.order)


def _render(sections: Sequence[Section], source: str, audience: str) -> str:
    """Write the TypeScript module the app imports.

    Args:
        sections: The parsed sections.
        source: The document they came from.
        audience: Which app this is for, for the header comment.

    Returns:
        The file's contents.
    """
    payload = [
        {"id": f"s{section.order}", "title": section.title, "blocks": section.blocks}
        for section in sections
    ]
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        "// Generated by scripts/build_guides.py from " + source + " — do not edit.\n"
        "//\n"
        "// The Guide for the " + audience + " has one source: that document. Edit the\n"
        "// document, run `python scripts/build_guides.py`, and commit both. A Guide that\n"
        "// can drift from the training document is two documents, and the second one is\n"
        "// the one nobody maintains — `scripts/check_docs.sh` fails when they disagree.\n"
        "\n"
        'import type { GuideSection } from "./guide";\n'
        "\n"
        "export const GUIDE: GuideSection[] = " + body + ";\n"
    )


def _generate() -> Iterator[tuple[Path, str]]:
    """Build every target.

    Yields:
        Each generated file's path and the contents it should have.
    """
    for document, target, audience in TARGETS:
        sections = _sections((ROOT / document).read_text())
        if not sections:
            raise SystemExit(f"{document} carries no guide markers")
        yield ROOT / target, _render(sections, document, audience)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the generated files, or check they are current.

    Args:
        argv: Command-line arguments.

    Returns:
        0 when everything is in order, 1 when ``--check`` found a stale file.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non-zero if a generated file is out of date",
    )
    args = parser.parse_args(argv)

    stale: list[str] = []
    for path, contents in _generate():
        current = path.read_text() if path.exists() else ""
        if current == contents:
            continue
        if args.check:
            stale.append(str(path.relative_to(ROOT)))
            continue
        path.write_text(contents)
        print(f"wrote {path.relative_to(ROOT)}")

    if stale:
        print(
            "these are out of date; run `python scripts/build_guides.py` and commit "
            f"the result: {', '.join(stale)}"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
