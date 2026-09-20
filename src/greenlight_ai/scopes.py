"""Where a definition applies, said one way (Phase 6.12a).

A check, a compliance rule, a field constraint and a learned rule all carry a scope,
and until now each reader interpreted the string itself: one compared it to ``"all"``,
another looked for a ``programme:`` prefix, a third listed the forms it happened to
know. Four shapes were stored and three of them were only ever recognised in some of
the places they could appear, which is the kind of near-miss that silently runs a rule
on the wrong delivery.

So there is one module, and it is the only thing in the product that interprets a scope
string. It parses every form that has ever been stored, renders the canonical one, and
answers the only question anyone actually asks: does this scope cover this run.

The canonical token is ``everywhere``, ``programme:CODE``, ``customer:NAME`` or
``config:ID``. The older forms — a bare ``all`` and a bare customer name — still parse,
and always will: a stored row, an administrator's bookmark and an in-flight request are
not reasons to break anything. Nothing rewrites the stored columns (ADR-037); a row
becomes canonical the next time somebody saves it, and until then it reads the same.

``config:ID`` is the fourth shape and it is not a delivery programme: a note written
against one configuration applies to that configuration and no other (ADR-024).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "EVERYWHERE",
    "PROGRAMME_PREFIX",
    "CUSTOMER_PREFIX",
    "CONFIG_PREFIX",
    "Scope",
    "ScopeKind",
    "covers",
    "everywhere",
    "for_configuration",
    "for_customer",
    "for_programme",
    "label",
    "parse",
    "token",
]

ScopeKind = Literal["everywhere", "programme", "customer", "configuration"]

#: The canonical token for a scope that covers every run.
EVERYWHERE: Final[str] = "everywhere"

#: The form still stored on rows written before the vocabulary was unified.
_LEGACY_EVERYWHERE: Final[frozenset[str]] = frozenset({"", "all", EVERYWHERE})

PROGRAMME_PREFIX: Final[str] = "programme:"
CUSTOMER_PREFIX: Final[str] = "customer:"
CONFIG_PREFIX: Final[str] = "config:"

#: Both spellings of the configuration prefix, so a hand-written token still parses.
_CONFIG_PREFIXES: Final[tuple[str, ...]] = (CONFIG_PREFIX, "configuration:")


@dataclass(frozen=True, slots=True)
class Scope:
    """Where one definition applies.

    Attributes:
        kind: ``everywhere``, ``programme``, ``customer`` or ``configuration``.
        value: The programme code, the customer name or the configuration id. Empty
            for ``everywhere``. A programme code is held upper-cased, because a code is
            an identifier; a customer name is held exactly as it was entered, because a
            name is not.
    """

    kind: ScopeKind = "everywhere"
    value: str = ""

    @property
    def token(self) -> str:
        """The canonical token, which is what the API returns and a console shows.

        Returns:
            ``everywhere``, ``programme:CODE``, ``customer:NAME`` or ``config:ID``.
        """
        if self.kind == "everywhere":
            return EVERYWHERE
        if self.kind == "programme":
            return f"{PROGRAMME_PREFIX}{self.value}"
        if self.kind == "configuration":
            return f"{CONFIG_PREFIX}{self.value}"
        return f"{CUSTOMER_PREFIX}{self.value}"

    def covers(
        self,
        customer: str = "",
        programme_code: str = "",
        configuration_id: str = "",
    ) -> bool:
        """Whether this scope covers a run.

        Args:
            customer: The run's customer name.
            programme_code: The run's delivery programme code, when it has one.
            configuration_id: The run's configuration id, when it has one.

        Returns:
            ``True`` when the scope is everywhere, or names this run's programme,
            customer or configuration. A programme scope never covers another
            programme and never covers a run with no programme; the same holds for a
            customer and for a configuration. A scope that names nothing covers
            nothing, so a half-written row cannot quietly become a global rule.
        """
        if self.kind == "everywhere":
            return True
        if not self.value:
            return False
        if self.kind == "programme":
            return self.value == programme_code.strip().upper()
        if self.kind == "configuration":
            return self.value == configuration_id.strip()
        return self.value == customer.strip()

    def label(self, programme_label: str = "") -> str:
        """How this scope reads on a screen.

        Args:
            programme_label: The programme's display name, when the caller has it.

        Returns:
            A phrase a person can read, never a raw token.
        """
        if self.kind == "everywhere":
            return "Everywhere"
        if self.kind == "programme":
            return f"Programme · {programme_label or self.value}"
        if self.kind == "configuration":
            return f"Configuration · {self.value}"
        return f"Customer · {self.value}"


def parse(raw: str | None) -> Scope:
    """Read any stored or submitted scope string.

    Args:
        raw: The scope as stored or as submitted. ``None`` and the empty string mean
            everywhere, because that is what an unset column has always meant.

    Returns:
        The scope it denotes. An unprefixed string that is not ``all`` is a customer
        name, which is the form every row written before Phase 6.12 uses.
    """
    text = (raw or "").strip()
    if text.lower() in _LEGACY_EVERYWHERE:
        return Scope("everywhere")
    lowered = text.lower()
    if lowered.startswith(PROGRAMME_PREFIX):
        return Scope("programme", text[len(PROGRAMME_PREFIX) :].strip().upper())
    for prefix in _CONFIG_PREFIXES:
        if lowered.startswith(prefix):
            return Scope("configuration", text[len(prefix) :].strip())
    if lowered.startswith(CUSTOMER_PREFIX):
        return Scope("customer", text[len(CUSTOMER_PREFIX) :].strip())
    return Scope("customer", text)


def token(raw: str | None) -> str:
    """Canonicalise a scope string.

    Args:
        raw: Any stored or submitted form.

    Returns:
        The canonical token for the same scope.
    """
    return parse(raw).token


def label(raw: str | None, programme_label: str = "") -> str:
    """How a stored scope reads on a screen.

    Args:
        raw: Any stored or submitted form.
        programme_label: The programme's display name, when the caller has it.

    Returns:
        A phrase a person can read.
    """
    return parse(raw).label(programme_label)


def covers(
    raw: str | None,
    customer: str = "",
    programme_code: str = "",
    configuration_id: str = "",
) -> bool:
    """Whether a stored scope covers a run.

    Args:
        raw: Any stored or submitted form.
        customer: The run's customer name.
        programme_code: The run's delivery programme code.
        configuration_id: The run's configuration id.

    Returns:
        ``True`` when the scope covers the run.
    """
    return parse(raw).covers(customer, programme_code, configuration_id)


def everywhere() -> Scope:
    """The scope that covers every run.

    Returns:
        The everywhere scope.
    """
    return Scope("everywhere")


def for_programme(code: str) -> Scope:
    """The scope covering one delivery programme.

    Args:
        code: The programme code.

    Returns:
        The programme scope, with the code upper-cased.
    """
    return Scope("programme", code.strip().upper())


def for_customer(name: str) -> Scope:
    """The scope covering one customer.

    Args:
        name: The customer name, exactly as it is entered on runs.

    Returns:
        The customer scope.
    """
    return Scope("customer", name.strip())


def for_configuration(configuration_id: str) -> Scope:
    """The scope covering one configuration (ADR-024).

    Args:
        configuration_id: The configuration id.

    Returns:
        The configuration scope.
    """
    return Scope("configuration", configuration_id.strip())
