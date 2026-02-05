#!/usr/bin/env python3
"""
Примеры использования Code Validator.

Запуск:
    python example_usage.py
"""

from code_validator import (
    # Быстрые функции
    validate_code,
    is_safe,
    prevalidate,
    analyze_static,
    execute_safe,
    
    # Классы для детальной настройки
    CodeValidator,
    ValidatorConfig,
    Prevalidator,
    SandboxType,
    
    # Результаты
    ValidationStatus,
    Severity,
)


def example_1_quick_validation():
    """Пример 1: Быстрая валидация кода."""
    print("\n" + "="*60)
    print("ПРИМЕР 1: Быстрая валидация")
    print("="*60)
    
    code = '''
def factorial(n: int) -> int:
    """Вычисление факториала."""
    if n <= 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
print(f"5! = {result}")
'''
    
    report = validate_code(code)
    print(report.summary())
    
    # Проверка статуса
    if report.status == ValidationStatus.PASSED:
        print("\n✓ Код прошёл все проверки!")
    elif report.status == ValidationStatus.WARNINGS:
        print("\n⚠ Код прошёл с предупреждениями")
    else:
        print("\n✗ Код не прошёл проверку")


def example_2_dangerous_code():
    """Пример 2: Обнаружение опасного кода."""
    print("\n" + "="*60)
    print("ПРИМЕР 2: Обнаружение опасного кода")
    print("="*60)
    
    dangerous_code = '''
import os
import subprocess

# Опасный код!
os.system("rm -rf /")
subprocess.run(["cat", "/etc/passwd"])
eval(input("Введите код: "))
'''
    
    # Быстрая проверка безопасности
    if is_safe(dangerous_code):
        print("Код безопасен")
    else:
        print("⚠ Код содержит опасные конструкции!")
    
    # Детальный отчёт
    result = prevalidate(dangerous_code)
    print(f"\nНайдено проблем: {len(result.issues)}")
    
    for issue in result.issues[:5]:
        print(f"  {issue}")


def example_3_static_analysis():
    """Пример 3: Статический анализ."""
    print("\n" + "="*60)
    print("ПРИМЕР 3: Статический анализ")
    print("="*60)
    
    code_with_issues = '''
def process_data(data):
    # Неиспользуемая переменная
    unused = 42
    
    # Потенциальная ошибка
    if data == None:
        return []
    
    # Плохой стиль
    result=[]
    for i in range(len(data)):
        result.append(data[i]*2)
    
    return result
'''
    
    result = analyze_static(code_with_issues)
    
    print(f"Успех: {result.success}")
    print(f"Ошибок: {result.error_count}")
    print(f"Предупреждений: {result.warning_count}")
    print(f"Инструменты: {[t.value for t in result.tools_run]}")
    
    if result.issues:
        print("\nПроблемы:")
        for issue in result.issues[:5]:
            print(f"  {issue}")


def example_4_sandbox_execution():
    """Пример 4: Безопасное выполнение в sandbox."""
    print("\n" + "="*60)
    print("ПРИМЕР 4: Sandbox-выполнение")
    print("="*60)
    
    # Безопасный код
    safe_code = '''
import math

def calculate_circle_area(radius):
    return math.pi * radius ** 2

areas = [calculate_circle_area(r) for r in range(1, 6)]
print("Площади кругов:", areas)
'''
    
    result = execute_safe(safe_code, sandbox_type=SandboxType.SUBPROCESS)
    
    print(f"Статус: {result.status.value}")
    print(f"Время: {result.execution_time:.3f}s")
    
    if result.stdout:
        print(f"Вывод: {result.stdout}")
    
    if result.error_message:
        print(f"Ошибка: {result.error_message}")


def example_5_custom_config():
    """Пример 5: Кастомная конфигурация валидатора."""
    print("\n" + "="*60)
    print("ПРИМЕР 5: Кастомная конфигурация")
    print("="*60)
    
    # Строгая конфигурация для продакшена
    strict_config = ValidatorConfig(
        stop_on_failure=True,
        max_code_length=10_000,
        max_lines=200,
        sandbox_timeout=5.0,
        sandbox_max_memory_mb=64,
        enable_property_tests=False,  # Отключаем для скорости
    )
    
    validator = CodeValidator(strict_config)
    
    code = '''
def greet(name: str) -> str:
    return f"Hello, {name}!"

print(greet("World"))
'''
    
    report = validator.validate(code)
    print(report.summary())


def example_6_forbidden_patterns():
    """Пример 6: Кастомные запрещённые паттерны."""
    print("\n" + "="*60)
    print("ПРИМЕР 6: Кастомные запрещённые паттерны")
    print("="*60)
    
    # Запрещаем даже безопасные модули для специфичного use case
    custom_forbidden = frozenset({
        "os", "sys", "subprocess",  # Стандартные
        "requests", "urllib",       # Сеть
        "json", "pickle",           # Сериализация
        "datetime",                  # Даже datetime!
    })
    
    validator = Prevalidator(forbidden_imports=custom_forbidden)
    
    code_with_datetime = '''
from datetime import datetime

now = datetime.now()
print(f"Текущее время: {now}")
'''
    
    result = validator.validate(code_with_datetime)
    
    if not result.is_valid:
        print("Код отклонён!")
        for issue in result.issues:
            print(f"  {issue}")
    else:
        print("Код принят")


def example_7_batch_validation():
    """Пример 7: Пакетная валидация."""
    print("\n" + "="*60)
    print("ПРИМЕР 7: Пакетная валидация")
    print("="*60)
    
    code_samples = [
        ("Безопасный", "print('Hello')"),
        ("С импортом", "import math\nprint(math.pi)"),
        ("Опасный", "import os\nos.system('ls')"),
        ("Синтаксическая ошибка", "def broken("),
        ("Бесконечный цикл", "while True: pass"),
    ]
    
    results = []
    for name, code in code_samples:
        is_code_safe = is_safe(code)
        results.append((name, is_code_safe))
    
    print("\nРезультаты:")
    for name, safe in results:
        status = "✓ безопасен" if safe else "✗ отклонён"
        print(f"  {name}: {status}")


def example_8_property_testing():
    """Пример 8: Property-based тестирование."""
    print("\n" + "="*60)
    print("ПРИМЕР 8: Property-тесты (требуется hypothesis)")
    print("="*60)
    
    try:
        from code_validator import test_function_properties, HYPOTHESIS_AVAILABLE
        
        if not HYPOTHESIS_AVAILABLE:
            print("⚠ Hypothesis не установлен. Установите: pip install hypothesis")
            return
        
        # Функция для тестирования
        def reverse_list(items: list) -> list:
            return items[::-1]
        
        result = test_function_properties(reverse_list, max_examples=50)
        
        print(f"Функция: {result.function_name}")
        print(f"Пройдено: {result.passed_count}/{len(result.results)}")
        
        for test_result in result.results:
            status = "✓" if test_result.passed else "✗"
            print(f"  {status} {test_result.property_type.value}: {test_result.num_examples_tested} примеров")
            
    except ImportError as e:
        print(f"⚠ Не удалось импортировать: {e}")


def main():
    """Запуск всех примеров."""
    print("\n" + "="*60)
    print("  CODE VALIDATOR — Примеры использования")
    print("="*60)
    
    example_1_quick_validation()
    example_2_dangerous_code()
    example_3_static_analysis()
    example_4_sandbox_execution()
    example_5_custom_config()
    example_6_forbidden_patterns()
    example_7_batch_validation()
    example_8_property_testing()
    
    print("\n" + "="*60)
    print("  Все примеры выполнены!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
