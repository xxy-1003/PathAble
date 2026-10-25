from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CameraAssignment(StrictModel):
    camera_id: str = "camera-b-01"
    node: Literal["B"] = "B"
    edge_key: Literal["B-C"] = "B-C"


class PhotoUpload(StrictModel):
    camera_id: str = Field(min_length=1, max_length=80)
    jpeg_base64: str = Field(min_length=1, max_length=699052)


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
