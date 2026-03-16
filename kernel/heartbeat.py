import asyncio
import logging
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
        
        # State tracking
        self.last_hustle: float = 0
        self.last_evolution: float = 0
        self.is_running: bool = False

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
        logger.info(
            f"Agency OS Heartbeat STARTED. "
            f"[Tick: {self.config.tick_interval}s, "
            f"Hustle: {self.config.hustle_interval_hours}h, "
            f"Evolve: {self.config.evolution_interval_hours}h]"
        )
        
        self._notifier.notify(
            title=self._msg("activated_title"),
            message=self._msg(
                "activated_body",
                hustle=self.config.hustle_interval_hours,
                evolve=self.config.evolution_interval_hours,
            ),
            source="heartbeat",
            priority=NotificationPriority.NORMAL,
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

    def stop(self) -> None:
        self.is_running = False
        logger.info("Agency OS Heartbeat STOPPED.")

    async def _tick(self) -> None:
        """The actual logic evaluated every minute."""
        now = time.time()
        
        # 1. Check if it's time to hustle (Find Clients/Opportunities)
        if now - self.last_hustle > (self.config.hustle_interval_hours * 3600):
            await self._run_hustle_cycle()
            self.last_hustle = time.time()
            
        # 2. Check if it's time to self-evolve (Improve Codebase)
        if now - self.last_evolution > (self.config.evolution_interval_hours * 3600):
            await self._run_evolution_cycle()
            self.last_evolution = time.time()
            
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
            logger.error(f"Evolution cycle failed: {e}")


_heartbeat: AgencyHeartbeat | None = None


def get_heartbeat() -> AgencyHeartbeat:
    global _heartbeat
    if _heartbeat is None:
        _heartbeat = AgencyHeartbeat()
    return _heartbeat
