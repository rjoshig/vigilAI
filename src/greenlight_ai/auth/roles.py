"""What each role may do, in one place (Phase 6.20, ADR-049).

Until now there were two roles and no matrix: ``admin`` or ``user``, and ``role ==
"admin"`` scattered through the routers. That is workable for two roles and stops being
workable at three, because the question stops being *who are you* and becomes *what may
you do* — and those have to be written down somewhere a person can read them.

**Roles grant capabilities; code asks about capabilities.** No router asks whether
somebody is a reviewer. It asks whether they may approve training, and the answer is
looked up here. Adding a fourth role is then an edit to one table rather than a search
through five routers, and the question *what can a reviewer actually do?* has an answer
that is read rather than reconstructed.

**A person holds several roles.** A senior associate is usually a reviewer *and* a user;
an administrator is nearly always a user too. Capabilities are the union of the roles
held, so holding more roles never takes anything away.

**The three roles, and the reasoning behind the line between them.**

- **user** — submits runs and reviews findings in the user app. No admin console.
- **reviewer** — everything in the console that is about *teaching and judging*:
  approving what the tool learned, the rule surfaces, worked examples, the review-load
  and usage figures, and the reference data a delivery's vocabulary needs. This is the
  senior associate who knows the programme.
- **admin** — all of that, plus what *defines the deployment*: delivery programmes,
  artifact types, meaning, accounts, settings, and the privacy controls.

The line is between **judging the work** and **defining the deployment**. A reviewer
decides whether a rule is right; an administrator decides what a programme is, who has
an account, and what the tool is allowed to send to a model. Those are different jobs
with different blast radii, and the second is a much smaller group.

**Masked columns sit on the admin side even though the rest of Reference data does
not.** Naming a column there is what keeps personal data out of every prompt (ADR-003).
It is the strongest control in the product and the one whose failure is least visible,
so it stays with the smaller group; aliases and field labels, which only help the tool
recognise a customer's vocabulary, do not.
"""

from __future__ import annotations

from enum import Enum
from typing import Final, Iterable

__all__ = [
    "Capability",
    "Role",
    "ROLES",
    "DEFAULT_ROLES",
    "capabilities_of",
    "has_capability",
    "normalize_roles",
    "describe",
    "holds",
]


class Role(str, Enum):
    """A named job. A person may hold more than one."""

    USER = "user"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class Capability(str, Enum):
    """One thing a person may do.

    Named for the act rather than the screen, because screens move and are renamed and
    the question a router needs answered does not change with them.
    """

    #: Open the admin console at all, and read what does not change anything: the
    #: dashboard, the usage figures, the review-load screen.
    VIEW_ADMIN = "view_admin"
    #: Approve, reject or withdraw what the tool learned from a person (ADR-021).
    APPROVE_TRAINING = "approve_training"
    #: Write and activate the surfaces that produce findings: checks, compliance
    #: rules, and the rule list itself.
    MANAGE_RULES = "manage_rules"
    #: Give the model worked examples and standing instructions through *Tell the tool*.
    TEACH_MODEL = "teach_model"
    #: Attribute aliases and field labels: what a delivery calls the things the tool
    #: already checks.
    MANAGE_REFERENCE = "manage_reference"
    #: Masked columns — what never reaches a prompt (ADR-003).
    MANAGE_PRIVACY = "manage_privacy"
    #: Artifact types, their samples, AI context and validation guides.
    MANAGE_ARTIFACTS = "manage_artifacts"
    #: Delivery programmes, their keywords, rules and standing instructions.
    MANAGE_PROGRAMMES = "manage_programmes"
    #: The mapping between requirements, configuration paths and report cells.
    MANAGE_MEANING = "manage_meaning"
    #: Create accounts and change what roles they hold.
    MANAGE_USERS = "manage_users"
    #: Runtime settings, including the ones that decide what the tool sends to a model.
    MANAGE_SETTINGS = "manage_settings"


#: What a reviewer may do: judge the work, and keep the vocabulary current.
_REVIEWER: Final[frozenset[Capability]] = frozenset(
    {
        Capability.VIEW_ADMIN,
        Capability.APPROVE_TRAINING,
        Capability.MANAGE_RULES,
        Capability.TEACH_MODEL,
        Capability.MANAGE_REFERENCE,
    }
)

#: What an administrator may do: everything a reviewer may, plus define the deployment.
_ADMIN: Final[frozenset[Capability]] = _REVIEWER | frozenset(
    {
        Capability.MANAGE_PRIVACY,
        Capability.MANAGE_ARTIFACTS,
        Capability.MANAGE_PROGRAMMES,
        Capability.MANAGE_MEANING,
        Capability.MANAGE_USERS,
        Capability.MANAGE_SETTINGS,
    }
)

#: Role to capability. A ``user`` has none of these: their work is the user app, which
#: is not gated by capability at all.
_GRANTS: Final[dict[Role, frozenset[Capability]]] = {
    Role.USER: frozenset(),
    Role.REVIEWER: _REVIEWER,
    Role.ADMIN: _ADMIN,
}

#: Every role, in the order a person should meet them: least to most.
ROLES: Final[tuple[str, ...]] = tuple(role.value for role in (Role.USER, Role.REVIEWER, Role.ADMIN))

#: What a new account holds when nobody says otherwise.
DEFAULT_ROLES: Final[tuple[str, ...]] = (Role.USER.value,)

#: What each role is for, in the words the console shows beside its checkbox.
_DESCRIPTIONS: Final[dict[str, str]] = {
    Role.USER.value: "Submits runs and reviews findings. No access to this console.",
    Role.REVIEWER.value: (
        "Everything here that is about judging the work: approving what the tool "
        "learned, the rule surfaces, worked examples, the figures, and reference data. "
        "Cannot change programmes, artifact types, meaning, accounts or settings."
    ),
    Role.ADMIN.value: "Everything, including what defines this deployment.",
}


def normalize_roles(roles: Iterable[str] | None) -> tuple[str, ...]:
    """Clean a set of role names into the canonical order, dropping what is not a role.

    Args:
        roles: Whatever was stored or submitted.

    Returns:
        The known roles, deduplicated, weakest first. Always at least ``user``: an
        account with no role at all cannot sign in to anything, which is a way to lock
        somebody out by saving a form with nothing ticked.
    """
    known = {role for role in (roles or ()) if role in ROLES}
    if not known:
        return DEFAULT_ROLES
    return tuple(role for role in ROLES if role in known)


def capabilities_of(roles: Iterable[str] | None) -> frozenset[Capability]:
    """Everything the holder of these roles may do.

    Args:
        roles: The roles held.

    Returns:
        The union of what each role grants. Holding more roles never grants less.
    """
    granted: set[Capability] = set()
    for name in normalize_roles(roles):
        granted |= _GRANTS[Role(name)]
    return frozenset(granted)


def has_capability(roles: Iterable[str] | None, capability: Capability) -> bool:
    """Whether the holder of these roles may do one thing.

    Args:
        roles: The roles held.
        capability: What is being attempted.

    Returns:
        True when any role held grants it.
    """
    return capability in capabilities_of(roles)


def describe(role: str) -> str:
    """What a role is for, for the console to show beside it.

    Args:
        role: The role name.

    Returns:
        One or two sentences, or the empty string for a name that is not a role.
    """
    return _DESCRIPTIONS.get(role, "")


def holds(roles: Iterable[str] | None, role: Role) -> bool:
    """Whether a stored role list includes one role.

    Args:
        roles: What the account holds.
        role: The role to look for.

    Returns:
        True when it is held.

    Asked in Python rather than in SQL on purpose. JSON membership is not portable
    across SQLite and Postgres (ADR-017) and the users table is small enough that
    reading it whole costs nothing, so *is there another administrator?* is answered
    over rows rather than by a dialect-specific predicate.
    """
    return role.value in normalize_roles(roles)
