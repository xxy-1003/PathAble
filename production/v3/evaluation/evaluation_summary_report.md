# PathAble v3: Evaluation Results & Metrics Summary

**Data Status**: `SYNTHETIC_FIXTURE`
**Evaluation Date**: 2026-10-24

> [!IMPORTANT]
> **Pre-integration Verification Only**: The results below are computed from synthetic fixtures
> to validate metric pipelines. Measured physical trial evidence will be populated after
> branches are integrated and corridor testing is conducted.

## Summary Scorecard against Proposal Targets

| Metric | Proposal Target | Evaluated Value | Status |
| :--- | :---: | :---: | :---: |
| Obstacle Detection Recall | $\ge 0.90$ | 0.92 | PASS |
| Obstacle Detection Precision | $\ge 0.85$ | 0.92 | PASS |
| Decision Accuracy (80 trials) | $\ge 85\%$ | 100.0% | PASS |
| Route Completion (20 runs) | $\ge 90\%$ | 95.0% | PASS |
| Collisions | 0 | 0 | PASS |
| End-to-end Latency (p95) | $\le 700\text{ ms}$ | 152.42 ms | PASS |
| Escalation Recall | $\ge 0.90$ | 0.85 | FAIL |
| Cloud Classification Accuracy | $\ge 80\%$ | 100.0% | PASS |
| False Escalations to Facilities | $\le 1 \text{ in } 30$ | 0 | PASS |
| COOL Speedup (Graviton COOL vs Stock) | Report gain | 1.61x | MEASURED |

## COOL on AWS Graviton Comparative Performance

| Configuration | Median Latency (ms) | p95 Latency (ms) | Throughput (FPS) | Cost / 1k Frames (USD) |
| :--- | :---: | :---: | :---: | :---: |
| c7g.large (Graviton3) + COOL | 22.7 | 24.0 | 43.99 | $0.000457 |
| c7g.large (Graviton3) + Stock OpenCV 5 | 37.0 | 39.2 | 27.4 | $0.000733 |
| c7i.large (x86) + Stock OpenCV 5 | 46.0 | 48.0 | 22.22 | $0.001112 |
