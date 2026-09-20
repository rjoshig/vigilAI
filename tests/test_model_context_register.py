"""The register of what reaches the model cannot drift from the code (Phase 6.14c).

`docs/model-context.md` is quoted by the field markers in both consoles, and an
administrator cannot see a prompt to check it. A register that has quietly stopped being
true is worse than none, so the claims it makes that *can* be checked mechanically are
checked here.

These are deliberately claims about structure, not prose: that the caps it quotes are
the caps the code uses, that the stages it says build a preamble are the ones that do,
and — the one that matters most — that no sample ever reaches a run.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

REPO: Final[Path] = Path(__file__).resolve().parent.parent
REGISTER: Final[Path] = REPO / "docs" / "model-context.md"
PIPELINE: Final[Path] = REPO / "src" / "greenlight_ai" / "pipeline"


@pytest.fixture(scope="module")
def register() -> str:
    """The register's text."""
    return REGISTER.read_text(encoding="utf-8")


def test_the_register_exists_and_says_when_it_was_derived(register: str) -> None:
    """A register with no date is a register nobody can tell is stale."""
    assert "Last derived from the call sites:" in register


def test_the_caps_it_quotes_are_the_caps_the_code_uses(register: str) -> None:
    """The numbers an administrator is shown come from the constants, not from memory."""
    guidance = (PIPELINE / "guidance.py").read_text(encoding="utf-8")
    context_cap = re.search(r"MAX_CONTEXT_CHARS: Final\[int\] = (\d+)", guidance)
    block_cap = re.search(r"MAX_BLOCK_CHARS: Final\[int\] = (\d+)", guidance)
    assert context_cap and block_cap

    # Written with a thousands separator in the document, as a person would read it.
    assert f"{int(context_cap.group(1)):,}" in register
    assert f"{int(block_cap.group(1)):,}" in register

    examples = (REPO / "src" / "greenlight_ai" / "llm" / "examples.py").read_text(encoding="utf-8")
    per_stage = re.search(r"MAX_PER_STAGE: Final\[int\] = (\d+)", examples)
    assert per_stage
    assert f"{per_stage.group(1)} per stage" in register


def test_the_stages_that_build_a_preamble_are_the_ones_the_register_lists(
    register: str,
) -> None:
    """A stage that starts reading guidance must not do so unannounced.

    The register states the list outright, so this compares a set with a set rather
    than fishing for digits in prose — which is how a register drifts while still
    appearing to pass.
    """
    building = sorted(
        int(path.stem[1])
        for path in PIPELINE.glob("s*.py")
        if "preamble(" in path.read_text(encoding="utf-8")
    )
    stated = re.search(r"\*\*The stages that build a preamble\*\* are (.+?)\.\s", register, re.S)
    assert stated, "the register no longer states which stages build a preamble"
    listed = sorted(int(n) for n in re.findall(r"\b(\d)\b \(", stated.group(1)))
    assert listed == building, (
        f"the code builds a preamble in stages {building}; " f"docs/model-context.md says {listed}"
    )


def test_no_sample_reaches_a_run(register: str) -> None:
    """The register's sharpest claim, and the one most worth a test.

    A sample is a specimen other definitions resolve against. If one ever starts being
    read during a run, that is a decision with an ADR-003 dimension and it must not
    happen by accident.
    """
    offenders = []
    for path in PIPELINE.glob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "sample" not in line.lower():
                continue
            # The only mentions allowed are the comments forbidding it.
            if "ADR-003" in line or "sample row" in line.lower():
                continue
            offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "a sample is being read inside the pipeline; docs/model-context.md says none is, "
        "and ADR-003 governs what may reach a prompt:\n" + "\n".join(offenders)
    )


#: Both consoles' source, for claims about what reaches the model.
UI_DIRS: Final[tuple[Path, ...]] = (REPO / "admin-ui", REPO / "user-ui")

#: Phrases that assert nothing reaches the model. Each one is a promise, and a promise
#: that stops being true is worse than no promise: an administrator cannot see a prompt,
#: so the screen is the only account they get.
_ABSOLUTE_CLAIMS: Final[tuple[str, ...]] = (
    "nothing here is sent to the model",
    "nothing on this screen reaches the model",
    "none of this reaches the model",
)


def _ui_sources() -> list[Path]:
    """Every page and component of both apps, skipping dependencies and builds."""
    found: list[Path] = []
    for root in UI_DIRS:
        for sub in ("app", "components"):
            found.extend(
                path
                for path in (root / sub).rglob("*.tsx")
                if "node_modules" not in path.parts and ".next" not in path.parts
            )
    return found


def test_no_screen_makes_a_blanket_claim_that_nothing_reaches_the_model() -> None:
    """A screen-wide promise cannot survive a screen gaining one model-backed field.

    This is not hypothetical. The compliance screen said "nothing here is sent to the
    model" and stayed saying it after Phase 6.15 gave compliance rules a model-backed
    locator; the checks screen said it while judgment checks had been sending their
    instruction since 6.13c. Both were true when written.

    A field may say what *it* does — that is what `<FieldEffect>` is for, and it lives
    next to the field that would change with it. A whole screen may not, because the
    claim outlives the thing it was describing.
    """
    offenders: list[str] = []
    for path in _ui_sources():
        lowered = path.read_text(encoding="utf-8").lower()
        for claim in _ABSOLUTE_CLAIMS:
            if claim in lowered:
                offenders.append(f"{path.relative_to(REPO)}: {claim!r}")
    assert not offenders, (
        "a screen claims nothing on it reaches the model. Say it on the field with "
        "<FieldEffect>, where it is next to the thing that would change:\n" + "\n".join(offenders)
    )
