#!/usr/bin/env python3
"""
Agency OS — Intelligent Task Router

Weighted keyword scoring with semantic categories.
Config-driven via configs/routing.yaml.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from kernel.config import get_config

logger = logging.getLogger("agency.router")

# ── Default routing rules (overridden by routing.yaml) ────────

DEFAULT_ROUTES: dict[str, dict[str, Any]] = {
    "leadops": {
        "keywords": [
            "lead", "leads", "scraping", "scrape", "prospect", "prospecting",
            "discovery", "enrich", "enrichment", "dedupe", "dedup",
            "scoring", "contact", "email", "phone", "directory",
            "database", "b2b", "list", "listas", "médico", "medico",
            "doctor", "hospital", "clinic", "clínica", "ecuador",
        ],
        "weight": 1.0,
        "description": "Lead generation, scraping, enrichment, dedup, scoring",
    },
    "sales": {
        "keywords": [
            "outreach", "follow-up", "followup", "close", "closing", "deal",
            "pipeline", "proposal", "propuesta", "cotización", "quote",
            "negotiation", "sequence", "cadence", "cold", "warm",
            "meeting", "demo", "pitch", "venta", "ventas", "comercial",
        ],
        "weight": 1.0,
        "description": "Outreach, follow-up, closing, commercial pipeline",
    },
    "marketing": {
        "keywords": [
            "campaign", "campaña", "funnel", "landing", "seo", "sem",
            "content", "copy", "copywriting", "brand", "positioning",
            "strategy", "growth", "cro", "conversion", "social",
            "ads", "email-marketing", "newsletter", "blog", "pr",
            "posicionamiento", "marca", "estrategia",
        ],
        "weight": 1.0,
        "description": "Campaigns, positioning, funnels, content strategy",
    },
    "dev": {
        "keywords": [
            "code", "coding", "develop", "development", "bug", "fix",
            "feature", "deploy", "deployment", "api", "backend", "frontend",
            "database", "repo", "repository", "git", "test", "testing",
            "architecture", "refactor", "build", "ci", "cd", "devops",
            "server", "endpoint", "integration", "script", "automation",
            "código", "desarrollo", "programar", "implementar",
        ],
        "weight": 1.0,
        "description": "Software development, architecture, QA, deployment",
    },
    "abm": {
        "keywords": [
            "abm", "account", "target", "targeting", "icp", "persona",
            "decision-maker", "decisor", "personalize", "personalización",
            "tier", "segment", "account-based", "enterprise", "key-account",
        ],
        "weight": 1.2,  # Higher weight — ABM keywords are very specific
        "description": "Account-based marketing and targeting",
    },
    "analytics": {
        "keywords": [
            "report", "reporte", "dashboard", "kpi", "metric", "data",
            "analysis", "análisis", "analytics", "insight", "trend",
            "performance", "roi", "attribution", "tracking",
        ],
        "weight": 1.0,
        "description": "Reporting, KPIs, dashboards, data analysis",
    },
    "creative": {
        "keywords": [
            "creative", "creativo", "design", "diseño", "asset", "video",
            "image", "graphic", "visual", "branding", "logo", "banner",
            "template", "mockup", "ui", "ux", "animation", "guión",
            "script", "material", "producción",
        ],
        "weight": 1.0,
        "description": "Creative assets, design, visual content production",
    },
}


@dataclass
class RouteResult:
    task: str
    studio: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    model_preference: list[str] = field(default_factory=list)


class TaskRouter:
    """Routes tasks to studios using weighted keyword scoring."""

    def __init__(self) -> None:
        cfg = get_config()
        yaml_routes = cfg.routing.get("routes", {})
        self.routes = yaml_routes if yaml_routes else DEFAULT_ROUTES
        self.default_studio = cfg.routing.get("default_studio", "leadops")
        self.model_preferences = cfg.routing.get("model_preferences", {})

    def route(self, task: str, context: dict[str, Any] | None = None) -> RouteResult:
        """Route a task to the best matching studio."""
        text = task.lower()
        scores: dict[str, float] = {}

        for studio, config in self.routes.items():
            keywords = config.get("keywords", [])
            weight = config.get("weight", 1.0)
            score = 0.0
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in text:
                    # Longer keywords get higher scores
                    score += len(kw_lower) * weight
            scores[studio] = score

        # Determine best studio
        if any(s > 0 for s in scores.values()):
            best_studio = max(scores, key=lambda k: scores[k])
            total = sum(scores.values())
            confidence = scores[best_studio] / total if total > 0 else 0
        else:
            best_studio = self.default_studio
            confidence = 0.1

        # Context overrides
        if context and "force_studio" in context:
            best_studio = context["force_studio"]
            confidence = 1.0

        # Get model preferences
        models = self.model_preferences.get(best_studio, [])

        result = RouteResult(
            task=task,
            studio=best_studio,
            confidence=round(confidence, 3),
            scores={k: round(v, 2) for k, v in scores.items() if v > 0},
            model_preference=models,
        )

        logger.info(
            "Routed task to %s (confidence=%.2f): %s",
            best_studio, confidence, task[:80],
        )
        return result

    def bulk_route(self, tasks: list[str]) -> list[RouteResult]:
        """Route multiple tasks at once."""
        return [self.route(t) for t in tasks]


def route_task(task: str, context: dict[str, Any] | None = None) -> RouteResult:
    """Convenience function to route a single task."""
    return TaskRouter().route(task, context)
