"""
Adaptive Temperature & Smart Candidate Count (Week 4).

Classifies task complexity and adapts (n_candidates, temperatures) accordingly.
Trivial tasks get 1 candidate (~24s), complex/critical get 3 (~72s).

Learning from history: after 5+ outcomes for a complexity level, the strategy
may upgrade/downgrade the number of candidates based on observed scores.

Usage:
    strategy = AdaptiveStrategy()
    config = strategy.get_strategy("write hello world")
    # config.n_candidates == 1, config.temperatures == (0.2,)

    config = strategy.get_strategy("implement JWT auth middleware")
    # config.n_candidates == 3, config.temperatures == (0.1, 0.4, 0.7)
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class CodegenComplexity(Enum):
    """Task complexity levels for code generation."""
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    CRITICAL = "critical"


@dataclass
class AdaptiveConfig:
    """Strategy decision for a single code-gen request."""
    n_candidates: int
    temperatures: Tuple[float, ...]
    complexity: CodegenComplexity
    reasoning: str
    confidence: float
    estimated_time_seconds: float


@dataclass
class StrategyOutcome:
    """Recorded outcome of a pipeline run with adaptive config."""
    timestamp: float
    query_hash: str
    complexity: str  # CodegenComplexity.value
    n_candidates: int
    temperatures: Tuple[float, ...]
    best_score: float
    all_passed: bool
    total_time: float
    swecas_code: Optional[int] = None


# ---------------------------------------------------------------------------
# Default strategy table
# ---------------------------------------------------------------------------

_DEFAULT_STRATEGIES: Dict[CodegenComplexity, Tuple[int, Tuple[float, ...]]] = {
    CodegenComplexity.TRIVIAL:  (1, (0.2,)),
    CodegenComplexity.SIMPLE:   (1, (0.3,)),
    CodegenComplexity.MODERATE: (2, (0.2, 0.6)),
    CodegenComplexity.COMPLEX:  (3, (0.2, 0.5, 0.8)),
    CodegenComplexity.CRITICAL: (3, (0.1, 0.4, 0.7)),
}

# Estimated time per candidate (seconds) — single GPU 7B model
_TIME_PER_CANDIDATE = 24.0


# ---------------------------------------------------------------------------
# Keyword patterns for classification
# ---------------------------------------------------------------------------

_CRITICAL_KEYWORDS = re.compile(
    r"\b(auth|encrypt|decrypt|jwt|token|security|password|hash|"
    r"credential|oauth|ssl|tls|certificate|race\s*condition|mutex|"
    r"lock|semaphore|deadlock|crypto|secret|sanitiz|injection|xss)\b",
    re.IGNORECASE,
)

_COMPLEX_KEYWORDS = re.compile(
    r"\b(middleware|parser|design\s*pattern|api|database|orm|"
    r"websocket|microservice|pipeline|scheduler|queue|cache\s*system|"
    r"state\s*machine|compiler|interpreter|protocol|distributed|"
    r"algorithm|tree|graph\s*traversal|dynamic\s*programming)\b",
    re.IGNORECASE,
)

_TRIVIAL_KEYWORDS = re.compile(
    r"\b(hello\s*world|fizzbuzz|print|add\s*two\s*numbers|"
    r"sum\s*of|swap\s*two|reverse\s*string|palindrome|"
    r"even\s*or\s*odd|factorial\s*simple|fibonacci\s*simple|"
    r"count\s*vowels|celsius\s*to|fahrenheit\s*to)\b",
    re.IGNORECASE,
)

_SIMPLE_KEYWORDS = re.compile(
    r"\b(sort|filter|map|reduce|validate\s*email|"
    r"read\s*file|write\s*file|format|convert|parse\s*json|"
    r"calculate|counter|iterate|list\s*comprehension)\b",
    re.IGNORECASE,
)

# SWECAS security codes
_SECURITY_SWECAS_RANGE = range(500, 600)


# ---------------------------------------------------------------------------
# AdaptiveStrategy
# ---------------------------------------------------------------------------

class AdaptiveStrategy:
    """
    Classifies code-gen task complexity and selects optimal
    (n_candidates, temperatures) for the multi-candidate pipeline.

    Learns from history to adjust moderate/complex strategies.
    """

    MAX_HISTORY = 200

    def __init__(
        self,
        history_path: Optional[str] = None,
        persist: bool = True,
    ):
        self._persist = persist
        self._history_path = Path(history_path) if history_path else None
        self._history: List[StrategyOutcome] = []

        # Mutable copy of strategies (learning can modify these)
        self._strategies: Dict[CodegenComplexity, Tuple[int, Tuple[float, ...]]] = dict(
            _DEFAULT_STRATEGIES
        )

        if self._persist and self._history_path:
            self._load_history()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_complexity(
        self,
        query: str,
        swecas_code: Optional[int] = None,
    ) -> CodegenComplexity:
        """Classify a query into a complexity level."""
        # SWECAS security codes override everything
        if swecas_code is not None and swecas_code in _SECURITY_SWECAS_RANGE:
            return CodegenComplexity.CRITICAL

        # Keyword-based classification (highest match wins)
        if _CRITICAL_KEYWORDS.search(query):
            return CodegenComplexity.CRITICAL
        if _COMPLEX_KEYWORDS.search(query):
            return CodegenComplexity.COMPLEX
        if _TRIVIAL_KEYWORDS.search(query):
            return CodegenComplexity.TRIVIAL
        if _SIMPLE_KEYWORDS.search(query):
            return CodegenComplexity.SIMPLE

        # Fallback: use query length as a rough proxy
        word_count = len(query.split())
        if word_count <= 8:
            return CodegenComplexity.SIMPLE
        if word_count <= 20:
            return CodegenComplexity.MODERATE
        return CodegenComplexity.COMPLEX

    def get_strategy(
        self,
        query: str,
        swecas_code: Optional[int] = None,
    ) -> AdaptiveConfig:
        """Get the optimal strategy for a code-gen task."""
        complexity = self.classify_complexity(query, swecas_code)
        n_candidates, temperatures = self._strategies[complexity]

        reasoning = f"Classified as {complexity.value}"
        if swecas_code is not None and swecas_code in _SECURITY_SWECAS_RANGE:
            reasoning += f" (SWECAS {swecas_code} = security)"

        return AdaptiveConfig(
            n_candidates=n_candidates,
            temperatures=temperatures,
            complexity=complexity,
            reasoning=reasoning,
            confidence=self._confidence(complexity, query),
            estimated_time_seconds=n_candidates * _TIME_PER_CANDIDATE,
        )

    def record_outcome(
        self,
        config: AdaptiveConfig,
        best_score: float,
        all_passed: bool,
        total_time: float,
        query: str = "",
        swecas_code: Optional[int] = None,
    ) -> None:
        """Record the outcome of a pipeline run for learning."""
        outcome = StrategyOutcome(
            timestamp=time.time(),
            query_hash=hashlib.md5(query.encode()).hexdigest()[:12],
            complexity=config.complexity.value,
            n_candidates=config.n_candidates,
            temperatures=config.temperatures,
            best_score=best_score,
            all_passed=all_passed,
            total_time=total_time,
            swecas_code=swecas_code,
        )
        self._history.append(outcome)

        # Cap history
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

        # Attempt learning
        self._learn(config.complexity)

        if self._persist and self._history_path:
            self._save_history()

    def get_stats(self) -> Dict[str, Any]:
        """Return statistics for /api/stats."""
        if not self._history:
            return {
                "total_outcomes": 0,
                "complexity_distribution": {},
                "current_strategies": {
                    c.value: {"n": n, "temps": list(t)}
                    for c, (n, t) in self._strategies.items()
                },
            }

        dist: Dict[str, int] = {}
        score_sums: Dict[str, float] = {}
        for o in self._history:
            dist[o.complexity] = dist.get(o.complexity, 0) + 1
            score_sums[o.complexity] = score_sums.get(o.complexity, 0) + o.best_score

        avg_scores = {
            k: round(score_sums[k] / dist[k], 4) for k in dist
        }

        return {
            "total_outcomes": len(self._history),
            "complexity_distribution": dist,
            "avg_scores": avg_scores,
            "current_strategies": {
                c.value: {"n": n, "temps": list(t)}
                for c, (n, t) in self._strategies.items()
            },
        }

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def _learn(self, complexity: CodegenComplexity) -> None:
        """Adjust strategy based on accumulated outcomes."""
        # CRITICAL and TRIVIAL are never changed by learning
        if complexity in (CodegenComplexity.CRITICAL, CodegenComplexity.TRIVIAL):
            return

        outcomes = [o for o in self._history if o.complexity == complexity.value]
        if len(outcomes) < 5:
            return

        recent = outcomes[-10:]  # Use last 10 for learning
        avg_score = sum(o.best_score for o in recent) / len(recent)
        pass_rate = sum(1 for o in recent if o.all_passed) / len(recent)

        current_n, current_temps = self._strategies[complexity]
        defaults_n, defaults_temps = _DEFAULT_STRATEGIES[complexity]

        if avg_score > 0.9 and pass_rate > 0.9 and current_n > 1:
            # Doing great — can reduce candidates
            new_n = max(1, current_n - 1)
            new_temps = current_temps[:new_n]
            self._strategies[complexity] = (new_n, new_temps)
            logger.info(
                "[Adaptive] Downgraded %s: n=%d→%d (avg_score=%.2f, pass_rate=%.2f)",
                complexity.value, current_n, new_n, avg_score, pass_rate,
            )
        elif (avg_score < 0.7 or pass_rate < 0.7) and current_n < 3:
            # Struggling — add more candidates
            new_n = min(3, current_n + 1)
            # Extend temperatures from defaults
            new_temps = _DEFAULT_STRATEGIES.get(
                CodegenComplexity.COMPLEX, (3, (0.2, 0.5, 0.8))
            )[1][:new_n]
            self._strategies[complexity] = (new_n, new_temps)
            logger.info(
                "[Adaptive] Upgraded %s: n=%d→%d (avg_score=%.2f, pass_rate=%.2f)",
                complexity.value, current_n, new_n, avg_score, pass_rate,
            )

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    def _confidence(self, complexity: CodegenComplexity, query: str) -> float:
        """Estimate confidence in the classification."""
        # Strong keyword match → high confidence
        if complexity == CodegenComplexity.CRITICAL and _CRITICAL_KEYWORDS.search(query):
            return 0.95
        if complexity == CodegenComplexity.TRIVIAL and _TRIVIAL_KEYWORDS.search(query):
            return 0.95
        if complexity == CodegenComplexity.COMPLEX and _COMPLEX_KEYWORDS.search(query):
            return 0.85
        if complexity == CodegenComplexity.SIMPLE and _SIMPLE_KEYWORDS.search(query):
            return 0.80
        # Fallback classification
        return 0.60

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_history(self) -> None:
        """Load history from JSON file."""
        if not self._history_path or not self._history_path.exists():
            return
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
            self._history = [
                StrategyOutcome(
                    timestamp=r["timestamp"],
                    query_hash=r["query_hash"],
                    complexity=r["complexity"],
                    n_candidates=r["n_candidates"],
                    temperatures=tuple(r["temperatures"]),
                    best_score=r["best_score"],
                    all_passed=r["all_passed"],
                    total_time=r["total_time"],
                    swecas_code=r.get("swecas_code"),
                )
                for r in data
            ]
            logger.info("[Adaptive] Loaded %d history records", len(self._history))
        except Exception as e:
            logger.warning("[Adaptive] Failed to load history: %s", e)

    def _save_history(self) -> None:
        """Save history to JSON file."""
        if not self._history_path:
            return
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {
                    "timestamp": o.timestamp,
                    "query_hash": o.query_hash,
                    "complexity": o.complexity,
                    "n_candidates": o.n_candidates,
                    "temperatures": list(o.temperatures),
                    "best_score": o.best_score,
                    "all_passed": o.all_passed,
                    "total_time": o.total_time,
                    "swecas_code": o.swecas_code,
                }
                for o in self._history
            ]
            self._history_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8",
            )
        except Exception as e:
            logger.warning("[Adaptive] Failed to save history: %s", e)
