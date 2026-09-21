"""The settings catalogue, and the file a deployment copies to configure it (ADR-023)."""

from __future__ import annotations

import pathlib
import re

from greenlight_ai.config.registry import SETTINGS


def _env_names_in_example() -> set[str]:
    """Every variable `.env.example` names, commented-out rows included.

    A commented row is documentation too: it is how the file says "this exists, and here
    is its default", which is exactly what a deprecated row or one bearing a secret
    needs.
    """
    example = pathlib.Path(__file__).resolve().parents[2] / ".env.example"
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example.read_text(encoding="utf-8"), re.M))


def test_every_setting_is_named_in_env_example() -> None:
    """`.env.example` is the middle layer of ADR-023, so it must list the whole surface.

    The file's own header tells a deployment that a setting nobody has touched in the
    console still comes from here. Twenty-nine of the sixty-four were missing from it —
    the entire report-chat group among them, which ships off and is therefore the one
    group a deployment has to find in order to use at all. A setting discoverable only
    by reading `config/registry.py` is not configurable by the person who deploys.
    """
    documented = _env_names_in_example()
    missing = sorted(spec.env for spec in SETTINGS if spec.env not in documented)
    assert not missing, (
        "these settings resolve from the environment but `.env.example` never names "
        "them:\n  " + "\n  ".join(missing)
    )


def _values_in_example() -> dict[str, str]:
    """Each variable in `.env.example` and the value it is given."""
    example = pathlib.Path(__file__).resolve().parents[2] / ".env.example"
    values: dict[str, str] = {}
    for line in example.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=(.*)$", line)
        if match:
            values.setdefault(match.group(1), match.group(2).split("#")[0].strip())
    return values


def test_env_example_agrees_with_the_built_in_defaults() -> None:
    """Naming a setting is not enough: the value beside it has to be the default.

    This layer **overrides** the built-in default (ADR-023), so a stale value in this
    file is not documentation that has fallen behind — it is a setting a deployment is
    actively changing without meaning to. `GREENLIGHT_AI_UI_THEME_LOCKED` was the one
    that proved it: Phase 6.14e deliberately moved the default to on, this file kept
    saying `false`, and every deployment that copied it unlocked the theme again.

    Typed and bounded here too, because a value outside a setting's own minimum or
    maximum is one the console would refuse and this file would still hand out.
    """
    values = _values_in_example()
    problems: list[str] = []
    for spec in SETTINGS:
        raw = values.get(spec.env)
        if raw is None:
            continue  # the test above owns absence
        if spec.kind == "int":
            try:
                number = int(raw)
            except ValueError:
                problems.append(f"{spec.env}: {raw!r} is not a whole number")
                continue
            if spec.minimum is not None and number < spec.minimum:
                problems.append(f"{spec.env}: {number} is below its minimum {spec.minimum}")
            if spec.maximum is not None and number > spec.maximum:
                problems.append(f"{spec.env}: {number} is above its maximum {spec.maximum}")
            if number != spec.default:
                problems.append(f"{spec.env}: file says {number}, the default is {spec.default}")
        elif spec.kind == "bool":
            if raw.lower() not in ("true", "false"):
                problems.append(f"{spec.env}: {raw!r} is not a boolean")
            elif (raw.lower() == "true") != bool(spec.default):
                problems.append(f"{spec.env}: file says {raw}, the default is {spec.default}")
        elif spec.kind == "enum" and raw and raw not in spec.choices:
            problems.append(f"{spec.env}: {raw!r} is not one of {list(spec.choices)}")
    assert not problems, "`.env.example` disagrees with the registry:\n  " + "\n  ".join(problems)


def test_no_variable_is_defined_twice_in_env_example() -> None:
    """One line per setting, because the last one silently wins.

    Found by a merge rather than by reasoning: `dev` had added
    `GREENLIGHT_AI_CHAT=false` at the foot of the file while this branch was giving the
    chat a section of its own. Git merged both regions happily — two definitions of one
    variable, the second overriding the first, and nothing in the suite looking. A
    duplicate is worse than an omission: the file reads as though it says one thing and
    behaves as the other.
    """
    example = pathlib.Path(__file__).resolve().parents[2] / ".env.example"
    seen: dict[str, int] = {}
    for number, line in enumerate(example.read_text(encoding="utf-8").splitlines(), 1):
        match = re.match(r"^([A-Z][A-Z0-9_]+)=", line)  # uncommented definitions only
        if match:
            key = match.group(1)
            if key in seen:
                raise AssertionError(
                    f"{key} is defined twice in .env.example, at lines {seen[key]} and "
                    f"{number}; the second silently wins"
                )
            seen[key] = number


def test_no_two_settings_share_an_environment_variable() -> None:
    """One name, one setting. Two names for one setting is how the temperature drifted.

    `LLM_TEMPERATURE` and `LLM_TEMPERATURE_PCT` meant the same thing and were read by
    different code paths, so `.env.example` documented the one the running product does
    not read. This catches the shape of that from the registry's side.
    """
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for spec in SETTINGS:
        if spec.env in seen:
            clashes.append(f"{spec.env} is claimed by both {seen[spec.env]} and {spec.key}")
        seen[spec.env] = spec.key
    assert not clashes, "\n".join(clashes)


def test_every_setting_says_what_it_does() -> None:
    """A console that shows a field and explains nothing is a field nobody dares change."""
    silent = [spec.key for spec in SETTINGS if not spec.help.strip()]
    assert not silent, f"these settings carry no help line: {silent}"
