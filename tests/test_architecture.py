"""The dependency arrows, enforced rather than remembered (ADR-071).

`architecture.md`, `CLAUDE.md` and `standards/python.md` have all said since Phase 0
that `api/` never imports `pipeline/`. Nothing checked it, and by Phase 8 it was broken
in three places — each time for the same reason, a pure function that happened to live
under `pipeline/`. Phase 8 then built `textfit.py` specifically to honour the rule while
those three imports sat there breaking it.

ADR-071 narrows the rule to what it always meant: **the API may import a pure leaf under
`pipeline/`, never a stage.** A stage owns prompts, a model client and a `RunContext`;
importing one into the API process drags all of that in to render a string. A leaf is
plain code over plain data.

This module is the check. A rule a test enforces is a rule; a rule only a document
states is a wish.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Final, Iterator

import pytest

SRC: Final = pathlib.Path(__file__).resolve().parents[1] / "src" / "greenlight_ai"

#: Modules under `pipeline/` that own a stage of the run. Each one reaches a prompt, a
#: model client or the orchestrator, so none of them may be imported from `api/`.
STAGE_MODULES: Final[frozenset[str]] = frozenset(
    {
        "run",
        "s1_parse",
        "s2_extract",
        "s3_describe",
        "s4_trace",
        "s5_compare",
        "s6_reverse",
        "s7_reports",
        "s8_verify",
        "s9_summarize",
    }
)

#: The pure leaves under `pipeline/` the API is allowed to reach, and nothing else.
#: Adding a name here is a deliberate act: it must hold for `test_every_allowed_leaf_is
#: _really_a_leaf` too, which is what stops the list becoming a way around the rule.
API_MAY_IMPORT: Final[frozenset[str]] = frozenset({"context", "coverage", "guidance"})


def _modules(package: str) -> Iterator[pathlib.Path]:
    """Every Python module under one subpackage."""
    yield from sorted((SRC / package).rglob("*.py"))


def _imports(path: pathlib.Path) -> Iterator[str]:
    """Every dotted name the file imports, absolute form only.

    `from greenlight_ai.pipeline import guidance` is joined back into
    `greenlight_ai.pipeline.guidance`, because the name is the module there and reading
    only `node.module` would see every such import as the package itself.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # `from . import s4_trace` inside api/ would have been invisible: the
                # rule would hold for the import style the code happens to use today
                # and not for the one somebody writes tomorrow. Resolved against the
                # file's own package so a relative import is judged like any other.
                package = _package_of(path)
                if node.level > 1:
                    package = ".".join(package.split(".")[: -(node.level - 1)] or ["greenlight_ai"])
                base = f"{package}.{node.module}" if node.module else package
                for alias in node.names:
                    yield f"{base}.{alias.name}"
            elif node.module:
                for alias in node.names:
                    yield f"{node.module}.{alias.name}"


def _package_of(path: pathlib.Path) -> str:
    """The dotted package a module file belongs to, for resolving relative imports."""
    parts = path.relative_to(SRC).parts[:-1]
    return ".".join(("greenlight_ai", *parts))


def _pipeline_module(dotted: str) -> str:
    """The `pipeline/` module a dotted import names, or an empty string."""
    prefix = "greenlight_ai.pipeline"
    if dotted == prefix:
        return "__init__"
    if not dotted.startswith(f"{prefix}."):
        return ""
    return dotted[len(prefix) + 1 :].split(".")[0]


def test_the_api_never_imports_a_stage() -> None:
    """The half of the rule that has not moved: a stage is a stage, and api/ is above it."""
    offences: list[str] = []
    for path in _modules("api"):
        for dotted in _imports(path):
            module = _pipeline_module(dotted)
            if module in STAGE_MODULES:
                offences.append(f"{path.relative_to(SRC)} imports {dotted}")
    assert not offences, "api/ must never import a pipeline stage:\n" + "\n".join(offences)


def test_the_api_imports_only_the_leaves_it_is_allowed() -> None:
    """The narrowed half: a pure leaf is allowed, and the list of them is explicit."""
    offences: list[str] = []
    for path in _modules("api"):
        for dotted in _imports(path):
            module = _pipeline_module(dotted)
            if module and module not in API_MAY_IMPORT:
                offences.append(f"{path.relative_to(SRC)} imports {dotted}")
    assert not offences, (
        "api/ may import only the pure pipeline leaves ADR-071 names "
        f"({', '.join(sorted(API_MAY_IMPORT))}):\n" + "\n".join(offences)
    )


@pytest.mark.parametrize("leaf", sorted(API_MAY_IMPORT))
def test_every_allowed_leaf_is_really_a_leaf(leaf: str) -> None:
    """A leaf that imports a stage would carry the stage in through the back door.

    This is what keeps :data:`API_MAY_IMPORT` honest. Without it the list is a hole in
    the rule rather than a narrowing of it: anybody could add a module to it, and a
    later commit could give that module a stage import nobody would notice.
    """
    path = SRC / "pipeline" / f"{leaf}.py"
    assert path.exists(), f"{leaf} is on the allow-list but does not exist"
    reached = {_pipeline_module(dotted) for dotted in _imports(path)}
    assert not (reached & STAGE_MODULES), (
        f"pipeline/{leaf}.py is on the API's allow-list but imports a stage: "
        f"{sorted(reached & STAGE_MODULES)}"
    )


def test_a_relative_import_is_judged_like_any_other(tmp_path: pathlib.Path) -> None:
    """The rule must hold for the import style somebody writes tomorrow.

    `_imports` read only absolute `from x import y`. A router written as
    `from ..pipeline import s4_trace` would have been invisible to every check in this
    module, so the rule was enforced against a convention rather than against the
    dependency.
    """
    module = SRC / "api" / "routers" / "__relimport_probe__.py"
    module.write_text("from ..  .pipeline import s4_trace\n".replace("  .", "."), encoding="utf-8")
    try:
        reached = {_pipeline_module(dotted) for dotted in _imports(module)}
        assert "s4_trace" in reached, f"a relative stage import was not seen: {reached}"
    finally:
        module.unlink()


def test_the_pipeline_never_imports_the_api_or_the_worker() -> None:
    """The rest of the arrow, so the whole direction is checked in one place."""
    offences: list[str] = []
    for path in _modules("pipeline"):
        for dotted in _imports(path):
            if dotted.startswith(("greenlight_ai.api", "greenlight_ai.worker")):
                offences.append(f"{path.relative_to(SRC)} imports {dotted}")
    assert not offences, "pipeline/ sits below api/ and worker/:\n" + "\n".join(offences)
