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
                "<b>{count}</b> new opportunities awaiting your approval.\n\n"
                "Use agency pipeline or the Initiative Engine to review."
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
                "<b>{count}</b> nuevas esperando tu aprobación.\n\n"
                "Usa agency pipeline o el Motor de Iniciativa para revisarlas."
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

        # ── Proactive startup notification ────────────────────
        try:
            from kernel.openclaw_bridge import get_openclaw
            get_openclaw().notify_owner(
                self._msg("activated_title") + "\n" +
                self._msg("activated_body",
                          hustle=self.config.hustle_interval_hours,
                          evolve=self.config.evolution_interval_hours)
            )
        except Exception:
            pass

        # ── Seed default scheduled tasks (first boot) ─────────
        self._seed_default_tasks()

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

        # 0. Sweep stuck missions (active/running > 2 hours = dead)
        self._sweep_stuck_missions()
        
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

        # 3. Autonomy: discover and execute tasks proactively
        await self._run_autonomy_cycle()

        # 4. Process missions in parallel (one per studio, concurrent execution)
        await self._run_mission_cycle()

        # 5. Execute dynamic scheduled tasks (from API)
        await self._run_scheduled_tasks()

        # 6. Check OAuth tokens and auto-refresh if near expiry
        self._check_token_refresh()

    async def _run_autonomy_cycle(self) -> None:
        """Run autonomy engine every tick — discover and execute proactive tasks."""
        try:
            from kernel.autonomy_engine import AutonomyEngine
            if not hasattr(self, "_autonomy_engine"):
                self._autonomy_engine = AutonomyEngine()
            
            result = self._autonomy_engine.run_cycle(max_tasks=2)
            
            discovered = result.get("discovered", 0)
            executed = result.get("executed", 0)
            
            if discovered > 0 or executed > 0:
                logger.info(
                    "Autonomy cycle: discovered %d, executed %d tasks",
                    discovered, executed,
                )
                if executed > 0:
                    try:
                        from kernel.openclaw_bridge import get_openclaw
                        get_openclaw().notify_owner(
                            f"🤖 Autonomy: executed {executed} proactive tasks"
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Autonomy cycle skipped: %s", e)

    def _seed_default_tasks(self) -> None:
        """Seed default scheduled tasks on first boot."""
        defaults = [
            {
                "name": "daily_lead_search",
                "prompt": (
                    "Busca 5 leads potenciales para servicios de desarrollo web, "
                    "automatización o marketing digital. Incluye nombre, empresa, "
                    "fuente y razón por la que son un buen prospecto."
                ),
                "interval_minutes": 1440,  # 24h
                "studio": "leadops",
                "priority": 6,
            },
            {
                "name": "daily_social_content",
                "prompt": (
                    "Genera 2 ideas de contenido para redes sociales (LinkedIn/Twitter) "
                    "sobre tendencias en desarrollo web, IA o marketing digital. "
                    "Incluye el copy listo para publicar."
                ),
                "interval_minutes": 1440,
                "studio": "creative",
                "priority": 4,
            },
            {
                "name": "weekly_competitive_analysis",
                "prompt": (
                    "Analiza 3 competidores en el espacio de agencias digitales. "
                    "Identifica sus fortalezas, debilidades y oportunidades que "
                    "podemos explotar. Presenta un resumen ejecutivo."
                ),
                "interval_minutes": 10080,  # 7 days
                "studio": "analytics",
                "priority": 5,
            },
            {
                "name": "weekly_performance_report",
                "prompt": (
                    "Genera un reporte semanal de rendimiento: misiones completadas, "
                    "leads generados, revenue, costos de IA, y métricas clave. "
                    "Envía el resumen al dueño."
                ),
                "interval_minutes": 10080,
                "studio": "analytics",
                "priority": 7,
            },
            {
                "name": "daily_revenue_check",
                "prompt": (
                    "Revisa el estado financiero del día: ingresos vs costos, "
                    "misiones activas por cliente, y alerta si hay anomalías "
                    "o clientes que necesitan seguimiento."
                ),
                "interval_minutes": 1440,
                "studio": "sales",
                "priority": 5,
            },
        ]
        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            seeded = 0
            for task in defaults:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO scheduled_tasks
                           (name, prompt, interval_minutes, studio, priority, enabled, created_at)
                           VALUES (?, ?, ?, ?, ?, 1, datetime('now'))""",
                        (task["name"], task["prompt"], task["interval_minutes"],
                         task["studio"], task["priority"]),
                    )
                    if conn.total_changes:
                        seeded += 1
                except Exception:
                    pass
            conn.commit()
            conn.close()
            if seeded:
                logger.info("Seeded %d default scheduled tasks", seeded)
        except Exception as e:
            logger.debug("Could not seed scheduled tasks: %s", e)

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
        """Process queued missions — one per studio in parallel.
        
        The orchestrator handles ALL awareness. Individual missions are silent.
        After processing, the orchestrator sends ONE digest notification.
        """
        try:
            if not hasattr(self, "_mission_engine"):
                from kernel.mission_engine import MissionEngine
                self._mission_engine = MissionEngine()
                self._mission_engine.auto_discover_studios()

            # (Stuck mission sweep already runs in step 0 of _tick)

            result = await self._mission_engine.run_parallel_cycle()
            if result.get("action") != "idle":
                studios = result.get("studios", 0)
                succeeded = result.get("succeeded", 0)
                failed = result.get("failed", 0)
                logger.info(
                    "Mission cycle: %d studios, %d succeeded, %d failed",
                    studios, succeeded, failed,
                )

                # ── Orchestrator Digest ──────────────────────────
                # Query missions completed in the last 5 minutes (this cycle)
                if succeeded > 0 or failed > 0:
                    self._send_orchestrator_digest()

        except Exception as e:
            logger.error("Mission cycle failed: %s", e, exc_info=True)

    def _send_orchestrator_digest(self) -> None:
        """Send ONE orchestrator digest of recently completed missions."""
        try:
            from kernel.state_manager import get_state
            state = get_state()

            recent = state._conn.execute("""
                SELECT id, name, studio, status, completed_at
                FROM missions 
                WHERE completed_at > datetime('now', '-5 minutes')
                AND status IN ('done', 'failed')
                ORDER BY completed_at DESC
            """).fetchall()

            if not recent:
                return

            done = [m for m in recent if m["status"] == "done"]
            failed = [m for m in recent if m["status"] == "failed"]
            studios = list(set(m["studio"] for m in recent))

            import os
            _es = os.environ.get("AGENCY_LANGUAGE", "en") == "es"

            lines = []
            for m in recent:
                icon = "✅" if m["status"] == "done" else "❌"
                short = m["name"].replace(f"[{m['studio'].upper()}] ", "")[:45]
                lines.append(f"  {icon} [{m['studio'].upper()}] {short}")

            summary = "\n".join(lines)

            if not failed:
                title = f"📊 {'Reporte' if _es else 'Report'}: {len(done)} {'completadas' if _es else 'done'}"
            else:
                title = (
                    f"📊 {'Reporte' if _es else 'Report'}: "
                    f"{len(done)}✅ {len(failed)}❌"
                )

            message = (
                f"{len(studios)} studio{'s' if len(studios) > 1 else ''}\n\n"
                f"{summary}"
            )

            try:
                from kernel.openclaw_bridge import get_openclaw
                get_openclaw().notify_owner(f"{title}\n{message}")
            except Exception:
                pass

        except Exception as e:
            logger.debug("Orchestrator digest error: %s", e)

    def _sweep_stuck_missions(self) -> None:
        """Mark missions stuck as active/running for too long as failed."""
        try:
            from kernel.state_manager import get_state
            state = get_state()

            # Running > 30 min or Active > 2 hours = dead
            stuck = state._conn.execute(
                """UPDATE missions 
                   SET status = 'failed', 
                       completed_at = datetime('now'),
                       result = '{"error": "Timed out — auto-cleaned"}'
                   WHERE (
                       (status = 'running' AND created_at < datetime('now', '-30 minutes'))
                       OR (status = 'active' AND created_at < datetime('now', '-2 hours'))
                   )
                   RETURNING id, name, status"""
            ).fetchall()
            if stuck:
                state._conn.commit()
                for row in stuck:
                    logger.warning(
                        "Swept stuck mission #%d (%s): %s", row[0], row[2], row[1]
                    )
                try:
                    from kernel.openclaw_bridge import get_openclaw
                    import os
                    _es = os.environ.get("AGENCY_LANGUAGE", "en") == "es"
                    get_openclaw().notify_owner(
                        f"🧹 {'Limpiadas' if _es else 'Cleaned'} {len(stuck)} "
                        f"{'misiones atascadas' if _es else 'stuck missions'}"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Stuck mission sweep error: %s", e)

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
                studio = task["studio"] or "analytics"
                priority = task["priority"] or 5

                # DEDUP: skip if an active/queued/running mission already exists for this task
                existing = state._conn.execute(
                    """SELECT COUNT(*) as cnt FROM missions
                       WHERE name LIKE ? AND status IN ('queued', 'active', 'running')""",
                    (f"%{task_name}%",),
                ).fetchone()
                if existing and existing["cnt"] > 0:
                    logger.debug("Scheduled task '%s' skipped — %d still pending", task_name, existing["cnt"])
                    continue

                logger.info("Scheduled task due: %s", task_name)

                try:
                    import json
                    mission_id = state.create_mission(
                        name=f"[Scheduled] {task_name}",
                        description=prompt,
                        studio=studio,
                        priority=priority,
                        metadata=json.dumps({
                            "source": "scheduled_task",
                            "task_name": task_name,
                        }),
                    )

                    state._conn.execute(
                        "UPDATE scheduled_tasks SET last_run_at = datetime('now') WHERE name = ?",
                        (task_name,),
                    )
                    state._conn.commit()

                    logger.info(
                        "Scheduled task '%s' → mission #%d (studio: %s)",
                        task_name, mission_id, studio,
                    )
                except Exception as e:
                    logger.error("Scheduled task '%s' failed to queue: %s", task_name, e)

        except Exception as e:
            logger.debug("Scheduled tasks check skipped: %s", e)

    def _check_token_refresh(self) -> None:
        """Check OAuth tokens and auto-refresh if near expiry (every 30 min)."""
        now = time.time()
        if not hasattr(self, "_last_token_check"):
            self._last_token_check = 0.0

        # Only check every 30 minutes
        if now - self._last_token_check < 1800:
            return

        self._last_token_check = now
        try:
            from kernel.token_refresher import check_and_refresh
            result = check_and_refresh()
            if result.get("refreshed", 0) > 0:
                logger.info("Token refresh: %s", result)
            elif result.get("failed", 0) > 0:
                logger.warning("Token refresh failures: %s", result)
        except Exception as e:
            logger.debug("Token refresh check skipped: %s", e)

_heartbeat: AgencyHeartbeat | None = None


def get_heartbeat() -> AgencyHeartbeat:
    global _heartbeat
    if _heartbeat is None:
        _heartbeat = AgencyHeartbeat()
    return _heartbeat
