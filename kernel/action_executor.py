#!/usr/bin/env python3
"""
Agency OS v5.0 — Action Executor

Transforms AI-generated text into REAL ACTIONS:
- Parses code blocks from AI responses → creates actual files
- Detects shell commands → executes them
- Git operations → commit + push
- Project scaffolding → creates folders, installs deps

This is what makes Agency OS an EXECUTOR, not just an advisor.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from kernel.config import get_config

logger = logging.getLogger("agency.actions")


@dataclass
class FileAction:
    """A file to create or modify."""

    path: str
    content: str
    language: str = ""
    action: str = "create"  # create | modify | delete


@dataclass
class ShellAction:
    """A shell command to run."""

    command: str
    cwd: str = ""
    description: str = ""


@dataclass
class GitAction:
    """A git operation."""

    operation: str  # add | commit | push | create-repo
    message: str = ""
    files: list[str] = field(default_factory=list)
    remote: str = "origin"
    branch: str = "main"


@dataclass
class ActionPlan:
    """Parsed plan of actions from AI output."""

    files: list[FileAction] = field(default_factory=list)
    commands: list[ShellAction] = field(default_factory=list)
    git: list[GitAction] = field(default_factory=list)
    summary: str = ""
    raw_output: str = ""


@dataclass
class ActionResult:
    """Result of executing an action plan."""

    success: bool = True
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    commands_run: list[dict[str, str]] = field(default_factory=list)
    git_operations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0


class ActionExecutor:
    """
    Parses AI output and EXECUTES real actions.

    Flow:
    1. AI generates response with code blocks + instructions
    2. ActionExecutor parses the response
    3. Creates files, runs commands, pushes to git
    4. Returns proof of what was done
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._safe_commands = {
            "npm",
            "npx",
            "node",
            "python3",
            "python",
            "pip",
            "pip3",
            "mkdir",
            "touch",
            "cp",
            "mv",
            "cat",
            "echo",
            "git",
            "curl",
            "wget",
            "pytest",
            "ruff",
            "black",
            "eslint",
            "prettier",
            "cargo",
            "go",
            "deno",
            "bun",
        }

    def parse(self, ai_output: str, project_dir: str = "") -> ActionPlan:
        """Parse AI output into actionable plan."""
        plan = ActionPlan(raw_output=ai_output)

        # 1. Extract code blocks with file paths
        plan.files = self._extract_files(ai_output, project_dir)

        # 2. Extract shell commands
        plan.commands = self._extract_commands(ai_output, project_dir)

        # 3. Extract git intentions
        plan.git = self._extract_git_actions(ai_output)

        # 4. Extract summary
        plan.summary = self._extract_summary(ai_output)

        return plan

    def execute(
        self,
        plan: ActionPlan,
        project_dir: str = "",
        dry_run: bool = False,
    ) -> ActionResult:
        """Execute the action plan for real."""
        start = time.monotonic()
        result = ActionResult()
        work_dir = project_dir or str(self.cfg.root)

        # 1. Create/modify files
        for file_action in plan.files:
            try:
                if dry_run:
                    result.files_created.append(f"[DRY] {file_action.path}")
                    continue

                filepath = Path(file_action.path)
                if not filepath.is_absolute():
                    filepath = Path(work_dir) / filepath

                filepath.parent.mkdir(parents=True, exist_ok=True)

                if file_action.action == "delete":
                    if filepath.exists():
                        filepath.unlink()
                        logger.info("Deleted: %s", filepath)
                else:
                    filepath.write_text(file_action.content, encoding="utf-8")
                    logger.info(
                        "Created: %s (%d bytes)", filepath, len(file_action.content)
                    )

                    if file_action.action == "create":
                        result.files_created.append(str(filepath))
                    else:
                        result.files_modified.append(str(filepath))

            except Exception as e:
                error = f"File error ({file_action.path}): {e}"
                result.errors.append(error)
                logger.error(error)

        # 2. Run shell commands
        for cmd_action in plan.commands:
            try:
                if dry_run:
                    result.commands_run.append(
                        {
                            "command": cmd_action.command,
                            "status": "dry_run",
                        }
                    )
                    continue

                if not self._is_safe_command(cmd_action.command):
                    result.errors.append(
                        f"Blocked unsafe command: {cmd_action.command}"
                    )
                    continue

                cwd = cmd_action.cwd or work_dir
                proc = subprocess.run(
                    cmd_action.command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=cwd,
                )

                result.commands_run.append(
                    {
                        "command": cmd_action.command,
                        "status": "success" if proc.returncode == 0 else "failed",
                        "output": proc.stdout[-1000:] if proc.stdout else "",
                        "error": proc.stderr[-500:] if proc.stderr else "",
                    }
                )

                if proc.returncode != 0:
                    result.errors.append(
                        f"Command failed: {cmd_action.command}: {proc.stderr[:200]}"
                    )

            except subprocess.TimeoutExpired:
                result.errors.append(f"Command timed out: {cmd_action.command}")
            except Exception as e:
                result.errors.append(f"Command error: {e}")

        # 3. Git operations
        for git_action in plan.git:
            try:
                if dry_run:
                    result.git_operations.append(f"[DRY] {git_action.operation}")
                    continue

                self._execute_git(git_action, work_dir, result)

            except Exception as e:
                result.errors.append(f"Git error: {e}")

        result.duration_ms = (time.monotonic() - start) * 1000
        result.success = len(result.errors) == 0

        return result

    # ── Parsers ──────────────────────────────────────────────

    def _extract_files(self, text: str, project_dir: str) -> list[FileAction]:
        """Extract file definitions from AI output."""
        files = []

        # Pattern 1: ```language:path/to/file.ext
        # or: ```language filepath: path/to/file.ext
        # Content...
        # ```
        pattern1 = re.compile(
            r"```(\w+)\s*(?::|\s+(?:filepath|file|path):\s*)"
            r"([^\n]+)\n(.*?)```",
            re.DOTALL,
        )
        for match in pattern1.finditer(text):
            lang, path, content = match.group(1), match.group(2).strip(), match.group(3)
            files.append(
                FileAction(
                    path=path,
                    content=content.strip() + "\n",
                    language=lang,
                    action="create",
                )
            )

        # Pattern 2: <!-- file: path/to/file.ext -->
        pattern2 = re.compile(
            r"<!--\s*file:\s*([^\s>]+)\s*-->\s*```\w*\n(.*?)```",
            re.DOTALL,
        )
        for match in pattern2.finditer(text):
            path, content = match.group(1).strip(), match.group(2)
            files.append(
                FileAction(
                    path=path,
                    content=content.strip() + "\n",
                    action="create",
                )
            )

        # Pattern 3: **`path/to/file.ext`** or ### `path/to/file.ext`
        pattern3 = re.compile(
            r"(?:\*\*`|###?\s*`?)([a-zA-Z0-9_./-]+\.\w{1,10})`?\*?\*?\s*\n"
            r"```(\w*)\n(.*?)```",
            re.DOTALL,
        )
        for match in pattern3.finditer(text):
            path, lang, content = match.group(1), match.group(2), match.group(3)
            # Skip if already captured
            if not any(f.path == path for f in files):
                files.append(
                    FileAction(
                        path=path,
                        content=content.strip() + "\n",
                        language=lang,
                        action="create",
                    )
                )

        return files

    def _extract_commands(self, text: str, project_dir: str) -> list[ShellAction]:
        """Extract shell commands from AI output."""
        commands = []

        # Find commands in ```bash or ```shell blocks
        pattern = re.compile(r"```(?:bash|shell|sh|zsh|cmd)\n(.*?)```", re.DOTALL)
        for match in pattern.finditer(text):
            block = match.group(1).strip()
            for line in block.split("\n"):
                line = line.strip()
                # Skip comments
                if line.startswith("#") or not line:
                    continue
                # Remove $ prompt
                if line.startswith("$ "):
                    line = line[2:]
                commands.append(
                    ShellAction(
                        command=line,
                        cwd=project_dir,
                    )
                )

        # Also detect inline commands like: Run `npm install`
        inline = re.findall(
            r"(?:run|execute|type|enter|use):?\s*`([^`]+)`",
            text,
            re.IGNORECASE,
        )
        for cmd in inline:
            if not any(c.command == cmd for c in commands):
                commands.append(ShellAction(command=cmd, cwd=project_dir))

        return commands

    def _extract_git_actions(self, text: str) -> list[GitAction]:
        """Detect git intentions from AI output."""
        actions = []
        text_lower = text.lower()

        # Auto-add git add + commit if files were created
        if any(
            phrase in text_lower
            for phrase in [
                "commit",
                "push",
                "save changes",
                "git add",
                "push to github",
                "push to remote",
            ]
        ):
            actions.append(
                GitAction(
                    operation="add",
                    files=["."],
                )
            )
            actions.append(
                GitAction(
                    operation="commit",
                    message="feat: auto-generated by Agency OS",
                )
            )

        if any(
            phrase in text_lower
            for phrase in ["push", "push to github", "push to remote"]
        ):
            actions.append(GitAction(operation="push"))

        return actions

    def _extract_summary(self, text: str) -> str:
        """Extract a summary from AI output."""
        # First paragraph or first 200 chars
        lines = text.strip().split("\n")
        summary_lines = []
        for line in lines:
            if line.strip() and not line.startswith("```") and not line.startswith("#"):
                summary_lines.append(line.strip())
                if len(" ".join(summary_lines)) > 200:
                    break
        return " ".join(summary_lines)[:300]

    # ── Safety ───────────────────────────────────────────────

    def _is_safe_command(self, command: str) -> bool:
        """Check if command is safe to run."""
        # Block dangerous patterns
        dangerous = [
            "rm -rf /",
            "rm -rf /*",
            "mkfs",
            "dd if=",
            ":(){",
            "> /dev/sda",
            "chmod 777 /",
            "sudo rm",
            "| bash",
            "| sh",
        ]
        cmd_lower = command.lower()
        for d in dangerous:
            if d in cmd_lower:
                return False

        # Check first command in pipe chain
        first_cmd = command.split()[0] if command.split() else ""
        first_cmd = first_cmd.lstrip("./")

        return first_cmd in self._safe_commands

    # ── Git Execution ────────────────────────────────────────

    def _execute_git(
        self,
        action: GitAction,
        work_dir: str,
        result: ActionResult,
    ) -> None:
        """Execute a git action."""
        if action.operation == "add":
            files = " ".join(action.files) if action.files else "."
            proc = subprocess.run(
                f"git add {files}",
                shell=True,
                capture_output=True,
                text=True,
                cwd=work_dir,
                timeout=30,
            )
            result.git_operations.append(f"git add {files}")

        elif action.operation == "commit":
            msg = action.message or "feat: auto-generated by Agency OS"
            proc = subprocess.run(
                ["git", "commit", "-m", msg],
                capture_output=True,
                text=True,
                cwd=work_dir,
                timeout=30,
            )
            if proc.returncode == 0:
                result.git_operations.append(f"git commit: {msg}")
            else:
                # Nothing to commit is not an error
                if "nothing to commit" not in proc.stdout + proc.stderr:
                    result.errors.append(f"git commit failed: {proc.stderr[:200]}")

        elif action.operation == "push":
            proc = subprocess.run(
                f"git push {action.remote} {action.branch}",
                shell=True,
                capture_output=True,
                text=True,
                cwd=work_dir,
                timeout=60,
            )
            if proc.returncode == 0:
                result.git_operations.append(
                    f"git push {action.remote} {action.branch}"
                )
            else:
                result.errors.append(f"git push failed: {proc.stderr[:200]}")

    # ── High-Level Helpers ───────────────────────────────────

    def auto_execute(
        self,
        ai_output: str,
        project_dir: str = "",
        auto_git: bool = False,
        dry_run: bool = False,
    ) -> ActionResult:
        """
        One-call: parse AI output → execute everything.

        This is the main entry point for autonomous execution.
        """
        plan = self.parse(ai_output, project_dir)

        if not auto_git:
            plan.git = []  # Don't auto-commit unless asked

        logger.info(
            "Action plan: %d files, %d commands, %d git ops",
            len(plan.files),
            len(plan.commands),
            len(plan.git),
        )

        return self.execute(plan, project_dir, dry_run)


_executor: ActionExecutor | None = None


def get_action_executor() -> ActionExecutor:
    global _executor
    if _executor is None:
        _executor = ActionExecutor()
    return _executor
