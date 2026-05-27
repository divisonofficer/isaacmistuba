from __future__ import annotations

from .scene_annotations import GoalRegion, SceneAnnotation


INSTRUCTION_TYPES = ("goal_only", "hazard_aware", "ambiguous")


def make_instruction(
    annotation: SceneAnnotation,
    goal_region: GoalRegion,
    *,
    instruction_type: str = "hazard_aware",
) -> str:
    if instruction_type not in INSTRUCTION_TYPES:
        raise ValueError(f"Unsupported instruction_type: {instruction_type}")
    goal_label = goal_region.label or goal_region.region_id.replace("_", " ")
    hazards = [item.hazard_type.replace("_", " ") for item in annotation.hazard_regions]
    hazard_label = hazards[0] if hazards else "transparent obstacle"
    if instruction_type == "goal_only":
        return f"Move to {goal_label}."
    if instruction_type == "ambiguous":
        return "Move to the target area ahead."
    return f"Move to {goal_label} without crossing the {hazard_label}."
