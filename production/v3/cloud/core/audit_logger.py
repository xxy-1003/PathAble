"""Audit logging and CloudWatch trace recorder (Proposal Section 9.6 & 11).

Logs structured decision traces with event ID correlation, tracking every step:
perception -> recheck tools -> state rule -> tiebreaker -> validation -> human review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger("pathable.cloud.audit")


@dataclass
class TraceRecord:
    timestamp: str
    event_id: str
    component: str  # "INTAKE" | "RECHECK_TOOLS" | "STATE_RULES" | "BEDROCK" | "VALIDATOR" | "APPROVAL" | "MAP_SYNC"
    action: str
    details: Dict[str, Any]


class CloudAuditLogger:
    """Records chronological decision traces for CloudWatch and judge dashboard."""

    def __init__(self):
        self._traces: List[TraceRecord] = []

    def log(
        self,
        event_id: str,
        component: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> TraceRecord:
        now_str = datetime.now(timezone.utc).isoformat()
        record = TraceRecord(
            timestamp=now_str,
            event_id=event_id,
            component=component,
            action=action,
            details=details or {},
        )
        self._traces.append(record)
        # Log to Python logger (which emits to standard logging / CloudWatch Logs)
        logger.info(
            "TRACE [%s] [%s] %s: %s",
            event_id,
            component,
            action,
            json.dumps(details or {}),
        )
        return record

    def get_traces_for_event(self, event_id: str) -> List[TraceRecord]:
        return [r for r in self._traces if r.event_id == event_id]

    def get_all_traces(self, limit: int = 100) -> List[TraceRecord]:
        return self._traces[-limit:]

    def clear(self) -> None:
        self._traces.clear()
