"""
Week 15: Self-Correction Loop

When the Multi-Candidate Pipeline validates code and finds errors,
this module re-generates with validation feedback injected into the prompt.
Up to MAX_ITERATIONS re-attempts before giving up.

Key design:
    - Wraps the existing pipeline (generate → validate → select)
    - Between iterations, builds a "correction prompt" from errors
    - Tracks improvement across iterations
    - Stops early if a candidate passes all validators
    - Returns the overall best across ALL iterations

Estimated quality improvement: +5-15% per correction iteration (same model).
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3
MIN_SCORE_FOR_CORRECTION = 0.1  # Don't correct if code is total garbage


@dataclass
class CorrectionAttempt:
    """Result of a single correction iteration."""

    iteration: int
    best_score: float
    all_passed: bool
    code: str
    errors: List[str]
    generation_time: float = 0.0
    validation_time: float = 0.0
    total_time: float = 0.0
    n_candidates: int = 0


@dataclass
class CorrectionResult:
    """Final result after all correction iterations."""

    # The overall best code (across all iterations)
    best_code: str
    best_score: float
    all_passed: bool

    # Iteration history
    attempts: List[CorrectionAttempt] = field(default_factory=list)
    total_iterations: int = 0
    total_time: float = 0.0

    # Did correction actually help?
    initial_score: float = 0.0
    final_score: float = 0.0
    improvement: float = 0.0
    corrected: bool = False  # True if correction improved the score

    # Original PipelineResult from the best iteration
    best_pipeline_result: Optional[Any] = None

    def summary(self) -> Dict[str, Any]:
        return {
            "total_iterations": self.total_iterations,
            "initial_score": round(self.initial_score, 4),
            "final_score": round(self.final_score, 4),
            "improvement": round(self.improvement, 4),
            "all_passed": self.all_passed,
            "corrected": self.corrected,
            "total_time": round(self.total_time, 3),
            "attempts": [
                {
                    "iteration": a.iteration,
                    "score": round(a.best_score, 4),
                    "all_passed": a.all_passed,
                    "errors": len(a.errors),
                    "time": round(a.total_time, 3),
                }
                for a in self.attempts
            ],
        }


def extract_validation_errors(pipeline_result) -> List[str]:
    """Extract structured validation errors from a PipelineResult.

    Returns a list of human-readable error strings suitable for
    injection into a correction prompt.
    """
    errors = []
    if not pipeline_result or not pipeline_result.best:
        return errors

    for vs in pipeline_result.best.validation_scores:
        if not vs.passed:
            for err in vs.errors:
                errors.append(f"[{vs.validator_name}] {err}")
            for warn in vs.warnings:
                errors.append(f"[{vs.validator_name}] WARNING: {warn}")

    return errors


def build_correction_prompt(
    original_query: str,
    previous_code: str,
    errors: List[str],
    iteration: int,
) -> str:
    """Build a prompt that includes previous code + its errors.

    The model receives:
    1. The original task description
    2. The code it generated last time
    3. The specific validation errors found
    4. Instructions to fix those errors
    """
    error_block = "\n".join(f"  - {e}" for e in errors[:10])  # Cap at 10 errors

    return (
        f"{original_query}\n\n"
        f"--- CORRECTION ATTEMPT {iteration}/{MAX_ITERATIONS} ---\n"
        f"Your previous code had validation errors. Fix them.\n\n"
        f"Previous code:\n```\n{previous_code}\n```\n\n"
        f"Validation errors found:\n{error_block}\n\n"
        f"Generate corrected code that fixes ALL the above errors.\n"
        f"Output ONLY the corrected source code."
    )


def extract_key_issues(attempts: List[CorrectionAttempt]) -> List[str]:
    """Find recurring error patterns across correction attempts.

    If the same error appears in multiple iterations, the model has
    "cognitive blindness" to that issue.
    """
    if not attempts:
        return []

    # Count error occurrences by validator name
    error_counts: Dict[str, int] = {}
    for attempt in attempts:
        seen_in_attempt = set()
        for err in attempt.errors:
            # Extract validator name from "[validator_name] message"
            key = err.split("]")[0].strip("[") if "]" in err else "unknown"
            if key not in seen_in_attempt:
                error_counts[key] = error_counts.get(key, 0) + 1
                seen_in_attempt.add(key)

    recurring = [
        f"{name} (failed {count}/{len(attempts)} attempts)"
        for name, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
        if count >= 2
    ]
    return recurring


class SelfCorrectionLoop:
    """
    Wraps the Multi-Candidate Pipeline with iterative error correction.

    Usage:
        loop = SelfCorrectionLoop(pipeline)
        result = loop.run_sync(query="Write a sort function", ...)

        if result.corrected:
            print(f"Improved from {result.initial_score} to {result.final_score}")
    """

    def __init__(
        self,
        pipeline,
        max_iterations: int = MAX_ITERATIONS,
        min_score: float = MIN_SCORE_FOR_CORRECTION,
    ):
        """
        Args:
            pipeline: MultiCandidatePipeline instance.
            max_iterations: Maximum correction attempts (1 = no correction).
            min_score: Minimum initial score to attempt correction.
                       Below this, the code is too broken to salvage.
        """
        self.pipeline = pipeline
        self.max_iterations = max(1, max_iterations)
        self.min_score = min_score

    def run_sync(
        self,
        query: str = "",
        task_id: str = "task",
        on_iteration=None,
        **pipeline_kwargs,
    ) -> CorrectionResult:
        """
        Run the pipeline with self-correction.

        Args:
            query: The original code generation prompt.
            task_id: Unique task identifier.
            on_iteration: Optional callback(iteration, attempt) for SSE events.
            **pipeline_kwargs: Forwarded to pipeline.run_sync().

        Returns:
            CorrectionResult with the overall best across all iterations.
        """
        t_start = time.perf_counter()

        attempts: List[CorrectionAttempt] = []
        best_overall_result = None
        best_overall_score = -1.0
        current_query = query

        for iteration in range(1, self.max_iterations + 1):
            logger.info(
                "[SelfCorrection] iteration %d/%d",
                iteration, self.max_iterations,
            )

            # Run the pipeline
            try:
                mc_result = self.pipeline.run_sync(
                    task_id=f"{task_id}_iter{iteration}",
                    query=current_query,
                    **pipeline_kwargs,
                )
            except Exception as exc:
                logger.error("[SelfCorrection] pipeline error on iter %d: %s", iteration, exc)
                break

            # Extract errors from this iteration
            errors = extract_validation_errors(mc_result)

            attempt = CorrectionAttempt(
                iteration=iteration,
                best_score=mc_result.score,
                all_passed=mc_result.all_passed,
                code=mc_result.code,
                errors=errors,
                generation_time=mc_result.generation_time,
                validation_time=mc_result.validation_time,
                total_time=mc_result.total_time,
                n_candidates=mc_result.pool.size,
            )
            attempts.append(attempt)

            # Notify caller
            if on_iteration:
                try:
                    on_iteration(iteration, attempt)
                except Exception:
                    pass

            # Track the overall best
            if mc_result.score > best_overall_score:
                best_overall_score = mc_result.score
                best_overall_result = mc_result

            # Early exit: all validators passed
            if mc_result.all_passed:
                logger.info(
                    "[SelfCorrection] all passed on iteration %d (score=%.4f)",
                    iteration, mc_result.score,
                )
                break

            # Don't try to correct garbage code
            if mc_result.score < self.min_score:
                logger.info(
                    "[SelfCorrection] score %.4f below min_score %.2f, stopping",
                    mc_result.score, self.min_score,
                )
                break

            # Last iteration — don't build correction prompt
            if iteration >= self.max_iterations:
                break

            # No errors to feed back (shouldn't happen if not all_passed, but be safe)
            if not errors:
                break

            # Build correction prompt for the next iteration
            current_query = build_correction_prompt(
                original_query=query,
                previous_code=mc_result.code,
                errors=errors,
                iteration=iteration + 1,
            )
            logger.info(
                "[SelfCorrection] building correction prompt with %d errors for iter %d",
                len(errors), iteration + 1,
            )

        total_time = time.perf_counter() - t_start

        # Compute improvement
        initial_score = attempts[0].best_score if attempts else 0.0
        final_score = best_overall_score if best_overall_score >= 0 else 0.0
        improvement = final_score - initial_score

        return CorrectionResult(
            best_code=best_overall_result.code if best_overall_result else "",
            best_score=final_score,
            all_passed=best_overall_result.all_passed if best_overall_result else False,
            attempts=attempts,
            total_iterations=len(attempts),
            total_time=total_time,
            initial_score=initial_score,
            final_score=final_score,
            improvement=improvement,
            corrected=improvement > 0.01 and len(attempts) > 1,
            best_pipeline_result=best_overall_result,
        )
