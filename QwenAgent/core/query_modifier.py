"""
Query Modifier Engine for QwenCode
===================================

Автоматическая модификация запросов пользователя:
- Добавление языковых суффиксов ("Ответь на русском")
- Автоматические префиксы для определённых типов запросов
- Настраиваемые модификаторы через .qwencoderules

Использование:
    from core.query_modifier import QueryModifierEngine
    
    engine = QueryModifierEngine()
    engine.set_language("ru")
    
    modified = engine.process("fix bug in parser.py")
    # -> "fix bug in parser.py Ответь на русском языке."

Интеграция с QwenCodeAgent:
    В __init__:
        self.query_modifier = QueryModifierEngine()
        self.query_modifier.load_from_config(config)
    
    В process():
        modified_input = self.query_modifier.process(user_input)

Author: QwenCode Team
Version: 1.0.0
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from enum import Enum
from pathlib import Path
import json


class ModifierPriority(Enum):
    """Приоритет применения модификатора."""
    FIRST = 0      # Применяется первым
    NORMAL = 50    # Обычный приоритет
    LAST = 100     # Применяется последним


@dataclass
class QueryModifier:
    """
    Модификатор запроса.
    
    Attributes:
        name: Уникальное имя модификатора
        pattern: Regex паттерн для срабатывания (None = всегда)
        prefix: Текст для добавления в начало
        suffix: Текст для добавления в конец
        replacement: Замена всего запроса (если задано)
        transform: Функция трансформации (query) -> query
        enabled: Включен ли модификатор
        priority: Приоритет применения
        description: Описание для пользователя
    """
    name: str
    pattern: Optional[str] = None
    prefix: str = ""
    suffix: str = ""
    replacement: Optional[str] = None
    transform: Optional[Callable[[str], str]] = None
    enabled: bool = True
    priority: ModifierPriority = ModifierPriority.NORMAL
    description: str = ""
    
    # Паттерны-исключения (не применять если совпадает)
    exclude_patterns: List[str] = field(default_factory=list)
    
    def matches(self, query: str) -> bool:
        """Проверить, применим ли модификатор к запросу."""
        if not self.enabled:
            return False
        
        # Проверить исключения
        for exc_pattern in self.exclude_patterns:
            if re.search(exc_pattern, query, re.IGNORECASE):
                return False
        
        # Если паттерн не задан - применяется всегда
        if self.pattern is None:
            return True
        
        return bool(re.search(self.pattern, query, re.IGNORECASE))
    
    def apply(self, query: str) -> str:
        """Применить модификатор к запросу."""
        if not self.matches(query):
            return query
        
        # Полная замена
        if self.replacement is not None:
            return self.replacement
        
        # Функция трансформации
        if self.transform is not None:
            return self.transform(query)
        
        # Префикс и суффикс
        result = query
        
        if self.prefix and not result.startswith(self.prefix.strip()):
            result = self.prefix + result
        
        if self.suffix and not result.rstrip().endswith(self.suffix.strip().rstrip('.')):
            result = result.rstrip() + self.suffix
        
        return result


class QueryModifierEngine:
    """
    Движок автоматической модификации запросов.
    
    Применяет модификаторы к запросам пользователя для:
    - Автоматического добавления языковых инструкций
    - Форматирования запросов определённых типов
    - Пользовательских трансформаций
    """
    
    # Языковые суффиксы
    LANGUAGE_SUFFIXES = {
        "ru": " Ответь на русском языке.",
        "en": " Answer in English.",
        "zh": " 请用中文回答。",
        "de": " Antworte auf Deutsch.",
        "fr": " Réponds en français.",
        "es": " Responde en español.",
        "auto": "",  # Автоопределение, без суффикса
    }
    
    # Паттерны, которые уже содержат языковую инструкцию
    LANGUAGE_INSTRUCTION_PATTERNS = [
        r"на русском|по[\-\s]?русски|in russian",
        r"in english|на английском|по[\-\s]?английски",
        r"ответь на|answer in|respond in",
        r"переведи|translate",
    ]
    
    def __init__(self):
        self.modifiers: List[QueryModifier] = []
        self.language: str = "auto"
        self.language_suffix: str = ""
        self.enabled: bool = True
        
        # Статистика
        self.stats = {
            "total_queries": 0,
            "modified_queries": 0,
            "language_suffix_added": 0,
        }
        
        # Загрузить стандартные модификаторы
        self._load_default_modifiers()
    
    def _load_default_modifiers(self):
        """Загрузить стандартные модификаторы."""
        
        # Модификатор для кода: краткий ответ
        self.add_modifier(QueryModifier(
            name="code_brief",
            pattern=r"(fix|исправь|bug|ошибк|error|баг)",
            suffix=" Покажи только исправленный код.",
            enabled=False,  # По умолчанию выключен
            priority=ModifierPriority.NORMAL,
            description="Краткий ответ для исправления кода",
            exclude_patterns=[r"объясни|explain|почему|why"],
        ))
        
        # Модификатор для объяснений
        self.add_modifier(QueryModifier(
            name="explain_simple",
            pattern=r"(объясни|explain|что такое|what is)",
            suffix=" Объясни простыми словами с примерами.",
            enabled=False,
            priority=ModifierPriority.NORMAL,
            description="Простое объяснение с примерами",
        ))
        
        # Автоматический поиск для актуальной информации
        self.add_modifier(QueryModifier(
            name="auto_search",
            pattern=r"(latest|newest|current|recent|2024|2025|2026|новости|последн|актуальн)",
            prefix="[SEARCH] ",
            enabled=True,
            priority=ModifierPriority.FIRST,
            description="Автоматический веб-поиск для актуальной информации",
            exclude_patterns=[r"^\[SEARCH\]"],  # Уже есть префикс
        ))
        
        # Модификатор для рефакторинга
        self.add_modifier(QueryModifier(
            name="refactor_deep",
            pattern=r"(refactor|рефактор|redesign|переделай|перепиши)",
            prefix="[DEEP3] ",
            enabled=True,
            priority=ModifierPriority.FIRST,
            description="Глубокий анализ для рефакторинга (DEEP3)",
            exclude_patterns=[r"^\[DEEP"],
        ))
        
        # Модификатор для перевода
        self.add_modifier(QueryModifier(
            name="translate_context",
            pattern=r"(переведи|translate|перевод)",
            suffix=" Сохрани форматирование и блоки кода.",
            enabled=True,
            priority=ModifierPriority.NORMAL,
            description="Сохранение форматирования при переводе",
        ))
    
    def add_modifier(self, modifier: QueryModifier):
        """Добавить модификатор."""
        # Удалить существующий с таким же именем
        self.modifiers = [m for m in self.modifiers if m.name != modifier.name]
        self.modifiers.append(modifier)
        
        # Отсортировать по приоритету
        self.modifiers.sort(key=lambda m: m.priority.value)
    
    def remove_modifier(self, name: str) -> bool:
        """Удалить модификатор по имени."""
        initial_count = len(self.modifiers)
        self.modifiers = [m for m in self.modifiers if m.name != name]
        return len(self.modifiers) < initial_count
    
    def get_modifier(self, name: str) -> Optional[QueryModifier]:
        """Получить модификатор по имени."""
        for m in self.modifiers:
            if m.name == name:
                return m
        return None
    
    def enable_modifier(self, name: str, enabled: bool = True) -> bool:
        """Включить/выключить модификатор."""
        modifier = self.get_modifier(name)
        if modifier:
            modifier.enabled = enabled
            return True
        return False
    
    def set_language(self, lang: str):
        """
        Установить язык ответов.
        
        Args:
            lang: Код языка (ru, en, auto, etc.)
        """
        self.language = lang.lower()
        self.language_suffix = self.LANGUAGE_SUFFIXES.get(
            self.language, 
            f" Answer in {lang}."
        )
    
    def _has_language_instruction(self, query: str) -> bool:
        """Проверить, содержит ли запрос языковую инструкцию."""
        for pattern in self.LANGUAGE_INSTRUCTION_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        return False
    
    def _is_code_only(self, query: str) -> bool:
        """Проверить, является ли запрос только кодом."""
        # Если запрос начинается с ``` или содержит только код
        if query.strip().startswith('```'):
            return True
        # Если это команда
        if query.strip().startswith('/'):
            return True
        return False
    
    def _is_special_command(self, query: str) -> bool:
        """Проверить, является ли запрос специальной командой или tool-командой."""
        special_patterns = [
            r"^/",                    # Команды /help, /mode, etc.
            r"^\d+\s*[\+\-\*\/]",    # Математика
            r"^(hi|hello|привет|ping|pong)\s*$",  # Приветствия
            # Tool commands - PatternRouter handles these, don't modify
            r"^(git|grep|read|find|ls|glob|edit|write|bash|cat|cd|mkdir|rm|cp|mv|touch|pip|python|npm|node|docker|kubectl)\s",
        ]
        for pattern in special_patterns:
            if re.match(pattern, query.strip(), re.IGNORECASE):
                return True
        return False
    
    def process(self, query: str) -> str:
        """
        Применить все модификаторы к запросу.
        
        Args:
            query: Исходный запрос пользователя
            
        Returns:
            Модифицированный запрос
        """
        if not self.enabled or not query:
            return query
        
        self.stats["total_queries"] += 1
        original_query = query
        result = query.strip()
        
        # Не модифицировать специальные команды
        if self._is_special_command(result):
            return result
        
        # Не модифицировать чистый код
        if self._is_code_only(result):
            return result
        
        # Применить все активные модификаторы
        for modifier in self.modifiers:
            if modifier.matches(result):
                result = modifier.apply(result)
        
        # Добавить языковой суффикс (если нужно)
        if (self.language_suffix and 
            self.language != "auto" and
            not self._has_language_instruction(result) and
            self.language_suffix.strip() not in result):
            
            result = result.rstrip() + self.language_suffix
            self.stats["language_suffix_added"] += 1
        
        # Обновить статистику
        if result != original_query:
            self.stats["modified_queries"] += 1
        
        return result
    
    def load_from_config(self, config: Dict[str, Any]):
        """
        Загрузить настройки из конфигурации.
        
        Args:
            config: Словарь конфигурации (из .qwencoderules)
        """
        modifiers_config = config.get("query_modifiers", {})
        
        # Язык
        if "language" in modifiers_config:
            self.set_language(modifiers_config["language"])
        
        # Включение/выключение
        if "enabled" in modifiers_config:
            self.enabled = modifiers_config["enabled"]
        
        # Автоматический русский
        if modifiers_config.get("auto_russian", False):
            self.set_language("ru")
        
        # Краткий режим для кода
        if modifiers_config.get("code_only", False):
            self.enable_modifier("code_brief", True)
        
        # Пользовательские модификаторы
        custom_modifiers = modifiers_config.get("custom_modifiers", [])
        for mod_config in custom_modifiers:
            self.add_modifier(QueryModifier(
                name=mod_config.get("name", f"custom_{len(self.modifiers)}"),
                pattern=mod_config.get("pattern"),
                prefix=mod_config.get("prefix", ""),
                suffix=mod_config.get("suffix", ""),
                enabled=mod_config.get("enabled", True),
                description=mod_config.get("description", ""),
            ))
    
    def load_from_file(self, filepath: str):
        """Загрузить настройки из файла."""
        path = Path(filepath)
        if not path.exists():
            return
        
        try:
            import yaml
            with open(path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                self.load_from_config(config)
        except ImportError:
            # Если yaml не установлен, попробовать JSON
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.load_from_config(config)
            except:
                pass
        except Exception as e:
            print(f"[QueryModifier] Error loading config: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику."""
        return {
            **self.stats,
            "modification_rate": (
                self.stats["modified_queries"] / max(self.stats["total_queries"], 1) * 100
            ),
            "active_modifiers": sum(1 for m in self.modifiers if m.enabled),
            "total_modifiers": len(self.modifiers),
            "language": self.language,
        }
    
    def list_modifiers(self) -> List[Dict[str, Any]]:
        """Получить список всех модификаторов."""
        return [
            {
                "name": m.name,
                "enabled": m.enabled,
                "pattern": m.pattern,
                "prefix": m.prefix,
                "suffix": m.suffix,
                "description": m.description,
                "priority": m.priority.name,
            }
            for m in self.modifiers
        ]
    
    def __repr__(self) -> str:
        active = sum(1 for m in self.modifiers if m.enabled)
        return f"QueryModifierEngine(lang={self.language}, modifiers={active}/{len(self.modifiers)})"


# =============================================================================
# КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ МОДИФИКАТОРАМИ
# =============================================================================

class ModifierCommands:
    """
    Команды для управления модификаторами через чат.
    
    Использование:
        /lang ru          - Установить русский язык
        /lang en          - Установить английский
        /lang auto        - Автоопределение
        /modifiers        - Список модификаторов
        /modifier on X    - Включить модификатор X
        /modifier off X   - Выключить модификатор X
        /russian on       - Включить автоматический русский
        /russian off      - Выключить
    """
    
    COMMANDS = {
        r"^/lang\s+(ru|en|auto|zh|de|fr|es)$": "set_language",
        r"^/modifiers?\s*$": "list_modifiers",
        r"^/modifier\s+(on|off)\s+(\w+)$": "toggle_modifier",
        r"^/russian\s+(on|off)$": "toggle_russian",
        r"^/brief\s+(on|off)$": "toggle_brief",
    }
    
    def __init__(self, engine: QueryModifierEngine):
        self.engine = engine
    
    def handle(self, query: str) -> Optional[str]:
        """
        Обработать команду.
        
        Returns:
            Ответ на команду или None если это не команда
        """
        query = query.strip()
        
        for pattern, handler_name in self.COMMANDS.items():
            match = re.match(pattern, query, re.IGNORECASE)
            if match:
                handler = getattr(self, f"_handle_{handler_name}", None)
                if handler:
                    return handler(match)
        
        return None
    
    def _handle_set_language(self, match) -> str:
        lang = match.group(1).lower()
        self.engine.set_language(lang)
        
        lang_names = {
            "ru": "Russian (RU)",
            "en": "English (EN)",
            "auto": "Auto-detect",
            "zh": "Chinese (ZH)",
            "de": "Deutsch (DE)",
            "fr": "Francais (FR)",
            "es": "Espanol (ES)",
        }

        return f"[OK] Language: {lang_names.get(lang, lang)}"
    
    def _handle_list_modifiers(self, match) -> str:
        modifiers = self.engine.list_modifiers()
        
        lines = ["**Query Modifiers:**\n"]

        for m in modifiers:
            status = "[ON]" if m["enabled"] else "[OFF]"
            lines.append(f"{status} **{m['name']}**")
            if m["description"]:
                lines.append(f"   _{m['description']}_")
            if m["pattern"]:
                lines.append(f"   Pattern: `{m['pattern']}`")
            lines.append("")

        lines.append(f"\nLanguage: {self.engine.language}")
        lines.append(f"Stats: {self.engine.stats['modified_queries']}/{self.engine.stats['total_queries']} queries modified")
        
        return "\n".join(lines)
    
    def _handle_toggle_modifier(self, match) -> str:
        action = match.group(1).lower()
        name = match.group(2)
        
        enabled = action == "on"
        
        if self.engine.enable_modifier(name, enabled):
            status = "ON" if enabled else "OFF"
            return f"Modifier **{name}** [{status}]"
        else:
            return f"[ERROR] Modifier **{name}** not found"
    
    def _handle_toggle_russian(self, match) -> str:
        action = match.group(1).lower()
        
        if action == "on":
            self.engine.set_language("ru")
            return "[OK] Auto-Russian **ON**\nAll responses in Russian."
        else:
            self.engine.set_language("auto")
            return "[OK] Auto-Russian **OFF**"

    def _handle_toggle_brief(self, match) -> str:
        action = match.group(1).lower()
        enabled = action == "on"

        self.engine.enable_modifier("code_brief", enabled)

        if enabled:
            return "[OK] Brief mode **ON**\nCode-only responses enabled."
        else:
            return "[OK] Brief mode **OFF**"


# =============================================================================
# ТЕСТИРОВАНИЕ
# =============================================================================

def test_query_modifier():
    """Тестирование движка модификации запросов."""
    
    print("=" * 60)
    print("QUERY MODIFIER ENGINE TESTS")
    print("=" * 60)
    
    engine = QueryModifierEngine()
    engine.set_language("ru")
    
    tests = [
        # (input, expected_contains)
        ("fix bug in parser.py", "на русском"),
        ("explain what is Python", "на русском"),
        ("2+2", "2+2"),  # Не модифицируется
        ("/help", "/help"),  # Не модифицируется
        ("привет", "привет"),  # Не модифицируется
        ("latest news about AI", "[SEARCH]"),  # Автопоиск
        ("refactor this code", "[DEEP]"),  # Глубокий анализ
        ("переведи на английский", "Сохрани форматирование"),  # Перевод
        ("объясни на русском что такое API", "объясни"),  # Уже есть язык
    ]
    
    passed = 0
    failed = 0
    
    for input_query, expected in tests:
        result = engine.process(input_query)
        
        if expected in result:
            status = "[OK]"
            passed += 1
        else:
            status = "[FAIL]"
            failed += 1

        print(f"{status} '{input_query[:30]}...'")
        print(f"   -> '{result[:60]}...'")
        print()
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print(f"Stats: {engine.get_stats()}")
    print("=" * 60)
    
    # Тест команд
    print("\nTesting commands:")
    commands = ModifierCommands(engine)
    
    cmd_tests = [
        "/lang en",
        "/modifiers",
        "/russian on",
        "/modifier on code_brief",
    ]
    
    for cmd in cmd_tests:
        result = commands.handle(cmd)
        if result:
            print(f"[OK] {cmd}")
            print(f"   -> {result[:50]}...")
        else:
            print(f"[FAIL] {cmd} - no response")
    
    print("=" * 60)


if __name__ == "__main__":
    test_query_modifier()
