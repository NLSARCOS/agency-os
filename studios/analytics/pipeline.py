#!/usr/bin/env python3
"""
Analytics Studio — Reporting & Insights Pipeline

Uses: .agent/agents/explorer-agent.md
Skills: performance-profiling, systematic-debugging
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from studios.base_studio import BaseStudio


class Studio(BaseStudio):
    name = "analytics"
    description = "KPI reporting, dashboards, data analysis, insights"
    agent_ref = "explorer-agent"
    skills_refs = ["performance-profiling", "systematic-debugging"]

    def intake(self, task: str, description: str, **kwargs) -> dict[str, Any]:
        task_lower = task.lower()
        operation = "report"
        if any(w in task_lower for w in ["dashboard", "panel", "vista"]):
            operation = "dashboard"
        elif any(w in task_lower for w in ["kpi", "metric", "métrica"]):
            operation = "kpi_analysis"
        elif any(w in task_lower for w in ["trend", "tendencia", "forecast"]):
            operation = "trend_analysis"
        elif any(w in task_lower for w in ["alert", "alerta", "anomaly"]):
            operation = "alerting"
        elif any(w in task_lower for w in ["attribution", "roi", "retorno"]):
            operation = "attribution"

        return {"task": task, "description": description, "operation": operation}

    def plan(self, intake_result: dict[str, Any]) -> dict[str, Any]:
        op = intake_result["operation"]
        steps = {
            "report": [
                "Collect data from all studios (missions, KPIs, events)",
                "Aggregate metrics by period and studio",
                "Calculate growth rates and trends",
                "Generate formatted report",
                "Distribute to stakeholders",
            ],
            "dashboard": [
                "Define dashboard layout and sections",
                "Pull real-time metrics from state DB",
                "Design visualizations (tables, charts description)",
                "Set up refresh schedule",
            ],
            "kpi_analysis": [
                "Extract KPI history from database",
                "Calculate period-over-period changes",
                "Identify top/bottom performers",
                "Generate actionable insights",
                "Recommend optimization targets",
            ],
            "trend_analysis": [
                "Collect historical data points",
                "Calculate moving averages and trends",
                "Identify seasonality patterns",
                "Project future performance",
                "Flag risk areas",
            ],
            "alerting": [
                "Define threshold rules per metric",
                "Scan current KPIs against thresholds",
                "Generate alerts for breaches",
                "Prioritize by severity",
                "Recommend remediation actions",
            ],
            "attribution": [
                "Map conversion touchpoints",
                "Calculate channel contribution",
                "Compute ROI per channel/campaign",
                "Identify highest-impact activities",
                "Recommend budget reallocation",
            ],
        }
        return {**intake_result, "steps": steps.get(op, steps["report"])}

    def execute(
        self, plan: dict[str, Any], task_id: int | None = None
    ) -> dict[str, Any]:
        operation = plan["operation"]

        # For reports and KPI analysis, use real data from state DB
        if operation in ("report", "kpi_analysis"):
            return self._execute_data_report(plan, task_id)

        # For other operations, use AI
        prompt = (
            f"## Analytics Task — {operation.upper()}\n"
            f"**Task:** {plan['task']}\n\n"
            f"## Steps\n"
            + "\n".join(f"- {s}" for s in plan["steps"])
            + "\n\nProvide data-driven analysis and actionable insights."
        )

        output = self.ai_call(prompt, task_id=task_id)
        return {
            "output": output,
            "operation": operation,
            "kpis": [{"name": f"analytics_{operation}", "value": 1, "unit": "count"}],
        }

    def _execute_data_report(self, plan: dict, task_id: int | None) -> dict:
        """Generate report from real state data."""
        stats = self.state.get_dashboard_stats()
        kpis = self.state.get_kpis(limit=50)
        events = self.state.get_events(limit=20)

        report_lines = [
            "# 📊 Analytics Report",
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Mission Summary",
            json.dumps(stats.get("missions", {}), indent=2),
            "",
            "## Tasks by Studio",
            json.dumps(stats.get("tasks_by_studio", {}), indent=2),
            "",
            "## Model Usage",
            json.dumps(stats.get("model_usage", []), indent=2, default=str),
            "",
            f"## KPI History ({len(kpis)} records)",
        ]

        for k in kpis[:20]:
            report_lines.append(
                f"- [{k['studio']}] {k['metric_name']}: {k['metric_value']} {k.get('unit', '')}"
            )

        report_lines.append(f"\n## Recent Events ({len(events)} records)")
        for e in events[:10]:
            report_lines.append(
                f"- [{e['level']}] {e['event_type']}: {e['message'][:80]}"
            )

        output = "\n".join(report_lines)

        return {
            "output": output,
            "operation": plan["operation"],
            "kpis": [
                {"name": "reports_generated", "value": 1, "unit": "count"},
                {"name": "kpis_analyzed", "value": len(kpis), "unit": "count"},
            ],
        }
