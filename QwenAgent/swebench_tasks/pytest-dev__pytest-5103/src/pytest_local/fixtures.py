"""Simplified pytest fixture system for SWE-bench task.

Bug: Module-scope fixture teardown runs BEFORE session-scope fixture teardown,
but module fixture depends on session fixture still being alive.
Fixture cleanup order is wrong.
SWECAS-900: Async, Concurrency & I/O (temporal ordering)
"""


class FixtureManager:
    """Manages fixture lifecycle with scope-based ordering."""

    SCOPE_ORDER = {"session": 0, "module": 1, "class": 2, "function": 3}

    def __init__(self):
        self._fixtures = {}  # name -> {scope, setup_fn, teardown_fn, value}
        self._active = []    # stack of active fixture names
        self._teardown_order = []  # recorded teardown order for testing

    def register(self, name, scope="function", setup_fn=None, teardown_fn=None):
        self._fixtures[name] = {
            "scope": scope,
            "setup_fn": setup_fn,
            "teardown_fn": teardown_fn,
            "value": None,
            "active": False,
        }

    def setup(self, name):
        """Setup a fixture and its dependencies."""
        fix = self._fixtures[name]
        if fix["active"]:
            return fix["value"]

        if fix["setup_fn"]:
            fix["value"] = fix["setup_fn"]()
        fix["active"] = True
        self._active.append(name)
        return fix["value"]

    def teardown_all(self):
        """Tear down all active fixtures.

        BUG: Tears down in registration order (FIFO) instead of
        reverse scope order. Session-scope fixtures should tear down LAST.
        Currently: session teardown may run before module teardown completes.
        """
        # BUG: iterates in forward order (FIFO)
        # Should reverse: function -> class -> module -> session
        for name in self._active:
            fix = self._fixtures[name]
            if fix["teardown_fn"]:
                fix["teardown_fn"]()
            fix["active"] = False
            self._teardown_order.append(name)
        self._active.clear()

    def get_teardown_order(self):
        return self._teardown_order
