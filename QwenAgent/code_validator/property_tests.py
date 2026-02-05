"""
Уровень 3: Property-Based тестирование для AI-сгенерированного кода.

Использует Hypothesis для автоматической генерации тестовых случаев.
Позволяет проверять свойства функций без знания конкретных ожидаемых результатов.
"""

import inspect
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, get_type_hints

# Опциональный импорт hypothesis
try:
    from hypothesis import given, settings, Verbosity, Phase
    from hypothesis import strategies as st
    from hypothesis.errors import Unsatisfied, InvalidArgument
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False


class PropertyType(Enum):
    """Типы свойств для проверки."""
    IDEMPOTENT = "idempotent"  # f(f(x)) == f(x)
    COMMUTATIVE = "commutative"  # f(x, y) == f(y, x)
    ASSOCIATIVE = "associative"  # f(f(x, y), z) == f(x, f(y, z))
    IDENTITY = "identity"  # f(x, identity) == x
    INVERSE = "inverse"  # f(f_inv(x)) == x
    INVARIANT = "invariant"  # Некоторое свойство сохраняется
    NO_EXCEPTION = "no_exception"  # Не выбрасывает исключения
    TYPE_PRESERVING = "type_preserving"  # Тип результата соответствует ожидаемому
    DETERMINISTIC = "deterministic"  # f(x) == f(x) при повторных вызовах


@dataclass
class PropertyTestResult:
    """Результат проверки свойства."""
    property_type: PropertyType
    passed: bool
    counterexample: Any = None
    error_message: str = ""
    num_examples_tested: int = 0


@dataclass
class PropertyTestSuiteResult:
    """Результат набора property-тестов."""
    function_name: str
    results: list[PropertyTestResult] = field(default_factory=list)
    
    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)
    
    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)


class PropertyTester:
    """
    Тестировщик свойств для функций.
    
    Автоматически генерирует тестовые данные на основе аннотаций типов
    и проверяет математические/логические свойства функций.
    """
    
    # Маппинг типов Python на стратегии Hypothesis
    TYPE_STRATEGIES = {
        int: lambda: st.integers(min_value=-1000, max_value=1000),
        float: lambda: st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
        str: lambda: st.text(min_size=0, max_size=100),
        bool: lambda: st.booleans(),
        bytes: lambda: st.binary(min_size=0, max_size=100),
        list: lambda: st.lists(st.integers(), max_size=50),
        dict: lambda: st.dictionaries(st.text(max_size=10), st.integers(), max_size=20),
        set: lambda: st.frozensets(st.integers(), max_size=50),
        tuple: lambda: st.tuples(st.integers(), st.integers()),
    }
    
    def __init__(
        self,
        max_examples: int = 100,
        timeout_per_test: int = 30,
        verbosity: str = "quiet",
    ):
        if not HYPOTHESIS_AVAILABLE:
            raise ImportError(
                "Hypothesis не установлен. Установите: pip install hypothesis"
            )
        
        self.max_examples = max_examples
        self.timeout_per_test = timeout_per_test
        self.verbosity = getattr(Verbosity, verbosity, Verbosity.quiet)
    
    def get_strategy_for_type(self, type_hint: type) -> Any:
        """Получить стратегию Hypothesis для типа."""
        # Обработка Optional
        origin = typing.get_origin(type_hint)
        args = typing.get_args(type_hint)
        
        if origin is typing.Union:
            # Optional[X] == Union[X, None]
            non_none_args = [a for a in args if a is not type(None)]
            if len(non_none_args) == 1:
                base_strategy = self.get_strategy_for_type(non_none_args[0])
                return st.one_of(base_strategy, st.none())
            else:
                return st.one_of(*[self.get_strategy_for_type(a) for a in non_none_args])
        
        if origin is list:
            if args:
                return st.lists(self.get_strategy_for_type(args[0]), max_size=50)
            return st.lists(st.integers(), max_size=50)
        
        if origin is dict:
            if len(args) >= 2:
                return st.dictionaries(
                    self.get_strategy_for_type(args[0]),
                    self.get_strategy_for_type(args[1]),
                    max_size=20
                )
            return st.dictionaries(st.text(max_size=10), st.integers(), max_size=20)
        
        if origin is tuple:
            if args:
                return st.tuples(*[self.get_strategy_for_type(a) for a in args])
            return st.tuples(st.integers(), st.integers())
        
        if origin is set or origin is frozenset:
            if args:
                return st.frozensets(self.get_strategy_for_type(args[0]), max_size=50)
            return st.frozensets(st.integers(), max_size=50)
        
        # Базовые типы
        if type_hint in self.TYPE_STRATEGIES:
            return self.TYPE_STRATEGIES[type_hint]()
        
        # По умолчанию — integers
        return st.integers(min_value=-100, max_value=100)
    
    def infer_strategies(self, func: Callable) -> dict[str, Any]:
        """Вывести стратегии из аннотаций типов функции."""
        try:
            hints = get_type_hints(func)
        except Exception:
            hints = {}
        
        sig = inspect.signature(func)
        strategies = {}
        
        for param_name, param in sig.parameters.items():
            if param_name in ('self', 'cls'):
                continue
            
            if param_name in hints:
                strategies[param_name] = self.get_strategy_for_type(hints[param_name])
            elif param.annotation != inspect.Parameter.empty:
                strategies[param_name] = self.get_strategy_for_type(param.annotation)
            else:
                # По умолчанию — целые числа
                strategies[param_name] = st.integers(min_value=-100, max_value=100)
        
        return strategies
    
    def test_no_exception(self, func: Callable) -> PropertyTestResult:
        """Проверить, что функция не выбрасывает исключения."""
        strategies = self.infer_strategies(func)
        counterexample = None
        error_msg = ""
        num_tested = 0
        passed = True
        
        if not strategies:
            # Функция без аргументов
            try:
                func()
                num_tested = 1
            except Exception as e:
                passed = False
                error_msg = f"{type(e).__name__}: {str(e)}"
            
            return PropertyTestResult(
                property_type=PropertyType.NO_EXCEPTION,
                passed=passed,
                error_message=error_msg,
                num_examples_tested=num_tested,
            )
        
        @settings(
            max_examples=self.max_examples,
            deadline=self.timeout_per_test * 1000,
            verbosity=self.verbosity,
            phases=[Phase.generate, Phase.target],
        )
        @given(**strategies)
        def test_func(**kwargs):
            nonlocal num_tested
            num_tested += 1
            func(**kwargs)
        
        try:
            test_func()
        except AssertionError:
            # Hypothesis нашёл контрпример
            passed = False
        except Exception as e:
            passed = False
            error_msg = f"{type(e).__name__}: {str(e)}"
        
        return PropertyTestResult(
            property_type=PropertyType.NO_EXCEPTION,
            passed=passed,
            counterexample=counterexample,
            error_message=error_msg,
            num_examples_tested=num_tested,
        )
    
    def test_deterministic(self, func: Callable) -> PropertyTestResult:
        """Проверить детерминированность: f(x) == f(x)."""
        strategies = self.infer_strategies(func)
        counterexample = None
        error_msg = ""
        num_tested = 0
        passed = True
        
        if not strategies:
            return PropertyTestResult(
                property_type=PropertyType.DETERMINISTIC,
                passed=True,
                num_examples_tested=0,
            )
        
        @settings(
            max_examples=self.max_examples,
            deadline=self.timeout_per_test * 1000,
            verbosity=self.verbosity,
        )
        @given(**strategies)
        def test_func(**kwargs):
            nonlocal num_tested, counterexample, passed
            num_tested += 1
            result1 = func(**kwargs)
            result2 = func(**kwargs)
            if result1 != result2:
                counterexample = kwargs
                passed = False
                raise AssertionError(f"Недетерминированность: {result1} != {result2}")
        
        try:
            test_func()
        except AssertionError as e:
            passed = False
            error_msg = str(e)
        except Exception as e:
            passed = False
            error_msg = f"{type(e).__name__}: {str(e)}"
        
        return PropertyTestResult(
            property_type=PropertyType.DETERMINISTIC,
            passed=passed,
            counterexample=counterexample,
            error_message=error_msg,
            num_examples_tested=num_tested,
        )
    
    def test_idempotent(self, func: Callable) -> PropertyTestResult:
        """Проверить идемпотентность: f(f(x)) == f(x)."""
        strategies = self.infer_strategies(func)
        
        # Нужен ровно 1 аргумент
        if len(strategies) != 1:
            return PropertyTestResult(
                property_type=PropertyType.IDEMPOTENT,
                passed=True,
                error_message="Тест применим только к функциям с одним аргументом",
                num_examples_tested=0,
            )
        
        param_name = list(strategies.keys())[0]
        strategy = strategies[param_name]
        
        counterexample = None
        error_msg = ""
        num_tested = 0
        passed = True
        
        @settings(
            max_examples=self.max_examples,
            deadline=self.timeout_per_test * 1000,
            verbosity=self.verbosity,
        )
        @given(x=strategy)
        def test_func(x):
            nonlocal num_tested, counterexample, passed
            num_tested += 1
            try:
                fx = func(x)
                ffx = func(fx)
                if fx != ffx:
                    counterexample = x
                    passed = False
                    raise AssertionError(f"f(f({x})) = {ffx} != f({x}) = {fx}")
            except TypeError:
                # Результат f(x) несовместим с входом — пропускаем
                pass
        
        try:
            test_func()
        except AssertionError as e:
            passed = False
            error_msg = str(e)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
        
        return PropertyTestResult(
            property_type=PropertyType.IDEMPOTENT,
            passed=passed,
            counterexample=counterexample,
            error_message=error_msg,
            num_examples_tested=num_tested,
        )
    
    def test_custom_property(
        self,
        func: Callable,
        property_check: Callable[[Any, Any], bool],
        property_name: str = "custom",
    ) -> PropertyTestResult:
        """
        Проверить пользовательское свойство.
        
        property_check получает (input, output) и возвращает True если свойство выполняется.
        """
        strategies = self.infer_strategies(func)
        counterexample = None
        error_msg = ""
        num_tested = 0
        passed = True
        
        if not strategies:
            return PropertyTestResult(
                property_type=PropertyType.INVARIANT,
                passed=True,
                num_examples_tested=0,
            )
        
        @settings(
            max_examples=self.max_examples,
            deadline=self.timeout_per_test * 1000,
            verbosity=self.verbosity,
        )
        @given(**strategies)
        def test_func(**kwargs):
            nonlocal num_tested, counterexample, passed
            num_tested += 1
            result = func(**kwargs)
            if not property_check(kwargs, result):
                counterexample = kwargs
                passed = False
                raise AssertionError(f"Свойство '{property_name}' нарушено для {kwargs}")
        
        try:
            test_func()
        except AssertionError as e:
            passed = False
            error_msg = str(e)
        except Exception as e:
            passed = False
            error_msg = f"{type(e).__name__}: {str(e)}"
        
        return PropertyTestResult(
            property_type=PropertyType.INVARIANT,
            passed=passed,
            counterexample=counterexample,
            error_message=error_msg,
            num_examples_tested=num_tested,
        )
    
    def run_all_tests(self, func: Callable) -> PropertyTestSuiteResult:
        """Запустить все применимые тесты для функции."""
        results = []
        
        # Базовые тесты
        results.append(self.test_no_exception(func))
        results.append(self.test_deterministic(func))
        results.append(self.test_idempotent(func))
        
        return PropertyTestSuiteResult(
            function_name=func.__name__,
            results=results,
        )


# Готовые проверки свойств для распространённых случаев
class CommonPropertyChecks:
    """Набор готовых проверок свойств."""
    
    @staticmethod
    def output_not_none(inputs: dict, output: Any) -> bool:
        """Результат не None."""
        return output is not None
    
    @staticmethod
    def output_same_type_as_first_arg(inputs: dict, output: Any) -> bool:
        """Тип результата совпадает с типом первого аргумента."""
        if not inputs:
            return True
        first_val = next(iter(inputs.values()))
        return type(output) == type(first_val)
    
    @staticmethod
    def list_length_preserved(inputs: dict, output: Any) -> bool:
        """Длина списка сохраняется (для функций обработки списков)."""
        for val in inputs.values():
            if isinstance(val, list) and isinstance(output, list):
                return len(val) == len(output)
        return True
    
    @staticmethod
    def list_elements_preserved(inputs: dict, output: Any) -> bool:
        """Элементы списка сохраняются (например, для сортировки)."""
        for val in inputs.values():
            if isinstance(val, list) and isinstance(output, list):
                return sorted(val) == sorted(output)
        return True
    
    @staticmethod
    def string_not_longer(inputs: dict, output: Any) -> bool:
        """Строка не стала длиннее (для функций обрезки/фильтрации)."""
        for val in inputs.values():
            if isinstance(val, str) and isinstance(output, str):
                return len(output) <= len(val)
        return True
    
    @staticmethod  
    def numeric_in_range(min_val: float, max_val: float):
        """Фабрика: числовой результат в диапазоне."""
        def check(inputs: dict, output: Any) -> bool:
            if isinstance(output, (int, float)):
                return min_val <= output <= max_val
            return True
        return check


def test_function_properties(func: Callable, **kwargs) -> PropertyTestSuiteResult:
    """Функция-обёртка для быстрого тестирования свойств."""
    if not HYPOTHESIS_AVAILABLE:
        raise ImportError("Hypothesis не установлен")
    
    tester = PropertyTester(**kwargs)
    return tester.run_all_tests(func)
