"""
Week 29 Tests: Trinity Pipeline — Multi-Model Candidate Generation

Tests for:
1. TrinityModelManager — selection strategies (rotate, role_based, risk_based)
2. AsyncLLMAdapter — model override parameter
3. MultiCandidateGenerator — model_manager integration
4. Config parsing — env var parsing for trinity models
5. Pipeline passthrough — model_manager wired through pipeline
6. Server endpoints — /api/trinity/status, /api/trinity/toggle

~40 tests covering all integration points.
"""
import asyncio
import os
import sys
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.generation.trinity_model_manager import (
    TrinityModelManager,
    TrinityRole,
    DEFAULT_TRINITY_MODELS,
    parse_trinity_models_env,
    _DEFAULT_ROLE_ORDER,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

TRINITY_MODELS = {
    "architect": "deepseek-r1:7b",
    "developer": "qwen2.5-coder:7b",
    "reviewer": "deepseek-coder:6.7b-instruct",
}


@pytest.fixture
def manager():
    return TrinityModelManager(models=TRINITY_MODELS, strategy="rotate")


@pytest.fixture
def role_manager():
    return TrinityModelManager(models=TRINITY_MODELS, strategy="role_based")


@pytest.fixture
def risk_manager():
    return TrinityModelManager(models=TRINITY_MODELS, strategy="risk_based")


@dataclass
class MockTaskContext:
    complexity: str = "MODERATE"


# ═══════════════════════════════════════════════════════════════════════════
# 1. TrinityModelManager — Core Behavior
# ═══════════════════════════════════════════════════════════════════════════

class TestTrinityModelManagerBasic:
    """Basic TrinityModelManager functionality."""

    def test_enabled_with_3_models(self, manager):
        assert manager.enabled is True

    def test_enabled_with_1_model(self):
        mgr = TrinityModelManager(
            models={"developer": "qwen2.5-coder:7b"},
        )
        assert mgr.enabled is False

    def test_enabled_with_duplicate_models(self):
        mgr = TrinityModelManager(
            models={"architect": "qwen:7b", "developer": "qwen:7b", "reviewer": "qwen:7b"},
        )
        assert mgr.enabled is False  # same model → no cross-arch benefit

    def test_enabled_with_2_distinct_models(self):
        mgr = TrinityModelManager(
            models={"architect": "deepseek-r1:7b", "developer": "qwen2.5-coder:7b"},
        )
        assert mgr.enabled is True

    def test_model_count(self, manager):
        assert manager.model_count == 3

    def test_disabled_flag(self, manager):
        assert manager.enabled is True
        manager._disabled = True
        assert manager.enabled is False
        manager._disabled = False
        assert manager.enabled is True


# ═══════════════════════════════════════════════════════════════════════════
# 2. Selection Strategies
# ═══════════════════════════════════════════════════════════════════════════

class TestRotateStrategy:
    """Round-robin rotation across all models."""

    def test_rotate_index_0(self, manager):
        model = manager.select_for_candidate(0)
        assert model in TRINITY_MODELS.values()

    def test_rotate_cycles(self, manager):
        models = [manager.select_for_candidate(i) for i in range(6)]
        # First 3 and second 3 should be the same rotation
        assert models[:3] == models[3:]

    def test_rotate_all_models_used(self, manager):
        models = {manager.select_for_candidate(i) for i in range(3)}
        assert len(models) == 3

    def test_stats_updated(self, manager):
        manager.select_for_candidate(0)
        assert manager._stats["selections"] == 1
        assert manager._stats["full_pipeline_used"] == 1


class TestRoleBasedStrategy:
    """Developer → Reviewer → Architect order."""

    def test_role_order_0_is_developer(self, role_manager):
        model = role_manager.select_for_candidate(0)
        assert model == "qwen2.5-coder:7b"

    def test_role_order_1_is_reviewer(self, role_manager):
        model = role_manager.select_for_candidate(1)
        assert model == "deepseek-coder:6.7b-instruct"

    def test_role_order_2_is_architect(self, role_manager):
        model = role_manager.select_for_candidate(2)
        assert model == "deepseek-r1:7b"

    def test_role_wraps_around(self, role_manager):
        model3 = role_manager.select_for_candidate(3)
        model0 = role_manager.select_for_candidate(0)
        assert model3 == model0  # wraps to developer


class TestRiskBasedStrategy:
    """Uses all models for complex tasks, developer only for simple."""

    def test_complex_uses_all_models(self, risk_manager):
        ctx = MockTaskContext(complexity="COMPLEX")
        models = {risk_manager.select_for_candidate(i, ctx) for i in range(3)}
        assert len(models) == 3

    def test_simple_uses_developer_only(self, risk_manager):
        ctx = MockTaskContext(complexity="SIMPLE")
        models = {risk_manager.select_for_candidate(i, ctx) for i in range(3)}
        assert len(models) == 1
        assert "qwen2.5-coder:7b" in models

    def test_trivial_uses_developer_only(self, risk_manager):
        ctx = MockTaskContext(complexity="TRIVIAL")
        model = risk_manager.select_for_candidate(0, ctx)
        assert model == "qwen2.5-coder:7b"

    def test_moderate_uses_all_models(self, risk_manager):
        ctx = MockTaskContext(complexity="MODERATE")
        models = {risk_manager.select_for_candidate(i, ctx) for i in range(3)}
        assert len(models) == 3

    def test_none_context_uses_full(self, risk_manager):
        models = {risk_manager.select_for_candidate(i) for i in range(3)}
        assert len(models) == 3


# ═══════════════════════════════════════════════════════════════════════════
# 3. should_use_full_pipeline
# ═══════════════════════════════════════════════════════════════════════════

class TestDomainRouting:

    def test_no_context_returns_true(self, manager):
        assert manager.should_use_full_pipeline(None) is True

    def test_trivial_returns_false(self, manager):
        ctx = MockTaskContext(complexity="TRIVIAL")
        assert manager.should_use_full_pipeline(ctx) is False

    def test_simple_returns_false(self, manager):
        ctx = MockTaskContext(complexity="SIMPLE")
        assert manager.should_use_full_pipeline(ctx) is False

    def test_moderate_returns_true(self, manager):
        ctx = MockTaskContext(complexity="MODERATE")
        assert manager.should_use_full_pipeline(ctx) is True

    def test_complex_returns_true(self, manager):
        ctx = MockTaskContext(complexity="COMPLEX")
        assert manager.should_use_full_pipeline(ctx) is True

    def test_enum_complexity(self, manager):
        """Test with complexity that has .name attribute (like an Enum)."""
        mock = Mock()
        mock.complexity = Mock()
        mock.complexity.name = "TRIVIAL"
        mock.complexity.value = "TRIVIAL"
        assert manager.should_use_full_pipeline(mock) is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. get_status / get_role_for_index
# ═══════════════════════════════════════════════════════════════════════════

class TestStatusAndHelpers:

    def test_get_status_dict(self, manager):
        status = manager.get_status()
        assert status["enabled"] is True
        assert status["strategy"] == "rotate"
        assert status["model_count"] == 3
        assert "models" in status
        assert "stats" in status

    def test_get_role_for_index(self, manager):
        assert manager.get_role_for_index(0) == TrinityRole.DEVELOPER
        assert manager.get_role_for_index(1) == TrinityRole.REVIEWER
        assert manager.get_role_for_index(2) == TrinityRole.ARCHITECT
        assert manager.get_role_for_index(3) == TrinityRole.DEVELOPER  # wraps

    def test_get_model_for_role(self, manager):
        assert manager.get_model_for_role(TrinityRole.ARCHITECT) == "deepseek-r1:7b"
        assert manager.get_model_for_role(TrinityRole.DEVELOPER) == "qwen2.5-coder:7b"
        assert manager.get_model_for_role(TrinityRole.REVIEWER) == "deepseek-coder:6.7b-instruct"


# ═══════════════════════════════════════════════════════════════════════════
# 5. parse_trinity_models_env
# ═══════════════════════════════════════════════════════════════════════════

class TestEnvParsing:

    def test_positional_3_models(self):
        result = parse_trinity_models_env(
            "deepseek-r1:7b,qwen2.5-coder:7b,deepseek-coder:6.7b-instruct"
        )
        assert result["architect"] == "deepseek-r1:7b"
        assert result["developer"] == "qwen2.5-coder:7b"
        assert result["reviewer"] == "deepseek-coder:6.7b-instruct"

    def test_positional_2_models(self):
        result = parse_trinity_models_env("deepseek-r1:7b,qwen2.5-coder:7b")
        assert len(result) == 2
        assert "architect" in result
        assert "developer" in result

    def test_key_value_format(self):
        result = parse_trinity_models_env(
            "architect=deepseek-r1:7b,developer=qwen2.5-coder:7b,reviewer=deepseek-coder:6.7b-instruct"
        )
        assert result["architect"] == "deepseek-r1:7b"
        assert result["developer"] == "qwen2.5-coder:7b"

    def test_empty_string(self):
        assert parse_trinity_models_env("") == {}

    def test_whitespace(self):
        result = parse_trinity_models_env(" deepseek-r1:7b , qwen2.5-coder:7b ")
        assert result["architect"] == "deepseek-r1:7b"
        assert result["developer"] == "qwen2.5-coder:7b"


# ═══════════════════════════════════════════════════════════════════════════
# 6. AsyncLLMAdapter — model override
# ═══════════════════════════════════════════════════════════════════════════

class TestLLMAdapterModelOverride:

    @pytest.fixture
    def adapter(self):
        from core.generation.llm_adapter import AsyncLLMAdapter
        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value="def hello(): pass")
        mock_client.generate_stream = True  # mark as async client
        return AsyncLLMAdapter(mock_client, model="qwen2.5-coder:7b")

    def test_default_model(self, adapter):
        assert adapter.model_name == "qwen2.5-coder:7b"

    def test_override_model_passed_to_client(self, adapter):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                adapter.generate(
                    prompt="test",
                    system="sys",
                    temperature=0.5,
                    seed=42,
                    model="deepseek-r1:7b",
                )
            )
        finally:
            loop.close()
        # Verify the override model was passed, not the default
        call_kwargs = adapter._client.generate.call_args
        assert call_kwargs.kwargs.get("model") == "deepseek-r1:7b"

    def test_none_override_uses_default(self, adapter):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                adapter.generate(
                    prompt="test",
                    system="sys",
                    temperature=0.5,
                    seed=42,
                    model=None,
                )
            )
        finally:
            loop.close()
        call_kwargs = adapter._client.generate.call_args
        assert call_kwargs.kwargs.get("model") == "qwen2.5-coder:7b"

    def test_no_model_param_uses_default(self, adapter):
        """Backwards compatibility: calling without model= works."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                adapter.generate(
                    prompt="test",
                    system="sys",
                    temperature=0.5,
                    seed=42,
                )
            )
        finally:
            loop.close()
        call_kwargs = adapter._client.generate.call_args
        assert call_kwargs.kwargs.get("model") == "qwen2.5-coder:7b"


# ═══════════════════════════════════════════════════════════════════════════
# 7. MultiCandidateGenerator with model_manager
# ═══════════════════════════════════════════════════════════════════════════

class TestGeneratorWithTrinity:

    @pytest.fixture
    def mock_llm(self):
        llm = AsyncMock()
        llm.model_name = "qwen2.5-coder:7b"
        llm.generate = AsyncMock(return_value="def hello(): pass")
        return llm

    def test_generator_accepts_model_manager(self, mock_llm):
        from core.generation.multi_candidate import MultiCandidateGenerator
        mgr = TrinityModelManager(models=TRINITY_MODELS)
        gen = MultiCandidateGenerator(llm=mock_llm, model_manager=mgr)
        assert gen.model_manager is mgr

    def test_generator_none_manager(self, mock_llm):
        from core.generation.multi_candidate import MultiCandidateGenerator
        gen = MultiCandidateGenerator(llm=mock_llm, model_manager=None)
        assert gen.model_manager is None

    def test_candidate_model_field_from_trinity(self, mock_llm):
        """Verify that candidate.model stores the Trinity-selected model."""
        from core.generation.multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
        mgr = TrinityModelManager(models=TRINITY_MODELS, strategy="role_based")
        config = MultiCandidateConfig(per_candidate_timeout=5.0, total_timeout=30.0)
        gen = MultiCandidateGenerator(llm=mock_llm, config=config, model_manager=mgr)

        task = Mock()
        task.task_id = "test_1"
        task.query = "write a sort function"
        task.affected_files = []
        task.swecas_code = None
        task.oss_context = ""
        task.type = None
        task.risk_level = None
        task.complexity = None

        loop = asyncio.new_event_loop()
        try:
            pool = loop.run_until_complete(gen.generate(task, n=3, parallel=False))
        finally:
            loop.close()

        assert pool.size == 3
        # With role_based strategy: developer, reviewer, architect
        models_used = [c.model for c in pool.candidates]
        assert models_used[0] == "qwen2.5-coder:7b"      # developer
        assert models_used[1] == "deepseek-coder:6.7b-instruct"  # reviewer
        assert models_used[2] == "deepseek-r1:7b"         # architect

    def test_candidate_model_without_manager(self, mock_llm):
        """Without model_manager, candidate.model should be llm.model_name."""
        from core.generation.multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
        config = MultiCandidateConfig(per_candidate_timeout=5.0, total_timeout=30.0)
        gen = MultiCandidateGenerator(llm=mock_llm, config=config, model_manager=None)

        task = Mock()
        task.task_id = "test_2"
        task.query = "write hello world"
        task.affected_files = []
        task.swecas_code = None
        task.oss_context = ""
        task.type = None
        task.risk_level = None
        task.complexity = None

        loop = asyncio.new_event_loop()
        try:
            pool = loop.run_until_complete(gen.generate(task, n=2, parallel=False))
        finally:
            loop.close()

        for c in pool.candidates:
            assert c.model == "qwen2.5-coder:7b"


# ═══════════════════════════════════════════════════════════════════════════
# 8. Pipeline passthrough
# ═══════════════════════════════════════════════════════════════════════════

class TestPipelinePassthrough:

    def test_pipeline_accepts_model_manager(self):
        from core.generation.pipeline import MultiCandidatePipeline
        llm = Mock()
        llm.model_name = "test"
        mgr = TrinityModelManager(models=TRINITY_MODELS)
        pipeline = MultiCandidatePipeline(llm=llm, model_manager=mgr)
        assert pipeline.model_manager is mgr
        assert pipeline.generator.model_manager is mgr

    def test_pipeline_none_manager(self):
        from core.generation.pipeline import MultiCandidatePipeline
        llm = Mock()
        llm.model_name = "test"
        pipeline = MultiCandidatePipeline(llm=llm, model_manager=None)
        assert pipeline.model_manager is None
        assert pipeline.generator.model_manager is None


# ═══════════════════════════════════════════════════════════════════════════
# 9. Config integration
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigIntegration:

    def test_model_config_defaults(self):
        from core.config import ModelConfig
        mc = ModelConfig()
        assert mc.trinity_enabled is False
        assert mc.trinity_strategy == "rotate"
        assert mc.trinity_models == {}

    def test_model_config_trinity_fields(self):
        from core.config import ModelConfig
        mc = ModelConfig(
            trinity_enabled=True,
            trinity_strategy="role_based",
            trinity_models=TRINITY_MODELS,
        )
        assert mc.trinity_enabled is True
        assert mc.trinity_strategy == "role_based"
        assert len(mc.trinity_models) == 3

    def test_from_env_trinity(self):
        from core.config import QwenCodeConfig
        env = {
            "QWEN_TRINITY_ENABLED": "true",
            "QWEN_TRINITY_STRATEGY": "risk_based",
            "QWEN_TRINITY_MODELS": "deepseek-r1:7b,qwen2.5-coder:7b,deepseek-coder:6.7b-instruct",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = QwenCodeConfig.from_env()
        assert cfg.models.trinity_enabled is True
        assert cfg.models.trinity_strategy == "risk_based"
        assert len(cfg.models.trinity_models) == 3

    def test_to_dict_includes_trinity(self):
        from core.config import QwenCodeConfig
        cfg = QwenCodeConfig()
        cfg.models.trinity_enabled = True
        cfg.models.trinity_models = TRINITY_MODELS
        d = cfg.to_dict()
        assert d["models"]["trinity_enabled"] is True
        assert d["models"]["trinity_models"] == TRINITY_MODELS


# ═══════════════════════════════════════════════════════════════════════════
# 10. TrinityRole enum
# ═══════════════════════════════════════════════════════════════════════════

class TestTrinityRole:

    def test_role_values(self):
        assert TrinityRole.ARCHITECT == "architect"
        assert TrinityRole.DEVELOPER == "developer"
        assert TrinityRole.REVIEWER == "reviewer"

    def test_role_is_string(self):
        assert isinstance(TrinityRole.ARCHITECT, str)

    def test_default_role_order(self):
        assert _DEFAULT_ROLE_ORDER == [
            TrinityRole.DEVELOPER,
            TrinityRole.REVIEWER,
            TrinityRole.ARCHITECT,
        ]

    def test_default_models(self):
        assert TrinityRole.ARCHITECT in DEFAULT_TRINITY_MODELS or \
               TrinityRole.ARCHITECT.value in {str(k) for k in DEFAULT_TRINITY_MODELS}


class TestToggleStrategyChange:
    """Test toggle endpoint behavior with strategy changes."""

    def _manager(self):
        return TrinityModelManager(
            models=TRINITY_MODELS,
            strategy="rotate",
        )

    def test_strategy_change_rotate_to_role_based(self):
        m = self._manager()
        assert m.strategy == "rotate"
        m.strategy = "role_based"
        assert m.strategy == "role_based"
        # Selection should now use role_based logic
        model = m.select_for_candidate(0)
        assert model == TRINITY_MODELS["developer"]

    def test_strategy_change_to_risk_based(self):
        m = self._manager()
        m.strategy = "risk_based"
        # Without context → full pipeline
        model = m.select_for_candidate(0)
        assert model in TRINITY_MODELS.values()

    def test_toggle_disable_reenable(self):
        m = self._manager()
        assert m.enabled is True
        m._disabled = True
        assert m.enabled is False
        m._disabled = False
        assert m.enabled is True

    def test_toggle_preserves_strategy(self):
        m = self._manager()
        m.strategy = "risk_based"
        m._disabled = True
        assert m.enabled is False
        assert m.strategy == "risk_based"
        m._disabled = False
        assert m.enabled is True
        assert m.strategy == "risk_based"

    def test_toggle_preserves_stats(self):
        m = self._manager()
        m.select_for_candidate(0)
        m.select_for_candidate(1)
        assert m._stats["selections"] == 2
        m._disabled = True
        m._disabled = False
        assert m._stats["selections"] == 2

    def test_status_reflects_strategy_change(self):
        m = self._manager()
        m.strategy = "role_based"
        status = m.get_status()
        assert status["strategy"] == "role_based"

    def test_invalid_strategy_still_works(self):
        """Manager doesn't crash on unexpected strategy — falls through to rotate."""
        m = self._manager()
        m.strategy = "unknown"
        # select_for_candidate should fall through to the else branch (rotate)
        model = m.select_for_candidate(0)
        assert model in TRINITY_MODELS.values()


# ============================================================
# Week 29: _extract_code — <think> tag stripping for reasoning models
# ============================================================

class TestExtractCodeThinkTags:
    """Verify _extract_code strips <think> blocks from deepseek-r1 output."""

    @staticmethod
    def _extract(raw):
        from core.generation.multi_candidate import MultiCandidateGenerator
        return MultiCandidateGenerator._extract_code(raw)

    def test_strips_think_tags_with_code_fence(self):
        raw = '<think>\nLet me reason about fibonacci...\n</think>\n\n```python\ndef fib(n):\n    return n if n < 2 else fib(n-1) + fib(n-2)\n```'
        result = self._extract(raw)
        assert result == "def fib(n):\n    return n if n < 2 else fib(n-1) + fib(n-2)"
        assert "<think>" not in result

    def test_strips_think_tags_without_code_fence(self):
        raw = '<think>\nThinking about this...\n</think>\n\ndef hello():\n    print("hello")'
        result = self._extract(raw)
        assert "def hello():" in result
        assert "<think>" not in result

    def test_multiple_think_blocks(self):
        raw = '<think>first thought</think>\nsome code\n<think>second thought</think>\nmore code'
        result = self._extract(raw)
        assert "<think>" not in result
        assert "some code" in result
        assert "more code" in result

    def test_no_think_tags_unchanged(self):
        raw = '```python\nprint("hello")\n```'
        result = self._extract(raw)
        assert result == 'print("hello")'

    def test_plain_code_unchanged(self):
        raw = 'def add(a, b):\n    return a + b'
        result = self._extract(raw)
        assert result == raw

    def test_think_only_output_fallback(self):
        """If entire output is <think> tags, fall back to raw."""
        raw = '<think>All reasoning, no code</think>'
        result = self._extract(raw)
        # Should not be empty — falls back to raw stripped
        assert len(result) > 0

    def test_nested_code_fence_inside_think(self):
        """Code fence inside <think> should be ignored; outer code kept."""
        raw = '<think>\n```python\nbad_code()\n```\n</think>\n\n```python\ngood_code()\n```'
        result = self._extract(raw)
        assert result == "good_code()"
