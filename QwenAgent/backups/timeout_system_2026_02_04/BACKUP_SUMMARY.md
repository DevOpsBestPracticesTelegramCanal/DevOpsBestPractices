# Timeout System Backup - 2026-02-04

## Overview

Complete backup of the 4-phase timeout management system for QwenCode agent.

**Date:** 2026-02-04
**Status:** 95% Complete (All phases integrated)
**Tests:** ALL PASSED

---

## Files Included

| File | Size | Description |
|------|------|-------------|
| qwencode_agent.py | 106KB | Main agent with budget integration |
| streaming_llm_client.py | 19KB | Phase 1: Async streaming with timeouts |
| timeout_llm_client.py | 15KB | Phase 1: Sync wrapper with fallback |
| time_budget.py | 20KB | Phase 2: Budget allocation system |
| budget_estimator.py | 14KB | Phase 2: History-based prediction |
| user_timeout_config.py | 14KB | Phase 3: User preferences |
| intent_scheduler.py | 29KB | Phase 4: Stream analysis |
| cot_engine.py | 19KB | CoT engine with budget tracking |

**Total:** ~237KB of timeout system code

---

## Phase Status

### Phase 1: Streaming Timeouts [COMPLETE]
- TTFT timeout (Time To First Token): 30s default
- Idle timeout (silence detection): 15s default
- Absolute timeout (hard limit): mode-dependent
- Automatic fallback to lighter model on timeout

### Phase 2: Budget Management [COMPLETE]
- TimeBudget class with step allocation
- Critical step gets 40% of budget
- Dynamic reallocation of saved time
- Budget exhaustion detection

**Key Integration in `_call_llm()`:**
```python
def _call_llm(self, prompt, system=None, max_time=None):
    # Phase 2: Use remaining budget
    if max_time is not None and max_time < float('inf'):
        effective_budget = min(mode_budget, max_time)

    timeout_override = TimeoutConfig(
        ttft_timeout=min(ttft, effective_budget * 0.3),
        idle_timeout=min(idle, effective_budget * 0.2),
        absolute_max=effective_budget
    )
```

### Phase 3: User Configuration [COMPLETE]
- `.qwencoderules` file support
- Mode-specific budgets (fast=30s, deep=120s, search=60s)
- Model preferences per mode
- Priority settings

### Phase 4: Intent Scheduler [COMPLETE]
- Real-time token stream analysis
- Pattern detection (exploring, stuck, coding)
- Dynamic timeout extension/reduction
- Integrated into TimeoutLLMClient.generate()

---

## Key Changes Made

### 1. `qwencode_agent.py`

**process() method (line ~440):**
```python
# Phase 2: Check budget before LLM call
if self.cot_engine.is_budget_exhausted():
    result["response"] = "[Budget exhausted] Task incomplete."
    break

# Phase 2: Get remaining budget
remaining_budget = self.cot_engine.get_remaining_budget()

# Call LLM with budget-aware timeout
llm_response = self._call_llm(current_prompt, system_prompt, max_time=remaining_budget)
```

**process_stream() method (line ~770):**
```python
# Phase 2: Check budget before LLM call
if self.cot_engine.is_budget_exhausted():
    yield {"event": "response", "text": "[Budget exhausted] Task incomplete."}
    break

# Phase 2: Get remaining budget for this call
remaining_budget = self.cot_engine.get_remaining_budget()

llm_response = self._call_llm(current_prompt, system_prompt, max_time=remaining_budget)
```

**_call_llm() method (line ~843):**
- Added `max_time` parameter
- Dynamic timeout calculation based on remaining budget
- Proportional TTFT and idle timeout adjustment

### 2. `timeout_llm_client.py`

**Added IntentScheduler support:**
```python
def __init__(self, ..., enable_intent_scheduler: bool = True):
    self._enable_intent_scheduler = enable_intent_scheduler

def _prepare_intent_scheduler(self, timeout: float = None):
    if self._enable_intent_scheduler:
        self._async_client.create_stream_analyzer(timeout)

def generate(self, ...):
    # Phase 4: Prepare IntentScheduler for this generation
    effective_timeout = timeout_override.absolute_max if timeout_override else None
    self._prepare_intent_scheduler(effective_timeout)
```

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
   Total: 120s
   Steps: ['analyze', 'plan', 'generate']
   Remaining: 120.0s
   Is exhausted: False
   [OK] TimeBudget works

[3/5] Testing IntentScheduler...
   Analyzer created: True
   Processed 11 tokens
   Should terminate: False
   Should extend: True
   [OK] IntentScheduler works

[4/5] Testing TimeoutConfig dynamic adjustment...
   Original: ttft=30s, idle=15s, max=120s
   Remaining budget: 45.0s
   Adjusted: ttft=13.5s, idle=9.0s, max=45.0s
   [OK] Dynamic adjustment works

[5/5] Checking qwencode_agent integration...
   _call_llm has max_time param: True
   Budget check in _call_llm: True
   Remaining budget passed: True
   [OK] Agent integration complete

RESULT: ALL TESTS PASSED
```

---

## Architecture Diagram

```
User Request
    |
    v
+-------------------+
| QwenCodeAgent     |
|   process()       |
+-------------------+
    |
    | 1. Check budget exhaustion
    | 2. Get remaining_budget from cot_engine
    |
    v
+-------------------+
| _call_llm()       |
|   max_time param  |
+-------------------+
    |
    | 3. Calculate effective_budget
    | 4. Adjust timeouts proportionally
    |
    v
+-------------------+
| TimeoutLLMClient  |
|   generate()      |
+-------------------+
    |
    | 5. Prepare IntentScheduler
    |
    v
+-------------------+
| StreamingLLMClient|
|   async generate  |
+-------------------+
    |
    | 6. TTFT monitoring
    | 7. Idle monitoring
    | 8. StreamAnalyzer decisions
    |
    v
+-------------------+
| Ollama API        |
+-------------------+
```

---

## Remaining Work (Low Priority)

1. **budget_estimator.py integration**: Use history to predict LLM call duration
2. **E2E testing**: Test with real Ollama under load
3. **Metrics collection**: Track timeout statistics for tuning

---

## Restore Instructions

To restore this backup:
```bash
cd C:/Users/serga/QwenAgent
cp backups/timeout_system_2026_02_04/*.py core/
```

---

## Related Documentation

- `QWEN_CODE_TIMEOUT_IMPLEMENTATION_PROGRAM.md` - Original 4-phase plan
- `core/time_budget.py` - TimeBudget class documentation
- `core/intent_scheduler.py` - StreamAnalyzer documentation

---

*Backup created: 2026-02-04 13:10*
*Total files: 8*
*Total size: ~237KB*
