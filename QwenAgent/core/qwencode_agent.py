"""
QwenCode Agent - Full Claude Code Clone
All features of Claude Code, powered by Qwen LLM
"""

import os
import re
import json
import time
import requests
from pathlib import Path
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
try:
    from .deep6_minsky import Deep6Minsky, Deep6Result  # Full 6-step Minsky CoT
except ImportError:
    Deep6Minsky = None
    Deep6Result = None

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

# Phase 5: No-LLM Optimization Components
from .no_llm_responder import NoLLMResponder, NoLLMResponse, ResponseType
from .solution_cache import SolutionCache
from .static_analyzer import StaticAnalyzer

# Phase 6: Query Modifier Engine
from .query_modifier import QueryModifierEngine, ModifierCommands

# Week 2: Working Memory for multi-step tasks
from .working_memory import WorkingMemory

# Week 3: Multi-Candidate Generation Pipeline
try:
    from .generation.pipeline import MultiCandidatePipeline, PipelineConfig, PipelineResult
    from .generation.llm_adapter import AsyncLLMAdapter
    from .generation.adaptive_strategy import AdaptiveStrategy
    HAS_MULTI_CANDIDATE = True
except ImportError as _mc_err:
    HAS_MULTI_CANDIDATE = False
    MultiCandidatePipeline = None
    AdaptiveStrategy = None
    print(f"[MULTI-CANDIDATE] Import failed: {_mc_err}")

# Week 15: Self-Correction Loop
try:
    from .generation.self_correction import SelfCorrectionLoop, CorrectionResult
    HAS_SELF_CORRECTION = True
except ImportError:
    HAS_SELF_CORRECTION = False
    SelfCorrectionLoop = None  # type: ignore

# Week 3.1: Cross-Architecture Review via Claude Haiku
try:
    from .cross_arch_review import CrossArchReviewer
    HAS_CROSS_REVIEW = True
except ImportError:
    HAS_CROSS_REVIEW = False
    CrossArchReviewer = None

# Week 8: OSS Consciousness integration
try:
    from .oss.oss_tool import OSSTool
    HAS_OSS = True
except ImportError:
    HAS_OSS = False
    OSSTool = None

# Week 9: BigQuery OSS pattern discovery
try:
    from .oss.bigquery_sync import BigQuerySync, SyncConfig
    from .oss.bigquery_collector import BigQueryConfig
    HAS_BIGQUERY = True
except ImportError:
    HAS_BIGQUERY = False
    BigQuerySync = None  # type: ignore
    SyncConfig = None  # type: ignore
    BigQueryConfig = None  # type: ignore

# Week 10: Neo4j Knowledge Graph for OSS pattern co-occurrence
try:
    from .oss.neo4j_graph import Neo4jGraph
    from .oss.graph_builder import GraphBuilder
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False
    Neo4jGraph = None  # type: ignore
    GraphBuilder = None  # type: ignore

# Week 11: Task Abstraction Layer
try:
    from .task_abstraction import TaskAbstraction, TaskContext, TaskType, RiskLevel, ValidationProfile
    HAS_TASK_ABSTRACTION = True
except ImportError:
    HAS_TASK_ABSTRACTION = False
    TaskAbstraction = None  # type: ignore

# Week 13: Outcome Feedback Loop
try:
    from .outcome_tracker import OutcomeTracker, OutcomeRecord, _query_hash
    HAS_OUTCOME_TRACKER = True
except ImportError:
    HAS_OUTCOME_TRACKER = False
    OutcomeTracker = None  # type: ignore


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

        # Phase 5: No-LLM Optimization Components
        self.solution_cache = SolutionCache()  # SQLite-based solution cache
        self.no_llm_responder = NoLLMResponder(solution_cache=self.solution_cache)
        self.static_analyzer = StaticAnalyzer(use_ruff=True)

        # Phase 6: Query Modifier Engine
        self.query_modifier = QueryModifierEngine()
        self.query_modifier.set_language("ru")
        if self.user_prefs:
            self.query_modifier.load_from_config(self.user_prefs.__dict__)
        self.modifier_commands = ModifierCommands(self.query_modifier)

        # Deep6 Minsky engine (full 6-step CoT with iterative rollback)
        self.deep6_engine = Deep6Minsky(
            fast_model=getattr(config, 'fast_model', None) if config else None,
            heavy_model=getattr(config, 'heavy_model', None) if config else None,
            enable_adversarial=True
        )

        # Week 3: Multi-Candidate Pipeline
        # Use StreamingLLMClient (async) directly — avoids nested event loop
        # from TimeoutLLMClient which breaks aiohttp inside run_sync()
        self.multi_candidate_pipeline = None
        self.adaptive_strategy = None
        if HAS_MULTI_CANDIDATE:
            try:
                from .streaming_llm_client import StreamingLLMClient as _StreamingClient
                mc_timeout = TimeoutConfig(
                    ttft_timeout=120,   # 2 min — slow 7B model on CPU/small GPU
                    idle_timeout=60,    # 1 min between tokens
                    absolute_max=300,   # 5 min absolute ceiling
                )
                mc_async_client = _StreamingClient(
                    base_url=self.config.ollama_url,
                    timeout_config=mc_timeout,
                )
                adapter = AsyncLLMAdapter(
                    mc_async_client,
                    model=self.config.model,
                )
                from .generation.multi_candidate import MultiCandidateConfig
                # Initialize CrossArchReviewer if ANTHROPIC_API_KEY is set
                cross_reviewer = None
                if HAS_CROSS_REVIEW:
                    api_key = os.environ.get("ANTHROPIC_API_KEY")
                    if api_key:
                        cross_reviewer = CrossArchReviewer(
                            api_key=api_key,
                            monthly_budget=5.0,
                        )
                        print("[CROSS-REVIEW] Enabled (Claude Haiku)")

                self.multi_candidate_pipeline = MultiCandidatePipeline(
                    llm=adapter,
                    config=PipelineConfig(
                        n_candidates=2,             # 2 candidates for single-GPU
                        parallel_generation=False,   # Sequential — avoids GPU contention
                        fail_fast_validation=True,
                        generation_config=MultiCandidateConfig(
                            per_candidate_timeout=300.0,  # 5 min per candidate
                            total_timeout=660.0,          # 11 min total
                        ),
                        cross_reviewer=cross_reviewer,
                    ),
                )
                print(f"[MULTI-CANDIDATE] Initialized (model={self.config.model}, n=2)")
                # Week 4: Adaptive Temperature Strategy
                try:
                    history_dir = Path(self.config.working_dir) / ".qwencode"
                    self.adaptive_strategy = AdaptiveStrategy(
                        history_path=str(history_dir / "adaptive_history.json"),
                        persist=True,
                    )
                    print("[ADAPTIVE] Strategy initialized")
                except Exception as _adp_err:
                    print(f"[ADAPTIVE] Init failed: {_adp_err}")
                    self.adaptive_strategy = None
            except Exception as _mc_init_err:
                print(f"[MULTI-CANDIDATE] Init failed: {_mc_init_err}")

        # Week 8: OSS Consciousness Tool (for pipeline context enrichment)
        self.oss_tool = None
        if HAS_OSS:
            try:
                oss_db_path = os.path.join(
                    self.config.working_dir, ".qwencode", "oss_patterns.db"
                )
                self.oss_tool = OSSTool(db_path=oss_db_path)
                print("[OSS] Tool initialized")
            except Exception as _oss_err:
                print(f"[OSS] Init failed: {_oss_err}")

        # Week 9: BigQuery OSS pattern sync (background daemon)
        self.bq_sync = None
        if HAS_BIGQUERY and self.oss_tool is not None:
            try:
                bq_cfg = BigQueryConfig(
                    cost_history_path=os.path.join(
                        self.config.working_dir, ".qwencode", "bigquery_costs.json"
                    ),
                )
                sync_cfg = SyncConfig(bq_config=bq_cfg)
                self.bq_sync = BigQuerySync(self.oss_tool.store, sync_cfg)
                if self.bq_sync.enabled:
                    self.bq_sync.start()
                    print("[BIGQUERY] Sync daemon started")
                else:
                    print("[BIGQUERY] Not enabled (no credentials or disabled)")
            except Exception as _bq_err:
                print(f"[BIGQUERY] Init failed: {_bq_err}")

        # Week 10: Neo4j Knowledge Graph for OSS pattern co-occurrence
        self.neo4j_graph = None
        self.graph_builder = None
        if HAS_NEO4J and self.oss_tool is not None:
            try:
                self.neo4j_graph = Neo4jGraph()
                if self.neo4j_graph.is_available():
                    self.graph_builder = GraphBuilder(
                        self.oss_tool.store, self.neo4j_graph
                    )
                    print("[NEO4J] Graph connected, builder ready")
                else:
                    print("[NEO4J] Not available (no URI or connection failed)")
            except Exception as _neo4j_err:
                print(f"[NEO4J] Init failed: {_neo4j_err}")

        # Week 11: Task Abstraction Layer
        self.task_abstraction = TaskAbstraction() if HAS_TASK_ABSTRACTION else None

        # Week 13: Outcome Feedback Loop
        self.outcome_tracker = None
        if HAS_OUTCOME_TRACKER:
            try:
                _ot_path = os.path.join(self.config.workspace_dir, ".qwencode", "outcomes.db")
                os.makedirs(os.path.dirname(_ot_path), exist_ok=True)
                self.outcome_tracker = OutcomeTracker(db_path=_ot_path)
            except Exception as _ot_err:
                print(f"[OUTCOME] Init failed: {_ot_err}")

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
            "intent_extensions": 0,
            # Phase 5: No-LLM optimization tracking
            "no_llm_responses": 0,
            "cache_hits": 0,
            "static_analysis_fixes": 0,
            # Phase 6: Query Modifier tracking
            "query_modifications": 0,
            # Week 3: Multi-Candidate tracking
            "multi_candidate_runs": 0,
            "multi_candidate_fallbacks": 0,
            # Week 3.1: Cross-Architecture Review tracking
            "cross_reviews": 0,
            "cross_review_criticals": 0,
            # Week 8: OSS Context tracking
            "oss_context_hits": 0,
            "oss_context_patterns_total": 0,
            # Week 4: Adaptive Strategy tracking
            "adaptive_trivial": 0,
            "adaptive_simple": 0,
            "adaptive_moderate": 0,
            "adaptive_complex": 0,
            "adaptive_critical": 0,
            "adaptive_time_saved_seconds": 0.0,
            # Week 9: BigQuery sync tracking
            "bq_syncs": 0,
            "bq_repos_added": 0,
            "bq_patterns_added": 0,
            "bq_cost_usd": 0.0,
            # Week 10: Neo4j Knowledge Graph tracking
            "neo4j_syncs": 0,
            "neo4j_nodes_total": 0,
            "neo4j_rels_total": 0,
            "neo4j_cooccurrences": 0,
            # Week 11: Task Abstraction tracking
            "task_type_command": 0,
            "task_type_code_gen": 0,
            "task_type_bug_fix": 0,
            "task_type_refactor": 0,
            "task_type_explain": 0,
            "task_type_search": 0,
            "task_type_general": 0,
            "risk_low": 0,
            "risk_medium": 0,
            "risk_high": 0,
            "risk_critical": 0,
            # Week 13: Outcome Feedback Loop tracking
            "outcomes_recorded": 0,
            "outcomes_all_passed": 0,
            # Week 14: Outcome-Driven Profile Adaptation
            "profile_overrides": 0,
            "profile_override_improved": 0,
            # Week 15: Self-Correction Loop
            "correction_runs": 0,
            "correction_iterations_total": 0,
            "correction_improvements": 0,
            "correction_all_passed_after": 0,  # Times correction led to all_passed
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
        print(f"[DEBUG] === process() called === input: {user_input[:50]}...")
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

        # STEP -2: Modifier commands (/lang, /modifiers, /russian, /brief)
        modifier_response = self.modifier_commands.handle(user_input)
        if modifier_response:
            result["response"] = modifier_response
            result["route_method"] = "modifier_command"
            return result

        # STEP -1: Apply query modifiers (language suffix, auto-prefixes)
        original_input = user_input
        user_input = self.query_modifier.process(user_input)
        if user_input != original_input:
            self.stats["query_modifications"] += 1
            print(f"[MODIFIER] '{original_input[:40]}' -> '{user_input[:60]}'")

        # Check for special commands
        special = self._handle_special_commands(user_input)
        if special:
            result["response"] = special["response"]
            result["route_method"] = "special_command"
            return result

        # STEP 0: No-LLM Responder for trivial queries (math, greetings, cached solutions)
        # Extract error context if present in user input (traceback detection)
        error_context = self._extract_error_context(user_input)
        no_llm_result = self.no_llm_responder.try_respond(user_input, context=error_context)
        if no_llm_result.success:
            # Track cache hits separately
            if no_llm_result.response_type == ResponseType.CACHED:
                self.stats["cache_hits"] += 1
            self.stats["no_llm_responses"] += 1
            result["response"] = no_llm_result.response
            result["route_method"] = f"no_llm_{no_llm_result.response_type.value}"
            result["no_llm_confidence"] = no_llm_result.confidence
            if no_llm_result.metadata:
                result["no_llm_metadata"] = no_llm_result.metadata
            if self.config.verbose:
                print(f"[NO-LLM] Responded via {no_llm_result.response_type.value} (conf: {no_llm_result.confidence})")
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

        # STEP 1.7.5: Static Analysis (NO-LLM) - for code in pre_read_content
        static_analysis_context = None
        if pre_read_content and pre_read_content.strip():
            try:
                analysis = self.static_analyzer.analyze(pre_read_content)
                if analysis.has_errors() or analysis.has_warnings():
                    static_analysis_context = analysis.get_context_for_llm(pre_read_content) if hasattr(analysis, 'summary') else analysis.summary
                    result["static_analysis"] = {
                        "ast_valid": analysis.ast_valid,
                        "complexity": analysis.complexity,
                        "undefined_names": analysis.undefined_names[:5],
                        "lint_errors_count": len(analysis.lint_errors),
                        "auto_fixes_count": len(analysis.get_high_confidence_fixes())
                    }
                    # Try auto-fix for high-confidence issues
                    high_conf_fixes = analysis.get_high_confidence_fixes(threshold=0.95)
                    if high_conf_fixes and not analysis.has_errors():
                        result["static_auto_fixes"] = high_conf_fixes
                        self.stats["static_analysis_fixes"] += len(high_conf_fixes)
            except Exception as e:
                if self.config.verbose:
                    print(f"[STATIC-ANALYSIS] Error: {e}")

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

        # Week 2: Working Memory for multi-step context retention
        memory = WorkingMemory(goal=user_input)

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

            # Call LLM with budget-aware timeout (pass remaining budget!)
            llm_response = self._call_llm(current_prompt, system_prompt, max_time=remaining_budget)
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

                # AUTO-FALLBACK: LLM не ответил → автоматический SEARCH
                print(f"[AUTO-FALLBACK] LLM timeout, switching to web search")
                search_result = self.web_search(user_input)
                if search_result.get("success") and search_result.get("results"):
                    # Форматируем результаты поиска
                    response_lines = [f"🌐 **Auto-Search Results** (LLM timeout)\n"]
                    for i, r in enumerate(search_result["results"][:5], 1):
                        title = r.get('title', 'No title')
                        text = r.get('text', '')[:200]
                        url = r.get('url', '')
                        response_lines.append(f"**{i}. {title}**")
                        if text:
                            response_lines.append(f"   {text}...")
                        if url:
                            response_lines.append(f"   🔗 {url}")
                        response_lines.append("")
                    result["response"] = "\n".join(response_lines)
                    result["route_method"] = "auto_search_fallback"
                else:
                    result["response"] = "🌐 LLM timeout. Try /search for web results."
                    result["route_method"] = "timeout_no_results"
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

                # Week 2: Update working memory with each tool result
                memory.update_from_tool_result(tool_name, params, tool_result)

            # Build continuation prompt with tool results and working memory
            current_prompt = self._build_continuation_prompt(tool_results, memory=memory)

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

        # Phase 5: Save to solution cache if this was an error fix
        if error_context and error_context.get("error_type") and result.get("response"):
            try:
                self._save_to_solution_cache(error_context, result["response"])
            except Exception as e:
                if self.config.verbose:
                    print(f"[CACHE] Failed to save: {e}")

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
        print(f"[DEBUG] === process_stream() called === input: {user_input[:50]}...")
        self.stats["total_requests"] += 1

        # Check for special commands
        special = self._handle_special_commands(user_input)
        if special:
            yield {"event": "response", "text": special["response"], "route_method": "special_command"}
            yield {"event": "done"}
            return

        # STEP 0: No-LLM Responder for trivial queries (math, greetings, cached solutions)
        print(f"[DEBUG] process_stream STEP 0: checking no_llm for: '{user_input[:80]}'")
        error_context = self._extract_error_context(user_input)
        no_llm_result = self.no_llm_responder.try_respond(user_input, context=error_context)
        print(f"[DEBUG] process_stream STEP 0: no_llm result success={no_llm_result.success}")
        if no_llm_result.success:
            if no_llm_result.response_type == ResponseType.CACHED:
                self.stats["cache_hits"] += 1
            self.stats["no_llm_responses"] += 1
            yield {"event": "response", "text": no_llm_result.response, "route_method": f"no_llm_{no_llm_result.response_type.value}"}
            yield {"event": "done"}
            return

        # STEP 0.5: Detect code generation tasks for Multi-Candidate
        _is_codegen = self.multi_candidate_pipeline and self._is_code_generation_task(user_input)

        # STEP 1: Try pattern routing (NO-LLM) — skip for code-gen tasks
        route = self.router.route(user_input)

        if route.confidence >= 0.85 and route.tool and not _is_codegen:
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

        # STEP 1.85: OSS Context Enrichment (NO-LLM, <10ms)
        oss_context = ""
        if _is_codegen and self.oss_tool:
            try:
                insight = self.oss_tool.engine.query(user_input)
                if insight.confidence >= 0.3 and insight.patterns:
                    oss_lines = []
                    for p in insight.patterns[:5]:
                        pname = p.get("pattern_name", "unknown")
                        rcount = p.get("repo_count", 0)
                        top = p.get("top_repo", "")
                        oss_lines.append(
                            f"- {pname}: used by {rcount} repos"
                            + (f" (top: {top})" if top else "")
                        )
                    oss_context = "\n".join(oss_lines)
                    self.stats["oss_context_hits"] += 1
                    self.stats["oss_context_patterns_total"] += len(insight.patterns)
                    yield {"event": "status", "text": f"OSS context: {len(insight.patterns)} patterns found"}
            except Exception:
                pass  # Graceful degradation

        # STEP 1.86: Task Abstraction — unified classification (NO-LLM, <1ms)
        task_context = None
        if self.task_abstraction:
            _ta_complexity = "MODERATE"
            if self.adaptive_strategy and _is_codegen:
                try:
                    _ta_swecas = int(swecas_result.get("swecas_code", 0)) if swecas_result.get("confidence", 0) >= 0.5 else None
                    _ta_complexity = self.adaptive_strategy.classify_complexity(user_input, _ta_swecas).value.upper()
                except Exception:
                    pass
            task_context = self.task_abstraction.classify(
                query=user_input,
                ducs_result=ducs_result,
                swecas_result=swecas_result,
                is_codegen=_is_codegen,
                is_command=False,  # commands already returned at STEP 1
                complexity=_ta_complexity,
                execution_mode=self.current_mode,
            )
            # Track stats
            type_key = f"task_type_{task_context.task_type.value}"
            if type_key in self.stats:
                self.stats[type_key] += 1
            risk_key = f"risk_{task_context.risk_level.value}"
            if risk_key in self.stats:
                self.stats[risk_key] += 1
            yield {"event": "status", "text": f"Task: {task_context.task_type.value} | Risk: {task_context.risk_level.value} | Profile: {task_context.validation_profile.value}"}

            # Week 14: Outcome-Driven Profile Adaptation
            if self.outcome_tracker and _is_codegen and HAS_TASK_ABSTRACTION:
                try:
                    from .task_abstraction import ValidationProfile as _VP
                    suggested = self.outcome_tracker.suggest_profile(
                        task_type=task_context.task_type.value,
                        complexity=task_context.complexity,
                    )
                    if suggested and suggested != task_context.validation_profile.value:
                        # Convert string → enum
                        try:
                            new_profile = _VP(suggested)
                            old_profile = task_context.validation_profile
                            task_context.validation_profile = new_profile
                            # Update derived fields from new profile
                            from .task_abstraction import _PROFILE_CONFIGS
                            new_cfg = _PROFILE_CONFIGS.get(new_profile, {})
                            task_context.fail_fast = new_cfg.get("fail_fast", task_context.fail_fast)
                            task_context.parallel_validation = new_cfg.get("parallel", task_context.parallel_validation)
                            self.stats["profile_overrides"] += 1
                            yield {"event": "status", "text": f"Profile override: {old_profile.value} -> {new_profile.value} (learned from {self.outcome_tracker.get_total_outcomes()} outcomes)"}
                        except ValueError:
                            pass  # Unknown profile value
                except Exception:
                    pass  # Graceful degradation

        # STEP 1.8: SEARCH MODE — чистый веб-поиск БЕЗ LLM
        if self.current_mode == ExecutionMode.SEARCH:
            yield {"event": "status", "text": "🌐 Searching the web..."}
            search_result = self.web_search(user_input)

            if search_result["success"] and search_result["results"]:
                # Форматируем результаты без LLM
                response_lines = [f"🌐 **Web Search Results for:** \"{user_input}\"\n"]

                for i, r in enumerate(search_result["results"][:7], 1):
                    title = r.get('title', 'No title')
                    text = r.get('text', '')[:300]
                    url = r.get('url', '')

                    response_lines.append(f"**{i}. {title}**")
                    if text:
                        response_lines.append(f"   {text}...")
                    if url:
                        response_lines.append(f"   🔗 {url}")
                    response_lines.append("")

                response_lines.append(f"---\n*Found {len(search_result['results'])} results*")

                yield {"event": "response", "text": "\n".join(response_lines), "route_method": "web_search_only"}
                yield {"event": "done"}
                return
            else:
                yield {"event": "response", "text": f"🌐 Search failed: {search_result.get('error', 'No results')}", "route_method": "web_search_only"}
                yield {"event": "done"}
                return

        # STEP 1.9: Multi-Candidate Generation (for pure code-gen tasks)
        if _is_codegen:
            swecas_code = None
            if swecas_result.get("confidence", 0) >= 0.5:
                try:
                    swecas_code = int(swecas_result.get("swecas_code", 0))
                except (ValueError, TypeError):
                    pass

            # Week 4: Adaptive strategy for candidate count & temperatures
            adaptive_config = None
            n_cands = self.multi_candidate_pipeline.config.n_candidates
            temperatures = None
            if self.adaptive_strategy:
                adaptive_config = self.adaptive_strategy.get_strategy(user_input, swecas_code)
                n_cands = adaptive_config.n_candidates
                temperatures = adaptive_config.temperatures
                complexity_key = f"adaptive_{adaptive_config.complexity.value}"
                if complexity_key in self.stats:
                    self.stats[complexity_key] += 1
                temps_str = ", ".join(f"{t:.1f}" for t in temperatures)
                yield {"event": "status", "text": f"Generating {n_cands} code variant{'s' if n_cands > 1 else ''} (complexity: {adaptive_config.complexity.value}, temp: {temps_str})..."}
            else:
                yield {"event": "status", "text": f"Generating {n_cands} code variants..."}

            try:
                _pipeline_kwargs = dict(
                    task_id=f"agent_{self.stats['total_requests']}",
                    query=user_input,
                    swecas_code=swecas_code,
                    n=n_cands,
                    temperatures=temperatures,
                    oss_context=oss_context,
                    task_type=task_context.task_type if task_context else None,
                    task_risk=task_context.risk_level if task_context else None,
                    validation_profile=task_context.validation_profile if task_context else None,
                )
                mc_result = self.multi_candidate_pipeline.run_sync(**_pipeline_kwargs)
                self.stats["multi_candidate_runs"] += 1

                # Week 15: Self-Correction Loop — re-generate with error feedback
                correction_result = None
                if (
                    HAS_SELF_CORRECTION
                    and not mc_result.all_passed
                    and mc_result.score >= 0.1
                    and mc_result.code
                ):
                    try:
                        loop = SelfCorrectionLoop(
                            self.multi_candidate_pipeline,
                            max_iterations=3,
                        )

                        def _on_iter(iteration, attempt):
                            pass  # SSE events yielded below via correction_result

                        # Remove query from kwargs (SelfCorrectionLoop has its own)
                        sc_kwargs = {k: v for k, v in _pipeline_kwargs.items() if k != "query" and k != "task_id"}
                        correction_result = loop.run_sync(
                            query=user_input,
                            task_id=_pipeline_kwargs["task_id"],
                            **sc_kwargs,
                        )
                        self.stats["correction_runs"] += 1
                        self.stats["correction_iterations_total"] += correction_result.total_iterations

                        if correction_result.corrected:
                            self.stats["correction_improvements"] += 1
                        if correction_result.all_passed and not mc_result.all_passed:
                            self.stats["correction_all_passed_after"] += 1

                        # Use the corrected result if it's better
                        if correction_result.best_pipeline_result and correction_result.best_score > mc_result.score:
                            mc_result = correction_result.best_pipeline_result
                            yield {
                                "event": "status",
                                "text": f"Self-correction improved score: {correction_result.initial_score:.2f} -> {correction_result.final_score:.2f} ({correction_result.total_iterations} iterations)",
                            }
                        elif correction_result.total_iterations > 1:
                            yield {
                                "event": "status",
                                "text": f"Self-correction: no improvement after {correction_result.total_iterations} iterations",
                            }

                    except Exception as sc_err:
                        logger.warning("[SELF-CORRECTION] Error: %s", sc_err)

                # Record outcome for adaptive learning
                if adaptive_config and self.adaptive_strategy:
                    self.adaptive_strategy.record_outcome(
                        config=adaptive_config,
                        best_score=mc_result.score,
                        all_passed=mc_result.all_passed,
                        total_time=mc_result.total_time,
                        query=user_input,
                        swecas_code=swecas_code,
                    )
                    # Track time saved vs default 2 candidates
                    default_time = 2 * 24.0  # default: 2 candidates @ ~24s each
                    estimated_time = adaptive_config.estimated_time_seconds
                    if estimated_time < default_time:
                        self.stats["adaptive_time_saved_seconds"] += default_time - estimated_time

                # Week 13: Record outcome in unified tracker
                if self.outcome_tracker and mc_result.best:
                    try:
                        _passed = [vs.validator_name for vs in mc_result.best.validation_scores if vs.passed]
                        _failed = [vs.validator_name for vs in mc_result.best.validation_scores if not vs.passed]
                        _all_run = [vs.validator_name for vs in mc_result.best.validation_scores]
                        self.outcome_tracker.record(OutcomeRecord(
                            query_hash=_query_hash(user_input),
                            task_type=task_context.task_type.value if task_context else "general",
                            risk_level=task_context.risk_level.value if task_context else "medium",
                            validation_profile=task_context.validation_profile.value if task_context else "balanced",
                            complexity=task_context.complexity if task_context else "MODERATE",
                            n_candidates=n_cands,
                            best_score=mc_result.score,
                            all_passed=mc_result.all_passed,
                            generation_time=mc_result.generation_time,
                            validation_time=mc_result.validation_time,
                            total_time=mc_result.total_time,
                            rules_run=",".join(_all_run),
                            rules_passed=",".join(_passed),
                            rules_failed=",".join(_failed),
                            n_rules_run=len(_all_run),
                            n_rules_passed=len(_passed),
                            n_rules_failed=len(_failed),
                            swecas_code=swecas_code,
                        ))
                        self.stats["outcomes_recorded"] += 1
                        if mc_result.all_passed:
                            self.stats["outcomes_all_passed"] += 1
                    except Exception:
                        pass  # Graceful degradation

                # Build response
                response_parts = [mc_result.code]
                summary = mc_result.summary()

                # Show validation warnings if any
                if mc_result.best and not mc_result.all_passed:
                    errors = []
                    for vs in mc_result.best.validation_scores:
                        if not vs.passed:
                            errors.extend(vs.errors[:2])
                    if errors:
                        response_parts.append(
                            "\n\n⚠️ Validation warnings:\n"
                            + "\n".join(f"  - {e}" for e in errors[:5])
                        )

                # Cross-Architecture Review results (advisory)
                if mc_result.cross_review_result and not mc_result.cross_review_result.skipped:
                    cr = mc_result.cross_review_result
                    self.stats["cross_reviews"] += 1
                    if cr.has_critical:
                        self.stats["cross_review_criticals"] += 1
                    n_issues = len(cr.issues)
                    yield {"event": "status", "text": f"Cross-review: {n_issues} issues found"}
                    yield {
                        "event": "tool_result",
                        "tool": "cross_review",
                        "params": {"model": cr.model},
                        "result": cr.to_dict(),
                    }
                    # Append critical issues as warnings to the response
                    critical_issues = [i for i in cr.issues if i.severity.value == "critical"]
                    if critical_issues:
                        response_parts.append(
                            "\n\n🔍 Cross-review critical issues:\n"
                            + "\n".join(
                                f"  - [{i.category}] {i.description}"
                                for i in critical_issues[:5]
                            )
                        )

                score_str = f"{mc_result.score:.2f}" if mc_result.score else "N/A"
                yield {"event": "status", "text": f"Best variant selected (score: {score_str}, candidates: {summary.get('candidates_generated', 3)})"}
                yield {
                    "event": "tool_start",
                    "tool": "multi_candidate",
                    "params": {"n_candidates": summary.get("candidates_generated", 3)},
                }
                yield {
                    "event": "tool_result",
                    "tool": "multi_candidate",
                    "params": {"n_candidates": summary.get("candidates_generated", 3)},
                    "result": summary,
                }
                yield {"event": "response", "text": "\n".join(response_parts), "route_method": "multi_candidate"}
                yield {"event": "done"}
                return

            except Exception as mc_err:
                self.stats["multi_candidate_fallbacks"] += 1
                print(f"[MULTI-CANDIDATE ERROR] {mc_err}, falling back to LLM")
                yield {"event": "status", "text": "Multi-Candidate failed, falling back to LLM..."}

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

        # Week 2: Working Memory for multi-step context retention
        memory = WorkingMemory(goal=user_input)

        # Agentic loop
        iteration = 0
        current_prompt = prompt
        all_tool_calls = []

        while iteration < self.config.max_iterations:
            iteration += 1
            yield {"event": "status", "text": f"Step {iteration}..."}

            # Phase 2: Check budget before LLM call
            if self.cot_engine.is_budget_exhausted():
                yield {"event": "response", "text": "[Budget exhausted] Task incomplete.", "route_method": "budget_exhausted"}
                break

            # Phase 2: Get remaining budget for this call
            remaining_budget = self.cot_engine.get_remaining_budget()

            llm_response = self._call_llm(current_prompt, system_prompt, max_time=remaining_budget)
            self.stats["llm_calls"] += 1

            if not llm_response:
                # AUTO-FALLBACK: LLM не ответил → автоматический SEARCH
                print(f"[AUTO-FALLBACK] LLM timeout in stream, switching to web search")
                yield {"event": "status", "text": "🌐 LLM timeout, searching web..."}
                search_result = self.web_search(user_input)
                if search_result.get("success") and search_result.get("results"):
                    response_lines = [f"🌐 **Auto-Search Results** (LLM timeout)\n"]
                    for i, r in enumerate(search_result["results"][:5], 1):
                        title = r.get('title', 'No title')
                        text = r.get('text', '')[:200]
                        url = r.get('url', '')
                        response_lines.append(f"**{i}. {title}**")
                        if text:
                            response_lines.append(f"   {text}...")
                        if url:
                            response_lines.append(f"   🔗 {url}")
                        response_lines.append("")
                    yield {"event": "response", "text": "\n".join(response_lines), "route_method": "auto_search_fallback"}
                else:
                    yield {"event": "response", "text": "🌐 LLM timeout. Try /search for web results.", "route_method": "timeout_no_results"}
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

                # Week 2: Update working memory with each tool result
                memory.update_from_tool_result(tool_name, params, tool_result)

            current_prompt = self._build_continuation_prompt(tool_results, memory=memory)

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

    def _call_llm(self, prompt: str, system: str = None, max_time: float = None) -> Optional[str]:
        """
        Call Ollama LLM with Phase 1+2 timeout management.

        Features:
        - TTFT timeout (model not starting)
        - Idle timeout (model stuck)
        - Absolute max timeout (limited by remaining budget)
        - Automatic fallback to lighter model
        - Partial result preservation

        Args:
            prompt: User prompt
            system: System prompt
            max_time: Maximum time for this call (from TimeBudget.remaining)
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

            # Phase 2: Use remaining budget if provided (limits absolute_max)
            if max_time is not None and max_time < float('inf'):
                effective_budget = min(mode_budget, max_time)
                if self.config.verbose:
                    print(f"[BUDGET] mode={mode_budget:.0f}s, remaining={max_time:.0f}s, using={effective_budget:.0f}s")
            else:
                effective_budget = mode_budget

            timeout_override = TimeoutConfig(
                ttft_timeout=min(self.timeout_config.ttft_timeout, effective_budget * 0.3),
                idle_timeout=min(self.timeout_config.idle_timeout, effective_budget * 0.2),
                absolute_max=effective_budget
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
                    print(f"[FALLBACK] {primary_model} -> {fallback_model}")

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

    def _build_continuation_prompt(self, tool_results: List[Tuple[str, Dict]],
                                    memory: 'WorkingMemory' = None) -> str:
        """Build prompt with tool results and working memory for continuation."""
        lines = []

        # Week 2: Inject working memory context first
        if memory:
            lines.append(memory.compact())
            lines.append("")

        lines.append("Tool results:")
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

    def _extract_error_context(self, user_input: str) -> Dict[str, Any]:
        """
        Extract error context from user input (traceback detection).

        Returns context dict with:
        - error_type: The exception type (TypeError, ValueError, etc.)
        - error_message: The error message
        - code: Code snippet if present
        """
        context = {}

        # Common Python error patterns
        error_patterns = [
            # Full traceback
            r"(\w+Error):\s*(.+?)(?:\n|$)",
            r"(\w+Exception):\s*(.+?)(?:\n|$)",
            # Just error message
            r"(TypeError|ValueError|AttributeError|ImportError|KeyError|IndexError|NameError|SyntaxError):\s*(.+)",
        ]

        for pattern in error_patterns:
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                context["error_type"] = match.group(1)
                context["error_message"] = match.group(2).strip()
                break

        # Extract code block if present
        code_match = re.search(r"```(?:python)?\s*(.*?)```", user_input, re.DOTALL)
        if code_match:
            context["code"] = code_match.group(1).strip()

        # Extract line number if present
        line_match = re.search(r"line (\d+)", user_input, re.IGNORECASE)
        if line_match:
            context["line_number"] = int(line_match.group(1))

        return context

    def _save_to_solution_cache(self, error_context: Dict[str, Any], solution: str):
        """
        Save a successful solution to the cache for future reuse.

        Only saves if:
        - Error context is present with error_type
        - Solution is not empty and doesn't contain error markers
        - Solution contains code (has code block or specific keywords)
        """
        if not error_context or not error_context.get("error_type"):
            return

        # Validate solution quality
        if not solution or len(solution) < 20:
            return
        if "Error:" in solution or "error" in solution.lower()[:50]:
            return

        # Check if solution has actionable content
        has_code = "```" in solution or "def " in solution or "if " in solution
        has_instruction = any(kw in solution.lower() for kw in ["add", "change", "remove", "replace", "use"])

        if not (has_code or has_instruction):
            return

        # Determine SWECAS category from error type
        error_type = error_context.get("error_type", "")
        swecas_map = {
            "AttributeError": "NULL_POINTER",
            "TypeError": "TYPE_ERROR",
            "ValueError": "TYPE_ERROR",
            "ImportError": "IMPORT_ERROR",
            "ModuleNotFoundError": "IMPORT_ERROR",
            "KeyError": "INDEX_ERROR",
            "IndexError": "INDEX_ERROR",
            "SyntaxError": "SYNTAX_ERROR",
            "NameError": "UNDEFINED_NAME",
        }
        swecas_category = swecas_map.get(error_type, "UNKNOWN")

        # Store in cache
        self.solution_cache.store(
            error_type=error_context.get("error_type", ""),
            error_msg=error_context.get("error_message", ""),
            code_context=error_context.get("code", ""),
            solution=solution,
            swecas_category=swecas_category,
            confidence=0.75  # Initial confidence, will adjust based on success rate
        )

        if self.config.verbose:
            print(f"[CACHE] Saved solution for {error_type} ({swecas_category})")

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

QUERY MODIFIERS:
/lang ru          - Answer in Russian (default)
/lang en          - Answer in English
/lang auto        - Auto-detect language
/russian on/off   - Toggle auto-Russian
/brief on/off     - Toggle code-only replies
/modifiers        - List all modifiers

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
            # Add No-LLM responder and cache stats
            no_llm_stats = self.no_llm_responder.get_stats()
            cache_stats = self.solution_cache.get_stats()
            stats_output = {
                **self.stats,
                "deep6_engine": self.deep6_engine.get_statistics(),
                "no_llm": {
                    "total_no_llm_responses": no_llm_stats.get("total_requests", 0) - no_llm_stats.get("llm_required", 0),
                    "no_llm_rate_percent": round(no_llm_stats.get("no_llm_rate", 0), 1),
                    "direct_responses": no_llm_stats.get("direct_responses", 0),
                    "template_responses": no_llm_stats.get("template_responses", 0),
                    "command_responses": no_llm_stats.get("command_responses", 0),
                },
                "solution_cache": {
                    "total_solutions": cache_stats.get("total_solutions", 0),
                    "cache_hit_rate_percent": cache_stats.get("hit_rate_percent", 0),
                    "cache_hits": cache_stats.get("cache_hits", 0),
                    "cache_misses": cache_stats.get("cache_misses", 0),
                }
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

    # Compiled regex patterns for code-gen detection (class-level, compiled once)
    _CODEGEN_PATTERNS = [
        # "write a [lang] function/class/script/code"
        re.compile(r"write\s+(?:a\s+)?(?:\w+\s+)?(?:function|class|script|code|module|test)\b"),
        # "create a [lang] function/class/script/dockerfile/makefile"
        re.compile(r"create\s+(?:a\s+)?(?:\w+\s+)?(?:function|class|script|dockerfile|makefile)\b"),
        # "implement a/the [lang] ..."
        re.compile(r"implement\s+(?:a\s+|the\s+)?"),
        # "generate code/a function/a class"
        re.compile(r"generate\s+(?:code|a\s+\w*\s*(?:function|class|script))\b"),
        # "write python/dockerfile/yaml/terraform/makefile"
        re.compile(r"write\s+(?:python|dockerfile|yaml|terraform|makefile|test)\b"),
        # Russian patterns
        re.compile(r"напиши\s+(?:\w+\s+)?(?:функцию|код|класс|скрипт|тест|dockerfile)\b"),
        re.compile(r"создай\s+(?:\w+\s+)?(?:функцию|класс|скрипт|dockerfile|makefile)\b"),
        re.compile(r"реализуй\s+"),
        re.compile(r"сгенерируй\s+"),
    ]
    _CODEGEN_EXCLUSIONS = [
        # File edit/read tasks — NOT code generation
        re.compile(r"\bedit\s+\w+\.\w+"),
        re.compile(r"\bmodify\s+\w+\.\w+"),
        re.compile(r"\bchange\s+\w+\.\w+"),
        re.compile(r"\bfix\s+in\s+"),
        re.compile(r"\bread\s+(?:file|the\s+file)\b"),
        re.compile(r"\.\w{1,4}\s"),  # ".py ", ".yaml ", ".json " etc.
        re.compile(r"\bфайл\s+\w+"),
        re.compile(r"\bисправь\s+в\s+"),
        re.compile(r"\bизмени\s+в\s+"),
    ]

    def _is_code_generation_task(self, user_input: str) -> bool:
        """
        Detect if task is a pure code generation request
        suitable for Multi-Candidate pipeline.

        Uses regex for flexible matching:
          YES: "Write a Python function...", "Create a Dockerfile...", "Implement..."
          NO:  "Read file X", "Edit main.py", "Explain this code"
        """
        input_lower = user_input.lower()

        # Step 1: Must match at least one code-gen pattern
        if not any(p.search(input_lower) for p in self._CODEGEN_PATTERNS):
            return False

        # Step 2: Must NOT match file-edit exclusions (skip "dockerfile")
        test_str = input_lower.replace("dockerfile", "dkrfl")
        if any(p.search(test_str) for p in self._CODEGEN_EXCLUSIONS):
            return False

        return True

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

        # AUTO MODE SELECTION: анализ сложности запроса
        # SEARCH и SEARCH_DEEP НЕ включены в авто-выбор — только по кнопке!
        complexity = self._analyze_query_complexity(user_input)

        if complexity == "trivial":
            return ExecutionMode.FAST
        elif complexity == "simple":
            return ExecutionMode.FAST
        elif complexity == "medium":
            return ExecutionMode.DEEP3
        elif complexity == "complex":
            return ExecutionMode.DEEP6
        elif complexity == "needs_search":
            # Автоматически переключаем на SEARCH для не-кодовых вопросов
            print(f"[AUTO-SEARCH] Query needs web search, switching to SEARCH mode")
            return ExecutionMode.SEARCH

        # Default: current mode
        return self.current_mode

    def _analyze_query_complexity(self, query: str) -> str:
        """
        Автоматический анализ сложности запроса.

        Returns:
            "trivial" - простейшие запросы (2+2, привет)
            "simple" - однострочные вопросы
            "medium" - требует анализа кода
            "complex" - многофайловые изменения, архитектура
            "needs_search" - требует актуальной информации из интернета
        """
        query_lower = query.lower().strip()
        print(f"[ANALYZE] Input query: '{query_lower[:50]}'")
        query_len = len(query)

        # TRIVIAL: математика, приветствия (BUT NOT general questions)
        trivial_patterns = [
            r"^\d+\s*[\+\-\*\/\%]\s*\d+",  # 2+2, 10/5
            r"^(hi|hello|hey|привет|ку|хай)\b",
            r"^what is \d",
            r"^(ping|test|echo)",
        ]
        for pattern in trivial_patterns:
            if re.match(pattern, query_lower):
                return "trivial"

        # NEEDS_SEARCH: Check FIRST before length check!
        # General questions require web search even if short
        search_indicators = [
            # Технические запросы
            r"latest|newest|current|recent|2024|2025|2026",
            r"cve-\d{4}-\d+",
            r"documentation|docs|official",
            r"best practice|how to .* in production",
            r"version \d+\.\d+",

            # Общие вопросы о персонах/событиях (EN)
            r"^who is |^who are |^who was ",
            r"^what is (?!.*\.(py|js|ts|go|rs|java|cpp|c|rb|php))",  # what is X (не файлы)
            r"^what are |^what was |^what were ",
            r"^when did |^when was |^when is ",
            r"^where is |^where are |^where was ",
            r"^why did |^why is |^why are ",
            r"^how did .* (happen|start|begin|end)",
            r"news about|news on|latest news",
            r"tell me about (?!.*code|.*file|.*function)",
            r"^list of |^examples of |^main |^basic |^common ",
            r"commands\?|commands$",  # "bash commands?" or "основные команды"

            # Общие вопросы о персонах/событиях (RU)
            r"^кто такой |^кто такая |^кто такие |^кто это ",
            r"^что такое (?!.*\.(py|js|ts|go|rs|java|cpp|c|rb|php))",
            r"^когда |^где |^почему |^зачем ",
            r"^расскажи о |^расскажи про ",
            r"новости о |новости про |последние новости",
            r"что случилось|что произошло",
            r"\bосновные\b|\bбазовые\b|\bглавные\b|\bпопулярные\b",  # где угодно в запросе
            r"команды\?|команды$|операторы|операции|типы данных|синтаксис",
            r"^как работает |^как использовать |^как настроить ",
            r"\bсписок\b|\bпримеры\b",  # где угодно
            # Вопросы о языках программирования (справочная информация)
            r"(python|javascript|java|c\+\+|rust|go|ruby|php|swift|kotlin)\s+(основн|базов|операт|синтакс|типы|команд)",
            r"(основн|базов|операт|синтакс|типы)\s+(python|javascript|java|c\+\+|rust|go|ruby|php|swift|kotlin)",

            # Известные персоны (частые запросы)
            r"трамп|trump|путин|putin|байден|biden|маск|musk|цукерберг|zuckerberg",
            r"президент|president|политик|politician|ceo|founder",

            # События и факты
            r"weather|погода|forecast|прогноз",
            r"stock|акции|price|цена|курс",
            r"score|счёт|результат|match|матч",
        ]
        for pattern in search_indicators:
            if re.search(pattern, query_lower):
                print(f"[ANALYZE] MATCH! Pattern '{pattern}' matched -> needs_search")
                return "needs_search"
        print(f"[ANALYZE] No search patterns matched")

        # Now check length - short non-search queries are trivial
        if query_len < 15:
            return "trivial"

        # COMPLEX: архитектура, рефакторинг, многофайловые изменения
        complex_indicators = [
            r"refactor|redesign|architect",
            r"multiple files|across.*files|whole.*project",
            r"migration|upgrade.*from",
            r"implement.*system|design.*pattern",
            r"integrate|integration",
        ]
        for pattern in complex_indicators:
            if re.search(pattern, query_lower):
                return "complex"

        # MEDIUM: анализ кода, исправление багов
        medium_indicators = [
            r"fix|bug|error|exception|traceback",
            r"why.*not work|doesn't work|broken",
            r"analyze|explain.*code|review",
            r"add.*function|create.*class|implement",
        ]
        for pattern in medium_indicators:
            if re.search(pattern, query_lower):
                return "medium"

        # SIMPLE: короткие вопросы
        if query_len < 100:
            return "simple"

        # Default based on length
        if query_len > 500:
            return "complex"
        elif query_len > 200:
            return "medium"

        return "simple"

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

    def _process_auto_web_search(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Автоматический веб-поиск для общих вопросов.
        Вызывается для вопросов типа "Who is Trump", "Кто такой Путин", etc.

        Returns:
            Dict с ответом если поиск успешен, None если нужно fallback на LLM
        """
        print(f"[AUTO-SEARCH] Processing general question: {user_input[:50]}...")

        try:
            # Perform web search
            search_result = self.web_search(user_input)
            print(f"[AUTO-SEARCH] web_search returned: success={search_result.get('success')}, has_results={bool(search_result.get('results'))}")
        except Exception as e:
            print(f"[AUTO-SEARCH] Exception in web_search: {e}")
            search_result = {"success": False, "error": str(e)}

        # Check for results - look in multiple possible locations
        results = search_result.get("results") or search_result.get("data", {}).get("results", [])
        has_success = search_result.get("success", False)

        # Also check if results are directly in response
        if not results and isinstance(search_result.get("response"), list):
            results = search_result.get("response")

        print(f"[AUTO-SEARCH] Final check: has_success={has_success}, results_count={len(results) if results else 0}")

        if results:
            # Format successful search results

            response = f"🔍 **Результаты поиска по запросу:** {user_input}\n\n"

            for i, r in enumerate(results[:5], 1):
                title = r.get('title', 'No title')
                text = r.get('text', '')[:400]
                url = r.get('url', '')

                response += f"### {i}. {title}\n"
                response += f"{text}\n"
                if url:
                    response += f"🔗 [{url[:60]}...]({url})\n"
                response += "\n"

            response += f"\n---\n_Источник: {search_result.get('source', 'web search')}_"

            return {
                "input": user_input,
                "response": response,
                "tool_calls": [],
                "thinking": [],
                "route_method": "auto_web_search",
                "iterations": 1,
                "plan_mode": False,
                "mode": "search",
                "mode_icon": "🌐",
                "success": True,
                "web_search": search_result
            }
        else:
            # No internet or search failed
            error_msg = search_result.get("error", "Unknown error")

            response = (
                "🚫 **Доступ в интернет отсутствует**\n\n"
                f"Не удалось выполнить поиск по запросу: _{user_input}_\n\n"
                f"Причина: `{error_msg}`\n\n"
                "**Что делать:**\n"
                "1. Проверьте подключение к интернету\n"
                "2. Попробуйте позже\n"
                "3. Или задайте вопрос о программировании - я могу помочь с кодом!\n"
            )

            return {
                "input": user_input,
                "response": response,
                "tool_calls": [],
                "thinking": [],
                "route_method": "auto_web_search_failed",
                "iterations": 1,
                "plan_mode": False,
                "mode": "search",
                "mode_icon": "🚫",
                "success": False,
                "error": error_msg
            }

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
        print(f"[DEBUG] === process_with_mode() called === input: {user_input[:50]}...")
        import time

        # Определить режим из ввода (НО не переключать если пользователь явно выбрал SEARCH)
        if self.current_mode == ExecutionMode.SEARCH:
            # Пользователь явно выбрал SEARCH — не переключать автоматически
            print(f"[DEBUG process_with_mode] SEARCH mode locked by user, skipping auto-detection")
        else:
            requested_mode = self.detect_mode_from_input(user_input)
            # Переключить режим если нужно
            if requested_mode != self.current_mode:
                self.switch_mode(requested_mode, reason="auto")
                print(f"[DEBUG process_with_mode] Switched to: {self.current_mode}")

        # Убрать префиксы режимов
        clean_input = self.strip_mode_prefix(user_input)
        print(f"[DEBUG process_with_mode] Clean input: {clean_input[:50]}...")

        # Modifier commands (/lang, /modifiers, etc.)
        modifier_response = self.modifier_commands.handle(clean_input)
        if modifier_response:
            return {
                "success": True,
                "response": modifier_response,
                "mode": self.current_mode.value,
                "mode_icon": self.current_mode.icon,
                "tool_calls": [],
                "thinking": [],
                "route_method": "modifier_command",
                "iterations": 0,
                "plan_mode": self.plan_mode.is_active
            }

        # Apply query modifiers (language suffix, auto-prefixes)
        original_clean = clean_input
        clean_input = self.query_modifier.process(clean_input)
        if clean_input != original_clean:
            self.stats["query_modifications"] += 1
            print(f"[MODIFIER] '{original_clean[:40]}' -> '{clean_input[:60]}'")

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

        # SEARCH MODE: чистый веб-поиск БЕЗ LLM (только результаты)
        print(f"[DEBUG process_with_mode] SEARCH mode: {self.current_mode}")
        if self.current_mode == ExecutionMode.SEARCH:
            search_result = self.web_search(clean_input)

            # Форматировать результаты поиска (БЕЗ LLM!)
            if search_result["success"] and search_result["results"]:
                # Красивое форматирование результатов
                response_lines = [f"🌐 **Web Search Results for:** \"{clean_input}\"\n"]

                for i, r in enumerate(search_result["results"][:7], 1):
                    title = r.get('title', 'No title')
                    text = r.get('text', '')[:300]
                    url = r.get('url', '')

                    response_lines.append(f"**{i}. {title}**")
                    if text:
                        response_lines.append(f"   {text}...")
                    if url:
                        response_lines.append(f"   🔗 {url}")
                    response_lines.append("")

                response_lines.append(f"---\n*Found {len(search_result['results'])} results*")

                return {
                    "success": True,
                    "response": "\n".join(response_lines),
                    "mode": self.current_mode.value,
                    "mode_icon": self.current_mode.icon,
                    "tool_calls": [],
                    "thinking": [],
                    "route_method": "web_search_only",  # NO LLM!
                    "iterations": 0,
                    "plan_mode": self.plan_mode.is_active,
                    "web_search": search_result
                }
            else:
                return {
                    "success": False,
                    "response": f"🌐 Web search failed: {search_result.get('error', 'No results found')}",
                    "mode": self.current_mode.value,
                    "mode_icon": self.current_mode.icon,
                    "tool_calls": [],
                    "thinking": [],
                    "route_method": "web_search_only",
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

            # AUTO-ESCALATION: Проверить на пустой ответ (timeout handled internally)
            response_text = result.get("response", "")
            is_timeout_response = (
                not response_text or
                response_text == "Error: No response from LLM" or
                "timeout" in response_text.lower()
            )

            if is_timeout_response and self.config.auto_escalation:
                elapsed = time.time() - start_time
                if self.config.verbose:
                    print(f"[AUTO-ESCALATION] Empty response after {elapsed:.1f}s, escalating...")

                escalation = self.escalate_mode()
                if escalation["success"]:
                    # Retry with escalated mode
                    return self.process_with_mode(user_input)
                else:
                    result["escalation_failed"] = True
                    result["escalation_message"] = escalation.get("message", "Max escalation reached")

            return result

        except (LLMTimeoutError, requests.exceptions.Timeout) as e:
            elapsed = time.time() - start_time

            # Автоматическая эскалация при timeout
            if self.config.auto_escalation:
                if self.config.verbose:
                    print(f"[AUTO-ESCALATION] Timeout exception after {elapsed:.1f}s, escalating...")

                escalation = self.escalate_mode()

                if escalation["success"]:
                    # Повторить с новым режимом
                    return self.process_with_mode(user_input)
                else:
                    return {
                        "success": False,
                        "error": f"Timeout after {elapsed:.1f}s. Max escalation reached.",
                        "mode": self.current_mode.value,
                        "partial_result": getattr(e, 'partial_result', None)
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
