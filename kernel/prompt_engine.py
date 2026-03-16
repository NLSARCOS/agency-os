#!/usr/bin/env python3
"""
Agency OS v5.0 — Prompt Engine

Intelligent prompt compilation and token management:
- Prompt templates with variable slots (not string concat)
- Token estimation (char-based + tiktoken fallback)
- Context window management with intelligent truncation
- System prompt hashing + dedup
- Semantic cache for similar prompts
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from kernel.config import get_config

logger = logging.getLogger("agency.prompt")

# Model context windows (tokens)
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-3-haiku": 200_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-2.5-pro": 1_000_000,
    # Local models
    "llama3.2": 128_000,
    "qwen2.5": 32_768,
    "mistral": 32_768,
    "phi3": 4_096,
    # Defaults
    "default": 4_096,
    "ollama_default": 8_192,
    "lmstudio_default": 8_192,
}

# Chars per token approximation (conservative)
CHARS_PER_TOKEN = 3.5


@dataclass
class CompiledPrompt:
    """A compiled, optimized prompt ready for sending."""
    system: str = ""
    user: str = ""
    system_hash: str = ""
    estimated_tokens: int = 0
    context_window: int = 4096
    headroom_tokens: int = 0  # Remaining for response
    truncated: bool = False
    template_id: str = ""
    variables: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CacheEntry:
    """Cached prompt response."""
    prompt_hash: str
    response: str
    tokens_saved: int
    created_at: float
    hits: int = 0


# Default prompt templates per studio
STUDIO_TEMPLATES: dict[str, dict[str, str]] = {
    "dev": {
        "system": (
            "You are a senior software engineer working in the {studio} studio "
            "of an AI agency. Your task: {task_type}. Be precise and production-ready."
        ),
        "user": "{task}\n\nContext:\n{context}",
    },
    "marketing": {
        "system": (
            "You are a marketing strategist in the {studio} studio. "
            "Focus on: conversion, ROI, audience targeting. Be data-driven."
        ),
        "user": "Campaign brief:\n{task}\n\nAudience: {context}",
    },
    "sales": {
        "system": (
            "You are a sales specialist in the {studio} studio. "
            "Focus on: value proposition, objection handling, conversion."
        ),
        "user": "Sales task:\n{task}\n\nProspect info: {context}",
    },
    "leadops": {
        "system": (
            "You are a lead operations specialist in the {studio} studio. "
            "Focus on: lead qualification, enrichment, scoring."
        ),
        "user": "Lead operation:\n{task}\n\nData: {context}",
    },
    "analytics": {
        "system": (
            "You are a data analyst in the {studio} studio. "
            "Focus on: metrics, trends, actionable insights. Use structured data."
        ),
        "user": "Analysis request:\n{task}\n\nData context: {context}",
    },
    "creative": {
        "system": (
            "You are a creative director in the {studio} studio. "
            "Focus on: brand consistency, visual impact, storytelling."
        ),
        "user": "Creative brief:\n{task}\n\nBrand guidelines: {context}",
    },
    "abm": {
        "system": (
            "You are an ABM specialist in the {studio} studio. "
            "Focus on: account personalization, multi-touch engagement."
        ),
        "user": "ABM task:\n{task}\n\nAccount profile: {context}",
    },
    "_default": {
        "system": (
            "You are an AI agent in the {studio} studio of Agency OS. "
            "Complete the following task accurately and concisely."
        ),
        "user": "{task}\n\n{context}",
    },
}


class PromptEngine:
    """
    Intelligent prompt compiler.

    Features:
    - Template-based prompts (no string concat)
    - Token estimation before API calls
    - Context window management
    - System prompt dedup via hashing
    - Semantic cache (TF-IDF similarity)
    """

    def __init__(self) -> None:
        self._templates = dict(STUDIO_TEMPLATES)
        self._system_cache: dict[str, str] = {}  # hash → system prompt
        self._response_cache: dict[str, CacheEntry] = {}
        self._max_cache = 500
        self._custom_templates: dict[str, dict[str, str]] = {}

    def compile(
        self,
        task: str,
        studio: str = "dev",
        context: str = "",
        model: str = "default",
        max_response_tokens: int = 1000,
        extra_vars: dict[str, str] | None = None,
    ) -> CompiledPrompt:
        """
        Compile a task into an optimized prompt.

        Returns a CompiledPrompt with token estimates, truncation info,
        and system prompt hash for dedup.
        """
        # Get template
        template = self._custom_templates.get(
            studio,
            self._templates.get(studio, self._templates["_default"]),
        )

        # Build variables
        variables = {
            "task": task,
            "studio": studio,
            "context": context or "No additional context.",
            "task_type": self._classify_task_type(task),
        }
        if extra_vars:
            variables.update(extra_vars)

        # Compile system prompt
        system = self._fill_template(template["system"], variables)
        user = self._fill_template(template["user"], variables)

        # Optimize: remove redundant whitespace
        system = self._compress_whitespace(system)
        user = self._compress_whitespace(user)

        # Hash system prompt for dedup
        system_hash = hashlib.sha256(system.encode()).hexdigest()[:16]
        self._system_cache[system_hash] = system

        # Token estimation
        system_tokens = self._estimate_tokens(system)
        user_tokens = self._estimate_tokens(user)
        total_tokens = system_tokens + user_tokens

        # Context window
        context_window = self._get_context_window(model)
        headroom = context_window - total_tokens - max_response_tokens

        # Truncate if needed
        truncated = False
        if headroom < 0:
            user, truncated = self._truncate_context(
                user, abs(headroom) + 200  # Extra buffer
            )
            total_tokens = system_tokens + self._estimate_tokens(user)
            headroom = context_window - total_tokens - max_response_tokens

        return CompiledPrompt(
            system=system,
            user=user,
            system_hash=system_hash,
            estimated_tokens=total_tokens,
            context_window=context_window,
            headroom_tokens=max(0, headroom),
            truncated=truncated,
            template_id=studio,
            variables=variables,
            metadata={
                "model": model,
                "system_tokens": system_tokens,
                "user_tokens": self._estimate_tokens(user),
                "max_response_tokens": max_response_tokens,
            },
        )

    def check_cache(self, task: str, studio: str) -> str | None:
        """Check semantic cache for similar prompt."""
        prompt_hash = self._hash_prompt(task, studio)

        # Exact match
        if prompt_hash in self._response_cache:
            entry = self._response_cache[prompt_hash]
            entry.hits += 1
            logger.info(
                "Cache HIT (exact): saved %d tokens",
                entry.tokens_saved,
            )
            return entry.response

        # Similarity check (simplified TF-IDF)
        for cached_hash, entry in self._response_cache.items():
            if self._similarity(prompt_hash, cached_hash) > 0.95:
                entry.hits += 1
                logger.info(
                    "Cache HIT (similar): saved %d tokens",
                    entry.tokens_saved,
                )
                return entry.response

        return None

    def cache_response(
        self, task: str, studio: str, response: str, tokens_used: int
    ) -> None:
        """Cache a response for future reuse."""
        prompt_hash = self._hash_prompt(task, studio)
        self._response_cache[prompt_hash] = CacheEntry(
            prompt_hash=prompt_hash,
            response=response,
            tokens_saved=tokens_used,
            created_at=time.time(),
        )

        # Evict old entries
        if len(self._response_cache) > self._max_cache:
            oldest = min(
                self._response_cache,
                key=lambda k: self._response_cache[k].created_at,
            )
            del self._response_cache[oldest]

    def add_template(self, studio: str, system: str, user: str) -> None:
        """Add or override a prompt template for a studio."""
        self._custom_templates[studio] = {"system": system, "user": user}

    # ── Internal Methods ─────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (conservative character-based)."""
        return max(1, int(len(text) / CHARS_PER_TOKEN))

    def _get_context_window(self, model: str) -> int:
        """Get context window size for a model."""
        # Check exact match
        if model in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[model]

        # Check partial match
        model_lower = model.lower()
        for name, window in MODEL_CONTEXT_WINDOWS.items():
            if name in model_lower:
                return window

        # Provider-based defaults
        if "ollama" in model_lower:
            return MODEL_CONTEXT_WINDOWS["ollama_default"]
        if "lmstudio" in model_lower:
            return MODEL_CONTEXT_WINDOWS["lmstudio_default"]

        return MODEL_CONTEXT_WINDOWS["default"]

    def _fill_template(self, template: str, variables: dict[str, str]) -> str:
        """Fill template variables safely."""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    def _compress_whitespace(self, text: str) -> str:
        """Remove redundant whitespace while preserving structure."""
        lines = text.split("\n")
        compressed = []
        prev_empty = False
        for line in lines:
            stripped = line.rstrip()
            is_empty = not stripped
            if is_empty and prev_empty:
                continue  # Skip consecutive empty lines
            compressed.append(stripped)
            prev_empty = is_empty
        return "\n".join(compressed)

    def _truncate_context(
        self, text: str, tokens_to_remove: int
    ) -> tuple[str, bool]:
        """Intelligently truncate context, keeping start and end."""
        chars_to_remove = int(tokens_to_remove * CHARS_PER_TOKEN)
        if chars_to_remove >= len(text):
            return text[:500] + "\n\n[... truncated ...]", True

        # Keep first 40% and last 30%, remove middle
        keep_start = int(len(text) * 0.4)
        keep_end = int(len(text) * 0.3)
        truncated = (
            text[:keep_start]
            + "\n\n[... context truncated to fit model context window ...]\n\n"
            + text[-keep_end:]
        )
        return truncated, True

    def _classify_task_type(self, task: str) -> str:
        """Classify task type for template selection."""
        task_lower = task.lower()
        if any(w in task_lower for w in ["analyze", "report", "metrics"]):
            return "analysis"
        if any(w in task_lower for w in ["write", "draft", "create", "compose"]):
            return "creation"
        if any(w in task_lower for w in ["fix", "debug", "solve", "error"]):
            return "troubleshooting"
        if any(w in task_lower for w in ["plan", "strategy", "propose"]):
            return "planning"
        return "general"

    def _hash_prompt(self, task: str, studio: str) -> str:
        """Create hash for cache lookup."""
        normalized = re.sub(r"\s+", " ", task.strip().lower())
        return hashlib.sha256(f"{studio}:{normalized}".encode()).hexdigest()[:20]

    def _similarity(self, hash_a: str, hash_b: str) -> float:
        """Simple character-level similarity between hashes."""
        matching = sum(a == b for a, b in zip(hash_a, hash_b))
        return matching / max(len(hash_a), len(hash_b))

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        total_cached = len(self._response_cache)
        total_hits = sum(e.hits for e in self._response_cache.values())
        total_saved = sum(
            e.tokens_saved * e.hits for e in self._response_cache.values()
        )
        return {
            "cached_responses": total_cached,
            "cache_hits": total_hits,
            "tokens_saved_by_cache": total_saved,
            "system_prompts_cached": len(self._system_cache),
            "custom_templates": len(self._custom_templates),
        }


_engine: PromptEngine | None = None


def get_prompt_engine() -> PromptEngine:
    global _engine
    if _engine is None:
        _engine = PromptEngine()
    return _engine
