"""Test for django/django#11099: QuerySet.exclude() with None value.

Bug: exclude(field=None) uses == instead of `is` for None comparison,
which can produce incorrect results with objects that override __eq__.

Fix: Use `item.get(key) is value` when value is None in exclude().
SWECAS-600: Logic & Control Flow
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from django_local.queryset import QuerySet


def test_exclude_none_value():
    """Excluding None should use identity check (is), not equality (==)."""
    data = [
        {"id": 1, "name": "Alice", "email": "alice@test.com"},
        {"id": 2, "name": "Bob", "email": None},
        {"id": 3, "name": "Charlie", "email": "charlie@test.com"},
    ]
    qs = QuerySet(data)
    result = qs.exclude(email=None)
    assert result.count() == 2, f"Expected 2 items after excluding email=None, got {result.count()}"
    names = result.values_list("name", flat=True)
    assert "Bob" not in names, "Bob (email=None) should be excluded"
    print("  PASS: exclude(email=None) correctly removes None entries")
    return True


def test_exclude_non_none():
    """Excluding a concrete value should work normally."""
    data = [
        {"id": 1, "status": "active"},
        {"id": 2, "status": "inactive"},
        {"id": 3, "status": "active"},
    ]
    qs = QuerySet(data)
    result = qs.exclude(status="inactive")
    assert result.count() == 2, f"Expected 2, got {result.count()}"
    print("  PASS: exclude(status='inactive') works correctly")
    return True


def test_filter_isnull():
    """Filter with __isnull lookup should work."""
    data = [
        {"id": 1, "email": "a@b.com"},
        {"id": 2, "email": None},
    ]
    qs = QuerySet(data)
    result = qs.filter(email__isnull=True)
    assert result.count() == 1, f"Expected 1, got {result.count()}"
    print("  PASS: filter(email__isnull=True) works")
    return True


if __name__ == '__main__':
    print("=== SWE-bench Task: django__django-11099 ===")
    print("QuerySet.exclude() with None value\n")

    results = []

    print("Test 1: exclude(email=None)")
    results.append(test_exclude_none_value())

    print("\nTest 2: exclude non-None value")
    results.append(test_exclude_non_none())

    print("\nTest 3: filter with __isnull")
    results.append(test_filter_isnull())

    passed = sum(results)
    total = len(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} tests passed")
    if all(results):
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
