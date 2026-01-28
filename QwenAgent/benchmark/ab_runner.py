#!/usr/bin/env python3
"""
A/B benchmark runner for QwenCode modes.

Compares FAST vs DEEP vs SWECAS+DEEP modes on SWE-bench tasks.
Outputs scores, timing, and markdown comparison report.

Usage:
    python benchmark/ab_runner.py
    python benchmark/ab_runner.py --modes fast deep
    python benchmark/ab_runner.py --task pallets__flask-4045
"""

import os
import sys
import json
import time
import subprocess
import argparse

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ABRunner:
    """A/B benchmark runner for comparing QwenCode execution modes."""

    MODES = ["fast", "deep", "swecas_deep"]

    def __init__(self, tasks_dir=None, results_dir=None):
        self.tasks_dir = tasks_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "swebench_tasks"
        )
        self.results_dir = results_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "results"
        )
        os.makedirs(self.results_dir, exist_ok=True)

    def _list_tasks(self):
        """List all SWE-bench task directories."""
        tasks = []
        if not os.path.isdir(self.tasks_dir):
            return tasks
        for name in sorted(os.listdir(self.tasks_dir)):
            task_path = os.path.join(self.tasks_dir, name)
            if (os.path.isdir(task_path)
                    and not name.startswith('.')
                    and name != '__pycache__'
                    and '__' in name):  # SWE-bench tasks have format repo__issue
                tasks.append(name)
        return tasks

    def _find_test_file(self, task_name):
        """Find the test file for a given task."""
        task_path = os.path.join(self.tasks_dir, task_name)
        for fname in os.listdir(task_path):
            if fname.startswith('test_') and fname.endswith('.py'):
                return os.path.join(task_path, fname)
        return None

    def run_task_tests(self, task_name):
        """Run tests for a task and return pass/fail counts."""
        test_file = self._find_test_file(task_name)
        if not test_file:
            return {"passed": 0, "total": 0, "error": "No test file found"}

        try:
            result = subprocess.run(
                [sys.executable, test_file],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.path.join(self.tasks_dir, task_name),
                encoding='utf-8',
                errors='replace'
            )

            output = result.stdout + result.stderr

            # Parse test results from output
            # Look for "X/Y tests passed" pattern
            import re
            match = re.search(r'(\d+)/(\d+)\s+tests?\s+passed', output)
            if match:
                passed = int(match.group(1))
                total = int(match.group(2))
            else:
                # Check for ALL TESTS PASSED
                if 'ALL TESTS PASSED' in output or 'All tests passed' in output:
                    # Count PASS lines
                    passed = output.count('PASS')
                    total = passed + output.count('FAIL')
                    if total == 0:
                        total = passed = 1  # At least 1 if all passed
                else:
                    passed = output.count('PASS')
                    total = passed + output.count('FAIL')

            return {
                "passed": passed,
                "total": max(total, 1),
                "return_code": result.returncode,
                "output": output[:2000]
            }
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": 1, "error": "Test timeout"}
        except Exception as e:
            return {"passed": 0, "total": 1, "error": str(e)}

    def run_task(self, task_name, mode="fast"):
        """
        Run a single SWE-bench task in specified mode, return result.

        Note: This runs the existing test file to check current state.
        Full A/B testing with QwenCodeAgent requires Ollama running.
        """
        start = time.time()

        # Run tests to see current pass rate
        test_result = self.run_task_tests(task_name)

        duration = time.time() - start

        # Load SWECAS classification if available
        swecas_code = None
        mapping_path = os.path.join(self.tasks_dir, "swecas_task_mapping.json")
        if os.path.exists(mapping_path):
            try:
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    mapping = json.load(f)
                if task_name in mapping:
                    swecas_code = mapping[task_name].get("swecas_code")
            except Exception:
                pass

        return {
            "task": task_name,
            "mode": mode,
            "passed": test_result.get("passed", 0),
            "total": test_result.get("total", 0),
            "duration_s": round(duration, 2),
            "swecas_code": swecas_code,
            "error": test_result.get("error"),
            "score": round(test_result.get("passed", 0) / max(test_result.get("total", 1), 1), 2)
        }

    def run_all(self, modes=None, tasks=None):
        """Run all tasks in all modes."""
        modes = modes or self.MODES
        tasks = tasks or self._list_tasks()
        results = []

        for task_name in tasks:
            print(f"\nTask: {task_name}")
            for mode in modes:
                print(f"  Mode: {mode}...", end=" ", flush=True)
                result = self.run_task(task_name, mode)
                results.append(result)
                score = result["score"]
                print(f"score={score:.2f} ({result['passed']}/{result['total']}) "
                      f"in {result['duration_s']}s")

        return results

    def generate_report(self, results):
        """Generate markdown comparison report."""
        lines = [
            "# A/B Benchmark Report",
            "",
            f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Tasks:** {len(set(r['task'] for r in results))}",
            f"**Modes:** {', '.join(sorted(set(r['mode'] for r in results)))}",
            "",
            "## Results by Task",
            "",
            "| Task | Mode | Score | Passed | Total | Time (s) | SWECAS |",
            "|------|------|-------|--------|-------|----------|--------|",
        ]

        for r in results:
            swecas = f"SWECAS-{r['swecas_code']}" if r.get('swecas_code') else "-"
            lines.append(
                f"| {r['task']} | {r['mode']} | {r['score']:.2f} | "
                f"{r['passed']} | {r['total']} | {r['duration_s']} | {swecas} |"
            )

        # Summary by mode
        lines.extend(["", "## Summary by Mode", ""])
        modes_seen = sorted(set(r['mode'] for r in results))
        lines.append("| Mode | Avg Score | Total Passed | Total Tests |")
        lines.append("|------|-----------|-------------|-------------|")

        for mode in modes_seen:
            mode_results = [r for r in results if r['mode'] == mode]
            avg_score = sum(r['score'] for r in mode_results) / max(len(mode_results), 1)
            total_passed = sum(r['passed'] for r in mode_results)
            total_tests = sum(r['total'] for r in mode_results)
            lines.append(f"| {mode} | {avg_score:.2f} | {total_passed} | {total_tests} |")

        return "\n".join(lines)

    def save_results(self, results):
        """Save results to JSON + markdown report."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        json_path = os.path.join(self.results_dir, f"ab_results_{timestamp}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nJSON results: {json_path}")

        report = self.generate_report(results)
        md_path = os.path.join(self.results_dir, f"ab_report_{timestamp}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"Markdown report: {md_path}")

        return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="A/B benchmark runner for QwenCode modes")
    parser.add_argument("--modes", nargs="+", default=None,
                        help="Modes to test (default: all)")
    parser.add_argument("--task", type=str, default=None,
                        help="Run single task only")
    parser.add_argument("--tasks-dir", type=str, default=None,
                        help="Path to swebench_tasks directory")
    parser.add_argument("--results-dir", type=str, default=None,
                        help="Path to results output directory")
    args = parser.parse_args()

    runner = ABRunner(tasks_dir=args.tasks_dir, results_dir=args.results_dir)

    print("=" * 60)
    print("QwenCode A/B Benchmark Runner")
    print("=" * 60)

    tasks = [args.task] if args.task else None
    if tasks:
        print(f"Running single task: {args.task}")
    else:
        all_tasks = runner._list_tasks()
        print(f"Found {len(all_tasks)} tasks: {', '.join(all_tasks)}")

    results = runner.run_all(modes=args.modes, tasks=tasks)
    runner.save_results(results)

    print("\n" + "=" * 60)
    print(runner.generate_report(results))
    print("=" * 60)


if __name__ == "__main__":
    main()
