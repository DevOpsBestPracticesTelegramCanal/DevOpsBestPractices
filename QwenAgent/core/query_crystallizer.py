"""
Hybrid Query Crystallizer for QwenCode v2.1
============================================

3-уровневая архитектура кристаллизации запросов с LRU-кэшированием:

┌─────────────────────────────────────────────────────────────┐
│  УРОВЕНЬ 0: Cache (0ms)      → Повторные запросы            │
│  УРОВЕНЬ 1: Regex (0.1ms)    → 70% запросов                 │
│  УРОВЕНЬ 2: Fuzzy (10-50ms)  → 20% запросов                 │
│  УРОВЕНЬ 3: Clarification    → 10% запросов                 │
└─────────────────────────────────────────────────────────────┘

Оптимизации v2.1:
- LRU-кэш на 1000 запросов (~0ms для повторных)
- Предкомпилированные regex паттерны
- Статистика cache hit/miss
- Метод очистки кэша

Использование:
    from core.query_crystallizer import HybridCrystallizer
    
    crystallizer = HybridCrystallizer()
    result = crystallizer.crystallize("забабахай сортировку на питоне")
    
    # Статистика кэша
    print(crystallizer.cache_stats())  # {'hits': 42, 'misses': 10, 'hit_rate': 0.81}

Зависимости:
    pip install rapidfuzz  # Опционально, для fuzzy matching

Author: QwenCode Team
Version: 2.1.0
"""

import re
import hashlib
from functools import lru_cache
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


# =============================================================================
# ENUMS И DATACLASSES
# =============================================================================

class TaskType(Enum):
    """Тип задачи программирования."""
    CREATE = "create"
    EDIT = "edit"          # NEW: Edit existing file/class/function
    FIX = "fix"
    REFACTOR = "refactor"
    EXPLAIN = "explain"
    OPTIMIZE = "optimize"
    DEBUG = "debug"
    TEST = "test"
    DOCUMENT = "document"
    CONVERT = "convert"
    REVIEW = "review"
    SEARCH = "search"
    UNKNOWN = "unknown"


class Complexity(Enum):
    """Сложность задачи."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class CrystallizedQuery:
    """Структурированный результат кристаллизации."""
    
    # Основные поля
    original_query: str
    task_type: TaskType
    objective: str                    # EN
    objective_ru: str                 # RU
    
    # Технические детали
    language: Optional[str] = None
    framework: Optional[str] = None
    libraries: List[str] = field(default_factory=list)
    
    # Требования
    requirements: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    
    # Контекст
    error_message: Optional[str] = None
    code_context: Optional[str] = None
    
    # Метаданные
    confidence: float = 0.0
    complexity: Complexity = Complexity.MEDIUM
    detection_method: str = "unknown"  # cache, regex, fuzzy, clarification
    
    # Поиск (для TaskType.SEARCH)
    search_pattern: Optional[str] = None
    search_description: Optional[str] = None
    
    # Уточнение (если нужно)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    
    # Оптимизированный промпт
    optimized_prompt: str = ""
    
    # Кэш метаданные
    cached: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_query": self.original_query,
            "task_type": self.task_type.value,
            "objective": self.objective,
            "objective_ru": self.objective_ru,
            "language": self.language,
            "framework": self.framework,
            "requirements": self.requirements,
            "constraints": self.constraints,
            "confidence": self.confidence,
            "complexity": self.complexity.value,
            "detection_method": self.detection_method,
            "needs_clarification": self.needs_clarification,
            "search_pattern": self.search_pattern,
            "cached": self.cached,
            "optimized_prompt": self.optimized_prompt,
        }
    
    def copy(self) -> 'CrystallizedQuery':
        """Создать копию результата."""
        return CrystallizedQuery(
            original_query=self.original_query,
            task_type=self.task_type,
            objective=self.objective,
            objective_ru=self.objective_ru,
            language=self.language,
            framework=self.framework,
            libraries=self.libraries.copy(),
            requirements=self.requirements.copy(),
            constraints=self.constraints.copy(),
            error_message=self.error_message,
            code_context=self.code_context,
            confidence=self.confidence,
            complexity=self.complexity,
            detection_method=self.detection_method,
            search_pattern=self.search_pattern,
            search_description=self.search_description,
            needs_clarification=self.needs_clarification,
            clarification_question=self.clarification_question,
            optimized_prompt=self.optimized_prompt,
            cached=self.cached,
        )


# =============================================================================
# ПРЕДКОМПИЛИРОВАННЫЕ REGEX ПАТТЕРНЫ (оптимизация)
# =============================================================================

class CompiledPatterns:
    """
    Предкомпилированные regex паттерны для быстрого matching.
    Компиляция происходит один раз при загрузке модуля.
    """
    
    # Паттерны типов задач
    TASK_PATTERNS_RAW = {
        TaskType.CREATE: [
            r"(напиши|создай|сделай|реализуй|разработай|генерируй)\s+",
            r"нужн[аоы]\s+(функци|класс|модуль|скрипт|программ)",
            r"(хочу|надо|требуется)\s+(написать|создать|сделать)",
            r"(write|create|make|implement|develop|generate|build)\s+",
            r"(need|want)\s+(a\s+)?(function|class|module|script)",
            r"can you (write|create|make|build)",
        ],
        TaskType.EDIT: [
            # "добавь метод X в класс Y" - edit existing class
            r"(добавь|вставь|допиши)\s+(метод|функцию|поле|атрибут)\s+\w+\s+(в|к)\s+(класс|файл)",
            r"(add|insert|append)\s+(method|function|field|attribute)\s+\w+\s+(to|in)\s+(class|file)",
            # "измени метод X в файле Y"
            r"(измени|поменяй|обнови|модифицируй)\s+(метод|функцию|класс|код)\s+",
            r"(change|modify|update|alter)\s+(method|function|class|code)\s+",
            # "в файле X добавь Y"
            r"в\s+(файле?|класс[ае]?|модул[ье])\s+.+\s+(добавь|вставь|измени)",
            r"in\s+(file|class|module)\s+.+\s+(add|insert|change)",
            # "добавь в ConfigValidator метод"
            r"(добавь|вставь)\s+(в|к)\s+\w+\s+(метод|функцию|поле)",
        ],
        TaskType.FIX: [
            r"(исправь|почини|поправь|устрани|реши|пофикси)\s*",
            r"(fix|repair|resolve|solve)\s*",
            r"(ошибка|error|exception|bug|не работает|broken|crashes)",
            r"(traceback|exception|NameError|TypeError|ValueError)",
        ],
        TaskType.REFACTOR: [
            r"(рефактор|переделай|перепиши|улучши\s+код|переработай)",
            r"(refactor|rewrite|improve|clean\s*up|restructure)",
            r"(сделай|перепиши)\s+(код\s+)?(чище|лучше|читаем)",
        ],
        TaskType.EXPLAIN: [
            r"(объясни|расскажи|поясни|опиши|растолкуй)\s*(как|что|зачем|почему)?",
            r"(explain|describe|tell\s+me|clarify)\s*(how|what|why)?",
            r"(что делает|как работает|зачем нужн)",
        ],
        TaskType.OPTIMIZE: [
            r"(оптимизируй|ускорь|улучши\s+производительность|разгони)",
            r"(optimize|speed\s*up|improve\s+performance|make.*faster)",
            r"(медленно|тормозит|slow|performance)",
        ],
        TaskType.DEBUG: [
            r"(отладь|найди\s+ошибку|продебажь)",
            r"(debug|find\s+the\s+bug|trace)",
        ],
        TaskType.TEST: [
            r"(напиши|создай|добавь)\s*(тест|unit|интеграционн)",
            r"(write|create|add)\s*(test|unit|spec)",
        ],
        TaskType.DOCUMENT: [
            r"(документируй|добавь\s+docstring|задокументируй)",
            r"(document|add\s+docstring|write\s+docs)",
        ],
        TaskType.CONVERT: [
            r"(конвертируй|преобразуй|переведи|перепиши)\s*(код\s+)?(из|с|на)",
            r"(convert|transform|translate|port)\s*(from|to)",
        ],
        TaskType.REVIEW: [
            r"(проверь|ревью|review|оцени)\s*(код|мой\s+код)?",
            r"(review|check|evaluate)\s*(my|this)?\s*code",
        ],
        TaskType.SEARCH: [
            r"(найди|поищи|покажи)\s+(все\s+)?(классы|функции|методы|импорты)",
            r"(find|search|show)\s+(all\s+)?(classes|functions|methods|imports)",
            r"где\s+(находится|находятся|используется)",
            # Project analysis patterns
            r"(покажи|выведи|отобрази)\s+(описани|docstring|документаци|структур)",
            r"(анализ|обзор|overview)\s+(модул|проект|директор|папк|код)",
            r"(список|list)\s+(модул|файл|класс|функци)",
            r"что\s+(есть|содержит|находится)\s+в\s+",
            r"(найди|поищи)\s+(все\s+)?(docstring|описани|комментари)",
            r"(что\s+)?(содержит|внутри)\s+(директор|папк|модул)",
            r"(найди|покажи)\s+(все\s+)?(TODO|FIXME|HACK)",
        ],
    }
    
    # Языки программирования
    LANGUAGES_RAW = {
        r"\b(python|питон|пайтон|py)\b": "python",
        r"\.py\b": "python",
        r"\b(javascript|js|джаваскрипт)\b": "javascript",
        r"\b(typescript|ts|тайпскрипт)\b": "typescript",
        r"\b(java|джава)(?!script)\b": "java",
        r"\b(c\+\+|cpp|плюсы)\b": "cpp",
        r"\b(c\#|csharp|шарп)\b": "csharp",
        r"\b(go|golang|гоу)\b": "go",
        r"\b(rust|раст)\b": "rust",
        r"\b(ruby|руби)\b": "ruby",
        r"\b(php|пхп)\b": "php",
        r"\b(swift|свифт)\b": "swift",
        r"\b(kotlin|котлин)\b": "kotlin",
        r"\b(sql|mysql|postgresql)\b": "sql",
        r"\b(bash|shell|sh)\b": "bash",
    }
    
    # Фреймворки
    FRAMEWORKS_RAW = {
        r"\b(django|джанго)\b": ("django", "python"),
        r"\b(flask|фласк)\b": ("flask", "python"),
        r"\b(fastapi)\b": ("fastapi", "python"),
        r"\b(react|реакт)\b": ("react", "javascript"),
        r"\b(vue|вью)\b": ("vue", "javascript"),
        r"\b(angular)\b": ("angular", "typescript"),
        r"\b(node\.?js|нода)\b": ("nodejs", "javascript"),
        r"\b(spring|спринг)\b": ("spring", "java"),
        r"\b(pandas|пандас)\b": ("pandas", "python"),
        r"\b(numpy)\b": ("numpy", "python"),
        r"\b(tensorflow|pytorch)\b": ("ml", "python"),
    }
    
    # Контексты поиска (для TaskType.SEARCH)
    SEARCH_CONTEXTS_RAW = [
        # Specific patterns first (order matters!)
        (["наследован", "наследуется", "inherit", "extends", "базов", "parent"],
         r"class \w+\([^)]+\):", "classes with inheritance"),
        (["класс", "классы", "class"], r"class \w+:", "class definitions"),
        (["async", "асинхрон", "корутин"], r"async def \w+\(", "async functions"),
        (["функци", "function", "def", "метод"], r"def \w+\(", "function definitions"),
        (["импорт", "import"], r"^(import |from .* import)", "import statements"),
        (["декоратор", "decorator"], r"@\w+", "decorators"),
        (["todo", "fixme"], r"#.*(TODO|FIXME|HACK)", "TODO comments"),
        (["exception", "исключени", "raise"], r"(raise \w+|except \w+)", "exception handling"),
        (["тест", "test"], r"def test_\w+\(", "test functions"),
        (["константа", "constant", "UPPER"], r"^[A-Z][A-Z_0-9]+ =", "constants"),

        # Project analysis patterns
        (["описани", "docstring", "документаци", "описания модул", "докстринг"],
         r'^"""', "module docstrings"),
        (["структур", "анализ модул", "обзор", "overview", "анализ код"],
         r"^(class |def |async def )", "code structure"),
        (["глобальн", "global", "переменн"],
         r"^[a-z_][a-z_0-9]+ =", "global variables"),
        (["__init__", "конструктор", "инициализ"],
         r"def __init__\(", "constructors"),
        (["property", "свойств", "getter", "setter"],
         r"@property|\.setter", "properties"),
        (["staticmethod", "classmethod", "статическ"],
         r"@(staticmethod|classmethod)", "static/class methods"),
        (["dataclass", "датакласс", "pydantic"],
         r"@dataclass|class \w+\(BaseModel\)", "dataclasses"),
        (["типы", "type", "typing", "аннотаци"],
         r"(: [A-Z]\w+|-> [A-Z]\w+|\[.+\])", "type annotations"),
        (["список модул", "list of module", "модули в"],
         r"^(class |def )", "module listing"),
        (["содержит", "contains", "что есть в", "что внутри"],
         r"^(class |def |import )", "directory contents"),
    ]
    
    def __init__(self):
        """Компилировать все паттерны при инициализации."""
        # Компилировать паттерны задач
        self.task_patterns: Dict[TaskType, List[re.Pattern]] = {}
        for task_type, patterns in self.TASK_PATTERNS_RAW.items():
            self.task_patterns[task_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
        
        # Компилировать паттерны языков
        self.language_patterns: List[Tuple[re.Pattern, str]] = [
            (re.compile(p, re.IGNORECASE), lang) 
            for p, lang in self.LANGUAGES_RAW.items()
        ]
        
        # Компилировать паттерны фреймворков
        self.framework_patterns: List[Tuple[re.Pattern, Tuple[str, str]]] = [
            (re.compile(p, re.IGNORECASE), fw_lang) 
            for p, fw_lang in self.FRAMEWORKS_RAW.items()
        ]


# Глобальный singleton для скомпилированных паттернов
_compiled_patterns: Optional[CompiledPatterns] = None

def get_compiled_patterns() -> CompiledPatterns:
    """Получить singleton скомпилированных паттернов."""
    global _compiled_patterns
    if _compiled_patterns is None:
        _compiled_patterns = CompiledPatterns()
    return _compiled_patterns


# =============================================================================
# ТЕРМИНЫ RU → EN
# =============================================================================

TERM_TRANSLATIONS = {
    "функция": "function", "функции": "function", "функцию": "function",
    "класс": "class", "классы": "classes",
    "метод": "method", "методы": "methods",
    "модуль": "module", "переменная": "variable",
    "массив": "array", "список": "list",
    "словарь": "dictionary", "строка": "string",
    "сортировка": "sorting", "поиск": "search",
    "рекурсия": "recursion", "цикл": "loop",
    "ошибка": "error", "исключение": "exception",
    "создать": "create", "удалить": "delete",
    "парсинг": "parsing", "валидация": "validation",
    "авторизация": "authorization", "аутентификация": "authentication",
}


# =============================================================================
# УРОВЕНЬ 1: REGEX CRYSTALLIZER (с предкомпилированными паттернами)
# =============================================================================

class RegexCrystallizer:
    """
    Быстрый детерминированный кристаллизатор на предкомпилированных regex.
    Обрабатывает ~70% типовых запросов за ~0.1ms.
    """
    
    def __init__(self):
        self.patterns = get_compiled_patterns()
    
    def crystallize(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> CrystallizedQuery:
        """Кристаллизовать запрос с помощью regex."""
        context = context or {}
        query_clean = query.strip()
        query_lower = query_clean.lower()
        
        # 1. Тип задачи (используем предкомпилированные паттерны)
        task_type, task_confidence = self._detect_task_type(query_lower)
        
        # 2. Язык
        language = self._detect_language(query_lower, context)
        
        # 3. Фреймворк
        framework, fw_lang = self._detect_framework(query_lower)
        if fw_lang and not language:
            language = fw_lang
        
        # 4. Поиск (если TaskType.SEARCH)
        search_pattern = None
        search_description = None
        if task_type == TaskType.SEARCH:
            search_pattern, search_description = self._detect_search_context(query_lower)
        
        # 5. Требования
        requirements = self._extract_requirements(query_clean, task_type)
        
        # 6. Ограничения
        constraints = self._extract_constraints(query_clean)
        
        # 7. Ошибка
        error_message = self._extract_error(query_clean, context)
        
        # 8. Objectives
        objective_en = self._create_objective_en(query_clean, task_type, language)
        objective_ru = self._create_objective_ru(query_clean, task_type, language)
        
        # 9. Сложность
        complexity = self._estimate_complexity(query_clean, requirements)
        
        # 10. Confidence
        total_confidence = self._calculate_confidence(
            task_confidence, language, framework
        )
        
        return CrystallizedQuery(
            original_query=query_clean,
            task_type=task_type,
            objective=objective_en,
            objective_ru=objective_ru,
            language=language or "python",
            framework=framework,
            requirements=requirements,
            constraints=constraints,
            error_message=error_message,
            code_context=context.get("code"),
            confidence=total_confidence,
            complexity=complexity,
            detection_method="regex",
            search_pattern=search_pattern,
            search_description=search_description,
        )
    
    def _detect_task_type(self, query: str) -> Tuple[TaskType, float]:
        """Определить тип задачи (предкомпилированные паттерны)."""
        scores = {task: 0 for task in TaskType}
        
        for task_type, compiled_patterns in self.patterns.task_patterns.items():
            for pattern in compiled_patterns:
                if pattern.search(query):
                    scores[task_type] += 1
        
        best = max(scores, key=scores.get)
        best_score = scores[best]
        
        if best_score == 0:
            return TaskType.CREATE, 0.3
        
        total = sum(scores.values())
        confidence = min((best_score / max(total, 1)) + 0.3, 1.0)
        
        return best, confidence
    
    def _detect_language(self, query: str, context: Dict) -> Optional[str]:
        """Определить язык (предкомпилированные паттерны)."""
        if context.get("language"):
            return context["language"]
        
        for pattern, lang in self.patterns.language_patterns:
            if pattern.search(query):
                return lang
        
        return None
    
    def _detect_framework(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        """Определить фреймворк (предкомпилированные паттерны)."""
        for pattern, (fw, lang) in self.patterns.framework_patterns:
            if pattern.search(query):
                return fw, lang
        return None, None
    
    def _detect_search_context(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        """Определить контекст поиска для SEARCH задач."""
        for keywords, pattern, description in CompiledPatterns.SEARCH_CONTEXTS_RAW:
            if any(kw.lower() in query for kw in keywords):
                return pattern, description
        return None, None
    
    def _extract_requirements(self, query: str, task_type: TaskType) -> List[str]:
        """Извлечь требования."""
        requirements = []
        
        patterns = [
            r"(должн[аоы]|нужн[оа]|требуется|чтобы)\s+(.+?)(?:\.|,|$)",
            r"(with|that|which)\s+(has|includes?|supports?)\s+(.+?)(?:\.|,|$)",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, query, re.IGNORECASE)
            for match in matches:
                req = match[-1].strip() if isinstance(match, tuple) else match.strip()
                if req and len(req) > 3:
                    requirements.append(self._normalize_terms(req))
        
        if not requirements:
            defaults = {
                TaskType.CREATE: ["Clean, readable code", "Error handling"],
                TaskType.FIX: ["Identify root cause", "Provide fix"],
                TaskType.REFACTOR: ["Improve structure", "Maintain functionality"],
                TaskType.OPTIMIZE: ["Improve performance", "Maintain correctness"],
                TaskType.TEST: ["Good coverage", "Edge cases"],
                TaskType.SEARCH: ["Find all matches", "Show file locations"],
            }
            requirements = defaults.get(task_type, ["Follow best practices"])
        
        return requirements
    
    def _extract_constraints(self, query: str) -> List[str]:
        """Извлечь ограничения."""
        constraints = []
        
        patterns = [
            r"(без|не использ\w+|не применя\w+)\s+(.+?)(?:\.|,|$)",
            r"(without|don'?t use|avoid|no)\s+(.+?)(?:\.|,|$)",
            r"(только|исключительно|only)\s+(.+?)(?:\.|,|$)",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, query, re.IGNORECASE)
            for match in matches:
                c = " ".join(match).strip() if isinstance(match, tuple) else match.strip()
                if c and len(c) > 2:
                    constraints.append(c)
        
        return constraints
    
    def _extract_error(self, query: str, context: Dict) -> Optional[str]:
        """Извлечь ошибку."""
        if context.get("error"):
            return context["error"]
        
        patterns = [
            r"(Traceback.*?)(?=\n\n|\Z)",
            r"(Error:.*?)(?=\n|$)",
            r"(\w+Error:.*?)(?=\n|$)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
    
    def _normalize_terms(self, text: str) -> str:
        """Нормализовать термины RU→EN."""
        result = text
        for ru, en in TERM_TRANSLATIONS.items():
            result = re.sub(rf"\b{ru}\b", en, result, flags=re.IGNORECASE)
        return result.strip()
    
    def _create_objective_en(
        self, query: str, task_type: TaskType, language: Optional[str]
    ) -> str:
        """Создать objective на EN."""
        verbs = {
            TaskType.CREATE: "Create",
            TaskType.EDIT: "Edit",
            TaskType.FIX: "Fix",
            TaskType.REFACTOR: "Refactor",
            TaskType.EXPLAIN: "Explain",
            TaskType.OPTIMIZE: "Optimize",
            TaskType.DEBUG: "Debug",
            TaskType.TEST: "Write tests for",
            TaskType.DOCUMENT: "Document",
            TaskType.CONVERT: "Convert",
            TaskType.REVIEW: "Review",
            TaskType.SEARCH: "Search for",
        }
        
        verb = verbs.get(task_type, "Create")
        normalized = self._normalize_terms(query)
        
        prefixes = [
            r"^(пожалуйста\s+)?(напиши|создай|сделай|исправь|объясни|найди)\s+(мне\s+)?",
            r"^(please\s+)?(write|create|make|fix|explain|find)\s+(me\s+)?(a\s+)?",
        ]
        
        for p in prefixes:
            normalized = re.sub(p, "", normalized, flags=re.IGNORECASE)
        
        if len(normalized) > 80:
            normalized = normalized[:80] + "..."
        
        lang_str = f"{language} " if language else ""
        return f"{verb} {lang_str}{normalized}".strip()
    
    def _create_objective_ru(
        self, query: str, task_type: TaskType, language: Optional[str]
    ) -> str:
        """Создать objective на RU."""
        verbs = {
            TaskType.CREATE: "Создать",
            TaskType.EDIT: "Изменить",
            TaskType.FIX: "Исправить",
            TaskType.REFACTOR: "Рефакторить",
            TaskType.EXPLAIN: "Объяснить",
            TaskType.OPTIMIZE: "Оптимизировать",
            TaskType.DEBUG: "Отладить",
            TaskType.TEST: "Написать тесты",
            TaskType.DOCUMENT: "Документировать",
            TaskType.CONVERT: "Конвертировать",
            TaskType.REVIEW: "Проверить",
            TaskType.SEARCH: "Найти",
        }
        
        verb = verbs.get(task_type, "Создать")
        
        normalized = query
        prefixes = [r"^(пожалуйста\s+)?(напиши|создай|сделай|исправь|найди)\s+(мне\s+)?"]
        
        for p in prefixes:
            normalized = re.sub(p, "", normalized, flags=re.IGNORECASE)
        
        if len(normalized) > 80:
            normalized = normalized[:80] + "..."
        
        lang_str = f"на {language}: " if language else ""
        return f"{verb} {lang_str}{normalized}".strip()
    
    def _estimate_complexity(self, query: str, requirements: List[str]) -> Complexity:
        """Оценить сложность."""
        score = 0
        
        if len(query) > 300:
            score += 2
        elif len(query) > 150:
            score += 1
        
        score += len(requirements) // 2
        
        complex_kw = [
            r"многопоточн|async|concurrent|parallel",
            r"распределен|distributed|microservice",
            r"машинн|learning|neural|ml|ai",
            r"архитектур|architecture|pattern",
            r"безопасност|security|auth|crypto",
        ]
        
        for kw in complex_kw:
            if re.search(kw, query, re.IGNORECASE):
                score += 1
        
        if score >= 4:
            return Complexity.HIGH
        elif score >= 2:
            return Complexity.MEDIUM
        return Complexity.LOW
    
    def _calculate_confidence(
        self, task_confidence: float, language: Optional[str], framework: Optional[str]
    ) -> float:
        """Вычислить общую уверенность."""
        confidence = task_confidence
        
        if language:
            confidence += 0.1
        if framework:
            confidence += 0.1
        
        return min(confidence, 1.0)


# =============================================================================
# УРОВЕНЬ 2: FUZZY CRYSTALLIZER
# =============================================================================

class FuzzyCrystallizer:
    """
    Fuzzy matching для сленга и разговорных форм.
    Обрабатывает ~20% нестандартных запросов.
    """
    
    SLANG_SYNONYMS = {
        "create": [
            "забабахай", "накидай", "сваргань", "замути", "запили",
            "накатай", "сбацай", "нафигачь", "залепи", "склепай",
        ],
        "fix": [
            "почини", "пофикси", "поправь", "вылечи", "подлатай",
        ],
        "optimize": [
            "ускорь", "разгони", "прокачай", "оптимизни", "бустани",
        ],
        "explain": [
            "растолкуй", "разжуй", "втолкуй", "раскрой",
        ],
        "refactor": [
            "перелопать", "причесать", "причеши", "облагородь", "подчисти",
        ],
        "debug": [
            "продебажь", "отловь", "вылови",
        ],
        "test": [
            "затесть", "протестируй", "оттестируй",
        ],
        "search": [
            "отыщи", "разыщи", "выискай",
        ],
    }
    
    def __init__(self):
        self._fuzzy_available = False
        self._fuzz = None
        self._process = None
        self._init_fuzzy()
    
    def _init_fuzzy(self):
        """Инициализировать rapidfuzz."""
        try:
            from rapidfuzz import fuzz, process
            self._fuzz = fuzz
            self._process = process
            self._fuzzy_available = True
        except ImportError:
            pass
    
    @property
    def is_available(self) -> bool:
        return self._fuzzy_available
    
    def enhance(self, query: str, result: CrystallizedQuery) -> CrystallizedQuery:
        """Улучшить результат с помощью fuzzy matching."""
        if not self._fuzzy_available:
            return result
        
        query_lower = query.lower()
        confidence_boost = 0.0
        
        for task_type, synonyms in self.SLANG_SYNONYMS.items():
            match = self._process.extractOne(
                query_lower, synonyms, scorer=self._fuzz.partial_ratio
            )
            if match and match[1] >= 70:
                result.task_type = TaskType[task_type.upper()]
                confidence_boost = max(confidence_boost, (match[1] - 70) / 100)
                result.detection_method = "fuzzy"
                break
        
        result.confidence = min(result.confidence + confidence_boost, 1.0)
        
        return result


# =============================================================================
# УРОВЕНЬ 3: CLARIFICATION GENERATOR
# =============================================================================

class ClarificationGenerator:
    """Генератор уточняющих вопросов."""
    
    TEMPLATES = {
        "no_language": (
            "На каком языке программирования написать код?\n"
            "Например: Python, JavaScript, Java, Go"
        ),
        "no_task_type": (
            "Уточните, что нужно сделать:\n"
            "• Создать новый код\n"
            "• Исправить ошибку\n"
            "• Оптимизировать\n"
            "• Объяснить"
        ),
        "ambiguous": (
            "Ваш запрос неоднозначен. Уточните:\n"
            "• Что конкретно должен делать код?\n"
            "• Какие входные/выходные данные?"
        ),
        "need_context": (
            "Нужен дополнительный контекст:\n"
            "• Покажите текущий код\n"
            "• Опишите ошибку"
        ),
    }
    
    def generate(self, result: CrystallizedQuery) -> str:
        """Сгенерировать уточняющий вопрос."""
        if result.confidence < 0.4:
            return self.TEMPLATES["ambiguous"]
        if not result.language:
            return self.TEMPLATES["no_language"]
        if result.task_type == TaskType.UNKNOWN:
            return self.TEMPLATES["no_task_type"]
        if result.task_type == TaskType.FIX and not result.error_message:
            return self.TEMPLATES["need_context"]
        return self.TEMPLATES["ambiguous"]


# =============================================================================
# PROMPT BUILDER
# =============================================================================

class PromptBuilder:
    """Построитель оптимизированных промптов."""
    
    SYSTEM_PROMPT = """You are a Senior {language} Developer with 15+ years of experience.

## Quality Standards
- Write clean, idiomatic {language} code
- Follow {language} best practices
- Include proper error handling
- Add clear comments for complex logic

## Output Format
- Provide complete, working code
- Include brief explanation
- Add example usage if helpful"""

    TASK_TEMPLATES = {
        TaskType.CREATE: """## Task: {objective}

### Requirements
{requirements}
{constraints}

### Instructions
Create a complete, production-ready implementation with error handling and documentation.""",

        TaskType.FIX: """## Task: {objective}

### Error Context
{error_context}

### Requirements
{requirements}

### Instructions
1. Identify the root cause
2. Explain why the error occurs
3. Provide the corrected code""",

        TaskType.SEARCH: """## Task: {objective}

### Search Pattern
{search_pattern}

### Instructions
Search for the specified pattern and show:
1. File locations
2. Matching lines
3. Context around matches""",

        TaskType.EDIT: """## Task: {objective}

### Requirements
{requirements}
{constraints}

### CRITICAL INSTRUCTIONS - USE TOOLS!
You MUST use tools to complete this task:

1. **READ** the target file first to understand its structure
2. **FIND** the exact location where to make changes
3. **EDIT** the file using the edit tool with old_string/new_string
4. **VERIFY** the change was applied correctly

DO NOT just generate example code!
You have access to: read, edit, grep, glob tools.
USE THEM to modify the actual file.""",
    }
    
    def build(self, result: CrystallizedQuery) -> str:
        """Построить оптимизированный промпт."""
        template = self.TASK_TEMPLATES.get(
            result.task_type,
            self.TASK_TEMPLATES[TaskType.CREATE]
        )
        
        req_str = "\n".join(f"- {r}" for r in result.requirements) if result.requirements else "- Follow best practices"
        
        constr_str = ""
        if result.constraints:
            constr_str = "\n### Constraints\n" + "\n".join(f"- {c}" for c in result.constraints)
        
        error_ctx = ""
        if result.error_message:
            error_ctx = f"```\n{result.error_message}\n```"
        
        search_pattern = result.search_pattern or "N/A"
        
        prompt = template.format(
            objective=result.objective,
            requirements=req_str,
            constraints=constr_str,
            error_context=error_ctx,
            search_pattern=search_pattern,
        )
        
        system = self.SYSTEM_PROMPT.format(language=result.language)
        
        return f"{system}\n\n{prompt}".strip()


# =============================================================================
# ГЛАВНЫЙ КЛАСС: HYBRID CRYSTALLIZER с LRU CACHE
# =============================================================================

class HybridCrystallizer:
    """
    3-уровневый гибридный кристаллизатор запросов с LRU-кэшированием.
    
    Уровень 0: Cache (0ms)       → Повторные запросы
    Уровень 1: Regex (0.1ms)     → 70% запросов
    Уровень 2: Fuzzy (10-50ms)   → 20% запросов  
    Уровень 3: Clarification     → 10% запросов
    
    Использование:
        crystallizer = HybridCrystallizer()
        result = crystallizer.crystallize("забабахай сортировку на питоне")
        
        # Статистика кэша
        stats = crystallizer.cache_stats()
        print(f"Hit rate: {stats['hit_rate']:.1%}")
    """
    
    CONFIDENCE_HIGH = 0.8
    CONFIDENCE_MEDIUM = 0.5
    CACHE_SIZE = 1000
    
    def __init__(self, default_language: str = "python"):
        self.default_language = default_language
        
        # Компоненты
        self.regex_crystallizer = RegexCrystallizer()
        self.fuzzy_crystallizer = FuzzyCrystallizer()
        self.clarification_generator = ClarificationGenerator()
        self.prompt_builder = PromptBuilder()
        
        # Статистика кэша
        self._cache_hits = 0
        self._cache_misses = 0
    
    @staticmethod
    def _normalize_query(query: str) -> str:
        """Нормализовать запрос для кэширования."""
        return query.lower().strip()
    
    @staticmethod
    def _query_hash(query: str, context_hash: str) -> str:
        """Создать хэш для кэша."""
        combined = f"{query}|{context_hash}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    @staticmethod
    def _context_hash(context: Optional[Dict]) -> str:
        """Создать хэш контекста."""
        if not context:
            return "none"
        # Хэшируем только ключевые поля
        key_fields = ["language", "code", "error"]
        parts = [f"{k}={context.get(k, '')}" for k in key_fields if context.get(k)]
        return hashlib.md5("|".join(parts).encode()).hexdigest()[:8]
    
    # LRU-кэш для внутренней функции кристаллизации
    @lru_cache(maxsize=1000)
    def _cached_crystallize(self, query_hash: str, query: str, context_hash: str) -> Tuple:
        """
        Кэшированная кристаллизация (возвращает tuple для hashability).
        
        Returns:
            Tuple с данными для восстановления CrystallizedQuery
        """
        # Восстановить контекст из хэша (упрощённо - только язык)
        context = {}
        if context_hash != "none":
            # Для полного решения нужен отдельный кэш контекстов
            pass
        
        # Выполнить кристаллизацию
        result = self._do_crystallize(query, context)
        
        # Вернуть как tuple (hashable)
        return (
            result.task_type.value,
            result.objective,
            result.objective_ru,
            result.language,
            result.framework,
            tuple(result.requirements),
            tuple(result.constraints),
            result.confidence,
            result.complexity.value,
            result.detection_method,
            result.search_pattern,
            result.search_description,
            result.needs_clarification,
            result.clarification_question,
            result.optimized_prompt,
        )
    
    def _tuple_to_result(self, query: str, data: Tuple) -> CrystallizedQuery:
        """Восстановить CrystallizedQuery из tuple."""
        return CrystallizedQuery(
            original_query=query,
            task_type=TaskType(data[0]),
            objective=data[1],
            objective_ru=data[2],
            language=data[3],
            framework=data[4],
            requirements=list(data[5]),
            constraints=list(data[6]),
            confidence=data[7],
            complexity=Complexity(data[8]),
            detection_method=data[9],
            search_pattern=data[10],
            search_description=data[11],
            needs_clarification=data[12],
            clarification_question=data[13],
            optimized_prompt=data[14],
            cached=True,
        )
    
    def _do_crystallize(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> CrystallizedQuery:
        """Фактическая кристаллизация (без кэша)."""
        context = context or {}
        
        # Уровень 1: Regex
        result = self.regex_crystallizer.crystallize(query, context)
        
        if result.confidence >= self.CONFIDENCE_HIGH:
            result.optimized_prompt = self.prompt_builder.build(result)
            return result
        
        # Уровень 2: Fuzzy
        if self.fuzzy_crystallizer.is_available:
            result = self.fuzzy_crystallizer.enhance(query, result)
            
            if result.confidence >= self.CONFIDENCE_HIGH:
                result.optimized_prompt = self.prompt_builder.build(result)
                return result
        
        # Уровень 3: Clarification
        if result.confidence < self.CONFIDENCE_MEDIUM:
            result.needs_clarification = True
            result.clarification_question = self.clarification_generator.generate(result)
        
        result.optimized_prompt = self.prompt_builder.build(result)
        return result
    
    def crystallize(
        self, 
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> CrystallizedQuery:
        """
        Кристаллизовать запрос с LRU-кэшированием.
        
        Args:
            query: Исходный запрос пользователя
            context: Дополнительный контекст
            
        Returns:
            CrystallizedQuery с результатом
        """
        # Нормализация
        query_normalized = self._normalize_query(query)
        ctx_hash = self._context_hash(context)
        q_hash = self._query_hash(query_normalized, ctx_hash)
        
        # Проверка кэша
        cache_info = self._cached_crystallize.cache_info()
        
        # Вызов кэшированной функции
        try:
            cached_data = self._cached_crystallize(q_hash, query_normalized, ctx_hash)
            
            # Проверить, был ли это cache hit
            new_cache_info = self._cached_crystallize.cache_info()
            if new_cache_info.hits > cache_info.hits:
                self._cache_hits += 1
                result = self._tuple_to_result(query, cached_data)
                result.detection_method = "cache"
            else:
                self._cache_misses += 1
                result = self._tuple_to_result(query, cached_data)
            
            return result
            
        except Exception:
            # Fallback без кэша
            self._cache_misses += 1
            return self._do_crystallize(query, context)
    
    def get_prompt(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Быстрый метод для получения промпта."""
        result = self.crystallize(query, context)
        return result.optimized_prompt
    
    def cache_stats(self) -> Dict[str, Any]:
        """Получить статистику кэша."""
        cache_info = self._cached_crystallize.cache_info()
        total = self._cache_hits + self._cache_misses
        
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "total": total,
            "hit_rate": self._cache_hits / max(total, 1),
            "cache_size": cache_info.currsize,
            "max_size": cache_info.maxsize,
            "lru_hits": cache_info.hits,
            "lru_misses": cache_info.misses,
        }
    
    def clear_cache(self):
        """Очистить кэш."""
        self._cached_crystallize.cache_clear()
        self._cache_hits = 0
        self._cache_misses = 0


# =============================================================================
# ФУНКЦИИ БЫСТРОГО ДОСТУПА
# =============================================================================

# Глобальный singleton
_crystallizer: Optional[HybridCrystallizer] = None

def get_crystallizer() -> HybridCrystallizer:
    """Получить singleton кристаллизатора."""
    global _crystallizer
    if _crystallizer is None:
        _crystallizer = HybridCrystallizer()
    return _crystallizer

def crystallize(query: str, context: Optional[Dict] = None) -> CrystallizedQuery:
    """Быстрая кристаллизация через singleton."""
    return get_crystallizer().crystallize(query, context)

def translate_search_to_grep(query: str, path: str = ".") -> Optional[Dict[str, Any]]:
    """Перевести поисковый запрос в grep параметры."""
    result = crystallize(query)
    
    if result.task_type != TaskType.SEARCH:
        return None
    
    if not result.search_pattern:
        return None
    
    return {
        "pattern": result.search_pattern,
        "path": path,
        "glob": "*.py",
        "description": result.search_description,
        "confidence": result.confidence,
    }


# =============================================================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ
# =============================================================================

QueryCrystallizer = HybridCrystallizer
CrystallizerHandler = HybridCrystallizer


# =============================================================================
# ТЕСТЫ
# =============================================================================

def test_hybrid_crystallizer():
    """Тестирование с кэшем."""
    
    print("=" * 70)
    print("HYBRID QUERY CRYSTALLIZER v2.1 TESTS (with LRU Cache)")
    print("=" * 70)
    
    crystallizer = HybridCrystallizer()
    
    print(f"\nFuzzy: {'[OK]' if crystallizer.fuzzy_crystallizer.is_available else '[NO]'}")
    print(f"Cache size: {crystallizer.CACHE_SIZE}")
    
    tests = [
        ("напиши функцию сортировки на python", TaskType.CREATE, "python"),
        ("fix the bug in my code", TaskType.FIX, None),
        ("найди все классы с наследованием", TaskType.SEARCH, None),
        ("забабахай сортировку на питоне", TaskType.CREATE, "python"),
        ("оптимизируй этот sql запрос", TaskType.OPTIMIZE, "sql"),
    ]
    
    print(f"\n{'Query':<45} {'Type':<10} {'Lang':<8} {'Method':<8} {'Conf':<6}")
    print("-" * 85)
    
    # Первый прогон
    for query, exp_type, exp_lang in tests:
        result = crystallizer.crystallize(query)
        print(f"{query[:44]:<45} {result.task_type.value:<10} {result.language or '-':<8} "
              f"{result.detection_method:<8} {result.confidence:.2f}")
    
    print("\n" + "-" * 85)
    print("Second pass (should be cached):")
    print("-" * 85)
    
    # Второй прогон (из кэша)
    for query, _, _ in tests:
        result = crystallizer.crystallize(query)
        print(f"{query[:44]:<45} {result.task_type.value:<10} {result.language or '-':<8} "
              f"{result.detection_method:<8} {result.confidence:.2f}")
    
    # Статистика
    stats = crystallizer.cache_stats()
    print(f"\n{'='*70}")
    print("CACHE STATISTICS:")
    print(f"  Hits:     {stats['hits']}")
    print(f"  Misses:   {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.1%}")
    print(f"  Size:     {stats['cache_size']}/{stats['max_size']}")
    
    # Тест поиска
    print(f"\n{'='*70}")
    print("SEARCH TRANSLATION TEST:")
    print("-" * 70)
    
    search_tests = [
        "найди все классы с наследованием в core/",
        "найди все функции async",
        "покажи все импорты",
        "найди TODO комментарии",
    ]
    
    for query in search_tests:
        grep = translate_search_to_grep(query)
        if grep:
            print(f"  {query[:40]}")
            print(f"    -> pattern: {grep['pattern']}")
            print(f"    -> {grep['description']}")
        else:
            print(f"  {query[:40]} -> NOT A SEARCH QUERY")
    
    print("=" * 70)


if __name__ == "__main__":
    test_hybrid_crystallizer()
