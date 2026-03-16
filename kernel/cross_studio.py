#!/usr/bin/env python3
"""
Agency OS v4.0 — Cross-Studio Pipeline Chains

Automatic chaining: LeadOps → Sales → Marketing → Analytics.
Define triggers between studios so one studio's output
automatically feeds into another studio's input.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from kernel.event_bus import get_event_bus, Event

logger = logging.getLogger("agency.pipelines")


@dataclass
class PipelineChain:
    """Defines an automatic chain between studios."""
    name: str = ""
    source_studio: str = ""
    target_studio: str = ""
    trigger_condition: str = "on_success"  # on_success | on_failure | always
    transform: str = ""  # How to map source output to target input
    enabled: bool = True
    priority: int = 5


@dataclass
class ChainExecution:
    """Record of a chain execution."""
    chain_name: str
    source_studio: str
    target_studio: str
    source_output: dict
    target_input: dict
    status: str = "pending"  # pending | running | completed | failed
    started_at: str = ""
    completed_at: str = ""
    error: str = ""


# Pre-built chain templates for common agency workflows
DEFAULT_CHAINS: list[dict] = [
    {
        "name": "lead_to_sales",
        "source_studio": "leadops",
        "target_studio": "sales",
        "trigger_condition": "on_success",
        "transform": "leads_to_prospects",
        "priority": 1,
    },
    {
        "name": "sales_to_marketing",
        "source_studio": "sales",
        "target_studio": "marketing",
        "trigger_condition": "on_success",
        "transform": "prospects_to_campaign",
        "priority": 2,
    },
    {
        "name": "marketing_to_analytics",
        "source_studio": "marketing",
        "target_studio": "analytics",
        "trigger_condition": "on_success",
        "transform": "campaign_to_metrics",
        "priority": 3,
    },
    {
        "name": "analytics_to_creative",
        "source_studio": "analytics",
        "target_studio": "creative",
        "trigger_condition": "on_success",
        "transform": "insights_to_brief",
        "priority": 4,
    },
    {
        "name": "lead_to_abm",
        "source_studio": "leadops",
        "target_studio": "abm",
        "trigger_condition": "on_success",
        "transform": "leads_to_accounts",
        "priority": 2,
    },
]


class CrossStudioPipelines:
    """
    Manages automatic chains between studios.

    When a studio completes its pipeline, the cross-studio
    system checks for matching chains and triggers the next
    studio automatically with transformed data.
    """

    def __init__(self) -> None:
        self._chains: dict[str, PipelineChain] = {}
        self._history: list[ChainExecution] = []
        self._bus = get_event_bus()
        self._load_defaults()

    def _load_defaults(self) -> None:
        for cfg in DEFAULT_CHAINS:
            chain = PipelineChain(**cfg)
            self._chains[chain.name] = chain

    def add_chain(self, **kwargs) -> PipelineChain:
        chain = PipelineChain(**kwargs)
        self._chains[chain.name] = chain
        logger.info("Chain added: %s → %s", chain.source_studio, chain.target_studio)
        return chain

    def remove_chain(self, name: str) -> bool:
        if name in self._chains:
            del self._chains[name]
            return True
        return False

    def get_chains_for_studio(self, source_studio: str) -> list[PipelineChain]:
        """Get all chains triggered by a specific studio."""
        return sorted(
            [c for c in self._chains.values()
             if c.source_studio == source_studio and c.enabled],
            key=lambda c: c.priority,
        )

    def trigger_chains(
        self, source_studio: str, output: dict, success: bool
    ) -> list[ChainExecution]:
        """
        Trigger all matching chains after a studio completes.

        Returns list of chain executions (pending = needs processing).
        """
        chains = self.get_chains_for_studio(source_studio)
        executions = []

        for chain in chains:
            # Check trigger condition
            if chain.trigger_condition == "on_success" and not success:
                continue
            if chain.trigger_condition == "on_failure" and success:
                continue

            # Transform output to input for next studio
            target_input = self._transform_data(
                chain.transform, source_studio, output
            )

            now = datetime.now(timezone.utc).isoformat()
            execution = ChainExecution(
                chain_name=chain.name,
                source_studio=chain.source_studio,
                target_studio=chain.target_studio,
                source_output=output,
                target_input=target_input,
                status="pending",
                started_at=now,
            )
            executions.append(execution)
            self._history.append(execution)

            # Emit event for job queue to pick up
            self._bus.publish_sync(Event(
                type="chain.triggered",
                source=source_studio,
                payload={
                    "chain": chain.name,
                    "source": source_studio,
                    "target": chain.target_studio,
                    "input": target_input,
                },
            ))

            logger.info(
                "Chain triggered: %s → %s (%s)",
                source_studio, chain.target_studio, chain.name,
            )

        return executions

    def _transform_data(
        self, transform: str, source: str, output: dict
    ) -> dict[str, Any]:
        """Transform source output to target input."""
        content = output.get("content", "")
        base = {
            "source_studio": source,
            "source_content": content[:2000] if isinstance(content, str) else str(content)[:2000],
            "auto_triggered": True,
        }

        transforms = {
            "leads_to_prospects": lambda: {
                **base,
                "task": f"Follow up on leads from {source}: {content[:300]}",
                "context": "Auto-triggered from lead generation pipeline",
            },
            "prospects_to_campaign": lambda: {
                **base,
                "task": f"Create marketing campaign for sales prospects: {content[:300]}",
                "context": "Auto-triggered from sales outreach pipeline",
            },
            "campaign_to_metrics": lambda: {
                **base,
                "task": f"Analyze marketing campaign results: {content[:300]}",
                "context": "Auto-triggered from marketing campaign",
            },
            "insights_to_brief": lambda: {
                **base,
                "task": f"Create creative brief from analytics insights: {content[:300]}",
                "context": "Auto-triggered from analytics pipeline",
            },
            "leads_to_accounts": lambda: {
                **base,
                "task": f"Create ABM plan for identified accounts: {content[:300]}",
                "context": "Auto-triggered from lead ops pipeline",
            },
        }

        transformer = transforms.get(transform)
        if transformer:
            return transformer()

        return {**base, "task": f"Process output from {source}"}

    def get_history(self, limit: int = 20) -> list[dict]:
        return [
            {
                "chain": e.chain_name,
                "source": e.source_studio,
                "target": e.target_studio,
                "status": e.status,
                "started_at": e.started_at,
                "completed_at": e.completed_at,
                "error": e.error,
            }
            for e in self._history[-limit:]
        ]

    def get_all_chains(self) -> list[dict]:
        return [
            {
                "name": c.name,
                "source": c.source_studio,
                "target": c.target_studio,
                "trigger": c.trigger_condition,
                "enabled": c.enabled,
                "priority": c.priority,
            }
            for c in sorted(self._chains.values(), key=lambda c: c.priority)
        ]

    def get_stats(self) -> dict:
        total = len(self._history)
        completed = sum(1 for e in self._history if e.status == "completed")
        failed = sum(1 for e in self._history if e.status == "failed")
        return {
            "total_chains": len(self._chains),
            "enabled_chains": sum(1 for c in self._chains.values() if c.enabled),
            "total_executions": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / max(total, 1) * 100, 1),
        }


_pipelines: CrossStudioPipelines | None = None


def get_cross_studio_pipelines() -> CrossStudioPipelines:
    global _pipelines
    if _pipelines is None:
        _pipelines = CrossStudioPipelines()
    return _pipelines
