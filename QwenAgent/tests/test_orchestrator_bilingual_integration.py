# -*- coding: utf-8 -*-
"""
Test Orchestrator + BilingualContextRouter Integration
=======================================================

Comprehensive tests for Orchestrator using BilingualContextRouter.
"""

import sys
import os
import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestrator import Orchestrator

# BilingualContextRouter module doesn't exist yet — skip tests that need it
try:
    from core.bilingual_context_router import BilingualContextRouter
    _has_bilingual = BilingualContextRouter is not None
except ImportError:
    _has_bilingual = False


@pytest.mark.skipif(not _has_bilingual, reason="bilingual_context_router module not yet implemented")
def test_orchestrator_bilingual_basic():
    """Test basic Orchestrator with BilingualContextRouter"""
    print("=" * 70)
    print("TEST: Orchestrator with BilingualContextRouter - Basic Commands")
    print("=" * 70)

    # Create Orchestrator with BilingualContextRouter
    orch = Orchestrator(use_bilingual_router=True)

    test_cases = [
        # English commands
        ("read config.py", "read", 0),  # Tier 0 (Regex)
        ("grep TODO src/", "grep", 0),   # Tier 0 (Regex)

        # Russian commands
        ("прочитай .env", "read", 1),   # Tier 1 (NLP)
        ("найди error", "grep", 1),      # Tier 1 (NLP)

        # Context commands (setup first)
        ("read setup.py", "read", 0),    # Setup context
        ("edit it line 20", "edit", 2),  # Tier 2 (Context)
    ]

    passed = 0
    failed = 0

    for query, expected_tool, expected_tier in test_cases:
        result = orch.process(query)

        if result and result.tool_calls:
            tool_call = result.tool_calls[0]
            tool_name = tool_call.get("tool")
            router_tier = tool_call.get("router_tier", 0)

            if tool_name == expected_tool:
                print(f"[OK] {query:30s} -> {tool_name} (T{router_tier})")
                passed += 1
            else:
                print(f"[FAIL] {query:30s} -> {tool_name} (expected: {expected_tool})")
                failed += 1
        else:
            print(f"[FAIL] {query:30s} -> NO RESULT")
            failed += 1

    print()
    print(f"Passed: {passed}/{passed+failed}")
    print()

    return passed == passed + failed


@pytest.mark.skipif(not _has_bilingual, reason="bilingual_context_router module not yet implemented")
def test_orchestrator_statistics():
    """Test Orchestrator statistics with BilingualContextRouter"""
    print("=" * 70)
    print("TEST: Orchestrator Statistics & Metrics")
    print("=" * 70)

    orch = Orchestrator(use_bilingual_router=True)

    # Run queries
    queries = [
        "read config.py",         # Tier 0
        "grep TODO",              # Tier 0
        "прочитай .env",          # Tier 1
        "найди error",            # Tier 1
        "read setup.py",          # Tier 0 (setup context)
        "edit it line 20",        # Tier 2 (context)
    ]

    for query in queries:
        orch.process(query)

    # Get statistics
    stats = orch.get_stats()

    print(f"Total Requests:     {stats['total_requests']}")
    print(f"Tier 0 (Pattern):   {stats['tier0_pattern']}")
    print(f"Tier 1 (DUCS):      {stats['tier1_ducs']}")
    print(f"Tier 1.5 (LLM):     {stats['tier1_5_llm']}")
    print(f"NO-LLM Rate:        {stats['no_llm_rate']}%")
    print(f"Light LLM Rate:     {stats['light_llm_rate']}%")
    print()

    # Check bilingual router stats
    if "bilingual_router_stats" in stats:
        br_stats = stats["bilingual_router_stats"]
        print("BilingualContextRouter Stats:")
        print(f"  Total:            {br_stats['total_requests']}")
        print(f"  Tier 0 hits:      {br_stats['tier0_hits']}")
        print(f"  Tier 1 hits:      {br_stats['tier1_hits']}")
        print(f"  Tier 2 hits:      {br_stats['tier2_hits']}")
        print(f"  Tier 1.5 hits:    {br_stats['tier1_5_hits']}")
        print(f"  Tier 4 escalations: {br_stats['tier4_escalations']}")
        print(f"  NO-LLM Rate:      {br_stats['no_llm_rate']}%")
        print(f"  Escalation Rate:  {br_stats['escalation_rate']}%")
        print()

    # Validate
    checks = []

    # Check 1: NO-LLM Rate >= 80%
    if stats["no_llm_rate"] >= 80.0:
        print("[OK] NO-LLM Rate >= 80%")
        checks.append(True)
    else:
        print(f"[FAIL] NO-LLM Rate {stats['no_llm_rate']}% < 80%")
        checks.append(False)

    # Check 2: Total requests match
    if stats["total_requests"] == len(queries):
        print(f"[OK] Total requests = {len(queries)}")
        checks.append(True)
    else:
        print(f"[FAIL] Total requests {stats['total_requests']} != {len(queries)}")
        checks.append(False)

    print()

    return all(checks)


def test_orchestrator_legacy_compatibility():
    """Test Legacy PatternRouter compatibility"""
    print("=" * 70)
    print("TEST: Legacy PatternRouter Compatibility")
    print("=" * 70)

    # Create Orchestrator with legacy router
    orch = Orchestrator(use_bilingual_router=False)

    test_cases = [
        ("read config.py", "read"),
        ("grep TODO", "grep"),
    ]

    passed = 0
    failed = 0

    for query, expected_tool in test_cases:
        result = orch.process(query)

        if result and result.tool_calls:
            tool_name = result.tool_calls[0].get("tool")

            if tool_name == expected_tool:
                print(f"[OK] {query:30s} -> {tool_name}")
                passed += 1
            else:
                print(f"[FAIL] {query:30s} -> {tool_name} (expected: {expected_tool})")
                failed += 1
        else:
            print(f"[FAIL] {query:30s} -> NO RESULT")
            failed += 1

    print()
    print(f"Passed: {passed}/{passed+failed}")
    print()

    return passed == passed + failed


if __name__ == "__main__":
    print("\n")
    print("=" * 70)
    print("ORCHESTRATOR + BILINGUAL CONTEXT ROUTER INTEGRATION TEST SUITE")
    print("=" * 70)
    print()

    results = []

    # Test 1: Basic integration
    results.append(("Basic Integration", test_orchestrator_bilingual_basic()))

    # Test 2: Statistics
    results.append(("Statistics & Metrics", test_orchestrator_statistics()))

    # Test 3: Legacy compatibility
    results.append(("Legacy Compatibility", test_orchestrator_legacy_compatibility()))

    # Final summary
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    failed = sum(1 for _, result in results if not result)

    for name, result in results:
        status = "[OK]" if result else "[FAIL]"
        print(f"{status} {name}")

    print()
    print(f"Total Passed:  {passed}")
    print(f"Total Failed:  {failed}")
    print(f"Success Rate:  {passed / (passed + failed) * 100:.1f}%")
    print()

    if passed == len(results):
        print("[OK] ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print(f"[FAIL] {failed} test(s) failed")
        sys.exit(1)
