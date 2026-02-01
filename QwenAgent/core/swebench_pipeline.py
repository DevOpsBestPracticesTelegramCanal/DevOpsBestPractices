# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
SWE-BENCH PIPELINE V2 - Full Integration
═══════════════════════════════════════════════════════════════════════════════

Complete pipeline for SWE-bench evaluation:

1. SETUP: Clone repo, checkout base commit
2. ANALYZE: Pattern Router → Deep Mode V2
3. APPLY: Apply patch with line_edit
4. VALIDATE: Syntax check with py_compile
5. TEST: Run pytest
6. RETRY: If fail, retry with feedback (max 3 attempts)

This is the FINAL component that ties everything together.

Usage:
    pipeline = SWEBenchPipeline()

    result = pipeline.run_task(
        task_id="django__django-11099",
        repo="django/django",
        base_commit="abc123...",
        problem_statement="Fix the validation bug...",
        test_cmd="pytest tests/test_validation.py"
    )

    print(f"Pass: {result.passed}")
    print(f"Attempts: {result.attempts}")

═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import time
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from deep_mode_v2 import DeepModeV2, DeepModeResult
    from router_v2 import PatternRouterV2, RouteResult
    from repo_manager import RepositoryManager, ApplyResult, TestResult, PatchFormat
except ImportError:
    # Fallback for direct execution
    import importlib.util
    def load_module(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    CORE_DIR = Path(__file__).parent
    deep_mode_v2 = load_module("deep_mode_v2", CORE_DIR / "deep_mode_v2.py")
    router_v2 = load_module("router_v2", CORE_DIR / "router_v2.py")
    repo_manager = load_module("repo_manager", CORE_DIR / "repo_manager.py")

    DeepModeV2 = deep_mode_v2.DeepModeV2
    PatternRouterV2 = router_v2.PatternRouterV2
    RepositoryManager = repo_manager.RepositoryManager
    PatchFormat = repo_manager.PatchFormat


class PipelineStage(Enum):
    """Pipeline execution stages"""
    SETUP = "setup"
    ANALYZE = "analyze"
    GENERATE = "generate"
    APPLY = "apply"
    VALIDATE = "validate"
    TEST = "test"
    COMPLETE = "complete"
    FAILED = "failed"
    # Aliases for compatibility
    TESTS_PASSED = "complete"  # alias
    SUCCESS = "complete"       # alias


@dataclass
class AttemptResult:
    """Result of a single attempt"""
    attempt_number: int
    patch: str
    patch_applied: bool
    syntax_valid: bool
    tests_passed: bool
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class PipelineResult:
    """Final result of pipeline execution"""
    task_id: str
    passed: bool
    stage_reached: PipelineStage
    attempts: int
    best_attempt: Optional[AttemptResult] = None
    all_attempts: List[AttemptResult] = field(default_factory=list)
    total_time_ms: float = 0.0
    repo_path: str = ""
    error: str = ""

    # Aliases for compatibility
    @property
    def success(self) -> bool:
        """Alias for passed"""
        return self.passed

    @property
    def stage(self) -> str:
        """Alias for stage_reached.value"""
        return self.stage_reached.value

    @property
    def response(self) -> str:
        """Get response from best attempt"""
        if self.best_attempt:
            return self.best_attempt.patch
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "stage_reached": self.stage_reached.value,
            "attempts": self.attempts,
            "total_time_ms": self.total_time_ms,
            "error": self.error
        }


class SWEBenchPipeline:
    """
    Complete SWE-bench evaluation pipeline.

    Features:
    - Full repo setup with git clone/checkout
    - Pattern routing for fast cases
    - Deep Mode V2 for complex reasoning
    - Line-based patch application
    - Syntax validation
    - Test execution
    - Retry loop with feedback
    """

    def __init__(
        self,
        max_attempts: int = 3,
        fast_model: str = "qwen2.5-coder:3b",
        heavy_model: str = "qwen2.5-coder:7b",
        workspace: str = None,
        verbose: bool = True
    ):
        """
        Initialize pipeline.

        Args:
            max_attempts: Maximum retry attempts (default: 3)
            fast_model: Model for analysis steps
            heavy_model: Model for code generation
            workspace: Directory for cloned repos
            verbose: Print progress
        """
        self.max_attempts = max_attempts
        self.verbose = verbose

        # Initialize components
        self.router = PatternRouterV2()
        self.deep_mode = DeepModeV2(fast_model, heavy_model)
        self.repo_manager = RepositoryManager(workspace)

        # Statistics
        self.stats = {
            "tasks_run": 0,
            "tasks_passed": 0,
            "total_attempts": 0,
            "avg_attempts_per_task": 0.0,
            "by_stage": {}
        }

    def run_task(
        self,
        task_id: str,
        repo: str,
        base_commit: str,
        problem_statement: str,
        test_cmd: str = "pytest",
        test_files: List[str] = None,
        gold_patch: str = None
    ) -> PipelineResult:
        """
        Run complete pipeline for a task.

        Args:
            task_id: Unique task identifier
            repo: Repository path (e.g., "django/django")
            base_commit: Commit to checkout
            problem_statement: The bug/issue description
            test_cmd: Test command
            test_files: Specific test files
            gold_patch: Expected solution (for comparison)

        Returns:
            PipelineResult with pass/fail and details
        """
        start_time = time.time()
        self.stats["tasks_run"] += 1

        result = PipelineResult(
            task_id=task_id,
            passed=False,
            stage_reached=PipelineStage.SETUP,
            attempts=0
        )

        if self.verbose:
            print(f"\n{'='*70}")
            print(f"  TASK: {task_id}")
            print(f"  Repo: {repo}")
            print(f"{'='*70}")

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 1: SETUP
        # ─────────────────────────────────────────────────────────────────────

        if self.verbose:
            print(f"\n  [STAGE 1/6] SETUP")

        setup_result = self.repo_manager.setup_task(task_id, repo, base_commit)

        if not setup_result.success:
            result.error = f"Setup failed: {setup_result.message}"
            result.stage_reached = PipelineStage.FAILED
            result.total_time_ms = (time.time() - start_time) * 1000
            return result

        result.repo_path = setup_result.repo_path

        if self.verbose:
            print(f"    Repo ready at: {setup_result.repo_path}")
            print(f"    Setup time: {setup_result.setup_time_ms:.0f}ms")

        # ─────────────────────────────────────────────────────────────────────
        # STAGE 2: ANALYZE
        # ─────────────────────────────────────────────────────────────────────

        result.stage_reached = PipelineStage.ANALYZE

        if self.verbose:
            print(f"\n  [STAGE 2/6] ANALYZE")

        route_result = self.router.route(problem_statement)

        if self.verbose:
            print(f"    Category: {route_result.category.value}")
            print(f"    Needs Deep Mode: {route_result.needs_deep_mode}")
            print(f"    Confidence: {route_result.confidence:.0%}")

        # ─────────────────────────────────────────────────────────────────────
        # RETRY LOOP: GENERATE → APPLY → VALIDATE → TEST
        # ─────────────────────────────────────────────────────────────────────

        feedback = ""  # Accumulate feedback from failed attempts

        for attempt in range(1, self.max_attempts + 1):
            result.attempts = attempt
            self.stats["total_attempts"] += 1

            if self.verbose:
                print(f"\n  [ATTEMPT {attempt}/{self.max_attempts}]")

            attempt_start = time.time()
            attempt_result = AttemptResult(
                attempt_number=attempt,
                patch="",
                patch_applied=False,
                syntax_valid=False,
                tests_passed=False
            )

            # ─────────────────────────────────────────────────────────────────
            # STAGE 3: GENERATE
            # ─────────────────────────────────────────────────────────────────

            result.stage_reached = PipelineStage.GENERATE

            if self.verbose:
                print(f"\n    [STAGE 3/6] GENERATE (Deep Mode V2)")

            # Build context with feedback
            context = self._build_context(
                task_id, repo, problem_statement, feedback, attempt
            )

            deep_result = self.deep_mode.execute(
                problem_statement[:2000],
                context,
                verbose=self.verbose
            )

            if not deep_result.success or not deep_result.final_answer:
                attempt_result.error = "No code generated"
                attempt_result.duration_ms = (time.time() - attempt_start) * 1000
                result.all_attempts.append(attempt_result)

                feedback += f"\nAttempt {attempt} failed: No code generated."
                continue

            attempt_result.patch = deep_result.final_answer

            if self.verbose:
                print(f"      Generated: {len(deep_result.final_answer)} chars")

            # ─────────────────────────────────────────────────────────────────
            # STAGE 4: APPLY
            # ─────────────────────────────────────────────────────────────────

            result.stage_reached = PipelineStage.APPLY

            if self.verbose:
                print(f"\n    [STAGE 4/6] APPLY")

            # Detect patch format
            patch_format = self._detect_patch_format(deep_result.final_answer)

            if self.verbose:
                print(f"      Format: {patch_format.value}")

            apply_result = self.repo_manager.apply_patch(
                result.repo_path,
                deep_result.final_answer,
                patch_format
            )

            attempt_result.patch_applied = apply_result.success

            if not apply_result.success:
                attempt_result.error = f"Apply failed: {apply_result.message}"
                attempt_result.duration_ms = (time.time() - attempt_start) * 1000
                result.all_attempts.append(attempt_result)

                feedback += f"\nAttempt {attempt} apply failed: {apply_result.message}"

                # Rollback and retry
                if apply_result.backup_path:
                    self.repo_manager.rollback(result.repo_path, apply_result.backup_path)
                continue

            if self.verbose:
                print(f"      Applied to: {apply_result.files_modified}")

            # ─────────────────────────────────────────────────────────────────
            # STAGE 5: VALIDATE
            # ─────────────────────────────────────────────────────────────────

            result.stage_reached = PipelineStage.VALIDATE

            if self.verbose:
                print(f"\n    [STAGE 5/6] VALIDATE")

            syntax_result = self.repo_manager.validate_syntax(
                result.repo_path,
                apply_result.files_modified
            )

            attempt_result.syntax_valid = syntax_result["valid"]

            if not syntax_result["valid"]:
                errors = syntax_result.get("errors", [])
                error_msg = "; ".join(e.get("error", "")[:100] for e in errors)
                attempt_result.error = f"Syntax error: {error_msg}"
                attempt_result.duration_ms = (time.time() - attempt_start) * 1000
                result.all_attempts.append(attempt_result)

                if self.verbose:
                    print(f"      Syntax errors: {len(errors)}")
                    for e in errors[:2]:
                        print(f"        - {e.get('file')}: {e.get('error', '')[:80]}")

                feedback += f"\nAttempt {attempt} syntax error: {error_msg[:200]}"

                # Rollback and retry
                self.repo_manager.rollback(result.repo_path, apply_result.backup_path)
                continue

            if self.verbose:
                print(f"      Syntax: OK")

            # ─────────────────────────────────────────────────────────────────
            # STAGE 6: TEST
            # ─────────────────────────────────────────────────────────────────

            result.stage_reached = PipelineStage.TEST

            if self.verbose:
                print(f"\n    [STAGE 6/6] TEST")

            test_result = self.repo_manager.run_tests(
                result.repo_path,
                test_cmd,
                test_files
            )

            attempt_result.tests_passed = test_result.success
            attempt_result.duration_ms = (time.time() - attempt_start) * 1000
            result.all_attempts.append(attempt_result)

            if self.verbose:
                print(f"      Passed: {test_result.tests_passed}/{test_result.tests_total}")
                print(f"      Duration: {test_result.duration_ms:.0f}ms")

            if test_result.success:
                # SUCCESS!
                result.passed = True
                result.stage_reached = PipelineStage.COMPLETE
                result.best_attempt = attempt_result

                self.stats["tasks_passed"] += 1

                if self.verbose:
                    print(f"\n  [SUCCESS] Task passed on attempt {attempt}!")

                break
            else:
                # Tests failed - add feedback and retry
                test_output = test_result.stderr or test_result.stdout
                feedback += f"\nAttempt {attempt} tests failed: {test_output[:300]}"

                # Rollback for next attempt
                self.repo_manager.rollback(result.repo_path, apply_result.backup_path)

                if self.verbose:
                    print(f"      Tests failed, will retry...")

        # ─────────────────────────────────────────────────────────────────────
        # FINALIZE
        # ─────────────────────────────────────────────────────────────────────

        result.total_time_ms = (time.time() - start_time) * 1000

        # Update statistics
        self._update_stats(result)

        if self.verbose:
            status = "[PASS]" if result.passed else "[FAIL]"
            print(f"\n{'='*70}")
            print(f"  {status} {task_id}")
            print(f"  Attempts: {result.attempts}")
            print(f"  Total time: {result.total_time_ms/1000:.1f}s")
            print(f"{'='*70}")

        return result

    def _build_context(
        self,
        task_id: str,
        repo: str,
        problem: str,
        feedback: str,
        attempt: int
    ) -> str:
        """Build context for Deep Mode"""

        context = f"""
Repository: {repo}
Task ID: {task_id}
Attempt: {attempt}/{self.max_attempts}

Problem Statement:
{problem[:1500]}

IMPORTANT INSTRUCTIONS:
1. Output code using edit_lines() format:
   edit_lines('path/to/file.py', START_LINE, END_LINE, '''
   NEW_CODE_HERE
   ''')

2. Use grep -n to find line numbers first
3. Output ONLY the fix, not the entire file
4. Make minimal changes to fix the issue
"""

        if feedback:
            context += f"""

FEEDBACK FROM PREVIOUS ATTEMPTS:
{feedback[-800:]}

Learn from these errors and try a different approach.
"""

        return context

    def _detect_patch_format(self, patch: str) -> PatchFormat:
        """Detect the format of generated patch"""

        if "edit_lines(" in patch:
            return PatchFormat.EDIT_LINES
        elif patch.strip().startswith("{"):
            return PatchFormat.DIRECT_WRITE
        elif "diff --git" in patch or "---" in patch and "+++" in patch:
            return PatchFormat.UNIFIED_DIFF
        else:
            # Default to edit_lines - try to parse it
            return PatchFormat.EDIT_LINES

    def _update_stats(self, result: PipelineResult):
        """Update pipeline statistics"""

        stage = result.stage_reached.value
        self.stats["by_stage"][stage] = self.stats["by_stage"].get(stage, 0) + 1

        if self.stats["tasks_run"] > 0:
            self.stats["avg_attempts_per_task"] = (
                self.stats["total_attempts"] / self.stats["tasks_run"]
            )

    def get_statistics(self) -> Dict[str, Any]:
        """Get pipeline statistics"""
        return {
            **self.stats,
            "pass_rate": (
                self.stats["tasks_passed"] / self.stats["tasks_run"]
                if self.stats["tasks_run"] > 0 else 0.0
            )
        }

    def cleanup(self, task_id: str = None):
        """Cleanup task resources"""
        self.repo_manager.cleanup(task_id)


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

_default_pipeline: Optional[SWEBenchPipeline] = None


def get_pipeline() -> SWEBenchPipeline:
    """Get or create default pipeline"""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = SWEBenchPipeline()
    return _default_pipeline


def run_swebench_task(
    task_id: str,
    repo: str,
    base_commit: str,
    problem_statement: str,
    test_cmd: str = "pytest"
) -> PipelineResult:
    """Quick function to run a single SWE-bench task"""
    return get_pipeline().run_task(
        task_id, repo, base_commit, problem_statement, test_cmd
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 70)
    print("  SWE-BENCH PIPELINE V2 TEST")
    print("=" * 70)

    # Create pipeline
    pipeline = SWEBenchPipeline(
        max_attempts=2,
        verbose=True
    )

    print(f"\n  Pipeline Configuration:")
    print(f"    Max attempts: {pipeline.max_attempts}")
    print(f"    Fast model: {pipeline.deep_mode.fast_model}")
    print(f"    Heavy model: {pipeline.deep_mode.heavy_model}")

    # Test with mock task (no real git clone)
    print("\n" + "=" * 70)
    print("  MOCK TEST (without git clone)")
    print("=" * 70)

    # Create mock environment
    import tempfile
    import shutil

    mock_repo = Path(tempfile.mkdtemp())

    # Create test files
    (mock_repo / "validator.py").write_text('''
def validate_name(name):
    """Validate that name is not empty"""
    if not name:  # Bug: should check for None too
        raise ValueError("Name cannot be empty")
    return name.strip()
''')

    (mock_repo / "test_validator.py").write_text('''
import pytest
from validator import validate_name

def test_valid_name():
    assert validate_name("Alice") == "Alice"

def test_empty_name():
    with pytest.raises(ValueError):
        validate_name("")

def test_none_name():
    with pytest.raises(ValueError):
        validate_name(None)  # This will fail!
''')

    print(f"\n  Mock repo created: {mock_repo}")

    # Simulate running Deep Mode and applying patch
    print("\n  [SIMULATING] Pipeline stages...")

    # Mock the setup to use our test directory
    pipeline.repo_manager.active_tasks["mock-task"] = mock_repo

    # Test apply_patch with edit_lines format
    patch = '''
edit_lines('validator.py', 4, 5, '    if name is None or not name:
        raise ValueError("Name cannot be empty")')
'''

    print(f"\n  Applying patch...")
    apply_result = pipeline.repo_manager.apply_patch(
        str(mock_repo),
        patch,
        PatchFormat.EDIT_LINES
    )
    print(f"  Apply result: {apply_result.success} - {apply_result.message}")

    # Validate syntax
    print(f"\n  Validating syntax...")
    syntax_result = pipeline.repo_manager.validate_syntax(
        str(mock_repo),
        ["validator.py"]
    )
    print(f"  Syntax valid: {syntax_result['valid']}")

    # Run tests
    print(f"\n  Running tests...")
    test_result = pipeline.repo_manager.run_tests(
        str(mock_repo),
        "pytest",
        timeout=30
    )
    print(f"  Tests passed: {test_result.success}")
    print(f"  Output: {test_result.stdout[:200] if test_result.stdout else 'None'}")

    # Cleanup
    shutil.rmtree(mock_repo)

    # Print statistics
    print("\n" + "=" * 70)
    print("  PIPELINE STATISTICS")
    print("=" * 70)

    stats = pipeline.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n  [OK] SWE-Bench Pipeline V2 ready!")
    print("\n  To run real tasks:")
    print("    python run_swebench_v3.py")
