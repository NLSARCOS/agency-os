#!/usr/bin/env python3
"""
Agency OS — Unified CLI

The single entry point for all Agency OS operations.
Powered by Click + Rich for beautiful terminal output.
"""
from __future__ import annotations

import json
import logging
import sys

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


# ── Main Group ────────────────────────────────────────────────

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.version_option("0.5.0", prog_name="Agency OS")
def main(verbose: bool) -> None:
    """🏢 Agency OS — Sistema Operativo de Agencia AI

    Desarrollo · Marketing · Ventas · Prospección · ABM · Analytics · Creative
    """
    _setup_logging(verbose)


# ── Status ────────────────────────────────────────────────────

@main.command()
def status() -> None:
    """Show full system status dashboard."""
    from kernel.config import get_config
    from kernel.state_manager import get_state

    cfg = get_config()
    state = get_state()
    stats = state.get_dashboard_stats()

    # Header
    console.print(Panel.fit(
        "[bold cyan]🏢 AGENCY OS[/bold cyan] — Sistema Operativo de Agencia AI",
        border_style="cyan",
    ))
    console.print(f"  📁 Root: [dim]{cfg.root}[/dim]")
    console.print(f"  💻 Platform: [green]{cfg.platform}[/green]")
    console.print(f"  🔑 Providers: [yellow]{', '.join(cfg.available_providers) or 'None configured'}[/yellow]")
    console.print()

    # Mission stats
    mission_stats = stats.get("missions", {})
    if mission_stats:
        table = Table(title="📊 Missions", border_style="blue")
        table.add_column("Status", style="bold")
        table.add_column("Count", justify="right")
        icons = {"queued": "⏳", "active": "🔵", "running": "🟢", "done": "✅", "failed": "❌", "blocked": "🚧"}
        for s, c in sorted(mission_stats.items()):
            table.add_row(f"{icons.get(s, '⚪')} {s.capitalize()}", str(c))
        console.print(table)
    else:
        console.print("[dim]No missions yet. Use [bold]agency-os mission add[/bold] to create one.[/dim]")

    # Tasks by studio
    tasks = stats.get("tasks_by_studio", {})
    if tasks:
        console.print()
        table = Table(title="🎨 Studios Activity", border_style="green")
        table.add_column("Studio", style="bold")
        table.add_column("Tasks", justify="right")
        for studio, count in sorted(tasks.items()):
            table.add_row(studio.capitalize(), str(count))
        console.print(table)

    # Recent events
    events = state.get_events(limit=5)
    if events:
        console.print()
        console.print("[bold]📝 Recent Events[/bold]")
        for e in events:
            level_color = {"info": "blue", "warning": "yellow", "error": "red"}.get(e["level"], "white")
            console.print(f"  [{level_color}]●[/{level_color}] {e['event_type']}: {e['message'][:80]}")

    console.print()


# ── Mission Commands ──────────────────────────────────────────

@main.group()
def mission() -> None:
    """Manage missions (add, list, run, inspect)."""
    pass


@mission.command("add")
@click.argument("name")
@click.option("-d", "--description", default="", help="Mission description")
@click.option("-p", "--priority", default=5, type=int, help="Priority (1=highest, 10=lowest)")
@click.option("-s", "--studio", default=None, help="Force assign to studio")
def mission_add(name: str, description: str, priority: int, studio: str | None) -> None:
    """Add a new mission to the queue."""
    from kernel.mission_engine import get_engine

    engine = get_engine()
    mission_id = engine.submit_mission(name, description, priority, studio)
    mission = engine.state.get_mission(mission_id)

    console.print(Panel(
        f"[bold green]✅ Mission #{mission_id} created[/bold green]\n\n"
        f"  📌 Name: {name}\n"
        f"  🎨 Studio: [cyan]{mission['studio']}[/cyan]\n"
        f"  📊 Priority: {priority}\n"
        f"  📝 Status: queued",
        title="New Mission",
        border_style="green",
    ))


@mission.command("list")
@click.option("--status", "-s", default=None, help="Filter by status")
@click.option("--limit", "-n", default=20, type=int, help="Number of results")
def mission_list(status: str | None, limit: int) -> None:
    """List all missions."""
    from kernel.state_manager import MissionStatus, get_state

    state = get_state()
    ms = None
    if status:
        try:
            ms = MissionStatus(status)
        except ValueError:
            console.print(f"[red]Invalid status: {status}[/red]")
            return

    missions = state.get_missions(status=ms, limit=limit)

    if not missions:
        console.print("[dim]No missions found.[/dim]")
        return

    table = Table(title="🚀 Missions", border_style="blue")
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Mission")
    table.add_column("Studio", style="cyan")
    table.add_column("Priority", justify="center")
    table.add_column("Status")
    table.add_column("Created", style="dim")

    icons = {"queued": "⏳", "active": "🔵", "running": "🟢", "done": "✅", "failed": "❌"}
    for m in missions:
        s = m.get("status", "")
        table.add_row(
            str(m["id"]),
            m["name"][:50],
            m["studio"],
            str(m["priority"]),
            f"{icons.get(s, '⚪')} {s}",
            m["created_at"][:19],
        )
    console.print(table)


@mission.command("run")
@click.argument("mission_id", type=int)
def mission_run(mission_id: int) -> None:
    """Execute a specific mission."""
    from kernel.mission_engine import get_engine

    engine = get_engine()
    console.print(f"[bold]🚀 Executing mission #{mission_id}...[/bold]")

    with console.status("[green]Running pipeline..."):
        result = engine.execute_mission(mission_id)

    if result.get("status") == "done":
        console.print(Panel(
            f"[green]✅ Mission #{mission_id} completed[/green]\n"
            f"  ⏱️  Duration: {result.get('duration_seconds', 0):.1f}s\n"
            f"  📦 Output: {str(result.get('output', ''))[:200]}",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"[red]❌ Mission #{mission_id} failed[/red]\n"
            f"  💥 Error: {result.get('error', 'Unknown')[:200]}",
            border_style="red",
        ))


# ── Studio Commands ───────────────────────────────────────────

@main.group()
def studio() -> None:
    """Manage and run studio pipelines."""
    pass


@studio.command("list")
def studio_list() -> None:
    """List all available studios."""
    from kernel.config import get_config

    cfg = get_config()
    table = Table(title="🎨 Studios", border_style="magenta")
    table.add_column("Studio", style="bold")
    table.add_column("Has Pipeline")
    table.add_column("Description")

    descriptions = {
        "dev": "Software development, architecture, QA, deployment",
        "marketing": "Campaigns, positioning, funnels, content strategy",
        "sales": "Outreach, follow-up, closing, commercial pipeline",
        "leadops": "Lead generation, scraping, enrichment, dedup, scoring",
        "abm": "Account-based marketing and targeting",
        "analytics": "Reporting, KPIs, dashboards, data analysis",
        "creative": "Creative assets, design, visual content production",
    }

    for name in cfg.studio_names:
        pipeline_exists = (cfg.studios_dir / name / "pipeline.py").exists()
        table.add_row(
            name.capitalize(),
            "✅" if pipeline_exists else "❌",
            descriptions.get(name, ""),
        )
    console.print(table)


@studio.command("run")
@click.argument("studio_name")
@click.argument("task", required=False, default="")
@click.option("-d", "--description", default="", help="Task description")
def studio_run(studio_name: str, task: str, description: str) -> None:
    """Run a studio pipeline directly."""
    from kernel.mission_engine import get_engine

    if not task:
        task = f"Manual execution of {studio_name} studio"

    engine = get_engine()
    mission_id = engine.submit_mission(task, description, force_studio=studio_name)
    result = engine.execute_mission(mission_id)

    if result.get("status") == "done":
        console.print(f"[green]✅ {studio_name.capitalize()} pipeline completed[/green]")
    else:
        console.print(f"[red]❌ {studio_name.capitalize()} pipeline failed: {result.get('error', '')}[/red]")


# ── Cycle / Daemon ────────────────────────────────────────────

@main.command()
@click.option("--once", is_flag=True, help="Run a single cycle then exit")
def start(once: bool) -> None:
    """Start the Agency OS scheduler daemon."""
    from kernel.scheduler import AgencyScheduler

    sched = AgencyScheduler()
    sched.setup()

    if once:
        console.print("[bold]🔄 Running single cycle...[/bold]")
        results = sched.run_once()
        for r in results:
            icon = "✅" if r["status"] == "ok" else "❌"
            console.print(f"  {icon} {r['job']}: {r['status']} ({r.get('duration', '?')}s)")
    else:
        console.print(Panel(
            "[bold green]🚀 Agency OS Scheduler Starting[/bold green]\n\n"
            f"  Jobs: {len(sched._jobs)}\n"
            "  Press Ctrl+C to stop",
            border_style="green",
        ))
        sched.start_daemon()


# ── Report ────────────────────────────────────────────────────

@main.command()
@click.option("--json", "fmt", flag_value="json", help="Output as JSON")
@click.option("--markdown", "fmt", flag_value="markdown", default=True, help="Output as Markdown")
def report(fmt: str) -> None:
    """Generate and display a system report."""
    from kernel.reporter import generate_report

    report_str = generate_report(output_format=fmt)
    if fmt == "json":
        console.print_json(report_str)
    else:
        from rich.markdown import Markdown
        console.print(Markdown(report_str))


# ── Route (utility) ──────────────────────────────────────────

@main.command()
@click.argument("task_text")
def route(task_text: str) -> None:
    """Test task routing — see which studio would handle a task."""
    from kernel.task_router import route_task

    result = route_task(task_text)

    console.print(Panel(
        f"[bold]📌 Task:[/bold] {result.task}\n"
        f"[bold]🎨 Studio:[/bold] [cyan]{result.studio}[/cyan]\n"
        f"[bold]📊 Confidence:[/bold] {result.confidence:.0%}\n"
        f"[bold]🏆 Scores:[/bold] {json.dumps(result.scores, indent=2)}",
        title="🧭 Route Result",
        border_style="cyan",
    ))


# ── Health ────────────────────────────────────────────────────

@main.command()
def health() -> None:
    """Run system health check."""
    from kernel.scheduler import health_check

    checks = health_check()
    is_healthy = checks.pop("healthy", False)
    checks.pop("timestamp", None)

    title = "[bold green]✅ System Healthy[/bold green]" if is_healthy else "[bold red]❌ System Degraded[/bold red]"
    console.print(Panel(title, border_style="green" if is_healthy else "red"))

    for check, ok in checks.items():
        icon = "✅" if ok else "❌"
        console.print(f"  {icon} {check.replace('_', ' ').capitalize()}")


# ── Init ──────────────────────────────────────────────────────

@main.command()
def init() -> None:
    """Initialize Agency OS in current directory (create dirs + configs)."""
    from kernel.config import get_config

    cfg = get_config()
    dirs = [
        cfg.data_dir, cfg.logs_dir, cfg.reports_dir,
        cfg.studios_dir, cfg.configs_dir,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Create default .env if missing
    env_file = cfg.root / ".env"
    if not env_file.exists():
        env_example = cfg.root / "configs" / "env.example"
        if env_example.exists():
            import shutil
            shutil.copy(env_example, env_file)
            console.print(f"  📄 Created .env from template")

    console.print("[green]✅ Agency OS initialized[/green]")
    console.print(f"  📁 Root: {cfg.root}")
    console.print(f"  📊 Database: {cfg.db_path}")
    console.print(f"  📁 Studios: {cfg.studios_dir}")
    console.print(f"  📝 Reports: {cfg.reports_dir}")


if __name__ == "__main__":
    main()
