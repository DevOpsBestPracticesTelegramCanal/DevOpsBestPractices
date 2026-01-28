# -*- coding: utf-8 -*-
"""
QwenAgent - Autonomous Code Agent
Like Claude Code but with local Qwen LLM
"""

import json
import re
import requests
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from .tools import TOOL_REGISTRY, execute_tool
from .router import HybridRouter, RouteResult
from .cot_engine import CoTEngine, TaskDecomposer, SelfCorrection

@dataclass
class AgentConfig:
    """Agent configuration"""
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:3b"
    max_iterations: int = 10
    deep_mode: bool = False
    auto_execute: bool = True
    timeout: int = 120

class QwenAgent:
    """
    Autonomous Code Agent
    Combines:
    - Hybrid Router (NO-LLM + LLM)
    - Chain-of-Thought reasoning
    - Task decomposition
    - Self-correction
    - All Claude Code tools
    """

    SYSTEM_PROMPT = """You are an autonomous code agent with access to tools.
Your goal is to help users with coding tasks by using the available tools.

Available tools:
- bash(command): Execute shell command
- read(file_path): Read file content
- write(file_path, content): Write/create file
- edit(file_path, old_string, new_string): Edit file
- glob(pattern): Find files (e.g., **/*.py)
- grep(pattern, path): Search in files
- ls(path): List directory
- git(command): Git operations
- claude(prompt): Delegate complex task to Claude Code AI

To use a tool, respond with:
[TOOL: tool_name(param1="value1", param2="value2")]

Examples:
[TOOL: read(file_path="package.json")]
[TOOL: bash(command="git status")]
[TOOL: glob(pattern="**/*.py")]
[TOOL: edit(file_path="app.py", old_string="old", new_string="new")]
[TOOL: claude(prompt="explain this code and suggest improvements")]

After seeing tool results, provide a helpful explanation.
If a task requires multiple steps, execute them one by one.
If an error occurs, try to fix it or suggest alternatives."""

    def __init__(self, config: AgentConfig = None):
        self.config = config or AgentConfig()
        self.router = HybridRouter()
        self.cot = CoTEngine()
        self.decomposer = TaskDecomposer()
        self.corrector = SelfCorrection()

        self.conversation: List[Dict[str, str]] = []
        self.tool_history: List[Dict[str, Any]] = []

    def call_llm(self, prompt: str, system: str = None) -> str:
        """Call Ollama LLM"""
        try:
            response = requests.post(
                f"{self.config.ollama_url}/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": prompt,
                    "system": system or self.SYSTEM_PROMPT,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 2000
                    }
                },
                timeout=self.config.timeout
            )
            if response.status_code == 200:
                return response.json().get('response', '')
            return f"Error: {response.status_code}"
        except Exception as e:
            return f"Error: {e}"

    def parse_tool_call(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Parse tool call from LLM response"""
        # Pattern: [TOOL: tool_name(params)]
        match = re.search(r'\[TOOL:\s*(\w+)\((.*?)\)\]', text, re.DOTALL)
        if not match:
            return None

        tool_name = match.group(1)
        params_str = match.group(2).strip()

        # Parse parameters
        params = {}
        if params_str:
            # Try key=value format
            for part in re.findall(r'(\w+)\s*=\s*["\']([^"\']*)["\']', params_str):
                params[part[0]] = part[1]

            # If no params found, try positional
            if not params and params_str:
                # Single argument
                arg = params_str.strip('"\'')
                if tool_name == 'bash':
                    params = {'command': arg}
                elif tool_name in ['read', 'ls', 'glob']:
                    params = {'file_path': arg} if tool_name == 'read' else {'path': arg} if tool_name == 'ls' else {'pattern': arg}
                elif tool_name == 'grep':
                    params = {'pattern': arg}
                elif tool_name == 'git':
                    params = {'command': arg}

        return tool_name, params

    def process(self, user_input: str) -> Dict[str, Any]:
        """
        Process user input through the agent pipeline

        Returns:
            Dict with response, tool_calls, thinking, etc.
        """
        result = {
            'response': '',
            'tool_calls': [],
            'thinking': [],
            'route_method': '',
            'iterations': 0
        }

        # Enable deep mode if requested
        if '[deep]' in user_input.lower() or self.config.deep_mode:
            self.cot.enable_deep_mode(True)
            user_input = user_input.replace('[deep]', '').replace('[DEEP]', '').strip()

        # STEP 1: Try hybrid router (NO-LLM first)
        route = self.router.route(user_input)
        result['route_method'] = route.method

        if route.confidence >= 0.85 and route.tool:
            # Direct tool execution (NO-LLM path)
            tool_result = execute_tool(route.tool, **route.params)
            result['tool_calls'].append({
                'tool': route.tool,
                'params': route.params,
                'result': tool_result
            })

            # Format response
            if 'error' in tool_result:
                result['response'] = f"Error: {tool_result['error']}"
            else:
                result['response'] = self._format_tool_result(route.tool, tool_result)

            return result

        # STEP 2: LLM path with potential tool use
        prompt = user_input
        if self.cot.deep_mode:
            prompt = self.cot.create_thinking_prompt(user_input)
            result['thinking'].append("Deep mode enabled")

        iterations = 0
        while iterations < self.config.max_iterations:
            iterations += 1
            result['iterations'] = iterations

            # Call LLM
            llm_response = self.call_llm(prompt)

            # Check for tool call
            tool_call = self.parse_tool_call(llm_response)

            if tool_call:
                tool_name, params = tool_call
                tool_result = execute_tool(tool_name, **params)

                result['tool_calls'].append({
                    'tool': tool_name,
                    'params': params,
                    'result': tool_result
                })

                # Check for errors and self-correct
                error_analysis = self.corrector.analyze_result(tool_result)
                if error_analysis['has_error']:
                    suggestion = self.corrector.suggest_fix(error_analysis, user_input)
                    result['thinking'].append(f"Error detected: {error_analysis['error_type']}")
                    if suggestion:
                        result['thinking'].append(f"Suggestion: {suggestion}")

                # Continue conversation with tool result
                prompt = f"""Previous request: {user_input}

Tool {tool_name} was executed with result:
{json.dumps(tool_result, indent=2)}

Provide a helpful response to the user. If more actions are needed, use another tool.
If the task is complete, summarize what was done."""

            else:
                # No tool call - this is the final response
                result['response'] = llm_response
                break

        return result

    def _format_tool_result(self, tool: str, result: Dict[str, Any]) -> str:
        """Format tool result for display"""
        if tool == 'read' and 'content' in result:
            return result['content']
        elif tool == 'ls' and 'items' in result:
            lines = []
            for item in result['items']:
                prefix = "[D]" if item['type'] == 'dir' else "[F]"
                lines.append(f"{prefix} {item['name']}")
            return '\n'.join(lines)
        elif tool == 'glob' and 'files' in result:
            return '\n'.join(result['files'][:50])
        elif tool == 'grep' and 'results' in result:
            return '\n'.join(r['content'] for r in result['results'][:20])
        elif tool == 'bash' and 'output' in result:
            return result['output']
        elif tool == 'git' and 'output' in result:
            return result['output']
        elif tool == 'claude' and 'output' in result:
            return result['output']
        elif 'success' in result:
            return "Done" if result['success'] else "Failed"
        else:
            return json.dumps(result, indent=2)

    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics"""
        return {
            'router_stats': self.router.get_stats(),
            'tool_calls': len(self.tool_history),
            'model': self.config.model
        }
