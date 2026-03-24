#!/usr/bin/env python3
"""
Sales Studio — Outreach & Pipeline

Uses: .agent/agents/product-owner.md
Skills: brainstorming, plan-writing
"""

from __future__ import annotations

from typing import Any
from studios.base_studio import BaseStudio


class Studio(BaseStudio):
    name = "sales"
    description = "Outreach, follow-up, closing, commercial pipeline"
    agent_ref = "product-owner"
    skills_refs = ["brainstorming", "plan-writing"]

    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        task_lower = task.lower()
        operation = "outreach"
        if any(w in task_lower for w in ["close", "closing", "deal", "cerrar"]):
            operation = "closing"
        elif any(w in task_lower for w in ["follow", "followup", "seguimiento"]):
            operation = "followup"
        elif any(
            w in task_lower for w in ["proposal", "propuesta", "quote", "cotización"]
        ):
            operation = "proposal"
        elif any(w in task_lower for w in ["sequence", "cadence", "secuencia"]):
            operation = "sequence"
        elif any(w in task_lower for w in ["pipeline", "crm", "deal"]):
            operation = "pipeline"

        return {"task": task, "description": description, "operation": operation}

    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        op = intake_result["operation"]
        steps = {
            "outreach": [
                "Define outreach target list",
                "Research prospects and personalization hooks",
                "Craft outreach messages (email/LinkedIn/call)",
                "Set up multi-touch sequence",
                "Track response metrics",
            ],
            "closing": [
                "Review deal history and stakeholders",
                "Prepare closing arguments and value summary",
                "Handle objections preparation",
                "Create contract/proposal draft",
                "Set follow-up schedule",
            ],
            "followup": [
                "Review pending follow-ups",
                "Prioritize by deal value and urgency",
                "Craft personalized follow-up messages",
                "Update CRM/pipeline status",
                "Report on follow-up outcomes",
            ],
            "proposal": [
                "Analyze client requirements",
                "Design solution scope",
                "Calculate pricing and ROI projection",
                "Write proposal document",
                "Create presentation deck outline",
            ],
            "sequence": [
                "Define sequence objective and audience",
                "Map touchpoint cadence (day 1, 3, 7, 14)",
                "Write email templates for each step",
                "Set up automation triggers",
                "Define exit criteria and escalation",
            ],
            "pipeline": [
                "Audit current pipeline stages",
                "Identify stuck deals and blockers",
                "Forecast revenue by stage",
                "Create action items for each deal",
                "Report pipeline health metrics",
            ],
        }
        return {**intake_result, "steps": steps.get(op, steps["outreach"])}

    def execute(
        self, plan: dict[str, Any], task_id: int | None = None
    ) -> dict[str, Any]:
        prompt = (
            f"## Sales Task — {plan['operation'].upper()}\n"
            f"**Task:** {plan['task']}\n"
            f"**Description:** {plan.get('description', 'N/A')}\n\n"
            f"## Steps\n"
            + "\n".join(f"- {s}" for s in plan["steps"])
            + "\n\nProvide actionable sales deliverables. Include specific email templates, "
            "call scripts, or proposal outlines as appropriate. Focus on conversion."
        )

        output = self.ai_call(prompt, task_id=task_id)
        return {
            "output": output,
            "operation": plan["operation"],
            "kpis": [
                {"name": f"{plan['operation']}_completed", "value": 1, "unit": "count"},
            ],
        }
