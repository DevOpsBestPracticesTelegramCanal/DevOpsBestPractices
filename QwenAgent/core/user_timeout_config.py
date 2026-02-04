# -*- coding: utf-8 -*-
"""
user_timeout_config.py — Пользовательская конфигурация таймаутов
================================================================

Загружает настройки из .qwencoderules (YAML) и транслирует
пользовательские предпочтения в технические параметры.

Принцип: "Пользователь задаёт границы и цели, агент — тактику"

Файлы конфигурации (в порядке приоритета):
1. {project_dir}/.qwencoderules
2. ~/.qwencoderules
3. Дефолтные значения

Использование:
    from core.user_timeout_config import load_user_config

    config = load_user_config(".")
    timeout_config = config.to_timeout_config()
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

# Попробуем импортировать yaml, если нет — используем fallback
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from .streaming_llm_client import TimeoutConfig


@dataclass
class UserTimeoutPreferences:
    """
    Пользовательские предпочтения по таймаутам.

    Это то, что пользователь понимает и может настроить.
    Технические параметры (ttft, idle, absolute) вычисляются автоматически.
    """
    # === Таймауты ===
    max_wait: float = 120.0          # Макс. время ожидания ответа (секунды)
    on_timeout: str = "degrade"      # Что делать при таймауте: degrade | abort | ask
    risk_tolerance: str = "balanced" # Допустимый риск: conservative | balanced | aggressive

    # === Предпочтения ===
    priority: str = "balanced"       # Приоритет: speed | balanced | quality
    preferred_model: str = ""        # Предпочитаемая модель (если указана)
    fallback_model: str = ""         # Модель для fallback

    # === Режимы ===
    deep_mode_budget: float = 300.0  # Бюджет для DEEP режима (5 мин)
    fast_mode_budget: float = 120.0  # Бюджет для FAST режима (2 мин для CPU)

    def to_timeout_config(self) -> TimeoutConfig:
        """
        Транслирует пользовательские предпочтения в технические параметры.

        Логика:
        - speed → короткие таймауты, быстрый fallback
        - quality → длинные таймауты, больше терпения
        - balanced → средние значения
        """
        if self.priority == "speed":
            return TimeoutConfig(
                ttft_timeout=10,
                idle_timeout=8,
                absolute_max=min(self.max_wait, 60)
            )
        elif self.priority == "quality":
            return TimeoutConfig(
                ttft_timeout=45,
                idle_timeout=30,
                absolute_max=min(self.max_wait, 600)
            )
        else:  # balanced
            return TimeoutConfig(
                ttft_timeout=45,    # CPU может требовать 30+ сек на prefill
                idle_timeout=25,    # Между токенами на CPU
                absolute_max=min(self.max_wait, 300)
            )

    def get_model_config(self) -> Dict[str, str]:
        """Получить конфигурацию моделей."""
        if self.priority == "speed":
            return {
                "primary": self.preferred_model or "qwen2.5-coder:3b",
                "fallback": self.fallback_model or "qwen2.5-coder:3b"
            }
        elif self.priority == "quality":
            return {
                "primary": self.preferred_model or "qwen2.5-coder:7b",
                "fallback": self.fallback_model or "qwen2.5-coder:3b"
            }
        else:  # balanced
            return {
                "primary": self.preferred_model or "qwen2.5-coder:7b",
                "fallback": self.fallback_model or "qwen2.5-coder:3b"
            }

    def get_mode_budget(self, mode: str) -> float:
        """Получить бюджет для режима."""
        mode_lower = mode.lower()
        if "fast" in mode_lower:
            return min(self.fast_mode_budget, self.max_wait)
        elif "deep6" in mode_lower:
            return min(self.deep_mode_budget * 1.5, self.max_wait)
        elif "deep" in mode_lower:
            return min(self.deep_mode_budget, self.max_wait)
        elif "search" in mode_lower:
            return min(self.fast_mode_budget * 2, self.max_wait)
        else:
            return min(self.deep_mode_budget, self.max_wait)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для API/логов."""
        return {
            "max_wait": self.max_wait,
            "on_timeout": self.on_timeout,
            "risk_tolerance": self.risk_tolerance,
            "priority": self.priority,
            "preferred_model": self.preferred_model,
            "fallback_model": self.fallback_model,
            "deep_mode_budget": self.deep_mode_budget,
            "fast_mode_budget": self.fast_mode_budget,
            "computed_timeout_config": {
                "ttft_timeout": self.to_timeout_config().ttft_timeout,
                "idle_timeout": self.to_timeout_config().idle_timeout,
                "absolute_max": self.to_timeout_config().absolute_max
            }
        }


def load_user_config(project_dir: str = ".") -> UserTimeoutPreferences:
    """
    Загружает конфигурацию из .qwencoderules.

    Поиск файла:
    1. {project_dir}/.qwencoderules
    2. ~/.qwencoderules
    3. Дефолтные значения

    Args:
        project_dir: Директория проекта

    Returns:
        UserTimeoutPreferences с настройками
    """
    config_paths = [
        Path(project_dir) / ".qwencoderules",
        Path.home() / ".qwencoderules"
    ]

    for path in config_paths:
        if path.exists():
            try:
                return _load_from_file(path)
            except Exception as e:
                print(f"[CONFIG] Error loading {path}: {e}")
                continue

    # Дефолтные значения
    return UserTimeoutPreferences()


def _load_from_file(path: Path) -> UserTimeoutPreferences:
    """Загрузить конфигурацию из файла."""
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if HAS_YAML:
        data = yaml.safe_load(content)
    else:
        # Простой парсер для базовых случаев
        data = _simple_yaml_parse(content)

    if not data:
        return UserTimeoutPreferences()

    timeouts = data.get("timeouts", {})
    preferences = data.get("preferences", {})
    modes = data.get("modes", {})

    return UserTimeoutPreferences(
        max_wait=float(timeouts.get("max_wait", 120)),
        on_timeout=str(timeouts.get("on_timeout", "degrade")),
        risk_tolerance=str(timeouts.get("risk_tolerance", "balanced")),
        priority=str(preferences.get("priority", "balanced")),
        preferred_model=str(preferences.get("preferred_model", "")),
        fallback_model=str(preferences.get("fallback_model", "")),
        deep_mode_budget=float(modes.get("deep_budget", 180)),
        fast_mode_budget=float(modes.get("fast_budget", 30))
    )


def _simple_yaml_parse(content: str) -> Dict[str, Any]:
    """
    Простой парсер YAML для базовых случаев (без вложенности).
    Используется если PyYAML не установлен.
    """
    result = {}
    current_section = None

    for line in content.split('\n'):
        line = line.rstrip()
        if not line or line.startswith('#'):
            continue

        # Секция (без отступа, с двоеточием)
        if not line.startswith(' ') and line.endswith(':'):
            current_section = line[:-1].strip()
            result[current_section] = {}
            continue

        # Ключ-значение (с отступом)
        if current_section and ':' in line:
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip()

            # Убираем комментарии
            if '#' in value:
                value = value.split('#')[0].strip()

            # Преобразуем типы
            if value.lower() in ('true', 'yes'):
                value = True
            elif value.lower() in ('false', 'no'):
                value = False
            elif value.isdigit():
                value = int(value)
            elif value.replace('.', '').isdigit():
                value = float(value)

            result[current_section][key] = value

    return result


def create_default_config(path: str = ".qwencoderules") -> str:
    """
    Создать файл конфигурации по умолчанию.

    Returns:
        Путь к созданному файлу
    """
    default_content = '''# QwenCode User Configuration
# ============================
# Этот файл определяет пользовательские предпочтения по таймаутам.
# Агент транслирует их в технические параметры автоматически.

timeouts:
  # Максимальное время ожидания ответа (секунды)
  # "Я не готов ждать дольше X секунд"
  max_wait: 120

  # Политика при таймауте:
  # - degrade: попробовать лёгкую модель (рекомендуется)
  # - abort: вернуть ошибку
  # - ask: спросить пользователя
  on_timeout: degrade

  # Допустимый риск (влияет на approval и fallback):
  # - conservative: минимальный риск, больше проверок
  # - balanced: сбалансированный подход (по умолчанию)
  # - aggressive: максимальная скорость, меньше проверок
  risk_tolerance: balanced

preferences:
  # Приоритет: скорость или качество
  # - speed: всегда быстрая модель, короткие таймауты
  # - balanced: агент решает сам (по умолчанию)
  # - quality: тяжёлая модель, длинные таймауты
  priority: balanced

  # Предпочитаемая модель (опционально)
  # preferred_model: qwen2.5-coder:7b

  # Модель для fallback при таймауте
  # fallback_model: qwen2.5-coder:3b

modes:
  # Бюджет времени для DEEP режима (секунды)
  deep_budget: 180

  # Бюджет времени для FAST режима (секунды)
  fast_budget: 30
'''

    with open(path, 'w', encoding='utf-8') as f:
        f.write(default_content)

    return path


# ═══════════════════════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЙ КОНФИГ
# ═══════════════════════════════════════════════════════════════════════════════

_global_config: Optional[UserTimeoutPreferences] = None


def get_config(project_dir: str = ".") -> UserTimeoutPreferences:
    """
    Получить глобальную конфигурацию (с кешированием).

    Использование:
        config = get_config()
        timeout = config.to_timeout_config()
    """
    global _global_config
    if _global_config is None:
        _global_config = load_user_config(project_dir)
    return _global_config


def reload_config(project_dir: str = ".") -> UserTimeoutPreferences:
    """Перезагрузить конфигурацию."""
    global _global_config
    _global_config = load_user_config(project_dir)
    return _global_config


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТ
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("User Timeout Config Test")
    print("=" * 60)

    # Test 1: Default config
    print("\n--- Test 1: Default Config ---")
    config = UserTimeoutPreferences()
    print(f"Config: {config.to_dict()}")

    # Test 2: Speed priority
    print("\n--- Test 2: Speed Priority ---")
    speed_config = UserTimeoutPreferences(priority="speed", max_wait=60)
    timeout = speed_config.to_timeout_config()
    print(f"Priority: speed")
    print(f"Timeout: ttft={timeout.ttft_timeout}s, idle={timeout.idle_timeout}s, max={timeout.absolute_max}s")
    print(f"Models: {speed_config.get_model_config()}")

    # Test 3: Quality priority
    print("\n--- Test 3: Quality Priority ---")
    quality_config = UserTimeoutPreferences(priority="quality", max_wait=300)
    timeout = quality_config.to_timeout_config()
    print(f"Priority: quality")
    print(f"Timeout: ttft={timeout.ttft_timeout}s, idle={timeout.idle_timeout}s, max={timeout.absolute_max}s")
    print(f"Models: {quality_config.get_model_config()}")

    # Test 4: Load from file (if exists)
    print("\n--- Test 4: Load from File ---")
    loaded = load_user_config(".")
    print(f"Loaded config: {loaded.to_dict()}")

    # Test 5: Create default config
    print("\n--- Test 5: Create Default Config ---")
    # path = create_default_config(".qwencoderules.example")
    # print(f"Created: {path}")

    print("\n--- Done ---")
