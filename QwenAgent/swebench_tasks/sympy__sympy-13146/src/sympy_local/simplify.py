"""Simplified SymPy expression simplification for SWE-bench task.

Bug: simplify() does not handle double negation correctly.
simplify(--x) returns --x instead of x.
SWECAS-600: Logic & Control Flow
"""


class Expr:
    """Base expression class."""
    pass


class Symbol(Expr):
    def __init__(self, name):
        self.name = name

    def __neg__(self):
        return Neg(self)

    def __eq__(self, other):
        return isinstance(other, Symbol) and self.name == other.name

    def __repr__(self):
        return self.name


class Neg(Expr):
    """Negation: -expr"""
    def __init__(self, operand):
        self.operand = operand

    def __neg__(self):
        return Neg(self)

    def __eq__(self, other):
        return isinstance(other, Neg) and self.operand == other.operand

    def __repr__(self):
        return f"-{self.operand}"


class Add(Expr):
    """Addition: left + right"""
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def __eq__(self, other):
        return (isinstance(other, Add)
                and self.left == other.left
                and self.right == other.right)

    def __repr__(self):
        return f"({self.left} + {self.right})"


def simplify(expr):
    """Simplify an expression.

    BUG: Does not handle double negation.
    simplify(Neg(Neg(x))) should return x, but returns Neg(Neg(x)).
    """
    if isinstance(expr, Add):
        left = simplify(expr.left)
        right = simplify(expr.right)
        # Simplify x + 0 -> x (if we had a Zero type)
        return Add(left, right)

    if isinstance(expr, Neg):
        inner = simplify(expr.operand)
        # BUG: missing double negation simplification
        # Should be: if isinstance(inner, Neg): return inner.operand
        return Neg(inner)

    return expr
