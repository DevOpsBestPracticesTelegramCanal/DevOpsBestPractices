"""
Уровень 4: Мониторинг ресурсов при выполнении кода.

Отслеживает:
- Потребление памяти
- Время выполнения
- Использование CPU
- Операции ввода-вывода
"""

import os
import signal
import sys
import time
import threading
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any

# Опциональный импорт resource (только Unix)
try:
    import resource
    RESOURCE_AVAILABLE = True
except ImportError:
    RESOURCE_AVAILABLE = False

# Опциональный импорт psutil
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class ResourceLimitExceeded(Exception):
    """Исключение при превышении лимита ресурсов."""
    pass


class MemoryLimitExceeded(ResourceLimitExceeded):
    """Превышен лимит памяти."""
    pass


class TimeLimitExceeded(ResourceLimitExceeded):
    """Превышен лимит времени."""
    pass


class CPULimitExceeded(ResourceLimitExceeded):
    """Превышен лимит CPU."""
    pass


@dataclass
class ResourceSnapshot:
    """Снимок использования ресурсов."""
    timestamp: float
    memory_current_mb: float = 0.0
    memory_peak_mb: float = 0.0
    cpu_time_user: float = 0.0
    cpu_time_system: float = 0.0
    wall_time: float = 0.0


@dataclass
class ResourceUsageReport:
    """Отчёт об использовании ресурсов."""
    success: bool
    wall_time_seconds: float = 0.0
    cpu_time_seconds: float = 0.0
    memory_peak_mb: float = 0.0
    memory_average_mb: float = 0.0
    snapshots: list[ResourceSnapshot] = field(default_factory=list)
    limit_exceeded: str | None = None
    error_message: str = ""
    return_value: Any = None
    
    def summary(self) -> str:
        """Краткая сводка."""
        status = "✓" if self.success else "✗"
        return (
            f"{status} Время: {self.wall_time_seconds:.3f}s | "
            f"CPU: {self.cpu_time_seconds:.3f}s | "
            f"Память (пик): {self.memory_peak_mb:.1f}MB"
        )


@dataclass
class ResourceLimits:
    """Лимиты ресурсов."""
    max_memory_mb: float = 256.0
    max_wall_time_seconds: float = 30.0
    max_cpu_time_seconds: float = 30.0
    max_output_size_bytes: int = 1_000_000
    
    # Мягкие лимиты (предупреждения)
    warn_memory_mb: float = 200.0
    warn_wall_time_seconds: float = 20.0


class ResourceMonitor:
    """
    Монитор ресурсов.
    
    Отслеживает использование ресурсов в отдельном потоке
    и может прервать выполнение при превышении лимитов.
    """
    
    def __init__(
        self,
        limits: ResourceLimits | None = None,
        sample_interval: float = 0.1,
    ):
        self.limits = limits or ResourceLimits()
        self.sample_interval = sample_interval
        
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None
        self._snapshots: list[ResourceSnapshot] = []
        self._start_time: float = 0.0
        self._start_cpu: tuple[float, float] = (0.0, 0.0)
        self._target_pid: int | None = None
        self._limit_exceeded: str | None = None
    
    def start(self, pid: int | None = None) -> None:
        """Начать мониторинг."""
        self._target_pid = pid or os.getpid()
        self._snapshots = []
        self._limit_exceeded = None
        self._start_time = time.perf_counter()
        
        if RESOURCE_AVAILABLE:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            self._start_cpu = (usage.ru_utime, usage.ru_stime)
        
        tracemalloc.start()
        
        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def stop(self) -> ResourceUsageReport:
        """Остановить мониторинг и вернуть отчёт."""
        self._monitoring = False
        
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        
        wall_time = time.perf_counter() - self._start_time
        
        # Финальный снимок
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        cpu_time = 0.0
        if RESOURCE_AVAILABLE:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            cpu_time = (usage.ru_utime - self._start_cpu[0]) + (usage.ru_stime - self._start_cpu[1])
        
        peak_mb = peak / (1024 * 1024)
        
        # Средняя память
        if self._snapshots:
            avg_mb = sum(s.memory_current_mb for s in self._snapshots) / len(self._snapshots)
        else:
            avg_mb = peak_mb
        
        success = self._limit_exceeded is None
        
        return ResourceUsageReport(
            success=success,
            wall_time_seconds=wall_time,
            cpu_time_seconds=cpu_time,
            memory_peak_mb=peak_mb,
            memory_average_mb=avg_mb,
            snapshots=self._snapshots,
            limit_exceeded=self._limit_exceeded,
        )
    
    def _monitor_loop(self) -> None:
        """Цикл мониторинга в отдельном потоке."""
        while self._monitoring:
            snapshot = self._take_snapshot()
            self._snapshots.append(snapshot)
            
            # Проверка лимитов
            if snapshot.memory_peak_mb > self.limits.max_memory_mb:
                self._limit_exceeded = f"memory:{snapshot.memory_peak_mb:.1f}MB"
                self._monitoring = False
                break
            
            if snapshot.wall_time > self.limits.max_wall_time_seconds:
                self._limit_exceeded = f"wall_time:{snapshot.wall_time:.1f}s"
                self._monitoring = False
                break
            
            time.sleep(self.sample_interval)
    
    def _take_snapshot(self) -> ResourceSnapshot:
        """Сделать снимок ресурсов."""
        current, peak = tracemalloc.get_traced_memory()
        wall_time = time.perf_counter() - self._start_time
        
        cpu_user = 0.0
        cpu_system = 0.0
        
        if RESOURCE_AVAILABLE:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            cpu_user = usage.ru_utime - self._start_cpu[0]
            cpu_system = usage.ru_stime - self._start_cpu[1]
        
        return ResourceSnapshot(
            timestamp=time.time(),
            memory_current_mb=current / (1024 * 1024),
            memory_peak_mb=peak / (1024 * 1024),
            cpu_time_user=cpu_user,
            cpu_time_system=cpu_system,
            wall_time=wall_time,
        )


class ResourceGuard:
    """
    Контекстный менеджер для ограничения ресурсов.
    
    Использование:
        with ResourceGuard(max_memory_mb=100, max_time_seconds=5) as guard:
            result = expensive_function()
        print(guard.report.summary())
    """
    
    def __init__(
        self,
        max_memory_mb: float = 256,
        max_time_seconds: float = 30,
        enforce_limits: bool = True,
    ):
        self.limits = ResourceLimits(
            max_memory_mb=max_memory_mb,
            max_wall_time_seconds=max_time_seconds,
            max_cpu_time_seconds=max_time_seconds,
        )
        self.enforce_limits = enforce_limits
        self.monitor = ResourceMonitor(limits=self.limits)
        self.report: ResourceUsageReport | None = None
        self._alarm_triggered = False
    
    def __enter__(self) -> "ResourceGuard":
        self.monitor.start()
        
        if self.enforce_limits and RESOURCE_AVAILABLE:
            # Установка лимита памяти (только Linux)
            try:
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                limit_bytes = int(self.limits.max_memory_mb * 1024 * 1024)
                resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, hard))
            except (ValueError, OSError):
                pass  # Не все системы поддерживают
            
            # Установка таймера
            def alarm_handler(signum, frame):
                self._alarm_triggered = True
                raise TimeLimitExceeded(
                    f"Превышено время выполнения: {self.limits.max_wall_time_seconds}s"
                )
            
            signal.signal(signal.SIGALRM, alarm_handler)
            signal.alarm(int(self.limits.max_wall_time_seconds) + 1)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self.enforce_limits:
            signal.alarm(0)  # Отмена таймера
        
        self.report = self.monitor.stop()
        
        # Обработка исключений
        if exc_type is not None:
            if exc_type is MemoryError:
                self.report.limit_exceeded = "memory:MemoryError"
                self.report.success = False
                self.report.error_message = "Превышен лимит памяти (MemoryError)"
            elif exc_type is TimeLimitExceeded:
                self.report.success = False
                self.report.error_message = str(exc_val)
        
        return False  # Не подавляем исключения


@contextmanager
def resource_limited(
    max_memory_mb: float = 256,
    max_time_seconds: float = 30,
):
    """
    Контекстный менеджер-обёртка.
    
    Использование:
        with resource_limited(max_memory_mb=100, max_time_seconds=5):
            do_something()
    """
    guard = ResourceGuard(
        max_memory_mb=max_memory_mb,
        max_time_seconds=max_time_seconds,
    )
    
    with guard:
        yield guard
    
    if guard.report and not guard.report.success:
        raise ResourceLimitExceeded(guard.report.error_message or guard.report.limit_exceeded)


def measure_resources(func: Callable, *args, **kwargs) -> ResourceUsageReport:
    """
    Измерить ресурсы при выполнении функции.
    
    Использование:
        report = measure_resources(my_function, arg1, arg2, kwarg1=value)
        print(report.summary())
    """
    monitor = ResourceMonitor()
    monitor.start()
    
    try:
        result = func(*args, **kwargs)
        report = monitor.stop()
        report.return_value = result
        return report
    except Exception as e:
        report = monitor.stop()
        report.success = False
        report.error_message = f"{type(e).__name__}: {str(e)}"
        return report


class MemoryProfiler:
    """
    Профилировщик памяти для детального анализа.
    
    Позволяет отслеживать, какие строки кода потребляют память.
    """
    
    def __init__(self, top_n: int = 10):
        self.top_n = top_n
        self._snapshot: Any = None
    
    def start(self) -> None:
        """Начать профилирование."""
        tracemalloc.start()
    
    def snapshot(self) -> None:
        """Сделать снимок текущего состояния."""
        self._snapshot = tracemalloc.take_snapshot()
    
    def stop(self) -> list[tuple[str, int]]:
        """
        Остановить профилирование и вернуть топ потребителей памяти.
        
        Возвращает список кортежей (traceback_string, size_bytes).
        """
        if self._snapshot is None:
            self._snapshot = tracemalloc.take_snapshot()
        
        stats = self._snapshot.statistics('lineno')
        
        result = []
        for stat in stats[:self.top_n]:
            result.append((str(stat.traceback), stat.size))
        
        tracemalloc.stop()
        return result
    
    def get_diff(self, other_snapshot: Any) -> list[tuple[str, int]]:
        """Получить разницу между двумя снимками."""
        if self._snapshot is None:
            return []
        
        diff = self._snapshot.compare_to(other_snapshot, 'lineno')
        
        result = []
        for stat in diff[:self.top_n]:
            if stat.size_diff > 0:
                result.append((str(stat.traceback), stat.size_diff))
        
        return result
