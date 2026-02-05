# -*- coding: utf-8 -*-
"""
Pattern Audit Script for QwenCode Query Crystallizer
=====================================================

This script provides:
1. Pattern inventory - list all patterns by TaskType
2. Pattern testing - verify patterns match expected inputs
3. Conflict detection - find ambiguous phrases that trigger multiple patterns
4. Coverage report - show what's covered and what's missing

Usage:
    python tests/audit_patterns.py
    python tests/audit_patterns.py --verbose
    python tests/audit_patterns.py --conflicts-only

Author: QwenCode Team
Version: 1.0.0
"""

import sys
import os
import re
import argparse
from typing import Dict, List, Tuple, Set

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.query_crystallizer import (
    HybridCrystallizer,
    TaskType,
    CompiledPatterns,
    translate_search_to_grep,
    get_compiled_patterns,
)
from core.pattern_router import PatternRouter, get_router


def print_header(title: str, char: str = "="):
    """Print formatted header."""
    print(f"\n{char * 60}")
    print(f"  {title}")
    print(f"{char * 60}")


def audit_task_patterns():
    """List all TaskType patterns."""
    print_header("TASK TYPE PATTERNS INVENTORY")

    patterns = CompiledPatterns.TASK_PATTERNS_RAW
    total = 0

    for task_type, pattern_list in patterns.items():
        print(f"\n[{task_type.value.upper()}] ({len(pattern_list)} patterns)")
        for i, p in enumerate(pattern_list, 1):
            # Highlight negative lookahead
            if "(?!" in p:
                print(f"  {i}. {p}  [PROTECTED]")
            else:
                print(f"  {i}. {p}")
        total += len(pattern_list)

    print(f"\n  TOTAL: {total} patterns across {len(patterns)} task types")


def audit_search_contexts():
    """List all search context patterns."""
    print_header("SEARCH CONTEXT PATTERNS (GREP)")

    contexts = CompiledPatterns.SEARCH_CONTEXTS_RAW
    print(f"\n{'Keywords':<40} | {'Grep Pattern':<30} | Description")
    print("-" * 100)

    for keywords, pattern, desc in contexts:
        kw_str = ", ".join(keywords[:3])
        if len(keywords) > 3:
            kw_str += "..."
        print(f"{kw_str:<40} | {pattern:<30} | {desc}")

    print(f"\n  TOTAL: {len(contexts)} search contexts")


def audit_router_patterns():
    """List all direct router patterns."""
    print_header("PATTERN ROUTER (FAST PATH)")

    router = get_router()

    print(f"\n{'Tool':<10} | Pattern")
    print("-" * 70)

    tool_counts = {}
    for pattern, tool, _ in router.patterns:
        tool_name = tool if isinstance(tool, str) else tool.__name__
        print(f"{tool_name:<10} | {pattern.pattern[:55]}")
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

    print(f"\n  TOTAL: {len(router.patterns)} router patterns")
    print("  By tool:")
    for tool, count in sorted(tool_counts.items()):
        print(f"    {tool}: {count}")


def test_task_recognition():
    """Test TaskType recognition with known inputs."""
    print_header("TASK RECOGNITION TESTS")

    crystallizer = HybridCrystallizer()

    # Test cases: (query, expected_type)
    tests = [
        # CREATE
        ("напиши функцию сортировки", TaskType.CREATE),
        ("создай класс User", TaskType.CREATE),
        ("write a function to parse JSON", TaskType.CREATE),

        # EDIT
        ("добавь метод validate в класс User", TaskType.EDIT),
        ("измени функцию main", TaskType.EDIT),
        ("add method to class Config", TaskType.EDIT),

        # FIX - should override CREATE/SEARCH
        ("исправь ошибку в функции", TaskType.FIX),
        ("fix the bug in login", TaskType.FIX),
        ("найди и исправь баг", TaskType.FIX),  # Should be FIX, not SEARCH!
        ("создай баг-репорт", TaskType.FIX),    # Should be FIX, not CREATE!
        ("напиши почему падает код", TaskType.FIX),  # Should be FIX!

        # SEARCH
        ("найди все классы", TaskType.SEARCH),
        ("покажи структуру модуля", TaskType.SEARCH),
        ("find all async functions", TaskType.SEARCH),

        # REFACTOR
        ("отрефактори этот код", TaskType.REFACTOR),
        ("refactor the module", TaskType.REFACTOR),

        # OPTIMIZE
        ("оптимизируй запрос", TaskType.OPTIMIZE),
        ("ускорь этот код", TaskType.OPTIMIZE),
    ]

    passed = 0
    failed = 0

    print(f"\n{'Query':<45} | {'Expected':<10} | {'Got':<10} | Status")
    print("-" * 85)

    for query, expected in tests:
        result = crystallizer.crystallize(query)
        status = "[OK]" if result.task_type == expected else "[FAIL]"

        if result.task_type == expected:
            passed += 1
        else:
            failed += 1

        print(f"{query[:44]:<45} | {expected.value:<10} | {result.task_type.value:<10} | {status}")

    print(f"\n  RESULTS: {passed}/{len(tests)} passed ({100*passed/len(tests):.1f}%)")

    if failed > 0:
        print(f"  WARNING: {failed} tests failed!")

    return failed == 0


def test_search_translation():
    """Test search query to grep translation."""
    print_header("SEARCH TRANSLATION TESTS")

    tests = [
        ("найди все классы", r"class \w+:"),
        ("покажи функции async", r"async def"),
        ("найди TODO комментарии", r"TODO|FIXME"),
        ("покажи импорты", r"import"),
        ("найди все docstrings", r'^"""'),
    ]

    passed = 0

    print(f"\n{'Query':<35} | {'Expected Pattern':<25} | {'Got Pattern':<25} | Status")
    print("-" * 100)

    for query, expected_pattern in tests:
        grep = translate_search_to_grep(query)

        if grep:
            got_pattern = grep.get("pattern", "None")
            # Check if expected pattern is contained
            match = expected_pattern.lower() in got_pattern.lower() or got_pattern.lower() in expected_pattern.lower()
        else:
            got_pattern = "None"
            match = False

        status = "[OK]" if match else "[WARN]"
        if match:
            passed += 1

        print(f"{query:<35} | {expected_pattern:<25} | {got_pattern[:24]:<25} | {status}")

    print(f"\n  RESULTS: {passed}/{len(tests)} matched")


def detect_conflicts():
    """Detect phrases that trigger multiple TaskTypes."""
    print_header("CONFLICT DETECTION")

    # Ambiguous test phrases
    probes = [
        "найди и исправь",
        "создай баг-репорт",
        "напиши почему падает",
        "добавь и почини",
        "исправь и добавь метод",
        "создай поиск",
        "найди ошибку",
        "измени и удали баг",
    ]

    patterns = CompiledPatterns.TASK_PATTERNS_RAW
    conflicts_found = 0

    print(f"\nChecking {len(probes)} potentially ambiguous phrases...\n")

    for probe in probes:
        matches = []

        for task_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                try:
                    if re.search(pattern, probe, re.IGNORECASE):
                        matches.append(task_type.value)
                        break  # One match per type is enough
                except re.error:
                    pass

        if len(matches) > 1:
            conflicts_found += 1
            print(f"  [CONFLICT] '{probe}'")
            print(f"             Triggers: {', '.join(matches)}")
        elif len(matches) == 1:
            print(f"  [OK] '{probe}' -> {matches[0]}")
        else:
            print(f"  [NONE] '{probe}' -> no match")

    print(f"\n  CONFLICTS: {conflicts_found}/{len(probes)} ambiguous phrases")

    if conflicts_found == 0:
        print("  All clear! No ambiguous patterns detected.")
    else:
        print("  Consider adjusting patterns with Negative Lookahead.")

    return conflicts_found == 0


def detect_router_crystallizer_overlap():
    """Check if Router and Crystallizer agree."""
    print_header("ROUTER vs CRYSTALLIZER OVERLAP")

    router = get_router()
    crystallizer = HybridCrystallizer()

    # Phrases that should go to Router (fast path)
    router_probes = [
        "прочитай файл test.py",
        "cat config.json",
        "ls core/",
        "pwd",
        "git status",
        "grep class User",
        "найди класс MyClass",
    ]

    print(f"\nChecking Router priority for {len(router_probes)} commands...\n")

    for probe in router_probes:
        route = router.match(probe)  # Method is 'match', not 'route'
        crystal = crystallizer.crystallize(probe)

        if route:
            tool = route.get('tool', 'unknown') if isinstance(route, dict) else str(route)
            print(f"  [ROUTER] '{probe[:40]}'")
            print(f"           Tool: {tool}, TaskType: {crystal.task_type.value}")
            print(f"           (Router wins - OK)")
        else:
            print(f"  [LLM] '{probe[:40]}'")
            print(f"        TaskType: {crystal.task_type.value}")


def run_full_audit(verbose: bool = False, conflicts_only: bool = False):
    """Run complete audit."""
    print("\n" + "=" * 60)
    print("  QWENCODE PATTERN AUDIT REPORT")
    print("=" * 60)

    all_passed = True

    if not conflicts_only:
        # Inventory
        audit_task_patterns()
        audit_search_contexts()
        audit_router_patterns()

        # Tests
        if not test_task_recognition():
            all_passed = False

        test_search_translation()

    # Conflicts (always run)
    if not detect_conflicts():
        all_passed = False

    if not conflicts_only:
        detect_router_crystallizer_overlap()

    # Summary
    print_header("AUDIT SUMMARY", "=")

    if all_passed:
        print("\n  STATUS: ALL CHECKS PASSED")
        print("  No critical issues found.")
    else:
        print("\n  STATUS: ISSUES DETECTED")
        print("  Review the warnings above.")

    print("\n" + "=" * 60)

    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QwenCode Pattern Audit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--conflicts-only", "-c", action="store_true", help="Only check conflicts")

    args = parser.parse_args()

    success = run_full_audit(verbose=args.verbose, conflicts_only=args.conflicts_only)
    sys.exit(0 if success else 1)
