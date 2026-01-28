"""Test for pytest-dev/pytest#5103: Fixture teardown order.

Bug: Fixtures tear down in registration order (FIFO) instead of
reverse scope order. Function-scope should tear down first, session last.
Fix: Sort teardown by scope in reverse order (function -> session).
SWECAS-900: Async, Concurrency & I/O (temporal ordering)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from pytest_local.fixtures import FixtureManager


def test_teardown_order():
    """Fixtures should tear down in reverse scope order."""
    fm = FixtureManager()
    teardown_log = []

    fm.register("db_session", scope="session",
                setup_fn=lambda: "DB",
                teardown_fn=lambda: teardown_log.append("session"))
    fm.register("db_module", scope="module",
                setup_fn=lambda: "MOD",
                teardown_fn=lambda: teardown_log.append("module"))
    fm.register("db_function", scope="function",
                setup_fn=lambda: "FUNC",
                teardown_fn=lambda: teardown_log.append("function"))

    # Setup in order: session, module, function
    fm.setup("db_session")
    fm.setup("db_module")
    fm.setup("db_function")

    # Teardown
    fm.teardown_all()

    # Expected: function, module, session (reverse scope order)
    expected = ["function", "module", "session"]
    assert teardown_log == expected, \
        f"Expected teardown order {expected}, got {teardown_log}"
    print(f"  PASS: Teardown order correct: {teardown_log}")
    return True


def test_setup_returns_value():
    """Setup function return value should be accessible."""
    fm = FixtureManager()
    fm.register("conn", scope="session", setup_fn=lambda: {"host": "localhost"})
    value = fm.setup("conn")
    assert value == {"host": "localhost"}
    print("  PASS: Setup returns fixture value")
    return True


def test_duplicate_setup_idempotent():
    """Setting up same fixture twice should return cached value."""
    fm = FixtureManager()
    call_count = [0]

    def expensive_setup():
        call_count[0] += 1
        return "result"

    fm.register("expensive", scope="session", setup_fn=expensive_setup)
    fm.setup("expensive")
    fm.setup("expensive")
    assert call_count[0] == 1, f"Setup called {call_count[0]} times, expected 1"
    print("  PASS: Duplicate setup is idempotent")
    return True


if __name__ == '__main__':
    print("=== SWE-bench Task: pytest-dev__pytest-5103 ===")
    print("Fixture teardown ordering\n")

    results = []
    print("Test 1: Teardown order (function -> module -> session)")
    results.append(test_teardown_order())
    print("\nTest 2: Setup returns value")
    results.append(test_setup_returns_value())
    print("\nTest 3: Duplicate setup idempotent")
    results.append(test_duplicate_setup_idempotent())

    passed = sum(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{len(results)} tests passed")
    if all(results): print("ALL TESTS PASSED!")
    else: print("SOME TESTS FAILED"); sys.exit(1)
