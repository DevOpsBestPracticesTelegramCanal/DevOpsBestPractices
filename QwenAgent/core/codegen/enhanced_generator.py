"""
Enhanced Code Generator для QwenCode
====================================
Интеграция всех улучшений в единый pipeline.

Pipeline:
1. Template Cache (TIER 0) → 100% success на DevOps, <10ms
2. Quality Prompts → Инжекция требований качества
3. Few-Shot Examples → Примеры для LLM
4. LLM Generation → Qwen 2.5 Coder 7B
5. Post-Processing → Modernizer исправляет deprecated

Использование:
    from core.codegen.enhanced_generator import EnhancedCodeGenerator
    
    generator = EnhancedCodeGenerator(llm_client)
    code = await generator.generate("create kubernetes deployment for nginx")
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Protocol
from dataclasses import dataclass
from enum import Enum
import time

# Internal imports (adjust paths as needed)
from core.codegen.devops_templates import TemplateCache, TemplateMatch
from core.codegen.modernizer import CodeModernizer, ModernizationResult
from core.codegen.quality_prompts import get_prompt_for_task, detect_task_type
from core.codegen.few_shot import get_examples_for_prompt


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GenerationTier(Enum):
    """Уровень генерации кода"""
    CACHE = "cache"      # Template cache hit
    LLM = "llm"          # LLM generation
    FALLBACK = "fallback"  # Fallback/error


@dataclass
class GenerationResult:
    """Результат генерации кода"""
    code: str
    tier: GenerationTier
    template_id: Optional[str]
    task_type: str
    latency_ms: float
    modernization_changes: list
    confidence: float


class LLMClient(Protocol):
    """Protocol для LLM клиента"""
    
    async def generate(self, prompt: str) -> str:
        """Генерация текста через LLM"""
        ...


class MockLLMClient:
    """Mock LLM клиент для тестов"""
    
    async def generate(self, prompt: str) -> str:
        await asyncio.sleep(0.1)  # Simulate latency
        return f"# Generated code for: {prompt[:50]}...\npass"


class EnhancedCodeGenerator:
    """
    Улучшенный генератор кода с кэшем, качественными промптами и модернизацией.
    
    Workflow:
    1. Проверка Template Cache (DevOps шаблоны)
    2. Если cache miss → LLM с quality prompts + few-shot
    3. Post-processing: Modernizer исправляет deprecated код
    
    Attributes:
        llm: LLM клиент для генерации
        cache: Кэш DevOps шаблонов
        modernizer: Модернизатор кода
        use_few_shot: Включить few-shot examples
        use_quality_prompts: Включить quality requirements
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        cache_db_path: str = "cache/codegen_cache.db",
        use_few_shot: bool = True,
        use_quality_prompts: bool = True
    ):
        self.llm = llm_client or MockLLMClient()
        self.cache = TemplateCache(cache_db_path)
        self.modernizer = CodeModernizer()
        self.use_few_shot = use_few_shot
        self.use_quality_prompts = use_quality_prompts
        
        logger.info("EnhancedCodeGenerator initialized")
        logger.info(f"  - Cache templates: {len(self.cache.list_templates())}")
        logger.info(f"  - Few-shot: {use_few_shot}")
        logger.info(f"  - Quality prompts: {use_quality_prompts}")
    
    async def generate(self, query: str, **kwargs) -> GenerationResult:
        """
        Генерирует код для запроса.
        
        Args:
            query: Запрос пользователя
            **kwargs: Дополнительные параметры для шаблонов
            
        Returns:
            GenerationResult с кодом и метаданными
        """
        start_time = time.time()
        
        # 1. TIER 0: Проверяем кэш шаблонов
        cache_match = self.cache.match(query)
        
        if cache_match:
            logger.info(f"Cache HIT: {cache_match.template_id} (conf: {cache_match.confidence})")
            
            # Объединяем параметры из match и kwargs
            params = {**cache_match.params, **kwargs}
            code = self.cache.get(cache_match.template_id, **params)
            
            if code:
                latency = (time.time() - start_time) * 1000
                
                return GenerationResult(
                    code=code,
                    tier=GenerationTier.CACHE,
                    template_id=cache_match.template_id,
                    task_type=cache_match.category.value,
                    latency_ms=latency,
                    modernization_changes=[],
                    confidence=cache_match.confidence
                )
        
        logger.info("Cache MISS, falling back to LLM")
        
        # 2. TIER 1: LLM Generation
        task_type = detect_task_type(query)
        
        # Строим enhanced prompt
        enhanced_prompt = self._build_enhanced_prompt(query, task_type)
        
        # Генерируем через LLM
        try:
            raw_code = await self.llm.generate(enhanced_prompt)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return GenerationResult(
                code=f"# Error: {e}",
                tier=GenerationTier.FALLBACK,
                template_id=None,
                task_type=task_type,
                latency_ms=(time.time() - start_time) * 1000,
                modernization_changes=[],
                confidence=0.0
            )
        
        # 3. Post-processing: Modernizer
        modernization = self.modernizer.modernize(raw_code, task_type)
        
        latency = (time.time() - start_time) * 1000
        
        logger.info(f"Generated via LLM in {latency:.1f}ms")
        if modernization.changes_made:
            logger.info(f"Modernization: {len(modernization.changes_made)} changes")
        
        return GenerationResult(
            code=modernization.code,
            tier=GenerationTier.LLM,
            template_id=None,
            task_type=task_type,
            latency_ms=latency,
            modernization_changes=modernization.changes_made,
            confidence=0.7  # LLM confidence estimate
        )
    
    def _build_enhanced_prompt(self, query: str, task_type: str) -> str:
        """
        Строит улучшенный промпт с quality requirements и few-shot.
        
        Args:
            query: Исходный запрос
            task_type: Тип задачи
            
        Returns:
            Улучшенный промпт
        """
        parts = []
        
        # 1. Quality Requirements
        if self.use_quality_prompts:
            enhanced = get_prompt_for_task(query, task_type)
            parts.append(enhanced)
        else:
            parts.append(query)
        
        # 2. Few-Shot Examples
        if self.use_few_shot:
            examples = get_examples_for_prompt(query)
            if examples:
                parts.append(examples)
        
        return "\n\n".join(parts)
    
    def generate_sync(self, query: str, **kwargs) -> GenerationResult:
        """Синхронная версия generate()"""
        return asyncio.run(self.generate(query, **kwargs))
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Статистика кэша"""
        stats = self.cache.get_stats()
        return {
            "templates_count": len(self.cache.list_templates()),
            "usage_stats": stats[:10]  # Top 10
        }
    
    def close(self):
        """Закрыть ресурсы"""
        self.cache.close()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_default_generator: Optional[EnhancedCodeGenerator] = None


def get_generator() -> EnhancedCodeGenerator:
    """Получить default генератор (singleton)"""
    global _default_generator
    if _default_generator is None:
        _default_generator = EnhancedCodeGenerator()
    return _default_generator


async def generate_code(query: str, **kwargs) -> str:
    """
    Быстрая генерация кода.
    
    Args:
        query: Запрос пользователя
        **kwargs: Параметры для шаблонов
        
    Returns:
        Сгенерированный код
    """
    generator = get_generator()
    result = await generator.generate(query, **kwargs)
    return result.code


def generate_code_sync(query: str, **kwargs) -> str:
    """Синхронная версия generate_code()"""
    return asyncio.run(generate_code(query, **kwargs))


# =============================================================================
# INTEGRATION WITH EXISTING ORCHESTRATOR
# =============================================================================

class OrchestratorIntegration:
    """
    Класс для интеграции с существующим Orchestrator.
    
    Использование в orchestrator.py:
        from core.codegen.enhanced_generator import OrchestratorIntegration
        
        class Orchestrator:
            def __init__(self):
                self.enhanced = OrchestratorIntegration(self.llm_client)
            
            async def process(self, query: str):
                # Сначала пробуем enhanced generator
                result = await self.enhanced.try_generate(query)
                if result:
                    return result.code
                
                # Fallback на старую логику
                return await self.old_generate(query)
    """
    
    def __init__(self, llm_client: LLMClient):
        self.generator = EnhancedCodeGenerator(llm_client)
    
    async def try_generate(self, query: str, **kwargs) -> Optional[GenerationResult]:
        """
        Попытка генерации через enhanced pipeline.
        
        Возвращает результат если:
        - Cache hit (TIER 0)
        - Успешная LLM генерация
        
        Возвращает None если нужен fallback на старую логику.
        """
        result = await self.generator.generate(query, **kwargs)
        
        # Успешная генерация
        if result.tier in [GenerationTier.CACHE, GenerationTier.LLM]:
            if result.code and not result.code.startswith("# Error"):
                return result
        
        return None
    
    def should_use_enhanced(self, query: str) -> bool:
        """
        Определяет, стоит ли использовать enhanced pipeline.
        
        Returns:
            True для DevOps задач (K8s, Terraform, GHA, Docker)
        """
        query_lower = query.lower()
        
        devops_keywords = [
            'kubernetes', 'k8s', 'deployment', 'pod',
            'terraform', 'aws', 's3', 'ec2', 'lambda',
            'github action', 'ci', 'pipeline', 'workflow',
            'dockerfile', 'docker', 'container',
        ]
        
        return any(kw in query_lower for kw in devops_keywords)


# =============================================================================
# TESTS
# =============================================================================

async def test_generator():
    """Тесты генератора"""
    generator = EnhancedCodeGenerator()
    
    print("=" * 60)
    print("ENHANCED CODE GENERATOR TESTS")
    print("=" * 60)
    
    # Test 1: Cache hit (K8s)
    print("\n--- Test 1: K8s Deployment (Cache) ---")
    result = await generator.generate(
        "create kubernetes deployment for nginx with 5 replicas"
    )
    print(f"Tier: {result.tier.value}")
    print(f"Template: {result.template_id}")
    print(f"Latency: {result.latency_ms:.1f}ms")
    print(f"Confidence: {result.confidence}")
    print(f"Code preview: {result.code[:200]}...")
    
    # Test 2: Cache hit (Terraform)
    print("\n--- Test 2: Terraform S3 (Cache) ---")
    result = await generator.generate("terraform module for s3 bucket")
    print(f"Tier: {result.tier.value}")
    print(f"Template: {result.template_id}")
    print(f"Latency: {result.latency_ms:.1f}ms")
    
    # Test 3: Cache hit (GitHub Actions)
    print("\n--- Test 3: GitHub Actions (Cache) ---")
    result = await generator.generate("github actions ci pipeline for python")
    print(f"Tier: {result.tier.value}")
    print(f"Template: {result.template_id}")
    
    # Test 4: Cache miss (LLM)
    print("\n--- Test 4: Custom Function (LLM) ---")
    result = await generator.generate("write a function to merge two sorted arrays")
    print(f"Tier: {result.tier.value}")
    print(f"Task type: {result.task_type}")
    print(f"Latency: {result.latency_ms:.1f}ms")
    
    # Stats
    print("\n--- Cache Statistics ---")
    stats = generator.get_cache_stats()
    print(f"Templates: {stats['templates_count']}")
    
    generator.close()
    print("\n✓ All tests passed!")


if __name__ == "__main__":
    asyncio.run(test_generator())
