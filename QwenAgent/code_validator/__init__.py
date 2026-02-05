"""
Code Validator — многоуровневая система валидации AI-сгенерированного Python-кода.

Уровни проверки:
    0. Превалидация (AST-анализ, запрещённые паттерны)
    1. Статический анализ (Ruff, Mypy, Bandit)
    2. Sandbox-выполнение (изолированное исполнение)
    3. Property-тесты (Hypothesis)
    4. Мониторинг ресурсов (память, CPU, время)

Быстрый старт:
    from code_validator import validate_code, is_safe
    
    # Полная валидация
    report = validate_code('''
    def fibonacci(n: int) -> int:
        if n <= 1:
            return n
        return fibonacci(n - 1) + fibonacci(n - 2)
    ''')
    print(report.summary())
    
    # Быстрая проверка безопасности
    if is_safe(code):
        exec(code)

Продвинутое использование:
    from code_validator import CodeValidator, ValidatorConfig
    
    config = ValidatorConfig(
        stop_on_failure=True,
        sandbox_type=SandboxType.DOCKER,
        sandbox_timeout=5.0,
    )
    
    validator = CodeValidator(config)
    report = validator.validate(code, test_function_name="fibonacci")
"""

__version__ = "1.0.0"
__author__ = "Code Validator Team"

# Превалидация
from .prevalidator import (
    Prevalidator,
    PrevalidationResult,
    Issue,
    Severity,
    prevalidate,
    DEFAULT_FORBIDDEN_IMPORTS,
    DEFAULT_FORBIDDEN_BUILTINS,
    DEFAULT_FORBIDDEN_ATTRIBUTES,
)

# Статический анализ
from .static_analysis import (
    StaticAnalyzer,
    StaticAnalysisResult,
    ToolIssue,
    AnalysisTool,
    analyze_static,
)

# Sandbox
from .sandbox import (
    BaseSandbox,
    RestrictedPythonSandbox,
    SubprocessSandbox,
    DockerSandbox,
    SandboxConfig,
    SandboxType,
    ExecutionResult,
    ExecutionStatus,
    create_sandbox,
    execute_safe,
)

# Мониторинг ресурсов
from .resource_guard import (
    ResourceMonitor,
    ResourceGuard,
    ResourceSnapshot,
    ResourceUsageReport,
    ResourceLimits,
    ResourceLimitExceeded,
    MemoryLimitExceeded,
    TimeLimitExceeded,
    resource_limited,
    measure_resources,
)

# Главный валидатор
from .validator import (
    CodeValidator,
    ValidatorConfig,
    ValidationReport,
    ValidationLevel,
    ValidationStatus,
    LevelResult,
    validate_code,
    is_safe,
)

# Property-тесты (опционально)
try:
    from .property_tests import (
        PropertyTester,
        PropertyTestResult,
        PropertyTestSuiteResult,
        PropertyType,
        CommonPropertyChecks,
        test_function_properties,
        HYPOTHESIS_AVAILABLE,
    )
except ImportError:
    HYPOTHESIS_AVAILABLE = False

__all__ = [
    # Версия
    "__version__",
    
    # Превалидация
    "Prevalidator",
    "PrevalidationResult",
    "Issue",
    "Severity",
    "prevalidate",
    "DEFAULT_FORBIDDEN_IMPORTS",
    "DEFAULT_FORBIDDEN_BUILTINS",
    "DEFAULT_FORBIDDEN_ATTRIBUTES",
    
    # Статический анализ
    "StaticAnalyzer",
    "StaticAnalysisResult",
    "ToolIssue",
    "AnalysisTool",
    "analyze_static",
    
    # Sandbox
    "BaseSandbox",
    "RestrictedPythonSandbox",
    "SubprocessSandbox",
    "DockerSandbox",
    "SandboxConfig",
    "SandboxType",
    "ExecutionResult",
    "ExecutionStatus",
    "create_sandbox",
    "execute_safe",
    
    # Мониторинг ресурсов
    "ResourceMonitor",
    "ResourceGuard",
    "ResourceSnapshot",
    "ResourceUsageReport",
    "ResourceLimits",
    "ResourceLimitExceeded",
    "MemoryLimitExceeded",
    "TimeLimitExceeded",
    "resource_limited",
    "measure_resources",
    
    # Главный валидатор
    "CodeValidator",
    "ValidatorConfig",
    "ValidationReport",
    "ValidationLevel",
    "ValidationStatus",
    "LevelResult",
    "validate_code",
    "is_safe",
    
    # Property-тесты
    "PropertyTester",
    "PropertyTestResult",
    "PropertyTestSuiteResult",
    "PropertyType",
    "CommonPropertyChecks",
    "test_function_properties",
    "HYPOTHESIS_AVAILABLE",
]
