"""
Главный класс-оркестратор многоуровневой валидации.

Объединяет все уровни проверки в единый pipeline:
0. Превалидация (AST)
1. Статический анализ (Ruff, Mypy, Bandit)
2. Sandbox-выполнение
3. Property-тесты
4. Мониторинг ресурсов
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .prevalidator import Prevalidator, PrevalidationResult, Severity, Issue
from .static_analysis import StaticAnalyzer, StaticAnalysisResult, AnalysisTool
from .sandbox import (
    BaseSandbox, 
    SubprocessSandbox, 
    DockerSandbox,
    SandboxConfig,
    SandboxType,
    ExecutionResult,
    ExecutionStatus,
    create_sandbox,
)
from .resource_guard import (
    ResourceGuard, 
    ResourceUsageReport, 
    ResourceLimits,
    measure_resources,
)

# Опциональный импорт property_tests
try:
    from .property_tests import (
        PropertyTester,
        PropertyTestSuiteResult,
        HYPOTHESIS_AVAILABLE,
    )
except ImportError:
    HYPOTHESIS_AVAILABLE = False
    PropertyTester = None
    PropertyTestSuiteResult = None


class ValidationLevel(Enum):
    """Уровни валидации."""
    PREVALIDATION = 0
    STATIC_ANALYSIS = 1
    SANDBOX_EXECUTION = 2
    PROPERTY_TESTING = 3
    RESOURCE_MONITORING = 4


class ValidationStatus(Enum):
    """Итоговый статус валидации."""
    PASSED = "passed"
    WARNINGS = "warnings"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class LevelResult:
    """Результат одного уровня валидации."""
    level: ValidationLevel
    passed: bool
    duration_seconds: float = 0.0
    details: Any = None
    error_message: str = ""
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class ValidationReport:
    """Полный отчёт о валидации кода."""
    status: ValidationStatus
    code_hash: str
    total_duration_seconds: float
    levels_completed: int
    level_results: dict[ValidationLevel, LevelResult] = field(default_factory=dict)
    
    @property
    def prevalidation(self) -> LevelResult | None:
        return self.level_results.get(ValidationLevel.PREVALIDATION)
    
    @property
    def static_analysis(self) -> LevelResult | None:
        return self.level_results.get(ValidationLevel.STATIC_ANALYSIS)
    
    @property
    def sandbox_execution(self) -> LevelResult | None:
        return self.level_results.get(ValidationLevel.SANDBOX_EXECUTION)
    
    @property
    def property_testing(self) -> LevelResult | None:
        return self.level_results.get(ValidationLevel.PROPERTY_TESTING)
    
    @property
    def resource_monitoring(self) -> LevelResult | None:
        return self.level_results.get(ValidationLevel.RESOURCE_MONITORING)
    
    def summary(self) -> str:
        """Краткая сводка отчёта."""
        lines = [
            f"{'═' * 50}",
            f"  ОТЧЁТ О ВАЛИДАЦИИ",
            f"{'═' * 50}",
            f"  Статус: {self.status.value.upper()}",
            f"  Время: {self.total_duration_seconds:.3f}s",
            f"  Пройдено уровней: {self.levels_completed}/5",
            f"{'─' * 50}",
        ]
        
        status_icons = {True: "✓", False: "✗", None: "○"}
        
        for level in ValidationLevel:
            result = self.level_results.get(level)
            if result:
                if result.skipped:
                    icon = "⊘"
                    status_text = f"пропущен ({result.skip_reason})"
                else:
                    icon = status_icons[result.passed]
                    status_text = f"{result.duration_seconds:.3f}s"
                    if not result.passed and result.error_message:
                        status_text += f" - {result.error_message[:50]}"
            else:
                icon = "○"
                status_text = "не запускался"
            
            lines.append(f"  {icon} {level.name}: {status_text}")
        
        lines.append(f"{'═' * 50}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """Конвертация в словарь для JSON."""
        return {
            "status": self.status.value,
            "code_hash": self.code_hash,
            "total_duration_seconds": self.total_duration_seconds,
            "levels_completed": self.levels_completed,
            "levels": {
                level.name: {
                    "passed": result.passed,
                    "duration": result.duration_seconds,
                    "skipped": result.skipped,
                    "error": result.error_message,
                }
                for level, result in self.level_results.items()
            }
        }


@dataclass
class ValidatorConfig:
    """Конфигурация валидатора."""
    # Общие настройки
    stop_on_failure: bool = True  # Остановиться при первой ошибке
    
    # Уровень 0: Превалидация
    enable_prevalidation: bool = True
    max_code_length: int = 50_000
    max_lines: int = 1000
    forbidden_imports: frozenset[str] | None = None
    
    # Уровень 1: Статический анализ
    enable_static_analysis: bool = True
    use_ruff: bool = True
    use_mypy: bool = True
    use_bandit: bool = True
    static_analysis_timeout: int = 30
    
    # Уровень 2: Sandbox
    enable_sandbox: bool = True
    sandbox_type: SandboxType = SandboxType.SUBPROCESS
    sandbox_timeout: float = 10.0
    sandbox_max_memory_mb: int = 128
    
    # Уровень 3: Property-тесты
    enable_property_tests: bool = True
    property_test_examples: int = 100
    
    # Уровень 4: Мониторинг ресурсов
    enable_resource_monitoring: bool = True
    resource_max_memory_mb: float = 256
    resource_max_time_seconds: float = 30


class CodeValidator:
    """
    Многоуровневый валидатор Python-кода.
    
    Пример использования:
        validator = CodeValidator()
        report = validator.validate(code)
        print(report.summary())
    """
    
    def __init__(self, config: ValidatorConfig | None = None):
        self.config = config or ValidatorConfig()
        
        # Инициализация компонентов
        self._prevalidator: Prevalidator | None = None
        self._static_analyzer: StaticAnalyzer | None = None
        self._sandbox: BaseSandbox | None = None
        self._property_tester: Any = None  # PropertyTester, если доступен
    
    def _get_prevalidator(self) -> Prevalidator:
        if self._prevalidator is None:
            self._prevalidator = Prevalidator(
                max_code_length=self.config.max_code_length,
                max_lines=self.config.max_lines,
                forbidden_imports=self.config.forbidden_imports,
            )
        return self._prevalidator
    
    def _get_static_analyzer(self) -> StaticAnalyzer:
        if self._static_analyzer is None:
            self._static_analyzer = StaticAnalyzer(
                use_ruff=self.config.use_ruff,
                use_mypy=self.config.use_mypy,
                use_bandit=self.config.use_bandit,
                timeout=self.config.static_analysis_timeout,
            )
        return self._static_analyzer
    
    def _get_sandbox(self) -> BaseSandbox:
        if self._sandbox is None:
            sandbox_config = SandboxConfig(
                timeout_seconds=self.config.sandbox_timeout,
                max_memory_mb=self.config.sandbox_max_memory_mb,
            )
            self._sandbox = create_sandbox(
                self.config.sandbox_type,
                config=sandbox_config,
            )
        return self._sandbox
    
    def _get_property_tester(self) -> Any:
        if not HYPOTHESIS_AVAILABLE:
            return None
        if self._property_tester is None:
            self._property_tester = PropertyTester(
                max_examples=self.config.property_test_examples,
            )
        return self._property_tester
    
    def validate(
        self,
        code: str,
        test_function_name: str | None = None,
        custom_globals: dict | None = None,
    ) -> ValidationReport:
        """
        Выполнить полную валидацию кода.
        
        Args:
            code: Python-код для валидации
            test_function_name: Имя функции для property-тестов (опционально)
            custom_globals: Дополнительные глобальные переменные для выполнения
        
        Returns:
            ValidationReport с результатами всех уровней
        """
        import hashlib
        
        start_time = time.perf_counter()
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        level_results: dict[ValidationLevel, LevelResult] = {}
        levels_completed = 0
        has_warnings = False
        has_failures = False
        
        # === УРОВЕНЬ 0: Превалидация ===
        if self.config.enable_prevalidation:
            level_start = time.perf_counter()
            try:
                prevalidator = self._get_prevalidator()
                result = prevalidator.validate(code)
                
                level_results[ValidationLevel.PREVALIDATION] = LevelResult(
                    level=ValidationLevel.PREVALIDATION,
                    passed=result.is_valid,
                    duration_seconds=time.perf_counter() - level_start,
                    details=result,
                    error_message="; ".join(str(i) for i in result.issues[:3]) if result.issues else "",
                )
                
                if result.is_valid:
                    levels_completed += 1
                elif any(i.severity == Severity.WARNING for i in result.issues):
                    has_warnings = True
                    levels_completed += 1
                else:
                    has_failures = True
                    if self.config.stop_on_failure:
                        return self._make_report(
                            code_hash, start_time, level_results, 
                            levels_completed, has_warnings, has_failures
                        )
                        
            except Exception as e:
                level_results[ValidationLevel.PREVALIDATION] = LevelResult(
                    level=ValidationLevel.PREVALIDATION,
                    passed=False,
                    duration_seconds=time.perf_counter() - level_start,
                    error_message=f"Ошибка превалидации: {str(e)}",
                )
                has_failures = True
                if self.config.stop_on_failure:
                    return self._make_report(
                        code_hash, start_time, level_results,
                        levels_completed, has_warnings, has_failures
                    )
        
        # === УРОВЕНЬ 1: Статический анализ ===
        if self.config.enable_static_analysis:
            level_start = time.perf_counter()
            try:
                analyzer = self._get_static_analyzer()
                result = analyzer.analyze(code)
                
                passed = result.success
                if result.error_count > 0:
                    has_failures = True
                    passed = False
                elif result.warning_count > 0:
                    has_warnings = True
                
                level_results[ValidationLevel.STATIC_ANALYSIS] = LevelResult(
                    level=ValidationLevel.STATIC_ANALYSIS,
                    passed=passed,
                    duration_seconds=time.perf_counter() - level_start,
                    details=result,
                    error_message="; ".join(str(i) for i in result.issues[:3]) if result.issues else "",
                )
                
                if passed:
                    levels_completed += 1
                elif self.config.stop_on_failure and not result.success:
                    return self._make_report(
                        code_hash, start_time, level_results,
                        levels_completed, has_warnings, has_failures
                    )
                    
            except Exception as e:
                level_results[ValidationLevel.STATIC_ANALYSIS] = LevelResult(
                    level=ValidationLevel.STATIC_ANALYSIS,
                    passed=False,
                    duration_seconds=time.perf_counter() - level_start,
                    error_message=f"Ошибка статического анализа: {str(e)}",
                )
        
        # === УРОВЕНЬ 2: Sandbox-выполнение ===
        if self.config.enable_sandbox:
            level_start = time.perf_counter()
            try:
                sandbox = self._get_sandbox()
                result = sandbox.execute(code, custom_globals)
                
                passed = result.success
                if not passed:
                    has_failures = True
                
                level_results[ValidationLevel.SANDBOX_EXECUTION] = LevelResult(
                    level=ValidationLevel.SANDBOX_EXECUTION,
                    passed=passed,
                    duration_seconds=time.perf_counter() - level_start,
                    details=result,
                    error_message=result.error_message,
                )
                
                if passed:
                    levels_completed += 1
                elif self.config.stop_on_failure:
                    return self._make_report(
                        code_hash, start_time, level_results,
                        levels_completed, has_warnings, has_failures
                    )
                    
            except Exception as e:
                level_results[ValidationLevel.SANDBOX_EXECUTION] = LevelResult(
                    level=ValidationLevel.SANDBOX_EXECUTION,
                    passed=False,
                    duration_seconds=time.perf_counter() - level_start,
                    error_message=f"Ошибка sandbox: {str(e)}",
                )
                has_failures = True
        
        # === УРОВЕНЬ 3: Property-тесты ===
        if self.config.enable_property_tests and test_function_name:
            level_start = time.perf_counter()
            
            if not HYPOTHESIS_AVAILABLE:
                level_results[ValidationLevel.PROPERTY_TESTING] = LevelResult(
                    level=ValidationLevel.PROPERTY_TESTING,
                    passed=True,
                    skipped=True,
                    skip_reason="Hypothesis не установлен",
                )
            else:
                try:
                    # Извлекаем функцию из кода
                    local_ns: dict = {}
                    exec(code, custom_globals or {}, local_ns)
                    
                    if test_function_name in local_ns:
                        func = local_ns[test_function_name]
                        tester = self._get_property_tester()
                        result = tester.run_all_tests(func)
                        
                        passed = result.all_passed
                        if not passed:
                            has_warnings = True  # Property-тесты — предупреждения
                        
                        level_results[ValidationLevel.PROPERTY_TESTING] = LevelResult(
                            level=ValidationLevel.PROPERTY_TESTING,
                            passed=passed,
                            duration_seconds=time.perf_counter() - level_start,
                            details=result,
                            error_message=f"Провалено: {result.failed_count}/{len(result.results)}" if not passed else "",
                        )
                        
                        if passed:
                            levels_completed += 1
                    else:
                        level_results[ValidationLevel.PROPERTY_TESTING] = LevelResult(
                            level=ValidationLevel.PROPERTY_TESTING,
                            passed=True,
                            skipped=True,
                            skip_reason=f"Функция '{test_function_name}' не найдена",
                        )
                        
                except Exception as e:
                    level_results[ValidationLevel.PROPERTY_TESTING] = LevelResult(
                        level=ValidationLevel.PROPERTY_TESTING,
                        passed=False,
                        duration_seconds=time.perf_counter() - level_start,
                        error_message=f"Ошибка property-тестов: {str(e)}",
                    )
        elif self.config.enable_property_tests:
            level_results[ValidationLevel.PROPERTY_TESTING] = LevelResult(
                level=ValidationLevel.PROPERTY_TESTING,
                passed=True,
                skipped=True,
                skip_reason="Имя функции не указано",
            )
        
        # === УРОВЕНЬ 4: Мониторинг ресурсов ===
        if self.config.enable_resource_monitoring:
            level_start = time.perf_counter()
            
            # Уже выполняли в sandbox, берём данные оттуда
            sandbox_result = level_results.get(ValidationLevel.SANDBOX_EXECUTION)
            if sandbox_result and sandbox_result.details:
                exec_result: ExecutionResult = sandbox_result.details
                
                level_results[ValidationLevel.RESOURCE_MONITORING] = LevelResult(
                    level=ValidationLevel.RESOURCE_MONITORING,
                    passed=exec_result.status not in (
                        ExecutionStatus.TIMEOUT, 
                        ExecutionStatus.MEMORY_ERROR
                    ),
                    duration_seconds=time.perf_counter() - level_start,
                    details={
                        "execution_time": exec_result.execution_time,
                        "status": exec_result.status.value,
                    },
                )
                
                if exec_result.status == ExecutionStatus.SUCCESS:
                    levels_completed += 1
            else:
                level_results[ValidationLevel.RESOURCE_MONITORING] = LevelResult(
                    level=ValidationLevel.RESOURCE_MONITORING,
                    passed=True,
                    skipped=True,
                    skip_reason="Sandbox не выполнялся",
                )
        
        return self._make_report(
            code_hash, start_time, level_results,
            levels_completed, has_warnings, has_failures
        )
    
    def _make_report(
        self,
        code_hash: str,
        start_time: float,
        level_results: dict[ValidationLevel, LevelResult],
        levels_completed: int,
        has_warnings: bool,
        has_failures: bool,
    ) -> ValidationReport:
        """Сформировать итоговый отчёт."""
        if has_failures:
            status = ValidationStatus.FAILED
        elif has_warnings:
            status = ValidationStatus.WARNINGS
        else:
            status = ValidationStatus.PASSED
        
        return ValidationReport(
            status=status,
            code_hash=code_hash,
            total_duration_seconds=time.perf_counter() - start_time,
            levels_completed=levels_completed,
            level_results=level_results,
        )
    
    def quick_check(self, code: str) -> bool:
        """Быстрая проверка: только превалидация и статический анализ."""
        original_config = self.config
        
        self.config = ValidatorConfig(
            enable_prevalidation=True,
            enable_static_analysis=True,
            enable_sandbox=False,
            enable_property_tests=False,
            enable_resource_monitoring=False,
        )
        
        try:
            report = self.validate(code)
            return report.status in (ValidationStatus.PASSED, ValidationStatus.WARNINGS)
        finally:
            self.config = original_config


def validate_code(code: str, **kwargs) -> ValidationReport:
    """
    Функция-обёртка для быстрой валидации.
    
    Использование:
        report = validate_code('''
        def add(a, b):
            return a + b
        ''')
        print(report.summary())
    """
    config = ValidatorConfig(**kwargs)
    validator = CodeValidator(config)
    return validator.validate(code)


def is_safe(code: str) -> bool:
    """
    Проверить, безопасен ли код для выполнения.
    
    Выполняет только превалидацию (самая быстрая проверка).
    """
    prevalidator = Prevalidator()
    result = prevalidator.validate(code)
    return result.is_valid
