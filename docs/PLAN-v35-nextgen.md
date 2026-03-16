# Agency OS v3.5 — Implementation Plan

> Upgrade from powerful CLI tool → **production-grade enterprise AI agency platform**

## Proposed Changes

### Phase 6: Guardrails + Audit Trail 🛡️

#### [NEW] `kernel/guardrails.py`
- **Cost limiter**: max tokens/day per studio, per agent, global
- **Content filter**: block PII in outputs, profanity filter, prompt injection detection
- **Rate limiter**: max concurrent calls per agent, request throttling
- **Budget tracker**: real-time spend per studio/model with alerts at 80%, 100%

#### [NEW] `kernel/audit_trail.py`
- Every AI call logged: model, agent_id, tokens_in, tokens_out, estimated_cost, latency_ms, success
- Exportable to JSON/CSV for compliance
- Dashboard-queryable via CLI: `agency-os audit summary`, `agency-os audit costs`
- Retention policy (auto-cleanup after N days)

#### [MODIFY] `studios/base_studio.py`
- Wrap `ai_call()` with guardrail checks (pre-call budget, post-call audit)

#### [MODIFY] `kernel/cli.py`
- Add `audit` command group: `summary`, `costs`, `export`, `clear`
- Add `guardrail` command group: `status`, `set-budget`, `set-limit`

---

### Phase 7: Observability + Streaming 📊

#### [NEW] `kernel/telemetry.py`
- Pipeline timeline: start → intake → plan → execute → review → deliver with timestamps
- Step-level tracing with correlation IDs
- Token usage per step/pipeline/studio aggregation
- Error classification: `model_error`, `timeout`, `rate_limit`, `content_filter`, `unknown`
- Export: JSON log, console pretty-print

#### [NEW] `kernel/streaming.py`
- SSE generator for streaming AI responses
- Progress callbacks for pipeline steps
- Console streaming mode: `agency-os mission run --stream`

#### [MODIFY] `studios/base_studio.py`
- Emit telemetry events at each lifecycle phase
- Support streaming AI calls when `--stream` flag

---

### Phase 8: API Server + Dashboard 🌐

#### [NEW] `kernel/api_server.py`
- FastAPI server with routes:
  - `POST /api/mission` — Create and run mission
  - `GET /api/status` — System status
  - `GET /api/studios` — List studios
  - `POST /api/studio/{name}/run` — Run studio pipeline
  - `GET /api/workflows` — List workflows
  - `POST /api/workflow/{id}/run` — Execute workflow
  - `GET /api/auto/discover` — Autonomy discovery
  - `GET /api/audit/summary` — Audit summary
  - `WS /api/stream` — WebSocket for live output
- JWT auth with configurable API keys
- CORS for dashboard

#### [NEW] `dashboard/index.html`
- Single-page real-time dashboard (vanilla JS + CSS)
- Sections: system status, active pipelines, studio KPIs, recent missions, audit summary
- Auto-refresh every 5s via API polling
- Dark mode, responsive

#### [MODIFY] `kernel/cli.py`
- Add `serve` command: `agency-os serve --port 8080`

---

### Phase 9: Intelligent Crew Assembly 🤖

#### [NEW] `kernel/crew_engine.py`
- Given a task description, auto-select the best agents for a crew
- Agent capability matrix: scored by domain (dev, marketing, sales, analysis)
- Cross-studio crews: e.g., launch campaign = marketing + creative + analytics
- Crew history: track which combinations succeed/fail
- Learning feedback: successful crews get priority score boost

#### [MODIFY] `kernel/agent_manager.py`
- Add capability scoring and crew history tracking

#### [MODIFY] `kernel/mission_engine.py`
- Support crew-based mission execution (auto-assemble then execute)

---

### Phase 10: Plugin System 🔌

#### [NEW] `kernel/plugin_loader.py`
- Scan `plugins/` directory for `plugin.yaml` manifests
- Dynamic registration: studios, tools, channels
- Hot-reload on file change
- Sandboxed execution (separate namespace)

#### [NEW] `plugins/README.md`
- Plugin development guide
- Manifest format specification
- Example plugin structure

#### [NEW] `plugins/example-hubspot/`
- Sample plugin: HubSpot CRM integration
- Demonstrates tool registration, studio extension

---

## Verification Plan

### Automated Tests
```bash
# Phase 6
python -c "from kernel.guardrails import get_guardrails; g = get_guardrails(); print(g.check_budget('dev'))"
python -c "from kernel.audit_trail import get_audit; a = get_audit(); print(a.get_summary())"
agency-os audit summary
agency-os guardrail status

# Phase 7
agency-os mission run dev "test" --stream
python -c "from kernel.telemetry import get_telemetry; t = get_telemetry(); print(t.get_timeline())"

# Phase 8
agency-os serve --port 8080 &
curl http://localhost:8080/api/status
curl http://localhost:8080/api/studios

# Phase 9
python -c "from kernel.crew_engine import get_crew_engine; c = get_crew_engine(); print(c.assemble('launch marketing campaign'))"

# Phase 10
python -c "from kernel.plugin_loader import get_plugins; p = get_plugins(); print(p.list_plugins())"
```

### Commit Strategy
One commit per phase, pushed immediately:
- `feat: Phase 6 — Guardrails + Audit Trail`
- `feat: Phase 7 — Observability + Streaming`
- `feat: Phase 8 — API Server + Dashboard`
- `feat: Phase 9 — Intelligent Crew Assembly`
- `feat: Phase 10 — Plugin System`
