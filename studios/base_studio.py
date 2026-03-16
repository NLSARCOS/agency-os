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

    v3.0: Integrated with tools, memory, OpenClaw, and workflows.
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
        self._tool_executor = None
        self._memory_manager = None
        self._openclaw = None

    @property
    def model_router(self):
        if self._model_router is None:
            from kernel.model_router import get_model_router
            self._model_router = get_model_router()
        return self._model_router

    @property
    def tools(self):
        """Access the sandboxed tool executor."""
        if self._tool_executor is None:
            from kernel.tool_executor import get_tool_executor
            self._tool_executor = get_tool_executor()
        return self._tool_executor

    @property
    def memory(self):
        """Access the memory manager."""
        if self._memory_manager is None:
            from kernel.memory_manager import get_memory_manager
            self._memory_manager = get_memory_manager()
        return self._memory_manager

    @property
    def openclaw(self):
        """Access the OpenClaw bridge."""
        if self._openclaw is None:
            from kernel.openclaw_bridge import get_openclaw
            self._openclaw = get_openclaw()
        return self._openclaw

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

    # ── AI Calls (v3.0: OpenClaw → model_router fallback) ─────

    def ai_call(self, prompt: str, system: str = "", task_id: int | None = None) -> str:
        """Make an AI call through OpenClaw or model_router fallback."""
        if not system:
            system = self.get_agent_prompt()

        # Inject memory context
        memory_context = self.memory.get_context_for_agent(
            agent_id=self.agent_ref or self.name,
            task=prompt[:200],
            max_memory=3,
            max_knowledge=2,
        )
        if memory_context:
            prompt = f"{prompt}\n\n## Context\n{memory_context}"

        # Try OpenClaw first
        try:
            if self.openclaw.is_available():
                response = self.openclaw.chat(
                    messages=[
                        {"role": "system", "content": system[:3000]},
                        {"role": "user", "content": prompt},
                    ],
                    agent_id=self.agent_ref or self.name,
                )
                content = response.get("content", "")
                if content:
                    # Store in memory
                    self.memory.store(
                        self.agent_ref or self.name,
                        "assistant", content[:500],
                    )
                    return content
        except Exception as e:
            logger.debug("OpenClaw call failed, falling back: %s", e)

        # Fallback to model_router
        response = self.model_router.call_model_sync(
            prompt=prompt,
            studio=self.name,
            system=system,
            task_id=task_id,
        )
        content = response.content

        # Store in memory
        self.memory.store(
            self.agent_ref or self.name,
            "assistant", content[:500],
        )
        return content

    # ── Tool Shortcuts ────────────────────────────────────────

    def web_search(self, query: str) -> str:
        """Search the web using Brave API."""
        result = self.tools.execute(
            "search_web", {"query": query},
            agent_id=self.agent_ref or self.name,
        )
        return result.output if result.success else ""

    def scrape_url(self, url: str) -> str:
        """Scrape text content from a URL."""
        result = self.tools.execute(
            "scrape_url", {"url": url},
            agent_id=self.agent_ref or self.name,
        )
        return result.output if result.success else ""

    def shell(self, command: str, cwd: str = "") -> str:
        """Execute a shell command."""
        params: dict[str, Any] = {"command": command}
        if cwd:
            params["cwd"] = cwd
        result = self.tools.execute(
            "shell", params,
            agent_id=self.agent_ref or self.name,
        )
        return result.output if result.success else f"Error: {result.error}"

    def save_output(self, filename: str, content: str) -> Path:
        """Save output to the studio's output directory."""
        output_dir = self.cfg.reports_dir / self.name
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    # ── Lifecycle Methods ─────────────────────────────────────

    @abstractmethod
    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        """Phase 1: Parse and validate the incoming task."""
        ...

    @abstractmethod
    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        """Phase 2: Create an execution plan based on intake."""
        ...

    @abstractmethod
    def execute(self, plan: dict[str, Any], task_id: int | None = None) -> dict[str, Any]:
        """Phase 3: Run the core pipeline."""
        ...

    def review(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Phase 4: Quality gate — validate execution results."""
        output = execution_result.get("output", "")
        passed = bool(output and len(str(output)) > 10)
        return {
            **execution_result,
            "review_passed": passed,
            "review_notes": "Passed basic quality check" if passed else "Output too short or empty",
        }

    def deliver(self, review_result: dict[str, Any]) -> StudioResult:
        """Phase 5: Package deliverables."""
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

        # Store task in memory
        self.memory.store(
            self.agent_ref or self.name,
            "user", f"[{self.name}] {task[:300]}",
        )

        try:
            intake_result = self.intake(task, description, **(metadata or {}))
            logger.info("[%s] Intake complete", self.name)

            plan = self.plan(intake_result)
            logger.info("[%s] Plan created", self.name)

            execution_result = self.execute(plan, task_id)
            logger.info("[%s] Execution complete", self.name)

            review_result = self.review(execution_result)
            logger.info("[%s] Review: %s", self.name,
                       "PASSED" if review_result.get("review_passed") else "FAILED")

            result = self.deliver(review_result)
            result.duration_seconds = time.monotonic() - start

            # Log KPIs
            self.state.log_kpi(self.name, "pipeline_duration", result.duration_seconds, "seconds")
            self.state.log_kpi(self.name, "pipeline_success", 1.0 if result.success else 0.0)

            # Store result as knowledge
            if result.success and result.output:
                self.memory.learn(
                    topic=f"{self.name}:{intake_result.get('operation', 'task')}",
                    content=result.output[:500],
                    source_agent=self.agent_ref or self.name,
                    tags=[self.name, intake_result.get("operation", "")],
                )

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
