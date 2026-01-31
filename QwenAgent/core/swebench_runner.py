# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
SWE-BENCH MEGA RUNNER - Batch Processing for 2300+ Tasks
═══════════════════════════════════════════════════════════════════════════════

CLI tool for running the adaptive pipeline on SWE-bench dataset.

Features:
- Load tasks from JSON
- Process tasks in parallel
- Resume from checkpoint (SQLite-based)
- Real-time progress tracking
- Export results

Usage:
    # Load tasks
    python swebench_runner.py load swebench_verified.json

    # Run all pending tasks
    python swebench_runner.py run --workers 4

    # Run specific task
    python swebench_runner.py task django__django-10914

    # Show progress
    python swebench_runner.py stats

    # Export results
    python swebench_runner.py export results.json

═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import time
import signal
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

try:
    from adaptive_pipeline import AdaptivePipeline, PipelineConfig
    from db_manager import DatabaseManager
except ImportError:
    from .adaptive_pipeline import AdaptivePipeline, PipelineConfig
    from .db_manager import DatabaseManager


# ═══════════════════════════════════════════════════════════════════════════════
# PROGRESS DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════

class ProgressDisplay:
    """Real-time progress display"""

    def __init__(self, db: DatabaseManager, refresh_interval: float = 5.0):
        self.db = db
        self.refresh_interval = refresh_interval
        self.start_time = time.time()
        self.last_update = 0

    def show(self, force: bool = False):
        """Show progress if enough time has passed"""
        now = time.time()
        if not force and (now - self.last_update) < self.refresh_interval:
            return

        self.last_update = now
        progress = self.db.get_progress()
        elapsed = now - self.start_time

        # Calculate ETA
        if progress['success'] + progress['failed'] > 0:
            rate = (progress['success'] + progress['failed']) / elapsed
            remaining = progress['pending'] + progress['running']
            eta = remaining / rate if rate > 0 else 0
        else:
            eta = 0

        # Build progress bar
        total = progress['total'] or 1
        done = progress['success'] + progress['failed']
        pct = done / total
        bar_width = 40
        filled = int(bar_width * pct)
        bar = '#' * filled + '-' * (bar_width - filled)

        # Print
        print(f"\r[{bar}] {pct*100:5.1f}% | "
              f"OK:{progress['success']} FAIL:{progress['failed']} PEND:{progress['pending']} | "
              f"Rate: {progress['success_rate']:.1f}% | "
              f"ETA: {self._format_time(eta)}", end='', flush=True)

    def _format_time(self, seconds: float) -> str:
        """Format time in human-readable format"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.0f}m"
        else:
            return f"{seconds/3600:.1f}h"

    def final_summary(self):
        """Show final summary"""
        progress = self.db.get_progress()
        elapsed = time.time() - self.start_time

        print("\n\n" + "="*60)
        print("FINAL SUMMARY")
        print("="*60)
        print(f"Total tasks:    {progress['total']}")
        print(f"Success:        {progress['success']} ({progress['success_rate']:.1f}%)")
        print(f"Failed:         {progress['failed']}")
        print(f"Pending:        {progress['pending']}")
        print(f"Running:        {progress['running']}")
        print(f"Time elapsed:   {self._format_time(elapsed)}")
        print("="*60)


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

class SWEBenchRunner:
    """Main runner for SWE-bench batch processing"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pipeline = AdaptivePipeline(config)
        self.db = self.pipeline.db
        self.progress = ProgressDisplay(self.db)
        self.running = True

        # Setup signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signal"""
        print("\n\n[SHUTDOWN] Received signal, stopping gracefully...")
        self.running = False

    def load_tasks(self, json_path: str) -> int:
        """Load tasks from JSON file"""
        if not os.path.exists(json_path):
            print(f"Error: File not found: {json_path}")
            return 0

        count = self.pipeline.load_tasks(json_path)
        print(f"\n[OK] Loaded {count} tasks from {json_path}")

        # Show initial stats
        progress = self.db.get_progress()
        print(f"  Total:   {progress['total']}")
        print(f"  Pending: {progress['pending']}")

        return count

    def run_batch(
        self,
        max_tasks: int = None,
        workers: int = 1,
        resume: bool = True
    ) -> Dict[str, Any]:
        """
        Run batch processing.

        Args:
            max_tasks: Maximum number of tasks to process
            workers: Number of parallel workers
            resume: Continue from previous checkpoint (always True with SQLite)

        Returns:
            Dict with statistics
        """
        self.progress.start_time = time.time()

        print("\n" + "="*60)
        print("SWE-BENCH BATCH PROCESSING")
        print("="*60)
        print(f"Model:   {self.config.model_name}")
        print(f"Workers: {workers}")
        print(f"Max:     {max_tasks or 'all'}")
        print("="*60 + "\n")

        processed = 0
        success_count = 0
        failed_count = 0

        try:
            while self.running:
                if max_tasks and processed >= max_tasks:
                    break

                result = self.pipeline.process_next()
                if result is None:
                    # No more pending tasks
                    break

                processed += 1
                if result.get("success"):
                    success_count += 1
                else:
                    failed_count += 1

                self.progress.show()

        except Exception as e:
            print(f"\n[ERROR] {e}")

        self.progress.final_summary()

        return {
            "processed": processed,
            "success": success_count,
            "failed": failed_count,
            "success_rate": success_count / processed if processed > 0 else 0
        }

    def run_single(self, instance_id: str) -> Dict[str, Any]:
        """Run a single task by instance_id"""
        print(f"\nProcessing task: {instance_id}")
        result = self.pipeline.process_task(instance_id)

        print("\n" + "="*60)
        print("RESULT")
        print("="*60)
        print(json.dumps(result, indent=2, default=str))

        return result

    def show_stats(self, detailed: bool = False):
        """Show current statistics"""
        stats = self.pipeline.get_stats()
        progress = stats["progress"]

        print("\n" + "="*60)
        print("PROGRESS")
        print("="*60)
        print(f"Total:   {progress['total']}")
        print(f"Success: {progress['success']} ({progress['success_rate']:.1f}%)")
        print(f"Failed:  {progress['failed']}")
        print(f"Pending: {progress['pending']}")
        print(f"Running: {progress['running']}")

        print("\n" + "="*60)
        print("SWECAS STATISTICS")
        print("="*60)
        for s in stats["swecas_stats"]:
            bar_len = int(s['success_rate'] / 5)
            bar = '#' * bar_len + '-' * (20 - bar_len)
            print(f"{s['category']:15} ({s['code']:3d}): [{bar}] "
                  f"{s['success']:3d}/{s['total']:3d} ({s['success_rate']:5.1f}%)")

        if detailed:
            print("\n" + "="*60)
            print("PATTERN STATISTICS")
            print("="*60)
            for p in stats.get("pattern_stats", [])[:10]:
                print(f"{p['pattern_id']}: {p['swecas_category']} - "
                      f"{p['success_count']}/{p['success_count']+p['fail_count']} "
                      f"({p['success_rate']:.1f}%)")

            print("\n" + "="*60)
            print("RECENT RUNS")
            print("="*60)
            for r in stats.get("recent_runs", [])[:10]:
                status = "OK" if r['success'] else "X "
                print(f"{status} {r['instance_id'][:40]:40s} | "
                      f"{r['swecas_category']:15s} | "
                      f"{r['total_time_ms']:7.0f}ms")

    def export_results(self, output_path: str):
        """Export results to JSON"""
        path = self.pipeline.export_results(output_path)
        print(f"\n[OK] Exported results to {path}")

    def reset_failed(self):
        """Reset all failed tasks to pending"""
        with self.db.transaction() as conn:
            cursor = conn.execute("""
                UPDATE tasks
                SET status = 'pending', locked_by = NULL, locked_at = NULL
                WHERE status = 'failed'
            """)
            count = cursor.rowcount

        print(f"\n[OK] Reset {count} failed tasks to pending")

    def reset_all(self):
        """Reset all tasks to pending"""
        with self.db.transaction() as conn:
            cursor = conn.execute("""
                UPDATE tasks
                SET status = 'pending', locked_by = NULL, locked_at = NULL
            """)
            count = cursor.rowcount

        print(f"\n[OK] Reset {count} tasks to pending")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="SWE-bench Mega Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python swebench_runner.py load swebench_verified.json
  python swebench_runner.py run --workers 4 --max 100
  python swebench_runner.py task django__django-10914
  python swebench_runner.py stats --detailed
  python swebench_runner.py export results.json
  python swebench_runner.py reset --failed
        """
    )

    # Global options
    parser.add_argument("--db", default="./swebench.db",
                        help="SQLite database path (default: ./swebench.db)")
    parser.add_argument("--model", default="qwen2.5-coder:7b",
                        help="Ollama model name")
    parser.add_argument("--ollama", default="http://localhost:11434",
                        help="Ollama URL")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # load command
    load_parser = subparsers.add_parser("load", help="Load tasks from JSON")
    load_parser.add_argument("json_file", help="JSON file with SWE-bench tasks")

    # run command
    run_parser = subparsers.add_parser("run", help="Run batch processing")
    run_parser.add_argument("--max", type=int, help="Maximum tasks to process")
    run_parser.add_argument("--workers", type=int, default=1,
                            help="Number of parallel workers (default: 1)")

    # task command
    task_parser = subparsers.add_parser("task", help="Process single task")
    task_parser.add_argument("instance_id", help="Task instance ID")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show statistics")
    stats_parser.add_argument("--detailed", "-d", action="store_true",
                              help="Show detailed stats")

    # export command
    export_parser = subparsers.add_parser("export", help="Export results")
    export_parser.add_argument("output", help="Output JSON file")

    # reset command
    reset_parser = subparsers.add_parser("reset", help="Reset tasks")
    reset_parser.add_argument("--failed", action="store_true",
                              help="Reset only failed tasks")
    reset_parser.add_argument("--all", action="store_true",
                              help="Reset all tasks")

    args = parser.parse_args()

    # Create config
    config = PipelineConfig(
        db_path=args.db,
        model_name=args.model,
        ollama_url=args.ollama,
        verbose=args.verbose
    )

    runner = SWEBenchRunner(config)

    if args.command == "load":
        runner.load_tasks(args.json_file)

    elif args.command == "run":
        runner.run_batch(max_tasks=args.max, workers=args.workers)

    elif args.command == "task":
        runner.run_single(args.instance_id)

    elif args.command == "stats":
        runner.show_stats(detailed=args.detailed)

    elif args.command == "export":
        runner.export_results(args.output)

    elif args.command == "reset":
        if args.all:
            runner.reset_all()
        elif args.failed:
            runner.reset_failed()
        else:
            print("Specify --failed or --all")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
