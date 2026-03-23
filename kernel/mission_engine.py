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
from pathlib import Path
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

    def execute_mission(self, mission_id: int, _retry: int = 0) -> dict[str, Any]:
        """Execute a mission through its full lifecycle (with auto-retry)."""
        MAX_RETRIES = 2

        mission = self.state.get_mission(mission_id)
        if not mission:
            return {"success": False, "error": f"Mission #{mission_id} not found"}

        if mission_id in self._running_missions:
            return {"success": False, "error": f"Mission #{mission_id} already running"}

        self._running_missions.add(mission_id)
        studio = mission["studio"]
        name = mission["name"]
        description = mission.get("description", "")

        logger.info(
            "Executing mission #%d: %s → %s (attempt %d/%d)",
            mission_id, name, studio, _retry + 1, MAX_RETRIES + 1,
        )
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
            logger.error("Mission #%d failed (attempt %d): %s", mission_id, _retry + 1, e)

            # ── Auto-retry with exponential backoff ──
            self._running_missions.discard(mission_id)
            if _retry < MAX_RETRIES:
                delay = 2 ** (_retry + 1)  # 2s, 4s
                logger.info(
                    "Retrying mission #%d in %ds (attempt %d/%d)",
                    mission_id, delay, _retry + 2, MAX_RETRIES + 1,
                )
                time.sleep(delay)
                self.state.update_mission_status(
                    mission_id, MissionStatus.QUEUED, f"Retry {_retry + 2}"
                )
                return self.execute_mission(mission_id, _retry=_retry + 1)

            self.state.update_mission_status(
                mission_id, MissionStatus.FAILED, error_msg[:2000]
            )
            result = {
                "success": False,
                "mission_id": mission_id,
                "error": str(e),
                "retries": _retry,
            }

        finally:
            self._running_missions.discard(mission_id)

        # ── Report to PM (OpenClaw) silently — PM decides notifications ──
        self._save_output(mission_id, name, studio, result)
        self._callback_openclaw(mission_id, name, studio, result)

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

    def _save_output(
        self, mission_id: int, name: str, studio: str, result: dict
    ) -> None:
        """Save mission output to data/outputs/ for user access."""
        try:
            output_dir = get_config().root / "data" / "outputs"
            output_dir.mkdir(parents=True, exist_ok=True)

            output_file = output_dir / f"mission_{mission_id}.json"
            output_data = {
                "mission_id": mission_id,
                "name": name,
                "studio": studio,
                "success": result.get("success", False),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": result,
            }
            output_file.write_text(
                json.dumps(output_data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Output saved: %s", output_file)
        except Exception as e:
            logger.error("Failed to save output for mission #%d: %s", mission_id, e)

    def _notify_completion(
        self, mission_id: int, name: str, studio: str, result: dict
    ) -> None:
        """Send notification on mission completion — consolidated for objectives."""
        try:
            # Check if this mission is part of an objective batch
            mission = self.state.get_mission(mission_id)
            meta = {}
            if mission and mission.get("metadata"):
                try:
                    meta = json.loads(mission["metadata"]) if isinstance(mission["metadata"], str) else mission["metadata"]
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            objective_id = meta.get("objective_id")

            if objective_id:
                # Part of a batch — check if ALL missions in this objective are done
                all_missions = self.state._conn.execute(
                    """SELECT id, name, status, studio, result, metadata
                       FROM missions WHERE metadata LIKE ?""",
                    (f'%"objective_id": "{objective_id}"%',),
                ).fetchall()

                total = len(all_missions)
                done = sum(1 for m in all_missions if m["status"] in ("done", "failed"))

                if done < total:
                    # Not all done yet — stay silent, just log
                    logger.info(
                        "Mission #%d done (%d/%d for objective %s) — waiting for batch",
                        mission_id, done, total, objective_id[:8],
                    )
                    return

                # ALL done — send ONE consolidated notification
                self._notify_objective_complete(objective_id, meta, all_missions)
            else:
                # Standalone mission — notify immediately (compact)
                self._notify_single_mission(mission_id, name, studio, result)

        except Exception as e:
            logger.error("Notification for mission #%d failed: %s", mission_id, e)

    def _notify_single_mission(
        self, mission_id: int, name: str, studio: str, result: dict
    ) -> None:
        """Compact notification for a single standalone mission."""
        from kernel.notifier import get_notifier, NotificationPriority
        notifier = get_notifier()
        _es = self.cfg.language == "es"
        success = result.get("success", False)

        if success:
            notifier.notify(
                title=f"✅ #{mission_id} | {studio.upper()}",
                message=f"{name[:60]}\n⏱ {result.get('duration_ms', 0):.0f}ms",
                priority=NotificationPriority.NORMAL,
                source="mission_engine", category="task",
                data={"mission_id": mission_id, "studio": studio},
            )
        else:
            notifier.notify(
                title=f"❌ #{mission_id} | {studio.upper()}",
                message=f"{name[:60]}\n{result.get('error', '?')[:100]}",
                priority=NotificationPriority.HIGH,
                source="mission_engine", category="error",
                data={"mission_id": mission_id, "studio": studio},
            )

    def _notify_objective_complete(
        self, objective_id: str, meta: dict, all_missions: list
    ) -> None:
        """Send ONE consolidated notification for a completed objective."""
        from kernel.notifier import get_notifier, NotificationPriority
        notifier = get_notifier()
        _es = self.cfg.language == "es"

        objective = meta.get("objective", "?")[:80]
        total = len(all_missions)
        succeeded = sum(1 for m in all_missions if m["status"] == "done")
        failed = total - succeeded
        studios = list(set(m["studio"] for m in all_missions))

        # Build per-studio summary
        lines = []
        for m in all_missions:
            status_icon = "✅" if m["status"] == "done" else "❌"
            short_name = m["name"].replace(f"[{m['studio'].upper()}] ", "")[:40]
            lines.append(f"  {status_icon} [{m['studio'].upper()}] {short_name}")

        summary = "\n".join(lines)

        if failed == 0:
            title = f"✅ {'Objetivo completado' if _es else 'Objective complete'}"
        else:
            title = f"⚠️ {'Objetivo parcial' if _es else 'Partial objective'}"

        message = (
            f"**{objective}**\n"
            f"📊 {succeeded}/{total} {'misiones' if _es else 'missions'} | "
            f"{len(studios)} studios\n\n"
            f"{summary}"
        )

        notifier.notify(
            title=title,
            message=message,
            priority=NotificationPriority.NORMAL,
            source="mission_engine", category="objective",
            data={"objective_id": objective_id, "total": total, "succeeded": succeeded},
        )

        logger.info(
            "Objective %s complete: %d/%d succeeded across %s",
            objective_id[:8], succeeded, total, studios,
        )

    def _callback_openclaw(
        self, mission_id: int, name: str, studio: str, result: dict
    ) -> None:
        """Report mission result back to OpenClaw for autonomous feedback."""
        try:
            from kernel.openclaw_bridge import get_openclaw
            oc = get_openclaw()

            # Collect artifact paths from step results
            artifacts = []
            for step_data in result.get("steps", {}).values():
                artifacts.extend(step_data.get("artifacts", []))

            # Build output summary from step contents (compact)
            output_parts = []
            for step_id, step_data in result.get("steps", {}).items():
                content = step_data.get("content", "")
                if content:
                    # Strip JSON noise, keep meaningful text
                    clean = content.replace('\n', ' ').strip()[:200]
                    output_parts.append(f"[{step_id}] {clean}")
            output_summary = " | ".join(output_parts)[:300]

            oc.report_mission_result(
                mission_id=mission_id,
                name=name,
                status=result.get("status", "unknown"),
                studio=studio,
                output_summary=output_summary,
                artifacts=artifacts,
                duration_ms=result.get("duration_ms", 0),
                error=result.get("error", ""),
            )
        except Exception as e:
            logger.warning("OpenClaw callback failed for #%d: %s", mission_id, e)

    def _report_progress(self, mission_id: int, message: str) -> None:
        """Log real-time progress update (silent from user perspective)."""
        try:
            logger.debug("Mission #%d progress: %s", mission_id, message)
            # We purposely do NOT call OpenClaw/Telegram here anymore.
            # The PM tracks completion silently.
        except Exception as e:
            logger.debug("Progress report failed for #%d: %s", mission_id, e)

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

    DAG_TIMEOUT_SECONDS = 1800  # 30 minutes max for entire DAG

    def _execute_dag(
        self,
        mission_id: int,
        steps: list[MissionStep],
    ) -> dict[str, dict]:
        """
        Execute mission steps as a DAG.
        Steps with no unmet dependencies run in order.
        Includes global timeout and OpenClaw progress reporting.
        """
        step_map = {s.id: s for s in steps}
        results: dict[str, dict] = {}
        completed = set()
        dag_start = time.monotonic()

        max_iterations = len(steps) * 2  # Safety limit
        iteration = 0

        while len(completed) < len(steps) and iteration < max_iterations:
            # Global timeout check
            if (time.monotonic() - dag_start) > self.DAG_TIMEOUT_SECONDS:
                logger.error(
                    "Mission #%d DAG timed out after %ds",
                    mission_id, self.DAG_TIMEOUT_SECONDS,
                )
                remaining = [s.id for s in steps if s.id not in completed]
                for sid in remaining:
                    results[sid] = {
                        "status": "failed",
                        "error": f"DAG timeout after {self.DAG_TIMEOUT_SECONDS}s",
                    }
                # Notify via OpenClaw
                self._report_progress(
                    mission_id,
                    f"⏰ Mission #{mission_id} timed out. {len(completed)}/{len(steps)} steps completed.",
                )
                break
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
                    studio=self.state.get_mission(mission_id).get("studio", "dev"),
                )

                step.status = "completed" if step_result.get("success") else "failed"
                step.result = step_result

                # Extract file artifacts from agent response
                content = step_result.get("content", "")
                artifacts = self._extract_file_artifacts(
                    mission_id, step.id, content
                )

                results[step.id] = {
                    "status": step.status,
                    "agent": step.agent,
                    "content": content[:1000],
                    "model": step_result.get("model", ""),
                    "duration_ms": step_result.get("duration_ms", 0),
                    "tools_used": len(step_result.get("tool_results", [])),
                    "error": step_result.get("error", ""),
                    "artifacts": artifacts,
                }

                completed.add(step.id)
                progress = True

                # Report step progress via OpenClaw
                status_icon = "✅" if step.status == "completed" else "❌"
                self._report_progress(
                    mission_id,
                    f"{status_icon} Step '{step.name}' {step.status} "
                    f"({len(completed)}/{len(steps)} steps done)",
                )

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

    def _extract_file_artifacts(
        self, mission_id: int, step_id: str, content: str
    ) -> list[str]:
        """Extract code blocks from agent response and save as files.

        Supports patterns like:
          ```html filename="index.html"
          ```python # filename: app.py
          <!-- filename: style.css -->
        """
        import re

        if not content:
            return []

        artifacts: list[str] = []
        output_dir = get_config().root / "data" / "outputs" / f"mission_{mission_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Pattern: ```lang filename="name" or ```lang # name
        code_block_pattern = re.compile(
            r'```(\w+)(?:\s+(?:filename[=:]"?([^"\n]+)"?|#\s*(\S+)))?\s*\n'
            r'(.*?)'
            r'\n```',
            re.DOTALL,
        )

        # Language → extension map
        ext_map = {
            "html": ".html", "css": ".css", "javascript": ".js", "js": ".js",
            "typescript": ".ts", "ts": ".ts", "python": ".py", "py": ".py",
            "json": ".json", "yaml": ".yaml", "yml": ".yaml",
            "markdown": ".md", "md": ".md", "sql": ".sql",
            "shell": ".sh", "bash": ".sh", "tsx": ".tsx", "jsx": ".jsx",
            "go": ".go", "rust": ".rs", "java": ".java",
        }

        block_idx = 0
        for match in code_block_pattern.finditer(content):
            lang = match.group(1).lower()
            filename = match.group(2) or match.group(3)
            code = match.group(4)

            if not code.strip():
                continue

            if not filename:
                ext = ext_map.get(lang, f".{lang}")
                filename = f"{step_id}_{block_idx}{ext}"

            # Sanitize filename
            filename = Path(filename).name  # Remove path components
            filepath = output_dir / filename

            try:
                filepath.write_text(code, encoding="utf-8")
                artifacts.append(str(filepath))
                logger.info("Artifact saved: %s", filepath)
                block_idx += 1
            except Exception as e:
                logger.error("Failed to save artifact %s: %s", filename, e)

        # Also check for <!-- filename: X --> patterns before code blocks
        inline_pattern = re.compile(
            r'<!--\s*filename:\s*(\S+)\s*-->\s*\n```\w*\n(.*?)\n```',
            re.DOTALL,
        )
        for match in inline_pattern.finditer(content):
            filename = Path(match.group(1)).name
            code = match.group(2)
            if not code.strip():
                continue
            filepath = output_dir / filename
            if not filepath.exists():  # Don't overwrite
                try:
                    filepath.write_text(code, encoding="utf-8")
                    artifacts.append(str(filepath))
                    block_idx += 1
                except Exception:
                    pass

        if artifacts:
            logger.info(
                "Mission #%d step '%s': %d file artifacts saved",
                mission_id, step_id, len(artifacts),
            )

        return artifacts

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

        # ── Progress Notification (Silent Log Only) ──────────────
        mission_list = "\n".join(
            f"  • {m['studio'].upper()}: {m['name']}" for m in promoted
        )
        logger.info("🚀 Studios Working:\n%s", mission_list)

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

        # ── Consolidated Report: check if entire objective is done ──
        self._check_objective_completion(promoted)

        return {
            "action": "parallel",
            "studios": len(promoted),
            "succeeded": succeeded,
            "results": cycle_results,
        }

    def _check_objective_completion(self, just_executed: list[dict]) -> None:
        """Check if all missions from an objective are done → generate final report."""
        # Group by objective
        objectives_seen: set[str] = set()
        for m in just_executed:
            try:
                meta = json.loads(m.get("metadata", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            obj = meta.get("objective", "")
            if obj:
                objectives_seen.add(obj)

        if not objectives_seen:
            return

        for objective in objectives_seen:
            # Query ALL missions for this objective
            with self.state._lock:
                rows = self.state._conn.execute(
                    "SELECT id, name, studio, status, result, metadata FROM missions "
                    "WHERE metadata LIKE ?",
                    (f'%{objective[:50]}%',),
                ).fetchall()

            if not rows:
                continue

            # Check if all are done (done or failed, not queued/running)
            terminal = {"done", "failed"}
            all_done = all(r["status"] in terminal for r in rows)
            if not all_done:
                continue

            # All missions for this objective are complete → generate report
            self._generate_consolidated_report(objective, rows)

    def _generate_consolidated_report(
        self, objective: str, missions: list
    ) -> None:
        """Generate ONE final report for a completed objective."""
        try:
            output_dir = get_config().root / "data" / "outputs"
            output_dir.mkdir(parents=True, exist_ok=True)

            total = len(missions)
            succeeded = sum(1 for m in missions if m["status"] == "done")
            failed = total - succeeded

            # Build markdown report
            _es = self.cfg.language == "es"
            lines = [
                f"# 📋 {'Objetivo Completado' if _es else 'Objective Complete'}: {objective}",
                f"",
                f"**{'Resultado' if _es else 'Result'}:** {succeeded}/{total} {'misiones exitosas' if _es else 'missions succeeded'}"
                + (f" | {failed} {'fallaron' if _es else 'failed'}" if failed else ""),
                f"",
                f"---",
                f"",
            ]

            for m in missions:
                status_icon = "✅" if m["status"] == "done" else "❌"
                lines.append(f"## {status_icon} [{m['studio'].upper()}] {m['name']}")
                lines.append(f"")
                result_text = m.get("result", "")
                if result_text:
                    # Extract content from result JSON
                    try:
                        result_data = json.loads(result_text)
                        if isinstance(result_data, dict):
                            for step_name, step_info in result_data.items():
                                content = step_info.get("content", "")
                                if content:
                                    lines.append(content[:1500])
                                    lines.append("")
                        else:
                            lines.append(str(result_text)[:1500])
                    except (json.JSONDecodeError, TypeError):
                        lines.append(str(result_text)[:1500])
                lines.append("")
                lines.append("---")
                lines.append("")

            # Save report
            import hashlib
            obj_hash = hashlib.md5(objective.encode()).hexdigest()[:8]
            report_file = output_dir / f"objective_{obj_hash}.md"
            report_file.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Consolidated report: %s", report_file)

            # Also save as JSON
            json_report = {
                "objective": objective,
                "total_missions": total,
                "succeeded": succeeded,
                "failed": failed,
                "missions": [
                    {
                        "id": m["id"],
                        "name": m["name"],
                        "studio": m["studio"],
                        "status": m["status"],
                    }
                    for m in missions
                ],
                "report_file": str(report_file),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            json_file = output_dir / f"objective_{obj_hash}.json"
            json_file.write_text(
                json.dumps(json_report, indent=2, default=str),
                encoding="utf-8",
            )

            # Send ONE consolidated Telegram notification
            try:
                from kernel.notifier import Notifier, NotificationPriority
                notifier = Notifier()
                studios_list = ", ".join(
                    m["studio"].upper() for m in missions
                )
                _es = self.cfg.language == "es"
                notifier.notify(
                    title="📋 ¡Objetivo Completado!" if _es else "📋 Objective Complete!",
                    message=(
                        f"**{objective[:100]}**\n\n"
                        f"✅ {succeeded}/{total} {'misiones exitosas' if _es else 'missions succeeded'}\n"
                        f"{'Estudios' if _es else 'Studios'}: {studios_list}\n"
                        f"{'Reporte' if _es else 'Report'}: `{report_file.name}`"
                    ),
                    priority=NotificationPriority.NORMAL,
                    source="mission_engine",
                    category="task",
                    data={
                        "objective": objective[:200],
                        "report": str(report_file),
                    },
                )
            except Exception as e:
                logger.error("Failed consolidated notification: %s", e)

            # Report objective completion to OpenClaw
            try:
                from kernel.openclaw_bridge import get_openclaw
                oc = get_openclaw()
                studios_used = list(set(m["studio"] for m in missions))
                oc.report_objective_complete(
                    objective=objective,
                    total=total,
                    succeeded=succeeded,
                    report_file=str(report_file),
                    studios=studios_used,
                )
            except Exception as e:
                logger.debug("OpenClaw objective callback failed: %s", e)

        except Exception as e:
            logger.error("Failed to generate consolidated report: %s", e)

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
                raw = row["metadata"]
                meta = json.loads(raw) if raw else {}
                if isinstance(meta, str):
                    meta = json.loads(meta)
            except Exception:
                meta = {}
            if not isinstance(meta, dict):
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
