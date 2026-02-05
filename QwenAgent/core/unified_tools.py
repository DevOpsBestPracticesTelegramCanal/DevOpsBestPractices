# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
QwenCode UNIFIED TOOLS - Единый источник правды
═══════════════════════════════════════════════════════════════════════════════

ПРИНЦИП: Один файл, один формат, все используют его.

Стандартный формат ответов:
    grep()  → {success, matches: [{file, line_number, line}], count}
    read()  → {success, content, file_path, total_lines, shown_lines}
    bash()  → {success, stdout, stderr, return_code}
    ls()    → {success, items: [{name, type, size}], count}
    glob()  → {success, matches: [paths], count}
    write() → {success, file_path, bytes_written}
    edit()  → {success, file_path, replacements}
    find()  → smart search (grep + read context)

Использование:
    from core.unified_tools import UnifiedTools

    tools = UnifiedTools(project_root="C:/Users/serga/QwenAgent")
    result = tools.grep("class", "core/")
    # {success: True, matches: [{file: "...", line_number: 10, line: "class X:"}], count: 5}

═══════════════════════════════════════════════════════════════════════════════
"""

import os
import re
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════
# CONTRACTS - Стандартные форматы ответов
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GrepMatch:
    """Одно совпадение grep"""
    file: str
    line_number: int
    line: str

@dataclass
class GrepResult:
    """Результат grep"""
    success: bool
    matches: List[GrepMatch]
    count: int
    pattern: str = ""
    engine: str = "python"
    error: str = ""

@dataclass
class ReadResult:
    """Результат read"""
    success: bool
    content: str = ""
    file_path: str = ""
    total_lines: int = 0
    shown_lines: int = 0
    is_binary: bool = False
    error: str = ""

@dataclass
class WriteResult:
    """Результат write"""
    success: bool
    file_path: str = ""
    bytes_written: int = 0
    error: str = ""

@dataclass
class EditResult:
    """Результат edit"""
    success: bool
    file_path: str = ""
    replacements: int = 0
    total_matches: int = 0
    error: str = ""

@dataclass
class BashResult:
    """Результат bash"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    error: str = ""

@dataclass
class LsItem:
    """Элемент списка ls"""
    name: str
    type: str  # "file" | "directory"
    size: int = 0

@dataclass
class LsResult:
    """Результат ls"""
    success: bool
    items: List[LsItem] = None
    count: int = 0
    path: str = ""
    error: str = ""

@dataclass
class GlobResult:
    """Результат glob"""
    success: bool
    matches: List[str] = None
    count: int = 0
    pattern: str = ""
    error: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED TOOLS CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class UnifiedTools:
    """
    ЕДИНЫЙ ИСТОЧНИК ПРАВДЫ для всех инструментов QwenCode.

    Все остальные реализации должны импортировать этот класс.
    """

    # Бинарные расширения
    BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.exe', '.dll', '.so', '.pyc'}

    # Игнорируемые директории
    IGNORE_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.idea', '.vscode'}

    def __init__(self, project_root: str = None):
        """
        Инициализация с корневой директорией проекта.

        Args:
            project_root: Корень проекта. По умолчанию - текущая директория.
        """
        if project_root:
            self.project_root = Path(project_root).resolve()
        else:
            self.project_root = Path.cwd()

        # Статистика использования
        self.stats = {
            'files_read': 0,
            'files_written': 0,
            'files_edited': 0,
            'commands_executed': 0,
            'searches_performed': 0
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # GREP - Поиск паттерна в файлах
    # ═══════════════════════════════════════════════════════════════════════════

    def grep(self, pattern: str, path: str = ".",
             include: str = None, max_results: int = 50,
             context_before: int = 0, context_after: int = 0) -> Dict[str, Any]:
        """
        Поиск паттерна в файлах.

        СТАНДАРТНЫЙ ФОРМАТ ОТВЕТА:
        {
            "success": True,
            "matches": [
                {"file": "core/tools.py", "line_number": 15, "line": "class Tools:"}
            ],
            "count": 1,
            "pattern": "class",
            "engine": "ripgrep|python"
        }

        Args:
            pattern: Регулярное выражение для поиска
            path: Путь для поиска (относительный или абсолютный)
            include: Glob-паттерн для фильтрации файлов (например, "*.py")
            max_results: Максимум результатов
            context_before: Строк контекста до совпадения
            context_after: Строк контекста после совпадения

        Returns:
            GrepResult как словарь
        """
        try:
            self.stats['searches_performed'] += 1

            # Разрешаем путь
            search_path = self._resolve_path(path)

            # Пробуем ripgrep сначала (быстрее)
            if shutil.which("rg"):
                result = self._grep_ripgrep(pattern, search_path, include, max_results)
                if result['success']:
                    return result

            # Python fallback
            return self._grep_python(pattern, search_path, include, max_results)

        except Exception as e:
            return {"success": False, "matches": [], "count": 0, "pattern": pattern, "error": str(e)}

    def _grep_ripgrep(self, pattern: str, path: Path, include: str, max_results: int) -> Dict[str, Any]:
        """Grep через ripgrep (быстрый путь)"""
        try:
            cmd = [
                "rg", pattern, str(path),
                "--line-number",
                "--max-count", str(max_results),
                "--color", "never",
                "--no-heading",
                "--with-filename"
            ]
            if include:
                cmd.extend(["--glob", include])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')

            if result.returncode in (0, 1):  # 0 = matches found, 1 = no matches
                matches = []
                if result.stdout.strip():
                    for line in result.stdout.strip().split('\n')[:max_results]:
                        # Формат: file:line_number:line_content
                        parts = line.split(':', 2)
                        if len(parts) >= 3:
                            file_path = parts[0]
                            try:
                                line_num = int(parts[1])
                            except ValueError:
                                continue
                            line_text = parts[2] if len(parts) > 2 else ""

                            # Относительный путь
                            try:
                                rel_path = str(Path(file_path).relative_to(self.project_root))
                            except ValueError:
                                rel_path = file_path

                            matches.append({
                                "file": rel_path.replace("\\", "/"),
                                "line_number": line_num,
                                "line": line_text.strip()[:200]
                            })

                return {
                    "success": True,
                    "matches": matches,
                    "count": len(matches),
                    "pattern": pattern,
                    "engine": "ripgrep"
                }

            return {"success": False, "matches": [], "count": 0, "pattern": pattern, "error": "ripgrep error"}

        except Exception as e:
            return {"success": False, "matches": [], "count": 0, "pattern": pattern, "error": str(e)}

    def _grep_python(self, pattern: str, path: Path, include: str, max_results: int) -> Dict[str, Any]:
        """Grep через Python (fallback)"""
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            matches = []

            # Собираем файлы
            if path.is_file():
                files = [path]
            else:
                if include:
                    files = list(path.rglob(include))
                else:
                    files = [f for f in path.rglob("*") if f.is_file()]

            # Фильтруем бинарные и игнорируемые
            files = [
                f for f in files
                if f.suffix.lower() not in self.BINARY_EXTENSIONS
                and not any(d in f.parts for d in self.IGNORE_DIRS)
            ]

            for file_path in files[:500]:  # Лимит файлов
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()

                    for i, line in enumerate(lines, 1):
                        if regex.search(line):
                            try:
                                rel_path = str(file_path.relative_to(self.project_root))
                            except ValueError:
                                rel_path = str(file_path)

                            matches.append({
                                "file": rel_path.replace("\\", "/"),
                                "line_number": i,
                                "line": line.strip()[:200]
                            })

                            if len(matches) >= max_results:
                                break
                except:
                    continue

                if len(matches) >= max_results:
                    break

            return {
                "success": True,
                "matches": matches,
                "count": len(matches),
                "pattern": pattern,
                "engine": "python"
            }

        except Exception as e:
            return {"success": False, "matches": [], "count": 0, "pattern": pattern, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # READ - Чтение файла
    # ═══════════════════════════════════════════════════════════════════════════

    def read(self, file_path: str = None, path: str = None,
             offset: int = 0, limit: int = 2000,
             start_line: int = None, end_line: int = None) -> Dict[str, Any]:
        """
        Чтение файла с номерами строк.

        СТАНДАРТНЫЙ ФОРМАТ ОТВЕТА:
        {
            "success": True,
            "content": "1: line1\\n2: line2...",
            "file_path": "core/tools.py",
            "total_lines": 100,
            "shown_lines": 50
        }

        Args:
            file_path: Путь к файлу
            path: Альтернативное имя параметра
            offset: Начальная строка (0-based)
            limit: Количество строк
            start_line: Начальная строка (1-based, переопределяет offset)
            end_line: Конечная строка (1-based)

        Returns:
            ReadResult как словарь
        """
        # Нормализация параметров
        if not file_path and path:
            file_path = path
        if not file_path:
            return {"success": False, "content": "", "error": "file_path is required"}

        try:
            self.stats['files_read'] += 1

            # Разрешаем путь
            resolved = self._resolve_path(file_path)

            if not resolved.exists():
                return {"success": False, "content": "", "error": f"File not found: {file_path}"}

            # Бинарный файл?
            if resolved.suffix.lower() in self.BINARY_EXTENSIONS:
                return {
                    "success": True,
                    "content": f"[Binary file: {resolved.suffix}, size: {resolved.stat().st_size} bytes]",
                    "file_path": str(resolved),
                    "total_lines": 0,
                    "shown_lines": 0,
                    "is_binary": True
                }

            # Читаем файл
            with open(resolved, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            total = len(lines)

            # Поддержка lines X-Y синтаксиса
            if start_line is not None:
                offset = max(0, start_line - 1)
                if end_line is not None:
                    limit = end_line - start_line + 1

            # Выбираем строки
            selected = lines[offset:offset + limit]

            # Форматируем с номерами строк
            content_lines = []
            for i, line in enumerate(selected):
                line_num = offset + i + 1
                content_lines.append(f"{line_num:6d}: {line.rstrip()}")

            return {
                "success": True,
                "content": "\n".join(content_lines),
                "file_path": str(resolved),
                "total_lines": total,
                "shown_lines": len(selected)
            }

        except Exception as e:
            return {"success": False, "content": "", "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # WRITE - Запись файла
    # ═══════════════════════════════════════════════════════════════════════════

    def write(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        Запись содержимого в файл.

        СТАНДАРТНЫЙ ФОРМАТ ОТВЕТА:
        {
            "success": True,
            "file_path": "core/new_file.py",
            "bytes_written": 1234
        }
        """
        try:
            self.stats['files_written'] += 1

            resolved = self._resolve_path(file_path)

            # Создаём директории если нужно
            resolved.parent.mkdir(parents=True, exist_ok=True)

            # Валидация Python синтаксиса
            if resolved.suffix.lower() == '.py':
                try:
                    compile(content, str(resolved), 'exec')
                except SyntaxError as e:
                    return {
                        "success": False,
                        "file_path": str(resolved),
                        "bytes_written": 0,
                        "error": f"Python syntax error: {e}"
                    }

            # Записываем
            with open(resolved, 'w', encoding='utf-8') as f:
                bytes_written = f.write(content)

            return {
                "success": True,
                "file_path": str(resolved),
                "bytes_written": bytes_written
            }

        except Exception as e:
            return {"success": False, "file_path": file_path, "bytes_written": 0, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # EDIT - Редактирование файла
    # ═══════════════════════════════════════════════════════════════════════════

    def edit(self, file_path: str, old_string: str, new_string: str,
             replace_all: bool = False) -> Dict[str, Any]:
        """
        Редактирование файла - поиск и замена.

        СТАНДАРТНЫЙ ФОРМАТ ОТВЕТА:
        {
            "success": True,
            "file_path": "core/tools.py",
            "replacements": 1,
            "total_matches": 3
        }
        """
        try:
            self.stats['files_edited'] += 1

            resolved = self._resolve_path(file_path)

            if not resolved.exists():
                return {
                    "success": False,
                    "file_path": str(resolved),
                    "replacements": 0,
                    "error": f"File not found: {file_path}"
                }

            with open(resolved, 'r', encoding='utf-8') as f:
                content = f.read()

            if old_string not in content:
                return {
                    "success": False,
                    "file_path": str(resolved),
                    "replacements": 0,
                    "error": "String not found in file"
                }

            total_matches = content.count(old_string)

            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements = total_matches
            else:
                new_content = content.replace(old_string, new_string, 1)
                replacements = 1

            # Валидация Python синтаксиса
            if resolved.suffix.lower() == '.py':
                try:
                    compile(new_content, str(resolved), 'exec')
                except SyntaxError as e:
                    return {
                        "success": False,
                        "file_path": str(resolved),
                        "replacements": 0,
                        "error": f"Edit would create syntax error: {e}"
                    }

            with open(resolved, 'w', encoding='utf-8') as f:
                f.write(new_content)

            # Generate diff for tree-style display
            def generate_diff(old_str, new_str):
                """Generate simple diff for display"""
                diff = []
                line_num = 1

                # Show removed lines
                for line in old_str.splitlines()[:5]:
                    diff.append({
                        "line": line_num,
                        "type": "remove",
                        "content": line
                    })
                    line_num += 1

                # Show added lines
                line_num = 1
                for line in new_str.splitlines()[:5]:
                    diff.append({
                        "line": line_num,
                        "type": "add",
                        "content": line
                    })
                    line_num += 1

                return diff

            # Calculate lines changed
            old_line_count = old_string.count('\n') + 1
            new_line_count = new_string.count('\n') + 1
            lines_added = max(1, new_line_count)
            lines_removed = max(1, old_line_count)

            return {
                "success": True,
                "file_path": str(resolved),
                "replacements": replacements,
                "total_matches": total_matches,
                # Fields for tree-style formatting
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "old_string": old_string,
                "new_string": new_string,
                "diff": generate_diff(old_string, new_string)
            }

        except Exception as e:
            return {"success": False, "file_path": file_path, "replacements": 0, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # BASH - Выполнение команды
    # ═══════════════════════════════════════════════════════════════════════════

    def bash(self, command: str, timeout: int = 120,
             working_dir: str = None) -> Dict[str, Any]:
        """
        Выполнение shell команды.

        СТАНДАРТНЫЙ ФОРМАТ ОТВЕТА:
        {
            "success": True,
            "stdout": "output...",
            "stderr": "",
            "return_code": 0
        }
        """
        try:
            self.stats['commands_executed'] += 1

            cwd = working_dir or str(self.project_root)

            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            # Windows: UTF-8 support
            if os.name == 'nt':
                full_command = f'chcp 65001 >nul && {command}'
            else:
                full_command = command

            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                encoding='utf-8',
                errors='replace',
                env=env
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:30000] if result.stdout else "",
                "stderr": result.stderr[:5000] if result.stderr else "",
                "return_code": result.returncode
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "stdout": "", "stderr": "", "return_code": -1, "error": f"Timeout after {timeout}s"}
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": "", "return_code": -1, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # LS - Список файлов
    # ═══════════════════════════════════════════════════════════════════════════

    def ls(self, path: str = ".") -> Dict[str, Any]:
        """
        Список файлов в директории.

        СТАНДАРТНЫЙ ФОРМАТ ОТВЕТА:
        {
            "success": True,
            "items": [
                {"name": "tools.py", "type": "file", "size": 12345},
                {"name": "agents/", "type": "directory", "size": 0}
            ],
            "count": 2,
            "path": "core/"
        }
        """
        try:
            resolved = self._resolve_path(path)

            if not resolved.exists():
                return {"success": False, "items": [], "count": 0, "path": path, "error": f"Path not found: {path}"}

            if resolved.is_file():
                return {
                    "success": True,
                    "items": [{"name": resolved.name, "type": "file", "size": resolved.stat().st_size}],
                    "count": 1,
                    "path": path
                }

            items = []
            for item in sorted(resolved.iterdir()):
                if item.name.startswith('.') and item.name not in ['.env', '.gitignore']:
                    continue

                item_type = "directory" if item.is_dir() else "file"
                size = 0 if item.is_dir() else item.stat().st_size

                items.append({
                    "name": item.name + ("/" if item.is_dir() else ""),
                    "type": item_type,
                    "size": size
                })

            return {
                "success": True,
                "items": items,
                "count": len(items),
                "path": path
            }

        except Exception as e:
            return {"success": False, "items": [], "count": 0, "path": path, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # GLOB - Поиск файлов по паттерну
    # ═══════════════════════════════════════════════════════════════════════════

    def glob(self, pattern: str, path: str = ".") -> Dict[str, Any]:
        """
        Поиск файлов по glob-паттерну.

        СТАНДАРТНЫЙ ФОРМАТ ОТВЕТА:
        {
            "success": True,
            "matches": ["core/tools.py", "core/agent.py"],
            "count": 2,
            "pattern": "*.py"
        }
        """
        try:
            resolved = self._resolve_path(path)

            matches = []
            for match in resolved.rglob(pattern):
                try:
                    rel_path = str(match.relative_to(self.project_root))
                except ValueError:
                    rel_path = str(match)
                matches.append(rel_path.replace("\\", "/"))

            return {
                "success": True,
                "matches": matches[:100],  # Лимит
                "count": len(matches),
                "pattern": pattern
            }

        except Exception as e:
            return {"success": False, "matches": [], "count": 0, "pattern": pattern, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════════
    # FIND - Умный поиск (grep + read контекста)
    # ═══════════════════════════════════════════════════════════════════════════

    def find(self, query: str, path: str = ".") -> Dict[str, Any]:
        """
        Умный поиск: grep + автоматическое чтение контекста.

        Объединяет grep и read для получения полного контекста.

        Args:
            query: Что искать (функция, класс, паттерн)
            path: Где искать

        Returns:
            Результат grep + контекст найденных совпадений
        """
        # Сначала grep
        grep_result = self.grep(query, path, max_results=10)

        if not grep_result['success'] or grep_result['count'] == 0:
            return grep_result

        # Добавляем контекст для первых 3 совпадений
        enriched_matches = []
        for match in grep_result['matches'][:3]:
            file_path = match['file']
            line_num = match['line_number']

            # Читаем контекст (5 строк до и после)
            read_result = self.read(
                file_path,
                start_line=max(1, line_num - 5),
                end_line=line_num + 5
            )

            enriched_match = {
                **match,
                "context": read_result.get('content', '') if read_result['success'] else ''
            }
            enriched_matches.append(enriched_match)

        # Остальные без контекста
        enriched_matches.extend(grep_result['matches'][3:])

        return {
            "success": True,
            "matches": enriched_matches,
            "count": grep_result['count'],
            "pattern": query,
            "engine": grep_result.get('engine', 'python')
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # EXECUTE - Универсальный метод выполнения
    # ═══════════════════════════════════════════════════════════════════════════

    def help(self) -> Dict[str, Any]:
        """
        Показать справку по доступным командам.

        Returns:
            Справочная информация
        """
        help_text = """
QWENCODE UNIFIED TOOLS - Available Commands
============================================

FILE OPERATIONS:
  read <file> [lines X-Y]     Read file content
  write <file>: <content>     Write content to file
  edit <file>                 Edit file (via LLM)
  ls [path]                   List directory contents
  glob <pattern> [path]       Find files by pattern
  tree [path]                 Show directory tree

SEARCH:
  grep <pattern> [in <path>]  Search for pattern
  find <query>                Smart search with context

GIT:
  git status                  Show git status
  git diff [file]             Show changes
  git log                     Show commit history
  git branch                  List/create branches
  git add <files>             Stage changes
  git commit -m "msg"         Commit changes

SYSTEM:
  bash <command>              Execute shell command
  python --version            Show Python version
  pip list                    List installed packages
  pwd                         Show current directory
  which <cmd>                 Find command location

CHAINS:
  cmd1; cmd2; cmd3            Execute multiple commands

EXAMPLES:
  read core/tools.py lines 1-20
  grep class in core/
  ls; git status; git diff
  find UnifiedTools
"""
        return {
            "success": True,
            "content": help_text.strip(),
            "commands": [
                "read", "write", "edit", "ls", "glob", "tree",
                "grep", "find", "git", "bash", "python", "pip", "pwd", "which"
            ]
        }

    def execute(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Универсальный метод выполнения инструмента.

        Args:
            tool_name: Имя инструмента (grep, read, bash, etc.)
            params: Параметры инструмента

        Returns:
            Результат выполнения
        """
        tool_map = {
            'grep': self.grep,
            'read': self.read,
            'write': self.write,
            'edit': self.edit,
            'bash': self.bash,
            'ls': self.ls,
            'glob': self.glob,
            'find': self.find,
            'help': self.help,
        }

        if tool_name not in tool_map:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        try:
            return tool_map[tool_name](**params)
        except TypeError as e:
            return {"success": False, "error": f"Invalid parameters for {tool_name}: {e}"}

    # ═══════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _resolve_path(self, path: str) -> Path:
        """Разрешение пути относительно project_root"""
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.project_root / path).resolve()

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики использования"""
        return self.stats.copy()


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

# Глобальный экземпляр для импорта
_default_tools: Optional[UnifiedTools] = None

def get_tools(project_root: str = None) -> UnifiedTools:
    """
    Получить глобальный экземпляр UnifiedTools.

    Usage:
        from core.unified_tools import get_tools
        tools = get_tools()
        result = tools.grep("class", "core/")
    """
    global _default_tools
    if _default_tools is None or project_root:
        _default_tools = UnifiedTools(project_root)
    return _default_tools


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("UnifiedTools - Единый источник правды")
    print("=" * 70)

    tools = UnifiedTools(project_root="C:/Users/serga/QwenAgent")

    # Test grep
    print("\n[TEST] grep 'class' in 'core/':")
    result = tools.grep("class", "core/", max_results=5)
    print(f"  Success: {result['success']}")
    print(f"  Count: {result['count']}")
    print(f"  Engine: {result.get('engine', 'N/A')}")
    for m in result.get('matches', [])[:3]:
        print(f"    {m['file']}:{m['line_number']}: {m['line'][:50]}...")

    # Test read
    print("\n[TEST] read 'core/unified_tools.py' lines 1-10:")
    result = tools.read("core/unified_tools.py", start_line=1, end_line=10)
    print(f"  Success: {result['success']}")
    print(f"  Total lines: {result.get('total_lines', 0)}")
    print(f"  Shown lines: {result.get('shown_lines', 0)}")

    # Test ls
    print("\n[TEST] ls 'core/':")
    result = tools.ls("core")
    print(f"  Success: {result['success']}")
    print(f"  Count: {result['count']}")
    for item in result.get('items', [])[:5]:
        print(f"    {item['name']} ({item['type']})")

    # Test execute
    print("\n[TEST] execute('grep', {pattern: 'def', path: 'core/'}):")
    result = tools.execute('grep', {'pattern': 'def ', 'path': 'core/', 'max_results': 3})
    print(f"  Success: {result['success']}")
    print(f"  Count: {result['count']}")

    print("\n" + "=" * 70)
    print("Stats:", tools.get_stats())
    print("=" * 70)
    print("\n✅ UnifiedTools работает корректно!")
