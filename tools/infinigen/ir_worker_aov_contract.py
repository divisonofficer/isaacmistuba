"""Pure helpers for the Blender IR worker AOV compatibility contract."""
from __future__ import annotations

from collections.abc import Iterable


# These auxiliary labels were introduced with MetallicContractV2.  A passive
# NIR backfill does not render or replace any GT artifacts, so an older
# prepared blend may omit them without weakening the existing dataset GT.
LEGACY_PASSIVE_BACKFILL_OPTIONAL_AOV_SOURCES = frozenset({
    "GT_MetallicFamilyID",
    "GT_MetalCoverage",
    "GT_ExposedMetal",
})


def required_aov_sources(
    sources: Iterable[str],
    *,
    always_optional: Iterable[str] = (),
    allow_legacy_passive_backfill: bool = False,
) -> frozenset[str]:
    """Return the GT AOVs that the prepared blend must expose.

    The legacy exception is deliberately opt-in and only covers the three
    MetallicContractV2 auxiliary labels.  Core PBR inputs remain required.
    """
    optional = set(always_optional)
    if allow_legacy_passive_backfill:
        optional.update(LEGACY_PASSIVE_BACKFILL_OPTIONAL_AOV_SOURCES)
    return frozenset(
        source for source in sources
        if source.startswith("GT_") and source not in optional
    )
