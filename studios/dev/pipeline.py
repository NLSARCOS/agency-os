#!/usr/bin/env python3
"""
Dev Studio — Autonomous Software Development Pipeline

This studio BUILDS, not just suggests:
1. Debates architecture via AI
2. Generates actual code
3. Creates real files on disk
4. Runs build commands
5. Commits and pushes to git

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
        """Parse dev task: detect type and extract project context."""
        task_lower = task.lower()

        # Classify task type
        task_type = "feature"
        if any(w in task_lower for w in ["bug", "fix", "error", "crash", "broken"]):
            task_type = "bugfix"
        elif any(w in task_lower for w in ["refactor", "clean", "optimize", "improve"]):
            task_type = "refactor"
        elif any(w in task_lower for w in ["deploy", "release", "ship", "launch"]):
            task_type = "deploy"
        elif any(w in task_lower for w in ["test", "qa", "coverage"]):
            task_type = "testing"
        elif any(
            w in task_lower
            for w in [
                "web",
                "landing",
                "page",
                "site",
                "website",
                "app",
                "dashboard",
                "portal",
                "frontend",
            ]
        ):
            task_type = "webapp"

        # Detect target project dir
        project_dir = kwargs.get("project_dir", "")
        auto_git = kwargs.get("auto_git", False)

        return {
            "task": task,
            "description": description,
            "type": task_type,
            "project_dir": project_dir,
            "auto_git": auto_git,
            "priority": kwargs.get("priority", 5),
        }

    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        """Create execution plan with real steps."""
        task_type = intake_result["type"]

        steps = {
            "feature": [
                "Analyze requirements and constraints",
                "Design architecture/component structure",
                "Generate and CREATE all code files",
                "Run tests if applicable",
                "Commit changes to git",
            ],
            "bugfix": [
                "Analyze bug context from code",
                "Root cause analysis",
                "Generate and APPLY the fix",
                "Write regression test",
                "Verify fix and commit",
            ],
            "refactor": [
                "Analyze current code structure",
                "Identify improvement areas",
                "Apply clean code changes to REAL files",
                "Verify no behavioral changes",
                "Commit refactored code",
            ],
            "deploy": [
                "Pre-deployment checks",
                "Build and verify",
                "Deploy to target",
                "Post-deployment verification",
            ],
            "testing": [
                "Analyze test coverage gaps",
                "Generate test files",
                "CREATE test files on disk",
                "Run full test suite",
                "Report coverage metrics",
            ],
            "webapp": [
                "Debate architecture and tech stack",
                "Generate project structure",
                "CREATE all project files (HTML, CSS, JS, config)",
                "Install dependencies if needed",
                "Run dev server to verify",
                "Commit and push to GitHub",
            ],
        }

        return {
            **intake_result,
            "steps": steps.get(task_type, steps["feature"]),
            "agent": self.agent_ref,
            "skills": self.skills_refs,
        }

    def execute(
        self, plan: dict[str, Any], task_id: int | None = None
    ) -> dict[str, Any]:
        """Execute the dev pipeline — CREATE REAL FILES, not just markdown."""
        task_type = plan["type"]
        project_dir = plan.get("project_dir", "")
        auto_git = plan.get("auto_git", False)

        # Gather project context
        git_context = self._get_git_context()
        skills_context = "\n".join(
            self.get_skill_content(s)[:500] for s in self.skills_refs[:2]
        )

        # Build the execution prompt — instruct AI to include file paths
        prompt = self._build_executor_prompt(plan, git_context, skills_context)

        # Get AI response with actual code
        ai_output = self.ai_call(prompt, task_id=task_id)

        # Save the full AI plan/reasoning as report
        report_path = self.save_output(
            f"{task_type}_{plan['task'][:30].replace(' ', '_')}.md",
            ai_output,
        )

        # EXECUTE: Parse AI output → create REAL files, run commands
        action_result = self.execute_actions(
            ai_output=ai_output,
            project_dir=project_dir,
            auto_git=auto_git,
        )

        return {
            "output": ai_output,
            "type": plan["type"],
            "steps_executed": plan["steps"],
            "model_used": self.name,
            "artifacts": [str(report_path)] + action_result.get("files_created", []),
            "actions": action_result,
            "kpis": [
                {"name": "tasks_completed", "value": 1, "unit": "count"},
                {"name": f"{plan['type']}_completed", "value": 1, "unit": "count"},
                {
                    "name": "files_created",
                    "value": len(action_result.get("files_created", [])),
                    "unit": "count",
                },
                {
                    "name": "commands_run",
                    "value": len(action_result.get("commands_run", [])),
                    "unit": "count",
                },
            ],
        }

    def _build_executor_prompt(
        self,
        plan: dict,
        git_context: str,
        skills_context: str,
    ) -> str:
        """Build prompt that instructs AI to output actionable code with file paths."""
        task_type = plan["type"]

        # Core instruction for the AI to format output with file paths
        format_instructions = """
## CRITICAL OUTPUT FORMAT

You MUST format ALL code with file paths so the system can CREATE real files.
Use this format for EVERY file:

```language:path/to/filename.ext
// actual file content here
```

For example:
```html:index.html
<!DOCTYPE html>
<html>...
</html>
```

```css:styles/main.css
body { margin: 0; }
```

```javascript:src/app.js
console.log('Hello');
```

For shell commands to run:
```bash
npm init -y
npm install express
```

IMPORTANT: Include COMPLETE file contents, not snippets. Every code block MUST have a filepath.
"""

        prompt = (
            f"## Dev Task\n"
            f"**Type:** {task_type}\n"
            f"**Task:** {plan['task']}\n"
            f"**Description:** {plan.get('description', 'N/A')}\n\n"
            f"## Execution Steps\n"
            + "\n".join(f"- {s}" for s in plan["steps"])
            + f"\n\n## Git Context\n{git_context}\n\n"
            f"## Skills Context\n{skills_context[:1000]}\n\n"
            f"{format_instructions}\n\n"
            f"Now execute this task. Create ALL necessary files with COMPLETE content. "
            f"Include build/install commands as bash blocks."
        )

        return prompt

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
