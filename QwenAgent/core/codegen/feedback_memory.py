"""
Working Memory и Feedback Loop для QwenCode Generator
=====================================================
Решает проблемы:
- Модель "забывает" контекст после 3-4 шагов
- Повторяет одни и те же ошибки (примитивные регулярки)

Working Memory: Структурированное сохранение контекста между шагами.
Feedback Loop: Анализ ошибок для улучшения будущих генераций.

Использование:
    from core.codegen.feedback_memory import WorkingMemory, FeedbackLoop
    
    memory = WorkingMemory()
    memory.goal = "Implement REST API"
    memory.add_fact("Using FastAPI framework")
    memory.add_decision("Chose Pydantic for validation")
    
    feedback = FeedbackLoop()
    feedback.log_outcome(task, code, validation, user_action)
    anti_patterns = feedback.get_anti_patterns()
"""

import json
import sqlite3
import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib


# =============================================================================
# WORKING MEMORY
# =============================================================================

@dataclass
class WorkingMemory:
    """
    Структурированная рабочая память для многошаговых задач.
    
    Сохраняет:
    - goal: Цель задачи
    - plan: Шаги выполнения
    - facts: Извлечённые факты
    - decisions: Принятые решения
    - tool_log: История вызовов инструментов
    
    Attributes:
        goal: Текущая цель
        plan: Список шагов плана
        facts: Извлечённые факты
        decisions: Принятые решения
        tool_log: Лог вызовов инструментов
    """
    
    goal: str = ""
    plan: List[str] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    tool_log: List[Dict[str, Any]] = field(default_factory=list)
    
    # Limits
    MAX_FACTS = 20
    MAX_DECISIONS = 10
    MAX_TOOL_LOG = 50
    
    def add_fact(self, fact: str) -> None:
        """Добавить факт"""
        if fact not in self.facts:
            self.facts.append(fact)
            # Ограничиваем размер (FIFO)
            if len(self.facts) > self.MAX_FACTS:
                self.facts = self.facts[-self.MAX_FACTS:]
    
    def add_decision(self, decision: str, reason: Optional[str] = None) -> None:
        """Добавить решение с опциональной причиной"""
        entry = decision
        if reason:
            entry = f"{decision} (reason: {reason})"
        
        if entry not in self.decisions:
            self.decisions.append(entry)
            if len(self.decisions) > self.MAX_DECISIONS:
                self.decisions = self.decisions[-self.MAX_DECISIONS:]
    
    def log_tool_call(
        self, 
        tool_name: str, 
        input_data: Any, 
        output_data: Any,
        success: bool = True
    ) -> None:
        """Логировать вызов инструмента"""
        self.tool_log.append({
            "tool": tool_name,
            "input": str(input_data)[:200],
            "output": str(output_data)[:200],
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        
        if len(self.tool_log) > self.MAX_TOOL_LOG:
            self.tool_log = self.tool_log[-self.MAX_TOOL_LOG:]
    
    def set_plan(self, steps: List[str]) -> None:
        """Установить план выполнения"""
        self.plan = steps
    
    def complete_step(self, step_index: int) -> None:
        """Отметить шаг как выполненный"""
        if 0 <= step_index < len(self.plan):
            self.plan[step_index] = f"✓ {self.plan[step_index]}"
    
    def compact(self, max_tokens: int = 2000) -> str:
        """
        Сжатие памяти в текст для промпта.
        
        Выбирает наиболее релевантную информацию,
        чтобы уложиться в max_tokens.
        """
        sections = []
        
        if self.goal:
            sections.append(f"GOAL: {self.goal}")
        
        if self.plan:
            plan_str = ", ".join(self.plan[:5])  # Top 5 steps
            sections.append(f"PLAN: {plan_str}")
        
        if self.facts:
            # Последние 5 фактов
            facts_str = ", ".join(self.facts[-5:])
            sections.append(f"FACTS: {facts_str}")
        
        if self.decisions:
            # Последние 3 решения
            decisions_str = ", ".join(self.decisions[-3:])
            sections.append(f"DECISIONS: {decisions_str}")
        
        # Собираем и обрезаем
        result = "\n".join(sections)
        
        # Грубая оценка токенов (4 символа = 1 токен)
        estimated_tokens = len(result) // 4
        if estimated_tokens > max_tokens:
            # Обрезаем до лимита
            result = result[:max_tokens * 4]
        
        return result
    
    def to_dict(self) -> Dict:
        """Сериализация в dict"""
        return {
            "goal": self.goal,
            "plan": self.plan,
            "facts": self.facts,
            "decisions": self.decisions,
            "tool_log": self.tool_log
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "WorkingMemory":
        """Десериализация из dict"""
        memory = cls()
        memory.goal = data.get("goal", "")
        memory.plan = data.get("plan", [])
        memory.facts = data.get("facts", [])
        memory.decisions = data.get("decisions", [])
        memory.tool_log = data.get("tool_log", [])
        return memory
    
    def clear(self) -> None:
        """Очистить память"""
        self.goal = ""
        self.plan = []
        self.facts = []
        self.decisions = []
        self.tool_log = []


# =============================================================================
# FEEDBACK LOOP
# =============================================================================

class UserAction(Enum):
    """Действие пользователя с результатом генерации"""
    APPLIED = "applied"       # Код применён
    MODIFIED = "modified"     # Код модифицирован
    REJECTED = "rejected"     # Код отклонён
    ROLLBACK = "rollback"     # Откат изменений


@dataclass
class GenerationOutcome:
    """Результат генерации с обратной связью"""
    task_hash: str
    task_type: str
    swecas_code: str
    code_hash: str
    validation_errors: List[str]
    user_action: UserAction
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class FeedbackLoop:
    """
    Система обратной связи для обучения на ошибках.
    
    Логирует:
    - Результаты генерации
    - Ошибки валидации
    - Действия пользователя (applied/rejected/rollback)
    
    Анализирует:
    - Частые ошибки → формирует анти-паттерны
    - Успешные генерации → best practices
    
    Attributes:
        db_path: Путь к SQLite базе данных
    """
    
    def __init__(self, db_path: str = "cache/feedback.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_db()
    
    def _init_db(self) -> None:
        """Инициализация схемы БД"""
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_hash TEXT NOT NULL,
                task_type TEXT,
                swecas_code TEXT,
                code_hash TEXT,
                validation_errors TEXT,
                user_action TEXT,
                timestamp TEXT,
                metadata TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_task_type ON outcomes(task_type);
            CREATE INDEX IF NOT EXISTS idx_user_action ON outcomes(user_action);
            CREATE INDEX IF NOT EXISTS idx_timestamp ON outcomes(timestamp);
            
            CREATE TABLE IF NOT EXISTS anti_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT UNIQUE,
                occurrences INTEGER DEFAULT 1,
                severity TEXT DEFAULT 'warning',
                fix_suggestion TEXT,
                last_seen TEXT
            );
            
            CREATE TABLE IF NOT EXISTS best_practices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT,
                pattern TEXT,
                success_rate REAL,
                last_seen TEXT
            );
        ''')
        self.conn.commit()
    
    def log_outcome(
        self,
        task: str,
        task_type: str,
        code: str,
        validation_errors: List[str],
        user_action: UserAction,
        swecas_code: str = "",
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Логировать результат генерации.
        
        Args:
            task: Описание задачи
            task_type: Тип задачи (algorithm, api, etc.)
            code: Сгенерированный код
            validation_errors: Список ошибок валидации
            user_action: Действие пользователя
            swecas_code: SWECAS код задачи
            metadata: Дополнительные метаданные
        """
        task_hash = hashlib.sha256(task.encode()).hexdigest()[:16]
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        
        self.conn.execute('''
            INSERT INTO outcomes 
            (task_hash, task_type, swecas_code, code_hash, validation_errors, 
             user_action, timestamp, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task_hash,
            task_type,
            swecas_code,
            code_hash,
            json.dumps(validation_errors),
            user_action.value,
            datetime.now().isoformat(),
            json.dumps(metadata or {})
        ))
        self.conn.commit()
        
        # Анализируем ошибки для анти-паттернов
        if user_action in [UserAction.REJECTED, UserAction.ROLLBACK]:
            for error in validation_errors:
                self._record_anti_pattern(error)
    
    def _record_anti_pattern(self, error: str) -> None:
        """Записать анти-паттерн"""
        # Нормализуем ошибку (убираем номера строк и т.д.)
        normalized = self._normalize_error(error)
        
        self.conn.execute('''
            INSERT INTO anti_patterns (pattern, occurrences, last_seen)
            VALUES (?, 1, ?)
            ON CONFLICT(pattern) DO UPDATE SET
                occurrences = occurrences + 1,
                last_seen = excluded.last_seen
        ''', (normalized, datetime.now().isoformat()))
        self.conn.commit()
    
    def _normalize_error(self, error: str) -> str:
        """Нормализация ошибки для группировки"""
        import re
        
        # Убираем номера строк
        error = re.sub(r'line \d+', 'line N', error)
        # Убираем конкретные имена переменных
        error = re.sub(r"'[^']+'\s+is", "'VAR' is", error)
        # Убираем пути к файлам
        error = re.sub(r'/[^\s]+\.py', '/FILE.py', error)
        
        return error.strip()[:200]  # Limit length
    
    def get_anti_patterns(self, min_occurrences: int = 5) -> List[Dict]:
        """
        Получить частые анти-паттерны.
        
        Args:
            min_occurrences: Минимум повторений для включения
            
        Returns:
            Список анти-паттернов с частотой
        """
        cursor = self.conn.execute('''
            SELECT pattern, occurrences, severity, fix_suggestion
            FROM anti_patterns
            WHERE occurrences >= ?
            ORDER BY occurrences DESC
            LIMIT 20
        ''', (min_occurrences,))
        
        return [
            {
                "pattern": row[0],
                "occurrences": row[1],
                "severity": row[2],
                "fix_suggestion": row[3]
            }
            for row in cursor.fetchall()
        ]
    
    def get_success_rate(self, task_type: str) -> float:
        """
        Получить процент успешных генераций для типа задачи.
        
        Returns:
            Success rate (0.0 - 1.0)
        """
        cursor = self.conn.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN user_action = 'applied' THEN 1 ELSE 0 END) as success
            FROM outcomes
            WHERE task_type = ?
        ''', (task_type,))
        
        row = cursor.fetchone()
        if row and row[0] > 0:
            return row[1] / row[0]
        return 0.0
    
    def get_common_errors(self, task_type: str, limit: int = 10) -> List[str]:
        """
        Получить частые ошибки для типа задачи.
        
        Returns:
            Список строк с ошибками
        """
        cursor = self.conn.execute('''
            SELECT validation_errors
            FROM outcomes
            WHERE task_type = ? AND user_action IN ('rejected', 'rollback')
            ORDER BY timestamp DESC
            LIMIT 100
        ''', (task_type,))
        
        # Собираем все ошибки
        all_errors = []
        for row in cursor.fetchall():
            errors = json.loads(row[0])
            all_errors.extend(errors)
        
        # Считаем частоту
        from collections import Counter
        error_counts = Counter(all_errors)
        
        return [error for error, _ in error_counts.most_common(limit)]
    
    def generate_prompt_warnings(self, task_type: str) -> str:
        """
        Генерирует warnings для промпта на основе исторических ошибок.
        
        Returns:
            Строка с предупреждениями для инъекции в промпт
        """
        anti_patterns = self.get_anti_patterns(min_occurrences=3)
        common_errors = self.get_common_errors(task_type, limit=5)
        
        if not anti_patterns and not common_errors:
            return ""
        
        warnings = ["CRITICAL: Avoid these common mistakes:"]
        
        # Добавляем анти-паттерны
        for ap in anti_patterns[:5]:
            warnings.append(f"- {ap['pattern']}")
        
        # Добавляем частые ошибки для этого типа
        for error in common_errors[:3]:
            if error not in [ap['pattern'] for ap in anti_patterns]:
                warnings.append(f"- {error}")
        
        return "\n".join(warnings)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Получить общую статистику"""
        cursor = self.conn.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN user_action = 'applied' THEN 1 ELSE 0 END) as applied,
                SUM(CASE WHEN user_action = 'modified' THEN 1 ELSE 0 END) as modified,
                SUM(CASE WHEN user_action = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN user_action = 'rollback' THEN 1 ELSE 0 END) as rollback
            FROM outcomes
        ''')
        
        row = cursor.fetchone()
        
        # Анти-паттерны
        ap_cursor = self.conn.execute('SELECT COUNT(*) FROM anti_patterns')
        ap_count = ap_cursor.fetchone()[0]
        
        return {
            "total_generations": row[0],
            "applied": row[1],
            "modified": row[2],
            "rejected": row[3],
            "rollback": row[4],
            "success_rate": row[1] / row[0] if row[0] > 0 else 0,
            "anti_patterns_count": ap_count
        }
    
    def close(self) -> None:
        """Закрыть соединение"""
        self.conn.close()


# =============================================================================
# MEMORY-AWARE AGENT
# =============================================================================

class MemoryAwareAgent:
    """
    Агент с рабочей памятью для многошаговых задач.
    
    Интегрирует WorkingMemory и FeedbackLoop в процесс генерации.
    """
    
    def __init__(self, llm_client, feedback_db: str = "cache/feedback.db"):
        self.llm = llm_client
        self.memory = WorkingMemory()
        self.feedback = FeedbackLoop(feedback_db)
    
    async def process_task(self, query: str, task_type: str = "general") -> str:
        """
        Обработка задачи с использованием памяти.
        
        Шаги:
        1. Установить цель
        2. Анализ задачи
        3. Построение плана
        4. Генерация с контекстом памяти
        """
        # Устанавливаем цель
        self.memory.goal = query
        
        # Получаем warnings из истории
        warnings = self.feedback.generate_prompt_warnings(task_type)
        
        # Шаг 1: Анализ
        analysis_prompt = f"""
Analyze this task and extract key requirements:
{query}

Return a brief analysis in 2-3 sentences.
"""
        analysis = await self.llm.generate(analysis_prompt)
        self.memory.add_fact(f"Task analysis: {analysis[:100]}")
        
        # Шаг 2: План
        plan_prompt = f"""
Create a step-by-step plan for:
{query}

Analysis: {analysis}

Return 3-5 steps.
"""
        plan = await self.llm.generate(plan_prompt)
        self.memory.set_plan(plan.split('\n')[:5])
        
        # Шаг 3: Генерация с контекстом памяти
        context = self.memory.compact(max_tokens=500)
        
        generation_prompt = f"""
{context}

{warnings}

Generate code for: {query}

Follow best practices from top GitHub repositories.
"""
        
        code = await self.llm.generate(generation_prompt)
        
        # Логируем вызов инструмента
        self.memory.log_tool_call(
            tool_name="code_generation",
            input_data=query,
            output_data=code[:200],
            success=True
        )
        
        return code
    
    def record_feedback(
        self,
        task: str,
        task_type: str,
        code: str,
        validation_errors: List[str],
        user_action: UserAction
    ) -> None:
        """Записать feedback пользователя"""
        self.feedback.log_outcome(
            task=task,
            task_type=task_type,
            code=code,
            validation_errors=validation_errors,
            user_action=user_action
        )
    
    def reset_memory(self) -> None:
        """Сбросить рабочую память"""
        self.memory.clear()


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Test Working Memory
    print("=== Working Memory Test ===")
    memory = WorkingMemory()
    
    memory.goal = "Implement REST API for user management"
    memory.set_plan([
        "Define User model",
        "Create CRUD endpoints",
        "Add authentication",
        "Write tests"
    ])
    memory.add_fact("Using FastAPI framework")
    memory.add_fact("PostgreSQL database")
    memory.add_decision("Use Pydantic for validation", "Type safety")
    memory.log_tool_call("code_gen", "create user model", "class User...", True)
    
    print("Memory compact:")
    print(memory.compact())
    
    # Test Feedback Loop
    print("\n=== Feedback Loop Test ===")
    feedback = FeedbackLoop("cache/test_feedback.db")
    
    # Логируем несколько outcomes
    for i in range(10):
        feedback.log_outcome(
            task=f"Create user endpoint {i}",
            task_type="api",
            code="def create_user():\n    pass",
            validation_errors=["Missing type hints", "No docstring"] if i % 3 == 0 else [],
            user_action=UserAction.APPLIED if i % 3 != 0 else UserAction.REJECTED
        )
    
    print("Statistics:", feedback.get_statistics())
    print("Anti-patterns:", feedback.get_anti_patterns(min_occurrences=1))
    print("Success rate (api):", feedback.get_success_rate("api"))
    print("Prompt warnings:\n", feedback.generate_prompt_warnings("api"))
    
    feedback.close()
    
    # Cleanup test db
    os.remove("cache/test_feedback.db")
