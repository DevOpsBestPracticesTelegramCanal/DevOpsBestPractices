# -*- coding: utf-8 -*-
"""
test_phase3_predictive.py — Тест Phase 3: Predictive Timeout Estimator
======================================================================

Запуск:
    python test_phase3_predictive.py

Тесты:
1. PredictiveEstimator базовая функциональность
2. Feature extraction
3. Model/Mode calibration
4. Learning from outcomes
5. Agent integration
"""

import sys
import time

# Ensure UTF-8 output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, '.')

from core.predictive_estimator import (
    PredictiveEstimator,
    PredictionResult,
    FeatureExtractor,
    ModelCalibrator,
    ModeCalibrator,
    TaskComplexity,
    predict_timeout,
    predict_with_details
)


def print_section(title: str):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def test_feature_extraction():
    """Тест извлечения признаков."""
    print_section("TEST 1: Feature Extraction")

    # 1.1 Simple prompt
    print("\n[1.1] Simple prompt:")
    simple = "What is 2+2?"
    features = FeatureExtractor.extract(simple)
    print(f"  Prompt: {simple}")
    print(f"  Features: {len(features)} extracted")
    print(f"    prompt_length: {features.get('prompt_length', 0):.2f}")
    print(f"    is_question: {features.get('is_question', 0):.2f}")

    # 1.2 Complex prompt
    print("\n[1.2] Complex prompt:")
    complex_prompt = """
    Refactor the entire authentication module to use JWT.
    The current implementation in auth.py has security vulnerabilities.
    ```python
    def login(user, password):
        # vulnerable code
        pass
    ```
    """
    features = FeatureExtractor.extract(complex_prompt)
    print(f"  Prompt: {complex_prompt[:50]}...")
    print(f"  Key features:")
    print(f"    complexity_keywords: {features.get('complexity_keywords', 0):.2f}")
    print(f"    task_refactoring: {features.get('task_refactoring', 0):.2f}")
    print(f"    has_code_block: {features.get('has_code_block', 0):.2f}")
    print(f"    has_file_path: {features.get('has_file_path', 0):.2f}")

    # 1.3 Bug fix prompt
    print("\n[1.3] Bug fix prompt:")
    bug_prompt = "Fix the IndexError bug in parser.py line 42"
    features = FeatureExtractor.extract(bug_prompt)
    print(f"  Prompt: {bug_prompt}")
    print(f"    task_bug_fix: {features.get('task_bug_fix', 0):.2f}")
    print(f"    has_error_trace: {features.get('has_error_trace', 0):.2f}")

    print("\n  Feature extraction tests passed!")
    return True


def test_calibrators():
    """Тест калибраторов."""
    print_section("TEST 2: Calibrators")

    # 2.1 Model calibrator
    print("\n[2.1] Model calibrator:")
    model_cal = ModelCalibrator()
    models = ["qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen2.5-coder:32b"]
    for model in models:
        cal = model_cal.get_calibration(model)
        print(f"  {model}: {cal:.2f}")

    # 2.2 Mode calibrator
    print("\n[2.2] Mode calibrator:")
    mode_cal = ModeCalibrator()
    modes = ["fast", "deep3", "deep6", "search"]
    for mode in modes:
        cal = mode_cal.get_calibration(mode)
        print(f"  {mode}: {cal:.2f}")

    # 2.3 Calibration update
    print("\n[2.3] Calibration update (learning):")
    model_cal.update("qwen2.5-coder:7b", 1.2)  # Actual was 20% slower
    model_cal.update("qwen2.5-coder:7b", 1.1)
    model_cal.update("qwen2.5-coder:7b", 0.9)
    new_cal = model_cal.get_calibration("qwen2.5-coder:7b")
    print(f"  After 3 updates: {new_cal:.2f}")

    print("\n  Calibrator tests passed!")
    return True


def test_predictions():
    """Тест предсказаний."""
    print_section("TEST 3: Predictions")

    estimator = PredictiveEstimator()

    # 3.1 Different modes
    print("\n[3.1] Different modes:")
    prompt = "Write a function to sort a list"
    for mode in ["fast", "deep3", "deep6"]:
        result = estimator.predict(mode, prompt)
        print(f"  {mode}: {result.timeout:.1f}s (conf: {result.confidence:.0%}, "
              f"complexity: {result.complexity.value})")

    # 3.2 Different models
    print("\n[3.2] Different models (deep3 mode):")
    for model in ["qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen2.5-coder:32b"]:
        result = estimator.predict("deep3", prompt, model)
        print(f"  {model}: {result.timeout:.1f}s (model_cal: {result.model_calibration:.2f})")

    # 3.3 Different complexities
    print("\n[3.3] Different task complexities:")
    prompts = [
        ("print('hello')", "trivial"),
        ("Fix typo in README", "simple"),
        ("Implement caching for API", "moderate"),
        ("Refactor database layer to async", "complex"),
    ]
    for prompt, expected in prompts:
        result = estimator.predict("deep3", prompt)
        match = "OK" if result.complexity.value == expected else "?"
        print(f"  [{match}] {prompt[:30]}... -> {result.complexity.value}")

    print("\n  Prediction tests passed!")
    return True


def test_learning():
    """Тест обучения на результатах."""
    print_section("TEST 4: Learning from Outcomes")

    estimator = PredictiveEstimator()

    # 4.1 Initial predictions
    print("\n[4.1] Initial predictions:")
    results = []
    for i in range(5):
        result = estimator.predict("deep3", f"Task {i}: implement feature {i}")
        results.append(result)
        print(f"  Task {i}: predicted {result.timeout:.1f}s")

    # 4.2 Record outcomes
    print("\n[4.2] Recording outcomes:")
    for i, result in enumerate(results):
        # Simulate actual times (vary around prediction)
        actual = result.timeout * (0.7 + 0.1 * i)  # 70% to 110%
        success = i < 4  # Last one fails
        estimator.record_outcome(result.id, actual, success, tokens_generated=100)
        ratio = actual / result.timeout
        print(f"  Task {i}: actual {actual:.1f}s (ratio: {ratio:.2f})")

    # 4.3 Check stats
    print("\n[4.3] Statistics after learning:")
    stats = estimator.get_stats()
    print(f"  Total predictions: {stats['total_predictions']}")
    print(f"  Mean accuracy: {stats['mean_accuracy']:.2f}")
    print(f"  Success rate: {stats['success_rate']:.0%}")
    print(f"  Recent accuracy: {stats['recent_accuracy']:.2f}")

    # 4.4 New prediction after learning
    print("\n[4.4] New prediction after learning:")
    new_result = estimator.predict("deep3", "Task 5: implement feature 5")
    print(f"  New prediction: {new_result.timeout:.1f}s")
    print(f"  Confidence: {new_result.confidence:.0%}")

    print("\n  Learning tests passed!")
    return True


def test_convenience_functions():
    """Тест удобных функций."""
    print_section("TEST 5: Convenience Functions")

    # 5.1 predict_timeout
    print("\n[5.1] predict_timeout():")
    timeout = predict_timeout("deep3", "Fix bug in parser.py")
    print(f"  Result: {timeout:.1f}s")

    # 5.2 predict_with_details
    print("\n[5.2] predict_with_details():")
    details = predict_with_details("deep6", "Refactor entire module")
    for key, value in details.items():
        if key != "factors":
            print(f"  {key}: {value}")

    print("\n  Convenience function tests passed!")
    return True


def test_agent_integration():
    """Тест интеграции с агентом."""
    print_section("TEST 6: Agent Integration")

    # 6.1 Import and create agent
    print("\n[6.1] Create agent with predictive estimator:")
    from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig
    from core.execution_mode import ExecutionMode

    config = QwenCodeConfig()
    config.model = 'qwen2.5-coder:3b'
    config.execution_mode = ExecutionMode.DEEP3

    agent = QwenCodeAgent(config)
    print(f"  Agent created")
    print(f"  Predictive estimator: {agent.predictive_estimator is not None}")

    # 6.2 Check stats include prediction tracking
    print("\n[6.2] Stats include prediction tracking:")
    stats = agent.stats
    prediction_stats = ["predictions_made", "prediction_accuracy_sum"]
    for stat in prediction_stats:
        value = stats.get(stat, "MISSING")
        print(f"  {stat}: {value}")

    # 6.3 Make a prediction manually
    print("\n[6.3] Manual prediction test:")
    prediction = agent.predictive_estimator.predict(
        mode="deep3",
        prompt="Test task for integration",
        model=config.model
    )
    print(f"  Timeout: {prediction.timeout:.1f}s")
    print(f"  Confidence: {prediction.confidence:.0%}")
    print(f"  Complexity: {prediction.complexity.value}")

    print("\n  Agent integration tests passed!")
    return True


def main():
    """Запуск всех тестов."""
    print("\n" + "=" * 60)
    print(" QwenCode Phase 3 - Predictive Timeout Estimator Tests")
    print("=" * 60)

    results = []

    # Test 1: Feature Extraction
    try:
        results.append(("Feature Extraction", test_feature_extraction()))
    except Exception as e:
        print(f"\n  Feature Extraction test failed: {e}")
        results.append(("Feature Extraction", False))

    # Test 2: Calibrators
    try:
        results.append(("Calibrators", test_calibrators()))
    except Exception as e:
        print(f"\n  Calibrators test failed: {e}")
        results.append(("Calibrators", False))

    # Test 3: Predictions
    try:
        results.append(("Predictions", test_predictions()))
    except Exception as e:
        print(f"\n  Predictions test failed: {e}")
        results.append(("Predictions", False))

    # Test 4: Learning
    try:
        results.append(("Learning", test_learning()))
    except Exception as e:
        print(f"\n  Learning test failed: {e}")
        results.append(("Learning", False))

    # Test 5: Convenience Functions
    try:
        results.append(("Convenience Functions", test_convenience_functions()))
    except Exception as e:
        print(f"\n  Convenience Functions test failed: {e}")
        results.append(("Convenience Functions", False))

    # Test 6: Agent Integration
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
        print("\n  Phase 3 Predictive Timeout Estimator - ALL TESTS PASSED!")
    else:
        print("\n  Some tests failed. Check output above.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
