#!/usr/bin/env python3
"""
Agency OS — State Manager

Persistent state via SQLite. Tracks missions, tasks, KPIs, events.
No more overwriting markdown files as "state".
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from kernel.config import get_config


class MissionStatus(str, Enum):
    QUEUED = "queued"
    ACTIVE = "active"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskStatus(str, Enum):
    PENDING = "pending"
    ROUTED = "routed"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    studio TEXT DEFAULT '',
    status TEXT DEFAULT 'queued',
    priority INTEGER DEFAULT 5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    result TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER REFERENCES missions(id),
    name TEXT NOT NULL,
    studio TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    model_used TEXT DEFAULT '',
    input_data TEXT DEFAULT '',
    output_data TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    duration_seconds REAL DEFAULT 0,
    error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kpis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studio TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    unit TEXT DEFAULT '',
    recorded_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source TEXT DEFAULT '',
    message TEXT NOT NULL,
    level TEXT DEFAULT 'info',
    timestamp TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS model_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    studio TEXT DEFAULT '',
    task_id INTEGER REFERENCES tasks(id),
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    latency_ms REAL DEFAULT 0,
    success INTEGER DEFAULT 1,
    error TEXT DEFAULT '',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    mission_id INTEGER REFERENCES missions(id),
    timestamp TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workflow_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    mission_id INTEGER REFERENCES missions(id),
    current_node TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    graph_def TEXT DEFAULT '{}',
    node_results TEXT DEFAULT '{}',
    checkpoint TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    agent_id TEXT DEFAULT '',
    mission_id INTEGER REFERENCES missions(id),
    params TEXT DEFAULT '{}',
    output TEXT DEFAULT '',
    success INTEGER DEFAULT 1,
    error TEXT DEFAULT '',
    duration_ms REAL DEFAULT 0,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    task TEXT NOT NULL,
    context TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    result TEXT DEFAULT '',
    mission_id INTEGER REFERENCES missions(id),
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    name TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL DEFAULT 60,
    studio TEXT DEFAULT '',
    priority INTEGER DEFAULT 5,
    enabled INTEGER DEFAULT 1,
    last_run_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company TEXT DEFAULT '',
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    pipeline_stage TEXT DEFAULT 'lead',
    source TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    total_revenue REAL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS financial_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER REFERENCES missions(id),
    client_id INTEGER REFERENCES clients(id),
    record_type TEXT NOT NULL DEFAULT 'cost',
    amount REAL NOT NULL DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_studio ON tasks(studio);
CREATE INDEX IF NOT EXISTS idx_kpis_studio ON kpis(studio);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_model_usage_model ON model_usage(model_name);
CREATE INDEX IF NOT EXISTS idx_agent_memory_agent ON agent_memory(agent_id);
CREATE INDEX IF NOT EXISTS idx_workflow_state_mission ON workflow_state(mission_id);
CREATE INDEX IF NOT EXISTS idx_tool_results_agent ON tool_results(agent_id);
CREATE INDEX IF NOT EXISTS idx_delegations_status ON delegations(status);
CREATE INDEX IF NOT EXISTS idx_clients_stage ON clients(pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_financial_mission ON financial_records(mission_id);
CREATE INDEX IF NOT EXISTS idx_financial_client ON financial_records(client_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateManager:
    """Thread-safe persistent state manager backed by SQLite."""

    _instance: StateManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> StateManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        cfg = get_config()
        self._db_path = cfg.db_path
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=15.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=15000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(DB_SCHEMA)
        self._conn.commit()

    # ── Missions ──────────────────────────────────────────────

    def create_mission(
        self,
        name: str,
        description: str = "",
        studio: str = "",
        priority: int = 5,
        metadata: dict | None = None,
    ) -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO missions (name, description, studio, priority,
                   created_at, updated_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, description, studio, priority, now, now,
                 json.dumps(metadata or {})),
            )
            self._conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def update_mission_status(
        self, mission_id: int, status: MissionStatus, result: str = ""
    ) -> None:
        now = _now()
        extras: dict[str, Any] = {"updated_at": now}
        if status == MissionStatus.RUNNING:
            extras["started_at"] = now
        elif status in (MissionStatus.DONE, MissionStatus.FAILED):
            extras["completed_at"] = now
            extras["result"] = result
        set_clause = ", ".join(f"{k} = ?" for k in ["status", *extras])
        vals = [status.value, *extras.values(), mission_id]
        with self._lock:
            self._conn.execute(
                f"UPDATE missions SET {set_clause} WHERE id = ?", vals
            )
            self._conn.commit()

    def get_missions(
        self, status: MissionStatus | None = None, limit: int = 50
    ) -> list[dict]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM missions WHERE status = ? ORDER BY priority ASC, created_at ASC LIMIT ?",
                (status.value, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM missions ORDER BY priority ASC, created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_mission(self, mission_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
        return dict(row) if row else None

    def promote_next_mission(self) -> dict | None:
        """Auto-promote the next queued mission to active."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM missions WHERE status = 'queued' "
                "ORDER BY priority ASC, created_at ASC LIMIT 1"
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE missions SET status = 'active', updated_at = ? WHERE id = ?",
                    (_now(), row["id"]),
                )
                self._conn.commit()
                return dict(row)
        return None

    def promote_next_per_studio(self) -> list[dict]:
        """Promote one queued mission per studio for parallel execution."""
        with self._lock:
            # Get distinct studios with queued missions
            studios = self._conn.execute(
                "SELECT DISTINCT studio FROM missions WHERE status = 'queued'"
            ).fetchall()

            promoted = []
            for (studio,) in studios:
                row = self._conn.execute(
                    "SELECT * FROM missions WHERE status = 'queued' AND studio = ? "
                    "ORDER BY priority ASC, created_at ASC LIMIT 1",
                    (studio,),
                ).fetchone()
                if row:
                    self._conn.execute(
                        "UPDATE missions SET status = 'active', updated_at = ? WHERE id = ?",
                        (_now(), row["id"]),
                    )
                    promoted.append(dict(row))

            if promoted:
                self._conn.commit()
            return promoted

    # ── Tasks ─────────────────────────────────────────────────

    def create_task(
        self,
        name: str,
        studio: str,
        mission_id: int | None = None,
        input_data: str = "",
    ) -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO tasks (name, studio, mission_id, input_data, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, studio, mission_id, input_data, now),
            )
            self._conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def complete_task(
        self,
        task_id: int,
        output_data: str = "",
        model_used: str = "",
        duration: float = 0,
        error: str = "",
    ) -> None:
        status = TaskStatus.COMPLETED if not error else TaskStatus.FAILED
        with self._lock:
            self._conn.execute(
                """UPDATE tasks SET status = ?, output_data = ?, model_used = ?,
                   duration_seconds = ?, error = ?, completed_at = ? WHERE id = ?""",
                (status.value, output_data, model_used, duration, error, _now(), task_id),
            )
            self._conn.commit()

    def get_tasks(
        self, studio: str | None = None, status: TaskStatus | None = None, limit: int = 50
    ) -> list[dict]:
        conditions = []
        params: list[Any] = []
        if studio:
            conditions.append("studio = ?")
            params.append(studio)
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ?", params
        ).fetchall()
        return [dict(r) for r in rows]

    # ── KPIs ──────────────────────────────────────────────────

    def log_kpi(
        self,
        studio: str,
        metric_name: str,
        metric_value: float,
        unit: str = "",
        metadata: dict | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO kpis (studio, metric_name, metric_value, unit,
                   recorded_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (studio, metric_name, metric_value, unit, _now(),
                 json.dumps(metadata or {})),
            )
            self._conn.commit()

    def get_kpis(
        self, studio: str | None = None, metric: str | None = None, limit: int = 100
    ) -> list[dict]:
        conditions = []
        params: list[Any] = []
        if studio:
            conditions.append("studio = ?")
            params.append(studio)
        if metric:
            conditions.append("metric_name = ?")
            params.append(metric)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM kpis {where} ORDER BY recorded_at DESC LIMIT ?", params
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Events ────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        message: str,
        source: str = "",
        level: str = "info",
        metadata: dict | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO events (event_type, source, message, level,
                   timestamp, metadata) VALUES (?, ?, ?, ?, ?, ?)""",
                (event_type, source, message, level, _now(),
                 json.dumps(metadata or {})),
            )
            self._conn.commit()

    def get_events(
        self, event_type: str | None = None, level: str | None = None, limit: int = 100
    ) -> list[dict]:
        conditions = []
        params: list[Any] = []
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if level:
            conditions.append("level = ?")
            params.append(level)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM events {where} ORDER BY timestamp DESC LIMIT ?", params
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Model Usage ───────────────────────────────────────────

    def log_model_usage(
        self,
        model_name: str,
        studio: str = "",
        task_id: int | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: float = 0,
        success: bool = True,
        error: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO model_usage (model_name, studio, task_id, tokens_in,
                   tokens_out, latency_ms, success, error, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (model_name, studio, task_id, tokens_in, tokens_out,
                 latency_ms, int(success), error, _now()),
            )
            self._conn.commit()

    # ── Stats / Dashboard ─────────────────────────────────────

    def get_dashboard_stats(self) -> dict:
        """Get a snapshot of system health."""
        stats: dict[str, Any] = {}

        # Mission counts by status
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM missions GROUP BY status"
        ).fetchall()
        stats["missions"] = {r["status"]: r["cnt"] for r in rows}

        # Task counts by studio
        rows = self._conn.execute(
            "SELECT studio, COUNT(*) as cnt FROM tasks GROUP BY studio"
        ).fetchall()
        stats["tasks_by_studio"] = {r["studio"]: r["cnt"] for r in rows}

        # Recent KPIs per studio
        rows = self._conn.execute(
            """SELECT studio, metric_name, metric_value, recorded_at
               FROM kpis ORDER BY recorded_at DESC LIMIT 20"""
        ).fetchall()
        stats["recent_kpis"] = [dict(r) for r in rows]

        # Model usage summary
        rows = self._conn.execute(
            """SELECT model_name, COUNT(*) as calls,
                      SUM(tokens_in) as total_in, SUM(tokens_out) as total_out,
                      AVG(latency_ms) as avg_latency,
                      SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failures
               FROM model_usage GROUP BY model_name"""
        ).fetchall()
        stats["model_usage"] = [dict(r) for r in rows]

        # Event counts by level
        rows = self._conn.execute(
            "SELECT level, COUNT(*) as cnt FROM events GROUP BY level"
        ).fetchall()
        stats["events_by_level"] = {r["level"]: r["cnt"] for r in rows}

        return stats

    # ── Agent Memory Persistence ─────────────────────────────

    def save_agent_memory(
        self, agent_id: str, role: str, content: str,
        mission_id: int | None = None, metadata: dict | None = None,
    ) -> int:
        """Persist an agent memory entry to SQLite."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO agent_memory
                   (agent_id, role, content, mission_id, timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (agent_id, role, content[:5000], mission_id, now,
                 json.dumps(metadata or {})),
            )
            self._conn.commit()
            return cur.lastrowid

    def load_agent_memory(
        self, agent_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Load recent memory entries for an agent."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT role, content, mission_id, timestamp, metadata
                   FROM agent_memory WHERE agent_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (agent_id, limit),
            ).fetchall()
        # Return in chronological order
        return [dict(r) for r in reversed(rows)]

    # ── Clients (CRM) ────────────────────────────────────────

    def create_client(
        self,
        name: str,
        company: str = "",
        email: str = "",
        phone: str = "",
        source: str = "",
        notes: str = "",
        pipeline_stage: str = "lead",
    ) -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO clients
                   (name, company, email, phone, pipeline_stage, source, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, company, email, phone, pipeline_stage, source, notes, now, now),
            )
            self._conn.commit()
            return cur.lastrowid

    def update_client(self, client_id: int, **fields: Any) -> None:
        allowed = {"name", "company", "email", "phone", "pipeline_stage", "source", "notes", "total_revenue"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._lock:
            self._conn.execute(
                f"UPDATE clients SET {set_clause} WHERE id = ?",
                [*updates.values(), client_id],
            )
            self._conn.commit()

    def get_clients(
        self, pipeline_stage: str | None = None, limit: int = 100
    ) -> list[dict]:
        if pipeline_stage:
            rows = self._conn.execute(
                "SELECT * FROM clients WHERE pipeline_stage = ? ORDER BY updated_at DESC LIMIT ?",
                (pipeline_stage, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM clients ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_client(self, client_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── Financial Tracking ────────────────────────────────────

    def log_financial(
        self,
        record_type: str,
        amount: float,
        description: str = "",
        mission_id: int | None = None,
        client_id: int | None = None,
        currency: str = "USD",
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO financial_records
                   (mission_id, client_id, record_type, amount, currency, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (mission_id, client_id, record_type, amount, currency, description, _now()),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_financial_summary(self, days: int = 30) -> dict:
        """Get financial summary for the last N days."""
        rows = self._conn.execute(
            """SELECT record_type, SUM(amount) as total, COUNT(*) as count, currency
               FROM financial_records
               WHERE created_at > datetime('now', ? || ' days')
               GROUP BY record_type, currency""",
            (f"-{days}",),
        ).fetchall()

        summary = {"revenue": 0.0, "costs": 0.0, "records": 0}
        for r in rows:
            if r["record_type"] == "revenue":
                summary["revenue"] += r["total"] or 0
            else:
                summary["costs"] += r["total"] or 0
            summary["records"] += r["count"]

        summary["profit"] = summary["revenue"] - summary["costs"]
        return summary

    def get_weekly_report_data(self) -> dict:
        """Aggregate data for auto-generated weekly reports."""
        report: dict[str, Any] = {}

        # Missions completed this week
        rows = self._conn.execute(
            """SELECT status, COUNT(*) as cnt FROM missions
               WHERE updated_at > datetime('now', '-7 days')
               GROUP BY status"""
        ).fetchall()
        report["missions"] = {r["status"]: r["cnt"] for r in rows}

        # Top studios by activity
        rows = self._conn.execute(
            """SELECT studio, COUNT(*) as cnt FROM tasks
               WHERE created_at > datetime('now', '-7 days')
               GROUP BY studio ORDER BY cnt DESC"""
        ).fetchall()
        report["studio_activity"] = {r["studio"]: r["cnt"] for r in rows}

        # Financial summary
        report["financials"] = self.get_financial_summary(7)

        # Pipeline counts
        rows = self._conn.execute(
            "SELECT pipeline_stage, COUNT(*) as cnt FROM clients GROUP BY pipeline_stage"
        ).fetchall()
        report["pipeline"] = {r["pipeline_stage"]: r["cnt"] for r in rows}

        # Model usage summary
        rows = self._conn.execute(
            """SELECT COUNT(*) as calls, SUM(tokens_in + tokens_out) as tokens
               FROM model_usage WHERE timestamp > datetime('now', '-7 days')"""
        ).fetchone()
        report["ai_usage"] = {
            "calls": rows["calls"] if rows else 0,
            "tokens": rows["tokens"] if rows else 0,
        }

        return report

    def close(self) -> None:
        self._conn.close()


def get_state() -> StateManager:
    return StateManager()
