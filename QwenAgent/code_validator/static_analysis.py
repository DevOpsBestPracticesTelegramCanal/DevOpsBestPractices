"""
Уровень 1: Статический анализ кода.

Интегрирует внешние инструменты:
- Ruff (линтер + форматтер)
- Mypy (проверка типов)  
- Bandit (безопасность)
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class AnalysisTool(Enum):
    """Доступные инструменты анализа."""
    RUFF = "ruff"
    MYPY = "mypy"
    BANDIT = "bandit"


@dataclass
class ToolIssue:
    """Проблема, найденная инструментом."""
    tool: AnalysisTool
    severity: str
    message: str
    line: int | None = None
    column: int | None = None
    code: str = ""
    
    def __str__(self) -> str:
        location = f":{self.line}" if self.line else ""
        if self.column:
            location += f":{self.column}"
        return f"[{self.tool.value}] {self.code}{location} - {self.message}"


@dataclass
class StaticAnalysisResult:
    """Результат статического анализа."""
    success: bool
    issues: list[ToolIssue] = field(default_factory=list)
    tools_run: list[AnalysisTool] = field(default_factory=list)
    tools_failed: list[tuple[AnalysisTool, str]] = field(default_factory=list)
    
    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity in ("error", "high"))
    
    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity in ("warning", "medium", "low"))


class StaticAnalyzer:
    """Статический анализатор Python-кода."""
    
    def __init__(
        self,
        use_ruff: bool = True,
        use_mypy: bool = True,
        use_bandit: bool = True,
        ruff_config: dict | None = None,
        mypy_config: dict | None = None,
        timeout: int = 30,
    ):
        self.use_ruff = use_ruff
        self.use_mypy = use_mypy
        self.use_bandit = use_bandit
        self.ruff_config = ruff_config or {}
        self.mypy_config = mypy_config or {}
        self.timeout = timeout
    
    def analyze(self, code: str) -> StaticAnalysisResult:
        """Выполнить статический анализ кода."""
        issues: list[ToolIssue] = []
        tools_run: list[AnalysisTool] = []
        tools_failed: list[tuple[AnalysisTool, str]] = []
        
        # Создаём временный файл для анализа
        with tempfile.NamedTemporaryFile(
            mode='w', 
            suffix='.py', 
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write(code)
            temp_path = Path(f.name)
        
        try:
            if self.use_ruff:
                result = self._run_ruff(temp_path)
                if result is not None:
                    issues.extend(result)
                    tools_run.append(AnalysisTool.RUFF)
                else:
                    tools_failed.append((AnalysisTool.RUFF, "Не удалось запустить ruff"))
            
            if self.use_mypy:
                result = self._run_mypy(temp_path)
                if result is not None:
                    issues.extend(result)
                    tools_run.append(AnalysisTool.MYPY)
                else:
                    tools_failed.append((AnalysisTool.MYPY, "Не удалось запустить mypy"))
            
            if self.use_bandit:
                result = self._run_bandit(temp_path)
                if result is not None:
                    issues.extend(result)
                    tools_run.append(AnalysisTool.BANDIT)
                else:
                    tools_failed.append((AnalysisTool.BANDIT, "Не удалось запустить bandit"))
        
        finally:
            temp_path.unlink(missing_ok=True)
        
        # Успех, если нет критических ошибок
        has_critical = any(
            i.severity in ("error", "high") 
            for i in issues
        )
        
        return StaticAnalysisResult(
            success=not has_critical,
            issues=issues,
            tools_run=tools_run,
            tools_failed=tools_failed,
        )
    
    def _run_ruff(self, path: Path) -> list[ToolIssue] | None:
        """Запуск Ruff."""
        try:
            cmd = [
                "ruff", "check",
                "--output-format=json",
                "--select=E,F,B,S,W",  # Ошибки, баги, безопасность, предупреждения
                str(path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            
            issues = []
            if result.stdout:
                try:
                    data = json.loads(result.stdout)
                    for item in data:
                        severity = "error" if item.get("code", "").startswith(("E", "F")) else "warning"
                        issues.append(ToolIssue(
                            tool=AnalysisTool.RUFF,
                            severity=severity,
                            message=item.get("message", ""),
                            line=item.get("location", {}).get("row"),
                            column=item.get("location", {}).get("column"),
                            code=item.get("code", ""),
                        ))
                except json.JSONDecodeError:
                    pass
            
            return issues
            
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            return None
    
    def _run_mypy(self, path: Path) -> list[ToolIssue] | None:
        """Запуск Mypy."""
        try:
            cmd = [
                "mypy",
                "--ignore-missing-imports",
                "--no-error-summary",
                "--show-column-numbers",
                "--no-color-output",
                str(path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            
            issues = []
            for line in result.stdout.splitlines():
                if ": error:" in line or ": note:" in line or ": warning:" in line:
                    parts = line.split(":", 4)
                    if len(parts) >= 4:
                        try:
                            line_num = int(parts[1])
                            col_num = int(parts[2]) if parts[2].strip().isdigit() else None
                            severity_msg = parts[3].strip() if col_num else parts[2].strip()
                            message = parts[4].strip() if len(parts) > 4 else parts[3].strip()
                            
                            severity = "error" if "error" in severity_msg else "warning"
                            
                            issues.append(ToolIssue(
                                tool=AnalysisTool.MYPY,
                                severity=severity,
                                message=message,
                                line=line_num,
                                column=col_num,
                                code="mypy",
                            ))
                        except (ValueError, IndexError):
                            continue
            
            return issues
            
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            return None
    
    def _run_bandit(self, path: Path) -> list[ToolIssue] | None:
        """Запуск Bandit."""
        try:
            cmd = [
                "bandit",
                "-f", "json",
                "-ll",  # Только medium и выше
                str(path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            
            issues = []
            if result.stdout:
                try:
                    data = json.loads(result.stdout)
                    for item in data.get("results", []):
                        severity_map = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
                        issues.append(ToolIssue(
                            tool=AnalysisTool.BANDIT,
                            severity=severity_map.get(item.get("issue_severity", ""), "low"),
                            message=item.get("issue_text", ""),
                            line=item.get("line_number"),
                            code=item.get("test_id", ""),
                        ))
                except json.JSONDecodeError:
                    pass
            
            return issues
            
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            return None
    
    @staticmethod
    def check_tools_available() -> dict[AnalysisTool, bool]:
        """Проверить доступность инструментов."""
        availability = {}
        
        for tool in AnalysisTool:
            try:
                subprocess.run(
                    [tool.value, "--version"],
                    capture_output=True,
                    timeout=5,
                )
                availability[tool] = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                availability[tool] = False
        
        return availability


def analyze_static(code: str, **kwargs) -> StaticAnalysisResult:
    """Функция-обёртка для быстрого статического анализа."""
    analyzer = StaticAnalyzer(**kwargs)
    return analyzer.analyze(code)
