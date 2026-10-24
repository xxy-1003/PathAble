// PathAble Slow-Loop & Facilities Review Dashboard
// Real-time map graph rendering, ticket review, and trace inspector.

const NODE_POSITIONS = {
  "A": { x: 70, y: 70, label: "A (Entrance)" },
  "B": { x: 230, y: 70, label: "B (Junction)" },
  "C": { x: 410, y: 70, label: "C (Junction)" },
  "D": { x: 530, y: 70, label: "D (Lab)" },
  "E": { x: 230, y: 210, label: "E (Junction)" },
  "F": { x: 530, y: 210, label: "F (Junction)" }
};

let currentMapData = null;

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

    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", p1.x);
    line.setAttribute("y1", p1.y);
    line.setAttribute("x2", p2.x);
    line.setAttribute("y2", p2.y);
    line.setAttribute("stroke", edge.blocked ? "#ef4444" : "#10b981");
    line.setAttribute("stroke-width", edge.blocked ? "5" : "3");
    if (edge.blocked) {
      line.setAttribute("stroke-dasharray", "6,4");
    }
    svg.appendChild(line);

    // Edge label (distance)
    const midX = (p1.x + p2.x) / 2;
    const midY = (p1.y + p2.y) / 2;
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", midX + (p1.x === p2.x ? 8 : 0));
    text.setAttribute("y", midY - (p1.y === p2.y ? 8 : 0));
    text.setAttribute("fill", edge.blocked ? "#fca5a5" : "#94a3b8");
    text.setAttribute("font-size", "11px");
    text.setAttribute("font-weight", "600");
    text.setAttribute("text-anchor", "middle");
    text.textContent = `${edge.distance}m${edge.blocked ? " [BLOCKED]" : ""}`;
    svg.appendChild(text);
  });

  document.getElementById("map-edges-status").textContent = `${edges.length} Edges (${blockedCount} Blocked)`;
  if (blockedCount > 0) {
    document.getElementById("map-edges-status").className = "pill pill-warning";
  } else {
    document.getElementById("map-edges-status").className = "pill pill-success";
  }

  // Render Nodes
  Object.keys(NODE_POSITIONS).forEach(id => {
    const pos = NODE_POSITIONS[id];

    // Circle
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", pos.x);
    circle.setAttribute("cy", pos.y);
    circle.setAttribute("r", "16");
    circle.setAttribute("fill", "#1e293b");
    circle.setAttribute("stroke", "#38bdf8");
    circle.setAttribute("stroke-width", "2.5");
    svg.appendChild(circle);

    // Text ID
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", pos.x);
    text.setAttribute("y", pos.y + 4);
    text.setAttribute("fill", "#ffffff");
    text.setAttribute("font-size", "12px");
    text.setAttribute("font-weight", "bold");
    text.setAttribute("text-anchor", "middle");
    text.textContent = id;
    svg.appendChild(text);

    // Label below
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", pos.x);
    label.setAttribute("y", pos.y + 26);
    label.setAttribute("fill", "#94a3b8");
    label.setAttribute("font-size", "10px");
    label.setAttribute("text-anchor", "middle");
    label.textContent = pos.label.split(" ")[1] || "";
    svg.appendChild(label);
  });
}

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
          <span class="pill pill-warning">PENDING REVIEW</span>
        </div>
        <div class="ticket-grid">
          <div class="ticket-detail-item">
            <span class="ticket-label">Detected Obstacle</span>
            <span><strong>${t.detected_classes.join(", ") || "Furniture"}</strong></span>
          </div>
          <div class="ticket-detail-item">
            <span class="ticket-label">Measured Free Clearance</span>
            <span><strong>${t.measured_clearance_m} m</strong> (MS 1184 min: 1.20 m)</span>
          </div>
          <div class="ticket-detail-item">
            <span class="ticket-label">Associated Event</span>
            <span><code>${t.event_id}</code></span>
          </div>
          <div class="ticket-detail-item">
            <span class="ticket-label">Submitted At</span>
            <span>${new Date(t.created_at).toLocaleTimeString()} UTC</span>
          </div>
        </div>
        <div class="ticket-justification">
          <strong>Justification:</strong> ${t.justification}
        </div>
        <div class="ticket-actions">
          <input type="text" id="reviewer-${t.ticket_id}" class="reviewer-input" placeholder="Staff Name / ID" value="facilities-officer-01">
          <button class="btn btn-danger" onclick="reviewTicket('${t.ticket_id}', 'APPROVE')">Approve Closure</button>
          <button class="btn btn-success" onclick="reviewTicket('${t.ticket_id}', 'REJECT')">Reject &amp; Reopen</button>
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

const FIXTURES = {
  temp: {
    schema_version: "1.0.0",
    event_id: "evt-temp-" + Date.now().toString().slice(-4),
    client_id: "laptop-demo-01",
    timestamp: new Date().toISOString(),
    edge: { from_node: "B", to_node: "C" },
    current_node: "B",
    destination_node: "D",
    local_reroute: ["B", "E", "F", "D"],
    observations: {
      confidence: 0.90,
      obstacle_classes: ["person"],
      distance_band: "near",
      ground_contact_distance_m: 1.1,
      zone_occupancy: { left: "clear", centre: "occupied", right: "clear" },
      moving: true,
      consecutive_blocked_frames: 6
    },
    keyframes: [],
    privacy: { people_blurred_on_device: true, face_recognition_used: false, s3_lifecycle_days: 7 },
    map_version: 1
  },
  uncertain: {
    schema_version: "1.0.0",
    event_id: "evt-unc-" + Date.now().toString().slice(-4),
    client_id: "laptop-demo-01",
    timestamp: new Date().toISOString(),
    edge: { from_node: "B", to_node: "C" },
    current_node: "B",
    destination_node: "D",
    local_reroute: ["B", "E", "F", "D"],
    observations: {
      confidence: 0.75,
      obstacle_classes: ["chair"],
      distance_band: "near",
      ground_contact_distance_m: 1.4,
      zone_occupancy: { left: "clear", centre: "occupied", right: "occupied" },
      moving: false,
      consecutive_blocked_frames: 6
    },
    keyframes: [],
    privacy: { people_blurred_on_device: true, face_recognition_used: false, s3_lifecycle_days: 7 },
    map_version: 1
  },
  lasting_1: {
    schema_version: "1.0.0",
    event_id: "evt-last1-" + Date.now().toString().slice(-4),
    client_id: "laptop-demo-01",
    timestamp: new Date(Date.now() - 25 * 60 * 1000).toISOString(), // 25 mins ago
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
      consecutive_blocked_frames: 7
    },
    keyframes: [],
    privacy: { people_blurred_on_device: true, face_recognition_used: false, s3_lifecycle_days: 7 },
    map_version: 1
  },
  lasting_2: {
    schema_version: "1.0.0",
    event_id: "evt-last2-" + Date.now().toString().slice(-4),
    client_id: "laptop-demo-02",
    timestamp: new Date().toISOString(),
    edge: { from_node: "B", to_node: "C" },
    current_node: "B",
    destination_node: "D",
    local_reroute: ["B", "E", "F", "D"],
    observations: {
      confidence: 0.88,
      obstacle_classes: ["chair", "dining table"],
      distance_band: "near",
      ground_contact_distance_m: 0.85,
      zone_occupancy: { left: "occupied", centre: "occupied", right: "occupied" },
      moving: false,
      consecutive_blocked_frames: 8
    },
    keyframes: [],
    privacy: { people_blurred_on_device: true, face_recognition_used: false, s3_lifecycle_days: 7 },
    map_version: 1
  },
  conflict: {
    schema_version: "1.0.0",
    event_id: "evt-conf-" + Date.now().toString().slice(-4),
    client_id: "laptop-demo-01",
    timestamp: new Date().toISOString(),
    edge: { from_node: "B", to_node: "C" },
    current_node: "B",
    destination_node: "D",
    local_reroute: ["B", "E", "F", "D"],
    observations: {
      confidence: 0.65,
      obstacle_classes: ["chair"],
      distance_band: "medium",
      ground_contact_distance_m: 1.6,
      zone_occupancy: { left: "clear", centre: "occupied", right: "clear" },
      moving: false,
      consecutive_blocked_frames: 6
    },
    keyframes: [],
    privacy: { people_blurred_on_device: true, face_recognition_used: false, s3_lifecycle_days: 7 },
    map_version: 1
  }
};

async function postFixture(type) {
  const resultBox = document.getElementById("intake-result");
  resultBox.className = "result-box";
  resultBox.textContent = `Posting fixture ${type}...`;
  resultBox.classList.remove("hidden");

  try {
    const payload = FIXTURES[type];
    const res = await fetchJSON("/api/v1/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    resultBox.innerHTML = `<strong>Result:</strong> ${res.outcome} &middot; Map ${res.map_version} &middot; Ticket: ${res.ticket_id || "None"}<br><small>${res.justification}</small>`;
    await refreshAll();
  } catch (e) {
    resultBox.innerHTML = `<span style="color:#ef4444">Error: ${e.message}</span>`;
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
