"""FastAPI REST Application for PathAble Slow Loop.

Provides endpoints for:
- Device blocked-edge intake: POST /api/v1/events
- Device map synchronization: GET /api/v1/map, GET /api/v1/map/version
- Facilities approval workflow: GET /api/v1/tickets, POST /api/v1/tickets/{id}/review
- Observability and traces: GET /api/v1/traces
- Health and status: GET /api/v1/health
"""

from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..core.orchestrator import SlowLoopOrchestrator
from ..core.recheck_tools import CloudRecheckTools
from ..core.validation import EventValidationError
from ..schema.models import HumanReviewAction, TicketStatus


MAP_PATH = Path(__file__).resolve().parents[3] / "map_graph.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="PathAble Cloud Slow-Loop API",
    version="1.0.0",
    description="Event intake, Graviton re-check orchestration, map sync, and human review.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Orchestrator
SIMULATION = os.environ.get("PATHABLE_SIMULATION") == "1"
orchestrator = SlowLoopOrchestrator(
    initial_map_path=MAP_PATH if MAP_PATH.exists() else None,
    simulation=SIMULATION,
    recheck_tools=None if SIMULATION else CloudRecheckTools(
        model_path=os.environ.get("PATHABLE_MODEL_PATH"),
        keyframe_root=os.environ.get("PATHABLE_KEYFRAME_ROOT")),
)


@app.get("/api/v1/health")
def get_health() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "service": "pathable-slow-loop",
        "recheck_mode": "simulation" if orchestrator.simulation else "recorded_or_unavailable",
        "map_version": orchestrator.map_sync.version,
        "total_events_ingested": orchestrator.intake_store.count(),
        "pending_tickets": len(orchestrator.approval_mgr.list_tickets(TicketStatus.PENDING)),
    }


@app.post("/api/v1/events", status_code=status.HTTP_200_OK)
def ingest_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ingests a blocked-edge event from edge device."""
    try:
        result = orchestrator.process_event(payload)
        return result
    except EventValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": e.message, "details": e.errors},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal processing error: {str(e)}",
        )


@app.get("/api/v1/map")
def get_shared_map() -> Dict[str, Any]:
    """Returns authoritative shared map graph for edge synchronization."""
    return orchestrator.map_sync.get_map()


@app.get("/api/v1/map/version")
def get_map_version() -> Dict[str, Any]:
    """Lightweight endpoint polled by edge devices at junctions."""
    return orchestrator.map_sync.get_version_info()


@app.get("/api/v1/tickets")
def list_tickets(status_filter: Optional[str] = Query(None, alias="status")) -> List[Dict[str, Any]]:
    """Lists human approval tickets."""
    st = None
    if status_filter:
        try:
            st = TicketStatus(status_filter.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    tickets = orchestrator.approval_mgr.list_tickets(status=st)
    return [t.model_dump(mode="json") for t in tickets]


@app.get("/api/v1/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> Dict[str, Any]:
    ticket = orchestrator.approval_mgr.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    return ticket.model_dump(mode="json")


@app.post("/api/v1/tickets/{ticket_id}/review")
def review_ticket(ticket_id: str, review: HumanReviewAction) -> Dict[str, Any]:
    """Processes facilities staff APPROVE / REJECT action."""
    try:
        ticket, new_version = orchestrator.approval_mgr.review_ticket(
            ticket_id=ticket_id,
            action=review.action,
            reviewer_id=review.reviewer_id,
            notes=review.notes,
        )
        orchestrator.audit.log(
            ticket.event_id,
            "APPROVAL",
            f"TICKET_{review.action}",
            {"ticket_id": ticket_id, "reviewer": review.reviewer_id, "new_map_version": new_version},
        )
        return {
            "ticket": ticket.model_dump(mode="json"),
            "new_map_version": new_version,
            "message": f"Ticket {ticket_id} {review.action} processed successfully.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/traces")
def get_decision_traces(
    event_id: Optional[str] = None, limit: int = Query(50, ge=1, le=500)
) -> List[Dict[str, Any]]:
    """Returns chronological decision trace stream for CloudWatch audit and judge review."""
    if event_id:
        records = orchestrator.audit.get_traces_for_event(event_id)
    else:
        records = orchestrator.audit.get_all_traces(limit=limit)
    return [
        {
            "timestamp": r.timestamp,
            "event_id": r.event_id,
            "component": r.component,
            "action": r.action,
            "details": r.details,
        }
        for r in records
    ]


# Mount static web dashboard
if STATIC_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(STATIC_DIR), html=True), name="dashboard")


@app.get("/")
def root_redirect():
    return FileResponse(str(STATIC_DIR / "index.html")) if (STATIC_DIR / "index.html").exists() else {"service": "PathAble Slow-Loop API"}
