# -*- coding: utf-8 -*-
"""
SWECAS classifier accuracy tests — 3 tests per category (9 x 3 = 27).

Each test presents a bug description + optional code snippet and asserts
the classifier returns the correct SWECAS category.

Run: python -m pytest tests/test_classifier_accuracy.py -v
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.swecas_classifier import SWECASClassifier


@pytest.fixture
def clf():
    return SWECASClassifier()


# =====================================================================
# SWECAS-100: Null/None & Value Errors  (3 tests)
# =====================================================================

class TestSWECAS100:
    def test_none_attribute_access(self, clf):
        """None check before .attr"""
        r = clf.classify("AttributeError: NoneType has no attribute 'name'. "
                          "Object was None when accessed.")
        assert r["swecas_code"] == 100

    def test_mutable_default_arg(self, clf):
        """Mutable default argument leads to None/unexpected value"""
        r = clf.classify(
            "Function returns None unexpectedly. Missing value, variable not set.",
            file_content="def append(item, lst=None):\n    if lst is None:\n        lst = []\n"
        )
        assert r["swecas_code"] == 100

    def test_uninitialized_optional(self, clf):
        """Optional parameter not initialized, null pointer style"""
        r = clf.classify("Variable is None, optional field uninitialized, "
                          "null pointer when calling method on undefined attribute")
        assert r["swecas_code"] == 100


# =====================================================================
# SWECAS-200: Import & Module / Dependency  (3 tests)
# =====================================================================

class TestSWECAS200:
    def test_circular_import(self, clf):
        """Circular import between modules"""
        r = clf.classify("ImportError: cannot import name 'X' from partially "
                          "initialized module. Circular dependency between modules.")
        assert r["swecas_code"] == 200

    def test_missing_optional_dep(self, clf):
        """Missing optional dependency"""
        r = clf.classify("ModuleNotFoundError: No module named 'pandas'. "
                          "Package not installed. Import dependency missing.")
        assert r["swecas_code"] == 200

    def test_wrong_module_path(self, clf):
        """Wrong relative import path"""
        r = clf.classify("ImportError: attempted relative import beyond top-level "
                          "package. Cannot import from __init__.")
        assert r["swecas_code"] == 200


# =====================================================================
# SWECAS-300: Type & Interface  (3 tests)
# =====================================================================

class TestSWECAS300:
    def test_wrong_return_type(self, clf):
        """Function returns wrong type"""
        r = clf.classify("TypeError: expected str, got int. Return type mismatch "
                          "in function signature. Type annotation violation.")
        assert r["swecas_code"] == 300

    def test_missing_argument(self, clf):
        """Missing required argument — signature mismatch"""
        r = clf.classify("TypeError: func() missing 1 required positional argument. "
                          "Function signature incompatible with caller.")
        assert r["swecas_code"] == 300

    def test_str_bytes_confusion(self, clf):
        """str/bytes confusion in I/O"""
        r = clf.classify("TypeError: a bytes-like object is required, not 'str'. "
                          "Cannot cast str to bytes implicitly.")
        assert r["swecas_code"] == 300


# =====================================================================
# SWECAS-400: API Usage & Deprecation  (3 tests)
# =====================================================================

class TestSWECAS400:
    def test_deprecated_method(self, clf):
        """Deprecated API method"""
        r = clf.classify("DeprecationWarning: method deprecated since version 3.0, "
                          "use new_func instead. Legacy API removed in next release.")
        assert r["swecas_code"] == 400

    def test_version_specific_behavior(self, clf):
        """Version-specific API behavior change"""
        r = clf.classify("API behavior changed in version 2.0. Breaking change in "
                          "backward compatibility. Use updated method instead.")
        assert r["swecas_code"] == 400

    def test_renamed_parameter(self, clf):
        """Renamed API parameter"""
        r = clf.classify("API parameter deprecated and renamed. Old parameter "
                          "removed in this version. Use new_param instead of legacy old_param.")
        assert r["swecas_code"] == 400


# =====================================================================
# SWECAS-500: Security & Validation  (3 tests)
# =====================================================================

class TestSWECAS500:
    def test_missing_input_validation(self, clf):
        """Missing input validation with assert"""
        r = clf.classify(
            "Input not validated. Should raise ValueError for invalid input. "
            "Assert statement used for validation check.",
            file_content="assert name.isalpha(), 'Invalid name'\nself.name = name\n"
        )
        assert r["swecas_code"] == 500

    def test_should_raise_error(self, clf):
        """Should raise proper error on bad input"""
        r = clf.classify("Function accepts invalid values without checking. "
                          "Must raise ValueError to validate and verify input. "
                          "Sanitize user data before use.")
        assert r["swecas_code"] == 500

    def test_hardcoded_validation(self, clf):
        """Validation logic with explicit checks"""
        r = clf.classify(
            "Need to validate input name does not contain invalid characters. "
            "Should raise ValueError if check fails.",
            file_content="if not valid:\n    raise ValueError('invalid value')\n"
        )
        assert r["swecas_code"] == 500


# =====================================================================
# SWECAS-600: Logic & Control Flow  (3 tests)
# =====================================================================

class TestSWECAS600:
    def test_wrong_predicate(self, clf):
        """Wrong condition in boolean predicate"""
        r = clf.classify("Logic error: wrong condition in if/else statement. "
                          "Incorrect result from algorithm. Control flow bug.")
        assert r["swecas_code"] == 600

    def test_missing_break(self, clf):
        """Missing break in loop — off-by-one behavior"""
        r = clf.classify("Off-by-one error in loop. Wrong behavior due to "
                          "missing loop termination. Incorrect predicate logic.")
        assert r["swecas_code"] == 600

    def test_swallowed_exception(self, clf):
        """Broad except swallows real errors"""
        r = clf.classify(
            "Exception silently swallowed. Wrong branch taken due to "
            "broad except clause hiding the actual logic error.",
            file_content="try:\n    result()\nexcept:\n    pass  # swallowed\n"
        )
        assert r["swecas_code"] == 600


# =====================================================================
# SWECAS-700: Config & Environment  (3 tests)
# =====================================================================

class TestSWECAS700:
    def test_wrong_path(self, clf):
        """Wrong configuration path"""
        r = clf.classify("Configuration error: path does not exist. "
                          "Wrong working directory in settings. "
                          "Config file not found at configured path.")
        assert r["swecas_code"] == 700

    def test_missing_env_var(self, clf):
        """Missing environment variable"""
        r = clf.classify("Environment variable ENV not set. Configuration "
                          "requires env var for path. Settings missing.")
        assert r["swecas_code"] == 700

    def test_bad_fixture_cleanup(self, clf):
        """Test fixture pollution"""
        r = clf.classify("Test fails due to environment pollution from previous "
                          "fixture. Framework setting leaked between test cases. "
                          "Configuration not cleaned up.")
        assert r["swecas_code"] == 700


# =====================================================================
# SWECAS-800: Performance & Resource  (3 tests)
# =====================================================================

class TestSWECAS800:
    def test_n_plus_1_query(self, clf):
        """N+1 query performance issue"""
        r = clf.classify("Performance issue: N+1 query pattern. Slow database "
                          "access. Need to optimize with eager loading.")
        assert r["swecas_code"] == 800

    def test_quadratic_loop(self, clf):
        """O(n^2) quadratic loop"""
        r = clf.classify("Slow performance due to quadratic nested loop. "
                          "Memory usage too high. Need to optimize algorithm.")
        assert r["swecas_code"] == 800

    def test_memory_leak(self, clf):
        """Memory leak from circular references"""
        r = clf.classify("Memory leak detected. Resource not released. "
                          "Cache growing unbounded. Performance degradation.")
        assert r["swecas_code"] == 800


# =====================================================================
# SWECAS-900: Async, Concurrency & I/O  (3 tests)
# =====================================================================

class TestSWECAS900:
    def test_missing_await(self, clf):
        """Missing await on coroutine"""
        r = clf.classify("RuntimeWarning: coroutine was never awaited. "
                          "Missing async await call. Coroutine not executed.")
        assert r["swecas_code"] == 900

    def test_race_condition(self, clf):
        """Race condition in concurrent code"""
        r = clf.classify("Race condition: concurrent threads modify shared state. "
                          "Threading lock missing. Deadlock possible.")
        assert r["swecas_code"] == 900

    def test_deadlock_pattern(self, clf):
        """Deadlock from lock ordering"""
        r = clf.classify("Deadlock detected: two threads waiting on each other's "
                          "lock. Synchronization issue in concurrent I/O. "
                          "Async task blocked.")
        assert r["swecas_code"] == 900
