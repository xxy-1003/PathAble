# PathAble recorded-keyframe COOL benchmark

This package times the v3 recorded-frame re-check pipeline in `../vision.py`:
YOLO11n-seg object evidence, Farneback motion evidence between keyframes in the
same sequence, and calibrated floor evidence when a verified camera/floor
calibration is supplied. It is an evidence re-check, not a navigation decision.

The repository currently contains no recorded 300-keyframe benchmark set or
AWS run results. Do not describe synthetic smoke output as recorded data, a
performance result, or a COOL speedup. `make_synthetic_inputs.py` exists only to
exercise the runner mechanics. The full run remains incomplete until all
configurations have processed an identical, hashed recorded manifest.

## Local smoke validation

Use the Python 3.11/3.12 environment and OpenCV 5 / NumPy setup already used by
`production/v3/requirements-vision.txt`. Download the YOLO11n-seg ONNX file as
described by the parent v3 README. From this directory:

```powershell
python make_synthetic_inputs.py
python run_benchmark.py --manifest synthetic_inputs/manifest.csv `
  --model ../models/yolo11n-seg.onnx --provider stock --dataset-label synthetic `
  --output runs/local-smoke --warmups 1 --runs 1 --build-label local-smoke
```

The local stock run is valid only if OpenCV provider evidence passes. It has no
AWS instance or AMI metadata and makes no cloud comparison. Run output is
ignored by Git. The synthetic label is persisted in `run.json`.

## Fallback when COOL Marketplace access is unavailable

The runner can still produce a stock-OpenCV baseline on a local machine with
the recorded 300-keyframe manifest. Keep the same model, frame order, image
resolution, OpenCV thread settings, and 3 warmup / 5 measured runs. For example:

```bash
python3 run_benchmark.py \
  --manifest /data/pathable/manifest.csv \
  --model ../models/yolo11n-seg.onnx \
  --provider stock \
  --dataset-label recorded \
  --build-label local-stock-opencv \
  --output runs/local-stock-recorded \
  --warmups 3 --runs 5
```

This is a **local stock baseline only**. Preserve its `run.json`, but do not pass
it to `compare_runs.py` as a COOL/Graviton comparison and do not claim a COOL
speedup. The comparison remains incomplete until a verified COOL run and a
stock run on the same Graviton instance type process the identical recorded
manifest. Synthetic smoke inputs remain mechanics-only and cannot replace the
recorded set.

If AWS Marketplace access is unavailable but the account can launch EC2, an
AWS-owned Amazon Linux 2023 Arm64 AMI can host the stock OpenCV configuration on
`c8g.large`. That is still only the stock side of the comparison; it does not
provide COOL. Confirm the account plan permits EC2 usage, then capture the
resolved AMI ID and launch-time price. AWS documents the public AL2023 AMI
families and their Arm64 naming here: [AL2023 on EC2](https://docs.aws.amazon.com/linux/al2023/ug/ec2.html).
The AWS Free account plan restricts access to some paid features and hardware,
so an AWS-owned AMI does not by itself bypass account-plan restrictions. See
[AWS Free Tier account plans](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html).

## Fixed recorded input set

Create one private dataset directory with exactly the same 300 recorded
keyframes for every configuration. Preserve privacy controls from the proposal
(people blurred before upload), retain original ordering, and write
`manifest.csv` with columns `sequence_id,timestamp_s,path`. Timestamps must
increase within each sequence. The runner hashes the manifest and every input;
`compare_runs.py` refuses comparisons with different hashes, incomplete runs,
unverified provider evidence, or mismatched Graviton instance types.

Use a local copy or S3 download staged on each benchmark host. Do not change
resolution, frame order, model, thresholds, OpenCV thread settings, or process
limits between configurations. Record any intentional change as a separate
configuration and do not mix it into the primary comparison.

## Per-configuration run

Run from this directory. Supply explicit rates only after verifying them for
the selected region, instance type, Marketplace entitlement, and run date.
Rates are optional; unless both the EC2 and Marketplace hourly rates are
provided, cost per 1,000 frames is null. The reported
estimate is `(EC2 hourly + Marketplace hourly) / measured frames per second / 3600
* 1000`; EBS, data transfer, taxes, and other services are excluded.

```bash
python3 run_benchmark.py \
  --manifest /data/pathable/manifest.csv \
  --model ../models/yolo11n-seg.onnx \
  --provider cool --cool-version "$COOL_VERSION" \
  --dataset-label recorded \
  --build-label "$BUILD_LABEL" \
  --output runs/cool-graviton \
  --warmups 3 --runs 5 \
  --ec2-hourly-usd "$EC2_HOURLY_USD" \
  --marketplace-hourly-usd "$MARKETPLACE_HOURLY_USD"
```

Repeat with `--provider stock`, the same manifest/model/options and a
stock-OpenCV Python environment on the same Graviton instance type. Run
`--provider stock` on the planned x86 instance only if capacity is available;
otherwise mark that configuration unavailable in the report. A stock run on a
different Graviton generation is not a same-hardware comparison.

For a floor evidence run, pass the verified camera and floor JSON files and
`--same-pose-verified`. To calculate side-passage estimates, also provide
`--corridor-x-limits-m LEFT RIGHT` measured in the floor calibration's x axis.
The parent v3 calibration checks remain authoritative. Without the verified
camera, floor, and same-pose flag, object distances and floor spans are
`unknown`. Projected box-edge span and side-passage values are approximate
geometric evidence, not remaining route clearance certification or a compliance
decision. Motion is a fixed-camera heuristic (per-object ROI flow
minus frame median); report it as evidence, not ground truth.

## Comparison and report

```bash
python3 compare_runs.py \
  --cool-graviton runs/cool-graviton/run.json \
  --stock-graviton runs/stock-graviton/run.json \
  --stock-x86 runs/stock-x86/run.json \
  --output runs/comparison.json
```

Omit `--stock-x86` if no x86 run was completed. The runner reports median and
p95 per-keyframe latency, median full-run throughput, and cost assumptions.
The comparison script only verifies comparability; it does not manufacture a
gain figure. State the observed values and their run status. If any primary
configuration is missing, label the overall comparison incomplete and make no
performance-gain claim.

## Exact AWS execution checklist

1. Confirm AWS account, region, service quotas, instance availability, and
   Marketplace entitlement. Do not launch an instance or subscribe to/install a
   Marketplace AMI until the project owner approves the estimated charges.
2. The proposal names `c7g.large` and COOL. Confirm the currently available
   COOL AMI version supports the selected Graviton instance. The current
   [AWS Marketplace listing](https://aws.amazon.com/marketplace/pp/prodview-fdvbfiewzuehs)
   advertises Graviton4-compatible families such as c8g, m8g and r8g; if c7g
   is unsupported, use a supported Graviton type for both same-hardware runs
   and document the deviation from the proposal. Listings can change; record
   the exact AMI ID, Marketplace product/version,
   COOL version, region, instance type, and displayed price at run time.
3. Prepare the same AMI/OS and Python version for both same-instance Graviton
   configurations where feasible. Install stock OpenCV only in its own clean
   environment; never overwrite the COOL environment. The COOL provider check
   requires `cv2.__file__` to resolve beneath `COOL_ROOT` (default
   `/opt/cool`). Preserve full `cv2.getBuildInformation()` in every record.
4. Place the same model and byte-identical fixed keyframes on each host. Set
   `BENCH_INSTANCE_TYPE`, `BENCH_AMI_ID` only if IMDSv2 metadata is unavailable;
   set `COOL_VERSION` for COOL. Confirm these values in the output before
   accepting a run.
5. Run each configuration with 3 warmups and 5 measured full-manifest passes.
   Save `run.json` outside the source tree. Stop instances after the final
   configuration and retain provider/build/output evidence with the report.
6. Run `compare_runs.py`. If it exits nonzero, resolve the listed blockers or
   publish the results as incomplete with no gain claim. Add x86 only when
   resources are available and label it as the planned baseline.

The benchmark records AMI and instance metadata via EC2 IMDSv2 when available.
Marketplace product listings currently describe COOL as a Graviton-optimized
OpenCV 5 distribution; the exact compatible generations and rates must be
checked against the chosen Marketplace version when the run is approved.
