"""Simplified expression parser for SWE-bench task.

Bug: parse_expr() doesn't handle implicit multiplication: '2x' should parse
as Mul(2, Symbol('x')), but raises TypeError because int * Symbol is not handled.
SWECAS-300: Type & Interface
"""
import re


class Expr:
    pass


class Number(Expr):
    def __init__(self, value):
        self.value = int(value)

    def __eq__(self, other):
        return isinstance(other, Number) and self.value == other.value

    def __repr__(self):
        return str(self.value)


class Symbol(Expr):
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Symbol) and self.name == other.name

    def __repr__(self):
        return self.name


class Mul(Expr):
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def __eq__(self, other):
        return (isinstance(other, Mul)
                and self.left == other.left
                and self.right == other.right)

    def __repr__(self):
        return f"({self.left}*{self.right})"


def parse_expr(text):
    """Parse a mathematical expression string.

    BUG: Does not handle implicit multiplication like '2x'.
    Token '2x' is treated as a single unknown token and raises TypeError.
    Should split into Number(2) * Symbol('x').
    """
    text = text.strip()
    tokens = _tokenize(text)
    if len(tokens) == 1:
        return _parse_token(tokens[0])
    # Only handles explicit * for now
    if len(tokens) == 3 and tokens[1] == '*':
        left = _parse_token(tokens[0])
        right = _parse_token(tokens[2])
        return Mul(left, right)

    raise ValueError(f"Cannot parse: {text}")


def _tokenize(text):
    """Split expression into tokens.

    BUG: Does not split '2x' into ['2', '*', 'x'].
    Treats '2x' as single token.
    """
    tokens = re.findall(r'[a-zA-Z]+|\d+|[*+\-/()]', text)
    return tokens


def _parse_token(token):
    """Parse a single token into Number or Symbol."""
    if token.isdigit():
        return Number(token)
    if token.isalpha():
        return Symbol(token)
    raise TypeError(f"Unknown token type: {token!r}")
