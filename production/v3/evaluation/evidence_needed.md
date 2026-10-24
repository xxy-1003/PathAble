# PathAble: Evidence Needed from Teammates and Physical Trials
**Checklist for Final Devpost Submission Preparation (Person 5)**

Person 5 has an evaluation framework, metric calculations, synthetic self-check fixtures, scenario protocols, a report outline, and a conditional video storyboard. These are preparation artifacts; physical and AWS results still require recorded evidence and review.

To transition from synthetic verification to final measured competition submission evidence, the following specific deliverables are required from teammates and physical corridor trials:

---

## 1. From Person 1 (Navigation and Voice — `codex/pathable-navigation`)
| Deliverable | Specific Requirement | Why Needed |
| :--- | :--- | :--- |
| **Integrated Decision Engine** | `local_agent.py` and `voice.py` capable of receiving real live `Observation` streams. | Drives decisions during physical corridor runs. |
| **Recorded Speech Audio** | Audio capture of live TTS warnings during corridor navigation (e.g., reroute, wait, step aside). | Required for video demonstration and audio verification. |
| **Decision Logs with Latency** | Timestamps recorded with `time.perf_counter()` from observation receipt to speech start. | Populates real whole-pipeline latency metrics ($\le 700\text{ ms}$). |

---

## 2. From Person 2 (Camera and Perception — `codex/pathable-perception`)
| Deliverable | Specific Requirement | Why Needed |
| :--- | :--- | :--- |
| **Camera Calibration JSON** | `calibration/camera.json` for the Logitech USB webcam on the fixed chest mount ($\text{RMS} \le 1.5\text{ px}$, `verified_target_size: true`). | Undistorts pixels for homography and ArUco pose. |
| **Floor Calibration JSON** | `calibration/floor.json` measured from $\ge 8$ surveyed points in FTSM corridor (held-out error $\le 0.15\text{ m}$). | Converts obstacle ground contact points to real metric distances. |
| **ArUco Marker Wall Mounts** | Wall-relative orientations for printed markers A through F ($15\text{ cm}$, `DICT_4X4_50`). | Enables heading calculation and turn-left / turn-right guidance. |
| **Labelled Video Clips** | 10–20 short MP4 corridor clips with frame-level bounding boxes/masks for COCO classes within $2.5\text{ m}$. | Populates physical detection recall ($\ge 0.90$) and precision ($\ge 0.85$). |

---

## 3. From Person 3 (AWS and Shared Map — `codex/pathable-cloud`)
| Deliverable | Specific Requirement | Why Needed |
| :--- | :--- | :--- |
| **Live Intake & Privacy Audit** | API Gateway endpoint accepting blocked-edge JSON; verification that faces in S3 keyframes are blurred. | Proves privacy compliance in Section 9.1. |
| **Decision Trace CloudWatch Logs** | Complete CloudWatch log stream for a staged event showing `detect`, `motion`, `clearance`, and `history` tool outputs. | Feeds the Section 11 decision trace in the technical report. |
| **Bedrock Justification Samples** | JSON output from Amazon Nova Lite tie-breaker showing 2-sentence written justifications. | Proves Agentic Vision Award qualification. |
| **Human Approval Evidence** | Screen recording or screenshots of an authenticated facilities review and the actual before/after shared-map version, if deployed. | Verifies human approval and map synchronization when available. |

---

## 4. From Person 4 (COOL Performance — `codex/pathable-cool-benchmark`)
| Deliverable | Specific Requirement | Why Needed |
| :--- | :--- | :--- |
| **Raw 300-Frame Benchmark Data** | CSV / JSON logs of 5 measured runs across 300 keyframes for: <br>• Config A: c7g.large + COOL <br>• Config B: c7g.large + stock OpenCV 5 <br>• Config C: c7i.large + stock OpenCV 5. | Computes measured speedup, throughput (FPS), and cost per 1,000 frames. |
| **Proof of COOL Build** | Output of `cv.getBuildInformation()`, AWS Marketplace AMI ID, and Graviton instance ID. | Required evidence for the *Best Use of COOL* Award. |

---

## 5. Physical Trials in FTSM Corridor (Team + Spotter)
| Deliverable | Specific Requirement | Why Needed |
| :--- | :--- | :--- |
| **Safety & Consent Protocol** | Controlled corridor cordoned off; signed volunteer consent forms; designated safety spotters; agreed stop word. | Mandatory safety & ethics compliance before blindfolded trials. |
| **80 Scenario Trial Records** | Recorded JSON logs and ground-truth matches for the 8 scenarios ($10 \times 8 = 80$ trials). | Populates decision accuracy scorecard (target $\ge 85\%$). |
| **20 End-to-End Route Runs** | Continuous trial video and logs from Entrance (A) to Lab (D) with corridor B–C blocked. | Populates route completion rate (target $\ge 90\%$, 0 collisions). |
| **Spotter Intervention Log** | Log of any physical spotter touches, verbal halts, or cane collisions (target: zero collisions). | Proves system safety over baseline. |
| **Video B-Roll for Demo** | High-definition camera footage of volunteer walking, webcam view, and reaction to obstacles. | Edits into the final 5-minute submission video. |
