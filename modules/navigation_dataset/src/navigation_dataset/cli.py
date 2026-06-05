from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import urllib.error
import urllib.request

from .episode_schema import DEFAULT_MODALITIES, DatasetProject, read_episode, write_project, write_episode
from .evaluator import evaluate_dataset, write_evaluation
from .exporters.custom_json import export_dataset_zip, write_dataset_index, write_split_files
from .edge_builder import build_viewpoint_edges, graph_summary
from .graph_episode_sampler import GRAPH_SCENARIOS, plan_graph_episodes, write_graph_episodes
from .node_sampler import sample_viewpoint_nodes
from .renderer import render_episode_direct, write_rendered_episode
from .rollout import plan_episodes, split_counts_from_spec, write_episodes
from .scene_annotations import read_scene_annotation
from .sensor_sweep import render_viewpoint_sweep_direct
from .traversability import build_traversability_grid, load_traversability_grid, save_traversability_grid, write_nav_graph
from .validation import validate_dataset
from .viewpoint_graph import ViewpointGraph, read_viewpoint_graph, write_viewpoint_graph


def _dataset_root(value: str | None) -> Path:
    return Path(value or ".").resolve()


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        message = body
        try:
            message = json.loads(body).get("error", body)
        except Exception:
            pass
        raise RuntimeError(f"{exc.code} {exc.reason}: {message}") from exc


def _modalities(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_MODALITIES)
    return [item.strip() for item in value.split(",") if item.strip()]


def cmd_init(args) -> None:
    root = Path(args.root).resolve()
    for rel in (
        "scenes",
        "episodes/train",
        "episodes/val_seen",
        "episodes/val_unseen",
        "episodes/test",
        "observations",
        "viewpoint_observations",
        "splits",
        "evaluation",
        "docs",
        "render_batches",
        "graph_render_batches",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    project = DatasetProject(
        project_name=args.project_name,
        dataset_type=args.dataset_type,
        target_scenario=args.target_scenario,
        robot_profile=args.robot_profile,
        modalities=_modalities(args.modalities),
    )
    write_project(root / "dataset.json", project)
    (root / "README.md").write_text(
        f"# {args.project_name}\n\nTargeted synthetic fine-tuning dataset for optical-hazard navigation.\n",
        encoding="utf-8",
    )
    (root / "dataset_card.md").write_text(
        "# Dataset Card\n\nThis is not a benchmark replacement. It is targeted synthetic fine-tuning data.\n",
        encoding="utf-8",
    )
    (root / "docs" / "modality_definitions.md").write_text(
        "- active_nir_intensity: NIR-like proxy, not a calibrated physical NIR camera model.\n- hazard_mask: binary optical-hazard target mask.\n",
        encoding="utf-8",
    )
    (root / "docs" / "graph_action_interface.md").write_text(
        "Graph actions: move_to_neighbor, turn_left_30, turn_right_30, stop.\n",
        encoding="utf-8",
    )
    print(f"Wrote dataset project: {root}")


def cmd_scene_add(args) -> None:
    root = _dataset_root(args.dataset)
    scene_dir = root / "scenes" / args.scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)
    usd_src = Path(args.usd)
    usd_dst = scene_dir / usd_src.name
    if usd_src.exists() and usd_src.resolve() != usd_dst.resolve():
        shutil.copy2(usd_src, usd_dst)
    elif not usd_dst.exists():
        usd_dst.write_text("# placeholder scene ref; replace with real USD\n", encoding="utf-8")
    annotation_path = scene_dir / "scene_annotation.json"
    if not annotation_path.exists():
        _write_json(
            annotation_path,
            {
                "scene_id": args.scene_id,
                "usd_ref": f"scenes/{args.scene_id}/{usd_dst.name}",
                "objects": [],
                "transparent_surfaces": [],
                "reflective_hazards": [],
                "hazard_regions": [],
                "goal_regions": [],
                "landmarks": [],
                "traversable_regions": [],
                "metadata": {"status": "annotation_required"},
            },
        )
    print(f"Registered scene: {scene_dir}")


def cmd_scene_validate(args) -> None:
    annotation = read_scene_annotation(args.annotation)
    print(json.dumps({"ok": True, "scene_id": annotation.scene_id}, indent=2))


def cmd_map_build(args) -> None:
    root = _dataset_root(args.dataset)
    annotation_path = root / "scenes" / args.scene_id / "scene_annotation.json"
    annotation = read_scene_annotation(annotation_path)
    grid = build_traversability_grid(annotation, resolution=args.resolution)
    out_path = Path(args.out) if args.out else root / "scenes" / args.scene_id / "traversable_grid.npy"
    save_traversability_grid(out_path, grid)
    write_nav_graph(root / "scenes" / args.scene_id / "nav_graph.json", grid)
    print(f"Wrote traversable grid: {out_path}")


def cmd_episodes_plan(args) -> None:
    root = _dataset_root(args.dataset)
    annotation = read_scene_annotation(root / "scenes" / args.scene_id / "scene_annotation.json")
    grid_path = Path(args.grid) if args.grid else root / "scenes" / args.scene_id / "traversable_grid.npy"
    grid = load_traversability_grid(grid_path)
    episodes = plan_episodes(
        annotation=annotation,
        grid=grid,
        num_pairs=args.num_pairs,
        split_counts=split_counts_from_spec(args.splits),
        instruction_types=[item.strip() for item in args.instruction_types.split(",") if item.strip()],
        modalities=_modalities(args.modalities),
        seed=args.seed,
    )
    write_episodes(root, episodes)
    write_dataset_index(root)
    write_split_files(root)
    print(json.dumps({"planned": len(episodes), "scene_id": args.scene_id}, indent=2))


def cmd_episodes_render(args) -> None:
    root = _dataset_root(args.dataset)
    if args.backend != "direct":
        raise SystemExit("Only --backend direct is implemented in v0.1 CLI. Use the existing render daemon API separately for queued jobs.")
    if not args.scene_state or not args.camera_spec:
        raise SystemExit("--scene-state and --camera-spec JSON payloads are required for direct rendering.")
    scene_state = _read_json(args.scene_state)
    camera_spec = _read_json(args.camera_spec)
    count = 0
    for episode_path in sorted((root / "episodes").glob("*/*.json")):
        episode = read_episode(episode_path)
        rendered = render_episode_direct(
            episode,
            dataset_root=root,
            scene_state_payload=scene_state,
            camera_spec_payload=camera_spec,
            modalities=_modalities(args.modalities),
            variant=args.variant,
        )
        write_rendered_episode(root, rendered)
        count += 1
    print(json.dumps({"rendered_episodes": count}, indent=2))


def cmd_graph_build(args) -> None:
    root = _dataset_root(args.dataset)
    grid_path = Path(args.grid) if args.grid else root / "scenes" / args.scene_id / "traversable_grid.npy"
    grid = load_traversability_grid(grid_path)
    nodes = sample_viewpoint_nodes(
        grid,
        max_nodes=args.max_nodes,
        heading_count=args.heading_count,
        min_node_spacing_m=args.min_node_spacing,
        min_clearance_m=args.min_clearance,
        robot_radius_m=args.robot_radius,
        seed=args.seed,
    )
    edges = build_viewpoint_edges(
        grid,
        nodes,
        robot_radius_m=args.robot_radius,
        k_neighbors=args.k_neighbors,
        max_edge_length_m=args.max_edge_length,
    )
    graph = ViewpointGraph(
        scene_id=args.scene_id,
        graph_id=args.graph_id or f"{args.scene_id}_vg_0001",
        node_heading_count=args.heading_count,
        nodes=nodes,
        edges=edges,
        metadata={
            "generation_version": "opticalnav-v0.2",
            "robot_radius_m": args.robot_radius,
            "min_node_spacing_m": args.min_node_spacing,
            "max_edge_length_m": args.max_edge_length,
            "k_neighbors": args.k_neighbors,
            "seed": args.seed,
        },
    )
    graph_path = root / "scenes" / args.scene_id / "viewpoint_graph.json"
    write_viewpoint_graph(graph_path, graph)
    print(json.dumps({"graph_ref": graph_path.relative_to(root).as_posix(), **graph_summary(nodes, edges, heading_count=args.heading_count)}, indent=2))


def cmd_graph_sweep(args) -> None:
    root = _dataset_root(args.dataset)
    if not args.scene_state or not args.camera_spec:
        raise SystemExit("--scene-state and --camera-spec JSON payloads are required for graph sensor sweep.")
    if args.backend == "daemon":
        project_id = args.project_id or root.name
        url = f"{args.daemon_url.rstrip('/')}/api/opticalnav/projects/{project_id}/scenes/{args.scene_id}/graph/sweep"
        result = _post_json(
            url,
            {
                "backend": "daemon",
                "modalities": _modalities(args.modalities),
                "scene_state": _read_json(args.scene_state),
                "camera_spec": _read_json(args.camera_spec),
                "variant": args.variant,
            },
        )
        print(json.dumps(result, indent=2))
        return
    graph_path = Path(args.graph) if args.graph else root / "scenes" / args.scene_id / "viewpoint_graph.json"
    graph = read_viewpoint_graph(graph_path)
    updated = render_viewpoint_sweep_direct(
        graph,
        dataset_root=root,
        graph_path=graph_path,
        scene_state_payload=_read_json(args.scene_state),
        camera_spec_payload=_read_json(args.camera_spec),
        modalities=_modalities(args.modalities),
        variant=args.variant,
    )
    rendered = sum(1 for node in updated.nodes for heading in node.headings if heading.sensor_observations)
    print(json.dumps({"graph_id": updated.graph_id, "rendered_node_headings": rendered}, indent=2))


def cmd_graph_episodes_plan(args) -> None:
    root = _dataset_root(args.dataset)
    graph_path = Path(args.graph) if args.graph else root / "scenes" / args.scene_id / "viewpoint_graph.json"
    annotation_path = root / "scenes" / args.scene_id / "scene_annotation.json"
    annotation = read_scene_annotation(annotation_path) if annotation_path.exists() else None
    episodes = plan_graph_episodes(
        graph=read_viewpoint_graph(graph_path),
        num_pairs=args.num_pairs,
        split_counts=split_counts_from_spec(args.splits),
        scenarios=[item.strip() for item in args.scenarios.split(",") if item.strip()],
        modalities=_modalities(args.modalities),
        annotation=annotation,
        seed=args.seed,
    )
    written = write_graph_episodes(root, episodes)
    write_dataset_index(root)
    write_split_files(root)
    print(json.dumps({"planned": len(written), "scene_id": args.scene_id, "mode": "viewpoint_graph"}, indent=2))


def cmd_validate_dataset(args) -> None:
    report = validate_dataset(args.dataset, require_observations=args.require_observations)
    print(json.dumps(report.to_payload(), indent=2))
    if not report.ok:
        raise SystemExit(1)


def cmd_evaluate(args) -> None:
    root = _dataset_root(args.dataset)
    output = root / "evaluation" / f"{args.policy}.json"
    write_evaluation(output, root, success_radius=args.success_radius)
    print(json.dumps(evaluate_dataset(root, success_radius=args.success_radius)["metrics"], indent=2))


def cmd_export(args) -> None:
    root = _dataset_root(args.dataset)
    write_dataset_index(root)
    write_split_files(root)
    if args.zip:
        zip_path = export_dataset_zip(root, args.out)
        print(f"Wrote export zip: {zip_path}")
    else:
        print(f"Wrote dataset index and splits: {root}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="opticalnav")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("project_name")
    p_init.add_argument("--root", required=True)
    p_init.add_argument("--dataset-type", default="Synthetic fine-tuning dataset")
    p_init.add_argument("--target-scenario", default="glass / mirror / transparent partition navigation")
    p_init.add_argument("--robot-profile", default="mobile_base_front_camera")
    p_init.add_argument("--modalities", default=",".join(DEFAULT_MODALITIES))
    p_init.set_defaults(fn=cmd_init)

    p_scene = sub.add_parser("scene")
    scene_sub = p_scene.add_subparsers(dest="scene_cmd", required=True)
    p_scene_add = scene_sub.add_parser("add")
    p_scene_add.add_argument("--dataset", default=".")
    p_scene_add.add_argument("--scene-id", required=True)
    p_scene_add.add_argument("--usd", required=True)
    p_scene_add.set_defaults(fn=cmd_scene_add)
    p_scene_validate = scene_sub.add_parser("validate")
    p_scene_validate.add_argument("--annotation", required=True)
    p_scene_validate.set_defaults(fn=cmd_scene_validate)

    p_map = sub.add_parser("map")
    map_sub = p_map.add_subparsers(dest="map_cmd", required=True)
    p_map_build = map_sub.add_parser("build")
    p_map_build.add_argument("--dataset", default=".")
    p_map_build.add_argument("--scene-id", required=True)
    p_map_build.add_argument("--resolution", type=float, default=0.05)
    p_map_build.add_argument("--out", default=None)
    p_map_build.set_defaults(fn=cmd_map_build)

    p_episodes = sub.add_parser("episodes")
    episodes_sub = p_episodes.add_subparsers(dest="episodes_cmd", required=True)
    p_plan = episodes_sub.add_parser("plan")
    p_plan.add_argument("--dataset", default=".")
    p_plan.add_argument("--scene-id", required=True)
    p_plan.add_argument("--grid", default=None)
    p_plan.add_argument("--num-pairs", type=int, required=True)
    p_plan.add_argument("--instruction-types", default="goal_only,hazard_aware,ambiguous")
    p_plan.add_argument("--splits", default="train:60,val_seen:10,val_unseen:10")
    p_plan.add_argument("--modalities", default=",".join(DEFAULT_MODALITIES))
    p_plan.add_argument("--seed", type=int, default=0)
    p_plan.set_defaults(fn=cmd_episodes_plan)
    p_render = episodes_sub.add_parser("render")
    p_render.add_argument("--dataset", required=True)
    p_render.add_argument("--modalities", default=",".join(DEFAULT_MODALITIES))
    p_render.add_argument("--backend", choices=["direct", "daemon"], default="direct")
    p_render.add_argument("--scene-state", default=None)
    p_render.add_argument("--camera-spec", default=None)
    p_render.add_argument("--variant", default="auto")
    p_render.set_defaults(fn=cmd_episodes_render)

    p_graph = sub.add_parser("graph")
    graph_sub = p_graph.add_subparsers(dest="graph_cmd", required=True)
    p_graph_build = graph_sub.add_parser("build")
    p_graph_build.add_argument("--dataset", default=".")
    p_graph_build.add_argument("--scene-id", required=True)
    p_graph_build.add_argument("--grid", default=None)
    p_graph_build.add_argument("--graph-id", default=None)
    p_graph_build.add_argument("--max-nodes", type=int, default=300)
    p_graph_build.add_argument("--heading-count", type=int, default=12)
    p_graph_build.add_argument("--min-node-spacing", type=float, default=0.5)
    p_graph_build.add_argument("--min-clearance", type=float, default=0.0)
    p_graph_build.add_argument("--robot-radius", type=float, default=0.25)
    p_graph_build.add_argument("--k-neighbors", type=int, default=8)
    p_graph_build.add_argument("--max-edge-length", type=float, default=1.5)
    p_graph_build.add_argument("--seed", type=int, default=0)
    p_graph_build.set_defaults(fn=cmd_graph_build)
    p_graph_sweep = graph_sub.add_parser("sweep")
    p_graph_sweep.add_argument("--dataset", required=True)
    p_graph_sweep.add_argument("--scene-id", required=True)
    p_graph_sweep.add_argument("--graph", default=None)
    p_graph_sweep.add_argument("--modalities", default=",".join(DEFAULT_MODALITIES))
    p_graph_sweep.add_argument("--backend", choices=["direct", "daemon"], default="direct")
    p_graph_sweep.add_argument("--daemon-url", default="http://127.0.0.1:8765")
    p_graph_sweep.add_argument("--project-id", default=None)
    p_graph_sweep.add_argument("--scene-state", default=None)
    p_graph_sweep.add_argument("--camera-spec", default=None)
    p_graph_sweep.add_argument("--variant", default="auto")
    p_graph_sweep.set_defaults(fn=cmd_graph_sweep)
    p_graph_episodes = graph_sub.add_parser("episodes")
    graph_episodes_sub = p_graph_episodes.add_subparsers(dest="graph_episodes_cmd", required=True)
    p_graph_plan = graph_episodes_sub.add_parser("plan")
    p_graph_plan.add_argument("--dataset", default=".")
    p_graph_plan.add_argument("--scene-id", required=True)
    p_graph_plan.add_argument("--graph", default=None)
    p_graph_plan.add_argument("--num-pairs", type=int, required=True)
    p_graph_plan.add_argument("--splits", default="train:60,val_seen:10,val_unseen:10")
    p_graph_plan.add_argument("--scenarios", default=",".join(GRAPH_SCENARIOS))
    p_graph_plan.add_argument("--modalities", default=",".join(DEFAULT_MODALITIES))
    p_graph_plan.add_argument("--seed", type=int, default=0)
    p_graph_plan.set_defaults(fn=cmd_graph_episodes_plan)

    p_validate = sub.add_parser("validate")
    validate_sub = p_validate.add_subparsers(dest="validate_cmd", required=True)
    p_validate_dataset = validate_sub.add_parser("dataset")
    p_validate_dataset.add_argument("--dataset", required=True)
    p_validate_dataset.add_argument("--require-observations", action="store_true")
    p_validate_dataset.set_defaults(fn=cmd_validate_dataset)

    p_eval = sub.add_parser("evaluate")
    p_eval.add_argument("--dataset", required=True)
    p_eval.add_argument("--policy", default="shortest_oracle")
    p_eval.add_argument("--success-radius", type=float, default=0.5)
    p_eval.set_defaults(fn=cmd_evaluate)

    p_export = sub.add_parser("export")
    p_export.add_argument("--dataset", required=True)
    p_export.add_argument("--format", default="custom_json", choices=["custom_json"])
    p_export.add_argument("--zip", action="store_true")
    p_export.add_argument("--out", default=None)
    p_export.set_defaults(fn=cmd_export)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
