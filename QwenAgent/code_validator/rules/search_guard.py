"""
Week 22: Search-Only / Tutorial-Dump Guard

Detects responses that are NOT real code but instead:
  - Search results or link dumps ("see https://...", "check out ...")
  - Tutorial references without implementation
  - "Here's how to install..." without actual code
  - Placeholder comments with no logic

These responses score well on syntax (they parse as Python comments/strings)
but provide zero value as generated code.
"""

import re
from .base import Rule, RuleResult, RuleSeverity


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# URLs / link-dump patterns
_URL_RE = re.compile(r'https?://\S+')
_LINK_DUMP_RE = re.compile(
    r'(?:see|check\s+out|visit|refer\s+to|documentation\s+at|'
    r'more\s+info|for\s+details|official\s+docs|tutorial|'
    r'read\s+more|follow\s+this|guide\s+at)\s',
    re.IGNORECASE,
)

# Install / setup instructions without code
_INSTALL_RE = re.compile(
    r'(?:pip\s+install|npm\s+install|apt\s+get|brew\s+install|'
    r'curl\s+-[sLO]|wget\s+|git\s+clone)\b',
    re.IGNORECASE,
)

# "Step N:" tutorial pattern
_STEP_RE = re.compile(r'(?:step\s+\d|first,?\s+|then,?\s+|next,?\s+|finally,?\s+)', re.IGNORECASE)

# Placeholder / stub patterns (no real logic)
_PLACEHOLDER_RE = re.compile(
    r'(?:TODO|FIXME|pass\s*$|\.\.\.|\#\s*your\s+code\s+here|'
    r'\#\s*implement|NotImplementedError|raise\s+NotImplementedError)',
    re.MULTILINE,
)

# Comment-heavy: lines that are mostly comments or docstrings
_COMMENT_LINE_RE = re.compile(r'^\s*(?:#|"""|\'\'\'|\s*$)')


class SearchGuardRule(Rule):
    """Detects search-only / tutorial-dump responses that contain
    links and instructions instead of actual implementation code.

    Severity: WARNING (score penalty, not blocking).
    """

    name = "search_guard"
    severity = RuleSeverity.WARNING
    weight = 2.0

    def __init__(
        self,
        max_url_ratio: float = 0.3,
        max_comment_ratio: float = 0.8,
        min_code_lines: int = 3,
    ):
        self.max_url_ratio = max_url_ratio
        self.max_comment_ratio = max_comment_ratio
        self.min_code_lines = min_code_lines

    def check(self, code: str) -> RuleResult:
        if not code or not code.strip():
            return self._fail(0.0, ["Empty response"])

        lines = code.strip().splitlines()
        total = len(lines)
        if total == 0:
            return self._fail(0.0, ["Empty response"])

        messages = []
        penalties = 0.0

        # 1. URL density check
        url_lines = sum(1 for ln in lines if _URL_RE.search(ln))
        url_ratio = url_lines / total
        if url_ratio > self.max_url_ratio:
            messages.append(
                f"URL-heavy response: {url_lines}/{total} lines contain URLs "
                f"({url_ratio:.0%} > {self.max_url_ratio:.0%})"
            )
            penalties += 0.3

        # 2. Link-dump language
        link_dump_count = sum(1 for ln in lines if _LINK_DUMP_RE.search(ln))
        if link_dump_count >= 3:
            messages.append(
                f"Link-dump detected: {link_dump_count} lines with "
                f"'see/check out/refer to' patterns"
            )
            penalties += 0.3

        # 3. Install-only (no implementation)
        install_lines = sum(1 for ln in lines if _INSTALL_RE.search(ln))
        code_lines = sum(
            1 for ln in lines
            if not _COMMENT_LINE_RE.match(ln) and not _INSTALL_RE.search(ln)
        )
        if install_lines >= 2 and code_lines < self.min_code_lines:
            messages.append(
                f"Install-only response: {install_lines} install commands, "
                f"only {code_lines} actual code lines"
            )
            penalties += 0.3

        # 4. Comment-heavy (no real logic)
        comment_lines = sum(1 for ln in lines if _COMMENT_LINE_RE.match(ln))
        comment_ratio = comment_lines / total
        if comment_ratio > self.max_comment_ratio and total > 5:
            messages.append(
                f"Comment-heavy: {comment_lines}/{total} lines are comments/blanks "
                f"({comment_ratio:.0%} > {self.max_comment_ratio:.0%})"
            )
            penalties += 0.2

        # 5. Placeholder-heavy
        placeholder_count = len(_PLACEHOLDER_RE.findall(code))
        if placeholder_count >= 3:
            messages.append(
                f"Placeholder-heavy: {placeholder_count} TODO/pass/NotImplementedError stubs"
            )
            penalties += 0.2

        # 6. Step-by-step tutorial without code
        step_count = len(_STEP_RE.findall(code))
        if step_count >= 3 and code_lines < self.min_code_lines:
            messages.append(
                f"Tutorial-style: {step_count} step markers, "
                f"only {code_lines} code lines"
            )
            penalties += 0.2

        # Calculate final score
        score = max(0.0, 1.0 - penalties)
        passed = score >= 0.5

        if not messages:
            return self._ok(1.0)
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=score,
            severity=self.severity,
            messages=messages,
        )
