"""Human Approval & Maintenance Ticket workflow (Proposal Section 9.5).

When an obstruction is classified as LASTING, facilities staff receive an approval
request.
- Approve: Closes the edge and opens a maintenance ticket in DynamoDB.
- Reject: Reopens the edge.
- Fail-safe: If nobody responds, edge stays blocked.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Tuple

from ..schema.models import ApprovalTicket, EdgeRef, HumanReviewAction, TicketStatus
from .map_sync import MapSyncManager


logger = logging.getLogger("pathable.cloud.human_approval")


class HumanApprovalManager:
    """Manages human review tickets and synchronizes outcomes with the shared map."""

    def __init__(self, map_sync: MapSyncManager):
        self.map_sync = map_sync
        self._tickets: Dict[str, ApprovalTicket] = {}
        self._counter = 16  # Matches proposal trace starting around T-17

    def create_ticket(
        self,
        event_id: str,
        edge: EdgeRef,
        detected_classes: List[str],
        measured_clearance_m: float,
        justification: str,
        keyframes: Optional[List[str]] = None,
    ) -> ApprovalTicket:
        """Creates a pending review ticket for facilities staff."""
        self._counter += 1
        ticket_id = f"T-{self._counter}"

        ticket = ApprovalTicket(
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
        self.map_sync.apply_temporary_block(
            edge.from_node, edge.to_node, expiry_minutes=1440  # 24-hour fail-safe hold
        )

        logger.info(
            "Created facilities ticket %s for edge %s (fail-safe hold active)",
            ticket_id,
            edge.edge_key,
        )
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
