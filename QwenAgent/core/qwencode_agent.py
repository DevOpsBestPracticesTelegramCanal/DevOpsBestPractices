"""
QwenCode Agent - Full Claude Code Clone
All features of Claude Code, powered by Qwen LLM
"""

import os
import re
import json
import time
import requests
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from .tools_extended import ExtendedTools, EXTENDED_TOOL_REGISTRY, execute_tool, get_tools_description
from .router import PatternRouter, HybridRouter, RouteResult
from .cot_engine import CoTEngine
from .plan_mode import PlanMode
from .subagent import SubAgentManager, TaskTracker, TaskTool
from .ducs_classifier import DUCSClassifier
from .swecas_classifier import SWECASClassifier
from .deep6_minsky import Deep6Minsky, Deep6Result  # Full 6-step Minsky CoT

# CANONICAL ExecutionMode - единственное определение в проекте
from .execution_mode import ExecutionMode, ESCALATION_CHAIN, normalize_mode

# Phase 1: Timeout Management System
from .timeout_llm_client import (
    TimeoutLLMClient,
    TimeoutConfig,
    GenerationMetrics,
    LLMTimeoutError,
    TTFTTimeoutError,
    IdleTimeoutError,
    AbsoluteTimeoutError
)
from .user_timeout_config import load_user_config, UserTimeoutPreferences

# Phase 2: Budget Management System
from .time_budget import TimeBudget, BudgetPresets
from .budget_estimator import BudgetEstimator, create_mode_budget

# Phase 3: Predictive Timeout Estimator
from .predictive_estimator import PredictiveEstimator, PredictionResult, predict_timeout

# Phase 4: Intent-Aware Scheduler
from .intent_scheduler import IntentScheduler, StreamAnalyzer, SchedulerDecision


@dataclass
class QwenCodeConfig:
    """Configuration for QwenCode agent"""
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:32b"
    max_iterations: int = 10
    timeout: int = 120
    working_dir: str = field(default_factory=os.getcwd)
    deep_mode: bool = False
    verbose: bool = True
    # Новые параметры режимов
    execution_mode: ExecutionMode = ExecutionMode.FAST
    auto_escalation: bool = True  # Автоматическая эскалация при timeout
    escalation_timeout: int = 30  # Timeout для эскалации (секунды)
    # Search backend: "auto" | "duckduckgo" | "searxng"
    search_backend: str = "auto"
    searxng_url: str = "http://localhost:8888"


class QwenCodeAgent:
    """
    QwenCode - Full Claude Code Clone

    Features:
    - All Claude Code tools (15+)
    - Chain-of-Thought reasoning
    - Plan Mode
    - Sub-agents (Task tool)
    - NO-LLM pattern routing
    - Memory and context
    """

    VERSION = "1.0.0"

    SYSTEM_PROMPT = """You are QwenCode, an AI coding assistant that works with files using tools.

WORKFLOW — ALWAYS USE TOOLS FOR FILE TASKS:
1. Read the file FIRST: [TOOL: read(file_path="...")]
2. Edit the file: [TOOL: edit(file_path="...", old_string="...", new_string="...")]
3. Verify if needed: [TOOL: read(file_path="...")]

WHEN TO USE TOOLS (ALWAYS):
- "add function to file.py" → [TOOL: read(file_path="file.py")] then [TOOL: edit(...)]
- "fix bug in file.py" → [TOOL: read(file_path="file.py")] then [TOOL: edit(...)]
- "create new file" → [TOOL: write(file_path="...", content="...")]
- "run tests" → [TOOL: bash(command="python -m pytest")]
- "show file" → [TOOL: read(file_path="...")]
- "list files" → [TOOL: ls(path=".")]
- "find files" → [TOOL: glob(pattern="**/*.py")]
- "search for X" → [TOOL: grep(pattern="X")]

WHEN NOT TO USE TOOLS (text answer only):
- "explain what this code does" → answer in text
- "what is a decorator?" → answer in text
- "show me an algorithm" → show in markdown code block

RESPONSE LANGUAGE:
- Respond in the SAME language as the user's question

{tools_description}

TOOL FORMAT:
[TOOL: tool_name(param1="value1", param2="value2")]

Use \\n for newlines inside tool parameters.

FORBIDDEN ACTIONS:
- NEVER create files that the user did not ask for — no demo files, no sample files, no tutorial files
- NEVER use invented function names from training data — only names from the user's actual code
- ONLY modify files explicitly mentioned by the user's request
- When using write(), include ALL original code — do NOT omit unchanged parts
- NEVER invent new files to demonstrate a concept when the user asked to fix an existing file
- NEVER write partial files — always write the COMPLETE file content

VIOLATION CHECK (before EVERY tool call):
- Is this the user's TARGET file, not an invented example?
- Am I using code from the USER'S REQUEST, not my own invented examples?
- Does write() contain the COMPLETE file content, not a fragment?

IMPORTANT: For ANY task involving files, ALWAYS use tools. Never just show code in markdown when the user wants to modify a file.

Current working directory: {working_dir}
"""

    def __init__(self, config: QwenCodeConfig = None):
        self.config = config or QwenCodeConfig()

        # Phase 1: Load user timeout preferences from .qwencoderules
        self.user_prefs = load_user_config(self.config.working_dir)
        self.timeout_config = self.user_prefs.to_timeout_config()

        # Phase 1: Initialize TimeoutLLMClient with user preferences
        self.llm_client = TimeoutLLMClient(
            base_url=self.config.ollama_url,
            timeout_config=self.timeout_config
        )

        # Core components
        self.router = HybridRouter()
        self.cot_engine = CoTEngine(user_prefs=self.user_prefs)  # Phase 2: Pass user_prefs
        self.plan_mode = PlanMode()
        self.task_tracker = TaskTracker()
        self.ducs = DUCSClassifier()
        self.swecas = SWECASClassifier()

        # Phase 2: Budget Estimator
        self.budget_estimator = BudgetEstimator(self.user_prefs)

        # Phase 3: Predictive Timeout Estimator
        history_file = os.path.join(self.config.working_dir, ".qwencode_predictions.json")
        self.predictive_estimator = PredictiveEstimator(history_file=history_file)

        # Phase 4: Intent-Aware Scheduler
        self.intent_scheduler = IntentScheduler()

        # Deep6 Minsky engine (full 6-step CoT with iterative rollback)
        self.deep6_engine = Deep6Minsky(
            fast_model=getattr(config, 'fast_model', None) if config else None,
            heavy_model=getattr(config, 'heavy_model', None) if config else None,
            enable_adversarial=True
        )

        # Sub-agent manager (needs LLM client)
        self.subagent_manager = SubAgentManager(self._call_llm_simple)
        self.task_tool = TaskTool(self.subagent_manager)

        # State
        self.conversation_history: List[Dict[str, str]] = []
        self.tool_call_history: List[Dict[str, Any]] = []
        self.working_dir = self.config.working_dir

        # Statistics
        self.stats = {
            "total_requests": 0,
            "tool_calls": 0,
            "llm_calls": 0,
            "pattern_matches": 0,
            "cot_sessions": 0,
            "deep6_sessions": 0,  # Full 6-step Minsky sessions
            "deep6_rollbacks": 0,  # Rollbacks triggered by Self-Reflective step
            "plan_mode_sessions": 0,
            "mode_escalations": 0,
            "web_searches": 0,
            # Phase 2: Budget tracking
            "budget_exhaustions": 0,  # Times budget ran out
            "budget_savings_total": 0.0,  # Total time saved
            "budget_overruns": 0,  # Times steps exceeded budget
            # Phase 3: Prediction tracking
            "predictions_made": 0,
            "prediction_accuracy_sum": 0.0,
            # Phase 4: Intent tracking
            "intent_early_exits": 0,
            "intent_extensions": 0
        }

        # Mode tracking
        self.current_mode = self.config.execution_mode
        self.mode_history = []  # История переключений режимов
        self.search_deep_analysis_mode = ExecutionMode.DEEP3  # Режим анализа для Search+Deep (DEEP3 или DEEP6)

    def process(self, user_input: str) -> Dict[str, Any]:
        """
        Process user input - main entry point
        Returns structured response with tool calls, thinking, etc.
        """
        self.stats["total_requests"] += 1

        result = {
            "input": user_input,
            "response": "",
            "tool_calls": [],
            "thinking": [],
            "route_method": "",
            "iterations": 0,
            "plan_mode": self.plan_mode.is_active
        }

        # Check for special commands
        special = self._handle_special_commands(user_input)
        if special:
            result["response"] = special["response"]
            result["route_method"] = "special_command"
            return result

        # STEP 1: Try pattern routing (NO-LLM)
        route = self.router.route(user_input)

        if route.confidence >= 0.85 and route.tool:
            # Direct tool execution without LLM
            self.stats["pattern_matches"] += 1
            result["route_method"] = "pattern"

            tool_result = execute_tool(route.tool, **route.params)
            result["tool_calls"].append({
                "tool": route.tool,
                "params": route.params,
                "result": tool_result
            })

            result["response"] = self._format_tool_result(route.tool, tool_result)
            return result

        # STEP 1.5: NO-LLM pre-read for file modification tasks
        # Detects "add/fix/update X in file.py" and auto-reads the file
        # so LLM gets file context on first call (saves 1 round-trip)
        pre_read_context = self._try_pre_read(user_input)
        if pre_read_context:
            result["tool_calls"].append(pre_read_context["tool_call"])

        # STEP 1.6: DUCS domain classification (NO-LLM)
        ducs_result = self.ducs.classify(user_input)
        if ducs_result.get("confidence", 0) >= 0.5:
            result["ducs_code"] = ducs_result.get("ducs_code")
            result["ducs_category"] = ducs_result.get("category", "")
            result["ducs_confidence"] = ducs_result.get("confidence", 0)
        self._current_ducs = ducs_result

        # STEP 1.7: SWECAS bug classification (NO-LLM)
        pre_read_content = pre_read_context.get("content") if pre_read_context else None
        swecas_result = self.swecas.classify(user_input, file_content=pre_read_content)
        if swecas_result.get("confidence", 0) >= 0.6:
            result["swecas_code"] = swecas_result.get("swecas_code")
            result["swecas_category"] = swecas_result.get("name", "")
            result["swecas_confidence"] = swecas_result.get("confidence", 0)
        self._current_swecas = swecas_result

        # STEP 1.8: Phase 3 - Predictive timeout estimation
        prediction_context = {
            "pre_read_content": pre_read_content,
            "ducs_code": ducs_result.get("ducs_code"),
            "swecas_code": swecas_result.get("swecas_code")
        }
        self._current_prediction = self.predictive_estimator.predict(
            mode=self.current_mode.value,
            prompt=user_input,
            model=self.config.model,
            context=prediction_context
        )
        result["predicted_timeout"] = self._current_prediction.timeout
        result["prediction_confidence"] = self._current_prediction.confidence
        result["task_complexity"] = self._current_prediction.complexity.value
        self.stats["predictions_made"] += 1
        self._task_start_time = time.time()  # Track actual execution time

        # STEP 2: LLM processing
        result["route_method"] = "llm"

        # Build context (exclude web_search tools when not in SEARCH mode)
        exclude_tools = []
        if not self.current_mode.is_search:
            exclude_tools = ['web_search', 'web_search_searxng']

        system_prompt = self.SYSTEM_PROMPT.format(
            tools_description=get_tools_description(exclude=exclude_tools),
            working_dir=self.working_dir
        )

        # Add plan mode context if active
        if self.plan_mode.is_active:
            system_prompt += "\n\n[PLAN MODE ACTIVE - Read-only operations only until plan is approved]"

        # CoT mode based on current_mode (SWECAS-enhanced when applicable)
        is_deep6 = self.current_mode == ExecutionMode.DEEP6
        is_deep3 = self.current_mode == ExecutionMode.DEEP3
        use_legacy_deep = self.config.deep_mode and not is_deep6

        # DEEP6 MODE: Use full 6-step Minsky engine with iterative rollback
        if is_deep6:
            deep6_result = self._process_deep6(
                user_input,
                pre_read_context=pre_read_context,
                ducs_result=ducs_result,
                swecas_result=swecas_result
            )
            # Merge Deep6 result into main result
            result["response"] = deep6_result.get("response", "")
            result["tool_calls"] = deep6_result.get("tool_calls", [])
            result["thinking"] = deep6_result.get("thinking", [])
            result["deep6_audit"] = deep6_result.get("audit", {})
            result["deep6_iterations"] = deep6_result.get("iterations", 1)
            result["deep6_rollbacks"] = deep6_result.get("rollbacks", [])
            result["route_method"] = "deep6_minsky"
            return result

        # DEEP3 or legacy deep mode
        if use_legacy_deep or self._is_complex_task(user_input):
            self.stats["cot_sessions"] += 1
            self.cot_engine.enable_deep_mode(True)
            # Phase 2: Create budget for deep mode
            self.cot_engine.create_budget_for_mode()
            # Use SWECAS context if confidence is high enough
            swecas_ctx = swecas_result if swecas_result.get("confidence", 0) >= 0.6 else None
            prompt = self.cot_engine.create_thinking_prompt(
                user_input, ducs_context=ducs_result, swecas_context=swecas_ctx
            )
        elif is_deep3:
            self.stats["cot_sessions"] += 1
            self.cot_engine.enable_deep3_mode(True)
            # Phase 2: Create budget for deep3 mode
            self.cot_engine.create_budget_for_mode()
            prompt = self.cot_engine.create_thinking_prompt(
                user_input, ducs_context=ducs_result
            )
        else:
            self.cot_engine.enable_deep_mode(False)
            self.cot_engine.enable_deep3_mode(False)
            # Phase 2: Create budget for fast mode
            self.cot_engine.create_budget_for_mode()
            prompt = user_input

        # Inject pre-read file content into prompt (NO-LLM optimization)
        # Content has line numbers stripped so LLM can use exact strings for old_string
        if pre_read_context and pre_read_context.get("content"):
            file_path = pre_read_context["file_path"]
            file_content = pre_read_context["content"]
            prompt = f"""{prompt}

I already read {file_path} for you. Here is the EXACT file content (use these exact strings for old_string):
```
{file_content}
```

Now use [TOOL: edit(file_path="{file_path}", old_string="...", new_string="...")] to make the changes.
IMPORTANT: Copy old_string EXACTLY from the file content above. Do NOT add line numbers."""

        # Agentic loop - iterate until done or max iterations
        iteration = 0
        current_prompt = prompt
        full_response = ""

        while iteration < self.config.max_iterations:
            iteration += 1
            result["iterations"] = iteration

            # Phase 2: Check budget before LLM call
            if self.cot_engine.is_budget_exhausted():
                result["response"] = "[Budget exhausted] " + (full_response or "Task incomplete due to time limit.")
                result["budget_exhausted"] = True
                self.stats["budget_exhaustions"] += 1
                break

            # Phase 2: Get remaining budget (budget tracks elapsed time automatically)
            remaining_budget = self.cot_engine.get_remaining_budget()

            # Call LLM with budget-aware timeout
            llm_response = self._call_llm(current_prompt, system_prompt)
            self.stats["llm_calls"] += 1

            if not llm_response:
                # CHUNKED CONTEXT: If deep mode + SWECAS, retry with compressed prompt
                if self.config.deep_mode and hasattr(self, '_current_swecas'):
                    swecas = self._current_swecas
                    if swecas.get("confidence", 0) >= 0.6 and iteration == 1:
                        # Reduce context: keep only SWECAS template + file + task
                        fix_hint = swecas.get("fix_hint", "")
                        compressed = f"""Fix this bug. Category: SWECAS-{swecas.get('swecas_code', 0)} ({swecas.get('name', '')}).
Hint: {fix_hint}
Task: {user_input}"""
                        if pre_read_context and pre_read_context.get("content"):
                            file_path = pre_read_context["file_path"]
                            # Truncate file content to fit context window
                            file_content = pre_read_context["content"][:3000]
                            compressed += f"\n\nFile {file_path}:\n```\n{file_content}\n```\nUse [TOOL: edit(...)] to fix."
                        current_prompt = compressed
                        continue  # Retry with compressed prompt

                result["response"] = "Error: No response from LLM"
                break

            full_response += llm_response + "\n"

            # Parse tool calls from response
            tool_calls = self._parse_tool_calls(llm_response)

            if not tool_calls:
                # No more tool calls - we're done
                result["response"] = llm_response
                break

            # Execute tool calls
            tool_results = []
            for tool_name, params in tool_calls:
                self.stats["tool_calls"] += 1

                # Check plan mode restrictions
                if self.plan_mode.is_active and tool_name in ["write", "edit", "bash"]:
                    tool_result = {"success": False, "error": "Cannot modify files in plan mode"}
                else:
                    tool_result = execute_tool(tool_name, **params)

                result["tool_calls"].append({
                    "tool": tool_name,
                    "params": params,
                    "result": tool_result
                })
                tool_results.append((tool_name, tool_result))

            # Build continuation prompt with tool results
            current_prompt = self._build_continuation_prompt(tool_results)

        # Parse thinking if CoT mode
        if self.config.deep_mode:
            cot_steps = self.cot_engine.parse_cot_response(full_response)
            result["thinking"] = [step.thought for step in cot_steps if step.thought]

        # Phase 2: Add budget status to result
        budget_status = self.cot_engine.get_budget_status()
        result["budget"] = budget_status
        if budget_status.get("remaining", float('inf')) <= 0:
            self.stats["budget_exhaustions"] += 1
        if budget_status.get("total_savings", 0) > 0:
            self.stats["budget_savings_total"] += budget_status["total_savings"]

        # Phase 3: Record prediction outcome for learning
        if hasattr(self, '_current_prediction') and self._current_prediction:
            actual_time = time.time() - getattr(self, '_task_start_time', time.time())
            result["actual_time"] = actual_time
            # Determine success based on whether we got a response
            success = bool(result.get("response")) and "Error" not in result.get("response", "")
            # Record for ML learning
            self.predictive_estimator.record_outcome(
                prediction_id=self._current_prediction.id,
                actual_seconds=actual_time,
                success=success,
                tokens_generated=result.get("iterations", 1) * 100  # Rough estimate
            )
            # Track accuracy
            if self._current_prediction.timeout > 0:
                accuracy = actual_time / self._current_prediction.timeout
                self.stats["prediction_accuracy_sum"] += accuracy

        # Store in history
        self.conversation_history.append({
            "role": "user",
            "content": user_input
        })
        self.conversation_history.append({
            "role": "assistant",
            "content": result["response"]
        })

        return result

    def process_stream(self, user_input: str):
        """
        Generator version of process() — yields SSE events during processing.
        Events: status, tool_start, tool_result, thinking, response, done
        """
        self.stats["total_requests"] += 1

        # Check for special commands
        special = self._handle_special_commands(user_input)
        if special:
            yield {"event": "response", "text": special["response"], "route_method": "special_command"}
            yield {"event": "done"}
            return

        # STEP 1: Try pattern routing (NO-LLM)
        route = self.router.route(user_input)

        if route.confidence >= 0.85 and route.tool:
            self.stats["pattern_matches"] += 1
            yield {"event": "tool_start", "tool": route.tool, "params": route.params}
            tool_result = execute_tool(route.tool, **route.params)
            self.stats["tool_calls"] += 1
            yield {"event": "tool_result", "tool": route.tool, "params": route.params, "result": tool_result}
            yield {"event": "response", "text": self._format_tool_result(route.tool, tool_result), "route_method": "pattern"}
            yield {"event": "done"}
            return

        # STEP 1.5: NO-LLM pre-read for file modification tasks
        pre_read_context = self._try_pre_read(user_input)
        if pre_read_context:
            yield {"event": "tool_start", "tool": "read", "params": pre_read_context["tool_call"]["params"]}
            yield {"event": "tool_result", "tool": "read", "params": pre_read_context["tool_call"]["params"], "result": pre_read_context["tool_call"]["result"]}

        # STEP 1.6: DUCS domain classification (NO-LLM)
        ducs_result = self.ducs.classify(user_input)
        if ducs_result.get("confidence", 0) >= 0.5:
            yield {"event": "status", "text": f"Domain: {ducs_result.get('category', '')}"}
        self._current_ducs = ducs_result

        # STEP 1.7: SWECAS bug classification (NO-LLM)
        pre_read_content_stream = pre_read_context.get("content") if pre_read_context else None
        swecas_result = self.swecas.classify(user_input, file_content=pre_read_content_stream)
        if swecas_result.get("confidence", 0) >= 0.6:
            yield {"event": "status", "text": f"Bug: SWECAS-{swecas_result.get('swecas_code', '?')} ({swecas_result.get('name', '')})"}
        self._current_swecas = swecas_result

        # STEP 2: LLM processing
        yield {"event": "status", "text": "Thinking..."}

        # Exclude web_search tools when not in SEARCH mode
        exclude_tools = []
        if not self.current_mode.is_search:
            exclude_tools = ['web_search', 'web_search_searxng']

        system_prompt = self.SYSTEM_PROMPT.format(
            tools_description=get_tools_description(exclude=exclude_tools),
            working_dir=self.working_dir
        )

        if self.plan_mode.is_active:
            system_prompt += "\n\n[PLAN MODE ACTIVE - Read-only operations only until plan is approved]"

        # CoT mode based on current_mode (SWECAS-enhanced when applicable)
        is_deep6 = self.current_mode == ExecutionMode.DEEP6
        is_deep3 = self.current_mode == ExecutionMode.DEEP3
        use_legacy_deep = self.config.deep_mode and not is_deep6

        # DEEP6 MODE: Use full 6-step Minsky engine (streaming events)
        if is_deep6:
            yield {"event": "status", "text": "Deep6 Minsky: Starting 6-step pipeline..."}

            # Define streaming callback
            def on_step_stream(step_name: str, output: str):
                pass  # We'll yield events after execution

            # Execute Deep6 pipeline
            deep6_result = self.deep6_engine.execute(
                query=user_input,
                context=pre_read_context.get("content", "")[:2000] if pre_read_context else "",
                verbose=False,
                on_step=on_step_stream
            )

            self.stats["deep6_sessions"] += 1
            if deep6_result.rollback_reasons:
                self.stats["deep6_rollbacks"] += len(deep6_result.rollback_reasons)

            # Yield step events
            for step_name in deep6_result.call_sequence:
                yield {"event": "status", "text": f"Deep6: {step_name}"}

            # Yield rollback events if any
            for reason in deep6_result.rollback_reasons:
                yield {"event": "status", "text": f"Deep6 ROLLBACK: {reason}"}

            # Yield audit info
            if deep6_result.audit_results:
                audit = deep6_result.audit_results[-1]
                yield {"event": "thinking", "steps": [
                    f"Risk Score: {audit.overall_risk_score}/10",
                    f"Decision: {audit.decision}",
                    f"Vulnerabilities: {len(audit.vulnerabilities_found)}"
                ]}

            # Yield final response
            response = deep6_result.final_code or deep6_result.final_explanation or "No output"
            yield {"event": "response", "text": response, "route_method": "deep6_minsky"}
            yield {"event": "done"}
            return

        # DEEP3 or legacy deep mode
        if use_legacy_deep or self._is_complex_task(user_input):
            self.stats["cot_sessions"] += 1
            self.cot_engine.enable_deep_mode(True)
            swecas_ctx = swecas_result if swecas_result.get("confidence", 0) >= 0.6 else None
            prompt = self.cot_engine.create_thinking_prompt(
                user_input, ducs_context=ducs_result, swecas_context=swecas_ctx
            )
        elif is_deep3:
            self.stats["cot_sessions"] += 1
            self.cot_engine.enable_deep3_mode(True)
            prompt = self.cot_engine.create_thinking_prompt(
                user_input, ducs_context=ducs_result
            )
        else:
            self.cot_engine.enable_deep_mode(False)
            self.cot_engine.enable_deep3_mode(False)
            prompt = user_input

        # Inject pre-read file content (line numbers stripped for exact matching)
        if pre_read_context and pre_read_context.get("content"):
            file_path = pre_read_context["file_path"]
            file_content = pre_read_context["content"]
            prompt = f"""{prompt}

I already read {file_path} for you. Here is the EXACT file content (use these exact strings for old_string):
```
{file_content}
```

Now use [TOOL: edit(file_path="{file_path}", old_string="...", new_string="...")] to make the changes.
IMPORTANT: Copy old_string EXACTLY from the file content above. Do NOT add line numbers."""

        # Agentic loop
        iteration = 0
        current_prompt = prompt
        all_tool_calls = []

        while iteration < self.config.max_iterations:
            iteration += 1
            yield {"event": "status", "text": f"Step {iteration}..."}

            llm_response = self._call_llm(current_prompt, system_prompt)
            self.stats["llm_calls"] += 1

            if not llm_response:
                yield {"event": "response", "text": "Error: No response from LLM", "route_method": "llm"}
                break

            tool_calls = self._parse_tool_calls(llm_response)

            if not tool_calls:
                # No more tool calls — final response
                if self.config.deep_mode:
                    cot_steps = self.cot_engine.parse_cot_response(llm_response)
                    thinking = [step.thought for step in cot_steps if step.thought]
                    if thinking:
                        yield {"event": "thinking", "steps": thinking}

                yield {"event": "response", "text": llm_response, "route_method": "llm"}
                break

            # Execute tool calls
            tool_results = []
            for tool_name, params in tool_calls:
                self.stats["tool_calls"] += 1
                yield {"event": "tool_start", "tool": tool_name, "params": params}

                if self.plan_mode.is_active and tool_name in ["write", "edit", "bash"]:
                    tool_result = {"success": False, "error": "Cannot modify files in plan mode"}
                else:
                    tool_result = execute_tool(tool_name, **params)

                all_tool_calls.append({"tool": tool_name, "params": params, "result": tool_result})
                yield {"event": "tool_result", "tool": tool_name, "params": params, "result": tool_result}
                tool_results.append((tool_name, tool_result))

            current_prompt = self._build_continuation_prompt(tool_results)

        # Store in history
        self.conversation_history.append({"role": "user", "content": user_input})
        self.conversation_history.append({"role": "assistant", "content": "(streamed response)"})

        yield {"event": "done"}

    def _get_num_predict(self, ducs_result: dict = None) -> int:
        """Adjust max tokens based on DUCS classification and mode"""
        if self.config.deep_mode:
            return 4096  # Deep needs CoT reasoning + tool calls
        if ducs_result and ducs_result.get("confidence", 0) >= 0.85:
            return 512   # Known domain, shorter answers
        return 2048      # Unknown, full output

    def _call_llm(self, prompt: str, system: str = None) -> Optional[str]:
        """
        Call Ollama LLM with Phase 1 timeout management.

        Features:
        - TTFT timeout (model not starting)
        - Idle timeout (model stuck)
        - Absolute max timeout
        - Automatic fallback to lighter model
        - Partial result preservation
        """
        try:
            # Build full prompt with history
            full_prompt = ""
            if system:
                full_prompt = f"System: {system}\n\n"

            for msg in self.conversation_history[-8:]:
                role = "User" if msg["role"] == "user" else "Assistant"
                full_prompt += f"{role}: {msg['content']}\n\n"

            full_prompt += f"User: {prompt}\n\nAssistant:"

            # Get timeout config based on current mode
            mode_budget = self.user_prefs.get_mode_budget(self.current_mode.value)
            timeout_override = TimeoutConfig(
                ttft_timeout=self.timeout_config.ttft_timeout,
                idle_timeout=self.timeout_config.idle_timeout,
                absolute_max=mode_budget
            )

            # Get model config
            models = self.user_prefs.get_model_config()
            primary_model = self.config.model
            fallback_model = models.get('fallback', 'qwen2.5-coder:3b')

            # Call with fallback support
            result, metrics = self.llm_client.generate_with_fallback(
                prompt=full_prompt,
                model=primary_model,
                fallback_model=fallback_model,
                timeout_override=timeout_override
            )

            # Track metrics
            self.stats["llm_calls"] += 1
            if metrics.timeout_reason and 'fallback' in str(metrics.timeout_reason):
                if self.config.verbose:
                    print(f"[FALLBACK] {primary_model} → {fallback_model}")

            return result

        except LLMTimeoutError as e:
            if self.config.verbose:
                print(f"[TIMEOUT] {e.metrics.timeout_reason}: {e.metrics.tokens_generated} tokens in {e.metrics.total_time:.1f}s")
            # Return partial result if available
            if e.partial_result:
                return e.partial_result
            return None

        except Exception as e:
            if self.config.verbose:
                print(f"Ollama Error: {e}")
            return None

    def _call_llm_search(self, prompt: str) -> Optional[str]:
        """
        Lightweight LLM call for search result analysis.

        Uses shorter timeouts for faster response.
        """
        try:
            # Shorter timeouts for search analysis
            search_timeout = TimeoutConfig(
                ttft_timeout=15,
                idle_timeout=10,
                absolute_max=60
            )

            result, metrics = self.llm_client.generate_safe(
                prompt=f"User: {prompt}\n\nAssistant:",
                model=self.config.model,
                timeout_override=search_timeout,
                default_on_error=""
            )

            return result if result else None

        except Exception as e:
            if self.config.verbose:
                print(f"LLM Search Error: {e}")
            return None

    def _call_llm_simple(self, prompt: str, system: str = None) -> str:
        """
        Simple LLM call for sub-agents.

        Uses generate_safe to always return something (never throws).
        """
        try:
            # Prepare prompt with system
            full_prompt = prompt
            if system:
                full_prompt = f"System: {system}\n\n{prompt}"

            # Simple timeout config
            simple_timeout = TimeoutConfig(
                ttft_timeout=20,
                idle_timeout=12,
                absolute_max=self.config.timeout
            )

            result, metrics, error = self.llm_client.generate_safe(
                prompt=full_prompt,
                model=self.config.model,
                timeout_override=simple_timeout,
                default_on_error=""
            )

            return result

        except Exception:
            return ""

    # Valid parameters for each tool (for filtering invalid LLM arguments)
    VALID_TOOL_PARAMS = {
        'bash': ['command', 'timeout', 'working_dir'],
        'read': ['file_path', 'path', 'offset', 'limit'],
        'write': ['file_path', 'path', 'content'],
        'edit': ['file_path', 'path', 'old_string', 'new_string', 'old_str', 'new_str', 'replace_all'],
        'ls': ['path', 'directory', 'show_hidden'],
        'glob': ['pattern', 'path'],
        'grep': ['pattern', 'path', 'include', 'context_before', 'context_after'],
        'git': ['command', 'working_dir'],
        'tree': ['path', 'max_depth', 'show_hidden'],
        'diff': ['file1', 'file2'],
        'web_fetch': ['url', 'prompt'],
        'web_search': ['query', 'num_results'],
        'notebook_read': ['notebook_path'],
        'notebook_edit': ['notebook_path', 'cell_index', 'new_source', 'cell_type', 'edit_mode']
    }

    def _parse_tool_calls(self, response: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Parse tool calls from LLM response with validation"""
        tool_calls = []

        # Pattern: [TOOL: name(params)]
        pattern = r'\[TOOL:\s*(\w+)\((.*?)\)\]'
        matches = re.finditer(pattern, response, re.DOTALL)

        for match in matches:
            tool_name = match.group(1).lower()  # Normalize to lowercase
            params_str = match.group(2)

            # Check if tool exists
            if tool_name not in EXTENDED_TOOL_REGISTRY:
                print(f"[PARSE] Unknown tool: {tool_name}")
                continue

            # Parse parameters
            params = {}
            if params_str.strip():
                # Handle key="value" format
                param_pattern = r'(\w+)\s*=\s*["\']([^"\']*)["\']|(\w+)\s*=\s*([^,\)]+)'
                for pm in re.finditer(param_pattern, params_str):
                    if pm.group(1):
                        # Process escape sequences in string values (convert \n to real newlines)
                        value = pm.group(2)
                        value = self._process_escape_sequences(value)
                        params[pm.group(1)] = value
                    elif pm.group(3):
                        value = pm.group(4).strip()
                        # Try to parse as int/float/bool
                        if value.lower() == 'true':
                            value = True
                        elif value.lower() == 'false':
                            value = False
                        elif value.isdigit():
                            value = int(value)
                        params[pm.group(3)] = value

            # VALIDATION: Filter only valid params for this tool
            valid_params = self.VALID_TOOL_PARAMS.get(tool_name, [])
            filtered_params = {}
            invalid_params = []

            for key, value in params.items():
                if key in valid_params:
                    filtered_params[key] = value
                else:
                    invalid_params.append(key)

            if invalid_params:
                print(f"[PARSE] Filtered invalid params for {tool_name}: {invalid_params}")

            # Normalize param names (path -> file_path for read/write/edit)
            if tool_name in ['read', 'write', 'edit'] and 'path' in filtered_params and 'file_path' not in filtered_params:
                filtered_params['file_path'] = filtered_params.pop('path')

            # Add to list if we have valid params or tool needs no params
            if filtered_params or tool_name in ['ls']:  # ls can work without params
                tool_calls.append((tool_name, filtered_params))
            elif tool_name == 'bash' and 'command' not in filtered_params:
                print(f"[PARSE] bash tool missing 'command' parameter, skipping")
            else:
                tool_calls.append((tool_name, filtered_params))

        return tool_calls

    def _process_escape_sequences(self, value: str) -> str:
        """
        Convert escape sequences in strings to actual characters.
        E.g., '\\n' -> '\n', '\\t' -> '\t'
        This is needed because LLM outputs escape sequences as text.
        """
        try:
            # Use codecs to decode unicode escape sequences
            import codecs
            # Only process if there are escape sequences
            if '\\' in value:
                # Decode common escape sequences
                value = value.replace('\\n', '\n')
                value = value.replace('\\t', '\t')
                value = value.replace('\\r', '\r')
                value = value.replace('\\\\', '\\')
            return value
        except Exception:
            return value

    def _build_continuation_prompt(self, tool_results: List[Tuple[str, Dict]]) -> str:
        """Build prompt with tool results for continuation"""
        lines = ["Tool results:"]
        for tool_name, result in tool_results:
            lines.append(f"\n[{tool_name}]:")
            if result.get("success"):
                # Truncate large results
                result_str = json.dumps(result, indent=2, default=str)
                if len(result_str) > 3000:
                    result_str = result_str[:3000] + "\n...[truncated]"
                lines.append(result_str)
            else:
                lines.append(f"Error: {result.get('error', 'Unknown error')}")

        lines.append("\nBased on these results, continue with the task. Use more tools if needed, or provide the final answer.")
        return "\n".join(lines)

    def _format_tool_result(self, tool_name: str, result: Dict[str, Any]) -> str:
        """Format tool result for display"""
        if not result.get("success", True):
            return f"Error: {result.get('error', 'Unknown error')}"

        if tool_name == "ls":
            items = result.get("items", [])
            lines = [f"Directory: {result.get('path', '.')}"]
            for item in items[:50]:
                prefix = "[D]" if item.get("type") == "dir" else "[F]"
                lines.append(f"{prefix} {item['name']}")
            if len(items) > 50:
                lines.append(f"... and {len(items) - 50} more")
            return "\n".join(lines)

        elif tool_name == "read":
            return result.get("content", "")

        elif tool_name == "glob":
            files = result.get("files", [])
            if not files:
                return "No files found"
            return "\n".join([f["path"] for f in files[:50]])

        elif tool_name == "grep":
            matches = result.get("matches", [])
            if not matches:
                return "No matches found"
            lines = []
            for m in matches[:30]:
                lines.append(f"{m['file']}:{m['line_number']}: {m['line']}")
            return "\n".join(lines)

        elif tool_name == "bash":
            output = result.get("stdout", "")
            if result.get("stderr"):
                output += f"\n[stderr]: {result['stderr']}"
            return output or "(no output)"

        elif tool_name == "write":
            return f"Written {result.get('bytes_written', 0)} bytes to {result.get('file_path', 'file')}"

        elif tool_name == "edit":
            return f"Made {result.get('replacements', 0)} replacement(s) in {result.get('file_path', 'file')}"

        else:
            return json.dumps(result, indent=2, default=str)

    def _handle_special_commands(self, user_input: str) -> Optional[Dict[str, Any]]:
        """Handle special commands like /plan, /help, etc."""
        cmd = user_input.strip().lower()

        if cmd == "/help":
            return {
                "response": """QwenCode Commands:
/help             - Show this help
/plan             - Enter plan mode
/plan exit        - Exit plan mode
/plan status      - Show plan status
/tasks            - List tasks
/stats            - Show statistics
/deep6 stats      - Show Deep6 Minsky statistics
/clear            - Clear conversation
/model            - Show current model

MODE SWITCHING:
/mode             - Show current mode status
/mode fast        - Switch to FAST mode (quick queries)
/mode deep3       - Switch to DEEP3 mode (3-step CoT)
/mode deep        - Switch to DEEP6 mode (6-step Minsky)
/mode search      - Switch to SEARCH mode (web search)
/deep on          - Enable deep mode (alias for /mode deep)
/deep off         - Disable deep mode (alias for /mode fast)
/escalation on    - Enable auto-escalation
/escalation off   - Disable auto-escalation

MODE PREFIXES (in queries):
[DEEP3] query     - Run query in DEEP3 mode (3 steps)
[DEEP6] query     - Run query in DEEP6 mode (6-step Minsky)
[DEEP] query      - Run query in DEEP6 mode
[SEARCH] query    - Run query in SEARCH mode
--deep query      - Run query in DEEP mode
--search query    - Run query in SEARCH mode

DEEP6 MINSKY (6-step cognitive pipeline):
1. REACTION       - Quick classification
2. DELIBERATION   - Pattern matching
3. REFLECTIVE     - Method analysis
4. SELF-REFLECTIVE - Critical audit (can trigger ROLLBACK)
5. SELF-CONSTRUCTIVE - Code synthesis
6. VALUES/IDEALS  - Final verification

ESCALATION:
FAST -> DEEP3 -> DEEP6 -> SEARCH
"""
            }

        elif cmd == "/plan":
            result = self.plan_mode.enter()
            self.stats["plan_mode_sessions"] += 1
            return {"response": result.get("message", "") + "\n" + result.get("instructions", "")}

        elif cmd == "/plan exit":
            result = self.plan_mode.exit()
            return {"response": result.get("plan_summary", result.get("message", ""))}

        elif cmd == "/plan approve":
            result = self.plan_mode.approve()
            return {"response": result.get("message", "")}

        elif cmd == "/plan status":
            result = self.plan_mode.get_status()
            return {"response": json.dumps(result, indent=2)}

        elif cmd == "/tasks":
            result = self.task_tracker.list_all()
            if result["tasks"]:
                lines = ["Tasks:"]
                for t in result["tasks"]:
                    status_icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
                    lines.append(f"{status_icon.get(t['status'], '[ ]')} #{t['id']} {t['subject']}")
                return {"response": "\n".join(lines)}
            return {"response": "No tasks"}

        elif cmd == "/stats":
            stats_output = {
                **self.stats,
                "deep6_engine": self.deep6_engine.get_statistics()
            }
            return {"response": json.dumps(stats_output, indent=2)}

        elif cmd == "/deep6 stats":
            deep6_stats = self.get_deep6_stats()
            engine_stats = deep6_stats["engine_stats"]
            return {"response": f"""Deep6 Minsky Statistics:
Sessions: {deep6_stats['sessions']}
Rollbacks: {deep6_stats['rollbacks']}
Avg Duration: {engine_stats.get('avg_duration_ms', 0):.0f}ms
Avg Risk Score: {engine_stats.get('avg_risk_score', 0):.1f}/10
Adversarial Catches: {engine_stats.get('adversarial_catches', 0)}
Total Rollbacks (engine): {engine_stats.get('total_rollbacks', 0)}"""}

        elif cmd == "/clear":
            self.conversation_history.clear()
            return {"response": "Conversation cleared"}

        elif cmd == "/model":
            return {"response": f"Model: {self.config.model}\nURL: {self.config.ollama_url}"}

        elif cmd == "/deep on":
            result = self.switch_mode(ExecutionMode.DEEP6, reason="manual")
            return {"response": f"{result['message']}\nDeep6 mode (6-step Minsky CoT) enabled"}

        elif cmd == "/deep off":
            result = self.switch_mode(ExecutionMode.FAST, reason="manual")
            return {"response": f"{result['message']}\nDeep mode disabled"}

        # New mode commands
        elif cmd == "/mode":
            status = self.get_mode_status()
            icon = status["icon"]
            deep6_stats = self.get_deep6_stats()
            return {"response": f"""Current Mode: {icon} {status['current_mode'].upper()}
Auto-escalation: {'ON' if status['auto_escalation'] else 'OFF'}
Escalations: {status['escalations_count']}
Web searches: {status['web_searches_count']}
Deep6 sessions: {deep6_stats['sessions']}
Deep6 rollbacks: {deep6_stats['rollbacks']}

Use /mode fast|deep3|deep|search to switch"""}

        elif cmd == "/mode fast":
            result = self.switch_mode(ExecutionMode.FAST, reason="manual")
            return {"response": result["message"]}

        elif cmd == "/mode deep3":
            result = self.switch_mode(ExecutionMode.DEEP3, reason="manual")
            return {"response": result["message"]}

        elif cmd == "/mode deep" or cmd == "/mode deep6":
            result = self.switch_mode(ExecutionMode.DEEP6, reason="manual")
            return {"response": result["message"]}

        elif cmd == "/mode search" or cmd == "/mode deepsearch":
            result = self.switch_mode(ExecutionMode.SEARCH, reason="manual")
            return {"response": result["message"]}

        elif cmd == "/escalation on":
            self.config.auto_escalation = True
            return {"response": "[CONFIG] Auto-escalation ENABLED\nFAST -> DEEP -> DEEP_SEARCH on timeout"}

        elif cmd == "/escalation off":
            self.config.auto_escalation = False
            return {"response": "[CONFIG] Auto-escalation DISABLED"}

        elif cmd.startswith("/search "):
            # Direct web search
            query = cmd[8:].strip()
            result = self.web_search(query)
            if result["success"]:
                lines = [f"Web search: {query}", "=" * 40]
                for r in result["results"]:
                    lines.append(f"\n{r.get('title', r.get('type', ''))}:")
                    lines.append(f"  {r.get('text', '')}")
                    if r.get('url'):
                        lines.append(f"  URL: {r['url']}")
                return {"response": "\n".join(lines)}
            else:
                return {"response": f"Search error: {result.get('error', 'unknown')}"}

        return None

    # Pattern to detect "add/fix/update X in/to file.ext"
    _PRE_READ_PATTERN = re.compile(
        r'(?:add|insert|append|fix|update|modify|refactor|implement|remove|delete|change)\s+'
        r'.+?\s+(?:in|to|from|of)\s+["\']?([^\s"\']+\.\w{1,10})["\']?',
        re.IGNORECASE
    )

    @staticmethod
    def _strip_line_numbers(content: str) -> str:
        """
        Strip line number prefixes from read tool output.
        The read tool returns lines like "     1: code here" — we strip
        the "     N: " prefix so the LLM sees raw file content and can
        use exact strings in old_string for edits.
        """
        lines = content.split('\n')
        stripped = []
        for line in lines:
            # Match format: optional spaces + digits + colon + space
            m = re.match(r'^\s*\d+:\s?', line)
            if m:
                stripped.append(line[m.end():])
            else:
                stripped.append(line)
        return '\n'.join(stripped)

    def _try_pre_read(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        NO-LLM pre-read: detect file modification requests and auto-read the file.
        This gives the LLM file context on the first call, saving one round-trip.
        Returns dict with file content (line numbers stripped) and tool_call info, or None.
        """
        match = self._PRE_READ_PATTERN.search(user_input)
        if not match:
            return None

        file_path = match.group(1)

        # Validate it looks like a real file path (has extension)
        if '.' not in file_path or file_path.startswith('http'):
            return None

        # Execute read (NO-LLM)
        try:
            read_result = execute_tool('read', file_path=file_path)
            if read_result.get("success"):
                self.stats["tool_calls"] += 1
                # Strip line numbers so LLM sees raw content for exact old_string matching
                raw_content = self._strip_line_numbers(read_result.get("content", ""))
                return {
                    "file_path": file_path,
                    "content": raw_content,
                    "tool_call": {
                        "tool": "read",
                        "params": {"file_path": file_path},
                        "result": read_result
                    }
                }
        except Exception:
            pass

        return None

    def _is_complex_task(self, user_input: str) -> bool:
        """Detect if task needs CoT reasoning"""
        complex_indicators = [
            "refactor", "optimize", "design", "architect",
            "debug", "analyze", "explain why", "create test",
            "implement", "build", "migrate", "upgrade",
            "security", "performance", "scale"
        ]
        input_lower = user_input.lower()
        return any(ind in input_lower for ind in complex_indicators)

    # ==================== DEEP6 MINSKY PROCESSING ====================

    def _process_deep6(
        self,
        user_input: str,
        pre_read_context: Optional[Dict] = None,
        ducs_result: Optional[Dict] = None,
        swecas_result: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Process using Deep6 Minsky engine (full 6-step CoT with iterative rollback).

        Steps (per Minsky's cognitive hierarchy):
        1. REACTION - Quick classification
        2. DELIBERATION - Pattern matching
        3. REFLECTIVE - Method analysis
        4. SELF-REFLECTIVE - Critical audit (CAN TRIGGER ROLLBACK)
        5. SELF-CONSTRUCTIVE - Code synthesis
        6. VALUES/IDEALS - Final verification

        Returns structured result with code, audit, and rollback info.
        """
        self.stats["deep6_sessions"] += 1

        # Build context from pre-read and classifications
        context = ""
        if pre_read_context and pre_read_context.get("content"):
            file_path = pre_read_context["file_path"]
            file_content = pre_read_context["content"][:2000]  # Limit context
            context += f"\n\nFile content ({file_path}):\n```\n{file_content}\n```"

        if ducs_result and ducs_result.get("confidence", 0) >= 0.5:
            context += f"\n\nDomain: DUCS-{ducs_result.get('ducs_code', '')} ({ducs_result.get('category', '')})"

        if swecas_result and swecas_result.get("confidence", 0) >= 0.6:
            context += f"\nBug pattern: SWECAS-{swecas_result.get('swecas_code', '')} ({swecas_result.get('name', '')})"
            if swecas_result.get("fix_hint"):
                context += f"\nFix hint: {swecas_result['fix_hint']}"

        # Execute Deep6 Minsky pipeline
        if self.config.verbose:
            print(f"[DEEP6] Starting 6-step Minsky pipeline...")

        deep6_result = self.deep6_engine.execute(
            query=user_input,
            context=context,
            verbose=self.config.verbose,
            on_step=self._on_deep6_step if self.config.verbose else None
        )

        # Track rollbacks
        if deep6_result.rollback_reasons:
            self.stats["deep6_rollbacks"] += len(deep6_result.rollback_reasons)

        # Build response
        response_parts = []

        # Add thinking steps summary
        thinking = []
        for step_name, step_content in deep6_result.steps.items():
            if step_content and len(step_content) > 10:
                # Extract first 200 chars of each step for thinking display
                thinking.append(f"[{step_name.upper()}] {step_content[:200]}...")

        # Add main response
        if deep6_result.final_code:
            response_parts.append("## Generated Code\n")
            response_parts.append(f"```python\n{deep6_result.final_code}\n```")

        if deep6_result.final_explanation:
            response_parts.append(f"\n\n## Verification\n{deep6_result.final_explanation[:500]}")

        # Add audit summary if available
        if deep6_result.audit_results:
            last_audit = deep6_result.audit_results[-1]
            response_parts.append(f"\n\n## Audit Summary")
            response_parts.append(f"- Risk Score: {last_audit.overall_risk_score}/10")
            response_parts.append(f"- Decision: {last_audit.decision}")
            if last_audit.vulnerabilities_found:
                response_parts.append(f"- Vulnerabilities: {len(last_audit.vulnerabilities_found)}")
                for v in last_audit.vulnerabilities_found[:3]:
                    response_parts.append(f"  - [{v.severity}] {v.description}")

        # Add rollback info if any
        if deep6_result.rollback_reasons:
            response_parts.append(f"\n\n## Rollbacks")
            response_parts.append(f"Iterations: {deep6_result.iterations}")
            for reason in deep6_result.rollback_reasons:
                response_parts.append(f"- {reason}")

        response = "\n".join(response_parts) if response_parts else deep6_result.final_code or "No output generated"

        # Build tool calls from Deep6 (if code contains tool patterns)
        tool_calls = []
        if deep6_result.final_code and pre_read_context:
            # If we have pre-read context and generated code, suggest edit
            tool_calls.append({
                "tool": "edit_suggestion",
                "params": {
                    "file_path": pre_read_context["file_path"],
                    "code": deep6_result.final_code
                },
                "result": {"suggested": True, "from": "deep6_minsky"}
            })

        return {
            "success": deep6_result.success,
            "response": response,
            "tool_calls": tool_calls,
            "thinking": thinking,
            "audit": deep6_result.audit_results[-1].to_dict() if deep6_result.audit_results else {},
            "iterations": deep6_result.iterations,
            "rollbacks": deep6_result.rollback_reasons,
            "call_sequence": deep6_result.call_sequence,
            "duration_ms": deep6_result.total_duration_ms,
            "task_type": deep6_result.task_type.value,
            "has_code": deep6_result.has_code,
            "adversarial_passed": deep6_result.adversarial_passed
        }

    def _on_deep6_step(self, step_name: str, output: str):
        """Callback for Deep6 step progress (verbose mode)"""
        # Truncate output for display
        preview = output[:100].replace('\n', ' ') if output else ""
        print(f"  [{step_name.upper()}] {preview}...")

    def get_deep6_stats(self) -> Dict[str, Any]:
        """Get Deep6 Minsky engine statistics"""
        return {
            "sessions": self.stats["deep6_sessions"],
            "rollbacks": self.stats["deep6_rollbacks"],
            "engine_stats": self.deep6_engine.get_statistics()
        }

    # ==================== MODE SWITCHING SYSTEM ====================

    def switch_mode(self, new_mode: str, reason: str = "manual") -> Dict[str, Any]:
        """
        Переключение режима работы

        Args:
            new_mode: ExecutionMode.FAST, DEEP, или DEEP_SEARCH
            reason: "manual", "escalation", "auto"

        Returns:
            Результат переключения
        """
        old_mode = self.current_mode

        # All valid modes (5 canonical modes)
        valid_modes = [
            ExecutionMode.FAST,
            ExecutionMode.DEEP3,
            ExecutionMode.DEEP6,
            ExecutionMode.SEARCH,
            ExecutionMode.SEARCH_DEEP
        ]

        if new_mode not in valid_modes:
            return {
                "success": False,
                "error": f"Unknown mode: {new_mode}. Use: fast, deep3, deep6, search, search_deep"
            }

        self.current_mode = new_mode
        self.config.execution_mode = new_mode

        # Обновляем deep_mode для совместимости
        self.config.deep_mode = new_mode.is_deep

        # Запись в историю
        self.mode_history.append({
            "from": old_mode.value,
            "to": new_mode.value,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })

        if reason == "escalation":
            self.stats["mode_escalations"] += 1

        icon_old = old_mode.icon
        icon_new = new_mode.icon

        return {
            "success": True,
            "message": f"[MODE] {icon_old} {old_mode.name} -> {icon_new} {new_mode.name}",
            "reason": reason,
            "old_mode": old_mode.value,
            "new_mode": new_mode.value
        }

    def escalate_mode(self) -> Dict[str, Any]:
        """
        Автоматическая эскалация режима при timeout
        FAST -> DEEP -> DEEP_SEARCH
        """
        next_mode = ESCALATION_CHAIN.get(self.current_mode)

        if next_mode is None:
            return {
                "success": False,
                "message": "[ESCALATION] Already at maximum mode (SEARCH_DEEP)",
                "mode": self.current_mode.value
            }

        result = self.switch_mode(next_mode, reason="escalation")

        if result["success"]:
            result["message"] = f"[ESCALATION] {result['message']} (timeout triggered)"

        return result

    def detect_mode_from_input(self, user_input: str) -> str:
        """
        Определить режим из пользовательского ввода

        Поддерживаемые форматы:
        - [DEEP3] -> DEEP3 MODE (3 шага)
        - [DEEP6] или [DEEP] или --deep -> DEEP MODE (6 шагов Мински)
        - [SEARCH+DEEP] или [DEEP SEARCH] или [SEARCH] или --search -> DEEP_SEARCH MODE
        """
        input_upper = user_input.upper()

        # SEARCH + DEEP indicators (комбинированный режим: search → deep analysis)
        if any(ind in input_upper for ind in ["[SEARCH+DEEP]", "[SEARCHDEEP]"]):
            return ExecutionMode.SEARCH_DEEP

        # Simple SEARCH (только поиск, без deep анализа)
        if any(ind in input_upper for ind in ["[SEARCH]", "--SEARCH", "/SEARCH"]):
            return ExecutionMode.SEARCH  # legacy: DEEP_SEARCH = simple search

        # DEEP3 MODE indicators (3 шага)
        if "[DEEP3]" in input_upper:
            return ExecutionMode.DEEP3

        # DEEP6/DEEP MODE indicators (6 шагов Мински)
        if any(ind in input_upper for ind in ["[DEEP6]", "[DEEP]", "--DEEP"]):
            return ExecutionMode.DEEP6

        # Default: current mode
        return self.current_mode

    def strip_mode_prefix(self, user_input: str) -> str:
        """Удалить префиксы режимов из запроса"""
        import re
        # Remove mode prefixes
        patterns = [
            r'\[SEARCH\+DEEP\]\s*',
            r'\[SEARCHDEEP\]\s*',
            r'\[DEEP\s*SEARCH\]\s*',
            r'\[SEARCH\]\s*',
            r'\[DEEP6\]\s*',
            r'\[DEEP3\]\s*',
            r'\[DEEP\]\s*',
            r'--deep\s+',
            r'--search\s+',
            r'/search\s+'
        ]
        result = user_input
        for pattern in patterns:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        return result.strip()

    def _load_swecas_search_cache(self) -> Dict[str, Any]:
        """Load SWECAS search cache from JSON file"""
        if hasattr(self, '_swecas_cache') and self._swecas_cache:
            return self._swecas_cache
        try:
            cache_path = os.path.join(os.path.dirname(__file__), 'swecas_search_cache.json')
            with open(cache_path, 'r', encoding='utf-8') as f:
                self._swecas_cache = json.load(f)
            return self._swecas_cache
        except Exception:
            self._swecas_cache = {}
            return self._swecas_cache

    def _get_swecas_cache_fallback(self, swecas_code: int) -> Dict[str, Any]:
        """Get cached search results for a SWECAS category"""
        cache = self._load_swecas_search_cache()
        cat_key = str(swecas_code)
        if cat_key in cache:
            cat_data = cache[cat_key]
            results = []
            for i, hint in enumerate(cat_data.get("fix_hints", [])):
                results.append({
                    "type": "swecas_cache",
                    "title": f"SWECAS-{swecas_code} fix pattern #{i+1}",
                    "text": hint,
                    "url": ""
                })
            for pattern in cat_data.get("patterns", []):
                results.append({
                    "type": "swecas_cache",
                    "title": f"Code pattern",
                    "text": pattern,
                    "url": ""
                })
            return {
                "success": True,
                "query": cat_data.get("query", ""),
                "results": results,
                "count": len(results),
                "source": "swecas_cache"
            }
        return {"success": False, "error": "No cache for this category"}

    def web_search(self, query: str) -> Dict[str, Any]:
        """
        Поиск в интернете для DEEP SEARCH режима.
        Fallback chain: configured backend -> alternate backend -> SWECAS cache.

        search_backend config:
          "auto"       -> SearXNG -> DuckDuckGo -> SWECAS cache
          "searxng"    -> SearXNG -> DuckDuckGo -> SWECAS cache
          "duckduckgo" -> DuckDuckGo -> SearXNG -> SWECAS cache
        """
        self.stats["web_searches"] += 1

        backend = self.config.search_backend

        # Build search order based on config
        if backend == "searxng":
            search_order = ["searxng", "duckduckgo"]
        elif backend == "duckduckgo":
            search_order = ["duckduckgo", "searxng"]
        else:  # "auto"
            search_order = ["searxng", "duckduckgo"]

        last_error = None

        for engine in search_order:
            try:
                if engine == "searxng":
                    result = ExtendedTools.web_search_searxng(
                        query, num_results=5, searxng_url=self.config.searxng_url
                    )
                else:
                    result = ExtendedTools.web_search(query, num_results=5)

                if result.get("success"):
                    # Normalize result format
                    results = []
                    for r in result.get("results", []):
                        results.append({
                            "type": "search_result",
                            "title": r.get("title", ""),
                            "text": r.get("snippet", ""),
                            "url": r.get("url", "")
                        })

                    return {
                        "success": True,
                        "query": query,
                        "results": results,
                        "count": len(results),
                        "source": result.get("source", engine)
                    }
                else:
                    last_error = result.get("error", f"{engine} failed")
                    if self.config.verbose:
                        print(f"[SEARCH] {engine} failed: {last_error}, trying next...")

            except Exception as e:
                last_error = str(e)
                if self.config.verbose:
                    print(f"[SEARCH] {engine} exception: {last_error}, trying next...")

        # All backends failed — try SWECAS cache
        return self._try_swecas_cache_fallback({"error": last_error or "All search backends failed"})

    def _try_swecas_cache_fallback(self, failed_result: Dict[str, Any]) -> Dict[str, Any]:
        """Attempt SWECAS cache fallback when web search fails"""
        swecas = getattr(self, '_current_swecas', None)
        if swecas and swecas.get("confidence", 0) >= 0.5:
            cache_result = self._get_swecas_cache_fallback(swecas["swecas_code"])
            if cache_result.get("success"):
                return cache_result
        return {
            "success": False,
            "error": failed_result.get("error", "Search failed, no cache available")
        }

    def _process_search_deep(self, user_input: str) -> Dict[str, Any]:
        """
        SEARCH + DEEP режим:
        1. Сначала web search по запросу пользователя
        2. Результаты поиска + запрос передаются в Deep режим (Deep3 или Deep6)

        Это комбинированный режим для исследовательских задач.
        """
        # Step 1: Web Search
        search_result = self.web_search(user_input)

        search_context = ""
        if search_result["success"] and search_result.get("results"):
            search_context = "\n\n📌 WEB SEARCH RESULTS:\n"
            for i, r in enumerate(search_result["results"][:7], 1):
                title = r.get('title', 'No title')
                text = r.get('text', '')[:300]
                url = r.get('url', '')
                search_context += f"\n[{i}] {title}\n{text}"
                if url:
                    search_context += f"\n    🔗 {url}"
                search_context += "\n"
        else:
            search_context = "\n\n⚠️ Web search returned no results. Proceeding with Deep analysis based on existing knowledge.\n"

        # Step 2: Prepare combined prompt for Deep analysis
        combined_prompt = f"""{user_input}
{search_context}

Please analyze the above query using the web search results (if available) and provide a comprehensive answer."""

        # Step 3: Temporarily switch to Deep mode and process
        original_mode = self.current_mode
        analysis_mode = self.search_deep_analysis_mode  # DEEP3 or DEEP6

        # Switch to deep mode for analysis
        self.current_mode = analysis_mode

        # Enable appropriate CoT mode
        if analysis_mode == ExecutionMode.DEEP6:
            self.cot_engine.enable_deep_mode(True)
            self.cot_engine.enable_deep3_mode(False)
            mode_label = "Deep6 (6-step Minsky)"
        else:
            self.cot_engine.enable_deep3_mode(True)
            self.cot_engine.enable_deep_mode(False)
            mode_label = "Deep3 (3-step)"

        try:
            # Process with deep analysis
            result = self.process(combined_prompt)

            # Enhance response with search info
            response = result.get("response", "")
            if search_result["success"]:
                sources = "\n\n---\n📚 **Sources:**\n"
                for r in search_result.get("results", [])[:5]:
                    if r.get('url'):
                        sources += f"- [{r.get('title', 'Link')}]({r['url']})\n"
                response += sources

            result["response"] = response
            result["mode"] = ExecutionMode.SEARCH_DEEP.value
            result["mode_icon"] = ExecutionMode.SEARCH_DEEP.icon
            result["route_method"] = f"search_deep ({mode_label})"
            result["web_search"] = search_result

        finally:
            # Restore original mode
            self.current_mode = original_mode
            self.cot_engine.enable_deep_mode(False)
            self.cot_engine.enable_deep3_mode(False)

        return result

    def set_search_deep_mode(self, deep_mode: str) -> Dict[str, Any]:
        """
        Установить режим глубокого анализа для Search+Deep

        Args:
            deep_mode: 'deep3' или 'deep6'
        """
        if deep_mode.lower() == 'deep3':
            self.search_deep_analysis_mode = ExecutionMode.DEEP3
            return {"success": True, "mode": "deep3", "message": "Search+Deep will use Deep3 (3-step) analysis"}
        elif deep_mode.lower() in ['deep6', 'deep']:
            self.search_deep_analysis_mode = ExecutionMode.DEEP6
            return {"success": True, "mode": "deep6", "message": "Search+Deep will use Deep6 (6-step Minsky) analysis"}
        else:
            return {"success": False, "error": f"Unknown mode: {deep_mode}. Use 'deep3' or 'deep6'"}

    def process_with_mode(self, user_input: str) -> Dict[str, Any]:
        """
        Обработка с автоматическим определением режима
        Главная точка входа с поддержкой всех режимов
        """
        import time

        # Определить режим из ввода
        requested_mode = self.detect_mode_from_input(user_input)

        # Переключить режим если нужно
        if requested_mode != self.current_mode:
            self.switch_mode(requested_mode, reason="auto")
            print(f"[DEBUG process_with_mode] Switched to: {self.current_mode}")

        # Убрать префиксы режимов
        clean_input = self.strip_mode_prefix(user_input)
        print(f"[DEBUG process_with_mode] Clean input: {clean_input[:50]}...")

        # ALWAYS check special commands first (before mode-specific handling)
        special = self._handle_special_commands(clean_input)
        if special:
            print(f"[DEBUG process_with_mode] Special command handled: {clean_input[:30]}")
            return {
                "success": True,
                "response": special["response"],
                "mode": self.current_mode.value,
                "mode_icon": self.current_mode.icon,
                "tool_calls": [],
                "thinking": [],
                "route_method": "special_command",
                "iterations": 0,
                "plan_mode": self.plan_mode.is_active
            }

        # DEEP SEARCH: выполнить веб-поиск и напрямую LLM (без pattern routing)
        print(f"[DEBUG process_with_mode] Checking DEEP_SEARCH: current={self.current_mode}, expected={ExecutionMode.SEARCH}")
        if self.current_mode == ExecutionMode.SEARCH:
            search_result = self.web_search(clean_input)

            # Форматировать результаты поиска
            if search_result["success"] and search_result["results"]:
                context = "Web search results:\n"
                for r in search_result["results"][:5]:
                    text = r.get('text', '')[:200]
                    context += f"- {r.get('title', '')}: {text}\n"
                    if r.get("url"):
                        context += f"  URL: {r['url']}\n"

                # LLM анализ результатов (lightweight, no tools/history)
                analysis_prompt = f"""Query: "{clean_input}"

{context}

Summarize key findings in 3-5 bullet points. Include URLs."""

                llm_response = self._call_llm_search(analysis_prompt)

                return {
                    "success": True,
                    "response": llm_response or "No analysis available",
                    "mode": self.current_mode.value,
                    "mode_icon": self.current_mode.icon,
                    "tool_calls": [],
                    "thinking": [],
                    "route_method": "deep_search",
                    "iterations": 1,
                    "plan_mode": self.plan_mode.is_active,
                    "web_search": search_result
                }
            else:
                return {
                    "success": False,
                    "response": f"Web search failed: {search_result.get('error', 'No results')}",
                    "mode": self.current_mode.value,
                    "mode_icon": self.current_mode.icon,
                    "tool_calls": [],
                    "thinking": [],
                    "route_method": "deep_search",
                    "iterations": 0,
                    "plan_mode": self.plan_mode.is_active
                }

        # SEARCH + DEEP: сначала поиск, потом результаты передаются в Deep режим
        if self.current_mode == ExecutionMode.SEARCH_DEEP:
            return self._process_search_deep(clean_input)

        # Запустить обработку с timeout
        start_time = time.time()

        try:
            result = self.process(clean_input)

            # Добавить информацию о режиме
            result["mode"] = self.current_mode.value
            result["mode_icon"] = self.current_mode.icon

            return result

        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time

            # Автоматическая эскалация при timeout
            if self.config.auto_escalation:
                escalation = self.escalate_mode()

                if escalation["success"]:
                    # Повторить с новым режимом
                    return self.process_with_mode(user_input)
                else:
                    return {
                        "success": False,
                        "error": f"Timeout after {elapsed:.1f}s. Max escalation reached.",
                        "mode": self.current_mode.value
                    }
            else:
                return {
                    "success": False,
                    "error": f"Timeout after {elapsed:.1f}s",
                    "mode": self.current_mode.value
                }

    def get_mode_status(self) -> Dict[str, Any]:
        """Получить текущий статус режима"""
        return {
            "current_mode": self.current_mode.value,
            "icon": self.current_mode.icon,
            "label": self.current_mode.label,
            "is_deep": self.current_mode.is_deep,
            "is_search": self.current_mode.is_search,
            "deep_mode": self.config.deep_mode,
            "auto_escalation": self.config.auto_escalation,
            "mode_history": self.mode_history[-5:],  # Last 5 switches
            "escalations_count": self.stats["mode_escalations"],
            "web_searches_count": self.stats["web_searches"]
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics including timeout metrics"""
        # Get timeout stats from LLM client
        timeout_stats = self.llm_client.get_stats() if hasattr(self, 'llm_client') else {}

        return {
            **self.stats,
            "model": self.config.model,
            "deep_mode": self.config.deep_mode,
            "plan_mode_active": self.plan_mode.is_active,
            "conversation_length": len(self.conversation_history),
            # Phase 1: Timeout stats
            "timeout_stats": timeout_stats,
            "timeout_config": {
                "ttft": self.timeout_config.ttft_timeout if hasattr(self, 'timeout_config') else None,
                "idle": self.timeout_config.idle_timeout if hasattr(self, 'timeout_config') else None,
                "max": self.timeout_config.absolute_max if hasattr(self, 'timeout_config') else None
            },
            "user_priority": self.user_prefs.priority if hasattr(self, 'user_prefs') else None
        }
