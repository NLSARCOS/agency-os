#!/usr/bin/env python3
"""
Agency OS v5.0 — Initiative Engine (Proactive Agency)

The engine that makes Agency OS HUNT for work:

  "Nobody gave us a task? Let's FIND one."

  1. SCAN   — Research trends, markets, competitor gaps
  2. IDEATE — Generate solution proposals
  3. PITCH  — Present opportunity to owner for approval
  4. EXECUTE — Build the solution (via Project Manager)
  5. SELL   — Create outreach to sell it

This is what separates an agency from a tool.
A tool waits. An agency HUSTLES.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus

logger = logging.getLogger("agency.initiative")


@dataclass
class Opportunity:
    """A proactively identified business opportunity."""

    id: str = field(default_factory=lambda: uuid4().hex[:10])
    title: str = ""
    problem: str = ""
    target_market: str = ""
    proposed_solution: str = ""
    estimated_value: str = ""  # e.g., "$5,000 - $15,000"
    confidence: int = 0  # 0-100 how confident we are this will sell
    source: str = ""  # trend | competitor | market_gap | client_need
    status: str = "identified"  # identified | pitched | approved | building | selling | sold | rejected
    owner_notes: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class Initiative:
    """A full initiative: opportunity → solution → sales effort."""

    id: str = field(default_factory=lambda: uuid4().hex[:10])
    opportunity: Opportunity = field(default_factory=Opportunity)
    solution_plan: dict[str, Any] = field(default_factory=dict)
    project_id: str = ""  # Links to Project Manager
    sales_plan: dict[str, Any] = field(default_factory=dict)
    status: str = "planning"  # planning | approved | executing | selling | completed
    revenue: float = 0.0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Opportunity Templates ────────────────────────────────
# Pre-built patterns the agency knows how to scan for

OPPORTUNITY_SCANNERS: list[dict] = [
    {
        "name": "landing_page_gaps",
        "description": "Businesses with outdated or no landing pages",
        "target_market": "Small businesses, startups, local services",
        "solution_type": "Modern landing page + SEO",
        "estimated_value": "$1,000 - $5,000",
        "prompt": (
            "Identify 3 types of businesses that commonly need better landing pages. "
            "For each, describe: the typical problem, who the buyer is, "
            "and what a modern solution would include. Be specific."
        ),
    },
    {
        "name": "automation_opportunities",
        "description": "Repetitive processes that could be automated",
        "target_market": "SMBs with manual workflows",
        "solution_type": "Custom automation scripts/tools",
        "estimated_value": "$2,000 - $10,000",
        "prompt": (
            "Identify 3 common business processes that are still done manually "
            "and could be automated. For each, describe: the time wasted, "
            "the automation solution, and the ROI for the client."
        ),
    },
    {
        "name": "saas_micro_products",
        "description": "Small SaaS tools for niche problems",
        "target_market": "Niche professionals (dentists, trainers, etc.)",
        "solution_type": "Micro-SaaS web app",
        "estimated_value": "$5,000 - $20,000 + MRR",
        "prompt": (
            "Identify 3 niche professional groups that lack good software tools. "
            "For each, describe: the unmet need, what a simple SaaS solution "
            "would do, and the pricing model."
        ),
    },
    {
        "name": "content_marketing_gaps",
        "description": "Companies with weak content strategy",
        "target_market": "B2B SaaS, agencies, consultants",
        "solution_type": "Content strategy + execution",
        "estimated_value": "$2,000 - $8,000/month",
        "prompt": (
            "Identify 3 types of B2B companies that struggle with content marketing. "
            "For each, describe: what they're doing wrong, what a proper strategy "
            "looks like, and the expected results."
        ),
    },
    {
        "name": "ecommerce_optimization",
        "description": "Online stores losing sales to poor UX",
        "target_market": "E-commerce businesses with $10K-$500K monthly revenue",
        "solution_type": "UX audit + conversion optimization",
        "estimated_value": "$3,000 - $15,000",
        "prompt": (
            "Identify 3 common conversion killers in e-commerce sites. "
            "For each, describe: the problem, the fix, and the expected "
            "revenue lift."
        ),
    },
]


class InitiativeEngine:
    """
    The proactive brain: Agency OS hunts for business.

    Instead of waiting for tasks, the initiative engine:
    1. Scans for market opportunities
    2. Generates solution proposals
    3. Presents to owner for approval
    4. Builds the solution
    5. Creates sales outreach

    Everything requires owner approval before spending resources.
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._bus = get_event_bus()
        self._opportunities: list[Opportunity] = []
        self._initiatives: list[Initiative] = []

    # ── 1. SCAN FOR OPPORTUNITIES ─────────────────────────────

    def scan_opportunities(
        self,
        scanner_name: str = "",
        use_ai: bool = True,
    ) -> list[Opportunity]:
        """
        Proactively scan for business opportunities.

        If AI is available: uses AI to research and identify opportunities.
        If not: uses pre-built opportunity templates.
        """
        opportunities = []

        scanners = OPPORTUNITY_SCANNERS
        if scanner_name:
            scanners = [s for s in scanners if s["name"] == scanner_name]

        for scanner in scanners:
            if use_ai:
                # Try AI-powered scanning
                opp = self._ai_scan(scanner)
                if opp:
                    opportunities.append(opp)
                    continue

            # Fallback: template-based opportunity
            opp = Opportunity(
                title=scanner["description"],
                problem=f"Market gap: {scanner['description']}",
                target_market=scanner["target_market"],
                proposed_solution=scanner["solution_type"],
                estimated_value=scanner["estimated_value"],
                confidence=65,
                source="market_gap",
            )
            opportunities.append(opp)

        self._opportunities.extend(opportunities)

        self._bus.publish_sync(
            Event(
                type="initiative.scan_complete",
                source="initiative_engine",
                payload={
                    "opportunities_found": len(opportunities),
                    "scanner": scanner_name or "all",
                },
            )
        )

        logger.info("Scan found %d opportunities", len(opportunities))
        return opportunities

    def _ai_scan(self, scanner: dict) -> Opportunity | None:
        """Use AI to identify specific opportunities."""
        try:
            from kernel.openclaw_bridge import get_openclaw

            oc = get_openclaw()
            response = oc.ask(
                prompt=scanner["prompt"],
                system=(
                    "You are a business development AI for a digital agency. "
                    "Identify real, actionable opportunities. Be specific about "
                    "who would pay and how much. No generic advice."
                ),
                agent_id="initiative-scanner",
            )

            if response:
                return Opportunity(
                    title=scanner["description"],
                    problem=response[:500],
                    target_market=scanner["target_market"],
                    proposed_solution=scanner["solution_type"],
                    estimated_value=scanner["estimated_value"],
                    confidence=75,
                    source="ai_research",
                )
        except Exception as e:
            logger.debug("AI scan failed: %s", e)

        return None

    # ── 2. GENERATE SOLUTION PROPOSAL ─────────────────────────

    def propose_solution(
        self,
        opportunity_id: str,
    ) -> Initiative:
        """
        Generate a detailed solution proposal for an opportunity.

        Creates the full plan: what to build, how to sell it,
        estimated timeline, and pricing.
        """
        opp = next(
            (o for o in self._opportunities if o.id == opportunity_id),
            None,
        )
        if not opp:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        # Build solution plan
        solution = {
            "opportunity": opp.title,
            "problem": opp.problem[:300],
            "solution": opp.proposed_solution,
            "target": opp.target_market,
            "phases": self._plan_phases(opp),
            "timeline": "2-4 weeks",
            "pricing": opp.estimated_value,
        }

        # Build sales plan
        sales = {
            "outreach_channels": ["email", "linkedin", "cold_call"],
            "target_personas": self._identify_personas(opp),
            "pitch": self._generate_pitch(opp),
            "follow_up_cadence": "Day 1, Day 3, Day 7, Day 14",
        }

        initiative = Initiative(
            opportunity=opp,
            solution_plan=solution,
            sales_plan=sales,
            status="planning",
        )

        self._initiatives.append(initiative)
        opp.status = "pitched"

        self._bus.publish_sync(
            Event(
                type="initiative.proposed",
                source="initiative_engine",
                payload={
                    "initiative_id": initiative.id,
                    "opportunity": opp.title[:100],
                    "value": opp.estimated_value,
                },
            )
        )

        return initiative

    def _plan_phases(self, opp: Opportunity) -> list[dict]:
        """Plan the execution phases for a solution."""
        solution_type = opp.proposed_solution.lower()

        if (
            "landing" in solution_type
            or "web" in solution_type
            or "page" in solution_type
        ):
            return [
                {
                    "phase": 1,
                    "studio": "creative",
                    "task": "Design and copy",
                    "days": 3,
                },
                {"phase": 2, "studio": "dev", "task": "Build and deploy", "days": 5},
                {"phase": 3, "studio": "marketing", "task": "SEO + launch", "days": 3},
            ]
        elif "automation" in solution_type or "script" in solution_type:
            return [
                {
                    "phase": 1,
                    "studio": "analytics",
                    "task": "Process analysis",
                    "days": 2,
                },
                {"phase": 2, "studio": "dev", "task": "Build automation", "days": 7},
                {
                    "phase": 3,
                    "studio": "analytics",
                    "task": "ROI measurement",
                    "days": 2,
                },
            ]
        elif "saas" in solution_type or "app" in solution_type:
            return [
                {
                    "phase": 1,
                    "studio": "analytics",
                    "task": "Market research",
                    "days": 3,
                },
                {"phase": 2, "studio": "creative", "task": "UX/UI design", "days": 5},
                {"phase": 3, "studio": "dev", "task": "Build MVP", "days": 10},
                {
                    "phase": 4,
                    "studio": "marketing",
                    "task": "Launch campaign",
                    "days": 5,
                },
                {"phase": 5, "studio": "sales", "task": "First customers", "days": 7},
            ]
        elif "content" in solution_type:
            return [
                {
                    "phase": 1,
                    "studio": "analytics",
                    "task": "Audience research",
                    "days": 2,
                },
                {
                    "phase": 2,
                    "studio": "creative",
                    "task": "Content strategy",
                    "days": 3,
                },
                {
                    "phase": 3,
                    "studio": "marketing",
                    "task": "Content creation + distribution",
                    "days": 10,
                },
            ]
        else:
            return [
                {"phase": 1, "studio": "analytics", "task": "Research", "days": 3},
                {"phase": 2, "studio": "dev", "task": "Build solution", "days": 7},
                {"phase": 3, "studio": "sales", "task": "Sell to clients", "days": 5},
            ]

    def _identify_personas(self, opp: Opportunity) -> list[str]:
        """Identify buyer personas for the opportunity."""
        market = opp.target_market.lower()
        personas = []

        if "small business" in market or "local" in market:
            personas.extend(["Small business owner", "Office manager"])
        if "startup" in market:
            personas.extend(["Founder/CEO", "CTO", "Head of Growth"])
        if "saas" in market or "b2b" in market:
            personas.extend(["VP Marketing", "Head of Product", "CMO"])
        if "ecommerce" in market or "e-commerce" in market:
            personas.extend(["E-commerce manager", "DTC brand founder"])
        if not personas:
            personas = ["Decision maker", "Business owner"]

        return personas[:3]

    def _generate_pitch(self, opp: Opportunity) -> str:
        """Generate a one-paragraph sales pitch."""
        return (
            f"We help {opp.target_market} solve {opp.problem[:100]}. "
            f"Our solution: {opp.proposed_solution}. "
            f"Typical investment: {opp.estimated_value}. "
            f"We handle everything end-to-end — design, build, launch."
        )

    # ── 3. APPROVAL GATE ──────────────────────────────────────

    def approve_initiative(
        self,
        initiative_id: str,
        notes: str = "",
    ) -> Initiative:
        """Owner approves an initiative to proceed."""
        init = next(
            (i for i in self._initiatives if i.id == initiative_id),
            None,
        )
        if not init:
            raise ValueError(f"Initiative {initiative_id} not found")

        init.status = "approved"
        init.opportunity.status = "approved"
        init.opportunity.owner_notes = notes

        self._bus.publish_sync(
            Event(
                type="initiative.approved",
                source="initiative_engine",
                payload={
                    "initiative_id": init.id,
                    "opportunity": init.opportunity.title,
                },
            )
        )

        logger.info("Initiative approved: %s", init.opportunity.title)
        return init

    def reject_initiative(
        self,
        initiative_id: str,
        reason: str = "",
    ) -> Initiative:
        """Owner rejects an initiative."""
        init = next(
            (i for i in self._initiatives if i.id == initiative_id),
            None,
        )
        if not init:
            raise ValueError(f"Initiative {initiative_id} not found")

        init.status = "rejected"
        init.opportunity.status = "rejected"
        init.opportunity.owner_notes = reason

        logger.info("Initiative rejected: %s — %s", init.opportunity.title, reason)
        return init

    # ── 4. EXECUTE (after approval) ───────────────────────────

    def execute_initiative(
        self,
        initiative_id: str,
    ) -> dict[str, Any]:
        """
        Execute an approved initiative through Project Manager.

        Only runs after owner approval.
        """
        init = next(
            (i for i in self._initiatives if i.id == initiative_id),
            None,
        )
        if not init:
            raise ValueError(f"Initiative {initiative_id} not found")

        if init.status != "approved":
            raise ValueError(
                f"Initiative must be approved first (current: {init.status})"
            )

        init.status = "executing"

        try:
            from kernel.project_manager import get_project_manager

            pm = get_project_manager()

            goal = (
                f"{init.opportunity.proposed_solution} for "
                f"{init.opportunity.target_market}: {init.opportunity.title}"
            )

            project = pm.plan_project(goal)
            init.project_id = project.id

            self._bus.publish_sync(
                Event(
                    type="initiative.executing",
                    source="initiative_engine",
                    payload={
                        "initiative_id": init.id,
                        "project_id": project.id,
                        "phases": len(project.phases),
                    },
                )
            )

            return {
                "initiative_id": init.id,
                "project_id": project.id,
                "phases": [
                    {"studio": p.studio, "task": p.task[:80]} for p in project.phases
                ],
                "status": "executing",
            }

        except Exception as e:
            init.status = "failed"
            logger.error("Initiative execution failed: %s", e)
            return {"error": str(e)}

    # ── 5. FULL PROACTIVE CYCLE ───────────────────────────────

    def hustle(
        self,
        scanner_name: str = "",
    ) -> dict[str, Any]:
        """
        Full proactive cycle: scan → propose → present for approval.

        Finds opportunities and prepares pitches.
        Does NOT execute — waits for owner approval.
        """
        start = time.monotonic()

        # 1. Scan
        opportunities = self.scan_opportunities(scanner_name)

        # 2. Propose solutions for each
        initiatives = []
        for opp in opportunities:
            try:
                init = self.propose_solution(opp.id)
                initiatives.append(init)
            except Exception as e:
                logger.error("Failed to propose for %s: %s", opp.title, e)

        duration = (time.monotonic() - start) * 1000

        return {
            "opportunities_found": len(opportunities),
            "initiatives_created": len(initiatives),
            "pending_approval": [
                {
                    "id": init.id,
                    "title": init.opportunity.title,
                    "market": init.opportunity.target_market,
                    "value": init.opportunity.estimated_value,
                    "confidence": init.opportunity.confidence,
                    "phases": len(init.solution_plan.get("phases", [])),
                    "pitch": init.sales_plan.get("pitch", "")[:200],
                }
                for init in initiatives
            ],
            "duration_ms": duration,
        }

    # ── Status & Pipeline ─────────────────────────────────────

    def get_pipeline(self) -> dict[str, Any]:
        """Get the full sales pipeline status."""
        by_status = {}  # type: ignore
        for init in self._initiatives:
            by_status.setdefault(init.status, []).append(
                {
                    "id": init.id,
                    "title": init.opportunity.title[:60],
                    "value": init.opportunity.estimated_value,
                    "confidence": init.opportunity.confidence,
                }
            )

        total_potential = sum(
            self._parse_value(init.opportunity.estimated_value)
            for init in self._initiatives
            if init.status not in ("rejected",)
        )

        return {
            "total_opportunities": len(self._opportunities),
            "total_initiatives": len(self._initiatives),
            "pipeline": by_status,
            "total_potential_value": f"${total_potential:,.0f}",
        }

    def _parse_value(self, value_str: str) -> float:
        """Parse estimated value string to number (takes midpoint)."""
        import re

        numbers = re.findall(r"[\d,]+", value_str.replace(",", ""))
        if len(numbers) >= 2:
            return (float(numbers[0]) + float(numbers[1])) / 2
        elif numbers:
            return float(numbers[0])
        return 0

    def list_pending_approvals(self) -> list[dict]:
        """List all initiatives awaiting owner approval."""
        return [
            {
                "id": init.id,
                "title": init.opportunity.title,
                "market": init.opportunity.target_market,
                "value": init.opportunity.estimated_value,
                "confidence": init.opportunity.confidence,
                "pitch": init.sales_plan.get("pitch", "")[:200],
                "phases": init.solution_plan.get("phases", []),
            }
            for init in self._initiatives
            if init.status == "planning"
        ]


_engine: InitiativeEngine | None = None


def get_initiative_engine() -> InitiativeEngine:
    global _engine
    if _engine is None:
        _engine = InitiativeEngine()
    return _engine
