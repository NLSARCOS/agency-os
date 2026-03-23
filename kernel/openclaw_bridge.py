#!/usr/bin/env python3
"""
Agency OS v3.0 — OpenClaw Bridge

Integration layer with OpenClaw gateway for:
- Multi-model routing through the gateway
- Session-isolated agent contexts
- Multi-channel message handling (WhatsApp, Telegram, Discord, Slack, CLI)
- Hybrid intelligence (complex → premium, simple → free/local)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from kernel.config import get_config

logger = logging.getLogger("agency.openclaw")


@dataclass
class OpenClawConfig:
    """OpenClaw connection configuration."""
    gateway_url: str = "http://localhost:3000"
    api_key: str = ""
    default_agent: str = "main"
    timeout: float = 120.0
    max_retries: int = 2


@dataclass
class ChatMessage:
    """A message in OpenClaw format."""
    role: str  # system, user, assistant
    content: str
    name: str = ""
    tool_calls: list[dict] | None = None
    tool_call_id: str = ""


@dataclass
class OpenClawResponse:
    """Response from OpenClaw gateway."""
    content: str
    model: str = ""
    provider: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0
    success: bool = True
    error: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    session_id: str = ""
    raw: dict = field(default_factory=dict)


class OpenClawBridge:
    """
    Bridge between Agency OS and OpenClaw gateway.

    OpenClaw handles:
    - Model selection and routing (hybrid intelligence)
    - Session management and memory
    - Multi-channel input/output
    - Tool sandboxing
    - Authentication

    Agency OS uses it as the unified AI backbone.
    """

    def __init__(self, config: OpenClawConfig | None = None) -> None:
        cfg = get_config()
        self._config = config or OpenClawConfig(
            gateway_url=os.environ.get(
                "OPENCLAW_URL", "http://localhost:3000"
            ),
            api_key=os.environ.get(
                "OPENCLAW_API_KEY", ""
            ),
        )
        self._client = httpx.Client(timeout=self._config.timeout)
        self._sessions: dict[str, str] = {}  # agent_id → session_id
        self._healthy = False
        self._last_health_check = 0.0
        self._gateway_has_rest = True  # assume REST until proven otherwise

    # ── Health ────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if OpenClaw gateway is reachable."""
        now = time.monotonic()
        if now - self._last_health_check < 30:
            return self._healthy
        try:
            resp = self._client.get(
                f"{self._config.gateway_url}/health",
                timeout=5.0,
            )
            self._healthy = resp.status_code == 200
        except Exception:
            self._healthy = False
        self._last_health_check = now
        return self._healthy

    # ── Chat Completion ───────────────────────────────────────

    def chat(
        self,
        messages: list[ChatMessage],
        model: str = "",
        system: str = "",
        agent_id: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> OpenClawResponse:
        """
        Send a chat completion request through OpenClaw.

        Strategy:
        1. If gateway has REST API → use /v1/chat/completions
        2. If gateway is WebSocket-only (404) → auto-fallback to direct API
        3. If gateway is down → auto-fallback to direct API
        """
        # Fast path: gateway is WebSocket-only, skip HTTP attempt
        if not self._gateway_has_rest or not self.is_available():
            if not self.is_available():
                logger.debug("OpenClaw gateway down, using direct API")
            return self._direct_fallback(messages, model, system)

        # Build request payload
        msg_list = []
        if system:
            msg_list.append({"role": "system", "content": system})
        for m in messages:
            msg_dict: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.name:
                msg_dict["name"] = m.name
            if m.tool_calls:
                msg_dict["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg_dict["tool_call_id"] = m.tool_call_id
            msg_list.append(msg_dict)

        body: dict[str, Any] = {
            "messages": msg_list,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if model:
            body["model"] = model
        if tools:
            body["tools"] = tools

        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        if agent_id:
            headers["X-Agent-ID"] = agent_id
            session_id = self._sessions.get(agent_id, "")
            if session_id:
                headers["X-Session-ID"] = session_id

        start = time.monotonic()
        try:
            resp = self._client.post(
                f"{self._config.gateway_url}/v1/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            latency = (time.monotonic() - start) * 1000

            # Extract response
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            usage = data.get("usage", {})

            # Save session if returned
            new_session = resp.headers.get("X-Session-ID", "")
            if new_session and agent_id:
                self._sessions[agent_id] = new_session

            return OpenClawResponse(
                content=message.get("content", ""),
                model=data.get("model", model),
                provider=data.get("provider", "openclaw"),
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                latency_ms=latency,
                tool_calls=message.get("tool_calls", []),
                session_id=new_session,
                raw=data,
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Gateway is WebSocket-only; remember and fall back
                self._gateway_has_rest = False
                logger.info(
                    "OpenClaw gateway is WebSocket-only (no /v1/chat/completions). "
                    "Switching to direct API for all future calls."
                )
                return self._direct_fallback(messages, model, system)
            logger.error("OpenClaw HTTP error: %s", e)
            return OpenClawResponse(
                content="", success=False,
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            logger.error("OpenClaw error: %s", e)
            return OpenClawResponse(
                content="", success=False, error=str(e),
                latency_ms=(time.monotonic() - start) * 1000,
            )

    # ── Convenience Methods ───────────────────────────────────

    def ask(
        self,
        prompt: str,
        system: str = "",
        model: str = "",
        agent_id: str = "",
    ) -> str:
        """Simple ask → answer shortcut."""
        # Inject configured language into system prompt
        cfg = get_config()
        lang = cfg.language_instruction
        if lang and system:
            system = f"{system}\n{lang}"
        elif lang:
            system = lang

        resp = self.chat(
            messages=[ChatMessage(role="user", content=prompt)],
            system=system,
            model=model,
            agent_id=agent_id,
        )
        if not resp.success:
            logger.error("Ask failed: %s", resp.error)
            return ""
        return resp.content

    def ask_with_tools(
        self,
        prompt: str,
        tools: list[dict],
        system: str = "",
        model: str = "",
        agent_id: str = "",
    ) -> OpenClawResponse:
        """Ask with tool-use support (function calling)."""
        return self.chat(
            messages=[ChatMessage(role="user", content=prompt)],
            system=system,
            model=model,
            agent_id=agent_id,
            tools=tools,
        )

    # ── Session Management ────────────────────────────────────

    def get_session(self, agent_id: str) -> str:
        return self._sessions.get(agent_id, "")

    def clear_session(self, agent_id: str) -> None:
        self._sessions.pop(agent_id, None)

    def clear_all_sessions(self) -> None:
        self._sessions.clear()

    # ── Model Hints ───────────────────────────────────────────

    @staticmethod
    def model_for_complexity(complexity: str) -> str:
        """Suggest a model based on task complexity."""
        models = {
            "simple": "",  # Let OpenClaw pick free/fast
            "medium": "openrouter/stepfun/step-3.5-flash:free",
            "complex": "claude-sonnet-4-20250514",
            "critical": "claude-sonnet-4-20250514",
            "code": "claude-sonnet-4-20250514",
            "creative": "openrouter/stepfun/step-3.5-flash:free",
        }
        return models.get(complexity, "")

    # ── Fallback ──────────────────────────────────────────────

    def _direct_fallback(
        self,
        messages: list[ChatMessage],
        model: str,
        system: str,
    ) -> OpenClawResponse:
        """
        Fallback when the gateway REST endpoint is unavailable.
        
        Strategy:
        1. Try `openclaw agent` CLI (uses gateway WebSocket + OAuth models)
        2. If CLI fails, use model_router direct API calls
        """
        prompt = messages[-1].content if messages else ""
        
        # Strategy 1: Use OpenClaw CLI (leverages OAuth, all configured models)
        try:
            return self._call_via_cli(prompt, system)
        except Exception as e:
            logger.debug("OpenClaw CLI fallback failed: %s — trying direct API", e)
        
        # Strategy 2: Direct API calls via model_router
        from kernel.model_router import get_model_router
        router = get_model_router()
        resp = router.call_model_sync(prompt=prompt, system=system)
        return OpenClawResponse(
            content=resp.content,
            model=resp.model,
            provider=resp.provider,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            latency_ms=resp.latency_ms,
            success=resp.success,
            error=resp.error,
        )

    def _call_via_cli(self, prompt: str, system: str = "") -> OpenClawResponse:
        """
        Route through `openclaw agent` CLI (WebSocket → gateway models + OAuth).
        
        This leverages OpenClaw's full model stack including OAuth-connected
        providers like openai-codex that aren't accessible via REST.
        """
        import subprocess
        
        cmd = ["openclaw", "agent", "--agent", self._config.default_agent, "--json", "--message", prompt]
        
        start = time.monotonic()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        latency = (time.monotonic() - start) * 1000
        
        if result.returncode != 0:
            raise RuntimeError(f"openclaw agent failed (exit {result.returncode}): {result.stderr[:200]}")
        
        # Parse JSON output
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # If not valid JSON, the raw stdout is the response text
            return OpenClawResponse(
                content=result.stdout.strip(),
                model="openclaw-cli",
                provider="openclaw",
                latency_ms=latency,
            )
        
        # Extract from structured JSON response
        content = (
            data.get("result", {}).get("content", "")
            or data.get("content", "")
            or data.get("message", "")
            or result.stdout.strip()
        )
        
        return OpenClawResponse(
            content=content,
            model=data.get("model", "openclaw-cli"),
            provider="openclaw",
            tokens_in=data.get("usage", {}).get("prompt_tokens", 0),
            tokens_out=data.get("usage", {}).get("completion_tokens", 0),
            latency_ms=latency,
        )

    # ── Proactive Messaging (Agency → Owner) ─────────────────

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape HTML special chars for Telegram HTML parse_mode."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def send_telegram(
        self,
        message: str,
        chat_id: str = "",
        parse_mode: str = "HTML",
    ) -> bool:
        """
        Send a proactive message to the owner via Telegram Bot API.

        This is how the agency reaches out when it needs something:
        - "Found 5 opportunities, need your approval"
        - "Website built, pushed to GitHub"
        - "I improved myself, here's the PR"

        Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
        """
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        target_chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")

        if not bot_token or not target_chat:
            logger.debug("Telegram not configured (no token or chat_id)")
            return False

        # Telegram limit: 4096 chars. Split into chunks if needed.
        MAX_LEN = 4000  # leave margin
        chunks = []
        if len(message) <= MAX_LEN:
            chunks = [message]
        else:
            remaining = message
            while remaining:
                if len(remaining) <= MAX_LEN:
                    chunks.append(remaining)
                    break
                # Split at nearest newline before MAX_LEN
                split_at = remaining.rfind("\n", 0, MAX_LEN)
                if split_at <= 0:
                    split_at = MAX_LEN
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:].lstrip("\n")

        try:
            for i, chunk in enumerate(chunks):
                resp = self._client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": target_chat,
                        "text": chunk,
                        "parse_mode": parse_mode,
                    },
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.warning("Telegram chunk %d failed: %s", i, resp.text[:200])
                    return False
            logger.info("Telegram message sent (%d chunk(s)) to %s", len(chunks), target_chat)
            return True
        except Exception as e:
            logger.error("Telegram send error: %s", e)
            return False

    def send_to_channel(
        self,
        channel: str,
        message: str,
    ) -> bool:
        """
        Send a proactive message through a specific channel.

        Supported channels:
        - telegram: Direct Telegram Bot API push
        - openclaw: Send via OpenClaw gateway (if it has /v1/messages endpoint)
        - webhook: POST to configured webhook URL
        """
        if channel == "telegram":
            return self.send_telegram(message)

        elif channel == "openclaw":
            # Try OpenClaw messaging endpoint
            try:
                headers = {"Content-Type": "application/json"}
                if self._config.api_key:
                    headers["Authorization"] = f"Bearer {self._config.api_key}"

                resp = self._client.post(
                    f"{self._config.gateway_url}/v1/messages",
                    headers=headers,
                    json={
                        "content": message,
                        "source": "agency-os",
                        "channel": "owner",
                    },
                    timeout=10,
                )
                return resp.status_code in (200, 201)
            except Exception as e:
                logger.debug("OpenClaw messaging failed: %s", e)
                # Fallback: try Telegram
                return self.send_telegram(message)

        elif channel == "webhook":
            webhook_url = os.environ.get("AGENCY_WEBHOOK_URL", "")
            if not webhook_url:
                return False
            try:
                resp = self._client.post(
                    webhook_url,
                    json={"text": message, "source": "agency-os"},
                    timeout=10,
                )
                return resp.status_code in (200, 201, 204)
            except Exception as e:
                logger.debug("Webhook failed: %s", e)
                return False

        return False

    def notify_owner(self, message: str) -> bool:
        """
        Send a message to the owner through the BEST available channel.

        Priority order:
        1. Telegram (direct, real-time, always works)
        2. OpenClaw messaging (if available)
        3. Webhook (Slack/Discord)
        """
        # Try channels in priority order
        for channel in ["telegram", "openclaw", "webhook"]:
            if self.send_to_channel(channel, message):
                return True
        return False

    # ── Mission Result Callback ──────────────────────────────

    def report_mission_result(
        self,
        mission_id: int,
        name: str,
        status: str,
        studio: str = "",
        output_summary: str = "",
        artifacts: list[str] | None = None,
        duration_ms: float = 0,
        error: str = "",
    ) -> bool:
        """
        Report a mission result back to OpenClaw.

        This is the KEY feedback mechanism:
        - OpenClaw sends task → Agency OS executes → THIS reports back
        - OpenClaw can then inform the user and trigger follow-up actions

        Sends via:
        1. OpenClaw /v1/messages (structured, preferred)
        2. Telegram (fallback)
        """
        success = status in ("done", "completed")
        icon = "✅" if success else "❌"

        # Build structured result
        result_payload = {
            "type": "mission_result",
            "source": "agency-os",
            "mission_id": mission_id,
            "name": name,
            "status": status,
            "studio": studio,
            "success": success,
            "output_summary": output_summary[:2000],
            "artifacts": artifacts or [],
            "duration_ms": round(duration_ms, 1),
            "error": error[:500],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        # Human-readable message (i18n) — compact for Telegram
        _es = os.environ.get("AGENCY_LANGUAGE", "en") == "es"
        esc = self._escape_html
        msg_lines = [
            f"{icon} <b>#{mission_id} | {esc(studio.upper())}</b>",
            f"{esc(name[:60])}",
        ]
        if success:
            msg_lines.append(f"⏱️ {duration_ms:.0f}ms")
            if artifacts:
                msg_lines.append(f"📦 {len(artifacts)} {'archivos' if _es else 'files'}")
            if output_summary:
                # Compact: first 300 chars only
                short = output_summary[:300].replace('\n', ' ').strip()
                if len(output_summary) > 300:
                    short += "…"
                msg_lines.append(f"📄 {esc(short)}")
        else:
            msg_lines.append(f"💥 {esc(error[:150])}")

        message = "\n".join(line for line in msg_lines if line)

        # Try OpenClaw structured endpoint with retry + exponential backoff
        def _try_send_to_openclaw() -> bool:
            """Send result to OpenClaw with up to 3 retries."""
            import time as _time
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if not self.is_available():
                        break
                    headers = {"Content-Type": "application/json"}
                    if self._config.api_key:
                        headers["Authorization"] = f"Bearer {self._config.api_key}"

                    resp = self._client.post(
                        f"{self._config.gateway_url}/v1/messages",
                        headers=headers,
                        json=result_payload,
                        timeout=10,
                    )
                    if resp.status_code in (200, 201):
                        logger.info(
                            "Mission #%d result reported to OpenClaw (attempt %d)",
                            mission_id,
                            attempt + 1,
                        )
                        return True
                    logger.debug(
                        "OpenClaw callback attempt %d/%d failed: %s",
                        attempt + 1,
                        max_retries,
                        resp.status_code,
                    )
                except Exception as e:
                    logger.debug(
                        "OpenClaw callback attempt %d/%d error: %s",
                        attempt + 1,
                        max_retries,
                        e,
                    )
                if attempt < max_retries - 1:
                    _time.sleep(2 ** (attempt + 1))  # 2s, 4s backoff
            return False

        # Try OpenClaw first (non-blocking via thread for retries)
        import threading
        def _callback_with_fallback():
            if not _try_send_to_openclaw():
                self.notify_owner(message)

        thread = threading.Thread(
            target=_callback_with_fallback, daemon=True, name="callback-retry"
        )
        thread.start()
        return True

    def report_objective_complete(
        self,
        objective: str,
        total: int,
        succeeded: int,
        report_file: str = "",
        studios: list[str] | None = None,
    ) -> bool:
        """
        Report that an ENTIRE objective (all waves) is complete.
        This is the consolidated report callback.
        """
        failed = total - succeeded
        icon = "🎉" if failed == 0 else "⚠️"

        result_payload = {
            "type": "objective_complete",
            "source": "agency-os",
            "objective": objective[:200],
            "total_missions": total,
            "succeeded": succeeded,
            "failed": failed,
            "studios": studios or [],
            "report_file": report_file,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        _es = os.environ.get("AGENCY_LANGUAGE", "en") == "es"
        message = (
            f"{icon} **{'Objetivo Completado' if _es else 'Objective Complete'}**\n"
            f"📋 {objective[:100]}\n"
            f"✅ {succeeded}/{total} {'misiones exitosas' if _es else 'missions succeeded'}\n"
            + (f"❌ {failed} {'fallaron' if _es else 'failed'}\n" if failed else "")
            + (f"🏢 Studios: {', '.join(s.upper() for s in (studios or []))}\n" if studios else "")
            + (f"📄 {'Reporte' if _es else 'Report'}: `{report_file}`" if report_file else "")
        )

        # Try OpenClaw first
        try:
            if self.is_available():
                headers = {"Content-Type": "application/json"}
                if self._config.api_key:
                    headers["Authorization"] = f"Bearer {self._config.api_key}"

                resp = self._client.post(
                    f"{self._config.gateway_url}/v1/messages",
                    headers=headers,
                    json=result_payload,
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    logger.info("Objective complete reported to OpenClaw")
                    return True
        except Exception as e:
            logger.debug("OpenClaw objective callback failed: %s", e)

        return self.notify_owner(message)

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> dict:
        telegram_ok = bool(
            os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")
        )
        return {
            "gateway_url": self._config.gateway_url,
            "available": self.is_available(),
            "active_sessions": len(self._sessions),
            "sessions": dict(self._sessions),
            "telegram_configured": telegram_ok,
            "webhook_configured": bool(os.environ.get("AGENCY_WEBHOOK_URL")),
        }

    def close(self) -> None:
        self._client.close()


_openclaw: OpenClawBridge | None = None


def get_openclaw() -> OpenClawBridge:
    """Singleton — preserves sessions, health checks, and HTTP connection pool."""
    global _openclaw
    if _openclaw is None:
        _openclaw = OpenClawBridge()
    return _openclaw
