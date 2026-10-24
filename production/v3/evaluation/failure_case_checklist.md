# PathAble v3: Failure-Case Analysis Checklist

Conforms to Section 12.5 of the project proposal.

In safety-critical navigation for visually impaired individuals, systematically logging, categorizing, and dissecting failure cases is just as important as reporting accuracy scores. Every unsuccessful trial, spotter intervention, or erroneous decision is audited using this checklist.

---

## 1. Failure Categories & Root Cause Classification

| Code | Failure Category | Description & Typical Symptoms | Expected Fail-Safe Behavior |
| :--- | :--- | :--- | :--- |
| **FC-01** | **Glass & Glare** | Highly reflective polished tiles, floor-to-ceiling windows, or transparent glass doors confusing homography/depth. | `STOP_AND_ESCALATE`: "Please stop. I cannot verify the path." Never hallucinate a clear path. |
| **FC-02** | **Low Light (<50 lux)** | Evening or poorly lit corridors causing noisy edges, dropped segmentation masks, or low confidence scores. | Drop below 0.60 threshold $\rightarrow$ `WAIT_AND_REOBSERVE` $\times 2$ $\rightarrow$ `STOP_AND_ESCALATE`. |
| **FC-03** | **Dense Crowds** | Multiple crossing pedestrians occluding ground contact points simultaneously. | `WAIT_AND_REOBSERVE` with Farneback optical flow confirmation. |
| **FC-04** | **Camera Shake / Misalignment** | Chest harness movement or rapid walking pace shifting camera tilt beyond calibrated $20^\circ$. | Pitch/roll reprojection check triggers `unknown` distance bands $\rightarrow$ `STOP_AND_ESCALATE`. |
| **FC-05** | **Out-of-Vocabulary Obstacles** | Hazards not in COCO pretrained classes (e.g., wet floor warning cones, scaffolding poles, thin cables). | Transparently report limitation; Cane serves as tactile primary defense. |
| **FC-06** | **Occluded / Missed ArUco Marker** | Junction marker blocked by person or missed due to angle $>45^\circ$. | 10-second junction timeout triggers prompt: "Turn slowly to scan junction" $\rightarrow$ `STOP_AND_ESCALATE`. |

---

## 2. Failure Case Audit Entry Template

For every failed trial, record the following entry in the evaluation log:

```json
{
  "failure_id": "FAIL-20261024-001",
  "trial_id": "SCEN-08_T02",
  "timestamp": "2026-10-24T14:30:12Z",
  "category_code": "FC-01",
  "category_name": "Glass & Glare",
  "sensor_input": {
    "frame_id": 412,
    "keyframe_image": "failures/fail_001_frame412.jpg",
    "lux_estimate": 450,
    "confidence_score": 0.38
  },
  "agent_execution": {
    "system_action": "STOP_AND_ESCALATE",
    "voice_message": "Please stop and stay where you are. I cannot verify the path.",
    "spotter_intervened": false,
    "collision": false
  },
  "root_cause_analysis": "Intense solar glare on polished corridor floor washed out contrast, causing floor contact pixels to fall outside valid USAC homography hull.",
  "mitigation_or_remedy": "Add specular glare suppression prefilter or require conservative stop when homography reprojection residuals exceed threshold."
}
```
