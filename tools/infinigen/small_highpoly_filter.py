"""Conservative filter for pathological tiny, high-poly indoor decorations."""

from __future__ import annotations

STRUCTURAL_KINDS = frozenset({"structure", "door", "window"})
STRUCTURAL_TOKENS = (
    "wall", "floor", "ceiling", "roof", "frame", "column", "pillar",
    "panel", "room", "building", "door", "window", "stair",
)
DETAIL_SEMANTICS = frozenset({
    "landmark", "prop", "shelf", "clutter", "plant", "decor", "scatter",
    "scatter_fruit", "tableware", "book", "bookstack", "bookcolumn", "food",
    "fruit", "bottle", "jar", "cup", "bowl", "knife", "spoon", "chopsticks",
    "can", "bag", "container", "lamp", "trinket",
})

# These factory lists distinguish useful opaque PBR supervision from known
# pathological procedural clusters.  Keep them deliberately narrow: broad
# name matching here could remove real walls or architectural columns.
SMALL_HIGH_POLY_POLICY_VERSION = "tiny-high-poly-detail-v4-pbr-recovery"

# Factories with useful opaque PBR supervision should reach the normal IR LOD
# decimator/baker whenever their geometry is bounded.  The previous v3 policy
# dropped these names unconditionally—even a 90-triangle book stack—which left
# their original meshes visible in the derived blend without GT AOVs.
PBR_RECOVERABLE_FACTORY_TOKENS = (
    "bookcolumnfactory",
    "bookstackfactory",
    "naturetrinket",
    "natureshelftrinket",
    "jarfactory",
    "potfactory",
    "plantpotfactory",
    "vasefactory",
    "bowlfactory",
    "platefactory",
    "cupfactory",
)
PBR_RECOVERABLE_MAX_TRIANGLES = 500_000
PBR_RECOVERABLE_MAX_EXTENT_M = 0.75

# These factories are still excluded before strict bake.  They are known to
# carry nested/transmissive or disconnected procedural graphs whose cost is
# not proportional to the visible opaque supervision they provide.
PATHOLOGICAL_FACTORY_TOKENS = (
    # Aquarium assets are generated as nested glass/cactus shader groups in
    # some Infinigen rooms.  They are non-structural landmarks, yet can carry
    # 100k+ triangles without a bake-authoritative PBR contract.  Keep the
    # building frame/room geometry protected while filtering this pathological
    # detail before the expensive strict GLB bake.
    "aquariumtankfactory",
    # Generated fruit clusters are small scene dressing, but their
    # procedural meshes can trigger expensive per-channel atlas bakes.
    "fruitfactory",
)


def is_small_highpoly_record(record: dict, *, max_extent_m: float = 0.5,
                             min_triangles: int = 100_000) -> tuple[bool, str]:
    """Return ``(drop, reason)`` for a manifest-like unit record.

    Structural/portal geometry is protected first.  Only explicit detail
    semantics are eligible, so an unknown or unusually named object is kept.
    """
    if str(record.get("kind") or "") in STRUCTURAL_KINDS:
        return False, "protected_kind"
    name = " ".join(str(record.get(k) or "") for k in
                    ("blender_name", "factory", "subtype")).lower()
    # ``BookColumnFactory`` is a decorative book stack, not a building column.
    # Check this before the broad ``column`` structural guard so ordinary book
    # stacks can reach the recoverable PBR path without ever exposing real
    # architectural columns to filtering.
    decorative_column = any(token in name for token in ("bookcolumn", "book_column", "book column"))
    recoverable_factory = any(token in name for token in PBR_RECOVERABLE_FACTORY_TOKENS)
    pathological_factory = any(token in name for token in PATHOLOGICAL_FACTORY_TOKENS)
    decorative_factory = recoverable_factory or pathological_factory
    if not decorative_column and any(token in name for token in STRUCTURAL_TOKENS):
        return False, "protected_structural_token"
    semantic = str(record.get("semantic_type") or "").lower()
    subtype = str(record.get("subtype") or "").lower()
    if semantic not in DETAIL_SEMANTICS and subtype not in DETAIL_SEMANTICS \
            and not decorative_column and not decorative_factory:
        return False, "non_detail_semantics"
    values = record.get("dimensions") or record.get("place_size_m")
    try:
        extent = max(abs(float(v)) for v in values)
        triangles = int(record.get("triangles") or 0)
    except (TypeError, ValueError):
        return False, "missing_geometry_stats"
    # BookColumn is a stack of decorative books whose name happens to contain
    # the architectural token ``column``.  Its authored cluster can be wider
    # than the strict 25cm envelope, so permit a bounded one-metre detail
    # envelope when it is demonstrably high-poly.  Real building columns are
    # excluded by the structural guard above and never reach this branch.
    if pathological_factory:
        return True, "pathological_factory_filtered"
    if recoverable_factory:
        if triangles <= PBR_RECOVERABLE_MAX_TRIANGLES and extent <= PBR_RECOVERABLE_MAX_EXTENT_M:
            return False, "recoverable_pbr_detail"
        # Factory identity remains useful for sparse parent bounds, but only
        # after the bounded PBR recovery path above has had a chance to keep
        # ordinary books, ceramics and cookware.
        return True, "decorative_factory_filtered"
    if decorative_column and triangles >= int(min_triangles) and extent <= max(float(max_extent_m) * 4.0, 1.0):
        return True, "tiny_high_poly_detail_relaxed"
    # Some Infinigen detail factories (notably compositional fruit/plant
    # assets) are authored as a cluster.  The cluster AABB can exceed the
    # strict 25cm threshold even though it is still a small, non-structural
    # decoration and carries hundreds of thousands of triangles.  Allow a
    # bounded relaxed envelope only for those pathological high-poly detail
    # records; architectural geometry remains protected above.
    extent_limit = float(max_extent_m)
    if semantic in {"landmark", "prop", "plant", "decor", "scatter", "scatter_fruit"} \
        and triangles >= max(int(min_triangles) * 3, 600_000):
        # Keep the relaxed cluster envelope bounded in world metres.  Raising
        # the base filter threshold must not turn ordinary 0.8m furniture into
        # disposable clutter merely because it is tessellated densely.
        extent_limit = min(extent_limit * 3.0, 0.75)
        relaxed = True
    else:
        relaxed = False
    if extent > extent_limit:
        return False, "not_small"
    if triangles < int(min_triangles):
        return False, "not_high_poly"
    return True, "tiny_high_poly_detail_relaxed" if relaxed else "tiny_high_poly_detail"
