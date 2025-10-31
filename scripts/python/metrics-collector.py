#!/usr/bin/env python3
"""
Simple metrics collector example
"""

import psutil
import json
from datetime import datetime

def collect_metrics():
    """Collect system metrics"""
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory": psutil.virtual_memory()._asdict(),
        "disk": psutil.disk_usage('/')._asdict()
    }
    return metrics

if __name__ == "__main__":
    metrics = collect_metrics()
    print(json.dumps(metrics, indent=2))
