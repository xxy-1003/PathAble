"""Map synchronization and versioning manager (Proposal Section 9.6).

Maintains authoritative shared map state, version counter, temporary expiry timers,
and junction synchronization endpoints.

Persistence: when ``persistence_path`` is supplied the full map state is written to
a JSON file after every version bump and restored on startup, so blocked-edge state
survives server / Lambda restarts.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


logger = logging.getLogger("pathable.cloud.map_sync")


DEFAULT_MAP_DATA = {
    "version": 1,
    "nodes": {
        "0": "A",
        "1": "B",
        "2": "C",
        "3": "D",
        "4": "E",
        "5": "F",
    },
    "edges": [
        {"from": "A", "to": "B", "distance": 12.0, "blocked": False},
        {"from": "B", "to": "C", "distance": 15.0, "blocked": False},
        {"from": "C", "to": "D", "distance": 12.0, "blocked": False},
        {"from": "B", "to": "E", "distance": 10.0, "blocked": False},
        {"from": "E", "to": "F", "distance": 24.0, "blocked": False},
        {"from": "F", "to": "D", "distance": 10.0, "blocked": False},
    ],
}


class MapSyncManager:
    """Manages authoritative map versioning and synchronisation with edge devices."""

    def __init__(
        self,
        initial_map_path: Optional[str | Path] = None,
        persistence_path: Optional[str | Path] = None,
    ):
        self._persistence_path: Optional[Path] = (
            Path(persistence_path) if persistence_path else None
        )

        # Try restoring persisted state first
        if self._persistence_path and self._persistence_path.exists():
            if self._load_state():
                return  # Successfully restored — skip default init

        if initial_map_path and Path(initial_map_path).exists():
            with open(initial_map_path, "r", encoding="utf-8") as f:
                self._map_data = json.load(f)
        else:
            self._map_data = copy.deepcopy(DEFAULT_MAP_DATA)

        self.version = self._map_data.get("version", 1)
        self.nodes = self._map_data["nodes"]
        self.edges = self._map_data["edges"]
        self._temporary_expiries: Dict[str, datetime] = {}
        self._edge_metadata: Dict[str, Dict[str, Any]] = {}
        self.last_updated_at = datetime.now(timezone.utc)

    def _edge_key(self, a: str, b: str) -> str:
        nodes = sorted([a, b])
        return f"{nodes[0]}-{nodes[1]}"

    def check_expiries(self, now: Optional[datetime] = None) -> bool:
        """Checks for expired temporary blockages and reopens them.

        Returns True if any edge was updated and map version was bumped.
        """
        current_time = now or datetime.now(timezone.utc)
        reopened = False

        for edge_key, expiry_time in list(self._temporary_expiries.items()):
            if current_time >= expiry_time:
                logger.info("Temporary block on edge %s expired at %s; reopening edge", edge_key, expiry_time)
                del self._temporary_expiries[edge_key]
                if self._set_edge_blocked_state(edge_key, False):
                    reopened = True

        if reopened:
            self._bump_version("Temporary block expiry reopen")

        return reopened

    def _set_edge_blocked_state(self, edge_key: str, blocked: bool) -> bool:
        changed = False
        parts = edge_key.split("-")
        a, b = parts[0], parts[1]
        for edge in self.edges:
            if (edge["from"] == a and edge["to"] == b) or (edge["from"] == b and edge["to"] == a):
                if edge.get("blocked", False) != blocked:
                    edge["blocked"] = blocked
                    changed = True
        return changed

    def _bump_version(self, reason: str = "") -> int:
        self.version += 1
        self._map_data["version"] = self.version
        self.last_updated_at = datetime.now(timezone.utc)
        logger.info("Map version bumped to %d (reason: %s)", self.version, reason)
        self._save_state()
        return self.version

    # ---- Persistence helpers ----

    def _save_state(self) -> None:
        """Atomically persist full map state to JSON so it survives restarts."""
        if not self._persistence_path:
            return
        state = {
            "version": self.version,
            "nodes": self.nodes,
            "edges": self.edges,
            "temporary_expiries": {
                k: v.isoformat() for k, v in self._temporary_expiries.items()
            },
            "edge_metadata": self._edge_metadata,
            "last_updated_at": self.last_updated_at.isoformat(),
        }
        tmp_path = self._persistence_path.with_suffix(".tmp")
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            # Atomic replace (os.replace is atomic on same filesystem)
            os.replace(str(tmp_path), str(self._persistence_path))
            logger.info("Map state persisted to %s (version %d)", self._persistence_path, self.version)
        except OSError:
            logger.warning("Failed to persist map state to %s", self._persistence_path, exc_info=True)

    def _load_state(self) -> bool:
        """Restore map state from a persisted JSON file.  Returns True on success."""
        if not self._persistence_path or not self._persistence_path.exists():
            return False
        try:
            with open(self._persistence_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.version = state["version"]
            self.nodes = state["nodes"]
            self.edges = state["edges"]
            self._map_data = {"version": self.version, "nodes": self.nodes, "edges": self.edges}
            self._temporary_expiries = {
                k: datetime.fromisoformat(v)
                for k, v in state.get("temporary_expiries", {}).items()
            }
            self._edge_metadata = state.get("edge_metadata", {})
            self.last_updated_at = datetime.fromisoformat(state["last_updated_at"])
            logger.info(
                "Map state restored from %s (version %d, %d active temporary blocks)",
                self._persistence_path,
                self.version,
                len(self._temporary_expiries),
            )
            return True
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning(
                "Corrupted map persistence file %s; falling back to defaults",
                self._persistence_path,
                exc_info=True,
            )
            return False

    def apply_temporary_block(
        self,
        from_node: str,
        to_node: str,
        expiry_minutes: int = 10,
        now: Optional[datetime] = None,
    ) -> int:
        """Marks edge blocked with a temporary time expiry (Section 9.3)."""
        current_time = now or datetime.now(timezone.utc)
        edge_key = self._edge_key(from_node, to_node)
        from datetime import timedelta
        expiry = current_time + timedelta(minutes=expiry_minutes)
        self._temporary_expiries[edge_key] = expiry
        changed = self._set_edge_blocked_state(edge_key, True)
        if changed:
            return self._bump_version(f"Temporary block on {edge_key} for {expiry_minutes}m")
        return self.version

    def apply_lasting_closure(self, from_node: str, to_node: str, ticket_id: str) -> int:
        """Closes edge permanently based on facilities human approval."""
        edge_key = self._edge_key(from_node, to_node)
        if edge_key in self._temporary_expiries:
            del self._temporary_expiries[edge_key]
        self._edge_metadata[edge_key] = {"closed_by_ticket": ticket_id, "closed_at": datetime.now(timezone.utc).isoformat()}
        changed = self._set_edge_blocked_state(edge_key, True)
        return self._bump_version(f"Lasting closure approved via ticket {ticket_id}")

    def reopen_edge(self, from_node: str, to_node: str, reason: str = "") -> int:
        """Reopens edge (e.g. after facilities rejection or maintenance cleared)."""
        edge_key = self._edge_key(from_node, to_node)
        if edge_key in self._temporary_expiries:
            del self._temporary_expiries[edge_key]
        if edge_key in self._edge_metadata:
            del self._edge_metadata[edge_key]
        changed = self._set_edge_blocked_state(edge_key, False)
        if changed:
            return self._bump_version(f"Reopened edge {edge_key}: {reason}")
        return self.version

    def get_map(self) -> Dict[str, Any]:
        """Returns the full map dictionary."""
        self.check_expiries()
        data = copy.deepcopy(self._map_data)
        data["version"] = self.version
        data["last_updated_at"] = self.last_updated_at.isoformat()
        return data

    def get_version_info(self) -> Dict[str, Any]:
        """Returns lightweight version check endpoint."""
        self.check_expiries()
        return {
            "version": self.version,
            "last_updated_at": self.last_updated_at.isoformat(),
            "active_temporary_blocks": len(self._temporary_expiries),
        }

    def is_edge_blocked(self, from_node: str, to_node: str, now: Optional[datetime] = None) -> bool:
        self.check_expiries(now=now)
        edge_key = self._edge_key(from_node, to_node)
        parts = edge_key.split("-")
        a, b = parts[0], parts[1]
        for edge in self.edges:
            if (edge["from"] == a and edge["to"] == b) or (edge["from"] == b and edge["to"] == a):
                return bool(edge.get("blocked", False))
        return False
