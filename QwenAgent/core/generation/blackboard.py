"""
Week 21: Candidate Blackboard — Shared Knowledge Between Iterations

Stigmergy-inspired: candidates "leave traces" (good/bad patterns) that
subsequent iterations read.  This prevents the "correction regression"
problem where fixing one error introduces another.

Usage:
    bb = CandidateBlackboard()
    bb.extract_from_candidate(candidate)   # after validation
    hints = bb.build_hints_prompt()         # inject into correction prompt
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class BlackboardEntry:
    """A single piece of knowledge extracted from a validated candidate."""

    source_candidate_id: int
    source_iteration: int
    entry_type: str         # "good_pattern" | "bad_pattern" | "recurring_error"
    validator_name: str
    content: str
    confidence: float = 0.8


class CandidateBlackboard:
    """Shared knowledge accumulator across candidates and correction iterations.

    Good patterns:  "Validator X passed" — things to KEEP.
    Bad patterns:   "Validator Y failed: <error>" — things to AVOID.
    Recurring:      Same validator fails across iterations — cognitive blindness.
    """

    def __init__(self, max_entries: int = 50):
        self.entries: List[BlackboardEntry] = []
        self._max_entries = max_entries
        self._error_counts: Dict[str, int] = {}  # validator → fail count

    @property
    def size(self) -> int:
        return len(self.entries)

    def extract_from_candidate(
        self,
        candidate,
        iteration: int = 0,
    ) -> int:
        """Extract good/bad patterns from a validated candidate.

        Args:
            candidate: Candidate with validation_scores populated.
            iteration: Current correction iteration number.

        Returns:
            Number of entries added.
        """
        added = 0
        if not hasattr(candidate, "validation_scores"):
            return 0

        for vs in candidate.validation_scores:
            if vs.passed:
                self._add(BlackboardEntry(
                    source_candidate_id=candidate.id,
                    source_iteration=iteration,
                    entry_type="good_pattern",
                    validator_name=vs.validator_name,
                    content=f"Validator '{vs.validator_name}' passed (score={vs.score:.2f})",
                    confidence=0.8,
                ))
                added += 1
            else:
                for err in vs.errors[:3]:  # Cap per-validator errors
                    self._add(BlackboardEntry(
                        source_candidate_id=candidate.id,
                        source_iteration=iteration,
                        entry_type="bad_pattern",
                        validator_name=vs.validator_name,
                        content=f"[{vs.validator_name}] {err}",
                        confidence=0.9,
                    ))
                    added += 1
                # Track recurring failures
                self._error_counts[vs.validator_name] = \
                    self._error_counts.get(vs.validator_name, 0) + 1

        return added

    def get_recurring_errors(self, min_occurrences: int = 2) -> List[str]:
        """Find validators that fail across multiple iterations/candidates."""
        return [
            f"{name} (failed {count}x)"
            for name, count in sorted(
                self._error_counts.items(), key=lambda x: x[1], reverse=True
            )
            if count >= min_occurrences
        ]

    def build_hints_prompt(self, max_good: int = 5, max_bad: int = 8) -> str:
        """Generate a prompt section with accumulated knowledge.

        Returns empty string if no entries exist.
        """
        if not self.entries:
            return ""

        good = self._unique_entries("good_pattern")
        bad = self._unique_entries("bad_pattern")
        recurring = self.get_recurring_errors()

        parts: List[str] = []

        if recurring:
            parts.append(
                "RECURRING ISSUES (these keep appearing — pay special attention):"
            )
            for r in recurring[:5]:
                parts.append(f"  ⚠ {r}")
            parts.append("")

        if bad:
            parts.append("AVOID these issues found in previous attempts:")
            for b in bad[:max_bad]:
                parts.append(f"  ✗ {b}")
            parts.append("")

        if good:
            parts.append("KEEP these good patterns from previous attempts:")
            for g in good[:max_good]:
                parts.append(f"  ✓ {g}")
            parts.append("")

        return "\n".join(parts)

    def clear(self) -> None:
        """Reset the blackboard."""
        self.entries.clear()
        self._error_counts.clear()

    def to_dict(self) -> dict:
        """Serialize for SSE/REST."""
        return {
            "total_entries": len(self.entries),
            "good_patterns": len(self._unique_entries("good_pattern")),
            "bad_patterns": len(self._unique_entries("bad_pattern")),
            "recurring_errors": self.get_recurring_errors(),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _add(self, entry: BlackboardEntry) -> None:
        self.entries.append(entry)
        # Evict oldest if over limit
        if len(self.entries) > self._max_entries:
            self.entries = self.entries[-self._max_entries:]

    def _unique_entries(self, entry_type: str) -> List[str]:
        """Return deduplicated content strings for a given type."""
        seen: Set[str] = set()
        result: List[str] = []
        for e in self.entries:
            if e.entry_type == entry_type and e.content not in seen:
                seen.add(e.content)
                result.append(e.content)
        return result
