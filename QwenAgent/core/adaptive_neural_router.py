# -*- coding: utf-8 -*-
"""
Adaptive Neural Router (ANR) — embedding-based tool intent classifier.

Replaces the keyword-based IntentClassifier (TIER 1) with vector similarity.
Uses the same sentence-transformers model as SemanticSWECAS (all-MiniLM-L6-v2)
so there is no extra memory cost when both are loaded.

Architecture:
  TIER 0: PatternRouter  — 71 regex, <1ms, confidence 0.95
  TIER 1: ANR            — embeddings, ~20ms, confidence 0.6-0.9
  TIER 2: LLM fallback

ANR classifies the *tool intent* (read, grep, bash, etc.) and then delegates
parameter extraction to per-tool regex parsers.  It also learns from actual
usage: every routed query is stored in a SQLite DB so that retrain_from_history()
can incorporate real-world examples.

Graceful degradation: if sentence-transformers is not installed the module
exports a disabled singleton and HybridRouter falls back to IntentClassifier.

Usage:
    from core.adaptive_neural_router import AdaptiveNeuralRouter
    anr = AdaptiveNeuralRouter()
    result = anr.classify("show me the contents of agent.py")
    # result.tool == 'read', result.confidence ~ 0.8
"""

import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import for sentence-transformers (reuse semantic_swecas pattern)
# ---------------------------------------------------------------------------

_HAS_ST: Optional[bool] = None
_SentenceTransformer = None


def _check_st() -> bool:
    """Check if sentence-transformers is available (cached)."""
    global _HAS_ST, _SentenceTransformer
    if _HAS_ST is None:
        try:
            from sentence_transformers import SentenceTransformer
            _SentenceTransformer = SentenceTransformer
            _HAS_ST = True
        except ImportError:
            _HAS_ST = False
            logger.info("[ANR] sentence-transformers not installed — disabled")
    return _HAS_ST


# ---------------------------------------------------------------------------
# Training data: ~300 bilingual examples across 9 tool categories
# ---------------------------------------------------------------------------

TRAINING_DATA: Dict[str, List[str]] = {
    "read": [
        # English — natural variants
        "read core/tools.py",
        "show me the file agent.py",
        "display contents of router.py",
        "open the config file",
        "what's in file.py",
        "let me see main.py",
        "can you show server.py",
        "print the file requirements.txt",
        "view the source of utils.py",
        "read the readme",
        "show me what's inside config.json",
        "output the contents of .env",
        "I want to read orchestrator.py",
        "cat the log file",
        "look at the contents of Dockerfile",
        "show setup.py please",
        "read lines 10-50 of agent.py",
        "what does the file contain",
        "show this file to me",
        "display the module code",
        # Russian
        "прочитай файл tools.py",
        "покажи файл agent.py",
        "открой конфиг",
        "что в файле router.py",
        "покажи содержимое server.py",
        "прочитай мне этот файл",
        "выведи файл requirements.txt",
        "открой исходный код agent.py",
        "покажи что внутри config.json",
        "давай посмотрим main.py",
    ],
    "grep": [
        # English
        "search for 'def route' in router.py",
        "grep TODO in all files",
        "find all occurrences of import os",
        "search for class Agent",
        "look for error handling patterns",
        "where is the function process_stream defined",
        "find references to PatternRouter",
        "search the codebase for timeout",
        "look for all usages of confidence",
        "find where route_result is used",
        "grep for logging.error",
        "search for TODO comments",
        "where is __init__ defined for Agent",
        "find all print statements",
        "search in the test files for mock",
        "look for database connection code",
        "find the word deprecated in source",
        # Russian
        "найди 'def route' в router.py",
        "поиск TODO во всех файлах",
        "где определена функция process_stream",
        "найди все вхождения import os",
        "поищи в коде timeout",
        "где используется PatternRouter",
        "найди ошибки в логах",
        "поиск по слову deprecated",
        "найди все print в коде",
        "ищи класс Agent в проекте",
        "где определён метод classify",
        "поиск строки connection в исходниках",
        "покажи все места где используется cache",
        "найди определение RouteResult",
        "где вызывается route метод",
    ],
    "bash": [
        # English — general
        "run pip install requests",
        "execute python test.py",
        "run the tests",
        "install dependencies",
        "run pytest",
        "execute make build",
        "start the server",
        "run the linter",
        "check python version",
        "run mypy on the project",
        "execute the migration script",
        "compile the project",
        "run docker build",
        "restart the service",
        "run npm install",
        "kill the process on port 8080",
        "run black --check .",
        # Git commands
        "git status",
        "git log --oneline -10",
        "git diff HEAD",
        "commit the changes",
        "push to origin",
        "create a new branch feature/anr",
        "git stash",
        "show recent commits",
        "check git status",
        # Russian
        "запусти тесты",
        "выполни pip install",
        "запусти сервер",
        "установи зависимости",
        "запусти pytest",
        "выполни скрипт миграции",
        "собери проект",
        "запусти линтер",
        "проверь версию python",
        "запусти docker build",
        "перезапусти сервис",
        "покажи git status",
        "сделай git commit",
        "запушь изменения",
    ],
    "ls": [
        # English
        "list files in core/",
        "show directory contents",
        "what files are here",
        "list the current directory",
        "show me the project structure",
        "what's in the tests folder",
        "dir core/generation",
        "show files in this directory",
        "list all files",
        "what's in the root directory",
        "ls the project",
        "show the folder structure",
        "list contents of code_validator/",
        "what files exist in core/utils",
        "show me the directory listing",
        # Russian
        "покажи файлы в core/",
        "список файлов в директории",
        "что в папке tests",
        "покажи структуру проекта",
        "какие файлы в текущей директории",
        "список файлов в корне",
        "покажи содержимое папки",
        "что лежит в core/generation",
        "перечисли файлы",
        "покажи дерево проекта",
    ],
    "glob": [
        # English
        "find all Python files in the project",
        "find all .py files",
        "find all test files",
        "find files matching *.json",
        "show all TypeScript files",
        "list all markdown files",
        "find all config files",
        "find files with .yaml extension",
        "show all .txt files recursively",
        "find all files named __init__.py",
        "locate all requirements files",
        "find all Dockerfiles",
        "show .env files",
        "find all shell scripts",
        "glob for *.toml files",
        # Russian
        "найди все Python файлы в проекте",
        "найди все файлы .py",
        "найди все тестовые файлы",
        "покажи все json файлы",
        "найди файлы с расширением .yaml",
        "покажи все markdown файлы",
        "найди все конфиги",
        "список всех .txt файлов",
        "найди все Dockerfile",
        "покажи все скрипты",
    ],
    "write": [
        # English
        "create a new file utils.py",
        "write hello world to test.txt",
        "save this to output.json",
        "create config.yaml with default settings",
        "write the results to report.md",
        "make a new file called helper.py",
        "create an empty __init__.py",
        "save configuration to settings.json",
        "write a new module",
        "create a Dockerfile",
        # Russian
        "создай файл utils.py",
        "запиши в test.txt",
        "сохрани в output.json",
        "создай config.yaml с настройками по умолчанию",
        "запиши результаты в report.md",
        "создай новый файл helper.py",
        "создай пустой __init__.py",
        "сохрани конфигурацию",
        "создай новый модуль",
        "создай Dockerfile",
    ],
    "edit": [
        # English
        "replace 'old_func' with 'new_func' in utils.py",
        "change the port number from 8080 to 3000",
        "update the import statement in agent.py",
        "modify the timeout value in config",
        "rename the variable from x to count",
        "fix the typo in router.py",
        "change the default value of threshold",
        "edit the function signature",
        "update the version number",
        "replace deprecated method call",
        "change the class name from Foo to Bar",
        "modify the return type",
        "fix the indentation in test.py",
        "update the error message",
        "change the log level from debug to info",
        # Russian
        "замени 'old_func' на 'new_func' в utils.py",
        "измени порт с 8080 на 3000",
        "обнови импорт в agent.py",
        "поменяй таймаут в конфиге",
        "переименуй переменную",
        "исправь опечатку в router.py",
        "обнови значение по умолчанию",
        "измени сигнатуру функции",
        "обнови номер версии",
        "замени устаревший метод",
    ],
    "find": [
        # English
        "find the definition of class Agent",
        "where is the main entry point",
        "locate the router module",
        "find where PatternRouter is defined",
        "where is the test for semantic_swecas",
        "locate the configuration file",
        "find the implementation of process_stream",
        "where are the validation rules",
        "find the database schema",
        "locate the API endpoints",
        # Russian
        "найди определение класса Agent",
        "где главная точка входа",
        "найди модуль роутера",
        "где определён PatternRouter",
        "где тест для semantic_swecas",
    ],
    "help": [
        # English
        "help",
        "what can you do",
        "show available commands",
        "how do I use this",
        "what tools are available",
        "list capabilities",
        "guide me",
        "show usage instructions",
        # Russian
        "помощь",
        "что ты умеешь",
        "покажи доступные команды",
        "как пользоваться",
        "какие инструменты доступны",
    ],
}

# Tool names used by the router
TOOL_NAMES = list(TRAINING_DATA.keys())


# ---------------------------------------------------------------------------
# Per-tool regex param extractors (reuse PatternRouter patterns)
# ---------------------------------------------------------------------------

_PARAM_PATTERNS: Dict[str, List[Tuple[re.Pattern, callable]]] = {
    "read": [
        (re.compile(r'(?:read|show|cat|open|view|display)\s+(?:file\s+)?["\']?([^\s"\']+)["\']?', re.I),
         lambda m: {"file_path": m.group(1)}),
        (re.compile(r'(?:what\'?s?\s+in|contents?\s+of)\s+["\']?([^\s"\']+)["\']?', re.I),
         lambda m: {"file_path": m.group(1)}),
        (re.compile(r'["\']?(\S+\.\w{1,5})["\']?\s*$', re.I),
         lambda m: {"file_path": m.group(1)} if '.' in m.group(1) else None),
    ],
    "grep": [
        (re.compile(r'(?:grep|search|find)\s+["\'](.+?)["\']\s+(?:in\s+)?["\']?([^\s"\']+)?["\']?', re.I),
         lambda m: {"pattern": m.group(1), "path": m.group(2)}),
        (re.compile(r'(?:search|find|look)\s+(?:for\s+)?["\'](.+?)["\']', re.I),
         lambda m: {"pattern": m.group(1)}),
        (re.compile(r'(?:where\s+is|find)\s+(?:the\s+)?(?:function|class|method|def)\s+(\w+)', re.I),
         lambda m: {"pattern": m.group(1)}),
    ],
    "bash": [
        (re.compile(r'(?:run|exec|execute)\s+[`"\']?(.+?)[`"\']?$', re.I),
         lambda m: {"command": m.group(1)}),
        (re.compile(r'^[`$]\s*(.+)$'),
         lambda m: {"command": m.group(1)}),
        (re.compile(r'(git\s+\S+(?:\s+\S+)*)', re.I),
         lambda m: {"command": m.group(1)}),
    ],
    "ls": [
        (re.compile(r'(?:ls|list|dir)\s*["\']?([^\s"\']*)["\']?$', re.I),
         lambda m: {"path": m.group(1) or None}),
        (re.compile(r'(?:list|show)\s+(?:files|directory|folder|contents?)\s*(?:in|of)?\s*["\']?([^\s"\']*)["\']?', re.I),
         lambda m: {"path": m.group(1) or None}),
    ],
    "glob": [
        (re.compile(r'(?:find|search|glob)\s+["\']?(\*\*?[^\s"\']+)["\']?', re.I),
         lambda m: {"pattern": m.group(1)}),
        (re.compile(r'find\s+(?:all\s+)?(?:files?\s+)?(?:with\s+)?\.(\w+)\s+(?:files?|extension)', re.I),
         lambda m: {"pattern": f"**/*.{m.group(1)}"}),
        (re.compile(r'(?:find|show|list)\s+all\s+\.?(\w+)\s+files?', re.I),
         lambda m: {"pattern": f"**/*.{m.group(1)}"}),
        (re.compile(r'(?:find|show|list)\s+all\s+(\w+)\s+files?', re.I),
         lambda m: {"pattern": f"**/*.{m.group(1)}"}),
    ],
    "write": [
        (re.compile(r'(?:write|create|save)\s+["\']?(.+?)["\']?\s+(?:to|in)\s+["\']?([^\s"\']+)["\']?', re.I),
         lambda m: {"content": m.group(1), "file_path": m.group(2)}),
        (re.compile(r'(?:create|new)\s+(?:a\s+)?(?:new\s+)?file\s+(?:called\s+)?["\']?([^\s"\']+)["\']?', re.I),
         lambda m: {"file_path": m.group(1), "content": ""}),
    ],
    "edit": [
        (re.compile(r'(?:replace|change)\s+["\'](.+?)["\']\s+(?:to|with)\s+["\'](.+?)["\']\s+in\s+(?:file\s+)?["\']?([^\s"\']+)["\']?', re.I),
         lambda m: {"old_string": m.group(1), "new_string": m.group(2), "file_path": m.group(3)}),
    ],
    "find": [],
    "help": [],
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ANRResult:
    """Result of neural router classification."""
    tool: str
    confidence: float
    top_matches: List[Tuple[str, float]]  # [(tool_name, similarity), ...]
    method: str = "neural"
    embedding_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# AdaptiveNeuralRouter
# ---------------------------------------------------------------------------

class AdaptiveNeuralRouter:
    """
    Embedding-based tool intent classifier (TIER 1).

    Uses all-MiniLM-L6-v2 for embeddings and top-k weighted voting
    to classify user queries into tool intents.  After classification,
    per-tool regex parsers extract parameters.

    A SQLite database stores routing history for incremental learning.

    Args:
        db_path: path to SQLite learning database. Default: in-memory.
        model_name: sentence-transformers model.
        training_data: custom training data dict. Default: TRAINING_DATA.
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(
        self,
        db_path: Optional[str] = None,
        model_name: str = DEFAULT_MODEL,
        training_data: Optional[Dict[str, List[str]]] = None,
    ):
        if not _check_st():
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )

        self._model_name = model_name
        self._training_data = training_data or TRAINING_DATA
        self._db_path = db_path or ":memory:"

        # Model + embeddings
        self._model = None
        self._embeddings = None  # numpy (N, dim)
        self._labels: List[str] = []  # tool name per example
        self._texts: List[str] = []

        # Stats
        self._total_classifications = 0
        self._hits: Dict[str, int] = {}  # per-tool hit counts
        self._miss_count = 0  # below confidence threshold

        self._build_index()
        self._init_db()

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def _build_index(self) -> None:
        """Load model and encode all training examples."""
        import numpy as np

        t0 = time.time()
        self._model = _SentenceTransformer(self._model_name)

        self._texts = []
        self._labels = []
        for tool, examples in sorted(self._training_data.items()):
            for text in examples:
                self._texts.append(text)
                self._labels.append(tool)

        self._embeddings = self._model.encode(
            self._texts,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        import numpy as np
        self._embeddings = np.asarray(self._embeddings, dtype=np.float32)

        elapsed = time.time() - t0
        logger.info(
            "[ANR] Index built: %d examples, dim=%d, %.1fs",
            len(self._labels), self._embeddings.shape[1], elapsed,
        )

    # ------------------------------------------------------------------
    # SQLite learning DB
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create learning tables if they don't exist."""
        # For :memory: DBs, keep a single persistent connection
        # (each sqlite3.connect(":memory:") creates a separate DB).
        if self._db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:")
        else:
            self._persistent_conn = None

        conn = self._get_conn()
        try:
            if self._db_path != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS routing_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    predicted_tool TEXT,
                    predicted_confidence REAL,
                    actual_tool TEXT,
                    correct BOOLEAN,
                    timestamp REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_examples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    source TEXT DEFAULT 'history',
                    created_at REAL
                )
            """)
            conn.commit()
        finally:
            if not self._persistent_conn:
                conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a connection. For :memory: DBs returns the persistent one."""
        if self._persistent_conn:
            return self._persistent_conn
        return sqlite3.connect(self._db_path)

    def _close_conn(self, conn: sqlite3.Connection) -> None:
        """Close a connection (no-op for persistent/in-memory connections)."""
        if conn is not self._persistent_conn:
            conn.close()

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self, query: str, top_k: int = 5) -> ANRResult:
        """
        Classify a query into a tool intent using embedding similarity.

        Uses top-k weighted voting: each neighbour casts a vote for its
        tool label weighted by cosine similarity.

        Args:
            query: user input text
            top_k: number of nearest neighbours for voting

        Returns:
            ANRResult with tool, confidence, top_matches
        """
        import numpy as np

        t0 = time.time()

        q_emb = self._model.encode(
            [query],
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        q_emb = np.asarray(q_emb, dtype=np.float32)

        # Cosine similarity via dot product (normalized embeddings)
        similarities = (self._embeddings @ q_emb.T).squeeze()

        # Top-k indices
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        # Weighted voting
        votes: Dict[str, float] = {}
        for idx in top_indices:
            tool = self._labels[idx]
            sim = float(similarities[idx])
            votes[tool] = votes.get(tool, 0.0) + max(sim, 0.0)

        if not votes:
            elapsed_ms = (time.time() - t0) * 1000
            self._miss_count += 1
            self._total_classifications += 1
            return ANRResult(
                tool="unknown",
                confidence=0.0,
                top_matches=[],
                embedding_time_ms=round(elapsed_ms, 2),
            )

        best_tool = max(votes, key=votes.get)
        total_weight = sum(votes.values())
        confidence = votes[best_tool] / total_weight if total_weight > 0 else 0.0

        sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
        top_matches = [(tool, round(w / total_weight, 4)) for tool, w in sorted_votes]

        elapsed_ms = (time.time() - t0) * 1000

        self._total_classifications += 1
        self._hits[best_tool] = self._hits.get(best_tool, 0) + 1

        return ANRResult(
            tool=best_tool,
            confidence=round(confidence, 4),
            top_matches=top_matches,
            embedding_time_ms=round(elapsed_ms, 2),
        )

    # ------------------------------------------------------------------
    # Parameter extraction
    # ------------------------------------------------------------------

    def extract_params(self, query: str, tool_intent: str) -> Dict[str, Any]:
        """
        Extract parameters from the query using per-tool regex parsers.

        Args:
            query: user input
            tool_intent: classified tool name (read, grep, bash, etc.)

        Returns:
            dict of extracted parameters, or {'_raw_input': query} as fallback
        """
        patterns = _PARAM_PATTERNS.get(tool_intent, [])
        for regex, param_fn in patterns:
            match = regex.search(query)
            if match:
                try:
                    result = param_fn(match)
                    if result is not None:
                        return result
                except Exception:
                    continue

        return {"_raw_input": query}

    # ------------------------------------------------------------------
    # Full routing (classify + extract)
    # ------------------------------------------------------------------

    def route(self, query: str, min_confidence: float = 0.6) -> Optional[Dict[str, Any]]:
        """
        Full route: classify intent + extract parameters.

        Returns None if confidence below threshold.

        Args:
            query: user input
            min_confidence: minimum confidence to accept classification

        Returns:
            dict with tool, params, confidence, method — or None
        """
        result = self.classify(query)

        if result.confidence < min_confidence:
            return None

        params = self.extract_params(query, result.tool)

        return {
            "tool": result.tool,
            "params": params,
            "confidence": result.confidence,
            "method": "neural",
            "top_matches": result.top_matches,
            "embedding_time_ms": result.embedding_time_ms,
        }

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        query: str,
        predicted_tool: Optional[str],
        predicted_confidence: float,
        actual_tool: str,
    ) -> None:
        """
        Record a routing outcome for learning.

        If the prediction was wrong and actual_tool is known, the query
        is also stored as a custom example for the next retrain.

        Args:
            query: user input
            predicted_tool: what ANR predicted (or None)
            predicted_confidence: ANR confidence
            actual_tool: what tool was actually used
        """
        correct = predicted_tool == actual_tool
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO routing_history (query, predicted_tool, predicted_confidence, actual_tool, correct, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (query, predicted_tool, predicted_confidence, actual_tool, correct, time.time()),
            )
            # If wrong, add as custom example
            if not correct and actual_tool in TOOL_NAMES:
                conn.execute(
                    "INSERT INTO custom_examples (query, tool, source, created_at) VALUES (?, ?, 'history', ?)",
                    (query, actual_tool, time.time()),
                )
            conn.commit()
        finally:
            self._close_conn(conn)

    def retrain_from_history(self) -> int:
        """
        Incorporate custom examples from the learning DB.

        Reads all custom_examples, adds them to training data, rebuilds index.

        Returns:
            Number of new examples added.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT query, tool FROM custom_examples").fetchall()
        finally:
            self._close_conn(conn)

        if not rows:
            return 0

        added = 0
        for query, tool in rows:
            if tool in self._training_data:
                if query not in self._training_data[tool]:
                    self._training_data[tool].append(query)
                    added += 1

        if added > 0:
            self._build_index()
            logger.info("[ANR] Retrained with %d new examples", added)

        return added

    def add_custom_example(self, query: str, tool: str) -> None:
        """Manually add a training example to the learning DB."""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO custom_examples (query, tool, source, created_at) VALUES (?, ?, 'manual', ?)",
                (query, tool, time.time()),
            )
            conn.commit()
        finally:
            self._close_conn(conn)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return classification statistics."""
        conn = self._get_conn()
        try:
            total_history = conn.execute("SELECT COUNT(*) FROM routing_history").fetchone()[0]
            correct_count = conn.execute("SELECT COUNT(*) FROM routing_history WHERE correct = 1").fetchone()[0]
            custom_count = conn.execute("SELECT COUNT(*) FROM custom_examples").fetchone()[0]
        finally:
            self._close_conn(conn)

        total = self._total_classifications or 1
        return {
            "model": self._model_name,
            "total_training_examples": len(self._labels),
            "tool_categories": len(self._training_data),
            "total_classifications": self._total_classifications,
            "per_tool_hits": dict(self._hits),
            "miss_count": self._miss_count,
            "history_records": total_history,
            "history_accuracy": round(correct_count / max(total_history, 1), 4),
            "custom_examples": custom_count,
            "embedding_dim": self._embeddings.shape[1] if self._embeddings is not None else 0,
        }

    @property
    def is_available(self) -> bool:
        return self._model is not None and self._embeddings is not None

    @property
    def n_examples(self) -> int:
        return len(self._labels)

    @property
    def model_name(self) -> str:
        return self._model_name
