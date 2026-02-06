"""
Working Memory — structured scratchpad for multi-step agent tasks.

Solves the "forgetting problem": after 3-4 tool-loop iterations the LLM
loses track of the original goal, what it discovered, and what remains.

WorkingMemory auto-extracts facts from tool results and produces a
compact, token-budgeted prompt section that is injected before each
LLM continuation call.

Usage:
    memory = WorkingMemory(goal="Fix the import error in app.py")
    memory.set_plan(["Read app.py", "Find the broken import", "Fix it", "Run tests"])

    # After each tool call:
    memory.update_from_tool_result("read", {"file_path": "app.py"}, result)

    # Before next LLM call:
    prompt = memory.compact() + "\\n" + tool_results_text
"""

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class StepStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """A single step in the task plan."""
    description: str
    status: StepStatus = StepStatus.PENDING


@dataclass
class ToolRecord:
    """Compressed record of a single tool invocation."""
    tool: str
    summary: str  # e.g. "read(app.py) -> 45 lines"
    success: bool = True


class WorkingMemory:
    """
    Structured scratchpad that persists across tool-loop iterations.

    Designed for small LLMs (7B-32B) that lose coherence after a few
    iterations. The compact() method produces a short, structured section
    that keeps the model on track.
    """

    # Limits to keep the compact output small
    MAX_FACTS = 15
    MAX_DECISIONS = 5
    MAX_TOOL_LOG = 10
    MAX_PLAN_STEPS = 10

    def __init__(self, goal: str = ""):
        self.goal: str = goal
        self.plan: List[PlanStep] = []
        self.facts: OrderedDict[str, str] = OrderedDict()
        self.decisions: List[str] = []
        self.tool_log: List[ToolRecord] = []
        self._current_step: int = 0
        self._iteration: int = 0

    # ------------------------------------------------------------------
    # Plan management
    # ------------------------------------------------------------------

    def set_plan(self, steps: List[str]) -> None:
        """Set the task plan from a list of step descriptions."""
        self.plan = [PlanStep(description=s) for s in steps[:self.MAX_PLAN_STEPS]]
        if self.plan:
            self.plan[0].status = StepStatus.ACTIVE
            self._current_step = 0

    def advance_step(self) -> None:
        """Mark current step done and activate the next one."""
        if not self.plan:
            return
        if self._current_step < len(self.plan):
            self.plan[self._current_step].status = StepStatus.DONE
        self._current_step += 1
        if self._current_step < len(self.plan):
            self.plan[self._current_step].status = StepStatus.ACTIVE

    def skip_step(self) -> None:
        """Skip the current step."""
        if not self.plan:
            return
        if self._current_step < len(self.plan):
            self.plan[self._current_step].status = StepStatus.SKIPPED
        self._current_step += 1
        if self._current_step < len(self.plan):
            self.plan[self._current_step].status = StepStatus.ACTIVE

    @property
    def current_step_description(self) -> str:
        """Description of the current active step, or empty string."""
        if self.plan and self._current_step < len(self.plan):
            return self.plan[self._current_step].description
        return ""

    @property
    def plan_progress(self) -> str:
        """e.g. '2/5 steps done'"""
        if not self.plan:
            return ""
        done = sum(1 for s in self.plan if s.status == StepStatus.DONE)
        return f"{done}/{len(self.plan)} steps done"

    # ------------------------------------------------------------------
    # Facts (key-value discoveries)
    # ------------------------------------------------------------------

    def add_fact(self, key: str, value: str) -> None:
        """Store a discovered fact.  Overwrites if key already exists."""
        # Move to end (most recent) if already present
        if key in self.facts:
            del self.facts[key]
        self.facts[key] = value
        # Evict oldest if over limit
        while len(self.facts) > self.MAX_FACTS:
            self.facts.popitem(last=False)

    def get_fact(self, key: str) -> Optional[str]:
        return self.facts.get(key)

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def record_decision(self, decision: str) -> None:
        """Record a decision with rationale."""
        self.decisions.append(decision)
        if len(self.decisions) > self.MAX_DECISIONS:
            self.decisions = self.decisions[-self.MAX_DECISIONS:]

    # ------------------------------------------------------------------
    # Tool result processing (auto-extraction)
    # ------------------------------------------------------------------

    def update_from_tool_result(
        self, tool_name: str, params: Dict[str, Any], result: Dict[str, Any]
    ) -> None:
        """
        Auto-extract key facts from a tool result and append to tool log.
        This is the main integration point — called after every tool execution.
        """
        self._iteration += 1
        success = result.get("success", True)
        summary = self._extract_summary(tool_name, params, result)

        # Append to tool log
        self.tool_log.append(ToolRecord(
            tool=tool_name,
            summary=summary,
            success=success,
        ))
        if len(self.tool_log) > self.MAX_TOOL_LOG:
            self.tool_log = self.tool_log[-self.MAX_TOOL_LOG:]

        # Auto-extract facts based on tool type
        if not success:
            error_msg = result.get("error", "unknown error")
            self.add_fact(f"error_{self._iteration}", str(error_msg)[:200])
            return

        if tool_name == "read":
            self._extract_read_facts(params, result)
        elif tool_name == "grep":
            self._extract_grep_facts(params, result)
        elif tool_name in ("bash", "git"):
            self._extract_bash_facts(tool_name, params, result)
        elif tool_name == "glob":
            self._extract_glob_facts(params, result)
        elif tool_name in ("edit", "write"):
            self._extract_write_facts(tool_name, params, result)
        elif tool_name == "ls":
            self._extract_ls_facts(params, result)

    def _extract_summary(
        self, tool_name: str, params: Dict[str, Any], result: Dict[str, Any]
    ) -> str:
        """One-line summary of a tool call for the tool log."""
        success = result.get("success", True)
        status = "OK" if success else "FAIL"

        if tool_name == "read":
            path = params.get("file_path", params.get("path", "?"))
            lines = result.get("total_lines", "?")
            return f"read({_basename(path)}) -> {lines} lines [{status}]"
        elif tool_name == "grep":
            pattern = params.get("pattern", "?")
            matches = len(result.get("matches", []))
            return f"grep({pattern}) -> {matches} matches [{status}]"
        elif tool_name in ("bash", "git"):
            cmd = params.get("command", "?")
            return f"{tool_name}({cmd[:40]}) [{status}]"
        elif tool_name == "glob":
            pattern = params.get("pattern", "?")
            files = len(result.get("files", []))
            return f"glob({pattern}) -> {files} files [{status}]"
        elif tool_name in ("edit", "write"):
            path = params.get("file_path", params.get("path", "?"))
            return f"{tool_name}({_basename(path)}) [{status}]"
        elif tool_name == "ls":
            path = params.get("path", params.get("directory", "?"))
            items = len(result.get("items", []))
            return f"ls({_basename(path)}) -> {items} items [{status}]"
        else:
            return f"{tool_name}() [{status}]"

    def _extract_read_facts(self, params: Dict, result: Dict) -> None:
        path = params.get("file_path", params.get("path", "unknown"))
        content = result.get("content", "")
        total_lines = result.get("total_lines", len(content.splitlines()))
        # Store a brief summary of the file content
        preview = content[:300].replace("\n", " ").strip()
        if preview:
            self.add_fact(f"file:{_basename(path)}", f"{total_lines} lines. {preview}...")

    def _extract_grep_facts(self, params: Dict, result: Dict) -> None:
        pattern = params.get("pattern", "?")
        matches = result.get("matches", [])
        if matches:
            match_files = list(set(m.get("file", "?") for m in matches[:10]))
            first_lines = [m.get("line", "")[:80] for m in matches[:3]]
            self.add_fact(
                f"grep:{pattern[:30]}",
                f"{len(matches)} matches in {match_files}. First: {first_lines}"
            )
        else:
            self.add_fact(f"grep:{pattern[:30]}", "no matches")

    def _extract_bash_facts(self, tool_name: str, params: Dict, result: Dict) -> None:
        cmd = params.get("command", "?")
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        exit_code = result.get("exit_code", result.get("returncode", 0))
        output = (stdout or stderr)[:200].strip()
        self.add_fact(
            f"{tool_name}:{cmd[:25]}",
            f"exit={exit_code}. {output}"
        )

    def _extract_glob_facts(self, params: Dict, result: Dict) -> None:
        pattern = params.get("pattern", "?")
        files = result.get("files", [])
        file_names = [_basename(f) for f in files[:8]]
        self.add_fact(
            f"glob:{pattern[:25]}",
            f"{len(files)} files: {file_names}"
        )

    def _extract_write_facts(self, tool_name: str, params: Dict, result: Dict) -> None:
        path = params.get("file_path", params.get("path", "?"))
        self.add_fact(f"modified:{_basename(path)}", f"{tool_name} applied successfully")

    def _extract_ls_facts(self, params: Dict, result: Dict) -> None:
        path = params.get("path", params.get("directory", "."))
        items = result.get("items", [])
        names = [i.get("name", "?") for i in items[:8]]
        self.add_fact(f"ls:{_basename(path)}", f"{len(items)} items: {names}")

    # ------------------------------------------------------------------
    # Compact output (injected into LLM prompt)
    # ------------------------------------------------------------------

    def compact(self, max_chars: int = 2000) -> str:
        """
        Produce a structured, token-budgeted memory section for the LLM prompt.

        Typically ~500-1500 chars depending on accumulated state.
        The output is deterministic and does not depend on LLM parsing.
        """
        sections = []

        # Goal (always present)
        if self.goal:
            sections.append(f"GOAL: {self.goal[:200]}")

        # Plan progress
        if self.plan:
            plan_lines = []
            for i, step in enumerate(self.plan):
                icon = {
                    StepStatus.DONE: "done",
                    StepStatus.ACTIVE: ">>>",
                    StepStatus.SKIPPED: "skip",
                    StepStatus.PENDING: "...",
                }[step.status]
                plan_lines.append(f"  [{icon}] {i+1}. {step.description[:60]}")
            sections.append("PLAN:\n" + "\n".join(plan_lines))

        # Key facts
        if self.facts:
            fact_lines = [f"  - {k}: {v[:120]}" for k, v in self.facts.items()]
            sections.append("FACTS:\n" + "\n".join(fact_lines))

        # Decisions
        if self.decisions:
            dec_lines = [f"  - {d[:100]}" for d in self.decisions]
            sections.append("DECISIONS:\n" + "\n".join(dec_lines))

        # Recent tool calls (compressed)
        if self.tool_log:
            recent = self.tool_log[-5:]
            log_parts = [r.summary for r in recent]
            sections.append("RECENT: " + " | ".join(log_parts))

        output = "## Working Memory\n" + "\n".join(sections)

        # Truncate if over budget
        if len(output) > max_chars:
            output = output[:max_chars - 20] + "\n[...truncated]"

        return output

    # ------------------------------------------------------------------
    # Serialization (for tests and debugging)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "plan": [{"desc": s.description, "status": s.status.value} for s in self.plan],
            "facts": dict(self.facts),
            "decisions": list(self.decisions),
            "tool_log": [
                {"tool": r.tool, "summary": r.summary, "success": r.success}
                for r in self.tool_log
            ],
            "current_step": self._current_step,
            "iteration": self._iteration,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkingMemory":
        mem = cls(goal=data.get("goal", ""))
        for step_data in data.get("plan", []):
            mem.plan.append(PlanStep(
                description=step_data["desc"],
                status=StepStatus(step_data["status"]),
            ))
        for k, v in data.get("facts", {}).items():
            mem.facts[k] = v
        mem.decisions = data.get("decisions", [])
        for rec in data.get("tool_log", []):
            mem.tool_log.append(ToolRecord(
                tool=rec["tool"],
                summary=rec["summary"],
                success=rec.get("success", True),
            ))
        mem._current_step = data.get("current_step", 0)
        mem._iteration = data.get("iteration", 0)
        return mem

    def clear(self) -> None:
        """Reset all memory."""
        self.goal = ""
        self.plan.clear()
        self.facts.clear()
        self.decisions.clear()
        self.tool_log.clear()
        self._current_step = 0
        self._iteration = 0


def _basename(path: str) -> str:
    """Extract filename from path, handling both / and \\."""
    if not path:
        return "?"
    # Use the last component
    parts = path.replace("\\", "/").rstrip("/").split("/")
    return parts[-1] if parts else path
