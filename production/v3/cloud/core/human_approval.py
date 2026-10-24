"""Human Approval & Maintenance Ticket workflow (Proposal Section 9.5).

When an obstruction is classified as LASTING, facilities staff receive an approval
request.
- Approve: Closes the edge and opens a maintenance ticket in DynamoDB.
- Reject: Reopens the edge.
- Fail-safe: If nobody responds, edge stays blocked.

Safety additions:
- Duplicate-ticket prevention: only one PENDING ticket per edge at a time.
- Ticket expiry escalation: if 24 hours pass with no review, the ticket is
  marked EXPIRED and the fail-safe temporary block is automatically extended.
- Optional JSON-file persistence so tickets survive server restarts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..schema.models import ApprovalTicket, EdgeRef, HumanReviewAction, TicketStatus
from .map_sync import MapSyncManager


logger = logging.getLogger("pathable.cloud.human_approval")

# How long facilities staff have to review before auto-escalation
REVIEW_WINDOW_HOURS = 24


class HumanApprovalManager:
    """Manages human review tickets and synchronizes outcomes with the shared map."""

    def __init__(
        self,
        map_sync: MapSyncManager,
        persistence_path: Optional[str | Path] = None,
    ):
        self.map_sync = map_sync
        self._tickets: Dict[str, ApprovalTicket] = {}
        self._counter = 16  # Matches proposal trace starting around T-17
        self._persistence_path: Optional[Path] = (
            Path(persistence_path) if persistence_path else None
        )

        # Restore tickets from disk if available
        if self._persistence_path:
            self._load_tickets()

    def create_ticket(
        self,
        event_id: str,
        edge: EdgeRef,
        detected_classes: List[str],
        measured_clearance_m: float,
        justification: str,
        keyframes: Optional[List[str]] = None,
        evidence_mode: str = "unavailable",
    ) -> ApprovalTicket:
        """Creates a pending review ticket for facilities staff.

        Raises ``ValueError`` if a PENDING ticket already exists for this edge
        (duplicate-ticket safety guard).
        """
        # --- Duplicate-ticket prevention ---
        for existing in self._tickets.values():
            if (
                existing.status == TicketStatus.PENDING
                and existing.edge.edge_key == edge.edge_key
            ):
                raise ValueError(
                    f"PENDING ticket {existing.ticket_id} already exists for edge "
                    f"{edge.edge_key}; resolve it before creating a new one"
                )

        self._counter += 1
        ticket_id = f"T-{self._counter}"

        ticket = ApprovalTicket(
            evidence_mode=evidence_mode,
            ticket_id=ticket_id,
            event_id=event_id,
            edge=edge,
            status=TicketStatus.PENDING,
            detected_classes=detected_classes,
            measured_clearance_m=measured_clearance_m,
            justification=justification,
            keyframes=keyframes or [],
            created_at=datetime.now(timezone.utc),
        )
        self._tickets[ticket_id] = ticket

        # Fail-safe invariant: edge remains blocked while awaiting human response
        self.map_sync.apply_uncertain_hold(edge.from_node, edge.to_node)

        logger.info(
            "Created facilities ticket %s for edge %s (fail-safe hold active)",
            ticket_id,
            edge.edge_key,
        )
        self._save_tickets()
        return ticket

    def review_ticket(
        self,
        ticket_id: str,
        action: str,  # 'APPROVE' or 'REJECT'
        reviewer_id: str,
        notes: Optional[str] = None,
    ) -> Tuple[ApprovalTicket, int]:
        """Processes human review decision and updates authoritative map version."""
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        if ticket.status != TicketStatus.PENDING:
            raise ValueError(f"Ticket {ticket_id} is already resolved ({ticket.status})")

        now = datetime.now(timezone.utc)
        normalized_action = action.upper().strip()

        if normalized_action == "APPROVE":
            ticket.status = TicketStatus.APPROVED
            ticket.resolved_at = now
            ticket.resolved_by = reviewer_id
            ticket.resolution_notes = notes or "Corridor closed by facilities approval"

            # Approve closes edge and bumps map version
            new_version = self.map_sync.apply_lasting_closure(
                ticket.edge.from_node, ticket.edge.to_node, ticket_id
            )
            logger.info("Ticket %s APPROVED by %s; map version bumped to %d", ticket_id, reviewer_id, new_version)
            self._save_tickets()
            return ticket, new_version

        elif normalized_action == "REJECT":
            ticket.status = TicketStatus.REJECTED
            ticket.resolved_at = now
            ticket.resolved_by = reviewer_id
            ticket.resolution_notes = notes or "Closure rejected by facilities; edge reopened"

            # Reject reopens edge and bumps map version
            new_version = self.map_sync.reopen_edge(
                ticket.edge.from_node, ticket.edge.to_node, reason=f"Facilities rejected ticket {ticket_id}"
            )
            logger.info("Ticket %s REJECTED by %s; edge reopened; map version bumped to %d", ticket_id, reviewer_id, new_version)
            self._save_tickets()
            return ticket, new_version

        else:
            raise ValueError(f"Invalid review action: '{action}'. Must be APPROVE or REJECT.")

    def get_ticket(self, ticket_id: str) -> Optional[ApprovalTicket]:
        return self._tickets.get(ticket_id)

    def list_tickets(self, status: Optional[TicketStatus] = None) -> List[ApprovalTicket]:
        tickets = list(self._tickets.values())
        if status:
            tickets = [t for t in tickets if t.status == status]
        tickets.sort(key=lambda t: t.created_at, reverse=True)
        return tickets

    # ---- Ticket expiry escalation ----

    def check_ticket_expiries(
        self, now: Optional[datetime] = None
    ) -> List[ApprovalTicket]:
        """Auto-escalate PENDING tickets that exceed the review window.

        For each expired ticket the status is set to EXPIRED and a fresh
        24-hour temporary block is applied to keep the edge safely blocked.

        Returns the list of tickets that were escalated in this call.
        """
        current_time = now or datetime.now(timezone.utc)
        deadline = current_time - timedelta(hours=REVIEW_WINDOW_HOURS)
        escalated: List[ApprovalTicket] = []

        for ticket in list(self._tickets.values()):
            if ticket.status != TicketStatus.PENDING:
                continue
            if ticket.created_at <= deadline:
                ticket.status = TicketStatus.EXPIRED
                ticket.resolved_at = current_time
                ticket.resolution_notes = (
                    "Auto-escalated: no response within 24 hours"
                )
                # Re-apply fail-safe block so the edge stays closed
                self.map_sync.apply_uncertain_hold(
                    ticket.edge.from_node,
                    ticket.edge.to_node,
                )
                escalated.append(ticket)
                logger.warning(
                    "Ticket %s expired without review; fail-safe block extended "
                    "for edge %s",
                    ticket.ticket_id,
                    ticket.edge.edge_key,
                )

        if escalated:
            self._save_tickets()
        return escalated

    # ---- Persistence helpers ----

    def _save_tickets(self) -> None:
        """Persist all tickets to a JSON file so they survive restarts."""
        if not self._persistence_path:
            return
        data = {
            "counter": self._counter,
            "tickets": {
                tid: t.model_dump(mode="json") for tid, t in self._tickets.items()
            },
        }
        tmp_path = self._persistence_path.with_suffix(".tmp")
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(str(tmp_path), str(self._persistence_path))
            logger.info(
                "Tickets persisted to %s (%d tickets)",
                self._persistence_path,
                len(self._tickets),
            )
        except OSError:
            logger.warning(
                "Failed to persist tickets to %s",
                self._persistence_path,
                exc_info=True,
            )

    def _load_tickets(self) -> None:
        """Restore tickets from a persisted JSON file."""
        if not self._persistence_path or not self._persistence_path.exists():
            return
        try:
            with open(self._persistence_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._counter = data.get("counter", self._counter)
            for tid, tdata in data.get("tickets", {}).items():
                self._tickets[tid] = ApprovalTicket(**tdata)
            logger.info(
                "Tickets restored from %s (%d tickets, counter=%d)",
                self._persistence_path,
                len(self._tickets),
                self._counter,
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning(
                "Corrupted tickets file %s; starting with empty tickets",
                self._persistence_path,
                exc_info=True,
            )
