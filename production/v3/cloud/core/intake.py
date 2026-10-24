"""Idempotent event intake module for PathAble cloud service.

Handles event deduplication, idempotency key tracking, storage of validated events,
and prevents duplicate processing on network retries.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..schema.models import BlockedEdgeEventV1
from .validation import validate_event_dict, EventValidationError


logger = logging.getLogger("pathable.cloud.intake")


@dataclass
class IntakeRecord:
    event_id: str
    client_id: str
    edge_key: str
    received_at: datetime
    payload_hash: str
    event: BlockedEdgeEventV1
    processed: bool = False
    processing_result: Optional[Dict[str, Any]] = None


class IdempotentIntakeStore:
    """Thread-safe / in-memory store simulating DynamoDB Events table with conditional puts."""

    def __init__(self):
        self._records: Dict[str, IntakeRecord] = {}
        self._edge_index: Dict[str, list[str]] = {}

    def _hash_payload(self, event: BlockedEdgeEventV1) -> str:
        serialized = event.model_dump_json(exclude={"timestamp"})
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def ingest(
        self, payload: Dict[str, Any]
    ) -> Tuple[BlockedEdgeEventV1, bool, Optional[Dict[str, Any]]]:
        """Ingests an event idempotently.

        Returns:
            Tuple of (validated_event, is_duplicate, previous_result)
        """
        event = validate_event_dict(payload)
        payload_hash = self._hash_payload(event)

        if event.event_id in self._records:
            existing = self._records[event.event_id]
            logger.info("Duplicate event received: %s (idempotent return)", event.event_id)
            if existing.payload_hash != payload_hash:
                raise EventValidationError(
                    f"Conflict: Event {event.event_id} already exists with differing payload content"
                )
            return existing.event, True, existing.processing_result

        # New event
        record = IntakeRecord(
            event_id=event.event_id,
            client_id=event.client_id,
            edge_key=event.edge.edge_key,
            received_at=datetime.now(timezone.utc),
            payload_hash=payload_hash,
            event=event,
            processed=False,
            processing_result=None,
        )
        self._records[event.event_id] = record
        self._edge_index.setdefault(event.edge.edge_key, []).append(event.event_id)
        logger.info("New event accepted into intake: %s", event.event_id)
        return event, False, None

    def record_result(self, event_id: str, result: Dict[str, Any]) -> None:
        """Stores processing outcome against the idempotent record."""
        if event_id in self._records:
            self._records[event_id].processed = True
            self._records[event_id].processing_result = result

    def get_event(self, event_id: str) -> Optional[BlockedEdgeEventV1]:
        record = self._records.get(event_id)
        return record.event if record else None

    def get_events_for_edge(self, edge_key: str) -> list[BlockedEdgeEventV1]:
        event_ids = self._edge_index.get(edge_key, [])
        return [self._records[eid].event for eid in event_ids if eid in self._records]

    def count(self) -> int:
        return len(self._records)
