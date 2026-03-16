#!/usr/bin/env python3
"""
Agency OS v3.0 — Multi-Channel Connector

Routes messages from multiple channels through OpenClaw:
- WhatsApp (via webhook)
- Telegram (via bot API)
- Discord (via bot)
- Web (HTTP API)
- CLI (direct)

All channels converge to the unified mission engine.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus
from kernel.state_manager import get_state

logger = logging.getLogger("agency.channels")


class ChannelType(str, Enum):
    CLI = "cli"
    WEB = "web"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    API = "api"


@dataclass
class IncomingMessage:
    """A message from any channel."""
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    channel: ChannelType = ChannelType.CLI
    sender: str = ""
    content: str = ""
    attachments: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class OutgoingMessage:
    """A response message to send back."""
    channel: ChannelType = ChannelType.CLI
    recipient: str = ""
    content: str = ""
    attachments: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ChannelConnector:
    """
    Multi-channel message router.

    All channels → process_message → route to studio/agent → respond
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self.bus = get_event_bus()
        self._handlers: dict[ChannelType, Any] = {}

    def process_message(self, msg: IncomingMessage) -> OutgoingMessage:
        """
        Process an incoming message from any channel.

        Flow: parse intent → route to studio → execute → format response
        """
        logger.info(
            "Message from %s [%s]: %s",
            msg.channel.value, msg.sender, msg.content[:80],
        )

        self.bus.publish_sync(Event(
            type="channel.message_received",
            payload={
                "channel": msg.channel.value,
                "sender": msg.sender,
                "message_id": msg.id,
            },
        ))

        # Route the message
        intent = self._parse_intent(msg.content)
        studio_name = intent.get("studio", "")
        operation = intent.get("operation", "")

        if studio_name:
            response = self._execute_via_studio(
                studio_name, msg.content, operation
            )
        else:
            response = self._execute_via_openclaw(msg)

        return OutgoingMessage(
            channel=msg.channel,
            recipient=msg.sender,
            content=response,
            metadata={"intent": intent},
        )

    def _parse_intent(self, text: str) -> dict[str, Any]:
        """Parse user intent to route to the right studio."""
        text_lower = text.lower()

        # Studio routing keywords
        routes = {
            "dev": ["code", "develop", "build", "bug", "deploy", "test", "código"],
            "marketing": ["campaign", "seo", "content", "marketing", "funnel", "campaña"],
            "sales": ["sell", "outreach", "proposal", "close", "deal", "ventas", "prospecto"],
            "leadops": ["lead", "scrape", "enrich", "prospect", "contacto"],
            "abm": ["account", "abm", "target", "icp", "persona"],
            "analytics": ["report", "analytics", "kpi", "dashboard", "metrics", "reporte"],
            "creative": ["design", "landing", "email", "copy", "creative", "diseño"],
        }

        for studio, keywords in routes.items():
            if any(kw in text_lower for kw in keywords):
                return {"studio": studio, "operation": "auto"}

        # System commands
        if any(kw in text_lower for kw in ["status", "health", "estado"]):
            return {"studio": "_system", "operation": "status"}

        return {"studio": "", "operation": "chat"}

    def _execute_via_studio(
        self, studio_name: str, task: str, operation: str
    ) -> str:
        """Execute via a specific studio pipeline."""
        if studio_name == "_system":
            return self._get_system_status()

        try:
            from studios.base_studio import load_all_studios
            studios = load_all_studios()
            studio = studios.get(studio_name)

            if not studio:
                return f"❌ Studio '{studio_name}' not found."

            result = studio.run(task=task)
            if result.get("success"):
                output = result.get("output", "")
                return f"✅ [{studio_name}] {output[:2000]}"
            else:
                return f"⚠️ [{studio_name}] {result.get('error', 'Unknown error')}"

        except Exception as e:
            return f"❌ Error: {e}"

    def _execute_via_openclaw(self, msg: IncomingMessage) -> str:
        """Execute via OpenClaw for general chat."""
        try:
            from kernel.openclaw_bridge import get_openclaw
            oc = get_openclaw()

            if oc.is_available():
                response = oc.chat(
                    messages=[
                        {"role": "system", "content": (
                            "You are Agency OS, an autonomous agency system. "
                            "Help the user with their request."
                        )},
                        {"role": "user", "content": msg.content},
                    ],
                    agent_id="system",
                )
                return response.get("content", "No response from OpenClaw")
            else:
                return (
                    "🤖 Agency OS v3.0 ready. OpenClaw is offline.\n\n"
                    "Available studios: dev, marketing, sales, leadops, abm, analytics, creative\n"
                    "Try: 'generate leads for medical companies in Ecuador'"
                )
        except Exception as e:
            return f"🤖 Agency OS ready. Try mentioning a studio keyword.\nError: {e}"

    def _get_system_status(self) -> str:
        """Get system status summary."""
        from studios.base_studio import load_all_studios
        from kernel.workflow_engine import get_workflow_engine
        from kernel.memory_manager import get_memory_manager

        studios = load_all_studios()
        we = get_workflow_engine()
        mm = get_memory_manager()
        stats = self.state.get_dashboard_stats()
        mem_stats = mm.get_stats()

        return (
            f"🏢 **Agency OS v3.0 Status**\n\n"
            f"📊 Studios: {len(studios)} active\n"
            f"📋 Workflows: {len(we.list_workflows())} loaded\n"
            f"📝 Memories: {mem_stats['total_memories']}\n"
            f"📚 Knowledge: {mem_stats['total_knowledge']}\n"
            f"📈 Missions: {stats.get('missions', {})}\n"
        )

    # ── Channel-Specific Handlers ─────────────────────────────

    def handle_webhook(self, payload: dict, channel: ChannelType) -> dict:
        """Handle a webhook from WhatsApp/Telegram/Discord."""
        msg = IncomingMessage(
            channel=channel,
            sender=payload.get("from", payload.get("user", "")),
            content=payload.get("text", payload.get("message", "")),
            metadata=payload,
        )
        response = self.process_message(msg)
        return {
            "status": "ok",
            "response": response.content,
            "channel": response.channel.value,
        }


def get_channel_connector() -> ChannelConnector:
    return ChannelConnector()
