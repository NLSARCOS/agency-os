#!/usr/bin/env python3
"""
Agency OS v5.0 — Self-Evolution Engine

The system that makes Agency OS ALIVE:

  1. ANALYZE  — Scan own codebase for gaps, missing skills, weak modules
  2. PLAN     — AI generates improvement proposals
  3. CREATE   — Generate new skills, agents, module improvements
  4. SUBMIT   — Branch, commit, push, open PR to its own repo
  5. LEARN    — Track what worked, improve next cycle

This runs autonomously and continuously improves the system.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus

logger = logging.getLogger("agency.evolution")


@dataclass
class EvolutionProposal:
    """A self-improvement proposal."""
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    type: str = ""  # skill | agent | module | fix | optimization
    title: str = ""
    description: str = ""
    files_to_create: list[dict] = field(default_factory=list)
    files_to_modify: list[dict] = field(default_factory=list)
    branch_name: str = ""
    status: str = "proposed"  # proposed | approved | applied | pr_created | merged
    pr_url: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class CodebaseHealth:
    """Analysis of the codebase health."""
    total_modules: int = 0
    total_loc: int = 0
    total_studios: int = 0
    total_skills: int = 0
    total_agents: int = 0
    missing_tests: list[str] = field(default_factory=list)
    missing_docstrings: list[str] = field(default_factory=list)
    potential_skills: list[str] = field(default_factory=list)
    potential_agents: list[str] = field(default_factory=list)
    improvement_areas: list[str] = field(default_factory=list)


class SelfEvolutionEngine:
    """
    The evolution brain: Agency OS improves itself.

    AUTONOMOUS DECISION LOGIC:
    - Each detected gap gets a confidence score (0-100)
    - Score >= CONFIDENCE_THRESHOLD → auto-act (create + PR)
    - Score < CONFIDENCE_THRESHOLD → log only, no action
    - Score based on: impact, risk, effort, evidence

    Creates branches and PRs, never pushes to main directly.
    """

    # Confidence thresholds
    CONFIDENCE_THRESHOLD = 70  # Auto-act on gaps with score >= this
    HIGH_CONFIDENCE = 90       # Very safe to auto-create

    # Scoring rules
    SCORING_RULES = {
        "missing_skill_for_module": 90,   # Module exists, matching skill doesn't → safe
        "missing_agent_for_studio": 80,   # Studio exists without dedicated agent → safe
        "missing_test_file": 75,          # Module has no test file → safe to create
        "large_module_split": 50,         # Large file, splitting is risky → defer
        "new_feature_module": 40,         # New functionality → needs human review
        "code_refactor": 30,              # Structural changes → needs human review
    }

    def __init__(self) -> None:
        self.cfg = get_config()
        self._bus = get_event_bus()
        self._proposals: list[EvolutionProposal] = []
        self._root = self.cfg.root
        self._decisions_log: list[dict[str, Any]] = []  # Track every decision

    # ── 1. ANALYZE ───────────────────────────────────────────

    def analyze_codebase(self) -> CodebaseHealth:
        """Scan the entire codebase and identify improvement opportunities."""
        health = CodebaseHealth()

        # Count kernel modules
        kernel_dir = self._root / "kernel"
        if kernel_dir.exists():
            modules = [f for f in kernel_dir.iterdir()
                       if f.suffix == ".py" and not f.name.startswith("__")]
            health.total_modules = len(modules)

            # Check for missing tests and docstrings
            for mod in modules:
                content = mod.read_text(encoding="utf-8")
                health.total_loc += content.count("\n")

                test_file = self._root / "tests" / f"test_{mod.name}"
                if not test_file.exists():
                    health.missing_tests.append(mod.name)

                # Check top-level docstring
                if not content.strip().startswith('"""') and not content.strip().startswith("#!/"):
                    health.missing_docstrings.append(mod.name)

        # Count studios
        studios_dir = self._root / "studios"
        if studios_dir.exists():
            studios = [d for d in studios_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
            health.total_studios = len(studios)

        # Count skills
        skills_dir = self._root / ".agent" / "skills"
        if skills_dir.exists():
            existing_skills = {d.name for d in skills_dir.iterdir() if d.is_dir()}
            health.total_skills = len(existing_skills)

            # Detect potential new skills from code patterns
            skill_candidates = self._detect_skill_gaps(existing_skills)
            health.potential_skills = skill_candidates

        # Count agents
        agents_dir = self._root / ".agent" / "agents"
        if agents_dir.exists():
            existing_agents = {f.stem for f in agents_dir.iterdir() if f.suffix == ".md"}
            health.total_agents = len(existing_agents)

            # Detect potential new agents
            agent_candidates = self._detect_agent_gaps(existing_agents)
            health.potential_agents = agent_candidates

        # Improvement areas
        health.improvement_areas = self._detect_improvements()

        return health

    def _detect_skill_gaps(self, existing: set[str]) -> list[str]:
        """Find skills that could be created based on codebase needs."""
        candidates = []

        # Based on kernel modules that don't have matching skills
        potential = {
            "prompt-engineering": "prompt_engine.py",
            "model-routing": "model_router.py",
            "project-management": "project_manager.py",
            "automation-scripts": "script_engine.py",
            "quality-assurance": "quality_gates.py",
            "data-pipelines": "cross_studio.py",
            "self-improvement": "self_evolution.py",
            "cost-optimization": "guardrails.py",
            "memory-management": "memory_manager.py",
            "workflow-automation": "workflow_engine.py",
        }

        for skill_name, module in potential.items():
            if skill_name not in existing:
                module_path = self._root / "kernel" / module
                if module_path.exists():
                    candidates.append(skill_name)

        return candidates

    def _detect_agent_gaps(self, existing: set[str]) -> list[str]:
        """Find agents that could be created."""
        candidates = []

        # Agents that would enhance the system
        potential_agents = {
            "qa-specialist": "Quality assurance and testing specialist",
            "devops-engineer": "CI/CD and deployment automation",
            "data-analyst": "Data analysis and business intelligence",
            "copywriter": "Marketing copy and content writing",
            "ux-researcher": "User experience research and testing",
            "growth-hacker": "Growth strategies and experimentation",
        }

        for agent_name, desc in potential_agents.items():
            if agent_name not in existing:
                candidates.append(agent_name)

        return candidates

    def _detect_improvements(self) -> list[str]:
        """Detect areas that could be improved."""
        improvements = []

        # Check for modules over 300 lines (could be split)
        kernel_dir = self._root / "kernel"
        if kernel_dir.exists():
            for mod in kernel_dir.iterdir():
                if mod.suffix == ".py" and not mod.name.startswith("__"):
                    loc = mod.read_text(encoding="utf-8").count("\n")
                    if loc > 400:
                        improvements.append(
                            f"{mod.name}: {loc} lines — consider splitting"
                        )

        # Check test coverage
        tests_dir = self._root / "tests"
        if tests_dir.exists():
            test_count = len(list(tests_dir.glob("test_*.py")))
            if test_count < 5:
                improvements.append(
                    f"Only {test_count} test files — needs more coverage"
                )

        return improvements

    # ── 2. CREATE SKILLS ─────────────────────────────────────

    def create_skill(
        self,
        name: str,
        description: str,
        content: str = "",
    ) -> Path:
        """Create a new skill in .agent/skills/."""
        skill_dir = self._root / ".agent" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Generate SKILL.md
        if not content:
            content = self._generate_skill_content(name, description)

        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(content, encoding="utf-8")

        logger.info("Created skill: %s at %s", name, skill_file)
        return skill_file

    def _generate_skill_content(self, name: str, description: str) -> str:
        """Generate a SKILL.md with proper structure."""
        title = name.replace("-", " ").title()
        return f"""---
name: {name}
description: {description}
---

# {title}

## Purpose
{description}

## Core Principles

1. **Understand the Context** — Before applying this skill, understand the specific requirements and constraints.
2. **Apply Best Practices** — Use industry-standard patterns and proven approaches.
3. **Measure and Iterate** — Track outcomes and continuously improve.

## When to Use
- When tasks involve {name.replace('-', ' ')} patterns
- When optimizing for quality and consistency in this domain
- When building or improving {name.replace('-', ' ')} capabilities

## Key Patterns

### Pattern 1: Analysis First
Always start by analyzing the current state before making changes.

### Pattern 2: Incremental Improvement
Make small, verifiable changes rather than large rewrites.

### Pattern 3: Documentation
Document decisions and outcomes for future reference.

## Anti-Patterns
- Don't over-engineer solutions
- Don't skip validation steps
- Don't ignore error handling

## Integration
This skill integrates with the Agency OS kernel modules and can be referenced by agents and studios.
"""

    # ── 3. CREATE AGENTS ─────────────────────────────────────

    def create_agent(
        self,
        name: str,
        role: str,
        description: str,
        skills: list[str] | None = None,
    ) -> Path:
        """Create a new agent in .agent/agents/."""
        agents_dir = self._root / ".agent" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        content = self._generate_agent_content(name, role, description, skills or [])
        agent_file = agents_dir / f"{name}.md"
        agent_file.write_text(content, encoding="utf-8")

        logger.info("Created agent: %s at %s", name, agent_file)
        return agent_file

    def _generate_agent_content(
        self, name: str, role: str, description: str, skills: list[str],
    ) -> str:
        """Generate an agent .md file."""
        title = name.replace("-", " ").title()
        skills_list = "\n".join(f"  - {s}" for s in skills) if skills else "  - clean-code"

        return f"""---
name: {name}
role: {role}
skills:
{skills_list}
---

# {title}

## Role
{role}

## Description
{description}

## Core Competencies

1. **Domain Expertise** — Deep knowledge in {role.lower()}
2. **Problem Solving** — Analytical approach to challenges
3. **Communication** — Clear, actionable outputs
4. **Collaboration** — Works with other agents in multi-studio pipelines

## Behavioral Guidelines

### Decision Making
- Analyze before acting
- Consider trade-offs explicitly
- Document reasoning for major decisions

### Output Quality
- Every output must be actionable
- Include specific next steps
- Provide evidence-based recommendations

### Collaboration
- Share context with other agents
- Respect expertise boundaries
- Escalate when outside competency

## Anti-Patterns
- Avoid generic or vague recommendations
- Don't ignore constraints or requirements
- Never produce output without quality validation
"""

    # ── 4. SUBMIT PR ─────────────────────────────────────────

    def create_evolution_pr(
        self,
        proposal: EvolutionProposal,
    ) -> str:
        """Create a branch, apply changes, push, and create a PR."""
        branch = proposal.branch_name or f"evolution/{proposal.id}-{proposal.type}"

        cwd = str(self._root)

        # 1. Create branch
        self._run_git(f"git checkout -b {branch}", cwd)

        # 2. Create/modify files
        for file_info in proposal.files_to_create:
            filepath = Path(cwd) / file_info["path"]
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(file_info["content"], encoding="utf-8")

        for file_info in proposal.files_to_modify:
            filepath = Path(cwd) / file_info["path"]
            if filepath.exists():
                filepath.write_text(file_info["content"], encoding="utf-8")

        # 3. Commit
        self._run_git("git add -A", cwd)
        commit_msg = f"evolution({proposal.type}): {proposal.title}"
        self._run_git(f'git commit -m "{commit_msg}"', cwd)

        # 4. Push branch
        self._run_git(f"git push origin {branch}", cwd)

        # 5. Create PR via gh CLI (GitHub CLI)
        pr_body = (
            f"## 🧬 Self-Evolution Proposal\n\n"
            f"**Type:** {proposal.type}\n"
            f"**Title:** {proposal.title}\n\n"
            f"### Description\n{proposal.description}\n\n"
            f"### Files Changed\n"
            + "\n".join(f"- `{f['path']}`" for f in proposal.files_to_create)
            + "\n".join(f"- `{f['path']}`" for f in proposal.files_to_modify)
            + "\n\n---\n*Auto-generated by Agency OS Self-Evolution Engine*"
        )

        try:
            result = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--title", commit_msg,
                    "--body", pr_body,
                    "--base", "main",
                    "--head", branch,
                ],
                capture_output=True, text=True,
                cwd=cwd, timeout=30,
            )
            if result.returncode == 0:
                pr_url = result.stdout.strip()
                proposal.pr_url = pr_url
                proposal.status = "pr_created"
                logger.info("PR created: %s", pr_url)
            else:
                logger.warning("gh pr create failed: %s", result.stderr[:200])
                proposal.status = "pushed"  # Branch pushed, PR failed
        except FileNotFoundError:
            logger.info(
                "GitHub CLI not found. Branch pushed to %s — create PR manually.", branch,
            )
            proposal.status = "pushed"

        # 6. Return to main
        self._run_git("git checkout main", cwd)

        self._proposals.append(proposal)
        return proposal.pr_url or f"Branch: {branch}"

    def _run_git(self, command: str, cwd: str) -> str:
        """Run a git command safely."""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=cwd, timeout=30,
            )
            return result.stdout.strip()
        except Exception as e:
            logger.error("Git command failed: %s — %s", command, e)
            return ""

    # ── 5. AUTONOMOUS DECISION ENGINE ─────────────────────────

    def _score_gap(self, gap_type: str, name: str, context: str = "") -> int:
        """Score a gap's confidence for auto-action (0-100)."""
        base = self.SCORING_RULES.get(gap_type, 50)

        # Bonus: if the module it relates to is heavily used
        if "engine" in name or "router" in name:
            base = min(100, base + 5)

        # Penalty: if it involves modifying existing files
        if gap_type in ("code_refactor", "large_module_split"):
            base = max(0, base - 10)

        return base

    def _log_decision(
        self, gap_type: str, name: str, score: int, action: str, reason: str,
    ) -> None:
        """Log every autonomous decision for transparency."""
        decision = {
            "type": gap_type,
            "name": name,
            "confidence": score,
            "action": action,  # "create" | "skip" | "defer"
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._decisions_log.append(decision)
        logger.info(
            "Evolution decision: %s %s (confidence=%d) → %s: %s",
            gap_type, name, score, action, reason,
        )

    def evolve(
        self,
        auto_pr: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Run a full AUTONOMOUS self-evolution cycle.

        The engine DECIDES what to do based on confidence scoring:
        - Score >= 70: auto-create (skill, agent, test)
        - Score < 70: log and skip (needs human review)
        - Never touches main: always creates branches + PRs
        """
        start = time.monotonic()
        results = {
            "skills_created": [],
            "agents_created": [],
            "proposals": [],
            "decisions": [],
            "health": {},
        }

        # 1. Analyze
        health = self.analyze_codebase()
        results["health"] = {
            "modules": health.total_modules,
            "loc": health.total_loc,
            "studios": health.total_studios,
            "skills": health.total_skills,
            "agents": health.total_agents,
            "missing_tests": health.missing_tests[:5],
            "improvements": health.improvement_areas[:5],
        }

        logger.info(
            "Evolution cycle: %d modules, %d skills, %d agents",
            health.total_modules, health.total_skills, health.total_agents,
        )

        files_to_create = []

        # 2. DECIDE on skills — each one scored independently
        for skill_name in health.potential_skills:
            score = self._score_gap("missing_skill_for_module", skill_name)

            if score >= self.CONFIDENCE_THRESHOLD:
                self._log_decision(
                    "missing_skill_for_module", skill_name, score,
                    "create", f"Module exists, no matching skill. Score {score} >= {self.CONFIDENCE_THRESHOLD}",
                )

                if dry_run:
                    results["skills_created"].append(f"[DRY] {skill_name}")
                else:
                    desc = f"Principles and patterns for {skill_name.replace('-', ' ')}"
                    path = self.create_skill(skill_name, desc)
                    rel = str(path.relative_to(self._root))
                    results["skills_created"].append(skill_name)
                    files_to_create.append({
                        "path": rel,
                        "content": path.read_text(encoding="utf-8"),
                    })
            else:
                self._log_decision(
                    "missing_skill_for_module", skill_name, score,
                    "skip", f"Confidence {score} < {self.CONFIDENCE_THRESHOLD}. Needs review.",
                )

        # 3. DECIDE on agents
        agent_roles = {
            "qa-specialist": ("Quality assurance and test automation specialist",
                              ["testing-patterns", "tdd-workflow"]),
            "devops-engineer": ("CI/CD pipelines and deployment automation",
                                ["deployment-procedures", "server-management"]),
            "data-analyst": ("Data analysis and business intelligence",
                             ["database-design", "performance-profiling"]),
            "copywriter": ("Marketing copy and persuasive content",
                           ["seo-fundamentals", "frontend-design"]),
            "ux-researcher": ("User experience research and usability testing",
                              ["web-design-guidelines", "frontend-design"]),
            "growth-hacker": ("Growth experimentation and rapid validation",
                              ["seo-fundamentals", "testing-patterns"]),
        }

        for agent_name in health.potential_agents:
            score = self._score_gap("missing_agent_for_studio", agent_name)

            if score >= self.CONFIDENCE_THRESHOLD:
                role_info = agent_roles.get(agent_name, (f"{agent_name} specialist", []))
                self._log_decision(
                    "missing_agent_for_studio", agent_name, score,
                    "create", f"No agent for this domain. Score {score} >= {self.CONFIDENCE_THRESHOLD}",
                )

                if dry_run:
                    results["agents_created"].append(f"[DRY] {agent_name}")
                else:
                    path = self.create_agent(
                        agent_name, role_info[0], role_info[0],
                        skills=role_info[1] if len(role_info) > 1 else None,
                    )
                    rel = str(path.relative_to(self._root))
                    results["agents_created"].append(agent_name)
                    files_to_create.append({
                        "path": rel,
                        "content": path.read_text(encoding="utf-8"),
                    })
            else:
                self._log_decision(
                    "missing_agent_for_studio", agent_name, score,
                    "skip", f"Confidence {score} < threshold. Defer.",
                )

        # 4. Log decisions for improvements (never auto-act on refactors)
        for improvement in health.improvement_areas:
            score = self._score_gap("large_module_split", improvement)
            self._log_decision(
                "large_module_split", improvement, score,
                "defer", "Structural changes need human review.",
            )

        results["decisions"] = list(self._decisions_log[-20:])

        # 5. Submit PR with all auto-approved changes
        if files_to_create and auto_pr and not dry_run:
            skills_list = ", ".join(results["skills_created"])
            agents_list = ", ".join(results["agents_created"])
            proposal = EvolutionProposal(
                type="evolution",
                title=f"Auto: +{len(results['skills_created'])} skills, +{len(results['agents_created'])} agents",
                description=(
                    f"Autonomous evolution cycle.\n\n"
                    f"**Decision criteria:** confidence >= {self.CONFIDENCE_THRESHOLD}\n\n"
                    f"**Skills created** (score={self.SCORING_RULES['missing_skill_for_module']}):\n"
                    f"{skills_list}\n\n"
                    f"**Agents created** (score={self.SCORING_RULES['missing_agent_for_studio']}):\n"
                    f"{agents_list}\n\n"
                    f"**Deferred** (below threshold):\n"
                    + "\n".join(
                        f"- {d['name']} (score={d['confidence']})"
                        for d in self._decisions_log if d["action"] == "skip"
                    )
                ),
                files_to_create=files_to_create,
                branch_name=f"evolution/auto-{uuid4().hex[:6]}",
            )
            pr_result = self.create_evolution_pr(proposal)
            results["proposals"].append({
                "id": proposal.id,
                "title": proposal.title,
                "status": proposal.status,
                "pr_url": proposal.pr_url,
                "branch": proposal.branch_name,
                "files": len(files_to_create),
            })

        results["duration_ms"] = (time.monotonic() - start) * 1000

        self._bus.publish_sync(Event(
            type="evolution.cycle_complete",
            source="self_evolution",
            payload={
                "skills_created": len(results["skills_created"]),
                "agents_created": len(results["agents_created"]),
                "proposals": len(results["proposals"]),
                "decisions_made": len(results["decisions"]),
            },
        ))

        return results

    # ── AI-Powered Analysis ──────────────────────────────────

    def analyze_and_propose(self, focus: str = "") -> EvolutionProposal:
        """
        Use AI to analyze the codebase and propose specific improvements.

        This is the AI-powered version of evolve() — it reads code,
        understands patterns, and generates targeted improvements.
        """
        # Gather context about the codebase
        health = self.analyze_codebase()

        # Build analysis prompt
        prompt = self._build_analysis_prompt(health, focus)

        # Call AI for analysis
        try:
            from kernel.openclaw_bridge import get_openclaw
            oc = get_openclaw()
            response = oc.ask(
                prompt=prompt,
                system=(
                    "You are the self-evolution engine of Agency OS. "
                    "Analyze the codebase health data and propose specific, "
                    "actionable improvements. Format all code with file paths "
                    "using ```language:path/to/file format."
                ),
                agent_id="self-evolution",
            )

            if response:
                # Parse AI response into a proposal
                from kernel.action_executor import get_action_executor
                ae = get_action_executor()
                plan = ae.parse(response)

                proposal = EvolutionProposal(
                    type="ai-proposed",
                    title=f"AI Evolution: {focus or 'general improvement'}",
                    description=response[:500],
                    files_to_create=[
                        {"path": f.path, "content": f.content}
                        for f in plan.files
                    ],
                )

                self._proposals.append(proposal)
                return proposal

        except Exception as e:
            logger.error("AI analysis failed: %s", e)

        # Fallback: create a basic proposal
        return EvolutionProposal(
            type="fallback",
            title="Manual review needed",
            description=f"AI analysis unavailable. Health: {health.total_modules} modules, "
                        f"{len(health.potential_skills)} potential skills.",
        )

    def _build_analysis_prompt(self, health: CodebaseHealth, focus: str) -> str:
        """Build context for AI analysis."""
        return (
            f"## Agency OS Codebase Health Report\n\n"
            f"- **Kernel modules:** {health.total_modules}\n"
            f"- **Total LOC:** {health.total_loc}\n"
            f"- **Studios:** {health.total_studios}\n"
            f"- **Skills:** {health.total_skills}\n"
            f"- **Agents:** {health.total_agents}\n\n"
            f"### Missing Tests\n"
            + "\n".join(f"- {t}" for t in health.missing_tests[:10])
            + f"\n\n### Potential New Skills\n"
            + "\n".join(f"- {s}" for s in health.potential_skills)
            + f"\n\n### Potential New Agents\n"
            + "\n".join(f"- {a}" for a in health.potential_agents)
            + f"\n\n### Improvement Areas\n"
            + "\n".join(f"- {i}" for i in health.improvement_areas)
            + (f"\n\n### Focus Area\n{focus}" if focus else "")
            + "\n\nPropose 2-3 specific, high-impact improvements. "
              "For each, provide the COMPLETE file content using "
              "```language:path/to/file format."
        )

    # ── 6. LEARN FROM EXPERIENCE ───────────────────────────────

    # Performance thresholds that trigger self-improvement
    SLOW_THRESHOLD_MS = 30_000   # Task took > 30s = too slow
    LOW_QUALITY_THRESHOLD = 60   # Quality score < 60 = needs improvement
    HIGH_RETRY_THRESHOLD = 2     # > 2 retries = something is wrong

    def learn_from_execution(
        self,
        studio: str,
        task: str,
        duration_ms: float,
        quality_score: float,
        retries: int = 0,
        error: str = "",
    ) -> dict[str, Any]:
        """
        Called after EVERY task execution. Analyzes performance
        and auto-improves skills/agents that struggled.

        If the dev studio took 45s to build a simple page:
          → reads the dev skill
          → appends learnings: "For simple pages, use templates"
          → creates a PR with the improved skill
        """
        result = {
            "studio": studio,
            "action": "none",
            "reason": "",
            "improved_files": [],
        }

        triggers = []

        if duration_ms > self.SLOW_THRESHOLD_MS:
            triggers.append(f"slow ({duration_ms:.0f}ms > {self.SLOW_THRESHOLD_MS}ms)")

        if quality_score < self.LOW_QUALITY_THRESHOLD:
            triggers.append(f"low quality ({quality_score:.0f} < {self.LOW_QUALITY_THRESHOLD})")

        if retries > self.HIGH_RETRY_THRESHOLD:
            triggers.append(f"high retries ({retries} > {self.HIGH_RETRY_THRESHOLD})")

        if error:
            triggers.append(f"error: {error[:100]}")

        if not triggers:
            result["action"] = "none"
            result["reason"] = "Performance OK — no improvement needed"
            return result

        # Something went wrong — identify what to improve
        trigger_text = "; ".join(triggers)
        logger.info(
            "Learn from execution: %s studio triggered [%s] for task: %s",
            studio, trigger_text, task[:80],
        )

        learning = (
            f"\n\n### Learned Pattern (auto-generated)\n"
            f"- **Task:** {task[:200]}\n"
            f"- **Issue:** {trigger_text}\n"
            f"- **Lesson:** Optimize for this pattern. "
            f"Consider breaking into smaller steps or using templates.\n"
        )

        improved = []

        # Try to improve the matching skill
        skill_dir = self._root / ".agent" / "skills"
        studio_skill_map = {
            "dev": ["clean-code", "react-best-practices", "nodejs-best-practices"],
            "marketing": ["seo-fundamentals", "geo-fundamentals"],
            "sales": ["api-patterns"],
            "analytics": ["database-design", "performance-profiling"],
            "creative": ["frontend-design", "web-design-guidelines"],
            "leadops": ["api-patterns", "database-design"],
            "abm": ["api-patterns"],
        }

        skills_to_improve = studio_skill_map.get(studio, [])
        for skill_name in skills_to_improve[:1]:  # Improve the primary skill
            skill_file = skill_dir / skill_name / "SKILL.md"
            if skill_file.exists():
                content = skill_file.read_text(encoding="utf-8")
                # Append learning (don't overwrite existing content)
                if "## Learned Patterns" not in content:
                    content += "\n## Learned Patterns\n\n_Auto-generated from execution experience._\n"
                content += learning
                skill_file.write_text(content, encoding="utf-8")
                improved.append(str(skill_file.relative_to(self._root)))
                logger.info("Improved skill: %s", skill_name)

        # Try to improve the matching agent
        agents_dir = self._root / ".agent" / "agents"
        studio_agent_map = {
            "dev": "backend-specialist",
            "marketing": "product-manager",
            "sales": "product-owner",
            "creative": "frontend-specialist",
        }

        agent_name = studio_agent_map.get(studio)
        if agent_name:
            agent_file = agents_dir / f"{agent_name}.md"
            if agent_file.exists():
                content = agent_file.read_text(encoding="utf-8")
                if "## Execution Learnings" not in content:
                    content += "\n## Execution Learnings\n\n_Auto-generated from task performance._\n"
                content += learning
                agent_file.write_text(content, encoding="utf-8")
                improved.append(str(agent_file.relative_to(self._root)))
                logger.info("Improved agent: %s", agent_name)

        result["action"] = "improved"
        result["reason"] = trigger_text
        result["improved_files"] = improved

        # Log the learning decision
        self._log_decision(
            "experiential_learning", studio, 95,
            "improve", f"Auto-improved {len(improved)} files due to: {trigger_text}",
        )

        # Emit event
        self._bus.publish_sync(Event(
            type="evolution.learned",
            source="self_evolution",
            payload={
                "studio": studio,
                "triggers": triggers,
                "improved": improved,
            },
        ))

        return result

    # ── Status ───────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {
            "proposals": len(self._proposals),
            "applied": sum(1 for p in self._proposals if p.status in ("applied", "merged")),
            "pending_prs": sum(1 for p in self._proposals if p.status == "pr_created"),
            "total_decisions": len(self._decisions_log),
            "auto_acted": sum(1 for d in self._decisions_log if d["action"] == "create"),
            "deferred": sum(1 for d in self._decisions_log if d["action"] in ("skip", "defer")),
            "learned": sum(1 for d in self._decisions_log if d["action"] == "improve"),
            "history": [
                {
                    "id": p.id,
                    "type": p.type,
                    "title": p.title,
                    "status": p.status,
                    "pr_url": p.pr_url,
                    "created_at": p.created_at,
                }
                for p in self._proposals[-10:]
            ],
        }

    def get_decisions_log(self, limit: int = 20) -> list[dict]:
        """Get the full decision log for transparency."""
        return list(self._decisions_log[-limit:])


_engine: SelfEvolutionEngine | None = None


def get_evolution_engine() -> SelfEvolutionEngine:
    global _engine
    if _engine is None:
        _engine = SelfEvolutionEngine()
    return _engine

