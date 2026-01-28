"""Test for cpython/cpython#9267: OrderedDict.move_to_end() missing KeyError.

Bug: move_to_end() silently does nothing for missing keys instead of raising KeyError.
Fix: Add `if key not in self._data: raise KeyError(key)` at start.
SWECAS-100: Null/None & Value Errors
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from cpython_local.collections_utils import OrderedDict


def test_move_to_end_existing():
    """Moving existing key to end should reorder correctly."""
    od = OrderedDict([("a", 1), ("b", 2), ("c", 3)])
    od.move_to_end("a")
    assert od.keys() == ["b", "c", "a"], f"Expected ['b', 'c', 'a'], got {od.keys()}"
    print("  PASS: move_to_end('a') reorders correctly")
    return True


def test_move_to_beginning():
    """Moving existing key to beginning."""
    od = OrderedDict([("a", 1), ("b", 2), ("c", 3)])
    od.move_to_end("c", last=False)
    assert od.keys() == ["c", "a", "b"], f"Expected ['c', 'a', 'b'], got {od.keys()}"
    print("  PASS: move_to_end('c', last=False) works")
    return True


def test_move_missing_key_raises():
    """Moving a missing key should raise KeyError, not silently pass."""
    od = OrderedDict([("a", 1), ("b", 2)])
    try:
        od.move_to_end("z")
        print("  FAIL: No KeyError for missing key 'z'!")
        return False
    except KeyError:
        print("  PASS: KeyError raised for missing key")
        return True


if __name__ == '__main__':
    print("=== SWE-bench Task: cpython__cpython-9267 ===")
    print("OrderedDict.move_to_end() missing KeyError\n")

    results = []
    print("Test 1: Move existing key to end")
    results.append(test_move_to_end_existing())
    print("\nTest 2: Move to beginning")
    results.append(test_move_to_beginning())
    print("\nTest 3: Missing key should raise KeyError")
    results.append(test_move_missing_key_raises())

    passed = sum(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{len(results)} tests passed")
    if all(results): print("ALL TESTS PASSED!")
    else: print("SOME TESTS FAILED"); sys.exit(1)
