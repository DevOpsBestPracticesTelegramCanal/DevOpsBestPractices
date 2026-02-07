"""
Multi-Candidate Pipeline — the full generate → validate → select flow.

This is the main integration point that the Orchestrator calls.
It wires together:
    1. MultiCandidateGenerator  (produces N code variants)
    2. RuleRunner               (validates each variant)
    3. CandidateSelector        (picks the best one)

Usage:
    pipeline = MultiCandidatePipeline(llm_adapter)
    result = await pipeline.run(task_id="abc", query="Write a sort function")
    print(result.best.code)

Sync usage (for Flask/Orchestrator):
    result = pipeline.run_sync(task_id="abc", query="Write a sort function")
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from .candidate import Candidate, CandidatePool, CandidateStatus, ValidationScore
from .multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
from .selector import CandidateSelector, ScoringWeights

from code_validator.rules.base import RuleRunner, RuleResult
from code_validator.rules.python_validators import default_python_rules

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a full multi-candidate pipeline run."""

    pool: CandidatePool
    best: Optional[Candidate]
    all_passed: bool  # whether the best candidate passed all validators
    total_time: float = 0.0
    generation_time: float = 0.0
    validation_time: float = 0.0
    selection_time: float = 0.0

    @property
    def code(self) -> str:
        """Shortcut: code of the best candidate, or empty string."""
        return self.best.code if self.best else ""

    @property
    def score(self) -> float:
        return self.best.total_score if self.best else 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "candidates_generated": self.pool.size,
            "best_id": self.best.id if self.best else None,
            "best_score": round(self.score, 4),
            "all_passed": self.all_passed,
            "total_time": round(self.total_time, 3),
            "generation_time": round(self.generation_time, 3),
            "validation_time": round(self.validation_time, 3),
            "pool_stats": self.pool.stats(),
        }


@dataclass
class PipelineConfig:
    """Configuration for the pipeline."""

    n_candidates: int = 3
    parallel_generation: bool = True
    fail_fast_validation: bool = True  # stop validating on first CRITICAL fail
    generation_config: Optional[MultiCandidateConfig] = None
    scoring_weights: Optional[ScoringWeights] = None


class MultiCandidatePipeline:
    """
    Full pipeline: generate → validate → select.

    Designed to be created once and reused for multiple tasks.
    """

    def __init__(
        self,
        llm,
        config: Optional[PipelineConfig] = None,
        rules: Optional[List] = None,
    ):
        """
        Args:
            llm: LLMProtocol-compatible object (use AsyncLLMAdapter).
            config: Pipeline configuration.
            rules: Custom validation rules. Defaults to standard Python rules.
        """
        self.config = config or PipelineConfig()

        self.generator = MultiCandidateGenerator(
            llm,
            config=self.config.generation_config,
        )
        self.validator = RuleRunner(rules or default_python_rules())
        self.selector = CandidateSelector(
            scoring=self.config.scoring_weights,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        task_id: str = "task",
        query: str = "",
        affected_files: Optional[List[str]] = None,
        swecas_code: Optional[int] = None,
        n: Optional[int] = None,
    ) -> PipelineResult:
        """
        Run the full pipeline asynchronously.

        Args:
            task_id: Unique identifier for the task.
            query: The code generation prompt.
            affected_files: Files related to this task.
            swecas_code: SWECAS classification code.
            n: Override number of candidates.

        Returns:
            PipelineResult with best candidate and statistics.
        """
        t_start = time.perf_counter()
        n = n or self.config.n_candidates

        logger.info("[Pipeline] starting: task=%s, n=%d", task_id, n)

        # --- Step 1: Generate ---
        t_gen = time.perf_counter()

        task = _SimpleTask(
            task_id=task_id,
            query=query,
            affected_files=affected_files or [],
            swecas_code=swecas_code,
        )
        pool = await self.generator.generate(
            task,
            n=n,
            parallel=self.config.parallel_generation,
        )
        generation_time = time.perf_counter() - t_gen

        logger.info("[Pipeline] generated %d candidates in %.2fs", pool.size, generation_time)

        if pool.size == 0:
            raise RuntimeError(
                f"All {n} candidates failed to generate (timeout or LLM error)"
            )

        # --- Step 2: Validate ---
        t_val = time.perf_counter()
        self._validate_pool(pool)
        validation_time = time.perf_counter() - t_val

        logger.info("[Pipeline] validated in %.2fs", validation_time)

        # --- Step 3: Select ---
        t_sel = time.perf_counter()
        best = self.selector.select(pool)
        selection_time = time.perf_counter() - t_sel

        total_time = time.perf_counter() - t_start

        logger.info(
            "[Pipeline] done: best=#%d score=%.4f (%s errors) in %.2fs total",
            best.id,
            best.total_score,
            "has" if best.has_critical_errors else "no",
            total_time,
        )

        return PipelineResult(
            pool=pool,
            best=best,
            all_passed=best.all_passed,
            total_time=total_time,
            generation_time=generation_time,
            validation_time=validation_time,
            selection_time=selection_time,
        )

    def run_sync(self, **kwargs) -> PipelineResult:
        """
        Synchronous wrapper for Flask/Orchestrator integration.

        Accepts the same kwargs as run().
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already in an async context (nest_asyncio)
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(self.run(**kwargs))
        else:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.run(**kwargs))
            finally:
                loop.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate_pool(self, pool: CandidatePool) -> None:
        """Run all rules on every candidate in the pool."""
        for candidate in pool.candidates:
            candidate.status = CandidateStatus.VALIDATING

            results: List[RuleResult] = self.validator.run(
                candidate.code,
                fail_fast=self.config.fail_fast_validation,
            )

            for r in results:
                candidate.add_validation(
                    ValidationScore(
                        validator_name=r.rule_name,
                        passed=r.passed,
                        score=r.score,
                        errors=r.errors,
                        warnings=r.warnings,
                        duration=r.duration,
                        weight=self._rule_weight(r.rule_name),
                    )
                )

            candidate.status = CandidateStatus.VALIDATED

    def _rule_weight(self, rule_name: str) -> float:
        """Get weight for a rule from scoring config or rule default."""
        if self.config.scoring_weights:
            return self.config.scoring_weights.get(rule_name)
        # Fall back to default weight (1.0)
        return 1.0


@dataclass
class _SimpleTask:
    """Lightweight task object for the generator."""

    task_id: str = "task"
    query: str = ""
    affected_files: list = field(default_factory=list)
    swecas_code: Optional[int] = None
    type: object = None
    risk_level: object = None
