# -*- coding: utf-8 -*-
"""
GitHubCollector — fetches top Python repos via the GitHub REST API v3.

Uses GITHUB_TOKEN env var for authentication (5000 req/hour).
Handles pagination, rate limiting, and incremental collection.
"""

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RepoMeta:
    """Raw metadata fetched from GitHub for a single repository."""
    full_name: str           # "pallets/flask"
    stars: int = 0
    forks: int = 0
    language: str = "Python"
    description: str = ""
    topics: List[str] = field(default_factory=list)
    default_branch: str = "main"
    created_at: str = ""
    updated_at: str = ""
    license: str = ""
    readme_content: str = ""
    file_tree: List[str] = field(default_factory=list)
    requirements: str = ""
    setup_cfg: str = ""
    pyproject: str = ""
    dockerfile: str = ""
    ci_configs: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# GitHubCollector
# ---------------------------------------------------------------------------

class GitHubCollector:
    """Collect top GitHub repos via REST API v3."""

    API_BASE = "https://api.github.com"
    SEARCH_REPOS = "/search/repositories"
    PER_PAGE = 100  # max allowed by GitHub

    def __init__(
        self,
        token: Optional[str] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ):
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._session = requests.Session()
        if self._token:
            self._session.headers["Authorization"] = f"token {self._token}"
        self._session.headers["Accept"] = "application/vnd.github.v3+json"
        self._session.headers["User-Agent"] = "QwenAgent-OSS-Collector/1.0"
        self._on_progress = on_progress

        # Rate limit tracking
        self._rate_remaining = 5000
        self._rate_reset = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect_top_repos(
        self,
        language: str = "python",
        count: int = 1000,
        min_stars: int = 100,
    ) -> List[RepoMeta]:
        """
        Fetch the top `count` repos for a language sorted by stars.

        GitHub search API returns max 1000 results. For >1000, multiple
        queries with different star ranges would be needed (not implemented
        in MVP).
        """
        repos: List[RepoMeta] = []
        pages = min((count + self.PER_PAGE - 1) // self.PER_PAGE, 10)  # max 10 pages

        for page in range(1, pages + 1):
            self._report_progress(len(repos), count, f"Fetching page {page}/{pages}")
            query = f"language:{language} stars:>={min_stars}"
            params = {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": self.PER_PAGE,
                "page": page,
            }
            data = self._get(self.SEARCH_REPOS, params=params)
            if not data or "items" not in data:
                logger.warning("[GitHubCollector] No items on page %d", page)
                break

            for item in data["items"]:
                repos.append(self._item_to_meta(item))
                if len(repos) >= count:
                    break
            if len(repos) >= count:
                break

        logger.info("[GitHubCollector] Collected %d repo metadata records", len(repos))
        return repos

    def enrich_repo(self, meta: RepoMeta) -> RepoMeta:
        """
        Fetch additional details for a repo: README, file tree,
        dependency files, Dockerfile, CI configs.
        """
        owner_repo = meta.full_name
        self._report_progress(0, 5, f"Enriching {owner_repo}")

        # 1. README
        meta.readme_content = self._fetch_readme(owner_repo)

        # 2. File tree (top-level + common dirs)
        meta.file_tree = self._fetch_tree(owner_repo, meta.default_branch)

        # 3. Dependency files
        meta.requirements = self._fetch_file(owner_repo, "requirements.txt")
        meta.setup_cfg = self._fetch_file(owner_repo, "setup.py")
        meta.pyproject = self._fetch_file(owner_repo, "pyproject.toml")

        # 4. Dockerfile
        meta.dockerfile = self._fetch_file(owner_repo, "Dockerfile")

        # 5. CI configs
        meta.ci_configs = self._fetch_ci_configs(owner_repo, meta.file_tree)

        return meta

    def get_rate_limit(self) -> Dict[str, Any]:
        """Check current rate limit status."""
        data = self._get("/rate_limit")
        if data and "rate" in data:
            return data["rate"]
        return {
            "limit": 5000,
            "remaining": self._rate_remaining,
            "reset": self._rate_reset,
        }

    # ------------------------------------------------------------------
    # Private: HTTP
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """GET request with rate limit handling."""
        url = f"{self.API_BASE}{path}" if path.startswith("/") else path

        # Pre-check rate limit
        if self._rate_remaining <= 1 and self._rate_reset > time.time():
            wait = self._rate_reset - time.time() + 1
            logger.info("[GitHubCollector] Rate limit hit, sleeping %.0fs", wait)
            time.sleep(wait)

        try:
            resp = self._session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            logger.error("[GitHubCollector] Request error: %s", exc)
            return None

        # Update rate limit tracking
        self._rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 5000))
        self._rate_reset = float(resp.headers.get("X-RateLimit-Reset", 0))

        if resp.status_code == 403 or resp.status_code == 429:
            wait = max(self._rate_reset - time.time(), 60)
            logger.warning("[GitHubCollector] Rate limited (HTTP %d), sleeping %.0fs",
                           resp.status_code, wait)
            time.sleep(wait)
            return self._get(path, params)  # retry once

        if resp.status_code == 404:
            return None

        if resp.status_code != 200:
            logger.warning("[GitHubCollector] HTTP %d for %s", resp.status_code, path)
            return None

        return resp.json()

    # ------------------------------------------------------------------
    # Private: Fetch helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _item_to_meta(item: Dict) -> RepoMeta:
        lic = item.get("license") or {}
        return RepoMeta(
            full_name=item.get("full_name", ""),
            stars=item.get("stargazers_count", 0),
            forks=item.get("forks_count", 0),
            language=item.get("language", "Python"),
            description=item.get("description", "") or "",
            topics=item.get("topics", []),
            default_branch=item.get("default_branch", "main"),
            created_at=item.get("created_at", ""),
            updated_at=item.get("updated_at", ""),
            license=lic.get("spdx_id", "") if isinstance(lic, dict) else "",
        )

    def _fetch_readme(self, owner_repo: str) -> str:
        data = self._get(f"/repos/{owner_repo}/readme")
        if not data or "content" not in data:
            return ""
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _fetch_file(self, owner_repo: str, path: str) -> str:
        data = self._get(f"/repos/{owner_repo}/contents/{path}")
        if not data or "content" not in data:
            return ""
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _fetch_tree(self, owner_repo: str, branch: str) -> List[str]:
        """Fetch recursive file tree (truncated for large repos)."""
        data = self._get(f"/repos/{owner_repo}/git/trees/{branch}?recursive=1")
        if not data or "tree" not in data:
            return []
        return [item["path"] for item in data["tree"] if "path" in item][:5000]

    def _fetch_ci_configs(self, owner_repo: str, file_tree: List[str]) -> List[str]:
        """Fetch CI config file contents."""
        configs = []
        ci_files = [f for f in file_tree if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))]
        # Limit to 5 CI config files to stay under rate limit
        for cf in ci_files[:5]:
            content = self._fetch_file(owner_repo, cf)
            if content:
                configs.append(content)
        return configs

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def _report_progress(self, current: int, total: int, msg: str) -> None:
        if self._on_progress:
            self._on_progress(current, total, msg)
        logger.debug("[GitHubCollector] %s (%d/%d)", msg, current, total)
