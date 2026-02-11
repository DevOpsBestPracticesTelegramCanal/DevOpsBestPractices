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
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

from .candidate import Candidate, CandidatePool, CandidateStatus, ValidationScore
from .multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
from .selector import CandidateSelector, ScoringWeights

from code_validator.rules.base import RuleRunner, RuleResult, RuleSeverity
from code_validator.rules.python_validators import default_python_rules, build_rules_for_names
from code_validator.rules.devops_validators import detect_content_type, rules_for_content_type

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
_mc_validation_speedup = metrics_registry.histogram(
    "mc_validation_speedup", "Parallel validation speedup ratio",
    buckets=(1.0, 1.2, 1.5, 2.0, 3.0, 5.0),
)
_mc_validation_cache_hits = metrics_registry.counter(
    "mc_validation_cache_hits", "Validation cache hits",
)


@dataclass
class ValidationStats:
    """Statistics from candidate-level parallel validation (Week 18)."""

    parallel: bool = True
    n_candidates: int = 0
    per_candidate_times: List[float] = field(default_factory=list)
    sequential_estimate: float = 0.0   # sum of per-candidate times
    parallel_actual: float = 0.0       # wall-clock time
    speedup: float = 1.0
    max_workers_used: int = 0

    # Week 19: Validation Result Cache
    cache_hits: int = 0
    cache_misses: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parallel": self.parallel,
            "n_candidates": self.n_candidates,
            "per_candidate_times": [round(t, 4) for t in self.per_candidate_times],
            "sequential_estimate": round(self.sequential_estimate, 4),
            "parallel_actual": round(self.parallel_actual, 4),
            "speedup": round(self.speedup, 2),
            "max_workers_used": self.max_workers_used,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


class ValidationCache:
    """In-memory LRU cache for validation results. Thread-safe."""

    def __init__(self, max_size: int = 256):
        self._max_size = max_size
        self._cache: OrderedDict[str, list] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(code: str, rule_names: List[str]) -> str:
        normalized = code.strip()
        sorted_names = sorted(rule_names)
        payload = f"{normalized}||{'|'.join(sorted_names)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def get(self, code: str, rule_names: List[str]) -> Optional[list]:
        key = self._make_key(code, rule_names)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                self._cache.move_to_end(key)
                return self._cache[key]
            self._misses += 1
            return None

    def put(self, code: str, rule_names: List[str], results: list) -> None:
        key = self._make_key(code, rule_names)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = results
            else:
                if len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
                self._cache[key] = results

    def get_stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "cache_size": len(self._cache),
                "max_size": self._max_size,
                "cache_hits": self._hits,
                "cache_misses": self._misses,
                "hit_rate_percent": round(
                    (self._hits / total * 100) if total > 0 else 0.0, 1
                ),
            }

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0


def _serialize_rule_results(results: List[RuleResult]) -> list:
    """Serialize RuleResult objects for cache storage."""
    return [
        {
            "rule_name": r.rule_name,
            "passed": r.passed,
            "score": r.score,
            "severity": r.severity.value,
            "messages": list(r.messages),
        }
        for r in results
    ]


def _deserialize_rule_results(data: list) -> List[RuleResult]:
    """Deserialize cached validation results back to RuleResult objects."""
    return [
        RuleResult(
            rule_name=d["rule_name"],
            passed=d["passed"],
            score=d["score"],
            severity=RuleSeverity(d["severity"]),
            messages=list(d["messages"]),
            duration=0.0,
        )
        for d in data
    ]


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
    validation_stats: Optional[ValidationStats] = None

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
        if self.validation_stats:
            s["validation_stats"] = self.validation_stats.to_dict()
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
    # Week 18: Parallel Candidate Validation
    parallel_candidate_validation: bool = True
    max_validation_workers: int = 4
    # Week 19: Validation Result Cache
    validation_cache_enabled: bool = True
    max_validation_cache_size: int = 256


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

        # Week 19: Validation Result Cache
        self._validation_cache: Optional[ValidationCache] = None
        if self.config.validation_cache_enabled:
            self._validation_cache = ValidationCache(
                max_size=self.config.max_validation_cache_size,
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

        # --- Step 2: Validate (profile-aware since Week 12, parallel since Week 18) ---
        t_val = time.perf_counter()
        validation_stats = self._validate_pool(
            pool,
            validator=run_validator,
            fail_fast=run_fail_fast,
            parallel=run_parallel_val,
            validation_profile=validation_profile,
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
            validation_stats=validation_stats,
        )

    def run_sync(self, **kwargs) -> PipelineResult:
        """
        Synchronous wrapper for Flask/Orchestrator integration.

        Accepts the same kwargs as run().
        Uses a non-daemon thread to avoid 'Cannot run async subprocess
        in daemon thread' errors from Flask/Werkzeug.
        """
        import threading

        # If we're in a daemon thread (Flask/Werkzeug), spawn a non-daemon
        # worker thread that can safely create an asyncio event loop.
        current = threading.current_thread()
        if current.daemon:
            result_box: list = []
            error_box: list = []

            def _worker():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result_box.append(loop.run_until_complete(self.run(**kwargs)))
                    finally:
                        loop.close()
                except Exception as exc:
                    error_box.append(exc)

            t = threading.Thread(target=_worker, daemon=False)
            t.start()
            t.join(timeout=660)  # match total_timeout ceiling

            if t.is_alive():
                raise TimeoutError("Pipeline timed out (660s) in non-daemon thread")
            if error_box:
                raise error_box[0]
            if not result_box:
                raise RuntimeError("Pipeline returned no result")
            result = result_box[0]
        else:
            # Normal path — not in a daemon thread
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                result = loop.run_until_complete(self.run(**kwargs))
            else:
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(self.run(**kwargs))
                finally:
                    loop.close()

        # Phase 2: Store last result for REST API access
        self._last_result = result
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate_single_candidate(
        self,
        candidate: 'Candidate',
        validator: RuleRunner,
        fail_fast: bool,
        parallel: bool,
    ) -> float:
        """Validate one candidate. Returns wall-clock seconds."""
        t0 = time.perf_counter()
        candidate.status = CandidateStatus.VALIDATING

        # Week 16: detect content type and swap validators for DevOps code
        run_validator = validator
        content_type = detect_content_type(candidate.code)
        if content_type not in ("python", "unknown"):
            devops_rules = rules_for_content_type(content_type)
            if devops_rules:
                run_validator = RuleRunner(devops_rules)
                logger.info(
                    "[Pipeline] candidate content_type=%s, using %d DevOps rules",
                    content_type, len(devops_rules),
                )

        # Week 19: Check validation cache
        rule_names = [r.name for r in run_validator.rules]
        cached = None
        if self._validation_cache is not None:
            cached = self._validation_cache.get(candidate.code, rule_names)

        if cached is not None:
            results = _deserialize_rule_results(cached)
            _mc_validation_cache_hits.inc()
            logger.debug("[Pipeline] cache hit for candidate #%d", candidate.id)
        else:
            results: List[RuleResult] = run_validator.run(
                candidate.code,
                fail_fast=fail_fast,
                parallel=parallel,
            )
            if self._validation_cache is not None:
                self._validation_cache.put(
                    candidate.code, rule_names,
                    _serialize_rule_results(results),
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
        return time.perf_counter() - t0

    def _validate_pool(
        self,
        pool: CandidatePool,
        validator: Optional[RuleRunner] = None,
        fail_fast: Optional[bool] = None,
        parallel: bool = True,
        validation_profile: Optional[Any] = None,
    ) -> 'ValidationStats':
        """Run all rules on every candidate in the pool.

        Week 16: For non-Python content (Kubernetes, Terraform, etc.), detects
        the content type and substitutes DevOps-specific validators.

        Week 18: Validates candidates in parallel using ThreadPoolExecutor
        when parallel_candidate_validation is enabled and pool.size > 1.
        Returns ValidationStats with timing and speedup data.
        """
        validator = validator or self.validator
        if fail_fast is None:
            fail_fast = self.config.fail_fast_validation

        use_parallel = (
            self.config.parallel_candidate_validation
            and pool.size > 1
            and not fail_fast
        )
        n_workers = min(pool.size, self.config.max_validation_workers)

        # Week 19: snapshot cache counters before validation
        _hits_before = self._validation_cache._hits if self._validation_cache else 0
        _misses_before = self._validation_cache._misses if self._validation_cache else 0

        t0 = time.perf_counter()
        per_candidate_times: List[float] = []

        if use_parallel:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                futures = {
                    executor.submit(
                        self._validate_single_candidate,
                        c, validator, fail_fast, parallel,
                    ): i
                    for i, c in enumerate(pool.candidates)
                }
                results_map: Dict[int, float] = {}
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        duration = future.result()
                    except Exception as exc:
                        logger.error("[Pipeline] candidate %d validation crashed: %s", idx, exc)
                        pool.candidates[idx].status = CandidateStatus.VALIDATED
                        duration = 0.0
                    results_map[idx] = duration
                # Preserve candidate order
                per_candidate_times = [results_map[i] for i in range(pool.size)]
        else:
            for candidate in pool.candidates:
                duration = self._validate_single_candidate(
                    candidate, validator, fail_fast, parallel,
                )
                per_candidate_times.append(duration)

        parallel_actual = time.perf_counter() - t0
        sequential_estimate = sum(per_candidate_times)
        speedup = sequential_estimate / parallel_actual if parallel_actual > 0 else 1.0

        # Week 19: compute cache deltas for this batch
        cache_hits = (self._validation_cache._hits if self._validation_cache else 0) - _hits_before
        cache_misses = (self._validation_cache._misses if self._validation_cache else 0) - _misses_before

        stats = ValidationStats(
            parallel=use_parallel,
            n_candidates=pool.size,
            per_candidate_times=per_candidate_times,
            sequential_estimate=sequential_estimate,
            parallel_actual=parallel_actual,
            speedup=speedup,
            max_workers_used=n_workers if use_parallel else 1,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )

        if use_parallel:
            _mc_validation_speedup.observe(speedup)
            logger.info(
                "[Pipeline] parallel validation: %.2fs (est. seq: %.2fs, speedup: %.1fx)",
                parallel_actual, sequential_estimate, speedup,
            )

        return stats

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
