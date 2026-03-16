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
            # Show artifacts
            artifacts = step_data.get("artifacts", [])
            for art in artifacts:
                console.print(f"      📄 {art}")
    else:
        console.print(Panel(
            f"[red]❌ Mission #{mission_id} failed[/red]\n"
            f"  💥 Error: {result.get('error', 'Unknown')[:300]}",
            border_style="red",
        ))


@mission.command("results")
@click.argument("mission_id", type=int)
def mission_results(mission_id: int) -> None:
    """📦 View results and artifacts for a completed mission."""
    from pathlib import Path
    import json as json_mod

    cfg = get_config()
    output_dir = cfg.data_dir / "outputs"

    # Check mission-specific output
    mission_file = output_dir / f"mission_{mission_id}.json"
    mission_dir = output_dir / f"mission_{mission_id}"

    if mission_file.exists():
        data = json_mod.loads(mission_file.read_text())
        console.print(Panel(
            f"[bold]Mission #{mission_id}: {data.get('name', 'N/A')}[/bold]\n"
            f"  Studio: {data.get('studio', 'N/A')}\n"
            f"  Success: {'✅' if data.get('success') else '❌'}\n"
            f"  Timestamp: {data.get('timestamp', 'N/A')}",
            border_style="green" if data.get("success") else "red",
        ))
    else:
        console.print(f"[yellow]No output file for mission #{mission_id}[/yellow]")

    # List artifacts
    if mission_dir.exists():
        files = list(mission_dir.iterdir())
        if files:
            console.print(f"\n[bold]📄 File Artifacts ({len(files)}):[/bold]")
            for f in sorted(files):
                size = f.stat().st_size
                console.print(f"  📄 {f.name} ({size:,} bytes)")
                console.print(f"     Path: {f}")
        else:
            console.print("[dim]No file artifacts generated[/dim]")
    else:
        console.print("[dim]No artifact directory[/dim]")


@mission.command("outputs")
def mission_outputs() -> None:
    """📦 List all mission outputs and objective reports."""
    from pathlib import Path

    cfg = get_config()
    output_dir = cfg.data_dir / "outputs"

    if not output_dir.exists():
        console.print("[yellow]No outputs directory yet[/yellow]")
        return

    # List objective reports
    obj_reports = sorted(output_dir.glob("objective_*.md"))
    if obj_reports:
        console.print("[bold]📋 Objective Reports:[/bold]")
        for r in obj_reports:
            console.print(f"  📋 {r.name} ({r.stat().st_size:,} bytes)")

    # List mission outputs
    mission_files = sorted(output_dir.glob("mission_*.json"))
    if mission_files:
        console.print(f"\n[bold]📦 Mission Outputs ({len(mission_files)}):[/bold]")
        for f in mission_files:
            console.print(f"  📦 {f.name}")

    # List mission artifact directories
    mission_dirs = sorted(
        d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("mission_")
    )
    if mission_dirs:
        console.print(f"\n[bold]📄 Artifact Directories ({len(mission_dirs)}):[/bold]")
        for d in mission_dirs:
            files = list(d.iterdir())
            console.print(f"  📁 {d.name}/ ({len(files)} files)")
            for f in sorted(files)[:5]:
                console.print(f"      📄 {f.name}")
            if len(files) > 5:
                console.print(f"      ... and {len(files) - 5} more")

    if not obj_reports and not mission_files and not mission_dirs:
        console.print("[yellow]No outputs yet. Run `agency orchestrate` first.[/yellow]")


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


# ── Cycle / Daemon / Heartbeat ──────────────────────────────

@main.command()
@click.option("--once", is_flag=True, help="Run a single cycle then exit")
@click.option("--daemon", is_flag=True, help="Run the 24/7 Agency Heartbeat")
def start(once: bool, daemon: bool) -> None:
    """Start the Agency OS scheduler or permanent heartbeat."""
    if daemon:
        import asyncio
        from kernel.heartbeat import get_heartbeat
        
        console.print(Panel(
            "[bold green]🫀 Agency OS v5.0 Heartbeat Starting[/bold green]\n\n"
            "  The agency is now alive and running 24/7.\n"
            "  Press Ctrl+C to stop",
            border_style="green",
        ))
        
        hb = get_heartbeat()
        try:
            asyncio.run(hb.run())
        except KeyboardInterrupt:
            hb.stop()
            console.print("\n[yellow]Heartbeat stopped by user.[/yellow]")
        return

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
@click.argument("objective", nargs=-1, required=True)
def orchestrate(objective: tuple[str, ...]) -> None:
    """🎯 Orchestrate a full objective across multiple studios.

    Example: agency orchestrate "Create a landing page and sell it"
    """
    import asyncio
    from kernel.mission_planner import MissionPlanner

    full_objective = " ".join(objective)
    console.print(
        Panel(
            f"[bold cyan]🎯 Orchestrating:[/] {full_objective}",
            title="Mission Planner",
            border_style="cyan",
        )
    )
    console.print("[dim]Decomposing into sub-missions...[/]\n")

    planner = MissionPlanner()
    result = asyncio.run(planner.plan_and_execute(full_objective))

    # Show plan
    table = Table(title="📋 Execution Plan", show_lines=True)
    table.add_column("#", style="bold", width=4)
    table.add_column("Studio", style="cyan", width=12)
    table.add_column("Mission", width=30)
    table.add_column("Depends On", style="yellow", width=14)
    table.add_column("Priority", style="green", width=8)

    for i, m in enumerate(result["plan"], 1):
        deps = ", ".join(m["depends_on"]) if m["depends_on"] else "—"
        table.add_row(
            str(m.get("mission_id", i)),
            m["studio"].upper(),
            m["name"],
            deps,
            f"P{m['priority']}",
        )

    console.print(table)
    console.print()
    console.print(
        Panel(
            f"[bold green]✅ {result['sub_missions']} sub-missions queued[/]\n"
            f"  Studios: [cyan]{', '.join(s.upper() for s in result['studios'])}[/]\n"
            f"  Waves: [yellow]{result['waves']}[/] (parallel where possible)\n"
            f"  IDs: {result['mission_ids']}\n\n"
            f"[dim]The heartbeat will execute these in parallel every 60s.\n"
            f"Monitor progress: [bold]agency dashboard[/][/]",
            title="Queued",
            border_style="green",
        )
    )


@main.command()
@click.option("--port", default=3000, help="Dashboard port (default: 3000)")
@click.option("--host", default="0.0.0.0", help="Dashboard host")
def dashboard(port: int, host: str) -> None:
    """🖥️  Launch the web dashboard for real-time monitoring."""
    from kernel.dashboard import start_dashboard

    console.print(
        Panel(
            f"[bold green]🖥️  Agency OS Dashboard[/]\n\n"
            f"  Open in browser: [bold cyan]http://localhost:{port}[/]\n"
            f"  Auto-refresh every 10s\n"
            f"  Press Ctrl+C to stop",
            title="Dashboard",
            border_style="cyan",
        )
    )
    start_dashboard(host=host, port=port)


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


# ── Workflow Commands ─────────────────────────────────────────

@main.group()
def workflow() -> None:
    """Manage workflows (list, run, inspect)."""
    pass


@workflow.command("list")
def workflow_list() -> None:
    """List all available workflows."""
    from kernel.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    workflows = engine.list_workflows()

    if not workflows:
        console.print("[dim]No workflows found. Add YAML files to studios/*/workflows/[/dim]")
        return

    table = Table(title="📋 Workflows", border_style="blue")
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("Studio", style="cyan")
    table.add_column("Nodes", justify="right")
    table.add_column("Description", style="dim")

    for wf in workflows:
        table.add_row(
            wf["id"], wf["name"], wf["studio"],
            str(wf["nodes"]), wf["description"][:50],
        )
    console.print(table)


@workflow.command("run")
@click.argument("workflow_id")
@click.option("-m", "--mission", "mission_id", default=None, type=int, help="Link to mission ID")
def workflow_run(workflow_id: str, mission_id: int | None) -> None:
    """Execute a workflow by ID."""
    from kernel.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    console.print(f"[bold]📋 Running workflow: {workflow_id}...[/bold]")

    with console.status("[green]Executing workflow..."):
        run = engine.execute(workflow_id, mission_id=mission_id)

    if run.status.value == "completed":
        console.print(Panel(
            f"[green]✅ Workflow completed[/green]\n"
            f"  📋 Workflow: {run.workflow_id}\n"
            f"  ⏱️  Duration: {run.duration_ms:.0f}ms\n"
            f"  📦 Nodes: {len(run.node_results)}",
            border_style="green",
        ))
        for node_id, data in run.node_results.items():
            icon = {"completed": "✅", "failed": "❌", "skipped": "⏭️"}.get(data["status"], "⚪")
            console.print(f"  {icon} {node_id}: {data['status']} ({data.get('duration_ms', 0):.0f}ms)")
    elif run.status.value == "paused":
        console.print(Panel(
            f"[yellow]⏸️  Workflow paused — human input needed[/yellow]\n\n"
            f"  📋 Run ID: {run.id}\n"
            f"  📍 Node: {run.current_node}\n"
            f"  💬 {run.human_input_request[:200]}",
            border_style="yellow",
        ))
        console.print("[dim]Resume with: agency-os workflow resume [run_id] [response][/dim]")
    else:
        console.print(f"[red]❌ Workflow failed: {run.checkpoint.get('error', '')}[/red]")


@workflow.command("runs")
@click.option("-s", "--status", default=None, help="Filter by status")
def workflow_runs(status: str | None) -> None:
    """List workflow runs."""
    from kernel.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    runs = engine.list_runs(status)

    if not runs:
        console.print("[dim]No workflow runs found.[/dim]")
        return

    table = Table(title="📋 Workflow Runs", border_style="blue")
    table.add_column("ID", style="bold")
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Nodes", justify="right")
    table.add_column("Duration", justify="right")

    for r in runs:
        s = r["status"]
        icon = {"completed": "✅", "running": "🟢", "paused": "⏸️", "failed": "❌"}.get(s, "⚪")
        table.add_row(
            r["id"], r["workflow"], f"{icon} {s}",
            str(r["nodes_completed"]),
            f"{r['duration_ms']:.0f}ms",
        )
    console.print(table)


@workflow.command("resume")
@click.argument("run_id")
@click.argument("response")
def workflow_resume(run_id: str, response: str) -> None:
    """Resume a paused workflow with human input."""
    from kernel.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    run = engine.resume(run_id, response)
    if run:
        console.print(f"[green]✅ Workflow resumed: {run.status.value}[/green]")
    else:
        console.print(f"[red]Run not found or not paused: {run_id}[/red]")


# ── Memory Commands ───────────────────────────────────────────

@main.group()
def memory() -> None:
    """Manage agent memory and knowledge base."""
    pass


@memory.command("list")
@click.argument("agent_id")
@click.option("-n", "--limit", default=20, type=int)
def memory_list(agent_id: str, limit: int) -> None:
    """List recent memory for an agent."""
    from kernel.memory_manager import get_memory_manager

    mm = get_memory_manager()
    memories = mm.recall(agent_id, limit=limit)

    if not memories:
        console.print(f"[dim]No memories for agent: {agent_id}[/dim]")
        return

    table = Table(title=f"🧠 Memory: {agent_id}", border_style="magenta")
    table.add_column("Role", style="bold")
    table.add_column("Content")
    table.add_column("Time", style="dim")

    for m in memories:
        table.add_row(m.role, m.content[:80], m.timestamp[:19])
    console.print(table)


@memory.command("search")
@click.argument("agent_id")
@click.argument("query")
def memory_search(agent_id: str, query: str) -> None:
    """Search agent memory by relevance."""
    from kernel.memory_manager import get_memory_manager

    mm = get_memory_manager()
    results = mm.search_memory(agent_id, query)

    if not results:
        console.print(f"[dim]No relevant memories found.[/dim]")
        return

    table = Table(title=f"🔍 Memory Search: {query}", border_style="yellow")
    table.add_column("Relevance", justify="right", style="bold")
    table.add_column("Content")
    table.add_column("Time", style="dim")

    for r in results:
        table.add_row(f"{r.relevance:.3f}", r.content[:80], r.timestamp[:19])
    console.print(table)


@memory.command("knowledge")
@click.option("-q", "--query", default=None, help="Search query")
@click.option("-n", "--limit", default=20, type=int)
def memory_knowledge(query: str | None, limit: int) -> None:
    """List or search the shared knowledge base."""
    from kernel.memory_manager import get_memory_manager

    mm = get_memory_manager()

    if query:
        entries = mm.query_knowledge(query, limit=limit)
        title = f"🔍 Knowledge: {query}"
    else:
        entries = mm.get_all_knowledge(limit=limit)
        title = "📚 Knowledge Base"

    if not entries:
        console.print("[dim]No knowledge entries found.[/dim]")
        return

    table = Table(title=title, border_style="cyan")
    table.add_column("Topic", style="bold")
    table.add_column("Content")
    table.add_column("Source", style="dim")
    table.add_column("Access", justify="right")

    for k in entries:
        table.add_row(k.topic, k.content[:60], k.source_agent, str(k.access_count))
    console.print(table)


@memory.command("stats")
def memory_stats() -> None:
    """Show memory and knowledge statistics."""
    from kernel.memory_manager import get_memory_manager

    mm = get_memory_manager()
    stats = mm.get_stats()

    console.print(Panel(
        f"[bold]🧠 Memory Stats[/bold]\n\n"
        f"  📝 Total Memories: {stats['total_memories']}\n"
        f"  📚 Knowledge Entries: {stats['total_knowledge']}\n"
        f"  🤖 Agents with Memory: {', '.join(stats['agents_with_memory']) or 'None'}",
        border_style="magenta",
    ))


# ── Autonomy Commands ─────────────────────────────────────────

@main.group()
def auto() -> None:
    """Autonomous operations (discover, heal, learn)."""
    pass


@auto.command("discover")
def auto_discover() -> None:
    """Discover pending tasks proactively."""
    from kernel.autonomy_engine import get_autonomy_engine

    engine = get_autonomy_engine()
    result = engine.run_cycle(max_tasks=10, dry_run=True)

    console.print(Panel(
        f"[bold]🧠 Autonomy Discovery[/bold]\n\n"
        f"  📋 Tasks Found: {result['tasks_found']}\n"
        f"  📚 Learnings: {result['learnings']}\n"
        f"  🔍 Mode: Dry Run",
        border_style="cyan",
    ))

    if result["results"]:
        table = Table(title="🔍 Discovered Tasks", border_style="blue")
        table.add_column("Source", style="bold")
        table.add_column("Studio", style="cyan")
        table.add_column("Priority", justify="right")
        table.add_column("Task")
        table.add_column("Reason", style="dim")

        for r in result["results"]:
            prio = r["priority"]
            prio_icon = "🔴" if prio >= 8 else "🟡" if prio >= 5 else "🔵"
            table.add_row(
                r["source"], r.get("studio", "-"),
                f"{prio_icon} {prio:.1f}",
                r["task"][:50], r.get("reason", "")[:40],
            )
        console.print(table)
    else:
        console.print("[dim]No tasks discovered. System is healthy.[/dim]")


@auto.command("run")
@click.option("-n", "--max-tasks", default=3, type=int, help="Max tasks to execute")
def auto_run(max_tasks: int) -> None:
    """Execute an autonomy cycle (real execution)."""
    from kernel.autonomy_engine import get_autonomy_engine

    engine = get_autonomy_engine()

    console.print("[bold yellow]🧠 Running autonomy cycle (LIVE)...[/bold yellow]")
    with console.status("[green]Discovering and executing tasks..."):
        result = engine.run_cycle(max_tasks=max_tasks, dry_run=False)

    console.print(Panel(
        f"[bold]🧠 Autonomy Cycle Complete[/bold]\n\n"
        f"  📋 Tasks Found: {result['tasks_found']}\n"
        f"  ✅ Executed: {result['tasks_executed']}\n"
        f"  📚 Learnings: {result['learnings']}",
        border_style="green" if result["tasks_executed"] > 0 else "dim",
    ))

    for r in result["results"]:
        icon = "✅" if r.get("success") else "❌"
        console.print(f"  {icon} [{r['source']}] {r['task'][:60]}")


@auto.command("status")
def auto_status() -> None:
    """Show autonomy engine status."""
    from kernel.autonomy_engine import get_autonomy_engine

    engine = get_autonomy_engine()
    status = engine.get_status()

    console.print(Panel(
        f"[bold]🧠 Autonomy Engine[/bold]\n\n"
        f"  📚 Learnings: {status['learnings']}\n"
        f"  📝 Agent Memories: {status['memory_stats']['total_memories']}\n"
        f"  📖 Knowledge Items: {status['memory_stats']['total_knowledge']}",
        border_style="cyan",
    ))

    if status["top_patterns"]:
        table = Table(title="📊 Top Patterns", border_style="yellow")
        table.add_column("Pattern")
        table.add_column("Studio")
        table.add_column("Confidence", justify="right")
        table.add_column("Count", justify="right")

        for p in status["top_patterns"]:
            table.add_row(
                p["pattern"], p["studio"],
                f"{p['confidence']:.2f}", str(p["count"]),
            )
        console.print(table)


@auto.command("learn")
def auto_learn() -> None:
    """View autonomy learnings."""
    from kernel.autonomy_engine import get_autonomy_engine

    engine = get_autonomy_engine()
    learnings = engine.get_learnings()

    if not learnings:
        console.print("[dim]No learnings yet. Run cycles to accumulate patterns.[/dim]")
        return

    table = Table(title="🧠 Autonomy Learnings", border_style="magenta")
    table.add_column("Pattern", style="bold")
    table.add_column("Outcome")
    table.add_column("Studio")
    table.add_column("Confidence", justify="right")
    table.add_column("Count", justify="right")

    for l in learnings:
        icon = "✅" if l["outcome"] == "success" else "❌"
        table.add_row(
            l["pattern"], f"{icon} {l['outcome']}",
            l["studio"], f"{l['confidence']:.2f}", str(l["count"]),
        )
    console.print(table)


# ── Learning ──────────────────────────────────────────────

@main.group()
def learn():
    """🧠 Mission learning — analyze past missions and extract insights."""
    pass


@learn.command("analyze")
@click.option("--limit", default=50, help="Number of recent missions to analyze")
def learn_analyze(limit: int) -> None:
    """🧠 Run learning analysis on completed missions."""
    from kernel.mission_learner import get_mission_learner

    learner = get_mission_learner()
    console.print(f"[bold]🧠 Analyzing last {limit} missions...[/bold]")

    learnings = learner.analyze_recent_missions(limit=limit)

    if not learnings:
        console.print("[yellow]No new learnings found.[/yellow]")
        return

    table = Table(title=f"📊 {len(learnings)} Insights Extracted")
    table.add_column("Category", style="cyan")
    table.add_column("Insight", style="white", max_width=60)
    table.add_column("Confidence", style="green")
    table.add_column("Action", style="yellow", max_width=40)

    for l in learnings:
        table.add_row(
            l.category,
            l.insight[:60],
            f"{l.confidence:.0%}",
            l.recommended_action[:40],
        )

    console.print(table)


@learn.command("show")
@click.option("--category", type=click.Choice(["model_perf", "studio_pattern", "failure"]), default=None)
@click.option("--limit", default=20)
def learn_show(category: str | None, limit: int) -> None:
    """📊 Show stored learnings."""
    from kernel.mission_learner import get_mission_learner

    learner = get_mission_learner()
    learnings = learner.get_learnings(category=category, limit=limit)

    if not learnings:
        console.print("[yellow]No learnings stored yet. Run `agency learn analyze` first.[/yellow]")
        return

    table = Table(title=f"🧠 Stored Learnings ({len(learnings)})")
    table.add_column("#", style="dim")
    table.add_column("Category", style="cyan")
    table.add_column("Insight", style="white", max_width=50)
    table.add_column("Conf.", style="green")
    table.add_column("Recommendation", style="yellow", max_width=40)

    for l in learnings:
        table.add_row(
            str(l.get("id", "")),
            l.get("category", ""),
            l.get("insight", "")[:50],
            f"{l.get('confidence', 0):.0%}",
            l.get("recommended_action", "")[:40],
        )

    console.print(table)


# ── Audit Trail ──────────────────────────────────────────────

@main.group()
def audit():
    """📋 Audit trail — AI call logging and cost tracking"""
    pass


@audit.command("summary")
@click.option("--days", default=1, help="Period in days")
def audit_summary(days: int):
    """Show AI usage summary."""
    from kernel.audit_trail import get_audit
    a = get_audit()
    s = a.get_summary(days)

    console.print(Panel.fit(
        f"📋 Calls: {s['total_calls']}  |  "
        f"🎯 Tokens: {s['total_tokens']:,}  |  "
        f"💰 Cost: ${s['total_cost_usd']:.4f}\n"
        f"⏱️  Avg Latency: {s['avg_latency_ms']:.0f}ms  |  "
        f"✅ Success: {s['success_rate']}%  |  "
        f"❌ Failures: {s['failures']}",
        title=f"Audit Summary ({days}d)",
    ))


@audit.command("costs")
@click.option("--days", default=1, help="Period in days")
@click.option("--by", type=click.Choice(["studio", "model"]), default="studio")
def audit_costs(days: int, by: str):
    """Show cost breakdown."""
    from kernel.audit_trail import get_audit
    a = get_audit()

    table = Table(title=f"Cost Breakdown by {by} ({days}d)")
    table.add_column(by.capitalize(), style="bold")
    table.add_column("Calls", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost (USD)", justify="right", style="green")

    rows = a.get_costs_by_studio(days) if by == "studio" else a.get_costs_by_model(days)
    for r in rows:
        key = r.get("studio", r.get("model", ""))
        table.add_row(key, str(r["calls"]), f"{r['tokens']:,}", f"${r['cost_usd']:.4f}")
    console.print(table)


@audit.command("recent")
@click.option("--limit", default=10, help="Number of entries")
def audit_recent(limit: int):
    """Show recent AI calls."""
    from kernel.audit_trail import get_audit
    a = get_audit()
    entries = a.get_recent(limit)

    table = Table(title=f"Recent AI Calls (last {limit})")
    table.add_column("Studio", style="cyan")
    table.add_column("Model")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right", style="green")
    table.add_column("Latency", justify="right")
    table.add_column("OK", justify="center")

    for e in entries:
        tokens = (e.get("tokens_in", 0) or 0) + (e.get("tokens_out", 0) or 0)
        ok = "✅" if e.get("success") else "❌"
        table.add_row(
            e.get("studio", ""), e.get("model", ""),
            f"{tokens:,}", f"${e.get('estimated_cost', 0):.4f}",
            f"{e.get('latency_ms', 0):.0f}ms", ok,
        )
    console.print(table)


@audit.command("export")
@click.option("--days", default=7, help="Period in days")
@click.option("--format", "fmt", type=click.Choice(["json", "csv"]), default="json")
@click.option("--output", "-o", default="", help="Output file path")
def audit_export(days: int, fmt: str, output: str):
    """Export audit log to JSON or CSV."""
    from kernel.audit_trail import get_audit
    a = get_audit()

    data = a.export_json(days) if fmt == "json" else a.export_csv(days)

    if output:
        with open(output, "w") as f:
            f.write(data)
        console.print(f"✅ Exported to {output}")
    else:
        console.print(data)


# ── Guardrails ───────────────────────────────────────────────

@main.group()
def guardrail():
    """🛡️ Guardrails — Budget limits, rate limits, content filters"""
    pass


@guardrail.command("status")
def guardrail_status():
    """Show guardrail status and usage."""
    from kernel.guardrails import get_guardrails
    g = get_guardrails()
    status = g.get_status()

    console.print(Panel.fit(
        f"🔍 Scopes tracked: {status['scopes_tracked']}\n"
        f"📊 Budgets configured: {status['budgets_configured']}",
        title="🛡️ Guardrails Status",
    ))

    if status["usage"]:
        table = Table(title="Usage by Scope")
        table.add_column("Scope", style="bold")
        table.add_column("Tokens", justify="right")
        table.add_column("Limit", justify="right")
        table.add_column("Used %", justify="right")
        table.add_column("Cost", justify="right", style="green")
        table.add_column("Requests", justify="right")

        for scope, u in status["usage"].items():
            pct = u["tokens_pct"]
            pct_style = "red" if pct > 80 else "yellow" if pct > 50 else "green"
            table.add_row(
                scope, f"{u['tokens_used']:,}", f"{u['tokens_limit']:,}",
                f"[{pct_style}]{pct}%[/]", f"${u['cost_usd']:.4f}",
                str(u["requests"]),
            )
        console.print(table)


@guardrail.command("set-budget")
@click.argument("scope")
@click.option("--tokens", type=int, help="Max tokens per day")
@click.option("--cost", type=float, help="Max cost USD per day")
@click.option("--rpm", type=int, help="Max requests per minute")
def guardrail_set_budget(scope: str, tokens: int, cost: float, rpm: int):
    """Set budget limits for a scope (studio name or 'global')."""
    from kernel.guardrails import get_guardrails
    g = get_guardrails()
    kwargs = {}
    if tokens:
        kwargs["max_tokens_per_day"] = tokens
    if cost:
        kwargs["max_cost_per_day"] = cost
    if rpm:
        kwargs["max_requests_per_minute"] = rpm
    g.set_budget(scope, **kwargs)
    console.print(f"✅ Budget updated for '{scope}': {kwargs}")


@guardrail.command("check")
@click.argument("text")
def guardrail_check(text: str):
    """Check text for PII or prompt injection."""
    from kernel.guardrails import get_guardrails
    g = get_guardrails()
    result = g.check_content(text)
    if result.allowed:
        console.print("✅ Content is clean")
    else:
        console.print(f"❌ Blocked: {result.reason}")
    for w in result.warnings:
        console.print(f"  {w}")


if __name__ == "__main__":
    main()
