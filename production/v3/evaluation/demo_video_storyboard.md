# PathAble: 5-Minute Demo Video Storyboard
**OpenCV AI Competition 2026 Submission Video Plan**

**Target Duration**: 4 minutes 50 seconds (strictly $\le 5$ minutes).

**Production gate:** This is a filming plan, not a record of completed trials.
Use each scene and voiceover claim only after matching footage, logs, and a
measured report have been reviewed. Replace any unavailable scene with an
honest prototype demonstration and label it as such.

---

### Scene 1: The Problem — Static Maps in Dynamic Spaces (0:00 – 0:45)
- **Visuals**:
  - Film a controlled corridor setup with a consented volunteer and a safety spotter.
  - Show the staged obstruction and a static route illustration without staging a collision.
  - Text on Screen: *Static maps tell you where to go. They don't know what's in your way.*
- **Voiceover**:
  *"Navigating an unfamiliar building can involve sudden surprises. Buildings change throughout the day: furniture moves, carts block hallways, and doors close. PathAble explores whether vision can help an indoor route respond to those changes."*

---

### Scene 2: The Fast Loop — OpenCV 5 on Device (0:45 – 1:30)
- **Visuals**:
  - Close-up of the prototype rig: laptop in backpack, lightweight USB webcam on chest harness.
  - Picture-in-picture OpenCV 5 DNN overlay: YOLO11n-seg bounding boxes, segmentation masks, and floor contact point homography.
  - Split view showing Left / Centre / Right floor occupancy zones and ArUco marker junction tracking.
- **Voiceover**:
  *"PathAble is designed with a local decision loop and a separate cloud review loop. We will show the webcam detections, calibration evidence, route decisions, and voice output that work in the recorded demonstration. The 700 millisecond end-to-end latency is our target; the measured result will come from the trial logs."*

---

### Scene 3: The Live Corridor Demo — Walking A to D with Reroute (1:30 – 2:30)
- **Visuals**:
  - If a supervised continuous A-to-D trial succeeds, show the uncut route footage with its synchronized decision trace and recorded audio.
  - Show the actual marker, obstruction, route update, and voice instruction captured in that trial.
  - If the continuous trial is not ready, use a clearly labelled scripted replay instead.
- **Voiceover**:
  *"Here is the recorded route decision. The synchronized trace shows what the system observed, which action it selected, and what the user heard."* Use this line only with a real trial; describe a scripted replay as a simulation.

---

### Scene 4: The Slow Loop — AWS Graviton with COOL & Human Approval (2:30 – 3:30)
- **Visuals**:
  - Show actual AWS console and service traces only if the service has been deployed and tested.
  - Show privacy processing, human approval, and before/after map versions only when the logs demonstrate them.
  - Otherwise, show the local cloud simulator with a visible "simulation" label and describe AWS as planned work.
- **Voiceover**:
  *"Our cloud workflow is intended to review repeated blockage reports and request facilities approval for lasting closures. This footage shows the implementation and deployment state verified in the accompanying logs."*

---

### Scene 5: Benchmark & Performance Results (3:30 – 4:20)
- **Visuals**:
  - Populate charts only from reviewed measured reports: detection, route completion, safety events, latency, and benchmark comparisons.
  - Show the exact sample counts, hardware, OpenCV build, and data origin beside every chart.
  - If recorded AWS runs are unavailable, state that COOL results are pending and omit a speedup chart.
- **Voiceover**:
  *"We compared the same recorded inputs and model across the configurations shown here. The measured throughput, latency, and cost estimates are taken from the attached benchmark records."* Use this line only if the comparison gate and raw-run review pass.

---

### Scene 6: Responsible AI, Standards & Conclusion (4:20 – 4:50)
- **Visuals**:
  - Reference to Malaysia Accessibility Code of Practice MS 1184:2014 for corridor width.
  - Closing footage of consenting participants and verified team credits.
  - GitHub repository link and OpenCV AI Competition 2026 splash screen.
- **Voiceover**:
  *"PathAble explores how computer vision can help an indoor route respond to changing conditions. We will report both what the supervised trials demonstrate and where the prototype still needs work."*
