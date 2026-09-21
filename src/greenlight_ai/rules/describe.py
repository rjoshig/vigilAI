"""Rendering a rule as one line of prose (ADR-071).

This was `describe_rule` inside `pipeline/s4_trace.py`, where it had five callers: three
inside `pipeline/` and — the reason it moved — the requirements endpoint in
`api/routers/runs.py`. Importing it from there pulled a **stage** into the API process,
and with it the prompt registry and the whole tracing module, to render one string.

`architecture.md` has said since Phase 0 that `api/` never imports `pipeline/`. ADR-071
narrows that to what it always meant — the API may read a pure leaf under `pipeline/`,
never a stage — and this function is the one import that the narrowed rule still
refused, because a stage is exactly what `s4_trace` is. So it moved **down** into
`rules/`, beside the `Rule` it renders, where both sides can reach it and neither has to
reach across the arrow.

It carries field names, operators and thresholds only, never a sample row (ADR-003).
"""

from __future__ import annotations

from greenlight_ai.rules.schema import SET_TYPES, Rule

__all__ = ["describe_rule", "render_value"]


def render_value(value: object) -> str:
    """Render a condition value for comparison or display.

    Args:
        value: The value.

    Returns:
        A stable string. Whole floats lose their trailing zero so a config's ``755.0``
        matches an OSL's ``755``.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return ",".join(render_value(v) for v in value)
    return str(value)


def describe_rule(rule: Rule | None) -> str:
    """Render a rule as one line for a prompt or a finding.

    Args:
        rule: The rule, or ``None``.

    Returns:
        A short description. Carries field names, operators, and thresholds only, never
        a sample row (ADR-003).
    """
    if rule is None:
        return "(no rule)"
    if rule.req_type in SET_TYPES:
        mode = rule.mode or "include"
        return f"{rule.req_type} — {mode} {sorted(rule.values)}"
    if rule.req_type == "waterfall":
        return f"waterfall — steps {list(rule.steps)}"
    if rule.req_type == "quantity":
        return f"quantity — {rule.quantity}"
    parts = [f"{c.field_name} {c.operator} {render_value(c.value)}" for c in rule.conditions]
    joiner = f" {rule.logic} "
    return f"{rule.req_type} — {joiner.join(parts)} (action: {rule.action})"
