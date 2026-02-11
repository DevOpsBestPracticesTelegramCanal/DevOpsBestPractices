"""
Tests для QwenCode Improvements
===============================
pytest tests/test_all.py -v
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.codegen.devops_templates import TemplateCache, TemplateMatch, TemplateCategory
from core.codegen.modernizer import CodeModernizer, modernize_code
from core.codegen.quality_prompts import detect_task_type, inject_quality_requirements
from core.codegen.few_shot import get_example, get_relevant_examples


# =============================================================================
# TEMPLATE CACHE TESTS
# =============================================================================

class TestTemplateCache:
    """Тесты для DevOps Template Cache"""
    
    @pytest.fixture
    def cache(self, tmp_path):
        """Создаём временный кэш"""
        db_path = str(tmp_path / "test_cache.db")
        return TemplateCache(db_path)
    
    def test_k8s_nginx_match(self, cache):
        """Тест: матчинг K8s nginx deployment"""
        match = cache.match("create kubernetes deployment for nginx with 3 replicas")
        
        assert match is not None
        assert match.template_id == "k8s_nginx_deployment"
        assert match.category == TemplateCategory.KUBERNETES
        assert match.params["replicas"] == 3
        assert match.confidence >= 0.9
    
    def test_k8s_replicas_extraction(self, cache):
        """Тест: извлечение числа реплик"""
        match = cache.match("nginx deployment 5 replicas")
        assert match.params["replicas"] == 5
        
        match = cache.match("k8s nginx deployment")  # No replicas specified
        assert match.params["replicas"] == 3  # default
    
    def test_terraform_s3_match(self, cache):
        """Тест: матчинг Terraform S3"""
        match = cache.match("terraform module for s3 bucket")
        
        assert match is not None
        assert match.template_id == "tf_s3_bucket_secure"
        assert match.category == TemplateCategory.TERRAFORM
    
    def test_gha_python_match(self, cache):
        """Тест: матчинг GitHub Actions"""
        match = cache.match("github actions ci pipeline for python")
        
        assert match is not None
        assert match.template_id == "gha_python_ci"
        assert match.category == TemplateCategory.GITHUB_ACTIONS
    
    def test_dockerfile_match(self, cache):
        """Тест: матчинг Dockerfile"""
        match = cache.match("dockerfile for python fastapi")
        
        assert match is not None
        assert match.template_id == "dockerfile_python_fastapi"
    
    def test_template_get(self, cache):
        """Тест: получение шаблона с параметрами"""
        code = cache.get("k8s_nginx_deployment", replicas=5)
        
        assert code is not None
        assert "replicas: 5" in code
        assert "nginx:1.27-alpine" in code
        assert "resources:" in code
        assert "livenessProbe:" in code
    
    def test_no_match(self, cache):
        """Тест: нет матча для неизвестного запроса"""
        match = cache.match("write a poem about cats")
        assert match is None
    
    def test_list_templates(self, cache):
        """Тест: список шаблонов"""
        templates = cache.list_templates()
        
        assert len(templates) >= 6
        assert "k8s_nginx_deployment" in templates
        assert "tf_s3_bucket_secure" in templates


# =============================================================================
# MODERNIZER TESTS
# =============================================================================

class TestModernizer:
    """Тесты для Code Modernizer"""
    
    @pytest.fixture
    def modernizer(self):
        return CodeModernizer()
    
    def test_gha_version_update(self, modernizer):
        """Тест: обновление версий GitHub Actions"""
        old_code = """
        - uses: actions/checkout@v2
        - uses: actions/setup-python@v3
        """
        
        result = modernizer.modernize(old_code, "yaml")
        
        assert "checkout@v4" in result.code
        assert "setup-python@v5" in result.code
        assert len(result.changes_made) >= 2
    
    def test_python_version_update(self, modernizer):
        """Тест: обновление Python версии"""
        old_code = "python-version: '3.8'"
        
        result = modernizer.modernize(old_code, "yaml")
        
        assert "3.12" in result.code
    
    def test_flake8_to_ruff(self, modernizer):
        """Тест: замена flake8 на ruff"""
        old_code = "pip install flake8\nflake8 ."
        
        result = modernizer.modernize(old_code, "yaml")
        
        assert "ruff" in result.code
        assert "flake8" not in result.code or "ruff check" in result.code
    
    def test_k8s_deprecated_api(self, modernizer):
        """Тест: исправление deprecated K8s API"""
        old_code = "apiVersion: apps/v1beta1\nkind: Deployment"

        result = modernizer.modernize(old_code, "yaml")

        assert "apps/v1" in result.code
        assert "v1beta1" not in result.code
    
    def test_k8s_latest_tag(self, modernizer):
        """Тест: замена :latest на конкретный тег"""
        old_code = "apiVersion: apps/v1\nkind: Deployment\nimage: nginx:latest"

        result = modernizer.modernize(old_code, "yaml")

        assert ":latest" not in result.code
        assert "nginx:" in result.code
    
    def test_python_lock_to_rlock(self, modernizer):
        """Тест: замена Lock на RLock"""
        old_code = "self.lock = threading.Lock()"
        
        result = modernizer.modernize(old_code, "python")
        
        assert "RLock" in result.code
    
    def test_terraform_deprecated_warning(self, modernizer):
        """Тест: warning для deprecated Terraform"""
        old_code = 'acl = "private"'
        
        result = modernizer.modernize(old_code, "terraform")
        
        assert len(result.warnings) > 0
        assert "deprecated" in result.warnings[0].lower()
    
    def test_auto_detect_language(self, modernizer):
        """Тест: автоопределение языка"""
        k8s_code = "apiVersion: apps/v1\nkind: Deployment"
        tf_code = 'resource "aws_s3_bucket" "main" {}'
        py_code = "def foo():\n    pass"
        
        assert modernizer._detect_language(k8s_code) == "yaml"
        assert modernizer._detect_language(tf_code) == "terraform"
        assert modernizer._detect_language(py_code) == "python"


# =============================================================================
# QUALITY PROMPTS TESTS
# =============================================================================

class TestQualityPrompts:
    """Тесты для Quality Prompts"""
    
    def test_detect_kubernetes(self):
        """Тест: определение K8s задачи"""
        assert detect_task_type("create kubernetes deployment") == "kubernetes"
        assert detect_task_type("k8s pod for nginx") == "kubernetes"
    
    def test_detect_terraform(self):
        """Тест: определение Terraform задачи"""
        assert detect_task_type("terraform module for s3") == "terraform"
        assert detect_task_type("aws lambda function") == "terraform"
    
    def test_detect_github_actions(self):
        """Тест: определение GitHub Actions"""
        assert detect_task_type("github actions ci") == "github_actions"
        assert detect_task_type("ci/cd pipeline") == "github_actions"
    
    def test_detect_algorithm(self):
        """Тест: определение алгоритма"""
        assert detect_task_type("binary search algorithm") == "algorithm"
        assert detect_task_type("sort array") == "algorithm"
    
    def test_default_python(self):
        """Тест: дефолт Python для неизвестных задач"""
        assert detect_task_type("write a function") == "python"
        assert detect_task_type("something random") == "python"
    
    def test_inject_requirements(self):
        """Тест: инъекция требований в промпт"""
        prompt = inject_quality_requirements("write function", "python")
        
        assert "Type Hints" in prompt
        assert "Docstring" in prompt
        assert "Edge Cases" in prompt
    
    def test_k8s_requirements(self):
        """Тест: K8s requirements"""
        prompt = inject_quality_requirements("create deployment", "kubernetes")
        
        assert "resources:" in prompt or "Resources" in prompt
        assert "livenessProbe" in prompt or "Probes" in prompt
        assert ":latest" in prompt


# =============================================================================
# FEW-SHOT TESTS
# =============================================================================

class TestFewShot:
    """Тесты для Few-Shot Examples"""
    
    def test_get_email_example(self):
        """Тест: получение примера email validation"""
        example = get_example("email_validation")
        
        assert example is not None
        assert "email" in example.name.lower()
        assert len(example.good_code) > len(example.bad_code)
        assert "fullmatch" in example.good_code
    
    def test_get_bubble_sort_example(self):
        """Тест: получение примера bubble sort"""
        example = get_example("bubble_sort")
        
        assert example is not None
        assert "swapped" in example.good_code
        assert "swapped" not in example.bad_code
    
    def test_relevant_email(self):
        """Тест: релевантные примеры для email"""
        examples = get_relevant_examples("validate email address")
        
        assert len(examples) >= 1
        assert any("email" in ex.name.lower() for ex in examples)
    
    def test_relevant_sort(self):
        """Тест: релевантные примеры для sort"""
        examples = get_relevant_examples("implement bubble sort")
        
        assert len(examples) >= 1
        assert any("sort" in ex.name.lower() for ex in examples)
    
    def test_no_relevant(self):
        """Тест: нет релевантных примеров"""
        examples = get_relevant_examples("something completely unrelated xyz")
        
        # Может быть пустой или с низким match
        assert isinstance(examples, list)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Интеграционные тесты"""
    
    @pytest.fixture
    def cache(self, tmp_path):
        db_path = str(tmp_path / "test_cache.db")
        return TemplateCache(db_path)
    
    @pytest.fixture
    def modernizer(self):
        return CodeModernizer()
    
    def test_full_pipeline_k8s(self, cache, modernizer):
        """Тест: полный pipeline для K8s"""
        query = "create kubernetes deployment for nginx with 3 replicas"
        
        # 1. Cache match
        match = cache.match(query)
        assert match is not None
        
        # 2. Get template
        code = cache.get(match.template_id, **match.params)
        assert code is not None
        
        # 3. Modernize (should be already modern)
        result = modernizer.modernize(code, "yaml")
        
        # Verify quality
        assert "replicas: 3" in result.code
        assert "resources:" in result.code
        assert "livenessProbe:" in result.code
        assert ":latest" not in result.code
    
    def test_full_pipeline_terraform(self, cache, modernizer):
        """Тест: полный pipeline для Terraform"""
        query = "terraform s3 bucket"
        
        match = cache.match(query)
        assert match is not None
        
        code = cache.get(match.template_id)
        assert code is not None
        
        result = modernizer.modernize(code, "terraform")
        
        # Verify modern Terraform
        assert "aws_s3_bucket_ownership_controls" in result.code
        assert "aws_s3_bucket_public_access_block" in result.code
        assert "aws_s3_bucket_server_side_encryption" in result.code
        assert 'acl = "private"' not in result.code


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
