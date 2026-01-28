"""Simplified sklearn Estimator API for SWE-bench task.

Bug: Pipeline.fit_transform() calls fit() then transform() separately,
but doesn't pass fit() result to transform(). Some estimators need the
fitted state from fit() before transform() can work.
SWECAS-400: API Usage & Deprecation
"""


class BaseEstimator:
    """Base class for all estimators."""

    def get_params(self):
        return {}

    def set_params(self, **params):
        for key, value in params.items():
            setattr(self, key, value)
        return self


class TransformerMixin:
    """Mixin for transformers with fit_transform."""

    def fit_transform(self, X, y=None):
        """Fit and transform in one step.

        BUG: Calls fit() and transform() separately but does NOT
        return transform output. Returns self instead of transformed X.
        Should return self.fit(X, y).transform(X).
        """
        self.fit(X, y)
        # BUG: returns self instead of transform(X)
        return self


class StandardScaler(BaseEstimator, TransformerMixin):
    """Standardize features by removing mean and scaling to unit variance."""

    def __init__(self):
        self.mean_ = None
        self.scale_ = None

    def fit(self, X, y=None):
        self.mean_ = sum(X) / len(X)
        variance = sum((x - self.mean_) ** 2 for x in X) / len(X)
        self.scale_ = variance ** 0.5 if variance > 0 else 1.0
        return self

    def transform(self, X):
        if self.mean_ is None:
            raise RuntimeError("StandardScaler not fitted. Call fit() first.")
        return [(x - self.mean_) / self.scale_ for x in X]


class Pipeline:
    """Simplified pipeline of transforms."""

    def __init__(self, steps):
        self.steps = steps  # list of (name, estimator) tuples

    def fit_transform(self, X, y=None):
        result = X
        for name, estimator in self.steps:
            result = estimator.fit_transform(result, y)
        return result
