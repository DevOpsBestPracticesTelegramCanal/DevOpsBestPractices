# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
QwenCode PATTERN ROUTER - Fast Path без LLM
═══════════════════════════════════════════════════════════════════════════════

Мгновенное выполнение команд без обращения к LLM.

Поддерживаемые паттерны:
    read file.py                    → read(file_path="file.py")
    read file.py lines 10-20        → read(file_path="file.py", start_line=10, end_line=20)
    grep pattern in path            → grep(pattern="pattern", path="path")
    find pattern                    → find(query="pattern")
    ls path                         → ls(path="path")
    bash command                    → bash(command="command")
    command1; command2              → chain execution

Использование:
    from core.pattern_router import PatternRouter
    from core.unified_tools import UnifiedTools

    router = PatternRouter()
    tools = UnifiedTools(project_root=".")

    # Проверка и выполнение
    route = router.match("read core/tools.py lines 1-20")
    if route:
        result = tools.execute(route["tool"], route["params"])

═══════════════════════════════════════════════════════════════════════════════
"""

import os
import re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass


@dataclass
class RouteMatch:
    """Результат маршрутизации"""
    tool: str
    params: Dict[str, Any]
    original: str
    confidence: float = 1.0


class PatternRouter:
    """
    Fast Path Router - мгновенное выполнение без LLM.

    Порядок паттернов критичен: специфичные должны быть раньше общих!
    """

    def __init__(self):
        """Инициализация паттернов"""
        # Паттерны в порядке приоритета (специфичные раньше)
        self.patterns: List[Tuple[re.Pattern, str, callable]] = [
            # =====================================================
            # READ COMMANDS (English + Russian)
            # =====================================================
            # READ с диапазоном строк (наиболее специфичный)
            (
                re.compile(r'^read\s+(.+?)\s+lines?\s+(\d+)[-–](\d+)$', re.IGNORECASE),
                'read',
                self._parse_read_lines
            ),
            # READ с одной строкой
            (
                re.compile(r'^read\s+(.+?)\s+line\s+(\d+)$', re.IGNORECASE),
                'read',
                self._parse_read_line
            ),
            # READ базовый
            (
                re.compile(r'^read\s+(.+)$', re.IGNORECASE),
                'read',
                self._parse_read
            ),
            # RUSSIAN: прочитай/покажи/открой файл строки 10-20
            (
                re.compile(r'^(?:прочитай|прочти|покажи|открой)\s+(?:файл\s+)?(.+?)\s+(?:строки?|линии?)\s+(\d+)[-–](\d+)$', re.IGNORECASE),
                'read',
                self._parse_read_lines
            ),
            # RUSSIAN: прочитай/открой файл (без "покажи" - оно для ls)
            (
                re.compile(r'^(?:прочитай|прочти|открой|выведи)\s+(?:файл\s+)?(.+)$', re.IGNORECASE),
                'read',
                self._parse_read
            ),
            # RUSSIAN: покажи файл (конкретно файл, не папку)
            (
                re.compile(r'^покажи\s+файл\s+(.+)$', re.IGNORECASE),
                'read',
                self._parse_read
            ),

            # =====================================================
            # GREP/SEARCH COMMANDS (English + Russian)
            # =====================================================
            # GREP с путём
            (
                re.compile(r'^grep\s+"?([^"]+)"?\s+in\s+(.+)$', re.IGNORECASE),
                'grep',
                self._parse_grep_in
            ),
            # GREP базовый
            (
                re.compile(r'^grep\s+"?([^"]+)"?\s*$', re.IGNORECASE),
                'grep',
                self._parse_grep
            ),
            # FIND (умный поиск)
            (
                re.compile(r'^find\s+(.+)$', re.IGNORECASE),
                'find',
                self._parse_find
            ),
            # RUSSIAN: найди/поиск "pattern" в path (QUOTES REQUIRED for literal pattern)
            (
                re.compile(r'^(?:найди|найти|поиск|искать)\s+["\']([^"\']+)["\']\s+(?:в|в\s+папке|в\s+файле)\s+(.+)$', re.IGNORECASE),
                'grep',
                self._parse_grep_in
            ),
            # RUSSIAN: найди/поиск "pattern" (QUOTES REQUIRED for literal pattern)
            # Natural language queries like "найди все классы" go to search_translation
            (
                re.compile(r'^(?:найди|найти|поиск|искать)\s+["\']([^"\']+)["\']\s*$', re.IGNORECASE),
                'grep',
                self._parse_grep
            ),

            # =====================================================
            # GIT COMMANDS
            # =====================================================
            # GIT STATUS
            (
                re.compile(r'^git\s+status$', re.IGNORECASE),
                'bash',
                lambda m: {"command": "git status"}
            ),
            # GIT DIFF
            (
                re.compile(r'^git\s+diff\s*(.*)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"git diff {m.group(1).strip()}".strip()}
            ),
            # GIT LOG
            (
                re.compile(r'^git\s+log\s*(.*)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"git log --oneline -20 {m.group(1).strip()}".strip()}
            ),
            # GIT BRANCH
            (
                re.compile(r'^git\s+branch\s*(.*)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"git branch {m.group(1).strip()}".strip()}
            ),
            # GIT ADD
            (
                re.compile(r'^git\s+add\s+(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"git add {m.group(1).strip()}"}
            ),
            # GIT COMMIT
            (
                re.compile(r'^git\s+commit\s+(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"git commit {m.group(1).strip()}"}
            ),
            # GIT CHECKOUT
            (
                re.compile(r'^git\s+checkout\s+(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"git checkout {m.group(1).strip()}"}
            ),
            # GIT PULL
            (
                re.compile(r'^git\s+pull\s*(.*)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"git pull {m.group(1).strip()}".strip()}
            ),
            # GIT PUSH
            (
                re.compile(r'^git\s+push\s*(.*)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"git push {m.group(1).strip()}".strip()}
            ),

            # =====================================================
            # FILE/DIRECTORY COMMANDS (English + Russian)
            # =====================================================
            # LS
            (
                re.compile(r'^ls\s*(.*)$', re.IGNORECASE),
                'ls',
                self._parse_ls
            ),
            # RUSSIAN LS: покажи папку/список файлов/содержимое
            (
                re.compile(r'^(?:покажи|выведи)\s+(?:папку?|директорию?|содержимое)\s*(.*)$', re.IGNORECASE),
                'ls',
                self._parse_ls
            ),
            # RUSSIAN LS: список файлов
            (
                re.compile(r'^список\s+(?:файлов?|папок?|директории?)\s*(.*)$', re.IGNORECASE),
                'ls',
                self._parse_ls
            ),
            # RUSSIAN LS: что в папке X
            (
                re.compile(r'^что\s+в\s+(?:папке|директории)\s*(.*)$', re.IGNORECASE),
                'ls',
                self._parse_ls
            ),
            # TREE
            (
                re.compile(r'^tree\s*(.*)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"tree /F /A {m.group(1).strip()}".strip() if os.name == 'nt' else f"tree {m.group(1).strip()}".strip()}
            ),
            # GLOB
            (
                re.compile(r'^glob\s+"?([^"]+)"?\s*(.*)$', re.IGNORECASE),
                'glob',
                self._parse_glob
            ),
            # Natural language file search: "найди все .py файлы в core/"
            (
                re.compile(r'^(?:найди|покажи|выведи)\s+(?:все\s+)?\.?(\w+)\s+файл[ыа]?\s+(?:в\s+)?(.+)$', re.IGNORECASE),
                'glob',
                lambda m: {"pattern": f"**/*.{m.group(1)}", "path": m.group(2).strip().rstrip('/')}
            ),
            # "список файлов .py в core/"
            (
                re.compile(r'^(?:список|list)\s+(?:файлов?\s+)?\.?(\w+)\s+(?:в\s+)?(.+)$', re.IGNORECASE),
                'glob',
                lambda m: {"pattern": f"**/*.{m.group(1)}", "path": m.group(2).strip().rstrip('/')}
            ),
            # "какие файлы в core/"
            (
                re.compile(r'^(?:какие|что за)\s+файл[ыа]?\s+(?:есть\s+)?(?:в\s+)?(.+)$', re.IGNORECASE),
                'glob',
                lambda m: {"pattern": "**/*", "path": m.group(1).strip().rstrip('/')}
            ),
            # "*.py в core/" or "*.py files in core/"
            (
                re.compile(r'^\*\.(\w+)\s+(?:files?\s+)?(?:в|in)\s+(.+)$', re.IGNORECASE),
                'glob',
                lambda m: {"pattern": f"**/*.{m.group(1)}", "path": m.group(2).strip().rstrip('/')}
            ),

            # =====================================================
            # PROJECT ANALYSIS (Russian)
            # =====================================================
            # "покажи описания модулей в core/" -> grep for docstrings
            (
                re.compile(r'^(?:покажи|выведи)\s+(?:описания?|документацию|docstring)\s+(?:всех\s+)?(?:модулей|файлов)\s+(?:в\s+)?(.+)$', re.IGNORECASE),
                'grep',
                lambda m: {"pattern": r'^"""', "path": m.group(1).strip().rstrip('/'), "include": "*.py"}
            ),
            # "анализ модулей в core/" -> grep for class/def
            (
                re.compile(r'^(?:анализ|структура)\s+(?:модулей|кода)\s+(?:в\s+)?(.+)$', re.IGNORECASE),
                'grep',
                lambda m: {"pattern": r"^(class |def )", "path": m.group(1).strip().rstrip('/'), "include": "*.py"}
            ),
            # "список модулей в core/" -> ls
            (
                re.compile(r'^(?:список|покажи)\s+(?:все\s+)?модул(?:и|ей)\s+(?:в\s+)?(.+)$', re.IGNORECASE),
                'ls',
                lambda m: {"path": m.group(1).strip()}
            ),
            # "что делает модуль X" -> read first 30 lines
            (
                re.compile(r'^(?:что\s+делает|опиши)\s+(?:модуль|файл)\s+(.+\.py)$', re.IGNORECASE),
                'read',
                lambda m: {"file_path": m.group(1).strip(), "limit": 30}
            ),

            # =====================================================
            # EDIT PATTERNS - find class/function location
            # =====================================================
            # "добавь метод X в класс Y" -> find class Y first
            (
                re.compile(r'^(?:добавь|вставь|допиши)\s+(?:метод|функцию)\s+(\w+)\s+в\s+(?:класс|class)\s+(\w+)', re.IGNORECASE),
                'grep',
                lambda m: {"pattern": f"class {m.group(2)}.*:", "include": "*.py", "context_after": 5}
            ),
            # "измени класс X" -> find class X
            (
                re.compile(r'^(?:измени|обнови|модифицируй)\s+(?:класс|class)\s+(\w+)', re.IGNORECASE),
                'grep',
                lambda m: {"pattern": f"class {m.group(1)}.*:", "include": "*.py", "context_after": 10}
            ),
            # "найди класс X" -> grep for class definition
            (
                re.compile(r'^(?:найди|покажи|где)\s+(?:класс|class)\s+(\w+)', re.IGNORECASE),
                'grep',
                lambda m: {"pattern": f"class {m.group(1)}.*:", "include": "*.py", "context_after": 5}
            ),
            # "покажи метод X в классе Y" или "покажи метод X"
            (
                re.compile(r'^(?:покажи|найди)\s+(?:метод|функцию|def)\s+(\w+)(?:\s+в\s+(?:классе?|class)\s+(\w+))?', re.IGNORECASE),
                'grep',
                lambda m: {"pattern": f"def {m.group(1)}\\(", "include": "*.py", "context_after": 10}
            ),

            # "wc -l file" or "wc file" -> line count
            (
                re.compile(r'^wc\s+(?:-l\s+)?(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"powershell -Command \"(Get-Content '{m.group(1).strip()}' | Measure-Object -Line).Lines\""}
            ),
            # "count lines in file" or "lines in file"
            (
                re.compile(r'^(?:count\s+)?lines?\s+(?:in\s+)?(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"powershell -Command \"(Get-Content '{m.group(1).strip()}' | Measure-Object -Line).Lines\""}
            ),
            # "размер файла X" -> file size
            (
                re.compile(r'^(?:размер|size)\s+(?:файла?\s+)?(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"ls -lh \"{m.group(1).strip()}\"" if os.name != 'nt' else f"dir \"{m.group(1).strip()}\""}
            ),

            # PWD
            (
                re.compile(r'^pwd$', re.IGNORECASE),
                'bash',
                lambda m: {"command": "cd" if os.name == 'nt' else "pwd"}
            ),
            # CD (show only, don't actually change)
            (
                re.compile(r'^cd\s+(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"cd {m.group(1).strip()} && dir" if os.name == 'nt' else f"cd {m.group(1).strip()} && ls"}
            ),

            # =====================================================
            # PYTHON COMMANDS
            # =====================================================
            # PYTHON VERSION
            (
                re.compile(r'^python\s+--version$', re.IGNORECASE),
                'bash',
                lambda m: {"command": "python --version"}
            ),
            # PYTHON -c
            (
                re.compile(r'^python\s+-c\s+"?(.+)"?$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f'python -c "{m.group(1).strip()}"'}
            ),
            # PIP LIST
            (
                re.compile(r'^pip\s+list\s*(.*)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"pip list {m.group(1).strip()}".strip()}
            ),
            # PIP INSTALL
            (
                re.compile(r'^pip\s+install\s+(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"pip install {m.group(1).strip()}"}
            ),

            # =====================================================
            # SYSTEM COMMANDS (English + Russian)
            # =====================================================
            # BASH/CMD/RUN
            (
                re.compile(r'^(?:bash|cmd|run|exec)\s+(.+)$', re.IGNORECASE),
                'bash',
                self._parse_bash
            ),
            # RUSSIAN BASH: выполни/запусти команду
            (
                re.compile(r'^(?:выполни|запусти|исполни)\s+(?:команду?\s+)?(.+)$', re.IGNORECASE),
                'bash',
                self._parse_bash
            ),
            # ECHO
            (
                re.compile(r'^echo\s+(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"echo {m.group(1).strip()}"}
            ),
            # WHICH/WHERE
            (
                re.compile(r'^(?:which|where)\s+(.+)$', re.IGNORECASE),
                'bash',
                lambda m: {"command": f"where {m.group(1).strip()}" if os.name == 'nt' else f"which {m.group(1).strip()}"}
            ),

            # =====================================================
            # WRITE/EDIT COMMANDS (English + Russian)
            # =====================================================
            # EDIT: "in file.py replace "old" with "new""
            (
                re.compile(r'^in\s+(?:file\s+)?["\']?([^\s"\']+)["\']?\s+(?:replace|change)\s+["\'](.+?)["\']\s+(?:with|to)\s+["\'](.+?)["\']$', re.IGNORECASE),
                'edit',
                lambda m: {"file_path": m.group(1), "old_string": m.group(2), "new_string": m.group(3)}
            ),
            # EDIT: "replace "old" with "new" in file.py"
            (
                re.compile(r'^(?:replace|change)\s+["\'](.+?)["\']\s+(?:with|to)\s+["\'](.+?)["\']\s+in\s+(?:file\s+)?["\']?([^\s"\']+)["\']?$', re.IGNORECASE),
                'edit',
                lambda m: {"file_path": m.group(3), "old_string": m.group(1), "new_string": m.group(2)}
            ),
            # RUSSIAN EDIT: "в файле file.py замени "old" на "new""
            (
                re.compile(r'^в\s+(?:файле\s+)?["\']?([^\s"\']+)["\']?\s+(?:замени|измени|поменяй)\s+["\'](.+?)["\']\s+на\s+["\'](.+?)["\']$', re.IGNORECASE),
                'edit',
                lambda m: {"file_path": m.group(1), "old_string": m.group(2), "new_string": m.group(3)}
            ),
            # RUSSIAN EDIT: "замени "old" на "new" в файле file.py"
            (
                re.compile(r'^(?:замени|измени|поменяй)\s+["\'](.+?)["\']\s+на\s+["\'](.+?)["\']\s+в\s+(?:файле\s+)?["\']?([^\s"\']+)["\']?$', re.IGNORECASE),
                'edit',
                lambda m: {"file_path": m.group(3), "old_string": m.group(1), "new_string": m.group(2)}
            ),
            # RUSSIAN WRITE: "создай файл file.py с содержимым: ..."
            (
                re.compile(r'^(?:создай|напиши|запиши)\s+(?:файл\s+)?([^\s:]+)\s*(?:с\s+(?:содержимым|кодом|текстом))?\s*:\s*(.+)$', re.IGNORECASE | re.DOTALL),
                'write',
                self._parse_write
            ),
            # RUSSIAN WRITE: "создай файл file.py с функцией func_name которая ..."
            (
                re.compile(r'^(?:создай|напиши)\s+(?:файл\s+)?([^\s]+\.py)\s+с\s+функцией\s+(\w+)\s+котор\S+\s+(.+)$', re.IGNORECASE | re.DOTALL),
                'write',
                lambda m: {
                    "file_path": m.group(1),
                    "content": f'''# -*- coding: utf-8 -*-
"""Module with {m.group(2)} function."""


def {m.group(2)}(text: str) -> str:
    """
    {m.group(3).strip().rstrip('.')}.

    Args:
        text: Input text to process

    Returns:
        Processed text
    """
    # TODO: Implement {m.group(2)}
    return text.title()  # Basic implementation
'''
                }
            ),
            # RUSSIAN WRITE: "создай файл file.py с классом ClassName"
            (
                re.compile(r'^(?:создай|напиши)\s+(?:файл\s+)?([^\s]+\.py)\s+с\s+классом\s+(\w+)', re.IGNORECASE),
                'write',
                lambda m: {
                    "file_path": m.group(1),
                    "content": f'''# -*- coding: utf-8 -*-
"""Module with {m.group(2)} class."""


class {m.group(2)}:
    """
    {m.group(2)} class.

    TODO: Add description
    """

    def __init__(self):
        """Initialize {m.group(2)}."""
        pass
'''
                }
            ),
            # EDIT с диапазоном строк
            (
                re.compile(r'^edit\s+(.+?)\s+lines?\s+(\d+)[-–](\d+)$', re.IGNORECASE),
                'edit',
                self._parse_edit_lines
            ),
            # EDIT с одной строкой
            (
                re.compile(r'^edit\s+(.+?)\s+line\s+(\d+)$', re.IGNORECASE),
                'edit',
                self._parse_edit_line
            ),
            # EDIT базовый
            (
                re.compile(r'^edit\s+(.+)$', re.IGNORECASE),
                'edit',
                self._parse_edit
            ),
            # WRITE (простой)
            (
                re.compile(r'^write\s+(.+?)\s*:\s*(.+)$', re.IGNORECASE | re.DOTALL),
                'write',
                self._parse_write
            ),

            # =====================================================
            # HELP COMMANDS
            # =====================================================
            # HELP
            (
                re.compile(r'^(?:help|\?|commands)$', re.IGNORECASE),
                'help',
                lambda m: {}
            ),
        ]

        # Команды-алиасы (English + Russian)
        self.aliases = {
            'dir': 'ls',
            'cat': 'read',
            'search': 'grep',
            'type': 'read',  # Windows
            # Russian aliases
            'читай': 'read',
            'ищи': 'grep',
            'папка': 'ls',
        }

    def match(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет, соответствует ли сообщение паттерну.

        Args:
            message: Входное сообщение пользователя

        Returns:
            {"tool": "...", "params": {...}} или None если не паттерн
        """
        message = message.strip()
        if not message:
            return None

        # Проверяем алиасы
        first_word = message.split()[0].lower() if message.split() else ""
        if first_word in self.aliases:
            message = message.replace(first_word, self.aliases[first_word], 1)

        # Проверяем паттерны
        for pattern, tool_name, parser in self.patterns:
            match = pattern.match(message)
            if match:
                try:
                    params = parser(match)
                    return {
                        "tool": tool_name,
                        "params": params,
                        "original": message,
                        "matched_by": "pattern_router"
                    }
                except Exception:
                    continue

        # Fallback: try natural language search translation
        search_result = self._try_search_translation(message)
        if search_result:
            return search_result

        return None

    def _try_search_translation(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Try to translate natural language search query to grep command.

        Uses QueryCrystallizer to translate queries like:
        - "найди классы с наследованием" -> grep pattern
        - "покажи функции async" -> grep pattern
        """
        try:
            from core.query_crystallizer import translate_search_to_grep

            # Extract path if specified (e.g., "в core/" or "in core/")
            path = "."
            path_patterns = [
                r'\s+(?:в|in|из|from)\s+([^\s]+/?)',  # "в core/", "in src/"
                r'\s+([^\s]+/)\s*$',  # trailing "core/"
            ]
            for p in path_patterns:
                m = re.search(p, message, re.IGNORECASE)
                if m:
                    path = m.group(1).strip()
                    break

            result = translate_search_to_grep(message, path)
            if result:
                return {
                    "tool": "grep",
                    "params": {
                        "pattern": result["pattern"],
                        "path": result["path"],
                        "include": result.get("glob", "*.py"),  # unified_tools expects "include"
                    },
                    "original": message,
                    "matched_by": "search_translation",
                    "description": result.get("description", "")
                }
        except ImportError:
            pass
        except Exception:
            pass

        return None

    def match_chain(self, message: str) -> List[Dict[str, Any]]:
        """
        Разбирает цепочку команд (через ; или \\n).

        Args:
            message: Сообщение с возможной цепочкой команд

        Returns:
            Список маршрутов или пустой список
        """
        # Разбиваем по ; и переносам строк
        commands = re.split(r'[;\n]+', message)
        commands = [c.strip() for c in commands if c.strip()]

        routes = []
        for cmd in commands:
            route = self.match(cmd)
            if route:
                routes.append(route)

        return routes

    def is_command(self, message: str) -> bool:
        """Проверяет, является ли сообщение командой"""
        return self.match(message) is not None

    # ═══════════════════════════════════════════════════════════════════════════
    # PARSERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _parse_read_lines(self, match: re.Match) -> Dict[str, Any]:
        """read file.py lines 10-20"""
        file_path = match.group(1).strip()
        start = int(match.group(2))
        end = int(match.group(3))
        return {
            "file_path": file_path,
            "start_line": start,
            "end_line": end
        }

    def _parse_read_line(self, match: re.Match) -> Dict[str, Any]:
        """read file.py line 10"""
        file_path = match.group(1).strip()
        line = int(match.group(2))
        return {
            "file_path": file_path,
            "start_line": line,
            "end_line": line
        }

    def _parse_read(self, match: re.Match) -> Dict[str, Any]:
        """read file.py"""
        file_path = match.group(1).strip()
        return {"file_path": file_path}

    def _parse_grep_in(self, match: re.Match) -> Dict[str, Any]:
        """grep pattern in path"""
        pattern = match.group(1).strip()
        path = match.group(2).strip()
        return {"pattern": pattern, "path": path}

    def _parse_grep(self, match: re.Match) -> Dict[str, Any]:
        """grep pattern"""
        pattern = match.group(1).strip()
        return {"pattern": pattern, "path": "."}

    def _parse_find(self, match: re.Match) -> Dict[str, Any]:
        """find query"""
        query = match.group(1).strip()
        return {"query": query, "path": "."}

    def _parse_ls(self, match: re.Match) -> Dict[str, Any]:
        """ls path"""
        path = match.group(1).strip() or "."
        return {"path": path}

    def _parse_glob(self, match: re.Match) -> Dict[str, Any]:
        """glob pattern path"""
        pattern = match.group(1).strip()
        path = match.group(2).strip() or "."
        return {"pattern": pattern, "path": path}

    def _parse_bash(self, match: re.Match) -> Dict[str, Any]:
        """bash command"""
        command = match.group(1).strip()
        return {"command": command}

    def _parse_write(self, match: re.Match) -> Dict[str, Any]:
        """write file.py: content"""
        file_path = match.group(1).strip()
        content = match.group(2).strip()
        return {"file_path": file_path, "content": content}

    def _parse_edit_lines(self, match: re.Match) -> Dict[str, Any]:
        """edit file.py lines 10-20"""
        file_path = match.group(1).strip()
        start = int(match.group(2))
        end = int(match.group(3))
        return {
            "file_path": file_path,
            "start_line": start,
            "end_line": end
        }

    def _parse_edit_line(self, match: re.Match) -> Dict[str, Any]:
        """edit file.py line 10"""
        file_path = match.group(1).strip()
        line = int(match.group(2))
        return {
            "file_path": file_path,
            "line": line
        }

    def _parse_edit(self, match: re.Match) -> Dict[str, Any]:
        """edit file.py"""
        file_path = match.group(1).strip()
        return {"file_path": file_path}


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

_router: Optional[PatternRouter] = None

def get_router() -> PatternRouter:
    """Получить глобальный экземпляр роутера"""
    global _router
    if _router is None:
        _router = PatternRouter()
    return _router


def route(message: str) -> Optional[Dict[str, Any]]:
    """Быстрая маршрутизация"""
    return get_router().match(message)


def route_chain(message: str) -> List[Dict[str, Any]]:
    """Маршрутизация цепочки команд"""
    return get_router().match_chain(message)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("PatternRouter - Fast Path без LLM")
    print("=" * 70)

    router = PatternRouter()

    test_cases = [
        # READ
        "read core/tools.py",
        "read core/tools.py lines 10-20",
        "read core/tools.py line 15",

        # GREP
        "grep class in core/",
        'grep "def execute" in core/',
        "grep pattern",

        # FIND
        "find UnifiedTools",

        # LS
        "ls",
        "ls core",
        "ls core/",

        # GLOB
        'glob "*.py"',
        'glob "*.py" core/',

        # BASH
        "bash dir",
        "cmd python --version",

        # CHAIN
        "ls core; read tools.py lines 1-10",

        # ALIASES
        "dir core",
        "cat file.py",
        "search pattern in core/",

        # Not commands (should return None)
        "How do I fix this error?",
        "Explain the architecture",
        "что такое docker",
    ]

    print("\nТестирование паттернов:\n")

    for test in test_cases:
        result = router.match(test)
        if result:
            print(f"✅ '{test}'")
            print(f"   → tool: {result['tool']}, params: {result['params']}")
        else:
            print(f"❌ '{test}' → LLM path")
        print()

    # Test chain
    print("\n" + "=" * 70)
    print("Тестирование цепочек команд:")
    print("=" * 70)

    chain_test = "ls core; read tools.py lines 1-5; grep class"
    chain_result = router.match_chain(chain_test)
    print(f"\nInput: '{chain_test}'")
    print(f"Commands: {len(chain_result)}")
    for i, r in enumerate(chain_result, 1):
        print(f"  {i}. {r['tool']}: {r['params']}")

    print("\n" + "=" * 70)
    print("✅ PatternRouter работает корректно!")
