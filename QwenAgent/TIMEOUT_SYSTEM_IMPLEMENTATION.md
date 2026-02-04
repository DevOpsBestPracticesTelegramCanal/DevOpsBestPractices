# QwenCode Timeout System Implementation

**Date:** 2026-02-04
**Status:** 95% Complete
**Tests:** ALL PASSED

---

## Overview

This document describes the 4-phase timeout management system implemented for QwenCode agent. The system provides intelligent timeout handling with automatic budget allocation, fallback mechanisms, and stream-based decision making.

---

## Architecture

```
User Request (with optional time budget)
    |
    v
+------------------------+
| QwenCodeAgent          |
|   process()            |
|   process_stream()     |
+------------------------+
    |
    | 1. Check budget exhaustion
    | 2. Get remaining_budget from cot_engine
    |
    v
+------------------------+
| _call_llm(max_time)    |
|   - Calculate effective_budget
|   - Adjust timeouts proportionally
+------------------------+
    |
    v
+------------------------+
| TimeoutLLMClient       |
|   - Prepare IntentScheduler
|   - Call async client
+------------------------+
    |
    v
+------------------------+
| StreamingLLMClient     |
|   - TTFT monitoring
|   - Idle monitoring
|   - StreamAnalyzer decisions
+------------------------+
    |
    v
+------------------------+
| Ollama API             |
+------------------------+
```

---

## Phase 1: Streaming Timeouts

**Files:** `core/streaming_llm_client.py`, `core/timeout_llm_client.py`

### Timeout Types

| Timeout | Default | Purpose |
|---------|---------|---------|
| TTFT (Time To First Token) | 30s | Model not starting generation |
| Idle | 15s | Model stopped generating (silence) |
| Absolute | Mode-dependent | Hard limit for entire call |

### Implementation

```python
@dataclass
class TimeoutConfig:
    ttft_timeout: float = 30.0
    idle_timeout: float = 15.0
    absolute_max: float = 600.0
```

### Fallback Mechanism

When primary model times out, automatically falls back to lighter model:
- Primary: `qwen2.5-coder:7b`
- Fallback: `qwen2.5-coder:3b`

---

## Phase 2: Budget Management

**Files:** `core/time_budget.py`, `core/budget_estimator.py`

### TimeBudget Class

Allocates time budget across steps using BAM (Budget Allocation Model):
- Critical step (code generation): 40% of total budget
- Other steps: share remaining 60%

```python
budget = TimeBudget(
    total_seconds=120,
    steps=['analyze', 'plan', 'generate'],
    critical_step='generate'
)

# Result: analyze=24s, plan=24s, generate=72s
```

### Dynamic Reallocation

If a step finishes early, remaining time flows to subsequent steps:
```python
remaining_budget = self.cot_engine.get_remaining_budget()
llm_response = self._call_llm(prompt, system, max_time=remaining_budget)
```

### Timeout Adjustment Formula

```python
effective_budget = min(mode_budget, remaining_budget)
timeout_override = TimeoutConfig(
    ttft_timeout = min(ttft, effective_budget * 0.3),
    idle_timeout = min(idle, effective_budget * 0.2),
    absolute_max = effective_budget
)
```

---

## Phase 3: User Configuration

**File:** `core/user_timeout_config.py`

### .qwencoderules File

Users can configure timeouts via `.qwencoderules`:

```yaml
timeout:
  max_wait: 120          # Total budget in seconds
  priority: "quality"    # quality | speed | balanced

modes:
  fast:
    budget: 30
    model: "qwen2.5-coder:3b"
  deep:
    budget: 300
    model: "qwen2.5-coder:7b"
  search:
    budget: 60
    model: "qwen2.5-coder:3b"
```

### Mode Budgets

| Mode | Budget | Description |
|------|--------|-------------|
| fast | 30s | Quick responses |
| deep | 120s | Complex analysis |
| deep6 | 300s | Full 6-step reasoning |
| search | 60s | Web search |

---

## Phase 4: Intent Scheduler

**File:** `core/intent_scheduler.py`

### Stream Analysis

Real-time analysis of token stream to make intelligent decisions:

```python
class StreamAnalyzer:
    def process_token(self, token: str) -> SchedulingDecision:
        # Analyze token patterns
        # Return decision: extend, reduce, or terminate
```

### Pattern Detection

| Pattern | Action | Reason |
|---------|--------|--------|
| Exploring alternatives | Extend timeout | Model considering options |
| Code generation | Maintain | Active productive work |
| Repetition/loops | Reduce/terminate | Model stuck |
| Completion signals | Terminate early | Task done |

### Integration

```python
def generate(self, ...):
    # Phase 4: Prepare IntentScheduler
    effective_timeout = timeout_override.absolute_max
    self._prepare_intent_scheduler(effective_timeout)
```

---

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `qwencode_agent.py` | 2400 | Main agent with budget integration |
| `streaming_llm_client.py` | 460 | Async streaming with timeouts |
| `timeout_llm_client.py` | 410 | Sync wrapper with fallback |
| `time_budget.py` | 540 | Budget allocation |
| `intent_scheduler.py` | 750 | Stream analysis |
| `user_timeout_config.py` | 370 | User preferences |
| `budget_estimator.py` | 390 | History-based prediction |
| `cot_engine.py` | 560 | CoT with budget tracking |

**Total:** ~5,880 lines of timeout system code

---

## Test Results

```
[1/5] Importing components...
   [OK] TimeoutLLMClient
   [OK] TimeBudget
   [OK] user_timeout_config
   [OK] IntentScheduler
   [OK] StreamingLLMClient (IntentScheduler: True)

[2/5] Testing TimeBudget...
   [OK] TimeBudget works

[3/5] Testing IntentScheduler...
   [OK] IntentScheduler works

[4/5] Testing TimeoutConfig dynamic adjustment...
   [OK] Dynamic adjustment works

[5/5] Checking qwencode_agent integration...
   [OK] Agent integration complete

RESULT: ALL TESTS PASSED
```

---

## Usage Examples

### Basic Usage

```python
from core.qwencode_agent import QwenCodeAgent

agent = QwenCodeAgent()
result = agent.process("Fix the bug in auth.py")
```

### With Custom Budget

```python
# Via .qwencoderules
timeout:
  max_wait: 180
  priority: "quality"
```

### Programmatic Configuration

```python
from core.user_timeout_config import UserTimeoutPreferences

prefs = UserTimeoutPreferences()
prefs.mode_budgets['deep'] = 240  # 4 minutes for deep mode
```

---

## Remaining Work

1. **budget_estimator.py**: Use call history for prediction (low priority)
2. **E2E testing**: Test with real Ollama under load
3. **Metrics dashboard**: Track timeout statistics

---

## Backup Location

```
QwenAgent/backups/timeout_system_2026_02_04/
├── BACKUP_SUMMARY.md
├── qwencode_agent.py
├── streaming_llm_client.py
├── timeout_llm_client.py
├── time_budget.py
├── intent_scheduler.py
├── user_timeout_config.py
├── budget_estimator.py
└── cot_engine.py

QwenAgent/backups/timeout_system_2026_02_04.zip (64KB)
```

---

## Git Commit

```
commit 8498d05
Integrate 4-phase timeout management system
11 files changed, 6602 insertions(+), 14 deletions(-)
```

---

*Documentation created: 2026-02-04*
