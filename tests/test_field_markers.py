"""Every surface that writes something the model reads says so (Phase 6.19, part A).

`CLAUDE.md` puts the reason plainly: *an administrator cannot see a prompt, so the label
is the only account they get of where their words end up*. `<FieldEffect>` is that label,
and unlike the help tooltips it never hides.

A field that reaches the model and does not say so is the same defect as shipping it
undocumented, and worse in one specific way: somebody writing a careful paragraph into an
unmarked box has no reason to think it matters, so they write less than they would have
and the tool is worse for it.

**This exists because the gap was found by reading every screen by hand.** That is not a
thing anybody will do again, and a marker is exactly the kind of thing a refactor removes
without noticing. The check is deliberately coarse — it asserts a screen carries the
marker of the right kind, not where it sits — because a coarse check that runs is worth
more than a precise one nobody maintains.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

REPO: Final[Path] = Path(__file__).resolve().parent.parent

#: Every surface that writes something the model reads, and what it should be marked as.
#: Each entry is (path, kind, what the field is) — the third only so a failure says which
#: field a reader should go and look at.
MODEL_SURFACES: Final[tuple[tuple[str, str, str], ...]] = (
    # --- the administrator's console ------------------------------------------------
    ("admin-ui/app/artifacts/page.tsx", "model", "artifact AI context, and a sample's notes"),
    ("admin-ui/app/scopes/page.tsx", "model", "standing instructions, and a programme rule"),
    ("admin-ui/app/checks/page.tsx", "model", "a judgment check's reasoning"),
    ("admin-ui/app/compliance/page.tsx", "model", "a compliance rule's reasoning"),
    ("admin-ui/app/examples/page.tsx", "model", "a worked example, shown to the model directly"),
    ("admin-ui/app/meaning/page.tsx", "model", "a confirmed mapping"),
    ("admin-ui/app/tell/page.tsx", "model", "the sentence the model places on a surface"),
    ("admin-ui/components/guide-editor.tsx", "model", "a validation guide entry"),
    # --- the user's app ---------------------------------------------------------------
    ("user-ui/app/runs/new/page.tsx", "model", "delivery programme, suppressions, notes"),
    ("user-ui/components/config-notes.tsx", "model", "a standing note on a configuration"),
    ("user-ui/components/observation-dialog.tsx", "model", "what a reviewer teaches the tool"),
)

#: Surfaces whose field is evaluated by code rather than read by the model. Marked for
#: the same reason: somebody deciding how much care to take deserves to know which it is.
CODE_SURFACES: Final[tuple[tuple[str, str, str], ...]] = (
    ("admin-ui/app/reference/page.tsx", "code", "masked columns — what never reaches a prompt"),
    ("admin-ui/app/scopes/page.tsx", "code", "programme keywords"),
    ("admin-ui/app/checks/page.tsx", "code", "an expression check"),
    ("admin-ui/components/field-labels-card.tsx", "code", "the credit-date label"),
)


def _source(relative: str) -> str:
    path = REPO / relative
    assert path.exists(), f"{relative} has moved; update this test rather than deleting it"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "relative,kind,field",
    [*MODEL_SURFACES, *CODE_SURFACES],
    ids=[f"{r}:{k}" for r, k, _ in (*MODEL_SURFACES, *CODE_SURFACES)],
)
def test_a_surface_says_what_its_field_does(relative: str, kind: str, field: str) -> None:
    """Each screen carries the marker its field earns.

    Args:
        relative: The screen, from the repository root.
        kind: The `FieldEffect` kind it must carry.
        field: What the field is, so a failure is actionable.
    """
    source = _source(relative)
    assert f'kind="{kind}"' in source, (
        f"{relative} writes {field}, which is {kind!r}, and carries no such marker. "
        "An administrator cannot see a prompt, so the marker is the only account they get."
    )


def test_both_apps_define_the_marker_identically() -> None:
    """The two apps ship their own copy, and the wording people read must not diverge.

    A user told their note *helps the AI* and an administrator told the same thing in
    different words are being given two different products to reason about.
    """
    admin = _source("admin-ui/components/explain.tsx")
    user = _source("user-ui/components/explain.tsx")
    for kind in ("model", "code", "reviewer", "notes", "record"):
        assert f"{kind}: {{" in admin or f'"{kind}"' in admin
        assert f"{kind}: {{" in user or f'"{kind}"' in user
    assert 'label: "Helps the AI"' in admin
    assert 'label: "Helps the AI"' in user


def test_the_marker_cannot_be_switched_off() -> None:
    """`<Explain>` is help and hides when help is off; `<FieldEffect>` is not help.

    What a field does to a run is not a tip for beginners, and a console that stops
    saying it once somebody ticks a box is a console that lies to its experienced users.
    """
    for app in ("admin-ui", "user-ui"):
        source = _source(f"{app}/components/explain.tsx")
        effect = source[source.index("export function FieldEffect") :]
        effect = (
            effect[: effect.index("export function Explain")]
            if "export function Explain" in effect
            else effect
        )
        assert (
            "tooltips" not in effect
        ), f"{app}: FieldEffect must not consult the tooltips setting — it never hides."
