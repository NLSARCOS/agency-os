# Agency OS ↔ OpenClaw Integration Guide

## How It Works

```
Client → OpenClaw Gateway → Agency OS → Studios → Real Output
                                ↕
                         AI Providers
                    (Ollama, Cloud, OpenClaw)
```

OpenClaw is the **gateway**. Agency OS is the **brain + hands**.

---

## 1. Discovery: How OpenClaw Finds Agency OS

Agency OS exposes a `MANIFEST.yaml` at the project root. OpenClaw reads this to discover:

- **Studios**: What services are available (dev, marketing, sales, etc.)
- **Tools**: What each studio can do (create files, run commands, git push)
- **Providers**: Which AI backends are available
- **API endpoints**: How to send tasks

```bash
# Read the manifest
cat /path/to/agency-os/MANIFEST.yaml
```

---

## 2. Sending Tasks to Agency OS

### Via API (recommended)

```bash
# Submit a task
curl -X POST http://localhost:8000/api/task \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Build a landing page for a SaaS product",
    "studio": "dev",
    "auto_git": true,
    "project_dir": "/path/to/output"
  }'

# Response
{
  "task_id": "a1b2c3",
  "status": "running",
  "studio": "dev"
}
```

### Via CLI

```bash
cd /path/to/agency-os
source .venv/bin/activate
python -m kernel.cli dev "Build a landing page for a SaaS product"
```

### Via Python

```python
from kernel.orchestrator import get_orchestrator

orch = get_orchestrator()
result = orch.orchestrate(
    task="Build a landing page for a SaaS product",
    studio="dev",
    context={"project_dir": "/path/to/output", "auto_git": True},
)
```

---

## 3. What Happens Inside

When a task is submitted:

```
1. ORCHESTRATE → Score complexity (simple/medium/complex)
2. RESOLVE → Pick the right studio (dev, marketing, sales...)
3. CREW → Assemble specialist agents
4. ROUTE → Pick model (local Ollama for simple, cloud for complex)
5. EXECUTE → Studio pipeline:
   a. intake() → Parse and classify task
   b. plan() → Create execution steps
   c. execute() → AI generates code → ActionExecutor creates REAL files
   d. review() → Quality gate
   e. deliver() → Package deliverables
6. QUALITY → Evaluate output
7. CHAIN → Trigger follow-up studios (e.g., dev → marketing → analytics)
8. LEARN → Persist outcome to improve next time
```

---

## 4. The Execution Model

Agency OS has 3 execution modes:

| Mode | Behavior | Use When |
|------|----------|----------|
| **autonomous** | AI debates, creates files, runs commands, pushes to git | Production tasks |
| **supervised** | AI generates plan, waits for human approval | Critical changes |
| **advisory** | AI suggests, human executes | Learning/review |

Default is **autonomous**: the agency DOES the work.

---

## 5. OpenClaw ↔ Agency OS Communication

### Agency OS calls OpenClaw FOR AI:
```python
# All studios use this path for AI calls:
studio.ai_call(prompt)
  → OpenClawBridge.chat(messages)  # Try OpenClaw first
  → ModelRouter.call_model_sync()  # Fallback to direct APIs
```

### OpenClaw calls Agency OS FOR execution:
```python
# Via the API server:
POST /api/task → orchestrator.orchestrate() → studio.run() → real output
```

---

## 6. Provider Priority

```
1. OpenClaw (localhost:3000) — if running, routes through gateway
2. Ollama (localhost:11434) — local models for simple tasks (free)
3. LM Studio (localhost:1234) — local models alternative
4. OpenRouter — cloud multi-model API
5. Anthropic/OpenAI/Google — direct cloud calls
```

Auto-detected by `kernel/provider_detector.py` on startup.

---

## 7. Health Check

```bash
curl http://localhost:8000/api/health
```

Returns status of all 7 components: database, providers, memory, disk, modules, jobs, guardrails.
