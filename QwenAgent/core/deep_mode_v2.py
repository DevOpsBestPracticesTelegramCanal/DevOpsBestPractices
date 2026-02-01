# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
DEEP MODE V2 - Fast-Thinking (3 Steps instead of 6)
═══════════════════════════════════════════════════════════════════════════════

Оптимизация #1: Сжатие графа рассуждений
- Было: 6 шагов (~600 сек)
- Стало: 3 шага (~200 сек)

Steps:
1. ANALYZE: Understanding + Challenges (объединено)
2. PLAN: Approaches + Choose (объединено)
3. GENERATE: Solution

Оптимизация #2: Hybrid Model Mix
- Steps 1-2: Fast model (configurable, default 3B)
- Step 3: Heavy model (configurable, default 7B)

Models are configurable via config.py or environment variables.
Supports any Ollama model or model synthesis endpoint.

═══════════════════════════════════════════════════════════════════════════════
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
import time
import requests

# Import configuration
try:
    from .config import get_config, QwenCodeConfig, ModelRole
except ImportError:
    from config import get_config, QwenCodeConfig, ModelRole


class ModelTier(Enum):
    """Model tiers for hybrid approach (legacy, use config instead)"""
    FAST = "fast"    # Fast model for analysis
    HEAVY = "heavy"  # Heavy model for code generation


@dataclass
class DeepModeResult:
    """Результат Deep Mode V2"""
    steps: Dict[str, str] = field(default_factory=dict)
    final_answer: str = ""
    total_duration_ms: float = 0.0
    step_durations: Dict[str, float] = field(default_factory=dict)
    models_used: Dict[str, str] = field(default_factory=dict)
    success: bool = False

    # Dict-like interface for compatibility
    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access: result['solution']"""
        mapping = {
            'solution': self.final_answer,
            'code': self.final_answer,
            'answer': self.final_answer,
            'steps': self.steps,
            'success': self.success,
            'duration': self.total_duration_ms,
            'has_code': self.has_code
        }
        if key in mapping:
            return mapping[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like get method"""
        try:
            return self[key]
        except KeyError:
            return default

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'steps': self.steps,
            'solution': self.final_answer,
            'final_answer': self.final_answer,
            'total_duration_ms': self.total_duration_ms,
            'step_durations': self.step_durations,
            'models_used': self.models_used,
            'success': self.success,
            'has_code': self.has_code
        }

    @property
    def has_code(self) -> bool:
        """Check if result contains code"""
        if not self.final_answer:
            return False
        code_indicators = [
            'def ', 'class ', 'import ', 'from ', 'return ',
            'if ', 'for ', 'while ', 'try:', 'except:',
            'edit_lines(', '= ', '.append(', '.add(',
            'self.', 'async ', 'await ', 'raise ', 'with '
        ]
        return any(ind in self.final_answer for ind in code_indicators)


def extract_code_from_solution(solution: str) -> str:
    """
    Extract only code from solution, removing explanations.

    Handles:
    - ```python blocks
    - edit_lines() calls
    - Raw code
    """
    import re

    # Try to extract code blocks
    code_blocks = re.findall(r'```(?:python|py)?\s*\n(.*?)```', solution, re.DOTALL)
    if code_blocks:
        return '\n'.join(code_blocks).strip()

    # Try to extract edit_lines calls
    edit_calls = re.findall(r"edit_lines\s*\([^)]+\)", solution)
    if edit_calls:
        return '\n'.join(edit_calls)

    # Return as-is but truncated
    lines = solution.strip().split('\n')
    code_lines = [l for l in lines if not l.strip().startswith('#') or 'def ' in l or 'class ' in l]
    return '\n'.join(code_lines[:30])  # Max 30 lines


class DeepModeV2:
    """
    Fast-Thinking Deep Mode с 3 шагами вместо 6.

    Использует гибридную модель:
    - 3B для анализа (Steps 1-2)
    - 7B для генерации кода (Step 3)

    Usage:
        deep = DeepModeV2()
        result = deep.execute("How to implement retry logic?")
        print(result.final_answer)
    """

    # Промпты для 3 шагов (сжатые)
    STEP_PROMPTS = {
        "analyze": """[STEP 1/3: ANALYZE]
Task: {query}
Context: {context}

Combine understanding and challenges analysis:

1. UNDERSTANDING:
   - What is the task asking for?
   - Current state (S0) vs Desired state (S1)

2. CHALLENGES:
   - Key difficulties (list 2-3)
   - Edge cases to handle
   - Dependencies

Output your analysis concisely (max 200 words):""",

        "plan": """[STEP 2/3: PLAN]
Task: {query}
Analysis: {prev_output}

Generate approaches and choose the best:

1. APPROACHES (list 2-3 options):
   - Option A: [name] - pros/cons
   - Option B: [name] - pros/cons

2. DECISION:
   - Best approach: [chosen option]
   - Justification: [why this one]

Output your plan concisely (max 150 words):""",

        "generate": """[STEP 3/3: GENERATE]
Task: {query}
Plan: {prev_output}

OUTPUT ONLY THE CODE FIX. No explanations.

STRUCTURED FORMAT (use one of these):

Option 1 - Line Edit:
```python
edit_lines('file.py', START_LINE, END_LINE, '''
NEW_CODE_HERE
''')
```

Option 2 - Direct Code:
```python
def fixed_function():
    # Your fix here
    pass
```

RULES:
- Output ONLY the hunk/diff, NOT the entire file
- Use line numbers (get from grep -n first)
- Max 20 lines of code
- No explanations before or after

Output:"""
    }

    def __init__(
        self,
        fast_model: Optional[str] = None,
        heavy_model: Optional[str] = None,
        timeout: Optional[int] = None,
        step_timeout: Optional[int] = None,
        config: Optional[QwenCodeConfig] = None
    ):
        """
        Initialize Deep Mode V2.

        Models are configurable via:
        1. Direct parameters (fast_model, heavy_model)
        2. Config object
        3. Environment variables (QWEN_FAST_MODEL, QWEN_HEAVY_MODEL)

        Supports model synthesis via config.models.synthesis_url
        """
        # Load configuration
        self.config = config or get_config()

        # Model selection (parameters override config)
        self.fast_model = fast_model or self.config.models.fast_model
        self.heavy_model = heavy_model or self.config.models.heavy_model

        # Timeouts from config or parameters
        self.timeout = timeout or self.config.timeouts.ollama_timeout
        self.step_timeout = step_timeout or self.config.timeouts.step_timeout

        # Token limits from config
        self.token_limits = {
            "analyze": self.config.tokens.analyze,
            "plan": self.config.tokens.plan,
            "generate": self.config.tokens.generate
        }

        # Use synthesis endpoint if configured
        self.use_synthesis = self.config.models.use_synthesis
        self.synthesis_url = self.config.models.synthesis_url

        # Statistics
        self.stats = {
            "total_executions": 0,
            "avg_duration_ms": 0.0,
            "by_step": {},
            "timeouts": 0
        }

    def _call_model(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 500,
        step_name: str = ""
    ) -> tuple[str, float]:
        """
        Call model API with step timeout.

        Supports:
        - Ollama API (default)
        - Synthesis endpoint (if configured)

        Returns:
            (response, duration_ms)
        """
        start = time.time()
        effective_timeout = min(self.step_timeout, self.timeout)

        # Use synthesis endpoint if configured
        if self.use_synthesis and self.synthesis_url:
            return self._call_synthesis(prompt, model, max_tokens, effective_timeout)

        # Otherwise use Ollama
        return self._call_ollama_direct(prompt, model, max_tokens, effective_timeout)

    def _call_synthesis(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        timeout: int
    ) -> tuple[str, float]:
        """Call synthesis endpoint for model fusion"""
        start = time.time()
        try:
            resp = requests.post(
                self.synthesis_url,
                json={
                    "prompt": prompt,
                    "model_hint": model,  # Hint for synthesis
                    "max_tokens": max_tokens,
                    "temperature": 0.3
                },
                timeout=timeout
            )
            duration = (time.time() - start) * 1000
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", data.get("text", "")), duration
            return f"Synthesis Error: {resp.status_code}", duration
        except Exception as e:
            duration = (time.time() - start) * 1000
            return f"Synthesis Error: {e}", duration

    def _call_ollama_direct(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        timeout: int
    ) -> tuple[str, float]:
        """Call Ollama API directly"""
        start = time.time()
        ollama_url = f"{self.config.models.ollama_url}/api/generate"

        try:
            resp = requests.post(
                ollama_url,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": 0.3,
                        "stop": ["\n\n\n", "```\n\n"]  # Early stop
                    }
                },
                timeout=timeout
            )

            duration = (time.time() - start) * 1000

            if resp.status_code == 200:
                return resp.json().get("response", ""), duration
            return f"Ollama Error: {resp.status_code}", duration

        except requests.exceptions.Timeout:
            duration = (time.time() - start) * 1000
            self.stats["timeouts"] += 1
            return f"[TIMEOUT after {timeout}s]", duration

        except Exception as e:
            duration = (time.time() - start) * 1000
            return f"Ollama Error: {e}", duration

    # Legacy method name for compatibility
    def _call_ollama(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 500
    ) -> tuple[str, float]:
        """Legacy method - calls _call_model"""
        return self._call_model(prompt, model, max_tokens)

    def execute(
        self,
        query: str,
        context: str = "",
        verbose: bool = False
    ) -> DeepModeResult:
        """
        Execute 3-step Deep Mode.

        Args:
            query: The task/question
            context: Additional context (e.g., from search)
            verbose: Print progress

        Returns:
            DeepModeResult with steps and final answer
        """
        result = DeepModeResult()
        total_start = time.time()

        if verbose:
            print(f"  [DEEP MODE V2] 3-step fast-thinking")
            print(f"  Query: {query[:50]}...")

        prev_output = ""

        # Get model display names (short form)
        fast_display = self.fast_model.split(":")[-1] if ":" in self.fast_model else self.fast_model
        heavy_display = self.heavy_model.split(":")[-1] if ":" in self.heavy_model else self.heavy_model
        if self.use_synthesis:
            fast_display = f"synthesis/{fast_display}"
            heavy_display = f"synthesis/{heavy_display}"

        # Step 1: ANALYZE (fast model)
        if verbose:
            print(f"    Step 1/3: ANALYZE ({fast_display})...")

        prompt = self.STEP_PROMPTS["analyze"].format(
            query=query,
            context=context or "No additional context"
        )
        response, duration = self._call_model(
            prompt, self.fast_model,
            max_tokens=self.token_limits["analyze"],
            step_name="analyze"
        )

        result.steps["analyze"] = response
        result.step_durations["analyze"] = duration
        result.models_used["analyze"] = self.fast_model
        prev_output = response

        if verbose:
            print(f"      Done: {duration:.0f}ms ({len(response)} chars)")

        # Step 2: PLAN (fast model)
        if verbose:
            print(f"    Step 2/3: PLAN ({fast_display})...")

        prompt = self.STEP_PROMPTS["plan"].format(
            query=query,
            prev_output=prev_output[:500]  # Limit context
        )
        response, duration = self._call_model(
            prompt, self.fast_model,
            max_tokens=self.token_limits["plan"],
            step_name="plan"
        )

        result.steps["plan"] = response
        result.step_durations["plan"] = duration
        result.models_used["plan"] = self.fast_model
        prev_output = response

        if verbose:
            print(f"      Done: {duration:.0f}ms ({len(response)} chars)")

        # Step 3: GENERATE (heavy model for code)
        if verbose:
            print(f"    Step 3/3: GENERATE ({heavy_display})...")

        prompt = self.STEP_PROMPTS["generate"].format(
            query=query,
            prev_output=prev_output[:500]
        )
        response, duration = self._call_model(
            prompt, self.heavy_model,
            max_tokens=self.token_limits["generate"],
            step_name="generate"
        )

        result.steps["generate"] = response
        result.step_durations["generate"] = duration
        result.models_used["generate"] = self.heavy_model

        # Extract only code from solution (remove explanations)
        result.final_answer = extract_code_from_solution(response)

        if verbose:
            print(f"      Done: {duration:.0f}ms")
            if len(response) != len(result.final_answer):
                print(f"      Extracted: {len(response)} -> {len(result.final_answer)} chars")

        # Finalize
        result.total_duration_ms = (time.time() - total_start) * 1000
        result.success = len(result.final_answer) > 20  # Lowered threshold for extracted code

        # Update stats
        self.stats["total_executions"] += 1
        n = self.stats["total_executions"]
        self.stats["avg_duration_ms"] = (
            (self.stats["avg_duration_ms"] * (n-1) + result.total_duration_ms) / n
        )

        if verbose:
            print(f"  [DEEP MODE V2] Total: {result.total_duration_ms:.0f}ms")

        return result

    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics"""
        return self.stats


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMING VERSION (for even faster perceived response)
# ═══════════════════════════════════════════════════════════════════════════════

class DeepModeV2Streaming:
    """
    Streaming version of Deep Mode V2.

    Starts parsing tool_calls before full generation completes.
    Uses generator pattern for progressive output.

    Models are configurable via config.py
    """

    def __init__(
        self,
        fast_model: Optional[str] = None,
        heavy_model: Optional[str] = None,
        config: Optional[QwenCodeConfig] = None
    ):
        self.config = config or get_config()
        self.fast_model = fast_model or self.config.models.fast_model
        self.heavy_model = heavy_model or self.config.models.heavy_model
        self.ollama_url = f"{self.config.models.ollama_url}/api/generate"

    def execute_streaming(
        self,
        query: str,
        context: str = "",
        on_token: Optional[Callable[[str], None]] = None
    ):
        """
        Execute with streaming output.

        Args:
            query: The task
            context: Additional context
            on_token: Callback for each token (for UI updates)

        Yields:
            Tokens as they are generated
        """
        # Step 1 & 2 with 3B (fast, non-streaming for simplicity)
        deep = DeepModeV2(self.fast_model, self.heavy_model)

        # Quick analysis
        prompt1 = DeepModeV2.STEP_PROMPTS["analyze"].format(
            query=query, context=context or "None"
        )
        analysis, _ = deep._call_ollama(prompt1, self.fast_model, 400)

        prompt2 = DeepModeV2.STEP_PROMPTS["plan"].format(
            query=query, prev_output=analysis[:500]
        )
        plan, _ = deep._call_ollama(prompt2, self.fast_model, 300)

        # Step 3: Stream the code generation
        prompt3 = DeepModeV2.STEP_PROMPTS["generate"].format(
            query=query, prev_output=plan[:500]
        )

        try:
            resp = requests.post(
                self.ollama_url,
                json={
                    "model": self.heavy_model,
                    "prompt": prompt3,
                    "stream": True,
                    "options": {"num_predict": self.config.tokens.generate}
                },
                stream=True,
                timeout=self.config.timeouts.ollama_timeout
            )

            for line in resp.iter_lines():
                if line:
                    import json
                    data = json.loads(line)
                    token = data.get("response", "")
                    if token:
                        if on_token:
                            on_token(token)
                        yield token

        except Exception as e:
            yield f"Error: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

_default_deep_mode: Optional[DeepModeV2] = None


def get_deep_mode_v2(config: Optional[QwenCodeConfig] = None) -> DeepModeV2:
    """
    Get or create default Deep Mode V2 instance.

    Uses global configuration from config.py
    Can be overridden by passing a custom config.
    """
    global _default_deep_mode
    if _default_deep_mode is None or config is not None:
        _default_deep_mode = DeepModeV2(config=config)
    return _default_deep_mode


def reset_deep_mode():
    """Reset default instance (useful when config changes)"""
    global _default_deep_mode
    _default_deep_mode = None


def fast_think(query: str, context: str = "") -> str:
    """
    Quick function for fast-thinking deep mode.

    Args:
        query: The task/question
        context: Additional context

    Returns:
        The solution/answer
    """
    deep = get_deep_mode_v2()
    result = deep.execute(query, context, verbose=False)
    return result.final_answer


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import io
    from config import print_config

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  DEEP MODE V2 TEST (3 Steps)")
    print("=" * 60)

    # Show configuration
    print("\n[CONFIG]")
    print_config()

    deep = DeepModeV2()

    # Show actual settings
    print(f"\n[INSTANCE SETTINGS]")
    print(f"  Fast model: {deep.fast_model}")
    print(f"  Heavy model: {deep.heavy_model}")
    print(f"  Step timeout: {deep.step_timeout}s")
    print(f"  Token limits: {deep.token_limits}")
    print(f"  Use synthesis: {deep.use_synthesis}")

    query = "Write a Python function to validate email addresses"
    print(f"\nQuery: {query}")
    print("-" * 60)

    result = deep.execute(query, verbose=True)

    print("\n" + "=" * 60)
    print("  RESULT")
    print("=" * 60)

    print(f"\nTotal Duration: {result.total_duration_ms:.0f}ms ({result.total_duration_ms/1000:.1f}s)")
    print(f"Success: {result.success}")

    print(f"\nStep Durations:")
    for step, duration in result.step_durations.items():
        model = result.models_used.get(step, "unknown")
        print(f"  {step}: {duration:.0f}ms ({model})")

    print(f"\nFinal Answer:")
    print("-" * 60)
    print(result.final_answer[:800])

    # Compare with expected 6-step time
    expected_6step = 600000  # 10 minutes
    speedup = expected_6step / result.total_duration_ms if result.total_duration_ms > 0 else 0
    print(f"\n[INFO] Speedup vs 6-step: {speedup:.1f}x faster")
