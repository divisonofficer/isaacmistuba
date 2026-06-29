"""Runtime Mitsuba variant selection.

Robomituba often runs inside Docker containers where the NVIDIA driver and
OptiX runtime are inherited from the host. In that setup a CUDA variant can be
compiled into Mitsuba but still fail at runtime when Dr.Jit asks for a newer
OptiX ABI than the host driver provides. The helpers in this module choose the
fastest variant that can actually be activated in the current process.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)

AUTO_VARIANT = "auto"
ENV_VARIANT = "ROBOMITUBA_MITSUBA_VARIANT"
ENV_DISABLE_CUDA = "ROBOMITUBA_DISABLE_CUDA"
# Set to 1 to refuse falling back to LLVM/scalar variants when a CUDA
# variant fails at runtime. Default is unset (fallback allowed) so docker
# hosts without a working OptiX driver can still render. Operators who
# explicitly want CUDA-only — and prefer a clear failure over a 100× slow
# CPU render — should set ``ROBOMITUBA_DISABLE_CPU_FALLBACK=1``.
ENV_DISABLE_CPU_FALLBACK = "ROBOMITUBA_DISABLE_CPU_FALLBACK"

_VARIANTS_CACHE: list[str] | None = None
_WORKING_CACHE: dict[str, bool] = {}
_FAILURE_CACHE: dict[str, str] = {}


class MitsubaVariantUnavailable(RuntimeError):
    """Raised when no requested Mitsuba variant can be activated."""


def available_variants() -> list[str]:
    """Return variants compiled into the importable Mitsuba package."""
    global _VARIANTS_CACHE
    if _VARIANTS_CACHE is not None:
        return list(_VARIANTS_CACHE)

    try:
        import mitsuba as mi
    except ImportError:
        _VARIANTS_CACHE = []
        return []

    try:
        variants_fn = getattr(mi, "variants", None)
        if callable(variants_fn):
            _VARIANTS_CACHE = [str(v) for v in variants_fn()]
            return list(_VARIANTS_CACHE)
    except Exception as exc:
        logger.warning("mi.variants() failed: %s", exc)

    probe = (
        "cuda_ad_spectral_polarized",
        "cuda_spectral_polarized",
        "llvm_ad_spectral_polarized",
        "llvm_spectral_polarized",
        "scalar_spectral_polarized",
        "cuda_spectral",
        "cuda_ad_spectral",
        "cuda_rgb",
        "cuda_ad_rgb",
        "llvm_ad_spectral",
        "llvm_spectral",
        "llvm_ad_rgb",
        "llvm_rgb",
        "scalar_spectral",
        "scalar_rgb",
    )
    found: list[str] = []
    for variant in probe:
        if _can_set_variant(variant):
            found.append(variant)
    _VARIANTS_CACHE = found
    return list(found)


def variant_failure(variant: str) -> str | None:
    """Return the last activation failure for ``variant``, if any."""
    return _FAILURE_CACHE.get(str(variant))


def mark_variant_unavailable(variant: str, error: BaseException | str) -> None:
    """Mark ``variant`` as unusable after a late load/render failure."""
    variant = str(variant)
    _WORKING_CACHE[variant] = False
    if isinstance(error, BaseException):
        _FAILURE_CACHE[variant] = _compact_error(error)
    else:
        _FAILURE_CACHE[variant] = str(error).strip() or "runtime failure"


def ensure_mitsuba_variant(variant: str) -> str:
    """Activate ``variant`` and return the active variant name."""
    resolved = resolve_variant(variant)
    if not _can_set_variant(resolved):
        detail = variant_failure(resolved) or "unknown error"
        raise MitsubaVariantUnavailable(f"Mitsuba variant '{resolved}' is unavailable: {detail}")
    return resolved


def resolve_variant(
    preferred: str | None = None,
    *,
    kind: str = "spectral",
    allow_cpu: bool = True,
) -> str:
    """Resolve a preferred variant or ``auto`` to a working runtime variant.

    ``kind`` can be ``"rgb"``, ``"spectral"``, or ``"spectral_polarized"``.
    CUDA variants are tried first for speed, but activation failures are
    treated as a runtime compatibility signal and the resolver falls back to
    LLVM/scalar variants when ``allow_cpu`` is true.
    """
    requested = _normalize_variant(preferred)
    env_requested = _normalize_variant(os.environ.get(ENV_VARIANT))
    if requested is None and env_requested is not None:
        requested = env_requested

    available = set(available_variants())
    if not available:
        raise MitsubaVariantUnavailable("Mitsuba is not importable or reports no compiled variants.")

    cuda_disabled = _env_flag(ENV_DISABLE_CUDA)
    # When set, treat the caller's allow_cpu=True as a soft hint and
    # forcibly remove every non-CUDA candidate. Means "I'd rather hard-fail
    # than silently render on CPU and burn 100× wall-clock"; operators on
    # a working OptiX driver who never want surprise LLVM jobs set this.
    if _env_flag(ENV_DISABLE_CPU_FALLBACK):
        allow_cpu = False

    if requested is not None:
        candidates = [requested]
        if requested.startswith("cuda_") and allow_cpu:
            candidates.extend(_fallback_order(kind))
    else:
        candidates = list(_priority_order(kind, allow_cpu=allow_cpu))
    if cuda_disabled:
        candidates = [candidate for candidate in candidates if not candidate.startswith("cuda_")]

    seen: set[str] = set()
    failures: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate not in available:
            failures.append(f"{candidate}: not compiled")
            continue
        if _can_set_variant(candidate):
            return candidate
        failures.append(f"{candidate}: {variant_failure(candidate) or 'activation failed'}")

    joined = "; ".join(failures) if failures else "no candidates"
    raise MitsubaVariantUnavailable(f"No working Mitsuba variant for kind={kind!r}. Tried: {joined}")


def _normalize_variant(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped or stripped.lower() in {"auto", "default"}:
        return None
    return stripped


def _env_flag(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _can_set_variant(variant: str) -> bool:
    variant = str(variant)
    try:
        import mitsuba as mi

        cached = _WORKING_CACHE.get(variant)
        active_variant = getattr(mi, "variant", lambda: None)()
        if cached is True and active_variant == variant:
            return True
        if cached is False:
            return False
        if getattr(mi, "variant", lambda: None)() != variant:
            mi.set_variant(variant)
    except Exception as exc:
        _WORKING_CACHE[variant] = False
        _FAILURE_CACHE[variant] = _compact_error(exc)
        return False
    _WORKING_CACHE[variant] = True
    _FAILURE_CACHE.pop(variant, None)
    return True


def _compact_error(exc: BaseException) -> str:
    message = str(exc).strip().replace("\n", " ")
    return message or exc.__class__.__name__


def _priority_order(kind: str, *, allow_cpu: bool) -> Sequence[str]:
    if kind == "spectral_polarized":
        cuda = (
            "cuda_spectral_polarized",
            "cuda_ad_spectral_polarized",
        )
        cpu = (
            "llvm_ad_spectral_polarized",
            "llvm_spectral_polarized",
            "scalar_spectral_polarized",
        )
    elif kind == "rgb":
        cuda = (
            "cuda_rgb",
            "cuda_ad_rgb",
            "cuda_spectral",
            "cuda_ad_spectral",
        )
        cpu = (
            "llvm_ad_rgb",
            "llvm_rgb",
            "llvm_ad_spectral",
            "llvm_spectral",
            "scalar_rgb",
            "scalar_spectral",
        )
    else:
        cuda = (
            "cuda_spectral",
            "cuda_ad_spectral",
            "cuda_rgb",
            "cuda_ad_rgb",
        )
        cpu = (
            "llvm_ad_spectral",
            "llvm_spectral",
            "llvm_ad_rgb",
            "llvm_rgb",
            "scalar_spectral",
            "scalar_rgb",
        )
    return (*cuda, *cpu) if allow_cpu else cuda


def _fallback_order(kind: str) -> Iterable[str]:
    return (v for v in _priority_order(kind, allow_cpu=True) if not v.startswith("cuda_"))
