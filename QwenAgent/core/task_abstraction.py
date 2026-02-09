"""
Week 11: Task Abstraction Layer

Synthesizes all existing classification results (DUCS, SWECAS, AdaptiveStrategy,
ExecutionMode, code-gen detection) into a single TaskContext dataclass.

Does NOT replace any existing classifiers — it consumes their output and provides
a unified view for downstream consumers (pipeline, selector, validator).

Key benefits:
    - Single source of truth for task TYPE and RISK level
    - Validation profile selection (FAST_DEV → CRITICAL)
    - Stats tracking by task type
    - Pre-wires into _SimpleTask.type / _SimpleTask.risk_level
"""

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TaskType(Enum):
    """What kind of task the user is requesting."""
    COMMAND = "command"           # instant tool execution (read, ls, glob)
    CODE_GENERATION = "code_gen"  # write function/class/script
    BUG_FIX = "bug_fix"          # fix error/bug
    REFACTORING = "refactor"     # improve existing code
    EXPLANATION = "explain"      # explain code/concept
    SEARCH = "search"            # web search mode
    INFRASTRUCTURE = "infra"     # Kubernetes, Terraform, Helm, Ansible, YAML, Actions
    GENERAL = "general"          # general LLM query


class RiskLevel(Enum):
    """How risky the generated code could be."""
    LOW = "low"           # docs, comments, simple additions
    MEDIUM = "medium"     # standard code generation
    HIGH = "high"         # auth, database, API changes
    CRITICAL = "critical"  # security, crypto, production fixes


class ValidationProfile(Enum):
    """Which validation pipeline to use."""
    FAST_DEV = "fast_dev"     # minimal checks (~0.5s)
    BALANCED = "balanced"     # standard checks (~3s)
    SAFE_FIX = "safe_fix"    # thorough checks (~5-10s)
    CRITICAL = "critical"    # maximum checks (~10-30s)


@dataclass
class TaskContext:
    """Unified task classification — created once per request."""

    # Input
    query: str = ""
    timestamp: float = field(default_factory=time.time)

    # Core classification
    task_type: TaskType = TaskType.GENERAL
    risk_level: RiskLevel = RiskLevel.MEDIUM
    validation_profile: ValidationProfile = ValidationProfile.BALANCED

    # From DUCS classifier
    ducs_code: Optional[int] = None
    ducs_category: str = ""
    ducs_confidence: float = 0.0

    # From SWECAS classifier
    swecas_code: Optional[int] = None
    swecas_name: str = ""
    swecas_confidence: float = 0.0
    swecas_fix_hint: str = ""

    # From AdaptiveStrategy
    complexity: str = "MODERATE"  # TRIVIAL/SIMPLE/MODERATE/COMPLEX/CRITICAL

    # Derived flags
    is_code_generation: bool = False
    is_command: bool = False
    use_multi_candidate: bool = False
    use_deep_mode: bool = False

    # Validation control
    fail_fast: bool = False
    parallel_validation: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for SSE events and logging."""
        return {
            "query": self.query[:100],
            "task_type": self.task_type.value,
            "risk_level": self.risk_level.value,
            "validation_profile": self.validation_profile.value,
            "ducs_code": self.ducs_code,
            "ducs_category": self.ducs_category,
            "swecas_code": self.swecas_code,
            "swecas_name": self.swecas_name,
            "complexity": self.complexity,
            "is_code_generation": self.is_code_generation,
            "is_command": self.is_command,
            "use_multi_candidate": self.use_multi_candidate,
            "use_deep_mode": self.use_deep_mode,
            "fail_fast": self.fail_fast,
            "parallel_validation": self.parallel_validation,
            "timestamp": self.timestamp,
        }


# --- Compiled regex patterns for task type detection ---

_BUG_FIX_RE = re.compile(
    r'(?:\b(?:fix|bug|error|crash|failing|broken)\b'
    r'|(?:исправ|баг|ошибк|сломан|падает))',
    re.IGNORECASE,
)

_REFACTORING_RE = re.compile(
    r'(?:\b(?:refactor|restructure|clean\s*up|improve|simplify)\b'
    r'|(?:рефакторинг|упрост|улучш|реструктур|очист))',
    re.IGNORECASE,
)

_EXPLANATION_RE = re.compile(
    r'(?:\b(?:explain|what\s+is|how\s+does|why\s+does|describe)\b'
    r'|(?:объясн|что\s+тако|как\s+работ|почему|опиш))',
    re.IGNORECASE,
)

_INFRASTRUCTURE_RE = re.compile(
    r'(?:\b(?:kubernetes|k8s|terraform|helm|ansible|playbook|yaml|github\s*actions?|'
    r'dockerfile|docker[\-\s]compose|kustomize|argocd|flux|istio|'
    r'nginx\s+ingress|service\s+mesh|ci/?cd|pipeline|workflow|'
    r'shellcheck|bash\s+script|shell\s+script|helm\s+chart)\b'
    r'|(?:кубернет|терраформ|хельм|ансибл|плейбук|баш\s+скрипт))',
    re.IGNORECASE,
)

# Week 16: content type → DevOps rule names for validation
_DEVOPS_RULE_NAMES: Dict[str, List[str]] = {
    "kubernetes": ["yamllint", "kubeval", "kube-linter"],
    "terraform": ["tflint", "checkov"],
    "github_actions": ["yamllint", "actionlint"],
    "ansible": ["yamllint", "ansible-lint"],
    "helm": ["helm-lint"],
    "bash": ["shellcheck"],
    "docker_compose": ["yamllint", "docker-compose"],
    "yaml": ["yamllint"],
}

# SWECAS ranges for risk determination
_SECURITY_SWECAS_RANGE = range(500, 600)
_PERFORMANCE_SWECAS_RANGE = range(800, 900)

# All 8 default Python rules
_ALL_RULE_NAMES = [
    "ast_syntax",
    "no_forbidden_imports",
    "no_eval_exec",
    "code_length",
    "complexity",
    "docstring",
    "type_hints",
    "oss_patterns",
]

# Profile → validation config
_PROFILE_CONFIGS: Dict[ValidationProfile, Dict[str, Any]] = {
    ValidationProfile.FAST_DEV: {
        "rule_names": ["ast_syntax"],
        "fail_fast": False,
        "parallel": True,
    },
    ValidationProfile.BALANCED: {
        "rule_names": [
            "ast_syntax",
            "no_forbidden_imports",
            "no_eval_exec",
            "complexity",
            "oss_patterns",
        ],
        "fail_fast": False,
        "parallel": True,
    },
    ValidationProfile.SAFE_FIX: {
        "rule_names": list(_ALL_RULE_NAMES),
        "fail_fast": True,
        "parallel": True,
    },
    ValidationProfile.CRITICAL: {
        "rule_names": list(_ALL_RULE_NAMES),
        "fail_fast": True,
        "parallel": False,  # Sequential for maximum safety
    },
}


class TaskAbstraction:
    """
    Pure-logic classifier that synthesizes all existing classification results
    into a single TaskContext.

    No I/O, no LLM calls, no imports of heavy dependencies.
    Designed to be instantiated once and reused.
    """

    def classify(
        self,
        query: str,
        ducs_result: Optional[Dict[str, Any]] = None,
        swecas_result: Optional[Dict[str, Any]] = None,
        is_codegen: bool = False,
        is_command: bool = False,
        complexity: str = "MODERATE",
        execution_mode: Optional[Any] = None,
    ) -> TaskContext:
        """
        Create a TaskContext from all available classification signals.

        Args:
            query: Raw user input.
            ducs_result: Dict from DUCSClassifier.classify().
            swecas_result: Dict from SWECASClassifier.classify().
            is_codegen: Whether _is_code_generation_task() returned True.
            is_command: Whether the query was routed to a tool command.
            complexity: Complexity string from AdaptiveStrategy (TRIVIAL..CRITICAL).
            execution_mode: Current ExecutionMode (for SEARCH detection).

        Returns:
            TaskContext with all fields populated.
        """
        ducs_result = ducs_result or {}
        swecas_result = swecas_result or {}

        task_type = self._determine_task_type(
            query, is_codegen, is_command, execution_mode,
        )
        risk_level = self._determine_risk(
            task_type, swecas_result, complexity,
        )
        profile = self._determine_profile(
            task_type, risk_level, complexity,
        )

        # Extract DUCS fields
        ducs_code = None
        ducs_category = ""
        ducs_confidence = ducs_result.get("confidence", 0.0)
        if ducs_confidence >= 0.5:
            try:
                ducs_code = int(ducs_result.get("ducs_code", 0))
            except (ValueError, TypeError):
                pass
            ducs_category = ducs_result.get("category", "")

        # Extract SWECAS fields
        swecas_code = None
        swecas_name = ""
        swecas_confidence = swecas_result.get("confidence", 0.0)
        swecas_fix_hint = ""
        if swecas_confidence >= 0.5:
            try:
                swecas_code = int(swecas_result.get("swecas_code", 0))
            except (ValueError, TypeError):
                pass
            swecas_name = swecas_result.get("name", "")
            swecas_fix_hint = swecas_result.get("fix_hint", "")

        # Derive validation control from profile
        profile_cfg = _PROFILE_CONFIGS.get(profile, _PROFILE_CONFIGS[ValidationProfile.BALANCED])

        # Determine if deep mode should be used
        use_deep = False
        if execution_mode is not None:
            mode_val = getattr(execution_mode, "value", str(execution_mode))
            if "deep" in str(mode_val).lower():
                use_deep = True

        ctx = TaskContext(
            query=query,
            task_type=task_type,
            risk_level=risk_level,
            validation_profile=profile,
            ducs_code=ducs_code,
            ducs_category=ducs_category,
            ducs_confidence=ducs_confidence,
            swecas_code=swecas_code,
            swecas_name=swecas_name,
            swecas_confidence=swecas_confidence,
            swecas_fix_hint=swecas_fix_hint,
            complexity=complexity.upper(),
            is_code_generation=is_codegen,
            is_command=is_command,
            use_multi_candidate=is_codegen and task_type in (
                TaskType.CODE_GENERATION, TaskType.INFRASTRUCTURE,
            ),
            use_deep_mode=use_deep,
            fail_fast=profile_cfg["fail_fast"],
            parallel_validation=profile_cfg["parallel"],
        )
        return ctx

    # ------------------------------------------------------------------
    # Task type detection
    # ------------------------------------------------------------------

    def _determine_task_type(
        self,
        query: str,
        is_codegen: bool,
        is_command: bool,
        execution_mode: Optional[Any],
    ) -> TaskType:
        """
        Determine task type with priority order:
        COMMAND > SEARCH > CODE_GENERATION > BUG_FIX > REFACTORING > EXPLANATION > GENERAL
        """
        # Priority 1: Command (already routed by pattern router)
        if is_command:
            return TaskType.COMMAND

        # Priority 2: Search mode
        if execution_mode is not None:
            mode_val = str(getattr(execution_mode, "value", execution_mode)).lower()
            if "search" in mode_val:
                return TaskType.SEARCH

        # Priority 3: Code generation (detected by _is_code_generation_task)
        if is_codegen:
            return TaskType.CODE_GENERATION

        # Priority 4-6: Keyword-based detection
        if _BUG_FIX_RE.search(query):
            return TaskType.BUG_FIX

        if _REFACTORING_RE.search(query):
            return TaskType.REFACTORING

        if _EXPLANATION_RE.search(query):
            return TaskType.EXPLANATION

        # Priority 7: Infrastructure (Kubernetes, Terraform, Helm, etc.)
        if _INFRASTRUCTURE_RE.search(query):
            return TaskType.INFRASTRUCTURE

        # Default
        return TaskType.GENERAL

    # ------------------------------------------------------------------
    # Risk level determination
    # ------------------------------------------------------------------

    def _determine_risk(
        self,
        task_type: TaskType,
        swecas_result: Dict[str, Any],
        complexity: str,
    ) -> RiskLevel:
        """
        Determine risk level based on SWECAS, complexity, and task type.

        Priority:
        1. SWECAS 500-599 (Security) → CRITICAL
        2. complexity == CRITICAL → CRITICAL
        3. BUG_FIX + any SWECAS match → HIGH
        4. SWECAS 800-899 (Performance) → HIGH
        5. complexity == COMPLEX → HIGH
        6. COMMAND or EXPLANATION → LOW
        7. TRIVIAL/SIMPLE complexity + CODE_GEN → LOW
        8. Default → MEDIUM
        """
        complexity_upper = complexity.upper()

        # Extract SWECAS code
        swecas_code = None
        if swecas_result.get("confidence", 0) >= 0.5:
            try:
                swecas_code = int(swecas_result.get("swecas_code", 0))
            except (ValueError, TypeError):
                pass

        # Rule 1: Security SWECAS → CRITICAL
        if swecas_code is not None and swecas_code in _SECURITY_SWECAS_RANGE:
            return RiskLevel.CRITICAL

        # Rule 2: CRITICAL complexity → CRITICAL
        if complexity_upper == "CRITICAL":
            return RiskLevel.CRITICAL

        # Rule 3: BUG_FIX + SWECAS match → HIGH
        if task_type == TaskType.BUG_FIX and swecas_code is not None:
            return RiskLevel.HIGH

        # Rule 4: Performance SWECAS → HIGH
        if swecas_code is not None and swecas_code in _PERFORMANCE_SWECAS_RANGE:
            return RiskLevel.HIGH

        # Rule 5: COMPLEX complexity → HIGH
        if complexity_upper == "COMPLEX":
            return RiskLevel.HIGH

        # Rule 6: COMMAND or EXPLANATION → LOW
        if task_type in (TaskType.COMMAND, TaskType.EXPLANATION):
            return RiskLevel.LOW

        # Rule 7: TRIVIAL/SIMPLE + CODE_GEN → LOW
        if task_type == TaskType.CODE_GENERATION and complexity_upper in ("TRIVIAL", "SIMPLE"):
            return RiskLevel.LOW

        # Default
        return RiskLevel.MEDIUM

    # ------------------------------------------------------------------
    # Validation profile
    # ------------------------------------------------------------------

    def _determine_profile(
        self,
        task_type: TaskType,
        risk_level: RiskLevel,
        complexity: str,
    ) -> ValidationProfile:
        """Map risk level + task type to a validation profile."""
        # Risk CRITICAL → always CRITICAL profile
        if risk_level == RiskLevel.CRITICAL:
            return ValidationProfile.CRITICAL

        # Risk HIGH → SAFE_FIX
        if risk_level == RiskLevel.HIGH:
            return ValidationProfile.SAFE_FIX

        # COMMAND, EXPLANATION → FAST_DEV
        if task_type in (TaskType.COMMAND, TaskType.EXPLANATION):
            return ValidationProfile.FAST_DEV

        # TRIVIAL complexity → FAST_DEV
        if complexity.upper() == "TRIVIAL":
            return ValidationProfile.FAST_DEV

        # Default → BALANCED
        return ValidationProfile.BALANCED

    # ------------------------------------------------------------------
    # Config accessors (for downstream integration in Weeks 12-13)
    # ------------------------------------------------------------------

    @staticmethod
    def get_validation_config(profile: ValidationProfile) -> Dict[str, Any]:
        """Return validation config for a profile."""
        return dict(_PROFILE_CONFIGS.get(profile, _PROFILE_CONFIGS[ValidationProfile.BALANCED]))

    @staticmethod
    def get_scoring_weights(profile: ValidationProfile) -> Dict[str, float]:
        """
        Return custom scoring weights per profile.

        Returns a dict that can be passed to ScoringWeights(weights=...).
        """
        if profile == ValidationProfile.FAST_DEV:
            return {
                "ast_syntax": 10.0,
            }
        elif profile == ValidationProfile.CRITICAL:
            return {
                "ast_syntax": 10.0,
                "static_ruff": 4.0,
                "static_mypy": 3.0,
                "static_bandit": 6.0,  # Extra weight on security
                "complexity": 2.0,
                "style": 1.0,
                "docstring": 0.5,
                "oss_patterns": 1.0,
                "no_forbidden_imports": 5.0,
                "no_eval_exec": 5.0,
            }
        elif profile == ValidationProfile.SAFE_FIX:
            return {
                "ast_syntax": 10.0,
                "static_ruff": 3.0,
                "static_mypy": 2.5,
                "static_bandit": 5.0,
                "complexity": 2.0,
                "style": 1.0,
                "docstring": 0.5,
                "oss_patterns": 1.5,
                "no_forbidden_imports": 4.0,
                "no_eval_exec": 4.0,
            }
        else:
            # BALANCED — default weights
            return {
                "ast_syntax": 10.0,
                "static_ruff": 3.0,
                "static_mypy": 2.0,
                "static_bandit": 4.0,
                "complexity": 1.5,
                "style": 1.0,
                "docstring": 0.5,
                "oss_patterns": 1.5,
            }

    @staticmethod
    def get_validation_config_for_content(
        content_type: str,
        profile: ValidationProfile,
    ) -> Dict[str, Any]:
        """Return validation config adjusted for non-Python content types.

        For known DevOps content types (kubernetes, terraform, github_actions,
        yaml), returns the appropriate DevOps rule names.  For Python or
        unknown types, falls back to the standard profile config.
        """
        devops_names = _DEVOPS_RULE_NAMES.get(content_type)
        if devops_names is not None:
            base = dict(_PROFILE_CONFIGS.get(
                profile, _PROFILE_CONFIGS[ValidationProfile.BALANCED],
            ))
            base["rule_names"] = list(devops_names)
            return base
        # Fallback: standard Python rules
        return dict(_PROFILE_CONFIGS.get(
            profile, _PROFILE_CONFIGS[ValidationProfile.BALANCED],
        ))
