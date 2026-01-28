# -*- coding: utf-8 -*-
"""
Regression tests — ensure nothing breaks between commits.

Run: python -m pytest tests/test_regression.py -v
"""

import sys
import os
import subprocess
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.swecas_classifier import SWECASClassifier
from core.tools_extended import ExtendedTools
from core.qwencode_agent import QwenCodeAgent


# =========================================================================
# Regression 1: No math.py contamination in prompts
# =========================================================================

def test_no_math_py_contamination():
    """System prompt must never contain tutorial examples that leak into output."""
    prompt = QwenCodeAgent.SYSTEM_PROMPT
    contamination = [
        "math.py", "add(a,b)", "add(a, b)", "subtract",
        "hello.py", "hello world", "Hello World", "quicksort",
    ]
    found = [p for p in contamination if p.lower() in prompt.lower()]
    assert found == [], f"Contamination in system prompt: {found}"


# =========================================================================
# Regression 2: Generated Python always passes compile()
# =========================================================================

def test_no_syntax_errors_in_safe_write():
    """safe_write rejects broken Python, accepts valid Python."""
    tmpdir = tempfile.mkdtemp(prefix="reg_")
    try:
        valid = os.path.join(tmpdir, "ok.py")
        r = ExtendedTools.write(valid, "x = 1\n")
        assert r["success"], "Valid Python must be accepted"

        broken = os.path.join(tmpdir, "bad.py")
        r = ExtendedTools.write(broken, "def f(\n")
        assert not r["success"], "Broken Python must be rejected"
        assert not os.path.exists(broken)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# =========================================================================
# Regression 3: Classifier accuracy >= 80% on known tasks
# =========================================================================

def test_swecas_classification_accuracy():
    """Classifier must correctly classify >= 80% of known bug descriptions."""
    classifier = SWECASClassifier()
    known_tasks = [
        (500, "Blueprint name validation uses assert, should raise ValueError for invalid input"),
        (300, "builtin_str(method) converts bytes to wrong string representation, TypeError"),
        (100, "NoneType has no attribute, AttributeError accessing None object"),
        (200, "ImportError circular import ModuleNotFoundError"),
        (600, "Logic error wrong condition in if/else control flow"),
        (700, "Configuration error wrong path environment variable"),
        (800, "Performance slow memory leak N+1 query"),
        (900, "async await race condition deadlock concurrent"),
        (400, "DeprecationWarning API deprecated use instead"),
        (500, "Missing input validation, assert check, raise ValueError"),
    ]
    correct = sum(
        1 for expected, desc in known_tasks
        if classifier.classify(desc)["swecas_code"] == expected
    )
    accuracy = correct / len(known_tasks)
    assert accuracy >= 0.8, f"Accuracy {accuracy:.0%} < 80% ({correct}/{len(known_tasks)})"


# =========================================================================
# Regression 4: Search fallback chain works
# =========================================================================

def test_fallback_chain_returns_result():
    """SearXNG fail -> DuckDuckGo fallback -> at least one returns or cache."""
    r = ExtendedTools.web_search_searxng("test", searxng_url="http://127.0.0.1:1")
    assert not r["success"], "SearXNG on bad port should fail"
    assert r["source"] == "searxng"

    # DuckDuckGo should still be callable (may or may not succeed depending on network)
    r2 = ExtendedTools.web_search("python requests library")
    assert "source" in r2, "web_search must include source field"


# =========================================================================
# Regression 5: Flask-4045 baseline (4/4)
# =========================================================================

def test_flask_4045_still_passes():
    """Baseline: Flask-4045 must remain 4/4."""
    test_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "swebench_tasks", "pallets__flask-4045", "test_blueprint.py"
    )
    result = subprocess.run(
        [sys.executable, test_file],
        capture_output=True, text=True, timeout=30,
        encoding='utf-8', errors='replace'
    )
    assert result.returncode == 0, f"Flask-4045 tests failed:\n{result.stdout}\n{result.stderr}"
    assert "4/4" in result.stdout, "Expected 4/4 tests passed"


# =========================================================================
# Regression 6: requests-2317 baseline (2/2)
# =========================================================================

def test_requests_2317_still_passes():
    """Baseline: requests-2317 must remain passing."""
    test_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "swebench_tasks", "psf__requests-2317", "test_bug.py"
    )
    result = subprocess.run(
        [sys.executable, test_file],
        capture_output=True, text=True, timeout=30,
        encoding='utf-8', errors='replace'
    )
    assert result.returncode == 0, f"requests-2317 tests failed:\n{result.stdout}\n{result.stderr}"
    assert "All tests passed" in result.stdout
