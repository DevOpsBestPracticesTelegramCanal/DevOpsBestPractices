"""
Code Modernizer для QwenCode Generator
======================================
Автоматически исправляет deprecated код после генерации LLM.

Решает проблемы:
- Legacy deps: v2 actions → v4, Python 3.8 → 3.12
- Security: Lock → RLock, ACL deprecated
- K8s: :latest → pinned, missing probes/resources

Использование:
    from core.codegen.modernizer import CodeModernizer
    
    modernizer = CodeModernizer()
    fixed_code = modernizer.modernize(generated_code)
"""

import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ModernizationResult:
    """Результат модернизации кода"""
    code: str
    changes_made: List[str]
    warnings: List[str]


class CodeModernizer:
    """Автоматический модернизатор сгенерированного кода"""
    
    # =========================================================================
    # VERSION MAPPINGS
    # =========================================================================
    
    VERSION_MAP: Dict[str, str] = {
        # GitHub Actions - всегда последние major версии
        "actions/checkout@v2": "actions/checkout@v4",
        "actions/checkout@v3": "actions/checkout@v4",
        "actions/setup-python@v2": "actions/setup-python@v5",
        "actions/setup-python@v3": "actions/setup-python@v5",
        "actions/setup-python@v4": "actions/setup-python@v5",
        "actions/setup-node@v2": "actions/setup-node@v4",
        "actions/setup-node@v3": "actions/setup-node@v4",
        "actions/cache@v2": "actions/cache@v4",
        "actions/cache@v3": "actions/cache@v4",
        "actions/upload-artifact@v2": "actions/upload-artifact@v4",
        "actions/upload-artifact@v3": "actions/upload-artifact@v4",
        "actions/download-artifact@v2": "actions/download-artifact@v4",
        "actions/download-artifact@v3": "actions/download-artifact@v4",
        "docker/build-push-action@v4": "docker/build-push-action@v5",
        "docker/setup-buildx-action@v2": "docker/setup-buildx-action@v3",
        "docker/login-action@v2": "docker/login-action@v3",
        "docker/metadata-action@v4": "docker/metadata-action@v5",
        "codecov/codecov-action@v3": "codecov/codecov-action@v4",
        "hashicorp/setup-terraform@v2": "hashicorp/setup-terraform@v3",
        
        # Python versions (EOL)
        "python:3.7": "python:3.12",
        "python:3.8": "python:3.12",
        "python:3.9": "python:3.11",
        "python-version: '3.7'": "python-version: '3.12'",
        "python-version: '3.8'": "python-version: '3.12'",
        "python-version: 3.7": "python-version: '3.12'",
        "python-version: 3.8": "python-version: '3.12'",
        
        # Node versions
        "node:16": "node:20",
        "node:18": "node:20",
        "node-version: '16'": "node-version: '20'",
        "node-version: '18'": "node-version: '20'",
        
        # Linters (flake8 → ruff migration)
        "pip install flake8": "pip install ruff",
        "flake8 .": "ruff check .",
        "flake8 --": "ruff check --",
    }
    
    # =========================================================================
    # TERRAFORM FIXES (AWS Provider 5.x)
    # =========================================================================
    
    TERRAFORM_PATTERNS: List[Tuple[str, str, str]] = [
        # ACL deprecated - mark for manual fix
        (r'acl\s*=\s*"private"', 
         '# ACL deprecated in AWS Provider 5.x - use aws_s3_bucket_ownership_controls instead',
         "Terraform: ACL deprecated, needs aws_s3_bucket_ownership_controls"),
        
        (r'acl\s*=\s*"public-read"',
         '# ACL deprecated - use aws_s3_bucket_policy for public access',
         "Terraform: Public ACL deprecated"),
        
        # lifecycle_rule inside bucket - deprecated
        (r'lifecycle_rule\s*\{',
         '# lifecycle_rule deprecated - use aws_s3_bucket_lifecycle_configuration resource',
         "Terraform: lifecycle_rule deprecated"),
        
        # versioning inside bucket - deprecated  
        (r'versioning\s*\{\s*enabled\s*=',
         '# versioning block deprecated - use aws_s3_bucket_versioning resource',
         "Terraform: versioning block deprecated"),
        
        # Old provider version
        (r'version\s*=\s*"~>\s*4\.',
         'version = "~> 5.0"',
         "Terraform: Updated AWS provider to 5.x"),
        
        (r'version\s*=\s*"~>\s*3\.',
         'version = "~> 5.0"',
         "Terraform: Updated AWS provider to 5.x"),
    ]
    
    # =========================================================================
    # KUBERNETES FIXES
    # =========================================================================
    
    K8S_PATTERNS: List[Tuple[str, str, str]] = [
        # Deprecated API versions
        (r'apiVersion:\s*apps/v1beta1', 
         'apiVersion: apps/v1',
         "K8s: Updated deprecated apps/v1beta1 to apps/v1"),
        
        (r'apiVersion:\s*apps/v1beta2',
         'apiVersion: apps/v1', 
         "K8s: Updated deprecated apps/v1beta2 to apps/v1"),
        
        (r'apiVersion:\s*extensions/v1beta1',
         'apiVersion: networking.k8s.io/v1',
         "K8s: Updated deprecated extensions/v1beta1"),
        
        # :latest tag (security risk)
        (r'image:\s*nginx:latest',
         'image: nginx:1.27-alpine  # Pinned version for security',
         "K8s: Pinned nginx:latest to specific version"),
        
        (r'image:\s*postgres:latest',
         'image: postgres:16-alpine  # Pinned version',
         "K8s: Pinned postgres:latest to specific version"),
        
        (r'image:\s*redis:latest',
         'image: redis:7-alpine  # Pinned version',
         "K8s: Pinned redis:latest to specific version"),
        
        (r'image:\s*python:latest',
         'image: python:3.12-slim  # Pinned version',
         "K8s: Pinned python:latest to specific version"),
        
        (r'image:\s*node:latest',
         'image: node:20-alpine  # Pinned version',
         "K8s: Pinned node:latest to specific version"),
    ]
    
    # =========================================================================
    # PYTHON THREAD SAFETY FIXES
    # =========================================================================
    
    PYTHON_PATTERNS: List[Tuple[str, str, str]] = [
        # Lock → RLock for reentrant safety
        (r'threading\.Lock\(\)',
         'threading.RLock()  # Reentrant lock for nested calls',
         "Python: Changed Lock to RLock for reentrant safety"),
        
        (r'self\.lock\s*=\s*Lock\(\)',
         'self._lock = threading.RLock()  # Reentrant lock',
         "Python: Changed Lock to RLock"),
        
        # any → Any typing
        (r':\s*any(?=\s*[,)\]])',
         ': Any',
         "Python: Fixed 'any' to 'Any' for proper typing"),
        
        (r'->\s*any(?=\s*:)',
         '-> Any',
         "Python: Fixed return type 'any' to 'Any'"),
    ]
    
    # =========================================================================
    # GITHUB ACTIONS SPECIFIC FIXES
    # =========================================================================
    
    GHA_PATTERNS: List[Tuple[str, str, str]] = [
        # Add pip cache if missing with setup-python
        # This is handled in _fix_github_actions method
    ]
    
    def __init__(self):
        self.changes: List[str] = []
        self.warnings: List[str] = []
    
    def modernize(self, code: str, language: str = "auto") -> ModernizationResult:
        """
        Модернизирует код, исправляя deprecated patterns.
        
        Args:
            code: Исходный код
            language: Тип кода (auto, python, yaml, terraform, github_actions)
            
        Returns:
            ModernizationResult с исправленным кодом и списком изменений
        """
        self.changes = []
        self.warnings = []
        
        if language == "auto":
            language = self._detect_language(code)
        
        # 1. Общие замены версий (работает для всех языков)
        code = self._apply_version_map(code)
        
        # 2. Специфичные фиксы по языку
        if language == "terraform" or language == "hcl":
            code = self._fix_terraform(code)
        elif language == "yaml":
            if self._is_kubernetes(code):
                code = self._fix_kubernetes(code)
            if self._is_github_actions(code):
                code = self._fix_github_actions(code)
        elif language == "python":
            code = self._fix_python(code)
        
        return ModernizationResult(
            code=code,
            changes_made=self.changes,
            warnings=self.warnings
        )
    
    def _apply_version_map(self, code: str) -> str:
        """Применяет маппинг версий"""
        for old, new in self.VERSION_MAP.items():
            if old in code:
                code = code.replace(old, new)
                self.changes.append(f"Updated: {old} → {new}")
        return code
    
    def _fix_terraform(self, code: str) -> str:
        """Фиксы для Terraform"""
        for pattern, replacement, message in self.TERRAFORM_PATTERNS:
            if re.search(pattern, code):
                if replacement.startswith('#'):
                    # Это warning, а не замена
                    self.warnings.append(message)
                else:
                    code = re.sub(pattern, replacement, code)
                    self.changes.append(message)
        return code
    
    def _fix_kubernetes(self, code: str) -> str:
        """Фиксы для Kubernetes YAML"""
        for pattern, replacement, message in self.K8S_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                code = re.sub(pattern, replacement, code, flags=re.IGNORECASE)
                self.changes.append(message)
        
        # Добавить resources если отсутствуют
        if 'kind: Deployment' in code and 'resources:' not in code:
            code = self._inject_k8s_resources(code)
            self.changes.append("K8s: Added resource requests/limits")
        
        # Добавить probes если отсутствуют  
        if 'kind: Deployment' in code and 'livenessProbe:' not in code:
            code = self._inject_k8s_probes(code)
            self.changes.append("K8s: Added liveness/readiness probes")
        
        return code
    
    def _fix_github_actions(self, code: str) -> str:
        """Фиксы для GitHub Actions"""
        # Добавить cache: 'pip' если используется setup-python без cache
        if 'setup-python@' in code and "cache:" not in code:
            code = re.sub(
                r"(python-version:\s*[^\n]+)",
                r"\1\n        cache: 'pip'",
                code
            )
            self.changes.append("GHA: Added pip cache for faster builds")
        
        # Добавить concurrency если отсутствует
        if 'concurrency:' not in code and 'jobs:' in code:
            concurrency_block = '''
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
'''
            code = re.sub(
                r'(on:\s*\n(?:\s+[^\n]+\n)+)',
                r'\1' + concurrency_block,
                code,
                count=1
            )
            self.changes.append("GHA: Added concurrency for CI efficiency")
        
        return code
    
    def _fix_python(self, code: str) -> str:
        """Фиксы для Python кода"""
        for pattern, replacement, message in self.PYTHON_PATTERNS:
            if re.search(pattern, code):
                code = re.sub(pattern, replacement, code)
                self.changes.append(message)
        
        # Добавить typing import если используется Any
        if ': Any' in code or '-> Any' in code:
            if 'from typing import' in code:
                if 'Any' not in code.split('from typing import')[1].split('\n')[0]:
                    code = re.sub(
                        r'from typing import',
                        'from typing import Any, ',
                        code,
                        count=1
                    )
                    self.changes.append("Python: Added Any to typing imports")
            elif 'import typing' not in code:
                code = 'from typing import Any\n' + code
                self.changes.append("Python: Added typing import for Any")
        
        return code
    
    def _inject_k8s_resources(self, code: str) -> str:
        """Инжектит resource limits в K8s deployment"""
        resources_block = '''        resources:
          requests:
            cpu: "100m"
            memory: "64Mi"
          limits:
            cpu: "200m"
            memory: "128Mi"'''
        
        # Вставляем после image:
        code = re.sub(
            r'(image:\s*[^\n]+)',
            r'\1\n' + resources_block,
            code,
            count=1
        )
        return code
    
    def _inject_k8s_probes(self, code: str) -> str:
        """Инжектит probes в K8s deployment"""
        probes_block = '''        livenessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 5'''
        
        # Вставляем после resources: или после image: если resources нет
        if 'resources:' in code:
            # После блока limits
            code = re.sub(
                r'(limits:\s*\n\s+\w+:\s*"[^"]+"\s*\n\s+\w+:\s*"[^"]+")',
                r'\1\n' + probes_block,
                code,
                count=1
            )
        else:
            # После image:
            code = re.sub(
                r'(image:\s*[^\n]+)',
                r'\1\n' + probes_block,
                code,
                count=1
            )
        return code
    
    def _detect_language(self, code: str) -> str:
        """Автоопределение типа кода"""
        if 'apiVersion:' in code and 'kind:' in code:
            return 'yaml'
        if 'resource "aws' in code or 'terraform {' in code or 'provider "' in code:
            return 'terraform'
        if 'def ' in code and ('import ' in code or ':' in code):
            return 'python'
        if 'name:' in code and 'on:' in code and 'jobs:' in code:
            return 'yaml'
        if 'FROM ' in code and ('RUN ' in code or 'CMD ' in code):
            return 'dockerfile'
        return 'unknown'
    
    def _is_kubernetes(self, code: str) -> bool:
        """Проверка: это K8s YAML?"""
        return 'apiVersion:' in code and 'kind:' in code
    
    def _is_github_actions(self, code: str) -> bool:
        """Проверка: это GitHub Actions YAML?"""
        return ('on:' in code and 'jobs:' in code) or 'uses: actions/' in code


# =============================================================================
# STANDALONE FUNCTIONS
# =============================================================================

def modernize_code(code: str, language: str = "auto") -> str:
    """
    Удобная функция для быстрой модернизации кода.
    
    Args:
        code: Код для модернизации
        language: Тип кода (auto для автоопределения)
        
    Returns:
        Модернизированный код
    """
    modernizer = CodeModernizer()
    result = modernizer.modernize(code, language)
    return result.code


def get_modernization_report(code: str, language: str = "auto") -> ModernizationResult:
    """
    Модернизация с полным отчётом об изменениях.
    
    Returns:
        ModernizationResult с кодом, изменениями и предупреждениями
    """
    modernizer = CodeModernizer()
    return modernizer.modernize(code, language)


# =============================================================================
# TESTS / EXAMPLES
# =============================================================================

if __name__ == "__main__":
    modernizer = CodeModernizer()
    
    # Test 1: GitHub Actions
    print("=== Test 1: GitHub Actions ===")
    gha_old = '''
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - uses: actions/setup-python@v3
      with:
        python-version: 3.8
    - run: pip install flake8
    - run: flake8 .
'''
    result = modernizer.modernize(gha_old, "yaml")
    print("Changes:", result.changes_made)
    print("---")
    print(result.code[:500])
    
    # Test 2: Kubernetes
    print("\n=== Test 2: Kubernetes ===")
    k8s_old = '''
apiVersion: apps/v1beta1
kind: Deployment
metadata:
  name: nginx
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: nginx
        image: nginx:latest
'''
    result = modernizer.modernize(k8s_old, "yaml")
    print("Changes:", result.changes_made)
    print("---")
    print(result.code[:600])
    
    # Test 3: Terraform
    print("\n=== Test 3: Terraform ===")
    tf_old = '''
provider "aws" {
  version = "~> 4.0"
}

resource "aws_s3_bucket" "main" {
  bucket = "my-bucket"
  acl    = "private"
  
  versioning {
    enabled = true
  }
}
'''
    result = modernizer.modernize(tf_old, "terraform")
    print("Changes:", result.changes_made)
    print("Warnings:", result.warnings)
    
    # Test 4: Python
    print("\n=== Test 4: Python ===")
    py_old = '''
import threading

class Cache:
    def __init__(self):
        self.lock = threading.Lock()
        self.data: any = None
    
    def get(self) -> any:
        with self.lock:
            return self.data
'''
    result = modernizer.modernize(py_old, "python")
    print("Changes:", result.changes_made)
    print("---")
    print(result.code)
