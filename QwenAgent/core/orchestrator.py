"""
QwenCode Orchestrator - Центральный координатор
Интеграция ВСЕХ наших разработок:
- NO-LLM паттерны (85%+ запросов без LLM)
- DUCS классификатор
- Chain-of-Thought
- Автономное выполнение
- Self-correction

Это МОЗГ системы - как SWE-Guardian!
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import re
import json

from .ducs_classifier import DUCSClassifier, classify_task
from .pattern_router import PatternRouter  # Legacy fallback
try:
    from .bilingual_context_router import BilingualContextRouter  # NEW: Week 1.5 integration
except ImportError:
    BilingualContextRouter = None  # Optional module
from .router import HybridRouter, RouteResult
from .cot_engine import CoTEngine
from .tools_extended import execute_tool, EXTENDED_TOOL_REGISTRY
from .query_crystallizer import get_crystallizer, TaskType  # Query enhancement
from .working_memory import WorkingMemory  # Week 2: multi-step context

# Multi-Candidate Generation (Week 2)
try:
    from .generation.pipeline import MultiCandidatePipeline, PipelineConfig, PipelineResult
    from .generation.llm_adapter import AsyncLLMAdapter
    MULTI_CANDIDATE_AVAILABLE = True
except ImportError:
    MULTI_CANDIDATE_AVAILABLE = False


class ProcessingTier(Enum):
    """Уровни обработки запросов"""
    TIER0_PATTERN = 0       # Прямое сопоставление паттернов (NO-LLM)
    TIER1_DUCS = 1          # DUCS классификация + шаблоны (NO-LLM)
    TIER2_SIMPLE_LLM = 2    # Простой LLM запрос
    TIER3_COT = 3           # Chain-of-Thought reasoning
    TIER4_AUTONOMOUS = 4    # Полностью автономный агент


@dataclass
class ProcessingResult:
    """Результат обработки запроса"""
    tier: ProcessingTier
    response: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    thinking: List[str] = field(default_factory=list)
    ducs_code: Optional[str] = None
    confidence: float = 0.0
    iterations: int = 0
    self_corrections: int = 0
    processing_time_ms: int = 0


class Orchestrator:
    """
    Центральный оркестратор QwenCode

    Координирует ВСЕ компоненты:
    1. NO-LLM паттерны (Tier 0)
    2. DUCS классификация (Tier 1)
    3. LLM вызовы (Tier 2-4)
    4. Self-correction
    5. Автономное выполнение

    ЦЕЛЬ: Максимум без LLM, LLM только когда необходимо!
    """

    def __init__(self, llm_client=None, use_bilingual_router=True,
                 enable_multi_candidate=True, multi_candidate_model=None):
        """
        Args:
            llm_client: LLM client для Tier 2+
            use_bilingual_router: Использовать BilingualContextRouter (Week 1.5)
                                  True = новый роутер (RU+EN+Context+Tier1.5)
                                  False = старый PatternRouter (обратная совместимость)
            enable_multi_candidate: Enable Multi-Candidate generation (Week 2)
            multi_candidate_model: Model for multi-candidate generation
                                   (default: same as llm_client model)
        """
        # Компоненты
        if use_bilingual_router:
            # Week 1.5: Bilingual Context Router with Tier 1.5
            self.bilingual_router = BilingualContextRouter(enable_tier1_5=True)
            self.pattern_router = None  # Legacy router disabled
        else:
            # Legacy: PatternRouter only
            self.pattern_router = PatternRouter()
            self.bilingual_router = None

        self.hybrid_router = HybridRouter()
        self.ducs = DUCSClassifier()
        self.cot_engine = CoTEngine()
        self.llm_client = llm_client

        # Multi-Candidate Pipeline (Week 2)
        self.multi_candidate_pipeline = None
        if enable_multi_candidate and MULTI_CANDIDATE_AVAILABLE and llm_client:
            self._init_multi_candidate(llm_client, multi_candidate_model)

        # Статистика
        self.stats = {
            "total_requests": 0,
            "tier0_pattern": 0,      # Regex (NO-LLM)
            "tier1_ducs": 0,         # DUCS (NO-LLM)
            "tier1_5_llm": 0,        # NEW: Lightweight LLM classification
            "tier2_simple_llm": 0,
            "tier3_cot": 0,
            "tier4_autonomous": 0,
            "tier4_multi_candidate": 0,  # NEW: Multi-Candidate code generation
            "self_corrections": 0,
            "no_llm_rate": 0.0,
            "light_llm_rate": 0.0    # NEW: Tier 1.5 rate
        }

        # DUCS Templates - шаблоны ответов без LLM
        self.ducs_templates = self._load_ducs_templates()

    def _init_multi_candidate(self, llm_client, model=None):
        """Initialize Multi-Candidate Pipeline."""
        try:
            # Detect model name from client
            model_name = model
            if not model_name:
                if hasattr(llm_client, '_model'):
                    model_name = llm_client._model
                elif hasattr(llm_client, 'model'):
                    model_name = llm_client.model
                else:
                    model_name = "qwen2.5-coder:7b"

            # Get underlying async client if possible
            if hasattr(llm_client, '_async_client'):
                adapter = AsyncLLMAdapter(llm_client._async_client, model=model_name)
            else:
                adapter = AsyncLLMAdapter(llm_client, model=model_name)

            self.multi_candidate_pipeline = MultiCandidatePipeline(
                llm=adapter,
                config=PipelineConfig(
                    n_candidates=3,
                    parallel_generation=True,
                    fail_fast_validation=True,
                ),
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "[Orchestrator] Multi-Candidate init failed: %s", e
            )
            self.multi_candidate_pipeline = None

    def process(self, user_input: str, context: Dict[str, Any] = None) -> ProcessingResult:
        """
        Главная точка входа - обработка запроса

        Логика:
        1. Попробовать NO-LLM (Tier 0 + Tier 1)
        2. Если не получилось - определить сложность
        3. Выбрать подходящий Tier (2/3/4)
        4. Выполнить с self-correction если нужно
        """
        start_time = datetime.now()
        self.stats["total_requests"] += 1

        # ===== TIER 0: Pattern Matching (NO-LLM) =====
        tier0_result = self._try_tier0_pattern(user_input)
        if tier0_result:
            tier0_result.processing_time_ms = self._calc_time(start_time)
            self.stats["tier0_pattern"] += 1
            self._update_no_llm_rate()
            return tier0_result

        # ===== TIER 1: DUCS Classification (NO-LLM) =====
        tier1_result = self._try_tier1_ducs(user_input, context)
        if tier1_result:
            tier1_result.processing_time_ms = self._calc_time(start_time)
            self.stats["tier1_ducs"] += 1
            self._update_no_llm_rate()
            return tier1_result

        # ===== LLM Required - Determine complexity =====
        complexity = self._assess_complexity(user_input)

        if complexity == "simple":
            # TIER 2: Simple LLM
            result = self._process_tier2_simple(user_input, context)
            self.stats["tier2_simple_llm"] += 1
        elif complexity == "moderate":
            # TIER 3: Chain-of-Thought
            result = self._process_tier3_cot(user_input, context)
            self.stats["tier3_cot"] += 1
        else:
            # TIER 4: Autonomous agent
            result = self._process_tier4_autonomous(user_input, context)
            self.stats["tier4_autonomous"] += 1

        result.processing_time_ms = self._calc_time(start_time)
        self._update_no_llm_rate()
        return result

    def _try_tier0_pattern(self, user_input: str) -> Optional[ProcessingResult]:
        """
        Tier 0/1/1.5: Routing через BilingualContextRouter

        UPDATED 2026-02-04 (Week 1.5):
        - Использует BilingualContextRouter если доступен
        - Поддержка Tier 0 (Regex), Tier 1 (NLP), Tier 1.5 (LLM Classification)
        - Fallback на PatternRouter для обратной совместимости
        """
        # Week 1.5: Bilingual Context Router
        if self.bilingual_router:
            route = self.bilingual_router.route(user_input)

            if route.get("tier") == 4:
                # Escalation to DEEP Mode - не обрабатываем здесь
                return None

            tool_name = route.get("tool")
            args = route.get("args", "")
            tier = route.get("tier")
            confidence = route.get("confidence", 1.0)

            if tool_name:
                # Конвертируем args в params для execute_tool()
                params = {"args": args} if args else {}

                # Выполняем инструмент
                tool_result = execute_tool(tool_name, **params)

                # Обновляем статистику по tier
                if tier == 1.5:
                    self.stats["tier1_5_llm"] += 1

                return ProcessingResult(
                    tier=ProcessingTier.TIER0_PATTERN,  # Все NO-LLM/Light-LLM как Tier 0
                    response=self._format_tool_output(tool_name, tool_result),
                    tool_calls=[{
                        "tool": tool_name,
                        "params": params,
                        "result": tool_result,
                        "router_tier": tier  # Сохраняем оригинальный tier
                    }],
                    confidence=confidence
                )

        # Legacy: PatternRouter fallback
        elif self.pattern_router:
            route = self.pattern_router.match(user_input)

            if route:
                tool_name = route.get("tool")
                params = route.get("params", {})

                tool_result = execute_tool(tool_name, **params)

                return ProcessingResult(
                    tier=ProcessingTier.TIER0_PATTERN,
                    response=self._format_tool_output(tool_name, tool_result),
                    tool_calls=[{
                        "tool": tool_name,
                        "params": params,
                        "result": tool_result
                    }],
                    confidence=1.0
                )

        return None

    def _try_tier1_ducs(self, user_input: str, context: Dict = None) -> Optional[ProcessingResult]:
        """
        Tier 1: DUCS классификация + шаблоны (NO-LLM)
        Для DevOps задач с известными паттернами
        """
        classification = self.ducs.classify(user_input)

        if classification.get("confidence", 0) >= 0.85:
            ducs_code = classification.get("ducs_code")

            # Проверяем есть ли шаблон для этого DUCS кода
            template = self.ducs_templates.get(ducs_code)

            if template:
                # Генерируем ответ по шаблону
                response = self._apply_template(template, user_input, context)

                if response:
                    return ProcessingResult(
                        tier=ProcessingTier.TIER1_DUCS,
                        response=response,
                        ducs_code=ducs_code,
                        confidence=classification["confidence"]
                    )

        return None

    def _process_tier2_simple(self, user_input: str, context: Dict = None) -> ProcessingResult:
        """Tier 2: Простой LLM запрос"""
        if not self.llm_client:
            return ProcessingResult(
                tier=ProcessingTier.TIER2_SIMPLE_LLM,
                response="LLM not configured",
                confidence=0.0
            )

        response = self.llm_client(user_input)

        # Self-correction если нужно
        corrections = 0
        if self._needs_correction(response):
            response, corrections = self._self_correct(response, user_input)
            self.stats["self_corrections"] += corrections

        return ProcessingResult(
            tier=ProcessingTier.TIER2_SIMPLE_LLM,
            response=response,
            self_corrections=corrections
        )

    def _process_tier3_cot(self, user_input: str, context: Dict = None) -> ProcessingResult:
        """Tier 3: Chain-of-Thought reasoning"""
        if not self.llm_client:
            return ProcessingResult(
                tier=ProcessingTier.TIER3_COT,
                response="LLM not configured"
            )

        # Создаём CoT промпт
        cot_prompt = self.cot_engine.create_thinking_prompt(user_input, context)

        response = self.llm_client(cot_prompt)
        thinking = self.cot_engine.parse_thinking(response)

        return ProcessingResult(
            tier=ProcessingTier.TIER3_COT,
            response=response,
            thinking=thinking
        )

    def _process_tier4_autonomous(self, user_input: str, context: Dict = None) -> ProcessingResult:
        """Tier 4: Полностью автономный агент с итерациями"""
        if not self.llm_client:
            return ProcessingResult(
                tier=ProcessingTier.TIER4_AUTONOMOUS,
                response="LLM not configured"
            )

        # Crystallize query for enhanced prompt
        crystallizer = get_crystallizer()
        crystallized = crystallizer.crystallize(user_input, context)

        # --- Multi-Candidate path for code generation tasks ---
        if (
            self.multi_candidate_pipeline
            and self._is_code_generation_task(user_input, crystallized)
        ):
            return self._process_multi_candidate(user_input, crystallized, context)

        # --- Standard tool-loop path ---
        # Use optimized prompt with task-specific instructions
        enhanced_prompt = crystallized.optimized_prompt

        # For EDIT tasks, add explicit tool usage reminder
        if crystallized.task_type == TaskType.EDIT:
            enhanced_prompt = f"""IMPORTANT: This is an EDIT task. You MUST use tools!

{enhanced_prompt}

REMEMBER: Use 'read' tool first, then 'edit' tool. Do NOT just generate code!"""

        # Week 2: Working Memory for multi-step context retention
        memory = WorkingMemory(goal=user_input)

        tool_calls = []
        iterations = 0
        max_iterations = 10
        current_prompt = enhanced_prompt  # Use crystallized prompt

        while iterations < max_iterations:
            iterations += 1

            # LLM call
            response = self.llm_client(current_prompt)

            # Parse tool calls
            parsed_tools = self._parse_tool_calls(response)

            if not parsed_tools:
                # No more tools - done
                break

            # Execute tools
            for tool_name, params in parsed_tools:
                result = execute_tool(tool_name, **params)
                tool_calls.append({
                    "tool": tool_name,
                    "params": params,
                    "result": result
                })
                memory.update_from_tool_result(tool_name, params, result)

            # Build continuation with working memory
            current_prompt = self._build_continuation(tool_calls[-len(parsed_tools):], memory=memory)

        return ProcessingResult(
            tier=ProcessingTier.TIER4_AUTONOMOUS,
            response=response,
            tool_calls=tool_calls,
            iterations=iterations
        )

    def _is_code_generation_task(self, user_input: str, crystallized=None) -> bool:
        """
        Detect if task is a pure code generation request
        (vs tool-based file editing or information retrieval).

        Multi-Candidate is best for:
        - "Write a function..."
        - "Create a class..."
        - "Implement..."
        - "Generate code for..."

        NOT for:
        - "Read file X" (tool task)
        - "Edit line 5 in foo.py" (tool task)
        - "Explain this code" (not code generation)
        """
        if crystallized and crystallized.task_type == TaskType.EDIT:
            return False  # EDIT tasks need tools, not multi-candidate

        input_lower = user_input.lower()

        code_gen_indicators = [
            "write a function", "write a class", "write code",
            "create a function", "create a class", "create a script",
            "implement", "generate code", "generate a",
            "write python", "write dockerfile", "write yaml",
            "напиши функцию", "напиши код", "создай функцию",
            "создай класс", "реализуй", "сгенерируй",
        ]

        # Must match at least one indicator
        if not any(ind in input_lower for ind in code_gen_indicators):
            return False

        # Must NOT reference specific files (that's an edit/read task)
        file_indicators = [
            "file ", "файл ", ".py ", ".yaml ", ".json ",
            "edit ", "modify ", "change ", "fix in ",
        ]
        if any(ind in input_lower for ind in file_indicators):
            return False

        return True

    def _process_multi_candidate(
        self, user_input: str, crystallized, context: Dict = None
    ) -> ProcessingResult:
        """
        Multi-Candidate code generation path.

        Generates N code variants, validates each, selects the best.
        """
        # Build DUCS context if available
        classification = self.ducs.classify(user_input)
        swecas_code = None
        if classification.get("confidence", 0) >= 0.5:
            ducs_code_str = classification.get("ducs_code", "")
            try:
                swecas_code = int(ducs_code_str.split(".")[0]) if ducs_code_str else None
            except (ValueError, IndexError):
                pass

        try:
            result = self.multi_candidate_pipeline.run_sync(
                task_id=f"tier4_{self.stats['total_requests']}",
                query=crystallized.optimized_prompt,
                swecas_code=swecas_code,
            )

            self.stats["tier4_multi_candidate"] += 1

            # Format response
            summary = result.summary()
            response_parts = [result.code]

            if result.best and not result.all_passed:
                errors = []
                for vs in result.best.validation_scores:
                    if not vs.passed:
                        errors.extend(vs.errors[:2])
                if errors:
                    response_parts.append(
                        "\n\n⚠️ Validation warnings:\n"
                        + "\n".join(f"  - {e}" for e in errors[:5])
                    )

            return ProcessingResult(
                tier=ProcessingTier.TIER4_AUTONOMOUS,
                response="\n".join(response_parts),
                tool_calls=[{
                    "tool": "multi_candidate_pipeline",
                    "params": {"n_candidates": summary["candidates_generated"]},
                    "result": summary,
                }],
                confidence=result.score,
                ducs_code=str(swecas_code) if swecas_code else None,
            )

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                "[Orchestrator] Multi-Candidate failed, falling back: %s", e
            )
            # Fallback to standard tool-loop
            return self._process_tier4_tool_loop(user_input, crystallized, context)

    def _process_tier4_tool_loop(
        self, user_input: str, crystallized, context: Dict = None
    ) -> ProcessingResult:
        """Standard Tier 4 tool-loop path (fallback from multi-candidate)."""
        enhanced_prompt = crystallized.optimized_prompt

        if crystallized.task_type == TaskType.EDIT:
            enhanced_prompt = f"""IMPORTANT: This is an EDIT task. You MUST use tools!

{enhanced_prompt}

REMEMBER: Use 'read' tool first, then 'edit' tool. Do NOT just generate code!"""

        # Week 2: Working Memory
        memory = WorkingMemory(goal=user_input)

        tool_calls = []
        iterations = 0
        max_iterations = 10
        current_prompt = enhanced_prompt
        response = ""

        while iterations < max_iterations:
            iterations += 1
            response = self.llm_client(current_prompt)
            parsed_tools = self._parse_tool_calls(response)
            if not parsed_tools:
                break
            for tool_name, params in parsed_tools:
                result = execute_tool(tool_name, **params)
                tool_calls.append({
                    "tool": tool_name, "params": params, "result": result
                })
                memory.update_from_tool_result(tool_name, params, result)
            current_prompt = self._build_continuation(tool_calls[-len(parsed_tools):], memory=memory)

        return ProcessingResult(
            tier=ProcessingTier.TIER4_AUTONOMOUS,
            response=response,
            tool_calls=tool_calls,
            iterations=iterations,
        )

    def _assess_complexity(self, user_input: str) -> str:
        """Оценка сложности задачи"""
        input_lower = user_input.lower()

        # Complex indicators
        complex_indicators = [
            "refactor", "architect", "design", "migrate",
            "optimize", "analyze", "debug complex",
            "create system", "implement feature", "multi-step"
        ]

        # Moderate indicators
        moderate_indicators = [
            "create", "implement", "fix bug", "explain",
            "write test", "add feature", "modify"
        ]

        if any(ind in input_lower for ind in complex_indicators):
            return "complex"
        elif any(ind in input_lower for ind in moderate_indicators):
            return "moderate"
        else:
            return "simple"

    def _needs_correction(self, response: str) -> bool:
        """Проверка нужна ли коррекция"""
        error_indicators = [
            "error", "failed", "cannot", "invalid",
            "syntax error", "undefined", "not found"
        ]
        return any(ind in response.lower() for ind in error_indicators)

    def _self_correct(self, response: str, original_input: str) -> Tuple[str, int]:
        """Self-correction механизм"""
        corrections = 0
        max_corrections = 3

        while self._needs_correction(response) and corrections < max_corrections:
            corrections += 1
            correction_prompt = f"""
Previous response had errors. Please fix:

Original request: {original_input}
Previous response: {response}

Provide corrected response:
"""
            if self.llm_client:
                response = self.llm_client(correction_prompt)

        return response, corrections

    def _parse_tool_calls(self, response: str) -> List[Tuple[str, Dict]]:
        """Parse tool calls from response"""
        tool_calls = []
        pattern = r'\[TOOL:\s*(\w+)\((.*?)\)\]'

        for match in re.finditer(pattern, response, re.DOTALL):
            tool_name = match.group(1)
            params_str = match.group(2)
            params = self._parse_params(params_str)

            if tool_name in EXTENDED_TOOL_REGISTRY:
                tool_calls.append((tool_name, params))

        return tool_calls

    def _parse_params(self, params_str: str) -> Dict[str, Any]:
        """Parse parameters string"""
        params = {}
        pattern = r'(\w+)\s*=\s*["\']([^"\']*)["\']|(\w+)\s*=\s*([^,\)]+)'

        for match in re.finditer(pattern, params_str):
            if match.group(1):
                params[match.group(1)] = match.group(2)
            elif match.group(3):
                value = match.group(4).strip()
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                elif value.isdigit():
                    value = int(value)
                params[match.group(3)] = value

        return params

    def _build_continuation(self, recent_tools: List[Dict],
                             memory: 'WorkingMemory' = None) -> str:
        """Build continuation prompt with optional working memory."""
        lines = []

        # Week 2: Inject working memory context first
        if memory:
            lines.append(memory.compact())
            lines.append("")

        lines.append("Tool results:")
        for tc in recent_tools:
            lines.append(f"\n[{tc['tool']}]: {json.dumps(tc['result'], default=str)[:1000]}")
        lines.append("\nContinue with next action or provide final answer.")
        return "\n".join(lines)

    def _format_tool_output(self, tool: str, result: Dict) -> str:
        """Format tool output for display"""
        if not result.get("success", True):
            return f"Error: {result.get('error', 'Unknown')}"

        if tool == "ls":
            items = result.get("items", [])
            lines = []
            for item in items[:50]:
                prefix = "[D]" if item.get("type") == "dir" else "[F]"
                lines.append(f"{prefix} {item['name']}")
            return "\n".join(lines)

        elif tool == "read":
            return result.get("content", "")

        elif tool == "grep":
            matches = result.get("matches", [])
            return "\n".join([f"{m['file']}:{m['line_number']}: {m['line']}" for m in matches[:30]])

        elif tool == "bash":
            return result.get("stdout", "") + result.get("stderr", "")

        return json.dumps(result, indent=2, default=str)

    def _apply_template(self, template: Dict, user_input: str, context: Dict) -> Optional[str]:
        """Apply DUCS template"""
        # Simple template system
        if "response" in template:
            return template["response"]
        if "tool" in template:
            params = template.get("params", {})
            result = execute_tool(template["tool"], **params)
            return self._format_tool_output(template["tool"], result)
        return None

    def _load_ducs_templates(self) -> Dict[str, Dict]:
        """Load DUCS response templates"""
        return {
            # Dockerfile templates
            "100.01": {
                "patterns": ["dockerfile", "docker build"],
                "tool": None,
                "response": None  # Use LLM for generation
            },
            # Git templates
            "900.01": {
                "patterns": ["git status"],
                "tool": "git",
                "params": {"command": "status"}
            }
        }

    def _calc_time(self, start: datetime) -> int:
        """Calculate processing time in ms"""
        return int((datetime.now() - start).total_seconds() * 1000)

    def _update_no_llm_rate(self):
        """Update NO-LLM and Light LLM rate statistics

        UPDATED 2026-02-04 (Week 1.5):
        - NO-LLM: Tier 0 + Tier 1 (pure pattern matching, no AI)
        - Light LLM: Tier 1.5 (lightweight LLM classification, fast)
        - Heavy LLM: Tier 2-4 (full LLM processing, slow)
        """
        total = self.stats["total_requests"]
        if total > 0:
            # NO-LLM: Tier 0 (pattern) + Tier 1 (DUCS)
            no_llm = self.stats["tier0_pattern"] + self.stats["tier1_ducs"]
            self.stats["no_llm_rate"] = round(no_llm / total * 100, 1)

            # Light LLM: Tier 1.5
            self.stats["light_llm_rate"] = round(self.stats["tier1_5_llm"] / total * 100, 1)

    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics

        UPDATED 2026-02-04 (Week 1.5): BilingualContextRouter stats
        UPDATED 2026-02-06 (Week 2): Multi-Candidate stats
        """
        stats_dict = {
            **self.stats,
            "ducs_stats": self.ducs.get_stats(),
            "multi_candidate_available": self.multi_candidate_pipeline is not None,
        }

        # Add BilingualContextRouter stats if enabled
        if self.bilingual_router:
            stats_dict["bilingual_router_stats"] = self.bilingual_router.get_stats()

        return stats_dict
