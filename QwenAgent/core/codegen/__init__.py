"""
core.codegen — Code Generation Quality Improvements

Modules:
    devops_templates    — TIER 0 template cache (K8s, Terraform, GHA, Dockerfile)
    modernizer          — Post-processing: deprecated fixes (v2→v4, ACL, etc.)
    quality_validator   — 5-level validation pipeline (AST → Lint → Exec → Property → Domain)
    correction_generator— Multi-temperature self-correction with feedback
    feedback_memory     — Working memory + SQLite feedback loop
    quality_prompts     — Task-type-aware prompt injection
    few_shot            — Few-shot example bank
    enhanced_generator  — Feature integration wrapper
    codegen_pipeline    — Full end-to-end pipeline (Template → Prompt → Generate → Validate → Modernize)
"""

__version__ = "1.0.0"
