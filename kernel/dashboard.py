"""Agency OS — Web Dashboard (FastAPI + embedded UI)."""
import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from kernel.config import get_config
from kernel.state_manager import get_state

app = FastAPI(title="Agency OS Dashboard", version="5.0")


# ── API Endpoints ─────────────────────────────────────────

@app.get("/api/stats")
def api_stats():
    state = get_state()
    return JSONResponse(state.get_dashboard_stats())


@app.get("/api/events")
def api_events():
    state = get_state()
    events = state.get_events(limit=50)
    return JSONResponse(events)


@app.get("/api/missions")
def api_missions():
    state = get_state()
    missions = state.get_missions()
    return JSONResponse(missions)


@app.get("/api/heartbeat")
def api_heartbeat():
    cfg = get_config()
    pid_file = cfg.data_dir / "heartbeat.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 0)
            return {"status": "running", "pid": pid}
        except OSError:
            return {"status": "stale_pid", "pid": pid}
    return {"status": "stopped", "pid": None}


# ── Embedded HTML Dashboard ───────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agency OS — Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a2e;
    --border: #2a2a3e;
    --text: #e4e4ef;
    --text2: #9090a8;
    --accent: #6c5ce7;
    --green: #00e676;
    --yellow: #ffd740;
    --red: #ff5252;
    --blue: #448aff;
    --cyan: #18ffff;
  }
  body {
    font-family: 'Inter', -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 0;
  }
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 32px;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, #12121a 0%, #0a0a0f 100%);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .header h1 {
    font-size: 20px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .header h1 span { color: var(--accent); }
  .heartbeat-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 500;
    background: rgba(0, 230, 118, 0.1);
    border: 1px solid rgba(0, 230, 118, 0.3);
    color: var(--green);
  }
  .heartbeat-badge.stopped {
    background: rgba(255, 82, 82, 0.1);
    border-color: rgba(255, 82, 82, 0.3);
    color: var(--red);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }
  .dot.stopped { background: var(--red); animation: none; }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
    padding: 24px 32px;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    transition: border-color 0.2s;
  }
  .card:hover { border-color: var(--accent); }
  .card h3 {
    font-size: 13px;
    font-weight: 500;
    color: var(--text2);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 12px;
  }
  .stat-value {
    font-size: 36px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 4px;
  }
  .stat-label {
    font-size: 13px;
    color: var(--text2);
  }
  .section {
    padding: 0 32px 24px;
  }
  .section-title {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    background: var(--surface);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border);
  }
  th {
    text-align: left;
    padding: 12px 16px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text2);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background: var(--surface2);
    border-bottom: 1px solid var(--border);
  }
  td {
    padding: 10px 16px;
    font-size: 13px;
    border-bottom: 1px solid var(--border);
  }
  tr:last-child td { border-bottom: none; }
  tr:hover { background: rgba(108, 92, 231, 0.05); }
  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }
  .badge-active { background: rgba(0,230,118,.15); color: var(--green); }
  .badge-queued { background: rgba(255,215,64,.12); color: var(--yellow); }
  .badge-done { background: rgba(68,138,255,.12); color: var(--blue); }
  .badge-error { background: rgba(255,82,82,.12); color: var(--red); }
  .badge-info { background: rgba(108,92,231,.15); color: var(--accent); }
  .event-time {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 12px;
    color: var(--text2);
    white-space: nowrap;
  }
  .event-source {
    font-size: 12px;
    color: var(--cyan);
  }
  .refresh-note {
    text-align: center;
    padding: 16px;
    font-size: 12px;
    color: var(--text2);
  }
  .studio-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 10px;
  }
  .studio-chip {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    text-align: center;
    transition: all 0.2s;
  }
  .studio-chip:hover { border-color: var(--accent); transform: translateY(-2px); }
  .studio-chip .emoji { font-size: 24px; display: block; margin-bottom: 6px; }
  .studio-chip .name { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  .studio-chip .count { font-size: 11px; color: var(--text2); margin-top: 4px; }
</style>
</head>
<body>

<div class="header">
  <h1>🫀 <span>Agency OS</span> Dashboard</h1>
  <div class="heartbeat-badge" id="hb-badge">
    <div class="dot" id="hb-dot"></div>
    <span id="hb-text">Loading...</span>
  </div>
</div>

<div class="grid" id="stats-grid"></div>

<div class="section">
  <div class="section-title">🏢 Studios</div>
  <div class="studio-grid" id="studios-grid"></div>
</div>

<div class="section">
  <div class="section-title">📋 Missions</div>
  <table id="missions-table">
    <thead><tr><th>ID</th><th>Studio</th><th>Objective</th><th>Status</th><th>Created</th></tr></thead>
    <tbody id="missions-body"></tbody>
  </table>
</div>

<div class="section">
  <div class="section-title">📊 Recent Events</div>
  <table id="events-table">
    <thead><tr><th>Time</th><th>Type</th><th>Source</th><th>Message</th></tr></thead>
    <tbody id="events-body"></tbody>
  </table>
</div>

<div class="refresh-note">Auto-refresh every 10s • Agency OS v5.0</div>

<script>
const STUDIO_EMOJIS = {
  dev: '💻', marketing: '📣', sales: '💰', leadops: '🎯',
  abm: '🏢', analytics: '📈', creative: '🎨'
};
const ALL_STUDIOS = ['dev','marketing','sales','leadops','abm','analytics','creative'];

async function fetchJSON(url) {
  try { const r = await fetch(url); return await r.json(); }
  catch(e) { console.error(url, e); return null; }
}

function timeSince(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  const s = Math.floor((Date.now() - d) / 1000);
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago';
  return Math.floor(s/86400) + 'd ago';
}

function timeShort(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleTimeString('es', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

function badgeClass(status) {
  if (!status) return 'badge-info';
  const s = status.toLowerCase();
  if (['active','running','in_progress'].includes(s)) return 'badge-active';
  if (['queued','pending'].includes(s)) return 'badge-queued';
  if (['done','completed','success'].includes(s)) return 'badge-done';
  if (['error','failed'].includes(s)) return 'badge-error';
  return 'badge-info';
}

async function refresh() {
  // Heartbeat
  const hb = await fetchJSON('/api/heartbeat');
  if (hb) {
    const badge = document.getElementById('hb-badge');
    const dot = document.getElementById('hb-dot');
    const text = document.getElementById('hb-text');
    if (hb.status === 'running') {
      badge.className = 'heartbeat-badge';
      dot.className = 'dot';
      text.textContent = 'Running • PID ' + hb.pid;
    } else {
      badge.className = 'heartbeat-badge stopped';
      dot.className = 'dot stopped';
      text.textContent = hb.status === 'stale_pid' ? 'Stale PID' : 'Stopped';
    }
  }

  // Stats
  const stats = await fetchJSON('/api/stats');
  if (stats) {
    const grid = document.getElementById('stats-grid');
    const active = stats.missions?.active || 0;
    const queued = stats.missions?.queued || 0;
    const studioCount = Object.keys(stats.tasks_by_studio || {}).length;
    const kpis = stats.recent_kpis || [];
    const totalTokens = kpis
      .filter(k => k.metric_name === 'tokens_used')
      .reduce((s,k) => s + (k.metric_value || 0), 0);

    grid.innerHTML = `
      <div class="card"><h3>Active Missions</h3><div class="stat-value" style="color:var(--green)">${active}</div><div class="stat-label">${queued} in queue</div></div>
      <div class="card"><h3>Active Studios</h3><div class="stat-value" style="color:var(--accent)">${studioCount}</div><div class="stat-label">of 7 total</div></div>
      <div class="card"><h3>Tokens Used</h3><div class="stat-value" style="color:var(--cyan)">${totalTokens.toLocaleString()}</div><div class="stat-label">today</div></div>
      <div class="card"><h3>KPI Events</h3><div class="stat-value" style="color:var(--yellow)">${kpis.length}</div><div class="stat-label">recorded</div></div>
    `;

    // Studios
    const studioTasks = stats.tasks_by_studio || {};
    const sg = document.getElementById('studios-grid');
    sg.innerHTML = ALL_STUDIOS.map(s => {
      const count = studioTasks[s] || 0;
      return `<div class="studio-chip">
        <span class="emoji">${STUDIO_EMOJIS[s]||'📦'}</span>
        <div class="name">${s}</div>
        <div class="count">${count} task${count!==1?'s':''}</div>
      </div>`;
    }).join('');
  }

  // Missions
  const missions = await fetchJSON('/api/missions');
  if (missions && missions.length) {
    const mb = document.getElementById('missions-body');
    mb.innerHTML = missions.slice(0, 20).map(m => `
      <tr>
        <td style="font-family:monospace;color:var(--text2)">#${m.id || '?'}</td>
        <td>${STUDIO_EMOJIS[m.studio]||'📦'} ${m.studio || '—'}</td>
        <td>${(m.objective || m.description || '—').substring(0, 80)}</td>
        <td><span class="badge ${badgeClass(m.status)}">${m.status || '—'}</span></td>
        <td class="event-time">${timeSince(m.created_at)}</td>
      </tr>
    `).join('');
  }

  // Events
  const events = await fetchJSON('/api/events');
  if (events && events.length) {
    const eb = document.getElementById('events-body');
    eb.innerHTML = events.slice(0, 30).map(e => `
      <tr>
        <td class="event-time">${timeShort(e.created_at)}</td>
        <td><span class="badge ${badgeClass(e.level || e.event_type)}">${e.event_type || '—'}</span></td>
        <td class="event-source">${e.source || '—'}</td>
        <td>${(e.message || e.data || '—').substring(0, 120)}</td>
      </tr>
    `).join('');
  }
}

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


def start_dashboard(host: str = "0.0.0.0", port: int = 3000):
    """Launch the dashboard server."""
    uvicorn.run(app, host=host, port=port, log_level="info")
