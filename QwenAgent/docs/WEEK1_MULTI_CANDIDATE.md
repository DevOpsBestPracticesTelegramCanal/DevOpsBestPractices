# Week 1: Multi-Candidate Generation + Rule Validators

## Overview

The Multi-Candidate system generates 3 code variants with different temperatures,
validates each through a pipeline of rules, and selects the best.

**Impact:** pass@1 65% -> pass@3 80% (+15% improvement via diversity)

## Architecture

```
User Query ("Write a factorial function")
    |
    v
MultiCandidateGenerator
    |--- Candidate 1  (temp=0.2, seed=42)   conservative
    |--- Candidate 2  (temp=0.5, seed=137)  balanced
    |--- Candidate 3  (temp=0.8, seed=256)  creative
    |
    v
RuleRunner (7 in-process + 3 external validators)
    |--- ASTSyntaxRule          CRITICAL  wt=10.0
    |--- NoForbiddenImportsRule ERROR     wt=5.0
    |--- NoEvalExecRule         CRITICAL  wt=8.0
    |--- CodeLengthRule         ERROR     wt=2.0
    |--- ComplexityRule         WARNING   wt=1.5
    |--- DocstringRule          WARNING   wt=0.5
    |--- TypeHintRule           WARNING   wt=1.0
    |--- RuffValidator          WARNING   wt=2.0  (external)
    |--- MypyValidator          WARNING   wt=1.5  (external)
    |--- HadolintValidator      WARNING   wt=2.0  (external, Dockerfiles)
    |
    v
CandidateSelector
    |--- Weighted score = sum(rule.score * rule.weight) / sum(weights)
    |--- Penalty for critical errors
    |--- Best candidate selected
    v
PipelineResult { best, pool, timing, summary }
```

## Usage

### Automatic (via Orchestrator)

```python
from core.orchestrator import Orchestrator

orchestrator = Orchestrator(
    llm_client=my_client,
    enable_multi_candidate=True,
    multi_candidate_model="qwen2.5-coder:7b",
)

# Automatically uses Multi-Candidate for pure code generation tasks
result = orchestrator.process("Write a function to calculate fibonacci")
```

### Manual (Pipeline API)

```python
from core.generation import MultiCandidatePipeline, PipelineConfig, AsyncLLMAdapter

adapter = AsyncLLMAdapter(llm_client, model="qwen2.5-coder:7b")

pipeline = MultiCandidatePipeline(
    llm=adapter,
    config=PipelineConfig(n_candidates=3, parallel_generation=True),
)

result = await pipeline.run(
    task_id="task_1",
    query="Write a sorting algorithm",
)

print(f"Best code:\n{result.code}")
print(f"Score: {result.score:.4f}")
print(f"Passed all validators: {result.all_passed}")
print(f"Summary: {result.summary()}")
```

## Configuration

```python
@dataclass
class PipelineConfig:
    n_candidates: int = 3              # Number of variants to generate
    parallel_generation: bool = True   # Generate concurrently (faster)
    fail_fast_validation: bool = True  # Stop on first CRITICAL failure
```

## Validators

### In-Process (fast, < 10ms each)

| Rule | Severity | Weight | What it checks |
|------|----------|--------|----------------|
| ASTSyntaxRule | CRITICAL | 10.0 | Valid Python syntax (ast.parse) |
| NoForbiddenImportsRule | ERROR | 5.0 | No os/subprocess/socket/pickle |
| NoEvalExecRule | CRITICAL | 8.0 | No eval()/exec()/compile() |
| CodeLengthRule | ERROR | 2.0 | 1-500 lines (not empty, not huge) |
| ComplexityRule | WARNING | 1.5 | Cyclomatic complexity per function |
| DocstringRule | WARNING | 0.5 | Functions/classes have docstrings |
| TypeHintRule | WARNING | 1.0 | Return type annotations present |

### External (subprocess, ~1-3s each)

| Rule | Tool | Weight | Installation |
|------|------|--------|-------------|
| RuffValidator | `ruff check` | 2.0 | `pip install ruff` |
| MypyValidator | `mypy` | 1.5 | `pip install mypy` |
| HadolintValidator | `hadolint` | 2.0 | Download binary from GitHub |

External validators are **optional** — if the tool is not installed, the rule
passes with an INFO message and doesn't affect the score.

## Scoring

Each candidate gets a weighted score:

```
total_score = sum(rule_i.score * rule_i.weight) / sum(rule_i.weight)
```

Critical errors (AST syntax, eval/exec) apply a heavy penalty.
The candidate with the highest total_score is selected.

## Test Coverage

```
tests/generation/
    test_candidate.py          10 tests  (data model)
    test_multi_candidate.py    10 tests  (generator)
    test_pipeline.py           10 tests  (pipeline flow)
    test_llm_adapter.py         5 tests  (adapter)
    test_external_validators.py 16 tests (ruff/mypy/hadolint)
    test_e2e_pipeline.py       10 tests  (end-to-end)
tests/validators/
    test_rule_validators.py    35 tests  (all in-process rules)
```

## Files

```
core/generation/
    __init__.py                Exports
    candidate.py               Candidate, CandidatePool, ValidationScore
    multi_candidate.py         MultiCandidateGenerator
    selector.py                CandidateSelector
    pipeline.py                MultiCandidatePipeline
    llm_adapter.py             AsyncLLMAdapter

code_validator/rules/
    __init__.py                All rule exports
    base.py                    Rule, RuleResult, RuleRunner
    python_validators.py       7 in-process Python rules
    external_validators.py     3 external subprocess validators
```
