#!/usr/bin/env python3
"""
Agency OS — OAuth Token Auto-Refresher

Monitors OpenClaw OAuth tokens and refreshes them before expiry.
Supports openai-codex (ChatGPT) and any OAuth provider in auth-profiles.json.

Called from the heartbeat every tick (1 min). Only acts when tokens
are within 48h of expiry.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("agency.token_refresher")

AUTH_PROFILES_PATH = (
    Path.home() / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
)
REFRESH_THRESHOLD_HOURS = 48  # Refresh when < 48h left


def _load_profiles() -> dict:
    """Load auth-profiles.json."""
    if not AUTH_PROFILES_PATH.exists():
        return {}
    return json.loads(AUTH_PROFILES_PATH.read_text())


def _save_profiles(data: dict) -> None:
    """Save auth-profiles.json."""
    AUTH_PROFILES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _refresh_openai_codex(profile: dict) -> dict | None:
    """
    Refresh an OpenAI Codex OAuth token using the refresh token.
    Returns updated profile dict or None on failure.
    """
    import httpx

    refresh_token = profile.get("refresh", "")
    if not refresh_token:
        logger.warning("No refresh token for openai-codex, skipping")
        return None

    try:
        # OpenAI uses standard OAuth2 token refresh
        resp = httpx.post(
            "https://auth.openai.com/oauth/token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": "app-openclaw",
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if resp.status_code != 200:
            # Try alternative endpoint
            resp = httpx.post(
                "https://token.oai.azure.com/oidc/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=30,
            )

        if resp.status_code == 200:
            data = resp.json()
            new_access = data.get("access_token", "")
            new_refresh = data.get("refresh_token", refresh_token)
            expires_in = data.get("expires_in", 864000)  # default 10 days

            if new_access:
                profile["access"] = new_access
                profile["refresh"] = new_refresh
                profile["expires"] = int((time.time() + expires_in) * 1000)
                logger.info(
                    "OpenAI Codex token refreshed. New expiry: %.1f days",
                    expires_in / 86400,
                )
                return profile
            else:
                logger.warning("Token refresh response had no access_token")
        else:
            logger.warning(
                "Token refresh failed: %d %s",
                resp.status_code,
                resp.text[:200],
            )
    except Exception as e:
        logger.error("Token refresh error: %s", e)

    return None


# Provider refresh handlers
REFRESH_HANDLERS = {
    "openai-codex": _refresh_openai_codex,
}


def check_and_refresh() -> dict:
    """
    Check all OAuth tokens and refresh any that are near expiry.
    Returns summary of actions taken.
    """
    result = {"checked": 0, "refreshed": 0, "failed": 0, "skipped": 0}

    data = _load_profiles()
    profiles = data.get("profiles", {})
    changed = False

    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue

        # Only process OAuth profiles
        if profile.get("type") != "oauth":
            continue

        result["checked"] += 1
        provider = profile.get("provider", "")
        expires_ms = profile.get("expires", 0)

        if not expires_ms:
            result["skipped"] += 1
            continue

        now_ms = int(time.time() * 1000)
        remaining_ms = expires_ms - now_ms
        remaining_hours = remaining_ms / (1000 * 3600)

        if remaining_hours > REFRESH_THRESHOLD_HOURS:
            logger.debug("Token %s OK (%.1f hours remaining)", name, remaining_hours)
            result["skipped"] += 1
            continue

        logger.info(
            "Token %s near expiry (%.1f hours). Attempting refresh...",
            name,
            remaining_hours,
        )

        handler = REFRESH_HANDLERS.get(provider)
        if not handler:
            # Try CLI fallback
            logger.info(
                "No handler for provider %s. Try: openclaw models auth setup-token",
                provider,
            )
            result["failed"] += 1
            continue

        updated = handler(profile)
        if updated:
            profiles[name] = updated
            changed = True
            result["refreshed"] += 1
        else:
            # Notify the user via Telegram
            _notify_token_expiring(name, remaining_hours)
            result["failed"] += 1

    if changed:
        data["profiles"] = profiles
        _save_profiles(data)
        logger.info("Auth profiles updated with refreshed tokens")

    return result


def _notify_token_expiring(profile_name: str, hours_remaining: float) -> None:
    """Send Telegram alert when token refresh fails."""
    try:
        from kernel.notifier import Notifier, NotificationPriority
        from kernel.config import get_config

        cfg = get_config()
        _es = cfg.language == "es"

        notifier = Notifier()
        notifier.notify(
            title="⚠️ Token OAuth por expirar" if _es else "⚠️ OAuth Token Expiring",
            message=(
                f"**{profile_name}** — "
                + (
                    f"quedan {hours_remaining:.0f} horas.\n"
                    if _es
                    else f"{hours_remaining:.0f} hours remaining.\n"
                )
                + (
                    "No se pudo renovar automáticamente.\n"
                    if _es
                    else "Auto-refresh failed.\n"
                )
                + ("Ejecuta manualmente:\n" if _es else "Run manually:\n")
                + "`openclaw models auth add`"
            ),
            priority=NotificationPriority.HIGH,
            source="token_refresher",
            category="warning",
        )
    except Exception as e:
        logger.error("Failed to notify about expiring token: %s", e)
