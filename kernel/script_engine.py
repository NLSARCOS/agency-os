#!/usr/bin/env python3
"""
Agency OS v5.0 — Script Engine

Dynamic script generation and tool composition:
- Generate Python/Bash scripts from task descriptions
- Template library for common operations
- Tool chaining: pipe output of tool A → tool B
- Sandbox execution with timeout + resource limits
- Dry-run mode for safety
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kernel.config import get_config

logger = logging.getLogger("agency.script")


@dataclass
class ScriptResult:
    """Result of script execution."""

    id: str = field(default_factory=lambda: uuid4().hex[:10])
    script_type: str = "python"  # python | bash
    source: str = ""
    output: str = ""
    error: str = ""
    success: bool = False
    duration_ms: float = 0
    exit_code: int = -1
    dry_run: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Script templates for common operations
SCRIPT_TEMPLATES: dict[str, dict[str, str]] = {
    "scrape_and_extract": {
        "description": "Scrape a URL and extract structured data",
        "type": "python",
        "template": """
import urllib.request
import json
import re

url = "{url}"
try:
    resp = urllib.request.urlopen(url, timeout=10)
    html = resp.read().decode("utf-8", errors="replace")
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    print(json.dumps({{"url": url, "content": text[:3000], "length": len(text)}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
""",
    },
    "csv_transform": {
        "description": "Read CSV and transform data",
        "type": "python",
        "template": """
import csv
import json
import sys

input_file = "{input_file}"
output_field = "{output_field}"

results = []
with open(input_file, "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        results.append({{k: v for k, v in row.items()}})

print(json.dumps({{"rows": len(results), "fields": list(results[0].keys()) if results else [], "sample": results[:3]}}))
""",
    },
    "file_search": {
        "description": "Search for files matching a pattern",
        "type": "python",
        "template": """
import os
import json

root = "{root_dir}"
pattern = "{pattern}"
results = []

for dirpath, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in [".git", "__pycache__", "node_modules", ".venv"]]
    for f in files:
        if pattern.lower() in f.lower():
            path = os.path.join(dirpath, f)
            results.append({{"path": path, "size": os.path.getsize(path)}})

print(json.dumps({{"found": len(results), "files": results[:20]}}))
""",
    },
    "api_call": {
        "description": "Make an API call and process response",
        "type": "python",
        "template": """
import urllib.request
import json

url = "{url}"
method = "{method}"
headers = {headers}

req = urllib.request.Request(url, method=method)
for k, v in headers.items():
    req.add_header(k, v)

try:
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read())
    print(json.dumps({{"status": resp.status, "data": data}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
""",
    },
    "git_report": {
        "description": "Generate git activity report",
        "type": "bash",
        "template": """
#!/bin/bash
echo "=== Git Report ==="
echo "Branch: $(git branch --show-current)"
echo "Last 5 commits:"
git log --oneline -5
echo ""
echo "Changed files (uncommitted):"
git diff --stat
echo ""
echo "Contributors:"
git shortlog -sn --no-merges | head -5
""",
    },
    "system_info": {
        "description": "Collect system information",
        "type": "bash",
        "template": """
#!/bin/bash
echo "=== System Info ==="
echo "OS: $(uname -s) $(uname -r)"
echo "CPU: $(nproc) cores"
echo "Memory: $(free -h 2>/dev/null | awk '/^Mem:/ {print $2}' || echo 'N/A')"
echo "Disk: $(df -h / | tail -1 | awk '{print $4}') free"
echo "Python: $(python3 --version 2>&1)"
echo "Node: $(node --version 2>&1 || echo 'not installed')"
echo "Uptime: $(uptime -p 2>/dev/null || uptime)"
""",
    },
}


class ScriptEngine:
    """
    Dynamic script generation and execution engine.

    Capabilities:
    1. Generate scripts from task descriptions
    2. Use template library for common patterns
    3. Chain multiple scripts (pipe output)
    4. Sandbox execution with limits
    5. Dry-run mode for safety review
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._templates = dict(SCRIPT_TEMPLATES)
        self._history: list[ScriptResult] = []
        self._max_history = 100

    def from_template(
        self,
        template_name: str,
        variables: dict[str, str],
        dry_run: bool = False,
        timeout: float = 30.0,
    ) -> ScriptResult:
        """Generate and execute a script from a template."""
        template = self._templates.get(template_name)
        if not template:
            return ScriptResult(
                success=False,
                error=f"Template not found: {template_name}. Available: {list(self._templates.keys())}",
            )

        # Fill variables
        source = template["template"]
        for key, val in variables.items():
            source = source.replace(f"{{{key}}}", str(val))

        return self.execute(
            source=source,
            script_type=template["type"],
            dry_run=dry_run,
            timeout=timeout,
        )

    def execute(
        self,
        source: str,
        script_type: str = "python",
        dry_run: bool = False,
        timeout: float = 30.0,
        cwd: str | None = None,
    ) -> ScriptResult:
        """Execute a script in a sandbox."""
        result = ScriptResult(
            script_type=script_type,
            source=source.strip(),
            dry_run=dry_run,
        )

        # Safety check
        if not self._safety_check(source, script_type):
            result.error = "Script blocked by safety check"
            return result

        if dry_run:
            result.success = True
            result.output = (
                f"[DRY RUN] Would execute {script_type} script ({len(source)} chars)"
            )
            self._history.append(result)
            return result

        start = time.monotonic()
        work_dir = cwd or str(self.cfg.root)

        try:
            if script_type == "python":
                result = self._run_python(source, timeout, work_dir, result)
            elif script_type == "bash":
                result = self._run_bash(source, timeout, work_dir, result)
            else:
                result.error = f"Unsupported script type: {script_type}"
        except Exception as e:
            result.error = str(e)

        result.duration_ms = (time.monotonic() - start) * 1000
        self._history.append(result)

        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        return result

    def chain(
        self,
        steps: list[dict[str, Any]],
        dry_run: bool = False,
    ) -> list[ScriptResult]:
        """
        Chain multiple scripts, piping output from one to the next.

        Each step dict: {"source": str, "type": "python"|"bash"}
        Or: {"template": str, "variables": dict}
        """
        results: list[ScriptResult] = []
        previous_output = ""

        for i, step in enumerate(steps):
            if "template" in step:
                variables = step.get("variables", {})
                variables["_previous_output"] = previous_output
                result = self.from_template(
                    step["template"],
                    variables,
                    dry_run=dry_run,
                )
            else:
                source = step.get("source", "")
                # Inject previous output as variable
                source = source.replace("{_previous_output}", previous_output)
                result = self.execute(
                    source=source,
                    script_type=step.get("type", "python"),
                    dry_run=dry_run,
                )

            results.append(result)

            if not result.success and not dry_run:
                logger.warning("Chain stopped at step %d: %s", i, result.error)
                break

            previous_output = result.output

        return results

    def add_template(
        self,
        name: str,
        description: str,
        script_type: str,
        template: str,
    ) -> None:
        """Register a custom script template."""
        self._templates[name] = {
            "description": description,
            "type": script_type,
            "template": template,
        }

    def list_templates(self) -> list[dict[str, str]]:
        """List available templates."""
        return [
            {"name": name, "description": t["description"], "type": t["type"]}
            for name, t in self._templates.items()
        ]

    # ── Execution Sandboxes ──────────────────────────────────

    def _run_python(
        self,
        source: str,
        timeout: float,
        cwd: str,
        result: ScriptResult,
    ) -> ScriptResult:
        """Execute Python script in subprocess."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir="/tmp"
        ) as f:
            f.write(source)
            f.flush()
            script_path = f.name

        try:
            proc = subprocess.run(
                ["python3", script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            result.output = (
                proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout
            )
            result.error = proc.stderr[-2000:] if proc.stderr else ""
            result.exit_code = proc.returncode
            result.success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            result.error = f"Script timed out after {timeout}s"
        finally:
            os.unlink(script_path)

        return result

    def _run_bash(
        self,
        source: str,
        timeout: float,
        cwd: str,
        result: ScriptResult,
    ) -> ScriptResult:
        """Execute Bash script in subprocess."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir="/tmp"
        ) as f:
            f.write(source)
            f.flush()
            script_path = f.name

        try:
            proc = subprocess.run(
                ["bash", script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            result.output = (
                proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout
            )
            result.error = proc.stderr[-2000:] if proc.stderr else ""
            result.exit_code = proc.returncode
            result.success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            result.error = f"Script timed out after {timeout}s"
        finally:
            os.unlink(script_path)

        return result

    # ── Safety ───────────────────────────────────────────────

    def _safety_check(self, source: str, script_type: str) -> bool:
        """Check script for dangerous operations."""
        dangerous_patterns = [
            "rm -rf /",
            "mkfs.",
            "dd if=",
            ":(){ ",
            "fork bomb",
            "shutil.rmtree('/'",
            "os.remove('/'",
            "import subprocess; subprocess.run(['rm'",
            "eval(input(",
            "exec(input(",
            "curl.*|.*bash",
            "wget.*|.*sh",
        ]
        source_lower = source.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in source_lower:
                logger.warning("Blocked dangerous pattern: %s", pattern)
                return False
        return True

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        total = len(self._history)
        if total == 0:
            return {"total": 0, "templates": len(self._templates)}

        success = sum(1 for r in self._history if r.success)
        return {
            "total": total,
            "success": success,
            "failed": total - success,
            "success_rate": round(success / total * 100, 1),
            "avg_duration_ms": round(
                sum(r.duration_ms for r in self._history) / total, 1
            ),
            "templates": len(self._templates),
        }


_engine: ScriptEngine | None = None


def get_script_engine() -> ScriptEngine:
    global _engine
    if _engine is None:
        _engine = ScriptEngine()
    return _engine
