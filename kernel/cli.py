#!/usr/bin/env python3
"""
Agency OS v3.0 — Unified CLI

Full system control: missions, agents, tools, studios,
OpenClaw gateway, events, health, and reporting.
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
@click.version_option("3.0.0", prog_name="Agency OS")
def main(verbose: bool) -> None:
    """🏢 Agency OS v3.0 — Sistema Operativo de Agencia AI

    Desarrollo · Marketing · Ventas · Prospección · ABM · Analytics · Creative

    Powered by OpenClaw + Multi-Agent DAG Execution
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
        "[bold cyan]🏢 AGENCY OS v3.0[/bold cyan] — Sistema Operativo de Agencia AI\n"
        "[dim]OpenClaw-powered · Multi-Agent · DAG Execution[/dim]",
        border_style="cyan",
    ))
    console.print(f"  📁 Root: [dim]{cfg.root}[/dim]")
    console.print(f"  💻 Platform: [green]{cfg.platform}[/green]")
    console.print(f"  🔑 Providers: [yellow]{', '.join(cfg.available_providers) or 'None configured'}[/yellow]")

    # OpenClaw status
    try:
        from kernel.openclaw_bridge import get_openclaw
        oc = get_openclaw()
        oc_status = oc.get_status()
        oc_icon = "🟢" if oc_status["available"] else "🔴"
        console.print(f"  🐙 OpenClaw: {oc_icon} {oc_status['gateway_url']} ({oc_status['active_sessions']} sessions)")
    except Exception:
        console.print("  🐙 OpenClaw: [red]Not configured[/red]")

    console.print()

    # Mission stats
    mission_stats = stats.get("missions", {})
    if mission_stats:
        table = Table(title="📊 Missions", border_style="blue")
        table.add_column("Status", style="bold")
        table.add_column("Count", justify="right")
        icons = {"queued": "⏳", "active": "🔵", "running": "🟢", "review": "🔎",
                 "done": "✅", "failed": "❌", "blocked": "🚧"}
        for s, c in sorted(mission_stats.items()):
            table.add_row(f"{icons.get(s, '⚪')} {s.capitalize()}", str(c))
        console.print(table)
    else:
        console.print("[dim]No missions yet. Use [bold]agency-os mission add[/bold] to create one.[/dim]")

    # Agent status
    try:
        from kernel.agent_manager import get_agent_manager
        mgr = get_agent_manager()
        agents = mgr.list_agents()
        if agents:
            console.print()
            table = Table(title="🤖 Agents", border_style="magenta")
            table.add_column("Agent", style="bold")
            table.add_column("Skills", style="dim")
            table.add_column("Tasks", justify="right")
            table.add_column("Active")
            for a in agents:
                table.add_row(
                    a["id"],
                    ", ".join(a["skills"][:3]),
                    str(a["tasks_completed"]),
                    "🟢" if a["active"] else "⚫",
                )
            console.print(table)
    except Exception:
        pass

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
    from kernel.mission_engine import MissionEngine

    engine = MissionEngine()
    mission_id = engine.submit_mission(name, description, priority, force_studio=studio or "")
    m = engine.state.get_mission(mission_id)

    # Get crew info
    from kernel.agent_manager import get_agent_manager
    mgr = get_agent_manager()
    crew = mgr.assemble_crew(m["studio"])

    console.print(Panel(
        f"[bold green]✅ Mission #{mission_id} created[/bold green]\n\n"
        f"  📌 Name: {name}\n"
        f"  🎨 Studio: [cyan]{m['studio']}[/cyan]\n"
        f"  📊 Priority: {priority}\n"
        f"  🤖 Crew: [magenta]{', '.join(crew)}[/magenta]\n"
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

    icons = {"queued": "⏳", "active": "🔵", "running": "🟢", "review": "🔎",
             "done": "✅", "failed": "❌"}
    for m in missions:
        s = m.get("status", "")
        table.add_row(
            str(m["id"]), m["name"][:50], m["studio"],
            str(m["priority"]), f"{icons.get(s, '⚪')} {s}",
            m["created_at"][:19],
        )
    console.print(table)


@mission.command("run")
@click.argument("mission_id", type=int)
def mission_run(mission_id: int) -> None:
    """Execute a specific mission via DAG engine."""
    from kernel.mission_engine import MissionEngine

    engine = MissionEngine()
    console.print(f"[bold]🚀 Executing mission #{mission_id} via DAG engine...[/bold]")

    with console.status("[green]Running mission pipeline..."):
        result = engine.execute_mission(mission_id)

    if result.get("success"):
        steps = result.get("steps", {})
        console.print(Panel(
            f"[green]✅ Mission #{mission_id} completed[/green]\n"
            f"  ⏱️  Duration: {result.get('duration_ms', 0):.0f}ms\n"
            f"  📦 Steps: {len(steps)}\n"
            f"  🤖 Status: {result.get('status', '')}",
            border_style="green",
        ))
        for step_id, step_data in steps.items():
            icon = "✅" if step_data["status"] == "completed" else "❌" if step_data["status"] == "failed" else "⏭️"
            console.print(f"  {icon} {step_id}: {step_data['agent']} ({step_data.get('duration_ms', 0):.0f}ms)")
    else:
        console.print(Panel(
            f"[red]❌ Mission #{mission_id} failed[/red]\n"
            f"  💥 Error: {result.get('error', 'Unknown')[:300]}",
            border_style="red",
        ))


# ── Agent Commands ────────────────────────────────────────────

@main.group()
def agent() -> None:
    """Manage AI agents (list, inspect, delegate, execute)."""
    pass


@agent.command("list")
def agent_list() -> None:
    """List all loaded agents."""
    from kernel.agent_manager import get_agent_manager

    mgr = get_agent_manager()
    agents = mgr.list_agents()

    table = Table(title="🤖 Agents", border_style="magenta")
    table.add_column("ID", style="bold")
    table.add_column("Description")
    table.add_column("Skills", style="dim")
    table.add_column("Tasks Done", justify="right")
    table.add_column("Active")

    for a in agents:
        table.add_row(
            a["id"],
            a["description"][:60],
            ", ".join(a["skills"][:3]),
            str(a["tasks_completed"]),
            "🟢" if a["active"] else "⚫",
        )
    console.print(table)
    console.print(f"\n  [dim]Total agents: {len(agents)}[/dim]")


@agent.command("run")
@click.argument("agent_id")
@click.argument("task")
def agent_run(agent_id: str, task: str) -> None:
    """Execute a task using a specific agent."""
    from kernel.agent_manager import get_agent_manager

    mgr = get_agent_manager()

    if not mgr.get_agent(agent_id):
        console.print(f"[red]Unknown agent: {agent_id}[/red]")
        available = [a["id"] for a in mgr.list_agents()]
        console.print(f"[dim]Available: {', '.join(available)}[/dim]")
        return

    console.print(f"[bold]🤖 Executing via {agent_id}...[/bold]")

    with console.status(f"[green]{agent_id} working..."):
        result = mgr.execute_task(agent_id, task)

    if result["success"]:
        console.print(Panel(
            f"[green]✅ Task completed[/green]\n\n"
            f"  🤖 Agent: {result['agent']}\n"
            f"  🧠 Model: {result['model']}\n"
            f"  ⏱️  Duration: {result['duration_ms']:.0f}ms\n"
            f"  🔧 Tools used: {len(result.get('tool_results', []))}\n\n"
            f"[bold]Output:[/bold]\n{result['content'][:500]}",
            border_style="green",
            title=f"Agent: {agent_id}",
        ))
    else:
        console.print(f"[red]❌ Failed: {result.get('error', '')}[/red]")


@agent.command("delegate")
@click.argument("from_agent")
@click.argument("to_agent")
@click.argument("task")
def agent_delegate(from_agent: str, to_agent: str, task: str) -> None:
    """Delegate a task from one agent to another."""
    from kernel.agent_manager import get_agent_manager

    mgr = get_agent_manager()
    console.print(f"[bold]🔄 Delegating: {from_agent} → {to_agent}[/bold]")

    delegation = mgr.delegate(from_agent, to_agent, task)

    icon = "✅" if delegation.status == "completed" else "❌"
    console.print(f"  {icon} Status: {delegation.status}")
    if delegation.result:
        console.print(f"  📦 Result: {delegation.result[:200]}")


# ── Tool Commands ─────────────────────────────────────────────

@main.group()
def tool() -> None:
    """Manage and execute tools (shell, HTTP, file, DB, git)."""
    pass


@tool.command("list")
@click.option("-a", "--agent", "agent_id", default=None, help="Filter by agent permissions")
def tool_list(agent_id: str | None) -> None:
    """List available tools."""
    from kernel.tool_executor import get_tool_executor

    executor = get_tool_executor()
    tools = executor.list_tools(agent_id=agent_id)

    table = Table(title="🔧 Tools", border_style="yellow")
    table.add_column("Tool", style="bold")
    table.add_column("Description")
    table.add_column("Permissions", style="dim")
    if agent_id:
        table.add_column("Available")

    for t in tools:
        row = [t["name"], t["description"][:50], ", ".join(t["permissions"])]
        if agent_id:
            row.append("✅" if t.get("available") else "❌")
        table.add_row(*row)
    console.print(table)


@tool.command("exec")
@click.argument("tool_name")
@click.option("-p", "--params", default="{}", help="JSON params")
@click.option("-a", "--agent", "agent_id", default="system", help="Agent ID for permissions")
def tool_exec(tool_name: str, params: str, agent_id: str) -> None:
    """Execute a tool directly."""
    from kernel.tool_executor import get_tool_executor

    try:
        parsed = json.loads(params)
    except json.JSONDecodeError:
        console.print("[red]Invalid JSON params[/red]")
        return

    executor = get_tool_executor()
    result = executor.execute(tool_name, parsed, agent_id=agent_id)

    icon = "✅" if result.success else "❌"
    console.print(f"{icon} [bold]{tool_name}[/bold] ({result.duration_ms:.0f}ms)")
    if result.output:
        console.print(result.output[:1000])
    if result.error:
        console.print(f"[red]{result.error}[/red]")


@tool.command("history")
@click.option("-t", "--tool-name", default=None, help="Filter by tool")
@click.option("-n", "--limit", default=20, type=int)
def tool_history(tool_name: str | None, limit: int) -> None:
    """Show tool execution history."""
    from kernel.tool_executor import get_tool_executor

    executor = get_tool_executor()
    history = executor.get_history(tool=tool_name, limit=limit)

    table = Table(title="🔧 Tool History", border_style="yellow")
    table.add_column("Tool", style="bold")
    table.add_column("Status")
    table.add_column("Duration", justify="right")
    table.add_column("Timestamp", style="dim")

    for h in history:
        table.add_row(
            h["tool"],
            "✅" if h["success"] else "❌",
            f"{h['duration_ms']:.0f}ms",
            h["timestamp"][:19],
        )
    console.print(table)


# ── OpenClaw Commands ─────────────────────────────────────────

@main.group()
def openclaw() -> None:
    """OpenClaw gateway management."""
    pass


@openclaw.command("status")
def openclaw_status() -> None:
    """Check OpenClaw gateway connection status."""
    from kernel.openclaw_bridge import get_openclaw

    oc = get_openclaw()
    status = oc.get_status()

    icon = "🟢" if status["available"] else "🔴"
    console.print(Panel(
        f"[bold]{icon} OpenClaw Gateway[/bold]\n\n"
        f"  🌐 URL: {status['gateway_url']}\n"
        f"  📡 Available: {'Yes' if status['available'] else 'No'}\n"
        f"  🔗 Active Sessions: {status['active_sessions']}",
        border_style="cyan",
        title="🐙 OpenClaw",
    ))

    if status["sessions"]:
        console.print("\n[bold]Sessions:[/bold]")
        for agent, sid in status["sessions"].items():
            console.print(f"  🤖 {agent}: {sid[:20]}...")


@openclaw.command("ask")
@click.argument("prompt")
@click.option("-m", "--model", default="", help="Model override")
@click.option("-a", "--agent", "agent_id", default="", help="Agent context")
def openclaw_ask(prompt: str, model: str, agent_id: str) -> None:
    """Ask a question through OpenClaw gateway."""
    from kernel.openclaw_bridge import get_openclaw

    oc = get_openclaw()
    with console.status("[green]Thinking..."):
        response = oc.ask(prompt, model=model, agent_id=agent_id)

    if response:
        console.print(Panel(response[:2000], title="🐙 Response", border_style="green"))
    else:
        console.print("[red]No response received[/red]")


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
    from kernel.mission_engine import MissionEngine

    if not task:
        task = f"Manual execution of {studio_name} studio"

    engine = MissionEngine()
    mission_id = engine.submit_mission(task, description, force_studio=studio_name)
    result = engine.execute_mission(mission_id)

    if result.get("success"):
        console.print(f"[green]✅ {studio_name.capitalize()} pipeline completed[/green]")
    else:
        console.print(f"[red]❌ {studio_name.capitalize()} pipeline failed: {result.get('error', '')}[/red]")


# ── Events ────────────────────────────────────────────────────

@main.command("events")
@click.option("-t", "--type", "event_type", default=None, help="Filter by event type")
@click.option("-l", "--level", default=None, help="Filter by level (info/warning/error)")
@click.option("-n", "--limit", default=20, type=int)
def events_cmd(event_type: str | None, level: str | None, limit: int) -> None:
    """Show system events."""
    from kernel.state_manager import get_state

    state = get_state()
    events = state.get_events(event_type=event_type, level=level, limit=limit)

    if not events:
        console.print("[dim]No events found.[/dim]")
        return

    table = Table(title="📝 Events", border_style="blue")
    table.add_column("Type", style="bold")
    table.add_column("Message")
    table.add_column("Level")
    table.add_column("Source", style="dim")
    table.add_column("Time", style="dim")

    for e in events:
        level_style = {"info": "blue", "warning": "yellow", "error": "red"}.get(e["level"], "white")
        table.add_row(
            e["event_type"],
            e["message"][:60],
            f"[{level_style}]{e['level']}[/{level_style}]",
            e["source"],
            e["timestamp"][:19],
        )
    console.print(table)


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
            "[bold green]🚀 Agency OS v3.0 Scheduler Starting[/bold green]\n\n"
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
    """Run system health check (kernel + OpenClaw + agents)."""
    from kernel.scheduler import health_check

    checks = health_check()
    is_healthy = checks.pop("healthy", False)
    checks.pop("timestamp", None)

    title = "[bold green]✅ System Healthy[/bold green]" if is_healthy else "[bold red]❌ System Degraded[/bold red]"
    console.print(Panel(title, border_style="green" if is_healthy else "red"))

    for check, ok in checks.items():
        icon = "✅" if ok else "❌"
        console.print(f"  {icon} {check.replace('_', ' ').capitalize()}")

    # OpenClaw check
    try:
        from kernel.openclaw_bridge import get_openclaw
        oc = get_openclaw()
        available = oc.is_available()
        console.print(f"  {'✅' if available else '❌'} OpenClaw gateway")
    except Exception:
        console.print("  ❌ OpenClaw gateway")

    # Agent check
    try:
        from kernel.agent_manager import get_agent_manager
        mgr = get_agent_manager()
        count = len(mgr.list_agents())
        console.print(f"  ✅ Agents loaded ({count})")
    except Exception:
        console.print("  ❌ Agent manager")


# ── Init ──────────────────────────────────────────────────────

@main.command()
def init() -> None:
    """Initialize Agency OS in current directory."""
    from kernel.config import get_config

    cfg = get_config()
    dirs = [
        cfg.data_dir, cfg.logs_dir, cfg.reports_dir,
        cfg.studios_dir, cfg.configs_dir,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    env_file = cfg.root / ".env"
    if not env_file.exists():
        env_example = cfg.root / "configs" / "env.example"
        if env_example.exists():
            import shutil
            shutil.copy(env_example, env_file)
            console.print("  📄 Created .env from template")

    console.print("[green]✅ Agency OS v3.0 initialized[/green]")
    console.print(f"  📁 Root: {cfg.root}")
    console.print(f"  📊 Database: {cfg.db_path}")
    console.print(f"  📁 Studios: {cfg.studios_dir}")
    console.print(f"  📝 Reports: {cfg.reports_dir}")


if __name__ == "__main__":
    main()
