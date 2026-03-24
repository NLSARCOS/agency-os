#!/usr/bin/env python3
"""
Marketing Studio — Campaign & Strategy Pipeline

Uses: .agent/agents/product-manager.md
Skills: seo-fundamentals, frontend-design, brainstorming
"""

from __future__ import annotations

from typing import Any
from studios.base_studio import BaseStudio


class Studio(BaseStudio):
    name = "marketing"
    description = "Campaigns, positioning, funnels, content strategy, CRO"
    agent_ref = "product-manager"
    skills_refs = ["seo-fundamentals", "frontend-design", "brainstorming"]

    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        task_lower = task.lower()
        operation = "strategy"
        if any(w in task_lower for w in ["campaign", "campaña", "ads", "ad"]):
            operation = "campaign"
        elif any(w in task_lower for w in ["seo", "positioning", "posicionamiento"]):
            operation = "seo"
        elif any(w in task_lower for w in ["funnel", "landing", "conversion", "cro"]):
            operation = "funnel"
        elif any(w in task_lower for w in ["content", "blog", "newsletter", "copy"]):
            operation = "content"
        elif any(w in task_lower for w in ["social", "rrss", "instagram", "linkedin"]):
            operation = "social"
        elif any(w in task_lower for w in ["brand", "marca", "branding"]):
            operation = "branding"

        return {
            "task": task,
            "description": description,
            "operation": operation,
        }

    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        op = intake_result["operation"]
        steps = {
            "strategy": [
                "Market research and competitor analysis",
                "Define ICP and buyer personas",
                "Positioning and value proposition",
                "Channel strategy (organic, paid, referral)",
                "Go-to-market plan with timelines",
            ],
            "campaign": [
                "Define campaign objective and KPIs",
                "Target audience segmentation",
                "Create ad copy and creatives brief",
                "Set budget and bid strategy",
                "Launch plan and A/B test design",
            ],
            "seo": [
                "Keyword research and opportunity analysis",
                "On-page optimization checklist",
                "Technical SEO audit",
                "Content gap analysis",
                "Link building strategy",
            ],
            "funnel": [
                "Map customer journey stages",
                "Design landing page structure",
                "Create lead capture mechanism",
                "Email nurture sequence",
                "Conversion optimization plan",
            ],
            "content": [
                "Content audit and gap analysis",
                "Editorial calendar planning",
                "Content creation guidelines",
                "Distribution strategy",
                "Performance measurement plan",
            ],
            "social": [
                "Platform strategy and priorities",
                "Content pillars and themes",
                "Posting schedule",
                "Engagement response plan",
                "Growth and community building tactics",
            ],
            "branding": [
                "Brand audit and current perception",
                "Value proposition canvas",
                "Visual identity guidelines",
                "Messaging framework",
                "Brand consistency checklist",
            ],
        }
        return {**intake_result, "steps": steps.get(op, steps["strategy"])}

    def execute(
        self, plan: dict[str, Any], task_id: int | None = None
    ) -> dict[str, Any]:
        prompt = (
            f"## Marketing Task — {plan['operation'].upper()}\n"
            f"**Task:** {plan['task']}\n"
            f"**Description:** {plan.get('description', 'N/A')}\n\n"
            f"## Execution Steps\n"
            + "\n".join(f"- {s}" for s in plan["steps"])
            + "\n\nProvide a comprehensive, actionable marketing deliverable. "
            "Include specific recommendations, copy examples, and metrics to track."
        )

        output = self.ai_call(prompt, task_id=task_id)
        return {
            "output": output,
            "operation": plan["operation"],
            "kpis": [
                {"name": f"{plan['operation']}_completed", "value": 1, "unit": "count"},
            ],
        }
