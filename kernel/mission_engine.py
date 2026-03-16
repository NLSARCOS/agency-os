#!/usr/bin/env python3
"""
Agency OS — Mission Engine

Event-driven mission lifecycle with state machine.
Handles the full lifecycle: QUEUED → ACTIVE → RUNNING → REVIEW → DONE/FAILED.
Auto-promotes missions and executes studio pipelines.
"""
from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from kernel.config import get_config
from kernel.state_manager import MissionStatus, TaskStatus, get_state
from kernel.task_router import TaskRouter

logger = logging.getLogger("agency.mission")


class MissionEngine:
    """Core mission execution engine with state machine lifecycle."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self.router = TaskRouter()
        self._studios: dict[str, Any] = {}

    def register_studio(self, name: str, studio_instance: Any) -> None:
        """Register a studio pipeline for execution."""
        self._studios[name] = studio_instance
        logger.info("Registered studio: %s", name)

    def auto_discover_studios(self) -> None:
        """Auto-discover and register available studios."""
        from studios.base_studio import load_all_studios
        for name, studio in load_all_studios().items():
            self.register_studio(name, studio)

    # ── Mission Lifecycle ─────────────────────────────────────

    def submit_mission(
        self,
        name: str,
        description: str = "",
        priority: int = 5,
        force_studio: str | None = None,
    ) -> int:
        """Submit a new mission to the queue."""
        # Route the mission to a studio
        route = self.router.route(name, {"force_studio": force_studio} if force_studio else None)

        mission_id = self.state.create_mission(
            name=name,
            description=description,
            studio=route.studio,
            priority=priority,
            metadata={
                "route_confidence": route.confidence,
                "route_scores": route.scores,
                "model_preference": route.model_preference,
            },
        )

        self.state.log_event(
            "mission_submitted",
            f"Mission #{mission_id} submitted: {name} → {route.studio} "
            f"(confidence: {route.confidence:.0%})",
            source="mission_engine",
        )
        logger.info(
            "Mission #%d submitted → %s (confidence: %.0f%%)",
            mission_id, route.studio, route.confidence * 100,
        )
        return mission_id

    def execute_mission(self, mission_id: int) -> dict[str, Any]:
        """Execute a mission through its assigned studio pipeline."""
        mission = self.state.get_mission(mission_id)
        if not mission:
            return {"error": f"Mission #{mission_id} not found"}

        studio_name = mission["studio"]
        result: dict[str, Any] = {
            "mission_id": mission_id,
            "studio": studio_name,
            "status": "unknown",
        }

        # Transition: → RUNNING
        self.state.update_mission_status(mission_id, MissionStatus.RUNNING)
        self.state.log_event(
            "mission_started",
            f"Mission #{mission_id} started in {studio_name}",
            source="mission_engine",
        )

        start_time = time.monotonic()

        try:
            # Get studio pipeline
            studio = self._studios.get(studio_name)
            if not studio:
                raise RuntimeError(
                    f"Studio '{studio_name}' not registered. "
                    f"Available: {list(self._studios.keys())}"
                )

            # Create task in state
            task_id = self.state.create_task(
                name=mission["name"],
                studio=studio_name,
                mission_id=mission_id,
                input_data=mission["description"],
            )

            # Execute the studio pipeline
            pipeline_result = studio.run(
                task=mission["name"],
                description=mission["description"],
                task_id=task_id,
                metadata=mission.get("metadata", {}),
            )

            duration = time.monotonic() - start_time

            # Complete task
            self.state.complete_task(
                task_id=task_id,
                output_data=str(pipeline_result.get("output", "")),
                model_used=str(pipeline_result.get("model_used", "")),
                duration=duration,
            )

            # Log KPIs from pipeline
            for kpi in pipeline_result.get("kpis", []):
                self.state.log_kpi(
                    studio=studio_name,
                    metric_name=kpi["name"],
                    metric_value=kpi["value"],
                    unit=kpi.get("unit", ""),
                )

            # Transition: → DONE
            self.state.update_mission_status(
                mission_id, MissionStatus.DONE,
                result=str(pipeline_result.get("output", "completed")),
            )

            result.update({
                "status": "done",
                "duration_seconds": round(duration, 2),
                "output": pipeline_result.get("output", ""),
                "kpis": pipeline_result.get("kpis", []),
            })

            self.state.log_event(
                "mission_completed",
                f"Mission #{mission_id} completed in {duration:.1f}s",
                source="mission_engine",
            )
            logger.info("Mission #%d completed in %.1fs", mission_id, duration)

        except Exception as e:
            duration = time.monotonic() - start_time
            error_msg = f"{e.__class__.__name__}: {e}"
            tb = traceback.format_exc()

            # Transition: → FAILED
            self.state.update_mission_status(
                mission_id, MissionStatus.FAILED, result=error_msg
            )

            result.update({
                "status": "failed",
                "error": error_msg,
                "traceback": tb,
                "duration_seconds": round(duration, 2),
            })

            self.state.log_event(
                "mission_failed",
                f"Mission #{mission_id} failed: {error_msg}",
                source="mission_engine",
                level="error",
            )
            logger.error(
                "Mission #%d failed after %.1fs: %s",
                mission_id, duration, error_msg,
            )

        return result

    # ── Cycle Operations ──────────────────────────────────────

    def run_cycle(self, max_missions: int = 5) -> list[dict]:
        """Execute one full cycle: promote queued → active, run active missions."""
        results = []

        # Promote queued missions
        promoted = 0
        while promoted < max_missions:
            mission = self.state.promote_next_mission()
            if not mission:
                break
            promoted += 1
            logger.info("Promoted mission #%d: %s", mission["id"], mission["name"])

        # Execute active missions
        active = self.state.get_missions(status=MissionStatus.ACTIVE, limit=max_missions)
        for mission in active:
            result = self.execute_mission(mission["id"])
            results.append(result)

        # Auto-promote next batch
        if results:
            self.state.promote_next_mission()

        self.state.log_event(
            "cycle_completed",
            f"Cycle completed: promoted={promoted}, executed={len(results)}, "
            f"done={sum(1 for r in results if r.get('status') == 'done')}, "
            f"failed={sum(1 for r in results if r.get('status') == 'failed')}",
            source="mission_engine",
        )

        return results

    def get_status(self) -> dict:
        """Get current mission engine status."""
        return {
            "missions": {
                "queued": len(self.state.get_missions(MissionStatus.QUEUED)),
                "active": len(self.state.get_missions(MissionStatus.ACTIVE)),
                "running": len(self.state.get_missions(MissionStatus.RUNNING)),
                "done": len(self.state.get_missions(MissionStatus.DONE)),
                "failed": len(self.state.get_missions(MissionStatus.FAILED)),
            },
            "studios_registered": list(self._studios.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def get_engine() -> MissionEngine:
    """Get or create the mission engine singleton."""
    engine = MissionEngine()
    try:
        engine.auto_discover_studios()
    except Exception:
        logger.debug("Auto-discovery skipped (studios not yet initialized)")
    return engine
