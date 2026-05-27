from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal


ACTION_SPACE = (
    "move_forward",
    "turn_left",
    "turn_right",
    "stop",
    "move_to_neighbor",
    "turn_left_30",
    "turn_right_30",
)
SPLITS = ("train", "val_seen", "val_unseen", "test")
DEFAULT_MODALITIES = ("rgb", "depth", "active_nir_intensity", "hazard_mask")
GENERATION_VERSION = "opticalnav-v0.2"

JsonDict = dict[str, Any]
SplitName = Literal["train", "val_seen", "val_unseen", "test"]
ActionName = Literal["move_forward", "turn_left", "turn_right", "stop", "move_to_neighbor", "turn_left_30", "turn_right_30"]


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float = 0.0

    def to_list(self) -> list[float]:
        return [float(self.x), float(self.y), float(self.yaw)]

    @classmethod
    def from_value(cls, value: Any) -> "Pose2D":
        if isinstance(value, cls):
            return value
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError("Pose2D must be [x, y, yaw].")
        return cls(float(value[0]), float(value[1]), float(value[2]))


@dataclass
class EpisodeTimestep:
    timestep_index: int
    timestamp: float
    agent_pose: list[float]
    action: str
    collision: bool = False
    hazard_collision: bool = False
    observation_bundle_ref: str | None = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class EpisodeManifest:
    episode_id: str
    scene_id: str
    split: str
    start_pose: list[float]
    goal_pose: list[float]
    goal_region: str
    natural_language_instruction: str
    trajectory: list[list[float]]
    actions: list[str]
    timesteps: list[EpisodeTimestep] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)
    schema_version: str = "0.1"
    navigation_mode: str = "trajectory"
    graph_id: str | None = None
    start_node: str | None = None
    goal_node: str | None = None
    path_nodes: list[str] = field(default_factory=list)
    path_headings: list[str] = field(default_factory=list)
    observation_refs: list[str] = field(default_factory=list)


@dataclass
class DatasetProject:
    project_name: str
    dataset_type: str = "Synthetic fine-tuning dataset"
    target_scenario: str = "glass / mirror / transparent partition navigation"
    robot_profile: str = "mobile_base_front_camera"
    modalities: list[str] = field(default_factory=lambda: list(DEFAULT_MODALITIES))
    action_space: list[str] = field(default_factory=lambda: list(ACTION_SPACE))
    generation_version: str = GENERATION_VERSION
    scenes: list[JsonDict] = field(default_factory=list)
    splits: JsonDict = field(default_factory=lambda: {"train": [], "val_seen": [], "val_unseen": [], "test": []})
    metadata: JsonDict = field(default_factory=dict)


def _validate_repo_relative(value: str, *, field_name: str) -> None:
    if value == "":
        return
    path = PurePosixPath(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{field_name} must be repo/package-relative: {value}")


def _episode_timestep_from_payload(payload: JsonDict) -> EpisodeTimestep:
    return EpisodeTimestep(
        timestep_index=int(payload["timestep_index"]),
        timestamp=float(payload["timestamp"]),
        agent_pose=Pose2D.from_value(payload["agent_pose"]).to_list(),
        action=str(payload["action"]),
        collision=bool(payload.get("collision", False)),
        hazard_collision=bool(payload.get("hazard_collision", False)),
        observation_bundle_ref=payload.get("observation_bundle_ref"),
        extras=dict(payload.get("extras", {})),
    )


def episode_to_payload(episode: EpisodeManifest) -> JsonDict:
    payload = asdict(episode)
    payload["timesteps"] = [asdict(item) for item in episode.timesteps]
    return payload


def episode_from_payload(payload: JsonDict) -> EpisodeManifest:
    episode = EpisodeManifest(
        episode_id=str(payload["episode_id"]),
        scene_id=str(payload["scene_id"]),
        split=str(payload["split"]),
        start_pose=Pose2D.from_value(payload["start_pose"]).to_list(),
        goal_pose=Pose2D.from_value(payload["goal_pose"]).to_list(),
        goal_region=str(payload["goal_region"]),
        natural_language_instruction=str(payload["natural_language_instruction"]),
        trajectory=[Pose2D.from_value(item).to_list() for item in payload.get("trajectory", [])],
        actions=[str(item) for item in payload.get("actions", [])],
        timesteps=[_episode_timestep_from_payload(item) for item in payload.get("timesteps", [])],
        metadata=dict(payload.get("metadata", {})),
        schema_version=str(payload.get("schema_version", "0.1")),
        navigation_mode=str(payload.get("navigation_mode", "trajectory")),
        graph_id=payload.get("graph_id"),
        start_node=payload.get("start_node"),
        goal_node=payload.get("goal_node"),
        path_nodes=[str(item) for item in payload.get("path_nodes", [])],
        path_headings=[str(item) for item in payload.get("path_headings", [])],
        observation_refs=[str(item) for item in payload.get("observation_refs", [])],
    )
    validate_episode(episode)
    return episode


def validate_episode(episode: EpisodeManifest) -> None:
    if not episode.episode_id:
        raise ValueError("episode_id must not be empty.")
    if not episode.scene_id:
        raise ValueError("scene_id must not be empty.")
    if episode.split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {episode.split!r}.")
    Pose2D.from_value(episode.start_pose)
    Pose2D.from_value(episode.goal_pose)
    if not episode.goal_region:
        raise ValueError("goal_region must not be empty.")
    if not episode.natural_language_instruction:
        raise ValueError("natural_language_instruction must not be empty.")
    if not episode.trajectory:
        raise ValueError("trajectory must not be empty.")
    for pose in episode.trajectory:
        Pose2D.from_value(pose)
    if not episode.actions:
        raise ValueError("actions must not be empty.")
    unknown_actions = [action for action in episode.actions if action not in ACTION_SPACE]
    if unknown_actions:
        raise ValueError(f"Unsupported actions: {unknown_actions}")
    if episode.actions[-1] != "stop":
        raise ValueError("actions must end with stop.")
    if not episode.timesteps:
        raise ValueError("timesteps must not be empty.")
    if episode.navigation_mode not in {"trajectory", "viewpoint_graph"}:
        raise ValueError("navigation_mode must be 'trajectory' or 'viewpoint_graph'.")
    if episode.navigation_mode == "viewpoint_graph":
        if not episode.graph_id:
            raise ValueError("graph_id is required for viewpoint_graph episodes.")
        if not episode.start_node or not episode.goal_node:
            raise ValueError("start_node and goal_node are required for viewpoint_graph episodes.")
        if not episode.path_nodes:
            raise ValueError("path_nodes is required for viewpoint_graph episodes.")
    for ref in episode.observation_refs:
        _validate_repo_relative(ref, field_name="observation_refs[]")
    for index, timestep in enumerate(episode.timesteps):
        if timestep.timestep_index != index:
            raise ValueError("timestep_index values must be contiguous from 0.")
        Pose2D.from_value(timestep.agent_pose)
        if timestep.action not in ACTION_SPACE:
            raise ValueError(f"Unsupported timestep action: {timestep.action}")
        if timestep.observation_bundle_ref:
            _validate_repo_relative(timestep.observation_bundle_ref, field_name="observation_bundle_ref")
    json.dumps(episode.metadata)


def read_episode(path: str | Path) -> EpisodeManifest:
    return episode_from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def write_episode(path: str | Path, episode: EpisodeManifest) -> Path:
    validate_episode(episode)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(episode_to_payload(episode), ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def read_project(path: str | Path) -> DatasetProject:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return DatasetProject(
        project_name=str(payload["project_name"]),
        dataset_type=str(payload.get("dataset_type", "Synthetic fine-tuning dataset")),
        target_scenario=str(payload.get("target_scenario", "glass / mirror / transparent partition navigation")),
        robot_profile=str(payload.get("robot_profile", "mobile_base_front_camera")),
        modalities=[str(item) for item in payload.get("modalities", DEFAULT_MODALITIES)],
        action_space=[str(item) for item in payload.get("action_space", ACTION_SPACE)],
        generation_version=str(payload.get("generation_version", GENERATION_VERSION)),
        scenes=list(payload.get("scenes", [])),
        splits=dict(payload.get("splits", {})),
        metadata=dict(payload.get("metadata", {})),
    )


def write_project(path: str | Path, project: DatasetProject) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(project), ensure_ascii=False, indent=2), encoding="utf-8")
    return output
