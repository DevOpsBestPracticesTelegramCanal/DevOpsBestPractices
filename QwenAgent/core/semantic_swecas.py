# -*- coding: utf-8 -*-
"""
Semantic SWECAS Classifier — embedding-based classification for SWECAS V2.

Replaces/complements the keyword-based SWECASClassifier with vector similarity.
Uses sentence-transformers (all-MiniLM-L6-v2, 22 MB) for embeddings,
numpy cosine similarity for matching (~100 training examples, no FAISS needed).

HybridSWECAS combines both approaches:
  1. Try regex (fast, 0-cost)
  2. If confidence < threshold → semantic fallback

Graceful degradation: if sentence-transformers is not installed, the semantic
classifier silently disables itself and HybridSWECAS uses regex-only mode.

Usage:
    from core.semantic_swecas import HybridSWECAS

    hybrid = HybridSWECAS()  # auto-detects sentence-transformers
    result = hybrid.classify("SQL injection in user login")
    # result['swecas_code'] == 500, result['method'] == 'semantic'
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Lazy import for sentence-transformers
_HAS_SENTENCE_TRANSFORMERS = None
_SentenceTransformer = None


def _check_sentence_transformers() -> bool:
    """Check if sentence-transformers is available (cached)."""
    global _HAS_SENTENCE_TRANSFORMERS, _SentenceTransformer
    if _HAS_SENTENCE_TRANSFORMERS is None:
        try:
            from sentence_transformers import SentenceTransformer
            _SentenceTransformer = SentenceTransformer
            _HAS_SENTENCE_TRANSFORMERS = True
            logger.info("[SemanticSWECAS] sentence-transformers available")
        except ImportError:
            _HAS_SENTENCE_TRANSFORMERS = False
            logger.info("[SemanticSWECAS] sentence-transformers not installed — disabled")
    return _HAS_SENTENCE_TRANSFORMERS


# ---------------------------------------------------------------------------
# Training examples per SWECAS category
# ---------------------------------------------------------------------------

TRAINING_EXAMPLES: Dict[int, List[str]] = {
    100: [
        # English
        "NoneType has no attribute",
        "AttributeError: None object",
        "variable is None unexpectedly",
        "null pointer exception",
        "missing value error, attribute not set",
        "optional field returns None when accessed",
        "uninitialized variable causes crash",
        "accessing attribute of null reference",
        # Russian
        "ошибка NoneType нет атрибута",
        "переменная равна None, неожиданно",
        "нулевой указатель, пустое значение",
    ],
    200: [
        # English
        "ModuleNotFoundError: No module named 'requests'",
        "ImportError: cannot import name from module",
        "circular import between modules A and B",
        "dependency not found, pip install required",
        "failed to import library after upgrade",
        "relative import error in package structure",
        "missing module after migration to new version",
        "package not installed in virtual environment",
        # Russian
        "модуль не найден, ошибка импорта",
        "циклический импорт между модулями",
        "зависимость не установлена в окружении",
    ],
    300: [
        # English
        "TypeError: expected str but got int",
        "type mismatch in function signature",
        "incompatible return type annotation",
        "generic type parameter violation",
        "isinstance check fails for subclass",
        "overloaded method wrong signature dispatch",
        "cast from int to str raises type error",
        "annotation mismatch between caller and callee",
        # Russian
        "ошибка типа: ожидалась строка, получено число",
        "несовместимый тип возвращаемого значения",
        "аннотация типа не соответствует фактическому",
    ],
    400: [
        # English
        "DeprecationWarning: method removed in v3.0",
        "API breaking change after library upgrade",
        "deprecated function call use new_method instead",
        "backward compatibility issue with old version",
        "legacy code uses obsolete interface",
        "version mismatch between client and server API",
        "removed in latest release use alternative",
        "migration guide for deprecated endpoint",
        # Russian
        "устаревший API метод удалён в новой версии",
        "обратная совместимость нарушена обновлением",
        "устаревшая функция заменена новым интерфейсом",
    ],
    500: [
        # English
        "SQL injection vulnerability in user input",
        "XSS attack through unsanitized HTML output",
        "authentication bypass via token manipulation",
        "insecure deserialization of user data",
        "path traversal exploit in file upload",
        "missing input validation allows buffer overflow",
        "CSRF protection not implemented on form",
        "hardcoded credentials in configuration file",
        "sensitive data exposure through API response",
        "command injection via shell execution",
        "ValueError: invalid input not sanitized properly",
        "assertion should be explicit validation raise",
        # Russian
        "SQL инъекция через пользовательский ввод",
        "XSS атака через нефильтрованный вывод",
        "обход аутентификации через токен",
        "уязвимость безопасности в обработке данных",
        "отсутствует проверка валидации ввода",
    ],
    600: [
        # English
        "off-by-one error in loop boundary",
        "wrong branch taken in conditional logic",
        "incorrect algorithm produces wrong result",
        "logic error in predicate evaluation",
        "bug: function returns unexpected value",
        "broken control flow after refactoring",
        "infinite loop when input is empty list",
        "algorithm fails on edge case with negative numbers",
        "incorrect result for boundary condition",
        "doesn't work when array has duplicate elements",
        # Russian
        "ошибка на единицу в границе цикла",
        "неверная ветка условия, баг в логике",
        "алгоритм даёт неправильный результат",
        "некорректное поведение при граничных условиях",
    ],
    700: [
        # English
        "environment variable not set in production",
        "configuration file missing required field",
        "Dockerfile build fails due to wrong base image",
        "Kubernetes manifest has incorrect resource limits",
        "Nginx config syntax error causes 502",
        "Terraform plan fails with provider mismatch",
        "pytest conftest fixture not found",
        "working directory path incorrect in CI",
        "ENV variable override not working in Docker",
        "settings.py has wrong database URL for staging",
        # Russian
        "переменная окружения не установлена",
        "конфигурация Docker неверная, ошибка сборки",
        "Kubernetes манифест с неправильными лимитами",
        "настройки не совпадают между dev и prod",
    ],
    800: [
        # English
        "N+1 query problem causing slow page load",
        "memory leak in long-running worker process",
        "cache miss rate too high needs optimization",
        "database query takes 30 seconds without index",
        "CPU bottleneck in image processing pipeline",
        "resource exhaustion under high concurrency",
        "slow API response time needs profiling",
        "optimize batch processing to reduce memory usage",
        "performance regression after adding logging",
        "garbage collection pauses causing latency spikes",
        # Russian
        "N+1 запрос замедляет загрузку страницы",
        "утечка памяти в длительном процессе",
        "медленный запрос к базе данных без индекса",
        "оптимизация производительности кэширования",
    ],
    900: [
        # English
        "race condition between concurrent threads",
        "deadlock when acquiring multiple locks",
        "missing await on async coroutine call",
        "thread synchronization issue with shared state",
        "asyncio event loop already running error",
        "task cancelled before completion in async pipeline",
        "I/O blocking in async handler reduces throughput",
        "semaphore not released causing resource starvation",
        "concurrent writes corrupt shared data structure",
        "coroutine never awaited warning in production",
        # Russian
        "состояние гонки между потоками",
        "дедлок при захвате нескольких блокировок",
        "пропущен await на асинхронном вызове",
        "проблема синхронизации потоков",
    ],
}

# Category names (mirror of SWECASClassifier.CATEGORY_NAMES)
CATEGORY_NAMES: Dict[int, str] = {
    100: "Null/None & Value Errors",
    200: "Import & Module / Dependency",
    300: "Type & Interface",
    400: "API Usage & Deprecation",
    500: "Security & Validation",
    600: "Logic & Control Flow",
    700: "Config & Environment",
    800: "Performance & Resource",
    900: "Async, Concurrency & I/O",
}


# ---------------------------------------------------------------------------
# SemanticSWECAS — embedding-based classifier
# ---------------------------------------------------------------------------

@dataclass
class SemanticResult:
    """Result of semantic SWECAS classification."""
    swecas_code: int
    confidence: float
    name: str
    top_matches: List[Tuple[int, float]]  # [(code, similarity), ...]
    method: str = "semantic"
    embedding_time_ms: float = 0.0


class SemanticSWECAS:
    """
    Embedding-based SWECAS classifier using sentence-transformers.

    Uses all-MiniLM-L6-v2 (22 MB) for fast, high-quality embeddings.
    Cosine similarity with numpy for small training set (~100 examples).

    Graceful: raises RuntimeError if sentence-transformers unavailable.
    Use HybridSWECAS for automatic fallback to regex-only mode.
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        training_examples: Optional[Dict[int, List[str]]] = None,
    ):
        if not _check_sentence_transformers():
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )

        self._model_name = model_name
        self._examples = training_examples or TRAINING_EXAMPLES
        self._model = None
        self._embeddings = None  # numpy array (N, dim)
        self._labels: List[int] = []  # category code per training example
        self._texts: List[str] = []

        self._build_index()

    @property
    def is_available(self) -> bool:
        return self._model is not None and self._embeddings is not None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def n_examples(self) -> int:
        return len(self._labels)

    def _build_index(self) -> None:
        """Load model and encode all training examples."""
        import numpy as np

        t0 = time.time()
        self._model = _SentenceTransformer(self._model_name)

        # Flatten examples
        self._texts = []
        self._labels = []
        for code, examples in sorted(self._examples.items()):
            for text in examples:
                self._texts.append(text)
                self._labels.append(code)

        # Encode all at once (batch)
        self._embeddings = self._model.encode(
            self._texts,
            show_progress_bar=False,
            normalize_embeddings=True,  # for cosine similarity via dot product
        )
        # Ensure float32 numpy array
        self._embeddings = np.asarray(self._embeddings, dtype=np.float32)

        elapsed = time.time() - t0
        logger.info(
            "[SemanticSWECAS] Index built: %d examples, dim=%d, %.1fs",
            len(self._labels),
            self._embeddings.shape[1],
            elapsed,
        )

    def classify(
        self,
        query: str,
        top_k: int = 5,
    ) -> SemanticResult:
        """
        Classify a query by cosine similarity to training examples.

        Uses top-k weighted voting: each of the k nearest examples
        casts a vote weighted by its similarity score.

        Args:
            query: text to classify (bug description, task, etc.)
            top_k: number of nearest neighbors for voting

        Returns:
            SemanticResult with swecas_code, confidence, top_matches
        """
        import numpy as np

        t0 = time.time()

        # Encode query
        q_emb = self._model.encode(
            [query],
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        q_emb = np.asarray(q_emb, dtype=np.float32)

        # Cosine similarity (dot product since embeddings are normalized)
        similarities = (self._embeddings @ q_emb.T).squeeze()

        # Top-k indices
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        # Weighted voting
        votes: Dict[int, float] = {}
        for idx in top_indices:
            code = self._labels[idx]
            sim = float(similarities[idx])
            votes[code] = votes.get(code, 0.0) + max(sim, 0.0)

        if not votes:
            return SemanticResult(
                swecas_code=0,
                confidence=0.0,
                name="Unclassified",
                top_matches=[],
                embedding_time_ms=(time.time() - t0) * 1000,
            )

        # Best category by total vote weight
        best_code = max(votes, key=votes.get)
        total_weight = sum(votes.values())
        confidence = votes[best_code] / total_weight if total_weight > 0 else 0.0

        # Top matches for debugging
        sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
        top_matches = [(code, round(w / total_weight, 4)) for code, w in sorted_votes]

        elapsed_ms = (time.time() - t0) * 1000

        return SemanticResult(
            swecas_code=best_code,
            confidence=round(confidence, 4),
            name=CATEGORY_NAMES.get(best_code, "Unknown"),
            top_matches=top_matches,
            embedding_time_ms=round(elapsed_ms, 2),
        )

    def add_examples(self, code: int, examples: List[str]) -> None:
        """Add new training examples and rebuild index."""
        if code not in self._examples:
            self._examples[code] = []
        self._examples[code].extend(examples)
        self._build_index()

    def get_stats(self) -> Dict[str, Any]:
        """Return stats about the semantic classifier."""
        dist = {}
        for label in self._labels:
            dist[label] = dist.get(label, 0) + 1
        return {
            "model": self._model_name,
            "total_examples": len(self._labels),
            "categories": len(dist),
            "examples_per_category": dist,
            "embedding_dim": self._embeddings.shape[1] if self._embeddings is not None else 0,
        }


# ---------------------------------------------------------------------------
# HybridSWECAS — regex + semantic
# ---------------------------------------------------------------------------

class HybridSWECAS:
    """
    Hybrid classifier: tries regex first, falls back to semantic.

    If sentence-transformers is not installed, operates in regex-only mode.
    Thread-safe for classification (model.encode is thread-safe in ST).

    Args:
        confidence_threshold: minimum regex confidence to skip semantic.
            Default 0.5 — if regex confidence < 0.5, semantic is consulted.
        enable_semantic: explicitly enable/disable semantic. None = auto-detect.
        model_name: sentence-transformers model name.
        training_examples: custom training examples dict.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.5,
        enable_semantic: Optional[bool] = None,
        model_name: str = SemanticSWECAS.DEFAULT_MODEL,
        training_examples: Optional[Dict[int, List[str]]] = None,
    ):
        from .swecas_classifier import SWECASClassifier

        self._regex = SWECASClassifier()
        self._threshold = confidence_threshold
        self._semantic: Optional[SemanticSWECAS] = None

        # Statistics
        self._regex_only_count = 0
        self._semantic_used_count = 0
        self._semantic_override_count = 0

        # Initialize semantic if available
        should_enable = enable_semantic if enable_semantic is not None else _check_sentence_transformers()
        if should_enable:
            try:
                self._semantic = SemanticSWECAS(
                    model_name=model_name,
                    training_examples=training_examples,
                )
                logger.info("[HybridSWECAS] Semantic classifier enabled")
            except Exception as e:
                logger.warning("[HybridSWECAS] Semantic init failed: %s", e)
                self._semantic = None
        else:
            logger.info("[HybridSWECAS] Semantic disabled, regex-only mode")

    @property
    def has_semantic(self) -> bool:
        """Whether semantic classifier is available."""
        return self._semantic is not None

    def classify(
        self,
        description: str,
        file_content: str = None,
    ) -> Dict[str, Any]:
        """
        Classify using hybrid approach.

        1. Run regex classifier
        2. If regex confidence < threshold AND semantic available → run semantic
        3. Return result with higher confidence (and track method used)

        Returns dict compatible with SWECASClassifier.classify() output,
        plus extra keys: 'method', 'semantic_result' (if used).
        """
        # Step 1: regex classification
        regex_result = self._regex.classify(description, file_content)

        # If no semantic → return regex as-is
        if self._semantic is None:
            regex_result["method"] = "regex"
            self._regex_only_count += 1
            return regex_result

        # Step 2: check if semantic fallback needed
        regex_confidence = regex_result.get("confidence", 0.0)
        regex_code = regex_result.get("swecas_code", 0)

        if regex_confidence >= self._threshold and regex_code != 0:
            # Regex is confident enough
            regex_result["method"] = "regex"
            self._regex_only_count += 1
            return regex_result

        # Step 3: semantic classification
        self._semantic_used_count += 1
        sem_result = self._semantic.classify(description)

        # If regex found nothing (code=0) and semantic found something → use semantic
        if regex_code == 0 and sem_result.swecas_code != 0:
            self._semantic_override_count += 1
            return self._build_hybrid_result(sem_result, regex_result, "semantic")

        # If regex has low confidence → compare
        if sem_result.confidence > regex_confidence and sem_result.swecas_code != 0:
            self._semantic_override_count += 1
            return self._build_hybrid_result(sem_result, regex_result, "semantic")

        # Regex still wins (or semantic also has low confidence)
        regex_result["method"] = "regex_preferred"
        regex_result["semantic_result"] = {
            "swecas_code": sem_result.swecas_code,
            "confidence": sem_result.confidence,
            "name": sem_result.name,
        }
        return regex_result

    def _build_hybrid_result(
        self,
        sem: SemanticResult,
        regex_result: Dict[str, Any],
        method: str,
    ) -> Dict[str, Any]:
        """Build result dict from semantic classification, enriched with regex data."""
        from .swecas_classifier import SWECASClassifier

        # Use semantic classification but keep regex extras (diffuse, templates)
        result = {
            "swecas_code": sem.swecas_code,
            "confidence": sem.confidence,
            "subcategory": sem.swecas_code,
            "name": sem.name,
            "pattern_description": f"Semantic match (top: {sem.top_matches[:3]})",
            "fix_hint": "",
            "related": self._regex.get_diffuse_links(sem.swecas_code),
            "diffuse_insights": self._regex._build_diffuse_insights(sem.swecas_code),
            "diffuse_prompts": self._regex.get_diffuse_prompts(sem.swecas_code),
            "method": method,
            "semantic_result": {
                "swecas_code": sem.swecas_code,
                "confidence": sem.confidence,
                "name": sem.name,
                "top_matches": sem.top_matches,
                "embedding_time_ms": sem.embedding_time_ms,
            },
            "regex_result": {
                "swecas_code": regex_result.get("swecas_code", 0),
                "confidence": regex_result.get("confidence", 0.0),
            },
        }

        # Try to get fix_hint from regex for the semantic-chosen category
        fix_template = self._regex.get_fix_template(sem.swecas_code)
        if fix_template:
            result["fix_hint"] = f"Template available for SWECAS-{sem.swecas_code}"

        return result

    def get_stats(self) -> Dict[str, Any]:
        """Return classification statistics."""
        total = self._regex_only_count + self._semantic_used_count
        return {
            "has_semantic": self.has_semantic,
            "total_classifications": total,
            "regex_only": self._regex_only_count,
            "semantic_consulted": self._semantic_used_count,
            "semantic_overrides": self._semantic_override_count,
            "semantic_override_rate": (
                round(self._semantic_override_count / max(total, 1), 4)
            ),
            "confidence_threshold": self._threshold,
            "semantic_stats": self._semantic.get_stats() if self._semantic else None,
        }
