#!/usr/bin/env python3
"""
Agency OS v4.0 — Provider Detector

Auto-detects local AI providers:
- OpenClaw Gateway
- Ollama (local models like llama3, mistral, codestral)
- LM Studio (local OpenAI-compatible server)
- Cloud providers (OpenAI, Anthropic, Google, OpenRouter)

Used by setup.sh and by runtime to auto-configure model routing.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("agency.providers")


@dataclass
class ProviderStatus:
    """Status of a detected provider."""
    name: str
    installed: bool = False
    running: bool = False
    url: str = ""
    version: str = ""
    models: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class ProviderDetector:
    """
    Auto-detect all available AI providers.

    Checks for local providers (OpenClaw, Ollama, LM Studio)
    and cloud providers (via API keys in environment).
    """

    def __init__(self) -> None:
        self._results: dict[str, ProviderStatus] = {}

    def detect_all(self) -> dict[str, ProviderStatus]:
        """Run full detection scan."""
        self._results = {}
        self._detect_openclaw()
        self._detect_ollama()
        self._detect_lmstudio()
        self._detect_cloud_providers()
        return self._results

    # ── OpenClaw ──────────────────────────────────────────────

    def _detect_openclaw(self) -> None:
        status = ProviderStatus(name="openclaw")
        try:
            # Check binary
            if shutil.which("openclaw"):
                status.installed = True
                try:
                    ver = subprocess.run(
                        ["openclaw", "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    status.version = ver.stdout.strip().split("\n")[0]
                except Exception:
                    status.version = "installed"

            # Check config
            config_path = Path.home() / ".openclaw" / "openclaw.json"
            if config_path.exists():
                with open(config_path) as f:
                    cfg = json.load(f)
                port = cfg.get("gateway", {}).get("port", 3000)
                status.url = f"http://localhost:{port}"
                token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
                status.config = {"port": port, "has_token": bool(token)}

                # Extract models
                providers = cfg.get("models", {}).get("providers", {})
                for prov, pcfg in providers.items():
                    for m in pcfg.get("models", []):
                        status.models.append(f"{prov}/{m.get('id', 'unknown')}")

            # Check if running
            if status.url:
                status.running = self._check_http(status.url + "/health")
            elif status.installed:
                status.url = "http://localhost:3000"
                status.running = self._check_http(status.url + "/health")

        except Exception as e:
            status.error = str(e)

        self._results["openclaw"] = status

    # ── Ollama ────────────────────────────────────────────────

    def _detect_ollama(self) -> None:
        status = ProviderStatus(name="ollama")
        try:
            # Check binary
            if shutil.which("ollama"):
                status.installed = True
                try:
                    ver = subprocess.run(
                        ["ollama", "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    status.version = ver.stdout.strip()
                except Exception:
                    status.version = "installed"

            # Default Ollama URL
            ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            status.url = ollama_url

            # Check if running
            status.running = self._check_http(f"{ollama_url}/api/tags")

            # Get models if running
            if status.running:
                try:
                    import httpx
                    resp = httpx.get(f"{ollama_url}/api/tags", timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        status.models = [
                            m.get("name", "unknown")
                            for m in data.get("models", [])
                        ]
                except Exception:
                    # Try without httpx
                    try:
                        import urllib.request
                        req = urllib.request.urlopen(
                            f"{ollama_url}/api/tags", timeout=5
                        )
                        data = json.loads(req.read())
                        status.models = [
                            m.get("name", "unknown")
                            for m in data.get("models", [])
                        ]
                    except Exception:
                        pass

            status.config = {
                "host": ollama_url,
                "model_count": len(status.models),
            }

        except Exception as e:
            status.error = str(e)

        self._results["ollama"] = status

    # ── LM Studio ─────────────────────────────────────────────

    def _detect_lmstudio(self) -> None:
        status = ProviderStatus(name="lmstudio")
        try:
            # Check common paths
            lms_paths = [
                Path.home() / ".cache" / "lm-studio",
                Path.home() / "lm-studio",
                Path.home() / ".lmstudio",
                Path("/usr/share/lm-studio"),
            ]
            for p in lms_paths:
                if p.exists():
                    status.installed = True
                    break

            # Also check if lms CLI exists
            if shutil.which("lms"):
                status.installed = True
                try:
                    ver = subprocess.run(
                        ["lms", "version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    status.version = ver.stdout.strip()
                except Exception:
                    status.version = "installed"

            # Default LM Studio API URL (OpenAI-compatible)
            lms_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234")
            status.url = lms_url

            # Check if server is running
            status.running = self._check_http(f"{lms_url}/v1/models")

            # Get models if running
            if status.running:
                try:
                    import httpx
                    resp = httpx.get(f"{lms_url}/v1/models", timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        status.models = [
                            m.get("id", "unknown")
                            for m in data.get("data", [])
                        ]
                except Exception:
                    try:
                        import urllib.request
                        req = urllib.request.urlopen(
                            f"{lms_url}/v1/models", timeout=5
                        )
                        data = json.loads(req.read())
                        status.models = [
                            m.get("id", "unknown")
                            for m in data.get("data", [])
                        ]
                    except Exception:
                        pass

            status.config = {
                "api_url": lms_url,
                "openai_compatible": True,
                "model_count": len(status.models),
            }

        except Exception as e:
            status.error = str(e)

        self._results["lmstudio"] = status

    # ── Cloud Providers ───────────────────────────────────────

    def _detect_cloud_providers(self) -> None:
        cloud_map = {
            "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
            "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1"),
            "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com"),
            "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com"),
            "perplexity": ("PERPLEXITY_API_KEY", "https://api.perplexity.ai"),
        }

        for name, (env_var, url) in cloud_map.items():
            key = os.getenv(env_var, "")
            status = ProviderStatus(
                name=name,
                installed=bool(key),
                running=bool(key),  # Cloud = always running if key exists
                url=url if key else "",
                config={"env_var": env_var, "key_set": bool(key)},
            )
            if key:
                status.version = f"API key: {key[:8]}..."
            self._results[name] = status

    # ── Helpers ───────────────────────────────────────────────

    def _check_http(self, url: str) -> bool:
        """Check if an HTTP endpoint is responding."""
        try:
            import httpx
            resp = httpx.get(url, timeout=3)
            return resp.status_code < 500
        except Exception:
            try:
                import urllib.request
                req = urllib.request.urlopen(url, timeout=3)
                return req.status < 500
            except Exception:
                return False

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all detected providers."""
        if not self._results:
            self.detect_all()

        local = {k: v for k, v in self._results.items()
                 if k in ("openclaw", "ollama", "lmstudio")}
        cloud = {k: v for k, v in self._results.items()
                 if k not in ("openclaw", "ollama", "lmstudio")}

        all_models = []
        for p in self._results.values():
            all_models.extend(p.models)

        return {
            "local_providers": {
                name: {
                    "installed": s.installed,
                    "running": s.running,
                    "url": s.url,
                    "models": s.models,
                }
                for name, s in local.items()
            },
            "cloud_providers": {
                name: {
                    "configured": s.installed,
                    "url": s.url,
                }
                for name, s in cloud.items()
            },
            "total_models": len(all_models),
            "total_local_running": sum(
                1 for s in local.values() if s.running
            ),
            "total_cloud_configured": sum(
                1 for s in cloud.values() if s.installed
            ),
        }

    def generate_env_block(self) -> str:
        """Generate .env variables for detected providers."""
        if not self._results:
            self.detect_all()

        lines = []

        # OpenClaw
        oc = self._results.get("openclaw")
        if oc and oc.installed:
            lines.append(f"OPENCLAW_URL={oc.url}")
            if oc.config.get("has_token"):
                lines.append("# OPENCLAW_API_KEY=<from openclaw.json>")

        # Ollama
        ol = self._results.get("ollama")
        if ol and ol.installed:
            lines.append(f"\n# ── Ollama (Local Models) ─────────────")
            lines.append(f"OLLAMA_HOST={ol.url}")
            if ol.models:
                lines.append(f"OLLAMA_DEFAULT_MODEL={ol.models[0]}")
                lines.append(f"# Available: {', '.join(ol.models[:5])}")

        # LM Studio
        lms = self._results.get("lmstudio")
        if lms and lms.installed:
            lines.append(f"\n# ── LM Studio (Local OpenAI-compatible) ──")
            lines.append(f"LM_STUDIO_URL={lms.url}")
            if lms.models:
                lines.append(f"LM_STUDIO_DEFAULT_MODEL={lms.models[0]}")

        return "\n".join(lines)


_detector: ProviderDetector | None = None


def get_provider_detector() -> ProviderDetector:
    global _detector
    if _detector is None:
        _detector = ProviderDetector()
    return _detector
