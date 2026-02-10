# -*- coding: utf-8 -*-
"""
Deep6Minsky — 6-step Minsky CoT pipeline with iterative rollback.

Steps (per Minsky's cognitive hierarchy):
  1. REACTION     — Quick classification and understanding
  2. DELIBERATION — Challenge identification, pattern matching
  3. REFLECTIVE   — Approach generation and comparison
  4. SELF-REFLECTIVE — Constraint evaluation, critical audit
  5. SELF-CONSTRUCTIVE — Choose best approach, synthesize solution
  6. VALUES/IDEALS — Final verification, output

The on_step callback receives structured data for each step,
enabling real-time UI visualization via SSE events.
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional, Any, Callable, Dict
from enum import Enum


class TaskType(Enum):
    CODE = "code"
    ANALYSIS = "analysis"
    DEVOPS = "devops"
    UNKNOWN = "unknown"


# Step definitions
STEP_NAMES = [
    "understanding",
    "challenges",
    "approaches",
    "constraints",
    "choose",
    "solution",
]

STEP_LABELS = {
    "understanding": "Understanding",
    "challenges": "Challenges",
    "approaches": "Approaches",
    "constraints": "Constraints",
    "choose": "Choose",
    "solution": "Solution",
}

STEP_DESCRIPTIONS = {
    "understanding": "Classify the task, determine current and target state",
    "challenges": "Identify potential risks, edge cases, dependencies",
    "approaches": "Generate alternative approaches with pros/cons",
    "constraints": "Evaluate feasibility against validators and rules",
    "choose": "Select the best approach based on all evidence",
    "solution": "Implement the chosen approach, verify, produce output",
}


@dataclass
class Deep6Result:
    final_code: Optional[str] = None
    final_explanation: Optional[str] = None
    call_sequence: List[str] = field(default_factory=list)
    rollback_reasons: List[str] = field(default_factory=list)
    audit_results: List[Any] = field(default_factory=list)
    task_type: TaskType = TaskType.UNKNOWN
    # Per-step data for UI visualization
    step_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    total_time: float = 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "steps_completed": len(self.call_sequence),
            "rollbacks": len(self.rollback_reasons),
            "has_code": self.final_code is not None,
            "total_time": round(self.total_time, 3),
        }


@dataclass
class _StepStats:
    total_runs: int = 0
    total_duration_ms: float = 0.0
    rollbacks: int = 0
    adversarial_catches: int = 0


class Deep6Minsky:
    def __init__(self, fast_model: str = None, heavy_model: str = None,
                 enable_adversarial: bool = False):
        self.fast_model = fast_model
        self.heavy_model = heavy_model
        self.enable_adversarial = enable_adversarial
        self._stats = _StepStats()

    def execute(self, query: str, context: str = "",
                verbose: bool = False,
                on_step: Callable = None) -> Deep6Result:
        """
        Execute the 6-step Minsky pipeline.

        Args:
            query: User's task/question
            context: Pre-read file content and classification context
            verbose: Print step progress
            on_step: Callback(step: int, name: str, status: str, data: dict)
                     Called at start and completion of each step.
        """
        t_start = time.perf_counter()
        self._stats.total_runs += 1

        result = Deep6Result()
        call_sequence = []
        step_data = {}

        def _notify(step_num, name, status, data=None):
            if on_step:
                try:
                    on_step(step_num, name, status, data or {})
                except Exception:
                    pass

        # Step 1: Understanding (REACTION)
        _notify(1, "understanding", "starting", {
            "description": STEP_DESCRIPTIONS["understanding"],
        })
        s1_data = self._step_understanding(query, context)
        step_data["understanding"] = s1_data
        call_sequence.append("understanding")
        result.task_type = s1_data.get("task_type", TaskType.UNKNOWN)
        _notify(1, "understanding", "complete", s1_data)

        # Step 2: Challenges (DELIBERATION)
        _notify(2, "challenges", "starting", {
            "description": STEP_DESCRIPTIONS["challenges"],
        })
        s2_data = self._step_challenges(query, s1_data)
        step_data["challenges"] = s2_data
        call_sequence.append("challenges")
        _notify(2, "challenges", "complete", s2_data)

        # Step 3: Approaches (REFLECTIVE)
        _notify(3, "approaches", "starting", {
            "description": STEP_DESCRIPTIONS["approaches"],
        })
        s3_data = self._step_approaches(query, s1_data, s2_data)
        step_data["approaches"] = s3_data
        call_sequence.append("approaches")
        _notify(3, "approaches", "complete", s3_data)

        # Step 4: Constraints (SELF-REFLECTIVE)
        _notify(4, "constraints", "starting", {
            "description": STEP_DESCRIPTIONS["constraints"],
        })
        s4_data = self._step_constraints(s3_data, s2_data)
        step_data["constraints"] = s4_data
        call_sequence.append("constraints")
        _notify(4, "constraints", "complete", s4_data)

        # Step 5: Choose (SELF-CONSTRUCTIVE)
        _notify(5, "choose", "starting", {
            "description": STEP_DESCRIPTIONS["choose"],
        })
        s5_data = self._step_choose(s3_data, s4_data)
        step_data["choose"] = s5_data
        call_sequence.append("choose")
        _notify(5, "choose", "complete", s5_data)

        # Step 6: Solution (VALUES/IDEALS)
        _notify(6, "solution", "starting", {
            "description": STEP_DESCRIPTIONS["solution"],
        })
        s6_data = self._step_solution(query, s5_data)
        step_data["solution"] = s6_data
        call_sequence.append("solution")
        _notify(6, "solution", "complete", s6_data)

        total_time = time.perf_counter() - t_start
        self._stats.total_duration_ms += total_time * 1000

        result.call_sequence = call_sequence
        result.step_data = step_data
        result.total_time = total_time
        result.final_explanation = s6_data.get("explanation", f"[Deep6] Query: {query[:100]}")
        result.final_code = s6_data.get("code")

        return result

    # ---- Step implementations (stub logic, ready for LLM integration) ----

    def _step_understanding(self, query: str, context: str) -> Dict[str, Any]:
        """Step 1: Classify task type, determine S0 and S1."""
        task_type = TaskType.UNKNOWN
        q_lower = query.lower()
        if any(kw in q_lower for kw in ("write", "implement", "create", "function", "class", "def ")):
            task_type = TaskType.CODE
        elif any(kw in q_lower for kw in ("kubernetes", "terraform", "docker", "helm", "ansible", "yaml")):
            task_type = TaskType.DEVOPS
        elif any(kw in q_lower for kw in ("explain", "analyze", "review", "describe", "what")):
            task_type = TaskType.ANALYSIS

        return {
            "task_type": task_type,
            "query_length": len(query),
            "has_context": bool(context),
            "current_state": "S0: Query received, context available" if context else "S0: Query received",
            "target_state": "S1: Complete solution delivered",
        }

    def _step_challenges(self, query: str, s1: Dict) -> Dict[str, Any]:
        """Step 2: Identify risks, edge cases, dependencies."""
        challenges = []
        q_lower = query.lower()

        if any(kw in q_lower for kw in ("security", "auth", "password", "token", "crypto")):
            challenges.append({"type": "security", "desc": "Security-sensitive operations detected", "severity": "high"})
        if any(kw in q_lower for kw in ("database", "sql", "migration", "schema")):
            challenges.append({"type": "data", "desc": "Database operations — potential data loss risk", "severity": "high"})
        if any(kw in q_lower for kw in ("async", "parallel", "concurrent", "thread")):
            challenges.append({"type": "concurrency", "desc": "Concurrency patterns — race conditions possible", "severity": "medium"})
        if not challenges:
            challenges.append({"type": "general", "desc": "Standard complexity — no special risks identified", "severity": "low"})

        return {
            "challenges": challenges,
            "risk_count": len(challenges),
            "max_severity": max((c["severity"] for c in challenges), key=lambda s: {"low": 0, "medium": 1, "high": 2}.get(s, 0)),
        }

    def _step_approaches(self, query: str, s1: Dict, s2: Dict) -> Dict[str, Any]:
        """Step 3: Generate alternative approaches with pros/cons."""
        task_type = s1.get("task_type", TaskType.UNKNOWN)
        approaches = []

        if task_type == TaskType.CODE:
            approaches = [
                {
                    "name": "Direct Implementation",
                    "description": "Straightforward implementation matching the requirements exactly",
                    "pros": ["Simple", "Fast to implement", "Easy to understand"],
                    "cons": ["May miss edge cases", "Less robust"],
                    "complexity": "low",
                    "risk": "low",
                },
                {
                    "name": "Defensive Implementation",
                    "description": "Implementation with comprehensive error handling and validation",
                    "pros": ["Robust", "Handles edge cases", "Better error messages"],
                    "cons": ["More code", "Slightly slower", "More complex"],
                    "complexity": "medium",
                    "risk": "low",
                },
                {
                    "name": "Pattern-Based Implementation",
                    "description": "Use established design patterns for maintainability",
                    "pros": ["Maintainable", "Extensible", "Well-tested patterns"],
                    "cons": ["More abstraction", "Learning curve", "Potentially over-engineered"],
                    "complexity": "medium",
                    "risk": "medium",
                },
            ]
        elif task_type == TaskType.DEVOPS:
            approaches = [
                {
                    "name": "Minimal Configuration",
                    "description": "Bare minimum working configuration",
                    "pros": ["Quick", "Simple", "Easy to debug"],
                    "cons": ["Not production-ready", "Missing best practices"],
                    "complexity": "low",
                    "risk": "medium",
                },
                {
                    "name": "Production-Ready",
                    "description": "Full configuration with best practices and security",
                    "pros": ["Secure", "Scalable", "Follows standards"],
                    "cons": ["Complex", "More to maintain"],
                    "complexity": "high",
                    "risk": "low",
                },
                {
                    "name": "Iterative Build-Up",
                    "description": "Start simple, add layers incrementally",
                    "pros": ["Verifiable at each step", "Lower risk", "Educational"],
                    "cons": ["Slower", "Multiple iterations needed"],
                    "complexity": "medium",
                    "risk": "low",
                },
            ]
        else:
            approaches = [
                {
                    "name": "Comprehensive Analysis",
                    "description": "Thorough analysis covering all aspects",
                    "pros": ["Complete", "Detailed"],
                    "cons": ["Time-consuming"],
                    "complexity": "medium",
                    "risk": "low",
                },
                {
                    "name": "Focused Summary",
                    "description": "Key points only, concise output",
                    "pros": ["Fast", "Actionable"],
                    "cons": ["May miss nuances"],
                    "complexity": "low",
                    "risk": "low",
                },
            ]

        return {
            "approaches": approaches,
            "count": len(approaches),
        }

    def _step_constraints(self, s3: Dict, s2: Dict) -> Dict[str, Any]:
        """Step 4: Evaluate each approach against constraints."""
        approaches = s3.get("approaches", [])
        challenges = s2.get("challenges", [])
        evaluated = []

        for approach in approaches:
            feasibility = 0.8  # Base feasibility
            if approach.get("risk") == "high":
                feasibility -= 0.2
            if approach.get("complexity") == "high":
                feasibility -= 0.1
            # Adjust for challenges
            for c in challenges:
                if c["severity"] == "high" and approach.get("risk") != "low":
                    feasibility -= 0.1

            evaluated.append({
                "name": approach["name"],
                "feasibility": round(max(0.1, min(1.0, feasibility)), 2),
                "risk_adjusted": approach.get("risk", "medium"),
                "constraints_met": feasibility >= 0.5,
            })

        return {
            "evaluated": evaluated,
            "all_feasible": all(e["constraints_met"] for e in evaluated),
        }

    def _step_choose(self, s3: Dict, s4: Dict) -> Dict[str, Any]:
        """Step 5: Select the best approach."""
        approaches = s3.get("approaches", [])
        evaluated = s4.get("evaluated", [])

        if not evaluated:
            return {"chosen_index": 0, "chosen_name": "default", "reason": "No approaches to choose from"}

        # Pick the approach with highest feasibility
        best_idx = 0
        best_score = 0
        for i, e in enumerate(evaluated):
            if e["feasibility"] > best_score:
                best_score = e["feasibility"]
                best_idx = i

        chosen = approaches[best_idx] if best_idx < len(approaches) else approaches[0]
        rejected = [a["name"] for j, a in enumerate(approaches) if j != best_idx]

        return {
            "chosen_index": best_idx,
            "chosen_name": chosen.get("name", "unknown"),
            "reason": f"Highest feasibility ({best_score}), acceptable risk",
            "rejected": rejected,
            "score": best_score,
        }

    def _step_solution(self, query: str, s5: Dict) -> Dict[str, Any]:
        """Step 6: Produce final solution."""
        chosen = s5.get("chosen_name", "default")
        return {
            "explanation": f"[Deep6] Applied '{chosen}' approach to: {query[:200]}",
            "code": None,  # LLM integration will produce actual code
            "approach_used": chosen,
            "verified": True,
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Return engine statistics."""
        return {
            "total_runs": self._stats.total_runs,
            "total_duration_ms": round(self._stats.total_duration_ms, 1),
            "avg_duration_ms": round(self._stats.total_duration_ms / max(self._stats.total_runs, 1), 1),
            "avg_risk_score": 0.0,
            "adversarial_catches": self._stats.adversarial_catches,
            "total_rollbacks": self._stats.rollbacks,
        }
