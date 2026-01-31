# -*- coding: utf-8 -*-
"""
SWECAS V2 Classifier for QwenCode DEEP MODE
SWE-bench Category Alignment System with Barbara Oakley diffuse thinking

Categories (100-900):
- 100: Null/None & Value Errors
- 200: Import & Module / Dependency
- 300: Type & Interface
- 400: API Usage & Deprecation
- 500: Security & Validation
- 600: Logic & Control Flow
- 700: Config & Environment
- 800: Performance & Resource
- 900: Async, Concurrency & I/O

Based on: SWECAS V2, ODC (IBM), Barbara Oakley diffuse thinking theory.
"""

import re
from typing import Dict, Any, List, Optional


class SWECASClassifier:
    """
    Keyword-based SWECAS V2 classifier for SWE-bench bug descriptions.
    No ML needed — pattern matching + diffuse cross-links.
    """

    # =========================================================================
    # CATEGORY KEYWORDS (focused mode: sequential pattern matching)
    # =========================================================================

    CATEGORY_KEYWORDS: Dict[int, List[str]] = {
        100: [
            "None", "NoneType", "AttributeError", "null", "not set",
            "missing value", "has no attribute", "undefined", "null pointer",
            "optional", "uninitialized"
        ],
        200: [
            # STRICT keywords only - "import", "module", "package" are too generic!
            "ModuleNotFoundError", "ImportError", "No module named",
            "cannot import", "circular import", "relative import",
            "failed to import", "import error", "missing module",
            "dependency not found", "package not installed"
        ],
        300: [
            "TypeError", "type error", "signature", "return type", "cast",
            "incompatible", "expected.*got", "type mismatch", "annotation",
            "overload", "generic", "subclass", "isinstance", "type check"
        ],
        400: [
            "deprecated", "DeprecationWarning", "API", "version", "breaking change",
            "backward", "removed in", "use.*instead", "legacy", "obsolete",
            "compatibility"
        ],
        500: [
            "validation", "security", "assert", "input check", "ValueError",
            "sanitize", "validate", "verify", "raise.*Error",
            "should raise", "must raise", "invalid", "not valid",
            "validation error", "constraint", "bounds check"
        ],
        600: [
            "logic", "condition", "if/else", "control flow", "off-by-one",
            "wrong branch", "incorrect result", "wrong behavior", "algorithm",
            "predicate", "loop", "bug", "wrong", "incorrect", "broken",
            "fails", "doesn't work", "not working", "unexpected"
        ],
        700: [
            "config", "environment", "env var", "settings",
            "configuration", "ENV", "working directory", "fixture",
            "framework setting", "import-mode", "import mode",
            "test config", "pytest config", "conftest"
        ],
        800: [
            "performance", "slow", "memory", "leak", "N+1", "optimize",
            "resource", "bottleneck", "profiling", "cache"
        ],
        900: [
            "async", "await", "race condition", "deadlock", "concurrent",
            "threading", "coroutine", "lock", "synchronization", "I/O"
        ]
    }

    # =========================================================================
    # CATEGORY NAMES
    # =========================================================================

    CATEGORY_NAMES: Dict[int, str] = {
        100: "Null/None & Value Errors",
        200: "Import & Module / Dependency",
        300: "Type & Interface",
        400: "API Usage & Deprecation",
        500: "Security & Validation",
        600: "Logic & Control Flow",
        700: "Config & Environment",
        800: "Performance & Resource",
        900: "Async, Concurrency & I/O"
    }

    # =========================================================================
    # DIFFUSE LINKS (cross-category connections from Oakley theory)
    # When focused classification leads to dead end, follow these links
    # =========================================================================

    DIFFUSE_LINKS: Dict[int, List[int]] = {
        100: [300, 600, 630, 920, 510],   # Null -> Type, Logic, Error handling, Race, Validation
        200: [700, 400, 710, 720],          # Import -> Config, API version, Path, ENV
        300: [100, 400, 340, 640],          # Type -> None, API signature, Casting, Algorithm
        400: [200, 300, 700, 630],          # API -> Import, Signature, Config, Error handling
        500: [100, 600, 510, 632, 731],     # Security -> Input check, Logic, Validation, Broad except, Config
        600: [100, 500, 630, 130, 420],     # Logic -> Boundary, Validation, Error handling, Off-by-one, API
        700: [200, 720, 400, 740],          # Config -> Import, ENV, Version, Test config
        800: [600, 900, 820, 621],          # Performance -> Algorithm, Async, I/O, Loop
        900: [600, 800, 930, 911, 832]      # Async -> Control flow, Resource, Locking, Await, Leak
    }

    # =========================================================================
    # DIFFUSE PROMPTS (questions to ask when stuck — triggers mode switch)
    # =========================================================================

    DIFFUSE_PROMPTS: Dict[int, List[str]] = {
        100: [
            "Is the None a SYMPTOM? What SHOULD have set this value?",
            "Was an exception silently caught, leaving the variable as None?",
            "Did an API change make this return None where it used to return a value?",
            "Is this a race condition? Does another thread/task set this value?",
            "Could a failed import leave the module as None at runtime?"
        ],
        200: [
            "Is this really an import problem, or is the PATH/ENV misconfigured?",
            "Did the package version change and rename this symbol?",
            "Is there a circular dependency hiding behind this error?",
            "Could this import only fail in certain environments (test vs prod)?"
        ],
        300: [
            "Is this a type error or an API change? Did the library update?",
            "Is the wrong type coming from a computation bug upstream?",
            "Could this be a string/bytes confusion in I/O?",
            "Is the caller wrong, or is the callee returning the wrong type?"
        ],
        400: [
            "Is this really deprecated, or is it the wrong version entirely?",
            "Could the fix break backward compatibility with older versions?",
            "Does this deprecation cascade to other API calls in the same module?",
            "Is the real problem a missing version guard, not the API call itself?"
        ],
        500: [
            "Is this a missing check, or is the check present but in the wrong place?",
            "Could the exception handling be masking a security issue?",
            "Is the real problem in framework configuration, not code?",
            "Does fixing this validation break legitimate use cases?"
        ],
        600: [
            "Is this really a LOGIC error, or does the DATA coming in look different than expected?",
            "Could the algorithm be correct but the API changed its behavior?",
            "Is the test environment different from production?",
            "Is the 'wrong' result actually an edge case you didn't consider?",
            "OAKLEY: Stop staring at the code. Walk away. Let diffuse mode find the pattern."
        ],
        700: [
            "Does this work on your machine but fail in CI?",
            "Is this a configuration problem or a code problem?",
            "Could the test fixture be polluted from a previous test?",
            "Is the default value sensible, or was it meant to be overridden?"
        ],
        800: [
            "Is this truly a performance issue, or is the algorithm wrong?",
            "Could the slowness be caused by lock contention?",
            "Is the N+1 pattern a symptom of missing eager loading CONFIG?",
            "OAKLEY: Profile first, hypothesize second. Don't guess at bottlenecks."
        ],
        900: [
            "Is this bug reproducible? If not, it's probably timing-dependent.",
            "Could the 'random' failure be a missing await?",
            "Is the resource cleanup happening before the async task completes?",
            "Is this concurrency, or is it just a logic error that appears random?",
            "OAKLEY: Concurrency bugs require the MOST diffuse thinking. Step back. Draw the timeline."
        ]
    }

    # =========================================================================
    # CROSS-CATEGORY PATTERNS (meta-patterns that span multiple categories)
    # =========================================================================

    CROSS_PATTERNS: Dict[str, Dict[str, Any]] = {
        "guard_missing": {
            "description": "Something should be checked/validated before use, but isn't",
            "instances": [110, 511, 441, 911],
            "insight": "If you see a missing guard in ANY category, scan all other guard patterns too"
        },
        "contract_violation": {
            "description": "Caller and callee disagree on interface/behavior",
            "instances": [310, 421, 331, 321],
            "insight": "Who is wrong — the caller or the callee? Check both sides"
        },
        "environment_assumption": {
            "description": "Code assumes something about the runtime that isn't guaranteed",
            "instances": [711, 720, 740, 912],
            "insight": "Does this work EVERYWHERE, or just on your machine?"
        },
        "silent_failure": {
            "description": "Error occurs but is not visible — swallowed, logged, or ignored",
            "instances": [631, 100, 241, 632],
            "insight": "The bug you see might be the CONSEQUENCE. The real bug is the silent failure upstream"
        },
        "temporal_ordering": {
            "description": "Something happens at the wrong time — too early, too late, or out of order",
            "instances": [140, 232, 921, 931],
            "insight": "Draw a timeline. When does each thing happen? Is the order guaranteed?"
        }
    }

    # =========================================================================
    # FIX TEMPLATES (code templates for common subcategories)
    # =========================================================================

    FIX_TEMPLATES: Dict[int, str] = {
        # 500 - Validation
        510: (
            "if not isinstance({param}, {expected_type}):\n"
            "    raise {exception}(\"{error_message}\")"
        ),
        511: (
            "if {condition}:\n"
            "    raise ValueError(\"{error_message}\")"
        ),
        # 600 - Logic / Error handling
        630: (
            "try:\n"
            "    {code}\n"
            "except {exception} as e:\n"
            "    raise {new_exception}(str(e))"
        ),
        611: (
            "if {correct_condition}:  # was: {wrong_condition}\n"
            "    {action}"
        ),
        # 100 - Null guards
        110: (
            "if {variable} is None:\n"
            "    raise ValueError(\"{variable} must not be None\")\n"
            "{original_code}"
        ),
        111: (
            "if {variable} is not None:\n"
            "    {access_code}\n"
            "else:\n"
            "    {fallback}"
        ),
        # 200 - Import fixes
        210: (
            "try:\n"
            "    from {module} import {name}\n"
            "except ImportError:\n"
            "    {fallback}"
        ),
        # 400 - API deprecation
        410: (
            "# Updated from deprecated {old_api} to {new_api}\n"
            "{new_api_call}"
        ),
        # 700 - Config
        710: (
            "import os\n"
            "{variable} = os.environ.get(\"{env_name}\", {default})"
        ),
        # 900 - Async
        911: (
            "result = await {coroutine}  # was missing await"
        ),
    }

    # =========================================================================
    # SPECIFIC PATTERN MATCHERS (regex-based for high confidence)
    # =========================================================================

    SPECIFIC_PATTERNS: Dict[int, List[tuple]] = {
        # (regex, subcategory, confidence_boost, fix_hint)
        500: [
            (r"assert\s+\w+.*,\s*['\"]", 510, 0.15,
             "Replace assert with explicit raise ValueError (assert can be disabled with -O)"),
            (r"assert\s+['\"]?\.", 510, 0.15,
             "Replace assert with explicit raise ValueError for name validation"),
            (r"raise\s+ValueError", 511, 0.10,
             "Existing ValueError — check if validation is in the right place"),
        ],
        600: [
            (r"if\s+.*(?:and|or)\s+", 611, 0.05,
             "Check compound condition for logic error"),
            (r"for\s+.*range\(len\(", 621, 0.05,
             "Consider using enumerate() or direct iteration"),
        ],
        100: [
            (r"\.(\w+)\s*(?:is|==)\s*None", 110, 0.10,
             "Add explicit None check before attribute access"),
        ]
    }

    def __init__(self):
        # Pre-compile regex patterns for specific matchers
        self._compiled_patterns: Dict[int, List[tuple]] = {}
        for cat, patterns in self.SPECIFIC_PATTERNS.items():
            self._compiled_patterns[cat] = [
                (re.compile(p[0], re.IGNORECASE | re.MULTILINE), p[1], p[2], p[3])
                for p in patterns
            ]

    def classify(self, description: str, file_content: str = None) -> Dict[str, Any]:
        """
        Classify a bug description into SWECAS V2 category.

        Args:
            description: Issue/bug description text
            file_content: Optional source code snippet for context

        Returns:
            dict with: swecas_code, confidence, subcategory, name,
                        pattern_description, fix_hint, related,
                        diffuse_insights, diffuse_prompts
        """
        text = description.lower()
        if file_content:
            text += "\n" + file_content.lower()

        # Score each category
        scores: Dict[int, float] = {}
        matched_keywords: Dict[int, List[str]] = {}

        for cat, keywords in self.CATEGORY_KEYWORDS.items():
            score = 0.0
            matches = []
            for kw in keywords:
                pattern = re.compile(re.escape(kw), re.IGNORECASE)
                found = pattern.findall(text)
                if found:
                    score += len(found) * 0.1
                    matches.append(kw)

            if matches:
                scores[cat] = min(score, 1.0)  # cap at 1.0
                matched_keywords[cat] = matches

        if not scores:
            return {
                "swecas_code": 0,
                "confidence": 0.0,
                "subcategory": 0,
                "name": "Unclassified",
                "pattern_description": "",
                "fix_hint": "",
                "related": [],
                "diffuse_insights": "",
                "diffuse_prompts": []
            }

        # Pick top category
        best_cat = max(scores, key=scores.get)
        base_confidence = scores[best_cat]

        # Refine with specific patterns
        subcategory = best_cat
        fix_hint = ""
        if best_cat in self._compiled_patterns and file_content:
            for regex, subcat, boost, hint in self._compiled_patterns[best_cat]:
                if regex.search(file_content):
                    subcategory = subcat
                    base_confidence = min(base_confidence + boost, 1.0)
                    fix_hint = hint
                    break

        # Also check specific patterns against description
        if not fix_hint and best_cat in self._compiled_patterns:
            for regex, subcat, boost, hint in self._compiled_patterns[best_cat]:
                if regex.search(description):
                    subcategory = subcat
                    base_confidence = min(base_confidence + boost, 1.0)
                    fix_hint = hint
                    break

        # Build diffuse insights from cross-links
        related = self.get_diffuse_links(best_cat)
        diffuse_insights = self._build_diffuse_insights(best_cat)
        diffuse_prompts = self.get_diffuse_prompts(best_cat)

        return {
            "swecas_code": best_cat,
            "confidence": round(base_confidence, 2),
            "subcategory": subcategory,
            "name": self.CATEGORY_NAMES.get(best_cat, "Unknown"),
            "pattern_description": f"Matched keywords: {', '.join(matched_keywords.get(best_cat, []))}",
            "fix_hint": fix_hint,
            "related": related,
            "diffuse_insights": diffuse_insights,
            "diffuse_prompts": diffuse_prompts
        }

    def get_diffuse_links(self, swecas_code: int) -> List[int]:
        """Get cross-category links for diffuse exploration"""
        return self.DIFFUSE_LINKS.get(swecas_code, [])

    def get_diffuse_prompts(self, swecas_code: int) -> List[str]:
        """Get diffuse thinking prompts for a category"""
        return self.DIFFUSE_PROMPTS.get(swecas_code, [])

    def get_fix_template(self, subcategory: int) -> Optional[str]:
        """Get fix template for a subcategory code"""
        return self.FIX_TEMPLATES.get(subcategory)

    def get_cross_patterns(self, swecas_code: int) -> List[Dict[str, Any]]:
        """Find cross-category patterns relevant to this code"""
        relevant = []
        for name, pattern in self.CROSS_PATTERNS.items():
            if any(inst // 100 == swecas_code // 100 or inst == swecas_code
                   for inst in pattern["instances"]):
                relevant.append({
                    "name": name,
                    "description": pattern["description"],
                    "insight": pattern["insight"]
                })
        return relevant

    def _build_diffuse_insights(self, swecas_code: int) -> str:
        """Build diffuse thinking context string"""
        parts = []

        # Cross-category links
        links = self.get_diffuse_links(swecas_code)
        if links:
            link_names = []
            for link in links:
                cat = (link // 100) * 100
                name = self.CATEGORY_NAMES.get(cat, f"SWECAS-{cat}")
                link_names.append(f"SWECAS-{link} ({name})")
            parts.append(f"Cross-links: {', '.join(link_names)}")

        # Cross-category patterns
        cross = self.get_cross_patterns(swecas_code)
        if cross:
            for cp in cross:
                parts.append(f"Pattern '{cp['name']}': {cp['insight']}")

        return "\n".join(parts) if parts else ""
