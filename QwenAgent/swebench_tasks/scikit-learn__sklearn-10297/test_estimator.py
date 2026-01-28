"""Test for scikit-learn/sklearn#10297: fit_transform returns wrong type.

Bug: TransformerMixin.fit_transform() returns self instead of transformed data.
Fix: Return self.fit(X, y).transform(X) from fit_transform().
SWECAS-400: API Usage & Deprecation
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from sklearn_local.estimator import StandardScaler, Pipeline


def test_fit_transform_returns_data():
    """fit_transform should return transformed data, not self."""
    scaler = StandardScaler()
    X = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = scaler.fit_transform(X)
    assert isinstance(result, list), \
        f"fit_transform should return list, got {type(result).__name__}"
    assert len(result) == 5, f"Expected 5 elements, got {len(result)}"
    # Mean should be ~0 after standardization
    mean_result = sum(result) / len(result)
    assert abs(mean_result) < 0.01, f"Mean should be ~0, got {mean_result}"
    print("  PASS: fit_transform returns transformed data")
    return True


def test_fit_then_transform():
    """Separate fit() + transform() should work."""
    scaler = StandardScaler()
    X = [10.0, 20.0, 30.0]
    scaler.fit(X)
    result = scaler.transform(X)
    assert isinstance(result, list)
    assert len(result) == 3
    print("  PASS: fit() + transform() works correctly")
    return True


def test_pipeline_fit_transform():
    """Pipeline.fit_transform should return final transformed data."""
    pipe = Pipeline([
        ("scaler", StandardScaler()),
    ])
    X = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = pipe.fit_transform(X)
    assert isinstance(result, list), \
        f"Pipeline should return list, got {type(result).__name__}"
    print("  PASS: Pipeline.fit_transform returns data")
    return True


if __name__ == '__main__':
    print("=== SWE-bench Task: scikit-learn__sklearn-10297 ===")
    print("fit_transform() returns wrong type\n")

    results = []
    print("Test 1: fit_transform returns data (not self)")
    results.append(test_fit_transform_returns_data())
    print("\nTest 2: Separate fit + transform")
    results.append(test_fit_then_transform())
    print("\nTest 3: Pipeline fit_transform")
    results.append(test_pipeline_fit_transform())

    passed = sum(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{len(results)} tests passed")
    if all(results): print("ALL TESTS PASSED!")
    else: print("SOME TESTS FAILED"); sys.exit(1)
