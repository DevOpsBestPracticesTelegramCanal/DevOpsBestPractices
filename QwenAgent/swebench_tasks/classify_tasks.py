#!/usr/bin/env python3
"""
Auto-classify SWE-bench tasks by SWECAS category.

Scans all swebench_tasks/*/ directories, reads task descriptions and source files,
classifies each by SWECAS category, and outputs a mapping JSON.

Usage:
    python swebench_tasks/classify_tasks.py
"""

import os
import sys
import json
import re

# Add parent dir to path so we can import core modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.swecas_classifier import SWECASClassifier


def classify_all_tasks():
    """Classify all SWE-bench tasks in swebench_tasks/ directories."""
    classifier = SWECASClassifier()
    tasks_dir = os.path.dirname(os.path.abspath(__file__))
    mapping = {}

    for task_name in sorted(os.listdir(tasks_dir)):
        task_path = os.path.join(tasks_dir, task_name)
        if not os.path.isdir(task_path) or task_name.startswith('.') or task_name == '__pycache__':
            continue

        # Read task description from test files, README, or source files
        description = _extract_task_description(task_path, task_name)
        file_content = _read_main_source(task_path)

        result = classifier.classify(description, file_content=file_content)
        mapping[task_name] = {
            "swecas_code": result["swecas_code"],
            "swecas_name": result["name"],
            "confidence": result["confidence"],
            "subcategory": result.get("subcategory"),
            "fix_hint": result.get("fix_hint", ""),
            "description_used": description[:200]
        }

        print(f"  {task_name}: SWECAS-{result['swecas_code']} "
              f"({result['name']}) confidence={result['confidence']:.2f}")

    # Save mapping
    output_path = os.path.join(tasks_dir, "swecas_task_mapping.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    print(f"\nClassified {len(mapping)} tasks -> {output_path}")
    return mapping


def _extract_task_description(task_path, task_name):
    """Extract description from test file docstrings, README, or task name."""
    # 1. Try test_*.py docstrings
    for fname in os.listdir(task_path):
        if fname.startswith('test_') and fname.endswith('.py'):
            fpath = os.path.join(task_path, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                # Extract module docstring
                match = re.search(r'^"""(.*?)"""', content, re.DOTALL)
                if match:
                    return match.group(1).strip()
                # Try single-line docstring
                match = re.search(r"^'''(.*?)'''", content, re.DOTALL)
                if match:
                    return match.group(1).strip()
                # Try function docstrings
                match = re.search(r'def test_\w+\(.*?\):\s*"""(.*?)"""', content, re.DOTALL)
                if match:
                    return match.group(1).strip()
            except Exception:
                pass

    # 2. Try README.md
    readme_path = os.path.join(task_path, "README.md")
    if os.path.exists(readme_path):
        try:
            with open(readme_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read(500).strip()
        except Exception:
            pass

    # 3. Fall back to task_name parsing
    # e.g., "pallets__flask-4045" -> "Flask issue 4045"
    parts = task_name.replace('__', '/').replace('-', ' issue ')
    return f"SWE-bench task: {parts}"


def _read_main_source(task_path):
    """Read the main source file to be fixed (in src/ directory or root .py files)."""
    # Look for src/**/*.py files first
    src_dir = os.path.join(task_path, "src")
    if os.path.isdir(src_dir):
        for root, dirs, files in os.walk(src_dir):
            # Skip __pycache__
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for fname in files:
                if fname.endswith('.py') and not fname.startswith('__'):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                        if len(content) > 50:  # Skip near-empty files
                            return content[:5000]  # Cap at 5000 chars
                    except Exception:
                        pass

    # Look for *_local/**/*.py (like requests_local/)
    for item in os.listdir(task_path):
        item_path = os.path.join(task_path, item)
        if os.path.isdir(item_path) and not item.startswith('.') and item != '__pycache__':
            for fname in os.listdir(item_path):
                if fname.endswith('.py') and not fname.startswith('__'):
                    fpath = os.path.join(item_path, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                        if len(content) > 50:
                            return content[:5000]
                    except Exception:
                        pass

    return None


if __name__ == "__main__":
    print("=" * 60)
    print("SWECAS Task Classifier")
    print("=" * 60)
    print()
    mapping = classify_all_tasks()
    print()
    print("=" * 60)
    if mapping:
        print(f"Summary: {len(mapping)} tasks classified")
        codes = {}
        for info in mapping.values():
            code = info["swecas_code"]
            codes[code] = codes.get(code, 0) + 1
        for code in sorted(codes):
            print(f"  SWECAS-{code}: {codes[code]} task(s)")
    else:
        print("No tasks found to classify")
    print("=" * 60)
