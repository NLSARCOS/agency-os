#!/usr/bin/env python3
"""
Agency OS — Report Generator

Generates system status reports in markdown and JSON.
Replaces the old bash-only report script.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from kernel.config import get_config
from kernel.state_manager import get_state

logger = logging.getLogger("agency.reporter")


def generate_report(output_format: str = "markdown") -> str:
    """Generate a comprehensive system report."""
    cfg = get_config()
    state = get_state()

    now = datetime.now(timezone.utc)
    stats = state.get_dashboard_stats()

    # Recent missions
    recent_missions = state.get_missions(limit=10)
    state.get_missions(limit=10)

    # Recent events
    recent_events = state.get_events(limit=20)

    # Recent KPIs
    recent_kpis = state.get_kpis(limit=20)

    if output_format == "json":
        report_data = {
            "generated_at": now.isoformat(),
            "platform": cfg.platform,
            "stats": stats,
            "recent_missions": recent_missions,
            "recent_events": recent_events,
            "recent_kpis": recent_kpis,
        }
        report_str = json.dumps(report_data, indent=2, default=str)
    else:
        report_str = _build_markdown_report(
            now, cfg, stats, recent_missions, recent_events, recent_kpis
        )

    # Save to reports directory
    report_path = cfg.reports_dir / f"report_{now.strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(report_str, encoding="utf-8")

    # Also update the latest report
    latest_path = cfg.reports_dir / "latest_report.md"
    latest_path.write_text(report_str, encoding="utf-8")

    state.log_event(
        "report_generated",
        f"Report generated: {report_path.name}",
        source="reporter",
    )

    logger.info("Report generated: %s", report_path)
    return report_str


def _build_markdown_report(
    now: datetime,
    cfg: object,
    stats: dict,
    missions: list,
    events: list,
    kpis: list,
) -> str:
    lines = [
        "# 🏢 Agency OS — Status Report",
        "",
        f"**Generated:** {now.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Platform:** {cfg.platform}",  # type: ignore[attr-defined]
        f"**Root:** `{cfg.root}`",  # type: ignore[attr-defined]
        "",
        "---",
        "",
        "## 📊 Mission Dashboard",
        "",
    ]

    mission_stats = stats.get("missions", {})
    if mission_stats:
        lines.append("| Status | Count |")
        lines.append("|--------|-------|")
        for status, count in sorted(mission_stats.items()):
            emoji = {
                "queued": "⏳",
                "active": "🔵",
                "running": "🟢",
                "done": "✅",
                "failed": "❌",
            }.get(status, "⚪")
            lines.append(f"| {emoji} {status.capitalize()} | {count} |")
        lines.append("")
    else:
        lines.append("*No missions yet.*\n")

    # Tasks by studio
    tasks_by_studio = stats.get("tasks_by_studio", {})
    if tasks_by_studio:
        lines.append("## 🎨 Tasks by Studio")
        lines.append("")
        lines.append("| Studio | Tasks |")
        lines.append("|--------|-------|")
        for studio, count in sorted(tasks_by_studio.items()):
            lines.append(f"| {studio.capitalize()} | {count} |")
        lines.append("")

    # Model usage
    model_usage = stats.get("model_usage", [])
    if model_usage:
        lines.append("## 🤖 Model Usage")
        lines.append("")
        lines.append(
            "| Model | Calls | Tokens In | Tokens Out | Avg Latency | Failures |"
        )
        lines.append(
            "|-------|-------|-----------|------------|-------------|----------|"
        )
        for m in model_usage:
            lines.append(
                f"| {m['model_name']} | {m['calls']} | "
                f"{m.get('total_in', 0):,} | {m.get('total_out', 0):,} | "
                f"{m.get('avg_latency', 0):.0f}ms | {m.get('failures', 0)} |"
            )
        lines.append("")

    # Recent KPIs
    if kpis:
        lines.append("## 📈 Recent KPIs")
        lines.append("")
        lines.append("| Studio | Metric | Value | Recorded |")
        lines.append("|--------|--------|-------|----------|")
        for k in kpis[:10]:
            lines.append(
                f"| {k['studio']} | {k['metric_name']} | "
                f"{k['metric_value']}{k.get('unit', '')} | "
                f"{k['recorded_at'][:19]} |"
            )
        lines.append("")

    # Recent events
    if events:
        lines.append("## 📝 Recent Events")
        lines.append("")
        for e in events[:10]:
            level_emoji = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}.get(
                e.get("level", "info"), "⚪"
            )
            lines.append(
                f"- {level_emoji} **{e['event_type']}** — {e['message'][:100]}"
            )
        lines.append("")

    # Recent missions
    if missions:
        lines.append("## 🚀 Recent Missions")
        lines.append("")
        lines.append("| ID | Mission | Studio | Status | Created |")
        lines.append("|----|---------|--------|--------|---------|")
        for m in missions[:10]:
            status_emoji = {
                "queued": "⏳",
                "active": "🔵",
                "running": "🟢",
                "done": "✅",
                "failed": "❌",
            }.get(m.get("status", ""), "⚪")
            lines.append(
                f"| {m['id']} | {m['name'][:40]} | {m['studio']} | "
                f"{status_emoji} {m.get('status', '')} | {m['created_at'][:19]} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("*Generated by Agency OS v0.5.0*")
    return "\n".join(lines)
