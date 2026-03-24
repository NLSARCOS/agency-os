#!/usr/bin/env python3
"""
Agency OS v4.0 — Background Job Queue

SQLite-backed async job queue with:
- Job scheduling with priorities
- Retry with exponential backoff
- Dead letter queue for failed jobs
- Job status tracking
- Concurrent execution limits
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from kernel.config import get_config

logger = logging.getLogger("agency.jobqueue")


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD = "dead"  # Permanently failed → dead letter queue


@dataclass
class Job:
    id: str = ""
    name: str = ""
    payload: dict = field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    priority: int = 5  # 1=highest
    max_retries: int = 3
    retry_count: int = 0
    retry_delay_s: int = 5  # Base delay, doubles each retry
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    result: dict = field(default_factory=dict)


JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_queue (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 5,
    max_retries INTEGER DEFAULT 3,
    retry_count INTEGER DEFAULT 0,
    retry_delay_s INTEGER DEFAULT 5,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error TEXT DEFAULT '',
    result TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON job_queue(status);
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON job_queue(priority);

CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    name TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    retry_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    died_at TEXT NOT NULL
);
"""


class JobQueue:
    """
    SQLite-backed background job queue.

    Jobs are persisted so they survive restarts.
    Failed jobs retry with exponential backoff.
    Permanently failed jobs go to dead letter queue.
    """

    _instance: JobQueue | None = None
    _lock = threading.Lock()

    def __new__(cls) -> JobQueue:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False  # type: ignore
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore
            return
        self._initialized = True
        cfg = get_config()
        db_path = str(cfg.db_path).replace("agency.db", "jobs.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(JOB_SCHEMA)
        self._conn.commit()
        self._handlers: dict[str, Callable] = {}
        self._running = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = 3

    def register_handler(self, job_name: str, handler: Callable) -> None:
        """Register a handler function for a job type."""
        self._handlers[job_name] = handler
        logger.info("Job handler registered: %s", job_name)

    def enqueue(
        self,
        name: str,
        payload: dict | None = None,
        priority: int = 5,
        max_retries: int = 3,
    ) -> str:
        """Add a job to the queue. Returns job ID."""
        job_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            self._conn.execute(
                """INSERT INTO job_queue
                   (id, name, payload, status, priority, max_retries, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    name,
                    json.dumps(payload or {}),
                    JobStatus.PENDING.value,
                    priority,
                    max_retries,
                    now,
                ),
            )
            self._conn.commit()

        logger.info("Job enqueued: %s [%s] priority=%d", name, job_id, priority)
        return job_id

    def get_job(self, job_id: str) -> Job | None:
        """Get job status."""
        row = self._conn.execute(
            "SELECT * FROM job_queue WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            return None
        return Job(
            id=row["id"],
            name=row["name"],
            payload=json.loads(row["payload"] or "{}"),
            status=JobStatus(row["status"]),
            priority=row["priority"],
            max_retries=row["max_retries"],
            retry_count=row["retry_count"],
            retry_delay_s=row["retry_delay_s"],
            created_at=row["created_at"],
            started_at=row["started_at"] or "",
            completed_at=row["completed_at"] or "",
            error=row["error"] or "",
            result=json.loads(row["result"] or "{}"),
        )

    def process_next(self) -> Job | None:
        """Process the next pending job. Returns the job if processed."""
        with self._lock:
            row = self._conn.execute(
                """SELECT * FROM job_queue
                   WHERE status IN (?, ?)
                   ORDER BY priority ASC, created_at ASC
                   LIMIT 1""",
                (JobStatus.PENDING.value, JobStatus.RETRYING.value),
            ).fetchone()

            if not row:
                return None

            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "UPDATE job_queue SET status = ?, started_at = ? WHERE id = ?",
                (JobStatus.RUNNING.value, now, row["id"]),
            )
            self._conn.commit()

        job = Job(
            id=row["id"],
            name=row["name"],
            payload=json.loads(row["payload"] or "{}"),
            status=JobStatus.RUNNING,
            max_retries=row["max_retries"],
            retry_count=row["retry_count"],
            retry_delay_s=row["retry_delay_s"],
            created_at=row["created_at"],
            started_at=now,
        )

        handler = self._handlers.get(job.name)
        if not handler:
            self._fail_job(job, f"No handler for job type: {job.name}")
            return job

        try:
            result = handler(job.payload)
            self._complete_job(job, result or {})
        except Exception as e:
            self._handle_failure(job, str(e), traceback.format_exc())

        return job

    def _complete_job(self, job: Job, result: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """UPDATE job_queue
                   SET status = ?, completed_at = ?, result = ?
                   WHERE id = ?""",
                (JobStatus.COMPLETED.value, now, json.dumps(result), job.id),
            )
            self._conn.commit()
        job.status = JobStatus.COMPLETED
        logger.info("Job completed: %s [%s]", job.name, job.id)

    def _handle_failure(self, job: Job, error: str, tb: str) -> None:
        new_count = job.retry_count + 1

        if new_count >= job.max_retries:
            self._fail_job(job, error)
            self._send_to_dead_letter(job, error)
        else:
            # Schedule retry with exponential backoff
            delay = job.retry_delay_s * (2**job.retry_count)
            with self._lock:
                self._conn.execute(
                    """UPDATE job_queue
                       SET status = ?, retry_count = ?, error = ?
                       WHERE id = ?""",
                    (JobStatus.RETRYING.value, new_count, error, job.id),
                )
                self._conn.commit()
            logger.warning(
                "Job retrying: %s [%s] attempt %d/%d (delay %ds)",
                job.name,
                job.id,
                new_count,
                job.max_retries,
                delay,
            )

    def _fail_job(self, job: Job, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """UPDATE job_queue
                   SET status = ?, completed_at = ?, error = ?
                   WHERE id = ?""",
                (JobStatus.FAILED.value, now, error, job.id),
            )
            self._conn.commit()
        job.status = JobStatus.FAILED
        logger.error("Job failed: %s [%s] — %s", job.name, job.id, error)

    def _send_to_dead_letter(self, job: Job, error: str) -> None:
        """Move permanently failed job to dead letter queue."""
        now = datetime.now(timezone.utc).isoformat()
        dlq_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._conn.execute(
                """INSERT INTO dead_letter_queue
                   (id, job_id, name, payload, error, retry_count, created_at, died_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    dlq_id,
                    job.id,
                    job.name,
                    json.dumps(job.payload),
                    error,
                    job.retry_count,
                    job.created_at,
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE job_queue SET status = ? WHERE id = ?",
                (JobStatus.DEAD.value, job.id),
            )
            self._conn.commit()
        logger.error("Job sent to DLQ: %s [%s]", job.name, job.id)

    def get_pending_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM job_queue WHERE status IN (?, ?)",
            (JobStatus.PENDING.value, JobStatus.RETRYING.value),
        ).fetchone()
        return row["cnt"] if row else 0

    def get_dead_letters(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM dead_letter_queue ORDER BY died_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "job_id": r["job_id"],
                "name": r["name"],
                "error": r["error"],
                "retry_count": r["retry_count"],
                "created_at": r["created_at"],
                "died_at": r["died_at"],
            }
            for r in rows
        ]

    def retry_dead_letter(self, dlq_id: str) -> str | None:
        """Retry a job from the dead letter queue."""
        row = self._conn.execute(
            "SELECT * FROM dead_letter_queue WHERE id = ?", (dlq_id,)
        ).fetchone()
        if not row:
            return None

        new_id = self.enqueue(
            name=row["name"],
            payload=json.loads(row["payload"] or "{}"),
            priority=1,  # High priority for retries
        )

        with self._lock:
            self._conn.execute("DELETE FROM dead_letter_queue WHERE id = ?", (dlq_id,))
            self._conn.commit()

        return new_id

    def get_stats(self) -> dict:
        rows = self._conn.execute(
            """SELECT status, COUNT(*) as cnt
               FROM job_queue GROUP BY status"""
        ).fetchall()
        status_counts = {r["status"]: r["cnt"] for r in rows}

        dlq_count = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM dead_letter_queue"
        ).fetchone()

        return {
            "pending": status_counts.get("pending", 0),
            "running": status_counts.get("running", 0),
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
            "retrying": status_counts.get("retrying", 0),
            "dead_letters": dlq_count["cnt"] if dlq_count else 0,
            "handlers_registered": len(self._handlers),
        }

    def start_worker(self, poll_interval: float = 2.0) -> None:
        """Start background worker thread."""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(poll_interval,),
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Job queue worker started (poll=%.1fs)", poll_interval)

    def stop_worker(self) -> None:
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("Job queue worker stopped")

    def _worker_loop(self, poll_interval: float) -> None:
        while self._running:
            try:
                job = self.process_next()
                if job is None:
                    time.sleep(poll_interval)
            except Exception as e:
                logger.error("Worker error: %s", e)
                time.sleep(poll_interval)


_job_queue: JobQueue | None = None


def get_job_queue() -> JobQueue:
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue
