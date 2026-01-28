"""Test for django/django#12286: Model validation for empty unique fields.

Bug: full_clean() allows empty string for unique CharField with blank=False.
Fix: Add check for empty string on unique fields when blank=False.
SWECAS-500: Security & Validation
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from django_local.models import User, ValidationError, Model


def test_empty_unique_field_rejected():
    """Empty string for unique CharField(blank=False) should raise ValidationError."""
    Model.reset_registry()
    user = User(username="", email="test@test.com")
    try:
        user.full_clean()
        print("  FAIL: No error for empty unique username!")
        return False
    except ValidationError:
        print("  PASS: ValidationError raised for empty unique field")
        return True


def test_valid_user_passes():
    """Valid user data should pass validation."""
    Model.reset_registry()
    user = User(username="alice", email="alice@test.com")
    try:
        user.full_clean()
        print("  PASS: Valid user passes validation")
        return True
    except ValidationError as e:
        print(f"  FAIL: Valid user rejected: {e}")
        return False


def test_none_required_field_rejected():
    """None for required field should raise ValidationError."""
    Model.reset_registry()
    user = User(username=None, email="test@test.com")
    try:
        user.full_clean()
        print("  FAIL: No error for None required field!")
        return False
    except ValidationError:
        print("  PASS: ValidationError raised for None required field")
        return True


if __name__ == '__main__':
    print("=== SWE-bench Task: django__django-12286 ===")
    print("Model validation: empty unique fields\n")

    results = []

    print("Test 1: Valid user")
    results.append(test_valid_user_passes())

    print("\nTest 2: Empty unique field (should reject)")
    results.append(test_empty_unique_field_rejected())

    print("\nTest 3: None required field (should reject)")
    results.append(test_none_required_field_rejected())

    passed = sum(results)
    total = len(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} tests passed")
    if all(results):
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
