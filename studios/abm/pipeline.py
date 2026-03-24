#!/usr/bin/env python3
"""
ABM Studio — Account-Based Marketing Pipeline

Uses: .agent/agents/product-manager.md
Skills: brainstorming, plan-writing
"""

from __future__ import annotations

from typing import Any
from studios.base_studio import BaseStudio


class Studio(BaseStudio):
    name = "abm"
    description = "Account-based marketing: targeting, ICP, decisors, personalization"
    agent_ref = "product-manager"
    skills_refs = ["brainstorming", "plan-writing"]

    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        task_lower = task.lower()
        operation = "targeting"
        if any(w in task_lower for w in ["icp", "persona", "profile"]):
            operation = "icp_definition"
        elif any(w in task_lower for w in ["research", "investigate", "analiz"]):
            operation = "account_research"
        elif any(w in task_lower for w in ["personalize", "personal", "custom"]):
            operation = "personalization"
        elif any(w in task_lower for w in ["campaign", "play", "playbook"]):
            operation = "campaign_design"

        return {"task": task, "description": description, "operation": operation}

    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        op = intake_result["operation"]
        steps = {
            "targeting": [
                "Define target account criteria",
                "Build tiered account list (Tier 1/2/3)",
                "Map decision makers per account",
                "Prioritize by fit and intent signals",
            ],
            "icp_definition": [
                "Analyze best current customers",
                "Identify common firmographic patterns",
                "Define technographic signals",
                "Create ICP scoring model",
                "Document buyer personas with pain points",
            ],
            "account_research": [
                "Deep-dive on target accounts",
                "Map org structure and decision process",
                "Identify trigger events and timing",
                "Find personalization hooks",
                "Prepare account briefing document",
            ],
            "personalization": [
                "Analyze account-specific pain points",
                "Create personalized value propositions",
                "Design custom content/assets",
                "Plan personalized outreach sequence",
                "Set up 1:1 landing pages if needed",
            ],
            "campaign_design": [
                "Define ABM campaign objectives",
                "Select channel mix (email, ads, events, direct)",
                "Create account-specific content plan",
                "Design measurement framework",
                "Set up execution timeline",
            ],
        }
        return {**intake_result, "steps": steps.get(op, steps["targeting"])}

    def execute(
        self, plan: dict[str, Any], task_id: int | None = None
    ) -> dict[str, Any]:
        prompt = (
            f"## ABM Task — {plan['operation'].upper()}\n"
            f"**Task:** {plan['task']}\n"
            f"**Description:** {plan.get('description', '')}\n\n"
            f"## Steps\n"
            + "\n".join(f"- {s}" for s in plan["steps"])
            + "\n\nProvide a detailed ABM deliverable with account-specific strategies, "
            "templates, scoring criteria, and actionable next steps."
        )

        output = self.ai_call(prompt, task_id=task_id)
        return {
            "output": output,
            "operation": plan["operation"],
            "kpis": [
                {
                    "name": f"abm_{plan['operation']}_completed",
                    "value": 1,
                    "unit": "count",
                },
            ],
        }
