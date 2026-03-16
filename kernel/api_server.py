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

    return app


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the API server."""
    if not HAS_FASTAPI:
        print("❌ FastAPI not installed. Run: pip install fastapi uvicorn")
        return
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


# ── Embedded minimal dashboard ───────────────────────────────
_EMBEDDED_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agency OS v3.5 — Dashboard</title>
<style>
  :root { --bg: #0f172a; --card: #1e293b; --border: #334155;
          --text: #e2e8f0; --muted: #94a3b8; --accent: #38bdf8;
          --green: #22c55e; --red: #ef4444; --orange: #f59e0b; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', -apple-system, sans-serif; background: var(--bg);
         color: var(--text); min-height: 100vh; }
  .header { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            padding: 1.5rem 2rem; border-bottom: 1px solid var(--border);
            display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 1.5rem; }
  .header h1 span { color: var(--accent); }
  .status-dot { width: 10px; height: 10px; border-radius: 50%;
                display: inline-block; margin-right: 6px; }
  .status-dot.ok { background: var(--green); box-shadow: 0 0 8px var(--green); }
  .status-dot.offline { background: var(--red); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
          gap: 1rem; padding: 1.5rem 2rem; }
  .card { background: var(--card); border: 1px solid var(--border);
          border-radius: 12px; padding: 1.25rem; }
  .card h3 { font-size: 0.85rem; color: var(--muted); text-transform: uppercase;
             letter-spacing: 0.05em; margin-bottom: 0.75rem; }
  .card .value { font-size: 2rem; font-weight: 700; }
  .card .value.accent { color: var(--accent); }
  .card .value.green { color: var(--green); }
  .card .value.orange { color: var(--orange); }
  .studio-list { list-style: none; }
  .studio-list li { padding: 0.5rem 0; border-bottom: 1px solid var(--border);
                    display: flex; justify-content: space-between; }
  .studio-list li:last-child { border: none; }
  .tag { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;
         background: rgba(56, 189, 248, 0.15); color: var(--accent); }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-size: 0.8rem; text-transform: uppercase; }
  .refresh { color: var(--muted); font-size: 0.8rem; }
  @media (max-width: 768px) { .grid { grid-template-columns: 1fr; padding: 1rem; } }
</style>
</head>
<body>
<div class="header">
  <h1>🏢 Agency OS <span>v3.5</span></h1>
  <span class="refresh" id="refresh">Loading...</span>
</div>
<div class="grid" id="cards"></div>
<div style="padding: 0 2rem 2rem;">
  <div class="card" id="audit-card">
    <h3>📋 Recent AI Calls</h3>
    <table id="audit-table">
      <thead><tr><th>Studio</th><th>Model</th><th>Tokens</th><th>Cost</th><th>Latency</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>
<script>
async function refresh() {
  try {
    const [status, audit, guardrails, autoTasks] = await Promise.all([
      fetch('/api/status').then(r => r.json()),
      fetch('/api/audit/summary?days=1').then(r => r.json()),
      fetch('/api/guardrails').then(r => r.json()),
      fetch('/api/auto/discover').then(r => r.json()).catch(() => ({count:0})),
    ]);
    const oc = status.openclaw === 'connected';
    document.getElementById('cards').innerHTML = `
      <div class="card">
        <h3>🐙 OpenClaw</h3>
        <div class="value ${oc ? 'green' : 'orange'}">
          <span class="status-dot ${oc ? 'ok' : 'offline'}"></span>
          ${oc ? 'Connected' : 'Offline'}
        </div>
      </div>
      <div class="card">
        <h3>🏢 Studios</h3>
        <div class="value accent">${status.studios}</div>
        <ul class="studio-list">${status.studio_names.map(s =>
          `<li>${s} <span class="tag">active</span></li>`).join('')}</ul>
      </div>
      <div class="card">
        <h3>📋 Workflows</h3>
        <div class="value accent">${status.workflows}</div>
      </div>
      <div class="card">
        <h3>🧠 Memory</h3>
        <div class="value">${status.memories} <small style="font-size:0.5em;color:var(--muted)">memories</small></div>
        <div style="color:var(--muted);margin-top:4px">${status.knowledge} knowledge items</div>
      </div>
      <div class="card">
        <h3>📊 AI Calls (24h)</h3>
        <div class="value accent">${audit.total_calls}</div>
        <div style="color:var(--muted);margin-top:4px">${audit.total_tokens?.toLocaleString() || 0} tokens · $${audit.total_cost_usd?.toFixed(4) || '0'}</div>
      </div>
      <div class="card">
        <h3>🛡️ Guardrails</h3>
        <div class="value green">${guardrails.budgets_configured} budgets</div>
        <div style="color:var(--muted);margin-top:4px">${guardrails.scopes_tracked} scopes tracked</div>
      </div>
      <div class="card">
        <h3>🤖 Auto-Tasks</h3>
        <div class="value orange">${autoTasks.count}</div>
        <div style="color:var(--muted);margin-top:4px">discovered by autonomy engine</div>
      </div>
      <div class="card">
        <h3>✅ Success Rate</h3>
        <div class="value green">${audit.success_rate || 100}%</div>
        <div style="color:var(--muted);margin-top:4px">avg ${Math.round(audit.avg_latency_ms || 0)}ms latency</div>
      </div>
    `;
    // Recent calls
    const recent = await fetch('/api/audit/recent?limit=10').then(r => r.json());
    const tbody = document.querySelector('#audit-table tbody');
    tbody.innerHTML = (recent.entries || []).map(e => `
      <tr>
        <td>${e.studio}</td><td>${e.model}</td>
        <td>${((e.tokens_in||0)+(e.tokens_out||0)).toLocaleString()}</td>
        <td>$${(e.estimated_cost||0).toFixed(4)}</td>
        <td>${Math.round(e.latency_ms||0)}ms</td>
      </tr>
    `).join('') || '<tr><td colspan="5" style="color:var(--muted)">No calls yet</td></tr>';
    document.getElementById('refresh').textContent = 'Updated: ' + new Date().toLocaleTimeString();
  } catch(e) { document.getElementById('refresh').textContent = 'Error: ' + e.message; }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""
