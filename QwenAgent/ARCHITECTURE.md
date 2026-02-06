# QwenAgent - Architecture Diagrams

**Version:** 2.0 | **Modules:** 34 core + 8 validator + 13 tests = 55 Python files
**Date:** 2026-02-06

---

## SCHEMA 1: High-Level System Overview

```
+=========================================================================+
|                         QWENAGENT SYSTEM                                |
|                                                                         |
|  +------------------+     +------------------+     +-----------------+  |
|  |   FRONTEND       |     |    SERVER         |     |  LLM BACKEND   |  |
|  |                  |     |                  |     |                 |  |
|  |  Web UI (HTML)   |---->| Flask + SSE      |---->| Ollama API     |  |
|  |  CLI Terminal    |     | Port 5002        |     | localhost:11434 |  |
|  |  Claude Code     |     |                  |     |                 |  |
|  +------------------+     +--------+---------+     | qwen2.5-coder  |  |
|                                    |               | :3b / :7b      |  |
|                           +--------v---------+     +-----------------+  |
|                           |                  |                          |
|                           |  CORE ENGINE     |                          |
|                           |  (34 modules)    |                          |
|                           |                  |                          |
|                           +--------+---------+                          |
|                                    |                                    |
|                           +--------v---------+                          |
|                           |                  |                          |
|                           | CODE VALIDATOR   |                          |
|                           | (5 levels)       |                          |
|                           |                  |                          |
|                           +------------------+                          |
+=========================================================================+
```

**Description:**
The system consists of three main layers. The Frontend accepts user queries via Web UI
or CLI. The Server (Flask + SSE) handles HTTP requests and streams responses.
The Core Engine (34 modules) processes queries, classifies them, and executes tools.
The Code Validator (5 levels) ensures generated code quality.
The LLM Backend is Ollama running Qwen 2.5-coder models locally.

---

## SCHEMA 2: Request Processing Pipeline (Fast Path vs Deep Path)

```
                          USER INPUT
                              |
                              v
                    +-------------------+
                    | QueryModifier     |  Phase 6: auto-language suffix
                    | /lang, /modifiers |  skip tool-commands (git, grep...)
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | PatternRouter     |  71 regex patterns
                    | (Fast Path)       |  NO-LLM, instant response
                    +--------+----------+
                             |
                 +-----------+-----------+
                 |                       |
            MATCH FOUND             NO MATCH
                 |                       |
                 v                       v
        +----------------+     +-------------------+
        | UnifiedTools   |     | Orchestrator      |
        |                |     |                   |
        | read()         |     | Tier 0: Pattern   |
        | grep()         |     | Tier 1: DUCS      |
        | find()         |     | Tier 1.5: Light   |
        | ls()           |     | Tier 2: LLM       |
        | bash()         |     | Tier 3: CoT       |
        | edit()         |     | Tier 4: Agent     |
        | write()        |     |                   |
        +-------+--------+     +--------+----------+
                |                        |
                v                        v
        +----------------+     +-------------------+
        | SSE Response   |     | TimeoutLLMClient  |---> Ollama API
        | (instant)      |     | TTFT / Idle / Abs |
        +----------------+     +--------+----------+
                                        |
                                        v
                               +-------------------+
                               | SSE Response      |
                               | (streaming)       |
                               +-------------------+
```

**Description:**
Every request first passes through QueryModifier (adds language suffix, routes
modifier commands like /lang, /modifiers). Then PatternRouter tries 71 regex
patterns for instant NO-LLM execution. If matched, UnifiedTools executes the
command directly (read, grep, find, etc.) and returns an SSE response instantly.

If no pattern matches, the Orchestrator escalates through 5 tiers:
- Tier 0: Pattern matching (already failed)
- Tier 1: DUCS classification (DevOps templates, NO-LLM)
- Tier 1.5: Lightweight LLM classification
- Tier 2: Simple LLM call
- Tier 3: Chain-of-Thought reasoning
- Tier 4: Full autonomous agent

The LLM calls go through TimeoutLLMClient with three timeout levels (TTFT,
idle, absolute) to prevent hangs.

---

## SCHEMA 3: Timeout Escalation Chain

```
    +----------+   timeout   +----------+   timeout   +----------+
    |          | ----------> |          | ----------> |          |
    |   FAST   |             |   DEEP   |             |  SEARCH  |
    |   MODE   |             |   MODE   |             |   MODE   |
    |          | <---------- |          | <---------- |          |
    +----------+   success   +----------+   success   +----------+
         |                        |                        |
         v                        v                        v
    +-----------+          +-----------+          +-----------+
    | Pattern   |          | 3 or 6    |          | WebSearch |
    | Router    |          | Minsky    |          | + WebFetch|
    | + Tools   |          | Steps     |          | + Analyze |
    | NO-LLM   |          | + CoT     |          |           |
    +-----------+          +-----------+          +-----------+
    ~ 0.01 sec             ~ 5-30 sec             ~ 10-60 sec

    ESCALATION TRIGGERS:
    FAST -> DEEP:   Pattern not found, or task too complex
    DEEP -> SEARCH: Local data insufficient, or LLM timeout
```

**Description:**
The system uses an automatic escalation chain. FAST mode handles 85%+ of queries
without any LLM call. If FAST fails (no pattern match or task is complex),
it escalates to DEEP mode which uses 3-step (DEEP3) or 6-step (DEEP6) Minsky
reasoning with Chain-of-Thought. If DEEP mode times out or needs external
data, it escalates to SEARCH mode which uses web search (DuckDuckGo/SearXNG).
Each escalation is logged: "[ESCALATION] FAST -> DEEP: timeout".

---

## SCHEMA 4: Core Engine Module Map (34 modules)

```
+=========================================================================+
|                          CORE ENGINE                                    |
|                                                                         |
|  AGENT & ORCHESTRATION            ROUTING & QUERY                       |
|  +---------------------+         +------------------------+            |
|  | qwencode_agent.py   |-------->| pattern_router.py (71) |            |
|  | (central brain)     |    |    | router.py (hybrid)     |            |
|  +---------------------+    |    | pattern_discovery.py   |            |
|  | orchestrator.py     |----+    | query_modifier.py      |            |
|  | (tier 0-4)          |    |    | query_crystallizer.py  |            |
|  +---------------------+    |    +------------------------+            |
|  | adaptive_pipeline.py|    |                                           |
|  +---------------------+    |    CLASSIFICATION                         |
|                              |    +------------------------+            |
|  TOOLS                       +--->| swecas_classifier.py   |            |
|  +---------------------+    |    | (9 categories 100-900) |            |
|  | unified_tools.py    |<---+    +------------------------+            |
|  | (read,grep,find,ls, |    |    | ducs_classifier.py     |            |
|  |  bash,edit,write)   |    |    | (DevOps classification)|            |
|  +---------------------+    |    +------------------------+            |
|  | tools_extended.py   |    |    | tier1_5_classifier.py  |            |
|  | tools.py (legacy)   |    |    +------------------------+            |
|  +---------------------+    |                                           |
|                              |    REASONING & DEEP MODE                  |
|  TIMEOUT & BUDGET            |    +------------------------+            |
|  +---------------------+    +--->| cot_engine.py          |            |
|  | timeout_llm_client  |         | (CoT steps)            |            |
|  | (TTFT/idle/abs)     |         +------------------------+            |
|  +---------------------+         | deep_mode_v2.py        |            |
|  | time_budget.py      |         | (DEEP3: 3 steps)       |            |
|  | budget_estimator.py |         +------------------------+            |
|  | predictive_estimator|         | deep6_minsky.py        |            |
|  | intent_scheduler.py |         | (DEEP6: 6 steps)       |            |
|  | user_timeout_config |         +------------------------+            |
|  +---------------------+         | plan_mode.py           |            |
|                                   +------------------------+            |
|  LLM & STREAMING                                                        |
|  +---------------------+         AGENTS & TASKS                         |
|  | streaming_llm_client|         +------------------------+            |
|  | (Ollama SSE)        |         | subagent.py            |            |
|  +---------------------+         | (task delegation)      |            |
|                                   +------------------------+            |
|  CONFIG & UTILS                   | agent.py (interface)   |            |
|  +---------------------+         +------------------------+            |
|  | config.py           |                                                |
|  | config_validator.py |         SWE-BENCH                              |
|  | execution_mode.py   |         +------------------------+            |
|  | repo_manager.py     |         | swebench_pipeline.py   |            |
|  | search_translator.py|         | swebench_runner.py     |            |
|  | no_llm_responder.py |         +------------------------+            |
|  +---------------------+                                                |
+=========================================================================+
```

**Description:**
The Core Engine consists of 34 Python modules organized by function:

- **Agent & Orchestration** (3): Central brain that coordinates everything.
  `qwencode_agent.py` is the main entry point, `orchestrator.py` manages
  tier-based processing, `adaptive_pipeline.py` adjusts workflow dynamically.

- **Routing & Query** (5): `pattern_router.py` has 71 compiled regex patterns
  for instant NO-LLM command routing. `query_modifier.py` adds language
  suffixes and handles /lang, /modifiers commands. `pattern_discovery.py`
  analyses and tests pattern quality.

- **Classification** (3): `swecas_classifier.py` classifies bugs into 9
  categories (100-900) using pure pattern matching (NO ML).
  `ducs_classifier.py` classifies DevOps tasks. `tier1_5_classifier.py`
  is a lightweight LLM classifier between NO-LLM and full LLM.

- **Reasoning & Deep Mode** (4): Chain-of-Thought engine with 3-step (DEEP3)
  and 6-step (DEEP6 Minsky) modes. `plan_mode.py` handles multi-step planning.

- **Tools** (3): `unified_tools.py` is the single source of truth for all
  file operations (read, grep, find, ls, bash, edit, write).

- **Timeout & Budget** (5): 4-phase timeout management system from basic
  TTFT timeouts to predictive estimation and intent-aware scheduling.

- **LLM & Streaming** (1): SSE streaming client for Ollama API.

- **Config & Utils** (6): Configuration, validation, execution modes.

- **Agents & Tasks** (2): Sub-agent delegation and task tracking.

- **SWE-bench** (2): Benchmark pipeline and runner.

---

## SCHEMA 5: Code Validator Pipeline (5 Levels)

```
                      GENERATED CODE
                           |
                           v
    +==============================================+
    |  LEVEL 0: PREVALIDATION (prevalidator.py)    |  ~ 1ms
    |                                              |
    |  [AST Parse] --> [Forbidden Imports]          |
    |       |              os, sys, subprocess,     |
    |       |              socket, pickle, ctypes   |
    |       v                                      |
    |  [Forbidden Builtins] --> [Forbidden Attrs]   |
    |   eval, exec, compile     __code__, __globals_|
    |   open, __import__        __class__, __dict__ |
    |       |                                      |
    |       v                                      |
    |  [Infinite Loop] --> [String Patterns]        |
    |   while True no break    bypass attempts      |
    |                                              |
    |  Result: PASS / CRITICAL FAIL                |
    +======================+=======================+
                           | PASS
                           v
    +==============================================+
    |  LEVEL 1: STATIC ANALYSIS (static_analysis)  |  ~ 200ms
    |                                              |
    |  +----------+  +--------+  +---------+       |
    |  |   RUFF   |  |  MYPY  |  | BANDIT  |       |
    |  | (linter) |  | (types)|  |(security)|      |
    |  |  E,F,B,  |  | ignore |  |  -f json |      |
    |  |  S,W     |  | missing|  |  -ll     |      |
    |  +----+-----+  +---+----+  +----+-----+      |
    |       |             |           |             |
    |       +------+------+-----------+             |
    |              v                                |
    |       Aggregated Issues                       |
    |  Result: PASS / WARNINGS / FAIL              |
    +======================+=======================+
                           | PASS
                           v
    +==============================================+
    |  LEVEL 2: SANDBOX EXECUTION (sandbox.py)     |  ~ 5s
    |                                              |
    |  +------------------+                        |
    |  | RestrictedPython |  In-process, fastest   |
    |  +------------------+                        |
    |  | Subprocess       |  Separate process      |  <-- DEFAULT
    |  +------------------+                        |
    |  | Docker           |  Full container        |
    |  | --network=none   |  strongest isolation   |
    |  | --read-only      |                        |
    |  +------------------+                        |
    |                                              |
    |  Timeout: 10s | Memory: 128MB                |
    |  Result: SUCCESS / TIMEOUT / RUNTIME_ERROR   |
    +======================+=======================+
                           | SUCCESS
                           v
    +==============================================+
    |  LEVEL 3: PROPERTY TESTING (property_tests)  |  ~ 10s
    |                                              |
    |  Hypothesis library (100 examples/property)  |
    |                                              |
    |  +-------------------+  +------------------+ |
    |  | NO_EXCEPTION      |  | DETERMINISTIC    | |
    |  | f(x) doesn't crash|  | f(x)==f(x)       | |
    |  +-------------------+  +------------------+ |
    |  | IDEMPOTENT        |  | TYPE_PRESERVING  | |
    |  | f(f(x))==f(x)     |  | type(f(x))==T    | |
    |  +-------------------+  +------------------+ |
    |  | COMMUTATIVE       |  | INVARIANT        | |
    |  | f(x,y)==f(y,x)    |  | custom property  | |
    |  +-------------------+  +------------------+ |
    |                                              |
    |  Auto-infers strategies from type hints      |
    |  Result: PASSED / FAILED (per property)      |
    +======================+=======================+
                           | PASSED
                           v
    +==============================================+
    |  LEVEL 4: RESOURCE MONITORING (resource_guard)|  ~ 1ms
    |                                              |
    |  +-----------+  +----------+  +-----------+  |
    |  | Memory    |  | CPU Time |  | Wall Time |  |
    |  | tracemalloc  | resource |  | perf_cnt  |  |
    |  | peak MB   |  | seconds  |  | seconds   |  |
    |  +-----------+  +----------+  +-----------+  |
    |                                              |
    |  Limits: 256MB memory, 30s wall, 30s CPU     |
    |  Exceptions: MemoryLimitExceeded,            |
    |              TimeLimitExceeded,               |
    |              CPULimitExceeded                 |
    |  Result: PASS + ResourceUsageReport          |
    +==============================================+
                           |
                           v
                  +------------------+
                  | ValidationReport |
                  |                  |
                  | status: PASSED   |
                  | levels: 5/5      |
                  | duration: 15.2s  |
                  +------------------+
```

**Description:**
The Code Validator is a 5-level pipeline that ensures generated code quality:

- **Level 0 (Prevalidation):** Pure Python AST analysis in ~1ms. Checks syntax,
  forbidden imports (os, sys, subprocess...), forbidden builtins (eval, exec...),
  forbidden attributes (__code__, __globals__...), infinite loops, and string
  bypass patterns. A CRITICAL failure here stops the entire pipeline.

- **Level 1 (Static Analysis):** Runs three external tools in ~200ms:
  Ruff (linter for style/bugs), Mypy (type checking), Bandit (security scanning).
  Results are aggregated into a unified issue list.

- **Level 2 (Sandbox Execution):** Actually runs the code in isolation.
  Three sandbox types available: RestrictedPython (in-process, fastest),
  Subprocess (separate process, default), Docker (full container, strongest).
  Default limits: 10s timeout, 128MB memory.

- **Level 3 (Property Testing):** Uses Hypothesis library to generate 100
  random test cases per property. Auto-infers test strategies from type hints.
  Checks mathematical properties: idempotent, deterministic, commutative, etc.

- **Level 4 (Resource Monitoring):** Tracks memory (tracemalloc), CPU time,
  and wall time. Raises exceptions if limits are exceeded (256MB, 30s).

The pipeline can be configured to stop on first failure or collect all issues.

---

## SCHEMA 6: SWECAS Classification System (9 Categories)

```
                    BUG DESCRIPTION + CODE
                            |
                            v
                  +-------------------+
                  | SWECASClassifier  |  Pure regex, NO ML
                  | Pattern matching  |
                  +--------+----------+
                           |
           +---------------+---------------+
           |       |       |       |       |
           v       v       v       v       v
    +-----+ +-----+ +-----+ +-----+ +-----+
    | 100 | | 200 | | 300 | | 400 | | 500 |
    |Null/| |Imprt| |Type/| |API/ | | Sec |
    |None | |Deps | |Intf | |Depr | | Val |
    +-----+ +-----+ +-----+ +-----+ +-----+
           |       |       |       |
           v       v       v       v
    +-----+ +-----+ +-----+ +-----+
    | 600 | | 700 | | 800 | | 900 |
    |Logic| |Conf/| |Perf/| |Async|
    |Flow | |Env  | |Rsrc | |I/O  |
    +-----+ +-----+ +-----+ +-----+

    Each category provides:
    +----------------------------------------------+
    | swecas_code:  "600"                          |
    | subcategory:  "off-by-one"                   |
    | confidence:   0.85                           |
    | fix_hint:     "Check loop bounds..."         |
    | diffuse_links: [100, 300, 800]               |
    | diffuse_prompts: ["What if this is a         |
    |   type issue, not logic?"]                   |
    | fix_template:  "for i in range(len-1):..."   |
    +----------------------------------------------+

    DIFFUSE THINKING (Barbara Oakley):
    +----------+         +----------+
    | FOCUSED  | ------> | DIFFUSE  |
    | Category |  stuck  | Cross-   |
    | 600      |         | category |
    +----------+         | 100,300, |
         ^               | 800      |
         |    insight     +----------+
         +----------------+
```

**Description:**
SWECAS (Software Engineering Category and Subcategory) classifies bugs into
9 categories without any ML -- pure regex pattern matching. Each category
covers a specific domain:

- **100:** Null/None & Value Errors (NoneType, KeyError, IndexError)
- **200:** Import & Module Dependencies (ModuleNotFoundError, circular imports)
- **300:** Type & Interface Mismatches (TypeError, wrong signatures)
- **400:** API Usage & Deprecation (deprecated calls, wrong API parameters)
- **500:** Security & Validation (injection, XSS, CVE, authentication)
- **600:** Logic & Control Flow (off-by-one, infinite loops, wrong conditions)
- **700:** Configuration & Environment (env vars, config files, paths)
- **800:** Performance & Resource (memory leaks, N+1 queries, timeouts)
- **900:** Async, Concurrency & I/O (race conditions, deadlocks, file I/O)

The Diffuse Thinking feature (inspired by Barbara Oakley's "Learning How to
Learn") provides cross-category links when the focused approach is stuck.
For example, a "logic error" (600) might actually be a "type mismatch" (300)
or "null reference" (100).

---

## SCHEMA 7: Server Architecture (Flask + SSE)

```
    +================================================================+
    |                  qwencode_unified_server.py                     |
    |                                                                |
    |  ENDPOINTS:                                                    |
    |  +--------------------------+                                  |
    |  | GET  /                   |  Web UI (index.html)             |
    |  | GET  /api/health         |  Health check + stats            |
    |  | POST /api/chat           |  Synchronous chat                |
    |  | POST /api/chat/stream    |  SSE streaming chat              |
    |  | POST /api/approve        |  Human-in-the-loop approval      |
    |  +--------------------------+                                  |
    |                                                                |
    |  SINGLETONS (initialized at startup):                          |
    |  +---------------------+                                       |
    |  | UnifiedTools        |  File operations                      |
    |  | PatternRouter       |  71 patterns, fast path               |
    |  | SWECASClassifier    |  Bug classification                   |
    |  | QueryModifierEngine |  Language suffixes                    |
    |  | ApprovalManager     |  Human-in-the-loop (optional)         |
    |  +---------------------+                                       |
    |                                                                |
    |  MODELS:                                                       |
    |  +---------------------+                                       |
    |  | Fast:  qwen2.5-coder:3b  |  Pattern miss, simple queries   |
    |  | Heavy: qwen2.5-coder:3b  |  Deep mode, code generation     |
    |  +---------------------+                                       |
    |                                                                |
    |  SSE EVENT TYPES:                                              |
    |  +--------------------+------------------------------------+   |
    |  | status             | Processing status updates          |   |
    |  | tool_start         | Tool execution begins              |   |
    |  | tool_result        | Tool execution result              |   |
    |  | response           | LLM response chunk                 |   |
    |  | done               | Request complete                   |   |
    |  | approval_required  | Needs user confirmation            |   |
    |  +--------------------+------------------------------------+   |
    +================================================================+

    REQUEST FLOW (POST /api/chat):

    message -----> QueryModifier -----> PatternRouter
                        |                    |
                   /lang cmd?           match found?
                   Return immediately   Return tool result
                        |                    |
                        NO                   NO
                        |                    |
                        v                    v
                   SWECAS classify ---> Ollama LLM ---> Parse tools
                        |                                    |
                        v                                    v
                   Add classification            UnifiedTools.execute()
                   context to prompt                    |
                        |                               v
                        +-------> Aggregate response <---+
                                        |
                                        v
                                  JSON Response
```

**Description:**
The server is a Flask application with CORS support. It exposes 5 endpoints.
At startup, it initializes singletons: UnifiedTools, PatternRouter (71 patterns),
SWECASClassifier, QueryModifierEngine, and optionally ApprovalManager.

The /api/chat endpoint processes requests synchronously:
1. QueryModifier checks for /lang, /modifiers commands (returns immediately)
2. QueryModifier applies language suffix to normal queries
3. PatternRouter tries 71 regex patterns for instant tool execution
4. If no match, SWECAS classifies the query and sends to Ollama LLM
5. LLM response is parsed for tool calls, tools are executed
6. Final response is returned as JSON

The /api/chat/stream endpoint uses Server-Sent Events (SSE) for real-time
streaming, with event types: status, tool_start, tool_result, response, done.

---

## SCHEMA 8: Timeout Management (4 Phases)

```
    PHASE 1: Basic Timeouts          PHASE 2: Budget Management
    (timeout_llm_client.py)          (time_budget.py, budget_estimator.py)

    +-------------------+            +------------------------+
    | TimeoutLLMClient  |            | TimeBudget             |
    |                   |            |                        |
    | TTFT:    5s       |            | Step 1: 20% of total   |
    | (first token)     |            | Step 2: 30% of total   |
    |                   |            | Step 3: 50% of total   |
    | Idle:    3s       |            |                        |
    | (between tokens)  |            | Savings transfer:      |
    |                   |            | Step 1 saves 5s -->    |
    | Absolute: 60s     |            | Step 2 gets +5s bonus  |
    | (total time)      |            |                        |
    +-------------------+            +------------------------+

    PHASE 3: Predictive              PHASE 4: Intent-Aware
    (predictive_estimator.py)        (intent_scheduler.py)

    +-------------------+            +------------------------+
    | PredictiveEstim.  |            | IntentScheduler        |
    |                   |            |                        |
    | Input: task desc  |            | StreamAnalyzer:        |
    | Output: timeout   |            | - code detection       |
    |                   |            | - thinking detection   |
    | Learns from       |            | - tool call detection  |
    | past executions   |            |                        |
    | to predict how    |            | Dynamic adjustment:    |
    | long next task    |            | if code generating --> |
    | will take         |            |   extend timeout       |
    +-------------------+            | if idle chatter -->    |
                                     |   reduce timeout       |
                                     +------------------------+

    INTEGRATION:

    User Query --> Phase 4 (Intent) --> Phase 3 (Predict) -->
                  Phase 2 (Budget) --> Phase 1 (Execute)

    Example: "fix authentication bug"
    Phase 4: Intent = code_fix, complexity = medium
    Phase 3: Predicted time = 25s (based on history)
    Phase 2: Budget = Step1: 5s, Step2: 8s, Step3: 12s
    Phase 1: Execute with TTFT=5s, Idle=3s, Absolute=30s
```

**Description:**
Timeout management evolved through 4 phases:

- **Phase 1 (Basic):** Three timeout types -- TTFT (time to first token, 5s),
  Idle (gap between tokens, 3s), Absolute (total time, 60s). If any fires,
  raises specific exception (TTFTTimeoutError, IdleTimeoutError, etc.).

- **Phase 2 (Budget):** Allocates time budget per step with savings transfer.
  If Step 1 finishes early, unused time transfers to Step 2. This prevents
  wasting time on easy steps while giving more to hard ones.

- **Phase 3 (Predictive):** Learns from past executions to predict how long
  the next task will take. Input: task description. Output: predicted timeout.

- **Phase 4 (Intent-Aware):** StreamAnalyzer detects what the LLM is doing
  in real-time (generating code, thinking, calling tools) and dynamically
  adjusts timeouts. Code generation gets more time; idle chatter gets less.

All phases integrate: Phase 4 determines intent, Phase 3 predicts duration,
Phase 2 allocates budget, Phase 1 executes with hard limits.

---

## SCHEMA 9: Test Architecture (13 test files, 60+ checks)

```
    +================================================================+
    |                       TEST SUITE                                |
    |                                                                |
    |  conftest.py (shared fixtures)                                 |
    |  +----------------------------------------------------------+  |
    |  | classifier()    | SWECASClassifier instance               |  |
    |  | cot_engine()    | CoT engine with deep mode               |  |
    |  | search_cache()  | Loaded SWECAS search cache              |  |
    |  | tmpdir_clean()  | Temporary test directory                |  |
    |  +----------------------------------------------------------+  |
    |                                                                |
    |  CODE QUALITY TESTS (test_code_generation_quality.py)          |
    |  +----------------------------------------------------------+  |
    |  | Test 1:  Algorithms & Data Structures    | 6/6 checks    |  |
    |  | Test 2:  OOP: Inheritance, Polymorphism   | 6/6 checks    |  |
    |  | Test 3:  Async/Await Programming          | 6/6 checks    |  |
    |  | Test 4:  Security: Injection Prevention   | 6/6 checks    |  |
    |  | Test 5:  Data Processing Pipeline         | 6/6 checks    |  |
    |  | Test 6:  Error Handling & Exceptions       | 6/6 checks    |  |
    |  | Test 7:  Design Patterns (Strategy+Obs)   | 6/6 checks    |  |
    |  | Test 8:  Functional: Decorators           | 6/6 checks    |  |
    |  | Test 9:  Test Generation Quality          | 6/6 checks    |  |
    |  | Test 10: Pattern Coverage & Quality       | 6/6 checks    |  |
    |  +----------------------------------------------------------+  |
    |  Uses: Prevalidator + StaticAnalyzer + CodeValidator            |
    |        + PatternRouter (for pattern quality assessment)         |
    |                                                                |
    |  SWECAS TESTS                                                  |
    |  +----------------------------------------------------------+  |
    |  | test_swecas_integration.py    | 9 integration tests      |  |
    |  | test_classifier_accuracy.py   | 27 accuracy tests        |  |
    |  | test_edge_cases.py            | 15 edge case tests       |  |
    |  | test_search_fallback.py       | 5 fallback chain tests   |  |
    |  | test_regression.py            | 6 regression tests       |  |
    |  +----------------------------------------------------------+  |
    |                                                                |
    |  SYSTEM TESTS                                                  |
    |  +----------------------------------------------------------+  |
    |  | test_orchestrator_bilingual_integration.py                |  |
    |  | test_config_validator.py                                  |  |
    |  | devops_tests.py                                           |  |
    |  | audit_patterns.py                                         |  |
    |  | manual_test_full_system.py                                |  |
    |  +----------------------------------------------------------+  |
    +================================================================+

    VALIDATORS USED IN TESTS:
    +------------------+     +------------------+     +------------------+
    | check_ast_valid  |     | check_no_forbid  |     | check_type_hints |
    | (ast.parse)      |     | (Prevalidator)   |     | (AST annotation) |
    +------------------+     +------------------+     +------------------+
    | check_docstrings |     | check_complexity |     | check_secrets    |
    | (AST Constant)   |     | (nesting depth)  |     | (regex patterns) |
    +------------------+     +------------------+     +------------------+
    | check_errors     |     | check_func_len   |     | run_full_valid   |
    | (try/raise/bare) |     | (end_lineno)     |     | (CodeValidator)  |
    +------------------+     +------------------+     +------------------+
```

**Description:**
The test suite contains 13 Python files organized in three groups:

- **Code Quality Tests** (10 tests, 60 checks): Each test generates Python code
  for a specific domain (algorithms, OOP, async, security, etc.) and validates it
  through automatic quality control systems: Prevalidator (AST), StaticAnalyzer
  (Ruff/Mypy/Bandit), and CodeValidator. Test 10 specifically assesses pattern
  router coverage and quality (regex validity, priority conflicts, matching speed,
  category coverage, parameter extraction).

- **SWECAS Tests** (62 tests): Integration tests for the bug classifier,
  accuracy tests (3 per SWECAS category x 9 = 27), edge cases, fallback chains,
  and regression tests.

- **System Tests** (5 files): Bilingual integration, config validation,
  DevOps-specific tests, pattern audits, and manual full system tests.

---

## SCHEMA 10: Component Dependency Graph

```
                        qwencode_agent.py
                              |
        +----------+----------+----------+----------+
        |          |          |          |          |
        v          v          v          v          v
   pattern_    unified_   cot_      swecas_    timeout_
   router.py   tools.py  engine.py  classif.py llm_client.py
        |                    |                      |
        v                    v                      v
   pattern_           +------+------+         time_budget.py
   discovery.py       |             |               |
                 deep_mode    deep6_         budget_
                 _v2.py       minsky.py      estimator.py
                      |             |               |
                      v             v               v
                 config.py    plan_mode.py   predictive_
                                             estimator.py
                                                    |
                                                    v
                                             intent_
                                             scheduler.py

   orchestrator.py
        |
        +----------+----------+----------+
        |          |          |          |
        v          v          v          v
   pattern_    ducs_      query_     tier1_5_
   router.py   classif.py crystal.py classif.py

   qwencode_unified_server.py
        |
        +----------+----------+----------+----------+
        |          |          |          |          |
        v          v          v          v          v
   unified_   pattern_   swecas_   query_     approval_
   tools.py   router.py  classif.  modifier.  manager

   code_validator/validator.py
        |
        +----------+----------+----------+----------+
        |          |          |          |          |
        v          v          v          v          v
   prevalidator  static_    sandbox   property_  resource_
   .py           analysis.  .py       tests.py   guard.py
                 py
```

**Description:**
The dependency graph shows how modules connect:

- **qwencode_agent.py** is the central hub, importing 5 major subsystems:
  pattern routing, tools, reasoning (CoT), classification (SWECAS), and
  timeout management. The timeout chain goes 4 levels deep.

- **orchestrator.py** coordinates pattern routing, DUCS classification,
  query crystallization, and tier-based processing.

- **qwencode_unified_server.py** initializes 5 singletons at startup and
  wires them together for HTTP request handling.

- **code_validator/validator.py** orchestrates 5 independent validation
  levels, each with its own module. Levels can be enabled/disabled via config.

---

## SCHEMA 11: Data Flow -- Complete Request Lifecycle

```
    USER: "fix the authentication bug in login.py"
     |
     v
    [1] QueryModifier
     |  Input:  "fix the authentication bug in login.py"
     |  Output: "fix the authentication bug in login.py Respond in Russian."
     v
    [2] PatternRouter (71 patterns)
     |  No match (not a tool command)
     v
    [3] SWECASClassifier
     |  Pattern: "authentication" + "bug" + "fix"
     |  Result: { code: 500, subcategory: "auth-bypass",
     |            confidence: 0.82,
     |            fix_hint: "Check auth middleware..." }
     v
    [4] CoTEngine (DEEP3 mode)
     |  Step 1 (ANALYZE): Read login.py, understand auth flow
     |  Step 2 (PLAN):    Identify fix approach, check tests
     |  Step 3 (GENERATE): Write fix code
     v
    [5] TimeoutLLMClient --> Ollama API
     |  TTFT: 2.1s, Generation: 8.3s, Total: 10.4s
     |  Model: qwen2.5-coder:3b
     v
    [6] Parse LLM Response
     |  Tool calls found: [read("login.py"), edit("login.py", ...)]
     v
    [7] UnifiedTools.execute()
     |  read("login.py") --> file content
     |  edit("login.py", old="...", new="...") --> OK
     v
    [8] CodeValidator (if code generated)
     |  L0: Prevalidation  --> PASS (no forbidden constructs)
     |  L1: Static Analysis --> PASS (ruff OK, mypy OK)
     v
    [9] SSE Response
     |  event: status    "Analyzing authentication bug..."
     |  event: tool_start "Reading login.py"
     |  event: tool_result "File content (142 lines)"
     |  event: response   "Fixed auth check in line 47..."
     |  event: done       { total_time: 12.8s }
     v
    USER sees: fix applied, explanation provided
```

**Description:**
This shows the complete lifecycle of a real request through all system layers.
The query goes through modifier (language suffix), pattern router (no match),
SWECAS classification (category 500: security), CoT reasoning (3 steps),
LLM generation via Ollama, tool execution (read + edit), code validation
(2 levels), and finally SSE streaming response to the user.

Total time: ~12.8 seconds for a complete bug fix with classification,
reasoning, file reading, code editing, and validation.

---

*Generated: 2026-02-06 | QwenAgent v2.0 | 55 Python modules*
