"""Safe arithmetic for model answers (WP-5).

The model is told to write ``{{calc: 120+135+150}}`` instead of doing sums
itself. Each expression is evaluated here with a whitelist AST walker:
numbers, + - * /, parentheses, unary minus and ``round`` only. No names,
attributes, calls other than ``round``, powers or comprehensions, so
``__import__('os')`` and similar are rejected, never executed.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any

CALC_RE = re.compile(r"\{\{\s*calc\s*:\s*([^{}]{1,200}?)\s*\}\}", re.I)
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")

_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


class CalcError(ValueError):
    """The expression is not allowed or cannot be evaluated."""


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        right = _eval(node.right)
        if isinstance(node.op, ast.Div) and right == 0:
            raise CalcError("division by zero")
        return _BIN_OPS[type(node.op)](_eval(node.left), right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "round"
        and not node.keywords
        and 1 <= len(node.args) <= 2
    ):
        args = [_eval(a) for a in node.args]
        digits = int(args[1]) if len(args) == 2 else 0
        return round(args[0], digits)
    raise CalcError(f"not allowed: {type(node).__name__}")


def safe_eval(expression: str) -> float:
    expr = _THOUSANDS_RE.sub("", expression.strip())
    if len(expr) > 200:
        raise CalcError("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise CalcError("invalid expression") from exc
    value = _eval(tree)
    if abs(value) > 1e15:
        raise CalcError("result out of range")
    return value


def format_number(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def apply_calcs(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Replace each ``{{calc: ...}}`` with ``result (= expression)``."""
    calculations: list[dict[str, Any]] = []

    def sub(match: re.Match[str]) -> str:
        expr = " ".join(match.group(1).split())
        try:
            result = format_number(safe_eval(expr))
        except CalcError as exc:
            calculations.append({"expr": expr, "result": None, "error": str(exc)})
            return "[calculation could not be evaluated]"
        calculations.append({"expr": expr, "result": result, "error": None})
        return f"{result} (= {expr})"

    return CALC_RE.sub(sub, text), calculations
