# PathAble v3: Decision Trace Format Specification

Conforms to Section 11 of the project proposal: **Example Decision Trace**.

Every submission evidence log records the end-to-end decision chain spanning the on-device **Fast Loop**, the AWS **Slow Loop**, and the **Human-in-the-Loop** approval action.

---

## Trace Schema

```json
{
  "trace_id": "trace-20261024-e2e-01",
  "created_at": "2026-10-24T12:00:00Z",
  "target_route": ["A", "D"],
  "entries": [
    {
      "time_offset_s": 0.0,
      "loop": "Device",
      "observation": {
        "frame_id": 212,
        "obstacle_class": "chair",
        "confidence": 0.48,
        "zones": {"left": "unknown", "centre": "occupied", "right": "unknown"},
        "distance_m": 1.8,
        "distance_band": "medium"
      },
      "decision": "WAIT_AND_REOBSERVE",
      "spoken_message": "Please wait.",
      "route": ["B", "C", "D"],
      "latency_ms": 118.2
    },
    {
      "time_offset_s": 3.1,
      "loop": "Device",
      "observation": {
        "frame_id": 218,
        "obstacle_class": "chair",
        "confidence": 0.82,
        "zones": {"left": "occupied", "centre": "occupied", "right": "occupied"},
        "distance_m": 0.9,
        "distance_band": "near",
        "persistence_count": 6
      },
      "decision": "REROUTE",
      "spoken_message": "Route blocked. Turn left at this junction towards E.",
      "route": ["B", "E", "F", "D"],
      "event_emitted": "e-0193",
      "latency_ms": 125.4
    },
    {
      "time_offset_s": 7.1,
      "loop": "AWS",
      "tool_outputs": {
        "detect": ["chair", "dining table"],
        "motion": "static",
        "clearance_m": 0.6,
        "history": "none"
      },
      "decision": "UNCERTAIN",
      "action_taken": "Edge B-C remains blocked pending second confirmation report",
      "cloudwatch_log_ref": "arn:aws:logs:ap-southeast-1:123456789012:log-group:pathable/events"
    },
    {
      "time_offset_s": 1320.0,
      "loop": "AWS",
      "tool_outputs": {
        "detect": ["chair", "dining table"],
        "motion": "static",
        "clearance_m": 0.6,
        "history": "1 prior event (22 min ago)"
      },
      "decision": "LASTING",
      "action_taken": "SNS alert dispatched to facilities approval dashboard",
      "bedrock_justification": "Identical static furniture arrangement confirmed in corridor B-C across 2 independent runs over 22 minutes with clearance under 1.2m."
    },
    {
      "time_offset_s": 1800.0,
      "loop": "Human",
      "actor": "facilities_staff_01",
      "action_taken": "Approve",
      "ticket_id": "T-17",
      "map_version_updated": 14,
      "closed_edge": ["B", "C"]
    },
    {
      "time_offset_s": 1860.0,
      "loop": "Device",
      "user": "subsequent_user_02",
      "location": "Junction A",
      "action_taken": "Fetched map v14; computed optimal route A -> B -> E -> F -> D directly."
    }
  ]
}
```
