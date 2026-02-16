"""
Multi-Candidate Code Generation.

Generates N code variants with different temperatures/seeds,
then lets validators score each one so the selector can pick the best.

Key insight from Qwen benchmarks:
    pass@1 ≈ 65%  →  pass@3 ≈ 80%  (+15% improvement)

Usage:
    generator = MultiCandidateGenerator(llm_client)
    pool = await generator.generate(task, n=3)
    # ... validate each candidate ...
    best = pool.select_best()
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple

from .candidate import Candidate, CandidatePool
from .generator_roles import (
    GeneratorRole,
    GENERATOR_ROLES,
    get_role_for_candidate,
    build_role_system_prompt,
)
from .trinity_model_manager import TrinityModelManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Protocol — any client that implements .generate() works
# ---------------------------------------------------------------------------

class LLMProtocol(Protocol):
    """Minimal interface the generator needs from an LLM client."""

    model_name: str

    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float,
        seed: int,
        model: Optional[str] = None,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class MultiCandidateConfig:
    """Tuneable knobs for generation."""

    # Temperatures for each variant (len = default n_candidates)
    temperatures: tuple[float, ...] = (0.2, 0.5, 0.8)

    base_seed: int = 42

    # Timeout per single candidate (seconds)
    per_candidate_timeout: float = 30.0

    # Hard wall for the whole batch
    total_timeout: float = 120.0

    # Max tokens per candidate (0 = unlimited, model decides)
    max_tokens: int = 0


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class MultiCandidateGenerator:
    """
    Generates N code variants for a single task.

    Strategy:
        1.  Build the prompt once from the task.
        2.  Fire N parallel LLM calls with different (temperature, seed).
        3.  Return a CandidatePool (un-validated).
    """

    def __init__(
        self,
        llm: LLMProtocol,
        config: Optional[MultiCandidateConfig] = None,
        model_manager: Optional[TrinityModelManager] = None,
    ):
        self.llm = llm
        self.cfg = config or MultiCandidateConfig()
        self.model_manager = model_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        task,  # CodeTask or anything with .task_id, .query, etc.
        n: Optional[int] = None,
        parallel: bool = True,
        temperatures: Optional[Tuple[float, ...]] = None,
    ) -> CandidatePool:
        """Generate *n* candidates and return an un-validated pool.

        Args:
            temperatures: Override default temperatures for this request.
                          None = use config defaults.
        """
        self._override_temps = temperatures
        n = n or len(temperatures or self.cfg.temperatures)
        pool = CandidatePool(task_id=getattr(task, "task_id", "unknown"))

        logger.info("[MultiCandidate] generating %d candidates for %s", n, pool.task_id)

        try:
            if parallel:
                candidates = await self._parallel(task, n)
            else:
                candidates = await self._sequential(task, n)

            for c in candidates:
                pool.add(c)

            if candidates:
                avg_t = sum(c.generation_time for c in candidates) / len(candidates)
                logger.info(
                    "[MultiCandidate] %d candidates generated (avg %.2fs)",
                    len(candidates),
                    avg_t,
                )

            return pool
        finally:
            self._override_temps = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _parallel(self, task, n: int) -> List[Candidate]:
        coros = [self._one(task, i, n) for i in range(n)]
        try:
            raw = await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=self.cfg.total_timeout,
            )
            # Filter out exceptions (return_exceptions=True puts them in list)
            candidates = []
            for r in raw:
                if isinstance(r, Candidate):
                    candidates.append(r)
                elif isinstance(r, BaseException):
                    logger.error("[MultiCandidate] candidate failed: %s", r)
            return candidates
        except asyncio.TimeoutError:
            logger.error("[MultiCandidate] total timeout (%.0fs)", self.cfg.total_timeout)
            # return whatever finished
            return [
                r for r in coros if isinstance(r, Candidate)
            ]

    async def _sequential(self, task, n: int) -> List[Candidate]:
        results: List[Candidate] = []
        for i in range(n):
            try:
                results.append(await self._one(task, i, n))
            except Exception as exc:
                logger.error("[MultiCandidate] candidate %d failed: %s", i, exc)
        return results

    # Week 29: Mapping from Trinity roles to GeneratorRole prompts.
    # Ensures each model architecture gets a system prompt aligned with its
    # strength: Architect→correctness, Developer→readability, Reviewer→security.
    _TRINITY_ROLE_MAP = {
        "architect": "correctness",   # deepseek-r1: CoT reasoning → careful validation
        "developer": "readability",   # qwen2.5-coder: code gen → clean, typed code
        "reviewer": "security",       # deepseek-coder: review → security-focused
    }

    async def _one(self, task, index: int, total: int) -> Candidate:
        temps = self._override_temps or self.cfg.temperatures
        temp = temps[index % len(temps)]
        seed = self.cfg.base_seed + index

        # Week 29: Trinity model selection — each candidate can use a different model
        model_override = None
        trinity_role_name = None
        if self.model_manager and self.model_manager.enabled:
            model_override = self.model_manager.select_for_candidate(index, task)
            trinity_role = self.model_manager.get_role_for_index(index)
            trinity_role_name = trinity_role.value if trinity_role else None

        # Week 21 + Week 29: Role-specialized system prompts
        # When Trinity is active, override GeneratorRole based on Trinity role
        # to ensure prompt matches model strength.
        role = None
        if trinity_role_name and trinity_role_name in self._TRINITY_ROLE_MAP:
            gen_role_name = self._TRINITY_ROLE_MAP[trinity_role_name]
            role = GENERATOR_ROLES.get(gen_role_name)
            logger.debug(
                "[MultiCandidate] #%d: Trinity %s → GeneratorRole %s (model=%s)",
                index, trinity_role_name, gen_role_name, model_override,
            )
        else:
            role = self._get_role(task, index, total)

        prompt = self._prompt(task)
        system = self._system_prompt(task)
        if role:
            system = build_role_system_prompt(role, system)

        # Week 27: Validate LLM adapter before calling
        if not hasattr(self.llm, 'generate'):
            raise TypeError(
                f"self.llm is {type(self.llm).__name__} (not an LLMProtocol). "
                f"Expected AsyncLLMAdapter or similar with .generate() method."
            )

        t0 = time.perf_counter()

        code = await asyncio.wait_for(
            self.llm.generate(
                prompt=prompt,
                system=system,
                temperature=temp,
                seed=seed,
                model=model_override,
            ),
            timeout=self.cfg.per_candidate_timeout,
        )

        elapsed = time.perf_counter() - t0

        # Extract code from markdown fences if model wrapped it
        code = self._extract_code(code)

        candidate = Candidate(
            id=index,
            task_id=getattr(task, "task_id", "unknown"),
            code=code,
            temperature=temp,
            seed=seed,
            model=model_override or self.llm.model_name,
            generation_time=elapsed,
        )
        # Week 21: Store role name for traceability
        if role:
            candidate.role = role.name

        logger.debug(
            "[MultiCandidate] #%d done (role=%s, temp=%.1f, %d chars, %.2fs)",
            index,
            role.name if role else "default",
            temp,
            len(code),
            elapsed,
        )

        return candidate

    # ------------------------------------------------------------------
    # Role selection (Week 21)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_role(task, index: int, total: int) -> Optional[GeneratorRole]:
        """Pick a role for this candidate based on task metadata."""
        task_type = getattr(task, "type", None)
        type_val = task_type.value if task_type else None
        # Use complexity from task if available
        complexity = getattr(task, "complexity", None)
        if complexity and hasattr(complexity, "name"):
            complexity = complexity.name
        try:
            return get_role_for_candidate(
                index=index,
                n=total,
                complexity=complexity,
                task_type=type_val,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt(task) -> str:
        parts = [getattr(task, "query", str(task))]

        files = getattr(task, "affected_files", None)
        if files:
            parts.append(f"\nAffected files: {', '.join(files)}")

        swecas = getattr(task, "swecas_code", None)
        if swecas:
            parts.append(f"\nSWECAS category: {swecas}")

        oss_ctx = getattr(task, "oss_context", "")
        if oss_ctx:
            parts.append(f"\n\nOSS Best Practices (from top GitHub repos):\n{oss_ctx}")

        # Week 29: PE-02 (Few-Shot Examples) — inject curated code snippets (+2.2 gain)
        try:
            from .few_shot_library import get_few_shot_examples
            query = getattr(task, "query", "")
            if query:
                keywords = query.lower().split()
                examples = get_few_shot_examples(keywords, max_examples=2)
                if examples:
                    parts.append(examples)
                    logger.debug("[MultiCandidate] PE-02: %d few-shot chars injected", len(examples))
        except (ImportError, Exception) as exc:
            logger.debug("[MultiCandidate] few_shot_library not available: %s", exc)

        return "\n".join(parts)

    @staticmethod
    def _system_prompt(task) -> str:
        task_type = getattr(task, "type", None)
        risk = getattr(task, "risk_level", None)

        base = (
            "You are an expert code generator.\n"
            f"Task type: {task_type.value if task_type else 'general'}\n"
            f"Risk level: {risk.name if risk else 'UNKNOWN'}\n\n"
            "YOU RETURN CODE ONLY!\n"
            "DO NOT ADD EXPLANATIONS.\n"
            "DO NOT USE MARKDOWN to format your output.\n"
            "Include type hints, docstrings, error handling, and comments inside the code."
        )

        # Detect domain for quality requirements
        detected = "python"
        try:
            from core.codegen.quality_prompts import detect_task_type, QUALITY_REQUIREMENTS
            query = getattr(task, "query", "")
            detected = detect_task_type(query) if query else "python"
            if task_type:
                type_map = {
                    "code_generation": "python",
                    "infrastructure": "kubernetes",
                    "bug_fix": "python",
                    "refactoring": "python",
                    "general": "python",
                }
                detected = type_map.get(task_type.value, detected)
            requirements = QUALITY_REQUIREMENTS.get(detected, "")
            if requirements:
                base += f"\n\n{requirements}"
        except (ImportError, Exception) as exc:
            logger.debug("[MultiCandidate] quality_prompts not available: %s", exc)

        # Week 29: PE-04 (7 Deadly Sins) + PE-06 (Self-Check) + PE-03 (Error Warnings)
        # Biggest quality gain: +3.1 (PE-04) + +2.7 (PE-06) + +1.8 (PE-03) = +7.6
        try:
            from .engineer_10x import build_10x_prompt
            query = getattr(task, "query", "")
            base = build_10x_prompt(
                base_prompt=base,
                task_type=detected,
                include_sins=True,        # PE-04: 7 Deadly Sins (+3.1)
                include_self_check=True,  # PE-06: 6-Point Self-Check (+2.7)
                query=query,              # PE-03: Error Pattern Warnings (+1.8)
            )
            logger.debug("[MultiCandidate] PE-04/PE-06/PE-03 injected into system prompt")
        except (ImportError, Exception) as exc:
            logger.debug("[MultiCandidate] engineer_10x not available: %s", exc)

        oss_ctx = getattr(task, "oss_context", "")
        if oss_ctx:
            base += "\nUse patterns from popular open-source projects when applicable."

        return base

    @staticmethod
    def _extract_code(raw: str) -> str:
        """Extract code from markdown fences if present.

        Also strips <think>...</think> blocks from reasoning models
        (e.g. deepseek-r1) that wrap their chain-of-thought output.
        """
        # Strip <think>...</think> blocks (deepseek-r1, QwQ, etc.)
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if not cleaned:
            cleaned = raw.strip()  # fallback if entire output was in <think>

        # Match ```python ... ``` or ``` ... ```
        m = re.search(r"```(?:python|py)?\s*\n(.*?)```", cleaned, re.DOTALL)
        if m:
            return m.group(1).strip()
        return cleaned
