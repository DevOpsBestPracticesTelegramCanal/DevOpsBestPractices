"""Test for sympy/sympy#13480: Implicit multiplication parsing.

Bug: parse_expr('2x') raises TypeError instead of returning Mul(2, x).
Fix: Tokenizer should split '2x' into ['2', '*', 'x'].
SWECAS-300: Type & Interface
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from sympy_local.parser import parse_expr, Number, Symbol, Mul


def test_explicit_multiplication():
    """'2 * x' should parse correctly."""
    result = parse_expr("2 * x")
    assert isinstance(result, Mul), f"Expected Mul, got {type(result).__name__}"
    assert result.left == Number("2")
    assert result.right == Symbol("x")
    print("  PASS: '2 * x' parsed correctly")
    return True


def test_implicit_multiplication():
    """'2x' should parse as Mul(2, x) via implicit multiplication."""
    try:
        result = parse_expr("2x")
    except (TypeError, ValueError) as e:
        print(f"  FAIL: parse_expr('2x') raised {type(e).__name__}: {e}")
        return False

    assert isinstance(result, Mul), f"Expected Mul, got {type(result).__name__}"
    assert result.left == Number("2"), f"Left should be Number(2), got {result.left!r}"
    assert result.right == Symbol("x"), f"Right should be Symbol(x), got {result.right!r}"
    print("  PASS: '2x' parsed as implicit multiplication")
    return True


def test_plain_number():
    """'42' should parse as Number(42)."""
    result = parse_expr("42")
    assert isinstance(result, Number) and result.value == 42
    print("  PASS: '42' parsed as Number")
    return True


def test_plain_symbol():
    """'x' should parse as Symbol('x')."""
    result = parse_expr("x")
    assert isinstance(result, Symbol) and result.name == "x"
    print("  PASS: 'x' parsed as Symbol")
    return True


if __name__ == '__main__':
    print("=== SWE-bench Task: sympy__sympy-13480 ===")
    print("Implicit multiplication parsing\n")

    results = []
    print("Test 1: Explicit multiplication '2 * x'")
    results.append(test_explicit_multiplication())
    print("\nTest 2: Implicit multiplication '2x'")
    results.append(test_implicit_multiplication())
    print("\nTest 3: Plain number '42'")
    results.append(test_plain_number())
    print("\nTest 4: Plain symbol 'x'")
    results.append(test_plain_symbol())

    passed = sum(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{len(results)} tests passed")
    if all(results): print("ALL TESTS PASSED!")
    else: print("SOME TESTS FAILED"); sys.exit(1)
