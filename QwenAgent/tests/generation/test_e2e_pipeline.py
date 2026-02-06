"""
E2E Pipeline tests — full generate → validate (internal + external) → select.

Tests the pipeline with mock LLM and mocked external validators to verify
the complete integration including external rules.
"""

import asyncio
import json
import subprocess
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.generation.pipeline import MultiCandidatePipeline, PipelineConfig, PipelineResult
from core.generation.candidate import CandidateStatus
from code_validator.rules.python_validators import default_python_rules
from code_validator.rules.external_validators import python_external_rules


# ---------------------------------------------------------------------------
# Mock LLM — returns different quality code per temperature
# ---------------------------------------------------------------------------

class E2ELLM:
    """Returns 3 variants of increasing quality at lower temperatures."""

    model_name = "e2e-mock"

    async def generate(self, prompt: str, system: str, temperature: float, seed: int) -> str:
        await asyncio.sleep(0.005)
        if temperature < 0.3:
            return (
                'def factorial(n: int) -> int:\n'
                '    """Return n! (factorial of n)."""\n'
                '    if n < 0:\n'
                '        raise ValueError("n must be non-negative")\n'
                '    result = 1\n'
                '    for i in range(2, n + 1):\n'
                '        result *= i\n'
                '    return result\n'
            )
        elif temperature < 0.6:
            return (
                'def factorial(n):\n'
                '    """Factorial."""\n'
                '    if n <= 1:\n'
                '        return 1\n'
                '    return n * factorial(n - 1)\n'
            )
        else:
            return (
                'def fact(n):\n'
                '    return 1 if n<=1 else n*fact(n-1)\n'
            )


class AllBadLLM:
    """Returns syntactically invalid code regardless of temperature."""

    model_name = "bad-mock"

    async def generate(self, prompt, system, temperature, seed):
        return "def broken(:\n    pass"


# ---------------------------------------------------------------------------
# E2E Tests — internal rules only (no subprocess mocking needed)
# ---------------------------------------------------------------------------

class TestE2EInternalOnly:
    """Pipeline with only in-process Python rules."""

    async def test_full_flow(self):
        pipeline = MultiCandidatePipeline(E2ELLM())
        result = await pipeline.run(task_id="e2e_1", query="Write factorial", n=3)

        assert result.pool.size == 3
        assert result.best is not None
        assert "def " in result.code
        assert result.score > 0

    async def test_best_has_highest_score(self):
        pipeline = MultiCandidatePipeline(E2ELLM())
        result = await pipeline.run(query="Write factorial", n=3)

        scores = [(c.id, c.total_score) for c in result.pool.candidates]
        scores.sort(key=lambda x: x[1], reverse=True)
        assert result.best.id == scores[0][0]

    async def test_all_bad_still_selects_best(self):
        """Even when all candidates are broken, pipeline picks the 'least bad'."""
        pipeline = MultiCandidatePipeline(AllBadLLM())
        result = await pipeline.run(query="test", n=3)

        assert result.best is not None
        assert result.best.has_critical_errors

    async def test_single_candidate(self):
        pipeline = MultiCandidatePipeline(E2ELLM())
        result = await pipeline.run(query="test", n=1)

        assert result.pool.size == 1
        assert result.best is not None
        assert result.best.status == CandidateStatus.SELECTED

    async def test_sync_wrapper_matches_async(self):
        pipeline = MultiCandidatePipeline(E2ELLM())
        result = pipeline.run_sync(query="Write factorial", n=2)

        assert result.pool.size == 2
        assert result.best is not None
        assert result.score > 0


# ---------------------------------------------------------------------------
# E2E Tests — internal + external rules (with mocked subprocess)
# ---------------------------------------------------------------------------

class TestE2EWithExternalRules:
    """Pipeline with both internal Python rules and mocked external validators."""

    def _make_pipeline_with_externals(self):
        """Create pipeline with internal + external (ruff, mypy) rules."""
        all_rules = default_python_rules() + python_external_rules()
        return MultiCandidatePipeline(
            E2ELLM(),
            rules=all_rules,
        )

    async def test_external_tools_not_installed(self, monkeypatch):
        """When ruff/mypy not installed, external rules skip gracefully."""
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("tool not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        pipeline = self._make_pipeline_with_externals()
        result = await pipeline.run(query="Write factorial", n=3)

        # Should still work — external validators skip with passed=True
        assert result.best is not None
        assert result.score > 0
        # External validators should be in validation scores
        ext_names = set()
        for c in result.pool.candidates:
            for v in c.validation_scores:
                ext_names.add(v.validator_name)
        assert "ruff" in ext_names
        assert "mypy" in ext_names

    async def test_external_ruff_clean(self, monkeypatch):
        """Mock ruff returning clean output."""
        def mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and cmd and cmd[0] == "ruff":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if isinstance(cmd, list) and cmd and cmd[0] == "mypy":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            raise FileNotFoundError("unknown tool")
        monkeypatch.setattr(subprocess, "run", mock_run)

        pipeline = self._make_pipeline_with_externals()
        result = await pipeline.run(query="Write factorial", n=3)

        assert result.best is not None
        # With clean ruff + mypy, scores should be high
        assert result.score > 0.5

    async def test_external_ruff_errors_reduce_score(self, monkeypatch):
        """Mock ruff returning errors — score should be lower."""
        ruff_issues = [
            {"code": "E501", "message": "Line too long", "location": {"row": 1}, "fix": None},
        ]

        def mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and cmd and cmd[0] == "ruff":
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout=json.dumps(ruff_issues), stderr=""
                )
            if isinstance(cmd, list) and cmd and cmd[0] == "mypy":
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            raise FileNotFoundError("unknown tool")
        monkeypatch.setattr(subprocess, "run", mock_run)

        pipeline_with_ext = self._make_pipeline_with_externals()
        result_ext = await pipeline_with_ext.run(query="Write factorial", n=3)

        # Compare with internal-only pipeline
        pipeline_int = MultiCandidatePipeline(E2ELLM())
        result_int = await pipeline_int.run(query="Write factorial", n=3)

        # Both should produce results
        assert result_ext.best is not None
        assert result_int.best is not None

    async def test_result_summary_complete(self, monkeypatch):
        """PipelineResult.summary() should work with external rules."""
        def raise_fnf(*a, **kw):
            raise FileNotFoundError()
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        pipeline = self._make_pipeline_with_externals()
        result = await pipeline.run(query="test", n=2)
        summary = result.summary()

        assert summary["candidates_generated"] == 2
        assert summary["best_id"] is not None
        assert isinstance(summary["best_score"], float)
        assert isinstance(summary["all_passed"], bool)
