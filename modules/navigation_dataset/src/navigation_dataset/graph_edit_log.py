"""Append-only edit log for human viewpoint-graph (path) edits.

Every manual edit to a scene's viewpoint graph — add/delete node, add/delete edge,
rebuild edges, regenerate region, full build — is appended as one JSON line to
``<scene_dir>/graph_edit_history.jsonl``. The log is a permanent record (edits are
never removed from it, even if later undone in the graph) intended as training/
analysis data for improving the automatic path-generation algorithm: each event
carries the affected node/edge POSITIONS (ids are ephemeral) plus an "algorithm
view" (clearance, manual/auto provenance, feasibility verdict, local coverage) so
"human ≠ algorithm" decisions can be mined.

The graph helpers duck-type a ``ViewpointGraph`` (objects with ``.nodes`` /
``.edges`` whose items expose ``node_id`` / ``position`` / ``edge_id`` / ...), so
this module has no import dependency on viewpoint_graph and stays cheap + testable.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HISTORY_FILENAME = "graph_edit_history.jsonl"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pos2(position: Any) -> list[float] | None:
    if isinstance(position, (list, tuple)) and len(position) >= 2:
        try:
            return [float(position[0]), float(position[1])]
        except (TypeError, ValueError):
            return None
    return None


def _node_by_id(graph: Any, node_id: Any):
    for n in (getattr(graph, "nodes", None) or []):
        if getattr(n, "node_id", None) == node_id:
            return n
    return None


def _edge_by_id(graph: Any, edge_id: Any):
    for e in (getattr(graph, "edges", None) or []):
        if getattr(e, "edge_id", None) == edge_id:
            return e
    return None


def graph_size(graph: Any) -> dict[str, int]:
    return {
        "nodes": len(getattr(graph, "nodes", None) or []),
        "edges": len(getattr(graph, "edges", None) or []),
    }


def node_record(graph: Any, node_id: Any) -> dict[str, Any] | None:
    """Snapshot of a node (resolve BEFORE deletion). None if not present."""
    n = _node_by_id(graph, node_id)
    if n is None:
        return None
    return {
        "id": node_id,
        "position": _pos2(getattr(n, "position", None)),
        "clearance_m": float(getattr(n, "clearance_m", 0.0) or 0.0),
        "tags": list(getattr(n, "tags", None) or []),
        "extras": dict(getattr(n, "extras", None) or {}),
    }


def edge_record(graph: Any, edge_id: Any) -> dict[str, Any] | None:
    """Snapshot of an edge incl. both endpoint positions. None if not present."""
    e = _edge_by_id(graph, edge_id)
    if e is None:
        return None
    src = getattr(e, "source", None)
    tgt = getattr(e, "target", None)
    src_rec = node_record(graph, src)
    tgt_rec = node_record(graph, tgt)
    return {
        "id": edge_id,
        "source": src,
        "target": tgt,
        "source_pos": (src_rec or {}).get("position"),
        "target_pos": (tgt_rec or {}).get("position"),
        "distance_m": float(getattr(e, "distance_m", 0.0) or 0.0),
        "collision_free": bool(getattr(e, "collision_free", True)),
        "hazard_crossing": bool(getattr(e, "hazard_crossing", False)),
        "extras": dict(getattr(e, "extras", None) or {}),
    }


def nearest_node_distance(graph: Any, x: float, y: float, *, exclude: Iterable[str] = ()) -> float | None:
    """Distance (m) to the closest existing node — coverage signal for add_node
    ("did the sampler already cover this spot?"). None if the graph has no nodes."""
    ex = set(exclude or ())
    best: float | None = None
    for n in (getattr(graph, "nodes", None) or []):
        if getattr(n, "node_id", None) in ex:
            continue
        p = _pos2(getattr(n, "position", None))
        if p is None:
            continue
        d = math.hypot(p[0] - float(x), p[1] - float(y))
        if best is None or d < best:
            best = d
    return best


def append_graph_edit(scene_dir: str | Path, event: dict[str, Any], *, ts: str | None = None) -> bool:
    """Append one graph-edit event as a JSON line to the scene's history jsonl.

    Best-effort: stamps ``kind`` / ``timestamp`` / ``edit_id`` and writes. Never
    raises — a logging failure must never break the underlying graph edit. Returns
    True on success, False otherwise.
    """
    try:
        sdir = Path(scene_dir)
        stamp = ts or _utc_now_iso()
        digest = hashlib.sha1(
            f"{stamp}|{event.get('operation')}|{event.get('before')}|{event.get('after')}".encode("utf-8")
        ).hexdigest()[:10]
        record = {"kind": "graph_edit", "timestamp": stamp, "edit_id": f"gedit_{digest}", **event}
        sdir.mkdir(parents=True, exist_ok=True)
        with (sdir / HISTORY_FILENAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:  # noqa: BLE001 — logging is best-effort
        return False
