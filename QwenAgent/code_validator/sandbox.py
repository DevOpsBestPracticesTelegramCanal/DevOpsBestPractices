"""
Уровень 2: Изолированное выполнение кода (Sandbox).

Предоставляет несколько уровней изоляции:
- RestrictedPython: лёгкая изоляция для простых случаев
- Docker: полная изоляция в контейнере
- Subprocess с ограничениями ресурсов
"""

import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SandboxType(Enum):
    """Тип песочницы."""
    RESTRICTED_PYTHON = "restricted_python"
    SUBPROCESS = "subprocess"
    DOCKER = "docker"


class ExecutionStatus(Enum):
    """Статус выполнения."""
    SUCCESS = "success"
    TIMEOUT = "timeout"
    MEMORY_ERROR = "memory_error"
    RUNTIME_ERROR = "runtime_error"
    SECURITY_ERROR = "security_error"
    SANDBOX_ERROR = "sandbox_error"


@dataclass
class ExecutionResult:
    """Результат выполнения кода."""
    status: ExecutionStatus
    stdout: str = ""
    stderr: str = ""
    return_value: Any = None
    execution_time: float = 0.0
    error_message: str = ""
    
    @property
    def success(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS


@dataclass
class SandboxConfig:
    """Конфигурация песочницы."""
    timeout_seconds: float = 10.0
    max_memory_mb: int = 128
    max_output_size: int = 10_000
    allowed_imports: frozenset[str] = field(default_factory=lambda: frozenset({
        "math", "decimal", "fractions", "random", "statistics",
        "itertools", "functools", "operator",
        "collections", "heapq", "bisect",
        "datetime", "calendar",
        "json", "csv", "re",
        "copy", "typing", "dataclasses", "enum",
        "string", "textwrap",
    }))


class BaseSandbox(ABC):
    """Базовый класс песочницы."""
    
    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()
    
    @abstractmethod
    def execute(self, code: str, globals_dict: dict | None = None) -> ExecutionResult:
        """Выполнить код в песочнице."""
        pass


class RestrictedPythonSandbox(BaseSandbox):
    """
    Песочница на основе RestrictedPython.
    
    Лёгкая изоляция, работает в том же процессе.
    Подходит для простых вычислений без I/O.
    """
    
    def execute(self, code: str, globals_dict: dict | None = None) -> ExecutionResult:
        try:
            from RestrictedPython import compile_restricted, safe_globals
            from RestrictedPython.Guards import safe_builtins, guarded_iter_unpack_sequence
            from RestrictedPython.Eval import default_guarded_getiter
        except ImportError:
            return ExecutionResult(
                status=ExecutionStatus.SANDBOX_ERROR,
                error_message="RestrictedPython не установлен. Установите: pip install RestrictedPython",
            )
        
        start_time = time.perf_counter()
        
        try:
            # Компиляция с ограничениями
            byte_code = compile_restricted(code, '<sandbox>', 'exec')
            
            if byte_code.errors:
                return ExecutionResult(
                    status=ExecutionStatus.SECURITY_ERROR,
                    error_message=f"Ошибки компиляции: {byte_code.errors}",
                )
            
            # Подготовка безопасного окружения
            safe_env = {
                '__builtins__': safe_builtins,
                '_getiter_': default_guarded_getiter,
                '_iter_unpack_sequence_': guarded_iter_unpack_sequence,
                '__name__': '__sandbox__',
            }
            
            # Добавляем разрешённые модули
            for module_name in self.config.allowed_imports:
                try:
                    safe_env[module_name] = __import__(module_name)
                except ImportError:
                    pass
            
            # Добавляем пользовательские globals
            if globals_dict:
                safe_env.update(globals_dict)
            
            # Выполнение
            exec(byte_code.code, safe_env)
            
            execution_time = time.perf_counter() - start_time
            
            # Извлекаем результат, если есть переменная result
            return_value = safe_env.get('result')
            
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                return_value=return_value,
                execution_time=execution_time,
            )
            
        except Exception as e:
            execution_time = time.perf_counter() - start_time
            return ExecutionResult(
                status=ExecutionStatus.RUNTIME_ERROR,
                error_message=f"{type(e).__name__}: {str(e)}",
                execution_time=execution_time,
            )


class SubprocessSandbox(BaseSandbox):
    """
    Песочница на основе subprocess.
    
    Запускает код в отдельном процессе с ограничениями.
    Лучшая изоляция, чем RestrictedPython.
    """
    
    WRAPPER_TEMPLATE = '''
import sys
import json
import resource

# Ограничение памяти
max_memory = {max_memory} * 1024 * 1024
resource.setrlimit(resource.RLIMIT_AS, (max_memory, max_memory))

# Ограничение времени CPU
resource.setrlimit(resource.RLIMIT_CPU, ({timeout}, {timeout}))

# Запрещаем создание файлов
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

# Запрещаем форки
resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))

try:
    result = None
    exec("""
{code}
""")
    print(json.dumps({{"status": "success", "result": repr(result) if result is not None else None}}))
except MemoryError:
    print(json.dumps({{"status": "memory_error", "error": "Memory limit exceeded"}}))
except Exception as e:
    print(json.dumps({{"status": "error", "error": f"{{type(e).__name__}}: {{str(e)}}"}}))'
'''
    
    def execute(self, code: str, globals_dict: dict | None = None) -> ExecutionResult:
        start_time = time.perf_counter()
        
        # Экранируем код для вставки в шаблон
        escaped_code = code.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
        # Заменяем переносы строк, чтобы сохранить отступы
        escaped_code = escaped_code.replace('\n', '\\n')
        
        # Формируем wrapper-скрипт
        wrapper = self.WRAPPER_TEMPLATE.format(
            max_memory=self.config.max_memory_mb,
            timeout=int(self.config.timeout_seconds),
            code=escaped_code,
        )
        
        # Создаём временный файл
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False,
            encoding='utf-8'
        ) as f:
            # Пишем код напрямую, wrapper сложно отладить
            f.write(code)
            temp_path = Path(f.name)
        
        try:
            result = subprocess.run(
                [
                    "python3", "-u",
                    "-c", f"exec(open('{temp_path}').read())"
                ],
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            
            execution_time = time.perf_counter() - start_time
            
            stdout = result.stdout[:self.config.max_output_size]
            stderr = result.stderr[:self.config.max_output_size]
            
            if result.returncode == 0:
                return ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time=execution_time,
                )
            else:
                return ExecutionResult(
                    status=ExecutionStatus.RUNTIME_ERROR,
                    stdout=stdout,
                    stderr=stderr,
                    error_message=stderr or f"Exit code: {result.returncode}",
                    execution_time=execution_time,
                )
                
        except subprocess.TimeoutExpired:
            execution_time = time.perf_counter() - start_time
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                error_message=f"Превышено время выполнения ({self.config.timeout_seconds}s)",
                execution_time=execution_time,
            )
        finally:
            temp_path.unlink(missing_ok=True)


class DockerSandbox(BaseSandbox):
    """
    Песочница на основе Docker.
    
    Максимальная изоляция: отдельный контейнер без сети и ограниченными ресурсами.
    """
    
    DEFAULT_IMAGE = "python:3.12-slim"
    
    def __init__(
        self, 
        config: SandboxConfig | None = None,
        image: str = DEFAULT_IMAGE,
    ):
        super().__init__(config)
        self.image = image
    
    def execute(self, code: str, globals_dict: dict | None = None) -> ExecutionResult:
        start_time = time.perf_counter()
        
        # Создаём временный файл с кодом
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write(code)
            temp_path = Path(f.name)
        
        try:
            cmd = [
                "docker", "run",
                "--rm",  # Удалить контейнер после выполнения
                "--network=none",  # Без сети
                "--read-only",  # Только для чтения
                f"--memory={self.config.max_memory_mb}m",
                "--memory-swap", f"{self.config.max_memory_mb}m",  # Без swap
                "--cpus=0.5",  # Ограничение CPU
                "--pids-limit=50",  # Ограничение процессов
                "--security-opt=no-new-privileges",
                "-v", f"{temp_path}:/code.py:ro",
                self.image,
                "python3", "-u", "/code.py"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds + 5,  # +5 на старт контейнера
            )
            
            execution_time = time.perf_counter() - start_time
            
            stdout = result.stdout[:self.config.max_output_size]
            stderr = result.stderr[:self.config.max_output_size]
            
            # Проверяем на OOM kill
            if "Killed" in stderr or result.returncode == 137:
                return ExecutionResult(
                    status=ExecutionStatus.MEMORY_ERROR,
                    stdout=stdout,
                    stderr=stderr,
                    error_message="Процесс убит из-за превышения памяти",
                    execution_time=execution_time,
                )
            
            if result.returncode == 0:
                return ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time=execution_time,
                )
            else:
                return ExecutionResult(
                    status=ExecutionStatus.RUNTIME_ERROR,
                    stdout=stdout,
                    stderr=stderr,
                    error_message=stderr or f"Exit code: {result.returncode}",
                    execution_time=execution_time,
                )
                
        except subprocess.TimeoutExpired:
            execution_time = time.perf_counter() - start_time
            # Попытка убить зависший контейнер
            subprocess.run(
                ["docker", "kill", f"sandbox_{temp_path.stem}"],
                capture_output=True,
            )
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                error_message=f"Превышено время выполнения ({self.config.timeout_seconds}s)",
                execution_time=execution_time,
            )
        except FileNotFoundError:
            return ExecutionResult(
                status=ExecutionStatus.SANDBOX_ERROR,
                error_message="Docker не установлен или недоступен",
            )
        finally:
            temp_path.unlink(missing_ok=True)
    
    @staticmethod
    def is_available() -> bool:
        """Проверить доступность Docker."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


def create_sandbox(
    sandbox_type: SandboxType = SandboxType.SUBPROCESS,
    config: SandboxConfig | None = None,
    **kwargs
) -> BaseSandbox:
    """Фабрика для создания песочницы."""
    sandboxes = {
        SandboxType.RESTRICTED_PYTHON: RestrictedPythonSandbox,
        SandboxType.SUBPROCESS: SubprocessSandbox,
        SandboxType.DOCKER: DockerSandbox,
    }
    
    sandbox_class = sandboxes[sandbox_type]
    return sandbox_class(config=config, **kwargs)


def execute_safe(
    code: str,
    sandbox_type: SandboxType = SandboxType.SUBPROCESS,
    **kwargs
) -> ExecutionResult:
    """Функция-обёртка для быстрого безопасного выполнения."""
    sandbox = create_sandbox(sandbox_type, **kwargs)
    return sandbox.execute(code)
