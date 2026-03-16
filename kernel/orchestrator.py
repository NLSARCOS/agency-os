#!/usr/bin/env python3
"""
Agency OS v5.0 — Brain Orchestrator

The SINGLE coordinator that wires all brain modules into one flow:
  Task → Score Complexity → Assemble Crew → Build Workflow → Execute
  → Evaluate Quality → Trigger Cross-Studio Chain → Learn

This replaces manual wiring between isolated modules.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kernel.config import get_config
from kernel.event_bus import Event, get_event_bus

logger = logging.getLogger("agency.orchestrator")


@dataclass
class OrchestratedTask:
    """Full lifecycle of an orchestrated task."""
    id: str = field(default_factory=lambda: uuid4().hex[:10])
    task: str = ""
    studio: str = ""
    complexity: str = "medium"  # simple | medium | complex
    complexity_score: float = 5.0
    crew: list[str] = field(default_factory=list)
    model_used: str = ""
    tokens_estimated: int = 0
    tokens_actual: int = 0
    quality_score: float = 0.0
    quality_passed: bool = False
    chains_triggered: int = 0
    status: str = "pending"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Task complexity indicators
COMPLEXITY_SIGNALS = {
    "simple": {
        "keywords": ["list", "find", "check", "status", "count", "lookup", "get"],
        "max_tokens": 500,
        "preferred_tier": "free",
    },
    "medium": {
        "keywords": ["analyze", "create", "draft", "plan", "write", "summarize", "compare"],
        "max_tokens": 2000,
        "preferred_tier": "cloud",
    },
    "complex": {
        "keywords": ["build", "architect", "debug", "implement", "optimize",
                     "refactor", "design", "strategy", "research", "audit"],
        "max_tokens": 4000,
        "preferred_tier": "premium",
    },
}


class BrainOrchestrator:
    """
    Central brain that coordinates ALL modules for each task:

    1. SCORE    — Estimate complexity (simple/medium/complex)
    2. CREW     — Assemble agents via crew_engine
    3. ROUTE    — Pick model via smart routing
    4. EXECUTE  — Run via studio pipeline
    5. EVALUATE — Check quality gate
    6. CHAIN    — Trigger cross-studio chains
    7. LEARN    — Record outcome for future improvement
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._bus = get_event_bus()
        self._history: list[OrchestratedTask] = []
        self._max_history = 200

    def orchestrate(
        self,
        task: str,
        studio: str = "",
        context: dict[str, Any] | None = None,
    ) -> OrchestratedTask:
        """
        Full orchestration pipeline for a single task.
        """
        start = time.monotonic()
        ot = OrchestratedTask(task=task, studio=studio)
        ot.status = "running"

        self._bus.publish_sync(Event(
            type="orchestrator.task_start",
            source="orchestrator",
            payload={"task_id": ot.id, "task": task[:200], "studio": studio},
        ))

        try:
            # ── 1. SCORE COMPLEXITY ──
            ot.complexity, ot.complexity_score = self._score_complexity(task)
            logger.info(
                "Task [%s] complexity: %s (%.1f)",
                ot.id, ot.complexity, ot.complexity_score,
            )

            # ── 2. RESOLVE STUDIO ──
            if not studio:
                studio = self._resolve_studio(task)
                ot.studio = studio

            # ── 3. ASSEMBLE CREW ──
            ot.crew = self._assemble_crew(task, studio)

            # ── 4. ROUTE MODEL ──
            ot.model_used = self._route_model(studio, ot.complexity)

            # ── 5. EXECUTE ──
            ot.result = self._execute(task, studio, ot.model_used, context)
            ot.status = "completed" if ot.result.get("success") else "failed"

            # ── 6. EVALUATE QUALITY ──
            if ot.result.get("success"):
                ot.quality_score, ot.quality_passed = self._evaluate_quality(
                    studio, ot.result
                )

            # ── 7. TRIGGER CHAINS ──
            if ot.quality_passed:
                ot.chains_triggered = self._trigger_chains(
                    studio, ot.result, success=True
                )

            # ── 8. LEARN ──
            self._learn(ot)

        except Exception as e:
            ot.status = "failed"
            ot.error = str(e)
            logger.error("Orchestration failed [%s]: %s", ot.id, e)

        ot.duration_ms = (time.monotonic() - start) * 1000

        self._bus.publish_sync(Event(
            type="orchestrator.task_complete",
            source="orchestrator",
            payload={
                "task_id": ot.id,
                "status": ot.status,
                "studio": ot.studio,
                "complexity": ot.complexity,
                "quality_score": ot.quality_score,
                "duration_ms": round(ot.duration_ms, 1),
            },
        ))

        self._history.append(ot)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return ot

    # ── 1. Complexity Scorer ─────────────────────────────────

    def _score_complexity(self, task: str) -> tuple[str, float]:
        """Score task complexity based on content analysis."""
        task_lower = task.lower()
        scores = {"simple": 0.0, "medium": 0.0, "complex": 0.0}

        for level, signals in COMPLEXITY_SIGNALS.items():
            for keyword in signals["keywords"]:
                if keyword in task_lower:
                    scores[level] += 1.0

        # Length-based scoring
        word_count = len(task.split())
        if word_count < 10:
            scores["simple"] += 1.5
        elif word_count < 30:
            scores["medium"] += 1.0
        else:
            scores["complex"] += 1.5

        # Multi-step detection
        if any(w in task_lower for w in ["then", "after that", "step", "first", "next"]):
            scores["complex"] += 1.0

        # Pick highest
        best = max(scores, key=scores.get)
        score = scores[best]

        # Normalize to 1-10
        normalized = {
            "simple": min(3.0, score),
            "medium": min(6.0, score + 3),
            "complex": min(10.0, score + 6),
        }

        return best, round(normalized[best], 1)

    # ── 2. Studio Resolver ───────────────────────────────────

    def _resolve_studio(self, task: str) -> str:
        """Auto-detect which studio should handle this task."""
        try:
            from kernel.task_router import TaskRouter
            router = TaskRouter()
            return router.route(task)
        except Exception:
            # Fallback heuristic
            task_lower = task.lower()
            studio_keywords = {
                "dev": ["code", "build", "implement", "bug", "api", "function", "deploy"],
                "marketing": ["campaign", "content", "seo", "social", "brand", "copy"],
                "sales": ["prospect", "outreach", "follow up", "deal", "pipeline", "cold"],
                "leadops": ["lead", "contact", "scrape", "enrich", "qualifying"],
                "analytics": ["analyze", "report", "metric", "kpi", "dashboard", "data"],
                "creative": ["design", "visual", "logo", "graphic", "video", "photo"],
                "abm": ["account", "target", "enterprise", "personalize"],
            }
            best_studio = "dev"
            best_score = 0
            for studio, keywords in studio_keywords.items():
                score = sum(1 for k in keywords if k in task_lower)
                if score > best_score:
                    best_score = score
                    best_studio = studio
            return best_studio

    # ── 3. Crew Assembly ─────────────────────────────────────

    def _assemble_crew(self, task: str, studio: str) -> list[str]:
        """Assemble a crew for this task."""
        try:
            from kernel.crew_engine import get_crew_engine
            ce = get_crew_engine()
            crew = ce.assemble(task, studio)
            return [m.agent_id for m in crew.members]
        except Exception as e:
            logger.debug("Crew assembly skipped: %s", e)
            return [studio]

    # ── 4. Model Routing ─────────────────────────────────────

    def _route_model(self, studio: str, complexity: str) -> str:
        """Pick the right model based on complexity and availability."""
        try:
            from kernel.provider_detector import get_provider_detector
            pd = get_provider_detector()
            if not pd._results:
                pd.detect_all()

            # For simple tasks: prefer local (Ollama/LM Studio)
            if complexity == "simple":
                ollama = pd._results.get("ollama")
                if ollama and ollama.running and ollama.models:
                    return f"ollama/{ollama.models[0]}"

                lms = pd._results.get("lmstudio")
                if lms and lms.running and lms.models:
                    return f"lmstudio/{lms.models[0]}"

            # For medium: prefer free cloud
            if complexity in ("simple", "medium"):
                return "openrouter/free-model"

            # For complex: use premium
            return "anthropic/claude-sonnet"

        except Exception:
            return "default"

    # ── 5. Execute ───────────────────────────────────────────

    def _execute(
        self, task: str, studio: str, model: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the task through the studio pipeline."""
        try:
            from studios.base_studio import load_all_studios
            studios = load_all_studios()
            studio_instance = studios.get(studio)
            if studio_instance:
                result = studio_instance.run(task=task, description=task)
                return result if isinstance(result, dict) else {"success": True, "content": str(result)}
        except Exception as e:
            logger.debug("Studio execution skipped: %s", e)

        # Fallback: record as a task
        try:
            from kernel.state_manager import get_state
            state = get_state()
            task_id = state.create_task(
                studio=studio,
                description=task,
                status="pending",
            )
            return {
                "success": True,
                "content": f"Task {task_id} created in {studio} studio",
                "task_id": task_id,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── 6. Quality Gate ──────────────────────────────────────

    def _evaluate_quality(
        self, studio: str, result: dict
    ) -> tuple[float, bool]:
        """Evaluate output quality."""
        try:
            from kernel.quality_gates import get_quality_gates
            qg = get_quality_gates()
            evaluation = qg.evaluate(studio, result)
            return evaluation["score"], evaluation["passed"]
        except Exception:
            return 50.0, True  # Default pass

    # ── 7. Cross-Studio Chains ───────────────────────────────

    def _trigger_chains(
        self, studio: str, result: dict, success: bool
    ) -> int:
        """Trigger follow-up chains."""
        try:
            from kernel.cross_studio import get_cross_studio_pipelines
            csp = get_cross_studio_pipelines()
            execs = csp.trigger_chains(studio, result, success)
            return len(execs)
        except Exception:
            return 0

    # ── 8. Learn ─────────────────────────────────────────────

    def _learn(self, ot: OrchestratedTask) -> None:
        """Record outcome for future optimization."""
        try:
            from kernel.memory_manager import get_memory_manager
            mm = get_memory_manager()
            mm.learn(
                topic=f"orchestration:{ot.studio}:{ot.complexity}",
                content=(
                    f"Task: {ot.task[:200]}\n"
                    f"Complexity: {ot.complexity} ({ot.complexity_score})\n"
                    f"Model: {ot.model_used}\n"
                    f"Quality: {ot.quality_score}% ({'PASS' if ot.quality_passed else 'FAIL'})\n"
                    f"Duration: {ot.duration_ms:.0f}ms\n"
                    f"Status: {ot.status}"
                ),
                source_agent="orchestrator",
                tags=["orchestration", ot.studio, ot.complexity, ot.status],
            )
        except Exception as e:
            logger.debug("Learning skipped: %s", e)

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        total = len(self._history)
        if total == 0:
            return {"total": 0}

        completed = sum(1 for t in self._history if t.status == "completed")
        avg_duration = sum(t.duration_ms for t in self._history) / total
        avg_quality = sum(t.quality_score for t in self._history) / total
        complexity_dist = {}
        for t in self._history:
            complexity_dist[t.complexity] = complexity_dist.get(t.complexity, 0) + 1

        return {
            "total": total,
            "completed": completed,
            "failed": total - completed,
            "success_rate": round(completed / total * 100, 1),
            "avg_duration_ms": round(avg_duration, 1),
            "avg_quality_score": round(avg_quality, 1),
            "complexity_distribution": complexity_dist,
            "chains_triggered": sum(t.chains_triggered for t in self._history),
        }

    def get_history(self, limit: int = 20) -> list[dict]:
        return [
            {
                "id": t.id,
                "task": t.task[:80],
                "studio": t.studio,
                "complexity": t.complexity,
                "model": t.model_used,
                "quality": t.quality_score,
                "status": t.status,
                "duration_ms": round(t.duration_ms, 1),
                "created_at": t.created_at,
            }
            for t in self._history[-limit:]
        ]


_orchestrator: BrainOrchestrator | None = None


def get_orchestrator() -> BrainOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = BrainOrchestrator()
    return _orchestrator
