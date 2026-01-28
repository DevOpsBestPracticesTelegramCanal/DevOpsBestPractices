# -*- coding: utf-8 -*-
"""
QwenAgent DevOps Test Suite
Tests agent capability to write DevOps code
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from typing import Dict, Any, List
from dataclasses import dataclass

from core.agent import QwenAgent, AgentConfig

@dataclass
class TestCase:
    """Single test case"""
    name: str
    prompt: str
    expected_tool: str = None
    expected_keywords: List[str] = None
    category: str = "general"
    difficulty: str = "easy"

# DevOps Test Cases
DEVOPS_TESTS = [
    # === FILE OPERATIONS ===
    TestCase(
        name="Read Dockerfile",
        prompt="read Dockerfile",
        expected_tool="read",
        category="file",
        difficulty="easy"
    ),
    TestCase(
        name="List directory",
        prompt="list files in current directory",
        expected_tool="ls",
        category="file",
        difficulty="easy"
    ),
    TestCase(
        name="Find YAML files",
        prompt="find all .yaml files",
        expected_tool="glob",
        category="file",
        difficulty="easy"
    ),
    TestCase(
        name="Search for TODO",
        prompt="search for TODO in all python files",
        expected_tool="grep",
        category="file",
        difficulty="medium"
    ),

    # === GIT OPERATIONS ===
    TestCase(
        name="Git status",
        prompt="git status",
        expected_tool="git",
        category="git",
        difficulty="easy"
    ),
    TestCase(
        name="Git log",
        prompt="show last 5 commits",
        expected_tool="git",
        category="git",
        difficulty="easy"
    ),
    TestCase(
        name="Git diff",
        prompt="show git diff",
        expected_tool="git",
        category="git",
        difficulty="easy"
    ),

    # === DOCKER ===
    TestCase(
        name="Create Dockerfile",
        prompt="create a Dockerfile for Python Flask app",
        expected_keywords=["FROM", "python", "COPY", "RUN", "CMD"],
        category="docker",
        difficulty="medium"
    ),
    TestCase(
        name="Docker compose",
        prompt="create docker-compose.yml for web app with postgres",
        expected_keywords=["version", "services", "postgres", "volumes"],
        category="docker",
        difficulty="medium"
    ),

    # === KUBERNETES ===
    TestCase(
        name="K8s Deployment",
        prompt="create kubernetes deployment for nginx",
        expected_keywords=["apiVersion", "kind", "Deployment", "containers"],
        category="kubernetes",
        difficulty="medium"
    ),
    TestCase(
        name="K8s Service",
        prompt="create kubernetes service for the nginx deployment",
        expected_keywords=["kind", "Service", "selector", "port"],
        category="kubernetes",
        difficulty="medium"
    ),

    # === CI/CD ===
    TestCase(
        name="GitHub Actions",
        prompt="create GitHub Actions workflow for Python tests",
        expected_keywords=["name", "on", "jobs", "steps", "pytest"],
        category="cicd",
        difficulty="medium"
    ),
    TestCase(
        name="GitLab CI",
        prompt="create .gitlab-ci.yml for Docker build and push",
        expected_keywords=["stages", "build", "docker", "script"],
        category="cicd",
        difficulty="medium"
    ),

    # === BASH SCRIPTS ===
    TestCase(
        name="Backup script",
        prompt="write bash script to backup a directory to /backup with timestamp",
        expected_keywords=["#!/bin/bash", "tar", "date", "backup"],
        category="bash",
        difficulty="medium"
    ),
    TestCase(
        name="Health check",
        prompt="write bash script to check if a service is running and restart if not",
        expected_keywords=["#!/bin/bash", "if", "systemctl", "restart"],
        category="bash",
        difficulty="medium"
    ),

    # === TERRAFORM ===
    TestCase(
        name="Terraform AWS EC2",
        prompt="write terraform code to create AWS EC2 instance",
        expected_keywords=["resource", "aws_instance", "ami", "instance_type"],
        category="terraform",
        difficulty="hard"
    ),

    # === ANSIBLE ===
    TestCase(
        name="Ansible playbook",
        prompt="write ansible playbook to install nginx",
        expected_keywords=["hosts", "tasks", "apt", "nginx", "state"],
        category="ansible",
        difficulty="hard"
    ),

    # === COMPLEX TASKS ===
    TestCase(
        name="Multi-step deployment",
        prompt="[deep] create a complete CI/CD pipeline: Dockerfile, docker-compose, and GitHub Actions",
        expected_keywords=["FROM", "services", "jobs"],
        category="complex",
        difficulty="hard"
    ),
]


class DevOpsTestRunner:
    """Run DevOps tests against the agent"""

    def __init__(self, agent: QwenAgent):
        self.agent = agent
        self.results: List[Dict[str, Any]] = []

    def run_test(self, test: TestCase) -> Dict[str, Any]:
        """Run single test"""
        print(f"\n  Testing: {test.name}")
        print(f"  Prompt: {test.prompt[:50]}...")

        start = time.time()
        result = self.agent.process(test.prompt)
        elapsed = time.time() - start

        # Evaluate result
        passed = False
        reason = ""

        # Check tool usage
        if test.expected_tool:
            tool_used = any(tc['tool'] == test.expected_tool for tc in result.get('tool_calls', []))
            if tool_used:
                passed = True
                reason = f"Correct tool: {test.expected_tool}"
            else:
                reason = f"Expected tool {test.expected_tool} not used"

        # Check keywords in response
        elif test.expected_keywords:
            response = result.get('response', '').lower()
            found = sum(1 for kw in test.expected_keywords if kw.lower() in response)
            total = len(test.expected_keywords)
            if found >= total * 0.5:  # 50% threshold
                passed = True
                reason = f"Found {found}/{total} keywords"
            else:
                reason = f"Only {found}/{total} keywords found"

        test_result = {
            'name': test.name,
            'category': test.category,
            'difficulty': test.difficulty,
            'passed': passed,
            'reason': reason,
            'time': elapsed,
            'route_method': result.get('route_method', '-'),
            'tool_calls': len(result.get('tool_calls', [])),
            'iterations': result.get('iterations', 0)
        }

        status = "[PASS]" if passed else "[FAIL]"
        print(f"  Result: {status} ({reason})")
        print(f"  Time: {elapsed:.2f}s | Route: {test_result['route_method']}")

        self.results.append(test_result)
        return test_result

    def run_all(self, categories: List[str] = None) -> Dict[str, Any]:
        """Run all tests"""
        print("=" * 60)
        print("  QwenAgent DevOps Test Suite")
        print("=" * 60)

        tests_to_run = DEVOPS_TESTS
        if categories:
            tests_to_run = [t for t in DEVOPS_TESTS if t.category in categories]

        print(f"\n  Running {len(tests_to_run)} tests...")

        for test in tests_to_run:
            try:
                self.run_test(test)
            except Exception as e:
                print(f"  [ERROR] {e}")
                self.results.append({
                    'name': test.name,
                    'passed': False,
                    'reason': str(e),
                    'category': test.category
                })

        return self.summary()

    def summary(self) -> Dict[str, Any]:
        """Generate test summary"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r['passed'])
        failed = total - passed

        # By category
        categories = {}
        for r in self.results:
            cat = r.get('category', 'unknown')
            if cat not in categories:
                categories[cat] = {'passed': 0, 'failed': 0}
            if r['passed']:
                categories[cat]['passed'] += 1
            else:
                categories[cat]['failed'] += 1

        # By route method
        route_stats = {}
        for r in self.results:
            method = r.get('route_method', 'unknown')
            route_stats[method] = route_stats.get(method, 0) + 1

        summary = {
            'total': total,
            'passed': passed,
            'failed': failed,
            'pass_rate': f"{passed/total*100:.1f}%" if total > 0 else "0%",
            'by_category': categories,
            'by_route': route_stats,
            'avg_time': sum(r.get('time', 0) for r in self.results) / total if total > 0 else 0
        }

        print("\n" + "=" * 60)
        print("  SUMMARY")
        print("=" * 60)
        print(f"  Total: {total} | Passed: {passed} | Failed: {failed}")
        print(f"  Pass Rate: {summary['pass_rate']}")
        print(f"  Avg Time: {summary['avg_time']:.2f}s")
        print("\n  By Category:")
        for cat, stats in categories.items():
            print(f"    {cat}: {stats['passed']}/{stats['passed']+stats['failed']}")
        print("\n  By Route Method:")
        for method, count in route_stats.items():
            print(f"    {method}: {count}")
        print("=" * 60)

        return summary


def run_quick_tests():
    """Run quick sanity tests"""
    print("Quick DevOps Tests")
    print("-" * 40)

    config = AgentConfig(model="qwen2.5-coder:3b", max_iterations=3)
    agent = QwenAgent(config)
    runner = DevOpsTestRunner(agent)

    # Run only easy file tests
    runner.run_all(categories=['file', 'git'])


def run_full_tests():
    """Run full test suite"""
    config = AgentConfig(model="qwen2.5-coder:3b", max_iterations=5)
    agent = QwenAgent(config)
    runner = DevOpsTestRunner(agent)
    runner.run_all()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', action='store_true', help='Run full test suite')
    parser.add_argument('--category', help='Test specific category')
    args = parser.parse_args()

    if args.full:
        run_full_tests()
    elif args.category:
        config = AgentConfig(model="qwen2.5-coder:3b")
        agent = QwenAgent(config)
        runner = DevOpsTestRunner(agent)
        runner.run_all(categories=[args.category])
    else:
        run_quick_tests()
