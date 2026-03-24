"""
Agency OS — Mission Planner

Takes ONE simple prompt and decomposes it into multiple coordinated
sub-missions across studios with dependency chains.

Example: "Crear una página web que llame personas y venderla"
  → DEV: build the webpage
  → MARKETING: create pitch/copy materials  (depends on DEV)
  → SALES: outreach strategy               (depends on MARKETING)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from kernel.config import get_config
from kernel.model_router import ModelRouter
from kernel.mission_engine import MissionEngine

logger = logging.getLogger("agency.planner")

STUDIOS = ["dev", "marketing", "sales", "leadops", "abm", "analytics", "creative"]

DECOMPOSITION_PROMPT = """You are the Mission Planner of an AI agency with 7 specialized studios:
- DEV: software development, web, APIs, automation
- MARKETING: campaigns, copy, funnels, positioning, content
- SALES: outreach, pitching, closing, proposals, commercial
- LEADOPS: lead generation, scraping, enrichment, prospecting
- ABM: account-based marketing, targeting, ICP, personalization
- ANALYTICS: reports, KPIs, dashboards, data analysis
- CREATIVE: design, visual assets, branding, UI/UX

Given this objective from the owner, decompose it into sub-missions for the relevant studios.
Each sub-mission should specify:
- studio: which studio handles it
- name: short mission name
- description: what to do (detailed, actionable)
- depends_on: list of studio names this depends on (empty if independent)
- priority: 1 (highest) to 5 (lowest)

RULES:
1. Only include studios that are ACTUALLY needed. Don't force all 7.
2. Dependencies define execution ORDER. Independent studios run in PARALLEL.
3. Be SPECIFIC in descriptions — the studio agents need clear instructions.
4. Output ONLY valid JSON array, no markdown, no explanation.

OBJECTIVE: {objective}

Respond with a JSON array of sub-missions:
[{{"studio": "dev", "name": "...", "description": "...", "depends_on": [], "priority": 1}}, ...]"""


@dataclass
class PlannedMission:
    studio: str
    name: str
    description: str
    depends_on: list[str] = field(default_factory=list)
    priority: int = 3
    mission_id: int | None = None


class MissionPlanner:
    """Decomposes a prompt into coordinated multi-studio missions."""

    def __init__(self) -> None:
        self._cfg = get_config()
        self._router = ModelRouter()
        self._engine = MissionEngine()

    async def plan(self, objective: str) -> list[PlannedMission]:
        """Use AI to decompose an objective into sub-missions."""
        prompt = DECOMPOSITION_PROMPT.format(objective=objective)

        logger.info("Planning objective: %s", objective[:80])

        resp = await self._router.call_model(
            studio="analytics",  # Use analytics pool for planning
            prompt=prompt,
            system="You are a strategic mission planner. Output only valid JSON.",
        )

        # Parse AI response
        try:
            raw = resp.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw.rsplit("```", 1)[0]
            missions_data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Failed to parse AI plan: %s", resp.content[:200])
            # Fallback: single mission to default studio
            missions_data = [
                {
                    "studio": "dev",
                    "name": objective[:60],
                    "description": objective,
                    "depends_on": [],
                    "priority": 1,
                }
            ]

        # Validate and build missions
        planned = []
        for m in missions_data:
            studio = m.get("studio", "dev").lower()
            if studio not in STUDIOS:
                studio = "dev"
            planned.append(
                PlannedMission(
                    studio=studio,
                    name=m.get("name", "Untitled"),
                    description=m.get("description", objective),
                    depends_on=[
                        d.lower()
                        for d in m.get("depends_on", [])
                        if d.lower() in STUDIOS
                    ],
                    priority=min(max(int(m.get("priority", 3)), 1), 5),
                )
            )

        logger.info(
            "Plan generated: %d sub-missions across %d studios",
            len(planned),
            len(set(m.studio for m in planned)),
        )
        return planned

    def enqueue(self, planned: list[PlannedMission], objective: str) -> list[int]:
        """Submit all planned missions to the engine with proper ordering."""
        # Resolve execution waves based on dependencies
        waves = self._build_waves(planned)
        mission_ids = []

        for wave_num, wave in enumerate(waves, 1):
            for mission in wave:
                mid = self._engine.submit_mission(
                    name=f"[{mission.studio.upper()}] {mission.name}",
                    description=(
                        f"Part of objective: {objective}\n\n"
                        f"{mission.description}\n\n"
                        f"Wave: {wave_num}/{len(waves)} | "
                        f"Dependencies: {', '.join(mission.depends_on) or 'none'}"
                    ),
                    priority=mission.priority
                    + (wave_num - 1),  # Later waves get lower priority
                    force_studio=mission.studio,
                    metadata={
                        "planner": "mission_planner",
                        "objective": objective[:200],
                        "objective_id": hashlib.md5(objective.encode()).hexdigest()[
                            :12
                        ],
                        "wave": wave_num,
                        "total_waves": len(waves),
                        "total_missions": len(planned),
                        "depends_on": mission.depends_on,
                    },
                )
                mission.mission_id = mid
                mission_ids.append(mid)
                logger.info(
                    "Queued mission #%d: [%s] %s (wave %d, priority %d)",
                    mid,
                    mission.studio,
                    mission.name,
                    wave_num,
                    mission.priority,
                )

        return mission_ids

    async def plan_and_execute(self, objective: str) -> dict[str, Any]:
        """Full pipeline: prompt → plan → enqueue → summary."""
        planned = await self.plan(objective)
        mission_ids = self.enqueue(planned, objective)

        studios_involved = list(set(m.studio for m in planned))
        waves = self._build_waves(planned)

        return {
            "objective": objective,
            "sub_missions": len(planned),
            "studios": studios_involved,
            "waves": len(waves),
            "mission_ids": mission_ids,
            "plan": [
                {
                    "studio": m.studio,
                    "name": m.name,
                    "description": m.description[:100],
                    "depends_on": m.depends_on,
                    "priority": m.priority,
                    "mission_id": m.mission_id,
                }
                for m in planned
            ],
        }

    def _build_waves(
        self, missions: list[PlannedMission]
    ) -> list[list[PlannedMission]]:
        """Build execution waves from dependency graph."""
        resolved: set[str] = set()
        remaining = list(missions)
        waves: list[list[PlannedMission]] = []

        max_iter = len(missions) + 1
        for _ in range(max_iter):
            if not remaining:
                break

            # Find missions whose dependencies are all resolved
            wave = [m for m in remaining if all(d in resolved for d in m.depends_on)]

            if not wave:
                # Deadlock — force remaining into last wave
                wave = remaining[:]

            waves.append(wave)
            for m in wave:
                resolved.add(m.studio)
                remaining.remove(m)

        return waves
