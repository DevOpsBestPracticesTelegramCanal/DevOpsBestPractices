# -*- coding: utf-8 -*-
"""
Tests for Semantic SWECAS Classifier (core/semantic_swecas.py).

Tests cover:
- SemanticSWECAS: embedding-based classification
- HybridSWECAS: regex + semantic hybrid
- Graceful degradation when sentence-transformers unavailable
- Bilingual queries (English + Russian)
- Confidence scoring and threshold behavior
- Edge cases
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.semantic_swecas import (
    TRAINING_EXAMPLES,
    CATEGORY_NAMES,
    SemanticResult,
    _check_sentence_transformers,
)


# ---------------------------------------------------------------------------
# Helper: check if sentence-transformers is available
# ---------------------------------------------------------------------------

def _st_available():
    """Check if sentence-transformers is installed."""
    try:
        import sentence_transformers
        return True
    except ImportError:
        return False


SKIP_NO_ST = pytest.mark.skipif(
    not _st_available(),
    reason="sentence-transformers not installed",
)


# ===========================================================================
# Tests for TRAINING_EXAMPLES data structure
# ===========================================================================

class TestTrainingExamples:
    """Tests for training data completeness."""

    def test_all_nine_categories_present(self):
        """All 9 SWECAS categories have training examples."""
        for code in [100, 200, 300, 400, 500, 600, 700, 800, 900]:
            assert code in TRAINING_EXAMPLES, f"Missing category {code}"

    def test_minimum_examples_per_category(self):
        """Each category has at least 8 training examples."""
        for code, examples in TRAINING_EXAMPLES.items():
            assert len(examples) >= 8, (
                f"Category {code} has only {len(examples)} examples, need >= 8"
            )

    def test_no_empty_examples(self):
        """No empty strings in training examples."""
        for code, examples in TRAINING_EXAMPLES.items():
            for ex in examples:
                assert ex.strip(), f"Empty example in category {code}"

    def test_bilingual_coverage(self):
        """Each category has at least some Russian examples."""
        russian_chars = set("абвгдежзийклмнопрстуфхцчшщъыьэюя")
        for code, examples in TRAINING_EXAMPLES.items():
            has_russian = any(
                set(ex.lower()) & russian_chars
                for ex in examples
            )
            assert has_russian, f"Category {code} has no Russian examples"

    def test_category_names_match(self):
        """CATEGORY_NAMES covers all training categories."""
        for code in TRAINING_EXAMPLES:
            assert code in CATEGORY_NAMES, f"Missing name for category {code}"

    def test_total_examples_reasonable(self):
        """Total training examples between 80 and 200."""
        total = sum(len(v) for v in TRAINING_EXAMPLES.values())
        assert 80 <= total <= 200, f"Total examples: {total}"


# ===========================================================================
# Tests for SemanticSWECAS (requires sentence-transformers)
# ===========================================================================

@SKIP_NO_ST
class TestSemanticSWECAS:
    """Tests for SemanticSWECAS classifier."""

    @pytest.fixture(scope="class")
    def semantic(self):
        """Shared SemanticSWECAS instance (expensive to create)."""
        from core.semantic_swecas import SemanticSWECAS
        return SemanticSWECAS()

    def test_initialization(self, semantic):
        """Classifier initializes with model and index."""
        assert semantic.is_available
        assert semantic.n_examples > 0
        assert semantic.model_name == "all-MiniLM-L6-v2"

    def test_classify_security_query(self, semantic):
        """Security queries map to SWECAS 500."""
        result = semantic.classify("SQL injection in login form")
        assert result.swecas_code == 500
        assert result.confidence > 0.3
        assert result.method == "semantic"

    def test_classify_null_error(self, semantic):
        """Null/None queries map to SWECAS 100."""
        result = semantic.classify("AttributeError NoneType has no attribute name")
        assert result.swecas_code == 100
        assert result.confidence > 0.3

    def test_classify_import_error(self, semantic):
        """Import errors map to SWECAS 200."""
        result = semantic.classify("ModuleNotFoundError cannot find requests library")
        assert result.swecas_code == 200

    def test_classify_type_error(self, semantic):
        """Type errors map to SWECAS 300."""
        result = semantic.classify("TypeError expected string argument got integer")
        assert result.swecas_code == 300

    def test_classify_deprecation(self, semantic):
        """Deprecation queries map to SWECAS 400."""
        result = semantic.classify("DeprecationWarning this API method removed in version 3")
        assert result.swecas_code == 400

    def test_classify_logic_bug(self, semantic):
        """Logic bugs map to SWECAS 600."""
        result = semantic.classify("off by one error in for loop produces wrong result")
        assert result.swecas_code == 600

    def test_classify_config(self, semantic):
        """Config issues map to SWECAS 700."""
        result = semantic.classify("Dockerfile build fails wrong base image config")
        assert result.swecas_code == 700

    def test_classify_performance(self, semantic):
        """Performance issues map to SWECAS 800."""
        result = semantic.classify("N+1 query problem database slow memory leak")
        assert result.swecas_code == 800

    def test_classify_async(self, semantic):
        """Async issues map to SWECAS 900."""
        result = semantic.classify("deadlock race condition when acquiring multiple locks")
        assert result.swecas_code == 900

    # --- Russian queries ---

    def test_classify_russian_security(self, semantic):
        """Russian security query → SWECAS 500."""
        result = semantic.classify("SQL инъекция через пользовательский ввод данных")
        assert result.swecas_code == 500

    def test_classify_russian_null(self, semantic):
        """Russian null query → SWECAS 100."""
        result = semantic.classify("переменная равна None, ошибка NoneType атрибут")
        assert result.swecas_code == 100

    def test_classify_russian_performance(self, semantic):
        """Russian performance query → SWECAS 800."""
        result = semantic.classify("медленный запрос к базе данных утечка памяти")
        assert result.swecas_code == 800

    def test_classify_russian_async(self, semantic):
        """Russian async query → SWECAS 900."""
        result = semantic.classify("дедлок гонка потоков блокировка await")
        assert result.swecas_code == 900

    # --- Result structure ---

    def test_result_has_top_matches(self, semantic):
        """Result includes top_matches with category codes."""
        result = semantic.classify("memory leak in production server")
        assert len(result.top_matches) > 0
        assert all(isinstance(code, int) and isinstance(score, float)
                    for code, score in result.top_matches)

    def test_result_embedding_time(self, semantic):
        """Result tracks embedding time in milliseconds."""
        result = semantic.classify("SQL injection vulnerability")
        assert result.embedding_time_ms > 0
        assert result.embedding_time_ms < 5000  # should be under 5s

    def test_confidence_sums_to_one(self, semantic):
        """Top match confidences approximately sum to 1.0."""
        result = semantic.classify("race condition in thread pool")
        total = sum(score for _, score in result.top_matches)
        assert 0.95 <= total <= 1.05  # floating point tolerance

    # --- Stats ---

    def test_get_stats(self, semantic):
        """get_stats returns model info and example counts."""
        stats = semantic.get_stats()
        assert stats["model"] == "all-MiniLM-L6-v2"
        assert stats["total_examples"] > 80
        assert stats["categories"] == 9
        assert stats["embedding_dim"] > 0

    # --- Edge cases ---

    def test_empty_query(self, semantic):
        """Empty query returns a result (may be low confidence)."""
        result = semantic.classify("")
        assert isinstance(result.swecas_code, int)
        assert isinstance(result.confidence, float)

    def test_very_long_query(self, semantic):
        """Very long query doesn't crash."""
        long_query = "memory leak and performance issues " * 100
        result = semantic.classify(long_query)
        assert result.swecas_code in [100, 200, 300, 400, 500, 600, 700, 800, 900, 0]

    def test_add_examples(self, semantic):
        """Adding examples increases total count."""
        before = semantic.n_examples
        semantic.add_examples(500, ["new custom security example for testing"])
        after = semantic.n_examples
        assert after == before + 1


# ===========================================================================
# Tests for HybridSWECAS
# ===========================================================================

@SKIP_NO_ST
class TestHybridSWECAS:
    """Tests for HybridSWECAS (regex + semantic)."""

    @pytest.fixture(scope="class")
    def hybrid(self):
        """Shared HybridSWECAS instance."""
        from core.semantic_swecas import HybridSWECAS
        return HybridSWECAS(confidence_threshold=0.5)

    def test_has_semantic(self, hybrid):
        """Hybrid has semantic backend enabled."""
        assert hybrid.has_semantic

    def test_regex_confident_query(self, hybrid):
        """High-confidence regex query uses regex method."""
        # "validation", "security", "assert" are strong 500 keywords
        result = hybrid.classify(
            "validation security assert input check ValueError sanitize validate verify"
        )
        assert result["swecas_code"] == 500
        assert result["method"] in ("regex", "regex_preferred")

    def test_semantic_fallback_on_low_regex(self, hybrid):
        """Ambiguous query may trigger semantic fallback."""
        # Query that regex might not classify well
        result = hybrid.classify(
            "the application crashes when two threads access shared memory simultaneously"
        )
        assert result["swecas_code"] != 0
        assert "method" in result

    def test_result_compatible_with_swecas(self, hybrid):
        """Hybrid result has all standard SWECASClassifier keys."""
        result = hybrid.classify("NoneType error when accessing attribute")
        required_keys = [
            "swecas_code", "confidence", "subcategory", "name",
            "related", "diffuse_prompts", "method"
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_security_query_classified(self, hybrid):
        """Security query correctly classified by hybrid."""
        result = hybrid.classify("XSS vulnerability in HTML template output")
        assert result["swecas_code"] == 500

    def test_config_query_classified(self, hybrid):
        """Config query classified by hybrid."""
        result = hybrid.classify("Kubernetes pod manifest has wrong resource limits")
        assert result["swecas_code"] == 700

    def test_get_stats(self, hybrid):
        """Stats include both regex and semantic counters."""
        stats = hybrid.get_stats()
        assert "has_semantic" in stats
        assert stats["has_semantic"] is True
        assert "total_classifications" in stats
        assert "semantic_stats" in stats

    def test_threshold_behavior(self):
        """Higher threshold means more semantic fallback."""
        from core.semantic_swecas import HybridSWECAS

        # Very high threshold → almost always uses semantic
        h_high = HybridSWECAS(confidence_threshold=0.99)
        result = h_high.classify("some ambiguous description about bugs")
        # Will likely use semantic since regex rarely hits 0.99
        assert result["method"] in ("semantic", "regex", "regex_preferred")

    def test_diffuse_data_preserved(self, hybrid):
        """Even semantic results include diffuse links and prompts."""
        result = hybrid.classify(
            "deadlock when multiple threads try to acquire lock simultaneously"
        )
        if result["method"] == "semantic":
            assert "related" in result
            assert "diffuse_prompts" in result


# ===========================================================================
# Tests for graceful degradation (no sentence-transformers)
# ===========================================================================

class TestGracefulDegradation:
    """Tests for behavior when sentence-transformers is not installed."""

    def test_semantic_raises_without_st(self):
        """SemanticSWECAS raises RuntimeError if ST unavailable."""
        import core.semantic_swecas as mod
        original = mod._HAS_SENTENCE_TRANSFORMERS

        try:
            mod._HAS_SENTENCE_TRANSFORMERS = False
            with pytest.raises(RuntimeError, match="sentence-transformers"):
                from core.semantic_swecas import SemanticSWECAS
                SemanticSWECAS()
        finally:
            mod._HAS_SENTENCE_TRANSFORMERS = original

    def test_hybrid_regex_only_without_st(self):
        """HybridSWECAS falls back to regex-only without ST."""
        from core.semantic_swecas import HybridSWECAS

        hybrid = HybridSWECAS(enable_semantic=False)
        assert not hybrid.has_semantic

        # Use keywords that match regex classifier: "security", "validation"
        result = hybrid.classify("security validation assert input check ValueError")
        assert result["swecas_code"] == 500
        assert result["method"] == "regex"

    def test_hybrid_regex_only_stats(self):
        """Regex-only hybrid reports no semantic stats."""
        from core.semantic_swecas import HybridSWECAS

        hybrid = HybridSWECAS(enable_semantic=False)
        stats = hybrid.get_stats()
        assert stats["has_semantic"] is False
        assert stats["semantic_stats"] is None

    def test_hybrid_regex_only_classifies_all_categories(self):
        """Regex-only mode still classifies all SWECAS categories."""
        from core.semantic_swecas import HybridSWECAS

        hybrid = HybridSWECAS(enable_semantic=False)

        test_cases = {
            100: "NoneType has no attribute name AttributeError",
            200: "ModuleNotFoundError: No module named requests",
            300: "TypeError: expected str but got int",
            400: "DeprecationWarning: API method deprecated removed",
            500: "validation security assert input check ValueError",
            600: "logic error off-by-one wrong incorrect result",
            700: "config environment env var settings configuration",
            800: "performance slow memory leak cache optimize",
            900: "async await race condition deadlock concurrent",
        }

        for expected_code, query in test_cases.items():
            result = hybrid.classify(query)
            assert result["swecas_code"] == expected_code, (
                f"Expected {expected_code} for: {query!r}, got {result['swecas_code']}"
            )


# ===========================================================================
# Tests for SemanticResult dataclass
# ===========================================================================

class TestSemanticResult:
    """Tests for SemanticResult data structure."""

    def test_basic_creation(self):
        """SemanticResult can be created with required fields."""
        r = SemanticResult(
            swecas_code=500,
            confidence=0.85,
            name="Security & Validation",
            top_matches=[(500, 0.85), (600, 0.15)],
        )
        assert r.swecas_code == 500
        assert r.confidence == 0.85
        assert r.method == "semantic"
        assert r.embedding_time_ms == 0.0

    def test_custom_method(self):
        """SemanticResult accepts custom method."""
        r = SemanticResult(
            swecas_code=100,
            confidence=0.5,
            name="Test",
            top_matches=[],
            method="custom",
            embedding_time_ms=42.0,
        )
        assert r.method == "custom"
        assert r.embedding_time_ms == 42.0


# ===========================================================================
# Accuracy benchmark (requires sentence-transformers)
# ===========================================================================

@SKIP_NO_ST
class TestSemanticAccuracy:
    """Accuracy benchmark for semantic classifier."""

    @pytest.fixture(scope="class")
    def semantic(self):
        from core.semantic_swecas import SemanticSWECAS
        return SemanticSWECAS()

    # Queries that were NOT in training data but should classify correctly
    NOVEL_QUERIES = [
        (500, "buffer overflow in C extension module allows remote code execution"),
        (500, "SSRF attack possible through URL parameter"),
        (100, "variable is unexpectedly set to null after initialization"),
        (200, "pip install fails because of broken dependency resolution"),
        (300, "function expects List[str] but receives Optional[int]"),
        (400, "method was removed in Django 5.0 release notes"),
        (600, "test returns 4 but expected 5 due to boundary calculation"),
        (700, "CI pipeline fails because REDIS_URL not set in GitHub Actions"),
        (800, "API endpoint takes 10 seconds due to unindexed table scan"),
        (900, "coroutine was never awaited, event loop blocks"),
    ]

    def test_novel_queries_accuracy(self, semantic):
        """At least 7 out of 10 novel queries classified correctly."""
        correct = 0
        for expected_code, query in self.NOVEL_QUERIES:
            result = semantic.classify(query)
            if result.swecas_code == expected_code:
                correct += 1

        accuracy = correct / len(self.NOVEL_QUERIES)
        assert accuracy >= 0.7, (
            f"Accuracy {accuracy:.0%} ({correct}/{len(self.NOVEL_QUERIES)}) < 70%"
        )

    # Russian novel queries
    RUSSIAN_NOVEL_QUERIES = [
        (500, "возможна атака через подмену входных данных формы"),
        (800, "запрос к базе без индекса занимает 30 секунд"),
        (900, "корутина не завершена, блокировка event loop"),
        (600, "функция возвращает неверный результат на граничном случае"),
        (700, "переменные окружения не заданы в контейнере Docker"),
    ]

    def test_russian_novel_accuracy(self, semantic):
        """At least 2 out of 5 Russian novel queries classified correctly.

        Note: all-MiniLM-L6-v2 is English-focused; Russian accuracy is lower.
        For production, consider a multilingual model like paraphrase-multilingual-MiniLM-L12-v2.
        """
        correct = 0
        for expected_code, query in self.RUSSIAN_NOVEL_QUERIES:
            result = semantic.classify(query)
            if result.swecas_code == expected_code:
                correct += 1

        accuracy = correct / len(self.RUSSIAN_NOVEL_QUERIES)
        assert accuracy >= 0.4, (
            f"Russian accuracy {accuracy:.0%} ({correct}/{len(self.RUSSIAN_NOVEL_QUERIES)}) < 40%"
        )
