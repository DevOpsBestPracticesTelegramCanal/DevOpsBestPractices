# QwenAgent

**Autonomous Code Agent - Like Claude Code, but local**

## Features

- **NO-LLM Routing (85%+)** - Pattern matching for fast execution
- **Chain-of-Thought (CoT)** - Deep reasoning for complex tasks
- **Self-Correction** - Automatic error detection and recovery
- **All Claude Code Tools** - bash, read, write, edit, glob, grep, ls, git
- **DevOps Test Suite** - Validate code generation capability
- **Portable** - Run on any local machine

## Quick Start

```batch
# Install
install.bat

# Start server
start.bat

# Open browser
http://localhost:5002
```

## Architecture

```
QwenAgent/
├── core/
│   ├── agent.py       # Main autonomous agent
│   ├── tools.py       # Claude Code tools
│   ├── router.py      # NO-LLM + LLM hybrid routing
│   └── cot_engine.py  # Chain-of-Thought engine
├── tests/
│   └── devops_tests.py # DevOps test suite
├── templates/
│   └── terminal.html   # Terminal UI
├── server.py           # Flask server
├── start.bat           # Launch server
├── install.bat         # Install dependencies
└── run_tests.bat       # Run DevOps tests
```

## Tools

| Tool | Description | Example |
|------|-------------|---------|
| `bash` | Execute shell command | `run git status` |
| `read` | Read file content | `read package.json` |
| `write` | Write/create file | `write hello to test.txt` |
| `edit` | Edit file | `replace old with new in file.py` |
| `glob` | Find files | `find all .py files` |
| `grep` | Search in files | `search for TODO` |
| `ls` | List directory | `list files` |
| `git` | Git operations | `git status` |

## Commands

| Command | Action |
|---------|--------|
| `/help` | Show help |
| `/clear` | Clear screen |
| `/stats` | Show routing stats |
| `/test` | Run quick tests |
| `Ctrl+L` | Clear screen |
| `Ctrl+D` | Toggle Deep mode |

## Deep Mode (CoT)

Enable with `[deep]` prefix or Ctrl+D:

```
[deep] create kubernetes deployment for my app
```

This triggers 5-step reasoning:
1. Understanding
2. Planning
3. Execution
4. Verification
5. Reflection

## DevOps Tests

Run DevOps code generation tests:

```batch
# Quick tests (file, git)
run_tests.bat

# Full test suite
run_tests.bat --full

# Specific category
run_tests.bat --category docker
```

Categories: file, git, docker, kubernetes, cicd, bash, terraform, ansible, complex

## Requirements

- Python 3.8+
- Flask, Flask-CORS, Requests
- Ollama with qwen2.5-coder:3b

## Portable Package

To create portable archive:

```batch
python create_package.py
```

This creates `QwenAgent_Portable.zip` with all files.

## Credits

- Architecture: DUCS v3 (NO-LLM routing)
- CoT: Chain-of-Thought reasoning
- Self-Correction: SWE-Guardian patterns
- Created: 2026-01-25
