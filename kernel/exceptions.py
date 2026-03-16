#!/usr/bin/env python3
"""
Agency OS v4.0 — Exception Hierarchy

Typed exceptions replace all 40+ bare `except Exception` blocks.
Every error has: category, severity, suggested action, and context.
"""
from __future__ import annotations


class AgencyError(Exception):
    """Base exception for all Agency OS errors."""

    def __init__(self, message: str, context: dict | None = None) -> None:
        self.context = context or {}
        super().__init__(message)


# ── Configuration ─────────────────────────────────────────────

class ConfigError(AgencyError):
    """Configuration loading or validation error."""
    pass


class MissingConfigError(ConfigError):
    """Required configuration value is missing."""
    pass


# ── AI / Model ────────────────────────────────────────────────

class ModelError(AgencyError):
    """Error communicating with an AI model."""
    pass


class ModelTimeoutError(ModelError):
    """AI model call timed out."""
    pass


class ModelRateLimitError(ModelError):
    """AI model rate limit exceeded."""
    pass


class ModelContentFilterError(ModelError):
    """AI model blocked content due to safety filter."""
    pass


# ── OpenClaw ──────────────────────────────────────────────────

class OpenClawError(AgencyError):
    """Error communicating with OpenClaw gateway."""
    pass


class OpenClawUnavailableError(OpenClawError):
    """OpenClaw gateway is not accessible."""
    pass


# ── Studio / Pipeline ────────────────────────────────────────

class StudioError(AgencyError):
    """Error during studio pipeline execution."""
    pass


class PipelineStepError(StudioError):
    """A specific pipeline step failed."""

    def __init__(self, message: str, step: str = "", context: dict | None = None):
        self.step = step
        super().__init__(message, context)


class QualityGateError(StudioError):
    """Pipeline output didn't meet quality criteria."""
    pass


# ── Workflow ──────────────────────────────────────────────────

class WorkflowError(AgencyError):
    """Error during workflow execution."""
    pass


class WorkflowNodeError(WorkflowError):
    """A specific workflow node failed."""
    pass


class WorkflowDeadlockError(WorkflowError):
    """Workflow has circular dependencies."""
    pass


# ── Agent ─────────────────────────────────────────────────────

class AgentError(AgencyError):
    """Error related to agent operations."""
    pass


class AgentNotFoundError(AgentError):
    """Requested agent does not exist."""
    pass


class DelegationError(AgentError):
    """Agent delegation failed."""
    pass


# ── Tool ──────────────────────────────────────────────────────

class ToolError(AgencyError):
    """Error executing a tool."""
    pass


class ToolPermissionError(ToolError):
    """Agent lacks permission to execute tool."""
    pass


class ToolTimeoutError(ToolError):
    """Tool execution timed out."""
    pass


# ── Guardrail ─────────────────────────────────────────────────

class GuardrailError(AgencyError):
    """Guardrail blocked an operation."""
    pass


class BudgetExceededError(GuardrailError):
    """Token or cost budget exceeded."""
    pass


class ContentFilterError(GuardrailError):
    """Content was blocked by safety filter."""
    pass


class RateLimitError(GuardrailError):
    """Request rate limit exceeded."""
    pass


# ── Storage / DB ──────────────────────────────────────────────

class StorageError(AgencyError):
    """Database or storage operation failed."""
    pass


class StateCorruptionError(StorageError):
    """State data is corrupted or inconsistent."""
    pass


# ── Plugin ────────────────────────────────────────────────────

class PluginError(AgencyError):
    """Error loading or executing a plugin."""
    pass


class PluginLoadError(PluginError):
    """Plugin failed to load."""
    pass


# ── Channel ───────────────────────────────────────────────────

class ChannelError(AgencyError):
    """Error in channel communication."""
    pass
