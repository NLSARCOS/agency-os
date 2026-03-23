#!/usr/bin/env python3
"""
Agency OS v3.5 — API Server

REST API + WebSocket for external integrations:
- GET  /api/status          — System status
- GET  /api/studios         — List studios
- POST /api/studio/{name}   — Run studio pipeline
- GET  /api/workflows       — List workflows
- GET  /api/audit/summary   — Audit summary
- GET  /api/audit/costs     — Cost breakdown
- GET  /api/guardrails      — Guardrail status
- POST /api/auto/discover   — Autonomy discovery
- POST /api/channel/webhook — Multi-channel webhook
- GET  /                    — Web dashboard (HTML)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("agency.api")

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def create_app() -> Any:
    """Create the FastAPI application."""
    if not HAS_FASTAPI:
        raise ImportError(
            "FastAPI not installed. Run: pip install fastapi uvicorn"
        )

    app = FastAPI(
        title="Agency OS",
        version="3.5.0",
        description="AI Agency Operating System — REST API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ────────────────────────────────────────────

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "3.5.0"}

    # ── System Status ─────────────────────────────────────

    @app.get("/api/status")
    async def status():
        from studios.base_studio import load_all_studios
        from kernel.workflow_engine import get_workflow_engine
        from kernel.memory_manager import get_memory_manager
        from kernel.state_manager import get_state

        studios = load_all_studios()
        we = get_workflow_engine()
        mm = get_memory_manager()
        state = get_state()
        stats = state.get_dashboard_stats()
        mem = mm.get_stats()

        oc_status = "unknown"
        try:
            from kernel.openclaw_bridge import get_openclaw
            oc = get_openclaw()
            oc_status = "connected" if oc.is_available() else "offline"
        except Exception:
            oc_status = "error"

        return {
            "version": "3.5.0",
            "studios": len(studios),
            "studio_names": sorted(studios.keys()),
            "workflows": len(we.list_workflows()),
            "memories": mem["total_memories"],
            "knowledge": mem["total_knowledge"],
            "missions": stats.get("missions", {}),
            "openclaw": oc_status,
        }

    # ── Studios ───────────────────────────────────────────

    @app.get("/api/studios")
    async def list_studios():
        from studios.base_studio import load_all_studios
        studios = load_all_studios()
        return {
            "count": len(studios),
            "studios": [
                {"name": name, "agent": s.agent_ref}
                for name, s in studios.items()
            ],
        }

    @app.post("/api/studio/{name}")
    async def run_studio(name: str, request: Request):
        from studios.base_studio import load_all_studios
        studios = load_all_studios()
        studio = studios.get(name)
        if not studio:
            raise HTTPException(404, f"Studio '{name}' not found")

        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        task = body.get("task", f"Run {name} pipeline")

        try:
            result = studio.run(task=task)
            return {"studio": name, "result": result}
        except Exception as e:
            raise HTTPException(500, str(e))

    # ── Workflows ─────────────────────────────────────────

    @app.get("/api/workflows")
    async def list_workflows():
        from kernel.workflow_engine import get_workflow_engine
        we = get_workflow_engine()
        wfs = we.list_workflows()
        return {"count": len(wfs), "workflows": wfs}

    # ── Audit ─────────────────────────────────────────────

    @app.get("/api/audit/summary")
    async def audit_summary(days: int = 1):
        from kernel.audit_trail import get_audit
        return get_audit().get_summary(days)

    @app.get("/api/audit/costs")
    async def audit_costs(days: int = 1, by: str = "studio"):
        from kernel.audit_trail import get_audit
        a = get_audit()
        if by == "model":
            return {"by": "model", "data": a.get_costs_by_model(days)}
        return {"by": "studio", "data": a.get_costs_by_studio(days)}

    @app.get("/api/audit/recent")
    async def audit_recent(limit: int = 20):
        from kernel.audit_trail import get_audit
        return {"entries": get_audit().get_recent(limit)}

    # ── Guardrails ────────────────────────────────────────

    @app.get("/api/guardrails")
    async def guardrails_status():
        from kernel.guardrails import get_guardrails
        return get_guardrails().get_status()

    # ── Autonomy ──────────────────────────────────────────

    @app.post("/api/auto/discover")
    async def auto_discover():
        from kernel.autonomy_engine import get_autonomy_engine
        ae = get_autonomy_engine()
        tasks = ae.discover_tasks()
        return {
            "count": len(tasks),
            "tasks": [
                {
                    "source": t.source, "studio": t.studio,
                    "priority": t.priority, "task": t.task,
                    "reason": t.reason,
                }
                for t in tasks
            ],
        }

    # ── Orchestrate (Inbound from OpenClaw) ───────────────

    @app.post("/api/orchestrate")
    async def orchestrate(request: Request):
        """
        Accept a task from OpenClaw or any client.

        POST /api/orchestrate
        {
            "prompt": "Build a landing page for a dental clinic",
            "priority": 5
        }

        Returns immediately with mission IDs.
        Missions execute asynchronously in the heartbeat.
        Results are reported back via OpenClaw callback.
        """
        body = await request.json()
        prompt = body.get("prompt", "")
        priority = body.get("priority", 5)

        if not prompt:
            raise HTTPException(400, "prompt is required")

        try:
            from kernel.mission_planner import MissionPlanner

            planner = MissionPlanner()

            # Plan and enqueue all sub-missions
            result = await planner.plan_and_execute(prompt)

            logger.info(
                "API orchestrate: %d missions created for '%s'",
                result.get("sub_missions", 0), prompt[:60],
            )

            return {
                "status": "queued",
                "objective": result.get("objective", prompt[:200]),
                "missions": result.get("plan", []),
                "mission_ids": result.get("mission_ids", []),
                "total": result.get("sub_missions", 0),
                "studios": result.get("studios", []),
                "waves": result.get("waves", 1),
                "message": "Missions queued. Results will be reported via OpenClaw callback.",
            }

        except Exception as e:
            logger.error("Orchestrate failed: %s", e)
            raise HTTPException(500, f"Orchestration failed: {e}")

    @app.get("/api/mission/{mission_id}/status")
    async def mission_status(mission_id: int):
        """Check the status of a specific mission."""
        from kernel.state_manager import get_state
        state = get_state()
        m = state.get_mission(mission_id)
        if not m:
            raise HTTPException(404, f"Mission #{mission_id} not found")

        # Check for artifacts
        from pathlib import Path
        cfg = get_config()
        artifact_dir = cfg.root / "data" / "outputs" / f"mission_{mission_id}"
        artifacts = []
        if artifact_dir.exists():
            artifacts = [f.name for f in artifact_dir.iterdir()]

        return {
            "id": m["id"],
            "name": m["name"],
            "studio": m["studio"],
            "status": m["status"],
            "result": m.get("result", "")[:500],
            "artifacts": artifacts,
            "created_at": m.get("created_at", ""),
            "completed_at": m.get("completed_at", ""),
        }

    # ── Mission Feedback (Quality Gate) ───────────────────

    @app.post("/api/mission/{mission_id}/feedback")
    async def mission_feedback(mission_id: int, request: Request):
        """
        OpenClaw reviews a deliverable and sends it back for refinement.

        POST /api/mission/{id}/feedback
        {
            "action": "revise",        // "revise" or "approve"
            "feedback": "Missing CSS responsive design, add mobile breakpoints",
            "priority": 7              // optional, higher = more urgent
        }

        If action is "revise":
        - Creates a REVISION mission in the same studio
        - Carries original output + feedback as context
        - Executes automatically in next heartbeat tick
        - Returns new mission ID for tracking

        If action is "approve":
        - Marks mission as approved (no further action)
        """
        from kernel.state_manager import get_state
        from kernel.mission_engine import MissionEngine

        state = get_state()
        body = await request.json()

        action = body.get("action", "revise")
        feedback = body.get("feedback", "")
        priority = body.get("priority", 7)

        # Get original mission
        original = state.get_mission(mission_id)
        if not original:
            raise HTTPException(404, f"Mission #{mission_id} not found")

        if action == "approve":
            # Mark as approved — no further action
            logger.info("Mission #%d approved by reviewer", mission_id)
            return {
                "status": "approved",
                "mission_id": mission_id,
                "message": "Mission approved, no revision needed.",
            }

        if action != "revise":
            raise HTTPException(400, f"Unknown action: {action}")

        if not feedback:
            raise HTTPException(400, "feedback is required for revise action")

        # Create revision mission with original output as context
        original_result = original.get("result", "")[:3000]
        original_name = original.get("name", "Unknown")
        studio = original.get("studio", "dev")

        revision_description = (
            f"REVISION of Mission #{mission_id}: {original_name}\n\n"
            f"── ORIGINAL OUTPUT ──\n{original_result}\n\n"
            f"── REVIEWER FEEDBACK ──\n{feedback}\n\n"
            f"── INSTRUCTIONS ──\n"
            f"Fix the issues described in the reviewer feedback above. "
            f"Deliver a COMPLETE, REFINED version. Do NOT start from scratch — "
            f"improve the original output based on the feedback."
        )

        # Check for original artifacts to include as context
        artifact_dir = get_config().root / "data" / "outputs" / f"mission_{mission_id}"
        artifact_context = ""
        if artifact_dir.exists():
            for f in artifact_dir.iterdir():
                if f.is_file() and f.stat().st_size < 10000:
                    try:
                        content = f.read_text()
                        artifact_context += f"\n── FILE: {f.name} ──\n{content}\n"
                    except Exception:
                        pass

        if artifact_context:
            revision_description += f"\n── ORIGINAL FILES ──{artifact_context}"

        revision_id = state.create_mission(
            name=f"[REVISION] {original_name}",
            description=revision_description,
            studio=studio,
            priority=priority,
            metadata=json.dumps({
                "type": "revision",
                "original_mission_id": mission_id,
                "feedback": feedback[:500],
                "source": "openclaw_review",
            }),
        )

        logger.info(
            "Revision mission #%d created for original #%d (studio: %s)",
            revision_id, mission_id, studio,
        )

        return {
            "status": "revision_queued",
            "original_mission_id": mission_id,
            "revision_mission_id": revision_id,
            "studio": studio,
            "message": (
                f"Revision queued as mission #{revision_id}. "
                f"Will execute automatically. Results reported via callback."
            ),
        }

    @app.post("/api/mission/{mission_id}/cancel")
    async def cancel_mission(mission_id: int):
        """Cancel a queued or running mission."""
        from kernel.state_manager import get_state
        state = get_state()
        m = state.get_mission(mission_id)
        if not m:
            raise HTTPException(404, f"Mission #{mission_id} not found")
        
        if m["status"] in ("done", "failed"):
            return {"status": "error", "message": f"Mission already finished ({m['status']})"}

        try:
            with state._lock:
                state._conn.execute(
                    "UPDATE missions SET status = 'failed', result = ? WHERE id = ?",
                    ("Cancelled by PM/User request.", mission_id)
                )
                state._conn.commit()
            
            logger.info("PM manually cancelled mission #%d", mission_id)
            return {"status": "cancelled", "mission_id": mission_id}
        except Exception as e:
            raise HTTPException(500, f"Failed to cancel: {e}")

    @app.get("/api/missions/recent")
    async def recent_missions(limit: int = 5):
        """List recently completed or failed missions."""
        from kernel.state_manager import get_state
        state = get_state()
        try:
            with state._lock:
                rows = state._conn.execute(
                    """SELECT id, name, studio, status, priority, created_at, completed_at
                       FROM missions
                       WHERE status IN ('done', 'failed')
                       ORDER BY completed_at DESC, id DESC
                       LIMIT ?""", (limit,)
                ).fetchall()
            return {
                "count": len(rows),
                "missions": [dict(r) for r in rows]
            }
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/missions/active")
    async def active_missions():
        """List all active (queued/running) missions."""
        from kernel.state_manager import get_state
        state = get_state()
        try:
            with state._lock:
                rows = state._conn.execute(
                    """SELECT id, name, studio, status, priority, created_at
                       FROM missions
                       WHERE status IN ('queued', 'running')
                       ORDER BY priority DESC, created_at ASC"""
                ).fetchall()
            return {
                "count": len(rows),
                "missions": [dict(r) for r in rows],
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to list active missions: {e}")

    # ── Channel Webhook ───────────────────────────────────

    @app.post("/api/channel/webhook")
    async def channel_webhook(request: Request):
        from kernel.channel_connector import get_channel_connector, ChannelType
        body = await request.json()
        channel = body.get("channel", "api")
        try:
            ch_type = ChannelType(channel)
        except ValueError:
            ch_type = ChannelType.API
        cc = get_channel_connector()
        return cc.handle_webhook(body, ch_type)

    # ── Dashboard ─────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"
        if dashboard_path.exists():
            return HTMLResponse(dashboard_path.read_text())
        return HTMLResponse(_EMBEDDED_DASHBOARD)

    # ── API Key Authentication Middleware ─────────────────

    API_KEY = os.environ.get("AGENCY_API_KEY", "")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """Validate API key for non-public endpoints."""
        # Public endpoints (no auth needed)
        public = {"/api/health", "/", "/docs", "/openapi.json", "/favicon.ico"}
        if request.url.path in public or not API_KEY:
            return await call_next(request)

        # Check API key
        key = request.headers.get("X-API-Key", "")
        if not key:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                key = auth[7:]

        if key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing API key"},
            )

        return await call_next(request)

    # ── Dynamic Scheduled Tasks ──────────────────────────

    @app.post("/api/schedule")
    async def create_scheduled_task(request: Request):
        """
        Create a dynamic scheduled task.

        POST /api/schedule
        {
            "name": "find_leads_weekly",
            "prompt": "Busca nuevos leads en LinkedIn para servicios de desarrollo",
            "interval_minutes": 10080,  // 1 week
            "studio": "leadops",         // optional
            "priority": 5               // optional
        }
        """
        from kernel.state_manager import get_state
        state = get_state()
        body = await request.json()

        name = body.get("name", "")
        prompt = body.get("prompt", "")
        interval = body.get("interval_minutes", 60)

        if not name or not prompt:
            raise HTTPException(400, "name and prompt are required")

        # Store in SQLite
        try:
            state._conn.execute(
                """INSERT OR REPLACE INTO scheduled_tasks
                   (name, prompt, interval_minutes, studio, priority, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, datetime('now'))""",
                (
                    name,
                    prompt,
                    interval,
                    body.get("studio", ""),
                    body.get("priority", 5),
                ),
            )
            state._conn.commit()

            logger.info("Scheduled task created: %s (every %d min)", name, interval)
            return {
                "status": "created",
                "name": name,
                "interval_minutes": interval,
                "message": f"Task '{name}' scheduled every {interval} minutes.",
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to create scheduled task: {e}")

    @app.get("/api/schedule")
    async def list_scheduled_tasks():
        """List all scheduled tasks (static + dynamic)."""
        from kernel.state_manager import get_state
        state = get_state()
        tasks = []

        # Dynamic tasks from SQLite
        try:
            rows = state._conn.execute(
                """SELECT name, prompt, interval_minutes, studio, priority,
                          enabled, created_at
                   FROM scheduled_tasks ORDER BY created_at DESC"""
            ).fetchall()
            for r in rows:
                tasks.append({
                    "name": r["name"],
                    "prompt": r["prompt"],
                    "interval_minutes": r["interval_minutes"],
                    "studio": r["studio"],
                    "priority": r["priority"],
                    "enabled": bool(r["enabled"]),
                    "type": "dynamic",
                    "created_at": r["created_at"],
                })
        except Exception:
            pass  # Table may not exist yet

        # Static tasks from schedule.yaml
        from kernel.scheduler import DEFAULT_SCHEDULE
        for job in DEFAULT_SCHEDULE:
            tasks.append({
                "name": job["name"],
                "description": job.get("description", ""),
                "interval_minutes": job["interval_minutes"],
                "function": job["function"],
                "type": "static",
            })

        return {"count": len(tasks), "tasks": tasks}

    @app.delete("/api/schedule/{name}")
    async def delete_scheduled_task(name: str):
        """Delete a dynamic scheduled task."""
        from kernel.state_manager import get_state
        state = get_state()
        try:
            state._conn.execute(
                "DELETE FROM scheduled_tasks WHERE name = ?", (name,)
            )
            state._conn.commit()
            return {"status": "deleted", "name": name}
        except Exception as e:
            raise HTTPException(500, f"Failed to delete: {e}")

    @app.patch("/api/schedule/{name}")
    async def toggle_scheduled_task(name: str, request: Request):
        """Enable or disable a dynamic scheduled task."""
        from kernel.state_manager import get_state
        state = get_state()
        body = await request.json()
        enabled = 1 if body.get("enabled", True) else 0
        try:
            state._conn.execute(
                "UPDATE scheduled_tasks SET enabled = ? WHERE name = ?",
                (enabled, name),
            )
            state._conn.commit()
            return {
                "status": "updated",
                "name": name,
                "enabled": bool(enabled),
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to update: {e}")

    # ── Centralized Logs ─────────────────────────────────

    @app.get("/api/logs")
    async def get_logs(limit: int = 50, level: str = "", source: str = ""):
        """
        Get recent system logs/events.

        GET /api/logs?limit=50&level=error&source=mission_engine
        """
        from kernel.state_manager import get_state
        state = get_state()
        try:
            query = "SELECT * FROM events WHERE 1=1"
            params: list = []

            if level:
                query += " AND level = ?"
                params.append(level)
            if source:
                query += " AND source = ?"
                params.append(source)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(min(limit, 200))

            with state._lock:
                rows = state._conn.execute(query, params).fetchall()

            return {
                "count": len(rows),
                "logs": [dict(r) for r in rows],
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to fetch logs: {e}")

    @app.get("/api/logs/summary")
    async def logs_summary():
        """Get a summary of recent log activity."""
        from kernel.state_manager import get_state
        state = get_state()
        try:
            with state._lock:
                rows = state._conn.execute(
                    """SELECT level, COUNT(*) as count
                       FROM events
                       WHERE timestamp > datetime('now', '-24 hours')
                       GROUP BY level"""
                ).fetchall()
            summary = {r["level"]: r["count"] for r in rows}
            total = sum(summary.values())
            return {
                "last_24h": total,
                "by_level": summary,
            }
        except Exception as e:
            raise HTTPException(500, f"Failed to get log summary: {e}")

    # ── CRM (Clients) ────────────────────────────────────────

    @app.get("/api/clients")
    async def list_clients(stage: str = "", limit: int = 100):
        from kernel.state_manager import get_state
        state = get_state()
        clients = state.get_clients(pipeline_stage=stage or None, limit=limit)
        return {"count": len(clients), "clients": clients}

    @app.post("/api/clients")
    async def create_client(request: Request):
        from kernel.state_manager import get_state
        state = get_state()
        body = await request.json()
        name = body.get("name", "")
        if not name:
            raise HTTPException(400, "name is required")
        cid = state.create_client(
            name=name,
            company=body.get("company", ""),
            email=body.get("email", ""),
            phone=body.get("phone", ""),
            source=body.get("source", ""),
            notes=body.get("notes", ""),
            pipeline_stage=body.get("pipeline_stage", "lead"),
        )
        return {"status": "created", "id": cid}

    @app.patch("/api/clients/{client_id}")
    async def update_client(client_id: int, request: Request):
        from kernel.state_manager import get_state
        state = get_state()
        body = await request.json()
        state.update_client(client_id, **body)
        return {"status": "updated", "id": client_id}

    @app.get("/api/clients/{client_id}")
    async def get_client(client_id: int):
        from kernel.state_manager import get_state
        state = get_state()
        c = state.get_client(client_id)
        if not c:
            raise HTTPException(404, f"Client #{client_id} not found")
        return c

    # ── Financial ─────────────────────────────────────────

    @app.get("/api/financials/summary")
    async def financial_summary(days: int = 30):
        from kernel.state_manager import get_state
        return get_state().get_financial_summary(days)

    @app.post("/api/financials")
    async def log_financial(request: Request):
        from kernel.state_manager import get_state
        state = get_state()
        body = await request.json()
        fid = state.log_financial(
            record_type=body.get("type", "cost"),
            amount=body.get("amount", 0),
            description=body.get("description", ""),
            mission_id=body.get("mission_id"),
            client_id=body.get("client_id"),
            currency=body.get("currency", "USD"),
        )
        return {"status": "recorded", "id": fid}

    # ── Weekly Report ─────────────────────────────────────

    @app.get("/api/report/weekly")
    async def weekly_report():
        from kernel.state_manager import get_state
        return get_state().get_weekly_report_data()

    # ── Pipeline Summary ──────────────────────────────────

    @app.get("/api/pipeline")
    async def pipeline_summary():
        from kernel.state_manager import get_state
        state = get_state()
        try:
            stages = state._conn.execute(
                "SELECT pipeline_stage, COUNT(*) as cnt FROM clients GROUP BY pipeline_stage"
            ).fetchall()
            total_revenue = state._conn.execute(
                "SELECT SUM(total_revenue) as total FROM clients"
            ).fetchone()
            return {
                "stages": {r["pipeline_stage"]: r["cnt"] for r in stages},
                "total_clients": sum(r["cnt"] for r in stages),
                "total_revenue": total_revenue["total"] or 0 if total_revenue else 0,
            }
        except Exception as e:
            raise HTTPException(500, str(e))

    # ── Full Dashboard ────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"
        if dashboard_path.exists():
            return HTMLResponse(dashboard_path.read_text())
        return HTMLResponse(_EMBEDDED_DASHBOARD)

    return app


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the API server."""
    if not HAS_FASTAPI:
        print("❌ FastAPI not installed. Run: pip install fastapi uvicorn")
        return
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


# ── Full Embedded Dashboard ──────────────────────────────────
_EMBEDDED_DASHBOARD = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agency OS — Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0e1a; --surface: #111827; --card: #1a2332;
    --border: #2a3444; --text: #e2e8f0; --muted: #8892a4;
    --accent: #38bdf8; --green: #22c55e; --red: #ef4444;
    --orange: #f59e0b; --purple: #a78bfa; --pink: #f472b6;
    --radius: 12px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }

  .header {
    background: linear-gradient(135deg, rgba(56,189,248,.08), rgba(167,139,250,.08));
    backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center;
  }
  .header h1 { font-size: 1.3rem; font-weight: 700; }
  .header h1 span { color: var(--accent); }
  .header .meta { font-size: .75rem; color: var(--muted); display: flex; gap: 1rem; align-items: center; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot.on { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dot.off { background: var(--red); }

  .layout { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: .75rem; padding: 1rem 2rem; }
  .span2 { grid-column: span 2; }
  .span3 { grid-column: span 3; }
  .span4 { grid-column: span 4; }

  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 1rem; overflow: hidden;
  }
  .card h3 { font-size: .7rem; color: var(--muted); text-transform: uppercase;
             letter-spacing: .05em; margin-bottom: .6rem; font-weight: 600; }
  .big { font-size: 1.8rem; font-weight: 700; line-height: 1; }
  .sub { font-size: .75rem; color: var(--muted); margin-top: 4px; }

  table { width: 100%; border-collapse: collapse; font-size: .8rem; }
  th { color: var(--muted); font-size: .65rem; text-transform: uppercase; letter-spacing: .04em;
       padding: .4rem .5rem; text-align: left; border-bottom: 1px solid var(--border); }
  td { padding: .4rem .5rem; border-bottom: 1px solid rgba(42,52,68,.5); }
  tr:hover td { background: rgba(56,189,248,.03); }

  .badge { padding: 2px 8px; border-radius: 4px; font-size: .65rem; font-weight: 600; }
  .badge.green { background: rgba(34,197,94,.15); color: var(--green); }
  .badge.orange { background: rgba(245,158,11,.15); color: var(--orange); }
  .badge.red { background: rgba(239,68,68,.15); color: var(--red); }
  .badge.blue { background: rgba(56,189,248,.15); color: var(--accent); }
  .badge.purple { background: rgba(167,139,250,.15); color: var(--purple); }

  .pipeline { display: flex; gap: .5rem; }
  .pipe-stage {
    flex: 1; text-align: center; padding: .6rem; border-radius: 8px;
    background: rgba(56,189,248,.05); border: 1px solid var(--border);
  }
  .pipe-stage .count { font-size: 1.5rem; font-weight: 700; color: var(--accent); }
  .pipe-stage .label { font-size: .65rem; color: var(--muted); margin-top: 2px; }

  @media (max-width: 900px) { .layout { grid-template-columns: 1fr 1fr; }
    .span3, .span4 { grid-column: span 2; } }
  @media (max-width: 600px) { .layout { grid-template-columns: 1fr; }
    .span2, .span3, .span4 { grid-column: span 1; } }
</style>
</head>
<body>
<div class="header">
  <h1>🏢 Agency OS <span>Dashboard</span></h1>
  <div class="meta">
    <span id="oc-status"><span class="dot off"></span> OpenClaw</span>
    <span id="uptime">⏱ --</span>
    <span id="clock">--</span>
  </div>
</div>
<div class="layout" id="grid"></div>
<script>
const API = '';
async function j(url){return fetch(API+url).then(r=>r.json()).catch(()=>({}))}
function badge(text, color){return `<span class="badge ${color}">${text}</span>`}
function pipeStage(name, count){
  return `<div class="pipe-stage"><div class="count">${count||0}</div><div class="label">${name}</div></div>`;
}

async function refresh(){
  const [st, audit, pipe, fin, missions, logs, sched, auto] = await Promise.all([
    j('/api/status'), j('/api/audit/summary?days=1'), j('/api/pipeline'),
    j('/api/financials/summary?days=30'), j('/api/missions/active'),
    j('/api/logs?limit=15'), j('/api/schedule'), j('/api/auto/discover'),
  ]);

  const oc = st.openclaw === 'connected';
  document.getElementById('oc-status').innerHTML =
    `<span class="dot ${oc?'on':'off'}"></span> OpenClaw ${oc?'✓':'✗'}`;
  document.getElementById('clock').textContent = new Date().toLocaleTimeString();

  const m = st.missions || {};
  const totalM = Object.values(m).reduce((a,b)=>a+b, 0);
  const doneM = (m.done||0)+(m.completed||0);

  const grid = document.getElementById('grid');
  grid.innerHTML = `
    <!-- Row 1: KPIs -->
    <div class="card">
      <h3>📋 Misiones Totales</h3>
      <div class="big" style="color:var(--accent)">${totalM}</div>
      <div class="sub">${doneM} completadas · ${m.failed||0} fallidas · ${m.running||0} activas</div>
    </div>
    <div class="card">
      <h3>🏢 Studios Activos</h3>
      <div class="big" style="color:var(--green)">${st.studios||0}</div>
      <div class="sub">${(st.studio_names||[]).join(', ')}</div>
    </div>
    <div class="card">
      <h3>💰 Revenue (30d)</h3>
      <div class="big" style="color:var(--green)">$${(fin.revenue||0).toLocaleString()}</div>
      <div class="sub">Costos: $${(fin.costs||0).toLocaleString()} · Profit: $${(fin.profit||0).toLocaleString()}</div>
    </div>
    <div class="card">
      <h3>🤖 IA (24h)</h3>
      <div class="big" style="color:var(--purple)">${audit.total_calls||0}</div>
      <div class="sub">${(audit.total_tokens||0).toLocaleString()} tokens · $${(audit.total_cost_usd||0).toFixed(3)}</div>
    </div>

    <!-- Row 2: Pipeline -->
    <div class="card span4">
      <h3>🔄 Pipeline de Clientes (${pipe.total_clients||0} total · $${(pipe.total_revenue||0).toLocaleString()} revenue)</h3>
      <div class="pipeline">
        ${pipeStage('🎯 Leads', (pipe.stages||{}).lead)}
        ${pipeStage('🔍 Prospecto', (pipe.stages||{}).prospect)}
        ${pipeStage('✅ Activo', (pipe.stages||{}).active)}
        ${pipeStage('💰 Facturado', (pipe.stages||{}).invoiced)}
        ${pipeStage('📦 Entregado', (pipe.stages||{}).delivered)}
        ${pipeStage('❌ Churn', (pipe.stages||{}).churned)}
      </div>
    </div>

    <!-- Row 3: Active Missions + Autonomy + Scheduled -->
    <div class="card span2">
      <h3>🚀 Misiones Activas (${(missions.missions||[]).length})</h3>
      <table>
        <thead><tr><th>ID</th><th>Misión</th><th>Studio</th><th>Estado</th><th>Prio</th></tr></thead>
        <tbody>
          ${(missions.missions||[]).map(m=>`<tr>
            <td>#${m.id}</td><td>${(m.name||'').slice(0,40)}</td>
            <td>${badge(m.studio,'blue')}</td>
            <td>${badge(m.status, m.status==='running'?'green':'orange')}</td>
            <td>${m.priority}</td>
          </tr>`).join('')||'<tr><td colspan="5" style="color:var(--muted)">Sin misiones activas</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h3>🧠 Autonomía</h3>
      <div class="big" style="color:var(--orange)">${auto.count||0}</div>
      <div class="sub">tareas auto-descubiertas</div>
      ${(auto.tasks||[]).slice(0,3).map(t=>
        `<div style="margin-top:6px;font-size:.7rem;color:var(--muted)">↳ ${t.task?.slice(0,50)}</div>`
      ).join('')}
    </div>
    <div class="card">
      <h3>⏰ Tareas Programadas</h3>
      <div class="big" style="color:var(--accent)">${sched.count||0}</div>
      <div class="sub">tareas activas</div>
      ${(sched.tasks||[]).slice(0,3).map(t=>
        `<div style="margin-top:6px;font-size:.7rem;color:var(--muted)">↳ ${t.name} (${t.interval_minutes}min)</div>`
      ).join('')}
    </div>

    <!-- Row 4: Logs -->
    <div class="card span4">
      <h3>📝 Logs Recientes</h3>
      <table>
        <thead><tr><th>Hora</th><th>Nivel</th><th>Fuente</th><th>Mensaje</th></tr></thead>
        <tbody>
          ${(logs.logs||[]).map(l=>`<tr>
            <td style="white-space:nowrap;font-size:.7rem">${l.timestamp?.slice(11,19)||''}</td>
            <td>${badge(l.level, l.level==='error'?'red':l.level==='warning'?'orange':'green')}</td>
            <td style="font-size:.7rem">${l.source||''}</td>
            <td style="font-size:.75rem;max-width:500px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${(l.message||'').slice(0,80)}</td>
          </tr>`).join('')||'<tr><td colspan="4" style="color:var(--muted)">Sin logs recientes</td></tr>'}
        </tbody>
      </table>
    </div>
  `;
}
refresh();
setInterval(refresh, 8000);
</script>
</body>
</html>"""

