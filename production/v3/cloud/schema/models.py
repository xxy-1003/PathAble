"""Data models and schemas for PathAble AWS Slow-Loop Event Intake and Reasoning.

Version: 1.0.0
Standards:
- OpenCV AI Competition 2026 Proposal (Sections 6, 8, 9, 11)
- MS 1184:2014 Accessible Corridor Clearance (Minimum 1.20m clear width)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator


class OutcomeType(str, Enum):
    TEMPORARY = "TEMPORARY"
    UNCERTAIN = "UNCERTAIN"
    LASTING = "LASTING"


class TicketStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DistanceBand(str, Enum):
    NEAR = "near"
    MEDIUM = "medium"
    FAR = "far"
    UNKNOWN = "unknown"


class ZoneState(str, Enum):
    CLEAR = "clear"
    OCCUPIED = "occupied"
    UNKNOWN = "unknown"


class EdgeRef(BaseModel):
    from_node: str = Field(..., description="Starting junction node ID (e.g. 'B')")
    to_node: str = Field(..., description="Ending junction node ID (e.g. 'C')")

    @property
    def edge_key(self) -> str:
        # Canonical undirected or directed edge key
        nodes = sorted([self.from_node, self.to_node])
        return f"{nodes[0]}-{nodes[1]}"

    @model_validator(mode="after")
    def validate_nodes(self) -> EdgeRef:
        if self.from_node == self.to_node:
            raise ValueError("Edge cannot connect a node to itself")
        return self


class ZoneOccupancy(BaseModel):
    left: ZoneState = Field(..., description="Left 30% of corridor zone")
    centre: ZoneState = Field(..., description="Center 40% of corridor zone (walking path)")
    right: ZoneState = Field(..., description="Right 30% of corridor zone")


class KeyframeRef(BaseModel):
    frame_id: str = Field(..., description="Identifier of keyframe (e.g. 'kf_001')")
    filename: str = Field(..., description="File name of the image")
    s3_key: Optional[str] = Field(None, description="Amazon S3 object key")
    sha256: Optional[str] = Field(None, description="SHA256 checksum of the frame image")
    mime_type: str = Field("image/jpeg", description="MIME type of frame")
    people_blurred: bool = Field(True, description="Privacy confirmation: all people blurred")


class ObservationsSummary(BaseModel):
    confidence: float = Field(..., ge=0.0, le=1.0, description="Mean confidence score")
    obstacle_classes: List[str] = Field(..., description="COCO obstacle classes detected")
    distance_band: DistanceBand = Field(..., description="Distance band of nearest obstacle")
    ground_contact_distance_m: Optional[float] = Field(
        None, ge=0.0, description="Estimated distance in metres from USAC floor homography"
    )
    zone_occupancy: ZoneOccupancy = Field(..., description="L/C/R zone occupancy states")
    moving: bool = Field(False, description="Whether movement was observed locally")
    consecutive_blocked_frames: int = Field(
        ..., ge=1, description="Number of consecutive frames confirming blockage"
    )


class PrivacyVerification(BaseModel):
    people_blurred_on_device: bool = Field(
        True,
        description="Must be true: person segmentation masks blurred with cv.GaussianBlur before upload",
    )
    face_recognition_used: bool = Field(
        False, description="Must be false: no face recognition allowed per Section 13"
    )
    s3_lifecycle_days: int = Field(
        7, description="Automatic retention limit: S3 keyframes expire after 7 days"
    )

    @model_validator(mode="after")
    def verify_privacy_invariants(self) -> PrivacyVerification:
        if not self.people_blurred_on_device:
            raise ValueError("Privacy policy violation: unblurred frames cannot be uploaded")
        if self.face_recognition_used:
            raise ValueError("Ethics policy violation: face recognition is prohibited")
        return self


class BlockedEdgeEventV1(BaseModel):
    schema_version: Literal["1.0.0"] = Field("1.0.0", description="Event schema version")
    event_id: str = Field(..., min_length=4, description="Unique event identifier")
    client_id: str = Field(..., min_length=1, description="Edge device identifier")
    timestamp: datetime = Field(..., description="ISO 8601 UTC timestamp of detection")
    edge: EdgeRef = Field(..., description="The corridor edge confirmed blocked")
    current_node: str = Field(..., description="Current verified ArUco junction")
    destination_node: str = Field(..., description="User destination junction")
    local_reroute: List[str] = Field(..., min_length=2, description="Replanned Dijkstra route")
    observations: ObservationsSummary = Field(..., description="Perception summary")
    keyframes: List[KeyframeRef] = Field(
        default_factory=list, description="3-5 blurred keyframes for cloud re-check"
    )
    privacy: PrivacyVerification = Field(
        default_factory=PrivacyVerification, description="Privacy verification checks"
    )
    map_version: int = Field(..., ge=1, description="Device map graph version at event creation")

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event_id cannot be blank")
        return v.strip()


# Cloud Re-check Tools Results (Section 9.2)
class DetectionResult(BaseModel):
    evidence_status: Literal["observed", "simulated", "unknown"] = "unknown"
    classes: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    has_blocking_objects: bool = True
    mask_coverage_percent: Optional[float] = Field(None, ge=0.0, le=100.0)


class MotionResult(BaseModel):
    evidence_status: Literal["observed", "simulated", "unknown"] = "unknown"
    is_moving: bool = False
    average_flow_magnitude: Optional[float] = Field(None, ge=0.0)
    motion_type: Literal["static", "moving", "undetermined"] = "undetermined"


class ClearanceResult(BaseModel):
    evidence_status: Literal["observed", "simulated", "unknown"] = "unknown"
    measurement_source: Optional[str] = None
    corridor_width_m: Optional[float] = Field(None, ge=0.0, description="Surveyed corridor width, when available")
    free_clearance_m: Optional[float] = Field(None, ge=0.0, description="Available walking width, unavailable without a measurement")
    meets_ms1184_standard: Optional[bool] = Field(
        None, description="Threshold comparison only when measured clearance is available"
    )


class EdgeHistoryEntry(BaseModel):
    evidence_mode: Literal["recorded", "simulated", "unavailable"] = "unavailable"
    timestamp: datetime
    event_id: str
    outcome: OutcomeType
    clearance_m: Optional[float] = None
    classes: List[str] = Field(default_factory=list)


class RecheckToolsOutput(BaseModel):
    evidence_mode: Literal["recorded", "simulated", "unavailable"] = "unavailable"
    event_id: str
    edge: EdgeRef
    detection: DetectionResult
    motion: MotionResult
    clearance: ClearanceResult
    history: List[EdgeHistoryEntry] = Field(default_factory=list)
    recheck_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Agent Proposal & Bedrock Tiebreaker (Section 9.4)
class AgentProposal(BaseModel):
    model_config = {"protected_namespaces": ()}

    outcome: OutcomeType
    expiry_minutes: Optional[int] = Field(
        None, ge=1, le=1440, description="Auto-expiry time for TEMPORARY blockages"
    )
    justification: str = Field(
        ..., min_length=10, max_length=500, description="Two-sentence written justification"
    )
    requires_facilities_approval: bool = False
    tiebreaker_used: bool = False
    model_id: Optional[str] = None


# Human Approval & Tickets (Section 9.5)
class HumanReviewAction(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    reviewer_id: str = Field(..., min_length=1)
    notes: Optional[str] = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalTicket(BaseModel):
    evidence_mode: Literal["recorded", "simulated", "unavailable"] = "unavailable"
    ticket_id: str = Field(..., description="Unique ticket ID, e.g. 'T-17'")
    event_id: str = Field(..., description="Associated blocked edge event ID")
    edge: EdgeRef
    status: TicketStatus = TicketStatus.PENDING
    detected_classes: List[str] = Field(default_factory=list)
    measured_clearance_m: float
    justification: str
    keyframes: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None
