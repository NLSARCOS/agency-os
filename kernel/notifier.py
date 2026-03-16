#!/usr/bin/env python3
"""
Agency OS v5.0 — Notifier (Outbound Communication)

How Agency OS talks TO the owner/team:

  channel_connector.py = INBOUND  (owner → agency)
  notifier.py          = OUTBOUND (agency → owner)

Channels:
  1. Console / CLI  — always available
  2. Webhook        — POST to any URL (Slack, Discord, custom)
  3. File inbox     — writes to notifications/ folder
  4. OpenClaw       — sends via ClawBot/OpenClaw chat
  5. Event bus      — internal (other modules can listen)

Events that trigger notifications:
  - Initiative found opportunities → "I found 5 things we could sell"
  - Task completed → "Website is built, pushed to GitHub"
  - Evolution PR created → "I created a PR to improve myself"
  - Quality gate failed → "The output wasn't good enough, retrying"
  - Approval needed → "I need your OK to proceed"
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus

logger = logging.getLogger("agency.notifier")


class NotificationPriority(str, Enum):
    LOW = "low"           # Info: task completed, stats update
    NORMAL = "normal"     # Update: phase completed, PR created
    HIGH = "high"         # Action needed: approval required
    URGENT = "urgent"     # Problem: quality failure, error


class NotificationChannel(str, Enum):
    CONSOLE = "console"
    WEBHOOK = "webhook"
    FILE = "file"
    OPENCLAW = "openclaw"
    TELEGRAM = "telegram"
    EVENT = "event"


@dataclass
class Notification:
    """A message from Agency OS to the owner."""
    id: str = field(default_factory=lambda: uuid4().hex[:10])
    title: str = ""
    message: str = ""
    priority: NotificationPriority = NotificationPriority.NORMAL
    source: str = ""  # Which engine sent it
    category: str = ""  # opportunity | task | evolution | error | approval
    data: dict[str, Any] = field(default_factory=dict)
    channels_sent: list[str] = field(default_factory=list)
    read: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Notifier:
    """
    Agency OS outbound communication system.

    Sends notifications to the owner through all configured channels.
    Auto-detects available channels on init.
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._bus = get_event_bus()
        self._root = self.cfg.root
        self._inbox: list[Notification] = []
        self._channels: dict[str, bool] = {}
        self._webhook_url = os.getenv("AGENCY_WEBHOOK_URL", "")
        self._detect_channels()
        self._subscribe_to_events()

    def _detect_channels(self) -> None:
        """Auto-detect which outbound channels are available."""
        self._channels = {
            "console": True,  # Always available
            "file": True,     # Always available
            "event": True,    # Always available
            "telegram": bool(
                os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")
            ),
            "webhook": bool(self._webhook_url),
            "openclaw": bool(os.getenv("OPENCLAW_URL")),
        }
        active = [k for k, v in self._channels.items() if v]
        logger.info("Notifier channels: %s", active)

    def _subscribe_to_events(self) -> None:
        """Listen to internal events and auto-notify."""
        subscriptions = {
            "initiative.scan_complete": self._on_initiative_scan,
            "initiative.approved": self._on_initiative_approved,
            "project.completed": self._on_project_completed,
            "project.phase_complete": self._on_phase_complete,
            "evolution.cycle_complete": self._on_evolution_complete,
            "evolution.learned": self._on_evolution_learned,
            "orchestrator.task_complete": self._on_task_complete,
        }
        for event_type, handler in subscriptions.items():
            try:
                self._bus.subscribe(event_type, handler)
            except Exception:
                pass  # Event bus may not support all features

    # ── SEND ─────────────────────────────────────────────────

    def notify(
        self,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        source: str = "",
        category: str = "",
        data: dict[str, Any] | None = None,
        channels: list[str] | None = None,
    ) -> Notification:
        """
        Send a notification through all (or specified) channels.

        This is the main method — all others call this.
        """
        notif = Notification(
            title=title,
            message=message,
            priority=priority,
            source=source,
            category=category,
            data=data or {},
        )

        target_channels = channels or list(self._channels.keys())

        for ch in target_channels:
            if not self._channels.get(ch):
                continue

            try:
                if ch == "console":
                    self._send_console(notif)
                elif ch == "file":
                    self._send_file(notif)
                elif ch == "telegram":
                    self._send_telegram(notif)
                elif ch == "webhook":
                    self._send_webhook(notif)
                elif ch == "openclaw":
                    self._send_openclaw(notif)
                elif ch == "event":
                    self._send_event(notif)

                notif.channels_sent.append(ch)
            except Exception as e:
                logger.error("Channel %s failed: %s", ch, e)

        self._inbox.append(notif)
        return notif

    # ── Channel Implementations ──────────────────────────────

    def _send_console(self, notif: Notification) -> None:
        """Print to console with formatting."""
        icons = {
            NotificationPriority.LOW: "ℹ️ ",
            NotificationPriority.NORMAL: "📢",
            NotificationPriority.HIGH: "🔔",
            NotificationPriority.URGENT: "🚨",
        }
        icon = icons.get(notif.priority, "📢")
        print(f"\n{icon} [{notif.source}] {notif.title}")
        print(f"   {notif.message}")
        if notif.data:
            for k, v in list(notif.data.items())[:5]:
                print(f"   • {k}: {v}")

    def _send_file(self, notif: Notification) -> None:
        """Write notification to file inbox."""
        inbox_dir = self._root / "notifications"
        inbox_dir.mkdir(exist_ok=True)

        filename = f"{notif.created_at[:10]}_{notif.id}.json"
        filepath = inbox_dir / filename

        filepath.write_text(
            json.dumps({
                "id": notif.id,
                "title": notif.title,
                "message": notif.message,
                "priority": notif.priority.value,
                "source": notif.source,
                "category": notif.category,
                "data": notif.data,
                "read": notif.read,
                "created_at": notif.created_at,
            }, indent=2),
            encoding="utf-8",
        )

    def _send_webhook(self, notif: Notification) -> None:
        """POST to webhook URL (Slack, Discord, custom)."""
        if not self._webhook_url:
            return

        payload = {
            "text": f"*{notif.title}*\n{notif.message}",
            "title": notif.title,
            "message": notif.message,
            "priority": notif.priority.value,
            "source": notif.source,
            "category": notif.category,
            "data": notif.data,
        }

        try:
            with httpx.Client(timeout=10) as client:
                client.post(self._webhook_url, json=payload)
        except Exception as e:
            logger.debug("Webhook failed: %s", e)

    def _send_openclaw(self, notif: Notification) -> None:
        """Send via OpenClaw/ClawBot for chat-based notification."""
        try:
            from kernel.openclaw_bridge import get_openclaw
            oc = get_openclaw()
            if oc.is_available():
                oc.ask(
                    prompt=(
                        f"[AGENCY NOTIFICATION]\n"
                        f"Priority: {notif.priority.value}\n"
                        f"From: {notif.source}\n\n"
                        f"**{notif.title}**\n\n"
                        f"{notif.message}"
                    ),
                    system="You are relaying a notification from Agency OS to the user. Present it clearly.",
                    agent_id="notifier",
                )
        except Exception as e:
            logger.debug("OpenClaw notification failed: %s", e)

    def _send_telegram(self, notif: Notification) -> None:
        """Push directly to owner's Telegram via Bot API."""
        try:
            from kernel.openclaw_bridge import get_openclaw
            oc = get_openclaw()

            icons = {
                NotificationPriority.LOW: "ℹ️",
                NotificationPriority.NORMAL: "📢",
                NotificationPriority.HIGH: "🔔",
                NotificationPriority.URGENT: "🚨",
            }
            icon = icons.get(notif.priority, "📢")

            text = (
                f"{icon} *{notif.title}*\n\n"
                f"{notif.message}\n\n"
                f"_Source: {notif.source} | {notif.priority.value}_"
            )

            oc.send_telegram(text)
        except Exception as e:
            logger.debug("Telegram push failed: %s", e)

    def _send_event(self, notif: Notification) -> None:
        """Publish to internal event bus."""
        self._bus.publish_sync(Event(
            type=f"notification.{notif.category or 'general'}",
            source="notifier",
            payload={
                "id": notif.id,
                "title": notif.title,
                "priority": notif.priority.value,
            },
        ))

    # ── Pre-Built Notification Templates ─────────────────────

    def opportunity_found(self, count: int, total_value: str) -> Notification:
        """Notify: we found business opportunities."""
        return self.notify(
            title=f"🎯 Found {count} opportunities",
            message=f"The initiative engine identified {count} potential opportunities worth {total_value}. Awaiting your approval.",
            priority=NotificationPriority.HIGH,
            source="initiative_engine",
            category="opportunity",
            data={"count": count, "value": total_value},
        )

    def approval_needed(self, item: str, context: str) -> Notification:
        """Notify: we need owner approval."""
        return self.notify(
            title=f"🔔 Approval needed: {item}",
            message=f"Agency OS needs your approval to proceed.\n{context}",
            priority=NotificationPriority.HIGH,
            source="approval_gate",
            category="approval",
            data={"item": item},
        )

    def task_completed(self, studio: str, task: str, files: int = 0) -> Notification:
        """Notify: a task finished."""
        msg = f"The {studio} studio completed: {task[:200]}"
        if files:
            msg += f"\n{files} files created."
        return self.notify(
            title=f"✅ Task completed: {studio}",
            message=msg,
            priority=NotificationPriority.NORMAL,
            source=studio,
            category="task",
            data={"studio": studio, "files_created": files},
        )

    def evolution_pr(self, pr_url: str, items: int) -> Notification:
        """Notify: self-evolution created a PR."""
        return self.notify(
            title=f"🧬 Self-improvement PR created",
            message=f"I analyzed my own code and created {items} improvements.\nPR: {pr_url}",
            priority=NotificationPriority.NORMAL,
            source="self_evolution",
            category="evolution",
            data={"pr_url": pr_url, "items": items},
        )

    def error_alert(self, source: str, error: str) -> Notification:
        """Notify: something went wrong."""
        return self.notify(
            title=f"🚨 Error in {source}",
            message=f"Something went wrong: {error[:500]}",
            priority=NotificationPriority.URGENT,
            source=source,
            category="error",
            data={"error": error[:200]},
        )

    # ── Event Handlers (auto-trigger) ────────────────────────

    def _on_initiative_scan(self, event: Event) -> None:
        count = event.payload.get("opportunities_found", 0)
        if count > 0:
            self.opportunity_found(count, "pending valuation")

    def _on_initiative_approved(self, event: Event) -> None:
        opp = event.payload.get("opportunity", "Unknown")
        self.notify(
            title=f"✅ Initiative approved: {opp[:50]}",
            message=f"Building solution for: {opp}",
            priority=NotificationPriority.NORMAL,
            source="initiative_engine",
            category="task",
        )

    def _on_project_completed(self, event: Event) -> None:
        pid = event.payload.get("project_id", "")
        status = event.payload.get("status", "")
        phases = event.payload.get("phases_completed", 0)
        total = event.payload.get("total_phases", 0)
        self.task_completed(
            "project_manager",
            f"Project {pid}: {phases}/{total} phases ({status})",
        )

    def _on_phase_complete(self, event: Event) -> None:
        studio = event.payload.get("studio", "")
        phase = event.payload.get("phase", 0)
        self.notify(
            title=f"Phase {phase} complete: {studio}",
            message=f"Phase {phase} ({studio} studio) finished.",
            priority=NotificationPriority.LOW,
            source="project_manager",
            category="task",
        )

    def _on_evolution_complete(self, event: Event) -> None:
        skills = event.payload.get("skills_created", 0)
        agents = event.payload.get("agents_created", 0)
        if skills or agents:
            self.evolution_pr("pending", skills + agents)

    def _on_evolution_learned(self, event: Event) -> None:
        studio = event.payload.get("studio", "")
        improved = event.payload.get("improved", [])
        self.notify(
            title=f"📈 Learned from {studio} execution",
            message=f"Improved {len(improved)} files based on performance data.",
            priority=NotificationPriority.LOW,
            source="self_evolution",
            category="evolution",
        )

    def _on_task_complete(self, event: Event) -> None:
        studio = event.payload.get("studio", "")
        status = event.payload.get("status", "")
        if status == "failed":
            self.error_alert(studio, f"Task failed in {studio} studio")

    # ── Inbox Management ─────────────────────────────────────

    def get_inbox(self, unread_only: bool = False, limit: int = 20) -> list[dict]:
        """Get notification inbox."""
        items = self._inbox
        if unread_only:
            items = [n for n in items if not n.read]

        return [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message[:200],
                "priority": n.priority.value,
                "source": n.source,
                "category": n.category,
                "read": n.read,
                "channels": n.channels_sent,
                "created_at": n.created_at,
            }
            for n in items[-limit:]
        ]

    def mark_read(self, notification_id: str) -> bool:
        for n in self._inbox:
            if n.id == notification_id:
                n.read = True
                return True
        return False

    def get_stats(self) -> dict:
        total = len(self._inbox)
        unread = sum(1 for n in self._inbox if not n.read)
        by_priority = {}
        for n in self._inbox:
            by_priority[n.priority.value] = by_priority.get(n.priority.value, 0) + 1
        return {
            "total": total,
            "unread": unread,
            "by_priority": by_priority,
            "channels_active": [k for k, v in self._channels.items() if v],
        }


_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
    return _notifier
