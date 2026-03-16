#!/usr/bin/env python3
"""
Agency OS v3.5 — Guardrails System

Enterprise-grade safety for autonomous AI operations:
- Cost limits: max tokens/cost per studio, agent, and global
- Rate limits: max concurrent calls, requests per minute
- Content filter: PII detection, prompt injection, output validation
- Budget tracking: real-time spend per studio/model with alerts
"""
from __future__ import annotations

import logging
import re
import time
import threading
from dataclasses import dataclass, field
from typing import Any

from kernel.config import get_config
from kernel.state_manager import get_state

logger = logging.getLogger("agency.guardrails")


@dataclass
class BudgetConfig:
    """Budget configuration for a scope (studio, agent, or global)."""
    max_tokens_per_day: int = 500_000
    max_cost_per_day: float = 10.0  # USD
    max_requests_per_minute: int = 30
    max_concurrent: int = 5
    alert_threshold: float = 0.8  # Alert at 80% of budget


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    allowed: bool = True
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class UsageRecord:
    """Tracking record for token/cost usage."""
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost: float = 0.0
    request_count: int = 0
    last_reset: float = field(default_factory=time.time)
    request_timestamps: list[float] = field(default_factory=list)


# Cost per 1K tokens by model category
MODEL_COSTS = {
    "claude-sonnet": {"input": 0.003, "output": 0.015},
    "claude-opus": {"input": 0.015, "output": 0.075},
    "gpt-5": {"input": 0.005, "output": 0.015},
    "gpt-4": {"input": 0.01, "output": 0.03},
    "gemini": {"input": 0.0, "output": 0.0},
    "free": {"input": 0.0, "output": 0.0},
    "local": {"input": 0.0, "output": 0.0},
    "default": {"input": 0.001, "output": 0.002},
}

# PII patterns
PII_PATTERNS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),
    (r"\b\d{16}\b", "Credit Card"),
    (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "Credit Card"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "Email"),
    (r"\b(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "Phone"),
]

# Prompt injection patterns
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now\s+(?:a|an)\s+(?:different|new)",
    r"forget\s+(?:everything|all|your)\s+(?:rules|instructions)",
    r"system\s*:\s*you\s+are",
    r"<\|im_start\|>",
    r"\[INST\]",
]


class Guardrails:
    """
    Enterprise guardrails for Agency OS.

    Checks performed before every AI call:
    1. Budget check — within token/cost limits?
    2. Rate limit — not too many concurrent/minute?
    3. Content filter — no PII, no injection?
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self._lock = threading.Lock()

        # Usage tracking per scope
        self._usage: dict[str, UsageRecord] = {}

        # Budget configs per scope
        self._budgets: dict[str, BudgetConfig] = {
            "global": BudgetConfig(
                max_tokens_per_day=2_000_000,
                max_cost_per_day=50.0,
                max_requests_per_minute=60,
                max_concurrent=10,
            ),
        }

        # Active request counter
        self._active_requests: dict[str, int] = {}

    # ── Pre-Call Check ────────────────────────────────────────

    def check_pre_call(
        self,
        studio: str = "",
        agent_id: str = "",
        prompt: str = "",
        estimated_tokens: int = 1000,
    ) -> GuardrailResult:
        """Check all guardrails before making an AI call."""
        result = GuardrailResult()

        # 1. Budget check
        budget_result = self.check_budget(studio or "global")
        if not budget_result.allowed:
            return budget_result
        result.warnings.extend(budget_result.warnings)

        # 2. Rate limit
        rate_result = self.check_rate_limit(studio or "global")
        if not rate_result.allowed:
            return rate_result

        # 3. Content filter on input
        content_result = self.check_content(prompt, direction="input")
        if not content_result.allowed:
            return content_result
        result.warnings.extend(content_result.warnings)

        return result

    # ── Post-Call Record ──────────────────────────────────────

    def record_usage(
        self,
        studio: str,
        agent_id: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float = 0,
        success: bool = True,
    ) -> None:
        """Record token usage after an AI call."""
        cost = self._estimate_cost(model, tokens_in, tokens_out)

        with self._lock:
            for scope in [studio, "global"]:
                usage = self._get_usage(scope)
                usage.tokens_in += tokens_in
                usage.tokens_out += tokens_out
                usage.estimated_cost += cost
                usage.request_count += 1

            # Release concurrent slot
            if studio in self._active_requests:
                self._active_requests[studio] = max(
                    0, self._active_requests.get(studio, 1) - 1
                )

        # Log to state DB
        self.state.log_kpi(studio, "tokens_used", tokens_in + tokens_out, "tokens")
        self.state.log_kpi(studio, "estimated_cost", cost, "usd")

    # ── Budget Check ──────────────────────────────────────────

    def check_budget(self, scope: str) -> GuardrailResult:
        """Check if scope is within budget."""
        usage = self._get_usage(scope)
        budget = self._get_budget(scope)

        self._maybe_reset_daily(usage)

        total_tokens = usage.tokens_in + usage.tokens_out
        result = GuardrailResult()

        # Token limit
        if total_tokens >= budget.max_tokens_per_day:
            return GuardrailResult(
                allowed=False,
                reason=f"Token budget exceeded for '{scope}': "
                       f"{total_tokens:,}/{budget.max_tokens_per_day:,}",
            )

        # Cost limit
        if usage.estimated_cost >= budget.max_cost_per_day:
            return GuardrailResult(
                allowed=False,
                reason=f"Cost budget exceeded for '{scope}': "
                       f"${usage.estimated_cost:.2f}/${budget.max_cost_per_day:.2f}",
            )

        # Warnings at threshold
        token_pct = total_tokens / budget.max_tokens_per_day
        cost_pct = usage.estimated_cost / budget.max_cost_per_day if budget.max_cost_per_day > 0 else 0

        if token_pct >= budget.alert_threshold:
            result.warnings.append(
                f"⚠️ Token usage at {token_pct:.0%} for '{scope}'"
            )
        if cost_pct >= budget.alert_threshold:
            result.warnings.append(
                f"⚠️ Cost at {cost_pct:.0%} for '{scope}'"
            )

        return result

    # ── Rate Limit ────────────────────────────────────────────

    def check_rate_limit(self, scope: str) -> GuardrailResult:
        """Check requests per minute and concurrent limits."""
        budget = self._get_budget(scope)
        now = time.time()

        with self._lock:
            usage = self._get_usage(scope)

            # Clean old timestamps (keep last 60s)
            usage.request_timestamps = [
                ts for ts in usage.request_timestamps if now - ts < 60
            ]

            # RPM check
            if len(usage.request_timestamps) >= budget.max_requests_per_minute:
                return GuardrailResult(
                    allowed=False,
                    reason=f"Rate limit exceeded for '{scope}': "
                           f"{len(usage.request_timestamps)}/{budget.max_requests_per_minute} RPM",
                )

            # Concurrent check
            active = self._active_requests.get(scope, 0)
            if active >= budget.max_concurrent:
                return GuardrailResult(
                    allowed=False,
                    reason=f"Concurrent limit for '{scope}': "
                           f"{active}/{budget.max_concurrent}",
                )

            # Record this request
            usage.request_timestamps.append(now)
            self._active_requests[scope] = active + 1

        return GuardrailResult()

    # ── Content Filter ────────────────────────────────────────

    def check_content(self, text: str, direction: str = "input") -> GuardrailResult:
        """Check content for PII and prompt injection."""
        result = GuardrailResult()

        if not text:
            return result

        # PII detection
        for pattern, pii_type in PII_PATTERNS:
            if re.search(pattern, text):
                result.warnings.append(
                    f"⚠️ Possible {pii_type} detected in {direction}"
                )

        # Prompt injection (input only)
        if direction == "input":
            text_lower = text.lower()
            for pattern in INJECTION_PATTERNS:
                if re.search(pattern, text_lower):
                    return GuardrailResult(
                        allowed=False,
                        reason=f"Possible prompt injection detected in {direction}",
                    )

        return result

    # ── Budget Management ─────────────────────────────────────

    def set_budget(self, scope: str, **kwargs) -> None:
        """Set budget for a scope."""
        budget = self._get_budget(scope)
        for key, value in kwargs.items():
            if hasattr(budget, key):
                setattr(budget, key, value)
        self._budgets[scope] = budget
        logger.info("Budget updated for '%s': %s", scope, kwargs)

    def get_usage_summary(self) -> dict[str, Any]:
        """Get usage summary for all scopes."""
        summary = {}
        for scope, usage in self._usage.items():
            budget = self._get_budget(scope)
            total = usage.tokens_in + usage.tokens_out
            summary[scope] = {
                "tokens_used": total,
                "tokens_limit": budget.max_tokens_per_day,
                "tokens_pct": round(total / budget.max_tokens_per_day * 100, 1),
                "cost_usd": round(usage.estimated_cost, 4),
                "cost_limit": budget.max_cost_per_day,
                "requests": usage.request_count,
                "rpm_limit": budget.max_requests_per_minute,
            }
        return summary

    def get_status(self) -> dict[str, Any]:
        """Get guardrails status."""
        return {
            "scopes_tracked": len(self._usage),
            "budgets_configured": len(self._budgets),
            "usage": self.get_usage_summary(),
        }

    # ── Internals ─────────────────────────────────────────────

    def _get_usage(self, scope: str) -> UsageRecord:
        if scope not in self._usage:
            self._usage[scope] = UsageRecord()
        return self._usage[scope]

    def _get_budget(self, scope: str) -> BudgetConfig:
        return self._budgets.get(scope, self._budgets.get("global", BudgetConfig()))

    def _maybe_reset_daily(self, usage: UsageRecord) -> None:
        """Reset counters if a new day has started."""
        now = time.time()
        if now - usage.last_reset > 86400:  # 24h
            usage.tokens_in = 0
            usage.tokens_out = 0
            usage.estimated_cost = 0.0
            usage.request_count = 0
            usage.last_reset = now

    def _estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Estimate cost based on model name."""
        model_lower = model.lower()
        costs = MODEL_COSTS["default"]

        for key, c in MODEL_COSTS.items():
            if key in model_lower:
                costs = c
                break

        return (tokens_in / 1000 * costs["input"]) + (tokens_out / 1000 * costs["output"])


_guardrails: Guardrails | None = None


def get_guardrails() -> Guardrails:
    global _guardrails
    if _guardrails is None:
        _guardrails = Guardrails()
    return _guardrails
