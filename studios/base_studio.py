#!/usr/bin/env python3
"""
Agency OS — Base Studio

Abstract base class for all studio pipelines.
Every studio implements the same lifecycle: intake → plan → execute → review → deliver.

Studios integrate with:
- .agent/agents/ — for specialist AI personas
- .agent/skills/ — for domain-specific knowledge
- kernel/model_router.py — for multi-model AI calls
- kernel/state_manager.py — for persistent state & KPIs
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kernel.config import get_config
from kernel.state_manager import get_state

logger = logging.getLogger("agency.studio")


@dataclass
class StudioResult:
    """Result from a studio pipeline execution."""
    output: str = ""
    artifacts: list[str] = field(default_factory=list)
    kpis: list[dict[str, Any]] = field(default_factory=list)
    model_used: str = ""
    duration_seconds: float = 0
    success: bool = True
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "artifacts": self.artifacts,
            "kpis": self.kpis,
            "model_used": self.model_used,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseStudio(ABC):
    """Abstract base class for all Agency OS studios.

    Every studio follows the same 5-phase lifecycle:
    1. intake() — Parse and validate the task
    2. plan() — Create execution plan
    3. execute() — Run the core pipeline
    4. review() — Quality gate + validation
    5. deliver() — Package deliverables

    v3.0: Integrated with tools, memory, OpenClaw, and workflows.
    """

    name: str = "base"
    description: str = "Base studio"
    agent_ref: str = ""  # Reference to .agent/agents/*.md
    skills_refs: list[str] = None  # References to .agent/skills/*/

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.skills_refs is None:
            cls.skills_refs = []

    def __init__(self) -> None:
        self.cfg = get_config()
        self.state = get_state()
        self.studio_dir = self.cfg.studios_dir / self.name
        self._model_router = None
        self._tool_executor = None
        self._memory_manager = None
        self._openclaw = None

    @property
    def model_router(self):
        if self._model_router is None:
            from kernel.model_router import get_model_router
            self._model_router = get_model_router()
        return self._model_router

    @property
    def tools(self):
        """Access the sandboxed tool executor."""
        if self._tool_executor is None:
            from kernel.tool_executor import get_tool_executor
            self._tool_executor = get_tool_executor()
        return self._tool_executor

    @property
    def memory(self):
        """Access the memory manager."""
        if self._memory_manager is None:
            from kernel.memory_manager import get_memory_manager
            self._memory_manager = get_memory_manager()
        return self._memory_manager

    @property
    def openclaw(self):
        """Access the OpenClaw bridge."""
        if self._openclaw is None:
            from kernel.openclaw_bridge import get_openclaw
            self._openclaw = get_openclaw()
        return self._openclaw

    def get_agent_prompt(self) -> str:
        """Load the agent system prompt from .agent/agents/."""
        if not self.agent_ref:
            return ""
        agent_path = self.cfg.root / ".agent" / "agents" / f"{self.agent_ref}.md"
        if agent_path.exists():
            return agent_path.read_text(encoding="utf-8")
        return ""

    def get_skill_content(self, skill_name: str) -> str:
        """Load a skill's SKILL.md content."""
        skill_path = self.cfg.root / ".agent" / "skills" / skill_name / "SKILL.md"
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
        return ""

    # ── AI Calls (v3.5: Guardrails → OpenClaw → Fallback → Audit) ─

    def ai_call(self, prompt: str, system: str = "", task_id: int | None = None) -> str:
        """Make an AI call with guardrails, audit, and fallback."""
        import time as _time
        from kernel.guardrails import get_guardrails
        from kernel.audit_trail import get_audit

        guardrails = get_guardrails()
        audit = get_audit()

        if not system:
            system = self.get_agent_prompt()

        # Pre-call guardrail check
        check = guardrails.check_pre_call(
            studio=self.name,
            agent_id=self.agent_ref or self.name,
            prompt=prompt,
        )
        if not check.allowed:
            logger.warning("Guardrail blocked: %s", check.reason)
            return f"[BLOCKED] {check.reason}"
        for w in check.warnings:
            logger.warning(w)

        # Inject memory context
        memory_context = self.memory.get_context_for_agent(
            agent_id=self.agent_ref or self.name,
            task=prompt[:200],
            max_memory=3,
            max_knowledge=2,
        )
        if memory_context:
            prompt = f"{prompt}\n\n## Context\n{memory_context}"

        start = _time.monotonic()
        model_used = ""
        tokens_in = 0
        tokens_out = 0
        success = True
        error_msg = ""

        # Try OpenClaw first
        try:
            if self.openclaw.is_available():
                response = self.openclaw.chat(
                    messages=[
                        {"role": "system", "content": system[:3000]},
                        {"role": "user", "content": prompt},
                    ],
                    agent_id=self.agent_ref or self.name,
                )
                content = response.get("content", "")
                model_used = response.get("model", "openclaw")
                tokens_in = response.get("tokens_in", 0)
                tokens_out = response.get("tokens_out", 0)
                if content:
                    self.memory.store(
                        self.agent_ref or self.name,
                        "assistant", content[:500],
                    )
                    latency = (_time.monotonic() - start) * 1000
                    guardrails.record_usage(
                        self.name, self.agent_ref or self.name,
                        model_used, tokens_in, tokens_out, latency,
                    )
                    audit.log(
                        studio=self.name, agent_id=self.agent_ref or self.name,
                        model=model_used, provider="openclaw",
                        tokens_in=tokens_in, tokens_out=tokens_out,
                        estimated_cost=guardrails._estimate_cost(model_used, tokens_in, tokens_out),
                        latency_ms=latency, success=True,
                        prompt_preview=prompt[:100],
                    )
                    return content
        except Exception as e:
            logger.debug("OpenClaw call failed, falling back: %s", e)
            error_msg = str(e)

        # Fallback to model_router
        response = self.model_router.call_model_sync(
            prompt=prompt,
            studio=self.name,
            system=system,
            task_id=task_id,
        )
        content = response.content
        model_used = getattr(response, "model", "model_router")
        tokens_in = getattr(response, "tokens_in", 0)
        tokens_out = getattr(response, "tokens_out", 0)
        latency = (_time.monotonic() - start) * 1000

        self.memory.store(
            self.agent_ref or self.name,
            "assistant", content[:500],
        )
        guardrails.record_usage(
            self.name, self.agent_ref or self.name,
            model_used, tokens_in, tokens_out, latency,
        )
        audit.log(
            studio=self.name, agent_id=self.agent_ref or self.name,
            model=model_used, provider="model_router",
            tokens_in=tokens_in, tokens_out=tokens_out,
            estimated_cost=guardrails._estimate_cost(model_used, tokens_in, tokens_out),
            latency_ms=latency, success=bool(content),
            error=error_msg, prompt_preview=prompt[:100],
        )
        return content

    # ── Action Execution (v5.0: REAL work, not just advice) ───

    @property
    def action_executor(self):
        """Access the action executor for autonomous file/command execution."""
        if not hasattr(self, "_action_executor") or self._action_executor is None:
            from kernel.action_executor import get_action_executor
            self._action_executor = get_action_executor()
        return self._action_executor

    def execute_actions(
        self,
        ai_output: str,
        project_dir: str = "",
        auto_git: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Parse AI output and EXECUTE real actions.

        This turns AI text with code blocks into:
        - Real files on disk
        - Real shell commands executed
        - Real git commits + pushes
        """
        result = self.action_executor.auto_execute(
            ai_output=ai_output,
            project_dir=project_dir or str(self.cfg.root),
            auto_git=auto_git,
            dry_run=dry_run,
        )
        return {
            "success": result.success,
            "files_created": result.files_created,
            "files_modified": result.files_modified,
            "commands_run": result.commands_run,
            "git_operations": result.git_operations,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
        }

    def create_file(self, path: str, content: str, project_dir: str = "") -> Path:
        """Create a real file on disk."""
        base = Path(project_dir) if project_dir else self.cfg.root
        filepath = base / path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        logger.info("[%s] Created file: %s", self.name, filepath)
        return filepath

    def git_commit_push(
        self,
        message: str,
        project_dir: str = "",
        push: bool = True,
    ) -> dict[str, Any]:
        """Git add, commit, and optionally push."""
        import subprocess
        cwd = project_dir or str(self.cfg.root)
        results = {"operations": [], "errors": []}

        # Add
        proc = subprocess.run(
            "git add -A", shell=True, capture_output=True, text=True,
            cwd=cwd, timeout=30,
        )
        results["operations"].append("git add -A")

        # Commit
        proc = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=cwd, timeout=30,
        )
        if proc.returncode == 0:
            results["operations"].append(f"git commit: {message}")
        elif "nothing to commit" not in (proc.stdout + proc.stderr):
            results["errors"].append(proc.stderr[:200])

        # Push
        if push:
            proc = subprocess.run(
                "git push origin main", shell=True,
                capture_output=True, text=True, cwd=cwd, timeout=60,
            )
            if proc.returncode == 0:
                results["operations"].append("git push origin main")
            else:
                results["errors"].append(proc.stderr[:200])

        return results

    # ── Tool Shortcuts ────────────────────────────────────────

    def web_search(self, query: str) -> str:
        """Search the web using Brave API."""
        result = self.tools.execute(
            "search_web", {"query": query},
            agent_id=self.agent_ref or self.name,
        )
        return result.output if result.success else ""

    def scrape_url(self, url: str) -> str:
        """Scrape text content from a URL."""
        result = self.tools.execute(
            "scrape_url", {"url": url},
            agent_id=self.agent_ref or self.name,
        )
        return result.output if result.success else ""

    def shell(self, command: str, cwd: str = "") -> str:
        """Execute a shell command."""
        params: dict[str, Any] = {"command": command}
        if cwd:
            params["cwd"] = cwd
        result = self.tools.execute(
            "shell", params,
            agent_id=self.agent_ref or self.name,
        )
        return result.output if result.success else f"Error: {result.error}"

    def save_output(self, filename: str, content: str) -> Path:
        """Save output to the studio's output directory."""
        output_dir = self.cfg.reports_dir / self.name
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    # ── Lifecycle Methods ─────────────────────────────────────

    @abstractmethod
    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        """Phase 1: Parse and validate the incoming task."""
        ...

    @abstractmethod
    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        """Phase 2: Create an execution plan based on intake."""
        ...

    @abstractmethod
    def execute(self, plan: dict[str, Any], task_id: int | None = None) -> dict[str, Any]:
        """Phase 3: Run the core pipeline."""
        ...

    def review(self, execution_result: dict[str, Any]) -> dict[str, Any]:
        """Phase 4: Quality gate — validate execution results."""
        output = execution_result.get("output", "")

        # Basic sanity check first
        if not output or len(str(output)) < 20:
            return {
                **execution_result,
                "review_passed": False,
                "review_notes": "Output too short or empty",
            }

        # LLM-based quality check via OpenClaw (fast, one-shot)
        quality_notes = "Passed structural check"
        passed = True
        try:
            from kernel.openclaw_bridge import get_openclaw
            oc = get_openclaw()
            if oc.is_available():
                verdict = oc.ask(
                    prompt=(
                        f"Rate the quality of this output (1-10) and give a brief reason. "
                        f"Only respond with: SCORE: X\nREASON: ...\n\n"
                        f"Output to evaluate:\n{str(output)[:1500]}"
                    ),
                    system="You are a QA reviewer. Be concise.",
                    agent_id="quality-gate",
                )
                if verdict:
                    quality_notes = verdict[:300]
                    # Parse score if present
                    import re
                    score_match = re.search(r'SCORE:\s*(\d+)', verdict)
                    if score_match:
                        score = int(score_match.group(1))
                        passed = score >= 5
        except Exception as e:
            logger.debug("LLM quality check skipped: %s", e)

        return {
            **execution_result,
            "review_passed": passed,
            "review_notes": quality_notes,
        }

    def deliver(self, review_result: dict[str, Any]) -> StudioResult:
        """Phase 5: Package deliverables."""
        return StudioResult(
            output=str(review_result.get("output", "")),
            artifacts=review_result.get("artifacts", []),
            kpis=review_result.get("kpis", []),
            model_used=review_result.get("model_used", ""),
            success=review_result.get("review_passed", True),
        )

    # ── Main Entry Point ──────────────────────────────────────

    def run(
        self,
        task: str,
        description: str = "",
        task_id: int | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """Execute the full studio lifecycle."""
        start = time.monotonic()
        logger.info("[%s] Starting pipeline: %s", self.name, task[:80])

        # Store task in memory
        self.memory.store(
            self.agent_ref or self.name,
            "user", f"[{self.name}] {task[:300]}",
        )

        try:
            intake_result = self.intake(task, description, **(metadata or {}))
            logger.info("[%s] Intake complete", self.name)

            plan = self.plan(intake_result)
            logger.info("[%s] Plan created", self.name)

            execution_result = self.execute(plan, task_id)
            logger.info("[%s] Execution complete", self.name)

            review_result = self.review(execution_result)
            logger.info("[%s] Review: %s", self.name,
                       "PASSED" if review_result.get("review_passed") else "FAILED")

            result = self.deliver(review_result)
            result.duration_seconds = time.monotonic() - start

            # Log KPIs
            self.state.log_kpi(self.name, "pipeline_duration", result.duration_seconds, "seconds")
            self.state.log_kpi(self.name, "pipeline_success", 1.0 if result.success else 0.0)

            # Store result as knowledge
            if result.success and result.output:
                self.memory.learn(
                    topic=f"{self.name}:{intake_result.get('operation', 'task')}",
                    content=result.output[:500],
                    source_agent=self.agent_ref or self.name,
                    tags=[self.name, intake_result.get("operation", "")],
                )

            return result.to_dict()

        except Exception as e:
            duration = time.monotonic() - start
            error_msg = f"{e.__class__.__name__}: {e}"
            logger.error("[%s] Pipeline failed: %s", self.name, error_msg)

            self.state.log_kpi(self.name, "pipeline_success", 0.0)
            self.state.log_kpi(self.name, "pipeline_duration", duration, "seconds")

            return StudioResult(
                success=False,
                error=error_msg,
                duration_seconds=duration,
            ).to_dict()


_studios_cache: dict[str, BaseStudio] | None = None


def load_all_studios() -> dict[str, BaseStudio]:
    """Auto-discover and load all studio implementations (singleton cache)."""
    global _studios_cache
    if _studios_cache is not None:
        return _studios_cache

    studios: dict[str, BaseStudio] = {}

    # Import each studio's pipeline module
    studio_modules = {
        "dev": "studios.dev.pipeline",
        "marketing": "studios.marketing.pipeline",
        "sales": "studios.sales.pipeline",
        "leadops": "studios.leadops.pipeline",
        "abm": "studios.abm.pipeline",
        "analytics": "studios.analytics.pipeline",
        "creative": "studios.creative.pipeline",
    }

    import importlib
    for name, module_path in studio_modules.items():
        try:
            mod = importlib.import_module(module_path)
            studio_class = getattr(mod, "Studio", None)
            if studio_class:
                studios[name] = studio_class()
                logger.info("Loaded studio: %s", name)
        except (ImportError, AttributeError) as e:
            logger.debug("Studio %s not available: %s", name, e)

    _studios_cache = studios
    return studios
