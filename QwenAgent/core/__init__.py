# QwenCode Core - Full Claude Code Clone
# Все компоненты генератора кода нового поколения

from .agent import QwenAgent, AgentConfig
from .router import PatternRouter, HybridRouter, RouteResult
from .cot_engine import CoTEngine, TaskDecomposer, SelfCorrection
from .tools import Tools, TOOL_REGISTRY
from .tools_extended import ExtendedTools, EXTENDED_TOOL_REGISTRY, execute_tool
from .ducs_classifier import DUCSClassifier, DUCSCategory, classify_task
from .orchestrator import Orchestrator, ProcessingTier, ProcessingResult
from .plan_mode import PlanMode, PlanPhase
from .subagent import SubAgentManager, TaskTracker, TaskTool

__all__ = [
    # Main agent
    'QwenAgent',
    'AgentConfig',

    # Routing (NO-LLM)
    'PatternRouter',
    'HybridRouter',
    'RouteResult',

    # Chain-of-Thought
    'CoTEngine',
    'TaskDecomposer',
    'SelfCorrection',

    # Tools
    'Tools',
    'ExtendedTools',
    'TOOL_REGISTRY',
    'EXTENDED_TOOL_REGISTRY',
    'execute_tool',

    # DUCS Expert System
    'DUCSClassifier',
    'DUCSCategory',
    'classify_task',

    # Orchestrator
    'Orchestrator',
    'ProcessingTier',
    'ProcessingResult',

    # Plan Mode
    'PlanMode',
    'PlanPhase',

    # Sub-agents
    'SubAgentManager',
    'TaskTracker',
    'TaskTool',
]

__version__ = "1.0.0"
__codename__ = "QwenCode"
