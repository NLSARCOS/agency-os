#!/usr/bin/env python3
"""
Agency OS — Centralized Configuration

Zero hardcoded paths. Everything is relative or env-driven.
Works on Linux AND macOS out of the box.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

import yaml  # type: ignore
from dotenv import load_dotenv


def _find_root() -> Path:
    """Find the Agency OS root directory. Priority:
    1. AGENCY_OS_ROOT env var
    2. Walk up from this file to find pyproject.toml
    """
    env_root = os.environ.get("AGENCY_OS_ROOT")
    if env_root:
        return Path(env_root).resolve()

    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current.parent


ROOT = _find_root()

# Load .env from root
load_dotenv(ROOT / ".env", override=False)


class Config:
    """Immutable configuration singleton for Agency OS."""

    _instance: Config | None = None

    def __new__(cls) -> Config:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False  # type: ignore
        return cls._instance

    def __init__(self) -> None:
        if self._loaded:  # type: ignore
            return
        self._loaded = True

        self.root = ROOT
        self.platform = platform.system().lower()  # 'linux' or 'darwin'

        # Core directories
        self.kernel_dir = ROOT / "kernel"
        self.studios_dir = ROOT / "studios"
        self.jobs_dir = ROOT / "jobs"
        self.configs_dir = ROOT / "configs"
        self.reports_dir = ROOT / "reports"
        self.data_dir = ROOT / "data"
        self.logs_dir = ROOT / "logs"

        # Ensure runtime dirs exist
        for d in [self.data_dir, self.logs_dir, self.reports_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Database
        self.db_path = self.data_dir / "agency.db"

        # Load YAML configs
        self.routing = self._load_yaml("routing.yaml")
        self.models = self._load_yaml("models.yaml")
        self.schedule = self._load_yaml("schedule.yaml")

        # API Keys (from env)
        self.api_keys = {
            "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
            "openai": os.getenv("OPENAI_API_KEY", ""),
            "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
            "gemini": os.getenv("GEMINI_API_KEY", ""),
            "github": os.getenv("GITHUB_TOKEN", ""),
            "brave": os.getenv("BRAVE_API_KEY", ""),
            "perplexity": os.getenv("PERPLEXITY_API_KEY", ""),
        }

        # Studio names
        self.studio_names = [
            "dev",
            "marketing",
            "sales",
            "leadops",
            "abm",
            "analytics",
            "creative",
        ]

        # Response language (e.g. 'en', 'es', 'pt', 'fr')
        self.language = os.getenv("AGENCY_LANGUAGE", "en").strip().lower()

    @property
    def language_instruction(self) -> str:
        """System prompt fragment to enforce response language."""
        lang_names = {
            "en": "English",
            "es": "Spanish",
            "pt": "Portuguese",
            "fr": "French",
            "de": "German",
            "it": "Italian",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
            "ar": "Arabic",
            "ru": "Russian",
            "tr": "Turkish",
        }
        name = lang_names.get(self.language, self.language)
        if self.language == "en":
            return ""
        return f"IMPORTANT: Always respond in {name} ({self.language})."

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        path = self.configs_dir / filename
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def has_api_key(self, provider: str) -> bool:
        return bool(self.api_keys.get(provider))

    @property
    def available_providers(self) -> list[str]:
        return [k for k, v in self.api_keys.items() if v]

    def __repr__(self) -> str:
        return (
            f"Config(root={self.root}, platform={self.platform}, "
            f"providers={self.available_providers})"
        )


# Convenience function
def get_config() -> Config:
    return Config()
