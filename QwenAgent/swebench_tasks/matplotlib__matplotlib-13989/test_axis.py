"""Test for matplotlib/matplotlib#13989: Axis limits not auto-swapped.

Bug: set_xlim(10, 0) stores (10, 0) instead of (0, 10) with inverted flag.
Fix: Auto-swap left/right when left > right, set inverted flag.
SWECAS-700: Config & Environment
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from mpl_local.axis import Axis


def test_normal_xlim():
    """set_xlim(0, 10) should work normally."""
    ax = Axis()
    ax.set_xlim(0, 10)
    assert ax.get_xlim() == (0.0, 10.0)
    print("  PASS: set_xlim(0, 10) works")
    return True


def test_inverted_xlim():
    """set_xlim(10, 0) should auto-swap to (0, 10)."""
    ax = Axis()
    ax.set_xlim(10, 0)
    xlim = ax.get_xlim()
    assert xlim[0] <= xlim[1], \
        f"Expected left <= right, got xlim={xlim}"
    print(f"  PASS: set_xlim(10, 0) -> {xlim} (ordered)")
    return True


def test_ylim_already_correct():
    """set_ylim already handles inverted (reference implementation)."""
    ax = Axis()
    ax.set_ylim(10, 0)
    ylim = ax.get_ylim()
    assert ylim[0] <= ylim[1], f"ylim should be ordered: {ylim}"
    assert ax.is_inverted(), "Should be marked as inverted"
    print("  PASS: set_ylim(10, 0) auto-swaps correctly")
    return True


if __name__ == '__main__':
    print("=== SWE-bench Task: matplotlib__matplotlib-13989 ===")
    print("Axis limits auto-swap\n")

    results = []
    print("Test 1: Normal xlim")
    results.append(test_normal_xlim())
    print("\nTest 2: Inverted xlim (should auto-swap)")
    results.append(test_inverted_xlim())
    print("\nTest 3: ylim already correct (reference)")
    results.append(test_ylim_already_correct())

    passed = sum(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{len(results)} tests passed")
    if all(results): print("ALL TESTS PASSED!")
    else: print("SOME TESTS FAILED"); sys.exit(1)
