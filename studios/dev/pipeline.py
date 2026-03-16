#!/usr/bin/env python3
"""
Dev Studio — Software Development Pipeline

Uses: .agent/agents/backend-specialist.md, frontend-specialist.md
Skills: clean-code, api-patterns, testing-patterns, architecture
"""
from __future__ import annotations

from typing import Any
from studios.base_studio import BaseStudio


class Studio(BaseStudio):
    name = "dev"
    description = "Software development: architecture, implementation, QA, deployment"
    agent_ref = "backend-specialist"
    skills_refs = ["clean-code", "api-patterns", "testing-patterns", "architecture"]

    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        """Parse dev task: detect if it's a feature, bugfix, refactor, deploy."""
        task_lower = task.lower()
        task_type = "feature"
        if any(w in task_lower for w in ["bug", "fix", "error", "crash", "broken"]):
            task_type = "bugfix"
        elif any(w in task_lower for w in ["refactor", "clean", "optimize", "improve"]):
            task_type = "refactor"
        elif any(w in task_lower for w in ["deploy", "release", "ship", "launch"]):
            task_type = "deploy"
        elif any(w in task_lower for w in ["test", "qa", "coverage"]):
            task_type = "testing"

        return {
            "task": task,
            "description": description,
            "type": task_type,
            "priority": kwargs.get("priority", 5),
        }

    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        """Create dev execution plan using architecture skill."""
        task_type = intake_result["type"]

        steps = {
            "feature": [
                "Analyze requirements and constraints",
                "Design architecture/component structure",
                "Implement core functionality",
                "Write unit and integration tests",
                "Code review checklist",
                "Deploy/deliver",
            ],
            "bugfix": [
                "Reproduce and isolate the bug",
                "Root cause analysis",
                "Implement fix",
                "Write regression test",
                "Verify fix doesn't break existing functionality",
            ],
            "refactor": [
                "Analyze current code structure",
                "Identify improvement areas",
                "Apply clean code principles",
                "Verify no behavioral changes",
                "Update documentation",
            ],
            "deploy": [
                "Pre-deployment checklist",
                "Build and verify",
                "Deploy to staging/production",
                "Post-deployment verification",
                "Monitor for issues",
            ],
            "testing": [
                "Analyze test coverage gaps",
                "Design test strategy",
                "Write tests (unit, integration, e2e)",
                "Run full test suite",
                "Report coverage metrics",
            ],
        }

        return {
            **intake_result,
            "steps": steps.get(task_type, steps["feature"]),
            "agent": self.agent_ref,
            "skills": self.skills_refs,
        }

    def execute(self, plan: dict[str, Any], task_id: int | None = None) -> dict[str, Any]:
        """Execute the dev pipeline with real tool integration."""
        task_type = plan["type"]

        # Gather real project context
        git_context = self._get_git_context()

        skills_context = "\n".join(
            self.get_skill_content(s)[:500] for s in self.skills_refs[:2]
        )

        prompt = (
            f"## Dev Task\n"
            f"**Type:** {task_type}\n"
            f"**Task:** {plan['task']}\n"
            f"**Description:** {plan.get('description', 'N/A')}\n\n"
            f"## Git Context\n{git_context}\n\n"
            f"## Execution Steps\n"
            + "\n".join(f"- {s}" for s in plan["steps"])
            + f"\n\n## Skills Context\n{skills_context[:1000]}\n\n"
            f"Execute this task step by step. Provide concrete, actionable output "
            f"with code snippets, file changes, and commands to run."
        )

        output = self.ai_call(prompt, task_id=task_id)
        path = self.save_output(f"{task_type}_{plan['task'][:30].replace(' ', '_')}.md", output)

        return {
            "output": output,
            "type": plan["type"],
            "steps_executed": plan["steps"],
            "model_used": self.name,
            "artifacts": [str(path)],
            "kpis": [
                {"name": "tasks_completed", "value": 1, "unit": "count"},
                {"name": f"{plan['type']}_completed", "value": 1, "unit": "count"},
            ],
        }

    def _get_git_context(self) -> str:
        """Get real git context from the project."""
        parts = []
        try:
            status = self.shell("git status --short", cwd=str(self.cfg.root))
            if status and not status.startswith("Error"):
                parts.append(f"**Modified files:**\n```\n{status[:500]}\n```")

            branch = self.shell("git branch --show-current", cwd=str(self.cfg.root))
            if branch and not branch.startswith("Error"):
                parts.append(f"**Branch:** {branch.strip()}")

            log = self.shell("git log --oneline -5", cwd=str(self.cfg.root))
            if log and not log.startswith("Error"):
                parts.append(f"**Recent commits:**\n```\n{log[:300]}\n```")
        except Exception:
            parts.append("Git context unavailable")

        return "\n".join(parts) if parts else "No git context"
