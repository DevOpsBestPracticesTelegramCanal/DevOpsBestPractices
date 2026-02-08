"""
Candidate Selector — picks the best candidate from a validated pool.

Scoring strategy:
    weighted_score = Σ (validator_score × validator_weight) / Σ weights
    + bonus for passing ALL validators
    + penalty for critical errors

Usage:
    selector = CandidateSelector()
    best = selector.select(pool)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .candidate import Candidate, CandidatePool, CandidateStatus

logger = logging.getLogger(__name__)


@dataclass
class ScoringWeights:
    """Weights for different validator categories."""

    # validator_name → weight  (higher = more important)
    weights: Dict[str, float] = field(default_factory=lambda: {
        "ast_syntax": 10.0,       # Must parse — deal-breaker
        "static_ruff": 3.0,
        "static_mypy": 2.0,
        "static_bandit": 4.0,     # Security is important
        "complexity": 1.5,
        "style": 1.0,
        "docstring": 0.5,
        "oss_patterns": 1.5,      # OSS pattern alignment — advisory
    })

    all_passed_bonus: float = 0.15    # +15% if every validator passes
    critical_error_penalty: float = 0.5  # ×0.5 per critical failure

    def get(self, validator_name: str) -> float:
        # Exact match first, then prefix match, then default
        if validator_name in self.weights:
            return self.weights[validator_name]
        for prefix, w in self.weights.items():
            if validator_name.startswith(prefix):
                return w
        return 1.0


class CandidateSelector:
    """Score and rank candidates, return the best one."""

    def __init__(self, scoring: Optional[ScoringWeights] = None):
        self.scoring = scoring or ScoringWeights()

    def select(self, pool: CandidatePool) -> Candidate:
        """
        Score all candidates and mark the best as SELECTED.

        Returns the winning Candidate.
        Raises ValueError if pool is empty.
        """
        if not pool.candidates:
            raise ValueError("Empty candidate pool")

        for candidate in pool.candidates:
            self._score(candidate)

        ranked = sorted(pool.candidates, key=lambda c: c.total_score, reverse=True)

        winner = ranked[0]
        winner.status = CandidateStatus.SELECTED
        pool.best = winner

        for c in ranked[1:]:
            c.status = CandidateStatus.REJECTED

        logger.info(
            "[Selector] winner: #%d (score=%.4f, %d validators, %s errors)",
            winner.id,
            winner.total_score,
            len(winner.validation_scores),
            "has" if winner.has_critical_errors else "no",
        )

        if len(ranked) > 1:
            runner_up = ranked[1]
            logger.debug(
                "[Selector] runner-up: #%d (score=%.4f)",
                runner_up.id,
                runner_up.total_score,
            )

        return winner

    def rank(self, pool: CandidatePool) -> List[Candidate]:
        """Return all candidates sorted best-first, without modifying status."""
        for c in pool.candidates:
            self._score(c)
        return sorted(pool.candidates, key=lambda c: c.total_score, reverse=True)

    # ------------------------------------------------------------------

    def _score(self, candidate: Candidate) -> None:
        """Compute total_score for one candidate."""
        if not candidate.validation_scores:
            candidate.total_score = 0.0
            return

        weighted_sum = 0.0
        weight_total = 0.0

        for vs in candidate.validation_scores:
            w = self.scoring.get(vs.validator_name)
            weighted_sum += vs.score * w
            weight_total += w

        base = weighted_sum / weight_total if weight_total > 0 else 0.0

        # Bonus for clean sweep
        if candidate.all_passed:
            base = min(1.0, base + self.scoring.all_passed_bonus)

        # Penalty for critical errors
        n_critical = sum(
            1 for s in candidate.validation_scores if not s.passed and s.errors
        )
        if n_critical:
            base *= self.scoring.critical_error_penalty ** n_critical

        candidate.total_score = round(base, 6)
