#!/usr/bin/env python3
"""
Creative Studio — Content & Asset Production Pipeline

Uses: .agent/agents/frontend-specialist.md
Skills: frontend-design, web-design-guidelines
"""

from __future__ import annotations

from typing import Any
from studios.base_studio import BaseStudio


class Studio(BaseStudio):
    name = "creative"
    description = "Content creation, design assets, landings, scripts, materials"
    agent_ref = "frontend-specialist"
    skills_refs = ["frontend-design", "web-design-guidelines"]

    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        task_lower = task.lower()
        operation = "content"
        if any(w in task_lower for w in ["landing", "page", "web"]):
            operation = "landing_page"
        elif any(w in task_lower for w in ["email", "template", "plantilla"]):
            operation = "email_template"
        elif any(w in task_lower for w in ["copy", "text", "texto", "headline"]):
            operation = "copywriting"
        elif any(w in task_lower for w in ["script", "guión", "guion", "video"]):
            operation = "script"
        elif any(w in task_lower for w in ["social", "post", "instagram", "linkedin"]):
            operation = "social_content"
        elif any(w in task_lower for w in ["design", "diseño", "asset", "visual"]):
            operation = "design_brief"

        return {"task": task, "description": description, "operation": operation}

    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        op = intake_result["operation"]
        steps = {
            "content": [
                "Understand brief and target audience",
                "Research tone, style, and competitive examples",
                "Create content outline",
                "Write/produce content",
                "Review and polish",
            ],
            "landing_page": [
                "Define page objective and conversion goal",
                "Plan page structure (hero, benefits, CTA, social proof)",
                "Write all page copy",
                "Create HTML/CSS structure",
                "Optimize for mobile and SEO",
            ],
            "email_template": [
                "Define email objective and audience segment",
                "Write subject line variations",
                "Create email body copy",
                "Design layout structure",
                "Add CTA and tracking links",
            ],
            "copywriting": [
                "Understand message objective",
                "Research audience language and pain points",
                "Write multiple variations",
                "Apply AIDA/PAS framework",
                "A/B test recommendations",
            ],
            "script": [
                "Define video/audio objective",
                "Write script outline with timing",
                "Create full script with stage directions",
                "Include visual cues and transitions",
                "Review for pacing and clarity",
            ],
            "social_content": [
                "Define content pillar and platform",
                "Create post copy with hashtags",
                "Design visual brief/description",
                "Write engagement hooks",
                "Schedule recommendations",
            ],
            "design_brief": [
                "Define design objectives and constraints",
                "Create mood board directions",
                "Specify dimensions and format requirements",
                "Write creative brief document",
                "Set revision process",
            ],
        }
        return {**intake_result, "steps": steps.get(op, steps["content"])}

    def execute(
        self, plan: dict[str, Any], task_id: int | None = None
    ) -> dict[str, Any]:
        skills_context = self.get_skill_content("frontend-design")[:800]

        prompt = (
            f"## Creative Task — {plan['operation'].upper()}\n"
            f"**Task:** {plan['task']}\n"
            f"**Description:** {plan.get('description', '')}\n\n"
            f"## Steps\n"
            + "\n".join(f"- {s}" for s in plan["steps"])
            + f"\n\n## Design Context\n{skills_context}\n\n"
            "Produce the complete creative deliverable. If it's a landing page, "
            "include full HTML. If it's copy, provide multiple variations. "
            "Make it production-ready and compelling."
        )

        output = self.ai_call(prompt, task_id=task_id)
        return {
            "output": output,
            "operation": plan["operation"],
            "kpis": [
                {
                    "name": f"creative_{plan['operation']}_completed",
                    "value": 1,
                    "unit": "count",
                },
            ],
        }
