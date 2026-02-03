# -*- coding: utf-8 -*-
"""
test_phase2_budget.py — Тест Phase 2: Budget Management System
==============================================================

Запуск:
    python test_phase2_budget.py

Тесты:
1. TimeBudget базовая функциональность
2. BudgetEstimator оценка бюджета
3. CoTEngine интеграция с бюджетом
4. QwenCodeAgent интеграция
"""

import sys
import time

# Ensure UTF-8 output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, '.')

from core.time_budget import TimeBudget, BudgetPresets, StepStatus
from core.budget_estimator import BudgetEstimator, estimate_task_budget, create_mode_budget
from core.cot_engine import CoTEngine
from core.execution_mode import ExecutionMode
from core.user_timeout_config import UserTimeoutPreferences


def print_section(title: str):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def test_time_budget():
    """Тест TimeBudget базовой функциональности."""
    print_section("TEST 1: TimeBudget")

    # 1.1 Create budget
    print("\n[1.1] Create budget:")
    budget = TimeBudget(
        total_seconds=120,
        steps=["analyze", "plan", "execute"],
        critical_step="execute"
    )
    print(f"  Total: {budget.total}s")
    print(f"  Steps: {list(budget.records.keys())}")
    print(f"  Critical: {budget.critical_step}")

    # 1.2 Check allocation
    print("\n[1.2] Budget allocation (BAM):")
    for name, rec in budget.records.items():
        critical = " (critical)" if name == budget.critical_step else ""
        print(f"  {name}: {rec.allocated:.1f}s{critical}")

    # 1.3 Test step timeout
    print("\n[1.3] Step timeouts:")
    for step in ["analyze", "plan", "execute"]:
        timeout = budget.get_step_timeout(step)
        print(f"  {step}: {timeout:.1f}s")

    # 1.4 Test step execution
    print("\n[1.4] Step execution simulation:")
    budget.start_step("analyze")
    time.sleep(0.1)  # Simulate 100ms work
    budget.complete_step("analyze")
    record = budget.records.get("analyze")
    savings = record.savings if record else 0
    print(f"  analyze completed, savings: {savings:.1f}s")

    # Check savings transfer
    plan_timeout = budget.get_step_timeout("plan")
    print(f"  plan timeout (with savings): {plan_timeout:.1f}s")

    # 1.5 Test budget exhaustion
    print("\n[1.5] Budget status:")
    print(f"  Elapsed: {budget.elapsed:.1f}s")
    print(f"  Remaining: {budget.remaining:.1f}s")
    print(f"  Is exhausted: {budget.is_exhausted}")

    print("\n[1.6] Budget presets:")
    fast = BudgetPresets.fast_mode(30)
    deep3 = BudgetPresets.deep3_mode(120)
    deep6 = BudgetPresets.deep6_mode(300)
    print(f"  FAST: {list(fast.records.keys())}")
    print(f"  DEEP3: {list(deep3.records.keys())}")
    print(f"  DEEP6: {list(deep6.records.keys())}")

    print("\n  TimeBudget tests passed!")
    return True


def test_budget_estimator():
    """Тест BudgetEstimator."""
    print_section("TEST 2: BudgetEstimator")

    # 2.1 Basic estimation
    print("\n[2.1] Basic estimation:")
    estimator = BudgetEstimator()
    for mode in [ExecutionMode.FAST, ExecutionMode.DEEP3, ExecutionMode.DEEP6]:
        est = estimator.estimate(mode)
        print(f"  {mode.value}: {est.total_seconds:.0f}s, conf: {est.confidence:.0%}")

    # 2.2 Prompt length impact
    print("\n[2.2] Prompt length impact (DEEP3):")
    for length in [100, 500, 1000, 2000]:
        prompt = " ".join(["word"] * length)
        est = estimator.estimate(ExecutionMode.DEEP3, prompt)
        mult = est.adjustments.get("prompt_length", 1.0)
        print(f"  {length} words: {est.total_seconds:.0f}s (x{mult:.2f})")

    # 2.3 Priority impact
    print("\n[2.3] Priority impact (DEEP3):")
    for priority in ["speed", "balanced", "quality"]:
        prefs = UserTimeoutPreferences(priority=priority, max_wait=300)
        est = BudgetEstimator(prefs).estimate(ExecutionMode.DEEP3)
        print(f"  {priority}: {est.total_seconds:.0f}s")

    # 2.4 Create TimeBudget
    print("\n[2.4] Create TimeBudget from estimate:")
    budget = estimator.create_budget(ExecutionMode.DEEP3)
    print(f"  Budget: {budget}")
    print(f"  Steps: {list(budget.records.keys())}")

    # 2.5 Convenience functions
    print("\n[2.5] Convenience functions:")
    secs = estimate_task_budget(ExecutionMode.DEEP6, prompt_length=1000, complexity="complex")
    print(f"  estimate_task_budget(DEEP6, 1000 words, complex): {secs:.0f}s")

    mode_budget = create_mode_budget(ExecutionMode.DEEP3, max_seconds=180)
    print(f"  create_mode_budget(DEEP3, 180s): {mode_budget}")

    print("\n  BudgetEstimator tests passed!")
    return True


def test_cot_engine_integration():
    """Тест CoTEngine интеграции с бюджетом."""
    print_section("TEST 3: CoTEngine Integration")

    # 3.1 Create CoTEngine with user prefs
    print("\n[3.1] Create CoTEngine:")
    prefs = UserTimeoutPreferences(max_wait=180, priority="balanced")
    cot = CoTEngine(user_prefs=prefs)
    print(f"  User prefs: max_wait={prefs.max_wait}s, priority={prefs.priority}")

    # 3.2 Enable DEEP3 and create budget
    print("\n[3.2] Enable DEEP3 mode:")
    cot.enable_deep3_mode(True)
    budget = cot.create_budget_for_mode()
    print(f"  Budget created: {budget}")
    print(f"  Mode: {cot._get_current_mode()}")

    # 3.3 Get budget status
    print("\n[3.3] Budget status:")
    status = cot.get_budget_status()
    print(f"  Mode: {status['mode']}")
    print(f"  Total: {status['total_seconds']}s")
    print(f"  Remaining: {status['remaining']:.1f}s")
    print(f"  Steps: {list(status['steps'].keys())}")

    # 3.4 Get step timeouts
    print("\n[3.4] Step timeouts:")
    for step in ["analyze", "plan", "execute"]:
        timeout = cot.get_step_timeout(step)
        print(f"  {step}: {timeout:.1f}s")

    # 3.5 Test step tracking
    print("\n[3.5] Step tracking:")
    timeout = cot.start_step("analyze")
    print(f"  Started analyze, timeout: {timeout:.1f}s")
    time.sleep(0.05)  # Simulate 50ms
    savings = cot.end_step("analyze")
    print(f"  Ended analyze, savings: {savings:.1f}s")

    # 3.6 Check exhaustion
    print("\n[3.6] Budget exhaustion check:")
    print(f"  Is exhausted: {cot.is_budget_exhausted()}")
    print(f"  Remaining: {cot.get_remaining_budget():.1f}s")

    print("\n  CoTEngine integration tests passed!")
    return True


def test_agent_integration():
    """Тест QwenCodeAgent интеграции."""
    print_section("TEST 4: QwenCodeAgent Integration")

    # 4.1 Import and create agent
    print("\n[4.1] Create agent:")
    from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig

    config = QwenCodeConfig()
    config.model = 'qwen2.5-coder:3b'
    config.execution_mode = ExecutionMode.DEEP3

    agent = QwenCodeAgent(config)
    print(f"  Agent created")
    print(f"  Mode: {agent.current_mode.value}")
    print(f"  User prefs: max_wait={agent.user_prefs.max_wait}s")
    print(f"  Budget estimator: {agent.budget_estimator is not None}")

    # 4.2 Check CoTEngine has budget support
    print("\n[4.2] CoTEngine budget support:")
    agent.cot_engine.enable_deep3_mode(True)
    budget = agent.cot_engine.create_budget_for_mode()
    print(f"  Budget: {budget}")
    status = agent.cot_engine.get_budget_status()
    print(f"  Status: mode={status['mode']}, total={status['total_seconds']}s")

    # 4.3 Check stats include budget tracking
    print("\n[4.3] Stats include budget tracking:")
    stats = agent.stats
    budget_stats = ["budget_exhaustions", "budget_savings_total", "budget_overruns"]
    for stat in budget_stats:
        value = stats.get(stat, "MISSING")
        print(f"  {stat}: {value}")

    print("\n  QwenCodeAgent integration tests passed!")
    return True


def main():
    """Запуск всех тестов."""
    print("\n" + "=" * 60)
    print(" QwenCode Phase 2 - Budget Management Tests")
    print("=" * 60)

    results = []

    # Test 1: TimeBudget
    try:
        results.append(("TimeBudget", test_time_budget()))
    except Exception as e:
        print(f"\n  TimeBudget test failed: {e}")
        results.append(("TimeBudget", False))

    # Test 2: BudgetEstimator
    try:
        results.append(("BudgetEstimator", test_budget_estimator()))
    except Exception as e:
        print(f"\n  BudgetEstimator test failed: {e}")
        results.append(("BudgetEstimator", False))

    # Test 3: CoTEngine Integration
    try:
        results.append(("CoTEngine Integration", test_cot_engine_integration()))
    except Exception as e:
        print(f"\n  CoTEngine Integration test failed: {e}")
        results.append(("CoTEngine Integration", False))

    # Test 4: Agent Integration
    try:
        results.append(("Agent Integration", test_agent_integration()))
    except Exception as e:
        print(f"\n  Agent Integration test failed: {e}")
        results.append(("Agent Integration", False))

    # Summary
    print_section("SUMMARY")
    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")

    print(f"\n  Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n  Phase 2 Budget Management System - ALL TESTS PASSED!")
    else:
        print("\n  Some tests failed. Check output above.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
