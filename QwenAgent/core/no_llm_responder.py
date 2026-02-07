# -*- coding: utf-8 -*-
"""
NoLLMResponder stub — responds to trivial queries without LLM.
Full implementation TBD.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Any


class ResponseType(Enum):
    CACHED = "cached"
    PATTERN = "pattern"
    MATH = "math"
    GREETING = "greeting"


@dataclass
class NoLLMResponse:
    success: bool = False
    response: str = ""
    confidence: float = 0.0
    response_type: ResponseType = ResponseType.PATTERN


class NoLLMResponder:
    def __init__(self, solution_cache: Any = None):
        self.solution_cache = solution_cache

    def try_respond(self, query: str, context: Any = None) -> NoLLMResponse:
        return NoLLMResponse(success=False)

    def process(self, query: str) -> Optional[str]:
        return None
