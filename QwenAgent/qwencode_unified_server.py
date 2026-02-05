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
    max_tokens_fast: int = 400
    max_tokens_deep: int = 800

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
    health_data = {
        "status": "ok",
        "fast_model": config.fast_model,
        "heavy_model": config.heavy_model,
        "ollama_url": config.ollama_url,
        "project_root": config.project_root,
        "tools_available": ["grep", "read", "write", "edit", "bash", "ls", "glob", "find", "help"],
        "pattern_router": True,
        "unified_tools": True,
        "swecas": HAS_SWECAS,
        "approval_manager": HAS_APPROVAL,
    }

    # Add approval stats if available
    if HAS_APPROVAL and approval_manager:
        health_data["approval_stats"] = approval_manager.get_stats()

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

    # 2. Deep Path (LLM) with SWECAS classification
    print(f"[DEEP PATH] Using LLM: {config.fast_model}")

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
            route = router.match(message)

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

            # 3. Deep Path (LLM) with SWECAS classification
            print(f"[DEEP PATH] LLM: {config.fast_model}")

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
# WARMUP
# ============================================================================

def warmup_model():
    """Warmup model before serving"""
    print(f"\n  [WARMUP] Prогрев модели: {config.fast_model}")

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
        print(f"  [WARMUP] Ollama not running! Start with: ollama serve")
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
    return jsonify({
        **_stats,
        "uptime_seconds": (datetime.now() - datetime.fromisoformat(_stats["start_time"])).total_seconds(),
        "config": {
            "fast_model": config.fast_model,
            "heavy_model": config.heavy_model,
            "project_root": config.project_root
        },
        "swecas_enabled": HAS_SWECAS,
        "approval_enabled": HAS_APPROVAL
    })


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
# MAIN
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="QwenCode Unified Server")
    parser.add_argument("--port", type=int, default=5002, help="Server port")
    parser.add_argument("--no-warmup", action="store_true", help="Skip model warmup")
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
    print(f"  SWECAS:            {'[+] enabled' if HAS_SWECAS else '[-] disabled'}")
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

    # Warmup
    if not args.no_warmup:
        warmup_model()

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
