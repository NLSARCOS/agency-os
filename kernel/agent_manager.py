#!/usr/bin/env python3
"""
Agency OS v3.0 — Agent Manager

Manages agent lifecycle: loading from .agent/agents/*.md,
delegation chains, inter-agent communication, and crew assembly.

Inspired by CrewAI roles/goals/backstories + AutoGen conversations.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from kernel.config import get_config
from kernel.event_bus import Event, EventBus, get_event_bus
from kernel.model_router import ModelRouter
from kernel.openclaw_bridge import ChatMessage, OpenClawBridge, get_openclaw
from kernel.tool_executor import ToolExecutor, ToolResult, get_tool_executor

logger = logging.getLogger("agency.agents")


@dataclass
class AgentProfile:
    """Profile loaded from .agent/agents/*.md"""
    id: str
    name: str
    description: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    model: str = ""
    system_prompt: str = ""
    backstory: str = ""
    goal: str = ""
    # Runtime state
    active: bool = False
    memory: list[dict] = field(default_factory=list)
    max_memory: int = 50
    stats: dict[str, int] = field(default_factory=lambda: {
        "tasks_completed": 0, "tasks_failed": 0,
        "delegations_sent": 0, "delegations_received": 0,
        "tools_used": 0, "tokens_total": 0,
    })


@dataclass
class DelegationRequest:
    """Request from one agent to another."""
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    from_agent: str = ""
    to_agent: str = ""
    task: str = ""
    context: str = ""
    priority: str = "normal"
    status: str = "pending"  # pending, accepted, completed, failed
    result: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AgentManager:
    """
    Manages the full lifecycle of AI agents.

    Features:
    - Load agent definitions from .agent/agents/*.md
    - Create agent sessions with OpenClaw
    - Execute tasks with tool access
    - Handle delegation chains between agents
    - Maintain per-agent memory (short-term)
    - Assemble dynamic crews for complex missions
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._agents: dict[str, AgentProfile] = {}
        self._delegations: list[DelegationRequest] = []
        self._openclaw: OpenClawBridge | None = None
        self._model_router: ModelRouter | None = None
        self._tools: ToolExecutor | None = None
        self._bus: EventBus | None = None
        self._skill_cache: dict[str, str] = {}

    def _get_openclaw(self) -> OpenClawBridge:
        if self._openclaw is None:
            self._openclaw = get_openclaw()
        return self._openclaw

    def _get_model_router(self) -> ModelRouter:
        if self._model_router is None:
            self._model_router = ModelRouter()
        return self._model_router

    def _get_tools(self) -> ToolExecutor:
        if self._tools is None:
            self._tools = get_tool_executor()
        return self._tools

    def _get_bus(self) -> EventBus:
        if self._bus is None:
            self._bus = get_event_bus()
        return self._bus

    # ── Load Agents ───────────────────────────────────────────

    def load_agents(self) -> int:
        """Load agent definitions from .agent/agents/*.md files."""
        agents_dir = self.cfg.root / ".agent" / "agents"
        if not agents_dir.is_dir():
            logger.warning("No agents directory found: %s", agents_dir)
            return 0

        count = 0
        for md_file in sorted(agents_dir.glob("*.md")):
            try:
                profile = self._parse_agent_file(md_file)
                if profile:
                    self._agents[profile.id] = profile
                    count += 1
                    logger.debug("Loaded agent: %s", profile.id)
            except Exception as e:
                logger.error("Error loading agent %s: %s", md_file.name, e)

        logger.info("Loaded %d agents from %s", count, agents_dir)
        return count

    def _parse_agent_file(self, path: Path) -> AgentProfile | None:
        """Parse an agent .md file with YAML frontmatter."""
        content = path.read_text(encoding="utf-8")

        # Extract YAML frontmatter
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not fm_match:
            return None

        frontmatter = fm_match.group(1)
        body = content[fm_match.end():]

        # Parse frontmatter fields
        def _get_field(name: str, default: str = "") -> str:
            m = re.search(rf"^{name}:\s*(.+)$", frontmatter, re.MULTILINE)
            return m.group(1).strip() if m else default

        agent_id = _get_field("name", path.stem)
        description = _get_field("description")
        tools_raw = _get_field("tools")
        skills_raw = _get_field("skills")
        model = _get_field("model", "inherit")

        tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]

        return AgentProfile(
            id=agent_id,
            name=agent_id.replace("-", " ").title(),
            description=description,
            tools=tools,
            skills=skills,
            model=model,
            system_prompt=body.strip(),
            backstory=f"Expert {agent_id} agent for Agency OS",
            goal=description,
        )

    # ── Get Agents ────────────────────────────────────────────

    def get_agent(self, agent_id: str) -> AgentProfile | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[dict]:
        return [
            {
                "id": a.id,
                "name": a.name,
                "description": a.description[:100],
                "skills": a.skills[:5],
                "active": a.active,
                "tasks_completed": a.stats["tasks_completed"],
            }
            for a in self._agents.values()
        ]

    # ── Load Skills ───────────────────────────────────────────

    def _load_skill_knowledge(self, skill_name: str) -> str:
        """Load skill content from .agent/skills/<name>/SKILL.md."""
        if skill_name in self._skill_cache:
            return self._skill_cache[skill_name]

        skill_path = self.cfg.root / ".agent" / "skills" / skill_name / "SKILL.md"
        if skill_path.exists():
            content = skill_path.read_text(encoding="utf-8")
            # Truncate to keep context manageable
            if len(content) > 3000:
                content = content[:3000] + "\n...[truncated]"
            self._skill_cache[skill_name] = content
            return content
        return ""

    def _build_system_prompt(self, agent: AgentProfile) -> str:
        """Build a comprehensive system prompt including agent definition + skills."""
        from kernel.config import get_config
        cfg = get_config()

        # Language directive
        lang_map = {
            "es": "IMPORTANTE: DEBES responder SIEMPRE en español. Todo tu output, análisis, reportes, briefings y resultados deben estar en español.",
            "pt": "IMPORTANTE: Você DEVE responder SEMPRE em português. Toda a sua saída deve ser em português.",
            "fr": "IMPORTANT: Vous DEVEZ toujours répondre en français.",
            "de": "WICHTIG: Sie MÜSSEN immer auf Deutsch antworten.",
        }
        lang_instruction = lang_map.get(cfg.language, "")

        parts = [
            f"You are {agent.name}, part of Agency OS — an autonomous AI agency.",
            f"Goal: {agent.goal}",
        ]

        if lang_instruction:
            parts.append("")
            parts.append(f"# Language\n{lang_instruction}")

        parts.append("")
        parts.append("# Agent Definition")
        parts.append(agent.system_prompt[:4000])

        # Load relevant skills (max 2 to keep context tight)
        loaded_skills = 0
        for skill_name in agent.skills[:3]:
            knowledge = self._load_skill_knowledge(skill_name)
            if knowledge and loaded_skills < 2:
                parts.append(f"\n# Skill: {skill_name}")
                parts.append(knowledge[:2000])
                loaded_skills += 1

        parts.append("\n# Rules")
        parts.append("- Be concise and actionable")
        parts.append("- Use tools when needed for real operations")
        parts.append("- Delegate to specialist agents when task is outside your expertise")
        parts.append("- Report results in structured format")
        if lang_instruction:
            parts.append(f"- {lang_instruction}")

        return "\n".join(parts)

    # ── Execute Task (ReAct Loop + OpenClaw-first) ─────────────

    MAX_REACT_ITERATIONS = 8
    TASK_TIMEOUT_SECONDS = 300  # 5 minutes max per task

    def execute_task(
        self,
        agent_id: str,
        task: str,
        context: str = "",
        tools_enabled: bool = True,
        studio: str = "",
    ) -> dict[str, Any]:
        """
        Execute a task using a specific agent with ReAct tool-calling loop.

        Flow (ReAct pattern — inspired by CrewAI/LangGraph):
        1. Load agent profile + skills → build system prompt
        2. Call LLM (OpenClaw first → ModelRouter fallback)
        3. If LLM returns tool_calls → execute tools → feed results back
        4. Repeat until LLM gives final answer or max iterations
        5. Return result with all tool outputs
        """
        agent = self._agents.get(agent_id)
        if not agent:
            return {"success": False, "error": f"Unknown agent: {agent_id}"}

        agent.active = True
        start = time.monotonic()

        system_prompt = self._build_system_prompt(agent)

        # Build user message with context
        user_msg = task
        if context:
            user_msg = f"Context:\n{context}\n\nTask:\n{task}"

        # Add recent memory for context continuity
        if agent.memory:
            recent = agent.memory[-3:]
            memory_context = "\n".join(
                f"[Previous] {m.get('role', '')}: {m.get('content', '')[:300]}"
                for m in recent
            )
            if memory_context:
                user_msg = f"Recent context:\n{memory_context}\n\n{user_msg}"

        # Inject learnings from past missions
        try:
            from kernel.mission_learner import get_mission_learner
            learner = get_mission_learner()
            summary = learner.get_learning_summary()
            tips = []
            for insight in summary.get("model_insights", [])[:2]:
                tips.append(f"• {insight}")
            for insight in summary.get("recommendations", [])[:2]:
                tips.append(f"• {insight}")
            if tips:
                user_msg += "\n\n[System Learnings]\n" + "\n".join(tips)
        except Exception:
            pass  # Non-critical

        # Determine studio for model selection
        target_studio = studio or self._studio_for_agent(agent_id) or "dev"

        # Build tool definitions if tools are enabled
        tool_defs = self._build_tool_defs(agent_id) if tools_enabled else []

        # ── ReAct Loop: LLM → Tools → LLM → ... → Final Answer ──
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_msg),
        ]
        all_tool_results: list[dict] = []
        content = ""
        model_used = ""
        provider_used = ""

        for iteration in range(self.MAX_REACT_ITERATIONS):
            # Timeout check
            elapsed = time.monotonic() - start
            if elapsed > self.TASK_TIMEOUT_SECONDS:
                logger.warning(
                    "Agent %s task timed out after %.0fs", agent_id, elapsed
                )
                break

            # ── Call LLM (OpenClaw first, then ModelRouter fallback) ──
            response = self._call_llm(
                messages=messages,
                agent_id=agent_id,
                agent=agent,
                studio=target_studio,
                system_prompt=system_prompt,
                tools=tool_defs if tools_enabled else None,
            )

            if not response["success"]:
                agent.stats["tasks_failed"] += 1
                agent.active = False
                return {
                    "success": False,
                    "error": response.get("error", "LLM call failed"),
                    "agent": agent_id,
                    "tool_results": all_tool_results,
                }

            content = response["content"]
            model_used = response.get("model", "")
            provider_used = response.get("provider", "")
            tool_calls = response.get("tool_calls", [])

            # If no tool calls → final answer, break
            if not tool_calls:
                logger.info(
                    "Agent %s: final answer at iteration %d",
                    agent_id, iteration + 1,
                )
                break

            # ── Execute tool calls ──
            logger.info(
                "Agent %s: %d tool_calls at iteration %d",
                agent_id, len(tool_calls), iteration + 1,
            )

            # Add assistant message with tool_calls to conversation
            messages.append(ChatMessage(
                role="assistant",
                content=content or "",
                tool_calls=tool_calls,
            ))

            # Execute each tool and add results
            tool_results = self._execute_tool_calls(agent_id, tool_calls)
            for tc, result in zip(tool_calls, tool_results):
                tool_name = tc.get("function", {}).get("name", "unknown")
                result_text = result.output if result.success else f"Error: {result.error}"
                all_tool_results.append({
                    "tool": tool_name,
                    "success": result.success,
                    "output": result_text[:2000],
                })
                # Add tool result message for next LLM iteration
                messages.append(ChatMessage(
                    role="tool",
                    content=result_text[:2000],
                    tool_call_id=tc.get("id", ""),
                    name=tool_name,
                ))

        # ── Finalize ──
        self._update_memory(agent, task, content)
        agent.stats["tasks_completed"] += 1
        agent.active = False
        duration = (time.monotonic() - start) * 1000

        # Emit event
        bus = self._get_bus()
        bus.publish_sync(Event(
            type="agent.task_completed",
            payload={
                "agent": agent_id, "task": task[:100],
                "duration_ms": duration,
                "model": model_used,
                "provider": provider_used,
                "studio": target_studio,
                "tools_used": len(all_tool_results),
            },
            source=agent_id,
        ))

        return {
            "success": True,
            "agent": agent_id,
            "content": content,
            "model": model_used,
            "provider": provider_used,
            "studio": target_studio,
            "duration_ms": round(duration, 1),
            "tool_results": all_tool_results,
            "react_iterations": min(iteration + 1, self.MAX_REACT_ITERATIONS),
        }

    def _call_llm(
        self,
        messages: list[ChatMessage],
        agent_id: str,
        agent: AgentProfile,
        studio: str,
        system_prompt: str,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        Call LLM with OpenClaw-first strategy + ModelRouter fallback.
        Returns dict with: success, content, model, provider, tool_calls
        """
        # ── Strategy 1: OpenClaw (primary — supports tools + sessions) ──
        try:
            oc = self._get_openclaw()
            if oc.is_available():
                response = oc.chat(
                    messages=messages,
                    system=system_prompt,
                    agent_id=agent_id,
                    model=agent.model if agent.model != "inherit" else "",
                    tools=tools,
                )
                if response.success and response.content:
                    return {
                        "success": True,
                        "content": response.content,
                        "model": response.model,
                        "provider": f"openclaw:{response.provider}",
                        "tool_calls": response.tool_calls or [],
                    }
                elif response.success and response.tool_calls:
                    # Tool calls with no text content (valid)
                    return {
                        "success": True,
                        "content": "",
                        "model": response.model,
                        "provider": f"openclaw:{response.provider}",
                        "tool_calls": response.tool_calls,
                    }
                else:
                    logger.warning(
                        "OpenClaw returned empty for %s: %s",
                        agent_id, response.error,
                    )
        except Exception as e:
            logger.warning("OpenClaw failed for %s: %s", agent_id, e)

        # ── Strategy 2: ModelRouter fallback (multi-provider) ──
        try:
            router = self._get_model_router()
            # Extract the user prompt from messages for the router
            user_prompt = ""
            for m in reversed(messages):
                if m.role == "user":
                    user_prompt = m.content
                    break
            if not user_prompt:
                user_prompt = messages[-1].content if messages else ""

            # FIX C1: call_model(prompt, studio, system) — correct order
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(
                            asyncio.run,
                            router.call_model(
                                prompt=user_prompt,
                                studio=studio,
                                system=system_prompt,
                            ),
                        )
                        resp = future.result(timeout=self.TASK_TIMEOUT_SECONDS)
                else:
                    resp = asyncio.run(
                        router.call_model(
                            prompt=user_prompt,
                            studio=studio,
                            system=system_prompt,
                        )
                    )
            except RuntimeError:
                resp = asyncio.run(
                    router.call_model(
                        prompt=user_prompt,
                        studio=studio,
                        system=system_prompt,
                    )
                )

            if resp.success:
                return {
                    "success": True,
                    "content": resp.content,
                    "model": resp.model,
                    "provider": resp.provider,
                    "tool_calls": [],  # ModelRouter doesn't support tool_calls
                }
            else:
                return {
                    "success": False,
                    "error": resp.error or "ModelRouter returned empty",
                }
        except Exception as e:
            logger.error("All LLM backends failed for %s: %s", agent_id, e)
            return {"success": False, "error": str(e)}

    def _studio_for_agent(self, agent_id: str) -> str:
        """Map agent to its most likely studio for model selection."""
        mapping = {
            "backend-specialist": "dev",
            "frontend-specialist": "dev",
            "devops-engineer": "dev",
            "product-owner": "sales",
            "product-manager": "marketing",
            "project-planner": "analytics",
        }
        return mapping.get(agent_id, "dev")

    # ── Tool Integration ──────────────────────────────────────

    def _build_tool_defs(self, agent_id: str) -> list[dict]:
        """Build OpenAI-compatible tool definitions for an agent."""
        executor = self._get_tools()
        available = executor.list_tools(agent_id=agent_id)
        defs = []
        for tool in available:
            if not tool.get("available", True):
                continue
            # Build function schema
            params = self._tool_params(tool["name"])
            defs.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": params,
                },
            })
        return defs

    @staticmethod
    def _tool_params(tool_name: str) -> dict:
        """Return JSON schema for tool parameters."""
        schemas: dict[str, dict] = {
            "shell": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["command"],
            },
            "read_file": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["path"],
            },
            "write_file": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            "http_request": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to request"},
                    "method": {"type": "string", "description": "HTTP method"},
                    "headers": {"type": "object", "description": "Request headers"},
                    "body": {"type": "object", "description": "Request body"},
                },
                "required": ["url"],
            },
            "search_web": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
            "scrape_url": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to scrape"},
                },
                "required": ["url"],
            },
            "git_status": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Repository path"},
                },
            },
            "git_commit": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                    "files": {"type": "string", "description": "Files to stage"},
                },
                "required": ["message"],
            },
        }
        return schemas.get(tool_name, {"type": "object", "properties": {}})

    def _execute_tool_calls(
        self, agent_id: str, tool_calls: list[dict]
    ) -> list[ToolResult]:
        """Execute tool calls returned by the LLM."""
        executor = self._get_tools()
        results = []
        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            try:
                params = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                params = {}

            result = executor.execute(
                tool_name=tool_name,
                params=params,
                agent_id=agent_id,
            )
            results.append(result)

            # Update agent stats
            agent = self._agents.get(agent_id)
            if agent:
                agent.stats["tools_used"] += 1

        return results

    # ── Memory ────────────────────────────────────────────────

    _MEMORY_CONTENT_LIMIT = 2000  # Was 500 — too aggressive truncation

    def _update_memory(
        self, agent: AgentProfile, task: str, response: str
    ) -> None:
        """Update agent's memory (in-memory + persistent SQLite)."""
        limit = self._MEMORY_CONTENT_LIMIT
        agent.memory.append({
            "role": "user",
            "content": task[:limit],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        agent.memory.append({
            "role": "assistant",
            "content": response[:limit],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Prune old memories
        if len(agent.memory) > agent.max_memory:
            agent.memory = agent.memory[-agent.max_memory:]

        # Persist to SQLite
        try:
            from kernel.state_manager import get_state
            state = get_state()
            state.save_agent_memory(agent.id, "user", task[:limit])
            state.save_agent_memory(agent.id, "assistant", response[:limit])
        except Exception as e:
            logger.debug("Memory persistence failed: %s", e)

    def get_agent_memory(self, agent_id: str, limit: int = 10) -> list[dict]:
        agent = self._agents.get(agent_id)
        # Try in-memory first
        if agent and agent.memory:
            return agent.memory[-limit:]
        # Fall back to SQLite (persistent memory)
        try:
            from kernel.state_manager import get_state
            state = get_state()
            return state.load_agent_memory(agent_id, limit)
        except Exception:
            return []

    def clear_agent_memory(self, agent_id: str) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.memory.clear()

    # ── Delegation ────────────────────────────────────────────

    def delegate(
        self,
        from_agent: str,
        to_agent: str,
        task: str,
        context: str = "",
    ) -> DelegationRequest:
        """
        Delegate a task from one agent to another.
        Implements CrewAI-style delegation chains.
        """
        delegation = DelegationRequest(
            from_agent=from_agent,
            to_agent=to_agent,
            task=task,
            context=context,
        )
        self._delegations.append(delegation)

        # Update stats
        from_a = self._agents.get(from_agent)
        if from_a:
            from_a.stats["delegations_sent"] += 1
        to_a = self._agents.get(to_agent)
        if to_a:
            to_a.stats["delegations_received"] += 1

        # Execute the delegation
        logger.info(
            "Delegation: %s → %s: %s",
            from_agent, to_agent, task[:80],
        )

        result = self.execute_task(
            agent_id=to_agent,
            task=task,
            context=f"Delegated by {from_agent}.\n{context}",
        )

        delegation.status = "completed" if result["success"] else "failed"
        delegation.result = result.get("content", result.get("error", ""))[:1000]

        # Emit delegation event
        bus = self._get_bus()
        bus.publish_sync(Event(
            type="agent.delegation",
            payload={
                "from": from_agent, "to": to_agent,
                "task": task[:100], "status": delegation.status,
            },
            source=from_agent,
            target=to_agent,
        ))

        return delegation

    # ── Crew Assembly ─────────────────────────────────────────

    def assemble_crew(
        self, mission_type: str
    ) -> list[str]:
        """
        Assemble a dynamic crew of agents for a mission type.
        Inspired by CrewAI crew concept.
        """
        crews: dict[str, list[str]] = {
            "development": ["backend-specialist", "frontend-specialist", "devops-engineer"],
            "marketing": ["product-manager", "frontend-specialist"],
            "sales": ["product-owner", "product-manager"],
            "leadops": ["backend-specialist"],
            "abm": ["product-manager", "product-owner"],
            "analytics": ["backend-specialist"],
            "creative": ["frontend-specialist", "product-manager"],
            "full_agency": [
                "product-owner", "product-manager", "project-planner",
                "backend-specialist", "frontend-specialist",
            ],
        }

        crew_ids = crews.get(mission_type, ["backend-specialist"])
        # Filter to only loaded agents
        available = [a for a in crew_ids if a in self._agents]
        logger.info("Assembled crew for '%s': %s", mission_type, available)
        return available

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "total_agents": len(self._agents),
            "active_agents": sum(1 for a in self._agents.values() if a.active),
            "total_delegations": len(self._delegations),
            "agents": self.list_agents(),
        }

    def get_delegation_history(self, limit: int = 20) -> list[dict]:
        return [
            {
                "id": d.id, "from": d.from_agent, "to": d.to_agent,
                "task": d.task[:80], "status": d.status,
                "created_at": d.created_at,
            }
            for d in self._delegations[-limit:]
        ]


_agent_manager: AgentManager | None = None


def get_agent_manager() -> AgentManager:
    """Singleton — reuses the same instance to preserve agent memory/state."""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager()
        _agent_manager.load_agents()
    return _agent_manager
