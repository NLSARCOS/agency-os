#!/usr/bin/env python3
"""
Agency OS v3.0 — Mission Engine

DAG-based mission execution with crew assembly, agent delegation,
tool execution, and checkpoint/resume. Full lifecycle:
QUEUED → ACTIVE → RUNNING → REVIEW → DONE/FAILED

Inspired by LangGraph state machines + CrewAI crew patterns.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from kernel.config import get_config
from kernel.state_manager import MissionStatus, TaskStatus, get_state
from kernel.task_router import TaskRouter
from kernel.event_bus import Event, get_event_bus
from kernel.agent_manager import AgentManager, get_agent_manager
from kernel.tool_executor import get_tool_executor

logger = logging.getLogger("agency.mission")


@dataclass
class MissionStep:
    """A single step in a mission's execution DAG."""
    id: str
    name: str
    agent: str
    task: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed, skipped
    result: dict[str, Any] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    condition: str = ""  # Condition for conditional branching


class MissionEngine:
    """
    Core mission execution engine with:
    - DAG-based step execution (parallel + sequential)
    - Crew assembly per mission type
    - Agent delegation chains
    - Tool execution integration
    - Checkpoint/resume after failures
    - Event-driven progress tracking
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self.router = TaskRouter()
        self._studios: dict[str, Any] = {}
        self._agent_manager: AgentManager | None = None
        self._running_missions: set[int] = set()

    def _get_agent_manager(self) -> AgentManager:
        if self._agent_manager is None:
            self._agent_manager = get_agent_manager()
        return self._agent_manager

    def register_studio(self, name: str, studio_instance: Any) -> None:
        self._studios[name] = studio_instance
        logger.info("Registered studio: %s", name)

    def auto_discover_studios(self) -> None:
        from studios.base_studio import load_all_studios
        for name, studio in load_all_studios().items():
            self.register_studio(name, studio)

    # ── Mission Lifecycle ─────────────────────────────────────

    def submit_mission(
        self,
        name: str,
        description: str = "",
        priority: int = 5,
        force_studio: str = "",
        metadata: dict | None = None,
    ) -> int:
        """Submit a new mission — routes, creates crew, and queues."""
        # Route to studio
        if force_studio:
            studio = force_studio
            confidence = 1.0
        else:
            route_result = self.router.route(name)
            studio = route_result.studio
            confidence = route_result.confidence

        # Create mission in DB
        meta = metadata or {}
        meta["routing_confidence"] = confidence
        mission_id = self.state.create_mission(
            name=name, description=description,
            studio=studio, priority=priority,
            metadata=meta,
        )

        # Assemble crew
        mgr = self._get_agent_manager()
        crew = mgr.assemble_crew(studio)
        meta["crew"] = crew

        logger.info(
            "Mission #%d submitted → %s (confidence: %.0f%%) crew: %s",
            mission_id, studio, confidence * 100, crew,
        )

        # Emit event
        bus = get_event_bus()
        bus.publish_sync(Event(
            type="mission.submitted",
            payload={
                "mission_id": mission_id, "name": name,
                "studio": studio, "crew": crew,
                "confidence": confidence,
            },
        ))

        self.state.log_event(
            "mission_submitted",
            f"Mission #{mission_id} submitted: {name} → {studio} "
            f"(confidence: {confidence:.0%}, crew: {crew})",
            source="mission_engine",
        )

        return mission_id

    def execute_mission(self, mission_id: int) -> dict[str, Any]:
        """Execute a mission through its full lifecycle."""
        mission = self.state.get_mission(mission_id)
        if not mission:
            return {"success": False, "error": f"Mission #{mission_id} not found"}

        if mission_id in self._running_missions:
            return {"success": False, "error": f"Mission #{mission_id} already running"}

        self._running_missions.add(mission_id)
        studio = mission["studio"]
        name = mission["name"]
        description = mission.get("description", "")

        logger.info("Executing mission #%d: %s → %s", mission_id, name, studio)

        # Transition: QUEUED → ACTIVE → RUNNING
        self.state.update_mission_status(mission_id, MissionStatus.ACTIVE)
        self.state.update_mission_status(mission_id, MissionStatus.RUNNING)

        bus = get_event_bus()
        bus.publish_sync(Event(
            type="mission.started",
            payload={"mission_id": mission_id, "studio": studio},
        ))

        start = time.monotonic()
        result: dict[str, Any] = {}

        try:
            # Build execution plan
            steps = self._plan_mission(mission_id, name, description, studio)

            # Execute DAG
            step_results = self._execute_dag(mission_id, steps)

            # Collect results
            success = all(
                s["status"] == "completed" for s in step_results.values()
            )
            result_text = json.dumps(step_results, indent=2, default=str)

            # Transition: RUNNING → REVIEW → DONE/FAILED
            self.state.update_mission_status(
                mission_id, MissionStatus.REVIEW, result_text[:1000]
            )

            final_status = MissionStatus.DONE if success else MissionStatus.FAILED
            self.state.update_mission_status(
                mission_id, final_status, result_text[:2000]
            )

            duration = (time.monotonic() - start) * 1000

            result = {
                "success": success,
                "mission_id": mission_id,
                "studio": studio,
                "duration_ms": round(duration, 1),
                "steps": step_results,
                "status": final_status.value,
            }

            bus.publish_sync(Event(
                type="mission.completed" if success else "mission.failed",
                payload={
                    "mission_id": mission_id,
                    "status": final_status.value,
                    "duration_ms": duration,
                },
            ))

        except Exception as e:
            error_msg = f"{e}\n{traceback.format_exc()}"
            logger.error("Mission #%d failed: %s", mission_id, e)
            self.state.update_mission_status(
                mission_id, MissionStatus.FAILED, error_msg[:2000]
            )
            result = {
                "success": False,
                "mission_id": mission_id,
                "error": str(e),
            }

        finally:
            self._running_missions.discard(mission_id)

        # Log KPIs
        self.state.log_kpi(
            studio, "mission_duration_ms",
            result.get("duration_ms", 0), "ms",
        )
        self.state.log_event(
            "mission_completed" if result.get("success") else "mission_failed",
            f"Mission #{mission_id}: {result.get('status', 'error')}",
            source="mission_engine",
        )

        return result

    # ── DAG Planning ──────────────────────────────────────────

    def _plan_mission(
        self,
        mission_id: int,
        name: str,
        description: str,
        studio: str,
    ) -> list[MissionStep]:
        """Build execution steps for a mission."""

        # Get crew
        mgr = self._get_agent_manager()
        crew = mgr.assemble_crew(studio)
        lead_agent = crew[0] if crew else "backend-specialist"

        # Default workflow: intake → plan → execute → review
        steps = [
            MissionStep(
                id="intake",
                name="Intake & Analysis",
                agent=lead_agent,
                task=f"Analyze this mission and define its scope:\n"
                     f"Mission: {name}\nDescription: {description}\n"
                     f"Studio: {studio}\n"
                     f"Provide a clear intake analysis with objectives.",
            ),
            MissionStep(
                id="plan",
                name="Plan & Strategy",
                agent=lead_agent,
                task=f"Based on the intake analysis, create a detailed "
                     f"execution plan for: {name}",
                depends_on=["intake"],
            ),
            MissionStep(
                id="execute",
                name="Execute",
                agent=lead_agent,
                task=f"Execute the plan for: {name}\n"
                     f"Use available tools to produce real deliverables.",
                depends_on=["plan"],
                tools=["shell", "read_file", "write_file", "http_request",
                        "search_web", "scrape_url"],
            ),
        ]

        # Add specialist steps if crew has multiple agents
        if len(crew) > 1:
            for specialist in crew[1:]:
                steps.append(MissionStep(
                    id=f"specialist_{specialist}",
                    name=f"Specialist: {specialist}",
                    agent=specialist,
                    task=f"Contribute your specialized expertise to: {name}\n"
                         f"Review the lead agent's work and enhance it.",
                    depends_on=["execute"],
                ))

        # Review step
        review_deps = ["execute"]
        if len(crew) > 1:
            review_deps.extend(f"specialist_{s}" for s in crew[1:])

        steps.append(MissionStep(
            id="review",
            name="Review & Quality Check",
            agent=lead_agent,
            task=f"Review all deliverables for: {name}\n"
                 f"Verify quality, completeness, and accuracy.",
            depends_on=review_deps,
        ))

        return steps

    # ── DAG Execution ─────────────────────────────────────────

    def _execute_dag(
        self,
        mission_id: int,
        steps: list[MissionStep],
    ) -> dict[str, dict]:
        """
        Execute mission steps as a DAG.
        Steps with no unmet dependencies run in order.
        """
        step_map = {s.id: s for s in steps}
        results: dict[str, dict] = {}
        completed = set()

        max_iterations = len(steps) * 2  # Safety limit
        iteration = 0

        while len(completed) < len(steps) and iteration < max_iterations:
            iteration += 1
            progress = False

            for step in steps:
                if step.id in completed:
                    continue

                # Check dependencies
                deps_met = all(d in completed for d in step.depends_on)
                if not deps_met:
                    continue

                # Check if any dependency failed
                deps_failed = any(
                    results.get(d, {}).get("status") == "failed"
                    for d in step.depends_on
                )
                if deps_failed:
                    step.status = "skipped"
                    results[step.id] = {
                        "status": "skipped",
                        "reason": "dependency_failed",
                    }
                    completed.add(step.id)
                    progress = True
                    continue

                # Execute step
                logger.info(
                    "Mission #%d step '%s' → agent: %s",
                    mission_id, step.name, step.agent,
                )

                # Build context from previous step results
                context_parts = []
                for dep_id in step.depends_on:
                    dep_result = results.get(dep_id, {})
                    content = dep_result.get("content", "")
                    if content:
                        context_parts.append(
                            f"[{dep_id}] {content[:500]}"
                        )
                context = "\n\n".join(context_parts)

                # Execute via agent manager
                mgr = self._get_agent_manager()
                step_result = mgr.execute_task(
                    agent_id=step.agent,
                    task=step.task,
                    context=context,
                    tools_enabled=bool(step.tools),
                )

                step.status = "completed" if step_result.get("success") else "failed"
                step.result = step_result

                results[step.id] = {
                    "status": step.status,
                    "agent": step.agent,
                    "content": step_result.get("content", "")[:1000],
                    "model": step_result.get("model", ""),
                    "duration_ms": step_result.get("duration_ms", 0),
                    "tools_used": len(step_result.get("tool_results", [])),
                    "error": step_result.get("error", ""),
                }

                completed.add(step.id)
                progress = True

                # Create task record
                task_id = self.state.create_task(
                    name=f"[{step.id}] {step.name}",
                    studio=self.state.get_mission(mission_id).get("studio", ""),
                    mission_id=mission_id,
                    input_data=step.task[:500],
                )
                self.state.complete_task(
                    task_id,
                    output_data=step_result.get("content", "")[:1000],
                    model_used=step_result.get("model", ""),
                    duration=step_result.get("duration_ms", 0) / 1000,
                    error=step_result.get("error", ""),
                )

            if not progress:
                # Deadlock detected
                remaining = [s.id for s in steps if s.id not in completed]
                logger.error(
                    "Mission #%d DAG deadlock. Remaining: %s",
                    mission_id, remaining,
                )
                for sid in remaining:
                    results[sid] = {
                        "status": "failed",
                        "error": "DAG deadlock",
                    }
                break

        return results

    # ── Cycle ─────────────────────────────────────────────────

    def run_cycle(self) -> dict[str, Any]:
        """Run one mission processing cycle (single mission)."""
        promoted = self.state.promote_next_mission()
        if not promoted:
            return {"action": "idle", "message": "No missions to process"}

        mission_id = promoted["id"]
        result = self.execute_mission(mission_id)
        return {"action": "executed", "mission_id": mission_id, **result}

    async def run_parallel_cycle(self) -> dict[str, Any]:
        """Run missions from ALL studios in parallel — one per studio simultaneously.

        After execution, injects results as context into dependent missions
        (wave handoff: DEV output → MARKETING input → SALES input).
        """
        promoted = self.state.promote_next_per_studio()
        if not promoted:
            return {"action": "idle", "studios": 0, "message": "No missions queued"}

        studios_active = [m["studio"] for m in promoted]
        logger.info(
            "🚀 Parallel cycle: %d studios active — %s",
            len(promoted), ", ".join(studios_active),
        )

        # Execute all missions concurrently (each studio uses its own model)
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, self.execute_mission, m["id"])
            for m in promoted
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        cycle_results = {}
        for mission, result in zip(promoted, results):
            studio = mission["studio"]
            if isinstance(result, Exception):
                logger.error("Studio %s failed: %s", studio, result)
                cycle_results[studio] = {
                    "success": False, "error": str(result),
                    "mission_id": mission["id"],
                }
            else:
                cycle_results[studio] = result

        # ── Wave Handoff: inject results into dependent missions ──
        completed_studios = [
            s for s, r in cycle_results.items() if r.get("success")
        ]
        if completed_studios:
            self._inject_wave_context(completed_studios, cycle_results)

        succeeded = sum(1 for r in cycle_results.values() if r.get("success"))
        logger.info(
            "Parallel cycle done: %d/%d studios succeeded",
            succeeded, len(cycle_results),
        )

        self.state.log_event(
            "parallel_cycle",
            f"Executed {len(promoted)} missions in parallel: "
            f"{', '.join(studios_active)} — {succeeded}/{len(promoted)} OK",
            source="mission_engine",
        )

        return {
            "action": "parallel",
            "studios": len(promoted),
            "succeeded": succeeded,
            "results": cycle_results,
        }

    def _inject_wave_context(
        self, completed_studios: list[str], results: dict[str, dict]
    ) -> None:
        """Inject completed studio results into queued missions that depend on them."""
        # Find queued missions with planner metadata that depend on completed studios
        with self.state._lock:
            rows = self.state._conn.execute(
                "SELECT id, description, metadata FROM missions WHERE status = 'queued'"
            ).fetchall()

        for row in rows:
            try:
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}

            depends_on = meta.get("depends_on", [])
            if not depends_on:
                continue

            # Check if any dependency was just completed
            newly_resolved = [d for d in depends_on if d in completed_studios]
            if not newly_resolved:
                continue

            # Build context from completed studios
            context_parts = []
            for studio in newly_resolved:
                r = results.get(studio, {})
                steps = r.get("steps", {})
                # Grab the execute step content (the main deliverable)
                for step_name, step_data in steps.items():
                    content = step_data.get("content", "")
                    if content:
                        context_parts.append(
                            f"[Output from {studio.upper()}] {content[:800]}"
                        )

            if context_parts:
                context_block = "\n\n--- Previous Studio Results ---\n" + "\n\n".join(context_parts)
                new_desc = row["description"] + context_block

                with self.state._lock:
                    self.state._conn.execute(
                        "UPDATE missions SET description = ? WHERE id = ?",
                        (new_desc[:5000], row["id"]),
                    )
                    self.state._conn.commit()

                logger.info(
                    "Wave handoff: injected %s context into mission #%d",
                    ", ".join(newly_resolved), row["id"],
                )

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> dict:
        stats = self.state.get_dashboard_stats()
        mgr = self._get_agent_manager()
        return {
            "missions": stats.get("missions", {}),
            "running_missions": list(self._running_missions),
            "studios_registered": list(self._studios.keys()),
            "agents": mgr.get_status() if mgr else {},
        }
