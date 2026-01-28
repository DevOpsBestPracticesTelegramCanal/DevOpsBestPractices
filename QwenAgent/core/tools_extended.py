"""
QwenCode Extended Tools - Full Claude Code Feature Parity
All tools that Claude Code has, now in QwenCode
"""

import os
import re
import json
import subprocess
import glob as glob_module
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import html2text


class ExtendedTools:
    """All Claude Code tools implemented for QwenCode"""

    # ============================================================
    # CORE TOOLS (Already implemented, enhanced versions)
    # ============================================================

    @staticmethod
    def bash(command: str, timeout: int = 120, working_dir: str = None, **kwargs) -> Dict[str, Any]:
        """
        Execute bash/shell command.
        Ignores unexpected kwargs from LLM (like 'pivot', 'arr', etc.)
        """
        # Ignore any extra kwargs - LLM sometimes sends wrong arguments
        if kwargs:
            print(f"[BASH] Ignoring unexpected args: {list(kwargs.keys())}")

        try:
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            # Windows: use chcp 65001 for UTF-8 support
            if os.name == 'nt':
                # Prepend chcp 65001 to fix encoding
                full_command = f'chcp 65001 >nul && {command}'
                result = subprocess.run(
                    full_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=working_dir or os.getcwd(),
                    encoding='utf-8',
                    errors='replace',
                    env=env
                )
            else:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=working_dir or os.getcwd(),
                    encoding='utf-8',
                    errors='replace',
                    env=env
                )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:30000] if result.stdout else "",
                "stderr": result.stderr[:5000] if result.stderr else "",
                "return_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Command timed out after {timeout}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def read(file_path: str = None, path: str = None, offset: int = 0, limit: int = 2000, **kwargs) -> Dict[str, Any]:
        """Read file contents with line numbers"""
        # Normalize: accept both file_path and path
        if not file_path and path:
            file_path = path

        if not file_path:
            return {"success": False, "error": "file_path is required"}

        try:
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}

            if not path.is_file():
                return {"success": False, "error": f"Not a file: {file_path}"}

            # Handle binary files
            if path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.exe']:
                return {
                    "success": True,
                    "content": f"[Binary file: {path.suffix}, size: {path.stat().st_size} bytes]",
                    "lines": 1,
                    "is_binary": True
                }

            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            total_lines = len(lines)
            selected = lines[offset:offset + limit]

            # Format with line numbers (like cat -n)
            content_lines = []
            for i, line in enumerate(selected, start=offset + 1):
                # Truncate long lines
                if len(line) > 2000:
                    line = line[:2000] + "...[truncated]"
                content_lines.append(f"{i:6d}: {line.rstrip()}")

            return {
                "success": True,
                "content": "\n".join(content_lines),
                "total_lines": total_lines,
                "shown_lines": len(selected),
                "offset": offset,
                "file_path": str(path.absolute())
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def write(file_path: str, content: str, **kwargs) -> Dict[str, Any]:
        """Write content to file with safety validation. Returns old/new content for diff display."""
        # Ignore extra kwargs from LLM
        try:
            path = Path(file_path)

            # SAFE_WRITE: Syntax validation for Python files
            if path.suffix.lower() == '.py':
                try:
                    compile(content, str(path), 'exec')
                except SyntaxError as e:
                    return {
                        "success": False,
                        "error": f"Python syntax error — file NOT written: {e.msg} (line {e.lineno})",
                        "syntax_error": True,
                        "line": e.lineno,
                        "offset": e.offset
                    }

            # Read old content if file exists (for diff + backup + ratio check)
            old_content = ""
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        old_content = f.read()
                except:
                    pass

                # Auto-backup before overwriting
                backup_path = Path(str(path) + '.bak')
                try:
                    import shutil
                    shutil.copy2(path, backup_path)
                except Exception:
                    pass  # Non-critical if backup fails

                # Diff ratio warning (informational, does not block write)
                if old_content:
                    import difflib
                    ratio = difflib.SequenceMatcher(None, old_content, content).ratio()
                    change_ratio = 1.0 - ratio
                else:
                    change_ratio = 0.0
            else:
                change_ratio = 0.0

            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)

            result = {
                "success": True,
                "file_path": str(path.absolute()),
                "file": str(path),
                "bytes_written": len(content.encode('utf-8')),
                "lines": content.count('\n') + 1,
                "old_content": old_content,
                "new_content": content
            }

            if change_ratio > 0.5:
                result["warning"] = f"Large change detected: {change_ratio:.0%} of file changed. Backup saved to {path.name}.bak"

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def edit(file_path: str, old_string: str = None, new_string: str = None,
             old_str: str = None, new_str: str = None,
             replace_all: bool = False, **kwargs) -> Dict[str, Any]:
        """Edit file by replacing text with safety validation. Returns old/new content for diff display."""
        # Normalize parameter names (old_str -> old_string)
        if old_str and not old_string:
            old_string = old_str
        if new_str and not new_string:
            new_string = new_str

        if not old_string or new_string is None:
            return {"success": False, "error": "Both old_string and new_string are required"}

        try:
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}

            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            old_content = content  # Save for diff

            if old_string not in content:
                return {"success": False, "error": "old_string not found in file"}

            count = content.count(old_string)
            if count > 1 and not replace_all:
                return {
                    "success": False,
                    "error": f"old_string found {count} times. Use replace_all=True or provide more context"
                }

            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements = count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replacements = 1

            # SAFE_EDIT: Syntax validation for Python files before writing
            if path.suffix.lower() == '.py':
                try:
                    compile(new_content, str(path), 'exec')
                except SyntaxError as e:
                    return {
                        "success": False,
                        "error": f"Edit would create invalid Python syntax — file NOT modified: {e.msg} (line {e.lineno})",
                        "syntax_error": True,
                        "line": e.lineno,
                        "offset": e.offset
                    }

            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            # Build context window for diff display (3 lines before/after)
            ctx = 3
            old_lines = old_content.split('\n')
            new_lines = new_content.split('\n')

            # Find first replaced occurrence line
            pos = old_content.find(old_string)
            start_line = old_content[:pos].count('\n')
            old_end_line = start_line + old_string.count('\n')
            new_end_line = start_line + new_string.count('\n')

            ctx_start = max(0, start_line - ctx)
            old_ctx_end = min(len(old_lines), old_end_line + 1 + ctx)
            new_ctx_end = min(len(new_lines), new_end_line + 1 + ctx)

            return {
                "success": True,
                "file_path": str(path.absolute()),
                "file": str(path),
                "replacements": replacements,
                "old_content": '\n'.join(old_lines[ctx_start:old_ctx_end]),
                "new_content": '\n'.join(new_lines[ctx_start:new_ctx_end]),
                "context_start_line": ctx_start + 1
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def glob(pattern: str, path: str = None, **kwargs) -> Dict[str, Any]:
        """Find files matching glob pattern"""
        try:
            base_path = Path(path) if path else Path.cwd()
            matches = list(base_path.glob(pattern))

            # Sort by modification time (newest first)
            matches.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)

            results = []
            for m in matches[:100]:  # Limit to 100 results
                try:
                    stat = m.stat()
                    results.append({
                        "path": str(m),
                        "name": m.name,
                        "size": stat.st_size,
                        "is_dir": m.is_dir(),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
                except:
                    results.append({"path": str(m), "name": m.name})

            return {
                "success": True,
                "pattern": pattern,
                "count": len(results),
                "files": results
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def grep(pattern: str, path: str = ".", include: str = None,
             context_before: int = 0, context_after: int = 0, **kwargs) -> Dict[str, Any]:
        """Search for pattern in files"""
        try:
            base_path = Path(path)
            results = []

            # Determine files to search
            if base_path.is_file():
                files = [base_path]
            else:
                if include:
                    files = list(base_path.rglob(include))
                else:
                    files = list(base_path.rglob("*"))

            regex = re.compile(pattern, re.IGNORECASE)

            for file_path in files[:1000]:  # Limit files
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() in ['.png', '.jpg', '.exe', '.zip', '.pdf']:
                    continue

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()

                    for i, line in enumerate(lines):
                        if regex.search(line):
                            match_result = {
                                "file": str(file_path),
                                "line_number": i + 1,
                                "line": line.strip()[:500]
                            }

                            # Add context if requested
                            if context_before > 0:
                                start = max(0, i - context_before)
                                match_result["before"] = [l.strip() for l in lines[start:i]]
                            if context_after > 0:
                                end = min(len(lines), i + context_after + 1)
                                match_result["after"] = [l.strip() for l in lines[i+1:end]]

                            results.append(match_result)

                            if len(results) >= 100:  # Limit results
                                break
                except:
                    continue

                if len(results) >= 100:
                    break

            return {
                "success": True,
                "pattern": pattern,
                "count": len(results),
                "matches": results
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def ls(path: str = None, directory: str = None, show_hidden: bool = False, **kwargs) -> Dict[str, Any]:
        """List directory contents"""
        # Normalize: accept both path and directory
        if not path and directory:
            path = directory

        try:
            target = Path(path) if path else Path.cwd()
            if not target.exists():
                return {"success": False, "error": f"Path not found: {path}"}

            items = []
            for item in sorted(target.iterdir()):
                if not show_hidden and item.name.startswith('.'):
                    continue

                try:
                    stat = item.stat()
                    items.append({
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": stat.st_size if item.is_file() else 0,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
                except:
                    items.append({"name": item.name, "type": "unknown"})

            return {
                "success": True,
                "path": str(target.absolute()),
                "count": len(items),
                "items": items[:200]  # Limit
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============================================================
    # NEW TOOLS - Claude Code Feature Parity
    # ============================================================

    @staticmethod
    def web_fetch(url: str, prompt: str = None) -> Dict[str, Any]:
        """
        Fetch content from URL and optionally process with prompt
        Like Claude Code's WebFetch tool
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '')

            if 'text/html' in content_type:
                # Convert HTML to markdown
                soup = BeautifulSoup(response.text, 'html.parser')

                # Remove scripts, styles
                for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                    tag.decompose()

                # Convert to text
                h = html2text.HTML2Text()
                h.ignore_links = False
                h.ignore_images = True
                text = h.handle(str(soup))

                # Truncate
                if len(text) > 15000:
                    text = text[:15000] + "\n\n[Content truncated...]"

                return {
                    "success": True,
                    "url": url,
                    "content_type": "html",
                    "content": text,
                    "title": soup.title.string if soup.title else None
                }

            elif 'application/json' in content_type:
                return {
                    "success": True,
                    "url": url,
                    "content_type": "json",
                    "content": json.dumps(response.json(), indent=2)[:15000]
                }

            else:
                return {
                    "success": True,
                    "url": url,
                    "content_type": content_type,
                    "content": response.text[:15000]
                }

        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Request failed: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def web_search(query: str, num_results: int = 5) -> Dict[str, Any]:
        """
        Search the web using DuckDuckGo
        Like Claude Code's WebSearch tool
        """
        try:
            # Use DuckDuckGo HTML search (no API key needed)
            url = "https://html.duckduckgo.com/html/"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.post(url, data={'q': query}, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')

            results = []
            for result in soup.select('.result')[:num_results]:
                title_elem = result.select_one('.result__title')
                snippet_elem = result.select_one('.result__snippet')
                link_elem = result.select_one('.result__url')

                if title_elem:
                    results.append({
                        "title": title_elem.get_text(strip=True),
                        "snippet": snippet_elem.get_text(strip=True) if snippet_elem else "",
                        "url": link_elem.get_text(strip=True) if link_elem else ""
                    })

            return {
                "success": True,
                "query": query,
                "count": len(results),
                "results": results
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def notebook_read(notebook_path: str) -> Dict[str, Any]:
        """
        Read Jupyter notebook (.ipynb)
        Like Claude Code's notebook reading
        """
        try:
            with open(notebook_path, 'r', encoding='utf-8') as f:
                nb = json.load(f)

            cells = []
            for i, cell in enumerate(nb.get('cells', [])):
                cell_type = cell.get('cell_type', 'unknown')
                source = ''.join(cell.get('source', []))

                cell_info = {
                    "index": i,
                    "type": cell_type,
                    "source": source[:2000]
                }

                # Include outputs for code cells
                if cell_type == 'code':
                    outputs = cell.get('outputs', [])
                    output_text = []
                    for out in outputs:
                        if 'text' in out:
                            output_text.extend(out['text'])
                        elif 'data' in out and 'text/plain' in out['data']:
                            output_text.extend(out['data']['text/plain'])
                    cell_info['output'] = ''.join(output_text)[:1000]

                cells.append(cell_info)

            return {
                "success": True,
                "path": notebook_path,
                "cell_count": len(cells),
                "cells": cells
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def notebook_edit(notebook_path: str, cell_index: int, new_source: str,
                      cell_type: str = None, edit_mode: str = "replace") -> Dict[str, Any]:
        """
        Edit Jupyter notebook cell
        Like Claude Code's NotebookEdit tool

        edit_mode: "replace", "insert", "delete"
        """
        try:
            with open(notebook_path, 'r', encoding='utf-8') as f:
                nb = json.load(f)

            cells = nb.get('cells', [])

            if edit_mode == "delete":
                if 0 <= cell_index < len(cells):
                    del cells[cell_index]
                else:
                    return {"success": False, "error": f"Invalid cell index: {cell_index}"}

            elif edit_mode == "insert":
                new_cell = {
                    "cell_type": cell_type or "code",
                    "source": new_source.split('\n'),
                    "metadata": {},
                }
                if cell_type != "markdown":
                    new_cell["outputs"] = []
                    new_cell["execution_count"] = None

                cells.insert(cell_index, new_cell)

            else:  # replace
                if 0 <= cell_index < len(cells):
                    cells[cell_index]['source'] = new_source.split('\n')
                    if cell_type:
                        cells[cell_index]['cell_type'] = cell_type
                else:
                    return {"success": False, "error": f"Invalid cell index: {cell_index}"}

            nb['cells'] = cells

            with open(notebook_path, 'w', encoding='utf-8') as f:
                json.dump(nb, f, indent=2)

            return {
                "success": True,
                "path": notebook_path,
                "edit_mode": edit_mode,
                "cell_index": cell_index
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def git(command: str, working_dir: str = None) -> Dict[str, Any]:
        """Execute git command"""
        full_command = f"git {command}"
        return ExtendedTools.bash(full_command, working_dir=working_dir)

    @staticmethod
    def tree(path: str = ".", max_depth: int = 3, show_hidden: bool = False) -> Dict[str, Any]:
        """
        Show directory tree structure
        Like running 'tree' command
        """
        try:
            base = Path(path)
            lines = [str(base)]

            def add_tree(directory: Path, prefix: str = "", depth: int = 0):
                if depth >= max_depth:
                    return

                try:
                    items = sorted(directory.iterdir())
                    if not show_hidden:
                        items = [i for i in items if not i.name.startswith('.')]

                    for i, item in enumerate(items):
                        is_last = i == len(items) - 1
                        connector = "└── " if is_last else "├── "

                        if item.is_dir():
                            lines.append(f"{prefix}{connector}{item.name}/")
                            new_prefix = prefix + ("    " if is_last else "│   ")
                            add_tree(item, new_prefix, depth + 1)
                        else:
                            size = item.stat().st_size
                            lines.append(f"{prefix}{connector}{item.name} ({size:,} bytes)")
                except PermissionError:
                    lines.append(f"{prefix}[Permission Denied]")

            add_tree(base)

            return {
                "success": True,
                "path": str(base.absolute()),
                "tree": "\n".join(lines[:500])  # Limit output
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def diff(file1: str, file2: str) -> Dict[str, Any]:
        """Compare two files"""
        try:
            import difflib

            with open(file1, 'r', encoding='utf-8') as f:
                lines1 = f.readlines()
            with open(file2, 'r', encoding='utf-8') as f:
                lines2 = f.readlines()

            diff = difflib.unified_diff(
                lines1, lines2,
                fromfile=file1, tofile=file2,
                lineterm=''
            )

            diff_text = '\n'.join(diff)

            return {
                "success": True,
                "file1": file1,
                "file2": file2,
                "diff": diff_text[:10000]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}



# Tool registry with descriptions (for LLM context)
EXTENDED_TOOL_REGISTRY = {
    "bash": {
        "func": ExtendedTools.bash,
        "description": "Execute shell command",
        "params": ["command", "timeout?", "working_dir?"]
    },
    "read": {
        "func": ExtendedTools.read,
        "description": "Read file contents with line numbers",
        "params": ["file_path", "offset?", "limit?"]
    },
    "write": {
        "func": ExtendedTools.write,
        "description": "Write content to file",
        "params": ["file_path", "content"]
    },
    "edit": {
        "func": ExtendedTools.edit,
        "description": "Edit file by replacing text",
        "params": ["file_path", "old_string", "new_string", "replace_all?"]
    },
    "glob": {
        "func": ExtendedTools.glob,
        "description": "Find files matching pattern",
        "params": ["pattern", "path?"]
    },
    "grep": {
        "func": ExtendedTools.grep,
        "description": "Search for pattern in files",
        "params": ["pattern", "path?", "include?", "context_before?", "context_after?"]
    },
    "ls": {
        "func": ExtendedTools.ls,
        "description": "List directory contents",
        "params": ["path?", "show_hidden?"]
    },
    "git": {
        "func": ExtendedTools.git,
        "description": "Execute git command",
        "params": ["command", "working_dir?"]
    },
    "web_fetch": {
        "func": ExtendedTools.web_fetch,
        "description": "Fetch and parse web page content",
        "params": ["url", "prompt?"]
    },
    "web_search": {
        "func": ExtendedTools.web_search,
        "description": "Search the web using DuckDuckGo",
        "params": ["query", "num_results?"]
    },
    "notebook_read": {
        "func": ExtendedTools.notebook_read,
        "description": "Read Jupyter notebook cells",
        "params": ["notebook_path"]
    },
    "notebook_edit": {
        "func": ExtendedTools.notebook_edit,
        "description": "Edit Jupyter notebook cell",
        "params": ["notebook_path", "cell_index", "new_source", "cell_type?", "edit_mode?"]
    },
    "tree": {
        "func": ExtendedTools.tree,
        "description": "Show directory tree structure",
        "params": ["path?", "max_depth?", "show_hidden?"]
    },
    "diff": {
        "func": ExtendedTools.diff,
        "description": "Compare two files",
        "params": ["file1", "file2"]
    },
}


def execute_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    """Execute a tool by name"""
    if tool_name not in EXTENDED_TOOL_REGISTRY:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    try:
        func = EXTENDED_TOOL_REGISTRY[tool_name]["func"]
        return func(**kwargs)
    except Exception as e:
        return {"success": False, "error": f"Tool execution failed: {str(e)}"}


def get_tools_description() -> str:
    """Get description of all tools for LLM context"""
    lines = ["Available tools:"]
    for name, info in EXTENDED_TOOL_REGISTRY.items():
        params = ", ".join(info["params"])
        lines.append(f"  - {name}({params}): {info['description']}")
    return "\n".join(lines)
