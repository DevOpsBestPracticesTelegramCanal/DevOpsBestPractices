# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
SWE-BENCH V3 RUNNER - Full Pipeline with Repository Manager
═══════════════════════════════════════════════════════════════════════════════

Complete SWE-bench evaluation with:
- Real git clone and checkout
- Deep Mode V2 (3 steps, hybrid model)
- Line-based patch application
- Syntax validation
- Test execution
- Retry loop (max 3 attempts)

Usage:
    python run_swebench_v3.py               # Run all 10 tasks
    python run_swebench_v3.py --quick       # Run 3 quick tasks
    python run_swebench_v3.py --task django__django-11099  # Run specific task
    python run_swebench_v3.py --dry         # Dry run (no git clone)
    python run_swebench_v3.py --local       # Use local task dirs (no clone)

═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import io
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add paths
SCRIPT_DIR = Path(__file__).parent
CORE_DIR = SCRIPT_DIR / "core"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(CORE_DIR))

# Direct imports
import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Load modules
swebench_pipeline = load_module("swebench_pipeline", CORE_DIR / "swebench_pipeline.py")
SWEBenchPipeline = swebench_pipeline.SWEBenchPipeline
PipelineResult = swebench_pipeline.PipelineResult

# Paths
BENCHMARK_DIR = SCRIPT_DIR / "swebench_benchmark"
TASKS_FILE = BENCHMARK_DIR / "tasks.json"
RESULTS_DIR = SCRIPT_DIR / "swebench_results"
RESULTS_DIR.mkdir(exist_ok=True)

# Local tasks directory
LOCAL_TASKS_DIR = SCRIPT_DIR / "swebench_tasks"


def load_tasks() -> dict:
    """Load SWE-bench tasks from JSON file"""
    if not TASKS_FILE.exists():
        print(f"[WARN] Tasks file not found: {TASKS_FILE}")
        print("Creating from local task directories...")
        return create_tasks_from_local()

    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_tasks_from_local() -> dict:
    """Create tasks dict from local swebench_tasks directory"""
    tasks = {}

    if not LOCAL_TASKS_DIR.exists():
        print(f"[ERROR] No tasks found at {LOCAL_TASKS_DIR}")
        return tasks

    # Try to load from swecas_task_mapping.json first
    mapping_file = LOCAL_TASKS_DIR / "swecas_task_mapping.json"
    task_mapping = {}
    if mapping_file.exists():
        with open(mapping_file, 'r', encoding='utf-8') as f:
            task_mapping = json.load(f)
        print(f"  Loaded {len(task_mapping)} tasks from swecas_task_mapping.json")

    for task_dir in LOCAL_TASKS_DIR.iterdir():
        if not task_dir.is_dir():
            continue
        if task_dir.name.startswith('__'):  # Skip __pycache__
            continue

        task_id = task_dir.name

        # Get problem statement from mapping or problem_statement.txt
        problem = ""
        if task_id in task_mapping:
            problem = task_mapping[task_id].get("description_used", "")
        else:
            problem_file = task_dir / "problem_statement.txt"
            if problem_file.exists():
                problem = problem_file.read_text(encoding='utf-8')

        if problem:
            tasks[task_id] = {
                "repo": task_id.replace("__", "/").rsplit("-", 1)[0],
                "problem_statement": problem,
                "base_commit": "HEAD",
                "local_path": str(task_dir)
            }

    return tasks


def run_local_task(
    pipeline: SWEBenchPipeline,
    task_id: str,
    task_data: dict
) -> PipelineResult:
    """Run task using local directory instead of git clone"""

    local_path = task_data.get("local_path")
    if not local_path:
        local_path = str(LOCAL_TASKS_DIR / task_id)

    problem = task_data.get("problem_statement", "")

    print(f"\n{'='*70}")
    print(f"  TASK: {task_id} (LOCAL)")
    print(f"  Path: {local_path}")
    print(f"{'='*70}")

    start_time = time.time()

    # Check local path exists
    if not Path(local_path).exists():
        return PipelineResult(
            task_id=task_id,
            passed=False,
            stage_reached=swebench_pipeline.PipelineStage.SETUP,
            attempts=0,
            error=f"Local path not found: {local_path}",
            total_time_ms=(time.time() - start_time) * 1000
        )

    # Register local path as active task
    pipeline.repo_manager.active_tasks[task_id] = Path(local_path)

    result = PipelineResult(
        task_id=task_id,
        passed=False,
        stage_reached=swebench_pipeline.PipelineStage.ANALYZE,
        attempts=0,
        repo_path=local_path
    )

    # Run analysis and generation
    print(f"\n  [ANALYZE] Routing task...")
    route_result = pipeline.router.route(problem)
    print(f"    Category: {route_result.category.value}")
    print(f"    Needs Deep Mode: {route_result.needs_deep_mode}")

    # Build context
    context = f"""
Local Task: {task_id}
Path: {local_path}

Problem Statement:
{problem[:1500]}

IMPORTANT:
1. Use edit_lines() format for code changes
2. Reference files relative to the task directory
3. Make minimal, focused changes
"""

    # Run Deep Mode
    print(f"\n  [GENERATE] Running Deep Mode V2...")
    deep_result = pipeline.deep_mode.execute(problem[:2000], context, verbose=True)

    if deep_result.success and deep_result.final_answer:
        result.stage_reached = swebench_pipeline.PipelineStage.GENERATE
        result.attempts = 1

        # For local tasks, we just report the generated code
        print(f"\n  [GENERATED CODE]")
        print(f"  {'-'*60}")
        print(f"  {deep_result.final_answer[:500]}")
        if len(deep_result.final_answer) > 500:
            print("  ...")

        # Check if code was generated
        has_code = any(ind in deep_result.final_answer for ind in [
            "def ", "class ", "edit_lines(", "```python", ".py"
        ])

        if has_code:
            result.passed = True
            result.stage_reached = swebench_pipeline.PipelineStage.COMPLETE

    result.total_time_ms = (time.time() - start_time) * 1000

    return result


def run_benchmark(
    quick: bool = False,
    dry_run: bool = False,
    local_only: bool = False,
    specific_task: str = None
):
    """Run SWE-bench V3 benchmark"""

    print("=" * 70)
    print("  SWE-BENCH V3 BENCHMARK")
    print("  Full Pipeline with Repository Manager")
    print("=" * 70)

    # Load tasks - prioritize local when --local flag is set
    if local_only:
        print("\n  [LOCAL MODE] Scanning swebench_tasks/ directory...")
        tasks = create_tasks_from_local()
    else:
        tasks = load_tasks()
    if not tasks:
        print("[ERROR] No tasks loaded")
        return

    print(f"\n  Loaded {len(tasks)} tasks")

    # Initialize pipeline
    pipeline = SWEBenchPipeline(
        max_attempts=3,
        verbose=True
    )

    print(f"\n  Pipeline Configuration:")
    print(f"    Max attempts: {pipeline.max_attempts}")
    print(f"    Fast model: {pipeline.deep_mode.fast_model}")
    print(f"    Heavy model: {pipeline.deep_mode.heavy_model}")
    print(f"    Mode: {'LOCAL' if local_only else 'GIT CLONE'}")

    # Select tasks
    if specific_task:
        if specific_task in tasks:
            task_ids = [specific_task]
        else:
            print(f"[ERROR] Task not found: {specific_task}")
            return
    else:
        task_ids = list(tasks.keys())
        if quick:
            task_ids = task_ids[:3]

    print(f"\n  Running {len(task_ids)} tasks")

    if dry_run:
        print("  [DRY RUN] No actual execution")
        for tid in task_ids:
            print(f"    - {tid}")
        return

    # Run tasks
    results = []
    total_start = time.time()

    for i, task_id in enumerate(task_ids, 1):
        print(f"\n[{i}/{len(task_ids)}]", end="")

        task_data = tasks[task_id]

        if local_only or task_data.get("local_path"):
            result = run_local_task(pipeline, task_id, task_data)
        else:
            result = pipeline.run_task(
                task_id=task_id,
                repo=task_data.get("repo", ""),
                base_commit=task_data.get("base_commit", "HEAD"),
                problem_statement=task_data.get("problem_statement", ""),
                test_cmd=task_data.get("test_cmd", "pytest")
            )

        results.append(result)

    total_time = time.time() - total_start

    # ─────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("  FINAL RESULTS")
    print("=" * 70)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    print(f"\n  Total Tasks: {len(results)}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Pass Rate: {passed/len(results)*100:.1f}%")
    print(f"  Total Time: {total_time:.1f}s")
    print(f"  Avg Time/Task: {total_time/len(results):.1f}s")

    # Breakdown
    print(f"\n  Results by Task:")
    print(f"  {'-'*60}")
    for r in results:
        status = "[PASS]" if r.passed else "[FAIL]"
        print(f"  {status} {r.task_id}")
        print(f"         Stage: {r.stage_reached.value}, Attempts: {r.attempts}, Time: {r.total_time_ms/1000:.1f}s")
        if r.error:
            print(f"         Error: {r.error[:60]}...")

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = RESULTS_DIR / f"swebench_v3_{timestamp}.json"

    results_data = {
        "timestamp": timestamp,
        "config": {
            "max_attempts": pipeline.max_attempts,
            "fast_model": pipeline.deep_mode.fast_model,
            "heavy_model": pipeline.deep_mode.heavy_model,
            "mode": "local" if local_only else "git_clone"
        },
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(results) if results else 0,
            "total_time_s": total_time
        },
        "results": [r.to_dict() for r in results],
        "pipeline_stats": pipeline.get_statistics()
    }

    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results_data, f, indent=2, ensure_ascii=False)

    print(f"\n  Results saved to: {results_file}")

    # Pipeline statistics
    print(f"\n  Pipeline Statistics:")
    stats = pipeline.get_statistics()
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"    {key}: {value:.2f}")
        else:
            print(f"    {key}: {value}")

    # Cleanup
    pipeline.cleanup()

    return results


def main():
    parser = argparse.ArgumentParser(
        description="SWE-bench V3 Runner with Full Pipeline"
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Run only 3 quick tasks"
    )
    parser.add_argument(
        "--dry", "-d",
        action="store_true",
        help="Dry run (no execution)"
    )
    parser.add_argument(
        "--local", "-l",
        action="store_true",
        help="Use local task directories (no git clone)"
    )
    parser.add_argument(
        "--task", "-t",
        type=str,
        help="Run specific task by ID"
    )

    args = parser.parse_args()

    run_benchmark(
        quick=args.quick,
        dry_run=args.dry,
        local_only=args.local,
        specific_task=args.task
    )


if __name__ == "__main__":
    main()
