# -*- coding: utf-8 -*-
"""Tests for core.oss.github_collector — GitHub API client (all mocked)."""

import os
import sys
import json
import base64
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.oss.github_collector import GitHubCollector, RepoMeta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_api_item(name="owner/repo", stars=1000, forks=100, lang="Python",
                   desc="A repo", topics=None, branch="main", lic="MIT"):
    return {
        "full_name": name,
        "stargazers_count": stars,
        "forks_count": forks,
        "language": lang,
        "description": desc,
        "topics": topics or [],
        "default_branch": branch,
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "license": {"spdx_id": lic} if lic else None,
    }


def _make_search_response(items, total=1000):
    return {"total_count": total, "items": items}


def _make_content_response(text):
    encoded = base64.b64encode(text.encode()).decode()
    return {"content": encoded, "encoding": "base64"}


def _make_tree_response(paths):
    return {"tree": [{"path": p, "type": "blob"} for p in paths]}


@pytest.fixture
def collector():
    """Collector with no token (will still work, just lower rate limit)."""
    return GitHubCollector(token="fake-token-for-tests")


# =========================================================================
# Test: Meta Parsing
# =========================================================================

class TestMetaParsing:
    def test_item_to_meta(self):
        item = _make_api_item("pallets/flask", 65000, 16000, "Python",
                              "Web framework", ["python", "web"], "main", "BSD-3-Clause")
        meta = GitHubCollector._item_to_meta(item)
        assert meta.full_name == "pallets/flask"
        assert meta.stars == 65000
        assert meta.forks == 16000
        assert meta.language == "Python"
        assert meta.description == "Web framework"
        assert meta.topics == ["python", "web"]
        assert meta.default_branch == "main"
        assert meta.license == "BSD-3-Clause"

    def test_item_to_meta_no_license(self):
        item = _make_api_item(lic=None)
        meta = GitHubCollector._item_to_meta(item)
        assert meta.license == ""

    def test_item_to_meta_no_description(self):
        item = _make_api_item(desc=None)
        meta = GitHubCollector._item_to_meta(item)
        assert meta.description == ""


# =========================================================================
# Test: Collect Top Repos (mocked)
# =========================================================================

class TestCollectTopRepos:
    @patch.object(GitHubCollector, "_get")
    def test_single_page(self, mock_get, collector):
        items = [_make_api_item(f"owner/repo{i}", stars=1000-i) for i in range(5)]
        mock_get.return_value = _make_search_response(items, total=5)

        repos = collector.collect_top_repos(count=5)
        assert len(repos) == 5
        assert repos[0].full_name == "owner/repo0"

    @patch.object(GitHubCollector, "_get")
    def test_multi_page(self, mock_get, collector):
        page1 = [_make_api_item(f"owner/repo{i}", stars=1000-i) for i in range(100)]
        page2 = [_make_api_item(f"owner/repo{i}", stars=900-i) for i in range(100, 150)]
        mock_get.side_effect = [
            _make_search_response(page1),
            _make_search_response(page2),
        ]

        repos = collector.collect_top_repos(count=150)
        assert len(repos) == 150
        assert mock_get.call_count == 2

    @patch.object(GitHubCollector, "_get")
    def test_empty_response(self, mock_get, collector):
        mock_get.return_value = {"items": []}
        repos = collector.collect_top_repos(count=10)
        assert len(repos) == 0

    @patch.object(GitHubCollector, "_get")
    def test_none_response(self, mock_get, collector):
        mock_get.return_value = None
        repos = collector.collect_top_repos(count=10)
        assert len(repos) == 0

    @patch.object(GitHubCollector, "_get")
    def test_count_limit(self, mock_get, collector):
        items = [_make_api_item(f"owner/repo{i}") for i in range(100)]
        mock_get.return_value = _make_search_response(items)
        repos = collector.collect_top_repos(count=10)
        assert len(repos) == 10


# =========================================================================
# Test: Enrich Repo (mocked)
# =========================================================================

class TestEnrichRepo:
    @patch.object(GitHubCollector, "_get")
    def test_enrich_readme(self, mock_get, collector):
        readme_text = "# My Project\nHello world"
        mock_get.side_effect = [
            _make_content_response(readme_text),  # README
            _make_tree_response(["src/main.py"]),  # tree
            None,  # requirements.txt
            None,  # setup.py
            None,  # pyproject.toml
            None,  # Dockerfile
        ]
        meta = RepoMeta(full_name="owner/repo")
        enriched = collector.enrich_repo(meta)
        assert "My Project" in enriched.readme_content
        assert "src/main.py" in enriched.file_tree

    @patch.object(GitHubCollector, "_get")
    def test_enrich_requirements(self, mock_get, collector):
        mock_get.side_effect = [
            None,  # README
            _make_tree_response(["requirements.txt"]),
            _make_content_response("flask>=2.0\npytest"),  # requirements
            None,  # setup.py
            None,  # pyproject.toml
            None,  # Dockerfile
        ]
        meta = RepoMeta(full_name="owner/repo")
        enriched = collector.enrich_repo(meta)
        assert "flask" in enriched.requirements

    @patch.object(GitHubCollector, "_get")
    def test_enrich_ci_configs(self, mock_get, collector):
        ci_content = "name: CI\non: [push]\njobs: ..."
        mock_get.side_effect = [
            None,  # README
            _make_tree_response([".github/workflows/ci.yml"]),
            None,  # requirements
            None,  # setup.py
            None,  # pyproject.toml
            None,  # Dockerfile
            _make_content_response(ci_content),  # CI config
        ]
        meta = RepoMeta(full_name="owner/repo")
        enriched = collector.enrich_repo(meta)
        assert len(enriched.ci_configs) == 1
        assert "CI" in enriched.ci_configs[0]


# =========================================================================
# Test: Rate Limit
# =========================================================================

class TestRateLimit:
    def test_rate_limit_tracking(self, collector):
        assert collector._rate_remaining == 5000

    @patch.object(GitHubCollector, "_get")
    def test_get_rate_limit(self, mock_get, collector):
        mock_get.return_value = {
            "rate": {"limit": 5000, "remaining": 4999, "reset": 1234567890}
        }
        rl = collector.get_rate_limit()
        assert rl["limit"] == 5000
        assert rl["remaining"] == 4999

    @patch.object(GitHubCollector, "_get")
    def test_get_rate_limit_fallback(self, mock_get, collector):
        mock_get.return_value = None
        rl = collector.get_rate_limit()
        assert "remaining" in rl


# =========================================================================
# Test: Progress Callback
# =========================================================================

class TestProgressCallback:
    @patch.object(GitHubCollector, "_get")
    def test_progress_called(self, mock_get):
        progress_calls = []
        collector = GitHubCollector(
            token="fake",
            on_progress=lambda cur, tot, msg: progress_calls.append((cur, tot, msg))
        )
        items = [_make_api_item(f"owner/repo{i}") for i in range(5)]
        mock_get.return_value = _make_search_response(items)
        collector.collect_top_repos(count=5)
        assert len(progress_calls) > 0


# =========================================================================
# Test: RepoMeta Dataclass
# =========================================================================

class TestRepoMetaDataclass:
    def test_defaults(self):
        m = RepoMeta(full_name="a/b")
        assert m.stars == 0
        assert m.topics == []
        assert m.readme_content == ""
        assert m.file_tree == []
        assert m.ci_configs == []

    def test_full_init(self):
        m = RepoMeta(
            full_name="x/y",
            stars=100, forks=50,
            language="Python",
            description="test",
            topics=["a", "b"],
            default_branch="main",
            license="MIT",
        )
        assert m.full_name == "x/y"
        assert m.stars == 100
        assert m.license == "MIT"
