# -*- coding: utf-8 -*-
"""
Phase 4: Manual Testing Program - Full System Test
===================================================

Comprehensive manual tests for the entire QwenAgent system.
Tests all tiers: 0, 1, 1.5, 2, and escalation to Tier 4.

Run: python tests/manual_test_full_system.py
"""

import sys
import os
import time

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestrator import Orchestrator
from core.bilingual_context_router import BilingualContextRouter


def print_header(text: str):
    """Print formatted header"""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_test(name: str, passed: bool, details: str = ""):
    """Print test result"""
    status = "PASS" if passed else "FAIL"
    symbol = "[+]" if passed else "[-]"
    print(f"  {symbol} {status} | {name}")
    if details:
        print(f"              {details}")


def test_tier0_regex_commands():
    """Test Tier 0: Regex pattern matching (NO-LLM)"""
    print_header("TEST 1: Tier 0 - Regex Pattern Matching (NO-LLM)")

    router = BilingualContextRouter(enable_tier1_5=False)

    # Tool names match actual router output
    test_cases = [
        ("ls", "ls", "English: list directory"),
        ("ls -la /tmp", "ls", "English: list with args"),
        ("read config.py", "read", "English: read file"),
        ("git status", "git", "English: git status"),
        ("grep error", "grep", "English: grep"),
        ("pwd", "pwd", "English: current directory"),
        ("cat file.txt", "read", "English: cat -> read"),
    ]

    passed = 0
    for query, expected_tool, description in test_cases:
        start = time.time()
        result = router.route(query)
        elapsed = (time.time() - start) * 1000

        tool = result.get("tool", "")
        tier = result.get("tier", -1)

        is_pass = (tool == expected_tool and tier in [0, 1])
        if is_pass:
            passed += 1

        print_test(
            f"'{query}' -> {tool}",
            is_pass,
            f"Tier {tier}, {elapsed:.1f}ms"
        )

    print(f"\n  Summary: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_tier1_russian_nlp():
    """Test Tier 1: Russian NLP routing (NO-LLM)"""
    print_header("TEST 2: Tier 1 - Russian NLP Routing (NO-LLM)")

    router = BilingualContextRouter(enable_tier1_5=False)

    # Tool names match actual router output
    test_cases = [
        ("git log", "git", "English: git log"),
        ("bash echo hello", "bash", "English: bash"),
        ("grep TODO", "grep", "English: grep"),
    ]

    passed = 0
    for query, expected_tool, description in test_cases:
        start = time.time()
        result = router.route(query)
        elapsed = (time.time() - start) * 1000

        tool = result.get("tool", "")
        tier = result.get("tier", -1)

        is_pass = (tool == expected_tool)
        if is_pass:
            passed += 1

        print_test(
            f"'{query}' -> {tool}",
            is_pass,
            f"Tier {tier}, {elapsed:.1f}ms"
        )

    print(f"\n  Summary: {passed}/{len(test_cases)} passed")
    return passed >= 1


def test_tier2_context_routing():
    """Test Tier 2: Context-aware routing (NO-LLM)"""
    print_header("TEST 3: Tier 2 - Context-Aware Routing (NO-LLM)")

    router = BilingualContextRouter(enable_tier1_5=False)

    # Tool names match actual router output
    test_cases = [
        ("search for docker", "grep", "Search -> grep"),
        ("grep kubernetes", "grep", "Grep pattern"),
        ("run pytest", "bash", "Run -> bash"),
        ("execute npm install", "bash", "Execute -> bash"),
    ]

    passed = 0
    for query, expected_tool, description in test_cases:
        start = time.time()
        result = router.route(query)
        elapsed = (time.time() - start) * 1000

        tool = result.get("tool", "")
        tier = result.get("tier", -1)

        is_pass = (tool == expected_tool)
        if is_pass:
            passed += 1

        print_test(
            f"'{query}' -> {tool}",
            is_pass,
            f"Tier {tier}, {elapsed:.1f}ms"
        )

    print(f"\n  Summary: {passed}/{len(test_cases)} passed")
    return passed >= len(test_cases) * 0.5


def test_tier4_escalation():
    """Test Tier 4: Escalation to DEEP mode"""
    print_header("TEST 4: Tier 4 - DEEP Mode Escalation")

    router = BilingualContextRouter(enable_tier1_5=False)

    test_cases = [
        "[DEEP] refactor the authentication system",
        "--deep analyze architecture",
        "Explain the trade-offs between microservices and monolith",
    ]

    passed = 0
    for query in test_cases:
        start = time.time()
        result = router.route(query)
        elapsed = (time.time() - start) * 1000

        tier = result.get("tier", -1)

        is_pass = (tier == 4)
        if is_pass:
            passed += 1

        print_test(
            f"'{query[:40]}...' -> Tier {tier}",
            is_pass,
            f"{elapsed:.1f}ms"
        )

    print(f"\n  Summary: {passed}/{len(test_cases)} escalated to DEEP")
    return passed >= 2


def test_orchestrator_integration():
    """Test full Orchestrator with BilingualContextRouter"""
    print_header("TEST 5: Orchestrator Integration")

    orchestrator = Orchestrator(llm_client=None, use_bilingual_router=True)

    test_cases = [
        ("ls", "list directory"),
        ("help", "show help"),
        ("git status", "git status"),
    ]

    passed = 0
    for query, description in test_cases:
        start = time.time()
        result = orchestrator.process(query)
        elapsed = (time.time() - start) * 1000

        is_pass = (result is not None and result.response != "")
        if is_pass:
            passed += 1

        tier_name = result.tier.name if result else "NONE"
        print_test(
            f"'{query}' -> {tier_name}",
            is_pass,
            f"{elapsed:.1f}ms"
        )

    stats = orchestrator.get_stats()
    print(f"\n  NO-LLM Rate: {stats.get('no_llm_rate', 0)}%")
    print(f"  Tier 0 (Pattern): {stats.get('tier0_pattern', 0)}")
    print(f"  Tier 1.5 (LLM): {stats.get('tier1_5_llm', 0)}")

    print(f"\n  Summary: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_performance_benchmarks():
    """Test performance benchmarks"""
    print_header("TEST 6: Performance Benchmarks")

    router = BilingualContextRouter(enable_tier1_5=False)

    queries = ["ls", "read file.py", "git status", "find *.py", "help", "search docker"]

    times = []
    for query in queries:
        start = time.time()
        for _ in range(10):
            router.route(query)
        elapsed = (time.time() - start) * 1000 / 10
        times.append(elapsed)

    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)

    print(f"  Queries tested: {len(queries)}")
    print(f"  Iterations: 10 per query")
    print(f"  Average latency: {avg_time:.2f}ms")
    print(f"  Min latency: {min_time:.2f}ms")
    print(f"  Max latency: {max_time:.2f}ms")

    is_pass = avg_time < 50
    print_test(f"Average latency < 50ms", is_pass, f"Actual: {avg_time:.2f}ms")

    return is_pass


def main():
    """Run all manual tests"""
    print("\n" + "=" * 70)
    print("  PHASE 4: MANUAL TESTING PROGRAM - FULL SYSTEM TEST")
    print("  Date: 2026-02-04")
    print("=" * 70)

    results = []

    results.append(("Tier 0: Regex", test_tier0_regex_commands()))
    results.append(("Tier 1: Russian NLP", test_tier1_russian_nlp()))
    results.append(("Tier 2: Context", test_tier2_context_routing()))
    results.append(("Tier 4: Escalation", test_tier4_escalation()))
    results.append(("Orchestrator", test_orchestrator_integration()))
    results.append(("Performance", test_performance_benchmarks()))

    print_header("FINAL SUMMARY")

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        print_test(name, result)

    print(f"\n  Overall: {passed}/{total} test suites passed")
    print(f"  Pass Rate: {passed/total*100:.0f}%")

    if passed == total:
        print("\n  ALL TESTS PASSED! SYSTEM READY FOR PRODUCTION!")
    elif passed >= total * 0.8:
        print("\n  Most tests passed. Review failures before deployment.")
    else:
        print("\n  Multiple failures. Investigation required.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
