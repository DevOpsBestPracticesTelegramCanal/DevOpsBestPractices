# -*- coding: utf-8 -*-
"""
Tier 1.5 Classifier - Lightweight LLM Classification for Edge Cases
====================================================================

Промежуточный слой между Tier 1 (NLP) и Tier 4 (DEEP Mode).
Использует малую модель (Qwen 3B) для быстрой классификации неоднозначных команд.

Когда использовать:
    - Pattern Router (Tier 0) не сработал
    - Bilingual NLP (Tier 1) выдал confidence < 0.8
    - Перед эскалацией в DEEP Mode (Tier 4)

Цель:
    - Latency: < 500ms (10x быстрее чем DEEP Mode)
    - Accuracy: 70%+ для edge cases
    - Снизить Escalation Rate с 8.33% до <5%

Author: QwenAgent Team
Date: 2026-02-04
"""

import time
from typing import Dict, Any, Optional
from .ollama_client import OllamaClient


class Tier15Classifier:
    """
    Lightweight LLM classifier for edge cases

    Uses Qwen 3B (fast, CPU-friendly) to classify ambiguous commands
    that didn't match in Tier 0 (Regex) or Tier 1 (NLP).
    """

    def __init__(self, model: str = "qwen2.5-coder:3b", timeout: int = 500):
        """
        Args:
            model: Model name to use (default: qwen2.5-coder:3b)
            timeout: Timeout in milliseconds (default: 500ms)
        """
        # Use lightweight model for fast classification
        self.model = model
        self.timeout = timeout
        self.temperature = 0.1  # Low temperature for deterministic output

        self.client = OllamaClient()

        # Available tools for classification
        self.tools = [
            "read",      # Read file contents
            "ls",        # List directory
            "grep",      # Search in files
            "edit",      # Edit file
            "bash",      # Execute bash command
            "git",       # Git operations
            "unknown",   # Cannot classify → DEEP Mode
        ]

        # Statistics
        self.stats = {
            "total_requests": 0,
            "successful_classifications": 0,
            "unknown_classifications": 0,
            "timeouts": 0,
            "errors": 0,
        }

    def _build_prompt(self, query: str) -> str:
        """
        Build classification prompt for the model

        Args:
            query: User command

        Returns:
            Formatted prompt
        """
        prompt = f"""You are a command classifier. Given a user command, identify which tool is needed.

Available tools:
- read: Read file contents (e.g., "show me config", "what's in the file")
- ls: List directory contents (e.g., "list files", "what's here")
- grep: Search for text in files (e.g., "find error", "search for TODO")
- edit: Edit file contents (e.g., "change line 10", "fix the typo")
- bash: Execute bash command (e.g., "run script", "execute command")
- git: Git operations (e.g., "commit changes", "push code")
- unknown: Cannot classify with confidence (complex or ambiguous query)

User command: "{query}"

Output ONLY the tool name (one word). Examples:
- "show me what's in config.py" → read
- "find all TODOs" → grep
- "what files are here" → ls
- "how to implement OAuth" → unknown

Tool:"""

        return prompt

    def classify(self, query: str) -> Dict[str, Any]:
        """
        Classify command using lightweight LLM

        Args:
            query: User command

        Returns:
            Dict with classification result:
                {
                    "tool": str or None,
                    "confidence": float,
                    "latency_ms": int,
                    "method": "tier1_5_llm"
                }
        """
        self.stats["total_requests"] += 1
        start_time = time.time()

        try:
            # Build prompt
            prompt = self._build_prompt(query)

            # Call LLM with timeout
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                temperature=self.temperature,
                max_tokens=10,  # Only need one word
                timeout=self.timeout / 1000.0  # Convert ms to seconds
            )

            # Extract tool name
            tool_name = response.strip().lower()

            # Validate tool name
            if tool_name not in self.tools:
                # LLM returned invalid tool
                self.stats["unknown_classifications"] += 1
                return {
                    "tool": None,
                    "confidence": 0.0,
                    "latency_ms": int((time.time() - start_time) * 1000),
                    "method": "tier1_5_llm",
                    "reason": f"invalid_tool_{tool_name}"
                }

            # Check if LLM said "unknown"
            if tool_name == "unknown":
                self.stats["unknown_classifications"] += 1
                return {
                    "tool": None,
                    "confidence": 0.0,
                    "latency_ms": int((time.time() - start_time) * 1000),
                    "method": "tier1_5_llm",
                    "reason": "llm_classified_as_unknown"
                }

            # Success!
            self.stats["successful_classifications"] += 1
            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "tool": tool_name,
                "confidence": 0.7,  # Medium confidence (LLM-based)
                "latency_ms": latency_ms,
                "method": "tier1_5_llm"
            }

        except TimeoutError:
            self.stats["timeouts"] += 1
            return {
                "tool": None,
                "confidence": 0.0,
                "latency_ms": self.timeout,
                "method": "tier1_5_llm",
                "reason": "timeout"
            }

        except Exception as e:
            self.stats["errors"] += 1
            return {
                "tool": None,
                "confidence": 0.0,
                "latency_ms": int((time.time() - start_time) * 1000),
                "method": "tier1_5_llm",
                "reason": f"error_{type(e).__name__}"
            }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get classifier statistics

        Returns:
            Dict with statistics
        """
        total = self.stats["total_requests"]
        if total == 0:
            return {**self.stats, "success_rate": 0.0}

        success_rate = (self.stats["successful_classifications"] / total) * 100

        return {
            **self.stats,
            "success_rate": round(success_rate, 2)
        }

    def reset_stats(self):
        """Reset statistics"""
        self.stats = {
            "total_requests": 0,
            "successful_classifications": 0,
            "unknown_classifications": 0,
            "timeouts": 0,
            "errors": 0,
        }


# --- EXAMPLE USAGE ---
if __name__ == "__main__":
    classifier = Tier15Classifier()

    # Test edge cases
    edge_cases = [
        "show me what's in the config file",
        "check the logs for errors",
        "what files are in this directory",
        "change line 42 in main.py",
        "how to implement JWT authentication",  # Complex → unknown
        "run the tests",
    ]

    print("=" * 70)
    print("Tier 1.5 Classifier - Edge Cases Test")
    print("=" * 70)

    for query in edge_cases:
        result = classifier.classify(query)
        tool = result.get("tool")
        latency = result.get("latency_ms")
        reason = result.get("reason", "")

        if tool:
            print(f"[OK] {query:45} -> {tool:8} ({latency}ms)")
        else:
            print(f"[UNKNOWN] {query:45} -> {reason} ({latency}ms)")

    print("\n" + "=" * 70)
    print("Classifier Statistics:")
    print("=" * 70)

    stats = classifier.get_stats()
    print(f"Total Requests:    {stats['total_requests']}")
    print(f"Successful:        {stats['successful_classifications']}")
    print(f"Unknown:           {stats['unknown_classifications']}")
    print(f"Timeouts:          {stats['timeouts']}")
    print(f"Errors:            {stats['errors']}")
    print(f"Success Rate:      {stats['success_rate']:.2f}%")

    print("\n" + "=" * 70)
    if stats['success_rate'] >= 70:
        print("[OK] Success Rate: PASS (target: >=70%)")
    else:
        print("[FAIL] Success Rate: FAIL (target: >=70%)")
