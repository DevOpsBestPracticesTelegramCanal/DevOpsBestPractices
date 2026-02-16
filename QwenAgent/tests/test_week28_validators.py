"""
Unit tests for Week 28 validators: ThreadSafetyRule, InitCompletenessRule, CrossModuleContractRule.

Tests cover:
- ThreadSafetyRule: shared mutable state, daemon threads, locks
- InitCompletenessRule: database setup, resource cleanup
- CrossModuleContractRule: enum contracts, abstract methods, dataclass fields
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from code_validator.rules.thread_safety import ThreadSafetyRule
from code_validator.rules.init_completeness import InitCompletenessRule
from code_validator.rules.cross_module_contract import CrossModuleContractRule


class TestThreadSafetyRule:
    """Tests for ThreadSafetyRule validator."""

    def test_mutable_attrs_without_lock_fails(self):
        """Class with mutable attrs mutated in methods WITHOUT Lock should FAIL."""
        code = """
class Cache:
    def __init__(self):
        self.data = {}
        self.items = []

    def add(self, key, value):
        self.data[key] = value
        self.items.append(key)

    def get(self, key):
        return self.data.get(key)
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("mutable" in msg.lower() or "thread" in msg.lower() for msg in result.messages)

    def test_mutable_attrs_with_lock_passes(self):
        """Class with mutable attrs but HAS Lock attr should PASS (skips detailed checking)."""
        code = """
import threading

class SafeCache:
    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()

    def add(self, key, value):
        with self.lock:
            self.data[key] = value
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_no_mutable_attrs_passes(self):
        """Class with no mutable attrs should PASS."""
        code = """
class Calculator:
    def __init__(self):
        self.name = "calc"
        self.version = 1.0

    def add(self, a, b):
        return a + b
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_daemon_thread_without_join_fails(self):
        """Thread(daemon=True) without join() should FAIL."""
        code = """
import threading

class Worker:
    def start(self):
        t = threading.Thread(target=self.work, daemon=True)
        t.start()

    def work(self):
        pass
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("daemon" in msg.lower() for msg in result.messages)

    def test_daemon_thread_with_join_passes(self):
        """Thread(daemon=True) with join() should PASS."""
        code = """
import threading

class Worker:
    def start(self):
        t = threading.Thread(target=self.work, daemon=True)
        t.start()
        t.join()

    def work(self):
        pass
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_global_mutable_without_lock_fails(self):
        """Global mutable dict + threading import without module Lock should FAIL."""
        code = """
import threading

cache = {}

def add_to_cache(key, value):
    cache[key] = value

def get_from_cache(key):
    return cache.get(key)
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("global" in msg.lower() or "mutable" in msg.lower() for msg in result.messages)

    def test_global_mutable_with_lock_passes(self):
        """Global mutable dict + module Lock should PASS."""
        code = """
import threading

cache = {}
cache_lock = threading.Lock()

def add_to_cache(key, value):
    with cache_lock:
        cache[key] = value
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_global_mutable_without_threading_import_passes(self):
        """Global mutable dict WITHOUT threading import should PASS."""
        code = """
cache = {}

def add_to_cache(key, value):
    cache[key] = value
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_syntax_error_returns_ok(self):
        """Syntax error code should return ok (skipped)."""
        code = """
class Broken
    def method(self):
        pass
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_subscript_assignment_detected(self):
        """Subscript assignment (self.data[key] = val) should be detected."""
        code = """
class Storage:
    def __init__(self):
        self.items = {}

    def store(self, key, value):
        self.items[key] = value
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0

    def test_init_mutations_not_flagged(self):
        """__init__ mutations should NOT be flagged."""
        code = """
class Config:
    def __init__(self):
        self.settings = {}
        self.settings['debug'] = True
        self.settings['port'] = 8080

    def get(self, key):
        return self.settings.get(key)
"""
        rule = ThreadSafetyRule()
        result = rule.check(code)

        # Should pass because mutations are only in __init__
        assert result.passed
        assert result.score == 1.0


class TestInitCompletenessRule:
    """Tests for InitCompletenessRule validator."""

    def test_database_without_schema_fails(self):
        """Class with self.conn but no CREATE TABLE should FAIL."""
        code = """
import sqlite3

class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)

    def insert(self, data):
        self.conn.execute("INSERT INTO users VALUES (?)", (data,))
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("schema" in msg.lower() or "create table" in msg.lower() for msg in result.messages)

    def test_database_with_schema_passes(self):
        """Class with self.db and has CREATE TABLE IF NOT EXISTS + close should PASS."""
        code = """
import sqlite3

class Database:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        ''')

    def insert(self, name):
        self.db.execute("INSERT INTO users (name) VALUES (?)", (name,))

    def close(self):
        self.db.close()
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_database_with_init_schema_method_passes(self):
        """Class with self.conn and has init_schema method + close should PASS."""
        code = """
import sqlite3

class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.init_schema()

    def init_schema(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        ''')

    def close(self):
        self.conn.close()
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_resource_without_cleanup_fails(self):
        """Class opens resource (open(), connect()) without close()/__exit__ should FAIL."""
        code = """
class FileHandler:
    def __init__(self, path):
        self.file = open(path, 'r')

    def read_line(self):
        return self.file.readline()
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("cleanup" in msg.lower() or "close" in msg.lower() for msg in result.messages)

    def test_resource_with_close_method_passes(self):
        """Class opens resource but has close() method should PASS."""
        code = """
class FileHandler:
    def __init__(self, path):
        self.file = open(path, 'r')

    def read_line(self):
        return self.file.readline()

    def close(self):
        self.file.close()
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_resource_with_exit_passes(self):
        """Class opens resource but has __exit__ should PASS."""
        code = """
class FileHandler:
    def __init__(self, path):
        self.file = open(path, 'r')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file.close()
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_resource_with_del_passes(self):
        """Class opens resource but has __del__ should PASS."""
        code = """
class FileHandler:
    def __init__(self, path):
        self.file = open(path, 'r')

    def __del__(self):
        if hasattr(self, 'file'):
            self.file.close()
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_class_without_init_returns_ok(self):
        """Class without __init__ should return ok."""
        code = """
class Helper:
    @staticmethod
    def format(value):
        return str(value)
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_syntax_error_returns_ok(self):
        """Syntax error should return ok."""
        code = """
class Broken
    def __init__(self):
        pass
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_no_classes_returns_ok(self):
        """Code with no classes should return ok."""
        code = """
def helper_function():
    return 42

result = helper_function()
"""
        rule = InitCompletenessRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0


class TestCrossModuleContractRule:
    """Tests for CrossModuleContractRule validator."""

    def test_single_class_returns_ok(self):
        """Single class should return ok (N/A)."""
        code = """
class SingleClass:
    def method(self):
        pass
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_enum_correct_access_passes(self):
        """Enum defined + enum value accessed correctly should PASS."""
        code = """
from enum import Enum

class Status(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"

def process(status):
    if status == Status.PENDING:
        return "Processing..."
    elif status == Status.COMPLETED:
        return "Done"
    return "Error"
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_enum_incorrect_access_fails(self):
        """Enum defined + non-existent value accessed should FAIL with message about available values."""
        code = """
from enum import Enum

class Status(Enum):
    PENDING = "pending"
    COMPLETED = "completed"

class Processor:
    def process(self, status):
        if status == Status.RUNNING:
            return "In progress"
        return "Done"
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("RUNNING" in msg and ("PENDING" in msg or "COMPLETED" in msg) for msg in result.messages)

    def test_abstract_method_implemented_passes(self):
        """Abstract method in base + implemented in subclass should PASS."""
        code = """
from abc import ABC, abstractmethod

class Base(ABC):
    @abstractmethod
    def process(self, data):
        pass

class Concrete(Base):
    def process(self, data):
        return data.upper()
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_abstract_method_not_implemented_fails(self):
        """Abstract method in base + NOT implemented in subclass should FAIL."""
        code = """
from abc import ABC, abstractmethod

class Base(ABC):
    @abstractmethod
    def process(self, data):
        pass

    @abstractmethod
    def validate(self, data):
        pass

class Concrete(Base):
    def process(self, data):
        return data.upper()
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("validate" in msg.lower() and "abstract" in msg.lower() for msg in result.messages)

    def test_signature_mismatch_fails(self):
        """Base and derived class have same method with different params should FAIL."""
        code = """
class Base:
    def process(self, data, format):
        pass

class Derived(Base):
    def process(self, data):
        return data.upper()
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("signature" in msg.lower() or "parameter" in msg.lower() for msg in result.messages)

    def test_signature_match_passes(self):
        """Base and derived class have same method with same params should PASS."""
        code = """
class Base:
    def process(self, data, format="json"):
        pass

class Derived(Base):
    def process(self, data, format="json"):
        return data.upper()
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_dataclass_correct_field_access_passes(self):
        """Dataclass defined + correct field accessed should PASS."""
        code = """
from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int
    email: str

def greet(user: User):
    return f"Hello {user.name}, you are {user.age} years old"
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0

    def test_dataclass_incorrect_field_access_fails(self):
        """Dataclass defined + incorrect field accessed should FAIL."""
        code = """
from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int

class Renderer:
    def display(self, user: User):
        print(f"{user.name} - {user.email}")
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert not result.passed
        assert result.score < 1.0
        assert any("email" in msg.lower() and ("name" in msg.lower() or "age" in msg.lower()) for msg in result.messages)

    def test_syntax_error_returns_ok(self):
        """Syntax error should return ok."""
        code = """
class Broken
    def method(self):
        pass
"""
        rule = CrossModuleContractRule()
        result = rule.check(code)

        assert result.passed
        assert result.score == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
