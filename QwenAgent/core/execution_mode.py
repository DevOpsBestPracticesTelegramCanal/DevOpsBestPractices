# -*- coding: utf-8 -*-
"""
ExecutionMode — canonical definition used by QwenCodeAgent, BudgetEstimator, etc.
"""

from enum import Enum
from typing import Optional


class ExecutionMode(Enum):
    """Execution modes with escalation support."""
    FAST = "fast"
    DEEP3 = "deep3"
    DEEP6 = "deep6"
    SEARCH = "search"
    SEARCH_DEEP = "search_deep"

    @property
    def icon(self) -> str:
        icons = {
            "fast": "[FAST]",
            "deep3": "[DEEP3]",
            "deep6": "[DEEP6]",
            "search": "[SEARCH]",
            "search_deep": "[SEARCH+DEEP]",
        }
        return icons.get(self.value, "[?]")

    @property
    def is_search(self) -> bool:
        return self in (ExecutionMode.SEARCH, ExecutionMode.SEARCH_DEEP)


# Escalation chain: current → next on timeout
ESCALATION_CHAIN = {
    ExecutionMode.FAST: ExecutionMode.DEEP3,
    ExecutionMode.DEEP3: ExecutionMode.DEEP6,
    ExecutionMode.DEEP6: ExecutionMode.SEARCH,
    ExecutionMode.SEARCH: ExecutionMode.SEARCH_DEEP,
    ExecutionMode.SEARCH_DEEP: None,  # terminal
}


def normalize_mode(mode_str: str) -> Optional[ExecutionMode]:
    """Convert string to ExecutionMode, returns None if unrecognised."""
    mapping = {
        "fast": ExecutionMode.FAST,
        "deep": ExecutionMode.DEEP3,
        "deep3": ExecutionMode.DEEP3,
        "deep6": ExecutionMode.DEEP6,
        "search": ExecutionMode.SEARCH,
        "deep_search": ExecutionMode.SEARCH_DEEP,
        "search_deep": ExecutionMode.SEARCH_DEEP,
    }
    return mapping.get(mode_str.lower().strip())
