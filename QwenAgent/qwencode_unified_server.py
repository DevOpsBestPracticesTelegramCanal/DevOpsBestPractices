# -*- coding: utf-8 -*-
"""
===============================================================================
QWENCODE UNIFIED SERVER - Единый источник правды
===============================================================================

Интегрирует:
- UnifiedTools (core/unified_tools.py) - единые инструменты
- PatternRouter (core/pattern_router.py) - Fast Path без LLM
- SWECAS Classification - классификация задач
- SSE Streaming - потоковые ответы

Архитектура:
                     USER INPUT
                         |
                         v
                 +--------------+
                 | PatternRouter |  Fast Path (read, grep, ls, bash)
                 +-------+------+
                         |
            match?       |        no match?
           +-------------+-------------+
           |                           |
           v                           v
    +-------------+            +---------------+
    | UnifiedTools|            | SWECAS + LLM  |  Deep Path
    +-------------+            +---------------+
           |                           |
           v                           v
                     SSE Response

Usage:
    python qwencode_unified_server.py --port 5002

===============================================================================
"""

import os
import sys
import json
import time
import re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import requests

from flask import Flask, request, jsonify, render_template, Response
from flask_cors import CORS

# Exit handler - активация сервера и прогрев при выходе из CLI
try:
    from core.exit_handler import (
        register_exit_handler, set_config as set_exit_config,
        ExitHandlerConfig
    )
    HAS_EXIT_HANDLER = True
except ImportError:
    HAS_EXIT_HANDLER = False

# UNIFIED IMPORTS - Единый источник правды
from core.unified_tools import UnifiedTools, get_tools
from core.pattern_router import PatternRouter, get_router

# SWECAS classifier for Deep Path classification
try:
    from core.swecas_classifier import SWECASClassifier
    swecas_classifier = SWECASClassifier()
    HAS_SWECAS = True
except ImportError:
    swecas_classifier = None
    HAS_SWECAS = False

# Orchestrator (tier waterfall + Multi-Candidate + WorkingMemory)
try:
    from core.orchestrator import Orchestrator, ProcessingResult, ProcessingTier
    HAS_ORCHESTRATOR = True
except ImportError as _orch_err:
    HAS_ORCHESTRATOR = False
    Orchestrator = None
    print(f"[ORCHESTRATOR] Import failed: {_orch_err}")

# QwenCodeAgent (streaming + WorkingMemory + agentic loop)
try:
    from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig
    HAS_AGENT = True
except ImportError as _agent_err:
    HAS_AGENT = False
    QwenCodeAgent = None
    QwenCodeConfig = None
    print(f"[AGENT] Import failed: {_agent_err}")

# ApprovalManager for Human-in-the-Loop
try:
    from core.approval_manager import (
        ApprovalManager, ApprovalRequest, ApprovalChoice,
        RiskLevel, RiskAssessor, get_approval_manager, set_approval_manager
    )
    HAS_APPROVAL = True
except ImportError:
    HAS_APPROVAL = False
    ApprovalManager = None
    RiskAssessor = None

# Observability metrics registry
try:
    from core.observability.metrics import metrics as metrics_registry
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False
    metrics_registry = None

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class ServerConfig:
    """Server configuration"""
    # Ollama settings
    ollama_url: str = "http://localhost:11434"
    fast_model: str = "qwen2.5-coder:3b"
    heavy_model: str = "qwen2.5-coder:7b"

    # Token limits
    max_tokens_fast: int = 1024
    max_tokens_deep: int = 2048

    # Timeouts
    ollama_timeout: int = 120

    # Project root
    project_root: str = "C:/Users/serga/QwenAgent"


# ============================================================================
# SSE EVENT HELPERS
# ============================================================================

def sse_event(event_type: str, data: Dict) -> str:
    """Format SSE event"""
    data["event"] = event_type
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_status(text: str) -> str:
    """Status event"""
    return sse_event("status", {"text": text})


def sse_tool_start(tool: str, params: Dict) -> str:
    """Tool start event"""
    return sse_event("tool_start", {"tool": tool, "params": params})


def sse_tool_result(tool: str, params: Dict, result: Dict) -> str:
    """Tool result event"""
    return sse_event("tool_result", {"tool": tool, "params": params, "result": result})


def sse_response(text: str, route_method: str = "pattern") -> str:
    """Response event"""
    return sse_event("response", {"text": text, "route_method": route_method})


def sse_done(success: bool = True, mode: str = "fast", swecas: dict = None) -> str:
    """Done event"""
    data = {"success": success, "mode": mode}
    if swecas:
        data["swecas"] = swecas
    return sse_event("done", data)


def sse_approval_required(request_data: Dict) -> str:
    """Approval required event - sent when user confirmation is needed"""
    return sse_event("approval_required", request_data)


def sse_approval_resolved(request_id: str, approved: bool, choice: str) -> str:
    """Approval resolved event - sent when user responds"""
    return sse_event("approval_resolved", {
        "request_id": request_id,
        "approved": approved,
        "choice": choice
    })


# Phase 1: Pipeline Monitor SSE helpers

def sse_task_context(data: Dict) -> str:
    """Task context event — after TaskAbstraction.classify()"""
    return sse_event("task_context", data)


def sse_pipeline_start(data: Dict) -> str:
    """Pipeline start event — before pipeline.run_sync()"""
    return sse_event("pipeline_start", data)


def sse_pipeline_candidate(data: Dict) -> str:
    """Per-candidate progress event"""
    return sse_event("pipeline_candidate", data)


def sse_pipeline_result(data: Dict) -> str:
    """Pipeline result event — after pipeline completes"""
    return sse_event("pipeline_result", data)


def sse_correction_start(data: Dict) -> str:
    """Self-correction loop start"""
    return sse_event("correction_start", data)


def sse_correction_iteration(data: Dict) -> str:
    """Self-correction iteration event"""
    return sse_event("correction_iteration", data)


def sse_correction_result(data: Dict) -> str:
    """Self-correction loop result"""
    return sse_event("correction_result", data)


def sse_working_memory(data: Dict) -> str:
    """Working memory state update — after each tool execution"""
    return sse_event("working_memory", data)


def sse_checkpoint_saved(data: Dict) -> str:
    """Checkpoint saved confirmation"""
    return sse_event("checkpoint_saved", data)


# Week 20: Token streaming SSE helpers

def sse_response_start(message_id: str) -> str:
    """Response start event — before first token"""
    return sse_event("response_start", {"message_id": message_id})


def sse_response_token(token: str, message_id: str) -> str:
    """Single token event — streamed incrementally"""
    return sse_event("response_token", {"token": token, "message_id": message_id})


def sse_response_done(content: str, message_id: str) -> str:
    """Response done event — full text ready for formatting"""
    return sse_event("response_done", {"content": content, "message_id": message_id})


# ============================================================================
# RESULT FORMATTERS
# ============================================================================

def format_grep_result(result: Dict) -> str:
    """Format grep result for display"""
    if not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"

    matches = result.get("matches", [])
    if not matches:
        return f"No matches found for pattern: {result.get('pattern', '')}"

    lines = [f"Found {result['count']} matches (engine: {result.get('engine', 'python')}):\n"]
    for m in matches[:20]:  # Limit display
        lines.append(f"{m['file']}:{m['line_number']}: {m['line']}")

    if result['count'] > 20:
        lines.append(f"\n... and {result['count'] - 20} more matches")

    return "\n".join(lines)


def format_read_result(result: Dict) -> str:
    """Format read result for display"""
    if not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"

    header = f"File: {result.get('file_path', '')} ({result.get('shown_lines', 0)}/{result.get('total_lines', 0)} lines)\n"
    return header + "-" * 40 + "\n" + result.get("content", "")


def format_ls_result(result: Dict) -> str:
    """Format ls result for display"""
    if not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"

    items = result.get("items", [])
    if not items:
        return f"Empty directory: {result.get('path', '.')}"

    lines = [f"Directory: {result.get('path', '.')} ({result['count']} items)\n"]

    # Group by type
    dirs = [i for i in items if i['type'] == 'directory']
    files = [i for i in items if i['type'] == 'file']

    for d in dirs:
        lines.append(f"  [DIR]  {d['name']}")
    for f in files:
        size = f['size']
        size_str = f"{size:,} B" if size < 1024 else f"{size/1024:.1f} KB"
        lines.append(f"  [FILE] {f['name']} ({size_str})")

    return "\n".join(lines)


def format_bash_result(result: Dict) -> str:
    """Format bash result for display"""
    if not result.get("success") and result.get("error"):
        return f"Error: {result.get('error')}"

    output = result.get("stdout", "")
    stderr = result.get("stderr", "")
    code = result.get("return_code", 0)

    parts = []
    if output:
        parts.append(output)
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    if code != 0:
        parts.append(f"\n[exit code: {code}]")

    return "\n".join(parts) if parts else "(no output)"


def format_help_result(result: Dict) -> str:
    """Format help result"""
    return result.get("content", "No help available")


def format_glob_result(result: Dict) -> str:
    """Format glob result"""
    if not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"

    files = result.get("files", [])
    if not files:
        return "(no files found)"

    return "\n".join(files[:50])


def format_edit_result(result: Dict) -> str:
    """
    Format edit result in Claude Code tree style:

    * Edit(file_path)
      |_  Added X lines, removed Y lines
          18      context line
          19 -    removed line
          19 +    added line
          20      context line

    Uses ASCII-compatible symbols for Windows compatibility.
    """
    if not result.get("success"):
        error = result.get("error", "Unknown error")
        return f"* Edit\n  |_  [X] Error: {error}"

    file_path = result.get("file_path", "unknown")

    # Count changes
    added = result.get("lines_added", 0)
    removed = result.get("lines_removed", 0)

    # Build header
    lines = [f"* Edit({file_path})"]

    # Summary line
    if added > 0 and removed > 0:
        summary = f"Added {added} line{'s' if added > 1 else ''}, removed {removed} line{'s' if removed > 1 else ''}"
    elif added > 0:
        summary = f"Added {added} line{'s' if added > 1 else ''}"
    elif removed > 0:
        summary = f"Removed {removed} line{'s' if removed > 1 else ''}"
    else:
        summary = "No changes"

    lines.append(f"  |_  {summary}")

    # Show diff if available
    diff = result.get("diff", [])
    if diff:
        for entry in diff[:30]:  # Limit display
            line_num = entry.get("line", "")
            change_type = entry.get("type", "context")  # "add", "remove", "context"
            content = entry.get("content", "")

            # Format line number (right-aligned, 6 chars)
            num_str = f"{line_num:>6}" if line_num else "      "

            if change_type == "add":
                lines.append(f"     {num_str} +{content}")
            elif change_type == "remove":
                lines.append(f"     {num_str} -{content}")
            else:
                lines.append(f"     {num_str}  {content}")

        if len(diff) > 30:
            lines.append(f"     ... and {len(diff) - 30} more lines")

    # Show old/new if no diff but we have the strings
    elif result.get("old_string") or result.get("new_string"):
        old = result.get("old_string", "")
        new = result.get("new_string", "")

        if old:
            for i, line in enumerate(old.split('\n')[:5]):
                lines.append(f"        -{line}")
        if new:
            for i, line in enumerate(new.split('\n')[:5]):
                lines.append(f"        +{line}")

    return "\n".join(lines)


def format_write_result(result: Dict) -> str:
    """
    Format write result in Claude Code tree style:

    * Write(file_path)
      |_  Wrote X lines to file_path

    Uses ASCII-compatible symbols for Windows compatibility.
    """
    if not result.get("success"):
        error = result.get("error", "Unknown error")
        return f"* Write\n  |_  [X] Error: {error}"

    file_path = result.get("file_path", "unknown")
    lines_written = result.get("lines_written", 0)

    return f"* Write({file_path})\n  |_  Wrote {lines_written} lines to {file_path}"


def format_tool_result(tool: str, result: Dict) -> str:
    """Format any tool result"""
    formatters = {
        "grep": format_grep_result,
        "find": format_grep_result,  # Same format
        "read": format_read_result,
        "ls": format_ls_result,
        "bash": format_bash_result,
        "help": format_help_result,
        "glob": format_glob_result,
        "edit": format_edit_result,
        "write": format_write_result,
    }

    formatter = formatters.get(tool)
    if formatter:
        return formatter(result)

    # Default: JSON
    return json.dumps(result, indent=2, ensure_ascii=False)


# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__, template_folder='templates')
app.config['JSON_AS_ASCII'] = False
CORS(app)

# Global instances
config = ServerConfig()
tools = UnifiedTools(project_root=config.project_root)
router = get_router()  # SINGLETON: использовать единый экземпляр
print(f"[SINGLETON] PatternRouter with {len(router.patterns)} patterns")

# Phase 6: Query Modifier Engine
try:
    from core.query_modifier import QueryModifierEngine, ModifierCommands
    query_modifier = QueryModifierEngine()
    query_modifier.set_language("ru")
    modifier_commands = ModifierCommands(query_modifier)
    HAS_QUERY_MODIFIER = True
    print(f"[QUERY MODIFIER] Loaded: lang={query_modifier.language}, {len(query_modifier.modifiers)} modifiers")
except ImportError:
    HAS_QUERY_MODIFIER = False
    query_modifier = None
    modifier_commands = None
    print("[QUERY MODIFIER] Not available")

# Approval Manager for Human-in-the-Loop
approval_manager = None
pending_approval_events = {}  # request_id → SSE event queue

if HAS_APPROVAL:
    def on_approval_needed(req: 'ApprovalRequest'):
        """Callback when approval is needed - store for SSE delivery"""
        pending_approval_events[req.id] = req.to_dict()
        print(f"[APPROVAL] Request {req.id}: {req.tool} - {req.description}")

    def on_approval_resolved(req: 'ApprovalRequest'):
        """Callback when approval is resolved"""
        pending_approval_events.pop(req.id, None)
        print(f"[APPROVAL] Resolved {req.id}: {req.status.value}")

    approval_manager = ApprovalManager(
        default_timeout=300.0,  # 5 minutes
        auto_approve_safe=True,
        auto_approve_low=True,
        auto_approve_moderate=False,
        on_approval_needed=on_approval_needed,
        on_approval_resolved=on_approval_resolved
    )
    set_approval_manager(approval_manager)


@app.route('/')
def index():
    """Serve terminal interface"""
    return render_template('qwencode_terminal.html')


@app.route('/api/health')
def health():
    """Health check endpoint"""
    # Check Ollama connectivity
    ollama_ok = False
    try:
        import urllib.request
        req = urllib.request.Request(config.ollama_url + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            ollama_ok = resp.status == 200
    except Exception:
        pass

    health_data = {
        "status": "ok",
        "ollama": ollama_ok,
        "model": config.fast_model,
        "fast_model": config.fast_model,
        "heavy_model": config.heavy_model,
        "ollama_url": config.ollama_url,
        "project_root": config.project_root,
        "tools_available": ["grep", "read", "write", "edit", "bash", "ls", "glob", "find", "help"],
        "pattern_router": True,
        "unified_tools": True,
        "swecas": HAS_SWECAS,
        "orchestrator": orchestrator is not None,
        "agent": agent is not None,
        "approval_manager": HAS_APPROVAL,
    }

    # Add orchestrator stats if available
    if orchestrator:
        health_data["orchestrator_stats"] = orchestrator.get_stats()

    # Add approval stats if available
    if HAS_APPROVAL and approval_manager:
        health_data["approval_stats"] = approval_manager.get_stats()

    # Multi-Candidate Pipeline info
    if agent and hasattr(agent, 'multi_candidate_pipeline'):
        mc_pipe = agent.multi_candidate_pipeline
        has_cross_review = bool(
            mc_pipe and hasattr(mc_pipe.config, 'cross_reviewer') and mc_pipe.config.cross_reviewer
        )
        health_data["multi_candidate"] = {
            "enabled": mc_pipe is not None,
            "n_candidates": mc_pipe.config.n_candidates if mc_pipe else 0,
            "runs": agent.stats.get("multi_candidate_runs", 0),
            "fallbacks": agent.stats.get("multi_candidate_fallbacks", 0),
            "cross_review": has_cross_review,
        }

    return jsonify(health_data)


@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Non-streaming chat endpoint.

    1. Try PatternRouter (Fast Path)
    2. Fallback to LLM (Deep Path)
    """
    data = request.json or {}
    message = data.get('message', '').strip()

    if not message:
        return jsonify({"error": "No message provided"}), 400

    print(f"\n[CHAT] Input: {message[:100]}...")

    # 0. Query Modifier: handle commands and apply modifiers
    if HAS_QUERY_MODIFIER:
        cmd_response = modifier_commands.handle(message)
        if cmd_response:
            return jsonify({
                "success": True,
                "response": cmd_response,
                "tool_calls": [],
                "route_method": "modifier_command",
                "mode": "fast",
                "mode_icon": "[FAST]"
            })

        modified = query_modifier.process(message)
        if modified != message:
            print(f"[MODIFIER] '{message[:40]}' -> '{modified[:60]}'")
            message = modified

    # 1. Try Fast Path (PatternRouter)
    route = router.match(message)

    if route:
        print(f"[FAST PATH] Tool: {route['tool']}, Params: {route['params']}")

        result = tools.execute(route['tool'], route['params'])
        formatted = format_tool_result(route['tool'], result)

        return jsonify({
            "success": True,
            "response": formatted,
            "tool_calls": [{
                "tool": route['tool'],
                "params": route['params'],
                "result": result
            }],
            "route_method": "pattern",
            "mode": "fast",
            "mode_icon": "[FAST]"
        })

    # 2. Deep Path: Orchestrator → LLM fallback
    print(f"[DEEP PATH] orchestrator={'yes' if orchestrator else 'no'}")

    # SWECAS classification for bug-related queries
    swecas_info = None
    if HAS_SWECAS and swecas_classifier:
        classification = swecas_classifier.classify(message)
        if classification.get("swecas_code"):
            swecas_info = {
                "category": classification["swecas_code"],
                "name": classification.get("name", ""),
                "confidence": classification.get("confidence", 0),
                "hint": classification.get("fix_hint", ""),
                "diffuse_prompts": classification.get("diffuse_prompts", [])
            }
            print(f"[SWECAS] Category: {swecas_info['category']} - {swecas_info['name']}")

    try:
        # --- Orchestrator path ---
        if orchestrator:
            orch_result: ProcessingResult = orchestrator.process(message)
            result = {
                "success": True,
                "response": orch_result.response,
                "tool_calls": orch_result.tool_calls,
                "route_method": f"orchestrator_{orch_result.tier.name.lower()}",
                "tier": orch_result.tier.name,
                "confidence": orch_result.confidence,
                "iterations": orch_result.iterations,
                "processing_time_ms": orch_result.processing_time_ms,
                "mode": "deep",
                "mode_icon": "[DEEP]"
            }
            if swecas_info:
                result["swecas"] = swecas_info
            return jsonify(result)

        # --- Raw LLM fallback ---
        response = call_llm(message)

        result = {
            "success": True,
            "response": response,
            "tool_calls": [],
            "route_method": "llm",
            "mode": "deep",
            "mode_icon": "[DEEP]"
        }

        if swecas_info:
            result["swecas"] = swecas_info

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """
    SSE Streaming endpoint.

    Events:
    - status: Processing status
    - tool_start: Tool execution started
    - tool_result: Tool execution result
    - response: Text response
    - done: Processing complete
    """
    data = request.json or {}
    message = data.get('message', '').strip()

    if not message:
        return jsonify({"error": "No message provided"}), 400

    print(f"\n{'='*60}")
    print(f"[STREAM] Input: {message[:100]}...")

    # Query Modifier: handle commands before streaming
    if HAS_QUERY_MODIFIER:
        cmd_response = modifier_commands.handle(message)
        if cmd_response:
            return jsonify({
                "success": True,
                "response": cmd_response,
                "tool_calls": [],
                "route_method": "modifier_command",
                "mode": "fast",
                "mode_icon": "[FAST]"
            })

        modified = query_modifier.process(message)
        if modified != message:
            print(f"[MODIFIER] '{message[:40]}' -> '{modified[:60]}'")
            message = modified

    def generate():
        global _stats, _last_debug

        # Update stats
        _stats["requests_total"] += 1
        _stats["last_request_time"] = datetime.now().isoformat()
        _last_debug["input"] = message
        _last_debug["timestamp"] = datetime.now().isoformat()
        _last_debug["tool_calls"] = []

        try:
            yield sse_status("Processing...")

            # 1. Try chain commands first (ls; read; grep)
            chain = router.match_chain(message)

            if chain:
                print(f"[CHAIN] {len(chain)} commands detected")

                for i, route in enumerate(chain, 1):
                    yield sse_status(f"Command {i}/{len(chain)}: {route['tool']}")
                    yield sse_tool_start(route['tool'], route['params'])

                    result = tools.execute(route['tool'], route['params'])
                    yield sse_tool_result(route['tool'], route['params'], result)

                    formatted = format_tool_result(route['tool'], result)
                    yield sse_response(f"## {route['tool'].upper()}\n\n{formatted}", "pattern")

                _stats["requests_fast_path"] += 1
                yield sse_done(True, "fast")
                return

            # 2. Try single command (Fast Path)
            # Skip pattern router for code generation tasks → Multi-Candidate in agent
            _is_codegen = agent and hasattr(agent, '_is_code_generation_task') and agent._is_code_generation_task(message)
            route = router.match(message) if not _is_codegen else None

            if route:
                print(f"[FAST PATH] Tool: {route['tool']}")

                # Check if approval needed (Human-in-the-Loop)
                if HAS_APPROVAL and RiskAssessor:
                    risk = RiskAssessor.assess(
                        route['tool'],
                        route['params'],
                        message
                    )

                    if RiskAssessor.needs_approval(route['tool'], route['params'], message):
                        yield sse_status(f"⚠️ {risk.value.upper()} risk operation - awaiting approval...")

                        # Emit approval required event
                        yield sse_approval_required({
                            "id": f"inline_{int(time.time()*1000)}",
                            "step_id": "inline_step",
                            "tool": route['tool'],
                            "description": f"Execute {route['tool']} with params: {route['params']}",
                            "params": route['params'],
                            "risk_level": risk.value,
                            "context": message,
                            "choices": [
                                {"key": "y", "label": "Yes", "action": "yes"},
                                {"key": "n", "label": "No", "action": "no"},
                            ]
                        })

                        # Note: In real implementation, would wait for user response
                        # For now, auto-approve after showing warning
                        yield sse_status(f"Auto-proceeding (inline mode)...")

                yield sse_tool_start(route['tool'], route['params'])

                result = tools.execute(route['tool'], route['params'])
                yield sse_tool_result(route['tool'], route['params'], result)

                formatted = format_tool_result(route['tool'], result)
                yield sse_response(formatted, "pattern")
                _stats["requests_fast_path"] += 1
                _last_debug["tool_calls"].append({"tool": route['tool'], "params": route['params']})
                yield sse_done(True, "fast")
                return

            # 3. Deep Path: Agent → Orchestrator → LLM fallback
            print(f"[DEEP PATH] agent={'yes' if agent else 'no'}, orchestrator={'yes' if orchestrator else 'no'}")

            # SWECAS classification for enhanced context
            swecas_info = None
            if HAS_SWECAS and swecas_classifier:
                classification = swecas_classifier.classify(message)
                if classification.get("swecas_code"):
                    swecas_info = {
                        "category": classification["swecas_code"],
                        "name": classification.get("name", ""),
                        "confidence": classification.get("confidence", 0)
                    }
                    print(f"[SWECAS] Category: {swecas_info['category']} - {swecas_info['name']}")
                    yield sse_status(f"[SWECAS-{swecas_info['category']}] {swecas_info['name']}")

            deep_handled = False

            # --- Priority 1: Agent (streaming agentic loop) ---
            if agent:
                try:
                    yield sse_status("Agent processing...")
                    for evt in agent.process_stream(message):
                        evt_type = evt.get("event", "")
                        if evt_type == "status":
                            yield sse_status(evt.get("text", ""))
                        elif evt_type == "tool_start":
                            yield sse_tool_start(evt.get("tool", ""), evt.get("params", {}))
                        elif evt_type == "tool_result":
                            yield sse_tool_result(evt.get("tool", ""), evt.get("params", {}), evt.get("result", {}))
                        elif evt_type == "thinking":
                            yield sse_event("thinking", {"steps": evt.get("steps", [])})
                        elif evt_type == "response":
                            yield sse_response(evt.get("text", ""), evt.get("route_method", "agent"))
                        elif evt_type == "done":
                            pass  # we emit our own done below
                        # Phase 1: Pipeline Monitor events — passthrough
                        elif evt_type == "task_context":
                            yield sse_task_context(evt)
                        elif evt_type == "pipeline_start":
                            yield sse_pipeline_start(evt)
                        elif evt_type == "pipeline_candidate":
                            yield sse_pipeline_candidate(evt)
                        elif evt_type == "pipeline_result":
                            yield sse_pipeline_result(evt)
                        elif evt_type == "pipeline_validation":
                            yield sse_event("pipeline_validation", evt)
                        elif evt_type == "correction_start":
                            yield sse_correction_start(evt)
                        elif evt_type == "correction_iteration":
                            yield sse_correction_iteration(evt)
                        elif evt_type == "correction_result":
                            yield sse_correction_result(evt)
                        elif evt_type == "deep_step":
                            yield sse_event("deep_step", evt)
                        # Week 20: Token streaming events — passthrough
                        elif evt_type == "response_start":
                            yield sse_response_start(evt.get("message_id", ""))
                        elif evt_type == "response_token":
                            yield sse_response_token(evt.get("token", ""), evt.get("message_id", ""))
                        elif evt_type == "response_done":
                            yield sse_response_done(evt.get("content", ""), evt.get("message_id", ""))
                        # Phase 7: Working Memory events — passthrough
                        elif evt_type == "working_memory":
                            yield sse_working_memory(evt)
                    _stats["requests_deep_path"] += 1
                    yield sse_done(True, "deep_agent", swecas=swecas_info)
                    deep_handled = True
                except Exception as agent_err:
                    print(f"[AGENT ERROR] {agent_err}, falling back to orchestrator")
                    yield sse_status(f"Agent error, falling back...")

            # --- Priority 2: Orchestrator (tier waterfall) ---
            if not deep_handled and orchestrator:
                try:
                    yield sse_status("Orchestrator processing...")
                    orch_result = orchestrator.process(message)
                    # Emit tool_call events
                    for tc in orch_result.tool_calls:
                        yield sse_tool_start(tc.get("tool", ""), tc.get("params", {}))
                        yield sse_tool_result(tc.get("tool", ""), tc.get("params", {}), tc.get("result", {}))
                    route_tag = f"orchestrator_{orch_result.tier.name.lower()}"
                    yield sse_response(orch_result.response, route_tag)
                    _stats["requests_deep_path"] += 1
                    yield sse_done(True, "deep_orchestrator", swecas=swecas_info)
                    deep_handled = True
                except Exception as orch_err:
                    print(f"[ORCHESTRATOR ERROR] {orch_err}, falling back to raw LLM")
                    yield sse_status(f"Orchestrator error, falling back...")

            # --- Priority 3: Raw LLM fallback ---
            if not deep_handled:
                yield sse_status(f"Thinking... (model: {config.fast_model})")
                response = call_llm_stream(message, yield_func=lambda x: None)
                yield sse_response(response, "llm")
                _stats["requests_deep_path"] += 1
                _last_debug["response"] = response[:500] if response else ""
                yield sse_done(True, "deep", swecas=swecas_info)

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield sse_event("error", {"text": str(e)})
            yield sse_done(False, "error")

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


# ============================================================================
# LLM HELPERS
# ============================================================================

def call_llm(message: str, model: str = None) -> str:
    """Call Ollama LLM (non-streaming)"""
    model = model or config.fast_model

    try:
        response = requests.post(
            f"{config.ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": message,
                "stream": False,
                "options": {
                    "num_predict": config.max_tokens_fast,
                    "temperature": 0.1
                }
            },
            timeout=config.ollama_timeout
        )

        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            return f"LLM Error: HTTP {response.status_code}"

    except requests.exceptions.Timeout:
        return "LLM Error: Timeout"
    except requests.exceptions.ConnectionError:
        return "LLM Error: Ollama not running. Start with: ollama serve"
    except Exception as e:
        return f"LLM Error: {e}"


def call_llm_stream(message: str, model: str = None, yield_func: callable = None) -> str:
    """Call Ollama LLM (streaming)"""
    model = model or config.fast_model
    full_response = []

    try:
        response = requests.post(
            f"{config.ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": message,
                "stream": True,
                "options": {
                    "num_predict": config.max_tokens_fast,
                    "temperature": 0.1
                }
            },
            timeout=config.ollama_timeout,
            stream=True
        )

        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        token = data.get("response", "")
                        full_response.append(token)
                        if yield_func:
                            yield_func(token)
                    except json.JSONDecodeError:
                        continue

        return "".join(full_response)

    except Exception as e:
        return f"LLM Error: {e}"


# ============================================================================
# ORCHESTRATOR + AGENT INSTANCES
# ============================================================================

orchestrator = None
agent = None

if HAS_ORCHESTRATOR:
    try:
        orchestrator = Orchestrator(
            llm_client=lambda p: call_llm(p, config.heavy_model),
            use_bilingual_router=False,
            enable_multi_candidate=True,
        )
        print(f"[ORCHESTRATOR] Initialized (multi-candidate={orchestrator.multi_candidate_pipeline is not None})")
    except Exception as _orch_init_err:
        print(f"[ORCHESTRATOR] Init failed: {_orch_init_err}")

if HAS_AGENT:
    try:
        agent = QwenCodeAgent(QwenCodeConfig(
            ollama_url=config.ollama_url,
            model=config.heavy_model,
            working_dir=config.project_root,
        ))
        print(f"[AGENT] Initialized (model={config.heavy_model})")
    except Exception as _agent_init_err:
        print(f"[AGENT] Init failed: {_agent_init_err}")


# ============================================================================
# OLLAMA AUTO-START
# ============================================================================

def is_ollama_running() -> bool:
    """Check if Ollama server is running"""
    try:
        response = requests.get(f"{config.ollama_url}/api/tags", timeout=5)
        return response.status_code == 200
    except:
        return False


def start_ollama() -> bool:
    """
    Start Ollama server automatically.

    Tries multiple methods:
    1. PowerShell (Windows)
    2. subprocess (cross-platform)

    Returns:
        True if Ollama started successfully
    """
    import subprocess
    import platform

    print("  [OLLAMA] Starting Ollama server...")

    try:
        if platform.system() == "Windows":
            # Windows: use PowerShell to start hidden process
            subprocess.Popen(
                ["powershell", "-Command",
                 "Start-Process", "ollama", "-ArgumentList", "'serve'",
                 "-WindowStyle", "Hidden"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            # Linux/Mac: use nohup
            subprocess.Popen(
                ["nohup", "ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        # Wait for Ollama to start (up to 30 seconds)
        for i in range(30):
            time.sleep(1)
            if is_ollama_running():
                print(f"  [OLLAMA] Started successfully in {i+1}s")
                return True
            if i % 5 == 4:
                print(f"  [OLLAMA] Waiting... ({i+1}s)")

        print("  [OLLAMA] Failed to start within 30 seconds")
        return False

    except FileNotFoundError:
        print("  [OLLAMA] Error: 'ollama' not found in PATH")
        print("  [OLLAMA] Install from: https://ollama.ai")
        return False
    except Exception as e:
        print(f"  [OLLAMA] Error starting: {e}")
        return False


def ensure_ollama_running() -> bool:
    """
    Ensure Ollama is running, start if needed.

    Returns:
        True if Ollama is running (was running or successfully started)
    """
    if is_ollama_running():
        print("  [OLLAMA] Already running [OK]")
        return True

    print("  [OLLAMA] Not running, attempting auto-start...")
    return start_ollama()


# ============================================================================
# WARMUP
# ============================================================================

def warmup_model(auto_start: bool = True):
    """
    Warmup model before serving.

    Args:
        auto_start: If True, automatically start Ollama if not running
    """
    # Step 1: Ensure Ollama is running
    if auto_start:
        if not ensure_ollama_running():
            print("  [WARMUP] Cannot warmup - Ollama not available")
            return False
    else:
        if not is_ollama_running():
            print("  [WARMUP] Ollama not running! Start with: ollama serve")
            return False

    # Step 2: Warmup the model
    print(f"\n  [WARMUP] Прогрев модели: {config.fast_model}")

    start = time.time()

    try:
        response = requests.post(
            f"{config.ollama_url}/api/generate",
            json={
                "model": config.fast_model,
                "prompt": "Say OK",
                "stream": False,
                "options": {"num_predict": 5}
            },
            timeout=120
        )

        elapsed = time.time() - start

        if response.status_code == 200:
            result = response.json().get("response", "").strip()
            print(f"  [WARMUP] Loaded in {elapsed:.1f}s, test: '{result}'")
            return True
        else:
            print(f"  [WARMUP] Error: HTTP {response.status_code}")
            return False

    except requests.exceptions.ConnectionError:
        print(f"  [WARMUP] Connection failed after Ollama start")
        return False
    except Exception as e:
        print(f"  [WARMUP] Error: {e}")
        return False


# ============================================================================
# APPROVAL API ENDPOINTS
# ============================================================================

@app.route('/api/approval/pending', methods=['GET'])
def get_pending_approvals():
    """
    Get all pending approval requests.

    Returns:
        List of pending approval requests
    """
    if not HAS_APPROVAL or not approval_manager:
        return jsonify({"error": "Approval manager not available"}), 503

    pending = approval_manager.get_pending()
    return jsonify({
        "pending": [req.to_dict() for req in pending],
        "count": len(pending)
    })


@app.route('/api/approval/respond', methods=['POST'])
def respond_to_approval():
    """
    Respond to an approval request.

    Body:
        {
            "request_id": "abc123",
            "choice": "yes" | "yes_and" | "no" | "skip" | "abort",
            "user_input": "optional modifications" (for yes_and)
        }

    Returns:
        Success status
    """
    if not HAS_APPROVAL or not approval_manager:
        return jsonify({"error": "Approval manager not available"}), 503

    data = request.json or {}
    request_id = data.get('request_id')
    choice = data.get('choice', 'no')
    user_input = data.get('user_input')

    if not request_id:
        return jsonify({"error": "request_id required"}), 400

    # Map string choice to enum
    choice_map = {
        'yes': ApprovalChoice.YES,
        'y': ApprovalChoice.YES,
        'yes_and': ApprovalChoice.YES_AND,
        'a': ApprovalChoice.YES_AND,
        'no': ApprovalChoice.NO,
        'n': ApprovalChoice.NO,
        'skip': ApprovalChoice.SKIP,
        's': ApprovalChoice.SKIP,
        'abort': ApprovalChoice.ABORT,
        'x': ApprovalChoice.ABORT,
    }

    approval_choice = choice_map.get(choice.lower())
    if not approval_choice:
        return jsonify({"error": f"Invalid choice: {choice}"}), 400

    success = approval_manager.respond(request_id, approval_choice, user_input)

    if success:
        return jsonify({
            "success": True,
            "request_id": request_id,
            "choice": approval_choice.value
        })
    else:
        return jsonify({
            "success": False,
            "error": f"Request {request_id} not found"
        }), 404


@app.route('/api/approval/approve/<request_id>', methods=['POST'])
def quick_approve(request_id: str):
    """Quick approve endpoint"""
    if not HAS_APPROVAL or not approval_manager:
        return jsonify({"error": "Approval manager not available"}), 503

    success = approval_manager.approve(request_id)
    return jsonify({"success": success, "request_id": request_id, "action": "approved"})


@app.route('/api/approval/reject/<request_id>', methods=['POST'])
def quick_reject(request_id: str):
    """Quick reject endpoint"""
    if not HAS_APPROVAL or not approval_manager:
        return jsonify({"error": "Approval manager not available"}), 503

    success = approval_manager.reject(request_id)
    return jsonify({"success": success, "request_id": request_id, "action": "rejected"})


@app.route('/api/approval/abort/<request_id>', methods=['POST'])
def quick_abort(request_id: str):
    """Abort entire operation"""
    if not HAS_APPROVAL or not approval_manager:
        return jsonify({"error": "Approval manager not available"}), 503

    success = approval_manager.abort(request_id)
    return jsonify({"success": success, "request_id": request_id, "action": "aborted"})


@app.route('/api/approval/cancel_all', methods=['POST'])
def cancel_all_approvals():
    """Cancel all pending approvals"""
    if not HAS_APPROVAL or not approval_manager:
        return jsonify({"error": "Approval manager not available"}), 503

    approval_manager.cancel_all()
    return jsonify({"success": True, "action": "all_cancelled"})


@app.route('/api/approval/stats', methods=['GET'])
def get_approval_stats():
    """Get approval statistics"""
    if not HAS_APPROVAL or not approval_manager:
        return jsonify({"error": "Approval manager not available"}), 503

    return jsonify(approval_manager.get_stats())


@app.route('/api/approval/history', methods=['GET'])
def get_approval_history():
    """Get approval history"""
    if not HAS_APPROVAL or not approval_manager:
        return jsonify({"error": "Approval manager not available"}), 503

    limit = request.args.get('limit', 20, type=int)
    history = approval_manager.get_history(limit)

    return jsonify({
        "history": [
            {
                "request_id": h.request_id,
                "tool": h.tool,
                "description": h.description,
                "risk_level": h.risk_level,
                "status": h.status,
                "choice": h.choice,
                "duration_ms": h.duration_ms,
                "timestamp": h.timestamp.isoformat()
            }
            for h in history
        ],
        "count": len(history)
    })


@app.route('/api/approval/assess', methods=['POST'])
def assess_risk():
    """
    Assess risk level of an operation without requesting approval.

    Body:
        {
            "tool": "bash",
            "params": {"command": "rm -rf /tmp/test"},
            "context": ""
        }
    """
    if not HAS_APPROVAL or not RiskAssessor:
        return jsonify({"error": "Risk assessor not available"}), 503

    data = request.json or {}
    tool = data.get('tool', '')
    params = data.get('params', {})
    context = data.get('context', '')

    risk = RiskAssessor.assess(tool, params, context)
    needs_approval = RiskAssessor.needs_approval(tool, params, context)

    return jsonify({
        "tool": tool,
        "risk_level": risk.value,
        "needs_approval": needs_approval,
        "description": f"{tool} operation assessed as {risk.value}"
    })


# ============================================================================
# SSE APPROVAL STREAM (для real-time уведомлений)
# ============================================================================

@app.route('/api/approval/stream')
def approval_stream():
    """
    SSE stream for approval notifications.

    Client connects and receives real-time approval requests.
    """
    def generate():
        import time
        last_seen = set()

        while True:
            # Check for new pending approvals
            if HAS_APPROVAL and approval_manager:
                current_pending = {req.id for req in approval_manager.get_pending()}

                # New requests
                new_requests = current_pending - last_seen
                for req_id in new_requests:
                    req_data = pending_approval_events.get(req_id)
                    if req_data:
                        yield sse_approval_required(req_data)

                # Resolved requests
                resolved = last_seen - current_pending
                for req_id in resolved:
                    yield sse_approval_resolved(req_id, False, "unknown")

                last_seen = current_pending

            time.sleep(0.5)  # Poll every 500ms

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


# ============================================================================
# MANAGEMENT ENDPOINTS (merged from qwencode_server.py)
# ============================================================================

# Server statistics
_stats = {
    "requests_total": 0,
    "requests_fast_path": 0,
    "requests_deep_path": 0,
    "requests_search": 0,
    "last_request_time": None,
    "start_time": datetime.now().isoformat()
}

# Debug storage
_last_debug = {
    "input": "",
    "route_result": None,
    "tool_calls": [],
    "response": "",
    "timestamp": None
}

# Execution mode
_current_mode = "auto"  # auto, fast, deep, search


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get server statistics"""
    stats_data = {
        **_stats,
        "uptime_seconds": (datetime.now() - datetime.fromisoformat(_stats["start_time"])).total_seconds(),
        "config": {
            "fast_model": config.fast_model,
            "heavy_model": config.heavy_model,
            "project_root": config.project_root
        },
        "swecas_enabled": HAS_SWECAS,
        "approval_enabled": HAS_APPROVAL,
    }
    if HAS_METRICS and metrics_registry:
        stats_data["metrics"] = metrics_registry.to_dict()
    if agent:
        stats_data["agent_stats"] = agent.stats
    return jsonify(stats_data)


# Phase 1: Pipeline Monitor REST endpoints

@app.route('/api/pipeline/status', methods=['GET'])
def pipeline_status():
    """Get current pipeline status and last result summary"""
    result = {"active": False, "last_result": None}
    if agent and hasattr(agent, 'stats'):
        result["runs"] = agent.stats.get("multi_candidate_runs", 0)
        result["corrections"] = agent.stats.get("correction_runs", 0)
        result["outcomes_recorded"] = agent.stats.get("outcomes_recorded", 0)
    return jsonify(result)


@app.route('/api/pipeline/candidates', methods=['GET'])
def pipeline_candidates():
    """Get full candidate comparison data from last pipeline run"""
    if not agent or not hasattr(agent, 'multi_candidate_pipeline') or not agent.multi_candidate_pipeline:
        return jsonify({"candidates": [], "error": "Pipeline not available"}), 404

    pipeline = agent.multi_candidate_pipeline
    if not hasattr(pipeline, '_last_result') or not pipeline._last_result:
        return jsonify({"candidates": [], "error": "No pipeline result available"})

    result = pipeline._last_result
    try:
        comparison = result.get_candidate_comparison()
        return jsonify({"candidates": comparison})
    except Exception as e:
        return jsonify({"candidates": [], "error": str(e)})


@app.route('/api/pipeline/candidate/<int:cand_id>', methods=['GET'])
def pipeline_candidate_detail(cand_id):
    """Get detailed data for a specific candidate"""
    if not agent or not hasattr(agent, 'multi_candidate_pipeline') or not agent.multi_candidate_pipeline:
        return jsonify({"error": "Pipeline not available"}), 404

    pipeline = agent.multi_candidate_pipeline
    if not hasattr(pipeline, '_last_result') or not pipeline._last_result:
        return jsonify({"error": "No pipeline result available"}), 404

    result = pipeline._last_result
    if not result.pool or not result.pool.candidates:
        return jsonify({"error": "No candidates in result"}), 404

    for cand in result.pool.candidates:
        if cand.id == cand_id:
            return jsonify(cand.to_dict())

    return jsonify({"error": f"Candidate {cand_id} not found"}), 404


@app.route('/api/pipeline/config', methods=['GET', 'POST'])
def pipeline_config():
    """Get or update pipeline configuration"""
    if not agent or not hasattr(agent, 'multi_candidate_pipeline') or not agent.multi_candidate_pipeline:
        return jsonify({"error": "Pipeline not available"}), 404

    pipeline = agent.multi_candidate_pipeline

    if request.method == 'GET':
        cfg = pipeline.config
        return jsonify({
            "n_candidates": cfg.n_candidates,
            "parallel_candidate_validation": cfg.parallel_candidate_validation,
            "max_validation_workers": cfg.max_validation_workers,
            "validation_cache_enabled": cfg.validation_cache_enabled,
            "max_validation_cache_size": cfg.max_validation_cache_size,
            "fail_fast": cfg.fail_fast,
        })

    # POST: update config
    data = request.json or {}
    cfg = pipeline.config
    if "n_candidates" in data:
        cfg.n_candidates = int(data["n_candidates"])
    if "parallel_candidate_validation" in data:
        cfg.parallel_candidate_validation = bool(data["parallel_candidate_validation"])
    if "max_validation_workers" in data:
        cfg.max_validation_workers = int(data["max_validation_workers"])
    if "validation_cache_enabled" in data:
        cfg.validation_cache_enabled = bool(data["validation_cache_enabled"])
    if "fail_fast" in data:
        cfg.fail_fast = bool(data["fail_fast"])
    return jsonify({"success": True, "updated": list(data.keys())})


# Phase 5: Settings & Config UI REST endpoints

@app.route('/api/pipeline/weights', methods=['GET', 'POST'])
def pipeline_weights():
    """Get or update scoring weights"""
    if not agent or not hasattr(agent, 'multi_candidate_pipeline') or not agent.multi_candidate_pipeline:
        return jsonify({"error": "Pipeline not available"}), 404

    pipeline = agent.multi_candidate_pipeline
    selector = pipeline.selector

    if request.method == 'GET':
        scoring = selector.scoring
        return jsonify({
            "weights": dict(scoring.weights),
            "all_passed_bonus": scoring.all_passed_bonus,
            "critical_error_penalty": scoring.critical_error_penalty,
        })

    # POST: update weights
    data = request.json or {}
    scoring = selector.scoring
    if "weights" in data and isinstance(data["weights"], dict):
        for name, val in data["weights"].items():
            scoring.weights[name] = float(val)
    if "bonus" in data:
        scoring.all_passed_bonus = float(data["bonus"])
    if "penalty" in data:
        scoring.critical_error_penalty = float(data["penalty"])
    return jsonify({"success": True})


@app.route('/api/pipeline/profiles', methods=['GET'])
def pipeline_profiles():
    """List available validation profiles with their configs"""
    try:
        from core.task_abstraction import ValidationProfile, TaskAbstraction

        profiles = []
        for p in ValidationProfile:
            cfg = TaskAbstraction.get_validation_config(p)
            weights = TaskAbstraction.get_scoring_weights(p)
            profiles.append({
                "name": p.value,
                "rule_names": cfg.get("rule_names", []),
                "fail_fast": cfg.get("fail_fast", False),
                "parallel": cfg.get("parallel", True),
                "weights": weights,
            })
        return jsonify({"profiles": profiles})
    except ImportError:
        return jsonify({"profiles": [], "error": "TaskAbstraction not available"})
    except Exception as e:
        return jsonify({"profiles": [], "error": str(e)})


# Phase 4: Dashboard & Analytics REST endpoints

@app.route('/api/analytics/outcomes', methods=['GET'])
def analytics_outcomes():
    """Recent pipeline outcomes for timeline widget"""
    limit = request.args.get('limit', 50, type=int)
    if not agent or not hasattr(agent, 'outcome_tracker') or not agent.outcome_tracker:
        return jsonify({"outcomes": [], "error": "OutcomeTracker not available"})
    try:
        outcomes = agent.outcome_tracker.get_recent_outcomes(limit=limit)
        return jsonify({"outcomes": outcomes})
    except Exception as e:
        return jsonify({"outcomes": [], "error": str(e)})


@app.route('/api/analytics/profiles', methods=['GET'])
def analytics_profiles():
    """Per-profile success rates and performance"""
    if not agent or not hasattr(agent, 'outcome_tracker') or not agent.outcome_tracker:
        return jsonify({"profiles": {}, "error": "OutcomeTracker not available"})
    try:
        profiles = agent.outcome_tracker.get_profile_stats()
        return jsonify({"profiles": profiles})
    except Exception as e:
        return jsonify({"profiles": {}, "error": str(e)})


@app.route('/api/analytics/rules', methods=['GET'])
def analytics_rules():
    """Per-rule effectiveness (catch rates)"""
    if not agent or not hasattr(agent, 'outcome_tracker') or not agent.outcome_tracker:
        return jsonify({"rules": {}, "error": "OutcomeTracker not available"})
    try:
        rules = agent.outcome_tracker.get_rule_effectiveness()
        return jsonify({"rules": rules})
    except Exception as e:
        return jsonify({"rules": {}, "error": str(e)})


@app.route('/api/analytics/cache', methods=['GET'])
def analytics_cache():
    """Validation cache + solution cache stats"""
    result = {}

    # Validation cache from pipeline
    if agent and hasattr(agent, 'multi_candidate_pipeline') and agent.multi_candidate_pipeline:
        pipeline = agent.multi_candidate_pipeline
        if hasattr(pipeline, '_validation_cache') and pipeline._validation_cache:
            vc = pipeline._validation_cache
            result["validation_cache"] = {
                "hits": vc.hits,
                "misses": vc.misses,
                "size": len(vc._cache) if hasattr(vc, '_cache') else 0,
                "max_size": vc.max_size if hasattr(vc, 'max_size') else 256,
            }

    # Solution cache
    if agent and hasattr(agent, 'solution_cache') and agent.solution_cache:
        try:
            sc_stats = agent.solution_cache.get_stats()
            result["solution_cache"] = sc_stats
        except Exception:
            pass

    # Timing stats from outcome tracker
    if agent and hasattr(agent, 'outcome_tracker') and agent.outcome_tracker:
        try:
            result["timing_stats"] = agent.outcome_tracker.get_cache_stats()
        except Exception:
            pass

    return jsonify(result)


@app.route('/api/analytics/metrics', methods=['GET'])
def analytics_metrics():
    """Prometheus metrics + agent stats + summary"""
    result = {}

    # Agent stats
    if agent:
        result["agent_stats"] = agent.stats

    # Prometheus
    if HAS_METRICS and metrics_registry:
        result["prometheus"] = metrics_registry.to_dict()

    # Summary from outcome tracker
    if agent and hasattr(agent, 'outcome_tracker') and agent.outcome_tracker:
        try:
            result["summary"] = agent.outcome_tracker.get_stats()
        except Exception:
            pass

    return jsonify(result)


@app.route('/api/analytics/summary', methods=['GET'])
def analytics_summary():
    """Comprehensive learning summary"""
    if not agent or not hasattr(agent, 'outcome_tracker') or not agent.outcome_tracker:
        return jsonify({"error": "OutcomeTracker not available"})
    try:
        summary = agent.outcome_tracker.get_learning_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/mode', methods=['GET', 'POST'])
def mode_endpoint():
    """Get or set execution mode (auto/fast/deep/search)"""
    global _current_mode

    if request.method == 'GET':
        return jsonify({
            "mode": _current_mode,
            "available": ["auto", "fast", "deep", "search"],
            "description": {
                "auto": "Automatic mode selection based on request",
                "fast": "Fast path only (PatternRouter, no LLM)",
                "deep": "Deep path (LLM + SWECAS)",
                "search": "Deep + web search"
            }
        })

    data = request.json or {}
    new_mode = data.get('mode', '').lower()

    if new_mode not in ["auto", "fast", "deep", "search"]:
        return jsonify({
            "success": False,
            "error": f"Invalid mode: {new_mode}. Use: auto, fast, deep, search"
        }), 400

    old_mode = _current_mode
    _current_mode = new_mode

    return jsonify({
        "success": True,
        "old_mode": old_mode,
        "new_mode": new_mode
    })


@app.route('/api/config', methods=['GET', 'POST'])
def config_endpoint():
    """Get or update server configuration"""
    if request.method == 'GET':
        return jsonify({
            "ollama_url": config.ollama_url,
            "fast_model": config.fast_model,
            "heavy_model": config.heavy_model,
            "max_tokens_fast": config.max_tokens_fast,
            "max_tokens_deep": config.max_tokens_deep,
            "ollama_timeout": config.ollama_timeout,
            "project_root": config.project_root
        })

    data = request.json or {}

    if 'fast_model' in data:
        config.fast_model = data['fast_model']
    if 'heavy_model' in data:
        config.heavy_model = data['heavy_model']
    if 'ollama_url' in data:
        config.ollama_url = data['ollama_url']
    if 'max_tokens_fast' in data:
        config.max_tokens_fast = int(data['max_tokens_fast'])
    if 'max_tokens_deep' in data:
        config.max_tokens_deep = int(data['max_tokens_deep'])

    return jsonify({
        "success": True,
        "config": {
            "fast_model": config.fast_model,
            "heavy_model": config.heavy_model,
            "ollama_url": config.ollama_url
        }
    })


@app.route('/api/timeout', methods=['GET', 'POST'])
def timeout_endpoint():
    """Get or update timeout preferences (used by Timeout Menu dropdown)"""
    if agent is None:
        return jsonify({"success": False, "error": "Agent not initialized"}), 503

    if request.method == 'GET':
        return jsonify({"success": True, **agent.user_prefs.to_dict()})

    # POST — validate and update
    data = request.json or {}
    errors = []

    if 'priority' in data and data['priority'] not in ('speed', 'balanced', 'quality'):
        errors.append("priority must be one of: speed, balanced, quality")
    if 'max_wait' in data:
        try:
            mw = float(data['max_wait'])
            if mw < 10 or mw > 3600:
                errors.append("max_wait must be between 10 and 3600")
        except (ValueError, TypeError):
            errors.append("max_wait must be a number")

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    agent.user_prefs.update(data)
    agent.timeout_config = agent.user_prefs.to_timeout_config()
    # Update LLM client timeout config if available
    if hasattr(agent, 'llm_client') and hasattr(agent.llm_client, 'timeout_config'):
        agent.llm_client.timeout_config = agent.timeout_config

    return jsonify({"success": True, **agent.user_prefs.to_dict()})


@app.route('/api/models', methods=['GET'])
def list_models():
    """List available Ollama models"""
    model_list = []

    try:
        r = requests.get(f"{config.ollama_url}/api/tags", timeout=5)
        if r.status_code == 200:
            for m in r.json().get('models', []):
                model_list.append({
                    'name': m['name'],
                    'size': m.get('size', 0),
                    'modified': m.get('modified_at', ''),
                    'family': m.get('details', {}).get('family', ''),
                    'params': m.get('details', {}).get('parameter_size', ''),
                    'provider': 'ollama'
                })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({
        "success": True,
        "models": model_list,
        "current_fast": config.fast_model,
        "current_heavy": config.heavy_model
    })


@app.route('/api/models/switch', methods=['POST'])
def switch_model():
    """Switch active model (fast or heavy)"""
    data = request.json or {}
    model_type = data.get('type', 'heavy')  # fast or heavy
    new_model = data.get('model', '')

    if not new_model:
        return jsonify({'success': False, 'error': 'No model specified'}), 400

    if model_type == 'fast':
        old_model = config.fast_model
        config.fast_model = new_model
    else:
        old_model = config.heavy_model
        config.heavy_model = new_model

    print(f"  Model switched ({model_type}): {old_model} -> {new_model}")

    return jsonify({
        'success': True,
        'type': model_type,
        'old_model': old_model,
        'new_model': new_model
    })


@app.route('/api/clear', methods=['POST'])
def clear_state():
    """Clear server state (stats, debug info)"""
    global _stats, _last_debug

    _stats = {
        "requests_total": 0,
        "requests_fast_path": 0,
        "requests_deep_path": 0,
        "requests_search": 0,
        "last_request_time": None,
        "start_time": datetime.now().isoformat()
    }

    _last_debug = {
        "input": "",
        "route_result": None,
        "tool_calls": [],
        "response": "",
        "timestamp": None
    }

    return jsonify({"success": True, "message": "State cleared"})


@app.route('/api/debug/last', methods=['GET'])
def debug_last_request():
    """Get debug info about the last request"""
    return jsonify(_last_debug)


@app.route('/api/debug/route', methods=['POST'])
def debug_route():
    """Test routing without executing - shows what the router would do"""
    print(f"[DEBUG ROUTE] router.patterns count: {len(router.patterns)}")
    print(f"[DEBUG ROUTE] router id: {id(router)}")
    data = request.json or {}
    message = data.get('message', '')

    if not message:
        return jsonify({"error": "No message provided"}), 400

    # Get routing decision
    result = router.match(message)
    chain_results = router.match_chain(message) if ';' in message else []

    return jsonify({
        "input": message,
        "route": result if result else None,
        "is_chain": ';' in message,
        "chain_results": chain_results if chain_results else [],
        "router_patterns_count": len(router.patterns)
    })


# ============================================================================
# PHASE 7: WORKING MEMORY & CHECKPOINTS
# ============================================================================

# In-memory checkpoint storage (per-session, resets on restart)
_checkpoints = []  # List[{id, timestamp, description, state}]
_checkpoint_counter = 0

# Working memory history (last N snapshots from SSE events)
_memory_history = []  # List[{timestamp, iteration, facts_count, tool_log_length, state}]
_MAX_MEMORY_HISTORY = 50


@app.route('/api/memory/current', methods=['GET'])
def get_current_memory():
    """Get the latest working memory snapshot"""
    if _memory_history:
        return jsonify(_memory_history[-1])
    return jsonify({"goal": "", "plan": [], "facts": {}, "decisions": [], "tool_log": [], "iteration": 0})


@app.route('/api/memory/history', methods=['GET'])
def get_memory_history():
    """Get working memory history (last N snapshots)"""
    limit = request.args.get('limit', 20, type=int)
    return jsonify(_memory_history[-limit:])


@app.route('/api/memory/record', methods=['POST'])
def record_memory_snapshot():
    """Record a working memory snapshot (called from SSE handler)"""
    global _memory_history
    data = request.json or {}
    data['timestamp'] = datetime.now().isoformat()
    _memory_history.append(data)
    if len(_memory_history) > _MAX_MEMORY_HISTORY:
        _memory_history = _memory_history[-_MAX_MEMORY_HISTORY:]
    return jsonify({"success": True, "count": len(_memory_history)})


@app.route('/api/checkpoints', methods=['GET', 'POST'])
def checkpoints():
    """List or create checkpoints"""
    global _checkpoint_counter, _checkpoints

    if request.method == 'GET':
        # Return list without full state to keep response light
        return jsonify([{
            "id": cp["id"],
            "timestamp": cp["timestamp"],
            "description": cp["description"],
            "facts_count": len(cp.get("state", {}).get("facts", {})),
            "tool_log_length": len(cp.get("state", {}).get("tool_log", [])),
        } for cp in _checkpoints])

    # POST: Create new checkpoint
    data = request.json or {}
    _checkpoint_counter += 1
    cp = {
        "id": f"cp-{_checkpoint_counter}",
        "timestamp": datetime.now().isoformat(),
        "description": data.get("description", f"Checkpoint #{_checkpoint_counter}"),
        "state": data.get("state", _memory_history[-1] if _memory_history else {}),
    }
    _checkpoints.append(cp)
    return jsonify({"success": True, "checkpoint": {
        "id": cp["id"],
        "timestamp": cp["timestamp"],
        "description": cp["description"],
    }})


@app.route('/api/checkpoints/<checkpoint_id>', methods=['GET', 'DELETE'])
def checkpoint_detail(checkpoint_id):
    """Get or delete a specific checkpoint"""
    global _checkpoints
    cp = next((c for c in _checkpoints if c["id"] == checkpoint_id), None)
    if not cp:
        return jsonify({"error": "Checkpoint not found"}), 404

    if request.method == 'DELETE':
        _checkpoints = [c for c in _checkpoints if c["id"] != checkpoint_id]
        return jsonify({"success": True, "message": f"Checkpoint {checkpoint_id} deleted"})

    return jsonify(cp)


# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="QwenCode Unified Server")
    parser.add_argument("--port", type=int, default=5002, help="Server port")
    parser.add_argument("--no-warmup", action="store_true", help="Skip model warmup")
    parser.add_argument("--no-auto-start", action="store_true", help="Don't auto-start Ollama")
    parser.add_argument("--no-exit-handler", action="store_true", help="Disable exit handler")
    parser.add_argument("--open", action="store_true", help="Open browser")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    args = parser.parse_args()

    print("=" * 60)
    print("  QWENCODE UNIFIED SERVER")
    print("  Единый источник правды")
    print("=" * 60)
    print(f"  Project root:      {config.project_root}")
    print(f"  Fast model:        {config.fast_model}")
    print(f"  Heavy model:       {config.heavy_model}")
    print(f"  Ollama URL:        {config.ollama_url}")
    print(f"  Port:              {args.port}")
    print(f"  Ollama auto-start: {'[+] enabled' if not args.no_auto_start else '[-] disabled'}")
    print(f"  SWECAS:            {'[+] enabled' if HAS_SWECAS else '[-] disabled'}")
    print(f"  Orchestrator:      {'[+] enabled' if orchestrator else '[-] disabled'}")
    print(f"  Agent:             {'[+] enabled' if agent else '[-] disabled'}")
    print(f"  ApprovalManager:   {'[+] enabled' if HAS_APPROVAL else '[-] disabled'}")
    print(f"  ExitHandler:       {'[+] enabled' if HAS_EXIT_HANDLER and not args.no_exit_handler else '[-] disabled'}")
    print("=" * 60)

    # Register exit handler
    # При выходе из CLI: проверка сервера + прогрев модели
    if HAS_EXIT_HANDLER and not args.no_exit_handler:
        exit_cfg = ExitHandlerConfig(
            server_url=f"http://localhost:{args.port}",
            ollama_url=config.ollama_url,
            model=config.fast_model,
            server_script="qwencode_unified_server.py",
            auto_start_server=True,
            auto_warmup=True,
            verbose=True
        )
        set_exit_config(exit_cfg)
        register_exit_handler()
        print("  [EXIT HANDLER] При выходе: автозапуск сервера + прогрев модели")

    # Warmup (with optional Ollama auto-start)
    if not args.no_warmup:
        warmup_model(auto_start=not args.no_auto_start)

    # Open browser
    if args.open:
        import webbrowser
        webbrowser.open(f"http://localhost:{args.port}")

    print(f"\n  Ready at: http://localhost:{args.port}")
    print("=" * 60)

    # Run server
    app.run(host='0.0.0.0', port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
