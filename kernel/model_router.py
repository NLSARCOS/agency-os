#!/usr/bin/env python3
"""
Agency OS — Multi-Model Router

Intelligent routing across multiple AI providers with automatic fallback,
latency tracking, cost estimation, and health monitoring.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from kernel.config import get_config
from kernel.state_manager import get_state

logger = logging.getLogger("agency.models")

# ── Default model pools ──────────────────────────────────────

DEFAULT_POOLS: dict[str, list[dict[str, Any]]] = {
    "leadops": [
        {"name": "openrouter/openrouter/hunter-alpha", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/qwen/qwen3-coder:free", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/openrouter/healer-alpha", "provider": "openrouter", "tier": "free"},
    ],
    "marketing": [
        {"name": "openrouter/openrouter/hunter-alpha", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/qwen/qwen3-coder:free", "provider": "openrouter", "tier": "free"},
    ],
    "sales": [
        {"name": "openrouter/openrouter/hunter-alpha", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/stepfun/step-3.5-flash:free", "provider": "openrouter", "tier": "free"},
    ],
    "dev": [
        {"name": "openrouter/qwen/qwen3-coder:free", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/openrouter/hunter-alpha", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/nvidia/nemotron-3-super-120b-a12b:free", "provider": "openrouter", "tier": "free"},
        {"name": "claude-sonnet-4-20250514", "provider": "anthropic", "tier": "premium"},
        {"name": "gpt-4o", "provider": "openai", "tier": "premium"},
    ],
    "analytics": [
        {"name": "openrouter/qwen/qwen3-coder:free", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/nvidia/nemotron-3-super-120b-a12b:free", "provider": "openrouter", "tier": "free"},
    ],
    "creative": [
        {"name": "openrouter/openrouter/hunter-alpha", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/qwen/qwen3-coder:free", "provider": "openrouter", "tier": "free"},
    ],
    "abm": [
        {"name": "openrouter/openrouter/hunter-alpha", "provider": "openrouter", "tier": "free"},
        {"name": "openrouter/openrouter/healer-alpha", "provider": "openrouter", "tier": "free"},
    ],
}

# Provider API configs
PROVIDER_ENDPOINTS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "ollama": "http://localhost:11434/api/chat",
}

PROVIDER_KEY_MAP: dict[str, str] = {
    "openrouter": "openrouter",
    "openai": "openai",
    "anthropic": "anthropic",
    "ollama": "",  # No key needed
}


@dataclass
class ModelResponse:
    content: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0
    success: bool = True
    error: str = ""


@dataclass
class ModelHealth:
    model_name: str
    total_calls: int = 0
    failures: int = 0
    avg_latency_ms: float = 0
    last_error: str = ""
    is_healthy: bool = True


class ModelRouter:
    """Routes requests to the best available model with automatic fallback."""

    def __init__(self) -> None:
        cfg = get_config()
        yaml_pools = cfg.models.get("pools", {})
        self.pools = yaml_pools if yaml_pools else DEFAULT_POOLS
        self.health: dict[str, ModelHealth] = {}
        self._client = httpx.Client(timeout=120.0)
        self._cfg = cfg

    def get_models_for_studio(self, studio: str) -> list[dict[str, Any]]:
        """Get ordered model list for a studio, filtering unhealthy ones."""
        pool = self.pools.get(studio, self.pools.get("leadops", []))
        return [
            m for m in pool
            if self.health.get(m["name"], ModelHealth(m["name"])).is_healthy
        ]

    async def call_model(
        self,
        prompt: str,
        studio: str = "dev",
        system: str = "",
        task_id: int | None = None,
        max_retries: int = 2,
    ) -> ModelResponse:
        """Call the best available model with automatic fallback."""
        models = self.get_models_for_studio(studio)
        if not models:
            models = self.pools.get(studio, [])  # Try all including unhealthy

        last_error = ""
        for model_cfg in models:
            for attempt in range(max_retries):
                try:
                    response = self._call_provider(model_cfg, prompt, system)
                    # Log success
                    state = get_state()
                    state.log_model_usage(
                        model_name=model_cfg["name"],
                        studio=studio,
                        task_id=task_id,
                        tokens_in=response.tokens_in,
                        tokens_out=response.tokens_out,
                        latency_ms=response.latency_ms,
                        success=True,
                    )
                    self._update_health(model_cfg["name"], True)
                    return response
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        retry_after = int(e.response.headers.get("Retry-After", "5"))
                        logger.warning(
                            "Model %s rate limited (429). Waiting %ds...",
                            model_cfg["name"], retry_after,
                        )
                        time.sleep(retry_after)
                        continue  # retry same model
                    last_error = str(e)
                    logger.warning(
                        "Model %s attempt %d failed: %s",
                        model_cfg["name"], attempt + 1, last_error,
                    )
                    self._update_health(model_cfg["name"], False, last_error)
                    time.sleep(1 * (attempt + 1))
                except Exception as e:
                    last_error = str(e)
                    logger.warning(
                        "Model %s attempt %d failed: %s",
                        model_cfg["name"], attempt + 1, last_error,
                    )
                    self._update_health(model_cfg["name"], False, last_error)
                    time.sleep(1 * (attempt + 1))

        # All models failed
        state = get_state()
        state.log_event("model_failure", f"All models failed for {studio}: {last_error}", source="model_router", level="error")
        return ModelResponse(
            content="", model="none", provider="none",
            success=False, error=f"All models failed: {last_error}",
        )

    def call_model_sync(
        self,
        prompt: str,
        studio: str = "dev",
        system: str = "",
        task_id: int | None = None,
    ) -> ModelResponse:
        """Synchronous version of call_model."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.call_model(prompt, studio, system, task_id),
                    )
                    return future.result()
            return loop.run_until_complete(
                self.call_model(prompt, studio, system, task_id)
            )
        except RuntimeError:
            return asyncio.run(
                self.call_model(prompt, studio, system, task_id)
            )

    def _call_provider(
        self, model_cfg: dict, prompt: str, system: str
    ) -> ModelResponse:
        provider = model_cfg["provider"]
        model_name = model_cfg["name"]
        start = time.monotonic()

        # Guard: skip providers with no API key (except ollama which needs none)
        if provider != "ollama":
            key_name = PROVIDER_KEY_MAP.get(provider, provider)
            api_key = self._cfg.api_keys.get(key_name, "")
            if not api_key:
                raise RuntimeError(f"No API key configured for provider '{provider}' (set it in .env)")

        if provider == "anthropic":
            return self._call_anthropic(model_name, prompt, system, start)
        elif provider == "ollama":
            return self._call_ollama(model_name, prompt, system, start)
        else:
            return self._call_openai_compatible(model_name, provider, prompt, system, start)

    def _call_openai_compatible(
        self, model: str, provider: str, prompt: str, system: str, start: float
    ) -> ModelResponse:
        endpoint = PROVIDER_ENDPOINTS.get(provider, PROVIDER_ENDPOINTS["openrouter"])
        key_name = PROVIDER_KEY_MAP.get(provider, provider)
        api_key = self._cfg.api_keys.get(key_name, "")

        # Strip provider prefix from model name (e.g. "openrouter/openai/gpt-4o" → "openai/gpt-4o")
        api_model = model.removeprefix(f"{provider}/") if model.startswith(f"{provider}/") else model

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://agency-os.local"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = self._client.post(
            endpoint,
            headers=headers,
            json={"model": api_model, "messages": messages},
        )
        resp.raise_for_status()
        data = resp.json()

        latency = (time.monotonic() - start) * 1000
        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})

        return ModelResponse(
            content=content,
            model=model,
            provider=provider,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency,
        )

    def _call_anthropic(
        self, model: str, prompt: str, system: str, start: float
    ) -> ModelResponse:
        api_key = self._cfg.api_keys.get("anthropic", "")
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        resp = self._client.post(
            PROVIDER_ENDPOINTS["anthropic"],
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        latency = (time.monotonic() - start) * 1000
        content = data.get("content", [{}])[0].get("text", "")
        usage = data.get("usage", {})

        return ModelResponse(
            content=content,
            model=model,
            provider="anthropic",
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
            latency_ms=latency,
        )

    def _call_ollama(
        self, model: str, prompt: str, system: str, start: float
    ) -> ModelResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = self._client.post(
            PROVIDER_ENDPOINTS["ollama"],
            json={"model": model, "messages": messages, "stream": False},
        )
        resp.raise_for_status()
        data = resp.json()

        latency = (time.monotonic() - start) * 1000
        content = data.get("message", {}).get("content", "")

        return ModelResponse(
            content=content,
            model=model,
            provider="ollama",
            latency_ms=latency,
        )

    def _update_health(self, model: str, success: bool, error: str = "") -> None:
        if model not in self.health:
            self.health[model] = ModelHealth(model_name=model)
        h = self.health[model]
        h.total_calls += 1
        if not success:
            h.failures += 1
            h.last_error = error
        # Mark unhealthy if >50% failure rate and at least 3 calls
        if h.total_calls >= 3 and h.failures / h.total_calls > 0.5:
            h.is_healthy = False
            logger.warning("Model %s marked unhealthy (%.0f%% failure)", model, h.failures / h.total_calls * 100)

    def get_health_report(self) -> list[dict]:
        report = []
        for name, h in self.health.items():
            report.append({
                "model": name,
                "calls": h.total_calls,
                "failures": h.failures,
                "healthy": h.is_healthy,
                "failure_rate": f"{h.failures / h.total_calls * 100:.0f}%" if h.total_calls > 0 else "0%",
                "last_error": h.last_error[:100] if h.last_error else "",
            })
        return report

    def close(self) -> None:
        self._client.close()


def get_model_router() -> ModelRouter:
    return ModelRouter()
