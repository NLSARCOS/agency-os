#!/usr/bin/env python3
"""
Agency OS — Cross-Platform Scheduler

Python-based scheduler that replaces cron dependency.
Works on both Linux and macOS. Runs as daemon or one-shot.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any, Callable

import schedule

from kernel.config import get_config
from kernel.state_manager import get_state

logger = logging.getLogger("agency.scheduler")

# ── Default schedule ──────────────────────────────────────────

DEFAULT_SCHEDULE: list[dict[str, Any]] = [
    {
        "name": "mission_cycle",
        "description": "Execute pending missions",
        "interval_minutes": 20,
        "function": "kernel.mission_engine:run_cycle",
    },
    {
        "name": "report_generation",
        "description": "Generate system status report",
        "interval_minutes": 240,  # 4 hours
        "function": "kernel.reporter:generate_report",
    },
    {
        "name": "health_check",
        "description": "System health check",
        "interval_minutes": 60,
        "function": "kernel.scheduler:health_check",
    },
]


def health_check() -> dict:
    """Run a system health check."""
    state = get_state()
    cfg = get_config()
    checks = {
        "database": False,
        "config_loaded": False,
        "studios_dir": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        state.get_missions(limit=1)
        checks["database"] = True
    except Exception:
        pass

    checks["config_loaded"] = bool(cfg.root)
    checks["studios_dir"] = cfg.studios_dir.exists()

    is_healthy = all(v for k, v in checks.items() if k != "timestamp")
    checks["healthy"] = is_healthy

    state.log_event(
        "health_check",
        f"Health: {'OK' if is_healthy else 'DEGRADED'} — {checks}",
        source="scheduler",
        level="info" if is_healthy else "warning",
    )

    return checks


def _import_function(path: str) -> Callable:
    """Import a function from a dotted path like 'module.submodule:function'."""
    module_path, func_name = path.rsplit(":", 1)
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, func_name)


class AgencyScheduler:
    """Cross-platform job scheduler for Agency OS."""

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self._running = False
        self._jobs: list[dict] = []

        # Load schedule from config or use defaults
        yaml_schedule = self.cfg.schedule.get("jobs", [])
        self._schedule_config = yaml_schedule if yaml_schedule else DEFAULT_SCHEDULE

    def setup(self) -> None:
        """Configure all scheduled jobs."""
        schedule.clear()
        self._jobs = []

        for job_cfg in self._schedule_config:
            name = job_cfg["name"]
            interval = job_cfg.get("interval_minutes", 60)
            func_path = job_cfg.get("function", "")

            if not func_path:
                logger.warning("Job %s has no function, skipping", name)
                continue

            try:
                func = _import_function(func_path)
            except (ImportError, AttributeError) as e:
                logger.warning("Cannot import %s for job %s: %s", func_path, name, e)
                continue

            # Register with schedule library
            schedule.every(interval).minutes.do(self._run_job, name=name, func=func)
            self._jobs.append(
                {
                    "name": name,
                    "interval_minutes": interval,
                    "function": func_path,
                    "description": job_cfg.get("description", ""),
                }
            )
            logger.info("Scheduled job: %s (every %d min)", name, interval)

        self.state.log_event(
            "scheduler_setup",
            f"Scheduler configured with {len(self._jobs)} jobs",
            source="scheduler",
        )

    def _run_job(self, name: str, func: Callable) -> None:
        """Execute a scheduled job with error handling."""
        start = time.monotonic()
        try:
            logger.info("Running job: %s", name)
            func()
            duration = time.monotonic() - start

            self.state.log_event(
                "job_completed",
                f"Job {name} completed in {duration:.1f}s",
                source="scheduler",
            )
            logger.info("Job %s completed in %.1fs", name, duration)

        except Exception as e:
            duration = time.monotonic() - start
            error_msg = f"{e.__class__.__name__}: {e}"

            self.state.log_event(
                "job_failed",
                f"Job {name} failed after {duration:.1f}s: {error_msg}",
                source="scheduler",
                level="error",
            )
            logger.error("Job %s failed: %s", name, error_msg)

    def run_once(self) -> list[dict]:
        """Execute all jobs once immediately (for testing/manual runs)."""
        results = []
        for job_cfg in self._jobs:
            name = job_cfg["name"]
            func_path = job_cfg["function"]
            try:
                func = _import_function(func_path)
                start = time.monotonic()
                result = func()
                duration = time.monotonic() - start
                results.append(
                    {
                        "job": name,
                        "status": "ok",
                        "duration": round(duration, 2),
                        "result": str(result)[:200] if result else "",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "job": name,
                        "status": "error",
                        "error": str(e),
                    }
                )
        return results

    def start_daemon(self) -> None:
        """Start the scheduler daemon (blocks until stopped)."""
        self._running = True

        # Handle graceful shutdown
        def _signal_handler(sig: int, frame: Any) -> None:
            logger.info("Received signal %d, shutting down...", sig)
            self._running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        self.state.log_event(
            "scheduler_started",
            f"Scheduler daemon started with {len(self._jobs)} jobs",
            source="scheduler",
        )
        logger.info("Agency OS Scheduler started. Press Ctrl+C to stop.")

        # Also start the API server in the background for OpenClaw integrations
        self._start_api_server()

        while self._running:
            schedule.run_pending()
            time.sleep(10)  # Check every 10 seconds

        self.state.log_event(
            "scheduler_stopped",
            "Scheduler daemon stopped gracefully",
            source="scheduler",
        )
        logger.info("Scheduler stopped.")

    def stop(self) -> None:
        """Stop the scheduler daemon."""
        self._running = False

    def _start_api_server(self) -> None:
        """Start the API server in a background thread for external integrations."""
        try:
            from kernel.api_server import run_server
            import threading
            import os

            port = int(os.environ.get("AGENCY_API_PORT", "8080"))
            
            thread = threading.Thread(
                target=run_server,
                kwargs={"host": "0.0.0.0", "port": port},
                daemon=True,
                name="agency-api-thread"
            )
            thread.start()
            logger.info("API server auto-started on port %d", port)
        except Exception as e:
            logger.error("Failed to start API server thread: %s", e)

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "running": self._running,
            "jobs": self._jobs,
            "next_runs": [
                {
                    "job": str(j),
                    "next_run": str(j.next_run),
                }
                for j in schedule.get_jobs()
            ],
        }


def run_cycle() -> dict:
    """Convenience: run one mission cycle. Used by scheduler."""
    from kernel.mission_engine import MissionEngine

    engine = MissionEngine()
    results = engine.run_cycle()
    return {
        "executed": len(results),
        "done": sum(1 for r in results if r.get("status") == "done"),  # type: ignore
        "failed": sum(1 for r in results if r.get("status") == "failed"),  # type: ignore
    }
