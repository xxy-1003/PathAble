# PathAble: Technical Report Outline
**Submission for OpenCV AI Competition 2026, powered by AWS**

---

### Title: PathAble: A Living Indoor Route for Visually Impaired Users
*Sub-title: Agentic Vision with OpenCV 5, COOL on AWS Graviton, and Shared Dynamic Maps*

1. **Executive Summary**
   - Problem: Pre-mapped indoor navigation fails when spaces dynamically change throughout the day.
   - Innovation: Vision changes the route, not just alerts; fast local decision loop (<700 ms) paired with AWS slow loop that learns lasting closures with human approval.
   - Core Awards Targeted: *Agentic Vision Award* and *Best Use of COOL on AWS Graviton*.

2. **Problem Statement & Accessibility Context**
   - 2.2 billion people with visual impairment worldwide (WHO).
   - Limitations of cane, scene describers (Seeing AI/Be My Eyes), and static beacon maps (NavCog).
   - Compliance with Accessibility Standards: Department of Standards Malaysia (MS 1184:2014) for corridor clearance.

3. **System Architecture (Two-Loop Design)**
   - Fast Loop (On-Device): Laptop + chest webcam, 640x480 @ 10 FPS, offline TTS, zero cloud dependency for walking safety.
   - Slow Loop (On-AWS): API Gateway, Lambda, S3, EC2 c7g.large Graviton with COOL, Amazon Bedrock (Nova Lite), DynamoDB, SNS.

4. **Computer Vision Implementation with OpenCV 5**
   - New OpenCV 5 DNN engine running YOLO11n-seg ONNX without external runtimes.
   - Floor plane homography using USAC MAGSAC (`cv.USAC_MAGSAC`) for ground-contact metric distances (<1.0m, 1.0–2.5m, >2.5m).
   - Junction localisation using ArUco markers (`DICT_4X4_50`) and `cv.solvePnP` for camera heading.
   - Farneback dense optical flow (`cv.calcOpticalFlowFarneback`) on cloud keyframes to separate moving people from static objects.

5. **Local Navigation Agent & Voice Guidance**
   - Deterministic decision table (CONTINUE, STEP ASIDE, WAIT AND RE-OBSERVE, TURN TO LOOK, REROUTE, STOP AND ESCALATE).
   - Active perception: resolving ambiguity via wait or look probes before committing.
   - Offline text-to-speech voice layer: emergency STOP priority interrupts, normally silent CONTINUE.
   - Latency budget breakdown: capture (40ms) + DNN (100ms) + mask/distance (30ms) + Dijkstra (10ms) + speech dispatch (300ms) <= 700 ms (95th percentile).

6. **AWS Graviton & COOL Cloud Re-check Workload**
   - EC2 c7g.large Graviton3 running Cloud-Optimized OpenCV Library (COOL).
   - Strands Agents SDK orchestrating re-check tools (`detect`, `motion`, `clearance`, `history`).
   - Tie-breaking with Amazon Bedrock (Amazon Nova Lite) with written justifications.
   - Human-in-the-loop facilities sign-off via S3/CloudFront dashboard before permanent DynamoDB map updates.

7. **COOL on AWS Graviton Benchmark & Cost Efficiency**
   - Methodology: Fixed 300 test keyframes across 3 configurations:
     - Config A: c7g.large + COOL
     - Config B: c7g.large + stock OpenCV 5
     - Config C: c7i.large (x86) + stock OpenCV 5
   - Metrics: Median/p95 latency, throughput (FPS), cost per 1,000 frames using AWS regional pricing.

8. **Experimental Evaluation & Validation Results**
   - 80 scenario trials across 8 staged corridor conditions (target: >=85% decision accuracy).
   - 20 continuous route runs from Entrance (A) to Lab (D) (target: >=90% completion, 0 collisions).
   - Baseline comparison (static map without perception).
   - Ablation study (removal of active perception).
   - Escalation accuracy (STOP_AND_ESCALATE recall >= 0.90 in unsafe scenarios).
   - Cloud classification accuracy across 30 staged sequences (>=80%).

9. **Failure Case Dissection & Safety Analysis**
   - Audit of difficult conditions: glass reflections, solar glare, low light, crowds, and out-of-vocabulary objects.
   - Transparent reporting of failure modes and cane-primary safety guarantees.

10. **Ethical Use, Privacy & Limitations**
    - Face/people blurring on device with Gaussian blur before frame upload; 7-day S3 retention.
    - Volunteer consent protocol and safety spotter requirements.
    - Limitations: flat floors, pre-placed ArUco markers, COCO-pretrained object scope.

11. **Conclusion & Submission Links**
    - Code repository: GitHub links, branch organization, reproducibility scripts.
    - 5-minute video demonstration link.
