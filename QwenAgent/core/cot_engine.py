# -*- coding: utf-8 -*-
"""
QwenAgent CoT Engine - Chain-of-Thought Reasoning
Deep thinking mode for complex tasks

Phase 2 Integration: TimeBudget support for step-wise timeout management
"""

from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import time

# Import TimeBudget for Phase 2 integration
try:
    from .time_budget import TimeBudget, BudgetPresets, StepRecord
    from .budget_estimator import BudgetEstimator, create_mode_budget
    from .execution_mode import ExecutionMode
    from .user_timeout_config import UserTimeoutPreferences
    BUDGET_AVAILABLE = True
except ImportError:
    BUDGET_AVAILABLE = False


class ThinkingStep(Enum):
    UNDERSTAND = "understanding"
    PLAN = "planning"
    EXECUTE = "executing"
    VERIFY = "verifying"
    REFLECT = "reflecting"
    # DEEP3 steps
    ANALYZE = "analyze"
    # DEEP6 steps (Minsky)
    CHALLENGES = "challenges"
    APPROACHES = "approaches"
    CONSTRAINTS = "constraints"
    CHOOSE = "choose"
    SOLUTION = "solution"


@dataclass
class CoTStep:
    """Single step in Chain-of-Thought"""
    step: ThinkingStep
    thought: str
    action: Optional[str] = None
    result: Optional[str] = None
    elapsed_seconds: float = 0.0
    budget_used: float = 0.0


@dataclass
class CoTResult:
    """Result of CoT execution with budget tracking"""
    steps: List[CoTStep]
    total_elapsed: float
    budget_exhausted: bool = False
    final_step_reached: str = ""
    savings_accumulated: float = 0.0


class CoTEngine:
    """
    Chain-of-Thought Engine for complex reasoning
    Implements structured thinking process

    Phase 2: Integrated TimeBudget support
    - Allocates time budget per step
    - Transfers savings between steps
    - Gracefully handles budget exhaustion
    """

    # Step mappings for different modes
    DEEP3_STEPS = ["analyze", "plan", "execute"]
    DEEP6_STEPS = ["understanding", "challenges", "approaches",
                   "constraints", "choose", "solution"]

    def __init__(self, user_prefs: 'UserTimeoutPreferences' = None):
        self.current_chain: List[CoTStep] = []
        self.deep_mode = False
        self.deep3_mode = False  # 3-step lightweight mode
        self.budget: Optional['TimeBudget'] = None
        self.user_prefs = user_prefs
        self._step_callbacks: List[Callable] = []

    def enable_deep_mode(self, enabled: bool = True):
        """Enable/disable deep thinking mode (6 steps)"""
        self.deep_mode = enabled
        if enabled:
            self.deep3_mode = False  # Disable DEEP3 when DEEP is on

    def enable_deep3_mode(self, enabled: bool = True):
        """Enable/disable DEEP3 mode (3 steps)"""
        self.deep3_mode = enabled
        if enabled:
            self.deep_mode = False  # Disable DEEP when DEEP3 is on

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 2: BUDGET MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════

    def set_budget(self, budget: 'TimeBudget'):
        """
        Set time budget for CoT execution.

        Args:
            budget: TimeBudget instance with step allocations
        """
        self.budget = budget

    def create_budget_for_mode(self, max_seconds: float = None) -> Optional['TimeBudget']:
        """
        Create appropriate budget based on current mode.

        Args:
            max_seconds: Maximum total seconds (uses user_prefs if None)

        Returns:
            TimeBudget configured for current mode
        """
        if not BUDGET_AVAILABLE:
            return None

        max_time = max_seconds
        if max_time is None and self.user_prefs:
            max_time = self.user_prefs.max_wait
        if max_time is None:
            max_time = 120.0  # Default 2 minutes

        if self.deep3_mode:
            self.budget = BudgetPresets.deep3_mode(max_time)
        elif self.deep_mode:
            self.budget = BudgetPresets.deep6_mode(max_time)
        else:
            self.budget = BudgetPresets.fast_mode(min(max_time, 30))

        return self.budget

    def get_step_timeout(self, step_name: str) -> float:
        """
        Get timeout for specific step, including accumulated savings.

        Args:
            step_name: Name of the step

        Returns:
            Timeout in seconds (includes savings from previous steps)
        """
        if self.budget is None:
            return 30.0  # Default timeout

        return self.budget.get_step_timeout(step_name)

    def start_step(self, step_name: str) -> float:
        """
        Mark step as started and return its timeout.

        Args:
            step_name: Name of the step

        Returns:
            Timeout for this step in seconds
        """
        if self.budget is None:
            return 30.0

        self.budget.start_step(step_name)
        return self.budget.get_step_timeout(step_name)

    def end_step(self, step_name: str, success: bool = True) -> float:
        """
        Mark step as completed and return savings.

        Args:
            step_name: Name of the step
            success: Whether step completed successfully

        Returns:
            Savings (positive) or overrun (negative) in seconds
        """
        if self.budget is None:
            return 0.0

        self.budget.complete_step(step_name)
        # Return savings from the completed step
        record = self.budget.records.get(step_name)
        if record:
            return record.savings
        return 0.0

    def is_budget_exhausted(self) -> bool:
        """Check if total budget is exhausted."""
        if self.budget is None:
            return False
        return self.budget.is_exhausted

    def get_remaining_budget(self) -> float:
        """Get remaining total budget in seconds."""
        if self.budget is None:
            return float('inf')
        return self.budget.remaining

    def get_budget_status(self) -> Dict[str, Any]:
        """Get current budget status."""
        if self.budget is None:
            return {"budget": "none", "mode": self._get_current_mode()}

        return {
            "mode": self._get_current_mode(),
            "total_seconds": self.budget.total,
            "elapsed": self.budget.elapsed,
            "remaining": self.budget.remaining,
            "total_savings": self.budget.total_savings,
            "steps": {
                name: {
                    "allocated": rec.allocated,
                    "actual": rec.actual,
                    "status": rec.status.value
                }
                for name, rec in self.budget.records.items()
            }
        }

    def _get_current_mode(self) -> str:
        """Get current mode name."""
        if self.deep_mode:
            return "deep6"
        elif self.deep3_mode:
            return "deep3"
        else:
            return "fast"

    def on_step_complete(self, callback: Callable):
        """Register callback for step completion events."""
        self._step_callbacks.append(callback)

    def _notify_step_complete(self, step_name: str, elapsed: float, savings: float):
        """Notify callbacks about step completion."""
        for callback in self._step_callbacks:
            try:
                callback(step_name, elapsed, savings)
            except Exception:
                pass  # Don't let callback errors break execution

    def create_thinking_prompt(self, task: str, context: Dict[str, Any] = None,
                               ducs_context: Dict[str, Any] = None,
                               swecas_context: Dict[str, Any] = None) -> str:
        """Create structured thinking prompt, optionally enriched with DUCS/SWECAS context"""
        # DEEP3 mode: 3-step lightweight reasoning
        if self.deep3_mode:
            return self._create_deep3_prompt(task, context, ducs_context)

        if not self.deep_mode:
            return task

        # SWECAS-enhanced pipeline takes priority for bug-fixing tasks
        if swecas_context and swecas_context.get("confidence", 0) >= 0.6:
            return self._create_swecas_thinking_prompt(task, swecas_context, context)

        # Build DUCS domain section if classified with high confidence
        ducs_section = ""
        tools_hint = ""
        if ducs_context and ducs_context.get("confidence", 0) >= 0.85:
            code = ducs_context.get("ducs_code", "")
            category = ducs_context.get("category", "")
            name = ducs_context.get("name", "")
            tools = ", ".join(ducs_context.get("tools", []))
            ducs_section = f"""
DOMAIN CLASSIFICATION (DUCS {code}):
- Category: {category}
- Technology: {name}
- Recommended tools: {tools}
- Use these tools in your PLANNING and EXECUTION steps.
"""
            tools_hint = f"\n   Recommended for this task: {tools}"

        prompt = f"""Task: {task}
{ducs_section}
Think through this step by step:

1. UNDERSTANDING: What exactly is being asked? What are the requirements?

2. PLANNING: What steps are needed? What tools should I use?
   Available tools: bash, read, write, edit, glob, grep, ls, git{tools_hint}

3. EXECUTION: Execute the plan step by step.

4. VERIFICATION: Check the results. Did it work correctly?

5. REFLECTION: What was learned? Any improvements for next time?

Now proceed with the task."""

        if context:
            prompt += f"\n\nContext:\n{context}"

        return prompt

    def _create_swecas_thinking_prompt(self, task: str, swecas: Dict[str, Any],
                                        context: Dict[str, Any] = None) -> str:
        """
        SWECAS-enhanced thinking prompt with diffuse thinking.
        Pipeline: CLASSIFY -> DIFFUSE -> FOCUS -> FIX
        """
        code = swecas.get("swecas_code", 0)
        name = swecas.get("name", "Unknown")
        subcat = swecas.get("subcategory", "N/A")
        confidence = swecas.get("confidence", 0)
        pattern_desc = swecas.get("pattern_description", "")
        fix_hint = swecas.get("fix_hint", "")
        diffuse_insights = swecas.get("diffuse_insights", "")
        related = swecas.get("related", [])
        diffuse_prompts = swecas.get("diffuse_prompts", [])

        # Format diffuse prompts as numbered list
        prompts_text = ""
        if diffuse_prompts:
            prompts_text = "\n".join(f"  - {p}" for p in diffuse_prompts[:3])

        prompt = f"""Task: {task}

## Bug Classification (SWECAS {code}: {name})
- Subcategory: {subcat}
- Confidence: {confidence}
- {pattern_desc}

## Fix Pattern
{fix_hint if fix_hint else 'No specific template — analyze the code carefully.'}

## Cross-Category Insights (Diffuse Thinking)
{diffuse_insights if diffuse_insights else 'No cross-links available.'}

## Diffuse Questions (ask yourself these before coding)
{prompts_text if prompts_text else '(none)'}

## Rules
- Use the fix pattern for SWECAS-{code} category
- Place validation BEFORE state assignment
- Do NOT use assert for production validation (can be disabled with -O flag)
- Do NOT create example files — only modify the target file
- When using write(), include the COMPLETE file content

## Steps:
1. CLASSIFY: Bug is SWECAS-{code} ({name})
2. DIFFUSE: Check related categories: {related}
3. FOCUS: Deep analysis of the target file with enriched context
4. FIX: Apply the fix using edit/write tool with COMPLETE file content

Now proceed with the task."""

        if context:
            prompt += f"\n\nAdditional context:\n{context}"

        return prompt

    def _create_deep3_prompt(self, task: str, context: Dict[str, Any] = None,
                             ducs_context: Dict[str, Any] = None) -> str:
        """
        DEEP3 Mode: 3-step lightweight reasoning
        Faster than full DEEP mode but more thorough than FAST
        """
        # Build DUCS section if available
        ducs_section = ""
        tools_hint = ""
        if ducs_context and ducs_context.get("confidence", 0) >= 0.85:
            code = ducs_context.get("ducs_code", "")
            category = ducs_context.get("category", "")
            name = ducs_context.get("name", "")
            tools = ", ".join(ducs_context.get("tools", []))
            ducs_section = f"""
DOMAIN (DUCS {code}): {category} / {name}
Recommended tools: {tools}
"""
            tools_hint = f" [{tools}]"

        prompt = f"""Task: {task}
{ducs_section}
## DEEP3 Mode (3-step reasoning)

### Step 1/3: ANALYZE 🔍
- What is the problem/task?
- What are the key risks or challenges?
- What files/components are involved?

### Step 2/3: PLAN 📋
- What approach will you use?
- What tools are needed?{tools_hint}
- What is the expected outcome?

### Step 3/3: EXECUTE ⚡
- Implement the solution
- Use tools to make changes
- Verify the result

Now proceed with the task."""

        if context:
            prompt += f"\n\nContext:\n{context}"

        return prompt

    def parse_cot_response(self, response: str) -> List[CoTStep]:
        """Parse CoT steps from LLM response"""
        steps = []
        current_step = None
        current_content = []

        for line in response.split('\n'):
            line_lower = line.lower().strip()

            # Detect step markers
            if 'understanding' in line_lower or '1.' in line:
                if current_step:
                    steps.append(CoTStep(current_step, '\n'.join(current_content)))
                current_step = ThinkingStep.UNDERSTAND
                current_content = []
            elif 'planning' in line_lower or '2.' in line:
                if current_step:
                    steps.append(CoTStep(current_step, '\n'.join(current_content)))
                current_step = ThinkingStep.PLAN
                current_content = []
            elif 'execution' in line_lower or 'executing' in line_lower or '3.' in line:
                if current_step:
                    steps.append(CoTStep(current_step, '\n'.join(current_content)))
                current_step = ThinkingStep.EXECUTE
                current_content = []
            elif 'verification' in line_lower or 'verifying' in line_lower or '4.' in line:
                if current_step:
                    steps.append(CoTStep(current_step, '\n'.join(current_content)))
                current_step = ThinkingStep.VERIFY
                current_content = []
            elif 'reflection' in line_lower or 'reflecting' in line_lower or '5.' in line:
                if current_step:
                    steps.append(CoTStep(current_step, '\n'.join(current_content)))
                current_step = ThinkingStep.REFLECT
                current_content = []
            else:
                current_content.append(line)

        # Add last step
        if current_step:
            steps.append(CoTStep(current_step, '\n'.join(current_content)))

        return steps

    def format_thinking(self, steps: List[CoTStep]) -> str:
        """Format CoT steps for display"""
        output = []
        for step in steps:
            icon = {
                ThinkingStep.UNDERSTAND: "🔍",
                ThinkingStep.PLAN: "📋",
                ThinkingStep.EXECUTE: "⚡",
                ThinkingStep.VERIFY: "✅",
                ThinkingStep.REFLECT: "💭"
            }.get(step.step, "•")

            output.append(f"{icon} {step.step.value.upper()}")
            if step.thought:
                output.append(step.thought.strip())
            output.append("")

        return '\n'.join(output)


class TaskDecomposer:
    """
    Decompose complex tasks into atomic steps
    Part of autonomous agent capability
    """

    def decompose(self, task: str) -> List[Dict[str, Any]]:
        """
        Decompose task into atomic steps
        Returns list of subtasks with dependencies
        """
        # Simple heuristic decomposition
        subtasks = []

        task_lower = task.lower()

        # Check if task involves multiple operations
        if ' and ' in task_lower or ' then ' in task_lower:
            # Split into subtasks
            parts = task_lower.replace(' then ', ' and ').split(' and ')
            for i, part in enumerate(parts):
                subtasks.append({
                    'id': i,
                    'task': part.strip(),
                    'depends_on': [i-1] if i > 0 else [],
                    'status': 'pending'
                })
        else:
            # Single task
            subtasks.append({
                'id': 0,
                'task': task,
                'depends_on': [],
                'status': 'pending'
            })

        return subtasks


class SelfCorrection:
    """
    Self-correction system for autonomous operation
    Detects and fixes errors automatically
    """

    ERROR_PATTERNS = [
        (r'error|exception|failed|not found|permission denied', 'execution_error'),
        (r'syntax error|invalid|unexpected', 'syntax_error'),
        (r'timeout|timed out', 'timeout_error'),
        (r'no such file|does not exist', 'file_not_found'),
    ]

    def analyze_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze result for errors"""
        import re

        analysis = {
            'has_error': False,
            'error_type': None,
            'suggestion': None
        }

        # Check for explicit error
        if 'error' in result:
            analysis['has_error'] = True
            error_text = str(result['error']).lower()

            for pattern, error_type in self.ERROR_PATTERNS:
                if re.search(pattern, error_text):
                    analysis['error_type'] = error_type
                    break

            # Generate suggestion
            if analysis['error_type'] == 'file_not_found':
                analysis['suggestion'] = "Check file path or use glob to find the file"
            elif analysis['error_type'] == 'permission_denied':
                analysis['suggestion'] = "Check file permissions or run with elevated privileges"
            elif analysis['error_type'] == 'syntax_error':
                analysis['suggestion'] = "Review the syntax and try again"

        return analysis

    def suggest_fix(self, error_analysis: Dict[str, Any], original_request: str) -> Optional[str]:
        """Suggest a fix for the error"""
        if not error_analysis['has_error']:
            return None

        suggestions = {
            'file_not_found': f"Try: glob **/* to find files, or check the exact path",
            'permission_denied': "Try running with administrator privileges",
            'timeout_error': "Try breaking the task into smaller parts",
            'execution_error': "Review the command and try a simpler version",
        }

        return suggestions.get(error_analysis['error_type'], "Review and retry")
