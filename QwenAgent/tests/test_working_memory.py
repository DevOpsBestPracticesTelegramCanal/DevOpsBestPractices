"""
Tests for Week 2: WorkingMemory — structured scratchpad for multi-step tasks.
"""

import pytest
from core.working_memory import (
    WorkingMemory,
    PlanStep,
    StepStatus,
    ToolRecord,
    _basename,
)


# ------------------------------------------------------------------
# Basic construction
# ------------------------------------------------------------------

class TestWorkingMemoryBasic:
    def test_empty_memory(self):
        mem = WorkingMemory()
        assert mem.goal == ""
        assert mem.plan == []
        assert len(mem.facts) == 0
        assert mem.decisions == []
        assert mem.tool_log == []

    def test_goal_set(self):
        mem = WorkingMemory(goal="Fix import error in app.py")
        assert mem.goal == "Fix import error in app.py"

    def test_compact_empty(self):
        mem = WorkingMemory()
        output = mem.compact()
        assert "## Working Memory" in output
        # Empty memory should be short
        assert len(output) < 200


# ------------------------------------------------------------------
# Plan management
# ------------------------------------------------------------------

class TestPlanManagement:
    def test_set_plan(self):
        mem = WorkingMemory(goal="task")
        mem.set_plan(["Read file", "Find bug", "Fix it", "Run tests"])
        assert len(mem.plan) == 4
        assert mem.plan[0].status == StepStatus.ACTIVE
        assert mem.plan[1].status == StepStatus.PENDING

    def test_advance_step(self):
        mem = WorkingMemory(goal="task")
        mem.set_plan(["Step 1", "Step 2", "Step 3"])

        mem.advance_step()
        assert mem.plan[0].status == StepStatus.DONE
        assert mem.plan[1].status == StepStatus.ACTIVE
        assert mem.plan[2].status == StepStatus.PENDING

    def test_advance_past_end(self):
        mem = WorkingMemory(goal="task")
        mem.set_plan(["Only step"])
        mem.advance_step()  # done
        mem.advance_step()  # past end — should not crash
        assert mem.plan[0].status == StepStatus.DONE

    def test_skip_step(self):
        mem = WorkingMemory(goal="task")
        mem.set_plan(["Step 1", "Step 2"])
        mem.skip_step()
        assert mem.plan[0].status == StepStatus.SKIPPED
        assert mem.plan[1].status == StepStatus.ACTIVE

    def test_plan_progress(self):
        mem = WorkingMemory(goal="task")
        mem.set_plan(["A", "B", "C"])
        assert mem.plan_progress == "0/3 steps done"
        mem.advance_step()
        assert mem.plan_progress == "1/3 steps done"
        mem.advance_step()
        assert mem.plan_progress == "2/3 steps done"

    def test_current_step_description(self):
        mem = WorkingMemory(goal="task")
        mem.set_plan(["Read file", "Fix bug"])
        assert mem.current_step_description == "Read file"
        mem.advance_step()
        assert mem.current_step_description == "Fix bug"

    def test_plan_in_compact(self):
        mem = WorkingMemory(goal="Fix stuff")
        mem.set_plan(["Read file", "Fix bug", "Test"])
        mem.advance_step()  # Step 1 done, Step 2 active
        output = mem.compact()
        assert "PLAN:" in output
        assert "[done]" in output
        assert "[>>>]" in output
        assert "[...]" in output

    def test_plan_limit(self):
        mem = WorkingMemory(goal="task")
        mem.set_plan([f"Step {i}" for i in range(20)])
        assert len(mem.plan) == WorkingMemory.MAX_PLAN_STEPS


# ------------------------------------------------------------------
# Facts
# ------------------------------------------------------------------

class TestFacts:
    def test_add_and_get_fact(self):
        mem = WorkingMemory()
        mem.add_fact("file_content", "contains 3 routes")
        assert mem.get_fact("file_content") == "contains 3 routes"

    def test_overwrite_fact(self):
        mem = WorkingMemory()
        mem.add_fact("key", "old value")
        mem.add_fact("key", "new value")
        assert mem.get_fact("key") == "new value"
        assert len(mem.facts) == 1

    def test_fact_eviction(self):
        mem = WorkingMemory()
        # Add more than MAX_FACTS
        for i in range(WorkingMemory.MAX_FACTS + 5):
            mem.add_fact(f"key_{i}", f"value_{i}")
        assert len(mem.facts) == WorkingMemory.MAX_FACTS
        # Oldest should be evicted
        assert mem.get_fact("key_0") is None
        assert mem.get_fact(f"key_{WorkingMemory.MAX_FACTS + 4}") is not None

    def test_facts_in_compact(self):
        mem = WorkingMemory(goal="task")
        mem.add_fact("error", "ImportError on line 15")
        output = mem.compact()
        assert "FACTS:" in output
        assert "ImportError" in output


# ------------------------------------------------------------------
# Decisions
# ------------------------------------------------------------------

class TestDecisions:
    def test_record_decision(self):
        mem = WorkingMemory()
        mem.record_decision("Using absolute import to avoid circular dependency")
        assert len(mem.decisions) == 1

    def test_decision_limit(self):
        mem = WorkingMemory()
        for i in range(WorkingMemory.MAX_DECISIONS + 3):
            mem.record_decision(f"Decision {i}")
        assert len(mem.decisions) == WorkingMemory.MAX_DECISIONS

    def test_decisions_in_compact(self):
        mem = WorkingMemory(goal="task")
        mem.record_decision("Use absolute import")
        output = mem.compact()
        assert "DECISIONS:" in output
        assert "absolute import" in output


# ------------------------------------------------------------------
# Tool result auto-extraction
# ------------------------------------------------------------------

class TestToolResultExtraction:
    def test_read_result(self):
        mem = WorkingMemory(goal="task")
        result = {
            "success": True,
            "content": "import os\nimport sys\n\ndef main():\n    pass\n",
            "total_lines": 5,
        }
        mem.update_from_tool_result("read", {"file_path": "/src/app.py"}, result)

        assert len(mem.tool_log) == 1
        assert "read(app.py)" in mem.tool_log[0].summary
        assert mem.get_fact("file:app.py") is not None
        assert "5 lines" in mem.get_fact("file:app.py")

    def test_grep_result_with_matches(self):
        mem = WorkingMemory(goal="task")
        result = {
            "success": True,
            "matches": [
                {"file": "a.py", "line_number": 10, "line": "import broken"},
                {"file": "b.py", "line_number": 20, "line": "import broken"},
            ],
        }
        mem.update_from_tool_result("grep", {"pattern": "broken"}, result)

        assert len(mem.tool_log) == 1
        fact = mem.get_fact("grep:broken")
        assert fact is not None
        assert "2 matches" in fact

    def test_grep_result_no_matches(self):
        mem = WorkingMemory(goal="task")
        result = {"success": True, "matches": []}
        mem.update_from_tool_result("grep", {"pattern": "xyz"}, result)
        assert mem.get_fact("grep:xyz") == "no matches"

    def test_bash_result(self):
        mem = WorkingMemory(goal="task")
        result = {
            "success": True,
            "stdout": "tests passed: 42\n",
            "exit_code": 0,
        }
        mem.update_from_tool_result("bash", {"command": "pytest tests/"}, result)
        fact = mem.get_fact("bash:pytest tests/")
        assert fact is not None
        assert "exit=0" in fact

    def test_glob_result(self):
        mem = WorkingMemory(goal="task")
        result = {
            "success": True,
            "files": ["src/a.py", "src/b.py", "src/c.py"],
        }
        mem.update_from_tool_result("glob", {"pattern": "src/*.py"}, result)
        fact = mem.get_fact("glob:src/*.py")
        assert "3 files" in fact

    def test_edit_result(self):
        mem = WorkingMemory(goal="task")
        result = {"success": True}
        mem.update_from_tool_result("edit", {"file_path": "/src/app.py"}, result)
        fact = mem.get_fact("modified:app.py")
        assert "edit applied" in fact

    def test_write_result(self):
        mem = WorkingMemory(goal="task")
        result = {"success": True}
        mem.update_from_tool_result("write", {"file_path": "/src/new.py"}, result)
        assert mem.get_fact("modified:new.py") is not None

    def test_error_result(self):
        mem = WorkingMemory(goal="task")
        result = {"success": False, "error": "FileNotFoundError: /missing.py"}
        mem.update_from_tool_result("read", {"file_path": "/missing.py"}, result)
        # Should record the error as a fact
        assert any("FileNotFoundError" in v for v in mem.facts.values())

    def test_ls_result(self):
        mem = WorkingMemory(goal="task")
        result = {
            "success": True,
            "items": [
                {"name": "foo.py", "type": "file"},
                {"name": "bar/", "type": "dir"},
            ],
        }
        mem.update_from_tool_result("ls", {"path": "/src"}, result)
        fact = mem.get_fact("ls:src")
        assert "2 items" in fact

    def test_tool_log_limit(self):
        mem = WorkingMemory(goal="task")
        for i in range(WorkingMemory.MAX_TOOL_LOG + 5):
            mem.update_from_tool_result(
                "bash", {"command": f"cmd_{i}"}, {"success": True, "stdout": "", "exit_code": 0}
            )
        assert len(mem.tool_log) == WorkingMemory.MAX_TOOL_LOG


# ------------------------------------------------------------------
# Compact output
# ------------------------------------------------------------------

class TestCompact:
    def test_full_compact(self):
        mem = WorkingMemory(goal="Fix import error in app.py")
        mem.set_plan(["Read app.py", "Find broken import", "Fix it"])
        mem.add_fact("file:app.py", "45 lines, Flask app with 3 routes")
        mem.add_fact("error", "ImportError on line 15")
        mem.record_decision("Use absolute import instead of relative")
        mem.update_from_tool_result(
            "read", {"file_path": "app.py"}, {"success": True, "content": "...", "total_lines": 45}
        )

        output = mem.compact()

        assert "## Working Memory" in output
        assert "GOAL:" in output
        assert "Fix import error" in output
        assert "PLAN:" in output
        assert "FACTS:" in output
        assert "DECISIONS:" in output
        assert "RECENT:" in output

    def test_compact_respects_max_chars(self):
        mem = WorkingMemory(goal="task")
        # Add lots of data
        for i in range(15):
            mem.add_fact(f"long_key_{i}", "x" * 200)
        for i in range(5):
            mem.record_decision("y" * 100)

        output = mem.compact(max_chars=500)
        assert len(output) <= 500

    def test_compact_without_plan(self):
        """compact() should work without a plan set."""
        mem = WorkingMemory(goal="simple task")
        mem.add_fact("result", "42")
        output = mem.compact()
        assert "GOAL:" in output
        assert "PLAN:" not in output  # No plan set
        assert "FACTS:" in output


# ------------------------------------------------------------------
# Serialization
# ------------------------------------------------------------------

class TestSerialization:
    def test_round_trip(self):
        mem = WorkingMemory(goal="Serialize test")
        mem.set_plan(["Step 1", "Step 2"])
        mem.advance_step()
        mem.add_fact("key1", "val1")
        mem.record_decision("decision A")
        mem.update_from_tool_result(
            "read", {"file_path": "test.py"}, {"success": True, "content": "hello", "total_lines": 1}
        )

        data = mem.to_dict()
        mem2 = WorkingMemory.from_dict(data)

        assert mem2.goal == "Serialize test"
        assert len(mem2.plan) == 2
        assert mem2.plan[0].status == StepStatus.DONE
        assert mem2.plan[1].status == StepStatus.ACTIVE
        assert mem2.get_fact("key1") == "val1"
        assert len(mem2.decisions) == 1
        assert len(mem2.tool_log) == 1


# ------------------------------------------------------------------
# Clear
# ------------------------------------------------------------------

class TestClear:
    def test_clear(self):
        mem = WorkingMemory(goal="task")
        mem.set_plan(["A", "B"])
        mem.add_fact("k", "v")
        mem.record_decision("d")
        mem.update_from_tool_result("bash", {"command": "ls"}, {"success": True, "stdout": "", "exit_code": 0})

        mem.clear()

        assert mem.goal == ""
        assert mem.plan == []
        assert len(mem.facts) == 0
        assert mem.decisions == []
        assert mem.tool_log == []


# ------------------------------------------------------------------
# Helper: _basename
# ------------------------------------------------------------------

class TestBasename:
    def test_unix_path(self):
        assert _basename("/home/user/app.py") == "app.py"

    def test_windows_path(self):
        assert _basename("C:\\Users\\app.py") == "app.py"

    def test_filename_only(self):
        assert _basename("app.py") == "app.py"

    def test_empty(self):
        assert _basename("") == "?"

    def test_trailing_slash(self):
        assert _basename("/src/dir/") == "dir"
