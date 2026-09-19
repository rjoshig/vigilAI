"""A safe evaluator for admin-defined check expressions.

Admins write checks as expressions over named values ("billing_count <= delivered_count")
and the worker runs them on every request at no token cost (``docs/design.md``
"Configurable checks"). The expressions arrive from a database row, so they are
untrusted input: this evaluator walks a parsed AST and permits only comparison and
arithmetic over the names supplied. There is no ``eval`` and no attribute access, so an
expression cannot reach the interpreter, the filesystem, or the network.

A value that cannot be resolved produces a "could not evaluate" finding; it is never a
silent skip.
"""

from __future__ import annotations

import ast
import logging
import operator
from dataclasses import dataclass
from typing import Callable, Final, Mapping

__all__ = [
    "ExpressionError",
    "UnresolvedValue",
    "EvaluationResult",
    "evaluate",
    "referenced_names",
    "validate",
    "ALLOWED_FUNCTIONS",
]

_LOG: Final = logging.getLogger(__name__)

Number = float | int


class ExpressionError(Exception):
    """The expression is not one this evaluator will run.

    Raised for a syntax error or for any construct outside the permitted subset. The
    message names the construct so an admin can correct the check.
    """


class UnresolvedValue(Exception):
    """A named value the expression needs was not found in the reports.

    The caller turns this into a ``could_not_evaluate`` finding rather than skipping the
    check, so a check that silently stops running cannot go unnoticed.
    """

    def __init__(self, name: str) -> None:
        """Initialise the error.

        Args:
            name: The named value that could not be resolved.
        """
        super().__init__(f"named value {name!r} could not be resolved")
        self.name = name

    def __reduce__(self) -> tuple[type[UnresolvedValue], tuple[str]]:
        """Support pickling across the worker's process boundary.

        Returns:
            The callable and arguments needed to rebuild the error.
        """
        return (type(self), (self.name,))


#: Binary arithmetic the evaluator permits. Division is included because a check such as
#: "null rate below 5 percent" needs it; ``**`` is excluded because a large exponent is
#: a denial-of-service in one character.
_BINARY: Final[Mapping[type[ast.operator], Callable[[Number, Number], Number]]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

#: Comparisons the evaluator permits.
_COMPARE: Final[Mapping[type[ast.cmpop], Callable[..., bool]]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

#: Unary operators the evaluator permits.
_UNARY: Final[Mapping[type[ast.unaryop], Callable[[Number], Number]]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

#: Functions an expression may call. Deliberately tiny: each one is pure, total, and
#: cannot be made to consume unbounded time or memory.
ALLOWED_FUNCTIONS: Final[Mapping[str, Callable[..., object]]] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
}


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """The outcome of running one check expression.

    Attributes:
        passed: Whether the expression held.
        value: What the expression evaluated to, for the finding detail.
        resolved: The named values used, so a failing check can show its inputs.
    """

    passed: bool
    value: object
    resolved: Mapping[str, object]


def evaluate(expression: str, values: Mapping[str, object]) -> EvaluationResult:
    """Evaluate a check expression over named values.

    Args:
        expression: The admin-authored expression, e.g. ``"billing_count <= delivered"``.
        values: Named value to resolved value. A name mapped to ``None`` counts as
            unresolved, because a report cell that was not found is not a zero.

    Returns:
        The result, including the values actually used.

    Raises:
        ExpressionError: When the expression is malformed or uses a construct outside
            the permitted subset.
        UnresolvedValue: When the expression references a name that is missing or
            ``None``.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"expression is not valid Python: {exc.msg}") from exc

    used: dict[str, object] = {}
    result = _eval(tree.body, values, used)
    return EvaluationResult(passed=bool(result), value=result, resolved=used)


def referenced_names(expression: str) -> frozenset[str]:
    """Report the named values an expression needs.

    Used by the admin-ui to show which named values a draft check depends on, and by the
    worker to resolve only what a check actually uses.

    Args:
        expression: The expression.

    Returns:
        Every name referenced, excluding permitted function names.

    Raises:
        ExpressionError: When the expression is malformed.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"expression is not valid Python: {exc.msg}") from exc
    return frozenset(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id not in ALLOWED_FUNCTIONS
    )


def _eval(node: ast.AST, values: Mapping[str, object], used: dict[str, object]) -> object:
    """Evaluate one AST node.

    Args:
        node: The node.
        values: The named values available.
        used: Accumulates the names actually read.

    Returns:
        The node's value.

    Raises:
        ExpressionError: When the node is outside the permitted subset.
        UnresolvedValue: When a referenced name is missing or ``None``.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise ExpressionError(f"constants of type {type(node.value).__name__} are not allowed")

    if isinstance(node, ast.Name):
        if node.id not in values:
            raise UnresolvedValue(node.id)
        value = values[node.id]
        if value is None:
            raise UnresolvedValue(node.id)
        used[node.id] = value
        return value

    if isinstance(node, ast.BinOp):
        handler = _BINARY.get(type(node.op))
        if handler is None:
            raise ExpressionError(f"operator {type(node.op).__name__} is not allowed")
        numerator = _as_number(_eval(node.left, values, used))
        denominator = _as_number(_eval(node.right, values, used))
        if handler in (operator.truediv, operator.mod, operator.floordiv) and denominator == 0:
            raise ExpressionError("division by zero")
        return handler(numerator, denominator)

    if isinstance(node, ast.UnaryOp):
        unary = _UNARY.get(type(node.op))
        if unary is None:
            raise ExpressionError(f"operator {type(node.op).__name__} is not allowed")
        return unary(_as_number(_eval(node.operand, values, used)))

    if isinstance(node, ast.Compare):
        current: object = _eval(node.left, values, used)
        for op, comparator in zip(node.ops, node.comparators):
            compare = _COMPARE.get(type(op))
            if compare is None:
                raise ExpressionError(f"comparison {type(op).__name__} is not allowed")
            following: object = _eval(comparator, values, used)
            try:
                held = compare(current, following)
            except TypeError as exc:
                raise ExpressionError(
                    f"cannot compare {type(current).__name__} with {type(following).__name__}"
                ) from exc
            if not held:
                return False
            current = following
        return True

    if isinstance(node, ast.BoolOp):
        results = [bool(_eval(value, values, used)) for value in node.values]
        return all(results) if isinstance(node.op, ast.And) else any(results)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
            name = getattr(node.func, "id", type(node.func).__name__)
            raise ExpressionError(f"function {name!r} is not allowed")
        if node.keywords:
            raise ExpressionError("keyword arguments are not allowed")
        arguments = [_eval(argument, values, used) for argument in node.args]
        return ALLOWED_FUNCTIONS[node.func.id](*arguments)

    raise ExpressionError(f"{type(node).__name__} is not allowed in a check expression")


def _as_number(value: object) -> Number:
    """Coerce an operand to a number for arithmetic.

    Args:
        value: The operand.

    Returns:
        The number.

    Raises:
        ExpressionError: When the operand is not numeric. Arithmetic on a label read
            from a report cell is a check-authoring mistake, not a data problem.
    """
    if isinstance(value, bool):
        raise ExpressionError("arithmetic on a boolean is not allowed")
    if isinstance(value, (int, float)):
        return value
    raise ExpressionError(f"arithmetic needs a number, got {type(value).__name__}")


def validate(expression: str) -> frozenset[str]:
    """Check that an expression uses only the permitted subset, without running it.

    Saving a check must reject a dangerous expression there and then, rather than
    letting it sit in the database until a run tries to evaluate it. Parsing alone is
    not enough: ``__import__("os")`` is valid Python, so the node types have to be
    walked the same way :func:`evaluate` walks them.

    Args:
        expression: The admin-authored expression.

    Returns:
        The named values it references.

    Raises:
        ExpressionError: When the expression is malformed or uses a construct outside
            the permitted subset.
    """
    names = referenced_names(expression)
    # Evaluating against dummy values exercises the real walker, so validation and
    # execution can never disagree about what is allowed.
    try:
        evaluate(expression, dict.fromkeys(names, 1))
    except UnresolvedValue as exc:  # pragma: no cover - every name was just supplied
        raise ExpressionError(f"unknown value {exc.name!r}") from exc
    return names
