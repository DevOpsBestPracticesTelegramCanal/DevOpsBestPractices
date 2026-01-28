"""Simplified collections utility for SWE-bench task.

Bug: OrderedDict.move_to_end() does not raise KeyError for missing keys.
Instead returns None silently, violating the expected API contract.
SWECAS-100: Null/None & Value Errors
"""


class OrderedDict:
    """Simplified ordered dictionary."""

    def __init__(self, items=None):
        self._keys = []
        self._data = {}
        if items:
            for k, v in items:
                self[k] = v

    def __setitem__(self, key, value):
        if key not in self._data:
            self._keys.append(key)
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._keys)

    def keys(self):
        return list(self._keys)

    def values(self):
        return [self._data[k] for k in self._keys]

    def items(self):
        return [(k, self._data[k]) for k in self._keys]

    def move_to_end(self, key, last=True):
        """Move an existing key to either end of the ordered dict.

        BUG: Does not raise KeyError when key is missing.
        Returns None silently, which can cause NoneType errors later.
        Should raise KeyError for missing key.
        """
        # BUG: no check for key existence
        if key in self._keys:
            self._keys.remove(key)
            if last:
                self._keys.append(key)
            else:
                self._keys.insert(0, key)
        # BUG: silently does nothing if key not found

    def __repr__(self):
        items_str = ", ".join(f"{k!r}: {self._data[k]!r}" for k in self._keys)
        return f"OrderedDict({{{items_str}}})"
