# Agency OS — Client Guide

## What Is Agency OS?

Agency OS is an AI agency that **DOES the work** — not just advises.

Ask it to build a website → it creates the files, runs the build, pushes to GitHub.
Ask it for a marketing campaign → it researches, writes copy, creates deliverables.
Ask it to find leads → it scrapes, enriches, and qualifies contacts.

---

## What Can I Ask For?

### 🖥️ Dev Studio
- "Build a landing page for my SaaS product"
- "Create a REST API for user management"
- "Fix the bug in the checkout flow"
- "Set up a Next.js app with authentication"

**What happens:** Creates real files, installs dependencies, pushes to GitHub.

### 📢 Marketing Studio
- "Create a Q3 marketing campaign for B2B SaaS"
- "Write 5 blog posts about AI automation"
- "Analyze SEO for competitor.com"

**What happens:** Research, strategy doc, content pieces, SEO report.

### 💰 Sales Studio
- "Write a cold outreach sequence for CFOs"
- "Create a sales proposal for [company]"
- "Analyze our sales pipeline and suggest improvements"

**What happens:** Personalized outreach templates, proposals, pipeline analysis.

### 🎯 Lead Ops Studio
- "Find 50 SaaS companies in fintech with <100 employees"
- "Enrich this lead list with emails and LinkedIn profiles"
- "Score and qualify these leads"

**What happens:** Lead scraping, enrichment, qualification scoring.

### 📊 Analytics Studio
- "Analyze our Q3 user retention data"
- "Create a KPI dashboard report"
- "Compare our metrics to industry benchmarks"

**What happens:** Data analysis, reports with metrics, trend insights.

### 🎨 Creative Studio
- "Create brand guidelines for a modern fintech startup"
- "Write a creative brief for a product launch video"

**What happens:** Brand documents, creative direction, content strategy.

### 🏢 ABM Studio
- "Create a personalized outreach plan for [target company]"
- "Research key stakeholders at [enterprise account]"

**What happens:** Account research, personalized multi-channel plan.

---

## How to Submit Tasks

### Option 1: CLI
```bash
agency dev "Build a landing page for my startup"
agency marketing "Create a Q3 content calendar"
agency sales "Write outreach emails for our new product"
```

### Option 2: API
```bash
curl -X POST http://localhost:8000/api/task \
  -d '{"task": "Build a website", "studio": "dev"}'
```

### Option 3: Through OpenClaw
Just tell your AI assistant what you need — OpenClaw routes it to Agency OS automatically.

---

## What Happens After Submitting?

1. **Task analyzed** — complexity scored, right studio selected
2. **AI debates approach** — considers architecture, best practices
3. **Execution** — creates real files, runs commands
4. **Quality check** — validates output meets standards
5. **Delivery** — files created, reports generated, git pushed (if requested)

---

## Execution Modes

| Mode | What It Does |
|------|-------------|
| **Autonomous** (default) | Does everything: creates files, runs commands, pushes to git |
| **Supervised** | Shows plan first, waits for your approval before executing |
| **Advisory** | Just tells you what to do, you execute manually |
