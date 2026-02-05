#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autonomous Mode Demo - Terminal Test
=====================================

Run: python run_autonomous_demo.py

This demo shows autonomous agent execution with human approval.
"""

import requests
import time
import threading
import sys

SERVER = "http://localhost:5002"

def log(msg, icon="*"):
    print(f"[{icon}] {msg}")

def check_server():
    try:
        r = requests.get(f"{SERVER}/api/health", timeout=3)
        return r.json().get("status") == "ok"
    except:
        return False

def get_pending():
    try:
        r = requests.get(f"{SERVER}/api/approval/pending", timeout=3)
        return r.json().get("pending", [])
    except:
        return []

def approve(req_id):
    try:
        r = requests.post(f"{SERVER}/api/approval/approve/{req_id}", timeout=3)
        return r.json().get("success", False)
    except:
        return False

def reject(req_id):
    try:
        r = requests.post(f"{SERVER}/api/approval/reject/{req_id}", timeout=3)
        return r.json().get("success", False)
    except:
        return False

def send_task(message):
    try:
        r = requests.post(
            f"{SERVER}/api/chat",
            json={"message": message},
            timeout=60
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def approval_monitor(auto_approve=False, duration=30):
    """Monitor and handle approval requests"""
    handled = set()
    start = time.time()

    while time.time() - start < duration:
        pending = get_pending()
        for req in pending:
            req_id = req.get("id")
            if req_id and req_id not in handled:
                print("\n" + "="*50)
                print("APPROVAL REQUIRED")
                print("="*50)
                print(f"Tool: {req.get('tool')}")
                print(f"Risk: {req.get('risk_level')}")
                print(f"Desc: {req.get('description')}")
                print(f"ID:   {req_id}")
                print("-"*50)

                if auto_approve:
                    print("[AUTO] Approving...")
                    time.sleep(0.5)
                    if approve(req_id):
                        log(f"Approved: {req_id}", "+")
                    handled.add(req_id)
                else:
                    print("Press [y] approve, [n] reject: ", end="", flush=True)
                    try:
                        choice = input().strip().lower()
                        if choice == 'y':
                            approve(req_id)
                            log(f"Approved: {req_id}", "+")
                        else:
                            reject(req_id)
                            log(f"Rejected: {req_id}", "!")
                        handled.add(req_id)
                    except:
                        pass
        time.sleep(0.3)

def demo_simple():
    """Demo 1: Simple file operations"""
    print("\n" + "="*60)
    print("DEMO 1: Simple File Operations")
    print("="*60)

    # Start approval monitor in background (auto-approve)
    monitor = threading.Thread(target=approval_monitor, args=(True, 30), daemon=True)
    monitor.start()

    # Step 1: Create file
    log("Creating file...")
    r = send_task("write demo_test.py: def hello(): return 'Hello'")
    log(f"Result: {r.get('success', False)}", "+" if r.get('success') else "!")

    time.sleep(1)

    # Step 2: Edit file
    log("Editing file...")
    r = send_task('in file demo_test.py replace "Hello" with "Hello World"')
    log(f"Result: {r.get('success', False)}", "+" if r.get('success') else "!")
    print(f"Response:\n{r.get('response', 'N/A')}")

    time.sleep(1)

    # Step 3: Read file
    log("Reading file...")
    r = send_task("read demo_test.py")
    log(f"Result: {r.get('success', False)}", "+" if r.get('success') else "!")
    print(f"Content:\n{r.get('response', 'N/A')[:200]}")

def demo_interactive():
    """Demo 2: Interactive approval"""
    print("\n" + "="*60)
    print("DEMO 2: Interactive Approval (YOU decide)")
    print("="*60)

    # Start approval monitor (manual)
    monitor = threading.Thread(target=approval_monitor, args=(False, 60), daemon=True)
    monitor.start()

    log("Running bash command (requires YOUR approval)...")
    r = send_task("echo 'Autonomous agent says hi!' && date")
    log(f"Result: {r.get('success', False)}", "+" if r.get('success') else "!")
    print(f"Output:\n{r.get('response', 'N/A')}")

def demo_multi_step():
    """Demo 3: Multi-step task"""
    print("\n" + "="*60)
    print("DEMO 3: Multi-Step Autonomous Task")
    print("="*60)

    monitor = threading.Thread(target=approval_monitor, args=(True, 45), daemon=True)
    monitor.start()

    steps = [
        ("Create config", "write demo_config.json: {\"version\": 1, \"name\": \"test\"}"),
        ("Create main", "write demo_main.py: import json; print('Config loaded')"),
        ("Edit config", 'in file demo_config.json replace "version\": 1" with "version\": 2"'),
        ("Verify", "read demo_config.json"),
    ]

    for name, cmd in steps:
        log(f"Step: {name}")
        r = send_task(cmd)
        status = "+" if r.get("success") else "!"
        log(f"  {r.get('success', False)}", status)
        time.sleep(0.5)

    print("\nAll steps completed!")

def main():
    print("="*60)
    print("AUTONOMOUS MODE DEMO")
    print("="*60)

    # Check server
    log("Checking server...")
    if not check_server():
        log("Server not running! Start with:", "!")
        print("  python qwencode_unified_server.py --port 5002")
        return
    log("Server OK", "+")

    # Menu
    print("\nSelect demo:")
    print("  1. Simple file operations (auto-approve)")
    print("  2. Interactive approval (you decide)")
    print("  3. Multi-step task (auto-approve)")
    print("  4. Run all demos")
    print("  q. Quit")

    try:
        choice = input("\nYour choice [1-4, q]: ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "q"

    if choice == "1":
        demo_simple()
    elif choice == "2":
        demo_interactive()
    elif choice == "3":
        demo_multi_step()
    elif choice == "4":
        demo_simple()
        time.sleep(2)
        demo_multi_step()
    elif choice == "q":
        print("Bye!")
        return
    else:
        print("Invalid choice")
        return

    print("\n" + "="*60)
    print("DEMO COMPLETE")
    print("="*60)

if __name__ == "__main__":
    main()
