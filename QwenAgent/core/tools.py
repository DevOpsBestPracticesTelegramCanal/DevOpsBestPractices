# -*- coding: utf-8 -*-
"""
QwenAgent Tools - All Claude Code Functions
"""

import subprocess
import os
import glob as glob_module
import re
import json
from typing import Dict, Any, Optional, List

WORKSPACE = os.path.expanduser("~")

class Tools:
    """All Claude Code tools implementation"""

    @staticmethod
    def bash(command: str, timeout: int = 120, cwd: str = None) -> Dict[str, Any]:
        """Execute shell command"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd or WORKSPACE
            )
            return {
                "output": (result.stdout + result.stderr)[:10000],
                "exit_code": result.returncode,
                "success": result.returncode == 0
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Timeout after {timeout}s", "exit_code": -1}
        except Exception as e:
            return {"error": str(e), "exit_code": -1}

    @staticmethod
    def read(file_path: str, limit: int = 500, offset: int = 0) -> Dict[str, Any]:
        """Read file content with line numbers"""
        try:
            path = os.path.join(WORKSPACE, file_path) if not os.path.isabs(file_path) else file_path
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            total = len(lines)
            selected = lines[offset:offset + limit]
            content = ''.join(f"{i+offset+1}: {line}" for i, line in enumerate(selected))

            return {
                "content": content,
                "total_lines": total,
                "shown_lines": len(selected),
                "path": path
            }
        except FileNotFoundError:
            return {"error": f"File not found: {file_path}"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def write(file_path: str, content: str) -> Dict[str, Any]:
        """Write content to file"""
        try:
            path = os.path.join(WORKSPACE, file_path) if not os.path.isabs(file_path) else file_path
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return {"success": True, "path": path, "bytes": len(content)}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def edit(file_path: str, old_string: str, new_string: str) -> Dict[str, Any]:
        """Edit file - find and replace string"""
        try:
            path = os.path.join(WORKSPACE, file_path) if not os.path.isabs(file_path) else file_path
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            if old_string not in content:
                return {"error": "String not found in file", "success": False}

            count = content.count(old_string)
            new_content = content.replace(old_string, new_string, 1)

            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            return {"success": True, "replacements": 1, "total_matches": count}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def glob(pattern: str, path: str = None) -> Dict[str, Any]:
        """Find files by glob pattern"""
        try:
            base = path or WORKSPACE
            if not os.path.isabs(base):
                base = os.path.join(WORKSPACE, base)

            full_pattern = os.path.join(base, pattern)
            files = glob_module.glob(full_pattern, recursive=True)
            files = sorted(files)[:200]

            return {"files": files, "count": len(files), "pattern": pattern}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def grep(pattern: str, path: str = None, file_type: str = None, max_results: int = 100) -> Dict[str, Any]:
        """Search for pattern in files"""
        try:
            base = path or WORKSPACE
            if not os.path.isabs(base):
                base = os.path.join(WORKSPACE, base)

            results = []
            search_glob = f"**/*.{file_type}" if file_type else "**/*"

            for file_path in glob_module.glob(os.path.join(base, search_glob), recursive=True):
                if os.path.isfile(file_path) and os.path.getsize(file_path) < 1_000_000:
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                if re.search(pattern, line, re.IGNORECASE):
                                    results.append({
                                        "file": file_path,
                                        "line": i,
                                        "content": line.strip()[:200]
                                    })
                                    if len(results) >= max_results:
                                        return {"results": results, "truncated": True}
                    except:
                        pass

            return {"results": results, "count": len(results)}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def ls(path: str = None) -> Dict[str, Any]:
        """List directory contents"""
        try:
            target = path or WORKSPACE
            if not os.path.isabs(target):
                target = os.path.join(WORKSPACE, target)

            items = []
            for name in sorted(os.listdir(target))[:100]:
                full = os.path.join(target, name)
                is_dir = os.path.isdir(full)
                size = os.path.getsize(full) if not is_dir else 0
                items.append({
                    "name": name,
                    "type": "dir" if is_dir else "file",
                    "size": size
                })

            return {"items": items, "path": target, "count": len(items)}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def git(command: str, cwd: str = None) -> Dict[str, Any]:
        """Execute git command"""
        return Tools.bash(f"git {command}", cwd=cwd)

    # Ollama config for local fallback
    _ollama_url = "http://localhost:11434"
    _ollama_model = "qwen2.5-coder:3b"

    @staticmethod
    def claude(prompt: str, timeout: int = 300, working_dir: str = None, **kwargs) -> Dict[str, Any]:
        """
        Delegate task to Claude Code CLI.
        Falls back to local Ollama if CLI unavailable or API has no credits.
        """
        import requests as req

        cli_error = None

        # --- Try Claude Code CLI ---
        try:
            check = subprocess.run(
                "claude --version", shell=True,
                capture_output=True, text=True, timeout=10
            )
            if check.returncode == 0:
                result = subprocess.run(
                    "claude -p" if os.name == 'nt' else ["claude", "-p"],
                    input=prompt, shell=(os.name == 'nt'),
                    capture_output=True, text=True,
                    timeout=timeout, cwd=working_dir or WORKSPACE
                )
                output = (result.stdout or "").strip()
                stderr = (result.stderr or "").strip()

                error_indicators = ["credit balance", "unauthorized", "authentication", "api key"]
                combined = (output + " " + stderr).lower()
                if not any(err in combined for err in error_indicators):
                    return {
                        "output": output[:30000],
                        "exit_code": result.returncode,
                        "success": result.returncode == 0,
                        "provider": "claude_cli"
                    }
                cli_error = output or stderr
            else:
                cli_error = "CLI not installed"
        except subprocess.TimeoutExpired:
            cli_error = f"Timeout {timeout}s"
        except (FileNotFoundError, OSError):
            cli_error = "CLI not found"
        except Exception as e:
            cli_error = str(e)

        # --- Fallback to local Ollama ---
        try:
            r = req.post(
                f"{Tools._ollama_url}/api/generate",
                json={
                    "model": Tools._ollama_model,
                    "prompt": f"You are an expert coding assistant.\n\nUser: {prompt}\n\nAssistant:",
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 2048}
                },
                timeout=min(timeout, 180)
            )
            if r.status_code == 200:
                return {
                    "output": r.json().get("response", ""),
                    "exit_code": 0,
                    "success": True,
                    "provider": "ollama_fallback",
                    "cli_note": f"Local Ollama (reason: {cli_error})"
                }
        except Exception as e:
            pass

        return {"error": f"Claude CLI: {cli_error}. Ollama also unavailable.", "exit_code": -1}

# Tool registry
TOOL_REGISTRY = {
    "bash": Tools.bash,
    "read": Tools.read,
    "write": Tools.write,
    "edit": Tools.edit,
    "glob": Tools.glob,
    "grep": Tools.grep,
    "ls": Tools.ls,
    "git": Tools.git,
    "claude": Tools.claude,
}

def execute_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    """Execute a tool by name"""
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return TOOL_REGISTRY[tool_name](**kwargs)
    except Exception as e:
        return {"error": str(e)}
