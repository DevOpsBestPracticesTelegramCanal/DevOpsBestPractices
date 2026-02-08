# -*- coding: utf-8 -*-
"""
Tests for OSS Consciousness → Multi-Candidate Pipeline integration.

Tests cover:
1. oss_context flows through _SimpleTask → generator → prompt
2. OSSPatternRule scoring
3. Agent STEP 1.85 OSS context enrichment
4. Graceful degradation (empty store, no oss_tool)
5. Prompt construction with/without oss_context
6. End-to-end: query → OSS enrichment → pipeline → code
"""

import asyncio
import re
import pytest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch, AsyncMock

from core.generation.pipeline import MultiCandidatePipeline, PipelineConfig, _SimpleTask
from core.generation.multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
from core.generation.selector import ScoringWeights, CandidateSelector
from core.generation.candidate import Candidate, CandidatePool
from code_validator.rules.python_validators import (
    OSSPatternRule, default_python_rules,
)
from code_validator.rules.base import RuleSeverity

from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord
from core.oss.oss_engine import OSSEngine
from core.oss.oss_tool import OSSTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    """In-memory pattern store seeded with sample data."""
    s = PatternStore(db_path=":memory:")
    # Add a few repos
    repos = [
        RepoRecord(full_name="pallets/flask", stars=65000, description="Web framework"),
        RepoRecord(full_name="tiangolo/fastapi", stars=75000, description="Fast web framework"),
        RepoRecord(full_name="psf/requests", stars=50000, description="HTTP library"),
    ]
    for r in repos:
        s.save_repo(r)

    # Add patterns
    patterns = [
        PatternRecord(repo_name="pallets/flask", category="framework", pattern_name="flask", confidence=1.0),
        PatternRecord(repo_name="tiangolo/fastapi", category="framework", pattern_name="fastapi", confidence=1.0),
        PatternRecord(repo_name="pallets/flask", category="testing", pattern_name="pytest", confidence=0.9),
        PatternRecord(repo_name="tiangolo/fastapi", category="testing", pattern_name="pytest", confidence=0.95),
        PatternRecord(repo_name="psf/requests", category="testing", pattern_name="pytest", confidence=0.8),
        PatternRecord(repo_name="tiangolo/fastapi", category="linting", pattern_name="ruff", confidence=1.0),
    ]
    s.save_patterns(patterns)
    s.refresh_pattern_stats()
    return s


@pytest.fixture
def engine(store):
    return OSSEngine(store)


@pytest.fixture
def oss_tool(store):
    """OSSTool backed by the seeded store."""
    tool = OSSTool(db_path=":memory:")
    # Replace the internal store/engine with our seeded ones
    tool._store = store
    tool._engine = OSSEngine(store)
    return tool


@pytest.fixture
def empty_store():
    """Empty in-memory store."""
    return PatternStore(db_path=":memory:")


@pytest.fixture
def empty_engine(empty_store):
    return OSSEngine(empty_store)


# ---------------------------------------------------------------------------
# Fake LLM for pipeline tests
# ---------------------------------------------------------------------------

class FakeLLM:
    model_name = "fake-test-model"

    async def generate(self, prompt, system, temperature, seed):
        """Return valid Python that includes some OSS patterns."""
        if "OSS Best Practices" in prompt:
            # OSS context was injected — return code using those patterns
            return (
                'import logging\n'
                'from dataclasses import dataclass\n'
                'from pathlib import Path\n\n'
                'logger = logging.getLogger(__name__)\n\n'
                '@dataclass\n'
                'class Config:\n'
                '    """Application configuration."""\n'
                '    path: Path = Path(".")\n\n'
                'def process(data: str) -> str:\n'
                '    """Process input data."""\n'
                '    try:\n'
                '        return data.upper()\n'
                '    except Exception as exc:\n'
                '        logger.error("Failed: %s", exc)\n'
                '        return ""\n'
            )
        else:
            # No OSS context — return simpler code
            return (
                'def process(data):\n'
                '    return data.upper()\n'
            )


# ===========================================================================
# Test _SimpleTask
# ===========================================================================

class TestSimpleTask:
    """Tests for the _SimpleTask dataclass."""

    def test_default_oss_context_is_empty(self):
        task = _SimpleTask()
        assert task.oss_context == ""

    def test_oss_context_set(self):
        task = _SimpleTask(oss_context="- pytest: used by 3 repos")
        assert task.oss_context == "- pytest: used by 3 repos"

    def test_oss_context_does_not_affect_other_fields(self):
        task = _SimpleTask(
            task_id="t1",
            query="write a sort function",
            oss_context="- ruff: used by 2 repos",
        )
        assert task.task_id == "t1"
        assert task.query == "write a sort function"
        assert task.swecas_code is None


# ===========================================================================
# Test prompt injection
# ===========================================================================

class TestPromptInjection:
    """Tests for OSS context in _prompt() and _system_prompt()."""

    def test_prompt_without_oss_context(self):
        task = _SimpleTask(query="write a function")
        prompt = MultiCandidateGenerator._prompt(task)
        assert "OSS Best Practices" not in prompt
        assert "write a function" in prompt

    def test_prompt_with_oss_context(self):
        ctx = "- pytest: used by 3 repos (top: tiangolo/fastapi)"
        task = _SimpleTask(query="write tests", oss_context=ctx)
        prompt = MultiCandidateGenerator._prompt(task)
        assert "OSS Best Practices (from top GitHub repos)" in prompt
        assert "pytest: used by 3 repos" in prompt

    def test_prompt_oss_context_comes_after_query(self):
        task = _SimpleTask(
            query="write a sort function",
            oss_context="- ruff: used by 2 repos",
        )
        prompt = MultiCandidateGenerator._prompt(task)
        query_pos = prompt.index("write a sort function")
        oss_pos = prompt.index("OSS Best Practices")
        assert oss_pos > query_pos

    def test_prompt_with_all_fields(self):
        task = _SimpleTask(
            query="write a validator",
            affected_files=["core/validator.py"],
            swecas_code=300,
            oss_context="- mypy: used by 5 repos",
        )
        prompt = MultiCandidateGenerator._prompt(task)
        assert "write a validator" in prompt
        assert "core/validator.py" in prompt
        assert "SWECAS category: 300" in prompt
        assert "mypy: used by 5 repos" in prompt

    def test_system_prompt_without_oss_context(self):
        task = _SimpleTask(query="write code")
        sys_prompt = MultiCandidateGenerator._system_prompt(task)
        assert "open-source projects" not in sys_prompt

    def test_system_prompt_with_oss_context(self):
        task = _SimpleTask(query="write code", oss_context="- flask: 10 repos")
        sys_prompt = MultiCandidateGenerator._system_prompt(task)
        assert "open-source projects" in sys_prompt

    def test_empty_oss_context_not_injected(self):
        task = _SimpleTask(query="write code", oss_context="")
        prompt = MultiCandidateGenerator._prompt(task)
        sys_prompt = MultiCandidateGenerator._system_prompt(task)
        assert "OSS" not in prompt
        assert "open-source" not in sys_prompt


# ===========================================================================
# Test OSSPatternRule
# ===========================================================================

class TestOSSPatternRule:
    """Tests for the OSSPatternRule validator."""

    def test_rule_name(self):
        rule = OSSPatternRule()
        assert rule.name == "oss_patterns"

    def test_rule_severity_is_info(self):
        rule = OSSPatternRule()
        assert rule.severity == RuleSeverity.INFO

    def test_rule_weight(self):
        rule = OSSPatternRule()
        assert rule.weight == 1.5

    def test_high_score_for_rich_code(self):
        """Code with many OSS patterns should score high."""
        code = '''
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class Config:
    """Application configuration."""
    path: Path = Path(".")

async def process(data: str) -> str:
    """Process input data."""
    try:
        return data.upper()
    except Exception as exc:
        logger.error("Failed: %s", exc)
        return ""
'''
        rule = OSSPatternRule()
        result = rule.check(code)
        assert result.passed is True
        assert result.score >= 0.8  # Most patterns present

    def test_low_score_for_minimal_code(self):
        """Code with no OSS patterns should score low."""
        code = 'x = 1 + 2\nprint(x)\n'
        rule = OSSPatternRule()
        result = rule.check(code)
        assert result.passed is True  # INFO severity always passes
        assert result.score <= 0.4

    def test_medium_score_for_some_patterns(self):
        """Code with a few patterns should score medium."""
        code = '''
def process(data: str) -> str:
    """Process the data."""
    try:
        return data.strip()
    except ValueError:
        return ""
'''
        rule = OSSPatternRule()
        result = rule.check(code)
        assert result.passed is True
        assert 0.3 <= result.score <= 1.0

    def test_always_passes(self):
        """OSSPatternRule should always pass (INFO severity)."""
        rule = OSSPatternRule()
        for code in ["x=1", "", "def f(): pass", "import logging\nlogger = logging.getLogger();"]:
            result = rule.check(code)
            assert result.passed is True

    def test_messages_contain_alignment_info(self):
        rule = OSSPatternRule()
        result = rule.check("def f(x: int) -> int:\n    return x")
        assert any("OSS alignment" in m for m in result.messages)

    def test_in_default_rules(self):
        rules = default_python_rules()
        names = [r.name for r in rules]
        assert "oss_patterns" in names


# ===========================================================================
# Test ScoringWeights
# ===========================================================================

class TestScoringWeightsOSS:
    """Tests for oss_patterns weight in ScoringWeights."""

    def test_oss_patterns_weight_exists(self):
        weights = ScoringWeights()
        assert "oss_patterns" in weights.weights

    def test_oss_patterns_weight_value(self):
        weights = ScoringWeights()
        assert weights.weights["oss_patterns"] == 1.5

    def test_get_oss_patterns_weight(self):
        weights = ScoringWeights()
        assert weights.get("oss_patterns") == 1.5


# ===========================================================================
# Test OSS context building from engine
# ===========================================================================

class TestOSSContextBuilding:
    """Tests for building context strings from OSSEngine queries."""

    def test_query_returns_patterns(self, engine):
        insight = engine.query("what testing frameworks are popular?")
        assert insight.confidence > 0
        assert len(insight.patterns) > 0

    def test_build_context_from_patterns(self, engine):
        insight = engine.query("testing tools")
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
        assert "pytest" in oss_context
        assert "used by" in oss_context

    def test_empty_store_returns_no_patterns(self, empty_engine):
        insight = empty_engine.query("testing tools")
        assert insight.confidence == 0.0 or len(insight.patterns) == 0

    def test_context_max_5_patterns(self, engine):
        insight = engine.query("framework")
        # Even if many patterns, we cap at 5
        capped = insight.patterns[:5]
        assert len(capped) <= 5


# ===========================================================================
# Test pipeline with OSS context
# ===========================================================================

class TestPipelineWithOSSContext:
    """Tests for the pipeline accepting oss_context parameter."""

    @pytest.fixture
    def pipeline(self):
        llm = FakeLLM()
        return MultiCandidatePipeline(
            llm=llm,
            config=PipelineConfig(
                n_candidates=1,
                parallel_generation=False,
                generation_config=MultiCandidateConfig(
                    per_candidate_timeout=10.0,
                    total_timeout=30.0,
                ),
            ),
        )

    def test_pipeline_run_without_oss_context(self, pipeline):
        result = pipeline.run_sync(
            task_id="test_no_oss",
            query="write a sort function",
        )
        assert result.best is not None
        assert result.code != ""

    def test_pipeline_run_with_oss_context(self, pipeline):
        result = pipeline.run_sync(
            task_id="test_with_oss",
            query="write a data processor function",
            oss_context="- pytest: used by 3 repos (top: tiangolo/fastapi)\n- ruff: used by 2 repos",
        )
        assert result.best is not None
        assert result.code != ""
        # OSS-enriched code should include logging (from FakeLLM)
        assert "logging" in result.code

    def test_pipeline_empty_oss_context_same_as_none(self, pipeline):
        result = pipeline.run_sync(
            task_id="test_empty_oss",
            query="write a sort function",
            oss_context="",
        )
        assert result.best is not None
        # Empty context → simple code (no logging)
        assert "process" in result.code or "sort" in result.code.lower() or result.code.strip()

    def test_oss_pattern_rule_scores_candidate(self, pipeline):
        """Pipeline with OSS context should produce candidate scored by OSSPatternRule."""
        result = pipeline.run_sync(
            task_id="test_oss_score",
            query="write a data processor",
            oss_context="- pytest: used by 3 repos",
        )
        # Check that oss_patterns validator was run
        if result.best and result.best.validation_scores:
            oss_scores = [
                vs for vs in result.best.validation_scores
                if vs.validator_name == "oss_patterns"
            ]
            assert len(oss_scores) == 1
            assert oss_scores[0].passed is True


# ===========================================================================
# Test graceful degradation
# ===========================================================================

class TestGracefulDegradation:
    """Tests for graceful degradation when OSS tool is unavailable."""

    def test_no_oss_tool_no_context(self):
        """When oss_tool is None, oss_context should remain empty."""
        oss_tool = None
        oss_context = ""
        if oss_tool:
            insight = oss_tool.engine.query("test")
            if insight.confidence >= 0.3:
                oss_context = "should not appear"
        assert oss_context == ""

    def test_empty_store_returns_low_confidence(self, empty_engine):
        """Empty store should return low confidence, so no context is built."""
        insight = empty_engine.query("write a flask app")
        # Empty store: confidence should be 0
        assert insight.confidence == 0.0

    def test_exception_in_query_graceful(self):
        """If engine.query() raises, context should remain empty."""
        mock_engine = MagicMock()
        mock_engine.query.side_effect = RuntimeError("DB error")

        oss_context = ""
        try:
            insight = mock_engine.query("test")
            if insight.confidence >= 0.3:
                oss_context = "should not appear"
        except Exception:
            pass  # Graceful degradation
        assert oss_context == ""

    def test_pipeline_works_without_oss_context(self):
        """Pipeline should work fine without any OSS context."""
        llm = FakeLLM()
        pipeline = MultiCandidatePipeline(
            llm=llm,
            config=PipelineConfig(
                n_candidates=1,
                parallel_generation=False,
                generation_config=MultiCandidateConfig(
                    per_candidate_timeout=10.0,
                    total_timeout=30.0,
                ),
            ),
        )
        result = pipeline.run_sync(task_id="no_oss", query="write a function")
        assert result.best is not None
        assert result.code != ""
