#!/usr/bin/env python3
"""
Agency OS v3.5 — Audit Trail

Comprehensive logging of every AI interaction:
- Every AI call: model, agent, tokens, cost, latency, success
- Exportable to JSON/CSV for compliance
- Queryable summaries by studio, model, time period
- Retention policy with auto-cleanup
"""
from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from kernel.config import get_config

logger = logging.getLogger("agency.audit")


@dataclass
class AuditEntry:
    """A single audit log entry."""
    timestamp: str
    studio: str
    agent_id: str
    model: str
    provider: str
    tokens_in: int
    tokens_out: int
    estimated_cost: float
    latency_ms: float
    success: bool
    error: str = ""
    prompt_preview: str = ""  # First 100 chars
    correlation_id: str = ""


class AuditTrail:
    """
    Full audit trail for every AI call made by Agency OS.

    Storage: SQLite table `audit_log` in the agency database.
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        db_path = self.cfg.data_dir / "agency.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                studio TEXT NOT NULL DEFAULT '',
                agent_id TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                estimated_cost REAL DEFAULT 0.0,
                latency_ms REAL DEFAULT 0.0,
                success INTEGER DEFAULT 1,
                error TEXT DEFAULT '',
                prompt_preview TEXT DEFAULT '',
                correlation_id TEXT DEFAULT ''
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_studio ON audit_log(studio)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp)
        """)
        self._conn.commit()

    # ── Log ───────────────────────────────────────────────────

    def log(
        self,
        studio: str,
        agent_id: str,
        model: str,
        provider: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        estimated_cost: float = 0.0,
        latency_ms: float = 0.0,
        success: bool = True,
        error: str = "",
        prompt_preview: str = "",
        correlation_id: str = "",
    ) -> int:
        """Log an AI call to the audit trail."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """INSERT INTO audit_log
               (timestamp, studio, agent_id, model, provider,
                tokens_in, tokens_out, estimated_cost, latency_ms,
                success, error, prompt_preview, correlation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now, studio, agent_id, model, provider,
                tokens_in, tokens_out, estimated_cost, latency_ms,
                1 if success else 0, error, prompt_preview[:100],
                correlation_id,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    # ── Query ─────────────────────────────────────────────────

    def get_summary(self, days: int = 1) -> dict[str, Any]:
        """Get usage summary for the last N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        row = self._conn.execute(
            """SELECT
                COUNT(*) as total_calls,
                SUM(tokens_in) as total_tokens_in,
                SUM(tokens_out) as total_tokens_out,
                SUM(estimated_cost) as total_cost,
                AVG(latency_ms) as avg_latency,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failures
               FROM audit_log WHERE timestamp >= ?""",
            (cutoff,),
        ).fetchone()

        return {
            "period_days": days,
            "total_calls": row["total_calls"] or 0,
            "total_tokens": (row["total_tokens_in"] or 0) + (row["total_tokens_out"] or 0),
            "total_cost_usd": round(row["total_cost"] or 0, 4),
            "avg_latency_ms": round(row["avg_latency"] or 0, 1),
            "failures": row["failures"] or 0,
            "success_rate": round(
                (1 - (row["failures"] or 0) / max(row["total_calls"] or 1, 1)) * 100, 1
            ),
        }

    def get_costs_by_studio(self, days: int = 1) -> list[dict]:
        """Get cost breakdown by studio."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        rows = self._conn.execute(
            """SELECT studio,
                COUNT(*) as calls,
                SUM(tokens_in + tokens_out) as tokens,
                SUM(estimated_cost) as cost,
                AVG(latency_ms) as avg_latency
               FROM audit_log WHERE timestamp >= ?
               GROUP BY studio ORDER BY cost DESC""",
            (cutoff,),
        ).fetchall()

        return [
            {
                "studio": r["studio"],
                "calls": r["calls"],
                "tokens": r["tokens"] or 0,
                "cost_usd": round(r["cost"] or 0, 4),
                "avg_latency_ms": round(r["avg_latency"] or 0, 1),
            }
            for r in rows
        ]

    def get_costs_by_model(self, days: int = 1) -> list[dict]:
        """Get cost breakdown by model."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        rows = self._conn.execute(
            """SELECT model,
                COUNT(*) as calls,
                SUM(tokens_in + tokens_out) as tokens,
                SUM(estimated_cost) as cost
               FROM audit_log WHERE timestamp >= ?
               GROUP BY model ORDER BY cost DESC""",
            (cutoff,),
        ).fetchall()

        return [
            {
                "model": r["model"],
                "calls": r["calls"],
                "tokens": r["tokens"] or 0,
                "cost_usd": round(r["cost"] or 0, 4),
            }
            for r in rows
        ]

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get most recent audit entries."""
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Export ────────────────────────────────────────────────

    def export_json(self, days: int = 7) -> str:
        """Export audit log as JSON."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE timestamp >= ? ORDER BY id",
            (cutoff,),
        ).fetchall()
        return json.dumps([dict(r) for r in rows], indent=2, default=str)

    def export_csv(self, days: int = 7) -> str:
        """Export audit log as CSV."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE timestamp >= ? ORDER BY id",
            (cutoff,),
        ).fetchall()

        if not rows:
            return "No data"

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=dict(rows[0]).keys())
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(r))
        return output.getvalue()

    # ── Cleanup ───────────────────────────────────────────────

    def cleanup(self, retention_days: int = 30) -> int:
        """Delete audit entries older than retention period."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM audit_log WHERE timestamp < ?", (cutoff,),
        )
        self._conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("Cleaned up %d audit entries older than %d days", deleted, retention_days)
        return deleted

    def get_total_entries(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as c FROM audit_log").fetchone()
        return row["c"] if row else 0


_audit: AuditTrail | None = None


def get_audit() -> AuditTrail:
    global _audit
    if _audit is None:
        _audit = AuditTrail()
    return _audit
