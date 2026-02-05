# -*- coding: utf-8 -*-
"""
Test Autonomous Workflow with Human-in-the-Loop Approval
=========================================================

This test simulates a complete autonomous agent workflow:
1. User submits a complex task
2. Agent breaks it down into steps
3. Agent executes steps autonomously
4. When dangerous operations are needed - asks for user approval
5. User can approve/reject via API or interactive console
6. Task completes with full report

Usage:
    # Run with simulated auto-approval (for CI/CD)
    python test_autonomous_workflow.py --auto

    # Run with interactive approval (manual testing)
    python test_autonomous_workflow.py --interactive

    # Run with API approval (frontend simulation)
    python test_autonomous_workflow.py --api

Author: QwenCode Team
Date: 2026-02-05
"""

import asyncio
import json
import sys
import time
import threading
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

# Add project root to path
sys.path.insert(0, 'C:/Users/serga/QwenAgent')

from core.approval_manager import (
    ApprovalManager, ApprovalRequest, ApprovalChoice,
    RiskLevel, RiskAssessor, get_approval_manager
)


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

@dataclass
class TestConfig:
    """Test configuration"""
    mode: str = "auto"  # auto, interactive, api
    server_url: str = "http://localhost:5002"
    approval_timeout: float = 30.0
    auto_approve_delay: float = 1.0  # Delay before auto-approve (for visibility)
    verbose: bool = True


# =============================================================================
# TASK DEFINITION
# =============================================================================

@dataclass
class TaskStep:
    """A single step in the task"""
    id: str
    name: str
    tool: str
    params: Dict[str, Any]
    description: str
    risk_level: RiskLevel = RiskLevel.MODERATE
    depends_on: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed, skipped
    result: Optional[Dict[str, Any]] = None


@dataclass
class AutonomousTask:
    """A complete autonomous task with multiple steps"""
    id: str
    name: str
    description: str
    steps: List[TaskStep]
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: str = "pending"


# =============================================================================
# TEST SCENARIOS
# =============================================================================

def create_test_task_simple() -> AutonomousTask:
    """Create a simple test task: Create and modify a file"""
    return AutonomousTask(
        id="task_001",
        name="Create and Modify Test File",
        description="Create a Python file, add a function, then modify it",
        steps=[
            TaskStep(
                id="step_1",
                name="Create test file",
                tool="write",
                params={
                    "file_path": "test_autonomous_output.py",
                    "content": "# Auto-generated test file\n\ndef hello():\n    return 'Hello'\n"
                },
                description="Create test_autonomous_output.py with hello() function",
                risk_level=RiskLevel.MODERATE
            ),
            TaskStep(
                id="step_2",
                name="Verify file created",
                tool="read",
                params={"file_path": "test_autonomous_output.py"},
                description="Read the created file to verify",
                risk_level=RiskLevel.SAFE,
                depends_on=["step_1"]
            ),
            TaskStep(
                id="step_3",
                name="Modify function",
                tool="edit",
                params={
                    "file_path": "test_autonomous_output.py",
                    "old_string": "return 'Hello'",
                    "new_string": "return 'Hello, World!'"
                },
                description="Change return value from 'Hello' to 'Hello, World!'",
                risk_level=RiskLevel.MODERATE,
                depends_on=["step_2"]
            ),
            TaskStep(
                id="step_4",
                name="Add new function",
                tool="edit",
                params={
                    "file_path": "test_autonomous_output.py",
                    "old_string": "return 'Hello, World!'",
                    "new_string": "return 'Hello, World!'\n\ndef goodbye():\n    return 'Goodbye!'"
                },
                description="Add goodbye() function after hello()",
                risk_level=RiskLevel.MODERATE,
                depends_on=["step_3"]
            ),
            TaskStep(
                id="step_5",
                name="Final verification",
                tool="read",
                params={"file_path": "test_autonomous_output.py"},
                description="Read final file content",
                risk_level=RiskLevel.SAFE,
                depends_on=["step_4"]
            )
        ]
    )


def create_test_task_with_dangerous_ops() -> AutonomousTask:
    """Create a task with dangerous operations that need approval"""
    return AutonomousTask(
        id="task_002",
        name="Task with Dangerous Operations",
        description="Task that includes bash commands and file deletion",
        steps=[
            TaskStep(
                id="step_1",
                name="Create temp file",
                tool="write",
                params={
                    "file_path": "temp_dangerous_test.txt",
                    "content": "This file will be deleted\n"
                },
                description="Create a temporary test file",
                risk_level=RiskLevel.MODERATE
            ),
            TaskStep(
                id="step_2",
                name="List directory",
                tool="bash",
                params={"command": "ls -la *.txt"},
                description="List all .txt files (DANGEROUS: bash command)",
                risk_level=RiskLevel.DANGEROUS,
                depends_on=["step_1"]
            ),
            TaskStep(
                id="step_3",
                name="Delete temp file",
                tool="bash",
                params={"command": "rm temp_dangerous_test.txt"},
                description="Delete the temporary file (DANGEROUS: rm command)",
                risk_level=RiskLevel.DANGEROUS,
                depends_on=["step_2"]
            ),
            TaskStep(
                id="step_4",
                name="Verify deletion",
                tool="bash",
                params={"command": "ls temp_dangerous_test.txt 2>&1 || echo 'File deleted successfully'"},
                description="Verify the file was deleted",
                risk_level=RiskLevel.DANGEROUS,
                depends_on=["step_3"]
            )
        ]
    )


def create_test_task_multi_file() -> AutonomousTask:
    """Create a task that works with multiple files"""
    return AutonomousTask(
        id="task_003",
        name="Multi-File Project Setup",
        description="Create a simple Python project structure",
        steps=[
            TaskStep(
                id="step_1",
                name="Create main.py",
                tool="write",
                params={
                    "file_path": "test_project/main.py",
                    "content": "#!/usr/bin/env python3\nfrom utils import greet\n\nif __name__ == '__main__':\n    print(greet('User'))\n"
                },
                description="Create main entry point",
                risk_level=RiskLevel.MODERATE
            ),
            TaskStep(
                id="step_2",
                name="Create utils.py",
                tool="write",
                params={
                    "file_path": "test_project/utils.py",
                    "content": "def greet(name: str) -> str:\n    return f'Hello, {name}!'\n"
                },
                description="Create utility module",
                risk_level=RiskLevel.MODERATE,
                depends_on=["step_1"]
            ),
            TaskStep(
                id="step_3",
                name="Create __init__.py",
                tool="write",
                params={
                    "file_path": "test_project/__init__.py",
                    "content": "# Test Project Package\n__version__ = '1.0.0'\n"
                },
                description="Create package init file",
                risk_level=RiskLevel.MODERATE,
                depends_on=["step_2"]
            ),
            TaskStep(
                id="step_4",
                name="Run project",
                tool="bash",
                params={"command": "cd test_project && python main.py"},
                description="Execute the project (DANGEROUS: bash)",
                risk_level=RiskLevel.DANGEROUS,
                depends_on=["step_3"]
            )
        ]
    )


# =============================================================================
# AUTONOMOUS EXECUTOR
# =============================================================================

class AutonomousExecutor:
    """
    Executes tasks autonomously with human-in-the-loop approval.
    """

    def __init__(self, config: TestConfig):
        self.config = config
        self.approval_manager = ApprovalManager(
            default_timeout=config.approval_timeout,
            auto_approve_safe=True,
            auto_approve_low=True,
            auto_approve_moderate=False,  # Need approval for moderate+
            on_approval_needed=self._on_approval_needed,
            on_approval_resolved=self._on_approval_resolved
        )
        self.current_task: Optional[AutonomousTask] = None
        self.execution_log: List[Dict[str, Any]] = []

    def _log(self, message: str, level: str = "INFO"):
        """Log a message"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message
        }
        self.execution_log.append(entry)
        if self.config.verbose:
            prefix = {"INFO": "[*]", "WARN": "[!]", "ERROR": "[X]", "OK": "[+]", "WAIT": "[?]"}
            print(f"{prefix.get(level, '[.]')} {timestamp} {message}")

    def _on_approval_needed(self, request: ApprovalRequest):
        """Callback when approval is needed"""
        self._log(f"APPROVAL NEEDED: {request.tool} - {request.description}", "WAIT")
        self._log(f"  Risk Level: {request.risk_level.value}", "WAIT")
        self._log(f"  Request ID: {request.id}", "WAIT")

        if self.config.mode == "auto":
            # Auto-approve after delay (for testing)
            threading.Thread(
                target=self._auto_approve,
                args=(request.id,),
                daemon=True
            ).start()
        elif self.config.mode == "interactive":
            # Show interactive prompt
            threading.Thread(
                target=self._interactive_approve,
                args=(request,),
                daemon=True
            ).start()

    def _on_approval_resolved(self, request: ApprovalRequest):
        """Callback when approval is resolved"""
        status = "APPROVED" if request.status.value == "approved" else "REJECTED"
        self._log(f"APPROVAL {status}: {request.tool} (choice: {request.choice.value if request.choice else 'none'})", "OK" if status == "APPROVED" else "WARN")

    def _auto_approve(self, request_id: str):
        """Auto-approve after delay"""
        time.sleep(self.config.auto_approve_delay)
        self._log(f"AUTO-APPROVING: {request_id}", "OK")
        self.approval_manager.approve(request_id)

    def _interactive_approve(self, request: ApprovalRequest):
        """Interactive approval via console"""
        print("\n" + "=" * 60)
        print("APPROVAL REQUIRED")
        print("=" * 60)
        print(f"Tool: {request.tool}")
        print(f"Description: {request.description}")
        print(f"Risk Level: {request.risk_level.value}")
        print(f"Params: {json.dumps(request.params, indent=2)}")
        print("-" * 60)
        print("Options:")
        print("  [y] Yes - Execute this operation")
        print("  [n] No  - Skip this operation")
        print("  [a] Yes, and... - Execute with modifications")
        print("  [x] Abort - Abort entire task")
        print("-" * 60)

        try:
            choice = input("Your choice [y/n/a/x]: ").strip().lower()
            user_input = None

            if choice == 'a':
                user_input = input("Modifications: ").strip()

            self.approval_manager.respond_by_key(request.id, choice, user_input)
        except EOFError:
            # Non-interactive mode
            self._log("Non-interactive mode, auto-approving", "WARN")
            self.approval_manager.approve(request.id)

    async def _execute_tool(self, step: TaskStep) -> Dict[str, Any]:
        """Execute a single tool via API"""
        if self.config.mode == "api":
            # Use server API
            try:
                response = requests.post(
                    f"{self.config.server_url}/api/chat",
                    json={"message": self._build_tool_command(step)},
                    timeout=30
                )
                return response.json()
            except Exception as e:
                return {"success": False, "error": str(e)}
        else:
            # Direct execution (simulation)
            return await self._simulate_tool_execution(step)

    def _build_tool_command(self, step: TaskStep) -> str:
        """Build natural language command for tool"""
        if step.tool == "write":
            return f"write file {step.params['file_path']} with content: {step.params['content'][:50]}..."
        elif step.tool == "read":
            return f"read file {step.params['file_path']}"
        elif step.tool == "edit":
            return f"in file {step.params['file_path']} replace \"{step.params['old_string']}\" with \"{step.params['new_string']}\""
        elif step.tool == "bash":
            return f"run command: {step.params['command']}"
        else:
            return f"{step.tool}: {json.dumps(step.params)}"

    async def _simulate_tool_execution(self, step: TaskStep) -> Dict[str, Any]:
        """Simulate tool execution for testing"""
        # Simulate execution time
        await asyncio.sleep(0.5)

        # For testing, return success
        return {
            "success": True,
            "tool": step.tool,
            "result": f"Simulated {step.tool} execution",
            "params": step.params
        }

    async def _request_approval_for_step(self, step: TaskStep) -> bool:
        """Request approval for a step if needed"""
        # Assess risk
        risk = RiskAssessor.assess(step.tool, step.params)

        # Override with step's declared risk if higher
        if step.risk_level.value > risk.value:
            risk = step.risk_level

        self._log(f"Risk assessment for {step.tool}: {risk.value}")

        # Check if approval needed
        if not RiskAssessor.needs_approval(step.tool, step.params, threshold=RiskLevel.MODERATE):
            self._log(f"Auto-approved (risk < MODERATE)")
            return True

        # Request approval
        result = await self.approval_manager.request_approval(
            step_id=step.id,
            tool=step.tool,
            description=step.description,
            params=step.params,
            risk_level=risk,
            context=self._build_tool_command(step)
        )

        return result["approved"]

    async def execute_task(self, task: AutonomousTask) -> Dict[str, Any]:
        """Execute a complete task autonomously"""
        self.current_task = task
        self._log(f"Starting task: {task.name}")
        self._log(f"Description: {task.description}")
        self._log(f"Total steps: {len(task.steps)}")
        self._log("-" * 40)

        task.status = "running"
        completed_steps = []
        failed_steps = []
        skipped_steps = []

        for step in task.steps:
            # Check dependencies
            unmet_deps = [d for d in step.depends_on if d not in completed_steps]
            if unmet_deps:
                self._log(f"Waiting for dependencies: {unmet_deps}", "WARN")
                # In real implementation, would wait or reorder
                # For now, continue if deps failed
                if any(d in failed_steps for d in step.depends_on):
                    self._log(f"Skipping {step.id}: dependency failed", "WARN")
                    step.status = "skipped"
                    skipped_steps.append(step.id)
                    continue

            self._log(f"Step {step.id}: {step.name}")
            step.status = "running"

            # Request approval if needed
            approved = await self._request_approval_for_step(step)

            if not approved:
                self._log(f"Step {step.id} REJECTED by user", "WARN")
                step.status = "skipped"
                skipped_steps.append(step.id)
                continue

            # Execute step
            try:
                result = await self._execute_tool(step)
                step.result = result

                if result.get("success", False):
                    step.status = "completed"
                    completed_steps.append(step.id)
                    self._log(f"Step {step.id} COMPLETED", "OK")
                else:
                    step.status = "failed"
                    failed_steps.append(step.id)
                    self._log(f"Step {step.id} FAILED: {result.get('error', 'Unknown error')}", "ERROR")

            except Exception as e:
                step.status = "failed"
                step.result = {"error": str(e)}
                failed_steps.append(step.id)
                self._log(f"Step {step.id} EXCEPTION: {e}", "ERROR")

        # Complete task
        task.completed_at = datetime.now()
        task.status = "completed" if not failed_steps else "partial"

        self._log("-" * 40)
        self._log(f"Task {task.status.upper()}")
        self._log(f"Completed: {len(completed_steps)}/{len(task.steps)}")
        self._log(f"Failed: {len(failed_steps)}")
        self._log(f"Skipped: {len(skipped_steps)}")

        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": task.status,
            "total_steps": len(task.steps),
            "completed": len(completed_steps),
            "failed": len(failed_steps),
            "skipped": len(skipped_steps),
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "skipped_steps": skipped_steps,
            "duration_ms": int((task.completed_at - task.created_at).total_seconds() * 1000),
            "approval_stats": self.approval_manager.get_stats()
        }


# =============================================================================
# TEST RUNNER
# =============================================================================

async def run_tests(config: TestConfig):
    """Run all test scenarios"""
    print("=" * 70)
    print("AUTONOMOUS WORKFLOW TEST")
    print(f"Mode: {config.mode}")
    print(f"Server: {config.server_url}")
    print("=" * 70)

    executor = AutonomousExecutor(config)
    results = []

    # Test 1: Simple file operations
    print("\n" + "=" * 70)
    print("TEST 1: Simple File Operations")
    print("=" * 70)
    task1 = create_test_task_simple()
    result1 = await executor.execute_task(task1)
    results.append(result1)
    print(f"\nResult: {json.dumps(result1, indent=2)}")

    # Test 2: Dangerous operations (if interactive or auto)
    if config.mode in ["auto", "interactive"]:
        print("\n" + "=" * 70)
        print("TEST 2: Dangerous Operations")
        print("=" * 70)
        task2 = create_test_task_with_dangerous_ops()
        result2 = await executor.execute_task(task2)
        results.append(result2)
        print(f"\nResult: {json.dumps(result2, indent=2)}")

    # Final summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    total_steps = sum(r["total_steps"] for r in results)
    total_completed = sum(r["completed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)

    print(f"Total Tests: {len(results)}")
    print(f"Total Steps: {total_steps}")
    print(f"Completed: {total_completed} ({100*total_completed/total_steps:.1f}%)")
    print(f"Failed: {total_failed}")
    print(f"Skipped: {total_skipped}")

    # Approval stats from last executor
    stats = executor.approval_manager.get_stats()
    print(f"\nApproval Statistics:")
    print(f"  Total requests: {stats['total_requests']}")
    print(f"  Auto-approved: {stats['auto_approved']}")
    print(f"  User-approved: {stats['user_approved']}")
    print(f"  User-rejected: {stats['user_rejected']}")
    print(f"  Timeouts: {stats['timeouts']}")

    print("\n" + "=" * 70)
    if total_failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"TESTS COMPLETED WITH {total_failed} FAILURES")
    print("=" * 70)

    return results


# =============================================================================
# API TEST (via server)
# =============================================================================

async def run_api_test(config: TestConfig):
    """Run test via actual server API"""
    print("=" * 70)
    print("API AUTONOMOUS WORKFLOW TEST")
    print(f"Server: {config.server_url}")
    print("=" * 70)

    # Check server health
    try:
        health = requests.get(f"{config.server_url}/api/health", timeout=5)
        health_data = health.json()
        print(f"Server status: {health_data.get('status', 'unknown')}")
    except Exception as e:
        print(f"Server not available: {e}")
        return

    # Create a multi-step task via natural language
    task_message = """
    Please do the following:
    1. Create a file called test_api_workflow.py with a simple hello function
    2. Read the file to verify it was created
    3. Edit the file to change 'Hello' to 'Hi there'
    4. Read the final content
    """

    print(f"\nSending task:\n{task_message}")
    print("-" * 70)

    try:
        response = requests.post(
            f"{config.server_url}/api/chat",
            json={"message": task_message},
            timeout=60
        )
        result = response.json()
        print(f"Response:\n{json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"API error: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Test Autonomous Workflow")
    parser.add_argument("--mode", choices=["auto", "interactive", "api"],
                        default="auto", help="Test mode")
    parser.add_argument("--server", default="http://localhost:5002",
                        help="Server URL for API mode")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="Approval timeout in seconds")
    parser.add_argument("--quiet", action="store_true",
                        help="Reduce output verbosity")

    args = parser.parse_args()

    config = TestConfig(
        mode=args.mode,
        server_url=args.server,
        approval_timeout=args.timeout,
        verbose=not args.quiet
    )

    if args.mode == "api":
        asyncio.run(run_api_test(config))
    else:
        asyncio.run(run_tests(config))


if __name__ == "__main__":
    main()
