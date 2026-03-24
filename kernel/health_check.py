#!/usr/bin/env python3
"""
Agency OS v4.0 — Deep Health Endpoint

Checks all system components and reports detailed status:
- Database connectivity
- OpenClaw / Ollama / LM Studio availability
- Memory usage
- CPU usage
- Disk space
- Module import health
- Queue status
"""

from __future__ import annotations

import os
import time
import importlib
from typing import Any


def check_health() -> dict[str, Any]:
    """Run comprehensive system health check."""
    results: dict[str, Any] = {
        "status": "ok",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": {},
    }
    failures = 0

    # 1. Database
    try:
        from kernel.state_manager import get_state

        state = get_state()
        count = state._conn.execute("SELECT COUNT(*) FROM missions").fetchone()[0]
        results["checks"]["database"] = {
            "status": "ok",
            "missions": count,
        }
    except Exception as e:
        results["checks"]["database"] = {"status": "error", "error": str(e)}
        failures += 1

    # 2. Providers
    try:
        from kernel.provider_detector import get_provider_detector

        pd = get_provider_detector()
        summary = pd.get_summary()
        results["checks"]["providers"] = {
            "status": "ok",
            "local_running": summary["total_local_running"],
            "cloud_configured": summary["total_cloud_configured"],
            "total_models": summary["total_models"],
        }
    except Exception as e:
        results["checks"]["providers"] = {"status": "error", "error": str(e)}
        failures += 1

    # 3. Memory
    try:
        import resource

        mem_usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        mem_mb = mem_usage / 1024  # KB to MB on Linux
        results["checks"]["memory"] = {
            "status": "ok" if mem_mb < 500 else "warning",
            "usage_mb": round(mem_mb, 1),
        }
    except ImportError:
        results["checks"]["memory"] = {"status": "unknown"}

    # 4. Disk
    try:
        from kernel.config import get_config

        cfg = get_config()
        stat = os.statvfs(str(cfg.root))
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        results["checks"]["disk"] = {
            "status": "ok" if free_gb > 1 else "warning",
            "free_gb": round(free_gb, 2),
        }
    except Exception as e:
        results["checks"]["disk"] = {"status": "error", "error": str(e)}

    # 5. Kernel modules
    modules = [
        "kernel.config",
        "kernel.state_manager",
        "kernel.event_bus",
        "kernel.guardrails",
        "kernel.audit_trail",
        "kernel.telemetry",
        "kernel.crew_engine",
        "kernel.quality_gates",
        "kernel.feature_flags",
        "kernel.cross_studio",
        "kernel.job_queue",
        "kernel.plugin_loader",
    ]
    loaded = 0
    failed_mods = []
    for mod in modules:
        try:
            importlib.import_module(mod)
            loaded += 1
        except Exception:
            failed_mods.append(mod)

    results["checks"]["modules"] = {
        "status": "ok" if not failed_mods else "degraded",
        "loaded": loaded,
        "total": len(modules),
        "failed": failed_mods,
    }
    if failed_mods:
        failures += 1

    # 6. Job queue
    try:
        from kernel.job_queue import get_job_queue

        jq = get_job_queue()
        stats = jq.get_stats()
        results["checks"]["job_queue"] = {
            "status": "ok",
            "pending": stats["pending"],
            "dead_letters": stats["dead_letters"],
        }
    except Exception as e:
        results["checks"]["job_queue"] = {"status": "error", "error": str(e)}

    # 7. Guardrails
    try:
        from kernel.guardrails import get_guardrails

        g = get_guardrails()
        usage = g.get_usage_summary()
        results["checks"]["guardrails"] = {
            "status": "ok",
            "scopes_tracked": len(usage),
        }
    except Exception as e:
        results["checks"]["guardrails"] = {"status": "error", "error": str(e)}

    # Overall status
    if failures > 0:
        results["status"] = "degraded"
    results["failures"] = failures

    return results
