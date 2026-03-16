#!/usr/bin/env python3
"""
Agency OS v3.5 — Telemetry & Observability

Pipeline-level tracing with:
- Correlation IDs for every operation
- Step-by-step timeline with timestamps and durations
- Token/cost aggregation per pipeline run
- Error classification and diagnostics
- Console-friendly pretty output
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

logger = logging.getLogger("agency.telemetry")


@dataclass
class SpanRecord:
    """A single span (step) in a pipeline trace."""
    name: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    parent_id: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "running"  # running, ok, error
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


@dataclass
class TraceRecord:
    """A complete pipeline trace."""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    correlation_id: str = ""
    studio: str = ""
    operation: str = ""
    start_time: str = ""
    end_time: str = ""
    total_duration_ms: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    status: str = "running"
    spans: list[SpanRecord] = field(default_factory=list)
    error: str = ""


class Telemetry:
    """
    Observable pipeline execution tracing.

    Usage:
        tel = get_telemetry()
        with tel.trace("leadops", "lead_generation") as t:
            with t.span("intake"):
                ...
            with t.span("plan"):
                ...
            with t.span("execute") as s:
                s.attributes["leads_found"] = 42
    """

    def __init__(self) -> None:
        self._traces: list[TraceRecord] = []
        self._active_traces: dict[str, TraceRecord] = {}

    @contextmanager
    def trace(
        self, studio: str, operation: str, correlation_id: str = ""
    ) -> Generator[_TraceContext, None, None]:
        """Start a new pipeline trace."""
        record = TraceRecord(
            correlation_id=correlation_id or uuid.uuid4().hex[:12],
            studio=studio,
            operation=operation,
            start_time=datetime.now(timezone.utc).isoformat(),
        )
        self._active_traces[record.trace_id] = record
        ctx = _TraceContext(record, self)

        logger.info(
            "🔍 Trace started: %s/%s [%s]",
            studio, operation, record.trace_id,
        )

        try:
            yield ctx
            record.status = "ok"
        except Exception as e:
            record.status = "error"
            record.error = str(e)
            raise
        finally:
            record.end_time = datetime.now(timezone.utc).isoformat()
            record.total_duration_ms = sum(s.duration_ms for s in record.spans)
            record.total_tokens = sum(s.tokens_in + s.tokens_out for s in record.spans)
            self._traces.append(record)
            self._active_traces.pop(record.trace_id, None)

            logger.info(
                "🔍 Trace complete: %s/%s [%s] %s %.0fms %d tokens",
                studio, operation, record.trace_id,
                record.status, record.total_duration_ms, record.total_tokens,
            )

    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        """Get recent completed traces."""
        traces = self._traces[-limit:]
        return [
            {
                "trace_id": t.trace_id,
                "studio": t.studio,
                "operation": t.operation,
                "status": t.status,
                "duration_ms": round(t.total_duration_ms, 1),
                "tokens": t.total_tokens,
                "spans": len(t.spans),
                "start_time": t.start_time,
                "error": t.error,
            }
            for t in reversed(traces)
        ]

    def get_trace(self, trace_id: str) -> TraceRecord | None:
        """Get a specific trace by ID."""
        for t in reversed(self._traces):
            if t.trace_id == trace_id:
                return t
        return self._active_traces.get(trace_id)

    def get_timeline(self, trace_id: str) -> list[dict]:
        """Get timeline of spans for a trace."""
        trace = self.get_trace(trace_id)
        if not trace:
            return []

        return [
            {
                "name": s.name,
                "status": s.status,
                "duration_ms": round(s.duration_ms, 1),
                "tokens": s.tokens_in + s.tokens_out,
                "model": s.model,
                "error": s.error,
                "attributes": s.attributes,
            }
            for s in trace.spans
        ]

    def get_active_traces(self) -> list[dict]:
        """Get currently running traces."""
        return [
            {
                "trace_id": t.trace_id,
                "studio": t.studio,
                "operation": t.operation,
                "spans_completed": len([s for s in t.spans if s.status != "running"]),
                "running_span": next(
                    (s.name for s in t.spans if s.status == "running"), None
                ),
            }
            for t in self._active_traces.values()
        ]

    def get_stats(self) -> dict[str, Any]:
        """Get telemetry statistics."""
        if not self._traces:
            return {
                "total_traces": 0, "active": len(self._active_traces),
                "avg_duration_ms": 0, "total_tokens": 0,
            }

        return {
            "total_traces": len(self._traces),
            "active": len(self._active_traces),
            "avg_duration_ms": round(
                sum(t.total_duration_ms for t in self._traces) / len(self._traces), 1
            ),
            "total_tokens": sum(t.total_tokens for t in self._traces),
            "by_studio": self._stats_by_studio(),
            "error_rate": round(
                sum(1 for t in self._traces if t.status == "error") / len(self._traces) * 100, 1
            ),
        }

    def _stats_by_studio(self) -> dict[str, dict]:
        studios: dict[str, dict] = {}
        for t in self._traces:
            if t.studio not in studios:
                studios[t.studio] = {"traces": 0, "tokens": 0, "errors": 0}
            studios[t.studio]["traces"] += 1
            studios[t.studio]["tokens"] += t.total_tokens
            if t.status == "error":
                studios[t.studio]["errors"] += 1
        return studios


class _TraceContext:
    """Context manager for trace spans."""

    def __init__(self, record: TraceRecord, telemetry: Telemetry) -> None:
        self._record = record
        self._telemetry = telemetry
        self.trace_id = record.trace_id
        self.correlation_id = record.correlation_id

    @contextmanager
    def span(self, name: str) -> Generator[SpanRecord, None, None]:
        """Create a span within this trace."""
        span = SpanRecord(name=name, parent_id=self._record.trace_id)
        span.start_time = time.monotonic()
        self._record.spans.append(span)

        logger.debug("  ├─ Span: %s [%s]", name, span.span_id)

        try:
            yield span
            span.status = "ok"
        except Exception as e:
            span.status = "error"
            span.error = str(e)
            raise
        finally:
            span.end_time = time.monotonic()
            span.duration_ms = (span.end_time - span.start_time) * 1000

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        """Add a point-in-time event to the current trace."""
        span = SpanRecord(
            name=f"event:{name}",
            status="ok",
            start_time=time.monotonic(),
            end_time=time.monotonic(),
            attributes=attributes or {},
        )
        self._record.spans.append(span)


_telemetry: Telemetry | None = None


def get_telemetry() -> Telemetry:
    global _telemetry
    if _telemetry is None:
        _telemetry = Telemetry()
    return _telemetry
