# -*- coding: utf-8 -*-
"""
QwenAgent Router - NO-LLM Pattern Matching + LLM Fallback
Based on DUCS v3 architecture: 85%+ NO-LLM routing
"""

import re
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

@dataclass
class RouteResult:
    """Result of routing decision"""
    tool: Optional[str]
    params: Dict[str, Any]
    confidence: float
    method: str  # 'pattern', 'llm', 'direct'
    reasoning: str = ""

class PatternRouter:
    """
    NO-LLM Pattern Router (TIER 0)
    Handles 85%+ of requests without LLM
    """

    # Pattern definitions with tool mappings
    PATTERNS = [
        # READ patterns
        (r'(?:read|show|cat|open|view|display)\s+(?:file\s+)?["\']?([^\s"\']+)["\']?',
         'read', lambda m: {'file_path': m.group(1)}, 0.95),
        (r'(?:what\'?s?\s+in|contents?\s+of)\s+["\']?([^\s"\']+)["\']?',
         'read', lambda m: {'file_path': m.group(1)}, 0.90),

        # WRITE patterns
        (r'(?:write|create|save)\s+["\']?(.+?)["\']?\s+(?:to|in)\s+["\']?([^\s"\']+)["\']?',
         'write', lambda m: {'content': m.group(1), 'file_path': m.group(2)}, 0.90),
        (r'(?:create|new)\s+file\s+["\']?([^\s"\']+)["\']?',
         'write', lambda m: {'file_path': m.group(1), 'content': ''}, 0.85),

        # LS patterns
        (r'(?:ls|list|dir)\s*["\']?([^\s"\']*)["\']?$',
         'ls', lambda m: {'path': m.group(1) or None}, 0.95),
        (r'(?:list|show)\s+(?:files|directory|folder|contents?)\s*(?:in|of)?\s*["\']?([^\s"\']*)["\']?',
         'ls', lambda m: {'path': m.group(1) or None}, 0.90),
        (r'what\s+(?:files|is)\s+(?:are\s+)?(?:in|here)',
         'ls', lambda m: {'path': None}, 0.85),

        # GLOB patterns
        (r'(?:find|search|glob)\s+["\']?(\*\*?[^\s"\']+)["\']?',
         'glob', lambda m: {'pattern': m.group(1)}, 0.95),
        (r'find\s+(?:all\s+)?(?:files?\s+)?(?:with\s+)?\.(\w+)\s+(?:files?|extension)',
         'glob', lambda m: {'pattern': f'**/*.{m.group(1)}'}, 0.90),
        (r'find\s+all\s+\.(\w+)\s+files?',
         'glob', lambda m: {'pattern': f'**/*.{m.group(1)}'}, 0.90),

        # GREP patterns
        (r'(?:grep|search|find)\s+["\'](.+?)["\']\s+(?:in\s+)?["\']?([^\s"\']+)?["\']?',
         'grep', lambda m: {'pattern': m.group(1), 'path': m.group(2)}, 0.90),
        (r'search\s+(?:for\s+)?["\'](.+?)["\']',
         'grep', lambda m: {'pattern': m.group(1)}, 0.85),

        # BASH patterns
        (r'(?:run|exec|execute)\s+[`"\']?(.+?)[`"\']?$',
         'bash', lambda m: {'command': m.group(1)}, 0.90),
        (r'^[`$]\s*(.+)$',
         'bash', lambda m: {'command': m.group(1)}, 0.95),

        # GIT patterns
        (r'git\s+(status|log|diff|branch|commit|push|pull|add|checkout|merge|stash|fetch|rebase|reset|show)',
         'git', lambda m: {'command': m.group(0).replace('git ', '')}, 0.95),
        (r'(?:show\s+)?git\s+(status|log|diff)',
         'git', lambda m: {'command': m.group(1)}, 0.90),

        # EDIT patterns
        (r'(?:replace|change|edit)\s+["\'](.+?)["\']\s+(?:to|with)\s+["\'](.+?)["\']\s+in\s+(?:file\s+)?["\']?([^\s"\']+)["\']?',
         'edit', lambda m: {'old_string': m.group(1), 'new_string': m.group(2), 'file_path': m.group(3)}, 0.90),
        # "in FILE replace "X" with "Y""
        (r'in\s+(?:file\s+)?["\']?([^\s"\']+)["\']?\s+(?:replace|change)\s+["\'](.+?)["\']\s+(?:to|with)\s+["\'](.+?)["\']',
         'edit', lambda m: {'file_path': m.group(1), 'old_string': m.group(2), 'new_string': m.group(3)}, 0.90),

    ]

    def route(self, user_input: str) -> RouteResult:
        """
        Route user input to appropriate tool using pattern matching
        Returns RouteResult with tool, params, confidence
        """
        text = user_input.strip()

        for pattern, tool, param_fn, confidence in self.PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    params = param_fn(match)
                    return RouteResult(
                        tool=tool,
                        params=params,
                        confidence=confidence,
                        method='pattern',
                        reasoning=f"Matched pattern for {tool}"
                    )
                except:
                    continue

        # No pattern matched - needs LLM
        return RouteResult(
            tool=None,
            params={},
            confidence=0.0,
            method='none',
            reasoning="No pattern matched, requires LLM"
        )


class IntentClassifier:
    """
    Simple intent classification (TIER 1)
    Classifies intent when patterns don't match exactly
    """

    INTENTS = {
        'file_read': ['read', 'show', 'cat', 'view', 'open', 'display', 'content'],
        'file_write': ['write', 'create', 'save', 'new file', 'make file'],
        'file_edit': ['edit', 'change', 'replace', 'modify', 'update'],
        'file_list': ['list', 'ls', 'dir', 'files', 'directory', 'folder'],
        'file_search': ['find', 'search', 'grep', 'look for', 'locate'],
        'git_operation': ['git', 'commit', 'push', 'pull', 'branch', 'merge'],
        'shell_command': ['run', 'execute', 'command', 'shell', 'terminal'],
        'code_generate': ['write code', 'create function', 'implement', 'code for'],
        'code_explain': ['explain', 'what does', 'how does', 'understand'],
        'code_fix': ['fix', 'bug', 'error', 'issue', 'problem', 'debug'],
    }

    INTENT_TO_TOOL = {
        'file_read': 'read',
        'file_write': 'write',
        'file_edit': 'edit',
        'file_list': 'ls',
        'file_search': 'grep',
        'git_operation': 'git',
        'shell_command': 'bash',
    }

    def classify(self, text: str) -> Tuple[str, float]:
        """Classify intent of user input"""
        text_lower = text.lower()
        scores = {}

        for intent, keywords in self.INTENTS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[intent] = score / len(keywords)

        if not scores:
            return 'unknown', 0.0

        best_intent = max(scores, key=scores.get)
        return best_intent, scores[best_intent]


class HybridRouter:
    """
    Hybrid Router combining:
    - TIER 0: Pattern matching (instant, 85%+)
    - TIER 1: Intent classification (fast)
    - TIER 2: LLM fallback (when needed)
    """

    def __init__(self):
        self.pattern_router = PatternRouter()
        self.intent_classifier = IntentClassifier()
        self.stats = {
            'total': 0,
            'pattern_hits': 0,
            'intent_hits': 0,
            'llm_fallback': 0
        }

    def route(self, user_input: str) -> RouteResult:
        """Route request through hybrid system"""
        self.stats['total'] += 1

        # TIER 0: Pattern matching
        result = self.pattern_router.route(user_input)
        if result.confidence >= 0.85:
            self.stats['pattern_hits'] += 1
            return result

        # TIER 1: Intent classification
        intent, confidence = self.intent_classifier.classify(user_input)
        if confidence >= 0.5 and intent in self.intent_classifier.INTENT_TO_TOOL:
            self.stats['intent_hits'] += 1
            tool = self.intent_classifier.INTENT_TO_TOOL[intent]
            return RouteResult(
                tool=tool,
                params={'_raw_input': user_input},
                confidence=confidence * 0.7,
                method='intent',
                reasoning=f"Intent: {intent}"
            )

        # TIER 2: LLM needed
        self.stats['llm_fallback'] += 1
        return RouteResult(
            tool=None,
            params={},
            confidence=0.0,
            method='llm_required',
            reasoning="Complex request requires LLM"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics"""
        total = self.stats['total'] or 1
        return {
            **self.stats,
            'pattern_rate': f"{self.stats['pattern_hits']/total*100:.1f}%",
            'intent_rate': f"{self.stats['intent_hits']/total*100:.1f}%",
            'llm_rate': f"{self.stats['llm_fallback']/total*100:.1f}%",
            'no_llm_rate': f"{(self.stats['pattern_hits']+self.stats['intent_hits'])/total*100:.1f}%"
        }
