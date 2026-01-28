"""Simplified matplotlib Axis configuration for SWE-bench task.

Bug: set_xlim(left, right) does not swap values when left > right.
Should auto-swap so xlim always has min <= max.
SWECAS-700: Config & Environment
"""


class Axis:
    """Simplified axis with limits and labels."""

    def __init__(self):
        self._xlim = (0.0, 1.0)
        self._ylim = (0.0, 1.0)
        self._xlabel = ""
        self._ylabel = ""
        self._inverted = False

    def set_xlim(self, left=None, right=None):
        """Set x-axis limits.

        BUG: Does not handle left > right.
        Should auto-swap or set inverted flag.
        When user passes set_xlim(10, 0), the axis should still
        store (0, 10) with inverted=True.
        """
        if left is not None and right is not None:
            # BUG: directly assigns without checking order
            self._xlim = (float(left), float(right))
        elif left is not None:
            self._xlim = (float(left), self._xlim[1])
        elif right is not None:
            self._xlim = (self._xlim[0], float(right))

    def get_xlim(self):
        return self._xlim

    def set_ylim(self, bottom=None, top=None):
        if bottom is not None and top is not None:
            if bottom > top:
                bottom, top = top, bottom
                self._inverted = True
            self._ylim = (float(bottom), float(top))

    def get_ylim(self):
        return self._ylim

    def is_inverted(self):
        return self._inverted

    def set_xlabel(self, label):
        self._xlabel = str(label)

    def set_ylabel(self, label):
        self._ylabel = str(label)
