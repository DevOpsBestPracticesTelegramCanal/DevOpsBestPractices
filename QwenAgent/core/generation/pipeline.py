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
from typing import Dict, List, Optional, Any, Tuple

from .candidate import Candidate, CandidatePool, CandidateStatus, ValidationScore
from .multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
from .selector import CandidateSelector, ScoringWeights

from code_validator.rules.base import RuleRunner, RuleResult
from code_validator.rules.python_validators import default_python_rules, build_rules_for_names

from core.observability.metrics import metrics as metrics_registry

logger = logging.getLogger(__name__)

# --- Prometheus-style metrics for Multi-Candidate Pipeline ---
_mc_runs = metrics_registry.counter("mc_pipeline_runs_total", "Total pipeline runs")
_mc_candidates = metrics_registry.counter("mc_candidates_generated_total", "Total candidates generated")
_mc_duration = metrics_registry.histogram(
    "mc_pipeline_duration_seconds", "Pipeline run duration",
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)
_mc_best_score = metrics_registry.histogram(
    "mc_best_score", "Best candidate score distribution",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
_mc_critical_errors = metrics_registry.counter("mc_critical_errors_total", "Candidates with critical errors")
_mc_cross_reviews = metrics_registry.counter("mc_cross_reviews_total", "Cross-architecture reviews performed")
_mc_cross_review_duration = metrics_registry.histogram(
    "mc_cross_review_duration_seconds", "Cross-review API call duration",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)
_mc_adaptive_complexity = metrics_registry.counter("mc_adaptive_complexity_total", "Adaptive complexity classifications")
_mc_adaptive_candidates = metrics_registry.counter("mc_adaptive_candidates_used", "Adaptive candidates used")
_mc_adaptive_time_saved = metrics_registry.counter("mc_adaptive_time_saved_seconds", "Time saved by adaptive strategy")
_mc_correction_runs = metrics_registry.counter("mc_correction_runs_total", "Self-correction loop invocations")
_mc_correction_iterations = metrics_registry.counter("mc_correction_iterations_total", "Total correction iterations")
_mc_correction_improvements = metrics_registry.counter("mc_correction_improvements_total", "Corrections that improved score")


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
    cross_review_result: Optional[Any] = None  # ReviewResult from cross_arch_review
    cross_review_time: float = 0.0

    @property
    def code(self) -> str:
        """Shortcut: code of the best candidate, or empty string."""
        return self.best.code if self.best else ""

    @property
    def score(self) -> float:
        return self.best.total_score if self.best else 0.0

    def get_candidate_comparison(self) -> List[Dict[str, Any]]:
        """Return per-candidate details sorted by score (best first)."""
        candidates = sorted(
            self.pool.candidates,
            key=lambda c: c.total_score,
            reverse=True,
        )
        result = []
        for c in candidates:
            validator_breakdown = {}
            for vs in c.validation_scores:
                validator_breakdown[vs.validator_name] = {
                    "passed": vs.passed,
                    "score": round(vs.score, 4),
                    "errors": len(vs.errors),
                    "warnings": len(vs.warnings),
                }
            result.append({
                "id": c.id,
                "temperature": c.temperature,
                "score": round(c.total_score, 4),
                "status": c.status.value,
                "all_passed": c.all_passed,
                "has_critical_errors": c.has_critical_errors,
                "validators": validator_breakdown,
                "generation_time": round(c.generation_time, 3),
                "code_lines": len(c.code.strip().splitlines()) if c.code else 0,
            })
        return result

    def summary(self) -> Dict[str, Any]:
        s = {
            "candidates_generated": self.pool.size,
            "best_id": self.best.id if self.best else None,
            "best_score": round(self.score, 4),
            "all_passed": self.all_passed,
            "total_time": round(self.total_time, 3),
            "generation_time": round(self.generation_time, 3),
            "validation_time": round(self.validation_time, 3),
            "pool_stats": self.pool.stats(),
            "candidate_comparison": self.get_candidate_comparison(),
        }
        if self.cross_review_result:
            s["cross_review"] = {
                "issues": len(self.cross_review_result.issues),
                "has_critical": self.cross_review_result.has_critical,
                "time": round(self.cross_review_time, 3),
                "model": self.cross_review_result.model,
            }
        return s


@dataclass
class PipelineConfig:
    """Configuration for the pipeline."""

    n_candidates: int = 3
    parallel_generation: bool = True
    fail_fast_validation: bool = True  # stop validating on first CRITICAL fail
    generation_config: Optional[MultiCandidateConfig] = None
    scoring_weights: Optional[ScoringWeights] = None
    cross_reviewer: Optional[Any] = None  # CrossArchReviewer instance (optional)
    # Week 15: Self-Correction Loop
    self_correction: bool = False          # Enable iterative error correction
    max_correction_iterations: int = 3     # Max re-generation attempts


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
        temperatures: Optional[Tuple[float, ...]] = None,
        oss_context: str = "",
        task_type: object = None,
        task_risk: object = None,
        validation_profile: object = None,
    ) -> PipelineResult:
        """
        Run the full pipeline asynchronously.

        Args:
            task_id: Unique identifier for the task.
            query: The code generation prompt.
            affected_files: Files related to this task.
            swecas_code: SWECAS classification code.
            n: Override number of candidates.
            temperatures: Override temperatures for generation (None = use defaults).
            oss_context: OSS best-practices context to inject into prompts.
            task_type: TaskType from Task Abstraction (Week 11). Advisory.
            task_risk: RiskLevel from Task Abstraction (Week 11). Advisory.
            validation_profile: ValidationProfile from Task Abstraction (Week 12).
                When provided, dynamically selects rules and scoring weights.

        Returns:
            PipelineResult with best candidate and statistics.
        """
        t_start = time.perf_counter()
        n = n or self.config.n_candidates

        # Week 12: Resolve per-run validator, selector, fail_fast from profile
        run_validator = self.validator
        run_selector = self.selector
        run_fail_fast = self.config.fail_fast_validation
        run_parallel_val = True

        if validation_profile is not None:
            try:
                from core.task_abstraction import TaskAbstraction
                val_cfg = TaskAbstraction.get_validation_config(validation_profile)
                rules = build_rules_for_names(val_cfg["rule_names"])
                if rules:
                    run_validator = RuleRunner(rules)
                run_fail_fast = val_cfg.get("fail_fast", run_fail_fast)
                run_parallel_val = val_cfg.get("parallel", True)

                score_weights = TaskAbstraction.get_scoring_weights(validation_profile)
                run_selector = CandidateSelector(
                    scoring=ScoringWeights(weights=score_weights),
                )
                profile_name = getattr(validation_profile, "value", str(validation_profile))
                logger.info("[Pipeline] profile=%s, rules=%d, fail_fast=%s",
                            profile_name, len(rules), run_fail_fast)
            except Exception as profile_err:
                logger.warning("[Pipeline] profile resolution failed: %s, using defaults", profile_err)

        logger.info("[Pipeline] starting: task=%s, n=%d", task_id, n)

        # --- Step 1: Generate ---
        t_gen = time.perf_counter()

        task = _SimpleTask(
            task_id=task_id,
            query=query,
            affected_files=affected_files or [],
            swecas_code=swecas_code,
            oss_context=oss_context,
            type=task_type,
            risk_level=task_risk,
        )
        pool = await self.generator.generate(
            task,
            n=n,
            parallel=self.config.parallel_generation,
            temperatures=temperatures,
        )
        generation_time = time.perf_counter() - t_gen

        logger.info("[Pipeline] generated %d candidates in %.2fs", pool.size, generation_time)

        if pool.size == 0:
            raise RuntimeError(
                f"All {n} candidates failed to generate (timeout or LLM error)"
            )

        # --- Step 2: Validate (profile-aware since Week 12) ---
        t_val = time.perf_counter()
        self._validate_pool(
            pool,
            validator=run_validator,
            fail_fast=run_fail_fast,
            parallel=run_parallel_val,
        )
        validation_time = time.perf_counter() - t_val

        logger.info("[Pipeline] validated in %.2fs", validation_time)

        # --- Step 3: Select (profile-aware scoring since Week 12) ---
        t_sel = time.perf_counter()
        best = run_selector.select(pool)
        selection_time = time.perf_counter() - t_sel

        # --- Step 4: Cross-Architecture Review (optional, advisory) ---
        cross_review_result = None
        cross_review_time = 0.0
        reviewer = self.config.cross_reviewer
        if reviewer and best:
            try:
                if reviewer.should_review(swecas_code=swecas_code, code=best.code):
                    t_review = time.perf_counter()
                    validation_summary = "; ".join(
                        f"{vs.validator_name}: {'PASS' if vs.passed else 'FAIL'}"
                        for vs in best.validation_scores
                    )
                    cross_review_result = reviewer.review(
                        code=best.code,
                        validation_summary=validation_summary,
                        query=query,
                        swecas_code=swecas_code,
                    )
                    cross_review_time = time.perf_counter() - t_review
                    _mc_cross_reviews.inc()
                    _mc_cross_review_duration.observe(cross_review_time)
                    logger.info(
                        "[Pipeline] cross-review: %d issues (%.2fs)",
                        len(cross_review_result.issues),
                        cross_review_time,
                    )
            except Exception as review_err:
                logger.warning("[Pipeline] cross-review failed: %s", review_err)

        total_time = time.perf_counter() - t_start

        # --- Record metrics ---
        _mc_runs.inc()
        _mc_candidates.inc(pool.size)
        _mc_duration.observe(total_time)
        _mc_best_score.observe(best.total_score if best else 0.0)
        for c in pool.candidates:
            if c.has_critical_errors:
                _mc_critical_errors.inc()

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
            cross_review_result=cross_review_result,
            cross_review_time=cross_review_time,
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

    def _validate_pool(
        self,
        pool: CandidatePool,
        validator: Optional[RuleRunner] = None,
        fail_fast: Optional[bool] = None,
        parallel: bool = True,
    ) -> None:
        """Run all rules on every candidate in the pool."""
        validator = validator or self.validator
        if fail_fast is None:
            fail_fast = self.config.fail_fast_validation

        for candidate in pool.candidates:
            candidate.status = CandidateStatus.VALIDATING

            results: List[RuleResult] = validator.run(
                candidate.code,
                fail_fast=fail_fast,
                parallel=parallel,
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
    oss_context: str = ""           # OSS best-practices context for prompt enrichment
    type: object = None
    risk_level: object = None
