"""Test for pallets/flask#4045: Blueprint name with dot should raise error.

Bug: Blueprint names with dots are allowed, but dots are now significant
for nested blueprints. Names like "myapp.frontend" break the nesting system.

Fix:
1. Raise ValueError in Blueprint.__init__ if name contains a dot
2. Change asserts in add_url_rule to raise ValueError instead
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from flask.blueprints import Blueprint
import pytest


def test_dotted_name_not_allowed():
    """Blueprint name with dot should raise ValueError."""
    try:
        bp = Blueprint("app.ui", __name__)
        print("  FAIL: No error raised for dotted blueprint name!")
        return False
    except ValueError as e:
        print(f"  PASS: ValueError raised: {e}")
        return True
    except Exception as e:
        print(f"  FAIL: Wrong exception type: {type(e).__name__}: {e}")
        return False


def test_endpoint_with_dots():
    """Endpoint with dot should raise ValueError (not AssertionError)."""
    bp = Blueprint("bp", __name__)
    try:
        bp.add_url_rule("/", endpoint="a.b")
        print("  FAIL: No error raised for dotted endpoint!")
        return False
    except ValueError as e:
        print(f"  PASS: ValueError raised: {e}")
        return True
    except AssertionError:
        print("  FAIL: AssertionError instead of ValueError!")
        return False


def test_view_func_name_with_dots():
    """View function with dotted name should raise ValueError."""
    bp = Blueprint("bp", __name__)

    def view():
        return ""
    view.__name__ = "a.b"

    try:
        bp.add_url_rule("/", view_func=view)
        print("  FAIL: No error raised for dotted view func name!")
        return False
    except ValueError as e:
        print(f"  PASS: ValueError raised: {e}")
        return True
    except AssertionError:
        print("  FAIL: AssertionError instead of ValueError!")
        return False


def test_normal_blueprint_works():
    """Normal blueprint without dots should work fine."""
    try:
        bp = Blueprint("admin", __name__)
        bp.add_url_rule("/", endpoint="index", view_func=lambda: "")
        print("  PASS: Normal blueprint works")
        return True
    except Exception as e:
        print(f"  FAIL: Unexpected error: {e}")
        return False


if __name__ == '__main__':
    print("=== SWE-bench Task: pallets__flask-4045 ===")
    print("Raise error when blueprint name contains a dot\n")

    results = []

    print("Test 1: Normal blueprint (should work)")
    results.append(test_normal_blueprint_works())

    print("\nTest 2: Dotted blueprint name (should raise ValueError)")
    results.append(test_dotted_name_not_allowed())

    print("\nTest 3: Dotted endpoint (should raise ValueError, not AssertionError)")
    results.append(test_endpoint_with_dots())

    print("\nTest 4: Dotted view func name (should raise ValueError)")
    results.append(test_view_func_name_with_dots())

    passed = sum(results)
    total = len(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} tests passed")

    if all(results):
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
