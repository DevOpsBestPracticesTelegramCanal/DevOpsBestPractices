"""
Multi-Candidate Code Generation System

Generates multiple code variants with different parameters,
validates each through rule-based validators, and selects the best.

Architecture:
    MultiCandidateGenerator → [Candidate, Candidate, ...] → RuleValidators → Selector → Best
"""

from .candidate import Candidate, CandidatePool, CandidateStatus, ValidationScore
from .multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
from .selector import CandidateSelector, ScoringWeights
from .llm_adapter import AsyncLLMAdapter
from .pipeline import MultiCandidatePipeline, PipelineConfig, PipelineResult
from .adaptive_strategy import AdaptiveStrategy, AdaptiveConfig, CodegenComplexity

__all__ = [
    "Candidate",
    "CandidatePool",
    "CandidateStatus",
    "ValidationScore",
    "MultiCandidateGenerator",
    "MultiCandidateConfig",
    "CandidateSelector",
    "ScoringWeights",
    "AsyncLLMAdapter",
    "MultiCandidatePipeline",
    "PipelineConfig",
    "PipelineResult",
    "AdaptiveStrategy",
    "AdaptiveConfig",
    "CodegenComplexity",
]
