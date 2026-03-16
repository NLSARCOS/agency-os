#!/usr/bin/env python3
"""
Agency OS — Base Studio

Abstract base class for all studio pipelines.
Every studio implements the same lifecycle: intake → plan → execute → review → deliver.

Studios integrate with:
- .agent/agents/ — for specialist AI personas
- .agent/skills/ — for domain-specific knowledge
- kernel/model_router.py — for multi-model AI calls
- kernel/state_manager.py — for persistent state & KPIs
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kernel.config import get_config
from kernel.state_manager import get_state

logger = logging.getLogger("agency.studio")


@dataclass
class StudioResult:
    """Result from a studio pipeline execution."""
    output: str = ""
    artifacts: list[str] = field(default_factory=list)
    kpis: list[dict[str, Any]] = field(default_factory=list)
    model_used: str = ""
    duration_seconds: float = 0
    success: bool = True
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "artifacts": self.artifacts,
            "kpis": self.kpis,
            "model_used": self.model_used,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseStudio(ABC):
    """Abstract base class for all Agency OS studios.

    Every studio follows the same 5-phase lifecycle:
    1. intake() — Parse and validate the task
    2. plan() — Create execution plan
    3. execute() — Run the core pipeline
    4. review() — Quality gate + validation
    5. deliver() — Package deliverables

    Studios can use .agent agents and skills for AI-powered operations.
    """

    name: str = "base"
    description: str = "Base studio"
    agent_ref: str = ""  # Reference to .agent/agents/*.md
    skills_refs: list[str] = []  # References to .agent/skills/*/

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self.studio_dir = self.cfg.studios_dir / self.name
        self._model_router = None

    @property
    def model_router(self):
        if self._model_router is None:
            from kernel.model_router import get_model_router
            self._model_router = get_model_router()
        return self._model_router

    def get_agent_prompt(self) -> str:
        """Load the agent system prompt from .agent/agents/."""
        if not self.agent_ref:
            return ""
        agent_path = self.cfg.root / ".agent" / "agents" / f"{self.agent_ref}.md"
        if agent_path.exists():
            return agent_path.read_text(encoding="utf-8")
        return ""

    def get_skill_content(self, skill_name: str) -> str:
        """Load a skill's SKILL.md content."""
        skill_path = self.cfg.root / ".agent" / "skills" / skill_name / "SKILL.md"
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
        return ""

    def ai_call(self, prompt: str, system: str = "", task_id: int | None = None) -> str:
        """Make an AI model call through the model router."""
        if not system:
            system = self.get_agent_prompt()
        response = self.model_router.call_model_sync(
            prompt=prompt,
            studio=self.name,
            system=system,
            task_id=task_id,
        )
        return response.content

    # ── Lifecycle Methods ─────────────────────────────────────

    @abstractmethod
    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        """Phase 1: Parse and validate the incoming task.
        Returns a structured task representation."""
        ...

    @abstractmethod
    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        """Phase 2: Create an execution plan based on intake.
        Returns a plan with steps, resources, and estimates."""
        ...

    @abstractmethod
    def execute(self, plan: dict[str, Any], task_id: int | None = None) -> dict[str, Any]:
        """Phase 3: Run the core pipeline.
        Returns execution results with artifacts."""
        ...

    def review(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Phase 4: Quality gate — validate execution results.
        Override for custom validation logic."""
        # Default: pass-through with basic checks
        output = execution_result.get("output", "")
        passed = bool(output and len(str(output)) > 10)
        return {
            **execution_result,
            "review_passed": passed,
            "review_notes": "Passed basic quality check" if passed else "Output too short or empty",
        }

    def deliver(self, review_result: dict[str, Any]) -> StudioResult:
        """Phase 5: Package deliverables.
        Override for custom packaging logic."""
        return StudioResult(
            output=str(review_result.get("output", "")),
            artifacts=review_result.get("artifacts", []),
            kpis=review_result.get("kpis", []),
            model_used=review_result.get("model_used", ""),
            success=review_result.get("review_passed", True),
        )

    # ── Main Entry Point ──────────────────────────────────────

    def run(
        self,
        task: str,
        description: str = "",
        task_id: int | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Execute the full studio lifecycle."""
        start = time.monotonic()
        logger.info("[%s] Starting pipeline: %s", self.name, task[:80])

        try:
            # Phase 1: Intake
            intake_result = self.intake(task, description, **(metadata or {}))
            logger.info("[%s] Intake complete", self.name)

            # Phase 2: Plan
            plan = self.plan(intake_result)
            logger.info("[%s] Plan created", self.name)

            # Phase 3: Execute
            execution_result = self.execute(plan, task_id)
            logger.info("[%s] Execution complete", self.name)

            # Phase 4: Review
            review_result = self.review(execution_result)
            logger.info("[%s] Review: %s", self.name,
                       "PASSED" if review_result.get("review_passed") else "FAILED")

            # Phase 5: Deliver
            result = self.deliver(review_result)
            result.duration_seconds = time.monotonic() - start

            # Log KPIs
            self.state.log_kpi(self.name, "pipeline_duration", result.duration_seconds, "seconds")
            self.state.log_kpi(self.name, "pipeline_success", 1.0 if result.success else 0.0)

            return result.to_dict()

        except Exception as e:
            duration = time.monotonic() - start
            error_msg = f"{e.__class__.__name__}: {e}"
            logger.error("[%s] Pipeline failed: %s", self.name, error_msg)

            self.state.log_kpi(self.name, "pipeline_success", 0.0)
            self.state.log_kpi(self.name, "pipeline_duration", duration, "seconds")

            return StudioResult(
                success=False,
                error=error_msg,
                duration_seconds=duration,
            ).to_dict()


def load_all_studios() -> dict[str, BaseStudio]:
    """Auto-discover and load all studio implementations."""
    studios: dict[str, BaseStudio] = {}

    # Import each studio's pipeline module
    studio_modules = {
        "dev": "studios.dev.pipeline",
        "marketing": "studios.marketing.pipeline",
        "sales": "studios.sales.pipeline",
        "leadops": "studios.leadops.pipeline",
        "abm": "studios.abm.pipeline",
        "analytics": "studios.analytics.pipeline",
        "creative": "studios.creative.pipeline",
    }

    import importlib
    for name, module_path in studio_modules.items():
        try:
            mod = importlib.import_module(module_path)
            studio_class = getattr(mod, "Studio", None)
            if studio_class:
                studios[name] = studio_class()
                logger.info("Loaded studio: %s", name)
        except (ImportError, AttributeError) as e:
            logger.debug("Studio %s not available: %s", name, e)

    return studios
