# -*- coding: utf-8 -*-
"""
Pattern Discovery Module для QwenAgent
=======================================

Автоматическое обнаружение, анализ и тестирование всех паттернов в проекте.

Возможности:
- Извлечение regex-паттернов из PatternRouter (прямой доступ)
- Извлечение из Python-файлов (AST + regex fallback)
- Генерация тестовых примеров для каждого паттерна
- Тестирование покрытия и валидация
- Отчёты в Markdown/JSON/HTML

Использование:
    python pattern_discovery.py                      # Полный анализ
    python pattern_discovery.py --quick              # Только PatternRouter
    python pattern_discovery.py --test               # С тестами покрытия
    python pattern_discovery.py --report html        # HTML отчёт
    python pattern_discovery.py -p C:\\path\\to\\project

Интеграция с QwenAgent:
    from pattern_discovery import PatternDiscovery
    
    discovery = PatternDiscovery(".")
    patterns = discovery.quick_discover()  # Из PatternRouter
    discovery.generate_tests()
    report = discovery.run_tests()
    print(f"Покрытие: {report.coverage_percent:.1f}%")
"""

import ast
import re
import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from datetime import datetime
import importlib.util


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class DiscoveredPattern:
    """Обнаруженный паттерн."""
    regex: str
    tool: str
    file: str = ""
    line: int = 0
    description: str = ""
    flags: int = 0
    has_handler: bool = False
    test_examples: List[str] = field(default_factory=list)
    
    def __hash__(self):
        return hash(self.regex)
    
    def __eq__(self, other):
        if isinstance(other, DiscoveredPattern):
            return self.regex == other.regex
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "regex": self.regex,
            "tool": self.tool,
            "file": self.file,
            "line": self.line,
            "flags": self.flags,
            "test_examples": self.test_examples[:5],  # Лимит примеров
        }


@dataclass
class CoverageReport:
    """Отчёт о покрытии."""
    total_patterns: int = 0
    covered_patterns: int = 0
    uncovered_patterns: List[DiscoveredPattern] = field(default_factory=list)
    matches_by_pattern: Dict[str, List[str]] = field(default_factory=dict)
    
    @property
    def coverage_percent(self) -> float:
        if self.total_patterns == 0:
            return 0.0
        return (self.covered_patterns / self.total_patterns) * 100


@dataclass 
class ValidationResult:
    """Результат валидации паттернов."""
    total: int = 0
    valid: int = 0
    invalid: int = 0
    warnings: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# PATTERN ROUTER EXTRACTOR (Прямой доступ к роутеру)
# ============================================================================

class PatternRouterExtractor:
    """Извлечение паттернов напрямую из PatternRouter."""
    
    def __init__(self, router_path: str = None):
        self.router_path = router_path
        self.router = None
    
    def load_router(self) -> bool:
        """Загрузить PatternRouter."""
        try:
            if self.router_path:
                # Загрузка из указанного пути
                spec = importlib.util.spec_from_file_location(
                    "pattern_router", 
                    self.router_path
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules["pattern_router"] = module
                    spec.loader.exec_module(module)
                    self.router = module.PatternRouter()
                    return True
            else:
                # Попытка импорта из текущего проекта
                try:
                    from core.pattern_router import PatternRouter
                    self.router = PatternRouter()
                    return True
                except ImportError:
                    pass
                
                # Поиск в текущей директории
                for path in [
                    Path("core/pattern_router.py"),
                    Path("pattern_router.py"),
                    Path("src/pattern_router.py"),
                ]:
                    if path.exists():
                        self.router_path = str(path)
                        return self.load_router()
            
            return False
        except Exception as e:
            print(f"  [!] Не удалось загрузить PatternRouter: {e}")
            return False
    
    def extract(self) -> List[DiscoveredPattern]:
        """Извлечь паттерны напрямую из роутера."""
        if not self.router and not self.load_router():
            return []
        
        patterns = []
        
        # Получаем атрибут patterns из роутера
        router_patterns = getattr(self.router, 'patterns', [])
        
        for idx, item in enumerate(router_patterns):
            if len(item) >= 2:
                compiled_pattern = item[0]
                tool = item[1]
                
                patterns.append(DiscoveredPattern(
                    regex=compiled_pattern.pattern,
                    tool=tool,
                    file="PatternRouter",
                    line=idx + 1,
                    flags=compiled_pattern.flags,
                    has_handler=len(item) >= 3,
                ))
        
        return patterns


# ============================================================================
# AST PATTERN EXTRACTOR
# ============================================================================

class ASTPatternExtractor(ast.NodeVisitor):
    """Извлечение паттернов через AST-анализ."""
    
    def __init__(self, source_code: str, file_path: str):
        self.source_code = source_code
        self.source_lines = source_code.split('\n')
        self.file_path = file_path
        self.patterns: List[DiscoveredPattern] = []
    
    def visit_Call(self, node: ast.Call) -> None:
        """Обработка вызовов re.compile()."""
        if self._is_re_compile(node):
            pattern = self._extract_pattern_string(node)
            if pattern:
                flags = self._extract_flags(node)
                tool = self._guess_tool_from_context(node)
                
                self.patterns.append(DiscoveredPattern(
                    regex=pattern,
                    tool=tool,
                    file=self.file_path,
                    line=node.lineno,
                    flags=flags,
                    has_handler=True,
                ))
        
        self.generic_visit(node)
    
    def visit_Tuple(self, node: ast.Tuple) -> None:
        """Обработка кортежей (pattern, tool, handler)."""
        if len(node.elts) >= 2:
            first = node.elts[0]
            second = node.elts[1]
            
            if isinstance(second, ast.Constant) and isinstance(second.value, str):
                tool = second.value
                
                if isinstance(first, ast.Call) and self._is_re_compile(first):
                    pattern = self._extract_pattern_string(first)
                    if pattern:
                        flags = self._extract_flags(first)
                        self.patterns.append(DiscoveredPattern(
                            regex=pattern,
                            tool=tool,
                            file=self.file_path,
                            line=node.lineno,
                            flags=flags,
                            has_handler=len(node.elts) >= 3,
                        ))
        
        self.generic_visit(node)
    
    def _is_re_compile(self, node: ast.Call) -> bool:
        """Проверка на re.compile()."""
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'compile':
                if isinstance(node.func.value, ast.Name):
                    return node.func.value.id == 're'
        return False
    
    def _extract_pattern_string(self, node: ast.Call) -> Optional[str]:
        """Извлечение строки паттерна."""
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant):
                return str(first_arg.value)
        return None
    
    def _extract_flags(self, node: ast.Call) -> int:
        """Извлечение флагов regex."""
        flags = 0
        flag_map = {
            'IGNORECASE': re.IGNORECASE, 'I': re.IGNORECASE,
            'MULTILINE': re.MULTILINE, 'M': re.MULTILINE,
            'DOTALL': re.DOTALL, 'S': re.DOTALL,
            'VERBOSE': re.VERBOSE, 'X': re.VERBOSE,
        }
        
        for kw in node.keywords:
            if kw.arg == 'flags' and isinstance(kw.value, ast.Attribute):
                flags |= flag_map.get(kw.value.attr, 0)
        
        if len(node.args) >= 2:
            arg = node.args[1]
            if isinstance(arg, ast.Attribute):
                flags |= flag_map.get(arg.attr, 0)
            elif isinstance(arg, ast.BinOp):
                flags |= self._parse_binop_flags(arg, flag_map)
        
        return flags
    
    def _parse_binop_flags(self, node: ast.BinOp, flag_map: Dict) -> int:
        """Парсинг флагов из BinOp (re.I | re.M)."""
        flags = 0
        if isinstance(node.left, ast.Attribute):
            flags |= flag_map.get(node.left.attr, 0)
        elif isinstance(node.left, ast.BinOp):
            flags |= self._parse_binop_flags(node.left, flag_map)
        if isinstance(node.right, ast.Attribute):
            flags |= flag_map.get(node.right.attr, 0)
        return flags
    
    def _guess_tool_from_context(self, node: ast.AST) -> str:
        """Угадывание инструмента по контексту."""
        start = max(0, node.lineno - 5)
        end = min(len(self.source_lines), node.lineno + 5)
        context = '\n'.join(self.source_lines[start:end]).lower()
        
        for tool in ['grep', 'glob', 'read', 'write', 'bash', 'edit', 'ls', 'cd']:
            if f"'{tool}'" in context or f'"{tool}"' in context:
                return tool
        
        return "unknown"


# ============================================================================
# TEST CASE GENERATOR
# ============================================================================

class TestCaseGenerator:
    """Генератор тестовых примеров для паттернов."""
    
    # Шаблоны для разных инструментов
    TEMPLATES = {
        'grep': [
            "найди класс Example",
            "покажи функцию main",
            "grep TODO",
            "поиск import",
        ],
        'glob': [
            "найди все .py файлы в src/",
            "список файлов .js",
            "*.py в core/",
        ],
        'read': [
            "прочитай main.py",
            "покажи файл config.py",
            "cat test.py",
        ],
        'write': [
            "создай файл test.py",
            "напиши в output.txt",
        ],
        'bash': [
            "git status",
            "git log --oneline",
            "ls -la",
            "pwd",
            "wc -l file.py",
        ],
        'edit': [
            "добавь метод test в класс Example",
            "измени функцию main",
        ],
        'ls': [
            "ls",
            "ls core/",
            "покажи папку src",
        ],
    }
    
    def generate_for_pattern(self, pattern: DiscoveredPattern) -> List[str]:
        """Генерация тестов для одного паттерна."""
        examples = []
        
        # 1. Шаблоны для инструмента
        if pattern.tool in self.TEMPLATES:
            examples.extend(self.TEMPLATES[pattern.tool])
        
        # 2. Анализ структуры regex
        examples.extend(self._generate_from_regex(pattern.regex))
        
        # Убираем дубликаты
        return list(set(e for e in examples if e and len(e) > 2))
    
    def _generate_from_regex(self, regex: str) -> List[str]:
        """Генерация примеров на основе regex."""
        examples = []
        
        # Извлекаем ключевые слова
        russian = re.findall(r'[а-яА-ЯёЁ]+', regex)
        english = re.findall(r'\b[a-zA-Z]{3,}\b', regex)
        english = [w for w in english if w.lower() not in 
                   ('compile', 'ignorecase', 'multiline', 'dotall', 'verbose')]
        
        if russian:
            examples.append(' '.join(russian[:3]))
        if english:
            examples.append(' '.join(english[:3]))
        
        # Специальные случаи
        if 'git' in regex.lower():
            examples.extend(['git status', 'git log'])
        if r'\.py' in regex:
            examples.append('найди .py файлы')
        if 'class' in regex.lower():
            examples.append('найди класс Test')
        if 'def ' in regex or 'функци' in regex.lower():
            examples.append('найди функцию main')
        
        return examples
    
    def generate_all(self, patterns: List[DiscoveredPattern]) -> Dict[str, List[str]]:
        """Генерация тестов для всех паттернов."""
        all_tests = {}
        
        for pattern in patterns:
            examples = self.generate_for_pattern(pattern)
            pattern.test_examples = examples
            key = pattern.regex[:40] if len(pattern.regex) > 40 else pattern.regex
            all_tests[key] = examples
        
        return all_tests


# ============================================================================
# PATTERN TESTER
# ============================================================================

class PatternTester:
    """Тестирование паттернов."""
    
    def __init__(self, patterns: List[DiscoveredPattern]):
        self.patterns = patterns
        self.compiled: Dict[str, re.Pattern] = {}
        self._compile_all()
    
    def _compile_all(self) -> None:
        """Компиляция всех паттернов."""
        for p in self.patterns:
            try:
                self.compiled[p.regex] = re.compile(
                    p.regex, 
                    p.flags or re.IGNORECASE
                )
            except re.error:
                pass
    
    def validate_all(self) -> ValidationResult:
        """Валидация всех паттернов."""
        result = ValidationResult(total=len(self.patterns))
        
        for pattern in self.patterns:
            detail = self._validate_one(pattern)
            result.details.append(detail)
            
            if detail["status"] == "valid":
                result.valid += 1
            elif detail["status"] == "invalid":
                result.invalid += 1
            else:
                result.warnings += 1
        
        return result
    
    def _validate_one(self, pattern: DiscoveredPattern) -> Dict[str, Any]:
        """Валидация одного паттерна."""
        detail = {
            "regex": pattern.regex[:50],
            "tool": pattern.tool,
            "status": "valid",
            "issues": []
        }
        
        try:
            compiled = re.compile(pattern.regex, re.IGNORECASE)
            detail["groups"] = compiled.groups
            
            # Проверки качества
            if len(pattern.regex) > 200:
                detail["issues"].append("Too long")
                detail["status"] = "warning"
            if pattern.regex.startswith('.*'):
                detail["issues"].append("Starts with .*")
                detail["status"] = "warning"
                
        except re.error as e:
            detail["status"] = "invalid"
            detail["error"] = str(e)
        
        return detail
    
    def test_coverage(self, test_inputs: List[str]) -> CoverageReport:
        """Проверка покрытия паттернов."""
        report = CoverageReport(total_patterns=len(self.patterns))
        covered = set()
        
        for pattern in self.patterns:
            compiled = self.compiled.get(pattern.regex)
            if not compiled:
                continue
            
            for input_text in test_inputs:
                try:
                    if compiled.search(input_text):
                        covered.add(pattern.regex)
                        key = pattern.regex[:30]
                        report.matches_by_pattern.setdefault(key, []).append(input_text)
                        break
                except Exception:
                    pass
        
        report.covered_patterns = len(covered)
        report.uncovered_patterns = [p for p in self.patterns if p.regex not in covered]
        
        return report
    
    def find_matching_pattern(self, input_text: str) -> Optional[DiscoveredPattern]:
        """Найти паттерн, соответствующий входу."""
        for pattern in self.patterns:
            compiled = self.compiled.get(pattern.regex)
            if compiled:
                try:
                    if compiled.search(input_text):
                        return pattern
                except Exception:
                    pass
        return None


# ============================================================================
# DISCOVERY ORCHESTRATOR
# ============================================================================

class PatternDiscovery:
    """Главный класс для обнаружения паттернов."""
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.patterns: List[DiscoveredPattern] = []
        self.router_extractor = PatternRouterExtractor()
        self.test_generator = TestCaseGenerator()
    
    def discover_all(self, 
                     use_router: bool = True,
                     use_ast: bool = True,
                     max_files: int = 100) -> List[DiscoveredPattern]:
        """Полное обнаружение паттернов."""
        all_patterns = []
        seen = set()
        
        # 1. Из PatternRouter (приоритет)
        if use_router:
            router_patterns = self.router_extractor.extract()
            for p in router_patterns:
                if p.regex not in seen:
                    seen.add(p.regex)
                    all_patterns.append(p)
            print(f"  [+] PatternRouter: {len(router_patterns)} паттернов")
        
        # 2. Из исходных файлов
        if use_ast:
            py_files = list(self.project_root.rglob("*.py"))[:max_files]
            file_patterns = 0
            
            for py_file in py_files:
                try:
                    content = py_file.read_text(encoding='utf-8', errors='ignore')
                    tree = ast.parse(content)
                    extractor = ASTPatternExtractor(content, str(py_file))
                    extractor.visit(tree)
                    
                    for p in extractor.patterns:
                        if p.regex not in seen:
                            seen.add(p.regex)
                            all_patterns.append(p)
                            file_patterns += 1
                except Exception:
                    pass
            
            print(f"  [+] Файлы ({len(py_files)}): {file_patterns} паттернов")
        
        self.patterns = all_patterns
        return all_patterns
    
    def quick_discover(self) -> List[DiscoveredPattern]:
        """Быстрое обнаружение (только PatternRouter)."""
        self.patterns = self.router_extractor.extract()
        return self.patterns
    
    def generate_tests(self) -> Dict[str, List[str]]:
        """Генерация тестов для всех паттернов."""
        return self.test_generator.generate_all(self.patterns)
    
    def run_tests(self, test_inputs: List[str] = None) -> CoverageReport:
        """Запуск тестов покрытия."""
        if test_inputs is None:
            test_inputs = []
            for p in self.patterns:
                test_inputs.extend(p.test_examples)
        
        tester = PatternTester(self.patterns)
        return tester.test_coverage(test_inputs)
    
    def validate(self) -> ValidationResult:
        """Валидация всех паттернов."""
        tester = PatternTester(self.patterns)
        return tester.validate_all()
    
    def find_pattern(self, input_text: str) -> Optional[DiscoveredPattern]:
        """Найти паттерн для входной строки."""
        tester = PatternTester(self.patterns)
        return tester.find_matching_pattern(input_text)


# ============================================================================
# REPORT GENERATOR
# ============================================================================

class ReportGenerator:
    """Генератор отчётов."""
    
    def __init__(self, patterns: List[DiscoveredPattern]):
        self.patterns = patterns
    
    def _safe_string(self, s: str) -> str:
        """Очистка строки от проблемных символов."""
        return s.encode('utf-8', errors='replace').decode('utf-8')
    
    def generate_markdown(self, output_path: str = "patterns_report.md") -> str:
        """Генерация Markdown-отчёта."""
        by_tool = defaultdict(list)
        for p in self.patterns:
            by_tool[p.tool].append(p)
        
        lines = [
            "# Pattern Discovery Report",
            "",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Total patterns:** {len(self.patterns)}",
            "",
            "## Statistics by Tool",
            "",
            "| Tool | Count | % |",
            "|------|-------|---|",
        ]
        
        for tool, patterns in sorted(by_tool.items(), key=lambda x: -len(x[1])):
            pct = len(patterns) / len(self.patterns) * 100 if self.patterns else 0
            lines.append(f"| {tool} | {len(patterns)} | {pct:.1f}% |")
        
        lines.extend(["", "## Patterns by Tool", ""])
        
        for tool, patterns in sorted(by_tool.items()):
            lines.append(f"### {tool.upper()} ({len(patterns)})")
            lines.append("")
            
            for i, p in enumerate(patterns[:20], 1):  # Лимит
                regex = self._safe_string(p.regex[:50])
                regex = regex.replace("|", "\\|").replace("`", "'")
                lines.append(f"{i}. `{regex}...`")
                if p.test_examples:
                    lines.append(f"   - Example: `{p.test_examples[0]}`")
            
            if len(patterns) > 20:
                lines.append(f"   ... and {len(patterns) - 20} more")
            lines.append("")
        
        content = '\n'.join(lines)
        Path(output_path).write_text(content, encoding='utf-8')
        return output_path
    
    def generate_json(self, output_path: str = "patterns_report.json") -> str:
        """Генерация JSON-отчёта."""
        by_tool = defaultdict(int)
        pattern_list = []
        
        for p in self.patterns:
            by_tool[p.tool] += 1
            pattern_list.append({
                "regex": self._safe_string(p.regex[:100]),
                "tool": p.tool,
                "file": p.file,
                "examples": p.test_examples[:3],
            })
        
        data = {
            "generated_at": datetime.now().isoformat(),
            "total": len(self.patterns),
            "by_tool": dict(by_tool),
            "patterns": pattern_list,
        }
        
        Path(output_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        return output_path
    
    def generate_html(self, output_path: str = "patterns_report.html") -> str:
        """Генерация HTML-отчёта."""
        by_tool = defaultdict(list)
        for p in self.patterns:
            by_tool[p.tool].append(p)
        
        tool_buttons = ""
        tool_sections = ""
        
        for tool, patterns in sorted(by_tool.items()):
            tool_buttons += f'<button class="btn" onclick="show(\'{tool}\')">{tool} ({len(patterns)})</button>\n'
            
            cards = ""
            for p in patterns[:50]:
                regex = self._safe_string(p.regex[:60])
                regex = regex.replace('<', '&lt;').replace('>', '&gt;')
                examples = ', '.join(f'<code>{e}</code>' for e in p.test_examples[:2])
                cards += f'''
                <div class="card">
                    <span class="badge">{tool}</span>
                    <code>{regex}...</code>
                    <div class="examples">{examples}</div>
                </div>'''
            
            tool_sections += f'<div id="{tool}" class="section">{cards}</div>'
        
        html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Pattern Discovery Report</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; background: #f0f0f0; }}
        h1 {{ color: #333; }}
        .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat {{ background: white; padding: 15px 25px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .stat h3 {{ margin: 0; color: #666; font-size: 14px; }}
        .stat .val {{ font-size: 28px; font-weight: bold; color: #333; }}
        .buttons {{ margin: 20px 0; }}
        .btn {{ padding: 8px 16px; margin: 4px; border: none; border-radius: 4px; cursor: pointer; background: #ddd; }}
        .btn:hover {{ background: #3498db; color: white; }}
        .section {{ display: none; }}
        .section.active {{ display: block; }}
        .card {{ background: white; margin: 10px 0; padding: 12px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .card code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 13px; }}
        .badge {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 11px; font-weight: bold; 
                  background: #3498db; color: white; margin-right: 8px; }}
        .examples {{ margin-top: 8px; color: #666; font-size: 13px; }}
    </style>
</head>
<body>
    <h1>Pattern Discovery Report</h1>
    <div class="stats">
        <div class="stat"><h3>Total Patterns</h3><div class="val">{len(self.patterns)}</div></div>
        <div class="stat"><h3>Tools</h3><div class="val">{len(by_tool)}</div></div>
    </div>
    <div class="buttons">
        <button class="btn" onclick="showAll()">All</button>
        {tool_buttons}
    </div>
    {tool_sections}
    <script>
        function show(tool) {{
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            document.getElementById(tool).classList.add('active');
        }}
        function showAll() {{
            document.querySelectorAll('.section').forEach(s => s.classList.add('active'));
        }}
        showAll();
    </script>
</body>
</html>'''
        
        Path(output_path).write_text(html, encoding='utf-8')
        return output_path


# ============================================================================
# CLI INTERFACE
# ============================================================================

def print_summary(patterns: List[DiscoveredPattern]) -> None:
    """Печать сводки."""
    print(f"\n{'='*50}")
    print(f"  PATTERN DISCOVERY SUMMARY")
    print(f"{'='*50}")
    print(f"  Total patterns: {len(patterns)}")
    
    by_tool = defaultdict(int)
    for p in patterns:
        by_tool[p.tool] += 1
    
    print(f"\n  By tool:")
    for tool, count in sorted(by_tool.items(), key=lambda x: -x[1]):
        bar = "#" * min(count, 30)
        print(f"    {tool:12} {bar} {count}")
    
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Pattern Discovery for QwenAgent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument('-p', '--project', default='.', 
                        help='Project path')
    parser.add_argument('--quick', action='store_true',
                        help='Quick mode (PatternRouter only)')
    parser.add_argument('--test', action='store_true',
                        help='Run coverage tests')
    parser.add_argument('--validate', action='store_true',
                        help='Validate patterns')
    parser.add_argument('--report', choices=['md', 'json', 'html', 'all'],
                        help='Report format')
    parser.add_argument('-o', '--output', default='patterns_report',
                        help='Output file base name')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    
    args = parser.parse_args()
    
    print("[*] Pattern Discovery for QwenAgent")
    print("-" * 40)
    
    discovery = PatternDiscovery(args.project)
    
    if args.quick:
        print("[*] Quick mode (PatternRouter only)")
        patterns = discovery.quick_discover()
    else:
        print(f"[*] Scanning: {args.project}")
        patterns = discovery.discover_all()
    
    if not patterns:
        print("[!] No patterns found!")
        return 1
    
    # Генерация тестов
    print("[*] Generating test examples...")
    discovery.generate_tests()
    
    # Сводка
    print_summary(patterns)
    
    # Валидация
    if args.validate:
        print("[*] Validating patterns...")
        result = discovery.validate()
        print(f"    Valid: {result.valid}")
        print(f"    Invalid: {result.invalid}")
        print(f"    Warnings: {result.warnings}")
        
        if args.verbose and result.invalid > 0:
            print("\n    Invalid patterns:")
            for d in result.details:
                if d['status'] == 'invalid':
                    print(f"      {d['regex']}: {d.get('error', '?')}")
    
    # Тесты
    if args.test:
        print("[*] Running coverage tests...")
        report = discovery.run_tests()
        print(f"    Coverage: {report.coverage_percent:.1f}%")
        print(f"    Covered: {report.covered_patterns}/{report.total_patterns}")
        
        if args.verbose and report.uncovered_patterns:
            print(f"\n    Uncovered ({len(report.uncovered_patterns)}):")
            for p in report.uncovered_patterns[:5]:
                print(f"      [{p.tool}] {p.regex[:40]}...")
    
    # Отчёты
    if args.report:
        print("[*] Generating reports...")
        reporter = ReportGenerator(patterns)
        
        if args.report in ('md', 'all'):
            path = reporter.generate_markdown(f"{args.output}.md")
            print(f"    [+] Markdown: {path}")
        
        if args.report in ('json', 'all'):
            path = reporter.generate_json(f"{args.output}.json")
            print(f"    [+] JSON: {path}")
        
        if args.report in ('html', 'all'):
            path = reporter.generate_html(f"{args.output}.html")
            print(f"    [+] HTML: {path}")
    
    print("\n[+] Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
