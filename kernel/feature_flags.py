#!/usr/bin/env python3
"""
Agency OS v4.0 — Feature Flags

Simple but effective feature flag system.
Enable/disable studios, features, and experimental capabilities
without code changes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from kernel.config import get_config

logger = logging.getLogger("agency.flags")

# Default feature flags
DEFAULT_FLAGS: dict[str, dict] = {
    # Studios
    "studio.dev": {"enabled": True, "description": "Development studio"},
    "studio.leadops": {"enabled": True, "description": "Lead operations studio"},
    "studio.marketing": {"enabled": True, "description": "Marketing studio"},
    "studio.sales": {"enabled": True, "description": "Sales studio"},
    "studio.analytics": {"enabled": True, "description": "Analytics studio"},
    "studio.creative": {"enabled": True, "description": "Creative studio"},
    "studio.abm": {"enabled": True, "description": "Account-based marketing studio"},
    # Features
    "feature.guardrails": {"enabled": True, "description": "Safety guardrails"},
    "feature.audit_trail": {"enabled": True, "description": "AI call logging"},
    "feature.telemetry": {"enabled": True, "description": "Pipeline tracing"},
    "feature.cross_studio": {"enabled": True, "description": "Cross-studio chains"},
    "feature.job_queue": {"enabled": True, "description": "Background job processing"},
    "feature.quality_gates": {"enabled": True, "description": "Pipeline quality gates"},
    "feature.crew_engine": {
        "enabled": True,
        "description": "Intelligent crew assembly",
    },
    "feature.plugins": {"enabled": True, "description": "Dynamic plugin system"},
    "feature.api_server": {"enabled": True, "description": "REST API server"},
    # Experimental
    "experimental.auto_chain": {
        "enabled": False,
        "description": "Auto-trigger cross-studio chains",
    },
    "experimental.learning": {
        "enabled": False,
        "description": "Agent performance learning",
    },
    "experimental.streaming": {
        "enabled": False,
        "description": "Streaming API responses",
    },
    # Provider preferences
    "provider.prefer_local": {
        "enabled": True,
        "description": "Prefer Ollama/LM Studio over cloud",
    },
    "provider.fallback_cloud": {
        "enabled": True,
        "description": "Fall back to cloud if local fails",
    },
}


class FeatureFlags:
    """
    Feature flag system.

    Flags can be set via:
    1. Default values (code)
    2. flags.json file (persistent)
    3. Environment variables AGENCY_FLAG_<NAME>=true/false
    4. Runtime API (temporary, in-memory)
    """

    def __init__(self) -> None:
        self._flags: dict[str, dict] = {}
        self._overrides: dict[str, bool] = {}  # Runtime overrides
        self._load()

    def _load(self) -> None:
        """Load flags from defaults, file, and environment."""
        # 1. Defaults
        self._flags = {k: dict(v) for k, v in DEFAULT_FLAGS.items()}

        # 2. File overrides
        cfg = get_config()
        flags_path = Path(cfg.root) / "configs" / "flags.json"
        if flags_path.exists():
            try:
                with open(flags_path) as f:
                    file_flags = json.load(f)
                for key, val in file_flags.items():
                    if key in self._flags:
                        if isinstance(val, bool):
                            self._flags[key]["enabled"] = val
                        elif isinstance(val, dict):
                            self._flags[key].update(val)
                logger.info(
                    "Loaded %d flag overrides from %s", len(file_flags), flags_path
                )
            except Exception as e:
                logger.warning("Failed to load flags.json: %s", e)

        # 3. Environment variable overrides
        import os

        for key in self._flags:
            env_name = f"AGENCY_FLAG_{key.replace('.', '_').upper()}"
            env_val = os.getenv(env_name)
            if env_val is not None:
                self._flags[key]["enabled"] = env_val.lower() in ("true", "1", "yes")

    def is_enabled(self, flag: str) -> bool:
        """Check if a flag is enabled."""
        # Runtime overrides take priority
        if flag in self._overrides:
            return self._overrides[flag]

        entry = self._flags.get(flag)
        if entry is None:
            return False
        return entry.get("enabled", False)

    def set_flag(self, flag: str, enabled: bool) -> None:
        """Set a runtime flag override."""
        self._overrides[flag] = enabled
        logger.info("Flag %s set to %s (runtime)", flag, enabled)

    def reset_flag(self, flag: str) -> None:
        """Remove runtime override, revert to config."""
        self._overrides.pop(flag, None)

    def get_all(self) -> dict[str, dict]:
        """Get all flags with current state."""
        result = {}
        for key, cfg in self._flags.items():
            effective = self._overrides.get(key, cfg.get("enabled", False))
            result[key] = {
                "enabled": effective,
                "description": cfg.get("description", ""),
                "overridden": key in self._overrides,
            }
        return result

    def save(self) -> None:
        """Save current state to flags.json."""
        cfg = get_config()
        flags_path = Path(cfg.root) / "configs" / "flags.json"
        flags_path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v["enabled"] for k, v in self._flags.items()}
        data.update(self._overrides)
        with open(flags_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Flags saved to %s", flags_path)

    def get_enabled_studios(self) -> list[str]:
        """Get list of enabled studio names."""
        return [
            key.split(".")[1]
            for key in self._flags
            if key.startswith("studio.") and self.is_enabled(key)
        ]

    def get_enabled_features(self) -> list[str]:
        """Get list of enabled feature names."""
        return [
            key.split(".")[1]
            for key in self._flags
            if key.startswith("feature.") and self.is_enabled(key)
        ]


_flags: FeatureFlags | None = None


def get_feature_flags() -> FeatureFlags:
    global _flags
    if _flags is None:
        _flags = FeatureFlags()
    return _flags
