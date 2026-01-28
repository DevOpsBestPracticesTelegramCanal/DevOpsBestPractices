# QwenAgent API Reference

## SWECASClassifier

**Module:** `core.swecas_classifier`

### `SWECASClassifier()`

Keyword-based bug classifier for SWECAS V2 categories.

#### `classify(description: str, file_content: str = None) -> dict`

Classify a bug description into a SWECAS category.

**Parameters:**
- `description` — Bug/issue description text
- `file_content` — Optional source code for context

**Returns:** dict with keys:
- `swecas_code` (int) — Category code (100-900) or 0 if unclassified
- `confidence` (float) — 0.0 to 1.0
- `subcategory` (int) — Subcategory code
- `name` (str) — Category name
- `pattern_description` (str) — Matched keywords
- `fix_hint` (str) — Suggested fix approach
- `related` (list[int]) — Cross-linked category codes
- `diffuse_insights` (str) — Cross-category analysis
- `diffuse_prompts` (list[str]) — Questions for diffuse thinking

#### `get_diffuse_links(swecas_code: int) -> list[int]`

Get cross-category links for diffuse exploration.

#### `get_diffuse_prompts(swecas_code: int) -> list[str]`

Get diffuse thinking prompts for a category.

#### `get_fix_template(subcategory: int) -> str | None`

Get code fix template for a subcategory.

#### `get_cross_patterns(swecas_code: int) -> list[dict]`

Find cross-category patterns relevant to this code.

---

## CoTEngine

**Module:** `core.cot_engine`

### `CoTEngine()`

Chain-of-Thought reasoning engine.

#### `enable_deep_mode(enabled: bool = True)`

Enable/disable deep thinking mode.

#### `create_thinking_prompt(task: str, context: dict = None, ducs_context: dict = None, swecas_context: dict = None) -> str`

Create structured thinking prompt. In FAST mode returns task as-is. In DEEP mode with SWECAS context, generates CLASSIFY -> DIFFUSE -> FOCUS -> FIX pipeline.

#### `parse_cot_response(response: str) -> list[CoTStep]`

Parse Chain-of-Thought steps from LLM response.

---

## ExtendedTools

**Module:** `core.tools_extended`

### Static Methods

#### `write(path: str, content: str) -> dict`

Write file with Python syntax validation. Returns `{"success": bool, "syntax_error": bool}`.

#### `edit(path: str, old_string: str, new_string: str) -> dict`

Edit file with syntax rollback. Rejects edits that would break Python syntax.

#### `web_search(query: str, num_results: int = 5) -> dict`

Search via DuckDuckGo HTML scraping. Returns `{"success": bool, "results": list, "source": "duckduckgo"}`.

#### `web_search_searxng(query: str, num_results: int = 5, searxng_url: str = "http://localhost:8888") -> dict`

Search via local SearXNG JSON API. Returns `{"success": bool, "results": list, "source": "searxng"}`. Graceful fallback on connection failure.

---

## QwenCodeConfig

**Module:** `core.qwencode_agent`

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ollama_url` | str | `http://localhost:11434` | Ollama API URL |
| `model` | str | `qwen2.5-coder:32b` | Model name |
| `max_iterations` | int | 10 | Max agent iterations |
| `timeout` | int | 120 | Request timeout (seconds) |
| `deep_mode` | bool | False | Enable DEEP mode |
| `search_backend` | str | `"auto"` | `"auto"` / `"duckduckgo"` / `"searxng"` |
| `searxng_url` | str | `http://localhost:8888` | SearXNG instance URL |
| `auto_escalation` | bool | True | Auto-escalate on timeout |

---

## ABRunner

**Module:** `benchmark.ab_runner`

### `ABRunner(tasks_dir=None, results_dir=None)`

A/B benchmark runner for comparing execution modes.

#### `run_task(task_name: str, mode: str = "fast") -> dict`

Run a single task and return results.

#### `run_all(modes: list = None, tasks: list = None) -> list`

Run all tasks in all modes.

#### `generate_report(results: list) -> str`

Generate markdown comparison report.

#### `save_results(results: list)`

Save results to JSON + markdown.

---

## classify_tasks

**Module:** `swebench_tasks.classify_tasks`

### `classify_all_tasks() -> dict`

Scan all `swebench_tasks/*/` directories, classify each by SWECAS category, save mapping to `swecas_task_mapping.json`.
