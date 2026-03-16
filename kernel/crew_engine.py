#!/usr/bin/env python3
"""
Agency OS v3.5 — Intelligent Crew Assembly

Auto-assemble optimal agent crews for any task:
- Capability matrix: each agent scored by domain
- Cross-studio crews: marketing + sales + creative for a launch
- Crew history: learn which combos succeed/fail
- Performance feedback: successful crews boost priority
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from kernel.agent_manager import get_agent_manager
from kernel.memory_manager import get_memory_manager

logger = logging.getLogger("agency.crew")


@dataclass
class CrewMember:
    """A selected agent with role and confidence."""
    agent_id: str
    role: str
    confidence: float  # 0-1 how suitable
    skills: list[str] = field(default_factory=list)


@dataclass
class Crew:
    """An assembled crew ready for execution."""
    name: str
    task: str
    members: list[CrewMember] = field(default_factory=list)
    studio: str = ""
    cross_studio: bool = False


# Domain-to-agent capability matrix
CAPABILITY_MATRIX: dict[str, list[tuple[str, float]]] = {
    "development": [
        ("backend-specialist", 0.95),
        ("frontend-specialist", 0.90),
        ("debugger", 0.85),
        ("devops-engineer", 0.80),
        ("database-architect", 0.85),
        ("code-archaeologist", 0.70),
    ],
    "marketing": [
        ("product-manager", 0.90),
        ("documentation-writer", 0.75),
        ("frontend-specialist", 0.60),
    ],
    "sales": [
        ("product-manager", 0.85),
        ("explorer-agent", 0.80),
    ],
    "leadops": [
        ("explorer-agent", 0.95),
        ("product-manager", 0.70),
    ],
    "analytics": [
        ("database-architect", 0.90),
        ("backend-specialist", 0.75),
        ("product-manager", 0.70),
    ],
    "creative": [
        ("frontend-specialist", 0.90),
        ("documentation-writer", 0.80),
    ],
    "security": [
        ("security-auditor", 0.95),
        ("backend-specialist", 0.75),
        ("devops-engineer", 0.80),
    ],
    "infrastructure": [
        ("devops-engineer", 0.95),
        ("backend-specialist", 0.80),
        ("database-architect", 0.75),
    ],
    "design": [
        ("frontend-specialist", 0.90),
        ("mobile-developer", 0.80),
    ],
    "mobile": [
        ("mobile-developer", 0.95),
        ("frontend-specialist", 0.70),
    ],
    "planning": [
        ("product-manager", 0.90),
        ("product-owner", 0.85),
        ("project-planner", 0.80),
    ],
}

# Task keyword → domain mapping
TASK_KEYWORDS: dict[str, list[str]] = {
    "development": ["code", "build", "api", "implement", "feature", "fix", "bug", "deploy", "test", "refactor"],
    "marketing": ["campaign", "content", "seo", "blog", "email", "funnel", "brand", "social"],
    "sales": ["sell", "deal", "proposal", "negotiate", "close", "pipeline", "revenue"],
    "leadops": ["lead", "scrape", "prospect", "enrich", "outbound", "cold"],
    "analytics": ["report", "metric", "kpi", "data", "dashboard", "analysis", "insight"],
    "creative": ["design", "landing", "visual", "copy", "branding", "video"],
    "security": ["security", "audit", "vulnerability", "pentest", "compliance", "owasp"],
    "infrastructure": ["server", "docker", "ci/cd", "kubernetes", "cloud", "devops", "infra"],
    "design": ["ui", "ux", "interface", "wireframe", "prototype", "figma"],
    "mobile": ["mobile", "ios", "android", "react native", "flutter", "app"],
    "planning": ["plan", "roadmap", "strategy", "sprint", "backlog", "prioritize"],
}


class CrewEngine:
    """
    Intelligent crew assembly engine.

    Given a task description, automatically selects the best agents,
    forms a crew, and tracks success/failure for learning.
    """

    def __init__(self) -> None:
        self.am = get_agent_manager()
        self.mm = get_memory_manager()
        self._history: list[dict] = []

    def assemble(
        self,
        task: str,
        max_members: int = 4,
        required_domains: list[str] | None = None,
    ) -> Crew:
        """
        Assemble the optimal crew for a task.

        1. Detect domains from task keywords
        2. Score agents by domain relevance
        3. Pick top agents, deduplicate
        4. Apply learnings from history
        """
        # 1. Detect domains
        domains = required_domains or self._detect_domains(task)
        if not domains:
            domains = ["development"]  # Default fallback

        logger.info("Crew assembly for: %s → domains: %s", task[:60], domains)

        # 2. Score agents
        scored: dict[str, float] = {}
        agent_domains: dict[str, list[str]] = {}

        for domain in domains:
            agents = CAPABILITY_MATRIX.get(domain, [])
            for agent_id, base_score in agents:
                # Boost from history
                history_boost = self._get_history_boost(agent_id, domain)
                final_score = min(1.0, base_score + history_boost)

                if agent_id not in scored or final_score > scored[agent_id]:
                    scored[agent_id] = final_score
                if agent_id not in agent_domains:
                    agent_domains[agent_id] = []
                agent_domains[agent_id].append(domain)

        # 3. Pick top agents
        sorted_agents = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        members = []

        for agent_id, confidence in sorted_agents[:max_members]:
            role_domains = agent_domains.get(agent_id, [])
            role = role_domains[0] if role_domains else "general"

            # Get skills from agent definition
            agent_def = self.am.get_agent(agent_id)
            skills = list(getattr(agent_def, "skills", [])) if agent_def else []

            members.append(CrewMember(
                agent_id=agent_id,
                role=role,
                confidence=round(confidence, 2),
                skills=skills[:5],
            ))

        # 4. Determine if cross-studio
        unique_domains = set()
        for m in members:
            unique_domains.add(m.role)
        cross_studio = len(unique_domains) > 1

        crew = Crew(
            name=f"crew-{'-'.join(domains[:2])}",
            task=task,
            members=members,
            studio=domains[0],
            cross_studio=cross_studio,
        )

        logger.info(
            "Crew assembled: %s — %d members %s",
            crew.name, len(crew.members),
            "(cross-studio)" if cross_studio else "",
        )

        return crew

    def record_outcome(
        self, crew: Crew, success: bool, notes: str = ""
    ) -> None:
        """Record crew performance for learning."""
        entry = {
            "crew_name": crew.name,
            "task": crew.task[:100],
            "members": [m.agent_id for m in crew.members],
            "domains": [m.role for m in crew.members],
            "success": success,
            "notes": notes,
        }
        self._history.append(entry)

        # Store in knowledge base for long-term learning
        outcome = "succeeded" if success else "failed"
        self.mm.learn(
            agent_id="crew_engine",
            topic=f"Crew {crew.name} {outcome}",
            content=(
                f"Task: {crew.task[:200]}\n"
                f"Members: {', '.join(m.agent_id for m in crew.members)}\n"
                f"Outcome: {outcome}\n{notes}"
            ),
        )

    def get_history(self, limit: int = 20) -> list[dict]:
        return self._history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        if not self._history:
            return {"total_crews": 0, "success_rate": 0, "domains": []}

        successes = sum(1 for h in self._history if h["success"])
        return {
            "total_crews": len(self._history),
            "success_rate": round(successes / len(self._history) * 100, 1),
            "top_agents": self._top_agents(),
            "domains": list(set(
                d for h in self._history for d in h["domains"]
            )),
        }

    def _detect_domains(self, task: str) -> list[str]:
        """Detect relevant domains from task description."""
        task_lower = task.lower()
        detected = []

        for domain, keywords in TASK_KEYWORDS.items():
            if any(kw in task_lower for kw in keywords):
                detected.append(domain)

        return detected or ["development"]

    def _get_history_boost(self, agent_id: str, domain: str) -> float:
        """Get historical performance boost for an agent in a domain."""
        relevant = [
            h for h in self._history
            if agent_id in h["members"] and domain in h["domains"]
        ]
        if not relevant:
            return 0.0

        successes = sum(1 for h in relevant if h["success"])
        return (successes / len(relevant)) * 0.1  # Max 10% boost

    def _top_agents(self) -> list[dict]:
        """Get top performing agents from history."""
        agent_stats: dict[str, dict] = {}
        for h in self._history:
            for a in h["members"]:
                if a not in agent_stats:
                    agent_stats[a] = {"total": 0, "success": 0}
                agent_stats[a]["total"] += 1
                if h["success"]:
                    agent_stats[a]["success"] += 1

        return sorted(
            [
                {
                    "agent": a,
                    "total": s["total"],
                    "success_rate": round(s["success"] / s["total"] * 100, 1),
                }
                for a, s in agent_stats.items()
            ],
            key=lambda x: x["success_rate"],
            reverse=True,
        )[:5]


_crew_engine: CrewEngine | None = None


def get_crew_engine() -> CrewEngine:
    global _crew_engine
    if _crew_engine is None:
        _crew_engine = CrewEngine()
    return _crew_engine
