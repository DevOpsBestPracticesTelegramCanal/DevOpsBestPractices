# -*- coding: utf-8 -*-
"""
Shared fixtures for QwenAgent test suite.
"""

import sys
import os
import json
import tempfile
import shutil
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.swecas_classifier import SWECASClassifier
from core.tools_extended import ExtendedTools
from core.cot_engine import CoTEngine


@pytest.fixture
def classifier():
    """Fresh SWECASClassifier instance."""
    return SWECASClassifier()


@pytest.fixture
def cot_engine():
    """CoT engine with deep mode enabled."""
    engine = CoTEngine()
    engine.enable_deep_mode(True)
    return engine


@pytest.fixture
def search_cache():
    """Loaded SWECAS search cache."""
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'core', 'swecas_search_cache.json'
    )
    with open(cache_path, 'r', encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture
def tmpdir_clean():
    """Temporary directory, cleaned up after test."""
    d = tempfile.mkdtemp(prefix="qwenagent_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def swebench_tasks_dir():
    """Path to swebench_tasks directory."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'swebench_tasks'
    )


@pytest.fixture
def all_swecas_categories():
    """All 9 SWECAS category codes."""
    return [100, 200, 300, 400, 500, 600, 700, 800, 900]
