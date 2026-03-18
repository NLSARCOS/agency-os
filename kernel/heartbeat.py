import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from dataclasses import dataclass

from kernel.config import get_config
from kernel.event_bus import get_event_bus
from kernel.initiative_engine import get_initiative_engine
from kernel.self_evolution import get_evolution_engine
from kernel.skill_evaluator import get_skill_evaluator
from kernel.notifier import get_notifier, NotificationPriority
from kernel.openclaw_bridge import get_openclaw

logger = logging.getLogger("agency.heartbeat")


@dataclass
class HeartbeatConfig:
    # How often the heartbeat loops to check conditions (seconds)
    tick_interval: int = 60
    
    # Hours between proactive hustle attempts
    hustle_interval_hours: int = 12
    
    # Hours between proactive self-evolution passes
    evolution_interval_hours: int = 24


class AgencyHeartbeat:
    """
    The 24/7 pulse of Agency OS.
    
    Runs indefinitely in a background thread or event loop.
    Checks the clock and decides:
    - Should I hustle for clients?
    - Should I optimize my own code (evolve)?
    - Do I need to clean up my HR (Skills)?
    """

    def __init__(self, config: HeartbeatConfig | None = None) -> None:
        self.config = config or HeartbeatConfig()
        self.cfg = get_config()
        self._bus = get_event_bus()
        self._initiative = get_initiative_engine()
        self._evolution = get_evolution_engine()
        self._skill_evaluator = get_skill_evaluator()
        self._notifier = get_notifier()
        self.openclaw = get_openclaw()

        # Persistent state (survives restarts)
        self._db_path = self.cfg.data_dir / "agency.db"
        self._pid_file = self.cfg.data_dir / "heartbeat.pid"
        self.last_hustle: float = self._load_timestamp("last_hustle")
        self.last_evolution: float = self._load_timestamp("last_evolution")
        self.is_running: bool = False

    def _load_timestamp(self, key: str) -> float:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS heartbeat_state (key TEXT PRIMARY KEY, value REAL)")
                row = conn.execute("SELECT value FROM heartbeat_state WHERE key = ?", (key,)).fetchone()
                return row[0] if row else 0.0
        except Exception:
            return 0.0

    def _save_timestamp(self, key: str, value: float) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS heartbeat_state (key TEXT PRIMARY KEY, value REAL)")
                conn.execute("INSERT OR REPLACE INTO heartbeat_state (key, value) VALUES (?, ?)", (key, value))
        except Exception as e:
            logger.warning("Failed to persist %s: %s", key, e)

    # ── i18n messages ────────────────────────────────────────
    _MESSAGES = {
        "en": {
            "activated_title": "🫀 Agency Heartbeat Activated",
            "activated_body": (
                "I am now alive and running autonomously 24/7.\n"
                "- Hustling every {hustle}h.\n"
                "- Self-evolving every {evolve}h.\n"
                "- Monitoring agent performance."
            ),
            "hustle_title": "💼 Hustle Cycle Complete",
            "hustle_body": (
                "I proactively searched for business and found "
                "**{count}** new opportunities awaiting your approval.\n\n"
                "Use `agency pipeline` or the Initiative Engine to review."
            ),
        },
        "es": {
            "activated_title": "🫀 Latido de Agencia Activado",
            "activated_body": (
                "Estoy viva y operando de forma autónoma 24/7.\n"
                "- Buscando oportunidades cada {hustle}h.\n"
                "- Auto-evolucionando cada {evolve}h.\n"
                "- Monitoreando rendimiento de agentes."
            ),
            "hustle_title": "💼 Ciclo de Búsqueda Completado",
            "hustle_body": (
                "Busqué proactivamente oportunidades de negocio y encontré "
                "**{count}** nuevas esperando tu aprobación.\n\n"
                "Usa `agency pipeline` o el Motor de Iniciativa para revisarlas."
            ),
        },
    }

    def _msg(self, key: str, **kwargs: object) -> str:
        lang = self.cfg.language
        msgs = self._MESSAGES.get(lang, self._MESSAGES["en"])
        template = msgs.get(key, self._MESSAGES["en"][key])
        return template.format(**kwargs) if kwargs else template

    async def run(self) -> None:
        """Start the infinite vitality loop."""
        if self.is_running:
            return

        self.is_running = True

        # Write PID file for external health checks
        self._pid_file.write_text(str(os.getpid()))

        # ── Graceful Shutdown ────────────────────────────────
        import signal

        def _handle_shutdown(signum: int, frame: object) -> None:
            sig_name = signal.Signals(signum).name
            logger.info("Received %s — shutting down gracefully...", sig_name)
            self.is_running = False

        signal.signal(signal.SIGTERM, _handle_shutdown)
        signal.signal(signal.SIGINT, _handle_shutdown)

        # ── Auto-start API Server ────────────────────────────
        self._start_api_server()

        logger.info(
            f"Agency OS Heartbeat STARTED (PID {os.getpid()}). "
            f"[Tick: {self.config.tick_interval}s, "
            f"Hustle: {self.config.hustle_interval_hours}h, "
            f"Evolve: {self.config.evolution_interval_hours}h]"
        )

        try:
            while self.is_running:
                await self._tick()
                await asyncio.sleep(self.config.tick_interval)
        except asyncio.CancelledError:
            logger.info("Heartbeat cancelled.")
        except Exception as e:
            logger.error(f"Heartbeat crashed: {e}")
        finally:
            self.is_running = False
            logger.info("Heartbeat stopped. Cleaning up...")
            if self._pid_file.exists():
                self._pid_file.unlink(missing_ok=True)

    def stop(self) -> None:
        self.is_running = False
        logger.info("Agency OS Heartbeat STOPPED.")
        if self._pid_file.exists():
            self._pid_file.unlink(missing_ok=True)

    def _start_api_server(self) -> None:
        """Start the API server in a background thread for OpenClaw feedback."""
        try:
            from kernel.api_server import create_app
            import uvicorn
            import threading

            port = int(os.environ.get("AGENCY_API_PORT", "8080"))
            app = create_app()

            def _run_server() -> None:
                uvicorn.run(
                    app,
                    host="0.0.0.0",
                    port=port,
                    log_level="warning",
                    access_log=False,
                )

            thread = threading.Thread(
                target=_run_server, daemon=True, name="agency-api"
            )
            thread.start()
            logger.info("API server started on port %d (for OpenClaw feedback)", port)
        except ImportError:
            logger.warning(
                "FastAPI/uvicorn not installed — API server disabled. "
                "Install with: pip install fastapi uvicorn"
            )
        except Exception as e:
            logger.error("Failed to start API server: %s", e)

    async def _tick(self) -> None:
        """The actual logic evaluated every minute."""
        now = time.time()
        
        # 1. Check if it's time to hustle (Find Clients/Opportunities)
        if now - self.last_hustle > (self.config.hustle_interval_hours * 3600):
            await self._run_hustle_cycle()
            self.last_hustle = time.time()
            self._save_timestamp("last_hustle", self.last_hustle)

        # 2. Check if it's time to self-evolve + learn (Improve Codebase)
        if now - self.last_evolution > (self.config.evolution_interval_hours * 3600):
            await self._run_evolution_cycle()
            await self._run_learning_cycle()
            self.last_evolution = time.time()
            self._save_timestamp("last_evolution", self.last_evolution)

        # 3. Process missions in parallel (one per studio, concurrent execution)
        await self._run_mission_cycle()

        # 4. Execute dynamic scheduled tasks (from API)
        await self._run_scheduled_tasks()
            
    async def _run_hustle_cycle(self) -> None:
        logger.info("Heartbeat: Triggering Hustle Cycle...")
        try:
            # Tell the agency to find business
            res = self._initiative.hustle()
            
            pending = len(res.get("pending_approval", []))
            
            if pending > 0:
                self._notifier.notify(
                    title=self._msg("hustle_title"),
                    message=self._msg("hustle_body", count=pending),
                    source="heartbeat",
                    priority=NotificationPriority.NORMAL,
                )
        except Exception as e:
            logger.error(f"Hustle cycle failed: {e}")

    async def _run_evolution_cycle(self) -> None:
        logger.info("Heartbeat: Triggering Self-Evolution Cycle...")
        try:
            # The evolution engine checks if the code is messy or if tests are failing
            self._evolution.evolve()
        except Exception as e:
            logger.error(
                "Evolution cycle failed: %s", e, exc_info=True
            )
            try:
                from kernel.openclaw_bridge import get_openclaw
                get_openclaw().notify_owner(
                    f"🚨 Evolution cycle failed: {e}"
                )
            except Exception:
                pass

    async def _run_learning_cycle(self) -> None:
        """Analyze past missions and extract learnings."""
        logger.info("Heartbeat: Running Learning Cycle...")
        try:
            from kernel.mission_learner import get_mission_learner
            learner = get_mission_learner()
            learnings = learner.analyze_recent_missions()
            if learnings:
                logger.info(
                    "Learning cycle: %d insights extracted", len(learnings)
                )
        except Exception as e:
            logger.error(f"Learning cycle failed: {e}")

    async def _run_mission_cycle(self) -> None:
        """Process queued missions — one per studio in parallel."""
        try:
            if not hasattr(self, "_mission_engine"):
                from kernel.mission_engine import MissionEngine
                self._mission_engine = MissionEngine()
                self._mission_engine.auto_discover_studios()

            # Clean up stuck missions (running > 30 minutes = likely hung)
            self._cleanup_stuck_missions()

            result = await self._mission_engine.run_parallel_cycle()
            if result.get("action") != "idle":
                studios = result.get("studios", 0)
                succeeded = result.get("succeeded", 0)
                failed = result.get("failed", 0)
                logger.info(
                    "Mission cycle: %d studios, %d succeeded, %d failed",
                    studios, succeeded, failed,
                )
                # Proactive notification on completion
                if succeeded > 0:
                    try:
                        from kernel.openclaw_bridge import get_openclaw
                        get_openclaw().notify_owner(
                            f"✅ Mission cycle: {succeeded} completed, {failed} failed"
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Mission cycle failed: %s", e, exc_info=True)

    def _cleanup_stuck_missions(self) -> None:
        """Mark missions stuck in 'running' for >30min as failed."""
        try:
            from kernel.state_manager import get_state
            state = get_state()
            stuck = state._conn.execute(
                """UPDATE missions 
                   SET status = 'failed', 
                       completed_at = datetime('now')
                   WHERE status = 'running' 
                   AND started_at < datetime('now', '-30 minutes')
                   RETURNING id, name"""
            ).fetchall()
            if stuck:
                state._conn.commit()
                for row in stuck:
                    logger.warning(
                        "Cleaned stuck mission #%d: %s", row[0], row[1]
                    )
                try:
                    from kernel.openclaw_bridge import get_openclaw
                    get_openclaw().notify_owner(
                        f"🧹 Cleaned {len(stuck)} stuck missions"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Stuck mission cleanup error: %s", e)

    async def _run_scheduled_tasks(self) -> None:
        """Execute dynamic scheduled tasks from the API-created schedule."""
        try:
            from kernel.state_manager import get_state
            state = get_state()

            # Check for enabled tasks due for execution
            rows = state._conn.execute(
                """SELECT name, prompt, interval_minutes, studio, priority, last_run_at
                   FROM scheduled_tasks
                   WHERE enabled = 1
                   AND (
                       last_run_at IS NULL
                       OR datetime(last_run_at, '+' || interval_minutes || ' minutes') <= datetime('now')
                   )"""
            ).fetchall()

            if not rows:
                return

            for task in rows:
                task_name = task["name"]
                prompt = task["prompt"]
                studio = task["studio"] or None
                priority = task["priority"] or 5

                logger.info("Scheduled task due: %s", task_name)

                try:
                    # Plan and queue via mission engine
                    objective = f"[Scheduled: {task_name}] {prompt}"
                    result = await self._mission_engine.plan_objective(
                        objective,
                        priority=priority,
                    )

                    # Update last_run_at
                    state._conn.execute(
                        "UPDATE scheduled_tasks SET last_run_at = datetime('now') WHERE name = ?",
                        (task_name,),
                    )
                    state._conn.commit()

                    logger.info(
                        "Scheduled task '%s' queued: %d missions",
                        task_name,
                        result.get("mission_count", 0),
                    )
                except Exception as e:
                    logger.error("Scheduled task '%s' failed to queue: %s", task_name, e)

        except Exception as e:
            logger.debug("Scheduled tasks check skipped: %s", e)
_heartbeat: AgencyHeartbeat | None = None


def get_heartbeat() -> AgencyHeartbeat:
    global _heartbeat
    if _heartbeat is None:
        _heartbeat = AgencyHeartbeat()
    return _heartbeat
