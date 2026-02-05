# -*- coding: utf-8 -*-
"""
Test Autonomous Workflow via Server API
=======================================

Tests the complete workflow through the actual QwenCode server:
1. Submits task via /api/chat
2. Server executes with approval checks
3. Monitors approval requests via /api/approvals/pending
4. Responds to approvals via /api/approve
5. Gets final result

Usage:
    python test_autonomous_api.py

Requirements:
    - Server running on localhost:5002
    - ApprovalManager enabled on server
"""

import requests
import time
import json
import threading
from datetime import datetime
from typing import Dict, Any, Optional

SERVER_URL = "http://localhost:5002"


def log(msg: str, level: str = "INFO"):
    """Log with timestamp"""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    prefix = {"INFO": "[*]", "OK": "[+]", "WARN": "[!]", "ERROR": "[X]", "WAIT": "[?]"}
    # Handle unicode for Windows console
    try:
        print(f"{prefix.get(level, '[.]')} {ts} {msg}")
    except UnicodeEncodeError:
        safe_msg = msg.encode('ascii', 'replace').decode('ascii')
        print(f"{prefix.get(level, '[.]')} {ts} {safe_msg}")


def check_server() -> bool:
    """Check if server is running"""
    try:
        r = requests.get(f"{SERVER_URL}/api/health", timeout=5)
        data = r.json()
        log(f"Server status: {data.get('status', 'unknown')}")
        log(f"Approval manager: {data.get('approval_manager', False)}")
        return data.get("status") == "ok"
    except Exception as e:
        log(f"Server not available: {e}", "ERROR")
        return False


def get_pending_approvals() -> list:
    """Get pending approval requests"""
    try:
        r = requests.get(f"{SERVER_URL}/api/approval/pending", timeout=5)
        return r.json().get("pending", [])
    except:
        return []


def approve_request(request_id: str, choice: str = "y") -> bool:
    """Approve or reject a request"""
    try:
        if choice == "y":
            r = requests.post(f"{SERVER_URL}/api/approval/approve/{request_id}", timeout=5)
        elif choice == "n":
            r = requests.post(f"{SERVER_URL}/api/approval/reject/{request_id}", timeout=5)
        else:
            r = requests.post(
                f"{SERVER_URL}/api/approval/respond",
                json={"request_id": request_id, "choice": choice},
                timeout=5
            )
        return r.json().get("success", False)
    except Exception as e:
        log(f"Approve error: {e}", "ERROR")
        return False


def approval_watcher(auto_approve: bool = True, watch_duration: float = 60.0):
    """Background thread that watches for and handles approvals"""
    start = time.time()
    handled = set()

    while time.time() - start < watch_duration:
        pending = get_pending_approvals()

        for req in pending:
            req_id = req.get("id")
            if req_id and req_id not in handled:
                log(f"APPROVAL REQUEST: {req.get('tool')} - {req.get('description')}", "WAIT")
                log(f"  Risk: {req.get('risk_level')}", "WAIT")
                log(f"  ID: {req_id}", "WAIT")

                if auto_approve:
                    time.sleep(0.5)  # Brief delay for visibility
                    if approve_request(req_id, "y"):
                        log(f"AUTO-APPROVED: {req_id}", "OK")
                        handled.add(req_id)
                    else:
                        log(f"APPROVE FAILED: {req_id}", "ERROR")

        time.sleep(0.5)


def test_simple_edit():
    """Test simple edit operation"""
    log("=" * 60)
    log("TEST: Simple Edit via API")
    log("=" * 60)

    # Start approval watcher
    watcher = threading.Thread(target=approval_watcher, args=(True, 30.0), daemon=True)
    watcher.start()

    # Create test file first (use pattern: write filename: content)
    log("Creating test file...")
    r = requests.post(
        f"{SERVER_URL}/api/chat",
        json={"message": "write test_api_autonomous.py: def greet(): return 'Hello'"},
        timeout=30
    )
    result = r.json()
    log(f"Create result: success={result.get('success')}")

    time.sleep(1)

    # Edit the file (use pattern: in file X replace Y with Z)
    log("Editing file...")
    r = requests.post(
        f"{SERVER_URL}/api/chat",
        json={"message": "in file test_api_autonomous.py replace \"Hello\" with \"Hello World\""},
        timeout=30
    )
    result = r.json()
    log(f"Edit result: success={result.get('success')}")
    log(f"Response:\n{result.get('response', 'no response')}")

    return result


def test_dangerous_operation():
    """Test dangerous operation (bash command)"""
    log("=" * 60)
    log("TEST: Dangerous Operation (bash)")
    log("=" * 60)

    # Start approval watcher
    watcher = threading.Thread(target=approval_watcher, args=(True, 30.0), daemon=True)
    watcher.start()

    # Run bash command (use direct command format)
    log("Running bash command...")
    r = requests.post(
        f"{SERVER_URL}/api/chat",
        json={"message": "echo 'Test dangerous operation' && date"},
        timeout=30
    )
    result = r.json()
    log(f"Bash result: success={result.get('success')}")
    log(f"Response:\n{result.get('response', 'no response')}")

    return result


def test_multi_step_task():
    """Test multi-step autonomous task"""
    log("=" * 60)
    log("TEST: Multi-Step Autonomous Task")
    log("=" * 60)

    # Start approval watcher
    watcher = threading.Thread(target=approval_watcher, args=(True, 60.0), daemon=True)
    watcher.start()

    task = """
    Please complete these steps:
    1. Create a file called test_multi_step.py with a hello() function
    2. Add a goodbye() function to the same file
    3. Read the file to show the final content
    """

    log(f"Submitting task:\n{task}")
    log("-" * 40)

    r = requests.post(
        f"{SERVER_URL}/api/chat",
        json={"message": task},
        timeout=60
    )
    result = r.json()
    log(f"Task result: success={result.get('success')}")
    log(f"Response:\n{result.get('response', 'no response')[:500]}")

    return result


def test_rejection():
    """Test approval rejection"""
    log("=" * 60)
    log("TEST: Approval Rejection")
    log("=" * 60)

    # Custom watcher that rejects
    def reject_watcher():
        start = time.time()
        handled = set()
        while time.time() - start < 30:
            pending = get_pending_approvals()
            for req in pending:
                req_id = req.get("id")
                if req_id and req_id not in handled:
                    log(f"REJECTING: {req.get('tool')} - {req_id}", "WARN")
                    approve_request(req_id, "n")
                    handled.add(req_id)
            time.sleep(0.5)

    watcher = threading.Thread(target=reject_watcher, daemon=True)
    watcher.start()

    # Try to run dangerous command
    log("Running command that will be rejected...")
    r = requests.post(
        f"{SERVER_URL}/api/chat",
        json={"message": "run command: rm -rf /tmp/test_nonexistent"},
        timeout=30
    )
    result = r.json()
    log(f"Result: success={result.get('success')}")
    log(f"Response:\n{result.get('response', 'no response')}")

    return result


def main():
    """Run all tests"""
    print("=" * 70)
    print("AUTONOMOUS WORKFLOW API TEST")
    print(f"Server: {SERVER_URL}")
    print("=" * 70)

    if not check_server():
        print("\nServer not available. Start with:")
        print("  python qwencode_unified_server.py --port 5002")
        return

    results = []

    # Test 1: Simple edit
    print("\n")
    r1 = test_simple_edit()
    results.append(("Simple Edit", r1.get("success", False)))
    time.sleep(2)

    # Test 2: Dangerous operation
    print("\n")
    r2 = test_dangerous_operation()
    results.append(("Dangerous Op", r2.get("success", False)))
    time.sleep(2)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for name, success in results:
        status = "[+] PASS" if success else "[X] FAIL"
        print(f"  {status}: {name}")

    passed = sum(1 for _, s in results if s)
    print(f"\nTotal: {passed}/{len(results)} passed")


if __name__ == "__main__":
    main()
