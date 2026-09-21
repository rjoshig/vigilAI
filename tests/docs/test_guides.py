"""The in-product Guide is built from the training document (Phase 6.19b).

**One source per audience.** A Guide that can drift from the training document is two
documents, and the second one is the one nobody maintains — which is the exact failure
`docs/phase-6.5.md` exists to prevent for the documents themselves.

The check that matters is the first one: the generated file each app imports is what the
generator produces from the document as it stands right now. Everything after it pins the
parser, because the output is consumed by a renderer that interprets nothing — so
anything the parser leaves as markdown reaches a person's screen as punctuation.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]


@functools.lru_cache(maxsize=1)
def _module() -> Any:
    """Load the generator, which is a script rather than a package module.

    Returns:
        The imported module.

    Registered in ``sys.modules`` before it is executed, because ``@dataclass`` resolves
    its annotations through the module's own entry and fails on a module that is not
    there yet.
    """
    spec = importlib.util.spec_from_file_location("build_guides", ROOT / "scripts/build_guides.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sections(target: str) -> list[dict[str, Any]]:
    """Read one app's generated Guide back out of its TypeScript module.

    Args:
        target: The generated file, relative to the repository root.

    Returns:
        The sections, as the app sees them.
    """
    text = (ROOT / target).read_text()
    payload = text[text.index("= ") + 2 : text.rindex(";")]
    return list(json.loads(payload))


TARGETS: Final = ("user-ui/lib/guide.generated.ts", "admin-ui/lib/guide.generated.ts")


def test_the_generated_guides_are_current() -> None:
    """The one that catches a session editing the document and forgetting to rebuild.

    ``scripts/check_docs.sh`` runs the same check, so this is the belt to that braces:
    the gate a contributor runs and the gate the suite runs both say it.
    """
    assert _module().main(["--check"]) == 0, (
        "a training document changed without its Guide being rebuilt; run "
        "`python scripts/build_guides.py` and commit the result"
    )


@pytest.mark.parametrize("target", TARGETS)
def test_every_section_has_a_title_and_content(target: str) -> None:
    """An empty section is a marker in the wrong place, which is silent otherwise."""
    sections = _sections(target)

    assert len(sections) >= 5, "a Guide with four sections is not teaching the job"
    for section in sections:
        assert section["title"].strip(), section
        assert section["blocks"], f"{section['title']} came out empty"


@pytest.mark.parametrize("target", TARGETS)
def test_no_markdown_survives_into_the_spans(target: str) -> None:
    """The renderer interprets nothing, so a survivor prints as punctuation.

    Table cells were exactly this: they reached the screen as ``**user**`` until the
    generator ran them through the same span resolution as everything else.
    """
    text = json.dumps(_sections(target))

    assert "**" not in text
    assert "*" not in text, "an unresolved italic run"
    assert "```" not in text
    assert not re.search(r"\]\(", text), "a markdown link the Guide cannot follow"


@pytest.mark.parametrize("target", TARGETS)
def test_no_diagram_reaches_the_guide(target: str) -> None:
    """Mermaid belongs to a document somebody is studying, not to a screen."""
    text = json.dumps(_sections(target))

    assert "flowchart" not in text
    assert "-->" not in text


@pytest.mark.parametrize("target", TARGETS)
def test_every_block_is_a_kind_the_renderer_draws(target: str) -> None:
    """A kind nobody drew would disappear from the screen without a word.

    The list is written out rather than imported from the renderer, because the point is
    that the two agree and a shared constant would make disagreement impossible to see.
    """
    drawn = {"heading", "text", "list", "ordered", "table"}

    for section in _sections(target):
        for block in section["blocks"]:
            assert block["kind"] in drawn, f"{section['title']}: {block['kind']}"


def test_a_marker_that_is_not_followed_by_a_heading_is_refused() -> None:
    """Otherwise it silently takes the rest of the document with it."""
    with pytest.raises(SystemExit):
        _module()._sections("<!-- guide 1: A title -->\nnot a heading\n")


def test_two_markers_cannot_claim_the_same_position() -> None:
    """One would win, the other would vanish, and the Guide would look complete."""
    document = (
        "<!-- guide 1: First -->\n## First\n\nSomething.\n\n"
        "<!-- guide 1: Second -->\n## Second\n\nSomething else.\n"
    )

    with pytest.raises(SystemExit):
        _module()._sections(document)


def test_the_marker_title_wins_over_the_document_heading() -> None:
    """A document heading is for a reader going front to back; a Guide's is for somebody
    who arrived with a question."""
    sections = _module()._sections(
        "<!-- guide 1: When the tool is unsure -->\n"
        '## Three different things are called "review"\n\nSomething.\n'
    )

    assert sections[0].title == "When the tool is unsure"
    assert sections[0].source == 'Three different things are called "review"'


def test_a_hard_wrapped_paragraph_is_rejoined() -> None:
    """The document wraps at 90 columns; a screen is whatever width it is."""
    blocks = _module()._blocks(["One sentence that", "runs over two lines."])

    assert blocks == [
        {"kind": "text", "spans": [{"text": "One sentence that runs over two lines."}]}
    ]


def test_a_table_loses_its_separator_row_and_keeps_its_emphasis() -> None:
    """The `| --- |` row says nothing a renderer needs; the bold in a cell does."""
    blocks = _module()._blocks(["| Role | What |", "| --- | --- |", "| **user** | Submits. |"])

    assert blocks == [
        {
            "kind": "table",
            "head": [[{"text": "Role"}], [{"text": "What"}]],
            "rows": [[[{"text": "user", "bold": True}], [{"text": "Submits."}]]],
        }
    ]
