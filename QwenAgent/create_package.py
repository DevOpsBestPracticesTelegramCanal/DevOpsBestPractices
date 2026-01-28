# -*- coding: utf-8 -*-
"""
Create portable QwenAgent package
"""

import os
import zipfile
from datetime import datetime

def create_package():
    """Create portable ZIP package"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"QwenAgent_Portable_{timestamp}.zip"
    zip_path = os.path.join(os.path.dirname(base_dir), zip_name)

    files_to_include = [
        'server.py',
        'start.bat',
        'install.bat',
        'run_tests.bat',
        'README.md',
        'core/__init__.py',
        'core/agent.py',
        'core/tools.py',
        'core/router.py',
        'core/cot_engine.py',
        'tests/__init__.py',
        'tests/devops_tests.py',
        'templates/terminal.html',
    ]

    print(f"Creating portable package: {zip_name}")
    print("-" * 50)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_rel in files_to_include:
            file_path = os.path.join(base_dir, file_rel)
            if os.path.exists(file_path):
                arc_name = f"QwenAgent/{file_rel}"
                zf.write(file_path, arc_name)
                print(f"  + {file_rel}")
            else:
                print(f"  - {file_rel} (not found)")

    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    print("-" * 50)
    print(f"Package created: {zip_path}")
    print(f"Size: {size_mb:.2f} MB")
    print()
    print("To use on another machine:")
    print("  1. Extract ZIP")
    print("  2. Install Ollama: https://ollama.ai/download")
    print("  3. Run: install.bat")
    print("  4. Run: start.bat")

    return zip_path

if __name__ == '__main__':
    create_package()
