"""What each role may do (Phase 6.20a, ADR-049).

The table in `greenlight_ai/auth/roles.py` is the specification; these tests are how it
is read back. Every line of the matrix in `docs/phase-6.20.md` has an assertion here, so
the document and the code cannot quietly disagree about what a reviewer may do.
"""

from __future__ import annotations

import pytest

from greenlight_ai.auth.roles import (
    ROLES,
    Capability,
    DEFAULT_ROLES,
    Role,
    capabilities_of,
    describe,
    has_capability,
    holds,
    normalize_roles,
)

#: What a reviewer may do, and what an administrator may do that a reviewer may not.
#: Written out rather than derived from the module, so changing a grant has to be done
#: twice -- once in the code and once here, deliberately.
REVIEWER_MAY = (
    Capability.VIEW_ADMIN,
    Capability.APPROVE_TRAINING,
    Capability.MANAGE_RULES,
    Capability.TEACH_MODEL,
    Capability.MANAGE_REFERENCE,
)
ADMIN_ONLY = (
    Capability.MANAGE_PRIVACY,
    Capability.MANAGE_ARTIFACTS,
    Capability.MANAGE_PROGRAMMES,
    Capability.MANAGE_MEANING,
    Capability.MANAGE_USERS,
    Capability.MANAGE_SETTINGS,
)


def test_a_user_may_do_nothing_in_the_console() -> None:
    """Their work is the user app, which is not gated by capability at all."""
    assert capabilities_of(["user"]) == frozenset()


@pytest.mark.parametrize("capability", REVIEWER_MAY, ids=lambda c: c.value)
def test_a_reviewer_judges_the_work(capability: Capability) -> None:
    """Approving what the tool learned, the rule surfaces, and the vocabulary.

    Args:
        capability: One row of the matrix.
    """
    assert has_capability(["reviewer"], capability)


@pytest.mark.parametrize("capability", ADMIN_ONLY, ids=lambda c: c.value)
def test_a_reviewer_does_not_define_the_deployment(capability: Capability) -> None:
    """The line this phase exists to draw: judging the work is not defining it.

    Args:
        capability: One row of the matrix.
    """
    assert not has_capability(["reviewer"], capability)


def test_an_administrator_may_do_everything() -> None:
    """Including everything a reviewer may: the roles nest rather than divide."""
    assert capabilities_of(["admin"]) == frozenset(Capability)
    assert capabilities_of(["reviewer"]) < capabilities_of(["admin"])


def test_roles_add_up_and_never_take_away() -> None:
    """Somebody is usually a reviewer *and* a user; holding both cannot cost them."""
    assert capabilities_of(["user", "reviewer"]) == capabilities_of(["reviewer"])
    assert capabilities_of(["user", "admin"]) == capabilities_of(["admin"])


def test_an_account_with_nothing_ticked_is_still_a_user() -> None:
    """Saving a form with no box ticked must not lock somebody out of everything."""
    assert normalize_roles([]) == DEFAULT_ROLES
    assert normalize_roles(None) == DEFAULT_ROLES


def test_a_name_that_is_not_a_role_is_dropped_rather_than_trusted() -> None:
    """A stored value from an older version, or a hand-edited row."""
    assert normalize_roles(["admin", "wizard"]) == ("admin",)
    assert normalize_roles(["wizard"]) == DEFAULT_ROLES


def test_roles_come_back_in_a_stable_order_weakest_first() -> None:
    """So a console renders them the same way twice and a stored value compares equal."""
    assert normalize_roles(["admin", "user"]) == ("user", "admin")
    assert normalize_roles(["reviewer", "admin", "user"]) == ROLES


def test_every_role_says_what_it_is_for() -> None:
    """The console shows this beside the checkbox; a blank one teaches nobody."""
    for role in ROLES:
        assert len(describe(role)) > 40, f"{role} needs a description worth reading"
    assert describe("wizard") == ""


# --- holds(): the one question SQL cannot portably answer ---------------------------


def test_holds_finds_a_role_in_the_list() -> None:
    """What ``other_active_admins`` asks of every row."""
    assert holds(["user", "admin"], Role.ADMIN) is True
    assert holds(["user", "reviewer"], Role.ADMIN) is False


def test_holds_normalizes_before_answering() -> None:
    """An unknown stored name is dropped rather than trusted, here as everywhere."""
    assert holds(["administrator"], Role.ADMIN) is False
    assert holds([], Role.USER) is True, "nothing stored still reads as a plain user"
    assert holds(None, Role.USER) is True
