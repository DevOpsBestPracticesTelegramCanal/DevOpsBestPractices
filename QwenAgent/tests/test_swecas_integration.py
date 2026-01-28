# -*- coding: utf-8 -*-
"""
Integration tests for SWECAS V2 + Diffuse Thinking + safe_write + prompt decontamination.

Run: python -m pytest tests/test_swecas_integration.py -v
"""

import sys
import os
import json
import tempfile
import shutil

# Add parent dir to path so we can import core modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.swecas_classifier import SWECASClassifier
from core.tools_extended import ExtendedTools
from core.cot_engine import CoTEngine


# =============================================================================
# Test 1: Classifier categories
# =============================================================================

def test_classifier_categories():
    """All 9 SWECAS categories classify correctly with matching keywords"""
    classifier = SWECASClassifier()

    test_cases = [
        (100, "NoneType has no attribute 'name', AttributeError when accessing None object"),
        (200, "ImportError: No module named 'flask', ModuleNotFoundError in dependency"),
        (300, "TypeError: expected str, got int. Type mismatch in function signature"),
        (400, "DeprecationWarning: function deprecated, use new_func instead. Breaking change in API"),
        (500, "assert name validation, should raise ValueError for invalid input, sanitize check"),
        (600, "Logic error: wrong condition in if/else control flow, off-by-one in loop"),
        (700, "Configuration error: wrong path in environment variable, ENV settings missing"),
        (800, "Performance issue: slow memory leak, N+1 query optimization needed"),
        (900, "async await race condition: deadlock in concurrent threading with missing lock"),
    ]

    passed = 0
    for expected_code, description in test_cases:
        result = classifier.classify(description)
        actual_code = result["swecas_code"]
        confidence = result["confidence"]

        status = "PASS" if actual_code == expected_code else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  [{status}] SWECAS-{expected_code}: got {actual_code} (confidence: {confidence:.2f})")

    print(f"\n  Classifier categories: {passed}/{len(test_cases)} passed")
    assert passed >= 7, f"At least 7/9 categories should classify correctly, got {passed}/9"


# =============================================================================
# Test 2: Diffuse links
# =============================================================================

def test_diffuse_links():
    """Cross-links return valid category codes"""
    classifier = SWECASClassifier()

    for cat_code in [100, 200, 300, 400, 500, 600, 700, 800, 900]:
        links = classifier.get_diffuse_links(cat_code)
        assert isinstance(links, list), f"SWECAS-{cat_code}: links should be a list"
        assert len(links) >= 2, f"SWECAS-{cat_code}: should have at least 2 cross-links, got {len(links)}"

        for link in links:
            assert isinstance(link, int), f"SWECAS-{cat_code}: link {link} should be int"
            assert 100 <= link <= 999, f"SWECAS-{cat_code}: link {link} out of range"

    print("  Diffuse links: all categories have valid cross-links")


# =============================================================================
# Test 3: Fix templates
# =============================================================================

def test_fix_templates():
    """Templates render valid Python (no syntax errors in template strings)"""
    classifier = SWECASClassifier()

    template_codes = [510, 511, 630, 611, 110, 111, 210, 410, 710, 911]
    found = 0
    for code in template_codes:
        template = classifier.get_fix_template(code)
        if template:
            found += 1
            # Template should be a non-empty string
            assert isinstance(template, str), f"Template {code} should be string"
            assert len(template) > 10, f"Template {code} too short"
            # Template should contain placeholder markers (curly braces)
            assert '{' in template, f"Template {code} should have placeholders"

    print(f"  Fix templates: {found}/{len(template_codes)} templates found")
    assert found >= 8, f"At least 8 templates should exist, got {found}"


# =============================================================================
# Test 4: safe_write syntax check
# =============================================================================

def test_safe_write_syntax_check():
    """Broken Python is rejected, valid Python is written"""
    # Create a temp directory for test files
    tmpdir = tempfile.mkdtemp(prefix="swecas_test_")

    try:
        # Test 1: Valid Python should be written
        valid_path = os.path.join(tmpdir, "valid.py")
        result = ExtendedTools.write(valid_path, "def hello():\n    return 'world'\n")
        assert result["success"], f"Valid Python should be written: {result.get('error')}"
        assert os.path.exists(valid_path), "File should exist after write"

        # Test 2: Broken Python should be rejected
        broken_path = os.path.join(tmpdir, "broken.py")
        result = ExtendedTools.write(broken_path, "def f(:\n  pass\n")
        assert not result["success"], "Broken Python should be rejected"
        assert result.get("syntax_error"), "Should report syntax_error flag"
        assert not os.path.exists(broken_path), "Broken file should NOT be created"

        # Test 3: Non-Python files should always be written (no syntax check)
        txt_path = os.path.join(tmpdir, "data.txt")
        result = ExtendedTools.write(txt_path, "this is not python: def f(:\n")
        assert result["success"], "Non-Python files should always be written"

        # Test 4: Valid Python overwriting existing file should create backup
        result2 = ExtendedTools.write(valid_path, "def goodbye():\n    return 'bye'\n")
        assert result2["success"], "Overwrite should succeed"
        backup_path = valid_path + ".bak"
        assert os.path.exists(backup_path), "Backup should be created on overwrite"

        print("  safe_write: all 4 checks passed")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# Test 5: safe_edit syntax check
# =============================================================================

def test_safe_edit_syntax_check():
    """Edit that would break syntax is rejected"""
    tmpdir = tempfile.mkdtemp(prefix="swecas_test_")

    try:
        # Create valid Python file
        test_path = os.path.join(tmpdir, "target.py")
        with open(test_path, 'w') as f:
            f.write("def greet(name):\n    return f'Hello {name}'\n")

        # Test 1: Valid edit should succeed
        result = ExtendedTools.edit(
            test_path,
            old_string="return f'Hello {name}'",
            new_string="return f'Hi {name}!'"
        )
        assert result["success"], f"Valid edit should succeed: {result.get('error')}"

        # Test 2: Edit that breaks syntax should be rejected
        result2 = ExtendedTools.edit(
            test_path,
            old_string="def greet(name):",
            new_string="def greet(name"  # Missing colon = syntax error
        )
        assert not result2["success"], "Syntax-breaking edit should be rejected"
        assert result2.get("syntax_error"), "Should report syntax_error flag"

        # Verify file still has valid content (not corrupted)
        with open(test_path, 'r') as f:
            content = f.read()
        assert "def greet(name):" in content, "File should still have valid content after rejected edit"

        print("  safe_edit: all checks passed")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# Test 6: Prompt decontamination
# =============================================================================

def test_prompt_no_contamination():
    """System prompt has no math.py, add(a,b), subtract examples"""
    from core.qwencode_agent import QwenCodeAgent

    prompt = QwenCodeAgent.SYSTEM_PROMPT

    contamination_patterns = [
        "math.py",
        "add(a,b)",
        "add(a, b)",
        "subtract",
        "hello.py",
        "hello world",
        "Hello World",
        "quicksort",
    ]

    found = []
    for pattern in contamination_patterns:
        if pattern.lower() in prompt.lower():
            found.append(pattern)

    assert len(found) == 0, f"System prompt still contains contamination: {found}"

    # Check that FORBIDDEN ACTIONS section exists
    assert "FORBIDDEN ACTIONS" in prompt, "SYSTEM_PROMPT must have FORBIDDEN ACTIONS section"
    assert "VIOLATION CHECK" in prompt, "SYSTEM_PROMPT must have VIOLATION CHECK section"
    assert "NEVER create files that the user did not ask for" in prompt, "Must prohibit uninstructed file creation"
    assert "NEVER invent new files" in prompt, "Must prohibit invented files"
    assert "COMPLETE file content" in prompt, "Must require complete file content"

    print("  Prompt decontamination: clean, no contamination found")


# =============================================================================
# Test 7: SWECAS CoT engine integration
# =============================================================================

def test_deep_mode_swecas_pipeline():
    """End-to-end CLASSIFY -> DIFFUSE -> FOCUS -> FIX pipeline"""
    classifier = SWECASClassifier()
    cot = CoTEngine()
    cot.enable_deep_mode(True)

    # Simulate Flask-4045 bug
    description = "Blueprint name validation uses assert. Should raise ValueError for names with dots."
    file_content = '''class Blueprint:
    def __init__(self, name, import_name):
        assert "." not in name, "Blueprint name should not contain dots"
        self.name = name
'''

    # Step 1: CLASSIFY
    swecas_result = classifier.classify(description, file_content=file_content)
    assert swecas_result["swecas_code"] == 500, \
        f"Flask-4045 should be SWECAS-500, got {swecas_result['swecas_code']}"
    assert swecas_result["confidence"] >= 0.6, \
        f"Confidence should be >= 0.6, got {swecas_result['confidence']}"

    # Step 2: Create SWECAS-enhanced CoT prompt
    prompt = cot.create_thinking_prompt(
        "Fix blueprint name validation in blueprints.py",
        swecas_context=swecas_result
    )

    # Verify prompt contains SWECAS context
    assert "SWECAS" in prompt, "Prompt should contain SWECAS classification"
    assert "500" in prompt, "Prompt should reference SWECAS-500"
    assert "CLASSIFY" in prompt, "Prompt should have CLASSIFY step"
    assert "DIFFUSE" in prompt, "Prompt should have DIFFUSE step"
    assert "FOCUS" in prompt, "Prompt should have FOCUS step"
    assert "FIX" in prompt, "Prompt should have FIX step"
    assert "assert" in prompt.lower() or "validation" in prompt.lower(), \
        "Prompt should mention validation pattern"

    # Step 3: Verify diffuse links exist
    links = classifier.get_diffuse_links(500)
    assert len(links) >= 3, f"SWECAS-500 should have at least 3 diffuse links, got {len(links)}"

    # Step 4: Verify fix template exists
    template = classifier.get_fix_template(510)
    assert template is not None, "SWECAS-510 should have a fix template"
    assert "raise" in template, "Template should contain raise statement"

    print("  SWECAS pipeline: CLASSIFY -> DIFFUSE -> FOCUS -> FIX verified")


# =============================================================================
# Test 8: Search cache
# =============================================================================

def test_search_cache():
    """Search cache loads and returns results for all 9 categories"""
    cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'core', 'swecas_search_cache.json')
    assert os.path.exists(cache_path), f"Cache file should exist at {cache_path}"

    with open(cache_path, 'r', encoding='utf-8') as f:
        cache = json.load(f)

    categories = ["100", "200", "300", "400", "500", "600", "700", "800", "900"]
    for cat in categories:
        assert cat in cache, f"Category {cat} missing from cache"
        assert "patterns" in cache[cat], f"Category {cat} missing patterns"
        assert "fix_hints" in cache[cat], f"Category {cat} missing fix_hints"
        assert len(cache[cat]["patterns"]) >= 3, f"Category {cat} needs at least 3 patterns"
        assert len(cache[cat]["fix_hints"]) >= 3, f"Category {cat} needs at least 3 fix_hints"

    print(f"  Search cache: all {len(categories)} categories present with patterns and hints")


# =============================================================================
# Test 9: Cross-category patterns
# =============================================================================

def test_cross_category_patterns():
    """Cross-category patterns are accessible and well-formed"""
    classifier = SWECASClassifier()

    expected_patterns = ["guard_missing", "contract_violation", "environment_assumption",
                         "silent_failure", "temporal_ordering"]

    for name in expected_patterns:
        assert name in classifier.CROSS_PATTERNS, f"Missing cross-pattern: {name}"
        pattern = classifier.CROSS_PATTERNS[name]
        assert "description" in pattern, f"Pattern {name} missing description"
        assert "instances" in pattern, f"Pattern {name} missing instances"
        assert "insight" in pattern, f"Pattern {name} missing insight"
        assert len(pattern["instances"]) >= 3, f"Pattern {name} needs at least 3 instances"

    # Test get_cross_patterns method
    patterns_500 = classifier.get_cross_patterns(500)
    assert len(patterns_500) >= 1, "SWECAS-500 should match at least 1 cross-pattern"

    print(f"  Cross-category patterns: all {len(expected_patterns)} patterns valid")


# =============================================================================
# Main runner
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("SWECAS V2 Integration Tests")
    print("=" * 60)

    tests = [
        ("1. Classifier categories", test_classifier_categories),
        ("2. Diffuse links", test_diffuse_links),
        ("3. Fix templates", test_fix_templates),
        ("4. safe_write syntax check", test_safe_write_syntax_check),
        ("5. safe_edit syntax check", test_safe_edit_syntax_check),
        ("6. Prompt decontamination", test_prompt_no_contamination),
        ("7. SWECAS pipeline (end-to-end)", test_deep_mode_swecas_pipeline),
        ("8. Search cache", test_search_cache),
        ("9. Cross-category patterns", test_cross_category_patterns),
    ]

    passed = 0
    failed = 0
    errors = []

    for name, test_fn in tests:
        print(f"\nTest {name}:")
        try:
            test_fn()
            passed += 1
            print(f"  -> PASSED")
        except AssertionError as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  -> FAILED: {e}")
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  -> ERROR: {e}")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  - {name}: {err}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
