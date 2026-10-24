# PathAble v3: Baseline and Ablation Protocol

Conforms to Section 12.4 of the project proposal.

To demonstrate that PathAble's dynamic perception and agentic loops provide measurable navigation utility, the evaluation methodology defines strict baseline and ablation comparison procedures.

---

## 1. Baseline: Static-Map Navigation

### Definition
The baseline represents conventional indoor turn-by-turn navigation (e.g. BLE beacon or pre-mapped routing without obstacle vision).
- **Setup**: Identical six-node floor graph (Nodes A through F), identical start (A) and destination (D), and identical speech synthesis module.
- **Perception**: Completely disabled (camera frames ignored).
- **Navigation Behavior**: The system computes shortest Dijkstra path $A \rightarrow B \rightarrow C \rightarrow D$ and issues junction turn directions based solely on elapsed estimated distance or ArUco markers.
- **Evaluation Metric**:
  - Number of collisions or spotter safety stops when encountering the obstacle in corridor B–C.
  - Total time spent before the user is blocked.

### Hypothesis
Without perception, the static baseline guide will send $100\%$ of users directly into the blocked B–C corridor, requiring spotter intervention or cane collision. PathAble will achieve $0$ collisions and automatically divert users via E–F.

---

## 2. Ablation Study: Active Perception Removal

### Definition
PathAble's fast loop incorporates **active perception** (`WAIT_AND_REOBSERVE` and `TURN_TO_LOOK`). When evidence is unclear or moving, the agent actively pauses or prompts the user to rotate slightly to resolve ambiguity rather than making a premature commitment.

### Ablation Configuration ("Passive Navigation Agent")
- Remove `WAIT_AND_REOBSERVE` and `TURN_TO_LOOK` from `local_agent.py`.
- The decision table is restricted strictly to: `CONTINUE`, `STEP_ASIDE`, `REROUTE`, and `STOP_AND_ESCALATE`.
- Low-confidence frames ($0.40 \le \text{confidence} < 0.60$) or moving obstacles are treated as immediate full obstacles or ignored as noise.

### Evaluation Scenarios Tested in Ablation
1. **Moving Person (Scenario 6)**:
   - *Full PathAble*: Pauses for 3 seconds (`WAIT_AND_REOBSERVE`), allows person to pass, then resumes `CONTINUE`.
   - *Ablated Agent*: Instantly triggers `STEP_ASIDE` or premature `REROUTE`, disrupting the user.
2. **Side Clearance Unclear (Scenario 3 & 4)**:
   - *Full PathAble*: Prompts `"Turn slightly left so I can check that side"` (`TURN_TO_LOOK`), inspects zone, confirms clearance, and steps aside safely.
   - *Ablated Agent*: Forces immediate blind step aside into potentially hazardous wall or stops abruptly.

---

## 3. Cloud Time Compression Staging Protocol

Because lasting facilities blockages in real buildings occur over hours or days, staged time-compressed sequences are used for AWS cloud re-check evaluation:
1. **Temporary Sequence**:
   - Frame 1 ($t=0$): Delivery trolley momentarily placed in corridor.
   - Frame 2 ($t=3\text{ min}$): Trolley moved away; corridor empty.
   - Expected Cloud Classification: `TEMPORARY` (10-minute auto-expiry; no facilities ticket).
2. **Lasting Sequence**:
   - Frame 1 ($t=0$): Broken chair and desk placed across corridor.
   - Frame 2 ($t=20\text{ min}$): Identical static furniture detected in same location with clearance $<1.2\text{ m}$.
   - Expected Cloud Classification: `LASTING` (Amazon SNS notification dispatched to facilities approval dashboard).
3. **Uncertain Sequence**:
   - Frame 1 ($t=0$): Static box near margin threshold ($1.0\text{ m}$ clearance), no prior event history.
   - Expected Cloud Classification: `UNCERTAIN` (retains edge blocked locally; awaits second report before alerting human).
