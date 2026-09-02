"""Daemonless candidate algorithms and metrics for executable support graphs.

This module deliberately has no writer for production scene sidecars.  The
normalizer is injected into :func:`build_navigation_support` by an offline lab
and records the three conceptual stages used by that lab:

* raw blueprint-induced support;
* global support consolidation;
* global executable stitching.

Blueprint ids are provenance, never a graph partitioning predicate.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from copy import deepcopy
from hashlib import sha1
import json
import math
import random
from typing import Any, Iterable, Mapping, Sequence

from .route_motion import _distance, _world_segment_safe, _yaw_to
from .traversability import TraversabilityGrid


LAB_SCHEMA_VERSION = "opticalnav.support_network_lab.v1"
ALGORITHM_ID = "global_executable_network_v2"


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha1(encoded.encode("utf-8")).hexdigest()


def _pose_id(pose: Mapping[str, Any]) -> str:
    return str(pose.get("motion_pose_id") or pose.get("motion_node_id") or pose.get("node_id") or "")


def _spatial_pairs(
    poses: Mapping[str, Mapping[str, Any]],
    radius: float,
) -> list[tuple[float, str, str]]:
    """Return deterministic pairs inside ``radius`` using a spatial hash."""
    if radius <= 0:
        return []
    buckets: dict[tuple[int, int], list[str]] = defaultdict(list)
    for pose_id, pose in sorted(poses.items()):
        x, y = (float(value) for value in pose["position"][:2])
        buckets[(math.floor(x / radius), math.floor(y / radius))].append(pose_id)
    pairs: list[tuple[float, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source, pose in sorted(poses.items()):
        x, y = (float(value) for value in pose["position"][:2])
        cell = (math.floor(x / radius), math.floor(y / radius))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for target in buckets.get((cell[0] + dx, cell[1] + dy), []):
                    pair = tuple(sorted((source, target)))
                    if source == target or pair in seen:
                        continue
                    seen.add(pair)
                    distance = _distance(poses[pair[0]]["position"], poses[pair[1]]["position"])
                    if distance < radius - 1e-9:
                        pairs.append((distance, pair[0], pair[1]))
    return sorted(pairs, key=lambda item: (item[0], item[1], item[2]))


def _portal_sets(
    pose_ids: Iterable[str],
    edges: Iterable[Mapping[str, Any]],
) -> dict[str, set[str]]:
    result = {pose_id: set() for pose_id in pose_ids}
    for edge in edges:
        portals = {str(value) for value in edge.get("portal_ids") or [] if str(value)}
        for pose_id in (str(edge.get("source") or ""), str(edge.get("target") or "")):
            if pose_id in result:
                result[pose_id].update(portals)
    return result


def _portals_compatible(left: set[str], right: set[str]) -> bool:
    # Empty means an ordinary open-grid sample.  A portal-adjacent sample can
    # join it when the restored motion grid certifies the direct segment.  Two
    # explicitly different portals must never be conflated.
    return not left or not right or bool(left & right)


def _pose_priority(pose_id: str, pose: Mapping[str, Any]) -> tuple[int, int, str]:
    tags = {str(value) for value in pose.get("tags") or []}
    return (
        0 if pose.get("anchor_node_ids") else 1,
        0 if tags & {"portal", "junction", "patch"} else 1,
        pose_id,
    )


def _source_blueprints(
    edge: Mapping[str, Any],
    blueprint_ids_by_place_edge: Mapping[str, set[str]],
) -> set[str]:
    owners = {str(value) for value in edge.get("source_blueprint_ids") or [] if str(value)}
    for place_edge_id in edge.get("place_edge_ids") or []:
        owners.update(blueprint_ids_by_place_edge.get(str(place_edge_id), set()))
    return owners


def _stage_payload(
    stage: str,
    poses: Mapping[str, Mapping[str, Any]],
    edges: Mapping[str, Mapping[str, Any]],
    anchor_poses: Mapping[str, set[str]],
    path_sequences: Sequence[Sequence[str]],
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": LAB_SCHEMA_VERSION,
        "algorithm_id": ALGORITHM_ID,
        "stage": stage,
        "poses": [deepcopy(poses[key]) for key in sorted(poses)],
        "nodes": [deepcopy(poses[key]) for key in sorted(poses)],
        "edges": [deepcopy(edges[key]) for key in sorted(edges)],
        "anchor_pose_ids": {key: sorted(value) for key, value in sorted(anchor_poses.items())},
        "path_sequences": [list(value) for value in path_sequences],
        "diagnostics": dict(diagnostics or {}),
    }


class _DisjointSet:
    def __init__(self, values: Iterable[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: str, right: str) -> bool:
        left, right = self.find(left), self.find(right)
        if left == right:
            return False
        self.parent[max(left, right)] = min(left, right)
        return True


class GlobalExecutableNetworkNormalizer:
    """Pairwise consolidation followed by provenance-independent stitching."""

    algorithm_id = ALGORITHM_ID

    def __init__(self) -> None:
        self.raw_support: dict[str, Any] | None = None
        self.consolidated_support: dict[str, Any] | None = None
        self.executable_support: dict[str, Any] | None = None

    def __call__(
        self,
        poses: dict[str, dict[str, Any]],
        edges: dict[str, dict[str, Any]],
        anchor_poses: dict[str, set[str]],
        path_sequences: list[list[str]],
        *,
        motion_grid: TraversabilityGrid,
        config: Mapping[str, Any],
        blueprint_ids_by_place_edge: Mapping[str, set[str]],
    ) -> dict[str, Any]:
        raw_poses = {key: deepcopy(value) for key, value in poses.items()}
        raw_edges = {key: deepcopy(value) for key, value in edges.items()}
        raw_anchors = {key: set(value) for key, value in anchor_poses.items()}
        raw_sequences = [list(value) for value in path_sequences]
        raw_pose_blueprints: dict[str, set[str]] = defaultdict(set)
        for edge in raw_edges.values():
            owners = _source_blueprints(edge, blueprint_ids_by_place_edge)
            edge["source_blueprint_ids"] = sorted(owners)
            raw_pose_blueprints[str(edge["source"])].update(owners)
            raw_pose_blueprints[str(edge["target"])].update(owners)
        for pose_id, pose in raw_poses.items():
            pose["blueprint_ids"] = sorted(raw_pose_blueprints[pose_id])
        self.raw_support = _stage_payload(
            "raw_blueprint_induced_support", raw_poses, raw_edges,
            raw_anchors, raw_sequences,
        )

        merge_radius = float(config.get("hard_merge_radius_m", config["min_pose_spacing_m"]))
        # Short links are legal now, so a merge that shortens a chord below the
        # old fixed step is no longer automatically invalid.
        action_min = float(config.get("min_link_distance_m", float(config["forward_step_m"]) - float(config["forward_tolerance_m"])))
        action_max = float(config["forward_step_m"]) + float(config["forward_tolerance_m"])
        raw_edge_rows = [raw_edges[key] for key in sorted(raw_edges)]
        portals = _portal_sets(raw_poses, raw_edge_rows)
        spatial_pairs = _spatial_pairs(raw_poses, merge_radius)
        neighbors: dict[str, list[str]] = defaultdict(list)
        for _distance_m, left, right in spatial_pairs:
            neighbors[left].append(right)
            neighbors[right].append(left)

        def representative_for(members: set[str]) -> str:
            return min(
                members,
                key=lambda pose_id: (
                    _pose_priority(pose_id, raw_poses[pose_id]),
                    sum(_distance(raw_poses[pose_id]["position"], raw_poses[item]["position"]) for item in members),
                    pose_id,
                ),
            )

        # Build local star-shaped subclusters rather than one transitive DSU
        # component. Parallel lattice phases are proposed atomically at all
        # neighbouring samples, while a 0.10+0.10 m chain can no longer drag
        # endpoints 0.20 m apart into one all-or-nothing set.
        provisional_groups: list[set[str]] = []
        unassigned = set(raw_poses)
        for seed in sorted(raw_poses, key=lambda value: _pose_priority(value, raw_poses[value])):
            if seed not in unassigned:
                continue
            group = {seed}
            for member in sorted(neighbors.get(seed, []), key=lambda value: _pose_priority(value, raw_poses[value])):
                if member not in unassigned:
                    continue
                if not _portals_compatible(portals[seed], portals[member]):
                    continue
                if not _world_segment_safe(
                    motion_grid,
                    tuple(raw_poses[seed]["position"][:2]),
                    tuple(raw_poses[member]["position"][:2]),
                ):
                    continue
                group.add(member)
            provisional_groups.append(group)
            unassigned -= group

        def mapping_for(groups: Sequence[set[str]]) -> tuple[dict[str, str], dict[str, int]]:
            result: dict[str, str] = {}
            group_for_pose: dict[str, int] = {}
            for index, members in enumerate(groups):
                representative = representative_for(members)
                for member in members:
                    result[member] = representative
                    group_for_pose[member] = index
            return result, group_for_pose

        def invalid_edges(candidate_mapping: Mapping[str, str]) -> list[tuple[str, str]]:
            invalid: list[tuple[str, str]] = []
            for edge in raw_edge_rows:
                source_raw, target_raw = str(edge["source"]), str(edge["target"])
                source, target = candidate_mapping[source_raw], candidate_mapping[target_raw]
                if source == target:
                    continue
                distance = _distance(raw_poses[source]["position"], raw_poses[target]["position"])
                if not (action_min - 1e-9 <= distance <= action_max + 1e-9):
                    invalid.append((source_raw, target_raw))
                    continue
                if not _world_segment_safe(
                    motion_grid,
                    tuple(raw_poses[source]["position"][:2]),
                    tuple(raw_poses[target]["position"][:2]),
                ):
                    invalid.append((source_raw, target_raw))
            return invalid

        # Validate every proposed subcluster under one simultaneous mapping.
        # On failure peel one member from only the implicated group. Unrelated
        # valid subclusters in the same spatial component remain merged.
        groups = [set(value) for value in provisional_groups]
        split_count = 0
        while True:
            mapping, group_for_pose = mapping_for(groups)
            invalid = invalid_edges(mapping)
            if not invalid:
                break
            implicated: Counter[int] = Counter()
            member_pressure: Counter[str] = Counter()
            for source_raw, target_raw in invalid:
                for pose_id in (source_raw, target_raw):
                    group_id = group_for_pose[pose_id]
                    if len(groups[group_id]) > 1:
                        implicated[group_id] += 1
                        member_pressure[pose_id] += 1
            if not implicated:
                raise ValueError("support_lab_original_graph_invalid")
            group_id = min(
                implicated,
                key=lambda value: (-implicated[value], -len(groups[value]), sorted(groups[value])),
            )
            members = groups[group_id]
            representative = representative_for(members)
            removable = sorted(
                members,
                key=lambda value: (
                    0 if value != representative else 1,
                    -member_pressure[value],
                    -_distance(raw_poses[representative]["position"], raw_poses[value]["position"]),
                    value,
                ),
            )[0]
            groups[group_id] = members - {removable}
            groups.append({removable})
            split_count += 1

        mapping, _group_for_pose = mapping_for(groups)
        rejected_pairs: list[tuple[str, str, str]] = []
        merge_rejections: Counter[str] = Counter()
        for _distance_m, left_raw, right_raw in spatial_pairs:
            if mapping[left_raw] == mapping[right_raw]:
                continue
            if not _portals_compatible(portals[left_raw], portals[right_raw]):
                reason = "portal"
            elif not _world_segment_safe(
                motion_grid,
                tuple(raw_poses[left_raw]["position"][:2]),
                tuple(raw_poses[right_raw]["position"][:2]),
            ):
                reason = "collision"
            else:
                reason = "action_chord"
            merge_rejections[reason] += 1
            rejected_pairs.append((left_raw, right_raw, reason))
        members_by_final: dict[str, list[str]] = defaultdict(list)
        for raw_id, final_id in mapping.items():
            members_by_final[final_id].append(raw_id)
        consolidated_poses: dict[str, dict[str, Any]] = {}
        for final_id, members in sorted(members_by_final.items()):
            pose = deepcopy(raw_poses[final_id])
            pose["motion_node_id"] = final_id
            pose["motion_pose_id"] = final_id
            pose["source_motion_pose_ids"] = sorted(members)
            pose["source_pose_ids"] = sorted(members)
            pose["merge_kind"] = "hard" if len(members) > 1 else "native"
            pose["tags"] = sorted({
                str(value) for member in members for value in raw_poses[member].get("tags") or []
            })
            pose["anchor_node_ids"] = sorted({
                str(value) for member in members
                for value in raw_poses[member].get("anchor_node_ids") or []
            })
            pose["blueprint_ids"] = sorted({
                str(value) for member in members
                for value in raw_poses[member].get("blueprint_ids") or []
            })
            consolidated_poses[final_id] = pose

        consolidated_edges: dict[str, dict[str, Any]] = {}
        chord_index: dict[tuple[str, str, str], str] = {}
        collapsed_edge_count = 0
        for raw_edge in raw_edge_rows:
            source, target = mapping[str(raw_edge["source"])], mapping[str(raw_edge["target"])]
            if source == target:
                collapsed_edge_count += 1
                continue
            distance = _distance(consolidated_poses[source]["position"], consolidated_poses[target]["position"])
            if not (action_min - 1e-9 <= distance <= action_max + 1e-9):
                raise ValueError(f"support_lab_non_action_chord:{raw_edge['motion_edge_id']}:{distance:.5f}")
            if not _world_segment_safe(
                motion_grid,
                tuple(consolidated_poses[source]["position"][:2]),
                tuple(consolidated_poses[target]["position"][:2]),
            ):
                raise ValueError(f"support_lab_unsafe_chord:{raw_edge['motion_edge_id']}")
            key = (source, target, str(raw_edge.get("action") or "move_forward"))
            owners = _source_blueprints(raw_edge, blueprint_ids_by_place_edge)
            if key in chord_index:
                edge = consolidated_edges[chord_index[key]]
                edge["source_motion_edge_ids"] = sorted(set(edge.get("source_motion_edge_ids") or []) | {str(raw_edge["motion_edge_id"])})
                edge["place_edge_ids"] = sorted(set(edge.get("place_edge_ids") or []) | {str(value) for value in raw_edge.get("place_edge_ids") or [] if str(value)})
                edge["portal_ids"] = sorted(set(edge.get("portal_ids") or []) | {str(value) for value in raw_edge.get("portal_ids") or [] if str(value)})
                edge["source_blueprint_ids"] = sorted(set(edge.get("source_blueprint_ids") or []) | owners)
                collapsed_edge_count += 1
                continue
            edge = deepcopy(raw_edge)
            edge["source"], edge["target"], edge["distance_m"] = source, target, distance
            edge["source_motion_edge_ids"] = [str(raw_edge["motion_edge_id"])]
            edge["source_blueprint_ids"] = sorted(owners)
            consolidated_edges[str(edge["motion_edge_id"])] = edge
            chord_index[key] = str(edge["motion_edge_id"])

        anchor_poses.clear()
        for pose_id, pose in consolidated_poses.items():
            for anchor_id in pose.get("anchor_node_ids") or []:
                anchor_poses[str(anchor_id)].add(pose_id)

        # Residual soft clusters are derived only from pairs which remain
        # distinct after the greedy valid subclusters have been accepted.
        residual_pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
        for left_raw, right_raw, reason in rejected_pairs:
            left, right = mapping[left_raw], mapping[right_raw]
            if left != right:
                residual_pairs[tuple(sorted((left, right)))].add(reason)
        residual_dsu = _DisjointSet(consolidated_poses)
        for left, right in residual_pairs:
            residual_dsu.union(left, right)
        residual_members: dict[str, set[str]] = defaultdict(set)
        for left, right in residual_pairs:
            residual_members[residual_dsu.find(left)].update((left, right))
        soft_clusters: list[dict[str, Any]] = []
        for index, members in enumerate(sorted(residual_members.values(), key=lambda value: sorted(value)), 1):
            cluster_id = f"soft_cluster_{index:03d}"
            reasons = sorted({
                reason for pair, pair_reasons in residual_pairs.items()
                if set(pair) <= members for reason in pair_reasons
            })
            for pose_id in members:
                consolidated_poses[pose_id]["soft_cluster_id"] = cluster_id
            soft_clusters.append({
                "cluster_id": cluster_id,
                "member_motion_pose_ids": sorted(members),
                "reasons": reasons,
            })

        remapped_sequences: list[list[str]] = []
        seen_sequences: set[tuple[str, ...]] = set()
        for sequence in raw_sequences:
            remapped: list[str] = []
            for pose_id in sequence:
                final_id = mapping.get(str(pose_id), str(pose_id))
                if not remapped or remapped[-1] != final_id:
                    remapped.append(final_id)
            if len(remapped) >= 2 and tuple(remapped) not in seen_sequences:
                remapped_sequences.append(remapped)
                seen_sequences.add(tuple(remapped))

        consolidation_diagnostics = {
            "stage": "global_support_consolidation",
            "raw_pose_count": len(raw_poses),
            "raw_edge_count": len(raw_edges),
            "hard_merge_spatial_pair_count": len(spatial_pairs),
            "hard_merge_candidate_cluster_count": sum(len(value) > 1 for value in provisional_groups),
            "hard_merge_cluster_count": sum(len(value) > 1 for value in members_by_final.values()),
            "hard_merged_pose_count": len(raw_poses) - len(consolidated_poses),
            "soft_cluster_count": len(soft_clusters),
            "soft_clusters": soft_clusters,
            "merge_rejection_reasons": dict(sorted(merge_rejections.items())),
            "constraint_split_count": split_count,
            "collapsed_action_edge_count": collapsed_edge_count,
            "consolidated_pose_count": len(consolidated_poses),
            "consolidated_edge_count": len(consolidated_edges),
        }
        self.consolidated_support = _stage_payload(
            "global_support_consolidation", consolidated_poses, consolidated_edges,
            anchor_poses, remapped_sequences, consolidation_diagnostics,
        )

        # Global executable stitching.  Connected components are joined first;
        # then safe local cycles and endpoint alternatives consume remaining
        # per-node stitch degree.
        existing_pairs = {
            tuple(sorted((str(edge["source"]), str(edge["target"]))))
            for edge in consolidated_edges.values()
        }
        base_degree: Counter[str] = Counter()
        for source, target in existing_pairs:
            base_degree[source] += 1
            base_degree[target] += 1
        components = _DisjointSet(consolidated_poses)
        for source, target in existing_pairs:
            components.union(source, target)
        normalized_portals = _portal_sets(consolidated_poses, consolidated_edges.values())
        stitch_min = float(config.get("global_stitch_min_distance_m", action_min))
        stitch_max = float(config.get("global_stitch_max_distance_m", action_max))
        stitch_target = float(config.get("global_stitch_target_distance_m", config["forward_step_m"]))
        heading_tolerance = float(config.get("global_stitch_heading_tolerance_deg", 7.5))
        degree_limit = max(0, int(config.get("global_stitch_max_degree", 4)))
        rejection_reasons: Counter[str] = Counter()
        stitch_candidates: list[tuple[float, str, str]] = []
        for distance, source, target in _spatial_pairs(consolidated_poses, stitch_max + 1e-9):
            pair = tuple(sorted((source, target)))
            if pair in existing_pairs:
                rejection_reasons["duplicate"] += 1
                continue
            if distance < stitch_min - 1e-9:
                rejection_reasons["distance"] += 1
                continue
            if not _portals_compatible(normalized_portals[source], normalized_portals[target]):
                rejection_reasons["portal"] += 1
                continue
            yaw = _yaw_to(consolidated_poses[source]["position"], consolidated_poses[target]["position"])
            heading_error = abs((yaw - round(yaw / 15.0) * 15.0 + 180.0) % 360.0 - 180.0)
            if heading_error > heading_tolerance + 1e-9:
                rejection_reasons["heading"] += 1
                continue
            if not _world_segment_safe(
                motion_grid,
                tuple(consolidated_poses[source]["position"][:2]),
                tuple(consolidated_poses[target]["position"][:2]),
            ):
                rejection_reasons["collision"] += 1
                continue
            stitch_candidates.append((abs(distance - stitch_target), source, target))

        stitch_degree: Counter[str] = Counter()
        selected: list[tuple[str, str]] = []
        selected_set: set[tuple[str, str]] = set()

        def room(source: str, target: str) -> bool:
            return degree_limit > 0 and stitch_degree[source] < degree_limit and stitch_degree[target] < degree_limit

        # First make the forest as connected as geometry permits.
        for _error, source, target in sorted(stitch_candidates):
            if not room(source, target) or components.find(source) == components.find(target):
                continue
            pair = tuple(sorted((source, target)))
            selected.append(pair)
            selected_set.add(pair)
            stitch_degree[source] += 1
            stitch_degree[target] += 1
            components.union(source, target)

        # Then create junctions and short local detours, preferring endpoints.
        remaining = sorted(
            stitch_candidates,
            key=lambda item: (
                0 if base_degree[item[1]] <= 1 or base_degree[item[2]] <= 1 else 1,
                item[0], item[1], item[2],
            ),
        )
        for _error, source, target in remaining:
            pair = tuple(sorted((source, target)))
            if pair in selected_set:
                continue
            if not room(source, target):
                rejection_reasons["degree"] += 1
                continue
            selected.append(pair)
            selected_set.add(pair)
            stitch_degree[source] += 1
            stitch_degree[target] += 1

        executable_edges = {key: deepcopy(value) for key, value in consolidated_edges.items()}
        for index, (source, target) in enumerate(selected, 1):
            distance = _distance(consolidated_poses[source]["position"], consolidated_poses[target]["position"])
            owners = sorted(
                set(consolidated_poses[source].get("blueprint_ids") or [])
                | set(consolidated_poses[target].get("blueprint_ids") or [])
            )
            for left, right, direction in ((source, target, "forward"), (target, source, "reverse")):
                edge_id = f"global_stitch_{index:05d}_{direction}"
                executable_edges[edge_id] = {
                    "motion_edge_id": edge_id,
                    "source": left,
                    "target": right,
                    "distance_m": distance,
                    "action": "move_forward",
                    "edge_type": "cross_blueprint_stitch",
                    "support_stage": "global_executable_stitching",
                    "lane": "global_executable_stitch",
                    "place_edge_ids": [],
                    "portal_ids": sorted(normalized_portals[source] & normalized_portals[target]),
                    "source_blueprint_ids": owners,
                    "collision_free": True,
                    "safety_certificate": {
                        "effective_clearance_m": float(config.get("effective_clearance_m", 0.0)),
                        "world_segment_safe": True,
                        "portal_open": True,
                    },
                }
            for pose_id in (source, target):
                consolidated_poses[pose_id]["tags"] = sorted(
                    set(consolidated_poses[pose_id].get("tags") or [])
                    | {"junction", "global_stitch"}
                )
            sequence = (source, target)
            if sequence not in seen_sequences:
                remapped_sequences.append(list(sequence))
                seen_sequences.add(sequence)
            reverse = (target, source)
            if reverse not in seen_sequences:
                remapped_sequences.append(list(reverse))
                seen_sequences.add(reverse)

        poses.clear()
        poses.update(consolidated_poses)
        edges.clear()
        edges.update(executable_edges)
        path_sequences[:] = remapped_sequences
        diagnostics = {
            "schema_version": "opticalnav.global_support_normalization.v2",
            "algorithm_id": ALGORITHM_ID,
            "stages": [
                "raw_blueprint_induced_support",
                "global_support_consolidation",
                "global_executable_stitching",
            ],
            **consolidation_diagnostics,
            "cross_blueprint_stitch_candidate_count": len(stitch_candidates),
            "cross_blueprint_stitch_pair_count": len(selected),
            "cross_blueprint_stitch_edge_count": len(selected) * 2,
            "stitch_rejection_reasons": dict(sorted(rejection_reasons.items())),
            "normalized_pose_count": len(poses),
            "normalized_edge_count": len(edges),
        }
        self.executable_support = _stage_payload(
            "global_executable_stitching", poses, edges, anchor_poses,
            path_sequences, diagnostics,
        )
        return diagnostics


def _graph_rows(graph: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[Mapping[str, Any]]]:
    node_rows = graph.get("poses") or graph.get("nodes") or []
    nodes = {_pose_id(item): item for item in node_rows if isinstance(item, Mapping) and _pose_id(item)}
    edges = [item for item in graph.get("edges") or [] if isinstance(item, Mapping)]
    return nodes, edges


def _undirected_adjacency(
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, set[str]], set[tuple[str, str]]]:
    adjacency = {node_id: set() for node_id in nodes}
    pairs: set[tuple[str, str]] = set()
    for edge in edges:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source not in nodes or target not in nodes or source == target:
            continue
        pair = tuple(sorted((source, target)))
        pairs.add(pair)
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency, pairs


def _components(adjacency: Mapping[str, set[str]]) -> list[set[str]]:
    remaining = set(adjacency)
    result: list[set[str]] = []
    while remaining:
        root = min(remaining)
        found = {root}
        pending = [root]
        while pending:
            current = pending.pop()
            for target in adjacency[current]:
                if target not in found:
                    found.add(target)
                    pending.append(target)
        remaining -= found
        result.append(found)
    return result


def _shortest_path(
    adjacency: Mapping[str, set[str]],
    source: str,
    target: str,
    banned: tuple[str, str] | None = None,
) -> list[str] | None:
    pending = deque([source])
    prior: dict[str, str | None] = {source: None}
    while pending:
        current = pending.popleft()
        if current == target:
            path = [target]
            while prior[path[-1]] is not None:
                path.append(str(prior[path[-1]]))
            return list(reversed(path))
        for next_id in sorted(adjacency.get(current, set())):
            if banned and tuple(sorted((current, next_id))) == banned:
                continue
            if next_id not in prior:
                prior[next_id] = current
                pending.append(next_id)
    return None


def support_graph_metrics(
    graph: Mapping[str, Any],
    *,
    blueprints: Mapping[str, Any] | None = None,
    motion_grid: TraversabilityGrid | None = None,
    sample_count: int = 200,
    seed: int = 0,
) -> dict[str, Any]:
    """Return deterministic connectivity, provenance, and action metrics."""
    nodes, edges = _graph_rows(graph)
    adjacency, pairs = _undirected_adjacency(nodes, edges)
    components = _components(adjacency)
    degrees = {node_id: len(targets) for node_id, targets in adjacency.items()}
    step = float(graph.get("forward_step_m") or 0.25)
    tolerance = float(graph.get("forward_tolerance_m") or 0.025)
    length_violations = 0
    collision_violations = 0
    for source, target in pairs:
        distance = _distance(nodes[source]["position"], nodes[target]["position"])
        if not math.isclose(distance, step, abs_tol=tolerance):
            length_violations += 1
        if motion_grid is not None and not _world_segment_safe(
            motion_grid, tuple(nodes[source]["position"][:2]), tuple(nodes[target]["position"][:2]),
        ):
            collision_violations += 1
    residual_pairs = _spatial_pairs(nodes, 0.15)
    stitch_pairs = {
        tuple(sorted((str(edge.get("source")), str(edge.get("target")))))
        for edge in edges if str(edge.get("edge_type") or "") == "cross_blueprint_stitch"
    }
    provenance_by_node: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        owners = {str(value) for value in edge.get("source_blueprint_ids") or [] if str(value)}
        provenance_by_node[str(edge.get("source") or "")].update(owners)
        provenance_by_node[str(edge.get("target") or "")].update(owners)
    mixed_junctions = sum(degrees.get(node_id, 0) >= 3 and len(owners) >= 2 for node_id, owners in provenance_by_node.items())

    anchor_map = {
        str(key): {str(value) for value in values if str(value) in nodes}
        for key, values in (graph.get("anchor_pose_ids") or {}).items()
    }
    approved_rows = [
        row for row in (blueprints or {}).get("blueprints") or []
        if isinstance(row, Mapping) and str(row.get("status") or "") == "approved"
    ]
    reachable_blueprints = 0
    for row in approved_rows:
        starts = anchor_map.get(str(row.get("start_anchor_id") or ""), set())
        goals = anchor_map.get(str(row.get("goal_anchor_id") or ""), set())
        if any(_shortest_path(adjacency, source, target) for source in starts for target in goals):
            reachable_blueprints += 1

    ids = sorted(nodes)
    all_pairs = [(ids[left], ids[right]) for left in range(len(ids)) for right in range(left + 1, len(ids))]
    rng = random.Random(seed)
    sampled = all_pairs if len(all_pairs) <= sample_count else rng.sample(all_pairs, sample_count)
    reachable = 0
    alternatives = 0
    for source, target in sampled:
        path = _shortest_path(adjacency, source, target)
        if path is None:
            continue
        reachable += 1
        if any(
            _shortest_path(adjacency, source, target, tuple(sorted((left, right)))) is not None
            for left, right in zip(path, path[1:])
        ):
            alternatives += 1

    payload = {
        "node_count": len(nodes),
        "directed_edge_count": len(edges),
        "undirected_edge_count": len(pairs),
        "connected_component_count": len(components),
        "largest_component_node_count": max((len(value) for value in components), default=0),
        "degree_one_node_count": sum(value == 1 for value in degrees.values()),
        "junction_node_count": sum(value >= 3 for value in degrees.values()),
        "cycle_rank": max(0, len(pairs) - len(nodes) + len(components)),
        "mixed_blueprint_junction_count": mixed_junctions,
        "residual_sub_015_pair_count": len(residual_pairs),
        "stitch_pair_count": len(stitch_pairs),
        "action_length_violation_count": length_violations,
        "collision_violation_count": collision_violations,
        "approved_blueprint_count": len(approved_rows),
        "reachable_approved_blueprint_count": reachable_blueprints,
        "random_pair_sample_count": len(sampled),
        "random_pair_reachable_count": reachable,
        "random_pair_reachability": reachable / len(sampled) if sampled else 1.0,
        "random_pair_alternative_count": alternatives,
        "random_pair_alternative_ratio": alternatives / reachable if reachable else 0.0,
        "degree_histogram": dict(sorted(Counter(degrees.values()).items())),
    }
    payload["graph_digest"] = _canonical_digest({
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": sorted(edges, key=lambda item: str(item.get("motion_edge_id") or "")),
    })
    return payload


def compare_support_metrics(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    numeric_keys = sorted({
        key for key, value in baseline.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    } & {
        key for key, value in candidate.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    })
    delta = {key: candidate[key] - baseline[key] for key in numeric_keys}
    hard_valid = (
        int(candidate.get("action_length_violation_count") or 0) == 0
        and int(candidate.get("collision_violation_count") or 0) == 0
        and int(candidate.get("reachable_approved_blueprint_count") or 0)
        >= int(baseline.get("reachable_approved_blueprint_count") or 0)
        and int(candidate.get("connected_component_count") or 0)
        <= int(baseline.get("connected_component_count") or 0)
    )
    network_improved = (
        int(candidate.get("residual_sub_015_pair_count") or 0)
        < int(baseline.get("residual_sub_015_pair_count") or 0)
        or int(candidate.get("degree_one_node_count") or 0)
        < int(baseline.get("degree_one_node_count") or 0)
        or int(candidate.get("junction_node_count") or 0)
        > int(baseline.get("junction_node_count") or 0)
        or int(candidate.get("cycle_rank") or 0) > int(baseline.get("cycle_rank") or 0)
        or float(candidate.get("random_pair_alternative_ratio") or 0.0)
        > float(baseline.get("random_pair_alternative_ratio") or 0.0)
    )
    return {
        "delta": delta,
        "hard_validation_passed": hard_valid,
        "network_improved": network_improved,
        "candidate_gate_passed": hard_valid and network_improved,
    }
