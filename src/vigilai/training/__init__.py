"""The training loop: observations, candidates, and the rule lifecycle (ADR-021).

A person's sentence becomes a rule through four gates, and a human holds the only one
that matters:

    observation → draft candidate → approved rule → shadow → active

Nothing here evaluates anything. Approval writes into the rule tables the pipeline
already reads, so there is one rule surface, one evaluator, and one place to look when
a finding is wrong.
"""

from vigilai.training.lifecycle import (
    RULE_STATES,
    RESTORE_WINDOW_DAYS,
    delete_rule,
    disable_rule,
    enable_rule,
    restore_rule,
    set_state,
)

__all__ = [
    "RULE_STATES",
    "RESTORE_WINDOW_DAYS",
    "delete_rule",
    "disable_rule",
    "enable_rule",
    "restore_rule",
    "set_state",
]
