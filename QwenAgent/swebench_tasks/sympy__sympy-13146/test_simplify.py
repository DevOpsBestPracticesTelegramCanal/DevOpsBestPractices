"""Test for sympy/sympy#13146: Double negation simplification.

Bug: simplify(--x) returns --x instead of x.
Fix: Add double negation rule: Neg(Neg(x)) -> x.
SWECAS-600: Logic & Control Flow
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from sympy_local.simplify import Symbol, Neg, Add, simplify


def test_double_negation():
    """--x should simplify to x."""
    x = Symbol("x")
    expr = Neg(Neg(x))
    result = simplify(expr)
    assert isinstance(result, Symbol) and result.name == "x", \
        f"Expected Symbol('x'), got {result!r}"
    print("  PASS: --x simplifies to x")
    return True


def test_single_negation_preserved():
    """-x should remain -x."""
    x = Symbol("x")
    expr = Neg(x)
    result = simplify(expr)
    assert isinstance(result, Neg), f"Expected Neg, got {type(result).__name__}"
    print("  PASS: -x remains -x")
    return True


def test_triple_negation():
    """---x should simplify to -x."""
    x = Symbol("x")
    expr = Neg(Neg(Neg(x)))
    result = simplify(expr)
    assert isinstance(result, Neg) and isinstance(result.operand, Symbol), \
        f"Expected -x, got {result!r}"
    print("  PASS: ---x simplifies to -x")
    return True


def test_add_simplification():
    """Addition is recursively simplified."""
    x = Symbol("x")
    expr = Add(Neg(Neg(x)), x)
    result = simplify(expr)
    assert isinstance(result, Add), f"Expected Add, got {type(result).__name__}"
    assert isinstance(result.left, Symbol), f"Left should be Symbol, got {type(result.left).__name__}"
    print("  PASS: (--x + x) simplifies left side")
    return True


if __name__ == '__main__':
    print("=== SWE-bench Task: sympy__sympy-13146 ===")
    print("Double negation simplification\n")

    results = []
    print("Test 1: Double negation --x -> x")
    results.append(test_double_negation())
    print("\nTest 2: Single negation preserved")
    results.append(test_single_negation_preserved())
    print("\nTest 3: Triple negation ---x -> -x")
    results.append(test_triple_negation())
    print("\nTest 4: Add with double negation")
    results.append(test_add_simplification())

    passed = sum(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{len(results)} tests passed")
    if all(results): print("ALL TESTS PASSED!")
    else: print("SOME TESTS FAILED"); sys.exit(1)
