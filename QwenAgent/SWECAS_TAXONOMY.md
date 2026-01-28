# SWECAS V2 Taxonomy

**SWE-bench Category Alignment System** — keyword-based bug classifier with diffuse thinking cross-links.

Based on: IBM ODC (Orthogonal Defect Classification), Barbara Oakley diffuse thinking theory.

## Categories

### 100 — Null/None & Value Errors

**Keywords:** None, NoneType, AttributeError, null, not set, missing value, undefined, optional, uninitialized

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 110 | Missing None guard | `if x is None: raise ValueError` |
| 111 | Safe None access | `getattr(obj, 'attr', None)` |
| 120 | Uninitialized variable | Variable used before assignment |
| 130 | None return from function | Missing `return` gives implicit None |

**Diffuse links:** 300 (Type), 600 (Logic), 630 (Error handling), 920 (Race), 510 (Validation)

---

### 200 — Import & Module / Dependency

**Keywords:** import, module, circular, ModuleNotFoundError, ImportError, dependency, package

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 210 | Missing package | `pip install` needed |
| 220 | Circular import | `if TYPE_CHECKING:` guard |
| 230 | Wrong path | `sys.path.insert()` fix |

**Diffuse links:** 700 (Config), 400 (API version), 710 (Path), 720 (ENV)

---

### 300 — Type & Interface

**Keywords:** TypeError, type, signature, return type, cast, incompatible, type mismatch, annotation

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 310 | Signature mismatch | Wrong param types |
| 320 | String/bytes confusion | `encode()`/`decode()` |
| 330 | Container type error | `list()`, `dict()` conversion |
| 340 | Numeric type coercion | `int()`, `float()` conversion |

**Diffuse links:** 100 (None), 400 (API), 340 (Casting), 640 (Algorithm)

---

### 400 — API Usage & Deprecation

**Keywords:** deprecated, DeprecationWarning, API, version, breaking change, backward, removed in

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 410 | Removed API | Replace with modern equivalent |
| 420 | Changed signature | Update call parameters |
| 430 | Renamed module/symbol | Update import path |

**Diffuse links:** 200 (Import), 300 (Signature), 700 (Config), 630 (Error handling)

---

### 500 — Security & Validation

**Keywords:** validation, security, assert, ValueError, sanitize, validate, check, verify, raise

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 510 | Input validation (assert -> raise) | Replace `assert` with `raise ValueError` |
| 511 | Boundary check | Range/length validation |
| 520 | Format validation | Regex pattern matching |
| 530 | Sanitization | Escape user input |

**Diffuse links:** 100 (Input check), 600 (Logic), 632 (Broad except), 731 (Config)

---

### 600 — Logic & Control Flow

**Keywords:** logic, condition, if/else, control flow, off-by-one, wrong branch, algorithm, predicate

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 610 | Inverted condition | `if not x` vs `if x` |
| 611 | Wrong compound condition | AND/OR confusion |
| 620 | Off-by-one / boundary | `range(n)` vs `range(n+1)` |
| 630 | Error handling logic | Catch specific exceptions |

**Diffuse links:** 100 (Boundary), 500 (Validation), 130 (Off-by-one), 420 (API)

---

### 700 — Config & Environment

**Keywords:** config, environment, path, env var, settings, configuration, fixture

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 710 | Path handling | `pathlib.Path()`, `os.path.join()` |
| 720 | Environment variable | `os.environ.get()` |
| 730 | Config file parsing | YAML/JSON/INI parsing |
| 740 | Test fixture config | `conftest.py`, `pytest.fixture` |

**Diffuse links:** 200 (Import), 720 (ENV), 400 (Version), 740 (Test config)

---

### 800 — Performance & Resource

**Keywords:** performance, slow, memory, leak, N+1, optimize, resource, bottleneck, cache

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 810 | Algorithm complexity | O(n^2) -> O(n log n) |
| 820 | I/O bottleneck | Batch reads, pooling |
| 830 | Memory leak | `weakref`, `gc.collect()` |
| 840 | Cache optimization | `@lru_cache`, memoize |

**Diffuse links:** 600 (Algorithm), 900 (Async), 820 (I/O), 621 (Loop)

---

### 900 — Async, Concurrency & I/O

**Keywords:** async, await, race condition, deadlock, concurrent, threading, coroutine, lock

**Subcategories:**
| Code | Name | Pattern |
|------|------|---------|
| 910 | Missing await | `await coro()` |
| 911 | Resource cleanup timing | `async with` context manager |
| 920 | Race condition | Lock protection |
| 930 | Deadlock | Lock ordering, timeouts |

**Diffuse links:** 600 (Control flow), 800 (Resource), 930 (Locking), 911 (Await), 832 (Leak)

---

## Cross-Category Patterns

| Pattern | Description | Categories |
|---------|-------------|------------|
| guard_missing | Something should be checked before use | 110, 511, 441, 911 |
| contract_violation | Caller/callee disagree on interface | 310, 421, 331, 321 |
| environment_assumption | Code assumes non-guaranteed runtime state | 711, 720, 740, 912 |
| silent_failure | Error swallowed or ignored | 631, 100, 241, 632 |
| temporal_ordering | Something happens at wrong time | 140, 232, 921, 931 |
