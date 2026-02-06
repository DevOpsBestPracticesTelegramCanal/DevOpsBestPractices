"""
Data structures for the Multi-Candidate generation system.

Candidate: a single generated code variant with metadata and validation scores.
CandidatePool: a collection of candidates for one task.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum


class CandidateStatus(Enum):
    GENERATED = "generated"
    VALIDATING = "validating"
    VALIDATED = "validated"
    SELECTED = "selected"
    REJECTED = "rejected"


@dataclass
class ValidationScore:
    """Result of one validator applied to one candidate."""

    validator_name: str
    passed: bool
    score: float  # 0.0 - 1.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration: float = 0.0
    weight: float = 1.0  # importance weight for this validator

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validator": self.validator_name,
            "passed": self.passed,
            "score": self.score,
            "errors": self.errors,
            "warnings": self.warnings,
            "duration": self.duration,
            "weight": self.weight,
        }


@dataclass
class Candidate:
    """One generated code variant."""

    id: int
    task_id: str
    code: str

    # Generation parameters
    temperature: float
    seed: int
    model: str

    # Validation
    validation_scores: List[ValidationScore] = field(default_factory=list)
    total_score: float = 0.0
    status: CandidateStatus = CandidateStatus.GENERATED

    # Timing
    generated_at: datetime = field(default_factory=datetime.now)
    validated_at: Optional[datetime] = None
    generation_time: float = 0.0

    def add_validation(self, score: ValidationScore) -> None:
        """Add a validation result and recalculate total score."""
        self.validation_scores.append(score)
        self._recalculate_score()

    def _recalculate_score(self) -> None:
        if not self.validation_scores:
            self.total_score = 0.0
            return

        weighted_sum = sum(s.score * s.weight for s in self.validation_scores)
        weight_total = sum(s.weight for s in self.validation_scores)
        self.total_score = weighted_sum / weight_total if weight_total > 0 else 0.0

        # Exponential penalty for critical failures
        critical_fails = sum(
            1 for s in self.validation_scores if not s.passed and s.errors
        )
        if critical_fails > 0:
            self.total_score *= 0.5 ** critical_fails

    @property
    def has_critical_errors(self) -> bool:
        return any(not s.passed and s.errors for s in self.validation_scores)

    @property
    def all_passed(self) -> bool:
        return bool(self.validation_scores) and all(
            s.passed for s in self.validation_scores
        )

    @property
    def code_lines(self) -> int:
        return self.code.count("\n") + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "code_length": len(self.code),
            "code_lines": self.code_lines,
            "temperature": self.temperature,
            "seed": self.seed,
            "model": self.model,
            "total_score": round(self.total_score, 4),
            "status": self.status.value,
            "has_critical_errors": self.has_critical_errors,
            "all_passed": self.all_passed,
            "validation_scores": [s.to_dict() for s in self.validation_scores],
            "generation_time": round(self.generation_time, 3),
        }


@dataclass
class CandidatePool:
    """Pool of candidates for a single task."""

    task_id: str
    candidates: List[Candidate] = field(default_factory=list)
    best: Optional[Candidate] = None

    def add(self, candidate: Candidate) -> None:
        self.candidates.append(candidate)

    def select_best(self) -> Candidate:
        """Select the candidate with the highest total_score."""
        if not self.candidates:
            raise ValueError("No candidates to select from")

        ranked = sorted(self.candidates, key=lambda c: c.total_score, reverse=True)
        self.best = ranked[0]
        self.best.status = CandidateStatus.SELECTED

        for c in ranked[1:]:
            c.status = CandidateStatus.REJECTED

        return self.best

    @property
    def size(self) -> int:
        return len(self.candidates)

    def stats(self) -> Dict[str, Any]:
        if not self.candidates:
            return {"total": 0}

        scores = [c.total_score for c in self.candidates]
        return {
            "total": len(self.candidates),
            "avg_score": round(sum(scores) / len(scores), 4),
            "max_score": round(max(scores), 4),
            "min_score": round(min(scores), 4),
            "passed_count": sum(1 for c in self.candidates if c.all_passed),
            "error_count": sum(
                1 for c in self.candidates if c.has_critical_errors
            ),
            "avg_generation_time": round(
                sum(c.generation_time for c in self.candidates) / len(self.candidates),
                3,
            ),
            "best_id": self.best.id if self.best else None,
        }
