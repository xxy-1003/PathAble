from typing import Literal
from uuid import UUID
from datetime import timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CameraAssignment(StrictModel):
    camera_id: str = "camera-b-01"
    node: Literal["B"] = "B"
    edge_key: Literal["B-C"] = "B-C"


class PhotoUpload(StrictModel):
    camera_id: str = Field(min_length=1, max_length=80)
    jpeg_base64: str = Field(min_length=1, max_length=699052)


class PresignInput(StrictModel):
    client_id: str = Field(min_length=1, max_length=80)
    content_type: Literal["image/jpeg"]
    size_bytes: int = Field(ge=1, le=524288, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PresignResult(StrictModel):
    photo_id: UUID
    method: Literal["PUT"]
    url: str
    headers: dict[str, str]
    expires_in: Literal[300]


class ImageReference(StrictModel):
    photo_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DetectionEvidence(StrictModel):
    obstacle_class: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)
    overlap_count: int = Field(ge=1, le=10000, strict=True)
    frame_count: int = Field(ge=1, le=10000, strict=True)
    evidence_status: Literal["client_reported"]

    @model_validator(mode="after")
    def valid_overlap(self):
        if self.overlap_count > self.frame_count:
            raise ValueError("overlap_count cannot exceed frame_count")
        return self


class HumanReportInput(StrictModel):
    schema_id: Literal["pathable.human-review.report.v1"]
    event_id: UUID
    client_id: str = Field(min_length=1, max_length=80)
    timestamp: AwareDatetime
    edge_key: Literal["B-C"]
    junction: Literal["B"]
    destination: Literal["D"]
    detection_evidence: DetectionEvidence
    image: ImageReference
    distance_m: None
    clearance_m: None
    measurement_source: None

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value):
        if value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be UTC (Z or +00:00)")
        return value

    def compact(self):
        evidence = self.detection_evidence.model_dump(exclude={"evidence_status"})
        return ReportInput(report_id=self.event_id, camera_id=self.client_id,
                           observed_at=self.timestamp, photo_id=self.image.photo_id, **evidence)


class ReportInput(StrictModel):
    report_id: UUID
    camera_id: str = Field(min_length=1, max_length=80)
    photo_id: UUID
    observed_at: AwareDatetime
    obstacle_class: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)
    overlap_count: int = Field(ge=1, le=10000, strict=True)
    frame_count: int = Field(ge=1, le=10000, strict=True)
    distance_m: None = None
    clearance_m: None = None
    measurement_source: None = None

    @model_validator(mode="after")
    def valid_overlap(self):
        if self.overlap_count > self.frame_count:
            raise ValueError("overlap_count cannot exceed frame_count")
        return self


class ReviewInput(StrictModel):
    action: Literal["APPROVE", "REJECT"]
    expected_map_version: int = Field(ge=1, strict=True)
    notes: str = Field(default="", max_length=2000)


class PhotoCreated(StrictModel):
    photo_id: UUID
    sha256: str


class ReviewRecord(ReviewInput):
    reviewer_id: str
    reviewed_at: AwareDatetime
    map_version: int


class ReportRecord(ReportInput):
    schema_id: str
    event_id: UUID
    client_id: str
    timestamp: AwareDatetime
    junction: Literal["B"]
    destination: Literal["D"]
    detection_evidence: DetectionEvidence
    image: ImageReference
    ticket_id: str
    payload_sha256: str
    received_at: AwareDatetime
    node: Literal["B"]
    edge_key: Literal["B-C"]
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    expected_map_version: int
    review: ReviewRecord | None


class ReportPage(StrictModel):
    items: list[ReportRecord]
    next_cursor: str | None


class ReviewResult(StrictModel):
    report: ReportRecord
    map_version: int


class PhotoLink(StrictModel):
    url: str
    expires_in: int


class MapVersion(StrictModel):
    map_id: Literal["prototype"]
    version: int


class MapEdge(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_node: str = Field(alias="from")
    to: str
    distance: None
    distance_source: Literal["unmeasured"]
    route_weight: int
    blocked: bool


class SharedMap(MapVersion):
    nodes: dict[str, str]
    edges: list[MapEdge]


class Health(StrictModel):
    status: Literal["healthy"]
    storage: str
    map_version: int


def initial_map():
    pairs = [("A", "B"), ("B", "C"), ("C", "D"),
             ("B", "E"), ("E", "F"), ("F", "D")]
    return {"map_id": "prototype", "version": 1,
            "nodes": {str(i): node for i, node in enumerate("ABCDEF")},
            "edges": [{"from": a, "to": b, "distance": None,
                       "distance_source": "unmeasured", "route_weight": 1,
                       "blocked": False} for a, b in pairs]}
