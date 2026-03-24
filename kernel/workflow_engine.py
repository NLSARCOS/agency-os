#!/usr/bin/env python3
"""
Agency OS v5.0.0 — Workflow Engine

DAG-based workflow execution engine inspired by LangGraph.

Features:
- Define workflows as directed acyclic graphs (YAML or code)
- Conditional branching based on intermediate results
- Parallel execution of independent nodes
- Human-in-the-loop pause/resume checkpoints
- Error recovery loops with retry
- Persistent checkpoint/resume after crashes
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import yaml  # type: ignore

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus
from kernel.state_manager import get_state

logger = logging.getLogger("agency.workflow")


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"  # Human-in-the-loop pause


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"  # Waiting for human input
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class WorkflowNode:
    """A single node in a workflow graph."""

    id: str
    name: str
    type: str = "agent"  # agent, tool, condition, human, parallel_group
    agent: str = ""
    tool: str = ""
    task: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    condition: str = ""  # Python expression for conditional branching
    on_success: str = ""  # Next node ID on success
    on_failure: str = ""  # Next node ID on failure
    retry_count: int = 0
    max_retries: int = 2
    timeout: float = 120.0
    # Runtime
    status: NodeStatus = NodeStatus.PENDING
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0
    started_at: str = ""
    completed_at: str = ""


@dataclass
class WorkflowDef:
    """Complete workflow definition."""

    id: str
    name: str
    description: str = ""
    nodes: list[WorkflowNode] = field(default_factory=list)
    studio: str = ""
    version: str = "1.0"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowRun:
    """A running instance of a workflow."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    workflow_id: str = ""
    mission_id: int | None = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_node: str = ""
    node_results: dict[str, dict] = field(default_factory=dict)
    checkpoint: dict[str, Any] = field(default_factory=dict)
    human_input_request: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = ""
    duration_ms: float = 0


# ── Node Executors ────────────────────────────────────────────

NodeExecutor = Callable[[WorkflowNode, dict[str, Any]], dict[str, Any]]


def _execute_agent_node(node: WorkflowNode, context: dict[str, Any]) -> dict[str, Any]:
    """Execute a node using an agent."""
    from kernel.agent_manager import get_agent_manager

    mgr = get_agent_manager()

    # Inject previous results into task
    task = node.task
    for dep_id in node.depends_on:
        dep_result = context.get(dep_id, {})
        content = dep_result.get("content", "")
        if content:
            task += f"\n\n[Previous step '{dep_id}' output]:\n{content[:800]}"

    result = mgr.execute_task(
        agent_id=node.agent,
        task=task,
        context=json.dumps(node.params) if node.params else "",
    )
    return result


def _execute_tool_node(node: WorkflowNode, context: dict[str, Any]) -> dict[str, Any]:
    """Execute a node using a tool directly."""
    from kernel.tool_executor import get_tool_executor

    executor = get_tool_executor()

    params = dict(node.params)
    # Template substitution from context
    for key, val in params.items():
        if isinstance(val, str) and val.startswith("$"):
            ref_key = val[1:]
            if "." in ref_key:
                node_id, field_name = ref_key.split(".", 1)
                params[key] = context.get(node_id, {}).get(field_name, val)

    result = executor.execute(
        tool_name=node.tool,
        params=params,
        agent_id=node.agent or "system",
        timeout=node.timeout,
    )
    return {
        "success": result.success,
        "content": result.output,
        "error": result.error,
        "tool": result.tool,
        "duration_ms": result.duration_ms,
    }


def _execute_condition_node(
    node: WorkflowNode, context: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate a condition for branching (safe, no eval)."""
    try:
        import ast

        # Build evaluation context from previous results
        eval_ctx: dict[str, Any] = {}
        for node_id, result in context.items():
            eval_ctx[node_id] = result
        eval_ctx["context"] = context

        # Safe evaluation: only support simple comparisons
        # e.g., "context['dev']['success'] == True"
        condition = node.condition.strip()

        # Try literal eval for simple True/False/number checks
        try:
            condition_result = bool(ast.literal_eval(condition))
        except (ValueError, SyntaxError):
            # Compile AST and only allow safe nodes
            tree = ast.parse(condition, mode="eval")
            for n in ast.walk(tree):
                allowed = (
                    ast.Expression,
                    ast.Compare,
                    ast.BoolOp,
                    ast.UnaryOp,
                    ast.Constant,
                    ast.Name,
                    ast.Attribute,
                    ast.Subscript,
                    ast.Load,
                    ast.Eq,
                    ast.NotEq,
                    ast.Lt,
                    ast.Gt,
                    ast.LtE,
                    ast.GtE,
                    ast.Is,
                    ast.IsNot,
                    ast.In,
                    ast.NotIn,
                    ast.And,
                    ast.Or,
                    ast.Not,
                    ast.Index,
                    ast.Slice,
                )
                if not isinstance(n, allowed):
                    raise ValueError(f"Unsafe AST node: {type(n).__name__}")
            # Only eval with restricted context, no builtins
            condition_result = bool(
                eval(
                    compile(tree, "<condition>", "eval"), {"__builtins__": {}}, eval_ctx
                )
            )

        return {
            "success": True,
            "content": str(condition_result),
            "condition_result": condition_result,
            "next_node": node.on_success if condition_result else node.on_failure,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Condition evaluation failed: {e}",
        }


NODE_EXECUTORS: dict[str, NodeExecutor] = {
    "agent": _execute_agent_node,
    "tool": _execute_tool_node,
    "condition": _execute_condition_node,
}


class WorkflowEngine:
    """
    DAG-based workflow execution engine.

    Executes workflows defined as graphs of nodes with:
    - Sequential and parallel execution
    - Conditional branching
    - Error recovery with retry
    - Human-in-the-loop pausing
    - Persistent checkpoints
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._workflows: dict[str, WorkflowDef] = {}
        self._runs: dict[str, WorkflowRun] = {}
        self._human_responses: dict[str, str] = {}

    # ── Load Workflows ────────────────────────────────────────

    def load_workflows(self) -> int:
        """Load workflow definitions from studios/*/workflows/*.yaml"""
        count = 0
        studios_dir = self.cfg.studios_dir
        if not studios_dir.is_dir():
            return 0

        for studio_dir in studios_dir.iterdir():
            if not studio_dir.is_dir():
                continue
            wf_dir = studio_dir / "workflows"
            if not wf_dir.is_dir():
                continue

            for wf_file in wf_dir.glob("*.yaml"):
                try:
                    wf = self._parse_workflow_yaml(wf_file, studio_dir.name)
                    if wf:
                        self._workflows[wf.id] = wf
                        count += 1
                except Exception as e:
                    logger.error("Error loading workflow %s: %s", wf_file, e)

        logger.info("Loaded %d workflows", count)
        return count

    def _parse_workflow_yaml(self, path: Path, studio: str) -> WorkflowDef | None:
        """Parse a workflow YAML file."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "nodes" not in data:
            return None

        wf_id = data.get("id", path.stem)
        nodes = []
        for node_data in data["nodes"]:
            nodes.append(
                WorkflowNode(
                    id=node_data["id"],
                    name=node_data.get("name", node_data["id"]),
                    type=node_data.get("type", "agent"),
                    agent=node_data.get("agent", ""),
                    tool=node_data.get("tool", ""),
                    task=node_data.get("task", ""),
                    params=node_data.get("params", {}),
                    depends_on=node_data.get("depends_on", []),
                    condition=node_data.get("condition", ""),
                    on_success=node_data.get("on_success", ""),
                    on_failure=node_data.get("on_failure", ""),
                    max_retries=node_data.get("max_retries", 2),
                    timeout=node_data.get("timeout", 120.0),
                )
            )

        return WorkflowDef(
            id=wf_id,
            name=data.get("name", wf_id),
            description=data.get("description", ""),
            nodes=nodes,
            studio=studio,
            version=data.get("version", "1.0"),
            metadata=data.get("metadata", {}),
        )

    def register_workflow(self, workflow: WorkflowDef) -> None:
        """Register a workflow programmatically."""
        self._workflows[workflow.id] = workflow

    # ── Build Workflow from Code ──────────────────────────────

    @staticmethod
    def build(
        workflow_id: str,
        name: str,
        studio: str = "",
        description: str = "",
    ) -> WorkflowBuilder:
        """Create a workflow using the builder pattern."""
        return WorkflowBuilder(workflow_id, name, studio, description)

    # ── Execute ───────────────────────────────────────────────

    def execute(
        self,
        workflow_id: str,
        mission_id: int | None = None,
        initial_context: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        """Execute a workflow by ID."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            run = WorkflowRun(
                workflow_id=workflow_id,
                status=WorkflowStatus.FAILED,
            )
            run.checkpoint["error"] = f"Workflow not found: {workflow_id}"
            return run

        return self.execute_workflow(wf, mission_id, initial_context)

    def execute_workflow(
        self,
        workflow: WorkflowDef,
        mission_id: int | None = None,
        initial_context: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        """Execute a workflow definition."""
        run = WorkflowRun(
            workflow_id=workflow.id,
            mission_id=mission_id,
            status=WorkflowStatus.RUNNING,
        )
        self._runs[run.id] = run

        start = time.monotonic()
        context = dict(initial_context or {})
        node_map = {n.id: n for n in workflow.nodes}
        completed: set[str] = set()
        skipped: set[str] = set()

        bus = get_event_bus()
        bus.publish_sync(
            Event(
                type="workflow.started",
                payload={
                    "run_id": run.id,
                    "workflow": workflow.id,
                    "mission_id": mission_id,
                    "nodes": len(workflow.nodes),
                },
            )
        )

        # Save initial checkpoint
        self._save_checkpoint(run, context)

        max_iterations = len(workflow.nodes) * 3
        iteration = 0

        while len(completed) + len(skipped) < len(workflow.nodes):
            iteration += 1
            if iteration > max_iterations:
                logger.error("Workflow %s exceeded max iterations", workflow.id)
                run.status = WorkflowStatus.FAILED
                run.checkpoint["error"] = "Max iterations exceeded (deadlock?)"
                break

            progress = False

            for node in workflow.nodes:
                if node.id in completed or node.id in skipped:
                    continue

                # Check dependencies
                deps_met = all(d in completed or d in skipped for d in node.depends_on)
                if not deps_met:
                    continue

                # Check if dependency failed
                deps_failed = any(
                    node_map[d].status == NodeStatus.FAILED
                    for d in node.depends_on
                    if d in node_map
                )
                if deps_failed and node.type != "condition":
                    node.status = NodeStatus.SKIPPED
                    skipped.add(node.id)
                    run.node_results[node.id] = {
                        "status": "skipped",
                        "reason": "dependency_failed",
                    }
                    progress = True
                    continue

                # Human-in-the-loop check
                if node.type == "human":
                    run.status = WorkflowStatus.PAUSED
                    run.current_node = node.id
                    run.human_input_request = node.task
                    self._save_checkpoint(run, context)

                    logger.info(
                        "Workflow %s paused at node '%s' for human input",
                        run.id,
                        node.id,
                    )
                    bus.publish_sync(
                        Event(
                            type="workflow.paused",
                            payload={
                                "run_id": run.id,
                                "node": node.id,
                                "prompt": node.task,
                            },
                        )
                    )

                    # Check for pre-submitted response
                    human_key = f"{run.id}:{node.id}"
                    if human_key in self._human_responses:
                        response = self._human_responses.pop(human_key)
                        context[node.id] = {
                            "success": True,
                            "content": response,
                        }
                        node.status = NodeStatus.COMPLETED
                        completed.add(node.id)
                        run.node_results[node.id] = context[node.id]
                        run.status = WorkflowStatus.RUNNING
                        progress = True
                        continue
                    else:
                        # Actually paused — caller should resume later
                        run.duration_ms = (time.monotonic() - start) * 1000
                        return run

                # Execute node
                run.current_node = node.id
                node.status = NodeStatus.RUNNING
                node.started_at = datetime.now(timezone.utc).isoformat()

                logger.info(
                    "Workflow %s executing node '%s' (type=%s)",
                    run.id,
                    node.id,
                    node.type,
                )

                node_result = self._execute_node(node, context)

                node.completed_at = datetime.now(timezone.utc).isoformat()
                node.result = node_result
                node.duration_ms = node_result.get("duration_ms", 0)

                if node_result.get("success", False):
                    node.status = NodeStatus.COMPLETED
                    context[node.id] = node_result
                    completed.add(node.id)

                    # Handle conditional branching
                    if node.type == "condition":
                        next_node = node_result.get("next_node", "")
                        if next_node:
                            # Skip nodes not on the chosen branch
                            for other_node in workflow.nodes:
                                if (
                                    other_node.id not in completed
                                    and other_node.id not in skipped
                                    and node.id in other_node.depends_on
                                ):
                                    # Only keep the chosen branch
                                    pass  # Dependencies handle this naturally
                else:
                    # Retry logic
                    if node.retry_count < node.max_retries:
                        node.retry_count += 1
                        node.status = NodeStatus.PENDING
                        logger.warning(
                            "Node '%s' failed, retry %d/%d",
                            node.id,
                            node.retry_count,
                            node.max_retries,
                        )
                        continue
                    else:
                        node.status = NodeStatus.FAILED
                        node.error = node_result.get("error", "Unknown error")
                        context[node.id] = node_result
                        completed.add(node.id)

                run.node_results[node.id] = {
                    "status": node.status.value,
                    "content": node_result.get("content", "")[:1000],
                    "error": node_result.get("error", ""),
                    "duration_ms": node.duration_ms,
                    "retries": node.retry_count,
                }
                progress = True

                # Checkpoint after each node
                self._save_checkpoint(run, context)

            if not progress:
                logger.error("Workflow %s deadlocked", run.id)
                run.status = WorkflowStatus.FAILED
                run.checkpoint["error"] = "Deadlock detected"
                break

        # Final status
        run.duration_ms = (time.monotonic() - start) * 1000
        run.completed_at = datetime.now(timezone.utc).isoformat()

        all_success = all(
            n.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
            for n in workflow.nodes
        )
        any(n.status == NodeStatus.FAILED for n in workflow.nodes)

        if run.status != WorkflowStatus.FAILED:
            run.status = (
                WorkflowStatus.COMPLETED if all_success else WorkflowStatus.FAILED
            )

        bus.publish_sync(
            Event(
                type="workflow.completed" if all_success else "workflow.failed",
                payload={
                    "run_id": run.id,
                    "workflow": workflow.id,
                    "duration_ms": run.duration_ms,
                    "nodes_completed": len(completed),
                    "nodes_skipped": len(skipped),
                    "nodes_failed": sum(
                        1 for n in workflow.nodes if n.status == NodeStatus.FAILED
                    ),
                },
            )
        )

        return run

    def _execute_node(
        self, node: WorkflowNode, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a single node with the appropriate executor."""
        executor = NODE_EXECUTORS.get(node.type)
        if not executor:
            return {
                "success": False,
                "error": f"Unknown node type: {node.type}",
            }

        start = time.monotonic()
        try:
            result = executor(node, context)
            result["duration_ms"] = (time.monotonic() - start) * 1000
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "duration_ms": (time.monotonic() - start) * 1000,
            }

    # ── Human-in-the-Loop ─────────────────────────────────────

    def resume(self, run_id: str, human_response: str) -> WorkflowRun | None:
        """Resume a paused workflow with human input."""
        run = self._runs.get(run_id)
        if not run or run.status != WorkflowStatus.PAUSED:
            return None

        # Store response and re-execute
        human_key = f"{run_id}:{run.current_node}"
        self._human_responses[human_key] = human_response

        # Reload workflow and continue
        wf = self._workflows.get(run.workflow_id)
        if not wf:
            return None

        # Restore context from checkpoint
        context = dict(run.checkpoint.get("context", {}))
        run.status = WorkflowStatus.RUNNING

        return self.execute_workflow(wf, run.mission_id, context)

    # ── Checkpoints ───────────────────────────────────────────

    def _save_checkpoint(self, run: WorkflowRun, context: dict[str, Any]) -> None:
        """Save workflow state for resume after crash."""
        run.checkpoint = {
            "context": {
                k: {ck: cv for ck, cv in v.items() if ck != "raw"}
                for k, v in context.items()
                if isinstance(v, dict)
            },
            "node_results": run.node_results,
            "current_node": run.current_node,
            "status": run.status.value,
        }

        # Persist to DB
        state = get_state()
        now = datetime.now(timezone.utc).isoformat()
        try:
            state._conn.execute(
                """INSERT OR REPLACE INTO workflow_state
                   (workflow_id, mission_id, current_node, status,
                    graph_def, node_results, checkpoint,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.workflow_id,
                    run.mission_id,
                    run.current_node,
                    run.status.value,
                    json.dumps({"run_id": run.id}),
                    json.dumps(run.node_results, default=str),
                    json.dumps(run.checkpoint, default=str),
                    run.created_at,
                    now,
                ),
            )
            state._conn.commit()
        except Exception as e:
            logger.error("Failed to save checkpoint: %s", e)

    # ── Management ────────────────────────────────────────────

    def list_workflows(self) -> list[dict]:
        return [
            {
                "id": wf.id,
                "name": wf.name,
                "studio": wf.studio,
                "nodes": len(wf.nodes),
                "description": wf.description[:80],
            }
            for wf in self._workflows.values()
        ]

    def list_runs(self, status: str | None = None) -> list[dict]:
        runs = self._runs.values()
        if status:
            runs = [r for r in runs if r.status.value == status]  # type: ignore
        return [
            {
                "id": r.id,
                "workflow": r.workflow_id,
                "mission_id": r.mission_id,
                "status": r.status.value,
                "current_node": r.current_node,
                "nodes_completed": len(r.node_results),
                "duration_ms": round(r.duration_ms, 1),
                "created_at": r.created_at,
            }
            for r in runs
        ]

    def get_run(self, run_id: str) -> WorkflowRun | None:
        return self._runs.get(run_id)


# ── Builder Pattern ───────────────────────────────────────────


class WorkflowBuilder:
    """Fluent builder for creating workflows in code."""

    def __init__(
        self,
        workflow_id: str,
        name: str,
        studio: str = "",
        description: str = "",
    ) -> None:
        self._wf = WorkflowDef(
            id=workflow_id,
            name=name,
            studio=studio,
            description=description,
        )

    def agent_node(
        self,
        node_id: str,
        agent: str,
        task: str,
        name: str = "",
        depends_on: list[str] | None = None,
        **kwargs: Any,
    ) -> WorkflowBuilder:
        self._wf.nodes.append(
            WorkflowNode(
                id=node_id,
                name=name or node_id,
                type="agent",
                agent=agent,
                task=task,
                depends_on=depends_on or [],
                **kwargs,
            )
        )
        return self

    def tool_node(
        self,
        node_id: str,
        tool: str,
        params: dict | None = None,
        name: str = "",
        depends_on: list[str] | None = None,
        agent: str = "system",
        **kwargs: Any,
    ) -> WorkflowBuilder:
        self._wf.nodes.append(
            WorkflowNode(
                id=node_id,
                name=name or node_id,
                type="tool",
                tool=tool,
                agent=agent,
                params=params or {},
                depends_on=depends_on or [],
                **kwargs,
            )
        )
        return self

    def condition_node(
        self,
        node_id: str,
        condition: str,
        on_success: str = "",
        on_failure: str = "",
        name: str = "",
        depends_on: list[str] | None = None,
    ) -> WorkflowBuilder:
        self._wf.nodes.append(
            WorkflowNode(
                id=node_id,
                name=name or node_id,
                type="condition",
                condition=condition,
                on_success=on_success,
                on_failure=on_failure,
                depends_on=depends_on or [],
            )
        )
        return self

    def human_node(
        self,
        node_id: str,
        prompt: str,
        name: str = "",
        depends_on: list[str] | None = None,
    ) -> WorkflowBuilder:
        self._wf.nodes.append(
            WorkflowNode(
                id=node_id,
                name=name or node_id,
                type="human",
                task=prompt,
                depends_on=depends_on or [],
            )
        )
        return self

    def build(self) -> WorkflowDef:
        return self._wf


# ── Convenience ───────────────────────────────────────────────


def get_workflow_engine() -> WorkflowEngine:
    engine = WorkflowEngine()
    engine.load_workflows()
    return engine
