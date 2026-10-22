"""Run a scripted, camera-free local decision trace from proposal v3."""

from pathlib import Path
from local_agent import LocalAgent, Observation, RouteMap


map_path = Path(__file__).resolve().parents[1] / "map_graph.json"
agent = LocalAgent(RouteMap.from_file(map_path), "A", "D")
print("Initial route:", " -> ".join(agent.current_route))

events = [
    Observation(0.0, None, 1.0, "clear", "clear", "clear", "far", node="A"),
    Observation(1.0, None, 1.0, "clear", "clear", "clear", "far", node="B"),
    Observation(2.0, "chair", 0.48, "unknown", "occupied", "unknown", "medium"),
]
events += [
    Observation(3.0 + i * 0.1, "chair", 0.82, "occupied", "occupied", "occupied", "near")
    for i in range(6)
]

for event in events:
    decision = agent.observe(event)
    print(f"{event.timestamp:.1f}s {decision.action}: {decision.message} "
          f"route={' -> '.join(decision.route)}")
