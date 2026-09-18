#!/usr/bin/env python3
"""Keep the status markers in the phase docs true to their checkboxes.

Every level of a phase doc carries a status — the phase, each milestone, each scope
group, each acceptance criterion — and a human updating four levels by hand will get one
of them wrong eventually. This derives the three upper levels from the boxes beneath
them, so the only thing anyone has to remember is to tick the box.

Run it to fix the docs, or with ``--check`` to fail when they have drifted, which is
what ``scripts/check_docs.sh`` does before every commit.

Usage:
    python scripts/update_phase_status.py            # rewrite the markers
    python scripts/update_phase_status.py --check    # exit 1 if any are stale
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Final, Sequence

__all__ = ["apply", "derive", "main"]

#: The marker written after a heading, by derived state.
MARK: Final[dict[str, str]] = {
    "complete": "✅ complete",
    "in_progress": "🟡 in progress",
    "not_started": "⬜ not started",
}

#: Sections whose contents are a checklist worth summarising.
SECTION: Final = re.compile(
    r"^(## (?:Scope|Milestones.*?|Acceptance criteria|Exit criteria))(?:\s+·\s+[✅🟡⬜].*)?$"
)
SUB: Final = re.compile(r"^(### .+?)(?:\s+·\s+[✅🟡⬜].*)?$")
GROUP: Final = re.compile(r"^(\*\*[^*\n]+\*\*(?:\s+\(.*\))?)(?:\s+·\s+[✅🟡⬜].*)?$")

#: Checkboxes appear as "- [x]" in scope lists and "1. [x]" in criteria lists. "[~]"
#: means partly met: real progress that must not read as done.
BOX: Final = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\[( |x|~)\]", re.M)


def derive(block: str) -> str | None:
    """Summarise a block of checkboxes.

    Args:
        block: The lines beneath a heading.

    Returns:
        The state, or ``None`` when the block holds no checkboxes and so has nothing to
        summarise. A block with any unticked or partial box is never ``"complete"``.
    """
    marks = [m.group(1) for m in BOX.finditer(block)]
    if not marks:
        return None
    if "~" in marks or (" " in marks and "x" in marks):
        return "in_progress"
    return "complete" if " " not in marks else "not_started"


def _is_group(line: str) -> bool:
    """Whether a line is a bold scope-group heading.

    Args:
        line: The line.

    Returns:
        ``True`` for a group heading, excluding the status and goal lines that open
        every phase doc.
    """
    return bool(GROUP.match(line)) and not line.startswith(("**Status:**", "**Goal:**"))


def _boundary(line: str, level: str) -> bool:
    """Whether a line ends the block belonging to a heading.

    Args:
        line: The line to test.
        level: ``"section"``, ``"sub"``, or ``"group"``.

    Returns:
        ``True`` when the block ends here.
    """
    if level == "section":
        return line.startswith("## ")
    if level == "sub":
        return line.startswith(("## ", "### "))
    return line.startswith(("## ", "### ")) or _is_group(line)


def rewrite(text: str) -> str:
    """Return the document with every derived marker refreshed.

    Args:
        text: The phase doc.

    Returns:
        The document with correct markers.
    """
    lines = text.split("\n")
    out: list[str] = []
    for index, line in enumerate(lines):
        base: str | None = None
        level = ""
        if (match := SECTION.match(line)) is not None:
            base, level = match.group(1), "section"
        elif line.startswith("### ") and (match := SUB.match(line)) is not None:
            base, level = match.group(1), "sub"
        elif _is_group(line) and (match := GROUP.match(line)) is not None:
            base, level = match.group(1), "group"

        if base is None:
            out.append(line)
            continue

        end = index + 1
        while end < len(lines) and not _boundary(lines[end], level):
            end += 1
        state = derive("\n".join(lines[index + 1 : end]))
        out.append(f"{base} · {MARK[state]}" if state else base)
    return "\n".join(out)


def apply(paths: Sequence[Path], check_only: bool = False) -> list[Path]:
    """Refresh or verify the markers in each document.

    Args:
        paths: The phase docs.
        check_only: Report drift without writing.

    Returns:
        The documents whose markers were stale.
    """
    stale: list[Path] = []
    for path in paths:
        current = path.read_text(encoding="utf-8")
        updated = rewrite(current)
        if updated != current:
            stale.append(path)
            if not check_only:
                path.write_text(updated, encoding="utf-8")
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments.

    Returns:
        ``0`` when the docs are correct (or were fixed), ``1`` when ``--check`` found
        drift.
    """
    parser = argparse.ArgumentParser(description="Derive phase-doc status markers.")
    parser.add_argument("--check", action="store_true", help="Fail if any marker is stale.")
    parser.add_argument(
        "--docs", type=Path, default=Path("docs"), help="Where the phase docs live."
    )
    args = parser.parse_args(argv)

    paths = sorted(args.docs.glob("phase-[0-6].md"))
    if not paths:
        print(f"no phase docs found in {args.docs}", file=sys.stderr)
        return 1

    stale = apply(paths, check_only=args.check)
    if args.check and stale:
        for path in stale:
            print(f"stale status marker in {path}", file=sys.stderr)
        print("run: python scripts/update_phase_status.py", file=sys.stderr)
        return 1
    if stale:
        for path in stale:
            print(f"updated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
