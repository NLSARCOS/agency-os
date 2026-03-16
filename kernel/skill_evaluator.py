import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus
from kernel.openclaw_bridge import get_openclaw

logger = logging.getLogger("agency.skill_evaluator")


@dataclass
class SkillPerformance:
    studio_or_skill: str
    total_runs: int = 0
    failures: int = 0
    avg_quality_score: float = 0.0
    latest_error_context: str = ""


class SkillEvaluator:
    """
    Abstract HR Manager for Agency OS.
    
    Monitors the performance of Studios, Agents, and Skills during projects.
    If a domain consistently fails or produces poor quality code/content,
    the evaluator autonomously rewrites the respective .md file or 
    generates a new specialized Agent.
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._bus = get_event_bus()
        self.openclaw = get_openclaw()
        
        # Track memory of runs in this session.
        # Long-term survival relies on the self-evolution auto-merge.
        self._performance: dict[str, SkillPerformance] = {}
        
        # We hook into project completions to evaluate the team
        self._bus.subscribe("project.phase_complete", self._on_phase_complete)

    def _on_phase_complete(self, event: Event) -> None:
        """Analyze how the studio performed after a phase finishes."""
        p = event.payload
        studio = p.get("studio")
        status = p.get("status")
        
        if not studio:
            return

        hw = self._performance.setdefault(studio, SkillPerformance(studio_or_skill=studio))
        hw.total_runs += 1
        
        if status == "failed":
            hw.failures += 1
            # Retrieve error context if possible (from project context, not fully wired here yet, 
            # so we just flag it)
            hw.latest_error_context = "Phase failed during execution."
            
        logger.debug(f"Evaluator tracked {studio}: {hw.failures}/{hw.total_runs} failures")
        
        # Automatically trigger an evaluation if we've gathered enough data
        if hw.total_runs >= 3:
            self.evaluate_studio(studio)

    def evaluate_studio(self, studio: str) -> None:
        """Evaluate if a studio needs to be fired/rehired (rewritten)."""
        perf = self._performance.get(studio)
        if not perf:
            return

        failure_rate = perf.failures / perf.total_runs if perf.total_runs > 0 else 0

        # If a studio fails more than 40% of the time, or has 3 straight failures, it's bad.
        if failure_rate > 0.4 or perf.failures >= 3:
            logger.warning(
                f"Studio '{studio}' is underperforming (Failure Rate: {failure_rate*100:.1f}%). "
                f"Initiating autonomous Skill/Agent restructuring."
            )
            
            # Announce via bus
            self._bus.publish_sync(Event(
                type="agency.hr.restructuring",
                source="skill_evaluator",
                payload={"studio": studio, "reason": "High failure rate"},
            ))
            
            self._restructure_domain(studio, perf.latest_error_context)
            
            # Reset metrics after restructuring attempt
            perf.failures = 0
            perf.total_runs = 0

    def _restructure_domain(self, domain: str, context: str) -> bool:
        """
        Takes drastic action:
        1. Try to find the existing SKILL.md or AGENT.md for this domain.
        2. Rewrite it using AI to be better and fix its blind spots.
        3. If it doesn't exist, create a new Agent.
        """
        agents_dir = self.cfg.root / ".agent" / "agents"
        skills_dir = self.cfg.root / ".agent" / "skills"
        
        # Look for existing files
        target_file = None
        
        # Check agents first
        agent_file = agents_dir / f"{domain}.md"
        if agent_file.exists():
            target_file = agent_file
            
        # Check skills if no agent
        if not target_file:
            # Domain might end in -specialist or similar, do a fuzzy match
            for p in skills_dir.glob("*/SKILL.md"):
                if domain.lower() in str(p.parent.name).lower():
                    target_file = p
                    break

        if target_file and target_file.exists():
            # Rewrite existing
            return self._rewrite_existing(target_file, domain, context)
        else:
            # Create new
            return self._create_new_agent(domain, context)

    def _rewrite_existing(self, filepath: Path, domain: str, error_context: str) -> bool:
        """Ask the AI to improve its own instruction file."""
        logger.info(f"Rewriting underperforming abstract employee: {filepath.name}")
        
        current_content = filepath.read_text(encoding="utf-8")
        
        prompt = (
            f"You are the Meta-HR AI of Agency OS.\n"
            f"The abstract employee (Agent/Skill) responsible for '{domain}' is FAILING in production.\n"
            f"Context of failure: {error_context}\n\n"
            f"Current Instructions:\n```\n{current_content}\n```\n\n"
            f"REWRITE this file completely to make it more resilient, robust, and capable.\n"
            f"Output ONLY the raw markdown file contents designed for an AI to read. Do not output anything else."
        )
        
        try:
            new_content = self.openclaw.ask(
                prompt=prompt,
                system="You are an expert prompt engineer and AI supervisor. Fix the fragile instructions.",
                agent_id="meta-hr"
            )
            
            if new_content and len(new_content) > 100:
                # Basic cleanup
                new_content = new_content.removeprefix("```markdown\n").removesuffix("\n```")
                new_content = new_content.removeprefix("```\n").removesuffix("\n```")
                
                filepath.write_text(new_content, encoding="utf-8")
                
                self._bus.publish_sync(Event(
                    type="agency.hr.promoted",
                    source="skill_evaluator",
                    payload={"file": str(filepath.name), "action": "rewritten"},
                ))
                return True
                
        except Exception as e:
            logger.error(f"Failed to rewrite {domain}: {e}")
            
        return False

    def _create_new_agent(self, domain: str, required_capability: str) -> bool:
        """If the agency encounters a problem it has no concept for, it hires a new Agent."""
        agents_dir = self.cfg.root / ".agent" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        
        agent_name = re.sub(r'[^a-zA-Z0-9-]', '-', domain.lower().strip())
        if not agent_name.endswith("-specialist") and not agent_name.endswith("-agent"):
            agent_name += "-specialist"
            
        new_file = agents_dir / f"{agent_name}.md"
        
        logger.info(f"Hiring new abstract employee: {agent_name}")
        
        prompt = (
            f"You are the Meta-HR AI of Agency OS.\n"
            f"The agency urgently needs a new expert agent for the domain: '{domain}'.\n"
            f"Context why we need this: {required_capability}\n\n"
            f"Create the full AGENT.md markdown file for this new role.\n"
            f"It must include exactly this frontmatter at the top:\n"
            f"---\nname: {agent_name}\ndescription: [short description]\nskills: [relevant skills, e.g. python-patterns]\n---\n\n"
            f"Then write the exact rules, principles, and workflows this agent must follow.\n"
            f"Output ONLY the raw markdown content."
        )
        
        try:
            new_content = self.openclaw.ask(
                prompt=prompt,
                system="You are an expert Prompt Engineer creating a new functional Specialist AI.",
                agent_id="meta-hr"
            )
            
            if new_content and len(new_content) > 100:
                new_content = new_content.removeprefix("```markdown\n").removesuffix("\n```")
                new_content = new_content.removeprefix("```\n").removesuffix("\n```")
                
                new_file.write_text(new_content, encoding="utf-8")
                
                self._bus.publish_sync(Event(
                    type="agency.hr.hired",
                    source="skill_evaluator",
                    payload={"agent": agent_name, "action": "created"},
                ))
                
                # We optionally trigger the Evolution Engine to commit this straight to git.
                # However, since Heartbeat manages global evolution cycle, we just leave it in the FS for now.
                return True
                
        except Exception as e:
            logger.error(f"Failed to hire {agent_name}: {e}")
            
        return False


_evaluator: SkillEvaluator | None = None


def get_skill_evaluator() -> SkillEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = SkillEvaluator()
    return _evaluator
