# -*- coding: utf-8 -*-
"""
QwenAgent CoT Engine - Chain-of-Thought Reasoning
Deep thinking mode for complex tasks
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

class ThinkingStep(Enum):
    UNDERSTAND = "understanding"
    PLAN = "planning"
    EXECUTE = "executing"
    VERIFY = "verifying"
    REFLECT = "reflecting"

@dataclass
class CoTStep:
    """Single step in Chain-of-Thought"""
    step: ThinkingStep
    thought: str
    action: Optional[str] = None
    result: Optional[str] = None

class CoTEngine:
    """
    Chain-of-Thought Engine for complex reasoning
    Implements structured thinking process
    """

    def __init__(self):
        self.current_chain: List[CoTStep] = []
        self.deep_mode = False

    def enable_deep_mode(self, enabled: bool = True):
        """Enable/disable deep thinking mode"""
        self.deep_mode = enabled

    def create_thinking_prompt(self, task: str, context: Dict[str, Any] = None,
                               ducs_context: Dict[str, Any] = None,
                               swecas_context: Dict[str, Any] = None) -> str:
        """Create structured thinking prompt, optionally enriched with DUCS/SWECAS context"""
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
