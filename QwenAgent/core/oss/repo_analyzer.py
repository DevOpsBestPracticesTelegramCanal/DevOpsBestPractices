# -*- coding: utf-8 -*-
"""
RepoAnalyzer — extracts architectural patterns from repository data.

Detects: frameworks, testing tools, CI/CD, Docker, linting, packaging,
database ORMs, architecture style, and license from README + deps + file tree.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RepoPattern:
    """A single detected pattern in a repository."""
    repo_name: str
    category: str          # framework, testing, ci_cd, docker, linting, packaging, database, architecture, license
    pattern_name: str      # e.g. "flask", "pytest", "github_actions"
    confidence: float = 1.0
    evidence: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------

# Maps: pattern_name → (pip_package_names, readme_keywords)
_FRAMEWORK_RULES: Dict[str, Tuple[List[str], List[str]]] = {
    "flask":    (["flask"], ["flask"]),
    "django":   (["django"], ["django"]),
    "fastapi":  (["fastapi"], ["fastapi"]),
    "tornado":  (["tornado"], ["tornado"]),
    "aiohttp":  (["aiohttp"], ["aiohttp"]),
    "starlette": (["starlette"], ["starlette"]),
    "sanic":    (["sanic"], ["sanic"]),
    "bottle":   (["bottle"], ["bottle"]),
    "pyramid":  (["pyramid"], ["pyramid"]),
    "falcon":   (["falcon"], ["falcon"]),
    "quart":    (["quart"], ["quart"]),
    "litestar": (["litestar"], ["litestar"]),
    "streamlit": (["streamlit"], ["streamlit"]),
    "gradio":   (["gradio"], ["gradio"]),
    "click":    (["click"], ["click cli"]),
    "typer":    (["typer"], ["typer"]),
    "rich":     (["rich"], []),
    "celery":   (["celery"], ["celery"]),
    "huggingface_transformers": (["transformers"], ["hugging face", "transformers"]),
    "pytorch":  (["torch", "pytorch"], ["pytorch"]),
    "tensorflow": (["tensorflow"], ["tensorflow"]),
    "scikit_learn": (["scikit-learn", "sklearn"], ["scikit-learn"]),
    "numpy":    (["numpy"], []),
    "pandas":   (["pandas"], []),
    "scipy":    (["scipy"], []),
    "pydantic": (["pydantic"], ["pydantic"]),
    "sqlalchemy": (["sqlalchemy"], ["sqlalchemy"]),
    "requests": (["requests"], []),
    "httpx":    (["httpx"], ["httpx"]),
}

_TESTING_RULES: Dict[str, Tuple[List[str], List[str]]] = {
    "pytest":     (["pytest"], ["pytest"]),
    "unittest":   ([], ["unittest"]),
    "tox":        (["tox"], ["tox"]),
    "nox":        (["nox"], ["nox"]),
    "hypothesis": (["hypothesis"], ["hypothesis"]),
    "coverage":   (["coverage", "pytest-cov"], ["coverage"]),
    "mock":       (["mock", "pytest-mock"], []),
    "factory_boy": (["factory-boy"], ["factory"]),
}

_LINTING_RULES: Dict[str, Tuple[List[str], List[str]]] = {
    "black":   (["black"], ["black"]),
    "ruff":    (["ruff"], ["ruff"]),
    "flake8":  (["flake8"], ["flake8"]),
    "pylint":  (["pylint"], ["pylint"]),
    "isort":   (["isort"], ["isort"]),
    "bandit":  (["bandit"], ["bandit"]),
    "mypy":    (["mypy"], ["mypy"]),
    "pyright": (["pyright"], ["pyright"]),
    "autopep8": (["autopep8"], []),
    "yapf":    (["yapf"], []),
    "pre_commit": (["pre-commit"], ["pre-commit"]),
}

_PACKAGING_RULES: Dict[str, Tuple[List[str], List[str]]] = {
    "setuptools": (["setuptools"], []),
    "poetry":     (["poetry"], ["poetry"]),
    "flit":       (["flit"], ["flit"]),
    "hatch":      (["hatch", "hatchling"], ["hatch"]),
    "pdm":        (["pdm"], ["pdm"]),
    "maturin":    (["maturin"], ["maturin"]),
    "pip_tools":  (["pip-tools"], ["pip-tools"]),
}

_DATABASE_RULES: Dict[str, Tuple[List[str], List[str]]] = {
    "sqlalchemy":    (["sqlalchemy"], ["sqlalchemy"]),
    "django_orm":    (["django"], ["django.db", "models.Model"]),
    "peewee":        (["peewee"], ["peewee"]),
    "tortoise_orm":  (["tortoise-orm"], ["tortoise"]),
    "sqlmodel":      (["sqlmodel"], ["sqlmodel"]),
    "alembic":       (["alembic"], ["alembic"]),
    "redis":         (["redis"], ["redis"]),
    "pymongo":       (["pymongo"], ["mongodb", "pymongo"]),
    "motor":         (["motor"], ["motor"]),
    "psycopg2":      (["psycopg2", "psycopg2-binary"], ["postgresql"]),
    "asyncpg":       (["asyncpg"], ["asyncpg"]),
    "aiosqlite":     (["aiosqlite"], []),
    "elasticsearch": (["elasticsearch"], ["elasticsearch"]),
}

# CI/CD config file patterns
_CI_PATTERNS: Dict[str, List[str]] = {
    "github_actions": [".github/workflows/"],
    "travis":         [".travis.yml"],
    "circleci":       [".circleci/"],
    "jenkins":        ["Jenkinsfile"],
    "gitlab_ci":      [".gitlab-ci.yml"],
    "azure_pipelines": ["azure-pipelines.yml"],
    "bitbucket":      ["bitbucket-pipelines.yml"],
    "tox_ci":         ["tox.ini"],
    "makefile":       ["Makefile"],
}

# Architecture heuristics based on file tree
_ARCH_SIGNALS: Dict[str, List[str]] = {
    "microservice":  ["docker-compose", "services/", "api/", "gateway/"],
    "monorepo":      ["packages/", "libs/", "modules/"],
    "cli":           ["cli.py", "main.py", "__main__.py", "console_scripts"],
    "library":       ["src/", "setup.py", "pyproject.toml"],
    "web_app":       ["templates/", "static/", "views/", "routes/"],
    "data_science":  ["notebooks/", ".ipynb", "data/"],
    "ml_project":    ["model/", "train.py", "predict.py", "weights/"],
}


# ---------------------------------------------------------------------------
# RepoAnalyzer
# ---------------------------------------------------------------------------

class RepoAnalyzer:
    """Extract structured patterns from repository metadata."""

    def analyze(
        self,
        repo_name: str,
        readme: str = "",
        file_tree: Optional[List[str]] = None,
        requirements: str = "",
        setup_cfg: str = "",
        pyproject: str = "",
        dockerfile: str = "",
        ci_configs: Optional[List[str]] = None,
        license_name: str = "",
    ) -> List[RepoPattern]:
        """Run all detectors and return a list of patterns."""
        file_tree = file_tree or []
        ci_configs = ci_configs or []
        readme_lower = readme.lower()
        tree_str = "\n".join(file_tree).lower()

        deps = self._extract_dep_names(requirements, setup_cfg, pyproject)

        patterns: List[RepoPattern] = []

        # 1. Frameworks
        patterns.extend(self._detect_from_rules(
            repo_name, "framework", _FRAMEWORK_RULES, deps, readme_lower
        ))

        # 2. Testing
        patterns.extend(self._detect_from_rules(
            repo_name, "testing", _TESTING_RULES, deps, readme_lower
        ))
        # unittest via file tree
        if any("test" in f for f in file_tree) and not any(p.pattern_name == "pytest" for p in patterns):
            if "unittest" in readme_lower or "unittest" in requirements.lower():
                pass  # already detected
            elif any("test_" in f or "tests/" in f for f in file_tree):
                patterns.append(RepoPattern(
                    repo_name=repo_name, category="testing",
                    pattern_name="has_tests", confidence=0.7,
                    evidence="Found test files in tree",
                ))

        # 3. Linting
        patterns.extend(self._detect_from_rules(
            repo_name, "linting", _LINTING_RULES, deps, readme_lower
        ))
        # pyproject.toml linting sections
        if pyproject:
            for tool in ("black", "ruff", "isort", "mypy", "flake8", "pylint"):
                if f"[tool.{tool}]" in pyproject and not any(
                    p.pattern_name == tool and p.category == "linting" for p in patterns
                ):
                    patterns.append(RepoPattern(
                        repo_name=repo_name, category="linting",
                        pattern_name=tool, confidence=0.9,
                        evidence=f"Found [tool.{tool}] in pyproject.toml",
                    ))

        # 4. Packaging
        patterns.extend(self._detect_from_rules(
            repo_name, "packaging", _PACKAGING_RULES, deps, readme_lower
        ))
        # Detect from pyproject.toml build-system
        if pyproject:
            if "poetry" in pyproject.lower():
                self._ensure_pattern(patterns, repo_name, "packaging", "poetry",
                                     0.95, "poetry detected in pyproject.toml")
            elif "hatchling" in pyproject.lower() or "hatch" in pyproject.lower():
                self._ensure_pattern(patterns, repo_name, "packaging", "hatch",
                                     0.9, "hatch detected in pyproject.toml")
            elif "flit" in pyproject.lower():
                self._ensure_pattern(patterns, repo_name, "packaging", "flit",
                                     0.9, "flit detected in pyproject.toml")
            elif "setuptools" in pyproject.lower():
                self._ensure_pattern(patterns, repo_name, "packaging", "setuptools",
                                     0.9, "setuptools detected in pyproject.toml")
        if any("setup.py" in f for f in file_tree):
            self._ensure_pattern(patterns, repo_name, "packaging", "setuptools",
                                 0.7, "setup.py present")

        # 5. Database
        patterns.extend(self._detect_from_rules(
            repo_name, "database", _DATABASE_RULES, deps, readme_lower
        ))

        # 6. CI/CD
        patterns.extend(self._detect_ci(repo_name, file_tree, ci_configs))

        # 7. Docker
        patterns.extend(self._detect_docker(repo_name, file_tree, dockerfile, tree_str))

        # 8. Architecture
        arch = self._detect_architecture(file_tree, readme_lower, tree_str, deps)
        if arch:
            patterns.append(RepoPattern(
                repo_name=repo_name, category="architecture",
                pattern_name=arch[0], confidence=arch[1],
                evidence=arch[2],
            ))

        # 9. License
        if license_name:
            patterns.append(RepoPattern(
                repo_name=repo_name, category="license",
                pattern_name=license_name.lower().replace(" ", "_"),
                confidence=1.0,
                evidence=f"License: {license_name}",
            ))

        return patterns

    # ------------------------------------------------------------------
    # Dependency extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_dep_names(requirements: str, setup_cfg: str, pyproject: str) -> List[str]:
        """Extract normalized pip package names from dependency files."""
        deps: List[str] = []
        # requirements.txt lines
        for line in (requirements or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # "flask>=2.0" → "flask"
            name = re.split(r"[>=<!\[\];@\s]", line)[0].strip().lower()
            if name:
                deps.append(name)
        # setup.cfg / setup.py — crude extraction
        for src in (setup_cfg, pyproject):
            if not src:
                continue
            # find strings that look like package names in install_requires / dependencies
            for m in re.finditer(r'["\']([a-zA-Z0-9_-]+)', src):
                name = m.group(1).lower()
                if len(name) > 1 and name not in ("python", "version", "name", "description"):
                    deps.append(name)
        return list(set(deps))

    # ------------------------------------------------------------------
    # Rule-based detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_from_rules(
        repo_name: str,
        category: str,
        rules: Dict[str, Tuple[List[str], List[str]]],
        deps: List[str],
        readme_lower: str,
    ) -> List[RepoPattern]:
        patterns: List[RepoPattern] = []
        for pattern_name, (pip_names, kw_list) in rules.items():
            # Check deps
            found_dep = None
            for pn in pip_names:
                if pn.lower() in deps:
                    found_dep = pn
                    break
            # Check README keywords
            found_kw = None
            for kw in kw_list:
                if kw.lower() in readme_lower:
                    found_kw = kw
                    break

            if found_dep:
                conf = 0.95
                evidence = f"Found '{found_dep}' in dependencies"
                if found_kw:
                    conf = 1.0
                    evidence += f" + '{found_kw}' in README"
                patterns.append(RepoPattern(
                    repo_name=repo_name, category=category,
                    pattern_name=pattern_name, confidence=conf,
                    evidence=evidence,
                ))
            elif found_kw:
                patterns.append(RepoPattern(
                    repo_name=repo_name, category=category,
                    pattern_name=pattern_name, confidence=0.6,
                    evidence=f"Found '{found_kw}' in README",
                ))
        return patterns

    # ------------------------------------------------------------------
    # CI/CD detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_ci(
        repo_name: str,
        file_tree: List[str],
        ci_configs: List[str],
    ) -> List[RepoPattern]:
        patterns: List[RepoPattern] = []
        tree_lower = [f.lower() for f in file_tree]
        for ci_name, markers in _CI_PATTERNS.items():
            for marker in markers:
                if any(marker.lower() in f for f in tree_lower):
                    # Extra confidence if we have config content
                    conf = 0.95 if ci_configs else 0.85
                    patterns.append(RepoPattern(
                        repo_name=repo_name, category="ci_cd",
                        pattern_name=ci_name, confidence=conf,
                        evidence=f"Found '{marker}' in file tree",
                    ))
                    break
        return patterns

    # ------------------------------------------------------------------
    # Docker detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_docker(
        repo_name: str,
        file_tree: List[str],
        dockerfile: str,
        tree_str: str,
    ) -> List[RepoPattern]:
        patterns: List[RepoPattern] = []
        tree_lower = [f.lower() for f in file_tree]

        has_dockerfile = any("dockerfile" in f for f in tree_lower)
        has_compose = any("docker-compose" in f or "compose.yml" in f or "compose.yaml" in f for f in tree_lower)

        if has_dockerfile:
            meta: Dict[str, Any] = {}
            if dockerfile:
                # Multi-stage detection
                from_count = len(re.findall(r"^FROM\s", dockerfile, re.MULTILINE | re.IGNORECASE))
                if from_count > 1:
                    meta["multi_stage"] = True
                    meta["stages"] = from_count
                # Base image
                base_match = re.search(r"^FROM\s+(\S+)", dockerfile, re.IGNORECASE)
                if base_match:
                    meta["base_image"] = base_match.group(1)
            patterns.append(RepoPattern(
                repo_name=repo_name, category="docker",
                pattern_name="dockerfile", confidence=0.95,
                evidence="Dockerfile present",
                metadata=meta,
            ))

        if has_compose:
            patterns.append(RepoPattern(
                repo_name=repo_name, category="docker",
                pattern_name="docker_compose", confidence=0.95,
                evidence="docker-compose config present",
            ))

        if ".dockerignore" in tree_str:
            patterns.append(RepoPattern(
                repo_name=repo_name, category="docker",
                pattern_name="dockerignore", confidence=0.9,
                evidence=".dockerignore present",
            ))

        return patterns

    # ------------------------------------------------------------------
    # Architecture detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_architecture(
        file_tree: List[str],
        readme_lower: str,
        tree_str: str,
        deps: List[str],
    ) -> Optional[Tuple[str, float, str]]:
        """Return (arch_name, confidence, evidence) or None."""
        scores: Dict[str, float] = {}
        evidence_map: Dict[str, str] = {}

        for arch, signals in _ARCH_SIGNALS.items():
            score = 0.0
            matched = []
            for sig in signals:
                if sig.lower() in tree_str:
                    score += 0.3
                    matched.append(sig)
            if matched:
                scores[arch] = min(score, 1.0)
                evidence_map[arch] = f"File tree signals: {', '.join(matched)}"

        # Boost from deps
        web_deps = {"flask", "django", "fastapi", "aiohttp", "starlette", "tornado"}
        if web_deps & set(deps):
            scores["web_app"] = scores.get("web_app", 0) + 0.4
            evidence_map.setdefault("web_app", "Web framework in deps")

        ml_deps = {"torch", "tensorflow", "scikit-learn", "transformers", "keras"}
        if ml_deps & set(deps):
            scores["ml_project"] = scores.get("ml_project", 0) + 0.4
            evidence_map.setdefault("ml_project", "ML framework in deps")

        ds_deps = {"pandas", "numpy", "matplotlib", "jupyter", "scipy"}
        if len(ds_deps & set(deps)) >= 2:
            scores["data_science"] = scores.get("data_science", 0) + 0.3
            evidence_map.setdefault("data_science", "Data science deps")

        # cli detection via entry points
        if "console_scripts" in readme_lower or "entry_points" in tree_str:
            scores["cli"] = scores.get("cli", 0) + 0.3
            evidence_map.setdefault("cli", "console_scripts entry point")

        if not scores:
            # Default to library if has setup.py/pyproject.toml
            if "setup.py" in tree_str or "pyproject.toml" in tree_str:
                return ("library", 0.5, "Has setup.py/pyproject.toml")
            return None

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        return (best, min(scores[best], 1.0), evidence_map.get(best, ""))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_pattern(
        patterns: List[RepoPattern],
        repo_name: str,
        category: str,
        pattern_name: str,
        confidence: float,
        evidence: str,
    ) -> None:
        """Add a pattern only if it isn't already present."""
        for p in patterns:
            if p.category == category and p.pattern_name == pattern_name:
                return
        patterns.append(RepoPattern(
            repo_name=repo_name, category=category,
            pattern_name=pattern_name, confidence=confidence,
            evidence=evidence,
        ))
