# PathAble: 5-Minute Demo Video Storyboard
**OpenCV AI Competition 2026 Submission Video Plan**

**Target Duration**: 4 minutes 50 seconds (strictly $\le 5$ minutes).

---

### Scene 1: The Problem — Static Maps in Dynamic Spaces (0:00 – 0:45)
- **Visuals**:
  - A blindfolded volunteer walks cautiously with a white cane in a corridor.
  - Suddenly, chairs and delivery boxes block the path. A typical phone map app shows a straight green line, oblivious to the blockage. The cane collides with the chair.
  - Text on Screen: *Static maps tell you where to go. They don't know what's in your way.*
- **Voiceover**:
  *"For over two billion people worldwide living with visual impairments, navigating unfamiliar buildings is full of sudden surprises. Existing aids rely on static maps. But buildings change every day: furniture moves, cleaning carts block hallways, and doors get closed. Today, we introduce PathAble: an indoor assistant where vision directly changes the next navigation decision."*

---

### Scene 2: The Fast Loop — OpenCV 5 on Device (0:45 – 1:30)
- **Visuals**:
  - Close-up of the prototype rig: laptop in backpack, lightweight USB webcam on chest harness.
  - Picture-in-picture OpenCV 5 DNN overlay: YOLO11n-seg bounding boxes, segmentation masks, and floor contact point homography.
  - Split view showing Left / Centre / Right floor occupancy zones and ArUco marker junction tracking.
- **Voiceover**:
  *"PathAble uses a dual-loop agentic architecture. On the device, our fast loop runs completely offline using OpenCV 5's new DNN engine and USAC MAGSAC homography. In under 700 milliseconds, our deterministic decision table evaluates the floor plane: if a hazard is partial, it tells the user to step aside; if evidence is uncertain, it pauses or asks the user to turn and scan. Safety never waits on the network."*

---

### Scene 3: The Live Corridor Demo — Walking A to D with Reroute (1:30 – 2:30)
- **Visuals**:
  - Continuous footage of a blindfolded volunteer and spotter starting at Entrance (A), heading for Lab (D).
  - Volunteer arrives at Junction B. Camera detects full blockage towards Corridor C (chairs across corridor).
  - Audio plays live offline TTS: *"Route blocked. Turn left at this junction and take the corridor towards E."*
  - Graphical HUD shows Dijkstra dynamically recomputing the green path through nodes B $\rightarrow$ E $\rightarrow$ F $\rightarrow$ D.
  - Volunteer turns left, encounters a moving pedestrian: *"Please wait for the person to pass"* $\rightarrow$ resumes walking smoothly.
- **Voiceover**:
  *"Watch what happens when the corridor to the lab is blocked. PathAble doesn't just buzz or say 'obstacle'. It confirms the blockage over consecutive frames, marks that corridor impassable, recalculates an alternative route via Dijkstra, and speaks turn guidance. It is a living indoor route."*

---

### Scene 4: The Slow Loop — AWS Graviton with COOL & Human Approval (2:30 – 3:30)
- **Visuals**:
  - Screen recording of AWS Cloud architecture: S3 event bucket, Lambda, and EC2 Graviton instance running COOL.
  - Keyframes uploaded with faces automatically blurred for privacy.
  - Facilities approval dashboard: Staff receives an SNS alert, views measured corridor clearance and history, and clicks 'Approve Closure'.
  - DynamoDB updates map graph version from v13 to v14.
  - Next user starts at Entrance A: their phone fetches v14 and routes them via corridor E from the very start!
- **Voiceover**:
  *"While the user safely diverts, PathAble uploads blurred keyframes to AWS. Here, our slow loop runs on an AWS Graviton instance accelerated by COOL — the Cloud-Optimized OpenCV Library. The cloud agent checks persistence and clearance. When an obstruction is lasting, it requests facilities staff approval. Once approved, every future user is routed safely from the start."*

---

### Scene 5: Benchmark & Performance Results (3:30 – 4:20)
- **Visuals**:
  - Animated bar charts showing:
    1. COOL on Graviton3 vs Stock OpenCV on Graviton3 vs Stock OpenCV on x86 (Throughput FPS and Cost per 1,000 frames).
    2. 80 Scenario Trials: 92% detection recall, 95% route completion, 0 collisions.
    3. Latency distribution: 95th percentile at 152 ms, well within 700 ms budget.
  - Terminal showing benchmark script output and `cv.getBuildInformation()`.
- **Voiceover**:
  *"To prove our cloud performance, we benchmarked 300 identical keyframes across three EC2 architectures. Graviton3 running COOL achieved a 1.6x speedup over stock OpenCV on the same ARM hardware, and over 1.9x faster than x86, slashing cloud processing cost to less than half a cent per thousand frames."*

---

### Scene 6: Responsible AI, Standards & Conclusion (4:20 – 4:50)
- **Visuals**:
  - Reference to Malaysia Accessibility Code of Practice MS 1184:2014 for corridor width.
  - Volunteer removing blindfold, smiling with team members Lee Zhi Xiong and faculty mentor Dr. Mohd Nor Akmal Khalid at FTSM, UKM.
  - GitHub repository link and OpenCV AI Competition 2026 splash screen.
- **Voiceover**:
  *"PathAble adheres to universal design standards, strict privacy, and safety-first active perception. We don't replace the white cane — we empower it with vision that changes decisions. Thank you to OpenCV and AWS for empowering accessible mobility."*
