# -*- coding: utf-8 -*-
"""
BilingualContextRouter stub — RU+EN context-aware router with Tier 1.5.
Full implementation TBD.
"""

from typing import Dict, Any, Optional


class BilingualContextRouter:
    def __init__(self, enable_tier1_5: bool = False):
        self.enable_tier1_5 = enable_tier1_5

    def route(self, query: str) -> Dict[str, Any]:
        return {"tool": None, "args": "", "tier": 4, "confidence": 0.0}

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_requests": 0,
            "tier0_hits": 0,
            "tier1_hits": 0,
            "tier2_hits": 0,
            "tier1_5_hits": 0,
            "tier4_escalations": 0,
            "no_llm_rate": 0.0,
            "escalation_rate": 0.0,
        }
