# PathAble v3: Evaluation Scenarios and Ground-Truth Labelling Protocol

This document defines the 8 test scenarios, ground-truth labelling schema, and trial safety protocols specified in Section 12 of the OpenCV AI Competition 2026 proposal.

---

## 1. Safety Spotter and Participant Protocol

> [!CAUTION]
> **Safety Mandatory Rule**: Do not conduct blindfolded walking trials until:
> 1. A controlled, cordoned corridor section in FTSM building is cleared of unscripted hazards.
> 2. Informed consent has been signed by the participant.
> 3. An assigned safety spotter walks directly beside the participant throughout each run, holding a ready stop grasp.
> 4. An explicit stop word (e.g., "STOP") is agreed upon before every trial. The participant or spotter may abort at any second.
> 5. All trials are video-recorded for post-run ground-truth auditing.

No visually impaired participants are involved in this prototype phase (scheduled for subsequent clinical trials with Institutional Ethics Approval).

---

## 2. The Eight Evaluation Scenarios (80 Trials Total)

| Scenario ID | Name | Physical Setup | Expected Correct Action(s) | Planned Trials | Metric Evaluated |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **SCEN-01** | **Clear corridor** | Unobstructed corridor between junctions. | `CONTINUE` | 10 | False-positive avoidance rate |
| **SCEN-02** | **Centre obstacle** | Single chair placed centrally in walking path; left & right zones clear. | `STEP_ASIDE` (left or right) | 10 | Local avoidance accuracy |
| **SCEN-03** | **Left side blocked** | Table/desk placed along left corridor wall; centre & right clear. | `CONTINUE` or `STEP_ASIDE` right | 10 | Margin clearance |
| **SCEN-04** | **Right side blocked**| Suitcase/backpack placed on right floor; centre & left clear. | `CONTINUE` or `STEP_ASIDE` left | 10 | Margin clearance |
| **SCEN-05** | **Full blockage** | Chairs and table spanning corridor width (>85% width blocked). | `REROUTE` (after 6-frame confirmation) | 10 | Dijkstra replan & AWS report |
| **SCEN-06** | **Moving person** | Sighted confederate walks across or down corridor path. | `WAIT_AND_REOBSERVE` $\rightarrow$ `CONTINUE` | 10 | Farneback/motion handling |
| **SCEN-07** | **Low light** | Corridor lighting dimmed / partially shut off (<50 lux). | Correct avoidance OR `STOP_AND_ESCALATE` | 10 | Graceful degradation |
| **SCEN-08** | **Glass door / Glare**| Sunny floor reflection / transparent glass door reflection probe. | `STOP_AND_ESCALATE` (zero wrong directions)| 10 | Failure probe safety |

**Total Scenario Trials**: $10 \times 8 = 80$ trials. Target decision accuracy: $\ge 85\%$.

---

## 3. Ground-Truth Labelling Schema

Every trial record is serialized as a JSON object adhering to the schema below:

The values below illustrate field structure only; they are not measured results.
Collect the actual distance, speech latency, and video timecodes for each run.

```json
{
  "trial_id": "SCEN-02_T03",
  "scenario_id": 2,
  "scenario_name": "centre_obstacle",
  "participant_id": "VOLUNTEER_01",
  "spotter_id": "SPOTTER_LEAD",
  "corridor_edge": ["A", "B"],
  "ground_truth": {
    "obstacle_present": true,
    "classes": ["chair"],
    "distance_band": "near",
    "distance_ground_truth_m": 1.45,
    "occupied_zones": ["centre"],
    "moving": false,
    "safety_critical": false,
    "acceptable_actions": ["STEP_ASIDE"],
    "unacceptable_actions": ["CONTINUE"]
  },
  "execution": {
    "system_action": "STEP_ASIDE",
    "system_message": "Obstacle ahead. Step slightly right.",
    "speech_latency_ms": 142.5,
    "spotter_intervened": false,
    "collision": false,
    "matched_ground_truth": true
  },
  "video_audit": {
    "recording_file": "corridor_session_20261024_01.mp4",
    "timecode_start_s": 124.0,
    "timecode_end_s": 136.5
  }
}
```

---

## 4. End-to-End Route Trials (20 Runs)

In addition to the 80 static scenario trials, 20 continuous runs from Entrance (A) to Lab (D) will be performed:
- 10 runs with corridor B–C fully blocked (requires online reroute through E–F).
- 10 runs with dynamic obstacles along the route (centre chair or moving pedestrian).
- Target: $\ge 90\%$ destination arrival rate with zero collisions.
