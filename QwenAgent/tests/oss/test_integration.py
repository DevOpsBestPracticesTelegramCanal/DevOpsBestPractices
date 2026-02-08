# -*- coding: utf-8 -*-
"""
Integration tests for OSS Consciousness MVP.

Tests the full pipeline: collect → analyze → store → query → tool
Uses both synthetic data and (optionally) live GitHub API.
"""

import os
import pytest
import time

from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord
from core.oss.repo_analyzer import RepoAnalyzer, RepoPattern
from core.oss.github_collector import GitHubCollector, RepoMeta
from core.oss.oss_engine import OSSEngine, OSSInsight
from core.oss.oss_tool import OSSTool, OSS_ROUTER_PATTERNS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    """In-memory pattern store."""
    return PatternStore(db_path=":memory:")


@pytest.fixture
def analyzer():
    return RepoAnalyzer()


@pytest.fixture
def engine(store):
    return OSSEngine(store)


@pytest.fixture
def tool():
    return OSSTool(db_path=":memory:")


# ---------------------------------------------------------------------------
# Realistic repo data (simulates what GitHubCollector would return)
# ---------------------------------------------------------------------------

FASTAPI_META = RepoMeta(
    full_name="tiangolo/fastapi",
    stars=75000,
    forks=6300,
    language="Python",
    description="FastAPI framework, high performance, easy to learn, fast to code, ready for production",
    topics=["python", "fastapi", "web", "api", "async"],
    default_branch="master",
    license="MIT",
    readme_content="""
# FastAPI

FastAPI is a modern, fast (high-performance), web framework for building APIs with Python 3.8+.

## Features
- Fast: Very high performance, on par with NodeJS and Go.
- Fast to code: Increase the speed to develop features by about 200% to 300%.
- Uses Pydantic for data validation.

## Requirements
Python 3.8+

## Installation
```bash
pip install fastapi uvicorn
```

## Testing
Run tests with pytest:
```bash
pytest tests/
```
    """,
    file_tree=[
        "fastapi/__init__.py", "fastapi/applications.py", "fastapi/routing.py",
        "tests/test_application.py", "tests/test_router.py",
        "docs/en/docs/index.md",
        "pyproject.toml", "requirements.txt",
        ".github/workflows/test.yml", ".github/workflows/publish.yml",
        "Dockerfile", ".dockerignore",
        "scripts/lint.sh",
    ],
    requirements="starlette>=0.27.0\npydantic>=1.7.4\nuvicorn[standard]\nhttpx\npytest\npytest-cov\nruff\nmypy\nblack",
    pyproject="""
[project]
name = "fastapi"
version = "0.104.1"
dependencies = ["starlette>=0.27.0", "pydantic>=1.7.4"]

[tool.ruff]
line-length = 88

[tool.mypy]
strict = true

[tool.black]
line-length = 88

[tool.pytest.ini_options]
testpaths = ["tests"]
    """,
    dockerfile="FROM python:3.11-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -e .\nCMD [\"uvicorn\", \"main:app\"]",
)

FLASK_META = RepoMeta(
    full_name="pallets/flask",
    stars=67000,
    forks=16000,
    language="Python",
    description="The Python micro framework for building web applications.",
    topics=["python", "flask", "web", "wsgi"],
    default_branch="main",
    license="BSD-3-Clause",
    readme_content="""
# Flask

Flask is a lightweight WSGI web application framework. It is designed to make
getting started quick and easy, with the ability to scale up to complex applications.

## Installation
```bash
pip install Flask
```

## Testing
```bash
pytest tests/
```
    """,
    file_tree=[
        "src/flask/__init__.py", "src/flask/app.py", "src/flask/blueprints.py",
        "tests/test_basic.py", "tests/test_blueprints.py",
        "pyproject.toml", "requirements/dev.txt",
        ".github/workflows/tests.yml",
        "tox.ini",
    ],
    requirements="werkzeug>=3.0\njinja2>=3.1\nclick>=8.1\nblinker>=1.7\nitsdangerous>=2.1",
    pyproject="""
[project]
name = "Flask"
dependencies = ["werkzeug>=3.0", "jinja2>=3.1", "click>=8.1"]

[build-system]
requires = ["flit_core"]
build-backend = "flit_core.api"

[tool.pytest.ini_options]
testpaths = ["tests"]
    """,
)

REQUESTS_META = RepoMeta(
    full_name="psf/requests",
    stars=52000,
    forks=9200,
    language="Python",
    description="A simple, yet elegant, HTTP library.",
    topics=["python", "http", "requests"],
    default_branch="main",
    license="Apache-2.0",
    readme_content="""
# Requests

Requests is a simple, yet elegant, HTTP library for Python.

## Installation
```bash
pip install requests
```

## Testing
Run tests:
```bash
pytest tests/
```
    """,
    file_tree=[
        "src/requests/__init__.py", "src/requests/api.py",
        "tests/test_requests.py",
        "setup.py", "setup.cfg", "Makefile",
        ".github/workflows/run-tests.yml",
        "tox.ini",
    ],
    requirements="certifi>=2017.4.17\ncharset-normalizer>=2,<4\nidna>=2.5,<4\nurllib3>=1.21.1,<3",
    setup_cfg="[metadata]\nname = requests\n[options]\ninstall_requires = certifi\n",
)

LANGCHAIN_META = RepoMeta(
    full_name="langchain-ai/langchain",
    stars=90000,
    forks=14000,
    language="Python",
    description="Building applications with LLMs through composability",
    topics=["python", "llm", "ai", "langchain", "openai"],
    default_branch="master",
    license="MIT",
    readme_content="""
# LangChain

LangChain is a framework for developing applications powered by language models.

Uses transformers, pytorch, and various LLM providers.

## Installation
```bash
pip install langchain
```
    """,
    file_tree=[
        "libs/langchain/langchain/__init__.py",
        "libs/core/langchain_core/__init__.py",
        "libs/community/langchain_community/__init__.py",
        "tests/unit_tests/", "tests/integration_tests/",
        "pyproject.toml", "poetry.lock",
        ".github/workflows/ci.yml", ".github/workflows/release.yml",
        "docker-compose.yml", "Makefile",
    ],
    requirements="pydantic>=2.1\nrequests\naiohttp\nnumpy\nsqlalchemy",
    pyproject="""
[tool.poetry]
name = "langchain"
version = "0.1.0"
dependencies = {python = "^3.8", pydantic = "^2.1"}

[tool.ruff]
select = ["E", "F", "I"]

[tool.mypy]
ignore_missing_imports = true
    """,
)

SAMPLE_REPOS = [FASTAPI_META, FLASK_META, REQUESTS_META, LANGCHAIN_META]


# ---------------------------------------------------------------------------
# Helper: seed store with analyzed data
# ---------------------------------------------------------------------------

def seed_store(store: PatternStore, analyzer: RepoAnalyzer) -> int:
    """Analyze sample repos and store results. Returns pattern count."""
    total_patterns = 0
    for meta in SAMPLE_REPOS:
        # Save repo record
        repo = RepoRecord(
            full_name=meta.full_name,
            stars=meta.stars,
            forks=meta.forks,
            description=meta.description,
            topics=meta.topics,
            license=meta.license,
            collected_at=time.time(),
        )
        repo_id = store.save_repo(repo)

        # Analyze
        patterns = analyzer.analyze(
            repo_name=meta.full_name,
            readme=meta.readme_content,
            file_tree=meta.file_tree,
            requirements=meta.requirements,
            setup_cfg=meta.setup_cfg,
            pyproject=meta.pyproject,
            dockerfile=meta.dockerfile,
            license_name=meta.license,
        )

        # Convert to PatternRecords
        records = [
            PatternRecord(
                repo_name=p.repo_name,
                category=p.category,
                pattern_name=p.pattern_name,
                confidence=p.confidence,
                evidence=p.evidence,
                metadata=p.metadata,
            )
            for p in patterns
        ]
        saved = store.save_patterns(records)
        total_patterns += saved

        # Mark as analyzed
        repo.analyzed_at = time.time()
        store.save_repo(repo)

    store.refresh_pattern_stats()
    return total_patterns


# ===========================================================================
# TEST 1: Full Pipeline — Analyze → Store → Query
# ===========================================================================

class TestFullPipeline:
    """Test the complete flow from analysis to querying."""

    def test_seed_produces_patterns(self, store, analyzer):
        count = seed_store(store, analyzer)
        assert count > 20, f"Expected >20 patterns, got {count}"
        stats = store.get_stats()
        assert stats["total_repos"] == 4
        assert stats["analyzed_repos"] == 4
        assert stats["total_patterns"] >= 20

    def test_categories_detected(self, store, analyzer):
        seed_store(store, analyzer)
        cats = store.get_categories()
        assert "framework" in cats
        assert "testing" in cats
        assert "linting" in cats
        assert "ci_cd" in cats
        assert "license" in cats

    def test_fastapi_patterns(self, store, analyzer):
        seed_store(store, analyzer)
        patterns = store.get_patterns_for_repo("tiangolo/fastapi")
        names = {p.pattern_name for p in patterns}
        assert "fastapi" in names, f"fastapi not in {names}"
        assert "pytest" in names, f"pytest not in {names}"
        assert "ruff" in names or "mypy" in names, f"No linting tools in {names}"
        assert "dockerfile" in names, f"No dockerfile in {names}"

    def test_flask_patterns(self, store, analyzer):
        seed_store(store, analyzer)
        patterns = store.get_patterns_for_repo("pallets/flask")
        names = {p.pattern_name for p in patterns}
        assert "flask" in names
        assert "click" in names, f"click not in {names}"
        assert "flit" in names, f"flit not in {names}"

    def test_langchain_patterns(self, store, analyzer):
        seed_store(store, analyzer)
        patterns = store.get_patterns_for_repo("langchain-ai/langchain")
        names = {p.pattern_name for p in patterns}
        assert "pydantic" in names, f"pydantic not in {names}"
        assert "sqlalchemy" in names, f"sqlalchemy not in {names}"
        assert "poetry" in names, f"poetry not in {names}"

    def test_pattern_stats_aggregated(self, store, analyzer):
        seed_store(store, analyzer)
        top = store.get_top_patterns(limit=50)
        assert len(top) > 5
        # Patterns used by multiple repos should appear
        pytest_stat = next((t for t in top if t["pattern_name"] == "pytest"), None)
        assert pytest_stat is not None
        assert pytest_stat["repo_count"] >= 2  # fastapi + flask + requests


# ===========================================================================
# TEST 2: OSSEngine Queries
# ===========================================================================

class TestEngineQueries:
    """Test natural-language queries through OSSEngine."""

    @pytest.fixture(autouse=True)
    def _seed(self, store, analyzer, engine):
        seed_store(store, analyzer)
        self.engine = engine

    def test_query_specific_pattern_flask(self):
        result = self.engine.query("How popular is flask?")
        assert result.confidence > 0
        assert "flask" in result.answer.lower()

    def test_query_specific_pattern_pytest(self):
        result = self.engine.query("Which repos use pytest?")
        assert result.confidence > 0
        assert "pytest" in result.answer.lower()
        assert len(result.sample_repos) > 0

    def test_query_category_testing(self):
        result = self.engine.query("What testing tools are popular?")
        assert result.confidence > 0
        assert "pytest" in result.answer.lower()

    def test_query_category_frameworks(self):
        result = self.engine.query("Popular web frameworks?")
        assert result.confidence > 0

    def test_query_comparison_flask_vs_django(self):
        result = self.engine.query("flask vs django")
        assert "flask" in result.answer.lower()
        assert "django" in result.answer.lower()

    def test_query_comparison_ruff_vs_pylint(self):
        result = self.engine.query("ruff vs pylint")
        assert result.confidence > 0

    def test_query_docker(self):
        result = self.engine.query("How many repos use Docker?")
        assert result.confidence > 0

    def test_query_full_overview(self):
        result = self.engine.query("Give me a complete overview")
        assert result.confidence > 0
        assert "OSS Consciousness Report" in result.answer

    def test_query_russian_frameworks(self):
        result = self.engine.query("Какие фреймворки популярны?")
        assert result.confidence > 0

    def test_full_report_markdown(self):
        report = self.engine.get_full_report()
        assert "# OSS Consciousness Report" in report
        assert "Repos analyzed:" in report
        assert "Patterns extracted:" in report

    def test_framework_stats(self):
        stats = self.engine.get_framework_stats()
        assert len(stats) > 0
        names = {s["pattern_name"] for s in stats}
        assert "fastapi" in names or "flask" in names

    def test_testing_stats(self):
        stats = self.engine.get_testing_stats()
        assert len(stats) > 0

    def test_get_stats(self):
        stats = self.engine.get_stats()
        assert stats["total_repos"] == 4
        assert stats["total_patterns"] > 0


# ===========================================================================
# TEST 3: OSSTool Actions
# ===========================================================================

class TestToolActions:
    """Test OSSTool execute() with various actions."""

    @pytest.fixture(autouse=True)
    def _seed(self, tool):
        self.tool = tool
        store = tool.store
        analyzer = RepoAnalyzer()
        seed_store(store, analyzer)

    def test_action_query(self):
        result = self.tool.execute("query", question="What frameworks are popular?")
        assert result["success"]
        assert "answer" in result
        assert result["confidence"] > 0

    def test_action_query_no_question(self):
        result = self.tool.execute("query")
        assert not result["success"]
        assert "error" in result

    def test_action_stats(self):
        result = self.tool.execute("stats")
        assert result["success"]
        assert result["stats"]["total_repos"] == 4

    def test_action_report(self):
        result = self.tool.execute("report")
        assert result["success"]
        assert "OSS Consciousness Report" in result["report"]

    def test_action_frameworks(self):
        result = self.tool.execute("frameworks")
        assert result["success"]
        assert len(result["data"]) > 0

    def test_action_testing(self):
        result = self.tool.execute("testing")
        assert result["success"]

    def test_action_ci(self):
        result = self.tool.execute("ci")
        assert result["success"]

    def test_action_docker(self):
        result = self.tool.execute("docker")
        assert result["success"]

    def test_action_linting(self):
        result = self.tool.execute("linting")
        assert result["success"]

    def test_action_packaging(self):
        result = self.tool.execute("packaging")
        assert result["success"]

    def test_action_databases(self):
        result = self.tool.execute("databases")
        assert result["success"]

    def test_action_architecture(self):
        result = self.tool.execute("architecture")
        assert result["success"]

    def test_action_pattern_lookup(self):
        result = self.tool.execute("pattern", pattern_name="pytest")
        assert result["success"]
        assert result["count"] > 0

    def test_action_unknown(self):
        result = self.tool.execute("nonexistent_action")
        assert not result["success"]

    def test_get_stats_method(self):
        stats = self.tool.get_stats()
        assert stats["total_repos"] == 4


# ===========================================================================
# TEST 4: RepoAnalyzer Edge Cases
# ===========================================================================

class TestAnalyzerEdgeCases:
    """Test analyzer with edge cases and realistic repo variations."""

    def test_empty_repo(self, analyzer):
        patterns = analyzer.analyze("empty/repo")
        assert len(patterns) == 0

    def test_repo_with_only_readme(self, analyzer):
        patterns = analyzer.analyze(
            "some/repo",
            readme="This project uses Flask and pytest for testing.",
        )
        names = {p.pattern_name for p in patterns}
        assert "flask" in names
        assert "pytest" in names

    def test_repo_with_only_requirements(self, analyzer):
        patterns = analyzer.analyze(
            "some/repo",
            requirements="django>=4.2\ncelery>=5.3\nredis>=5.0\npytest\n",
        )
        names = {p.pattern_name for p in patterns}
        assert "django" in names
        assert "celery" in names
        assert "redis" in names
        assert "pytest" in names

    def test_multistage_dockerfile(self, analyzer):
        dockerfile = """
FROM python:3.11-slim AS builder
RUN pip install poetry
COPY pyproject.toml .
RUN poetry install

FROM python:3.11-slim
COPY --from=builder /app /app
CMD ["python", "main.py"]
        """
        patterns = analyzer.analyze(
            "some/repo",
            file_tree=["Dockerfile", "pyproject.toml"],
            dockerfile=dockerfile,
        )
        docker_patterns = [p for p in patterns if p.category == "docker"]
        assert any(p.pattern_name == "dockerfile" for p in docker_patterns)
        # Multi-stage detection
        df_pattern = next(p for p in docker_patterns if p.pattern_name == "dockerfile")
        assert df_pattern.metadata.get("multi_stage") is True
        assert df_pattern.metadata.get("stages") == 2

    def test_docker_compose_detection(self, analyzer):
        patterns = analyzer.analyze(
            "some/repo",
            file_tree=["docker-compose.yml", "Dockerfile", "src/app.py"],
        )
        names = {p.pattern_name for p in patterns}
        assert "docker_compose" in names
        assert "dockerfile" in names

    def test_ml_project_detection(self, analyzer):
        patterns = analyzer.analyze(
            "some/ml-repo",
            readme="Deep learning model for image classification using PyTorch",
            requirements="torch>=2.0\ntorchvision\nnumpy\nmatplotlib\nscikit-learn\npandas",
            file_tree=["model/train.py", "model/predict.py", "data/", "notebooks/analysis.ipynb"],
        )
        arch_patterns = [p for p in patterns if p.category == "architecture"]
        assert len(arch_patterns) > 0
        # Should detect ml_project or data_science
        arch_names = {p.pattern_name for p in arch_patterns}
        assert "ml_project" in arch_names or "data_science" in arch_names

    def test_monorepo_detection(self, analyzer):
        patterns = analyzer.analyze(
            "some/monorepo",
            file_tree=["packages/core/", "packages/cli/", "packages/web/", "libs/shared/"],
        )
        arch_patterns = [p for p in patterns if p.category == "architecture"]
        if arch_patterns:
            assert any(p.pattern_name == "monorepo" for p in arch_patterns)

    def test_cli_detection(self, analyzer):
        patterns = analyzer.analyze(
            "some/cli-tool",
            readme="A powerful CLI tool. Install and use console_scripts entry point.",
            requirements="click>=8.0\nrich\n",
            file_tree=["cli.py", "__main__.py", "setup.py"],
        )
        names = {p.pattern_name for p in patterns}
        assert "click" in names

    def test_license_detection(self, analyzer):
        patterns = analyzer.analyze("some/repo", license_name="MIT")
        lic = [p for p in patterns if p.category == "license"]
        assert len(lic) == 1
        assert lic[0].pattern_name == "mit"

    def test_pyproject_linting_sections(self, analyzer):
        pyproject = """
[tool.ruff]
select = ["E", "F"]

[tool.isort]
profile = "black"

[tool.mypy]
strict = true
        """
        patterns = analyzer.analyze("some/repo", pyproject=pyproject)
        names = {p.pattern_name for p in patterns}
        assert "ruff" in names
        assert "isort" in names
        assert "mypy" in names


# ===========================================================================
# TEST 5: PatternStore Integrity
# ===========================================================================

class TestStoreIntegrity:
    """Test store data integrity after full pipeline."""

    @pytest.fixture(autouse=True)
    def _seed(self, store, analyzer):
        seed_store(store, analyzer)
        self.store = store

    def test_repo_count(self):
        assert self.store.count_repos() == 4

    def test_repos_ordered_by_stars(self):
        repos = self.store.list_repos()
        stars = [r.stars for r in repos]
        assert stars == sorted(stars, reverse=True)

    def test_repo_roundtrip(self):
        repo = self.store.get_repo("tiangolo/fastapi")
        assert repo is not None
        assert repo.stars == 75000
        assert "fastapi" in repo.topics

    def test_pattern_stats_refreshed(self):
        stats = self.store.get_top_patterns(limit=100)
        assert len(stats) > 0
        for s in stats:
            assert s["repo_count"] > 0
            assert s["top_repo"] != ""

    def test_query_repos_by_pattern(self):
        repos = self.store.query_repos_by_pattern("pytest")
        assert len(repos) >= 2
        # Should be sorted by stars descending
        stars = [r["stars"] for r in repos]
        assert stars == sorted(stars, reverse=True)

    def test_no_duplicate_patterns(self):
        """Each (repo, category, pattern_name) should be unique."""
        for meta in SAMPLE_REPOS:
            patterns = self.store.get_patterns_for_repo(meta.full_name)
            keys = [(p.category, p.pattern_name) for p in patterns]
            assert len(keys) == len(set(keys)), f"Duplicates in {meta.full_name}: {keys}"


# ===========================================================================
# TEST 6: Router Patterns
# ===========================================================================

class TestRouterPatterns:
    """Test that OSS_ROUTER_PATTERNS match expected queries."""

    def test_oss_patterns_exist(self):
        assert len(OSS_ROUTER_PATTERNS) > 0

    @pytest.mark.parametrize("query", [
        "oss pattern analysis",
        "open source stats",
        "popular python frameworks",
        "top testing tools",
        "flask vs django",
        "tech stack report",
        "какие фреймворки популярны",
        "анализ open source репозиториев",
    ])
    def test_pattern_matches(self, query):
        import re
        matched = False
        for pattern_str, tool_name, extractor in OSS_ROUTER_PATTERNS:
            m = re.search(pattern_str, query, re.IGNORECASE)
            if m:
                matched = True
                assert tool_name == "oss"
                result = extractor(m)
                assert "action" in result
                break
        assert matched, f"No router pattern matched: {query}"

    def test_non_oss_query_no_match(self):
        import re
        for pattern_str, _, _ in OSS_ROUTER_PATTERNS:
            assert not re.search(pattern_str, "what is the weather today", re.IGNORECASE)


# ===========================================================================
# TEST 7: Live GitHub API (skipped if no GITHUB_TOKEN)
# ===========================================================================

def _github_token_works() -> bool:
    """Check if GITHUB_TOKEN is set and valid (can reach GitHub API)."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return False
    try:
        import requests as req
        resp = req.get(
            "https://api.github.com/rate_limit",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(
    not _github_token_works(),
    reason="GITHUB_TOKEN not set or invalid"
)
class TestLiveGitHubAPI:
    """Test real GitHub API calls (requires valid GITHUB_TOKEN)."""

    def test_rate_limit_check(self):
        collector = GitHubCollector()
        rl = collector.get_rate_limit()
        assert "remaining" in rl
        assert rl["remaining"] >= 0

    def test_collect_small_batch(self):
        """Fetch 3 repos to verify API integration works."""
        collector = GitHubCollector()
        repos = collector.collect_top_repos(language="python", count=3, min_stars=50000)
        assert len(repos) >= 1
        # Top Python repo by stars should be well-known
        assert repos[0].stars > 50000
        assert repos[0].full_name != ""

    def test_collect_and_analyze(self):
        """Full pipeline: collect 2 repos → analyze → store → query."""
        collector = GitHubCollector()
        store = PatternStore(db_path=":memory:")
        analyzer = RepoAnalyzer()
        engine = OSSEngine(store)

        # Collect metadata only (no enrichment to save API calls)
        metas = collector.collect_top_repos(language="python", count=2, min_stars=50000)
        assert len(metas) >= 1

        for meta in metas:
            repo = RepoRecord(
                full_name=meta.full_name,
                stars=meta.stars,
                forks=meta.forks,
                description=meta.description,
                topics=meta.topics,
                license=meta.license,
                collected_at=time.time(),
            )
            store.save_repo(repo)

            # Analyze with just the metadata (no enrichment)
            patterns = analyzer.analyze(
                repo_name=meta.full_name,
                readme=meta.readme_content,  # empty without enrichment
                file_tree=meta.file_tree,     # empty without enrichment
                license_name=meta.license,
            )
            records = [
                PatternRecord(
                    repo_name=p.repo_name,
                    category=p.category,
                    pattern_name=p.pattern_name,
                    confidence=p.confidence,
                    evidence=p.evidence,
                )
                for p in patterns
            ]
            store.save_patterns(records)

        store.refresh_pattern_stats()
        stats = engine.get_stats()
        assert stats["total_repos"] >= 1

    def test_enrich_single_repo(self):
        """Enrich a single repo to test deep data fetching."""
        collector = GitHubCollector()
        meta = RepoMeta(
            full_name="psf/requests",
            stars=52000,
            default_branch="main",
        )
        enriched = collector.enrich_repo(meta)
        # After enrichment we should have some data
        assert len(enriched.readme_content) > 0
        assert len(enriched.file_tree) > 0

        # Analyze the enriched data
        analyzer = RepoAnalyzer()
        patterns = analyzer.analyze(
            repo_name=enriched.full_name,
            readme=enriched.readme_content,
            file_tree=enriched.file_tree,
            requirements=enriched.requirements,
            setup_cfg=enriched.setup_cfg,
            pyproject=enriched.pyproject,
            dockerfile=enriched.dockerfile,
            license_name=enriched.license,
        )
        assert len(patterns) > 0
        names = {p.pattern_name for p in patterns}
        # requests repo should have some known patterns
        assert len(names) >= 2


# ===========================================================================
# TEST 8: Performance
# ===========================================================================

class TestPerformance:
    """Ensure the pipeline runs fast enough for interactive use."""

    def test_analysis_speed(self, analyzer):
        """Analyzing a single repo should be <50ms."""
        start = time.time()
        for _ in range(100):
            analyzer.analyze(
                repo_name="test/repo",
                readme=FASTAPI_META.readme_content,
                file_tree=FASTAPI_META.file_tree,
                requirements=FASTAPI_META.requirements,
                pyproject=FASTAPI_META.pyproject,
                dockerfile=FASTAPI_META.dockerfile,
            )
        elapsed = time.time() - start
        per_call = elapsed / 100 * 1000  # ms
        assert per_call < 50, f"Analysis too slow: {per_call:.1f}ms per call"

    def test_query_speed(self, store, analyzer, engine):
        """Querying the engine should be <10ms with seeded data."""
        seed_store(store, analyzer)
        queries = [
            "How popular is flask?",
            "What testing tools are popular?",
            "flask vs django",
            "Give me a full report",
        ]
        start = time.time()
        for _ in range(50):
            for q in queries:
                engine.query(q)
        elapsed = time.time() - start
        per_query = elapsed / (50 * len(queries)) * 1000  # ms
        assert per_query < 10, f"Query too slow: {per_query:.1f}ms per query"

    def test_store_write_speed(self, store, analyzer):
        """Writing 100 repos should be <1s."""
        start = time.time()
        for i in range(100):
            repo = RepoRecord(
                full_name=f"test/repo-{i}",
                stars=1000 - i,
                description=f"Test repo {i}",
            )
            store.save_repo(repo)
        elapsed = time.time() - start
        assert elapsed < 1.0, f"Store writes too slow: {elapsed:.2f}s for 100 repos"
