"""Simplified Django QuerySet for SWE-bench task.

Bug: QuerySet.exclude() with None value uses wrong SQL predicate.
Uses `!= None` instead of `IS NOT NULL`, returning incorrect results.
SWECAS-600: Logic & Control Flow
"""


class QuerySet:
    """Simplified QuerySet that filters in-memory lists."""

    def __init__(self, data=None):
        self._data = list(data) if data else []

    def filter(self, **kwargs):
        """Filter records matching all kwargs."""
        result = []
        for item in self._data:
            match = True
            for key, value in kwargs.items():
                if key.endswith("__isnull"):
                    field = key[:-len("__isnull")]
                    is_null = item.get(field) is None
                    if is_null != value:
                        match = False
                elif item.get(key) != value:
                    match = False
            if match:
                result.append(item)
        return QuerySet(result)

    def exclude(self, **kwargs):
        """Exclude records matching kwargs.

        BUG: When excluding with a None value, uses equality check (`== None`)
        instead of identity check (`is None`), which can miss items where
        the field is actually None due to custom __eq__ behavior.
        """
        result = []
        for item in self._data:
            excluded = False
            for key, value in kwargs.items():
                # BUG: should use `is` for None comparison, not `==`
                if item.get(key) == value:
                    excluded = True
                    break
            if not excluded:
                result.append(item)
        return QuerySet(result)

    def count(self):
        return len(self._data)

    def all(self):
        return QuerySet(self._data[:])

    def values_list(self, *fields, flat=False):
        results = []
        for item in self._data:
            if flat and len(fields) == 1:
                results.append(item.get(fields[0]))
            else:
                results.append(tuple(item.get(f) for f in fields))
        return results

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return f"<QuerySet: {len(self._data)} items>"
