#!/usr/bin/env python3
"""
Agency OS v3.0 — Autonomy Engine

Proactive self-operating system that:
- Discovers pending work from pipelines, KPIs, and events
- Self-heals failed operations with intelligent retry
- Learns from success/failure patterns
- Prioritizes work by KPI impact
- Runs scheduled operations (cron-like)

This is the brain that makes Agency OS truly autonomous.
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus
from kernel.memory_manager import get_memory_manager
from kernel.state_manager import get_state

logger = logging.getLogger("agency.autonomy")


@dataclass
class AutoTask:
    """An auto-discovered task."""
    id: str = ""
    source: str = ""  # discovery, self_heal, schedule, kpi
    studio: str = ""
    task: str = ""
    priority: float = 5.0  # 1-10, higher = more urgent
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class LearningEntry:
    """A learning from past execution."""
    pattern: str = ""
    outcome: str = ""  # success, failure
    studio: str = ""
    operation: str = ""
    confidence: float = 0.5
    count: int = 1


class AutonomyEngine:
    """
    The autonomous operations brain of Agency OS.

    Capabilities:
    1. DISCOVER — Find work that needs doing
    2. HEAL — Retry/fix failed operations
    3. LEARN — Store success/failure patterns
    4. PRIORITIZE — Rank tasks by KPI impact
    5. SCHEDULE — Run periodic operations
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self.memory = get_memory_manager()
        self.bus = get_event_bus()
        self._learnings: dict[str, LearningEntry] = {}
        self._init_db()
        self._load_learnings_from_db()

    def _init_db(self) -> None:
        """Create learnings table if not exists."""
        try:
            self.state._conn.execute("""
                CREATE TABLE IF NOT EXISTS autonomy_learnings (
                    key TEXT PRIMARY KEY,
                    pattern TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    studio TEXT DEFAULT '',
                    operation TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.5,
                    count INTEGER DEFAULT 1,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.state._conn.commit()
        except Exception as e:
            logger.debug("Learnings table init: %s", e)

    def _load_learnings_from_db(self) -> None:
        """Load persisted learnings from SQLite on startup."""
        try:
            rows = self.state._conn.execute(
                "SELECT key, pattern, outcome, studio, operation, confidence, count "
                "FROM autonomy_learnings"
            ).fetchall()
            for r in rows:
                self._learnings[r["key"]] = LearningEntry(
                    pattern=r["pattern"],
                    outcome=r["outcome"],
                    studio=r["studio"],
                    operation=r["operation"],
                    confidence=r["confidence"],
                    count=r["count"],
                )
            if rows:
                logger.info("Loaded %d learnings from database", len(rows))
        except Exception as e:
            logger.debug("Could not load learnings: %s", e)

    def _persist_learning(self, key: str, entry: LearningEntry) -> None:
        """Persist a learning entry to SQLite."""
        try:
            self.state._conn.execute(
                """INSERT OR REPLACE INTO autonomy_learnings
                   (key, pattern, outcome, studio, operation, confidence, count, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (key, entry.pattern, entry.outcome, entry.studio,
                 entry.operation, entry.confidence, entry.count),
            )
            self.state._conn.commit()
        except Exception as e:
            logger.debug("Could not persist learning: %s", e)

    # ── 1. DISCOVER ───────────────────────────────────────────

    def discover_tasks(self) -> list[AutoTask]:
        """Proactively discover tasks that need attention."""
        tasks: list[AutoTask] = []

        tasks.extend(self._discover_stale_missions())
        tasks.extend(self._discover_failed_tasks())
        tasks.extend(self._discover_kpi_drops())
        tasks.extend(self._discover_idle_studios())
        tasks.extend(self._discover_from_knowledge())

        # Sort by priority (descending)
        tasks.sort(key=lambda t: t.priority, reverse=True)

        logger.info("Discovered %d auto-tasks", len(tasks))
        return tasks

    def _discover_stale_missions(self) -> list[AutoTask]:
        """Find missions that haven't progressed."""
        tasks = []
        try:
            rows = self.state._conn.execute(
                """SELECT id, name, status, updated_at FROM missions
                   WHERE status IN ('active', 'pending')
                   ORDER BY updated_at ASC LIMIT 10"""
            ).fetchall()

            for r in rows:
                updated = r["updated_at"] or ""
                if updated:
                    # Check if stale (no update in significant time)
                    tasks.append(AutoTask(
                        id=f"stale_mission_{r['id']}",
                        source="discovery",
                        studio="",
                        task=f"Resume stale mission: {r['name']}",
                        priority=7.0,
                        reason=f"Mission '{r['name']}' has been {r['status']} since {updated}",
                        metadata={"mission_id": r["id"]},
                    ))
        except Exception as e:
            logger.debug("Error discovering stale missions: %s", e)
        return tasks

    def _discover_failed_tasks(self) -> list[AutoTask]:
        """Find tasks that failed and could be retried."""
        tasks = []
        try:
            rows = self.state._conn.execute(
                """SELECT id, studio, description, status FROM tasks
                   WHERE status = 'failed'
                   ORDER BY updated_at DESC LIMIT 10"""
            ).fetchall()

            for r in rows:
                tasks.append(AutoTask(
                    id=f"retry_{r['id']}",
                    source="self_heal",
                    studio=r["studio"],
                    task=f"Retry failed task: {r['description'][:80]}",
                    priority=8.0,
                    reason=f"Task failed in {r['studio']} studio",
                    metadata={"task_id": r["id"], "original_studio": r["studio"]},
                ))
        except Exception as e:
            logger.debug("Error discovering failed tasks: %s", e)
        return tasks

    def _discover_kpi_drops(self) -> list[AutoTask]:
        """Detect KPI drops and suggest remediation."""
        tasks = []
        try:
            # Get recent KPIs and look for success rate drops
            kpis = self.state.get_kpis(limit=100)
            studios_failing: dict[str, int] = {}

            for kpi in kpis:
                if kpi.get("metric_name") == "pipeline_success" and kpi.get("metric_value", 1) < 1:
                    studio = kpi.get("studio", "")
                    studios_failing[studio] = studios_failing.get(studio, 0) + 1

            for studio, count in studios_failing.items():
                if count >= 2:
                    tasks.append(AutoTask(
                        id=f"kpi_drop_{studio}",
                        source="kpi",
                        studio=studio,
                        task=f"Investigate {studio} pipeline failures ({count} recent failures)",
                        priority=9.0,
                        reason=f"{studio} has {count} recent pipeline failures",
                        metadata={"failure_count": count},
                    ))
        except Exception as e:
            logger.debug("Error discovering KPI drops: %s", e)
        return tasks

    def _discover_idle_studios(self) -> list[AutoTask]:
        """Find studios that haven't been used recently."""
        tasks = []
        try:
            # Check which studios have no recent activity
            studios = ["dev", "marketing", "sales", "leadops", "abm", "analytics", "creative"]
            active_studios = set()

            rows = self.state._conn.execute(
                """SELECT DISTINCT studio FROM tasks
                   ORDER BY created_at DESC LIMIT 50"""
            ).fetchall()
            for r in rows:
                active_studios.add(r["studio"])

            idle = set(studios) - active_studios
            for studio in idle:
                tasks.append(AutoTask(
                    id=f"idle_{studio}",
                    source="discovery",
                    studio=studio,
                    task=f"Activate {studio} studio — suggest initial tasks",
                    priority=3.0,
                    reason=f"{studio} studio has no recent activity",
                ))
        except Exception as e:
            logger.debug("Error discovering idle studios: %s", e)
        return tasks

    def _discover_from_knowledge(self) -> list[AutoTask]:
        """Extract actionable tasks from the knowledge base."""
        tasks = []
        try:
            knowledge = self.memory.query_knowledge(
                "pending action next step improvement",
                limit=5,
            )
            for k in knowledge:
                if any(word in k.content.lower() for word in
                       ["should", "need", "todo", "improve", "fix", "upgrade"]):
                    tasks.append(AutoTask(
                        id=f"knowledge_{k.id}",
                        source="discovery",
                        studio="",
                        task=f"Follow up on knowledge: {k.topic}",
                        priority=4.0,
                        reason=f"Knowledge entry suggests action: {k.content[:100]}",
                        metadata={"knowledge_id": k.id},
                    ))
        except Exception as e:
            logger.debug("Error discovering from knowledge: %s", e)
        return tasks

    # ── 2. SELF-HEAL ──────────────────────────────────────────

    def self_heal(self, task: AutoTask) -> dict[str, Any]:
        """Attempt to heal/retry a failed operation."""
        logger.info("Self-healing: %s", task.task[:80])

        self.bus.publish_sync(Event(
            type="autonomy.heal_start",
            payload={"task_id": task.id, "studio": task.studio},
        ))

        try:
            # Load the studio and retry
            from studios.base_studio import load_all_studios
            studios = load_all_studios()

            studio = studios.get(task.studio)
            if not studio:
                return {"success": False, "error": f"Studio not found: {task.studio}"}

            result = studio.run(
                task=task.task,
                description=task.reason,
            )

            # Learn from result
            self.learn(
                pattern=f"retry:{task.studio}:{task.metadata.get('original_studio', '')}",
                outcome="success" if result.get("success") else "failure",
                studio=task.studio,
                operation="self_heal",
            )

            return result

        except Exception as e:
            self.learn(
                pattern=f"retry:{task.studio}",
                outcome="failure",
                studio=task.studio,
                operation="self_heal",
            )
            return {"success": False, "error": str(e)}

    # ── 3. LEARN ──────────────────────────────────────────────

    def learn(
        self,
        pattern: str,
        outcome: str,
        studio: str = "",
        operation: str = "",
    ) -> None:
        """Store a learning from execution."""
        key = f"{pattern}:{studio}:{operation}"

        if key in self._learnings:
            entry = self._learnings[key]
            entry.count += 1
            if outcome == "success":
                entry.confidence = min(1.0, entry.confidence + 0.1)
            else:
                entry.confidence = max(0.0, entry.confidence - 0.15)
        else:
            self._learnings[key] = LearningEntry(
                pattern=pattern,
                outcome=outcome,
                studio=studio,
                operation=operation,
                confidence=0.6 if outcome == "success" else 0.3,
            )

        # Persist to SQLite (survives restarts)
        self._persist_learning(key, self._learnings[key])

        # Persist to knowledge base
        self.memory.learn(
            topic=f"learning:{pattern}",
            content=(
                f"Pattern: {pattern}\n"
                f"Outcome: {outcome}\n"
                f"Studio: {studio}\n"
                f"Confidence: {self._learnings[key].confidence:.2f}\n"
                f"Count: {self._learnings[key].count}"
            ),
            source_agent="autonomy_engine",
            tags=["learning", studio, outcome],
        )

    def get_learnings(self) -> list[dict]:
        """Get all learnings sorted by count."""
        return sorted(
            [
                {
                    "pattern": e.pattern,
                    "outcome": e.outcome,
                    "studio": e.studio,
                    "operation": e.operation,
                    "confidence": round(e.confidence, 2),
                    "count": e.count,
                }
                for e in self._learnings.values()
            ],
            key=lambda x: x["count"],
            reverse=True,
        )

    def should_retry(self, studio: str, operation: str = "") -> bool:
        """Decide if a failed operation should be retried based on learnings."""
        key = f"retry:{studio}:{operation}"
        entry = self._learnings.get(key)
        if entry:
            return entry.confidence > 0.4
        return True  # Default: always retry first time

    # ── 4. PRIORITIZE ─────────────────────────────────────────

    def prioritize(self, tasks: list[AutoTask]) -> list[AutoTask]:
        """Re-prioritize tasks using KPI impact and learnings."""
        for task in tasks:
            # Boost priority for KPI-related tasks
            if task.source == "kpi":
                task.priority = min(10.0, task.priority + 1.0)

            # Reduce priority if past retries failed
            if task.source == "self_heal":
                if not self.should_retry(task.studio):
                    task.priority = max(1.0, task.priority - 3.0)

            # Boost priority if knowledge suggests urgency
            if task.source == "discovery":
                knowledge = self.memory.query_knowledge(
                    task.task[:50], limit=1,
                )
                if knowledge and knowledge[0].access_count > 3:
                    task.priority = min(10.0, task.priority + 0.5)

        tasks.sort(key=lambda t: t.priority, reverse=True)
        return tasks

    # ── 5. SCHEDULED OPS ──────────────────────────────────────

    def get_scheduled_tasks(self) -> list[AutoTask]:
        """Return tasks that should run on a schedule."""
        now = datetime.now(timezone.utc)
        hour = now.hour
        day = now.weekday()

        tasks = []

        # Daily: Analytics report
        if hour == 8:
            tasks.append(AutoTask(
                id="daily_analytics",
                source="schedule",
                studio="analytics",
                task="Generate daily analytics report",
                priority=6.0,
                reason="Scheduled daily report",
            ))

        # Monday: Weekly pipeline review
        if day == 0 and hour == 9:
            tasks.append(AutoTask(
                id="weekly_review",
                source="schedule",
                studio="analytics",
                task="Weekly pipeline performance review",
                priority=7.0,
                reason="Scheduled weekly review",
            ))

        # Daily: Check for stale leads
        if hour == 10:
            tasks.append(AutoTask(
                id="daily_leadops",
                source="schedule",
                studio="leadops",
                task="Check lead pipeline status and score new leads",
                priority=5.0,
                reason="Scheduled daily lead check",
            ))

        return tasks

    # ── MAIN LOOP ─────────────────────────────────────────────

    def run_cycle(self, max_tasks: int = 3, dry_run: bool = True) -> dict[str, Any]:
        """
        Run one autonomy cycle:
        1. Discover tasks
        2. Add scheduled tasks
        3. Prioritize
        4. Execute top N (or report if dry_run)
        """
        logger.info("🧠 Autonomy cycle starting...")

        # Discover
        discovered = self.discover_tasks()
        scheduled = self.get_scheduled_tasks()
        all_tasks = discovered + scheduled

        # Prioritize
        prioritized = self.prioritize(all_tasks)

        if not prioritized:
            return {
                "tasks_found": 0,
                "tasks_executed": 0,
                "results": [],
                "message": "No tasks discovered",
            }

        # Execute or report
        results = []
        executed = 0

        for task in prioritized[:max_tasks]:
            if dry_run:
                results.append({
                    "id": task.id,
                    "source": task.source,
                    "studio": task.studio,
                    "task": task.task[:100],
                    "priority": task.priority,
                    "reason": task.reason[:100],
                    "action": "would_execute",
                })
            else:
                result = self.self_heal(task)
                results.append({
                    "id": task.id,
                    "source": task.source,
                    "studio": task.studio,
                    "task": task.task[:100],
                    "priority": task.priority,
                    "success": result.get("success", False),
                    "output": str(result.get("output", ""))[:200],
                })
                executed += 1

        self.bus.publish_sync(Event(
            type="autonomy.cycle_complete",
            payload={
                "tasks_found": len(all_tasks),
                "tasks_executed": executed,
                "dry_run": dry_run,
            },
        ))

        return {
            "tasks_found": len(all_tasks),
            "tasks_executed": executed,
            "dry_run": dry_run,
            "results": results,
            "learnings": len(self._learnings),
        }

    # ── STATUS ────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get autonomy engine status."""
        return {
            "learnings": len(self._learnings),
            "top_patterns": self.get_learnings()[:5],
            "memory_stats": self.memory.get_stats(),
        }


def get_autonomy_engine() -> AutonomyEngine:
    return AutonomyEngine()
