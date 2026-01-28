"""
QwenCode SubAgent System - Task Delegation
Like Claude Code's Task tool for spawning specialized agents
"""

import threading
import queue
import time
import uuid
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class AgentType(Enum):
    """Types of specialized sub-agents"""
    EXPLORE = "explore"          # Codebase exploration
    BASH = "bash"                # Command execution
    PLAN = "plan"                # Planning and architecture
    GENERAL = "general"          # General purpose


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubTask:
    """Represents a delegated task"""
    id: str
    description: str
    agent_type: AgentType
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    run_in_background: bool = False
    output_file: Optional[str] = None


class SubAgentManager:
    """
    Manages sub-agents for task delegation
    Like Claude Code's Task tool
    """

    def __init__(self, llm_client: Callable):
        self.llm_client = llm_client
        self.tasks: Dict[str, SubTask] = {}
        self.background_tasks: Dict[str, threading.Thread] = {}
        self.results_queue = queue.Queue()

    def create_task(
        self,
        description: str,
        prompt: str,
        agent_type: str = "general",
        run_in_background: bool = False
    ) -> SubTask:
        """Create a new sub-task"""
        task_id = str(uuid.uuid4())[:8]

        task = SubTask(
            id=task_id,
            description=description,
            agent_type=AgentType(agent_type) if isinstance(agent_type, str) else agent_type,
            prompt=prompt,
            run_in_background=run_in_background
        )

        self.tasks[task_id] = task
        return task

    def execute_task(self, task: SubTask) -> Dict[str, Any]:
        """Execute a sub-task"""
        task.status = TaskStatus.RUNNING

        try:
            # Build specialized prompt based on agent type
            system_prompt = self._get_agent_system_prompt(task.agent_type)

            # Call LLM
            response = self.llm_client(
                prompt=task.prompt,
                system=system_prompt
            )

            task.result = {
                "response": response,
                "agent_type": task.agent_type.value
            }
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()

            return {
                "success": True,
                "task_id": task.id,
                "result": task.result
            }

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()

            return {
                "success": False,
                "task_id": task.id,
                "error": str(e)
            }

    def run_task_background(self, task: SubTask) -> Dict[str, Any]:
        """Run task in background thread"""
        def worker():
            result = self.execute_task(task)
            self.results_queue.put((task.id, result))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.background_tasks[task.id] = thread

        return {
            "success": True,
            "task_id": task.id,
            "status": "running_in_background",
            "message": f"Task {task.id} started in background"
        }

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Get status of a task"""
        if task_id not in self.tasks:
            return {"success": False, "error": f"Task not found: {task_id}"}

        task = self.tasks[task_id]

        return {
            "success": True,
            "task_id": task_id,
            "status": task.status.value,
            "description": task.description,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None
        }

    def list_tasks(self) -> Dict[str, Any]:
        """List all tasks"""
        tasks_list = []
        for task_id, task in self.tasks.items():
            tasks_list.append({
                "id": task_id,
                "description": task.description,
                "status": task.status.value,
                "agent_type": task.agent_type.value
            })

        return {
            "success": True,
            "count": len(tasks_list),
            "tasks": tasks_list
        }

    def _get_agent_system_prompt(self, agent_type: AgentType) -> str:
        """Get specialized system prompt for agent type"""
        prompts = {
            AgentType.EXPLORE: """You are a codebase exploration specialist.
Your job is to thoroughly explore and understand code structure.
- Search for files and patterns
- Analyze code architecture
- Find relevant implementations
- Summarize your findings clearly""",

            AgentType.BASH: """You are a command execution specialist.
Your job is to run shell commands and process results.
- Execute commands safely
- Parse and summarize output
- Handle errors gracefully
- Report results clearly""",

            AgentType.PLAN: """You are a software architect and planner.
Your job is to design implementation plans.
- Analyze requirements
- Identify critical files and components
- Consider trade-offs
- Create step-by-step plans""",

            AgentType.GENERAL: """You are a general-purpose coding assistant.
Your job is to help with various programming tasks.
- Write and review code
- Debug issues
- Explain concepts
- Provide solutions"""
        }

        return prompts.get(agent_type, prompts[AgentType.GENERAL])


class TaskTool:
    """
    Task tool implementation - delegates to sub-agents
    Like Claude Code's Task tool
    """

    def __init__(self, subagent_manager: SubAgentManager):
        self.manager = subagent_manager

    def __call__(
        self,
        description: str,
        prompt: str,
        subagent_type: str = "general",
        run_in_background: bool = False
    ) -> Dict[str, Any]:
        """
        Execute Task tool - spawn sub-agent

        Args:
            description: Short description (3-5 words)
            prompt: Full task prompt
            subagent_type: Type of agent (explore, bash, plan, general)
            run_in_background: Run asynchronously
        """
        # Validate agent type
        valid_types = ["explore", "bash", "plan", "general"]
        if subagent_type not in valid_types:
            return {
                "success": False,
                "error": f"Invalid subagent_type. Must be one of: {valid_types}"
            }

        # Create task
        task = self.manager.create_task(
            description=description,
            prompt=prompt,
            agent_type=subagent_type,
            run_in_background=run_in_background
        )

        # Execute
        if run_in_background:
            return self.manager.run_task_background(task)
        else:
            return self.manager.execute_task(task)


# Task list management (like Claude Code's TaskCreate, TaskUpdate, TaskList)
@dataclass
class UserTask:
    """User-facing task for tracking work"""
    id: str
    subject: str
    description: str
    status: str = "pending"  # pending, in_progress, completed
    owner: Optional[str] = None
    blocks: List[str] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


class TaskTracker:
    """Track user tasks like Claude Code's todo system"""

    def __init__(self):
        self.tasks: Dict[str, UserTask] = {}
        self._counter = 0

    def create(self, subject: str, description: str) -> Dict[str, Any]:
        """Create a new task"""
        self._counter += 1
        task_id = str(self._counter)

        task = UserTask(
            id=task_id,
            subject=subject,
            description=description
        )
        self.tasks[task_id] = task

        return {
            "success": True,
            "task_id": task_id,
            "message": f"Task #{task_id} created: {subject}"
        }

    def update(
        self,
        task_id: str,
        status: str = None,
        subject: str = None,
        description: str = None
    ) -> Dict[str, Any]:
        """Update a task"""
        if task_id not in self.tasks:
            return {"success": False, "error": f"Task not found: {task_id}"}

        task = self.tasks[task_id]

        if status:
            task.status = status
        if subject:
            task.subject = subject
        if description:
            task.description = description

        return {
            "success": True,
            "task_id": task_id,
            "status": task.status
        }

    def get(self, task_id: str) -> Dict[str, Any]:
        """Get task details"""
        if task_id not in self.tasks:
            return {"success": False, "error": f"Task not found: {task_id}"}

        task = self.tasks[task_id]
        return {
            "success": True,
            "task": {
                "id": task.id,
                "subject": task.subject,
                "description": task.description,
                "status": task.status,
                "blocks": task.blocks,
                "blocked_by": task.blocked_by
            }
        }

    def list_all(self) -> Dict[str, Any]:
        """List all tasks"""
        tasks_list = []
        for task in self.tasks.values():
            tasks_list.append({
                "id": task.id,
                "subject": task.subject,
                "status": task.status
            })

        return {
            "success": True,
            "count": len(tasks_list),
            "tasks": tasks_list
        }
