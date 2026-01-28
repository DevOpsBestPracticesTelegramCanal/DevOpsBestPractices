# -*- coding: utf-8 -*-
"""
Search fallback chain tests — 5 tests verifying SearXNG -> DuckDuckGo -> cache.

Run: python -m pytest tests/test_search_fallback.py -v
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools_extended import ExtendedTools


# =====================================================================
# Test 1: SearXNG graceful failure on bad URL
# =====================================================================

def test_searxng_connection_refused():
    """SearXNG returns success=False with clear error on connection refused."""
    r = ExtendedTools.web_search_searxng("test query", searxng_url="http://127.0.0.1:1")
    assert r["success"] is False
    assert "source" in r
    assert r["source"] == "searxng"
    assert "error" in r


# =====================================================================
# Test 2: SearXNG timeout on bad host
# =====================================================================

def test_searxng_bad_host():
    """SearXNG returns failure for unreachable host."""
    r = ExtendedTools.web_search_searxng("test", searxng_url="http://192.0.2.1:9999")
    assert r["success"] is False
    assert r["source"] == "searxng"


# =====================================================================
# Test 3: DuckDuckGo returns source field
# =====================================================================

def test_duckduckgo_has_source_field():
    """DuckDuckGo search result includes 'source' field."""
    r = ExtendedTools.web_search("python requests library")
    assert "source" in r, "web_search must include source field"
    if r["success"]:
        assert r["source"] == "duckduckgo"


# =====================================================================
# Test 4: SWECAS cache provides offline results
# =====================================================================

def test_swecas_cache_offline_fallback():
    """SWECAS search cache loads and provides results for all categories."""
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'core', 'swecas_search_cache.json'
    )
    with open(cache_path, 'r', encoding='utf-8') as f:
        cache = json.load(f)

    for cat in ["100", "200", "300", "400", "500", "600", "700", "800", "900"]:
        assert cat in cache, f"Category {cat} missing from cache"
        assert len(cache[cat]["patterns"]) >= 8, f"Category {cat}: need >= 8 patterns"
        assert len(cache[cat]["fix_hints"]) >= 8, f"Category {cat}: need >= 8 hints"
        assert "query" in cache[cat], f"Category {cat}: missing query field"


# =====================================================================
# Test 5: Search result format consistency
# =====================================================================

def test_search_result_format():
    """Both search backends return consistent result format."""
    # SearXNG (will fail but check format)
    r1 = ExtendedTools.web_search_searxng("test", searxng_url="http://127.0.0.1:1")
    assert "success" in r1
    assert "source" in r1

    # DuckDuckGo
    r2 = ExtendedTools.web_search("test")
    assert "success" in r2
    assert "source" in r2

    # Both have same fields
    for key in ["success", "source"]:
        assert key in r1, f"SearXNG result missing '{key}'"
        assert key in r2, f"DuckDuckGo result missing '{key}'"
