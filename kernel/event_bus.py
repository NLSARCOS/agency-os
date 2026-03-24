#!/usr/bin/env python3
"""
Agency OS v5.0.0 — Event Bus

Async pub/sub event system for inter-agent communication.
Decouples agent interactions and enables delegation chains.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine
from uuid import uuid4

logger = logging.getLogger("agency.events")


class EventPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class Event:
    """Immutable event object flowing through the bus."""

    type: str
    payload: dict[str, Any]
    source: str = ""
    target: str = ""  # Empty = broadcast
    priority: EventPriority = EventPriority.NORMAL
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    correlation_id: str = ""  # Links related events in a chain
    reply_to: str = ""  # For request-response pattern

    def reply(self, payload: dict[str, Any], event_type: str = "") -> Event:
        """Create a reply event linked to this one."""
        return Event(
            type=event_type or f"{self.type}.reply",
            payload=payload,
            source=self.target,
            target=self.source,
            correlation_id=self.correlation_id or self.id,
            reply_to=self.id,
        )


# Handler type: receives Event, returns optional response
EventHandler = Callable[[Event], Coroutine[Any, Any, dict[str, Any] | None]]
SyncEventHandler = Callable[[Event], dict[str, Any] | None]


class EventBus:
    """
    Async event bus for inter-agent communication.

    Supports:
    - Topic-based pub/sub (subscribe/publish)
    - Targeted messaging (send to specific agent)
    - Request/response pattern (request → await reply)
    - Priority queues
    - Event history for replay/debugging
    """

    _instance: EventBus | None = None
    _lock = threading.Lock()

    def __new__(cls) -> EventBus:
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
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._sync_handlers: dict[str, list[SyncEventHandler]] = defaultdict(list)
        self._agent_handlers: dict[str, EventHandler] = {}
        self._history: list[Event] = []
        self._max_history = 1000
        self._pending_replies: dict[str, asyncio.Future[Event]] = {}
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._running = False
        self._stats = {
            "published": 0,
            "delivered": 0,
            "errors": 0,
        }

    # ── Subscribe ─────────────────────────────────────────────

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe an async handler to an event type."""
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed to '%s': %s", event_type, handler.__name__)

    def subscribe_sync(self, event_type: str, handler: SyncEventHandler) -> None:
        """Subscribe a sync handler to an event type."""
        self._sync_handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (e.g., for logging)."""
        self._handlers["*"].append(handler)

    def register_agent(self, agent_id: str, handler: EventHandler) -> None:
        """Register a direct message handler for an agent."""
        self._agent_handlers[agent_id] = handler
        logger.debug("Agent '%s' registered for direct messages", agent_id)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    # ── Publish ───────────────────────────────────────────────

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        self._stats["published"] += 1
        self._record_history(event)

        # If targeted, deliver directly to agent
        if event.target and event.target in self._agent_handlers:
            try:
                await self._agent_handlers[event.target](event)
                self._stats["delivered"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.error("Error delivering to agent '%s': %s", event.target, e)
            return

        # Check for pending reply futures
        if event.reply_to and event.reply_to in self._pending_replies:
            self._pending_replies[event.reply_to].set_result(event)
            del self._pending_replies[event.reply_to]
            return

        # Broadcast to topic subscribers
        handlers = self._handlers.get(event.type, []) + self._handlers.get("*", [])
        for handler in handlers:
            try:
                await handler(event)
                self._stats["delivered"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(
                    "Error in handler '%s' for event '%s': %s",
                    handler.__name__,
                    event.type,
                    e,
                )

        # Also run sync handlers
        for handler in self._sync_handlers.get(event.type, []):  # type: ignore
            try:
                handler(event)  # type: ignore
                self._stats["delivered"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.error("Sync handler error for '%s': %s", event.type, e)

    def publish_sync(self, event: Event) -> None:
        """Synchronous publish for non-async contexts."""
        self._stats["published"] += 1
        self._record_history(event)

        for handler in self._sync_handlers.get(event.type, []):
            try:
                handler(event)
                self._stats["delivered"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                logger.error("Sync handler error: %s", e)

    # ── Request/Response ──────────────────────────────────────

    async def request(self, event: Event, timeout: float = 30.0) -> Event | None:
        """
        Send an event and wait for a reply.
        Implements request-response pattern for inter-agent calls.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Event] = loop.create_future()
        self._pending_replies[event.id] = future
        await self.publish(event)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Request timed out: %s → %s", event.type, event.target)
            self._pending_replies.pop(event.id, None)
            return None

    # ── Convenience Constructors ──────────────────────────────

    @staticmethod
    def mission_event(
        event_type: str, mission_id: int, payload: dict | None = None, **kwargs: Any
    ) -> Event:
        data = {"mission_id": mission_id, **(payload or {})}
        return Event(type=f"mission.{event_type}", payload=data, **kwargs)

    @staticmethod
    def agent_event(
        source: str, target: str, action: str, payload: dict | None = None
    ) -> Event:
        return Event(
            type=f"agent.{action}",
            payload=payload or {},
            source=source,
            target=target,
        )

    @staticmethod
    def tool_event(
        tool_name: str, result: dict | None = None, agent: str = ""
    ) -> Event:
        return Event(
            type=f"tool.{tool_name}",
            payload=result or {},
            source=agent,
        )

    # ── History & Stats ───────────────────────────────────────

    def _record_history(self, event: Event) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

    def get_history(
        self,
        event_type: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        events = self._history
        if event_type:
            events = [e for e in events if e.type == event_type]
        if source:
            events = [e for e in events if e.source == source]
        return [
            {
                "id": e.id,
                "type": e.type,
                "source": e.source,
                "target": e.target,
                "priority": e.priority.value,
                "timestamp": e.timestamp,
                "payload_keys": list(e.payload.keys()),
            }
            for e in events[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "subscribers": {k: len(v) for k, v in self._handlers.items()},
            "agents": list(self._agent_handlers.keys()),
            "history_size": len(self._history),
            "pending_replies": len(self._pending_replies),
        }

    def reset(self) -> None:
        """Reset for testing."""
        self._handlers.clear()
        self._sync_handlers.clear()
        self._agent_handlers.clear()
        self._history.clear()
        self._pending_replies.clear()
        self._stats = {"published": 0, "delivered": 0, "errors": 0}


def get_event_bus() -> EventBus:
    return EventBus()
