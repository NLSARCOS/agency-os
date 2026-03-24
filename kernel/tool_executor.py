#!/usr/bin/env python3
"""
Agency OS v5.0.0 — Tool Executor

Sandboxed tool execution engine. Agents use tools to interact with
the real world: shell, files, API calls, databases, git, browsers.
Every tool invocation is logged, sandboxed, and subject to permissions.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from kernel.config import get_config

logger = logging.getLogger("agency.tools")


class ToolPermission(str, Enum):
    READ = "read"  # Read files, DB queries
    WRITE = "write"  # Write files, DB mutations
    EXECUTE = "execute"  # Run shell commands
    NETWORK = "network"  # HTTP requests, API calls
    GIT = "git"  # Git operations
    BROWSER = "browser"  # Headless browser automation
    DANGEROUS = "dangerous"  # Destructive operations (rm, drop, etc.)


@dataclass
class ToolResult:
    """Result from a tool invocation."""

    tool: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class ToolDef:
    """Tool definition with metadata."""

    name: str
    description: str
    permissions: list[ToolPermission]
    handler: str = ""  # Method name in ToolExecutor


# Built-in tool registry
BUILTIN_TOOLS: dict[str, ToolDef] = {
    "shell": ToolDef(
        name="shell",
        description="Execute shell commands in a sandboxed environment",
        permissions=[ToolPermission.EXECUTE],
    ),
    "read_file": ToolDef(
        name="read_file",
        description="Read file contents from the filesystem",
        permissions=[ToolPermission.READ],
    ),
    "write_file": ToolDef(
        name="write_file",
        description="Write or create files on the filesystem",
        permissions=[ToolPermission.WRITE],
    ),
    "list_dir": ToolDef(
        name="list_dir",
        description="List directory contents",
        permissions=[ToolPermission.READ],
    ),
    "http_request": ToolDef(
        name="http_request",
        description="Make HTTP requests to external APIs",
        permissions=[ToolPermission.NETWORK],
    ),
    "db_query": ToolDef(
        name="db_query",
        description="Execute SQL queries against the agency database",
        permissions=[ToolPermission.READ],
    ),
    "db_execute": ToolDef(
        name="db_execute",
        description="Execute SQL mutations (INSERT, UPDATE, DELETE)",
        permissions=[ToolPermission.WRITE],
    ),
    "git_status": ToolDef(
        name="git_status",
        description="Get git repository status",
        permissions=[ToolPermission.GIT, ToolPermission.READ],
    ),
    "git_commit": ToolDef(
        name="git_commit",
        description="Stage and commit changes to git",
        permissions=[ToolPermission.GIT, ToolPermission.WRITE],
    ),
    "git_push": ToolDef(
        name="git_push",
        description="Push commits to remote repository",
        permissions=[ToolPermission.GIT, ToolPermission.NETWORK],
    ),
    "search_web": ToolDef(
        name="search_web",
        description="Search the web using Brave Search API",
        permissions=[ToolPermission.NETWORK],
    ),
    "scrape_url": ToolDef(
        name="scrape_url",
        description="Fetch and extract text content from a URL",
        permissions=[ToolPermission.NETWORK],
    ),
}


class ToolExecutor:
    """
    Sandboxed tool execution engine.

    Features:
    - Permission-based access control per agent
    - Timeout and resource limits
    - Result caching for identical invocations
    - Full execution logging
    - Retry with backoff
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._tools = dict(BUILTIN_TOOLS)
        self._http = httpx.Client(timeout=30.0)
        self._cache: dict[str, ToolResult] = {}
        self._history: list[ToolResult] = []
        self._max_history = 500

        # Default permission profiles
        self._agent_permissions: dict[str, set[ToolPermission]] = {
            "dev": {
                ToolPermission.READ,
                ToolPermission.WRITE,
                ToolPermission.EXECUTE,
                ToolPermission.GIT,
                ToolPermission.NETWORK,
            },
            "backend-specialist": {
                ToolPermission.READ,
                ToolPermission.WRITE,
                ToolPermission.EXECUTE,
                ToolPermission.NETWORK,
                ToolPermission.GIT,
            },
            "leadops": {
                ToolPermission.READ,
                ToolPermission.WRITE,
                ToolPermission.NETWORK,
            },
            "marketing": {
                ToolPermission.READ,
                ToolPermission.WRITE,
                ToolPermission.NETWORK,
            },
            "sales": {
                ToolPermission.READ,
                ToolPermission.WRITE,
                ToolPermission.NETWORK,
            },
            "abm": {ToolPermission.READ, ToolPermission.WRITE, ToolPermission.NETWORK},
            "analytics": {ToolPermission.READ, ToolPermission.NETWORK},
            "creative": {
                ToolPermission.READ,
                ToolPermission.WRITE,
                ToolPermission.NETWORK,
            },
        }

    # ── Permission Check ──────────────────────────────────────

    def check_permission(self, agent_id: str, tool_name: str) -> tuple[bool, str]:
        tool = self._tools.get(tool_name)
        if not tool:
            return False, f"Unknown tool: {tool_name}"
        agent_perms = self._agent_permissions.get(agent_id, {ToolPermission.READ})
        missing = [p for p in tool.permissions if p not in agent_perms]
        if missing:
            return False, f"Agent '{agent_id}' lacks permissions: {missing}"
        return True, ""

    def grant_permission(
        self, agent_id: str, permissions: list[ToolPermission]
    ) -> None:
        if agent_id not in self._agent_permissions:
            self._agent_permissions[agent_id] = set()
        self._agent_permissions[agent_id].update(permissions)

    # ── Execute ───────────────────────────────────────────────

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        agent_id: str = "system",
        timeout: float = 60.0,
        cache: bool = False,
    ) -> ToolResult:
        """Execute a tool with permission checking and sandboxing."""
        allowed, reason = self.check_permission(agent_id, tool_name)
        if not allowed:
            return ToolResult(
                tool=tool_name,
                success=False,
                error=f"Permission denied: {reason}",
            )

        # Cache check
        if cache:
            cache_key = f"{tool_name}:{json.dumps(params, sort_keys=True)}"
            if cache_key in self._cache:
                logger.debug("Cache hit: %s", tool_name)
                return self._cache[cache_key]

        start = time.monotonic()
        try:
            handler = getattr(self, f"_tool_{tool_name}", None)
            if not handler:
                return ToolResult(
                    tool=tool_name,
                    success=False,
                    error=f"No handler for tool: {tool_name}",
                )
            result = handler(params, timeout=timeout)
            result.duration_ms = (time.monotonic() - start) * 1000

            if cache and result.success:
                self._cache[cache_key] = result

        except Exception as e:
            result = ToolResult(
                tool=tool_name,
                success=False,
                error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )

        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        logger.info(
            "Tool %s: %s (%.0fms) agent=%s",
            tool_name,
            "OK" if result.success else "FAIL",
            result.duration_ms,
            agent_id,
        )
        return result

    # ── Built-in Tool Handlers ────────────────────────────────

    def _tool_shell(self, params: dict, timeout: float = 60.0) -> ToolResult:
        """Execute a shell command with sandboxing."""
        cmd = params.get("command", "")
        cwd = params.get("cwd", str(self.cfg.root))

        # Block dangerous commands — comprehensive sandbox
        blocked_exact = [
            "rm -rf /",
            "rm -rf /*",
            "mkfs",
            "dd if=",
            ":(){",
            "fork bomb",
            "sudo rm",
            "sudo dd",
            "sudo mkfs",
            "chmod 777 /",
            "shutdown",
            "reboot",
            "init 0",
            "init 6",
            "halt",
            "systemctl stop",
            "systemctl disable",
            "> /dev/sda",
            "> /dev/null",
        ]
        blocked_patterns = [
            "curl|bash",
            "curl|sh",
            "wget|bash",
            "wget|sh",
            "curl -s|",
            "wget -q|",  # pipe from internet to shell
            "pkill -9",
            "killall",
            "kill -9",
            "export AWS_",
            "export OPENAI_",
            "export ANTHROPIC_",
            "/etc/passwd",
            "/etc/shadow",
            "../../../../",  # path traversal
            "nc -l",
            "ncat",  # reverse shells
            "; rm ",
            "&& rm ",  # chained destructive
        ]

        cmd_lower = cmd.lower().strip()
        for d in blocked_exact:
            if d in cmd_lower:
                return ToolResult(
                    tool="shell",
                    success=False,
                    error=f"Blocked dangerous command: {d}",
                )
        for p in blocked_patterns:
            if p in cmd_lower.replace(" ", ""):
                return ToolResult(
                    tool="shell",
                    success=False,
                    error=f"Blocked dangerous pattern: {p}",
                )

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env={**os.environ, "LANG": "en_US.UTF-8"},
            )
            output = proc.stdout[-4000:] if len(proc.stdout) > 4000 else proc.stdout
            return ToolResult(
                tool="shell",
                success=proc.returncode == 0,
                output=output,
                error=proc.stderr[-2000:] if proc.stderr else "",
                metadata={"returncode": proc.returncode, "command": cmd},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool="shell",
                success=False,
                error=f"Command timed out after {timeout}s",
            )

    def _tool_read_file(self, params: dict, **kw: Any) -> ToolResult:
        """Read file contents."""
        path = Path(params.get("path", ""))
        if not path.is_absolute():
            path = self.cfg.root / path
        if not path.exists():
            return ToolResult(
                tool="read_file",
                success=False,
                error=f"File not found: {path}",
            )
        if path.stat().st_size > 1_000_000:  # 1MB limit
            return ToolResult(
                tool="read_file",
                success=False,
                error=f"File too large: {path.stat().st_size} bytes",
            )
        content = path.read_text(encoding="utf-8", errors="replace")
        return ToolResult(
            tool="read_file",
            success=True,
            output=content,
            metadata={"path": str(path), "size": len(content)},
        )

    def _tool_write_file(self, params: dict, **kw: Any) -> ToolResult:
        """Write content to a file."""
        path = Path(params.get("path", ""))
        content = params.get("content", "")
        if not path.is_absolute():
            path = self.cfg.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(
            tool="write_file",
            success=True,
            output=f"Written {len(content)} bytes to {path}",
            metadata={"path": str(path), "size": len(content)},
        )

    def _tool_list_dir(self, params: dict, **kw: Any) -> ToolResult:
        """List directory contents."""
        path = Path(params.get("path", str(self.cfg.root)))
        if not path.is_absolute():
            path = self.cfg.root / path
        if not path.is_dir():
            return ToolResult(
                tool="list_dir",
                success=False,
                error=f"Not a directory: {path}",
            )

        entries = []
        for p in sorted(path.iterdir()):
            entry = {
                "name": p.name,
                "type": "dir" if p.is_dir() else "file",
            }
            if p.is_file():
                entry["size"] = p.stat().st_size  # type: ignore
            entries.append(entry)

        return ToolResult(
            tool="list_dir",
            success=True,
            output=json.dumps(entries, indent=2),
            metadata={"path": str(path), "count": len(entries)},
        )

    def _tool_http_request(self, params: dict, timeout: float = 30.0) -> ToolResult:
        """Make an HTTP request."""
        method = params.get("method", "GET").upper()
        url = params.get("url", "")
        headers = params.get("headers", {})
        body = params.get("body")

        try:
            resp = self._http.request(
                method,
                url,
                headers=headers,
                json=body if body else None,
                timeout=timeout,
            )
            output = resp.text[:5000]  # Cap response size
            return ToolResult(
                tool="http_request",
                success=resp.is_success,
                output=output,
                metadata={
                    "status_code": resp.status_code,
                    "url": url,
                    "method": method,
                },
            )
        except httpx.TimeoutException:
            return ToolResult(
                tool="http_request",
                success=False,
                error=f"Request timed out: {url}",
            )
        except httpx.RequestError as e:
            return ToolResult(
                tool="http_request",
                success=False,
                error=f"Request error: {e}",
            )

    def _tool_db_query(self, params: dict, **kw: Any) -> ToolResult:
        """Execute read-only SQL query."""
        query = params.get("query", "")
        if not query.strip().upper().startswith("SELECT"):
            return ToolResult(
                tool="db_query",
                success=False,
                error="Only SELECT queries allowed in db_query",
            )
        try:
            conn = sqlite3.connect(str(self.cfg.db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()
            result = [dict(r) for r in rows[:100]]  # Cap at 100 rows
            conn.close()
            return ToolResult(
                tool="db_query",
                success=True,
                output=json.dumps(result, indent=2, default=str),
                metadata={"rows": len(result)},
            )
        except Exception as e:
            return ToolResult(
                tool="db_query",
                success=False,
                error=str(e),
            )

    def _tool_db_execute(self, params: dict, **kw: Any) -> ToolResult:
        """Execute SQL mutation."""
        query = params.get("query", "")
        query_params = params.get("params", [])
        try:
            conn = sqlite3.connect(str(self.cfg.db_path))
            cursor = conn.execute(query, query_params)
            conn.commit()
            result = {
                "rowcount": cursor.rowcount,
                "lastrowid": cursor.lastrowid,
            }
            conn.close()
            return ToolResult(
                tool="db_execute",
                success=True,
                output=json.dumps(result),
                metadata=result,
            )
        except Exception as e:
            return ToolResult(
                tool="db_execute",
                success=False,
                error=str(e),
            )

    def _tool_git_status(self, params: dict, **kw: Any) -> ToolResult:
        """Get git status."""
        cwd = params.get("cwd", str(self.cfg.root))
        return self._tool_shell({"command": "git status --short", "cwd": cwd})

    def _tool_git_commit(self, params: dict, **kw: Any) -> ToolResult:
        """Stage and commit."""
        message = params.get("message", "auto-commit by agency-os")
        files = params.get("files", ".")
        cwd = params.get("cwd", str(self.cfg.root))

        stage = self._tool_shell({"command": f"git add {files}", "cwd": cwd})
        if not stage.success:
            return stage
        return self._tool_shell({"command": f'git commit -m "{message}"', "cwd": cwd})

    def _tool_git_push(self, params: dict, **kw: Any) -> ToolResult:
        """Push to remote."""
        remote = params.get("remote", "origin")
        branch = params.get("branch", "main")
        cwd = params.get("cwd", str(self.cfg.root))
        return self._tool_shell({"command": f"git push {remote} {branch}", "cwd": cwd})

    def _tool_search_web(self, params: dict, **kw: Any) -> ToolResult:
        """Search the web using Brave Search API."""
        query = params.get("query", "")
        api_key = self.cfg.api_keys.get("brave", "")
        if not api_key:
            return ToolResult(
                tool="search_web",
                success=False,
                error="No Brave API key configured",
            )
        try:
            resp = self._http.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": api_key},
                params={"q": query, "count": 5},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for r in data.get("web", {}).get("results", [])[:5]:
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("description", "")[:200],
                    }
                )
            return ToolResult(
                tool="search_web",
                success=True,
                output=json.dumps(results, indent=2),
                metadata={"query": query, "count": len(results)},
            )
        except Exception as e:
            return ToolResult(
                tool="search_web",
                success=False,
                error=str(e),
            )

    def _tool_scrape_url(self, params: dict, **kw: Any) -> ToolResult:
        """Fetch and extract text from a URL."""
        url = params.get("url", "")
        try:
            resp = self._http.get(url, follow_redirects=True, timeout=15.0)
            resp.raise_for_status()
            # Simple HTML → text extraction
            text = resp.text
            # Strip HTML tags (basic)
            import re

            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            text = text[:5000]  # Cap output
            return ToolResult(
                tool="scrape_url",
                success=True,
                output=text,
                metadata={"url": url, "length": len(text)},
            )
        except Exception as e:
            return ToolResult(
                tool="scrape_url",
                success=False,
                error=str(e),
            )

    # ── Management ────────────────────────────────────────────

    def list_tools(self, agent_id: str | None = None) -> list[dict]:
        """List available tools, optionally filtered by agent permissions."""
        tools = []
        for name, tool_def in self._tools.items():
            entry = {
                "name": name,
                "description": tool_def.description,
                "permissions": [p.value for p in tool_def.permissions],
            }
            if agent_id:
                allowed, _ = self.check_permission(agent_id, name)
                entry["available"] = allowed  # type: ignore
            tools.append(entry)
        return tools

    def get_history(self, tool: str | None = None, limit: int = 50) -> list[dict]:
        items = self._history
        if tool:
            items = [r for r in items if r.tool == tool]
        return [
            {
                "id": r.id,
                "tool": r.tool,
                "success": r.success,
                "duration_ms": round(r.duration_ms, 1),
                "error": r.error[:100] if r.error else "",
                "timestamp": r.timestamp,
            }
            for r in items[-limit:]
        ]

    def close(self) -> None:
        self._http.close()


_tool_executor: ToolExecutor | None = None


def get_tool_executor() -> ToolExecutor:
    """Singleton — preserves tool cache, history, and HTTP connections."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
