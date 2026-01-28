# Contributing to QwenAgent

## Adding a New SWE-bench Task

1. Create directory: `swebench_tasks/<repo>__<issue>/`
2. Add source code with the bug: `src/<package>/module.py`
3. Add test file: `test_<name>.py` with 3-5 tests
4. Add `__init__.py` in package directories

### Task Structure

```
swebench_tasks/<repo>__<issue>/
├── src/
│   └── <package>/
│       ├── __init__.py
│       └── module.py          # Source with bug (docstring describes the bug)
└── test_<name>.py             # Tests (module docstring: bug + fix + SWECAS code)
```

### Test File Template

```python
"""Test for <repo>/<issue>: <short description>.

Bug: <what's wrong>
Fix: <what should change>
SWECAS-<code>: <category name>
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from <package>.module import TargetClass

def test_bug_scenario():
    """The bug scenario — should pass after fix."""
    ...

def test_normal_behavior():
    """Normal behavior — should always pass."""
    ...

if __name__ == '__main__':
    print("=== SWE-bench Task: <repo>__<issue> ===")
    results = []
    results.append(test_normal_behavior())
    results.append(test_bug_scenario())
    passed = sum(results)
    print(f"Results: {passed}/{len(results)} tests passed")
```

### After Adding

```bash
# Classify the new task
python swebench_tasks/classify_tasks.py

# Run the test
python swebench_tasks/<repo>__<issue>/test_<name>.py

# Run full suite
python -m pytest tests/ -v
```

## Adding SWECAS Patterns

### Search Cache (`core/swecas_search_cache.json`)

Add patterns, fix_hints, or subcategories to existing categories:

```json
{
  "<category_code>": {
    "patterns": ["new pattern here"],
    "fix_hints": ["new hint here"],
    "subcategories": {
      "<subcode>": {
        "name": "Subcategory name",
        "patterns": ["..."],
        "fix_hints": ["..."]
      }
    },
    "swebench_refs": ["<repo>__<issue>"],
    "real_world_examples": [
      {"task": "<issue>", "before": "old code", "after": "fixed code"}
    ]
  }
}
```

### Classifier Keywords (`core/swecas_classifier.py`)

Add keywords to `CATEGORY_KEYWORDS`, regex patterns to `SPECIFIC_PATTERNS`, or fix templates to `FIX_TEMPLATES`.

## Running Tests

```bash
# All tests
python -m pytest tests/ -v

# Single test file
python -m pytest tests/test_regression.py -v

# SWE-bench task tests
make test-all

# Lint
make lint
```

## Code Style

- Type hints on all public methods
- Docstrings on all public classes and methods
- No external dependencies beyond requirements.txt
- All Python files must pass `python -m py_compile`
