# -*- coding: utf-8 -*-
"""
Edge case tests for SWECAS system — 15 tests covering unusual scenarios.

Run: python -m pytest tests/test_edge_cases.py -v
"""

import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.swecas_classifier import SWECASClassifier
from core.tools_extended import ExtendedTools
from core.cot_engine import CoTEngine


# =====================================================================
# Edge Case 1-3: Cross-category bugs (spans 2+ categories)
# =====================================================================

def test_cross_category_null_plus_logic():
    """Bug that is both None-check (100) AND logic error (600)."""
    clf = SWECASClassifier()
    r = clf.classify("NoneType error because wrong condition in if/else "
                      "leads to None being returned instead of actual value. "
                      "Logic error causes null pointer.")
    # Should classify as one of {100, 600}
    assert r["swecas_code"] in [100, 600], f"Expected 100 or 600, got {r['swecas_code']}"
    assert r["confidence"] > 0, "Must have some confidence"


def test_cross_category_type_plus_api():
    """Bug spanning Type (300) and API deprecation (400)."""
    clf = SWECASClassifier()
    r = clf.classify("TypeError after upgrading library. API signature changed, "
                      "function now returns str instead of bytes. Deprecated old "
                      "type behavior in new version.")
    assert r["swecas_code"] in [300, 400], f"Expected 300 or 400, got {r['swecas_code']}"


def test_cross_category_validation_plus_logic():
    """Bug spanning Validation (500) and Logic (600)."""
    clf = SWECASClassifier()
    r = clf.classify("Validation check uses wrong condition. Assert with inverted "
                      "logic allows invalid input. Should raise ValueError but "
                      "control flow takes wrong branch.")
    assert r["swecas_code"] in [500, 600], f"Expected 500 or 600, got {r['swecas_code']}"


# =====================================================================
# Edge Case 4-5: Ambiguous descriptions
# =====================================================================

def test_ambiguous_minimal_description():
    """Very short, ambiguous description."""
    clf = SWECASClassifier()
    r = clf.classify("Fix the bug")
    # Should return something, even if low confidence
    assert r["swecas_code"] == 0 or r["confidence"] <= 0.3, \
        "Ambiguous input should have low confidence or be unclassified"


def test_ambiguous_no_keywords():
    """Description with no SWECAS keywords at all."""
    clf = SWECASClassifier()
    r = clf.classify("The application needs improvements to the user interface "
                      "and better color scheme for the dashboard.")
    assert r["swecas_code"] == 0, "No relevant keywords should be unclassified"


# =====================================================================
# Edge Case 6-7: Large file handling
# =====================================================================

def test_large_file_classification():
    """Classification with 500+ line file content."""
    clf = SWECASClassifier()
    # Generate a large file with validation pattern buried in it
    lines = [f"x_{i} = {i}\n" for i in range(500)]
    lines[250] = "assert name.isalnum(), 'Invalid name'  # validation bug\n"
    large_content = "".join(lines)

    r = clf.classify("Fix input validation bug", file_content=large_content)
    assert r["swecas_code"] in [500, 600, 100], "Should detect validation pattern"
    assert r["confidence"] > 0


def test_empty_file_content():
    """Classification with empty file content."""
    clf = SWECASClassifier()
    r = clf.classify("Fix TypeError in module", file_content="")
    assert r["swecas_code"] == 300, "Should classify from description alone"


# =====================================================================
# Edge Case 8-9: Fix template edge cases
# =====================================================================

def test_fix_template_unknown_subcategory():
    """Requesting template for non-existent subcategory."""
    clf = SWECASClassifier()
    t = clf.get_fix_template(999)
    assert t is None, "Unknown subcategory should return None"


def test_fix_template_all_known():
    """All documented subcategories have templates."""
    clf = SWECASClassifier()
    known = [510, 511, 630, 611, 110, 111, 210, 410, 710, 911]
    for code in known:
        t = clf.get_fix_template(code)
        assert t is not None, f"Template for {code} missing"
        assert len(t) > 5, f"Template for {code} too short"


# =====================================================================
# Edge Case 10-11: Diffuse thinking edge cases
# =====================================================================

def test_diffuse_links_for_all_categories():
    """Every category has at least 3 diffuse cross-links."""
    clf = SWECASClassifier()
    for cat in [100, 200, 300, 400, 500, 600, 700, 800, 900]:
        links = clf.get_diffuse_links(cat)
        assert len(links) >= 3, f"SWECAS-{cat}: only {len(links)} links, need >= 3"


def test_diffuse_prompts_all_categories():
    """Every category has at least 3 diffuse prompts."""
    clf = SWECASClassifier()
    for cat in [100, 200, 300, 400, 500, 600, 700, 800, 900]:
        prompts = clf.get_diffuse_prompts(cat)
        assert len(prompts) >= 3, f"SWECAS-{cat}: only {len(prompts)} prompts"
        for p in prompts:
            assert len(p) > 10, f"SWECAS-{cat}: prompt too short: {p!r}"


# =====================================================================
# Edge Case 12-13: CoT engine edge cases
# =====================================================================

def test_cot_fast_mode_passthrough():
    """In fast mode, CoT engine returns task string unchanged."""
    cot = CoTEngine()
    cot.enable_deep_mode(False)
    result = cot.create_thinking_prompt("Fix the bug")
    assert result == "Fix the bug", "Fast mode should return task as-is"


def test_cot_deep_mode_adds_structure():
    """In deep mode, CoT engine adds structured thinking steps."""
    cot = CoTEngine()
    cot.enable_deep_mode(True)
    result = cot.create_thinking_prompt("Fix the bug")
    assert "UNDERSTANDING" in result or "Task:" in result, \
        "Deep mode should add structure"
    assert len(result) > len("Fix the bug"), "Deep mode output should be longer"


# =====================================================================
# Edge Case 14-15: Search cache edge cases
# =====================================================================

def test_search_cache_has_meta():
    """Search cache must have _meta section with version."""
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'core', 'swecas_search_cache.json'
    )
    with open(cache_path, 'r', encoding='utf-8') as f:
        cache = json.load(f)

    assert "_meta" in cache, "Cache must have _meta section"
    assert "version" in cache["_meta"], "Meta must have version"
    assert cache["_meta"]["categories"] == 9


def test_search_cache_subcategories_valid():
    """All subcategories in cache have name, patterns, fix_hints."""
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'core', 'swecas_search_cache.json'
    )
    with open(cache_path, 'r', encoding='utf-8') as f:
        cache = json.load(f)

    for cat_key in ["100", "200", "300", "400", "500", "600", "700", "800", "900"]:
        subcats = cache[cat_key].get("subcategories", {})
        assert len(subcats) >= 3, f"Category {cat_key}: needs >= 3 subcategories"
        for sub_key, sub_val in subcats.items():
            assert "name" in sub_val, f"{cat_key}.{sub_key}: missing name"
            assert "patterns" in sub_val, f"{cat_key}.{sub_key}: missing patterns"
            assert "fix_hints" in sub_val, f"{cat_key}.{sub_key}: missing fix_hints"
