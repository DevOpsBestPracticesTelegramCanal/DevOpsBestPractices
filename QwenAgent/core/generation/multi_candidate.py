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
from typing import List, Optional, Protocol

from .candidate import Candidate, CandidatePool

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
    ):
        self.llm = llm
        self.cfg = config or MultiCandidateConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        task,  # CodeTask or anything with .task_id, .query, etc.
        n: Optional[int] = None,
        parallel: bool = True,
    ) -> CandidatePool:
        """Generate *n* candidates and return an un-validated pool."""
        n = n or len(self.cfg.temperatures)
        pool = CandidatePool(task_id=getattr(task, "task_id", "unknown"))

        logger.info("[MultiCandidate] generating %d candidates for %s", n, pool.task_id)

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

    async def _one(self, task, index: int, total: int) -> Candidate:
        temp = self.cfg.temperatures[index % len(self.cfg.temperatures)]
        seed = self.cfg.base_seed + index

        prompt = self._prompt(task)
        system = self._system_prompt(task)

        t0 = time.perf_counter()

        code = await asyncio.wait_for(
            self.llm.generate(
                prompt=prompt,
                system=system,
                temperature=temp,
                seed=seed,
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
            model=self.llm.model_name,
            generation_time=elapsed,
        )

        logger.debug(
            "[MultiCandidate] #%d done (temp=%.1f, %d chars, %.2fs)",
            index,
            temp,
            len(code),
            elapsed,
        )

        return candidate

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

        return "\n".join(parts)

    @staticmethod
    def _system_prompt(task) -> str:
        task_type = getattr(task, "type", None)
        risk = getattr(task, "risk_level", None)

        return (
            "You are an expert code generator.\n"
            f"Task type: {task_type.value if task_type else 'general'}\n"
            f"Risk level: {risk.name if risk else 'UNKNOWN'}\n\n"
            "Output ONLY valid source code. No markdown fences, no explanations.\n"
            "Include error handling and comments inside the code."
        )

    @staticmethod
    def _extract_code(raw: str) -> str:
        """Extract code from markdown fences if present."""
        # Match ```python ... ``` or ``` ... ```
        m = re.search(r"```(?:python|py)?\s*\n(.*?)```", raw, re.DOTALL)
        if m:
            return m.group(1).strip()
        return raw.strip()
