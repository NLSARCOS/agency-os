#!/usr/bin/env python3
"""
Agency OS v5.0 — Project Manager

The brain that decomposes complex goals into multi-studio PROJECTS:

  "Build a website and sell it" →
    Phase 1: dev    → build the website
    Phase 2: creative → write copy and brand assets
    Phase 3: marketing → create launch campaign
    Phase 4: sales   → outreach to prospects
    Phase 5: analytics → set up tracking

This is what makes Agency OS a REAL agency, not just a tool.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus

logger = logging.getLogger("agency.project_manager")


@dataclass
class ProjectPhase:
    """A single phase in a project."""
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    studio: str = ""
    task: str = ""
    description: str = ""
    depends_on: list[str] = field(default_factory=list)  # Phase IDs
    status: str = "pending"  # pending | running | completed | failed | skipped
    result: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0
    order: int = 0


@dataclass
class Project:
    """A multi-studio project with phases."""
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    name: str = ""
    goal: str = ""
    phases: list[ProjectPhase] = field(default_factory=list)
    status: str = "planning"  # planning | executing | completed | failed
    current_phase: int = 0
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = ""
    total_duration_ms: float = 0


# ── Project Templates (common agency workflows) ──────────

PROJECT_TEMPLATES: dict[str, list[dict]] = {
    "build_and_launch": [
        {"studio": "dev", "task": "Build {goal}", "order": 1},
        {"studio": "creative", "task": "Create brand assets and copy for {goal}", "order": 2},
        {"studio": "marketing", "task": "Create launch campaign for {goal}", "order": 3},
        {"studio": "analytics", "task": "Set up tracking and KPIs for {goal}", "order": 4},
    ],
    "build_and_sell": [
        {"studio": "dev", "task": "Build {goal}", "order": 1},
        {"studio": "creative", "task": "Create landing page copy for {goal}", "order": 2},
        {"studio": "marketing", "task": "Create marketing campaign for {goal}", "order": 3},
        {"studio": "sales", "task": "Create sales outreach for {goal}", "order": 4},
        {"studio": "analytics", "task": "Track sales pipeline for {goal}", "order": 5},
    ],
    "lead_gen_pipeline": [
        {"studio": "leadops", "task": "Find and qualify leads for {goal}", "order": 1},
        {"studio": "sales", "task": "Create outreach sequences for leads", "order": 2},
        {"studio": "marketing", "task": "Create nurture campaign for leads", "order": 3},
        {"studio": "analytics", "task": "Track conversion funnel", "order": 4},
    ],
    "content_campaign": [
        {"studio": "analytics", "task": "Research audience and competitors for {goal}", "order": 1},
        {"studio": "creative", "task": "Create content strategy for {goal}", "order": 2},
        {"studio": "marketing", "task": "Execute content campaign for {goal}", "order": 3},
        {"studio": "analytics", "task": "Measure campaign performance", "order": 4},
    ],
    "abm_campaign": [
        {"studio": "leadops", "task": "Identify target accounts for {goal}", "order": 1},
        {"studio": "abm", "task": "Create personalized outreach per account", "order": 2},
        {"studio": "sales", "task": "Execute multi-channel outreach", "order": 3},
        {"studio": "analytics", "task": "Track account engagement", "order": 4},
    ],
    "product_launch": [
        {"studio": "dev", "task": "Build and deploy {goal}", "order": 1},
        {"studio": "creative", "task": "Create launch assets (copy, visuals, messaging)", "order": 2},
        {"studio": "marketing", "task": "Create launch campaign + PR strategy", "order": 3},
        {"studio": "sales", "task": "Prepare sales team: scripts, demos, objections", "order": 4},
        {"studio": "leadops", "task": "Build prospect lists for launch", "order": 5},
        {"studio": "analytics", "task": "Launch day tracking + 30-day metrics plan", "order": 6},
    ],
}

# Keywords that map goals to templates
TEMPLATE_SIGNALS: dict[str, list[str]] = {
    "build_and_sell": [
        "build and sell", "create and sell", "make and sell",
        "build a website and sell", "create something to sell",
    ],
    "build_and_launch": [
        "build and launch", "create and launch", "make and launch",
        "build a website", "create a web", "build an app",
        "build a landing page", "create a site",
    ],
    "product_launch": [
        "product launch", "launch a product", "go to market",
        "launch strategy", "release a product",
    ],
    "lead_gen_pipeline": [
        "lead generation", "find leads", "generate leads",
        "prospect list", "find customers",
    ],
    "content_campaign": [
        "content campaign", "content strategy", "create content",
        "blog strategy", "social media campaign",
    ],
    "abm_campaign": [
        "abm", "account based", "target account",
        "enterprise outreach", "personalized outreach",
    ],
}


class ProjectManager:
    """
    The Agency Brain: decomposes complex goals into multi-studio projects.

    This is what makes Agency OS act like a REAL agency:
    - "Build a website and sell it" → 5 phases across 5 studios
    - "Launch a product" → 6 phases across 6 studios
    - Each phase runs in order, passing output to the next
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._bus = get_event_bus()
        self._projects: dict[str, Project] = {}

    def plan_project(
        self,
        goal: str,
        template: str = "",
        context: dict[str, Any] | None = None,
    ) -> Project:
        """
        Decompose a goal into a multi-studio project.

        Either use a named template or auto-detect from the goal.
        """
        if not template:
            template = self._detect_template(goal)

        phases_config = PROJECT_TEMPLATES.get(template, [])
        if not phases_config:
            # Fallback: single phase with auto-detected studio
            phases_config = [{"studio": "dev", "task": goal, "order": 1}]

        phases = []
        for cfg in phases_config:
            phase = ProjectPhase(
                studio=cfg["studio"],
                task=cfg["task"].format(goal=goal),
                description=f"Phase {cfg['order']}: {cfg['studio']} studio",
                order=cfg["order"],
            )
            # Each phase depends on the previous one
            if phases:
                phase.depends_on = [phases[-1].id]
            phases.append(phase)

        project = Project(
            name=f"Project: {goal[:80]}",
            goal=goal,
            phases=phases,
            context=context or {},
        )

        self._projects[project.id] = project

        self._bus.publish_sync(Event(
            type="project.planned",
            source="project_manager",
            payload={
                "project_id": project.id,
                "goal": goal[:200],
                "template": template,
                "phases": len(phases),
                "studios": [p.studio for p in phases],
            },
        ))

        logger.info(
            "Project planned [%s]: %d phases → %s",
            project.id, len(phases),
            " → ".join(p.studio for p in phases),
        )

        return project

    def execute_project(
        self,
        project_id: str,
        auto_git: bool = False,
    ) -> Project:
        """
        Execute ALL phases of a project sequentially.

        Each phase's output feeds into the next phase's context.
        """
        project = self._projects.get(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        project.status = "executing"
        start = time.monotonic()

        self._bus.publish_sync(Event(
            type="project.started",
            source="project_manager",
            payload={"project_id": project.id, "goal": project.goal[:200]},
        ))

        accumulated_context = dict(project.context)
        all_success = True

        for i, phase in enumerate(project.phases):
            project.current_phase = i

            logger.info(
                "Project [%s] Phase %d/%d: %s → %s",
                project.id, i + 1, len(project.phases),
                phase.studio, phase.task[:80],
            )

            # Check dependencies
            for dep_id in phase.depends_on:
                dep = next((p for p in project.phases if p.id == dep_id), None)
                if dep and dep.status == "failed":
                    phase.status = "skipped"
                    logger.warning("Phase skipped (dependency failed): %s", phase.studio)
                    continue

            # Execute phase
            phase.status = "running"
            phase_start = time.monotonic()

            try:
                from kernel.orchestrator import get_orchestrator
                orch = get_orchestrator()

                # Include accumulated context from previous phases
                phase_context = {
                    **accumulated_context,
                    "project_id": project.id,
                    "phase": i + 1,
                    "total_phases": len(project.phases),
                    "auto_git": auto_git,
                }

                # Execute via orchestrator
                ot = orch.orchestrate(
                    task=phase.task,
                    studio=phase.studio,
                    context=phase_context,
                )

                phase.result = {
                    "output": ot.result.get("output", "")[:3000],
                    "success": ot.status == "completed",
                    "quality_score": ot.quality_score,
                    "model_used": ot.model_used,
                    "files_created": ot.result.get("actions", {}).get("files_created", []),
                }
                phase.status = "completed" if ot.status == "completed" else "failed"

                # Accumulate context for next phase
                accumulated_context[f"phase_{i + 1}_output"] = phase.result.get("output", "")[:1000]
                accumulated_context[f"phase_{i + 1}_studio"] = phase.studio

            except Exception as e:
                phase.status = "failed"
                phase.result = {"error": str(e), "success": False}
                all_success = False
                logger.error("Phase failed: %s — %s", phase.studio, e)

            phase.duration_ms = (time.monotonic() - phase_start) * 1000

            self._bus.publish_sync(Event(
                type="project.phase_complete",
                source="project_manager",
                payload={
                    "project_id": project.id,
                    "phase": i + 1,
                    "studio": phase.studio,
                    "status": phase.status,
                    "duration_ms": phase.duration_ms,
                },
            ))

        project.status = "completed" if all_success else "failed"
        project.completed_at = datetime.now(timezone.utc).isoformat()
        project.total_duration_ms = (time.monotonic() - start) * 1000

        self._bus.publish_sync(Event(
            type="project.completed",
            source="project_manager",
            payload={
                "project_id": project.id,
                "status": project.status,
                "phases_completed": sum(
                    1 for p in project.phases if p.status == "completed"
                ),
                "total_phases": len(project.phases),
                "duration_ms": project.total_duration_ms,
            },
        ))

        logger.info(
            "Project [%s] %s: %d/%d phases completed in %.0fms",
            project.id, project.status,
            sum(1 for p in project.phases if p.status == "completed"),
            len(project.phases), project.total_duration_ms,
        )

        return project

    def plan_and_execute(
        self,
        goal: str,
        template: str = "",
        auto_git: bool = False,
        context: dict[str, Any] | None = None,
    ) -> Project:
        """One-call: plan a project then execute all phases."""
        project = self.plan_project(goal, template, context)
        return self.execute_project(project.id, auto_git=auto_git)

    # ── Template Detection ───────────────────────────────────

    def _detect_template(self, goal: str) -> str:
        """Auto-detect which project template fits the goal."""
        goal_lower = goal.lower()
        scores: dict[str, int] = {}

        for template, signals in TEMPLATE_SIGNALS.items():
            score = sum(1 for s in signals if s in goal_lower)
            if score > 0:
                scores[template] = score

        if scores:
            return max(scores, key=scores.get)

        # Fallback heuristic
        if any(w in goal_lower for w in ["build", "create", "make", "web", "app", "site"]):
            return "build_and_launch"
        if any(w in goal_lower for w in ["lead", "prospect", "find"]):
            return "lead_gen_pipeline"
        if any(w in goal_lower for w in ["campaign", "content", "marketing"]):
            return "content_campaign"

        return "build_and_launch"

    # ── Status & Reporting ───────────────────────────────────

    def get_project(self, project_id: str) -> dict | None:
        project = self._projects.get(project_id)
        if not project:
            return None

        return {
            "id": project.id,
            "name": project.name,
            "goal": project.goal,
            "status": project.status,
            "current_phase": project.current_phase,
            "total_phases": len(project.phases),
            "phases": [
                {
                    "order": p.order,
                    "studio": p.studio,
                    "task": p.task[:100],
                    "status": p.status,
                    "duration_ms": p.duration_ms,
                    "files_created": p.result.get("files_created", []),
                }
                for p in project.phases
            ],
            "created_at": project.created_at,
            "completed_at": project.completed_at,
            "total_duration_ms": project.total_duration_ms,
        }

    def list_projects(self) -> list[dict]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "phases": len(p.phases),
                "completed": sum(1 for ph in p.phases if ph.status == "completed"),
                "created_at": p.created_at,
            }
            for p in self._projects.values()
        ]

    def list_templates(self) -> list[dict]:
        return [
            {
                "name": name,
                "phases": len(phases),
                "studios": [p["studio"] for p in phases],
            }
            for name, phases in PROJECT_TEMPLATES.items()
        ]


_pm: ProjectManager | None = None


def get_project_manager() -> ProjectManager:
    global _pm
    if _pm is None:
        _pm = ProjectManager()
    return _pm
