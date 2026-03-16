#!/usr/bin/env python3
"""
Agency OS v4.0 — Quality Gates

Measurable success criteria for each studio pipeline.
Every pipeline run is evaluated against its quality gate
to determine if the output meets minimum standards.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agency.quality_gates")


@dataclass
class GateResult:
    """Result of a quality gate evaluation."""
    passed: bool = False
    score: float = 0.0  # 0-100
    checks: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@dataclass
class QualityGate:
    """Quality gate configuration for a studio."""
    studio: str
    min_score: float = 60.0
    require_content: bool = True
    min_content_length: int = 50
    require_structured: bool = False
    custom_checks: list[str] = field(default_factory=list)


# Default quality gates per studio
DEFAULT_GATES: dict[str, dict] = {
    "dev": {
        "min_score": 70,
        "require_content": True,
        "min_content_length": 100,
        "require_structured": True,
        "custom_checks": ["has_code", "has_explanation"],
    },
    "leadops": {
        "min_score": 60,
        "require_content": True,
        "min_content_length": 50,
        "custom_checks": ["has_leads", "has_contact_info"],
    },
    "marketing": {
        "min_score": 65,
        "require_content": True,
        "min_content_length": 100,
        "custom_checks": ["has_strategy", "has_cta"],
    },
    "sales": {
        "min_score": 60,
        "require_content": True,
        "min_content_length": 50,
        "custom_checks": ["has_prospects", "has_template"],
    },
    "analytics": {
        "min_score": 70,
        "require_content": True,
        "min_content_length": 100,
        "require_structured": True,
        "custom_checks": ["has_metrics", "has_insights"],
    },
    "creative": {
        "min_score": 65,
        "require_content": True,
        "min_content_length": 100,
        "custom_checks": ["has_deliverable"],
    },
    "abm": {
        "min_score": 60,
        "require_content": True,
        "min_content_length": 50,
        "custom_checks": ["has_accounts", "has_plan"],
    },
}


class QualityGates:
    """
    Quality gate system for studio pipelines.

    Evaluates pipeline output against minimum standards:
    - Content presence and length
    - Structured output (JSON/YAML/sections)
    - Custom domain-specific checks
    - Scoring with pass/fail threshold
    """

    def __init__(self) -> None:
        self._gates: dict[str, QualityGate] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        for studio, cfg in DEFAULT_GATES.items():
            self._gates[studio] = QualityGate(studio=studio, **cfg)

    def evaluate(self, studio: str, output: dict[str, Any]) -> dict[str, Any]:
        """
        Evaluate pipeline output against quality gate.

        Args:
            studio: Studio name
            output: Pipeline output dict with at minimum 'content' key

        Returns:
            Dict with 'passed', 'score', 'checks', 'failures'
        """
        gate = self._gates.get(studio, QualityGate(studio=studio))
        result = GateResult()
        max_score = 0
        earned_score = 0

        content = output.get("content", "")
        if isinstance(content, dict):
            content = str(content)

        # Check 1: Content presence
        max_score += 30
        if content and len(content.strip()) > 0:
            earned_score += 20
            result.checks.append({"name": "content_present", "passed": True})

            # Length check
            if len(content) >= gate.min_content_length:
                earned_score += 10
                result.checks.append({"name": "content_length", "passed": True})
            else:
                result.checks.append({
                    "name": "content_length", "passed": False,
                    "detail": f"{len(content)}/{gate.min_content_length} chars",
                })
                result.failures.append(
                    f"Content too short: {len(content)}/{gate.min_content_length}"
                )
        else:
            result.checks.append({"name": "content_present", "passed": False})
            result.failures.append("No content produced")

        # Check 2: Structured output
        if gate.require_structured:
            max_score += 20
            has_structure = (
                isinstance(output.get("sections"), list)
                or isinstance(output.get("steps"), list)
                or "##" in content
                or "{" in content
            )
            if has_structure:
                earned_score += 20
                result.checks.append({"name": "structured", "passed": True})
            else:
                result.checks.append({"name": "structured", "passed": False})
                result.failures.append("Output lacks structure")

        # Check 3: Custom domain checks
        for check_name in gate.custom_checks:
            max_score += 10
            passed = self._custom_check(check_name, content, output)
            if passed:
                earned_score += 10
            else:
                result.failures.append(f"Custom check failed: {check_name}")
            result.checks.append({"name": check_name, "passed": passed})

        # Score
        result.score = (earned_score / max(max_score, 1)) * 100
        result.passed = result.score >= gate.min_score

        if not result.passed:
            logger.warning(
                "Quality gate FAILED for %s: %.1f%% < %.1f%% — %s",
                studio, result.score, gate.min_score, result.failures,
            )

        return {
            "passed": result.passed,
            "score": round(result.score, 1),
            "min_score": gate.min_score,
            "checks": result.checks,
            "failures": result.failures,
        }

    def _custom_check(self, name: str, content: str, output: dict) -> bool:
        """Run a domain-specific quality check."""
        content_lower = content.lower()

        checks = {
            "has_code": lambda: "```" in content or "def " in content or "function" in content,
            "has_explanation": lambda: len(content) > 200 and any(w in content_lower for w in ["because", "therefore", "approach", "solution"]),
            "has_leads": lambda: any(w in content_lower for w in ["lead", "contact", "prospect", "company"]),
            "has_contact_info": lambda: "@" in content or "http" in content or "linkedin" in content_lower,
            "has_strategy": lambda: any(w in content_lower for w in ["strategy", "plan", "approach", "objective"]),
            "has_cta": lambda: any(w in content_lower for w in ["call to action", "cta", "sign up", "learn more", "contact"]),
            "has_prospects": lambda: any(w in content_lower for w in ["prospect", "target", "company", "decision maker"]),
            "has_template": lambda: any(w in content_lower for w in ["template", "subject:", "dear", "hi "]),
            "has_metrics": lambda: any(w in content_lower for w in ["metric", "kpi", "rate", "percentage", "count", "total"]),
            "has_insights": lambda: any(w in content_lower for w in ["insight", "trend", "pattern", "recommend", "suggest"]),
            "has_deliverable": lambda: len(content) > 100,
            "has_accounts": lambda: any(w in content_lower for w in ["account", "company", "target"]),
            "has_plan": lambda: any(w in content_lower for w in ["plan", "step", "phase", "timeline"]),
        }

        checker = checks.get(name)
        if checker:
            return checker()

        # Unknown check: check if it exists as output key
        return bool(output.get(name))

    def get_gate(self, studio: str) -> dict:
        """Get quality gate config for a studio."""
        gate = self._gates.get(studio, QualityGate(studio=studio))
        return {
            "studio": gate.studio,
            "min_score": gate.min_score,
            "require_content": gate.require_content,
            "min_content_length": gate.min_content_length,
            "require_structured": gate.require_structured,
            "custom_checks": gate.custom_checks,
        }

    def get_all_gates(self) -> dict[str, dict]:
        """Get all quality gate configs."""
        return {name: self.get_gate(name) for name in self._gates}

    def set_gate(self, studio: str, **kwargs) -> None:
        """Update quality gate for a studio."""
        gate = self._gates.get(studio, QualityGate(studio=studio))
        for key, value in kwargs.items():
            if hasattr(gate, key):
                setattr(gate, key, value)
        self._gates[studio] = gate


_quality_gates: QualityGates | None = None


def get_quality_gates() -> QualityGates:
    global _quality_gates
    if _quality_gates is None:
        _quality_gates = QualityGates()
    return _quality_gates
