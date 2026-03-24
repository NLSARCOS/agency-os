#!/usr/bin/env python3
"""
Agency OS — Mission Learner

Autonomous learning from completed missions:
  1. ANALYZE  — review completed/failed missions
  2. EXTRACT  — identify success patterns, failure causes, model performance
  3. STORE    — persist learnings in SQLite
  4. OPTIMIZE — adjust prompts, model routing, and agent selection

Runs automatically in the heartbeat cycle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from kernel.config import get_config
from kernel.state_manager import get_state

logger = logging.getLogger("agency.learner")


@dataclass
class MissionLearning:
    """A learning extracted from mission analysis."""

    id: str = ""
    category: str = ""  # model_perf | agent_skill | studio_pattern | failure
    insight: str = ""
    confidence: float = 0.0  # 0-1
    source_missions: list[int] = field(default_factory=list)
    recommended_action: str = ""
    applied: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class MissionLearner:
    """
    Learns from mission execution history.

    Analyzes:
    - Model performance per studio (latency, success rate)
    - Agent effectiveness per task type
    - Failure patterns and common causes
    - Optimal studio→model mappings
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self._learnings: list[MissionLearning] = []
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create learnings table if not exists."""
        try:
            self.state._conn.execute("""
                CREATE TABLE IF NOT EXISTS learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    insight TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    source_missions TEXT DEFAULT '[]',
                    recommended_action TEXT DEFAULT '',
                    applied INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            self.state._conn.commit()
        except Exception as e:
            logger.warning("Could not create learnings table: %s", e)

    # ── Analysis ─────────────────────────────────────────────

    def analyze_recent_missions(self, limit: int = 50) -> list[MissionLearning]:
        """Analyze recent completed missions and extract learnings."""
        learnings: list[MissionLearning] = []

        # Get recent completed/failed missions
        with self.state._lock:
            missions = self.state._conn.execute(
                """SELECT id, name, studio, status, result, metadata,
                          created_at, completed_at
                   FROM missions
                   WHERE status IN ('done', 'failed')
                   ORDER BY completed_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        if not missions:
            return learnings

        # 1. Model performance analysis
        learnings.extend(self._analyze_model_performance())

        # 2. Studio success rates
        learnings.extend(self._analyze_studio_patterns(missions))

        # 3. Failure pattern detection
        learnings.extend(self._analyze_failures(missions))

        # Store learnings
        for learning in learnings:
            self._store_learning(learning)

        self._learnings = learnings
        logger.info("Mission analysis: %d learnings extracted", len(learnings))
        return learnings

    def _analyze_model_performance(self) -> list[MissionLearning]:
        """Analyze which models perform best per studio."""
        learnings = []  # type: ignore
        try:
            with self.state._lock:
                rows = self.state._conn.execute("""
                    SELECT model_name, studio,
                           COUNT(*) as calls,
                           AVG(latency_ms) as avg_latency,
                           SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
                           SUM(tokens_in + tokens_out) as total_tokens
                    FROM model_usage
                    GROUP BY model_name, studio
                    HAVING calls >= 3
                    ORDER BY success_rate DESC, avg_latency ASC
                """).fetchall()

            if not rows:
                return learnings

            # Find best model per studio
            studio_best: dict[str, dict] = {}
            for r in rows:
                studio = r["studio"] or "general"
                data = dict(r)
                if (
                    studio not in studio_best
                    or data["success_rate"] > studio_best[studio]["success_rate"]
                ):
                    studio_best[studio] = data

            for studio, best in studio_best.items():
                if best["success_rate"] >= 80:
                    learnings.append(
                        MissionLearning(
                            category="model_perf",
                            insight=(
                                f"Best model for {studio}: {best['model_name']} "
                                f"({best['success_rate']:.0f}% success, "
                                f"{best['avg_latency']:.0f}ms avg latency)"
                            ),
                            confidence=min(best["success_rate"] / 100, 0.95),
                            recommended_action=f"Prioritize {best['model_name']} for {studio} studio",
                        )
                    )

            # Find problematic models (low success rate)
            for r in rows:
                data = dict(r)
                if data["success_rate"] < 50 and data["calls"] >= 5:
                    learnings.append(
                        MissionLearning(
                            category="model_perf",
                            insight=(
                                f"Model {data['model_name']} underperforming in "
                                f"{data['studio'] or 'general'}: {data['success_rate']:.0f}% success"
                            ),
                            confidence=0.7,
                            recommended_action=f"Consider replacing {data['model_name']} in {data['studio']}",
                        )
                    )

        except Exception as e:
            logger.error("Model performance analysis failed: %s", e)

        return learnings

    def _analyze_studio_patterns(self, missions: list) -> list[MissionLearning]:
        """Analyze studio success patterns."""
        learnings = []

        studio_stats: dict[str, dict] = {}
        for m in missions:
            studio = m["studio"]
            if studio not in studio_stats:
                studio_stats[studio] = {"total": 0, "success": 0, "fail": 0}
            studio_stats[studio]["total"] += 1
            if m["status"] == "done":
                studio_stats[studio]["success"] += 1
            else:
                studio_stats[studio]["fail"] += 1

        for studio, stats in studio_stats.items():
            rate = (
                (stats["success"] / stats["total"]) * 100 if stats["total"] > 0 else 0
            )

            if rate == 100 and stats["total"] >= 3:
                learnings.append(
                    MissionLearning(
                        category="studio_pattern",
                        insight=f"{studio} studio: 100% success rate ({stats['total']} missions)",
                        confidence=0.9,
                        recommended_action=f"{studio} is reliable, consider giving it more complex tasks",
                    )
                )
            elif rate < 50 and stats["total"] >= 3:
                learnings.append(
                    MissionLearning(
                        category="studio_pattern",
                        insight=(
                            f"{studio} studio struggling: {rate:.0f}% success rate "
                            f"({stats['fail']}/{stats['total']} failed)"
                        ),
                        confidence=0.8,
                        recommended_action=f"Review {studio} agent prompts and model assignment",
                    )
                )

        return learnings

    def _analyze_failures(self, missions: list) -> list[MissionLearning]:
        """Analyze failure patterns."""
        learnings = []  # type: ignore
        failures = [m for m in missions if m["status"] == "failed"]

        if not failures:
            return learnings

        # Categorize failure reasons
        timeout_count = 0
        model_error_count = 0
        tool_error_count = 0

        for m in failures:
            result = m.get("result", "")
            lower = result.lower() if result else ""

            if "timeout" in lower or "timed out" in lower:
                timeout_count += 1
            elif "model" in lower or "api" in lower or "rate limit" in lower:
                model_error_count += 1
            elif "tool" in lower or "command" in lower or "permission" in lower:
                tool_error_count += 1

        if timeout_count >= 2:
            learnings.append(
                MissionLearning(
                    category="failure",
                    insight=f"{timeout_count} missions failed due to timeouts",
                    confidence=0.85,
                    recommended_action="Increase timeout or break tasks into smaller steps",
                    source_missions=[
                        m["id"]
                        for m in failures
                        if "timeout" in (m.get("result", "").lower())
                    ],
                )
            )

        if model_error_count >= 2:
            learnings.append(
                MissionLearning(
                    category="failure",
                    insight=f"{model_error_count} missions failed due to model/API errors",
                    confidence=0.8,
                    recommended_action="Check model availability, consider adding more fallback providers",
                    source_missions=[
                        m["id"]
                        for m in failures
                        if "model" in (m.get("result", "").lower())
                        or "api" in (m.get("result", "").lower())
                    ],
                )
            )

        if tool_error_count >= 2:
            learnings.append(
                MissionLearning(
                    category="failure",
                    insight=f"{tool_error_count} missions failed due to tool errors",
                    confidence=0.75,
                    recommended_action="Review tool permissions and sandbox configuration",
                )
            )

        # Overall failure rate
        total = len(missions)
        fail_rate = (len(failures) / total) * 100 if total > 0 else 0
        if fail_rate > 30 and total >= 5:
            learnings.append(
                MissionLearning(
                    category="failure",
                    insight=f"High overall failure rate: {fail_rate:.0f}% ({len(failures)}/{total})",
                    confidence=0.9,
                    recommended_action="System-wide review needed: prompts, models, or task complexity",
                )
            )

        return learnings

    # ── Persistence ──────────────────────────────────────────

    def _store_learning(self, learning: MissionLearning) -> None:
        """Store a learning in SQLite."""
        try:
            # Check for duplicate insights
            with self.state._lock:
                existing = self.state._conn.execute(
                    "SELECT id FROM learnings WHERE insight = ? AND category = ?",
                    (learning.insight, learning.category),
                ).fetchone()

                if existing:
                    return  # Skip duplicate

                self.state._conn.execute(
                    """INSERT INTO learnings
                       (category, insight, confidence, source_missions,
                        recommended_action, applied, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        learning.category,
                        learning.insight,
                        learning.confidence,
                        json.dumps(learning.source_missions),
                        learning.recommended_action,
                        0,
                        learning.created_at,
                    ),
                )
                self.state._conn.commit()
        except Exception as e:
            logger.error("Failed to store learning: %s", e)

    def get_learnings(self, category: str | None = None, limit: int = 20) -> list[dict]:
        """Retrieve stored learnings."""
        try:
            with self.state._lock:
                if category:
                    rows = self.state._conn.execute(
                        "SELECT * FROM learnings WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                        (category, limit),
                    ).fetchall()
                else:
                    rows = self.state._conn.execute(
                        "SELECT * FROM learnings ORDER BY confidence DESC, created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_learning_summary(self) -> dict[str, Any]:
        """Get a summary of all learnings for agent context injection."""
        learnings = self.get_learnings(limit=50)

        summary: dict[str, list[str]] = {
            "model_insights": [],
            "studio_insights": [],
            "failure_patterns": [],
            "recommendations": [],
        }

        for learning in learnings:
            cat = learning.get("category", "")
            insight = learning.get("insight", "")
            action = learning.get("recommended_action", "")

            if cat == "model_perf":
                summary["model_insights"].append(insight)
            elif cat == "studio_pattern":
                summary["studio_insights"].append(insight)
            elif cat == "failure":
                summary["failure_patterns"].append(insight)

            if action:
                summary["recommendations"].append(action)

        return summary


def get_mission_learner() -> MissionLearner:
    return MissionLearner()
