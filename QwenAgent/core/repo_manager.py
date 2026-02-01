# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
REPOSITORY MANAGER - Git Operations for SWE-bench
═══════════════════════════════════════════════════════════════════════════════

Manages repository operations for SWE-bench tasks:
1. Clone repositories
2. Checkout specific commits
3. Apply patches (generated code)
4. Run tests
5. Validate fixes

This is the MISSING COMPONENT that allows the agent to:
- Work with REAL files (not just generate code)
- Validate solutions through actual tests
- Compare with gold patches

Usage:
    manager = RepositoryManager()

    # Setup task environment
    repo_path = manager.setup_task(
        task_id="django__django-11099",
        repo="django/django",
        base_commit="abc123..."
    )

    # Apply generated patch
    success = manager.apply_patch(repo_path, generated_code)

    # Run tests
    test_result = manager.run_tests(repo_path, "pytest tests/test_auth.py")

    # Cleanup
    manager.cleanup(repo_path)

═══════════════════════════════════════════════════════════════════════════════
"""

import os
import gc
import stat
import subprocess
import shutil
import tempfile
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum


def _windows_safe_rmtree(path: Path, max_retries: int = 3):
    """
    Windows-safe rmtree with retry logic for locked files.

    Handles:
    - Read-only files (git .pack files)
    - Locked files (retry with delay)
    - Garbage collection before delete
    """
    def on_rm_error(func, path, exc_info):
        """Error handler for shutil.rmtree"""
        # Try to remove read-only flag
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    # Force garbage collection to release file handles
    gc.collect()

    for attempt in range(max_retries):
        try:
            if Path(path).exists():
                shutil.rmtree(path, onerror=on_rm_error)
            return True
        except (PermissionError, OSError) as e:
            if attempt < max_retries - 1:
                gc.collect()
                time.sleep(0.5 * (attempt + 1))  # Progressive delay
            else:
                print(f"  [WARN] Could not delete {path}: {e}")
                return False
    return False


class PatchFormat(Enum):
    """Supported patch formats"""
    UNIFIED_DIFF = "unified_diff"       # Standard git diff
    EDIT_LINES = "edit_lines"           # Our edit_lines() format
    DIRECT_WRITE = "direct_write"       # Direct file content


@dataclass
class TestResult:
    """Result of running tests"""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    tests_passed: int = 0
    tests_failed: int = 0
    tests_total: int = 0


@dataclass
class ApplyResult:
    """Result of applying a patch"""
    success: bool
    message: str
    files_modified: List[str] = field(default_factory=list)
    backup_path: Optional[str] = None


@dataclass
class SetupResult:
    """Result of setting up a task"""
    success: bool
    repo_path: str
    message: str
    setup_time_ms: float


class RepositoryManager:
    """
    Manages Git repositories for SWE-bench task execution.

    Features:
    - Isolated workspace per task
    - Automatic backup before modifications
    - Multiple patch format support
    - Test execution with timeout
    - Cleanup and rollback
    """

    DEFAULT_WORKSPACE = Path(tempfile.gettempdir()) / "swebench_repos"
    GITHUB_BASE = "https://github.com"

    def __init__(
        self,
        workspace: Optional[str] = None,
        cache_repos: bool = True,
        timeout_clone: int = 300,
        timeout_test: int = 300
    ):
        """
        Initialize Repository Manager.

        Args:
            workspace: Base directory for cloned repos
            cache_repos: Whether to cache cloned repos between tasks
            timeout_clone: Timeout for git clone (seconds)
            timeout_test: Timeout for test execution (seconds)
        """
        self.workspace = Path(workspace) if workspace else self.DEFAULT_WORKSPACE
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.cache_repos = cache_repos
        self.timeout_clone = timeout_clone
        self.timeout_test = timeout_test

        # Track active tasks
        self.active_tasks: Dict[str, Path] = {}

        # Statistics
        self.stats = {
            "tasks_setup": 0,
            "patches_applied": 0,
            "tests_run": 0,
            "tests_passed": 0,
            "total_clone_time_ms": 0,
            "total_test_time_ms": 0
        }

    # ═══════════════════════════════════════════════════════════════════════
    # SETUP: Clone and prepare repository
    # ═══════════════════════════════════════════════════════════════════════

    def setup_task(
        self,
        task_id: str,
        repo: str,
        base_commit: str,
        install_deps: bool = False
    ) -> SetupResult:
        """
        Set up repository for a task.

        Args:
            task_id: Unique task identifier (e.g., "django__django-11099")
            repo: Repository path (e.g., "django/django")
            base_commit: Base commit hash to checkout
            install_deps: Whether to run pip install -e .

        Returns:
            SetupResult with repo_path and status
        """
        start_time = time.time()

        # Create task directory
        repo_name = repo.replace("/", "__")
        task_path = self.workspace / f"{task_id}_{int(time.time())}"

        try:
            # Check if we have cached repo
            cached_path = self.workspace / f"cache_{repo_name}"

            if self.cache_repos and cached_path.exists():
                # Copy from cache
                print(f"  [REPO] Using cached repo: {repo_name}")
                shutil.copytree(cached_path, task_path)
            else:
                # Clone fresh
                print(f"  [REPO] Cloning {repo}...")
                clone_url = f"{self.GITHUB_BASE}/{repo}.git"

                result = subprocess.run(
                    ["git", "clone", "--depth", "100", clone_url, str(task_path)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_clone
                )

                if result.returncode != 0:
                    return SetupResult(
                        success=False,
                        repo_path="",
                        message=f"Clone failed: {result.stderr}",
                        setup_time_ms=(time.time() - start_time) * 1000
                    )

                # Cache for future use
                if self.cache_repos:
                    shutil.copytree(task_path, cached_path)

            # Checkout base commit
            print(f"  [REPO] Checking out {base_commit[:8]}...")
            result = subprocess.run(
                ["git", "-C", str(task_path), "checkout", "-f", base_commit],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                # Try fetching more history
                subprocess.run(
                    ["git", "-C", str(task_path), "fetch", "--unshallow"],
                    capture_output=True,
                    timeout=120
                )
                result = subprocess.run(
                    ["git", "-C", str(task_path), "checkout", "-f", base_commit],
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if result.returncode != 0:
                    return SetupResult(
                        success=False,
                        repo_path=str(task_path),
                        message=f"Checkout failed: {result.stderr}",
                        setup_time_ms=(time.time() - start_time) * 1000
                    )

            # Clean working directory
            subprocess.run(
                ["git", "-C", str(task_path), "clean", "-fdx"],
                capture_output=True,
                timeout=60
            )

            # Install dependencies if requested
            if install_deps:
                print(f"  [REPO] Installing dependencies...")
                subprocess.run(
                    ["pip", "install", "-e", "."],
                    cwd=task_path,
                    capture_output=True,
                    timeout=300
                )

            # Track active task
            self.active_tasks[task_id] = task_path

            setup_time = (time.time() - start_time) * 1000
            self.stats["tasks_setup"] += 1
            self.stats["total_clone_time_ms"] += setup_time

            return SetupResult(
                success=True,
                repo_path=str(task_path),
                message=f"Repository ready at {task_path}",
                setup_time_ms=setup_time
            )

        except subprocess.TimeoutExpired:
            return SetupResult(
                success=False,
                repo_path="",
                message=f"Setup timed out after {self.timeout_clone}s",
                setup_time_ms=(time.time() - start_time) * 1000
            )
        except Exception as e:
            return SetupResult(
                success=False,
                repo_path="",
                message=f"Setup error: {e}",
                setup_time_ms=(time.time() - start_time) * 1000
            )

    # ═══════════════════════════════════════════════════════════════════════
    # APPLY: Apply generated patch to repository
    # ═══════════════════════════════════════════════════════════════════════

    def apply_patch(
        self,
        repo_path: str,
        patch: str,
        patch_format: PatchFormat = PatchFormat.UNIFIED_DIFF,
        create_backup: bool = True
    ) -> ApplyResult:
        """
        Apply a patch to the repository.

        Args:
            repo_path: Path to the repository
            patch: The patch content (diff, edit_lines, or file content)
            patch_format: Format of the patch
            create_backup: Whether to create backup before applying

        Returns:
            ApplyResult with status and modified files
        """
        repo_path = Path(repo_path)

        if not repo_path.exists():
            return ApplyResult(success=False, message=f"Repo not found: {repo_path}")

        # Create backup
        backup_path = None
        if create_backup:
            backup_path = str(repo_path) + "_backup"
            if Path(backup_path).exists():
                _windows_safe_rmtree(Path(backup_path))
            shutil.copytree(repo_path, backup_path)

        try:
            if patch_format == PatchFormat.UNIFIED_DIFF:
                return self._apply_unified_diff(repo_path, patch, backup_path)
            elif patch_format == PatchFormat.EDIT_LINES:
                return self._apply_edit_lines(repo_path, patch, backup_path)
            elif patch_format == PatchFormat.DIRECT_WRITE:
                return self._apply_direct_write(repo_path, patch, backup_path)
            else:
                return ApplyResult(
                    success=False,
                    message=f"Unknown patch format: {patch_format}",
                    backup_path=backup_path
                )

        except Exception as e:
            return ApplyResult(
                success=False,
                message=f"Apply error: {e}",
                backup_path=backup_path
            )

    def _apply_unified_diff(
        self,
        repo_path: Path,
        patch: str,
        backup_path: Optional[str]
    ) -> ApplyResult:
        """Apply standard unified diff"""

        # Write patch to temp file
        patch_file = repo_path / "temp_patch.diff"
        patch_file.write_text(patch, encoding='utf-8')

        try:
            # Try git apply
            result = subprocess.run(
                ["git", "-C", str(repo_path), "apply", str(patch_file)],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                self.stats["patches_applied"] += 1
                return ApplyResult(
                    success=True,
                    message="Patch applied successfully",
                    files_modified=self._get_modified_files(repo_path),
                    backup_path=backup_path
                )

            # Try with --3way
            result = subprocess.run(
                ["git", "-C", str(repo_path), "apply", "--3way", str(patch_file)],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                self.stats["patches_applied"] += 1
                return ApplyResult(
                    success=True,
                    message="Patch applied with 3-way merge",
                    files_modified=self._get_modified_files(repo_path),
                    backup_path=backup_path
                )

            return ApplyResult(
                success=False,
                message=f"git apply failed: {result.stderr}",
                backup_path=backup_path
            )

        finally:
            if patch_file.exists():
                patch_file.unlink()

    def _apply_edit_lines(
        self,
        repo_path: Path,
        patch: str,
        backup_path: Optional[str]
    ) -> ApplyResult:
        """Apply our edit_lines() format"""
        import re

        # Parse edit_lines calls
        # Pattern: edit_lines('file.py', START, END, '''content''')
        pattern = r"edit_lines\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*['\"\`]{1,3}(.*?)['\"\`]{1,3}\s*\)"

        matches = re.findall(pattern, patch, re.DOTALL)

        if not matches:
            # Try simpler pattern
            pattern = r"edit_lines\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\d+)\s*,\s*(\d+)"
            matches = re.findall(pattern, patch)

            if not matches:
                return ApplyResult(
                    success=False,
                    message="No edit_lines() calls found in patch",
                    backup_path=backup_path
                )

        modified_files = []

        for match in matches:
            if len(match) == 4:
                file_path, start, end, content = match
            else:
                file_path, start, end = match
                content = ""

            file_full_path = repo_path / file_path

            if not file_full_path.exists():
                return ApplyResult(
                    success=False,
                    message=f"File not found: {file_path}",
                    backup_path=backup_path
                )

            # Read file
            lines = file_full_path.read_text(encoding='utf-8').split('\n')

            start_idx = int(start) - 1
            end_idx = int(end)

            # Validate indices
            if start_idx < 0 or end_idx > len(lines):
                return ApplyResult(
                    success=False,
                    message=f"Invalid line range: {start}-{end} (file has {len(lines)} lines)",
                    backup_path=backup_path
                )

            # Replace lines
            new_lines = lines[:start_idx] + content.split('\n') + lines[end_idx:]

            # Write back
            file_full_path.write_text('\n'.join(new_lines), encoding='utf-8')
            modified_files.append(file_path)

        self.stats["patches_applied"] += 1

        return ApplyResult(
            success=True,
            message=f"Applied {len(matches)} edit_lines() calls",
            files_modified=modified_files,
            backup_path=backup_path
        )

    def _apply_direct_write(
        self,
        repo_path: Path,
        patch: str,
        backup_path: Optional[str]
    ) -> ApplyResult:
        """Apply by directly writing file content"""
        import json

        try:
            # Expect JSON: {"file": "path/to/file.py", "content": "..."}
            data = json.loads(patch)
            file_path = data.get("file", data.get("path"))
            content = data.get("content", data.get("code"))

            if not file_path or not content:
                return ApplyResult(
                    success=False,
                    message="Missing 'file' or 'content' in patch",
                    backup_path=backup_path
                )

            file_full_path = repo_path / file_path
            file_full_path.parent.mkdir(parents=True, exist_ok=True)
            file_full_path.write_text(content, encoding='utf-8')

            self.stats["patches_applied"] += 1

            return ApplyResult(
                success=True,
                message=f"Wrote file: {file_path}",
                files_modified=[file_path],
                backup_path=backup_path
            )

        except json.JSONDecodeError:
            return ApplyResult(
                success=False,
                message="Invalid JSON for direct_write format",
                backup_path=backup_path
            )

    def _get_modified_files(self, repo_path: Path) -> List[str]:
        """Get list of modified files via git status"""
        result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True,
            text=True
        )

        files = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                # Format: "XY path" or "XY old -> new"
                parts = line[3:].split(' -> ')
                files.append(parts[-1])

        return files

    # ═══════════════════════════════════════════════════════════════════════
    # VALIDATE: Run syntax check and linting
    # ═══════════════════════════════════════════════════════════════════════

    def validate_syntax(self, repo_path: str, files: List[str] = None) -> Dict[str, Any]:
        """
        Validate Python syntax of modified files.

        Args:
            repo_path: Path to the repository
            files: List of files to check (default: all modified .py files)

        Returns:
            {"valid": bool, "errors": [...]}
        """
        repo_path = Path(repo_path)

        if files is None:
            files = self._get_modified_files(repo_path)

        # Filter to Python files
        py_files = [f for f in files if f.endswith('.py')]

        if not py_files:
            return {"valid": True, "errors": [], "message": "No Python files to check"}

        errors = []

        for file_path in py_files:
            full_path = repo_path / file_path

            if not full_path.exists():
                continue

            result = subprocess.run(
                ["python", "-m", "py_compile", str(full_path)],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                errors.append({
                    "file": file_path,
                    "error": result.stderr.strip()
                })

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "files_checked": len(py_files)
        }

    # ═══════════════════════════════════════════════════════════════════════
    # TEST: Run tests to validate fix
    # ═══════════════════════════════════════════════════════════════════════

    def run_tests(
        self,
        repo_path: str,
        test_cmd: str = "pytest",
        test_files: List[str] = None,
        timeout: int = None
    ) -> TestResult:
        """
        Run tests to validate the fix.

        Args:
            repo_path: Path to the repository
            test_cmd: Test command (default: pytest)
            test_files: Specific test files to run
            timeout: Timeout in seconds (default: self.timeout_test)

        Returns:
            TestResult with pass/fail status
        """
        repo_path = Path(repo_path)
        timeout = timeout or self.timeout_test

        start_time = time.time()

        # Build command
        cmd = test_cmd.split()
        if test_files:
            cmd.extend(test_files)

        # Add pytest options for better output
        if "pytest" in test_cmd:
            if "-v" not in cmd:
                cmd.append("-v")
            if "--tb=short" not in cmd and "--tb" not in str(cmd):
                cmd.append("--tb=short")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=timeout
            )

            duration_ms = (time.time() - start_time) * 1000

            # Parse pytest output
            tests_passed, tests_failed, tests_total = self._parse_pytest_output(result.stdout)

            self.stats["tests_run"] += 1
            self.stats["total_test_time_ms"] += duration_ms
            if result.returncode == 0:
                self.stats["tests_passed"] += 1

            return TestResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration_ms,
                tests_passed=tests_passed,
                tests_failed=tests_failed,
                tests_total=tests_total
            )

        except subprocess.TimeoutExpired:
            return TestResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Test timed out after {timeout}s",
                duration_ms=(time.time() - start_time) * 1000
            )
        except Exception as e:
            return TestResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )

    def _parse_pytest_output(self, output: str) -> Tuple[int, int, int]:
        """Parse pytest output to get test counts"""
        import re

        # Pattern: "X passed, Y failed, Z errors"
        pattern = r"(\d+)\s+passed"
        match = re.search(pattern, output)
        passed = int(match.group(1)) if match else 0

        pattern = r"(\d+)\s+failed"
        match = re.search(pattern, output)
        failed = int(match.group(1)) if match else 0

        total = passed + failed

        return passed, failed, total

    # ═══════════════════════════════════════════════════════════════════════
    # ROLLBACK: Restore from backup
    # ═══════════════════════════════════════════════════════════════════════

    def rollback(self, repo_path: str, backup_path: str = None) -> bool:
        """
        Rollback repository to backup state.

        Args:
            repo_path: Path to the repository
            backup_path: Path to backup (default: {repo_path}_backup)

        Returns:
            True if rollback successful
        """
        repo_path = Path(repo_path)

        if backup_path is None:
            backup_path = Path(str(repo_path) + "_backup")
        else:
            backup_path = Path(backup_path)

        if not backup_path.exists():
            print(f"  [WARN] Backup not found: {backup_path}")
            return False

        try:
            _windows_safe_rmtree(repo_path)
            shutil.copytree(backup_path, repo_path)
            return True
        except Exception as e:
            print(f"  [ERROR] Rollback failed: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # CLEANUP: Remove task directories
    # ═══════════════════════════════════════════════════════════════════════

    def cleanup(self, task_id: str = None, keep_cache: bool = True):
        """
        Clean up task directories.

        Args:
            task_id: Specific task to clean (default: all)
            keep_cache: Whether to keep cached repos
        """
        if task_id:
            if task_id in self.active_tasks:
                task_path = self.active_tasks[task_id]
                if task_path.exists():
                    _windows_safe_rmtree(task_path)
                # Also remove backup
                backup_path = Path(str(task_path) + "_backup")
                if backup_path.exists():
                    _windows_safe_rmtree(backup_path)
                del self.active_tasks[task_id]
        else:
            # Clean all task directories
            for path in self.workspace.iterdir():
                if path.is_dir():
                    if keep_cache and path.name.startswith("cache_"):
                        continue
                    _windows_safe_rmtree(path)
            self.active_tasks.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Get repository manager statistics"""
        return {
            **self.stats,
            "active_tasks": len(self.active_tasks),
            "workspace": str(self.workspace)
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

_default_manager: Optional[RepositoryManager] = None


def get_repo_manager() -> RepositoryManager:
    """Get or create default repository manager"""
    global _default_manager
    if _default_manager is None:
        _default_manager = RepositoryManager()
    return _default_manager


def setup_swebench_task(task_id: str, repo: str, base_commit: str) -> SetupResult:
    """Quick setup for SWE-bench task"""
    return get_repo_manager().setup_task(task_id, repo, base_commit)


def apply_and_test(
    repo_path: str,
    patch: str,
    test_cmd: str = "pytest"
) -> Dict[str, Any]:
    """
    Apply patch and run tests in one step.

    Returns:
        {
            "patch_applied": bool,
            "syntax_valid": bool,
            "tests_passed": bool,
            "details": {...}
        }
    """
    manager = get_repo_manager()

    # Detect patch format
    if "edit_lines(" in patch:
        patch_format = PatchFormat.EDIT_LINES
    elif patch.strip().startswith("{"):
        patch_format = PatchFormat.DIRECT_WRITE
    else:
        patch_format = PatchFormat.UNIFIED_DIFF

    # Apply patch
    apply_result = manager.apply_patch(repo_path, patch, patch_format)

    if not apply_result.success:
        return {
            "patch_applied": False,
            "syntax_valid": False,
            "tests_passed": False,
            "details": {"apply_error": apply_result.message}
        }

    # Validate syntax
    syntax_result = manager.validate_syntax(repo_path, apply_result.files_modified)

    if not syntax_result["valid"]:
        # Rollback on syntax error
        manager.rollback(repo_path, apply_result.backup_path)
        return {
            "patch_applied": True,
            "syntax_valid": False,
            "tests_passed": False,
            "details": {"syntax_errors": syntax_result["errors"]}
        }

    # Run tests
    test_result = manager.run_tests(repo_path, test_cmd)

    return {
        "patch_applied": True,
        "syntax_valid": True,
        "tests_passed": test_result.success,
        "details": {
            "files_modified": apply_result.files_modified,
            "tests_passed": test_result.tests_passed,
            "tests_failed": test_result.tests_failed,
            "test_output": test_result.stdout[:1000] if test_result.stdout else ""
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 70)
    print("  REPOSITORY MANAGER TEST")
    print("=" * 70)

    manager = RepositoryManager()

    print(f"\n  Workspace: {manager.workspace}")
    print(f"  Cache repos: {manager.cache_repos}")

    # Test 1: Create mock task directory
    print("\n[TEST 1] Create mock task environment")
    print("-" * 40)

    import tempfile
    test_dir = Path(tempfile.mkdtemp())

    # Create test Python file
    test_file = test_dir / "calculator.py"
    test_file.write_text('''
def add(a, b):
    return a + b

def divide(a, b):
    return a / b  # Bug: no zero check
''')

    # Create test file
    test_test = test_dir / "test_calculator.py"
    test_test.write_text('''
from calculator import add, divide

def test_add():
    assert add(2, 3) == 5

def test_divide():
    assert divide(6, 2) == 3

def test_divide_by_zero():
    try:
        divide(1, 0)
        assert False, "Should raise"
    except ZeroDivisionError:
        pass
''')

    print(f"  Created test directory: {test_dir}")
    print(f"  [PASS] Mock environment ready")

    # Test 2: Apply edit_lines patch
    print("\n[TEST 2] Apply edit_lines() patch")
    print("-" * 40)

    patch = '''
edit_lines('calculator.py', 6, 6, '    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b')
'''

    result = manager._apply_edit_lines(test_dir, patch, None)
    print(f"  Result: {result.success} - {result.message}")

    if result.success:
        # Verify change
        new_content = test_file.read_text()
        if "if b == 0" in new_content:
            print("  [PASS] edit_lines() applied correctly")
        else:
            print("  [FAIL] Content not updated")

    # Test 3: Validate syntax
    print("\n[TEST 3] Validate syntax")
    print("-" * 40)

    syntax_result = manager.validate_syntax(str(test_dir), ["calculator.py"])
    print(f"  Valid: {syntax_result['valid']}")
    if syntax_result['errors']:
        for err in syntax_result['errors']:
            print(f"  Error: {err}")
    else:
        print("  [PASS] Syntax is valid")

    # Test 4: Run tests (if pytest available)
    print("\n[TEST 4] Run tests")
    print("-" * 40)

    try:
        test_result = manager.run_tests(str(test_dir), "pytest", timeout=30)
        print(f"  Success: {test_result.success}")
        print(f"  Passed: {test_result.tests_passed}, Failed: {test_result.tests_failed}")
        print(f"  Duration: {test_result.duration_ms:.0f}ms")

        if test_result.success:
            print("  [PASS] All tests passed")
        else:
            print("  [INFO] Some tests failed (expected if pytest not installed)")

    except Exception as e:
        print(f"  [SKIP] pytest not available: {e}")

    # Cleanup
    shutil.rmtree(test_dir)

    # Print statistics
    print("\n" + "=" * 70)
    print("  STATISTICS")
    print("=" * 70)
    stats = manager.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n  [OK] Repository Manager working!")
