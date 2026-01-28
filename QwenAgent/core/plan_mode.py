"""
QwenCode Plan Mode - Structured Planning System
Like Claude Code's EnterPlanMode / ExitPlanMode
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
import json


class PlanPhase(Enum):
    """Phases of planning"""
    EXPLORING = "exploring"      # Gathering information
    DESIGNING = "designing"      # Creating the plan
    REVIEWING = "reviewing"      # Plan ready for review
    APPROVED = "approved"        # Plan approved
    EXECUTING = "executing"      # Implementing plan
    COMPLETED = "completed"      # Plan executed


@dataclass
class PlanStep:
    """A single step in the plan"""
    number: int
    title: str
    description: str
    files: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, completed, skipped
    notes: str = ""


@dataclass
class Plan:
    """A structured implementation plan"""
    id: str
    title: str
    objective: str
    phase: PlanPhase = PlanPhase.EXPLORING
    steps: List[PlanStep] = field(default_factory=list)
    critical_files: List[str] = field(default_factory=list)
    considerations: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    approved_at: Optional[datetime] = None


class PlanMode:
    """
    Plan Mode Manager
    Handles structured planning workflow like Claude Code
    """

    def __init__(self):
        self.active_plan: Optional[Plan] = None
        self.plan_history: List[Plan] = []
        self.is_active: bool = False
        self._plan_counter = 0

    def enter(self, objective: str = None) -> Dict[str, Any]:
        """
        Enter plan mode - start structured planning
        Like Claude Code's EnterPlanMode
        """
        if self.is_active:
            return {
                "success": False,
                "error": "Already in plan mode. Exit first or continue current plan."
            }

        self._plan_counter += 1
        plan_id = f"plan-{self._plan_counter}"

        self.active_plan = Plan(
            id=plan_id,
            title="",
            objective=objective or ""
        )
        self.is_active = True

        return {
            "success": True,
            "plan_id": plan_id,
            "message": "Entered plan mode. Explore the codebase and design your implementation plan.",
            "phase": PlanPhase.EXPLORING.value,
            "instructions": """
Plan Mode Active. Follow these steps:
1. EXPLORE: Use glob, grep, read to understand the codebase
2. DESIGN: Create step-by-step implementation plan
3. REVIEW: Present plan for approval
4. EXIT: Use exit_plan_mode() when ready for approval

Available in plan mode:
- Read files (read, glob, grep)
- Explore structure (ls, tree)
- Search (web_search, web_fetch)
- NO file modifications until plan is approved
"""
        }

    def exit(self) -> Dict[str, Any]:
        """
        Exit plan mode and request approval
        Like Claude Code's ExitPlanMode
        """
        if not self.is_active:
            return {
                "success": False,
                "error": "Not in plan mode"
            }

        if not self.active_plan.steps:
            return {
                "success": False,
                "error": "Plan has no steps. Add steps before exiting."
            }

        self.active_plan.phase = PlanPhase.REVIEWING

        plan_summary = self._format_plan_summary()

        return {
            "success": True,
            "plan_id": self.active_plan.id,
            "message": "Plan ready for review",
            "plan_summary": plan_summary,
            "awaiting_approval": True
        }

    def approve(self) -> Dict[str, Any]:
        """Approve the current plan"""
        if not self.is_active or not self.active_plan:
            return {"success": False, "error": "No active plan to approve"}

        self.active_plan.phase = PlanPhase.APPROVED
        self.active_plan.approved_at = datetime.now()
        self.is_active = False

        # Move to history
        self.plan_history.append(self.active_plan)
        approved_plan = self.active_plan
        self.active_plan = None

        return {
            "success": True,
            "plan_id": approved_plan.id,
            "message": "Plan approved! Ready to implement.",
            "steps_count": len(approved_plan.steps)
        }

    def reject(self, reason: str = None) -> Dict[str, Any]:
        """Reject and discard the current plan"""
        if not self.is_active:
            return {"success": False, "error": "No active plan"}

        plan_id = self.active_plan.id
        self.active_plan = None
        self.is_active = False

        return {
            "success": True,
            "plan_id": plan_id,
            "message": "Plan rejected and discarded",
            "reason": reason
        }

    def set_title(self, title: str) -> Dict[str, Any]:
        """Set plan title"""
        if not self.active_plan:
            return {"success": False, "error": "No active plan"}

        self.active_plan.title = title
        return {"success": True, "title": title}

    def set_objective(self, objective: str) -> Dict[str, Any]:
        """Set plan objective"""
        if not self.active_plan:
            return {"success": False, "error": "No active plan"}

        self.active_plan.objective = objective
        return {"success": True, "objective": objective}

    def add_step(self, title: str, description: str, files: List[str] = None) -> Dict[str, Any]:
        """Add a step to the plan"""
        if not self.active_plan:
            return {"success": False, "error": "No active plan"}

        step_num = len(self.active_plan.steps) + 1
        step = PlanStep(
            number=step_num,
            title=title,
            description=description,
            files=files or []
        )

        self.active_plan.steps.append(step)
        self.active_plan.phase = PlanPhase.DESIGNING

        return {
            "success": True,
            "step_number": step_num,
            "title": title
        }

    def add_critical_file(self, file_path: str) -> Dict[str, Any]:
        """Mark a file as critical for the plan"""
        if not self.active_plan:
            return {"success": False, "error": "No active plan"}

        if file_path not in self.active_plan.critical_files:
            self.active_plan.critical_files.append(file_path)

        return {
            "success": True,
            "critical_files": self.active_plan.critical_files
        }

    def add_consideration(self, text: str) -> Dict[str, Any]:
        """Add architectural consideration"""
        if not self.active_plan:
            return {"success": False, "error": "No active plan"}

        self.active_plan.considerations.append(text)
        return {"success": True, "considerations_count": len(self.active_plan.considerations)}

    def add_risk(self, text: str) -> Dict[str, Any]:
        """Add identified risk"""
        if not self.active_plan:
            return {"success": False, "error": "No active plan"}

        self.active_plan.risks.append(text)
        return {"success": True, "risks_count": len(self.active_plan.risks)}

    def get_status(self) -> Dict[str, Any]:
        """Get current plan mode status"""
        if not self.is_active:
            return {
                "active": False,
                "message": "Not in plan mode"
            }

        return {
            "active": True,
            "plan_id": self.active_plan.id,
            "phase": self.active_plan.phase.value,
            "title": self.active_plan.title,
            "objective": self.active_plan.objective,
            "steps_count": len(self.active_plan.steps),
            "critical_files": len(self.active_plan.critical_files)
        }

    def _format_plan_summary(self) -> str:
        """Format plan as readable summary"""
        if not self.active_plan:
            return ""

        lines = [
            f"# {self.active_plan.title or 'Implementation Plan'}",
            "",
            f"**Objective:** {self.active_plan.objective}",
            "",
            "## Steps",
            ""
        ]

        for step in self.active_plan.steps:
            lines.append(f"### Step {step.number}: {step.title}")
            lines.append(step.description)
            if step.files:
                lines.append(f"Files: {', '.join(step.files)}")
            lines.append("")

        if self.active_plan.critical_files:
            lines.append("## Critical Files")
            for f in self.active_plan.critical_files:
                lines.append(f"- {f}")
            lines.append("")

        if self.active_plan.considerations:
            lines.append("## Considerations")
            for c in self.active_plan.considerations:
                lines.append(f"- {c}")
            lines.append("")

        if self.active_plan.risks:
            lines.append("## Risks")
            for r in self.active_plan.risks:
                lines.append(f"- {r}")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Export plan as dictionary"""
        if not self.active_plan:
            return {}

        return {
            "id": self.active_plan.id,
            "title": self.active_plan.title,
            "objective": self.active_plan.objective,
            "phase": self.active_plan.phase.value,
            "steps": [
                {
                    "number": s.number,
                    "title": s.title,
                    "description": s.description,
                    "files": s.files,
                    "status": s.status
                }
                for s in self.active_plan.steps
            ],
            "critical_files": self.active_plan.critical_files,
            "considerations": self.active_plan.considerations,
            "risks": self.active_plan.risks
        }
