"""
Week 22: Tests for Quality Validators

Tests for all 7 new Rule validators + Engineer10x prompt generator.
Each validator has positive (passes) and negative (caught) test cases.
"""

import ast
import pytest

# ---------------------------------------------------------------------------
# Import all new validators
# ---------------------------------------------------------------------------

from code_validator.rules.search_guard import SearchGuardRule
from code_validator.rules.promise_checker import PromiseCheckerRule
from code_validator.rules.antipattern_rules import AntiPatternRule
from code_validator.rules.extended_domain_rules import ExtendedDomainRule
from code_validator.rules.production_readiness import ProductionReadyRule
from code_validator.rules.async_safety import AsyncSafetyRule
from code_validator.rules.exception_rules import ExceptionHierarchyRule
from code_validator.rules.base import RuleRunner, RuleSeverity

# Import registry to verify registration
from code_validator.rules.python_validators import _RULE_REGISTRY, build_rules_for_names

# Import Engineer10x
from core.generation.engineer_10x import (
    build_10x_prompt,
    get_10x_role,
    should_use_10x,
    DEADLY_SINS,
    ENGINEER_10X_ROLE,
)
from core.generation.generator_roles import GeneratorRole


# =========================================================================
# 1. SearchGuardRule Tests
# =========================================================================

class TestSearchGuardRule:
    """Tests for search-only / tutorial-dump detection."""

    def setup_method(self):
        self.rule = SearchGuardRule()

    def test_valid_code_passes(self):
        code = '''
def fibonacci(n: int) -> int:
    """Return the n-th Fibonacci number."""
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
'''
        result = self.rule.check(code)
        assert result.passed
        assert result.score >= 0.8

    def test_url_dump_fails(self):
        code = '''
# See https://docs.python.org/3/library/functions.html
# Check out https://realpython.com/python-functions/
# Visit https://stackoverflow.com/questions/12345
# Refer to https://docs.djangoproject.com/
# More info at https://example.com/docs
# For details see https://github.com/example
'''
        result = self.rule.check(code)
        assert not result.passed
        assert result.score < 0.5
        assert any("URL" in m for m in result.messages)

    def test_link_dump_language(self):
        code = '''
# See the official documentation at https://example.com
# Check out the tutorial at https://example.com/tutorial
# Refer to the guide at https://example.com/guide
'''
        result = self.rule.check(code)
        assert any("Link-dump" in m or "URL" in m for m in result.messages)

    def test_install_only_fails(self):
        code = '''
# pip install flask
# pip install sqlalchemy
# pip install pytest
# Then run: flask run
'''
        result = self.rule.check(code)
        assert any("install" in m.lower() or "Install" in m for m in result.messages)

    def test_placeholder_heavy_fails(self):
        code = '''
def process_data(data):
    # TODO: implement data processing
    pass

def validate_input(value):
    # TODO: add validation
    pass

def transform(items):
    # your code here
    ...
'''
        result = self.rule.check(code)
        assert any("Placeholder" in m or "stub" in m.lower() for m in result.messages)

    def test_empty_code_fails(self):
        result = self.rule.check("")
        assert not result.passed

    def test_name_and_severity(self):
        assert self.rule.name == "search_guard"
        assert self.rule.severity == RuleSeverity.WARNING
        assert self.rule.weight == 2.0


# =========================================================================
# 2. PromiseCheckerRule Tests
# =========================================================================

class TestPromiseCheckerRule:
    """Tests for docstring vs implementation matching."""

    def setup_method(self):
        self.rule = PromiseCheckerRule()

    def test_matching_promises_pass(self):
        code = '''
def add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b
'''
        result = self.rule.check(code)
        assert result.passed

    def test_missing_return_fails(self):
        code = '''
def compute(data: list) -> dict:
    """Compute statistics from data.

    Returns:
        Dictionary with mean, median, and mode.
    """
    total = sum(data)
    mean = total / len(data)
    print(f"Mean: {mean}")
'''
        result = self.rule.check(code)
        assert any("return" in m.lower() for m in result.messages)

    def test_missing_raise_detected(self):
        code = '''
def validate(value: str) -> bool:
    """Validate the input string.

    Raises:
        ValueError: If value is empty.

    Returns:
        True if valid.
    """
    return len(value) > 0
'''
        result = self.rule.check(code)
        assert any("ValueError" in m for m in result.messages)

    def test_phantom_args_detected(self):
        code = '''
def greet(name: str) -> str:
    """Create a greeting.

    Args:
        name: Person's name.
        title: Optional title (Mr/Ms).
        suffix: Optional suffix.
    """
    return f"Hello, {name}!"
'''
        result = self.rule.check(code)
        assert any("don't exist" in m or "phantom" in m.lower() for m in result.messages)

    def test_stub_with_docstring_detected(self):
        code = '''
def complex_operation(data: list, config: dict) -> dict:
    """Perform a complex multi-step data transformation.

    This function applies multiple transformation stages
    including normalization, filtering, and aggregation.

    Args:
        data: Input data list.
        config: Configuration dictionary.

    Returns:
        Transformed data dictionary.
    """
    pass
'''
        result = self.rule.check(code)
        assert any("stub" in m.lower() for m in result.messages)

    def test_no_docstrings_passes(self):
        code = '''
def simple(x):
    return x * 2
'''
        result = self.rule.check(code)
        assert result.passed

    def test_syntax_error_skipped(self):
        result = self.rule.check("def broken(:\n    return")
        assert result.passed
        assert any("syntax" in m.lower() for m in result.messages)

    def test_name_and_severity(self):
        assert self.rule.name == "promise_checker"
        assert self.rule.severity == RuleSeverity.WARNING


# =========================================================================
# 3. AntiPatternRule Tests
# =========================================================================

class TestAntiPatternRule:
    """Tests for anti-pattern detection."""

    def setup_method(self):
        self.rule = AntiPatternRule()

    def test_clean_code_passes(self):
        code = '''
import logging

logger = logging.getLogger(__name__)

def get_user(user_id: int) -> dict:
    """Get user by ID using parameterized query."""
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    return cursor.fetchone()
'''
        result = self.rule.check(code)
        assert result.passed
        assert result.score >= 0.7

    def test_sql_injection_detected(self):
        code = '''
def get_user(user_id):
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
    return cursor.fetchone()
'''
        result = self.rule.check(code)
        assert any("sql_injection" in m.lower() or "SQL" in m for m in result.messages)

    def test_hardcoded_secret_detected(self):
        code = '''
API_KEY = "sk-1234567890abcdef1234567890abcdef"
password = "super_secret_password_123"
'''
        result = self.rule.check(code)
        assert any("secret" in m.lower() or "hardcoded" in m.lower() for m in result.messages)

    def test_unsafe_yaml_detected(self):
        code = '''
import yaml

data = yaml.load(open("config.yaml"))
'''
        result = self.rule.check(code)
        assert any("yaml" in m.lower() for m in result.messages)

    def test_unsafe_pickle_detected(self):
        code = '''
import pickle

data = pickle.loads(user_input)
'''
        result = self.rule.check(code)
        assert any("pickle" in m.lower() for m in result.messages)

    def test_debug_mode_detected(self):
        code = '''
app.run(debug=True, host="0.0.0.0")
'''
        result = self.rule.check(code)
        assert any("debug" in m.lower() for m in result.messages)

    def test_bare_except_detected(self):
        code = '''
try:
    risky_operation()
except:
    pass
'''
        result = self.rule.check(code)
        assert any("bare_except" in m for m in result.messages)

    def test_mutable_default_detected(self):
        code = '''
def process(items=[]):
    items.append("new")
    return items
'''
        result = self.rule.check(code)
        assert any("mutable_default" in m for m in result.messages)

    def test_global_mutation_detected(self):
        code = '''
counter = 0

def increment():
    global counter
    counter += 1
'''
        result = self.rule.check(code)
        assert any("global" in m.lower() for m in result.messages)

    def test_empty_code_passes(self):
        result = self.rule.check("")
        assert result.passed

    def test_name_and_severity(self):
        assert self.rule.name == "antipattern"
        assert self.rule.severity == RuleSeverity.ERROR
        assert self.rule.weight == 3.0


# =========================================================================
# 4. ExtendedDomainRule Tests
# =========================================================================

class TestExtendedDomainRule:
    """Tests for domain-specific validation."""

    def setup_method(self):
        self.rule = ExtendedDomainRule()

    def test_good_fastapi_passes(self):
        code = '''
from fastapi import FastAPI, Depends
from pydantic import BaseModel

app = FastAPI()

class UserResponse(BaseModel):
    id: int
    name: str

@app.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db=Depends(get_db)):
    return db.query(User).get(user_id)
'''
        result = self.rule.check(code)
        assert result.passed

    def test_fastapi_missing_response_model(self):
        code = '''
from fastapi import FastAPI

app = FastAPI()

@app.get("/users")
def list_users():
    return []

@app.post("/users")
def create_user():
    return {"id": 1}
'''
        result = self.rule.check(code)
        assert any("response_model" in m for m in result.messages)

    def test_dockerfile_no_multistage(self):
        code = '''
FROM python:3.12
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "main.py"]
'''
        result = self.rule.check(code)
        assert any("multi-stage" in m.lower() or "multistage" in m.lower() for m in result.messages)

    def test_dockerfile_latest_tag(self):
        code = '''
FROM python:latest
WORKDIR /app
CMD ["python", "main.py"]
'''
        result = self.rule.check(code)
        assert any(":latest" in m for m in result.messages)

    def test_dockerfile_good_practices_pass(self):
        code = '''
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
COPY --from=builder /app /app
USER nonroot
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1
CMD ["python", "main.py"]
'''
        result = self.rule.check(code)
        assert result.passed

    def test_database_fstring_sql(self):
        code = '''
from sqlalchemy import create_engine

engine = create_engine("postgresql://localhost/mydb")

def get_user(user_id):
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
'''
        result = self.rule.check(code)
        assert any("sql" in m.lower() or "f-string" in m.lower() for m in result.messages)

    def test_generic_code_passes(self):
        code = '''
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
'''
        result = self.rule.check(code)
        assert result.passed

    def test_name_and_severity(self):
        assert self.rule.name == "extended_domain"
        assert self.rule.severity == RuleSeverity.WARNING


# =========================================================================
# 5. ProductionReadyRule Tests
# =========================================================================

class TestProductionReadyRule:
    """Tests for production readiness checks."""

    def setup_method(self):
        self.rule = ProductionReadyRule()

    def test_production_ready_service_passes(self):
        code = '''
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/users")
def list_users():
    return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
        result = self.rule.check(code)
        assert result.passed

    def test_no_health_endpoint(self):
        code = '''
from flask import Flask

app = Flask(__name__)

@app.route("/users")
def list_users():
    return []

if __name__ == "__main__":
    app.run(host="0.0.0.0")
'''
        result = self.rule.check(code)
        assert any("health" in m.lower() for m in result.messages)

    def test_print_instead_of_logging(self):
        code = '''
from flask import Flask

app = Flask(__name__)

@app.route("/data")
def get_data():
    print("Getting data...")
    return {"data": []}

if __name__ == "__main__":
    app.run()
'''
        result = self.rule.check(code)
        assert any("print" in m.lower() or "logging" in m.lower() for m in result.messages)

    def test_debug_mode_detected(self):
        code = '''
from flask import Flask
app = Flask(__name__)

if __name__ == "__main__":
    app.run(debug=True)
'''
        result = self.rule.check(code)
        assert any("debug" in m.lower() for m in result.messages)

    def test_library_code_skipped(self):
        """Library code (no __main__, no web framework) should pass."""
        code = '''
def helper(x: int) -> int:
    return x * 2

class MyClass:
    pass
'''
        result = self.rule.check(code)
        assert result.passed
        assert result.score == 1.0

    def test_name_and_severity(self):
        assert self.rule.name == "production_ready"
        assert self.rule.severity == RuleSeverity.WARNING


# =========================================================================
# 6. AsyncSafetyRule Tests
# =========================================================================

class TestAsyncSafetyRule:
    """Tests for async anti-pattern detection."""

    def setup_method(self):
        self.rule = AsyncSafetyRule()

    def test_clean_async_passes(self):
        code = '''
import asyncio
import aiohttp

async def fetch_data(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()
'''
        result = self.rule.check(code)
        assert result.passed

    def test_blocking_sleep_detected(self):
        code = '''
import asyncio
import time

async def slow_handler():
    time.sleep(5)  # BLOCKING!
    return {"status": "done"}
'''
        result = self.rule.check(code)
        assert any("blocking" in m.lower() or "time.sleep" in m for m in result.messages)

    def test_blocking_requests_detected(self):
        code = '''
import asyncio
import requests

async def fetch(url: str):
    response = requests.get(url)  # BLOCKING!
    return response.json()
'''
        result = self.rule.check(code)
        assert any("blocking" in m.lower() or "requests.get" in m for m in result.messages)

    def test_sync_open_in_async(self):
        code = '''
import asyncio

async def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()
'''
        result = self.rule.check(code)
        assert any("sync" in m.lower() or "open" in m.lower() for m in result.messages)

    def test_sync_lock_in_async(self):
        code = '''
import asyncio
import threading

lock = threading.Lock()

async def critical_section():
    with lock:
        pass
'''
        result = self.rule.check(code)
        assert any("lock" in m.lower() for m in result.messages)

    def test_nested_asyncio_run(self):
        code = '''
import asyncio

async def handler():
    result = asyncio.run(other_coro())
    return result
'''
        result = self.rule.check(code)
        assert any("nested" in m.lower() or "asyncio.run" in m for m in result.messages)

    def test_sync_code_skipped(self):
        """Non-async code should pass without checks."""
        code = '''
import time

def slow_function():
    time.sleep(5)
    return True
'''
        result = self.rule.check(code)
        assert result.passed
        assert result.score == 1.0

    def test_name_and_severity(self):
        assert self.rule.name == "async_safety"
        assert self.rule.severity == RuleSeverity.WARNING
        assert self.rule.weight == 2.0


# =========================================================================
# 7. ExceptionHierarchyRule Tests
# =========================================================================

class TestExceptionHierarchyRule:
    """Tests for exception handling patterns."""

    def setup_method(self):
        self.rule = ExceptionHierarchyRule()

    def test_good_exceptions_pass(self):
        code = '''
class NotFoundError(ValueError):
    """Resource not found."""
    pass

class AuthenticationError(RuntimeError):
    """Authentication failed."""
    pass

def get_item(item_id: int):
    try:
        return lookup(item_id)
    except KeyError as err:
        raise NotFoundError(f"Item {item_id} not found") from err
'''
        result = self.rule.check(code)
        assert result.passed

    def test_bare_exception_base(self):
        code = '''
class MyError(Exception):
    pass
'''
        result = self.rule.check(code)
        assert any("broad_base" in m or "bare Exception" in m for m in result.messages)

    def test_base_exception_inherit(self):
        code = '''
class CriticalError(BaseException):
    pass
'''
        result = self.rule.check(code)
        assert any("BaseException" in m for m in result.messages)

    def test_swallowed_exception(self):
        code = '''
def risky():
    try:
        do_something()
    except ValueError:
        pass
'''
        result = self.rule.check(code)
        assert any("swallowed" in m.lower() for m in result.messages)

    def test_no_exception_chaining(self):
        code = '''
def convert(value):
    try:
        return int(value)
    except ValueError:
        raise TypeError("Cannot convert")
'''
        result = self.rule.check(code)
        assert any("chain" in m.lower() or "from" in m.lower() for m in result.messages)

    def test_proper_chaining_passes(self):
        code = '''
def convert(value):
    try:
        return int(value)
    except ValueError as err:
        raise TypeError("Cannot convert") from err
'''
        result = self.rule.check(code)
        # Should not flag chaining issue
        assert not any("no_chain" in m for m in result.messages)

    def test_broad_catch_without_logging(self):
        code = '''
def process():
    try:
        do_something()
    except Exception:
        return None
'''
        result = self.rule.check(code)
        assert any("broad_catch" in m or "broad" in m.lower() for m in result.messages)

    def test_broad_catch_with_logging_ok(self):
        code = '''
import logging
logger = logging.getLogger(__name__)

def process():
    try:
        do_something()
    except Exception:
        logger.error("Failed")
        return None
'''
        result = self.rule.check(code)
        # Should not flag broad_catch since it logs
        assert not any("broad_catch" in m for m in result.messages)

    def test_no_exceptions_passes(self):
        code = '''
def simple(x):
    return x * 2
'''
        result = self.rule.check(code)
        assert result.passed
        assert result.score == 1.0

    def test_name_and_severity(self):
        assert self.rule.name == "exception_hierarchy"
        assert self.rule.severity == RuleSeverity.WARNING


# =========================================================================
# 8. Engineer10x Tests
# =========================================================================

class TestEngineer10x:
    """Tests for the Engineer 10x prompt generator."""

    def test_role_definition(self):
        role = get_10x_role()
        assert role.name == "engineer_10x"
        assert role.temperature == 0.25
        assert len(role.priority_validators) > 0
        assert "ast_syntax" in role.priority_validators

    def test_build_prompt_basic(self):
        prompt = build_10x_prompt("Generate a function.")
        assert "10x engineer" in prompt
        assert "Generate a function." in prompt

    def test_build_prompt_with_sins(self):
        prompt = build_10x_prompt("Task.", include_sins=True)
        assert "CRITICAL RULES" in prompt
        assert "NEVER" in prompt

    def test_build_prompt_without_sins(self):
        prompt = build_10x_prompt("Task.", include_sins=False)
        assert "CRITICAL RULES" not in prompt

    def test_build_prompt_with_checklist(self):
        prompt = build_10x_prompt("Task.", task_type="python", include_checklist=True)
        assert "Quality checklist" in prompt
        assert "Type hints" in prompt

    def test_build_prompt_kubernetes_checklist(self):
        prompt = build_10x_prompt("Task.", task_type="kubernetes", include_checklist=True)
        assert "kubernetes" in prompt.lower()
        assert "probes" in prompt.lower() or "liveness" in prompt.lower()

    def test_build_prompt_unknown_domain(self):
        prompt = build_10x_prompt("Task.", task_type="unknown_domain")
        # No checklist for unknown domain, but prompt still works
        assert "10x engineer" in prompt

    def test_should_use_10x_critical(self):
        assert should_use_10x(complexity="CRITICAL")
        assert should_use_10x(complexity="COMPLEX")

    def test_should_use_10x_infra(self):
        assert should_use_10x(task_type="infrastructure")
        assert should_use_10x(task_type="infra")

    def test_should_use_10x_high_risk(self):
        assert should_use_10x(risk_level="high")
        assert should_use_10x(risk_level="critical")

    def test_should_not_use_10x_simple(self):
        assert not should_use_10x(complexity="SIMPLE")
        assert not should_use_10x(complexity="TRIVIAL")
        assert not should_use_10x(complexity="MODERATE")

    def test_deadly_sins_count(self):
        assert len(DEADLY_SINS) == 7

    def test_role_is_generator_role(self):
        assert isinstance(ENGINEER_10X_ROLE, GeneratorRole)


# =========================================================================
# 9. Registry Integration Tests
# =========================================================================

class TestRegistryIntegration:
    """Verify new rules are registered and can be built by name."""

    def test_all_new_rules_in_registry(self):
        expected = [
            "search_guard", "promise_checker", "antipattern",
            "extended_domain", "production_ready", "async_safety",
            "exception_hierarchy",
        ]
        for name in expected:
            assert name in _RULE_REGISTRY, f"{name} not found in _RULE_REGISTRY"

    def test_build_rules_for_names(self):
        names = ["search_guard", "promise_checker", "antipattern"]
        rules = build_rules_for_names(names)
        assert len(rules) == 3
        assert rules[0].name == "search_guard"
        assert rules[1].name == "promise_checker"
        assert rules[2].name == "antipattern"

    def test_build_mixed_old_and_new(self):
        names = ["ast_syntax", "search_guard", "no_eval_exec", "antipattern"]
        rules = build_rules_for_names(names)
        assert len(rules) == 4

    def test_unknown_name_skipped(self):
        names = ["search_guard", "nonexistent_rule", "antipattern"]
        rules = build_rules_for_names(names)
        assert len(rules) == 2


# =========================================================================
# 10. RuleRunner Integration Tests
# =========================================================================

class TestRuleRunnerIntegration:
    """Test new rules work correctly within RuleRunner."""

    def test_runner_with_all_new_rules(self):
        rules = [
            SearchGuardRule(),
            PromiseCheckerRule(),
            AntiPatternRule(),
            ExtendedDomainRule(),
            ProductionReadyRule(),
            AsyncSafetyRule(),
            ExceptionHierarchyRule(),
        ]
        runner = RuleRunner(rules)

        code = '''
def fibonacci(n: int) -> int:
    """Return the n-th Fibonacci number.

    Args:
        n: Index in the Fibonacci sequence.

    Returns:
        The n-th Fibonacci number.

    Raises:
        ValueError: If n is negative.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
'''
        results = runner.run(code, parallel=False)
        assert len(results) == 7
        for r in results:
            assert r.passed, f"{r.rule_name} failed: {r.messages}"

    def test_runner_parallel_execution(self):
        rules = [
            SearchGuardRule(),
            AntiPatternRule(),
            AsyncSafetyRule(),
        ]
        runner = RuleRunner(rules, max_workers=3)

        code = '''
def add(a: int, b: int) -> int:
    return a + b
'''
        results = runner.run(code, parallel=True)
        assert len(results) == 3
        for r in results:
            assert r.passed

    def test_runner_catches_bad_code(self):
        rules = [
            AntiPatternRule(),
            ExceptionHierarchyRule(),
        ]
        runner = RuleRunner(rules)

        code = '''
import pickle

password = "hardcoded_secret_value_12345"

class MyError(BaseException):
    pass

def process(items=[]):
    try:
        data = pickle.loads(user_input)
    except:
        pass
'''
        results = runner.run(code, parallel=False)
        # At least one rule should fail
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 1


# =========================================================================
# 11. ValidationProfile Integration Tests
# =========================================================================

class TestValidationProfileIntegration:
    """Test that new rules are in validation profiles."""

    def test_fast_dev_has_search_guard(self):
        from core.task_abstraction import _PROFILE_CONFIGS, ValidationProfile
        fast_dev = _PROFILE_CONFIGS[ValidationProfile.FAST_DEV]
        assert "search_guard" in fast_dev["rule_names"]

    def test_balanced_has_quality_rules(self):
        from core.task_abstraction import _PROFILE_CONFIGS, ValidationProfile
        balanced = _PROFILE_CONFIGS[ValidationProfile.BALANCED]
        assert "search_guard" in balanced["rule_names"]
        assert "promise_checker" in balanced["rule_names"]
        assert "antipattern" in balanced["rule_names"]

    def test_safe_fix_has_all_quality_rules(self):
        from core.task_abstraction import _PROFILE_CONFIGS, ValidationProfile
        safe_fix = _PROFILE_CONFIGS[ValidationProfile.SAFE_FIX]
        expected = [
            "search_guard", "promise_checker", "antipattern",
            "extended_domain", "production_ready", "async_safety",
            "exception_hierarchy",
        ]
        for name in expected:
            assert name in safe_fix["rule_names"], f"{name} missing from SAFE_FIX"

    def test_critical_has_all_quality_rules(self):
        from core.task_abstraction import _PROFILE_CONFIGS, ValidationProfile
        critical = _PROFILE_CONFIGS[ValidationProfile.CRITICAL]
        expected = [
            "search_guard", "promise_checker", "antipattern",
            "extended_domain", "production_ready", "async_safety",
            "exception_hierarchy",
        ]
        for name in expected:
            assert name in critical["rule_names"], f"{name} missing from CRITICAL"
