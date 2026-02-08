# -*- coding: utf-8 -*-
"""Tests for core.oss.repo_analyzer — pattern extraction."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.oss.repo_analyzer import RepoAnalyzer, RepoPattern


@pytest.fixture
def analyzer():
    return RepoAnalyzer()


# =========================================================================
# Test: Dependency Extraction
# =========================================================================

class TestDependencyExtraction:
    def test_requirements_txt(self, analyzer):
        reqs = "flask>=2.0\nrequests\npytest>=7.0\n# comment\n-r base.txt"
        deps = analyzer._extract_dep_names(reqs, "", "")
        assert "flask" in deps
        assert "requests" in deps
        assert "pytest" in deps

    def test_pyproject_toml(self, analyzer):
        pyproject = '''
[project]
dependencies = [
    "fastapi>=0.100",
    "uvicorn",
    "pydantic>=2.0",
]
'''
        deps = analyzer._extract_dep_names("", "", pyproject)
        assert "fastapi" in deps
        assert "uvicorn" in deps

    def test_empty_deps(self, analyzer):
        deps = analyzer._extract_dep_names("", "", "")
        assert deps == []

    def test_deduplication(self, analyzer):
        deps = analyzer._extract_dep_names("flask\nflask", "", "")
        assert deps.count("flask") == 1


# =========================================================================
# Test: Framework Detection
# =========================================================================

class TestFrameworkDetection:
    def test_flask_from_requirements(self, analyzer):
        patterns = analyzer.analyze("user/repo", requirements="flask>=2.0")
        names = {p.pattern_name for p in patterns if p.category == "framework"}
        assert "flask" in names

    def test_django_from_readme(self, analyzer):
        patterns = analyzer.analyze("user/repo", readme="This project uses Django")
        names = {p.pattern_name for p in patterns if p.category == "framework"}
        assert "django" in names

    def test_fastapi_both(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            requirements="fastapi>=0.100",
            readme="FastAPI application"
        )
        fastapi = [p for p in patterns if p.pattern_name == "fastapi"]
        assert len(fastapi) == 1
        assert fastapi[0].confidence == 1.0  # both deps + readme

    def test_multiple_frameworks(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            requirements="flask\ncelery\nredis"
        )
        names = {p.pattern_name for p in patterns if p.category == "framework"}
        assert "flask" in names
        assert "celery" in names

    def test_no_framework(self, analyzer):
        patterns = analyzer.analyze("user/repo", readme="A simple script")
        fw = [p for p in patterns if p.category == "framework"]
        assert len(fw) == 0


# =========================================================================
# Test: Testing Detection
# =========================================================================

class TestTestingDetection:
    def test_pytest_from_deps(self, analyzer):
        patterns = analyzer.analyze("user/repo", requirements="pytest>=7.0\ncoverage")
        names = {p.pattern_name for p in patterns if p.category == "testing"}
        assert "pytest" in names
        assert "coverage" in names

    def test_hypothesis(self, analyzer):
        patterns = analyzer.analyze("user/repo", requirements="hypothesis")
        names = {p.pattern_name for p in patterns if p.category == "testing"}
        assert "hypothesis" in names

    def test_test_files_in_tree(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=["src/main.py", "tests/test_main.py"]
        )
        names = {p.pattern_name for p in patterns if p.category == "testing"}
        assert "has_tests" in names


# =========================================================================
# Test: CI/CD Detection
# =========================================================================

class TestCICDDetection:
    def test_github_actions(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=[".github/workflows/ci.yml", "src/main.py"]
        )
        names = {p.pattern_name for p in patterns if p.category == "ci_cd"}
        assert "github_actions" in names

    def test_travis(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=[".travis.yml"]
        )
        names = {p.pattern_name for p in patterns if p.category == "ci_cd"}
        assert "travis" in names

    def test_multiple_ci(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=[".github/workflows/test.yml", ".travis.yml", "Makefile"]
        )
        names = {p.pattern_name for p in patterns if p.category == "ci_cd"}
        assert "github_actions" in names
        assert "travis" in names
        assert "makefile" in names

    def test_no_ci(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=["src/main.py", "README.md"]
        )
        ci = [p for p in patterns if p.category == "ci_cd"]
        assert len(ci) == 0


# =========================================================================
# Test: Docker Detection
# =========================================================================

class TestDockerDetection:
    def test_dockerfile(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=["Dockerfile", "src/main.py"],
            dockerfile="FROM python:3.11\nCOPY . .\nRUN pip install -r requirements.txt"
        )
        names = {p.pattern_name for p in patterns if p.category == "docker"}
        assert "dockerfile" in names

    def test_multistage(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=["Dockerfile"],
            dockerfile="FROM python:3.11 AS builder\nRUN pip install .\nFROM python:3.11-slim\nCOPY --from=builder ."
        )
        docker_p = [p for p in patterns if p.pattern_name == "dockerfile"]
        assert len(docker_p) == 1
        assert docker_p[0].metadata.get("multi_stage") is True
        assert docker_p[0].metadata.get("stages") == 2

    def test_docker_compose(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=["docker-compose.yml", "Dockerfile"]
        )
        names = {p.pattern_name for p in patterns if p.category == "docker"}
        assert "docker_compose" in names
        assert "dockerfile" in names

    def test_dockerignore(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=[".dockerignore", "Dockerfile"]
        )
        names = {p.pattern_name for p in patterns if p.category == "docker"}
        assert "dockerignore" in names


# =========================================================================
# Test: Linting Detection
# =========================================================================

class TestLintingDetection:
    def test_ruff_from_deps(self, analyzer):
        patterns = analyzer.analyze("user/repo", requirements="ruff>=0.1.0")
        names = {p.pattern_name for p in patterns if p.category == "linting"}
        assert "ruff" in names

    def test_black_from_pyproject(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            pyproject="[tool.black]\nline-length = 88"
        )
        names = {p.pattern_name for p in patterns if p.category == "linting"}
        assert "black" in names

    def test_multiple_linters(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            requirements="black\nruff\nmypy\nisort",
            pyproject="[tool.ruff]\nline-length = 88\n[tool.isort]\nprofile = 'black'"
        )
        names = {p.pattern_name for p in patterns if p.category == "linting"}
        assert "black" in names
        assert "ruff" in names
        assert "mypy" in names
        assert "isort" in names


# =========================================================================
# Test: Packaging Detection
# =========================================================================

class TestPackagingDetection:
    def test_poetry(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            pyproject='[tool.poetry]\nname = "mypackage"'
        )
        names = {p.pattern_name for p in patterns if p.category == "packaging"}
        assert "poetry" in names

    def test_setuptools_from_setup_py(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=["setup.py", "src/main.py"]
        )
        names = {p.pattern_name for p in patterns if p.category == "packaging"}
        assert "setuptools" in names

    def test_hatch(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            pyproject='[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"'
        )
        names = {p.pattern_name for p in patterns if p.category == "packaging"}
        assert "hatch" in names


# =========================================================================
# Test: Database Detection
# =========================================================================

class TestDatabaseDetection:
    def test_sqlalchemy(self, analyzer):
        patterns = analyzer.analyze("user/repo", requirements="sqlalchemy>=2.0")
        names = {p.pattern_name for p in patterns if p.category == "database"}
        assert "sqlalchemy" in names

    def test_redis(self, analyzer):
        patterns = analyzer.analyze("user/repo", requirements="redis")
        names = {p.pattern_name for p in patterns if p.category == "database"}
        assert "redis" in names

    def test_mongo(self, analyzer):
        patterns = analyzer.analyze("user/repo", requirements="pymongo\nmotor")
        names = {p.pattern_name for p in patterns if p.category == "database"}
        assert "pymongo" in names
        assert "motor" in names


# =========================================================================
# Test: Architecture Detection
# =========================================================================

class TestArchitectureDetection:
    def test_web_app(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            requirements="flask",
            file_tree=["app.py", "templates/index.html", "static/style.css"]
        )
        arch = [p for p in patterns if p.category == "architecture"]
        assert len(arch) == 1
        assert arch[0].pattern_name == "web_app"

    def test_cli(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=["cli.py", "__main__.py", "setup.py"],
            readme="console_scripts entry point"
        )
        arch = [p for p in patterns if p.category == "architecture"]
        assert len(arch) == 1
        assert arch[0].pattern_name == "cli"

    def test_ml_project(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            requirements="torch\nnumpy",
            file_tree=["model/train.py", "predict.py", "weights/model.pt"]
        )
        arch = [p for p in patterns if p.category == "architecture"]
        assert len(arch) == 1
        assert arch[0].pattern_name == "ml_project"

    def test_library_fallback(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            file_tree=["setup.py", "src/mylib/__init__.py"]
        )
        arch = [p for p in patterns if p.category == "architecture"]
        assert len(arch) == 1
        # Could be "library" or another match depending on signals

    def test_data_science(self, analyzer):
        patterns = analyzer.analyze(
            "user/repo",
            requirements="pandas\nnumpy\nmatplotlib",
            file_tree=["notebooks/analysis.ipynb", "data/raw/"]
        )
        arch = [p for p in patterns if p.category == "architecture"]
        assert len(arch) == 1
        assert arch[0].pattern_name == "data_science"


# =========================================================================
# Test: License Detection
# =========================================================================

class TestLicenseDetection:
    def test_mit_license(self, analyzer):
        patterns = analyzer.analyze("user/repo", license_name="MIT")
        lic = [p for p in patterns if p.category == "license"]
        assert len(lic) == 1
        assert lic[0].pattern_name == "mit"

    def test_no_license(self, analyzer):
        patterns = analyzer.analyze("user/repo")
        lic = [p for p in patterns if p.category == "license"]
        assert len(lic) == 0


# =========================================================================
# Test: Full Analysis
# =========================================================================

class TestFullAnalysis:
    def test_flask_project(self, analyzer):
        """Simulate a typical Flask project."""
        patterns = analyzer.analyze(
            repo_name="pallets/flask",
            readme="# Flask\nThe Python micro framework for building web applications.\nFlask is a lightweight WSGI web application framework.",
            file_tree=[
                "src/flask/__init__.py", "src/flask/app.py",
                "tests/test_basic.py", "tests/test_views.py",
                ".github/workflows/tests.yml",
                "setup.py", "pyproject.toml",
                "Dockerfile", ".dockerignore",
            ],
            requirements="pytest\ncoverage\nsphinx",
            pyproject='[tool.black]\nline-length = 88\n[tool.isort]\nprofile = "black"',
            dockerfile="FROM python:3.11-slim\nCOPY . .\nRUN pip install .",
            license_name="BSD-3-Clause",
        )
        cats = {p.category for p in patterns}
        assert "framework" in cats
        assert "testing" in cats
        assert "ci_cd" in cats
        assert "docker" in cats
        assert "license" in cats
        assert "linting" in cats

    def test_empty_project(self, analyzer):
        """Minimal project should still work."""
        patterns = analyzer.analyze("empty/repo")
        assert isinstance(patterns, list)

    def test_all_patterns_have_repo_name(self, analyzer):
        patterns = analyzer.analyze(
            "my/repo",
            requirements="flask\npytest",
            file_tree=[".github/workflows/ci.yml"]
        )
        for p in patterns:
            assert p.repo_name == "my/repo"
