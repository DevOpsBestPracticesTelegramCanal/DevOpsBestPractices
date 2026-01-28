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
from .router import PatternRouter, HybridRouter, RouteResult
from .cot_engine import CoTEngine
from .tools_extended import execute_tool, EXTENDED_TOOL_REGISTRY


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

    def __init__(self, llm_client=None):
        # Компоненты
        self.pattern_router = PatternRouter()
        self.hybrid_router = HybridRouter()
        self.ducs = DUCSClassifier()
        self.cot_engine = CoTEngine()
        self.llm_client = llm_client

        # Статистика
        self.stats = {
            "total_requests": 0,
            "tier0_pattern": 0,
            "tier1_ducs": 0,
            "tier2_simple_llm": 0,
            "tier3_cot": 0,
            "tier4_autonomous": 0,
            "self_corrections": 0,
            "no_llm_rate": 0.0
        }

        # DUCS Templates - шаблоны ответов без LLM
        self.ducs_templates = self._load_ducs_templates()

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
        Tier 0: Прямое сопоставление паттернов (NO-LLM)
        Для простых команд: ls, read, git status и т.д.
        """
        route = self.pattern_router.route(user_input)

        if route.confidence >= 0.85 and route.tool:
            # Выполняем инструмент напрямую
            tool_result = execute_tool(route.tool, **route.params)

            return ProcessingResult(
                tier=ProcessingTier.TIER0_PATTERN,
                response=self._format_tool_output(route.tool, tool_result),
                tool_calls=[{
                    "tool": route.tool,
                    "params": route.params,
                    "result": tool_result
                }],
                confidence=route.confidence
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

        tool_calls = []
        iterations = 0
        max_iterations = 10
        current_prompt = user_input

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

            # Build continuation
            current_prompt = self._build_continuation(tool_calls[-len(parsed_tools):])

        return ProcessingResult(
            tier=ProcessingTier.TIER4_AUTONOMOUS,
            response=response,
            tool_calls=tool_calls,
            iterations=iterations
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

    def _build_continuation(self, recent_tools: List[Dict]) -> str:
        """Build continuation prompt"""
        lines = ["Tool results:"]
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
        """Update NO-LLM rate statistic"""
        total = self.stats["total_requests"]
        if total > 0:
            no_llm = self.stats["tier0_pattern"] + self.stats["tier1_ducs"]
            self.stats["no_llm_rate"] = round(no_llm / total * 100, 1)

    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics"""
        return {
            **self.stats,
            "ducs_stats": self.ducs.get_stats()
        }
