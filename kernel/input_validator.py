#!/usr/bin/env python3
"""
Agency OS v5.0 — Input Validator

Production-safe input handling:
- Per-studio input schemas with required fields
- Rate limiting per source/channel
- Content sanitization
- Shell command whitelist (not blacklist!)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("agency.validator")


@dataclass
class ValidationResult:
    """Result of input validation."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sanitized_input: str = ""
    original_input: str = ""


# Per-studio input schemas
STUDIO_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "dev": {
        "min_length": 5,
        "max_length": 10000,
        "required_context": [],
        "forbidden_patterns": [],
        "description": "Development tasks: code, build, fix, deploy",
    },
    "marketing": {
        "min_length": 10,
        "max_length": 5000,
        "required_context": [],
        "forbidden_patterns": [],
        "description": "Marketing tasks: campaigns, content, SEO",
    },
    "sales": {
        "min_length": 10,
        "max_length": 5000,
        "required_context": [],
        "forbidden_patterns": [],
        "description": "Sales tasks: outreach, follow-up, proposals",
    },
    "leadops": {
        "min_length": 5,
        "max_length": 5000,
        "required_context": [],
        "forbidden_patterns": [],
        "description": "Lead operations: scraping, enrichment, scoring",
    },
    "analytics": {
        "min_length": 5,
        "max_length": 8000,
        "required_context": [],
        "forbidden_patterns": [],
        "description": "Analytics: reports, metrics, insights",
    },
    "creative": {
        "min_length": 10,
        "max_length": 5000,
        "required_context": [],
        "forbidden_patterns": [],
        "description": "Creative: design, branding, visual",
    },
    "abm": {
        "min_length": 10,
        "max_length": 5000,
        "required_context": [],
        "forbidden_patterns": [],
        "description": "ABM: account targeting, personalization",
    },
}

# Shell command whitelist (SAFE commands only)
SHELL_WHITELIST: set[str] = {
    # Read-only
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "find",
    "which",
    "whoami",
    "pwd",
    "echo",
    "date",
    "uname",
    "df",
    "du",
    "free",
    "uptime",
    "env",
    "printenv",
    "file",
    "stat",
    "tree",
    "less",
    "more",
    "sort",
    "uniq",
    "cut",
    "awk",
    "sed",
    "tr",
    "diff",
    "comm",
    # Git (read)
    "git status",
    "git log",
    "git branch",
    "git diff",
    "git show",
    "git shortlog",
    "git remote",
    "git tag",
    # Git (write — controlled)
    "git add",
    "git commit",
    "git push",
    "git pull",
    "git checkout",
    "git merge",
    "git stash",
    # Python/Node
    "python3",
    "python",
    "pip",
    "pip3",
    "node",
    "npm",
    "npx",
    # Safe system
    "curl",
    "wget",
    "ping",
    "nslookup",
    "dig",
    "mkdir",
    "touch",
    "cp",
    "mv",
    # Project tools
    "pytest",
    "ruff",
    "black",
    "mypy",
    "flake8",
}

# Explicitly blocked patterns (even within whitelisted commands)
BLOCKED_PATTERNS: list[str] = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){",
    "fork bomb",
    "> /dev/sda",
    "chmod 777 /",
    "sudo rm",
    "| bash",
    "| sh",
    "eval(",
    "exec(",
    "__import__(",
    "os.system(",
    "subprocess.call(",
]


class InputValidator:
    """
    Production-safe input validation and sanitization.

    Features:
    - Per-studio schema validation
    - Rate limiting per source
    - Command whitelist (not blacklist)
    - Content sanitization
    """

    def __init__(self) -> None:
        self._schemas = dict(STUDIO_INPUT_SCHEMAS)
        self._rate_limits: dict[str, list[float]] = {}
        self._rate_window = 60.0  # seconds
        self._rate_max = 30  # max requests per window

    def validate(
        self,
        task: str,
        studio: str = "",
        source: str = "cli",
    ) -> ValidationResult:
        """Validate task input against studio schema."""
        result = ValidationResult(
            original_input=task,
            sanitized_input=task,
        )

        # Rate limiting
        if not self._check_rate(source):
            result.valid = False
            result.errors.append(
                f"Rate limit exceeded for source '{source}' "
                f"({self._rate_max} requests per {self._rate_window}s)"
            )
            return result

        # Basic validation
        if not task or not task.strip():
            result.valid = False
            result.errors.append("Task cannot be empty")
            return result

        # Sanitize
        result.sanitized_input = self._sanitize(task)

        # Schema validation
        schema = self._schemas.get(studio)
        if schema:
            if len(task) < schema["min_length"]:
                result.valid = False
                result.errors.append(
                    f"Task too short (min {schema['min_length']} chars)"
                )
            if len(task) > schema["max_length"]:
                result.valid = False
                result.errors.append(
                    f"Task too long (max {schema['max_length']} chars)"
                )

        # Check for blocked patterns
        task_lower = task.lower()
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in task_lower:
                result.valid = False
                result.errors.append(f"Blocked pattern detected: '{pattern}'")

        # Injection detection
        injection_patterns = [
            r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|above|prior)\s+instructions",
            r"you\s+are\s+now\s+(?:a|an)\s+",
            r"system:\s*",
            r"<\|(?:im_(?:start|end)|system)\|>",
        ]
        for pattern in injection_patterns:
            if re.search(pattern, task_lower):
                result.valid = False
                result.errors.append("Potential prompt injection detected")
                break

        return result

    def validate_shell_command(self, command: str) -> ValidationResult:
        """Validate a shell command against the whitelist."""
        result = ValidationResult(
            original_input=command,
            sanitized_input=command,
        )

        # Check blocked patterns first
        cmd_lower = command.lower().strip()
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in cmd_lower:
                result.valid = False
                result.errors.append(f"Blocked: '{pattern}'")
                return result

        # Check whitelist
        first_cmd = cmd_lower.split()[0] if cmd_lower.split() else ""
        # Also check two-word commands like "git status"
        two_word = (
            " ".join(cmd_lower.split()[:2]) if len(cmd_lower.split()) >= 2 else ""
        )

        if first_cmd not in SHELL_WHITELIST and two_word not in SHELL_WHITELIST:
            result.valid = False
            result.errors.append(
                f"Command '{first_cmd}' not in whitelist. "
                f"Allowed: {sorted(list(SHELL_WHITELIST))[:10]}..."
            )
            result.warnings.append(
                "Use validate_shell_command() to check before execution"
            )

        # Pipe chain validation
        if "|" in command:
            parts = [p.strip() for p in command.split("|")]
            for part in parts:
                sub_cmd = part.split()[0] if part.split() else ""
                if sub_cmd not in SHELL_WHITELIST:
                    result.warnings.append(
                        f"Piped command '{sub_cmd}' not in whitelist"
                    )

        return result

    def _sanitize(self, text: str) -> str:
        """Sanitize input text."""
        # Remove null bytes
        text = text.replace("\x00", "")
        # Remove ANSI escape codes
        text = re.sub(r"\x1b\[[0-9;]*[mK]", "", text)
        # Normalize whitespace
        text = re.sub(r"\t", "    ", text)
        # Cap consecutive newlines
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()

    def _check_rate(self, source: str) -> bool:
        """Check rate limit for a source."""
        now = time.time()
        if source not in self._rate_limits:
            self._rate_limits[source] = []

        # Clean old entries
        self._rate_limits[source] = [
            t for t in self._rate_limits[source] if now - t < self._rate_window
        ]

        if len(self._rate_limits[source]) >= self._rate_max:
            return False

        self._rate_limits[source].append(now)
        return True

    def set_rate_limit(self, max_requests: int, window_seconds: float) -> None:
        """Configure rate limiting."""
        self._rate_max = max_requests
        self._rate_window = window_seconds

    def get_schema(self, studio: str) -> dict | None:
        """Get input schema for a studio."""
        return self._schemas.get(studio)

    def list_schemas(self) -> dict[str, str]:
        """List all studio schemas."""
        return {name: schema["description"] for name, schema in self._schemas.items()}


_validator: InputValidator | None = None


def get_input_validator() -> InputValidator:
    global _validator
    if _validator is None:
        _validator = InputValidator()
    return _validator
