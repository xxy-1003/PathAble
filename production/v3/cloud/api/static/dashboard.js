// PathAble Living Indoor Route & Physical Vision Simulation Dashboard
// Connects Fast Loop Physical Perception -> Multi-Frame Confirmation -> REROUTE -> AWS Slow Loop.

const NODE_POSITIONS = {
  "A": { x: 70, y: 70, label: "A (Entrance)" },
  "B": { x: 230, y: 70, label: "B (Junction)" },
  "C": { x: 410, y: 70, label: "C (Junction)" },
  "D": { x: 530, y: 70, label: "D (Lab)" },
  "E": { x: 230, y: 190, label: "E (Junction)" },
  "F": { x: 530, y: 190, label: "F (Junction)" }
};

let currentMapData = null;
let activeRoute = ["A", "B", "C", "D"];

async function fetchJSON(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || JSON.stringify(err));
  }
  return resp.json();
}

async function loadMap() {
  try {
    const data = await fetchJSON("/api/v1/map");
    currentMapData = data;
    document.getElementById("map-version").textContent = `v${data.version}`;
    renderGraph(data);
  } catch (e) {
    console.error("Failed to load map:", e);
  }
}

function renderGraph(mapData) {
  const svg = document.getElementById("map-svg");
  svg.innerHTML = "";

  const edges = mapData.edges || [];
  let blockedCount = 0;

  // Render Edges
  edges.forEach(edge => {
    const p1 = NODE_POSITIONS[edge.from];
    const p2 = NODE_POSITIONS[edge.to];
    if (!p1 || !p2) return;

    if (edge.blocked) blockedCount++;

    // Check if edge is on active route
    const onActiveRoute = isEdgeOnRoute(edge.from, edge.to, activeRoute);

    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", p1.x);
    line.setAttribute("y1", p1.y);
    line.setAttribute("x2", p2.x);
    line.setAttribute("y2", p2.y);

    let strokeColor = "#10b981"; // Passable green
    let strokeWidth = "3";
    let dash = "none";

    if (edge.blocked) {
      strokeColor = "#ef4444";
      strokeWidth = "5";
      dash = "6,4";
    } else if (onActiveRoute) {
      strokeColor = "#38bdf8";
      strokeWidth = "4.5";
    }

    line.setAttribute("stroke", strokeColor);
    line.setAttribute("stroke-width", strokeWidth);
    if (dash !== "none") line.setAttribute("stroke-dasharray", dash);
    svg.appendChild(line);

    // Distance label
    const midX = (p1.x + p2.x) / 2;
    const midY = (p1.y + p2.y) / 2;
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", midX + (p1.x === p2.x ? 10 : 0));
    text.setAttribute("y", midY - (p1.y === p2.y ? 8 : 0));
    text.setAttribute("fill", edge.blocked ? "#fca5a5" : (onActiveRoute ? "#38bdf8" : "#94a3b8"));
    text.setAttribute("font-size", "10px");
    text.setAttribute("font-weight", "600");
    text.setAttribute("text-anchor", "middle");
    text.textContent = `${edge.distance}m${edge.blocked ? " [BLOCKED]" : ""}`;
    svg.appendChild(text);
  });

  document.getElementById("map-edges-status").textContent = `${edges.length} Edges (${blockedCount} Blocked)`;
  document.getElementById("active-route-text").textContent = activeRoute.join(" -> ") + " (" + calculateRouteDistance(activeRoute, edges) + " m)";

  // Render Nodes
  Object.keys(NODE_POSITIONS).forEach(id => {
    const pos = NODE_POSITIONS[id];
    const isCurrent = activeRoute[0] === id;
    const isDest = activeRoute[activeRoute.length - 1] === id;

    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", pos.x);
    circle.setAttribute("cy", pos.y);
    circle.setAttribute("r", isCurrent || isDest ? "18" : "15");
    circle.setAttribute("fill", isCurrent ? "#0284c7" : "#1e293b");
    circle.setAttribute("stroke", isCurrent ? "#38bdf8" : "#64748b");
    circle.setAttribute("stroke-width", "2.5");
    svg.appendChild(circle);

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", pos.x);
    text.setAttribute("y", pos.y + 4);
    text.setAttribute("fill", "#ffffff");
    text.setAttribute("font-size", "11px");
    text.setAttribute("font-weight", "bold");
    text.setAttribute("text-anchor", "middle");
    text.textContent = id;
    svg.appendChild(text);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", pos.x);
    label.setAttribute("y", pos.y + 24);
    label.setAttribute("fill", "#94a3b8");
    label.setAttribute("font-size", "9px");
    label.setAttribute("text-anchor", "middle");
    label.textContent = pos.label.split(" ")[1] || "";
    svg.appendChild(label);
  });
}

function isEdgeOnRoute(from, to, route) {
  for (let i = 0; i < route.length - 1; i++) {
    if ((route[i] === from && route[i + 1] === to) || (route[i] === to && route[i + 1] === from)) {
      return true;
    }
  }
  return false;
}

function calculateRouteDistance(route, edges) {
  let total = 0;
  for (let i = 0; i < route.length - 1; i++) {
    const a = route[i], b = route[i + 1];
    const e = edges.find(ed => (ed.from === a && ed.to === b) || (ed.from === b && ed.to === a));
    if (e) total += e.distance;
  }
  return total;
}

// -------------------------------------------------------------
// PHYSICAL OBSTACLE ENCOUNTER SIMULATION (Fast Loop Frame-by-Frame)
// -------------------------------------------------------------
async function simulatePhysicalObstacleEncounter() {
  const box = document.getElementById("obstacle-box");
  const camStatus = document.getElementById("cam-status");
  const yoloLabel = document.getElementById("yolo-label");
  const distEl = document.getElementById("metric-dist");
  const covEl = document.getElementById("metric-coverage");
  const voiceAction = document.getElementById("voice-action");
  const voiceMsg = document.getElementById("voice-message");
  const speechBubble = document.getElementById("speech-bubble");
  const actionPill = document.getElementById("agent-action-pill");
  const dots = document.querySelectorAll("#buffer-meter .dot");

  // Step 1: User arrives at Junction B, initial detection
  camStatus.textContent = "Webcam 640x480 · 10 FPS · Facing Corridor B-C";
  box.classList.remove("hidden");
  yoloLabel.textContent = "chair 0.48";
  distEl.textContent = "1.8 m (Medium)";
  covEl.textContent = "22% (Lower 60%)";
  setZone("left", "unknown");
  setZone("centre", "occupied");
  setZone("right", "unknown");

  actionPill.className = "pill pill-warning";
  actionPill.textContent = "WAIT_AND_REOBSERVE";
  voiceAction.textContent = "Voice Guidance (Frame 1):";
  voiceMsg.textContent = '"Please wait while I check the path again."';
  speechBubble.className = "speech-bubble";

  await sleep(600);

  // Step 2: Multi-Frame Confirmation (6 consecutive frames over ring buffer)
  yoloLabel.textContent = "chair 0.85 · dining table 0.82";
  distEl.textContent = "0.9 m (Near)";
  covEl.textContent = "58% (Lower 60% Fully Blocked)";
  setZone("left", "occupied");
  setZone("centre", "occupied");
  setZone("right", "occupied");
  voiceMsg.textContent = '"Please wait while I check the blockage."';

  for (let i = 0; i < 6; i++) {
    dots[i].classList.add("dot-active");
    voiceAction.textContent = `Ring Buffer Confirmation (${i + 1}/6 Frames):`;
    await sleep(250);
  }

  // Step 3: Frame 6 confirmed -> REROUTE TRIGGERED ON DEVICE!
  actionPill.className = "pill pill-danger";
  actionPill.textContent = "REROUTE";
  speechBubble.className = "speech-bubble urgent";
  voiceAction.textContent = "Voice Guidance (Local Dijkstra Replanning):";
  voiceMsg.textContent = '"Route blocked. Take the corridor towards E."';

  // Local Dijkstra update: B -> E -> F -> D
  activeRoute = ["B", "E", "F", "D"];
  loadMap();

  camStatus.textContent = "[Privacy: cv.GaussianBlur applied] -> Emitting event evt-0193 to AWS Slow Loop...";
  await sleep(400);

  // Step 4: Dispatch Event to Cloud Intake
  try {
    const payload = {
      schema_version: "1.0.0",
      event_id: "evt-0193",
      client_id: "laptop-chest-mount-01",
      timestamp: new Date().toISOString(),
      edge: { from_node: "B", to_node: "C" },
      current_node: "B",
      destination_node: "D",
      local_reroute: ["B", "E", "F", "D"],
      observations: {
        confidence: 0.85,
        obstacle_classes: ["chair", "dining table"],
        distance_band: "near",
        ground_contact_distance_m: 0.9,
        zone_occupancy: { left: "occupied", centre: "occupied", right: "occupied" },
        moving: false,
        consecutive_blocked_frames: 6
      },
      keyframes: [
        {
          frame_id: "kf_01",
          filename: "chair_table_b_c_1.jpg",
          mime_type: "image/jpeg",
          people_blurred: true
        }
      ],
      privacy: { people_blurred_on_device: true, face_recognition_used: false, s3_lifecycle_days: 7 },
      map_version: currentMapData ? currentMapData.version : 1
    };

    const res = await fetchJSON("/api/v1/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    camStatus.textContent = `[AWS Slow-Loop Accepted] Outcome: ${res.outcome} · Map: v${res.map_version}`;
    await refreshAll();
  } catch (e) {
    console.error("Failed to post cloud event:", e);
  }
}

function resetToClearCorridor() {
  document.getElementById("obstacle-box").classList.add("hidden");
  document.getElementById("cam-status").textContent = "Webcam 640x480 · 10 FPS · Node A (Clear Corridor)";
  document.getElementById("metric-dist").textContent = "> 2.5 m (Far)";
  document.getElementById("metric-coverage").textContent = "0% (Lower 60%)";
  document.getElementById("agent-action-pill").className = "pill pill-success";
  document.getElementById("agent-action-pill").textContent = "CONTINUE";
  document.getElementById("speech-bubble").className = "speech-bubble";
  document.getElementById("voice-action").textContent = "Voice Guidance (pyttsx3):";
  document.getElementById("voice-message").textContent = "Path is clear. Proceeding towards Lab D.";

  setZone("left", "clear");
  setZone("centre", "clear");
  setZone("right", "clear");

  document.querySelectorAll("#buffer-meter .dot").forEach(d => d.classList.remove("dot-active"));
  activeRoute = ["A", "B", "C", "D"];
  loadMap();
}

function setZone(id, state) {
  const col = document.getElementById(`zone-${id}`);
  const val = document.getElementById(`zone-${id}-val`);
  col.className = `zone-col zone-${state}`;
  val.textContent = state;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// -------------------------------------------------------------
// Facilities Approval Queue & Decision Traces
// -------------------------------------------------------------
async function loadTickets() {
  try {
    const tickets = await fetchJSON("/api/v1/tickets");
    const container = document.getElementById("tickets-container");
    const countEl = document.getElementById("pending-ticket-count");

    const pending = tickets.filter(t => t.status === "PENDING");
    countEl.textContent = `${pending.length} Pending`;

    if (pending.length === 0) {
      container.innerHTML = `<p class="placeholder-text">No pending facilities tickets. All corridor edges are verified safe.</p>`;
      return;
    }

    container.innerHTML = pending.map(t => `
      <div class="ticket-card" id="card-${t.ticket_id}">
        <div class="ticket-header">
          <span class="ticket-title">Ticket ${t.ticket_id} · Edge ${t.edge.from_node}&ndash;${t.edge.to_node} Closure Request</span>
          <span class="pill pill-warning">PENDING FACILITIES SIGN-OFF</span>
        </div>
        <div class="ticket-grid">
          <div>
            <span class="ticket-label">Detected Obstacle</span>
            <span><strong>${t.detected_classes.join(", ") || "Furniture"}</strong></span>
          </div>
          <div>
            <span class="ticket-label">Measured Free Clearance</span>
            <span><strong>${t.measured_clearance_m} m</strong> (MS 1184 min: 1.20 m)</span>
          </div>
          <div>
            <span class="ticket-label">Event ID</span>
            <span><code>${t.event_id}</code></span>
          </div>
          <div>
            <span class="ticket-label">Submitted At</span>
            <span>${new Date(t.created_at).toLocaleTimeString()} UTC</span>
          </div>
        </div>
        <div class="ticket-justification">
          <strong>Bedrock Justification:</strong> ${t.justification}
        </div>
        <div class="ticket-actions">
          <input type="text" id="reviewer-${t.ticket_id}" class="reviewer-input" placeholder="Staff Name / ID" value="facilities-lead-01">
          <button class="btn btn-danger" onclick="reviewTicket('${t.ticket_id}', 'APPROVE')">Approve Closure (Close Edge &amp; Update Map)</button>
          <button class="btn btn-success" onclick="reviewTicket('${t.ticket_id}', 'REJECT')">Reject &amp; Reopen Corridor</button>
        </div>
      </div>
    `).join("");
  } catch (e) {
    console.error("Failed to load tickets:", e);
  }
}

async function reviewTicket(ticketId, action) {
  const reviewerInput = document.getElementById(`reviewer-${ticketId}`);
  const reviewerId = reviewerInput ? reviewerInput.value.trim() : "staff";
  try {
    const res = await fetchJSON(`/api/v1/tickets/${ticketId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: action,
        reviewer_id: reviewerId,
        notes: `Action taken via facilities review dashboard at ${new Date().toISOString()}`
      })
    });
    alert(res.message);
    await refreshAll();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

async function loadTraces() {
  try {
    const traces = await fetchJSON("/api/v1/traces?limit=15");
    const tbody = document.getElementById("traces-tbody");
    document.getElementById("trace-count").textContent = `${traces.length} Events`;

    if (traces.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-center">No trace events recorded yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = traces.slice().reverse().map(r => `
      <tr>
        <td><code>${new Date(r.timestamp).toLocaleTimeString()}</code></td>
        <td><code>${r.event_id}</code></td>
        <td><span class="pill">${r.component}</span></td>
        <td><strong>${r.action}</strong></td>
        <td><small>${JSON.stringify(r.details)}</small></td>
      </tr>
    `).join("");
  } catch (e) {
    console.error("Failed to load traces:", e);
  }
}

async function refreshAll() {
  await loadMap();
  await loadTickets();
  await loadTraces();
}

document.getElementById("btn-refresh").addEventListener("click", refreshAll);

// Initial load
refreshAll();
