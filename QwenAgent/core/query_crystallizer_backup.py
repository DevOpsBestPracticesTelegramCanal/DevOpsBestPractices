# -*- coding: utf-8 -*-
"""
Query Crystallizer - 3-Level Request Processing System
=======================================================

Transforms raw user requests into crystal-clear technical briefs.

Architecture:
    Level 1: Regex/Dict (0ms, free) - handles 70% of requests
    Level 2: Fuzzy matching (50ms, free) - handles 20% of requests
    Level 3: Clarification (optional) - handles 10% edge cases

Usage:
    from core.query_crystallizer import QueryCrystallizer

    crystallizer = QueryCrystallizer()
    result = crystallizer.crystallize("напиши сортировку на питоне")

    print(result.task_type)      # CREATE
    print(result.language)       # python
    print(result.objective)      # Create sorting function
    print(result.prompt)         # Full optimized prompt for LLM

Author: QwenCode Team
Date: 2026-02-05
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================

class TaskType(Enum):
    """Type of coding task."""
    CREATE = "create"           # Create new code
    FIX = "fix"                 # Fix bug/error
    REFACTOR = "refactor"       # Improve existing code
    EXPLAIN = "explain"         # Explain code
    OPTIMIZE = "optimize"       # Optimize performance
    TEST = "test"               # Write tests
    REVIEW = "review"           # Code review
    TRANSLATE = "translate"     # Translate code to another language
    DOCUMENT = "document"       # Add documentation
    DEBUG = "debug"             # Debug/trace issue
    SEARCH = "search"           # Search/find in codebase
    UNKNOWN = "unknown"


class Complexity(Enum):
    """Task complexity level."""
    TRIVIAL = "trivial"         # One-liner, simple
    LOW = "low"                 # Basic function
    MEDIUM = "medium"           # Multiple functions/class
    HIGH = "high"               # Complex system
    UNKNOWN = "unknown"


@dataclass
class CrystallizedQuery:
    """Result of query crystallization."""
    # Core fields
    original: str
    task_type: TaskType = TaskType.UNKNOWN
    language: Optional[str] = None
    framework: Optional[str] = None

    # Processed content
    objective: str = ""                    # Clear objective in English
    objective_ru: str = ""                 # Clear objective in Russian
    requirements: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

    # Metadata
    confidence: float = 0.0
    complexity: Complexity = Complexity.UNKNOWN
    keywords: List[str] = field(default_factory=list)

    # Generated prompt
    prompt: str = ""                       # Optimized prompt for LLM

    # Flags
    needs_clarification: bool = False
    clarification_question: str = ""
    detected_language: str = "en"          # Input language (en/ru)

    # Debug info
    detection_method: str = "unknown"
    processing_time_ms: float = 0.0


# =============================================================================
# DICTIONARIES & PATTERNS
# =============================================================================

# Task type detection patterns (Russian)
TASK_PATTERNS_RU = {
    TaskType.CREATE: [
        r"создай", r"напиши", r"сделай", r"реализуй", r"разработай",
        r"забабахай", r"накидай", r"сваргань", r"замути", r"накатай",
        r"добавь", r"имплементируй", r"закодь", r"набросай",
    ],
    TaskType.FIX: [
        r"исправь", r"почини", r"пофикси", r"поправь", r"вылечи",
        r"устрани", r"реши", r"убери\s+(?:ошибку|баг)",
    ],
    TaskType.REFACTOR: [
        r"рефактор", r"перепиши", r"улучши", r"переделай",
        r"реструктуризируй", r"приведи\s+в\s+порядок",
    ],
    TaskType.EXPLAIN: [
        r"объясни", r"расскажи", r"поясни", r"растолкуй",
        r"что\s+(?:такое|делает|значит)", r"как\s+работает",
    ],
    TaskType.OPTIMIZE: [
        r"оптимизируй", r"ускорь", r"разгони", r"прокачай",
        r"улучши\s+производительность", r"сделай\s+быстрее",
    ],
    TaskType.TEST: [
        r"напиши\s+тест", r"протестируй", r"добавь\s+тест",
        r"покрой\s+тестами", r"создай\s+тест",
    ],
    TaskType.REVIEW: [
        r"проверь", r"ревью", r"посмотри", r"оцени",
        r"что\s+не\s+так", r"найди\s+(?:ошибк|проблем)",
    ],
    TaskType.DOCUMENT: [
        r"задокументируй", r"добавь\s+(?:документацию|комментарии)",
        r"опиши", r"напиши\s+(?:докстринг|readme)",
    ],
    TaskType.DEBUG: [
        r"отладь", r"дебаг", r"найди\s+(?:баг|ошибку)",
        r"почему\s+(?:не\s+работает|падает|ошибка)",
    ],
    TaskType.SEARCH: [
        r"найди", r"покажи", r"поищи", r"где\s+(?:находится|находятся)",
        r"в\s+каких\s+файлах", r"список\s+(?:всех|файлов)",
    ],
}

# Task type detection patterns (English)
TASK_PATTERNS_EN = {
    TaskType.FIX: [
        r"\bfix\b", r"repair", r"solve", r"resolve", r"\bdebug\b",
        r"correct", r"patch", r"fix\s+the", r"fix\s+bug",
    ],
    TaskType.CREATE: [
        r"\bcreate\b", r"\bwrite\b", r"\bmake\b", r"implement", r"develop",
        r"build", r"\badd\b", r"generate", r"\bcode\b",
    ],
    TaskType.REFACTOR: [
        r"refactor", r"rewrite", r"improve", r"restructure",
        r"clean\s*up", r"reorganize",
    ],
    TaskType.EXPLAIN: [
        r"explain", r"describe", r"what\s+(?:is|does|means)",
        r"how\s+(?:does|to)", r"tell\s+me\s+about",
    ],
    TaskType.OPTIMIZE: [
        r"optimize", r"speed\s*up", r"improve\s+performance",
        r"make\s+faster", r"enhance",
    ],
    TaskType.TEST: [
        r"test", r"write\s+test", r"add\s+test", r"unit\s+test",
        r"cover\s+with\s+tests",
    ],
    TaskType.REVIEW: [
        r"review", r"check", r"evaluate", r"assess",
        r"find\s+(?:bug|issue|problem)",
    ],
    TaskType.DOCUMENT: [
        r"document", r"add\s+(?:docs|comments|docstring)",
        r"write\s+(?:readme|documentation)",
    ],
    TaskType.DEBUG: [
        r"debug", r"trace", r"find\s+bug", r"why\s+(?:doesn't|isn't|not)",
    ],
    TaskType.SEARCH: [
        r"\bfind\b", r"\bsearch\b", r"show\s+(?:me\s+)?(?:all|the)",
        r"where\s+(?:is|are)", r"list\s+(?:all|the)", r"locate",
    ],
}

# Programming languages
LANGUAGES = {
    # Python
    "python": ["python", "питон", "пайтон", "py", "пи"],
    "javascript": ["javascript", "js", "жс", "джаваскрипт", "джс", "node", "nodejs"],
    "typescript": ["typescript", "ts", "тайпскрипт"],
    "java": ["java", "джава", "жава"],
    "go": ["go", "golang", "гоу", "голанг"],
    "rust": ["rust", "раст"],
    "c": ["c", "си"],
    "cpp": ["c++", "cpp", "плюсы", "си++", "сипп"],
    "csharp": ["c#", "csharp", "шарп", "сишарп"],
    "php": ["php", "пхп"],
    "ruby": ["ruby", "руби"],
    "swift": ["swift", "свифт"],
    "kotlin": ["kotlin", "котлин"],
    "scala": ["scala", "скала"],
    "sql": ["sql", "скл", "эскюэль", "mysql", "postgres", "postgresql"],
    "html": ["html", "хтмл"],
    "css": ["css", "цсс", "стили"],
    "bash": ["bash", "shell", "sh", "баш", "шелл"],
    "powershell": ["powershell", "pwsh", "пауэршелл"],
}

# Frameworks
FRAMEWORKS = {
    # Python
    "django": ["django", "джанго"],
    "flask": ["flask", "фласк"],
    "fastapi": ["fastapi", "фастапи"],
    "pytorch": ["pytorch", "пайторч", "торч"],
    "tensorflow": ["tensorflow", "тензорфлоу", "tf"],
    "pandas": ["pandas", "пандас"],
    "numpy": ["numpy", "нампи"],
    # JavaScript
    "react": ["react", "реакт", "реактжс"],
    "vue": ["vue", "вью", "vuejs"],
    "angular": ["angular", "ангуляр"],
    "express": ["express", "экспресс"],
    "nextjs": ["next", "nextjs", "некст"],
    "nestjs": ["nest", "nestjs", "нест"],
    # Java
    "spring": ["spring", "спринг", "springboot"],
    # Go
    "gin": ["gin", "джин"],
    "fiber": ["fiber", "файбер"],
    # DevOps
    "docker": ["docker", "докер"],
    "kubernetes": ["kubernetes", "k8s", "кубер", "кубернетес"],
    "terraform": ["terraform", "терраформ"],
    "ansible": ["ansible", "ансибл"],
}

# Search context patterns - what to search for
# Format: (keywords, grep_pattern, description)
SEARCH_CONTEXTS = [
    # Classes - specific patterns first
    (["наследован", "наследуется", "наследуем", "наслед", "inherit", "extends", "базов", "parent", "subclass", "derived"],
     r"class \w+\([^)]+\):",
     "classes with inheritance"),

    (["класс", "классы", "class", "classes"],
     r"class \w+:",
     "class definitions"),

    (["dataclass", "датакласс", "data class"],
     r"@dataclass",
     "dataclass decorators"),

    # Functions
    (["async", "асинхрон", "await", "корутин", "coroutine"],
     r"async def \w+\(",
     "async functions"),

    (["функци", "function", "def", "метод", "method"],
     r"def \w+\(",
     "function definitions"),

    (["__init__", "конструктор", "constructor", "инициализ"],
     r"def __init__\(",
     "constructor methods"),

    # Imports
    (["импорт", "import", "подключ", "зависимост"],
     r"^(import |from .* import)",
     "import statements"),

    # Decorators
    (["декоратор", "decorator", "@"],
     r"@\w+",
     "decorators"),

    # Comments
    (["todo", "fixme", "hack", "xxx"],
     r"#.*(TODO|FIXME|HACK|XXX)",
     "TODO comments"),

    # Error handling
    (["exception", "исключени", "raise", "error", "ошибк"],
     r"(raise \w+|except \w+)",
     "exception handling"),

    (["try", "except", "обработка ошибок", "error handling"],
     r"(try:|except.*:)",
     "try/except blocks"),

    # Constants
    (["константа", "constant", "const", "UPPER"],
     r"^[A-Z][A-Z_0-9]+ =",
     "constants"),

    # API routes
    (["route", "endpoint", "api", "маршрут", "роут", "эндпоинт"],
     r"@(app|blueprint|router)\.(route|get|post|put|delete)",
     "API routes"),

    # Tests
    (["тест", "test", "unittest", "pytest"],
     r"def test_\w+\(",
     "test functions"),

    # Config
    (["config", "конфиг", "настройк", "settings", "env"],
     r"(CONFIG|config|Settings|\.env)",
     "configuration"),

    # Logging
    (["лог", "log", "logger", "logging", "print", "debug"],
     r"(logging\.\w+|print\(|logger\.)",
     "logging statements"),
]

# Russian to English term translations
RU_TO_EN_TERMS = {
    # Common programming terms
    "функция": "function",
    "функцию": "function",
    "класс": "class",
    "метод": "method",
    "переменная": "variable",
    "переменную": "variable",
    "массив": "array",
    "список": "list",
    "словарь": "dictionary",
    "цикл": "loop",
    "условие": "condition",
    "ошибка": "error",
    "ошибку": "error",
    "баг": "bug",
    "файл": "file",
    "файлы": "files",
    "сортировка": "sorting",
    "сортировку": "sorting",
    "поиск": "search",
    "фильтр": "filter",
    "валидация": "validation",
    "аутентификация": "authentication",
    "авторизация": "authorization",
    "база данных": "database",
    "базу данных": "database",
    "запрос": "query",
    "ответ": "response",
    "сервер": "server",
    "клиент": "client",
    "апи": "API",
    "эндпоинт": "endpoint",
    "роут": "route",
    "маршрут": "route",
    "тест": "test",
    "тесты": "tests",
    "модуль": "module",
    "пакет": "package",
    "библиотека": "library",
    "библиотеку": "library",
    "зависимость": "dependency",
    "импорт": "import",
    "экспорт": "export",
    "интерфейс": "interface",
    "наследование": "inheritance",
    "полиморфизм": "polymorphism",
    "инкапсуляция": "encapsulation",
    "паттерн": "pattern",
    "алгоритм": "algorithm",
    "рекурсия": "recursion",
    "итерация": "iteration",
    "асинхронный": "asynchronous",
    "синхронный": "synchronous",
    "многопоточный": "multithreaded",
    "парсер": "parser",
    "парсинг": "parsing",
    "сериализация": "serialization",
    "десериализация": "deserialization",
    "кэш": "cache",
    "кэширование": "caching",
    "логирование": "logging",
    "отладка": "debugging",
    "профилирование": "profiling",
    "оптимизация": "optimization",
    "рефакторинг": "refactoring",
    "деплой": "deployment",
    "развертывание": "deployment",
    "контейнер": "container",
    "микросервис": "microservice",
    "веб-приложение": "web application",
    "бэкенд": "backend",
    "фронтенд": "frontend",
}

# Slang to standard mapping for fuzzy matching
SLANG_MAP = {
    "create": ["забабахай", "накидай", "сваргань", "замути", "накатай", "закодь", "набросай"],
    "fix": ["пофикси", "вылечи", "залатай"],
    "optimize": ["разгони", "прокачай", "оптимизни"],
    "explain": ["растолкуй", "разжуй"],
    "refactor": ["причеши", "приведи в порядок"],
}


# =============================================================================
# QUERY CRYSTALLIZER
# =============================================================================

class QueryCrystallizer:
    """
    3-Level Query Crystallizer.

    Level 1: Regex/Dict - Fast, deterministic
    Level 2: Fuzzy matching - Handles variations
    Level 3: Clarification - For edge cases
    """

    def __init__(self, use_fuzzy: bool = True):
        """
        Initialize crystallizer.

        Args:
            use_fuzzy: Enable fuzzy matching (requires rapidfuzz)
        """
        self.use_fuzzy = use_fuzzy
        self._fuzzy_available = False

        if use_fuzzy:
            try:
                from rapidfuzz import fuzz, process
                self._fuzz = fuzz
                self._process = process
                self._fuzzy_available = True
            except ImportError:
                pass

    def crystallize(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> CrystallizedQuery:
        """
        Transform raw user query into structured technical brief.

        Args:
            query: Raw user input
            context: Optional context (current file, project info, etc.)

        Returns:
            CrystallizedQuery with all extracted information
        """
        import time
        start_time = time.time()

        query_clean = query.strip()
        query_lower = query_clean.lower()

        # Initialize result
        result = CrystallizedQuery(original=query_clean)

        # Detect input language
        result.detected_language = self._detect_input_language(query_lower)

        # LEVEL 1: Regex-based extraction
        result = self._level1_regex(query_lower, result)

        # LEVEL 2: Fuzzy enhancement (if needed and available)
        if result.confidence < 0.8 and self._fuzzy_available:
            result = self._level2_fuzzy(query_lower, result)

        # Extract keywords
        result.keywords = self._extract_keywords(query_lower)

        # Estimate complexity
        result.complexity = self._estimate_complexity(query_lower, result)

        # Generate objectives
        result.objective = self._generate_objective_en(result)
        result.objective_ru = self._generate_objective_ru(result)

        # Generate optimized prompt
        result.prompt = self._generate_prompt(result, context)

        # Check if clarification needed
        if result.confidence < 0.5 or result.task_type == TaskType.UNKNOWN:
            result.needs_clarification = True
            result.clarification_question = self._generate_clarification(query_clean, result)

        # Record processing time
        result.processing_time_ms = (time.time() - start_time) * 1000

        return result

    # =========================================================================
    # LEVEL 1: REGEX-BASED EXTRACTION
    # =========================================================================

    def _level1_regex(self, query: str, result: CrystallizedQuery) -> CrystallizedQuery:
        """Level 1: Fast regex-based extraction."""

        confidence_parts = []

        # Detect task type
        task_type, task_conf = self._detect_task_type(query)
        result.task_type = task_type
        confidence_parts.append(task_conf)

        # Detect language
        language, lang_conf = self._detect_language(query)
        result.language = language
        confidence_parts.append(lang_conf)

        # Detect framework
        framework, fw_conf = self._detect_framework(query)
        result.framework = framework
        if fw_conf > 0:
            confidence_parts.append(fw_conf)
            # Infer language from framework if not detected
            if not result.language:
                result.language = self._infer_language_from_framework(framework)

        # Calculate overall confidence
        if confidence_parts:
            result.confidence = sum(confidence_parts) / len(confidence_parts)

        result.detection_method = "regex"
        return result

    def _detect_task_type(self, query: str) -> Tuple[TaskType, float]:
        """Detect task type from query."""

        # Check Russian patterns first
        for task_type, patterns in TASK_PATTERNS_RU.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return task_type, 1.0

        # Check English patterns
        for task_type, patterns in TASK_PATTERNS_EN.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return task_type, 1.0

        return TaskType.UNKNOWN, 0.0

    def _detect_language(self, query: str) -> Tuple[Optional[str], float]:
        """Detect programming language from query."""

        for lang, keywords in LANGUAGES.items():
            for keyword in keywords:
                # Word boundary check for short keywords
                if len(keyword) <= 2:
                    pattern = rf'\b{re.escape(keyword)}\b'
                else:
                    pattern = re.escape(keyword)

                if re.search(pattern, query, re.IGNORECASE):
                    return lang, 1.0

        return None, 0.0

    def _detect_framework(self, query: str) -> Tuple[Optional[str], float]:
        """Detect framework from query."""

        for framework, keywords in FRAMEWORKS.items():
            for keyword in keywords:
                if keyword.lower() in query:
                    return framework, 1.0

        return None, 0.0

    def _infer_language_from_framework(self, framework: str) -> Optional[str]:
        """Infer programming language from framework."""
        FRAMEWORK_TO_LANGUAGE = {
            # Python
            "django": "python",
            "flask": "python",
            "fastapi": "python",
            "pytorch": "python",
            "tensorflow": "python",
            "pandas": "python",
            "numpy": "python",
            # JavaScript
            "react": "javascript",
            "vue": "javascript",
            "angular": "javascript",
            "express": "javascript",
            "nextjs": "javascript",
            "nestjs": "javascript",
            # Java
            "spring": "java",
            # Go
            "gin": "go",
            "fiber": "go",
        }
        return FRAMEWORK_TO_LANGUAGE.get(framework)

    def _detect_input_language(self, query: str) -> str:
        """Detect if input is Russian or English."""

        cyrillic_count = len(re.findall(r'[а-яё]', query, re.IGNORECASE))
        latin_count = len(re.findall(r'[a-z]', query, re.IGNORECASE))

        if cyrillic_count > latin_count:
            return "ru"
        return "en"

    # =========================================================================
    # LEVEL 2: FUZZY MATCHING
    # =========================================================================

    def _level2_fuzzy(self, query: str, result: CrystallizedQuery) -> CrystallizedQuery:
        """Level 2: Fuzzy matching for slang and variations."""

        if not self._fuzzy_available:
            return result

        # Check slang synonyms
        for task_type_str, synonyms in SLANG_MAP.items():
            match = self._process.extractOne(
                query,
                synonyms,
                scorer=self._fuzz.partial_ratio
            )

            if match and match[1] >= 70:
                # Map string to TaskType enum
                task_type_map = {
                    "create": TaskType.CREATE,
                    "fix": TaskType.FIX,
                    "optimize": TaskType.OPTIMIZE,
                    "explain": TaskType.EXPLAIN,
                    "refactor": TaskType.REFACTOR,
                }
                if task_type_str in task_type_map:
                    result.task_type = task_type_map[task_type_str]
                    result.confidence = min(result.confidence + 0.25, 1.0)
                    result.detection_method = "fuzzy"
                break

        return result

    # =========================================================================
    # EXTRACTION & GENERATION
    # =========================================================================

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract technical keywords from query."""

        keywords = []

        # Check for known terms
        for ru_term, en_term in RU_TO_EN_TERMS.items():
            if ru_term in query:
                keywords.append(en_term)

        # Check for language/framework mentions
        detected_lang = self._detect_language(query)[0]
        if detected_lang:
            keywords.append(detected_lang)

        detected_fw = self._detect_framework(query)[0]
        if detected_fw:
            keywords.append(detected_fw)

        return list(set(keywords))

    def _estimate_complexity(
        self,
        query: str,
        result: CrystallizedQuery
    ) -> Complexity:
        """Estimate task complexity."""

        # Simple heuristics
        word_count = len(query.split())

        # Complex indicators
        complex_indicators = [
            "система", "system", "архитектура", "architecture",
            "микросервис", "microservice", "распределен", "distributed",
            "масштабир", "scalab", "высоконагруж", "high-load",
        ]

        # Simple indicators
        simple_indicators = [
            "функци", "function", "метод", "method",
            "простой", "simple", "базов", "basic",
        ]

        has_complex = any(ind in query for ind in complex_indicators)
        has_simple = any(ind in query for ind in simple_indicators)

        if has_complex:
            return Complexity.HIGH
        elif has_simple or word_count < 10:
            return Complexity.LOW
        elif word_count > 30:
            return Complexity.HIGH
        else:
            return Complexity.MEDIUM

    def _generate_objective_en(self, result: CrystallizedQuery) -> str:
        """Generate clear objective in English."""

        # Map task type to action verb
        action_verbs = {
            TaskType.CREATE: "Create",
            TaskType.FIX: "Fix",
            TaskType.REFACTOR: "Refactor",
            TaskType.EXPLAIN: "Explain",
            TaskType.OPTIMIZE: "Optimize",
            TaskType.TEST: "Write tests for",
            TaskType.REVIEW: "Review",
            TaskType.DOCUMENT: "Document",
            TaskType.DEBUG: "Debug",
            TaskType.TRANSLATE: "Translate",
            TaskType.SEARCH: "Search for",
            TaskType.UNKNOWN: "Process",
        }

        verb = action_verbs.get(result.task_type, "Process")

        parts = [verb]

        if result.language:
            parts.append(result.language)

        if result.framework:
            parts.append(f"({result.framework})")

        if result.keywords:
            parts.append(": " + ", ".join(result.keywords[:3]))

        return " ".join(parts)

    def _generate_objective_ru(self, result: CrystallizedQuery) -> str:
        """Generate clear objective in Russian."""

        action_verbs_ru = {
            TaskType.CREATE: "Создать",
            TaskType.FIX: "Исправить",
            TaskType.REFACTOR: "Рефакторить",
            TaskType.EXPLAIN: "Объяснить",
            TaskType.OPTIMIZE: "Оптимизировать",
            TaskType.TEST: "Написать тесты для",
            TaskType.REVIEW: "Проверить",
            TaskType.DOCUMENT: "Задокументировать",
            TaskType.DEBUG: "Отладить",
            TaskType.TRANSLATE: "Перевести",
            TaskType.SEARCH: "Найти",
            TaskType.UNKNOWN: "Обработать",
        }

        verb = action_verbs_ru.get(result.task_type, "Обработать")

        parts = [verb]

        if result.language:
            parts.append(f"на {result.language}")

        if result.keywords:
            parts.append(": " + ", ".join(result.keywords[:3]))

        return " ".join(parts)

    def _generate_prompt(
        self,
        result: CrystallizedQuery,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate optimized prompt for LLM."""

        # Language-specific expertise
        lang_expertise = {
            "python": "Python with focus on PEP-8, type hints, and idiomatic patterns",
            "javascript": "JavaScript/Node.js with ES6+ features and best practices",
            "typescript": "TypeScript with strict typing and modern patterns",
            "go": "Go with emphasis on idiomatic Go patterns and error handling",
            "rust": "Rust with focus on safety, ownership, and zero-cost abstractions",
            "java": "Java with modern features (17+) and clean architecture",
        }

        expertise = lang_expertise.get(
            result.language or "python",
            f"{result.language or 'software'} development"
        )

        # Task-specific instructions
        task_instructions = {
            TaskType.CREATE: "Create clean, well-structured, production-ready code.",
            TaskType.FIX: "Identify the root cause and provide a fix with explanation.",
            TaskType.REFACTOR: "Improve code quality while preserving functionality.",
            TaskType.EXPLAIN: "Provide clear, educational explanation with examples.",
            TaskType.OPTIMIZE: "Optimize for performance with benchmarks if possible.",
            TaskType.TEST: "Write comprehensive tests with good coverage.",
            TaskType.REVIEW: "Review for bugs, security issues, and best practices.",
            TaskType.DOCUMENT: "Add clear documentation and docstrings.",
            TaskType.DEBUG: "Trace the issue and explain the debugging process.",
        }

        instruction = task_instructions.get(
            result.task_type,
            "Complete the requested task professionally."
        )

        # Build prompt
        prompt_parts = [
            f"You are a Senior Developer expert in {expertise}.",
            "",
            "## Task",
            result.objective,
            "",
            "## Original Request",
            result.original,
            "",
            "## Instructions",
            instruction,
            "",
            "## Quality Standards",
            f"- Follow {result.language or 'language'} idioms and best practices",
            "- Include error handling where appropriate",
            "- Add comments for complex logic",
            "- Provide example usage if creating new code",
        ]

        if result.framework:
            prompt_parts.append(f"- Use {result.framework} conventions")

        if context:
            prompt_parts.extend([
                "",
                "## Context",
            ])
            if "current_file" in context:
                prompt_parts.append(f"Current file: {context['current_file']}")
            if "project_type" in context:
                prompt_parts.append(f"Project type: {context['project_type']}")

        prompt_parts.extend([
            "",
            "## Output",
            "Provide clean, production-ready code with explanations.",
        ])

        return "\n".join(prompt_parts)

    def _generate_clarification(
        self,
        query: str,
        result: CrystallizedQuery
    ) -> str:
        """Generate clarification question for ambiguous requests."""

        if result.detected_language == "ru":
            if result.task_type == TaskType.UNKNOWN:
                return "Уточните, что именно нужно сделать: создать, исправить, объяснить?"
            if not result.language:
                return "На каком языке программирования нужен код?"
            return "Можете уточнить детали задачи?"
        else:
            if result.task_type == TaskType.UNKNOWN:
                return "Could you clarify what action is needed: create, fix, explain?"
            if not result.language:
                return "What programming language should be used?"
            return "Could you provide more details about the task?"


# =============================================================================
# TRANSLATION DETECTOR (INTEGRATED)
# =============================================================================

class TranslationDetector:
    """
    Detects translation requests in user queries.
    Integrated with QueryCrystallizer.
    """

    TRANSLATION_PATTERNS = [
        # Russian patterns
        (r"^переведи(\s+это)?(\s+на)?\s*рус", "ru"),
        (r"^перевод(\s+на)?\s*рус", "ru"),
        (r"^по[\-\s]?русски\s*$", "ru"),
        (r"^на\s+русском", "ru"),
        (r"^скажи(\s+это)?\s+по[\-\s]?русски", "ru"),
        (r"^напиши(\s+это)?\s+(на\s+)?русск", "ru"),
        (r"^(а\s+)?можно(\s+это)?\s+(на\s+|по[\-\s]?)?русск", "ru"),

        # English patterns
        (r"^translate(\s+this)?(\s+to)?\s*english", "en"),
        (r"^in\s+english", "en"),
        (r"^say(\s+it)?\s+in\s+english", "en"),
        (r"^переведи(\s+на)?\s*англ", "en"),
    ]

    @classmethod
    def detect(cls, query: str) -> Tuple[bool, Optional[str]]:
        """
        Detect if query is a translation request.

        Returns:
            (is_translation, target_language)
        """
        query_lower = query.lower().strip()

        for pattern, lang in cls.TRANSLATION_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                return True, lang

        return False, None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_crystallizer: Optional[QueryCrystallizer] = None


def get_crystallizer() -> QueryCrystallizer:
    """Get or create global crystallizer instance."""
    global _crystallizer
    if _crystallizer is None:
        _crystallizer = QueryCrystallizer()
    return _crystallizer


def crystallize(query: str, context: Dict[str, Any] = None) -> CrystallizedQuery:
    """Quick crystallization."""
    return get_crystallizer().crystallize(query, context)


def translate_search_to_grep(query: str, path: str = ".") -> Optional[Dict[str, Any]]:
    """
    Translate natural language search query to grep parameters.

    Args:
        query: Natural language search query (Russian or English)
        path: Search path (default: current directory)

    Returns:
        Dict with grep parameters or None if not a search query

    Examples:
        >>> translate_search_to_grep("найди все классы с наследованием", "core/")
        {'pattern': 'class \\w+\\([^)]+\\):', 'path': 'core/', 'glob': '*.py', 'description': 'classes with inheritance'}

        >>> translate_search_to_grep("покажи функции async")
        {'pattern': 'async def \\w+\\(', 'path': '.', 'glob': '*.py', 'description': 'async functions'}
    """
    query_lower = query.lower().strip()

    # Check if this is a search query
    search_triggers = [
        "найди", "найти", "поищи", "покажи", "где",
        "find", "search", "show", "list", "locate", "where"
    ]

    is_search = any(trigger in query_lower for trigger in search_triggers)
    if not is_search:
        return None

    # Find matching search context
    # Strategy: First pattern with ANY keyword match wins (order matters!)
    # SEARCH_CONTEXTS is ordered: specific patterns first, generic later

    for keywords, pattern, description in SEARCH_CONTEXTS:
        matches = sum(1 for kw in keywords if kw.lower() in query_lower)
        if matches > 0:
            return {
                "pattern": pattern,
                "path": path,
                "glob": "*.py",
                "description": description,
                "confidence": min(matches / len(keywords), 1.0)
            }

    return None


# =============================================================================
# TESTS
# =============================================================================

def test_query_crystallizer():
    """Test the query crystallizer."""

    print("=" * 70)
    print("QUERY CRYSTALLIZER TESTS")
    print("=" * 70)

    crystallizer = QueryCrystallizer(use_fuzzy=True)

    tests = [
        # Russian - CREATE
        ("напиши функцию сортировки на питоне", TaskType.CREATE, "python"),
        ("создай класс на java", TaskType.CREATE, "java"),
        ("забабахай сортировку на питоне", TaskType.CREATE, "python"),

        # Russian - FIX
        ("исправь ошибку в коде python", TaskType.FIX, "python"),
        ("пофикси баг", TaskType.FIX, None),

        # Russian - EXPLAIN
        ("объясни что делает этот код", TaskType.EXPLAIN, None),
        ("как работает рекурсия", TaskType.EXPLAIN, None),

        # English - CREATE
        ("write a sorting function in python", TaskType.CREATE, "python"),
        ("create react component", TaskType.CREATE, "javascript"),

        # English - FIX
        ("fix the bug in my code", TaskType.FIX, None),

        # With frameworks
        ("создай api на fastapi", TaskType.CREATE, "python"),
        ("напиши компонент на react", TaskType.CREATE, "javascript"),
    ]

    passed = 0
    failed = 0

    for query, expected_type, expected_lang in tests:
        result = crystallizer.crystallize(query)

        type_ok = result.task_type == expected_type
        lang_ok = result.language == expected_lang

        if type_ok and lang_ok:
            status = "OK"
            passed += 1
        else:
            status = "FAIL"
            failed += 1

        print(f"\n{status}: {query[:50]}...")
        print(f"  Type: {result.task_type.value} (exp: {expected_type.value})")
        print(f"  Lang: {result.language} (exp: {expected_lang})")
        print(f"  Conf: {result.confidence:.2f}")
        print(f"  Method: {result.detection_method}")
        print(f"  Objective EN: {result.objective}")

    print("\n" + "=" * 70)
    print(f"Results: {passed}/{len(tests)} passed")
    print("=" * 70)

    return passed == len(tests)


if __name__ == "__main__":
    test_query_crystallizer()
