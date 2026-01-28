"""
QwenCode Agent - Full Claude Code Clone
All features of Claude Code, powered by Qwen LLM
"""

import os
import re
import json
import requests
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from .tools_extended import ExtendedTools, EXTENDED_TOOL_REGISTRY, execute_tool, get_tools_description
from .router import PatternRouter, HybridRouter, RouteResult
from .cot_engine import CoTEngine
from .plan_mode import PlanMode
from .subagent import SubAgentManager, TaskTracker, TaskTool
from .ducs_classifier import DUCSClassifier
from .swecas_classifier import SWECASClassifier


class ExecutionMode:
    """Режимы выполнения с автоматической эскалацией"""
    FAST = "fast"           # Быстрые запросы (по умолчанию)
    DEEP = "deep"           # Критические задачи (6 шагов Мински)
    DEEP_SEARCH = "deep_search"  # Поиск в интернете

    # Цепочка эскалации при timeout
    ESCALATION_CHAIN = {
        FAST: DEEP,
        DEEP: DEEP_SEARCH,
        DEEP_SEARCH: None  # Конец цепочки
    }

    @classmethod
    def get_icon(cls, mode):
        icons = {
            cls.FAST: "⚡",
            cls.DEEP: "🧠",
            cls.DEEP_SEARCH: "🌐"
        }
        return icons.get(mode, "")


@dataclass
class QwenCodeConfig:
    """Configuration for QwenCode agent"""
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:32b"
    max_iterations: int = 10
    timeout: int = 120
    working_dir: str = field(default_factory=os.getcwd)
    deep_mode: bool = False
    verbose: bool = True
    # Новые параметры режимов
    execution_mode: str = ExecutionMode.FAST
    auto_escalation: bool = True  # Автоматическая эскалация при timeout
    escalation_timeout: int = 30  # Timeout для эскалации (секунды)


class QwenCodeAgent:
    """
    QwenCode - Full Claude Code Clone

    Features:
    - All Claude Code tools (15+)
    - Chain-of-Thought reasoning
    - Plan Mode
    - Sub-agents (Task tool)
    - NO-LLM pattern routing
    - Memory and context
    """

    VERSION = "1.0.0"

    SYSTEM_PROMPT = """You are QwenCode, an AI coding assistant that works with files using tools.

WORKFLOW — ALWAYS USE TOOLS FOR FILE TASKS:
1. Read the file FIRST: [TOOL: read(file_path="...")]
2. Edit the file: [TOOL: edit(file_path="...", old_string="...", new_string="...")]
3. Verify if needed: [TOOL: read(file_path="...")]

WHEN TO USE TOOLS (ALWAYS):
- "add function to file.py" → [TOOL: read(file_path="file.py")] then [TOOL: edit(...)]
- "fix bug in file.py" → [TOOL: read(file_path="file.py")] then [TOOL: edit(...)]
- "create new file" → [TOOL: write(file_path="...", content="...")]
- "run tests" → [TOOL: bash(command="python -m pytest")]
- "show file" → [TOOL: read(file_path="...")]
- "list files" → [TOOL: ls(path=".")]
- "find files" → [TOOL: glob(pattern="**/*.py")]
- "search for X" → [TOOL: grep(pattern="X")]

WHEN NOT TO USE TOOLS (text answer only):
- "explain what this code does" → answer in text
- "what is a decorator?" → answer in text
- "show me an algorithm" → show in markdown code block

RESPONSE LANGUAGE:
- Respond in the SAME language as the user's question

{tools_description}

TOOL FORMAT:
[TOOL: tool_name(param1="value1", param2="value2")]

Use \\n for newlines inside tool parameters.

FORBIDDEN ACTIONS:
- NEVER create files that the user did not ask for — no demo files, no sample files, no tutorial files
- NEVER use invented function names from training data — only names from the user's actual code
- ONLY modify files explicitly mentioned by the user's request
- When using write(), include ALL original code — do NOT omit unchanged parts
- NEVER invent new files to demonstrate a concept when the user asked to fix an existing file
- NEVER write partial files — always write the COMPLETE file content

VIOLATION CHECK (before EVERY tool call):
- Is this the user's TARGET file, not an invented example?
- Am I using code from the USER'S REQUEST, not my own invented examples?
- Does write() contain the COMPLETE file content, not a fragment?

IMPORTANT: For ANY task involving files, ALWAYS use tools. Never just show code in markdown when the user wants to modify a file.

Current working directory: {working_dir}
"""

    def __init__(self, config: QwenCodeConfig = None):
        self.config = config or QwenCodeConfig()

        # Core components
        self.router = HybridRouter()
        self.cot_engine = CoTEngine()
        self.plan_mode = PlanMode()
        self.task_tracker = TaskTracker()
        self.ducs = DUCSClassifier()
        self.swecas = SWECASClassifier()

        # Sub-agent manager (needs LLM client)
        self.subagent_manager = SubAgentManager(self._call_llm_simple)
        self.task_tool = TaskTool(self.subagent_manager)

        # State
        self.conversation_history: List[Dict[str, str]] = []
        self.tool_call_history: List[Dict[str, Any]] = []
        self.working_dir = self.config.working_dir

        # Statistics
        self.stats = {
            "total_requests": 0,
            "tool_calls": 0,
            "llm_calls": 0,
            "pattern_matches": 0,
            "cot_sessions": 0,
            "plan_mode_sessions": 0,
            "mode_escalations": 0,
            "web_searches": 0
        }

        # Mode tracking
        self.current_mode = self.config.execution_mode
        self.mode_history = []  # История переключений режимов

    def process(self, user_input: str) -> Dict[str, Any]:
        """
        Process user input - main entry point
        Returns structured response with tool calls, thinking, etc.
        """
        self.stats["total_requests"] += 1

        result = {
            "input": user_input,
            "response": "",
            "tool_calls": [],
            "thinking": [],
            "route_method": "",
            "iterations": 0,
            "plan_mode": self.plan_mode.is_active
        }

        # Check for special commands
        special = self._handle_special_commands(user_input)
        if special:
            result["response"] = special["response"]
            result["route_method"] = "special_command"
            return result

        # STEP 1: Try pattern routing (NO-LLM)
        route = self.router.route(user_input)

        if route.confidence >= 0.85 and route.tool:
            # Direct tool execution without LLM
            self.stats["pattern_matches"] += 1
            result["route_method"] = "pattern"

            tool_result = execute_tool(route.tool, **route.params)
            result["tool_calls"].append({
                "tool": route.tool,
                "params": route.params,
                "result": tool_result
            })

            result["response"] = self._format_tool_result(route.tool, tool_result)
            return result

        # STEP 1.5: NO-LLM pre-read for file modification tasks
        # Detects "add/fix/update X in file.py" and auto-reads the file
        # so LLM gets file context on first call (saves 1 round-trip)
        pre_read_context = self._try_pre_read(user_input)
        if pre_read_context:
            result["tool_calls"].append(pre_read_context["tool_call"])

        # STEP 1.6: DUCS domain classification (NO-LLM)
        ducs_result = self.ducs.classify(user_input)
        if ducs_result.get("confidence", 0) >= 0.5:
            result["ducs_code"] = ducs_result.get("ducs_code")
            result["ducs_category"] = ducs_result.get("category", "")
            result["ducs_confidence"] = ducs_result.get("confidence", 0)
        self._current_ducs = ducs_result

        # STEP 1.7: SWECAS bug classification (NO-LLM)
        pre_read_content = pre_read_context.get("content") if pre_read_context else None
        swecas_result = self.swecas.classify(user_input, file_content=pre_read_content)
        if swecas_result.get("confidence", 0) >= 0.6:
            result["swecas_code"] = swecas_result.get("swecas_code")
            result["swecas_category"] = swecas_result.get("name", "")
            result["swecas_confidence"] = swecas_result.get("confidence", 0)
        self._current_swecas = swecas_result

        # STEP 2: LLM processing
        result["route_method"] = "llm"

        # Build context
        system_prompt = self.SYSTEM_PROMPT.format(
            tools_description=get_tools_description(),
            working_dir=self.working_dir
        )

        # Add plan mode context if active
        if self.plan_mode.is_active:
            system_prompt += "\n\n[PLAN MODE ACTIVE - Read-only operations only until plan is approved]"

        # CoT mode for complex tasks (SWECAS-enhanced when applicable)
        if self.config.deep_mode or self._is_complex_task(user_input):
            self.stats["cot_sessions"] += 1
            self.cot_engine.enable_deep_mode(True)
            # Use SWECAS context if confidence is high enough
            swecas_ctx = swecas_result if swecas_result.get("confidence", 0) >= 0.6 else None
            prompt = self.cot_engine.create_thinking_prompt(
                user_input, ducs_context=ducs_result, swecas_context=swecas_ctx
            )
        else:
            self.cot_engine.enable_deep_mode(False)
            prompt = user_input

        # Inject pre-read file content into prompt (NO-LLM optimization)
        # Content has line numbers stripped so LLM can use exact strings for old_string
        if pre_read_context and pre_read_context.get("content"):
            file_path = pre_read_context["file_path"]
            file_content = pre_read_context["content"]
            prompt = f"""{prompt}

I already read {file_path} for you. Here is the EXACT file content (use these exact strings for old_string):
```
{file_content}
```

Now use [TOOL: edit(file_path="{file_path}", old_string="...", new_string="...")] to make the changes.
IMPORTANT: Copy old_string EXACTLY from the file content above. Do NOT add line numbers."""

        # Agentic loop - iterate until done or max iterations
        iteration = 0
        current_prompt = prompt
        full_response = ""

        while iteration < self.config.max_iterations:
            iteration += 1
            result["iterations"] = iteration

            # Call LLM
            llm_response = self._call_llm(current_prompt, system_prompt)
            self.stats["llm_calls"] += 1

            if not llm_response:
                # CHUNKED CONTEXT: If deep mode + SWECAS, retry with compressed prompt
                if self.config.deep_mode and hasattr(self, '_current_swecas'):
                    swecas = self._current_swecas
                    if swecas.get("confidence", 0) >= 0.6 and iteration == 1:
                        # Reduce context: keep only SWECAS template + file + task
                        fix_hint = swecas.get("fix_hint", "")
                        compressed = f"""Fix this bug. Category: SWECAS-{swecas.get('swecas_code', 0)} ({swecas.get('name', '')}).
Hint: {fix_hint}
Task: {user_input}"""
                        if pre_read_context and pre_read_context.get("content"):
                            file_path = pre_read_context["file_path"]
                            # Truncate file content to fit context window
                            file_content = pre_read_context["content"][:3000]
                            compressed += f"\n\nFile {file_path}:\n```\n{file_content}\n```\nUse [TOOL: edit(...)] to fix."
                        current_prompt = compressed
                        continue  # Retry with compressed prompt

                result["response"] = "Error: No response from LLM"
                break

            full_response += llm_response + "\n"

            # Parse tool calls from response
            tool_calls = self._parse_tool_calls(llm_response)

            if not tool_calls:
                # No more tool calls - we're done
                result["response"] = llm_response
                break

            # Execute tool calls
            tool_results = []
            for tool_name, params in tool_calls:
                self.stats["tool_calls"] += 1

                # Check plan mode restrictions
                if self.plan_mode.is_active and tool_name in ["write", "edit", "bash"]:
                    tool_result = {"success": False, "error": "Cannot modify files in plan mode"}
                else:
                    tool_result = execute_tool(tool_name, **params)

                result["tool_calls"].append({
                    "tool": tool_name,
                    "params": params,
                    "result": tool_result
                })
                tool_results.append((tool_name, tool_result))

            # Build continuation prompt with tool results
            current_prompt = self._build_continuation_prompt(tool_results)

        # Parse thinking if CoT mode
        if self.config.deep_mode:
            cot_steps = self.cot_engine.parse_cot_response(full_response)
            result["thinking"] = [step.thought for step in cot_steps if step.thought]

        # Store in history
        self.conversation_history.append({
            "role": "user",
            "content": user_input
        })
        self.conversation_history.append({
            "role": "assistant",
            "content": result["response"]
        })

        return result

    def process_stream(self, user_input: str):
        """
        Generator version of process() — yields SSE events during processing.
        Events: status, tool_start, tool_result, thinking, response, done
        """
        self.stats["total_requests"] += 1

        # Check for special commands
        special = self._handle_special_commands(user_input)
        if special:
            yield {"event": "response", "text": special["response"], "route_method": "special_command"}
            yield {"event": "done"}
            return

        # STEP 1: Try pattern routing (NO-LLM)
        route = self.router.route(user_input)

        if route.confidence >= 0.85 and route.tool:
            self.stats["pattern_matches"] += 1
            yield {"event": "tool_start", "tool": route.tool, "params": route.params}
            tool_result = execute_tool(route.tool, **route.params)
            self.stats["tool_calls"] += 1
            yield {"event": "tool_result", "tool": route.tool, "params": route.params, "result": tool_result}
            yield {"event": "response", "text": self._format_tool_result(route.tool, tool_result), "route_method": "pattern"}
            yield {"event": "done"}
            return

        # STEP 1.5: NO-LLM pre-read for file modification tasks
        pre_read_context = self._try_pre_read(user_input)
        if pre_read_context:
            yield {"event": "tool_start", "tool": "read", "params": pre_read_context["tool_call"]["params"]}
            yield {"event": "tool_result", "tool": "read", "params": pre_read_context["tool_call"]["params"], "result": pre_read_context["tool_call"]["result"]}

        # STEP 1.6: DUCS domain classification (NO-LLM)
        ducs_result = self.ducs.classify(user_input)
        if ducs_result.get("confidence", 0) >= 0.5:
            yield {"event": "status", "text": f"Domain: {ducs_result.get('category', '')}"}
        self._current_ducs = ducs_result

        # STEP 1.7: SWECAS bug classification (NO-LLM)
        pre_read_content_stream = pre_read_context.get("content") if pre_read_context else None
        swecas_result = self.swecas.classify(user_input, file_content=pre_read_content_stream)
        if swecas_result.get("confidence", 0) >= 0.6:
            yield {"event": "status", "text": f"Bug: SWECAS-{swecas_result.get('swecas_code', '?')} ({swecas_result.get('name', '')})"}
        self._current_swecas = swecas_result

        # STEP 2: LLM processing
        yield {"event": "status", "text": "Thinking..."}

        system_prompt = self.SYSTEM_PROMPT.format(
            tools_description=get_tools_description(),
            working_dir=self.working_dir
        )

        if self.plan_mode.is_active:
            system_prompt += "\n\n[PLAN MODE ACTIVE - Read-only operations only until plan is approved]"

        # CoT mode (SWECAS-enhanced when applicable)
        if self.config.deep_mode or self._is_complex_task(user_input):
            self.stats["cot_sessions"] += 1
            self.cot_engine.enable_deep_mode(True)
            swecas_ctx = swecas_result if swecas_result.get("confidence", 0) >= 0.6 else None
            prompt = self.cot_engine.create_thinking_prompt(
                user_input, ducs_context=ducs_result, swecas_context=swecas_ctx
            )
        else:
            self.cot_engine.enable_deep_mode(False)
            prompt = user_input

        # Inject pre-read file content (line numbers stripped for exact matching)
        if pre_read_context and pre_read_context.get("content"):
            file_path = pre_read_context["file_path"]
            file_content = pre_read_context["content"]
            prompt = f"""{prompt}

I already read {file_path} for you. Here is the EXACT file content (use these exact strings for old_string):
```
{file_content}
```

Now use [TOOL: edit(file_path="{file_path}", old_string="...", new_string="...")] to make the changes.
IMPORTANT: Copy old_string EXACTLY from the file content above. Do NOT add line numbers."""

        # Agentic loop
        iteration = 0
        current_prompt = prompt
        all_tool_calls = []

        while iteration < self.config.max_iterations:
            iteration += 1
            yield {"event": "status", "text": f"Step {iteration}..."}

            llm_response = self._call_llm(current_prompt, system_prompt)
            self.stats["llm_calls"] += 1

            if not llm_response:
                yield {"event": "response", "text": "Error: No response from LLM", "route_method": "llm"}
                break

            tool_calls = self._parse_tool_calls(llm_response)

            if not tool_calls:
                # No more tool calls — final response
                if self.config.deep_mode:
                    cot_steps = self.cot_engine.parse_cot_response(llm_response)
                    thinking = [step.thought for step in cot_steps if step.thought]
                    if thinking:
                        yield {"event": "thinking", "steps": thinking}

                yield {"event": "response", "text": llm_response, "route_method": "llm"}
                break

            # Execute tool calls
            tool_results = []
            for tool_name, params in tool_calls:
                self.stats["tool_calls"] += 1
                yield {"event": "tool_start", "tool": tool_name, "params": params}

                if self.plan_mode.is_active and tool_name in ["write", "edit", "bash"]:
                    tool_result = {"success": False, "error": "Cannot modify files in plan mode"}
                else:
                    tool_result = execute_tool(tool_name, **params)

                all_tool_calls.append({"tool": tool_name, "params": params, "result": tool_result})
                yield {"event": "tool_result", "tool": tool_name, "params": params, "result": tool_result}
                tool_results.append((tool_name, tool_result))

            current_prompt = self._build_continuation_prompt(tool_results)

        # Store in history
        self.conversation_history.append({"role": "user", "content": user_input})
        self.conversation_history.append({"role": "assistant", "content": "(streamed response)"})

        yield {"event": "done"}

    def _get_num_predict(self, ducs_result: dict = None) -> int:
        """Adjust max tokens based on DUCS classification and mode"""
        if self.config.deep_mode:
            return 4096  # Deep needs CoT reasoning + tool calls
        if ducs_result and ducs_result.get("confidence", 0) >= 0.85:
            return 512   # Known domain, shorter answers
        return 2048      # Unknown, full output

    def _call_llm(self, prompt: str, system: str = None) -> Optional[str]:
        """Call Ollama LLM using generate API"""
        try:
            full_prompt = ""
            if system:
                full_prompt = f"System: {system}\n\n"

            for msg in self.conversation_history[-8:]:
                role = "User" if msg["role"] == "user" else "Assistant"
                full_prompt += f"{role}: {msg['content']}\n\n"

            full_prompt += f"User: {prompt}\n\nAssistant:"

            num_predict = self._get_num_predict(getattr(self, '_current_ducs', None))

            response = requests.post(
                f"{self.config.ollama_url}/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": num_predict
                    }
                },
                timeout=180
            )

            if response.status_code == 200:
                return response.json().get("response", "")
            return None

        except Exception as e:
            if self.config.verbose:
                print(f"Ollama Error: {e}")
            return None

    def _call_llm_search(self, prompt: str) -> Optional[str]:
        """Lightweight LLM call for search result analysis"""
        try:
            response = requests.post(
                f"{self.config.ollama_url}/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": f"User: {prompt}\n\nAssistant:",
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 256
                    }
                },
                timeout=120
            )
            if response.status_code == 200:
                return response.json().get("response", "")
            return None
        except Exception as e:
            if self.config.verbose:
                print(f"LLM Search Error: {e}")
            return None

    def _call_llm_simple(self, prompt: str, system: str = None) -> str:
        """Simple LLM call for sub-agents"""
        try:
            response = requests.post(
                f"{self.config.ollama_url}/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": prompt,
                    "system": system or "",
                    "stream": False
                },
                timeout=self.config.timeout
            )
            if response.status_code == 200:
                return response.json().get("response", "")
            return ""
        except:
            return ""

    # Valid parameters for each tool (for filtering invalid LLM arguments)
    VALID_TOOL_PARAMS = {
        'bash': ['command', 'timeout', 'working_dir'],
        'read': ['file_path', 'path', 'offset', 'limit'],
        'write': ['file_path', 'path', 'content'],
        'edit': ['file_path', 'path', 'old_string', 'new_string', 'old_str', 'new_str', 'replace_all'],
        'ls': ['path', 'directory', 'show_hidden'],
        'glob': ['pattern', 'path'],
        'grep': ['pattern', 'path', 'include', 'context_before', 'context_after'],
        'git': ['command', 'working_dir'],
        'tree': ['path', 'max_depth', 'show_hidden'],
        'diff': ['file1', 'file2'],
        'web_fetch': ['url', 'prompt'],
        'web_search': ['query', 'num_results'],
        'notebook_read': ['notebook_path'],
        'notebook_edit': ['notebook_path', 'cell_index', 'new_source', 'cell_type', 'edit_mode']
    }

    def _parse_tool_calls(self, response: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Parse tool calls from LLM response with validation"""
        tool_calls = []

        # Pattern: [TOOL: name(params)]
        pattern = r'\[TOOL:\s*(\w+)\((.*?)\)\]'
        matches = re.finditer(pattern, response, re.DOTALL)

        for match in matches:
            tool_name = match.group(1).lower()  # Normalize to lowercase
            params_str = match.group(2)

            # Check if tool exists
            if tool_name not in EXTENDED_TOOL_REGISTRY:
                print(f"[PARSE] Unknown tool: {tool_name}")
                continue

            # Parse parameters
            params = {}
            if params_str.strip():
                # Handle key="value" format
                param_pattern = r'(\w+)\s*=\s*["\']([^"\']*)["\']|(\w+)\s*=\s*([^,\)]+)'
                for pm in re.finditer(param_pattern, params_str):
                    if pm.group(1):
                        # Process escape sequences in string values (convert \n to real newlines)
                        value = pm.group(2)
                        value = self._process_escape_sequences(value)
                        params[pm.group(1)] = value
                    elif pm.group(3):
                        value = pm.group(4).strip()
                        # Try to parse as int/float/bool
                        if value.lower() == 'true':
                            value = True
                        elif value.lower() == 'false':
                            value = False
                        elif value.isdigit():
                            value = int(value)
                        params[pm.group(3)] = value

            # VALIDATION: Filter only valid params for this tool
            valid_params = self.VALID_TOOL_PARAMS.get(tool_name, [])
            filtered_params = {}
            invalid_params = []

            for key, value in params.items():
                if key in valid_params:
                    filtered_params[key] = value
                else:
                    invalid_params.append(key)

            if invalid_params:
                print(f"[PARSE] Filtered invalid params for {tool_name}: {invalid_params}")

            # Normalize param names (path -> file_path for read/write/edit)
            if tool_name in ['read', 'write', 'edit'] and 'path' in filtered_params and 'file_path' not in filtered_params:
                filtered_params['file_path'] = filtered_params.pop('path')

            # Add to list if we have valid params or tool needs no params
            if filtered_params or tool_name in ['ls']:  # ls can work without params
                tool_calls.append((tool_name, filtered_params))
            elif tool_name == 'bash' and 'command' not in filtered_params:
                print(f"[PARSE] bash tool missing 'command' parameter, skipping")
            else:
                tool_calls.append((tool_name, filtered_params))

        return tool_calls

    def _process_escape_sequences(self, value: str) -> str:
        """
        Convert escape sequences in strings to actual characters.
        E.g., '\\n' -> '\n', '\\t' -> '\t'
        This is needed because LLM outputs escape sequences as text.
        """
        try:
            # Use codecs to decode unicode escape sequences
            import codecs
            # Only process if there are escape sequences
            if '\\' in value:
                # Decode common escape sequences
                value = value.replace('\\n', '\n')
                value = value.replace('\\t', '\t')
                value = value.replace('\\r', '\r')
                value = value.replace('\\\\', '\\')
            return value
        except Exception:
            return value

    def _build_continuation_prompt(self, tool_results: List[Tuple[str, Dict]]) -> str:
        """Build prompt with tool results for continuation"""
        lines = ["Tool results:"]
        for tool_name, result in tool_results:
            lines.append(f"\n[{tool_name}]:")
            if result.get("success"):
                # Truncate large results
                result_str = json.dumps(result, indent=2, default=str)
                if len(result_str) > 3000:
                    result_str = result_str[:3000] + "\n...[truncated]"
                lines.append(result_str)
            else:
                lines.append(f"Error: {result.get('error', 'Unknown error')}")

        lines.append("\nBased on these results, continue with the task. Use more tools if needed, or provide the final answer.")
        return "\n".join(lines)

    def _format_tool_result(self, tool_name: str, result: Dict[str, Any]) -> str:
        """Format tool result for display"""
        if not result.get("success", True):
            return f"Error: {result.get('error', 'Unknown error')}"

        if tool_name == "ls":
            items = result.get("items", [])
            lines = [f"Directory: {result.get('path', '.')}"]
            for item in items[:50]:
                prefix = "[D]" if item.get("type") == "dir" else "[F]"
                lines.append(f"{prefix} {item['name']}")
            if len(items) > 50:
                lines.append(f"... and {len(items) - 50} more")
            return "\n".join(lines)

        elif tool_name == "read":
            return result.get("content", "")

        elif tool_name == "glob":
            files = result.get("files", [])
            if not files:
                return "No files found"
            return "\n".join([f["path"] for f in files[:50]])

        elif tool_name == "grep":
            matches = result.get("matches", [])
            if not matches:
                return "No matches found"
            lines = []
            for m in matches[:30]:
                lines.append(f"{m['file']}:{m['line_number']}: {m['line']}")
            return "\n".join(lines)

        elif tool_name == "bash":
            output = result.get("stdout", "")
            if result.get("stderr"):
                output += f"\n[stderr]: {result['stderr']}"
            return output or "(no output)"

        elif tool_name == "write":
            return f"Written {result.get('bytes_written', 0)} bytes to {result.get('file_path', 'file')}"

        elif tool_name == "edit":
            return f"Made {result.get('replacements', 0)} replacement(s) in {result.get('file_path', 'file')}"

        else:
            return json.dumps(result, indent=2, default=str)

    def _handle_special_commands(self, user_input: str) -> Optional[Dict[str, Any]]:
        """Handle special commands like /plan, /help, etc."""
        cmd = user_input.strip().lower()

        if cmd == "/help":
            return {
                "response": """QwenCode Commands:
/help             - Show this help
/plan             - Enter plan mode
/plan exit        - Exit plan mode
/plan status      - Show plan status
/tasks            - List tasks
/stats            - Show statistics
/clear            - Clear conversation
/model            - Show current model

MODE SWITCHING:
/mode             - Show current mode status
/mode fast        - Switch to FAST mode (quick queries)
/mode deep        - Switch to DEEP mode (CoT reasoning)
/mode search      - Switch to DEEP SEARCH mode (web search)
/deep on          - Enable deep mode (alias for /mode deep)
/deep off         - Disable deep mode (alias for /mode fast)
/escalation on    - Enable auto-escalation
/escalation off   - Disable auto-escalation

MODE PREFIXES (in queries):
[DEEP] query      - Run query in DEEP mode
[SEARCH] query    - Run query in DEEP SEARCH mode
--deep query      - Run query in DEEP mode
--search query    - Run query in DEEP SEARCH mode

ESCALATION:
FAST --timeout--> DEEP --timeout--> DEEP SEARCH
"""
            }

        elif cmd == "/plan":
            result = self.plan_mode.enter()
            self.stats["plan_mode_sessions"] += 1
            return {"response": result.get("message", "") + "\n" + result.get("instructions", "")}

        elif cmd == "/plan exit":
            result = self.plan_mode.exit()
            return {"response": result.get("plan_summary", result.get("message", ""))}

        elif cmd == "/plan approve":
            result = self.plan_mode.approve()
            return {"response": result.get("message", "")}

        elif cmd == "/plan status":
            result = self.plan_mode.get_status()
            return {"response": json.dumps(result, indent=2)}

        elif cmd == "/tasks":
            result = self.task_tracker.list_all()
            if result["tasks"]:
                lines = ["Tasks:"]
                for t in result["tasks"]:
                    status_icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
                    lines.append(f"{status_icon.get(t['status'], '[ ]')} #{t['id']} {t['subject']}")
                return {"response": "\n".join(lines)}
            return {"response": "No tasks"}

        elif cmd == "/stats":
            return {"response": json.dumps(self.stats, indent=2)}

        elif cmd == "/clear":
            self.conversation_history.clear()
            return {"response": "Conversation cleared"}

        elif cmd == "/model":
            return {"response": f"Model: {self.config.model}\nURL: {self.config.ollama_url}"}

        elif cmd == "/deep on":
            result = self.switch_mode(ExecutionMode.DEEP, reason="manual")
            return {"response": f"{result['message']}\nDeep mode (Chain-of-Thought) enabled"}

        elif cmd == "/deep off":
            result = self.switch_mode(ExecutionMode.FAST, reason="manual")
            return {"response": f"{result['message']}\nDeep mode disabled"}

        # New mode commands
        elif cmd == "/mode":
            status = self.get_mode_status()
            icon = status["icon"]
            return {"response": f"""Current Mode: {icon} {status['current_mode'].upper()}
Auto-escalation: {'ON' if status['auto_escalation'] else 'OFF'}
Escalations: {status['escalations_count']}
Web searches: {status['web_searches_count']}

Use /mode fast|deep|search to switch"""}

        elif cmd == "/mode fast":
            result = self.switch_mode(ExecutionMode.FAST, reason="manual")
            return {"response": result["message"]}

        elif cmd == "/mode deep":
            result = self.switch_mode(ExecutionMode.DEEP, reason="manual")
            return {"response": result["message"]}

        elif cmd == "/mode search" or cmd == "/mode deepsearch":
            result = self.switch_mode(ExecutionMode.DEEP_SEARCH, reason="manual")
            return {"response": result["message"]}

        elif cmd == "/escalation on":
            self.config.auto_escalation = True
            return {"response": "[CONFIG] Auto-escalation ENABLED\nFAST -> DEEP -> DEEP_SEARCH on timeout"}

        elif cmd == "/escalation off":
            self.config.auto_escalation = False
            return {"response": "[CONFIG] Auto-escalation DISABLED"}

        elif cmd.startswith("/search "):
            # Direct web search
            query = cmd[8:].strip()
            result = self.web_search(query)
            if result["success"]:
                lines = [f"Web search: {query}", "=" * 40]
                for r in result["results"]:
                    lines.append(f"\n{r.get('title', r.get('type', ''))}:")
                    lines.append(f"  {r.get('text', '')}")
                    if r.get('url'):
                        lines.append(f"  URL: {r['url']}")
                return {"response": "\n".join(lines)}
            else:
                return {"response": f"Search error: {result.get('error', 'unknown')}"}

        return None

    # Pattern to detect "add/fix/update X in/to file.ext"
    _PRE_READ_PATTERN = re.compile(
        r'(?:add|insert|append|fix|update|modify|refactor|implement|remove|delete|change)\s+'
        r'.+?\s+(?:in|to|from|of)\s+["\']?([^\s"\']+\.\w{1,10})["\']?',
        re.IGNORECASE
    )

    @staticmethod
    def _strip_line_numbers(content: str) -> str:
        """
        Strip line number prefixes from read tool output.
        The read tool returns lines like "     1: code here" — we strip
        the "     N: " prefix so the LLM sees raw file content and can
        use exact strings in old_string for edits.
        """
        lines = content.split('\n')
        stripped = []
        for line in lines:
            # Match format: optional spaces + digits + colon + space
            m = re.match(r'^\s*\d+:\s?', line)
            if m:
                stripped.append(line[m.end():])
            else:
                stripped.append(line)
        return '\n'.join(stripped)

    def _try_pre_read(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        NO-LLM pre-read: detect file modification requests and auto-read the file.
        This gives the LLM file context on the first call, saving one round-trip.
        Returns dict with file content (line numbers stripped) and tool_call info, or None.
        """
        match = self._PRE_READ_PATTERN.search(user_input)
        if not match:
            return None

        file_path = match.group(1)

        # Validate it looks like a real file path (has extension)
        if '.' not in file_path or file_path.startswith('http'):
            return None

        # Execute read (NO-LLM)
        try:
            read_result = execute_tool('read', file_path=file_path)
            if read_result.get("success"):
                self.stats["tool_calls"] += 1
                # Strip line numbers so LLM sees raw content for exact old_string matching
                raw_content = self._strip_line_numbers(read_result.get("content", ""))
                return {
                    "file_path": file_path,
                    "content": raw_content,
                    "tool_call": {
                        "tool": "read",
                        "params": {"file_path": file_path},
                        "result": read_result
                    }
                }
        except Exception:
            pass

        return None

    def _is_complex_task(self, user_input: str) -> bool:
        """Detect if task needs CoT reasoning"""
        complex_indicators = [
            "refactor", "optimize", "design", "architect",
            "debug", "analyze", "explain why", "create test",
            "implement", "build", "migrate", "upgrade",
            "security", "performance", "scale"
        ]
        input_lower = user_input.lower()
        return any(ind in input_lower for ind in complex_indicators)

    # ==================== MODE SWITCHING SYSTEM ====================

    def switch_mode(self, new_mode: str, reason: str = "manual") -> Dict[str, Any]:
        """
        Переключение режима работы

        Args:
            new_mode: ExecutionMode.FAST, DEEP, или DEEP_SEARCH
            reason: "manual", "escalation", "auto"

        Returns:
            Результат переключения
        """
        old_mode = self.current_mode

        if new_mode not in [ExecutionMode.FAST, ExecutionMode.DEEP, ExecutionMode.DEEP_SEARCH]:
            return {
                "success": False,
                "error": f"Unknown mode: {new_mode}. Use: fast, deep, deep_search"
            }

        self.current_mode = new_mode
        self.config.execution_mode = new_mode

        # Обновляем deep_mode для совместимости
        self.config.deep_mode = (new_mode == ExecutionMode.DEEP)

        # Запись в историю
        self.mode_history.append({
            "from": old_mode,
            "to": new_mode,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })

        if reason == "escalation":
            self.stats["mode_escalations"] += 1

        icon_old = ExecutionMode.get_icon(old_mode)
        icon_new = ExecutionMode.get_icon(new_mode)

        return {
            "success": True,
            "message": f"[MODE] {icon_old} {old_mode.upper()} -> {icon_new} {new_mode.upper()}",
            "reason": reason,
            "old_mode": old_mode,
            "new_mode": new_mode
        }

    def escalate_mode(self) -> Dict[str, Any]:
        """
        Автоматическая эскалация режима при timeout
        FAST -> DEEP -> DEEP_SEARCH
        """
        next_mode = ExecutionMode.ESCALATION_CHAIN.get(self.current_mode)

        if next_mode is None:
            return {
                "success": False,
                "message": "[ESCALATION] Already at maximum mode (DEEP_SEARCH)",
                "mode": self.current_mode
            }

        result = self.switch_mode(next_mode, reason="escalation")

        if result["success"]:
            result["message"] = f"[ESCALATION] {result['message']} (timeout triggered)"

        return result

    def detect_mode_from_input(self, user_input: str) -> str:
        """
        Определить режим из пользовательского ввода

        Поддерживаемые форматы:
        - [DEEP] или --deep -> DEEP MODE
        - [SEARCH] или [DEEP SEARCH] или --search -> DEEP_SEARCH MODE
        """
        input_upper = user_input.upper()

        # DEEP SEARCH indicators
        if any(ind in input_upper for ind in ["[DEEP SEARCH]", "[SEARCH]", "--SEARCH"]):
            return ExecutionMode.DEEP_SEARCH

        # DEEP MODE indicators
        if any(ind in input_upper for ind in ["[DEEP]", "--DEEP"]):
            return ExecutionMode.DEEP

        # Default: current mode
        return self.current_mode

    def strip_mode_prefix(self, user_input: str) -> str:
        """Удалить префиксы режимов из запроса"""
        import re
        # Remove mode prefixes
        patterns = [
            r'\[DEEP\s*SEARCH\]\s*',
            r'\[SEARCH\]\s*',
            r'\[DEEP\]\s*',
            r'--deep\s+',
            r'--search\s+'
        ]
        result = user_input
        for pattern in patterns:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        return result.strip()

    def _load_swecas_search_cache(self) -> Dict[str, Any]:
        """Load SWECAS search cache from JSON file"""
        if hasattr(self, '_swecas_cache') and self._swecas_cache:
            return self._swecas_cache
        try:
            cache_path = os.path.join(os.path.dirname(__file__), 'swecas_search_cache.json')
            with open(cache_path, 'r', encoding='utf-8') as f:
                self._swecas_cache = json.load(f)
            return self._swecas_cache
        except Exception:
            self._swecas_cache = {}
            return self._swecas_cache

    def _get_swecas_cache_fallback(self, swecas_code: int) -> Dict[str, Any]:
        """Get cached search results for a SWECAS category"""
        cache = self._load_swecas_search_cache()
        cat_key = str(swecas_code)
        if cat_key in cache:
            cat_data = cache[cat_key]
            results = []
            for i, hint in enumerate(cat_data.get("fix_hints", [])):
                results.append({
                    "type": "swecas_cache",
                    "title": f"SWECAS-{swecas_code} fix pattern #{i+1}",
                    "text": hint,
                    "url": ""
                })
            for pattern in cat_data.get("patterns", []):
                results.append({
                    "type": "swecas_cache",
                    "title": f"Code pattern",
                    "text": pattern,
                    "url": ""
                })
            return {
                "success": True,
                "query": cat_data.get("query", ""),
                "results": results,
                "count": len(results),
                "source": "swecas_cache"
            }
        return {"success": False, "error": "No cache for this category"}

    def web_search(self, query: str) -> Dict[str, Any]:
        """
        Поиск в интернете для DEEP SEARCH режима
        Использует DuckDuckGo HTML parsing (полноценный веб-поиск)
        Falls back to SWECAS cache when search times out.
        """
        self.stats["web_searches"] += 1

        try:
            # Используем ExtendedTools.web_search - работает через HTML парсинг
            result = ExtendedTools.web_search(query, num_results=5)

            if result.get("success"):
                # Преобразуем формат результатов для совместимости
                results = []
                for r in result.get("results", []):
                    results.append({
                        "type": "search_result",
                        "title": r.get("title", ""),
                        "text": r.get("snippet", ""),
                        "url": r.get("url", "")
                    })

                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "count": len(results)
                }
            else:
                # Fallback to SWECAS cache if search failed and we have a classification
                return self._try_swecas_cache_fallback(result)

        except Exception as e:
            # Timeout or network error — try SWECAS cache
            return self._try_swecas_cache_fallback({"error": str(e)})

    def _try_swecas_cache_fallback(self, failed_result: Dict[str, Any]) -> Dict[str, Any]:
        """Attempt SWECAS cache fallback when web search fails"""
        swecas = getattr(self, '_current_swecas', None)
        if swecas and swecas.get("confidence", 0) >= 0.5:
            cache_result = self._get_swecas_cache_fallback(swecas["swecas_code"])
            if cache_result.get("success"):
                return cache_result
        return {
            "success": False,
            "error": failed_result.get("error", "Search failed, no cache available")
        }

    def process_with_mode(self, user_input: str) -> Dict[str, Any]:
        """
        Обработка с автоматическим определением режима
        Главная точка входа с поддержкой всех режимов
        """
        import time

        # Определить режим из ввода
        requested_mode = self.detect_mode_from_input(user_input)

        # Переключить режим если нужно
        if requested_mode != self.current_mode:
            self.switch_mode(requested_mode, reason="auto")
            print(f"[DEBUG process_with_mode] Switched to: {self.current_mode}")

        # Убрать префиксы режимов
        clean_input = self.strip_mode_prefix(user_input)
        print(f"[DEBUG process_with_mode] Clean input: {clean_input[:50]}...")

        # ALWAYS check special commands first (before mode-specific handling)
        special = self._handle_special_commands(clean_input)
        if special:
            print(f"[DEBUG process_with_mode] Special command handled: {clean_input[:30]}")
            return {
                "success": True,
                "response": special["response"],
                "mode": self.current_mode,
                "mode_icon": ExecutionMode.get_icon(self.current_mode),
                "tool_calls": [],
                "thinking": [],
                "route_method": "special_command",
                "iterations": 0,
                "plan_mode": self.plan_mode.is_active
            }

        # DEEP SEARCH: выполнить веб-поиск и напрямую LLM (без pattern routing)
        print(f"[DEBUG process_with_mode] Checking DEEP_SEARCH: current={self.current_mode}, expected={ExecutionMode.DEEP_SEARCH}")
        if self.current_mode == ExecutionMode.DEEP_SEARCH:
            search_result = self.web_search(clean_input)

            # Форматировать результаты поиска
            if search_result["success"] and search_result["results"]:
                context = "Web search results:\n"
                for r in search_result["results"][:5]:
                    text = r.get('text', '')[:200]
                    context += f"- {r.get('title', '')}: {text}\n"
                    if r.get("url"):
                        context += f"  URL: {r['url']}\n"

                # LLM анализ результатов (lightweight, no tools/history)
                analysis_prompt = f"""Query: "{clean_input}"

{context}

Summarize key findings in 3-5 bullet points. Include URLs."""

                llm_response = self._call_llm_search(analysis_prompt)

                return {
                    "success": True,
                    "response": llm_response or "No analysis available",
                    "mode": self.current_mode,
                    "mode_icon": ExecutionMode.get_icon(self.current_mode),
                    "tool_calls": [],
                    "thinking": [],
                    "route_method": "deep_search",
                    "iterations": 1,
                    "plan_mode": self.plan_mode.is_active,
                    "web_search": search_result
                }
            else:
                return {
                    "success": False,
                    "response": f"Web search failed: {search_result.get('error', 'No results')}",
                    "mode": self.current_mode,
                    "mode_icon": ExecutionMode.get_icon(self.current_mode),
                    "tool_calls": [],
                    "thinking": [],
                    "route_method": "deep_search",
                    "iterations": 0,
                    "plan_mode": self.plan_mode.is_active
                }

        # Запустить обработку с timeout
        start_time = time.time()

        try:
            result = self.process(clean_input)

            # Добавить информацию о режиме
            result["mode"] = self.current_mode
            result["mode_icon"] = ExecutionMode.get_icon(self.current_mode)

            return result

        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time

            # Автоматическая эскалация при timeout
            if self.config.auto_escalation:
                escalation = self.escalate_mode()

                if escalation["success"]:
                    # Повторить с новым режимом
                    return self.process_with_mode(user_input)
                else:
                    return {
                        "success": False,
                        "error": f"Timeout after {elapsed:.1f}s. Max escalation reached.",
                        "mode": self.current_mode
                    }
            else:
                return {
                    "success": False,
                    "error": f"Timeout after {elapsed:.1f}s",
                    "mode": self.current_mode
                }

    def get_mode_status(self) -> Dict[str, Any]:
        """Получить текущий статус режима"""
        return {
            "current_mode": self.current_mode,
            "icon": ExecutionMode.get_icon(self.current_mode),
            "deep_mode": self.config.deep_mode,
            "auto_escalation": self.config.auto_escalation,
            "mode_history": self.mode_history[-5:],  # Last 5 switches
            "escalations_count": self.stats["mode_escalations"],
            "web_searches_count": self.stats["web_searches"]
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics"""
        return {
            **self.stats,
            "model": self.config.model,
            "deep_mode": self.config.deep_mode,
            "plan_mode_active": self.plan_mode.is_active,
            "conversation_length": len(self.conversation_history)
        }
