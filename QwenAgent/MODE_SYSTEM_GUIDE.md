# QwenCode Mode System - Guide

**Version:** 1.0
**Updated:** 2026-01-26

---

## Overview

QwenCode implements a three-mode execution system with automatic escalation:

```
FAST MODE ──timeout──> DEEP MODE ──timeout──> DEEP SEARCH
   ⚡                     🧠                      🌐
(seconds)              (minutes)             (web search)
```

---

## Modes

### FAST MODE ⚡ (Default)

**When to use:**
- Simple queries
- File reading
- Running scripts
- Quick lookups

**Characteristics:**
- Speed: Fast (seconds)
- Pattern matching: 85%+
- No Chain-of-Thought

**Examples:**
```
show files in current directory
read config.py
run tests
```

---

### DEEP MODE 🧠

**When to use:**
- Complex refactoring
- Architecture design
- Critical bug fixes
- Security analysis

**Characteristics:**
- Speed: Moderate (minutes)
- Chain-of-Thought reasoning
- 6-step Minsky process
- Full tool access

**Activation:**
```
[DEEP] refactor this module
--deep analyze security vulnerabilities
/mode deep
```

**Examples:**
```
[DEEP] optimize database queries
[DEEP] design API architecture
--deep implement authentication system
```

---

### DEEP SEARCH MODE 🌐

**When to use:**
- Finding latest information
- Documentation lookup
- CVE research
- External resources

**Characteristics:**
- Web search integration
- DuckDuckGo API
- Source citations
- Real-time data

**Activation:**
```
[SEARCH] latest CVE for Docker
[DEEP SEARCH] Kubernetes 1.30 documentation
--search best practices terraform 2026
/mode search
```

**Examples:**
```
[SEARCH] Docker security updates 2026
[SEARCH] how to configure nginx ingress
--search latest python releases
```

---

## Commands

### Mode Switching

| Command | Description |
|---------|-------------|
| `/mode` | Show current mode status |
| `/mode fast` | Switch to FAST mode |
| `/mode deep` | Switch to DEEP mode |
| `/mode search` | Switch to DEEP SEARCH mode |
| `/deep on` | Enable DEEP mode (alias) |
| `/deep off` | Disable DEEP mode (alias) |

### Escalation Control

| Command | Description |
|---------|-------------|
| `/escalation on` | Enable auto-escalation on timeout |
| `/escalation off` | Disable auto-escalation |

### Web Search

| Command | Description |
|---------|-------------|
| `/search <query>` | Direct web search |

---

## Prefixes in Queries

| Prefix | Mode |
|--------|------|
| `[DEEP]` | DEEP MODE |
| `--deep` | DEEP MODE |
| `[SEARCH]` | DEEP SEARCH |
| `[DEEP SEARCH]` | DEEP SEARCH |
| `--search` | DEEP SEARCH |

---

## Auto-Escalation

When enabled (`/escalation on`), the system automatically escalates modes on timeout:

```
1. Request starts in FAST MODE
   └─ If timeout → [ESCALATION] Switch to DEEP MODE

2. DEEP MODE processes request
   └─ If timeout → [ESCALATION] Switch to DEEP SEARCH

3. DEEP SEARCH performs web search
   └─ If timeout → Report error to user
```

**Notifications:**
```
[ESCALATION] ⚡ FAST -> 🧠 DEEP (timeout triggered)
[ESCALATION] 🧠 DEEP -> 🌐 DEEP_SEARCH (timeout triggered)
```

---

## API Endpoints

### GET /api/mode

Returns current mode status:

```json
{
  "current_mode": "fast",
  "icon": "⚡",
  "deep_mode": false,
  "auto_escalation": true,
  "mode_history": [],
  "escalations_count": 0,
  "web_searches_count": 0
}
```

### POST /api/mode

Switch mode:

```json
// Request
{"mode": "deep"}

// Response
{
  "success": true,
  "message": "[MODE] ⚡ FAST -> 🧠 DEEP",
  "old_mode": "fast",
  "new_mode": "deep"
}
```

---

## Statistics

Mode-related stats available via `/stats`:

```json
{
  "mode_escalations": 0,
  "web_searches": 0,
  "cot_sessions": 0
}
```

---

## Integration with Claude Code

This mode system mirrors Claude Code's behavior:

| Claude Code | QwenCode |
|-------------|----------|
| Default mode | FAST MODE |
| `[DEEP]` prefix | DEEP MODE |
| Web search | DEEP SEARCH MODE |
| Auto-escalation | Timeout-based |

---

## Quick Start

```bash
# Start QwenCode
cd C:\Users\serga\QwenAgent
start.bat

# Open in browser
http://localhost:5002

# Try modes
/mode fast
read README.md

/mode deep
[DEEP] analyze this codebase architecture

/mode search
[SEARCH] latest Docker security CVE
```

---

*Created: 2026-01-26*
*QwenCode v1.0.0*
