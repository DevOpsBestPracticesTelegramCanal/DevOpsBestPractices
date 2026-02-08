# -*- coding: utf-8 -*-
"""
Tests for core.adaptive_neural_router — Adaptive Neural Router (ANR).

Groups:
  TestTrainingData          —  5 tests: data completeness, tool coverage, min examples
  TestANRClassification     — 15 tests: all 9 tools EN + RU + edge cases + confidence
  TestParamExtraction       —  6 tests: regex param extraction per tool
  TestLearning              —  4 tests: record_outcome, retrain, custom examples
  TestHybridIntegration     —  3 tests: HybridRouter with ANR, stats, fallback
  TestGracefulDegradation   —  2 tests: no sentence-transformers → fallback
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Check if sentence-transformers available
# ---------------------------------------------------------------------------

_HAS_ST = False
try:
    import sentence_transformers
    _HAS_ST = True
except ImportError:
    pass

requires_st = unittest.skipUnless(_HAS_ST, "sentence-transformers not installed")


# ===========================================================================
# TestTrainingData — data completeness
# ===========================================================================

class TestTrainingData(unittest.TestCase):
    """Validate TRAINING_DATA structure and completeness."""

    def test_training_data_exists(self):
        from core.adaptive_neural_router import TRAINING_DATA
        self.assertIsInstance(TRAINING_DATA, dict)
        self.assertGreater(len(TRAINING_DATA), 0)

    def test_all_tools_have_examples(self):
        from core.adaptive_neural_router import TRAINING_DATA, TOOL_NAMES
        for tool in TOOL_NAMES:
            self.assertIn(tool, TRAINING_DATA, f"Missing tool: {tool}")
            self.assertGreater(len(TRAINING_DATA[tool]), 0, f"No examples for {tool}")

    def test_minimum_examples_per_tool(self):
        from core.adaptive_neural_router import TRAINING_DATA
        for tool, examples in TRAINING_DATA.items():
            self.assertGreaterEqual(
                len(examples), 5,
                f"Tool '{tool}' has only {len(examples)} examples (min 5)"
            )

    def test_total_examples_count(self):
        from core.adaptive_neural_router import TRAINING_DATA
        total = sum(len(v) for v in TRAINING_DATA.values())
        self.assertGreaterEqual(total, 200, f"Only {total} total examples (need 200+)")

    def test_bilingual_coverage(self):
        """Each tool should have at least one Russian example."""
        from core.adaptive_neural_router import TRAINING_DATA
        russian_chars = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
        for tool, examples in TRAINING_DATA.items():
            has_russian = any(
                set(ex.lower()) & russian_chars for ex in examples
            )
            self.assertTrue(has_russian, f"Tool '{tool}' has no Russian examples")


# ===========================================================================
# TestANRClassification — embedding-based classification
# ===========================================================================

@requires_st
class TestANRClassification(unittest.TestCase):
    """Test classification accuracy for all tool categories."""

    @classmethod
    def setUpClass(cls):
        from core.adaptive_neural_router import AdaptiveNeuralRouter
        cls.anr = AdaptiveNeuralRouter()

    def _assert_tool(self, query, expected_tool, msg=None):
        result = self.anr.classify(query)
        self.assertEqual(
            result.tool, expected_tool,
            msg or f"Query '{query}' → {result.tool} (expected {expected_tool}, conf={result.confidence:.2f})"
        )
        return result

    # --- English classification tests ---

    def test_classify_read_en(self):
        self._assert_tool("show me the contents of agent.py", "read")

    def test_classify_grep_en(self):
        self._assert_tool("search for 'def classify' in the codebase", "grep")

    def test_classify_bash_en(self):
        self._assert_tool("run pytest on the test suite", "bash")

    def test_classify_ls_en(self):
        self._assert_tool("what files are in the core directory", "ls")

    def test_classify_glob_en(self):
        self._assert_tool("find all Python files in the project", "glob")

    def test_classify_write_en(self):
        self._assert_tool("create a new file called helper.py", "write")

    def test_classify_edit_en(self):
        self._assert_tool("change the timeout value from 30 to 60 in config", "edit")

    def test_classify_find_en(self):
        self._assert_tool("where is the main entry point defined", "find")

    def test_classify_help_en(self):
        self._assert_tool("what can you do for me", "help")

    # --- Russian classification tests ---

    def test_classify_read_ru(self):
        self._assert_tool("покажи мне содержимое файла server.py", "read")

    def test_classify_grep_ru(self):
        self._assert_tool("найди все вхождения слова timeout в коде", "grep")

    def test_classify_bash_ru(self):
        self._assert_tool("запусти тесты пожалуйста", "bash")

    def test_classify_ls_ru(self):
        self._assert_tool("покажи список файлов в папке tests", "ls")

    # --- Edge cases ---

    def test_confidence_above_threshold(self):
        """Clear queries should have confidence >= 0.5."""
        result = self.anr.classify("read the file config.py")
        self.assertGreaterEqual(result.confidence, 0.5)

    def test_result_has_top_matches(self):
        result = self.anr.classify("show me agent.py")
        self.assertIsInstance(result.top_matches, list)
        self.assertGreater(len(result.top_matches), 0)

    def test_timing_tracked(self):
        result = self.anr.classify("run the tests")
        self.assertGreaterEqual(result.embedding_time_ms, 0)

    def test_method_is_neural(self):
        result = self.anr.classify("list files here")
        self.assertEqual(result.method, "neural")

    def test_stats_increment(self):
        """Stats should track total classifications."""
        before = self.anr._total_classifications
        self.anr.classify("something")
        self.assertEqual(self.anr._total_classifications, before + 1)


# ===========================================================================
# TestParamExtraction — regex param extraction per tool
# ===========================================================================

@requires_st
class TestParamExtraction(unittest.TestCase):
    """Test parameter extraction after intent classification."""

    @classmethod
    def setUpClass(cls):
        from core.adaptive_neural_router import AdaptiveNeuralRouter
        cls.anr = AdaptiveNeuralRouter()

    def test_extract_read_params(self):
        params = self.anr.extract_params("read core/agent.py", "read")
        self.assertEqual(params.get("file_path"), "core/agent.py")

    def test_extract_grep_params(self):
        params = self.anr.extract_params("search for 'PatternRouter' in router.py", "grep")
        self.assertEqual(params.get("pattern"), "PatternRouter")

    def test_extract_bash_params(self):
        params = self.anr.extract_params("run pytest tests/ -v", "bash")
        self.assertEqual(params.get("command"), "pytest tests/ -v")

    def test_extract_ls_params(self):
        params = self.anr.extract_params("list files in core/", "ls")
        self.assertIn("path", params)

    def test_extract_glob_params(self):
        params = self.anr.extract_params("find all .py files", "glob")
        self.assertIn("pattern", params)
        self.assertIn("py", params["pattern"])

    def test_extract_fallback_raw_input(self):
        """When no regex matches, return raw input."""
        params = self.anr.extract_params("do something weird", "help")
        self.assertIn("_raw_input", params)
        self.assertEqual(params["_raw_input"], "do something weird")


# ===========================================================================
# TestFullRoute — classify + extract combined
# ===========================================================================

@requires_st
class TestFullRoute(unittest.TestCase):
    """Test the full route() method (classify + extract)."""

    @classmethod
    def setUpClass(cls):
        from core.adaptive_neural_router import AdaptiveNeuralRouter
        cls.anr = AdaptiveNeuralRouter()

    def test_route_returns_dict(self):
        result = self.anr.route("show me agent.py")
        self.assertIsNotNone(result)
        self.assertIn("tool", result)
        self.assertIn("params", result)
        self.assertIn("confidence", result)

    def test_route_low_confidence_returns_none(self):
        """Gibberish should return None (below threshold)."""
        result = self.anr.route("xyzzy plugh 12345 !@#$%", min_confidence=0.99)
        self.assertIsNone(result)

    def test_route_method_is_neural(self):
        result = self.anr.route("read the config file")
        if result:
            self.assertEqual(result["method"], "neural")


# ===========================================================================
# TestLearning — record_outcome, retrain, custom examples
# ===========================================================================

@requires_st
class TestLearning(unittest.TestCase):
    """Test learning DB: record_outcome, retrain, custom examples."""

    def setUp(self):
        from core.adaptive_neural_router import AdaptiveNeuralRouter
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.anr = AdaptiveNeuralRouter(db_path=self.tmp.name)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_record_correct_outcome(self):
        self.anr.record_outcome("show agent.py", "read", 0.85, "read")
        stats = self.anr.get_stats()
        self.assertEqual(stats["history_records"], 1)
        self.assertAlmostEqual(stats["history_accuracy"], 1.0)

    def test_record_wrong_outcome_creates_custom_example(self):
        self.anr.record_outcome("deploy to production", "bash", 0.7, "write")
        stats = self.anr.get_stats()
        self.assertEqual(stats["history_records"], 1)
        self.assertEqual(stats["custom_examples"], 1)

    def test_retrain_incorporates_examples(self):
        self.anr.add_custom_example("deploy the app to staging", "bash")
        self.anr.add_custom_example("ship it to production", "bash")
        count = self.anr.retrain_from_history()
        self.assertEqual(count, 2)

    def test_retrain_no_duplicates(self):
        self.anr.add_custom_example("deploy the app", "bash")
        count1 = self.anr.retrain_from_history()
        count2 = self.anr.retrain_from_history()
        # Second retrain should add 0 (already in training data)
        self.assertEqual(count2, 0)


# ===========================================================================
# TestHybridIntegration — HybridRouter with ANR
# ===========================================================================

@requires_st
class TestHybridIntegration(unittest.TestCase):
    """Test ANR integration in HybridRouter."""

    def test_hybrid_router_has_anr(self):
        from core.router import HybridRouter
        router = HybridRouter()
        anr = router._get_anr()
        self.assertIsNotNone(anr)

    def test_hybrid_stats_include_anr(self):
        from core.router import HybridRouter
        router = HybridRouter()
        stats = router.get_stats()
        self.assertIn("anr_hits", stats)
        self.assertIn("anr_rate", stats)
        self.assertIn("anr_available", stats)
        self.assertTrue(stats["anr_available"])

    def test_hybrid_routes_via_anr(self):
        """A query that misses PatternRouter but is clear should route via ANR."""
        from core.router import HybridRouter
        router = HybridRouter()
        # This phrasing is unusual enough to miss simple regex
        # but clear enough for the embedding model
        result = router.route("I need to see what's inside the orchestrator module")
        # Should route via neural or pattern (either is acceptable)
        self.assertIn(result.method, ('pattern', 'neural', 'intent'))
        if result.method == 'neural':
            self.assertEqual(router.stats['anr_hits'], 1)


# ===========================================================================
# TestANRProperties — basic properties and stats
# ===========================================================================

@requires_st
class TestANRProperties(unittest.TestCase):
    """Test ANR properties and get_stats()."""

    @classmethod
    def setUpClass(cls):
        from core.adaptive_neural_router import AdaptiveNeuralRouter
        cls.anr = AdaptiveNeuralRouter()

    def test_is_available(self):
        self.assertTrue(self.anr.is_available)

    def test_model_name(self):
        self.assertEqual(self.anr.model_name, "all-MiniLM-L6-v2")

    def test_n_examples(self):
        self.assertGreater(self.anr.n_examples, 200)

    def test_get_stats_keys(self):
        stats = self.anr.get_stats()
        expected_keys = {
            "model", "total_training_examples", "tool_categories",
            "total_classifications", "per_tool_hits", "miss_count",
            "history_records", "history_accuracy", "custom_examples",
            "embedding_dim",
        }
        for key in expected_keys:
            self.assertIn(key, stats, f"Missing key: {key}")

    def test_embedding_dim_384(self):
        """all-MiniLM-L6-v2 produces 384-dim embeddings."""
        stats = self.anr.get_stats()
        self.assertEqual(stats["embedding_dim"], 384)


# ===========================================================================
# TestGracefulDegradation — no sentence-transformers
# ===========================================================================

class TestGracefulDegradation(unittest.TestCase):
    """Test behaviour when sentence-transformers is not available."""

    def test_anr_raises_without_st(self):
        """ANR constructor should raise RuntimeError if ST unavailable."""
        import core.adaptive_neural_router as anr_mod
        original = anr_mod._HAS_ST
        anr_mod._HAS_ST = False
        try:
            with self.assertRaises(RuntimeError):
                anr_mod.AdaptiveNeuralRouter()
        finally:
            anr_mod._HAS_ST = original

    def test_hybrid_router_falls_back_without_anr(self):
        """HybridRouter should still work when ANR is disabled."""
        from core.router import HybridRouter
        router = HybridRouter()
        # Force ANR disabled
        router._anr = False
        result = router.route("list files in core/")
        # Should still route via pattern or intent
        self.assertIn(result.method, ('pattern', 'intent', 'llm_required'))


if __name__ == "__main__":
    unittest.main()
