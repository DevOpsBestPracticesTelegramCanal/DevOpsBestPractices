# QwenAgent — SWE-bench Capable Code Agent

AI-powered code agent with **SWECAS V2** bug classification, **diffuse thinking** (Oakley theory), and **Chain-of-Thought** reasoning for automated SWE-bench task solving.

## Architecture

```
QwenAgent/
├── core/                             # Core engine
│   ├── qwencode_agent.py             # Main agent (FAST/DEEP/SEARCH modes)
│   ├── swecas_classifier.py          # SWECAS V2 classifier (9 categories)
│   ├── swecas_search_cache.json      # Offline search patterns (v2.0)
│   ├── cot_engine.py                 # Chain-of-Thought reasoning
│   ├── tools_extended.py             # Tool suite (read/write/edit/search)
│   └── router.py                     # Request routing
│
├── tests/                            # Test suite (62+ tests)
│   ├── conftest.py                   # Shared fixtures
│   ├── test_swecas_integration.py    # 9 integration tests
│   ├── test_regression.py            # 6 regression tests
│   ├── test_classifier_accuracy.py   # 27 accuracy tests (3 per category)
│   ├── test_edge_cases.py            # 15 edge case tests
│   └── test_search_fallback.py       # 5 fallback chain tests
│
├── swebench_tasks/                   # SWE-bench task collection (10 tasks)
│   ├── pallets__flask-4045/          # SWECAS-500: Validation
│   ├── psf__requests-2317/           # SWECAS-300: Type
│   ├── django__django-11099/         # SWECAS-600: Logic
│   ├── django__django-12286/         # SWECAS-500: Validation
│   ├── sympy__sympy-13146/           # SWECAS-600: Logic
│   ├── sympy__sympy-13480/           # SWECAS-300: Type
│   ├── scikit-learn__sklearn-10297/  # SWECAS-400: API
│   ├── matplotlib__matplotlib-13989/ # SWECAS-700: Config
│   ├── pytest-dev__pytest-5103/      # SWECAS-900: Async
│   ├── cpython__cpython-9267/        # SWECAS-100: Null
│   ├── classify_tasks.py             # Auto-classify all tasks
│   └── swecas_task_mapping.json      # Classification results
│
├── benchmark/                        # A/B testing framework
│   ├── ab_runner.py                  # Compare FAST vs DEEP vs SWECAS+DEEP
│   └── results/                      # Benchmark reports
│
├── Makefile                          # Build/test targets
├── Dockerfile                        # Container build
├── docker-compose.yml                # Full stack deployment
├── requirements.txt                  # Python dependencies
└── .github/workflows/test.yml        # CI/CD pipeline
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
make test-all

# Run full test suite (62+ tests)
python -m pytest tests/ -v

# Classify SWE-bench tasks
make classify

# Run A/B benchmark
make benchmark

# Lint check
make lint
```

## SWECAS V2 Classification System

**SWECAS** (SWE-bench Category Alignment System) classifies bugs into 9 categories:

| Code | Category | Description | Example Task |
|------|----------|-------------|-------------|
| 100 | Null/None & Value | NoneType, AttributeError, missing values | cpython#9267 |
| 200 | Import & Module | ImportError, circular deps, wrong path | — |
| 300 | Type & Interface | TypeError, str/bytes confusion | requests#2317 |
| 400 | API & Deprecation | Deprecated methods, changed signatures | sklearn#10297 |
| 500 | Security & Validation | assert -> raise, input checking | flask#4045 |
| 600 | Logic & Control Flow | Wrong condition, off-by-one | django#11099 |
| 700 | Config & Environment | Path errors, env vars, fixtures | matplotlib#13989 |
| 800 | Performance & Resource | Memory leaks, N+1, slow loops | — |
| 900 | Async & Concurrency | Missing await, race conditions | pytest#5103 |

Each category includes:
- **Subcategories** (e.g., 510: Input validation, 511: Boundary check)
- **Cross-links** to related categories (diffuse thinking)
- **Diffuse prompts** (questions to ask when stuck)
- **Fix templates** for common patterns
- **Real-world examples** from solved tasks

See [SWECAS_TAXONOMY.md](SWECAS_TAXONOMY.md) for full taxonomy documentation.

## Execution Modes

| Mode | Activation | Pipeline |
|------|-----------|----------|
| **FAST** | Default | Direct problem solving |
| **DEEP** | `--deep` / `[DEEP]` | CLASSIFY -> DIFFUSE -> FOCUS -> FIX |
| **SEARCH** | `--search` / `[SEARCH]` | Web search with fallback chain |

### Search Fallback Chain

```
SearXNG (local) -> DuckDuckGo (web) -> SWECAS cache (offline)
```

Configured via `search_backend` ("auto" / "duckduckgo" / "searxng") and `searxng_url`.

## Docker Deployment

```bash
docker-compose up -d
# Services:
#   qwencode  -> http://localhost:5002
#   SearXNG   -> http://localhost:8888
#   Ollama    -> http://localhost:11434
```

## Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands |
| `read` | Read file content |
| `write` | Write file with syntax check (Python) |
| `edit` | Edit file with syntax rollback |
| `glob` | Find files by pattern |
| `grep` | Search file contents |
| `web_search` | DuckDuckGo search |
| `web_search_searxng` | SearXNG search |
| `git` | Git operations |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for adding new SWE-bench tasks and SWECAS patterns.

## API Reference

See [API.md](API.md) for public method documentation.
