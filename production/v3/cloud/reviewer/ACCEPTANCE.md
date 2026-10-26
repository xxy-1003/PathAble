# Acceptance and evidence — 25 October 2026

## Actually performed

- **16 focused Node behaviour tests passed.** Includes pending intake, approval,
  rejection, action lock, lost-response identical retry, refresh reconciliation,
  stale/conflicting map versions, saved-review/map-read partial failure, unknown
  measurements, unsupported responses, encoded pagination, endpoint restrictions,
  bearer handling, safe errors and browser-compatible fetch invocation.
- **Six HTTP contract checks passed** against Person 2's actual backend app at
  `63de1ad`, using localhost memory storage and synthetic evidence: report intake
  leaves map unchanged; duplicate report returns same ticket; isolated rejection
  does not update map; dashboard controller approval fetches full updated map;
  duplicate review does not increment again; changed terminal review returns 409.
- **Chrome interface checks performed:** fixture pending report/image, fixture
  approval to version 2, fresh fixture rejection leaving version 1; actual local
  API report/image, approval, returned `local-reviewer` identity and map version 2;
  fixture request failure left report PENDING with a stale map and offered identical
  retry; recovery through that retry reached version 2.
- Desktop screenshots inspected. Labels, unknown values, image, selected report,
  review buttons and map status were visible. Mobile layout, assistive technology,
  live JWT authorisation and expired real S3 URLs have not been browser-tested.
- JavaScript syntax checks and `git diff --check` passed.

Initial local preview access failed under the restricted process environment;
restarting only the test preview with local network access resolved it. Browser
testing then found a native fetch receiver issue and it was fixed, with a regression
test added. Neither issue was replaced with an assumed passing result.

## Required coordinated live tests

These are **NOT RUN end to end on AWS**. Local tests above do not satisfy the live
camera, durability, laptop or audible-recording gates.

| Case | Procedure and required observation | Actual result / remaining evidence |
| --- | --- | --- |
| A — empty region | Person 1 shows empty camera region; no qualifying report and no route change | NOT RUN in this workstream; live camera/client check required |
| B — chair outside | Show chair outside configured region; no qualifying overlap report or route change | NOT RUN; prior local recordings are baseline only |
| C — chair inside | One event/image reaches private AWS storage; dashboard shows PENDING; shared map unchanged | Local synthetic intake/map checks PASS; real camera → AWS NOT RUN |
| D — approval | Reviewer inspects image and approves; durable review/closure and new map version; laptop changes B-C-D to B-E-F-D; announcement heard | Local dashboard/API approval PASS; AWS durability, laptop and audible speech NOT RUN |
| E — rejection | Fresh isolated map/case; reject report; no approved closure is created from it | Fresh fixture rejection and local API rejection PASS; AWS case NOT RUN |
| F — duplicate/retry | Reuse identical event; same ticket; retry identical review; one version increment | Actual local API duplicate checks PASS; live AWS retry NOT RUN |
| G — connection failure | Fail a request; visible error; no invented approval or sync success; reconcile/retry | Browser fixture failure and controller lost-response/partial-failure tests PASS; deployed network/laptop check NOT RUN |

Record event/ticket IDs, before/after versions, service storage and reviewer identity
for each permitted live case. Never record tokens or full signed URLs. Person 2
checks durable reads from a fresh process; Person 1 verifies map application and
speech. A storage label or successful health response does not prove persistence.

## Local screenshot references

Kept outside Git in the parent project's `outputs/person3-review-dashboard/`:

- `local-api-approved.png`: local report/unknown measurements and map version 2;
  synthetic gray evidence. Does not prove AWS or a real obstruction.
- `local-api-approved-overview.png`: LOCAL API / NOT AWS banner and confirmed local
  approval status. Does not prove laptop receipt or speech.
- `fixture-connection-failure.png`: viewport captured during fixture failure testing;
  the DOM confirmed PENDING/error/retry. This cropped viewport alone does not show
  all failure indicators and is not sufficient proof of the complete failure state.
- `fixture-failure-dom.txt`: final browser state confirms the visible failure alert,
  PENDING ticket, disabled decisions, STALE map and available identical retry.
- `node-tests.txt`: final 16-test focused run output.

No final end-to-end recording has been made. Existing camera/local reroute recordings
in the integration branch remain baseline material; none was reclassified as AWS
evidence. Screenshots and recordings remain local, outside this source commit.

Baseline recording references from
[`camera_demo_evidence_2026-10-25.md`](../../evaluation/camera_demo_evidence_2026-10-25.md):
`20261025-0755-30.7477509.mp4` (manual confirmation/local proposed reroute),
`20261025-0811-19.2103612.mp4` (inside-region local camera demo), and
`20261025-0815-57.3810564.mp4` (outside-region local demo). These original files
were not replayed or audio-verified in this dashboard workstream. Their existing
evidence note does not establish the new AWS human-review workflow.

## Final demonstration instructions (pending live integration)

Title: **Camera report → AWS human review → shared-map update → route replanning.**

1. With Persons 1 and 2, verify the approved HTTPS endpoint, reviewer sign-in,
   exact camera assignment B / B–C, private image access, agreed retention and
   isolated starting map. Ensure all people/images have appropriate privacy handling.
2. Enable system/microphone recording audio. Make and listen to a short test
   recording before the actual run. A “speech completed” status is not audio proof.
3. Show the actual camera and detection region completely. Introduce the chair
   inside the region. Show the single event/ticket arriving in the API-connected
   dashboard as PENDING, with image. Show unchanged map and no cloud-approved reroute.
4. Inspect the evidence, add notes and approve. Capture the confirmed review status,
   returned reviewer identity and authoritative B–C closure/new map version.
5. Show the laptop receiving that same version, changing B-C-D to B-E-F-D and
   speaking the route. Play the recording back and confirm the announcement is heard.
6. Save the original recording locally with date, ticket ID, tested commits and
   observed failures. Run rejection separately from a fresh isolated case. Obtain
   explicit team approval before any evidence upload or sharing.

Do not claim autonomous corridor-clearance verification, moving-user localisation
or certified safe walking guidance. No Bedrock, COOL or junction-marker localisation
is part of this demonstration.
