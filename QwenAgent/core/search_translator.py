# -*- coding: utf-8 -*-
"""
Search Query Translator
=======================

Translates natural language search queries into grep/regex patterns.

Examples:
    "найди все классы" -> pattern: "class \w+:"
    "найди функции async" -> pattern: "async def \w+"
    "покажи импорты" -> pattern: "^import |^from .* import"

Usage:
    from core.search_translator import translate_search_query

    result = translate_search_query("найди все классы с наследованием")
    print(result)  # {'pattern': 'class \\w+\\([^)]+\\):', 'description': 'Classes with inheritance'}
"""

import re
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass


@dataclass
class SearchTranslation:
    """Result of search query translation."""
    original: str
    pattern: str
    description: str
    file_glob: str = "*.py"
    confidence: float = 1.0


# =============================================================================
# SEARCH PATTERNS DICTIONARY
# =============================================================================

# Format: (keywords_tuple, pattern, description, file_glob)
# NOTE: More specific patterns MUST come before generic ones!
SEARCH_PATTERNS: List[Tuple[tuple, str, str, str]] = [
    # Classes - SPECIFIC patterns first
    (("наследован", "наследуется", "inherit", "extends", "базов", "parent"),
     r"class \w+\([^)]+\):",
     "Classes with inheritance",
     "*.py"),

    (("класс", "классы", "class"),
     r"class \w+:",
     "Class definitions",
     "*.py"),

    (("dataclass", "датакласс"),
     r"@dataclass",
     "Dataclass decorators",
     "*.py"),

    # Functions
    (("функци", "function", "def", "метод"),
     r"def \w+\(",
     "Function definitions",
     "*.py"),

    (("async", "асинхрон", "await"),
     r"async def \w+\(",
     "Async function definitions",
     "*.py"),

    (("__init__", "конструктор", "инициализ"),
     r"def __init__\(",
     "Constructor methods",
     "*.py"),

    # Imports
    (("импорт", "import", "подключ"),
     r"^(import |from .* import)",
     "Import statements",
     "*.py"),

    # Decorators
    (("декоратор", "decorator", "@"),
     r"@\w+",
     "Decorators",
     "*.py"),

    # Comments & Docs
    (("todo", "fixme", "hack"),
     r"#.*(TODO|FIXME|HACK|XXX)",
     "TODO comments",
     "*.py"),

    (("docstring", "документац", "описани"),
     r'""".*"""',
     "Docstrings",
     "*.py"),

    # Error handling
    (("exception", "исключени", "raise", "error"),
     r"(raise \w+|except \w+)",
     "Exception handling",
     "*.py"),

    (("try", "except", "обработка ошибок"),
     r"(try:|except.*:)",
     "Try/except blocks",
     "*.py"),

    # Variables & Constants
    (("константа", "constant", "UPPER"),
     r"^[A-Z][A-Z_0-9]+ =",
     "Constants (UPPER_CASE)",
     "*.py"),

    (("глобальн", "global"),
     r"^[a-z_]\w* =",
     "Global variables",
     "*.py"),

    # Type hints
    (("тип", "type hint", "typing", "аннотац"),
     r"def \w+\([^)]*:[^)]+\)",
     "Functions with type hints",
     "*.py"),

    # API / Routes
    (("route", "endpoint", "api", "маршрут"),
     r"@(app|blueprint|router)\.(route|get|post|put|delete)",
     "API route definitions",
     "*.py"),

    # Tests
    (("тест", "test", "assert"),
     r"def test_\w+\(",
     "Test functions",
     "*.py"),

    (("pytest", "fixture"),
     r"@pytest\.(fixture|mark)",
     "Pytest decorators",
     "*.py"),

    # Config
    (("config", "конфиг", "настройк", "settings"),
     r"(CONFIG|config|Settings)\s*[=\[]",
     "Configuration definitions",
     "*.py"),

    # Logging
    (("лог", "log", "print", "debug"),
     r"(logging\.\w+|print\(|logger\.)",
     "Logging/print statements",
     "*.py"),
]


# =============================================================================
# TRANSLATOR FUNCTIONS
# =============================================================================

def _normalize_query(query: str) -> str:
    """Normalize query for matching."""
    return query.lower().strip()


def _match_keywords(query: str, keywords: tuple) -> float:
    """
    Calculate match score for keywords.

    Returns:
        Score based on number of matches (higher = better)
    """
    query_lower = query.lower()
    matches = sum(1 for kw in keywords if kw.lower() in query_lower)
    # Return absolute match count to prioritize more specific patterns
    return matches


def translate_search_query(query: str) -> Optional[SearchTranslation]:
    """
    Translate natural language search query to grep pattern.

    Args:
        query: Natural language search query (Russian or English)

    Returns:
        SearchTranslation object or None if no match

    Examples:
        >>> translate_search_query("найди все классы")
        SearchTranslation(pattern="class \\w+:", ...)

        >>> translate_search_query("покажи функции async")
        SearchTranslation(pattern="async def \\w+\\(", ...)
    """
    query_normalized = _normalize_query(query)

    best_match = None
    best_score = 0.0

    for keywords, pattern, description, file_glob in SEARCH_PATTERNS:
        score = _match_keywords(query_normalized, keywords)

        # Require at least one keyword match, prioritize higher scores
        if score > 0 and score > best_score:
            best_score = score
            best_match = SearchTranslation(
                original=query,
                pattern=pattern,
                description=description,
                file_glob=file_glob,
                confidence=min(score / len(keywords), 1.0)
            )

    return best_match


def get_all_patterns() -> List[Dict]:
    """Get all available search patterns for help/documentation."""
    return [
        {
            "keywords": keywords,
            "pattern": pattern,
            "description": description,
            "file_glob": file_glob
        }
        for keywords, pattern, description, file_glob in SEARCH_PATTERNS
    ]


# =============================================================================
# INTEGRATION HELPER
# =============================================================================

def translate_for_grep(query: str, path: str = ".") -> Optional[Dict]:
    """
    Translate query and return grep-ready parameters.

    Args:
        query: Natural language search query
        path: Search path (default: current directory)

    Returns:
        Dict with grep parameters or None

    Example:
        >>> translate_for_grep("найди классы с наследованием", "core/")
        {'pattern': 'class \\w+\\([^)]+\\):', 'path': 'core/', 'glob': '*.py'}
    """
    translation = translate_search_query(query)

    if translation:
        return {
            "pattern": translation.pattern,
            "path": path,
            "glob": translation.file_glob,
            "description": translation.description,
            "confidence": translation.confidence
        }

    return None


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":
    # Test examples
    test_queries = [
        "найди все классы",
        "найди классы с наследованием",
        "покажи функции async",
        "найди импорты",
        "покажи все декораторы",
        "найди TODO комментарии",
        "покажи тесты",
        "найди API routes",
        "покажи константы",
        "find all classes with inheritance",
    ]

    print("=" * 60)
    print("Search Query Translator - Test")
    print("=" * 60)

    for query in test_queries:
        result = translate_search_query(query)
        if result:
            print(f"\n  Query: {query}")
            print(f"  Pattern: {result.pattern}")
            print(f"  Description: {result.description}")
            print(f"  Confidence: {result.confidence:.0%}")
        else:
            print(f"\n  Query: {query}")
            print(f"  [NO MATCH]")
