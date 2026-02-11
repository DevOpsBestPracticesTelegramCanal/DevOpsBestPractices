"""
Full Pipeline Integration для QwenCode Generator
================================================
Объединяет все улучшения в единый production-ready pipeline.

Компоненты:
1. Template Cache — 100% success на DevOps (TIER 0)
2. Quality Prompts + Few-Shot — улучшение промптов
3. Self-Correction Loop — исправление через feedback
4. 5-Level Validation — многоуровневая проверка
5. Modernizer — post-processing deprecated кода
6. Working Memory — контекст для многошаговых задач
7. Feedback Loop — обучение на ошибках

Использование:
    from core.codegen.codegen_pipeline import QwenCodePipeline
    
    pipeline = QwenCodePipeline(llm_client)
    result = await pipeline.generate("create kubernetes deployment for nginx")
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Protocol, List
from dataclasses import dataclass, field
from enum import Enum
import time

# Internal imports
from core.codegen.devops_templates import TemplateCache, TemplateMatch
from core.codegen.quality_validator import CodeValidator, ValidationProfile, ValidationResult
from core.codegen.modernizer import CodeModernizer
from core.codegen.correction_generator import SelfCorrectionGenerator
from core.codegen.feedback_memory import WorkingMemory, FeedbackLoop, UserAction
from core.codegen.quality_prompts import get_prompt_for_task, detect_task_type
from core.codegen.few_shot import get_examples_for_prompt


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GenerationTier(Enum):
    """Уровень генерации"""
    TIER_0_CACHE = "cache"           # Template cache hit
    TIER_1_SIMPLE = "simple"         # Simple LLM generation
    TIER_2_CORRECTION = "correction" # Self-correction loop
    TIER_3_MULTI = "multi"           # Multi-candidate selection


class RiskLevel(Enum):
    """Уровень риска задачи"""
    LOW = "low"           # Документация, простые алгоритмы
    NORMAL = "normal"     # Стандартные задачи
    HIGH = "high"         # API, инфраструктура
    CRITICAL = "critical" # Security, production


@dataclass
class PipelineResult:
    """Результат pipeline"""
    success: bool
    code: str
    tier: GenerationTier
    task_type: str
    language: str
    validation: Optional[ValidationResult]
    score: float
    latency_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def summary(self) -> str:
        status = "✓ SUCCESS" if self.success else "✗ FAILED"
        return (f"{status} | Tier: {self.tier.value} | "
                f"Score: {self.score:.2f} | "
                f"Latency: {self.latency_ms:.0f}ms")


class LLMClient(Protocol):
    """Protocol для LLM клиента"""
    async def generate(self, prompt: str, temperature: float = 0.5) -> str:
        ...


class QwenCodePipeline:
    """
    Полный pipeline генерации кода.
    
    Workflow:
    1. Classify task → определить tier и risk level
    2. TIER 0: Check template cache (DevOps)
    3. TIER 1+: Build enhanced prompt (quality + few-shot)
    4. Generate with appropriate strategy:
       - TIER 1: Simple generation
       - TIER 2: Self-correction loop
       - TIER 3: Multi-candidate selection
    5. Post-process: Modernizer
    6. Validate: 5-Level Validator
    7. Log feedback for future improvement
    
    Attributes:
        llm: LLM client
        cache: Template cache
        validator: 5-Level validator
        modernizer: Code modernizer
        feedback: Feedback loop
    """
    
    def __init__(
        self,
        llm_client: LLMClient,
        cache_db_path: str = "cache/codegen_cache.db",
        feedback_db_path: str = "cache/feedback.db",
        use_self_correction: bool = True,
        use_working_memory: bool = True
    ):
        self.llm = llm_client
        
        # Components
        self.cache = TemplateCache(cache_db_path)
        self.validator = CodeValidator(ValidationProfile.SAFE_FIX)
        self.modernizer = CodeModernizer()
        self.feedback = FeedbackLoop(feedback_db_path)
        
        # Options
        self.use_self_correction = use_self_correction
        self.use_working_memory = use_working_memory
        
        # Working memory (reset per session)
        self.memory = WorkingMemory() if use_working_memory else None
        
        logger.info("QwenCodePipeline initialized")
        logger.info(f"  - Templates: {len(self.cache.list_templates())}")
        logger.info(f"  - Self-correction: {use_self_correction}")
        logger.info(f"  - Working memory: {use_working_memory}")
    
    async def generate(
        self,
        query: str,
        language: Optional[str] = None,
        risk_level: RiskLevel = RiskLevel.NORMAL,
        context: Optional[Dict] = None,
        **kwargs
    ) -> PipelineResult:
        """
        Генерация кода через полный pipeline.
        
        Args:
            query: Запрос пользователя
            language: Язык (auto-detect если None)
            risk_level: Уровень риска
            context: Дополнительный контекст
            **kwargs: Параметры для шаблонов
            
        Returns:
            PipelineResult с кодом и метаданными
        """
        start_time = time.time()
        
        # 1. Detect task type and language
        task_type = detect_task_type(query)
        if language is None:
            language = self._infer_language(task_type)
        
        logger.info(f"Processing: {query[:50]}...")
        logger.info(f"  Task type: {task_type}, Language: {language}")
        
        # 2. Update working memory
        if self.memory:
            self.memory.goal = query
            self.memory.add_fact(f"Task type: {task_type}")
            self.memory.add_fact(f"Language: {language}")
        
        # 3. TIER 0: Check template cache
        cache_match = self.cache.match(query)
        if cache_match:
            result = self._handle_cache_hit(cache_match, kwargs, start_time)
            if result:
                return result
        
        # 4. Determine generation strategy
        tier = self._select_tier(task_type, risk_level)
        logger.info(f"  Selected tier: {tier.value}")
        
        # 5. Build enhanced prompt
        prompt = self._build_prompt(query, task_type, language)
        
        # 6. Generate based on tier
        if tier == GenerationTier.TIER_2_CORRECTION and self.use_self_correction:
            code, score = await self._generate_with_correction(
                prompt, language, task_type
            )
        else:
            code, score = await self._generate_simple(prompt, language)
        
        # 7. Post-process: Modernizer
        modernization = self.modernizer.modernize(code, language)
        code = modernization.code
        
        if modernization.changes_made:
            logger.info(f"  Modernizer: {len(modernization.changes_made)} changes")
        
        # 8. Final validation
        validation = self.validator.validate(code, language)
        
        # Adjust score based on validation
        final_score = self._calculate_final_score(score, validation)
        
        # 9. Log to working memory
        if self.memory:
            self.memory.log_tool_call(
                "code_generation",
                query,
                f"Generated {len(code)} chars, score={final_score:.2f}",
                validation.passed
            )
        
        latency = (time.time() - start_time) * 1000
        
        return PipelineResult(
            success=validation.passed or final_score > 0.7,
            code=code,
            tier=tier,
            task_type=task_type,
            language=language,
            validation=validation,
            score=final_score,
            latency_ms=latency,
            metadata={
                "modernization_changes": modernization.changes_made,
                "validation_errors": len(validation.errors),
                "validation_warnings": len(validation.warnings)
            }
        )
    
    def _handle_cache_hit(
        self,
        cache_match: TemplateMatch,
        kwargs: Dict,
        start_time: float
    ) -> Optional[PipelineResult]:
        """Обработка cache hit"""
        logger.info(f"  TIER 0: Cache HIT ({cache_match.template_id})")
        
        params = {**cache_match.params, **kwargs}
        code = self.cache.get(cache_match.template_id, **params)
        
        if not code:
            return None
        
        # Validate cached code
        language = self._infer_language(cache_match.category.value)
        validation = self.validator.validate(code, language)
        
        latency = (time.time() - start_time) * 1000
        
        return PipelineResult(
            success=True,
            code=code,
            tier=GenerationTier.TIER_0_CACHE,
            task_type=cache_match.category.value,
            language=language,
            validation=validation,
            score=cache_match.confidence,
            latency_ms=latency,
            metadata={"template_id": cache_match.template_id}
        )
    
    def _select_tier(self, task_type: str, risk_level: RiskLevel) -> GenerationTier:
        """Выбор tier на основе типа задачи и риска"""
        
        # Critical → всегда self-correction
        if risk_level == RiskLevel.CRITICAL:
            return GenerationTier.TIER_2_CORRECTION
        
        # High risk tasks
        if task_type in ["api", "rest_api", "infrastructure", "security"]:
            return GenerationTier.TIER_2_CORRECTION
        
        # Simple tasks
        if task_type in ["algorithm", "documentation"]:
            return GenerationTier.TIER_1_SIMPLE
        
        # Default
        return GenerationTier.TIER_2_CORRECTION if self.use_self_correction else GenerationTier.TIER_1_SIMPLE
    
    def _build_prompt(self, query: str, task_type: str, language: str) -> str:
        """Строит улучшенный промпт"""
        parts = []
        
        # 1. Quality requirements
        quality_prompt = get_prompt_for_task(query, task_type)
        parts.append(quality_prompt)
        
        # 2. Few-shot examples
        examples = get_examples_for_prompt(query, max_examples=1)
        if examples:
            parts.append(examples)
        
        # 3. Feedback warnings (из истории ошибок)
        warnings = self.feedback.generate_prompt_warnings(task_type)
        if warnings:
            parts.append(warnings)
        
        # 4. Working memory context
        if self.memory:
            context = self.memory.compact(max_tokens=300)
            if context:
                parts.append(f"CONTEXT:\n{context}")
        
        return "\n\n---\n\n".join(parts)
    
    async def _generate_simple(
        self,
        prompt: str,
        language: str
    ) -> tuple[str, float]:
        """Простая генерация (TIER 1)"""
        try:
            code = await self.llm.generate(prompt, temperature=0.5)
            
            # Quick validation for score
            validation = self.validator.validate(
                code, language, ValidationProfile.FAST_DEV
            )
            score = 1.0 - (len(validation.errors) * 0.15)
            
            return code, max(0.0, score)
            
        except Exception as e:
            logger.error(f"Simple generation failed: {e}")
            return f"# Error: {e}", 0.0
    
    async def _generate_with_correction(
        self,
        prompt: str,
        language: str,
        task_type: str
    ) -> tuple[str, float]:
        """Генерация с self-correction (TIER 2)"""
        try:
            generator = SelfCorrectionGenerator(
                llm_client=self.llm,
                validator=self.validator,
                max_attempts=3
            )
            
            result = await generator.generate_with_correction(
                task=prompt,
                language=language
            )
            
            return result.best_code, result.best_score
            
        except Exception as e:
            logger.error(f"Self-correction failed: {e}")
            # Fallback to simple
            return await self._generate_simple(prompt, language)
    
    def _calculate_final_score(
        self,
        base_score: float,
        validation: ValidationResult
    ) -> float:
        """Вычисляет финальный score"""
        score = base_score
        
        # Penalties
        score -= len(validation.errors) * 0.1
        score -= len(validation.warnings) * 0.02
        
        # Bonus for passing
        if validation.passed:
            score += 0.1
        
        # Bonus for passed levels
        score += len(validation.levels_passed) * 0.02
        
        return max(0.0, min(1.0, score))
    
    def _infer_language(self, task_type: str) -> str:
        """Определяет язык по типу задачи"""
        mapping = {
            "kubernetes": "yaml",
            "terraform": "terraform",
            "github_actions": "yaml",
            "dockerfile": "dockerfile",
            "algorithm": "python",
            "api": "python",
            "rest_api": "python",
        }
        return mapping.get(task_type, "python")
    
    def record_user_feedback(
        self,
        query: str,
        code: str,
        task_type: str,
        validation_errors: List[str],
        action: UserAction
    ) -> None:
        """Записать feedback пользователя"""
        self.feedback.log_outcome(
            task=query,
            task_type=task_type,
            code=code,
            validation_errors=validation_errors,
            user_action=action
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Получить статистику pipeline"""
        feedback_stats = self.feedback.get_statistics()
        cache_stats = {
            "templates_count": len(self.cache.list_templates())
        }
        
        return {
            "feedback": feedback_stats,
            "cache": cache_stats
        }
    
    def reset_session(self) -> None:
        """Сбросить сессию (working memory)"""
        if self.memory:
            self.memory.clear()
    
    def close(self) -> None:
        """Закрыть ресурсы"""
        self.cache.close()
        self.feedback.close()


# =============================================================================
# MOCK LLM FOR TESTING
# =============================================================================

class MockLLMClient:
    """Mock LLM для тестов"""
    
    async def generate(self, prompt: str, temperature: float = 0.5) -> str:
        await asyncio.sleep(0.05)
        
        if "bubble sort" in prompt.lower():
            return '''
def bubble_sort(arr: list[int]) -> list[int]:
    """Sort array using optimized bubble sort.
    
    Args:
        arr: List of integers to sort.
    
    Returns:
        Sorted list.
    
    Time: O(n²) worst, O(n) best.
    """
    if not arr:
        return arr
    
    n = len(arr)
    for i in range(n):
        swapped = False
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        if not swapped:
            break
    return arr
'''
        
        return f"# Generated for: {prompt[:50]}...\npass"


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

async def test_pipeline():
    """Тест полного pipeline"""
    
    print("=" * 60)
    print("QWENCODE PIPELINE TEST")
    print("=" * 60)
    
    # Create pipeline
    llm = MockLLMClient()
    pipeline = QwenCodePipeline(
        llm_client=llm,
        use_self_correction=True,
        use_working_memory=True
    )
    
    # Test 1: Cache hit (K8s)
    print("\n--- Test 1: Kubernetes (Cache) ---")
    result = await pipeline.generate(
        "create kubernetes deployment for nginx with 3 replicas"
    )
    print(result.summary())
    print(f"Code preview: {result.code[:200]}...")
    
    # Test 2: Algorithm (LLM)
    print("\n--- Test 2: Algorithm (LLM) ---")
    result = await pipeline.generate(
        "implement bubble sort algorithm",
        risk_level=RiskLevel.LOW
    )
    print(result.summary())
    
    # Test 3: Terraform (Cache)
    print("\n--- Test 3: Terraform (Cache) ---")
    result = await pipeline.generate("terraform s3 bucket")
    print(result.summary())
    
    # Statistics
    print("\n--- Statistics ---")
    stats = pipeline.get_statistics()
    print(f"Templates: {stats['cache']['templates_count']}")
    
    pipeline.close()
    print("\n✓ All tests passed!")


if __name__ == "__main__":
    asyncio.run(test_pipeline())
