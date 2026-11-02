"""Pipeline + parallel-save behaviour for the K-view Stokes batch path.

These cover the two properties the fast path depends on and that nothing else
asserts: a deferred batch publishes only after its tail runs, and the pipeline
never lets two tails overlap.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from mitsuba_converter.multimodal import (
    _save_polarization_products_batch,
    polar_save_worker_count,
)
from mitsuba_converter.preview_worker import _SavePipeline


REQUESTED = {"polar_rgb_preview", "dop", "aolp", "s1", "s2", "s1_over_s0", "s2_over_s0"}


def _strip(height: int = 24, width: int = 32, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    strip = np.abs(rng.normal(0.3, 0.25, size=(height, width, 15))).astype(np.float32)
    strip[:, :, 6:15] *= 0.15
    return strip


def test_parallel_save_matches_serial_bytes(tmp_path):
    """Threading the save must not perturb a single output byte."""
    strips = [_strip(seed=index) for index in range(4)]

    def run(workers: int, tag: str):
        dests = [tmp_path / tag / f"v{index}" for index in range(len(strips))]
        for dest in dests:
            dest.mkdir(parents=True)
        import os

        os.environ["ROBOMITUBA_POLAR_SAVE_WORKERS"] = str(workers)
        saved = _save_polarization_products_batch(
            strips, dests, REQUESTED, visualization_policy="full_v1"
        )
        blobs = {
            str(path.relative_to(tmp_path / tag)): path.read_bytes()
            for path in sorted((tmp_path / tag).rglob("*"))
            if path.is_file()
        }
        return saved, blobs

    serial, serial_blobs = run(1, "serial")
    pooled, pooled_blobs = run(4, "pooled")

    assert serial_blobs.keys() == pooled_blobs.keys()
    assert serial_blobs == pooled_blobs
    for (s_summary, s_arrays), (p_summary, p_arrays) in zip(serial, pooled):
        assert s_summary["schema_version"] == p_summary["schema_version"] if "schema_version" in s_summary else True
        for key in s_arrays:
            np.testing.assert_array_equal(s_arrays[key], p_arrays[key])


def test_save_worker_count_never_exceeds_batch():
    assert polar_save_worker_count(1) == 1
    assert polar_save_worker_count(2) <= 2
    assert polar_save_worker_count(64) >= 1


def test_pipeline_defers_then_publishes():
    """submit() returns before the tail runs; drain() guarantees it has."""
    pipeline = _SavePipeline()
    published: list[str] = []
    release = threading.Event()

    def tail() -> None:
        release.wait(timeout=5.0)
        published.append("done")

    pipeline.submit(tail)
    assert published == [], "submit must not block on the tail"
    release.set()
    pipeline.drain(timeout=5.0)
    assert published == ["done"]


def test_pipeline_depth_is_one():
    """A second submit blocks until the first tail has finished."""
    pipeline = _SavePipeline()
    order: list[str] = []
    lock = threading.Lock()
    first_started = threading.Event()
    let_first_finish = threading.Event()

    def first() -> None:
        first_started.set()
        let_first_finish.wait(timeout=5.0)
        with lock:
            order.append("first")

    def second() -> None:
        with lock:
            order.append("second")

    pipeline.submit(first)
    assert first_started.wait(timeout=5.0)

    done = threading.Event()

    def submit_second() -> None:
        pipeline.submit(second)
        done.set()

    thread = threading.Thread(target=submit_second)
    thread.start()
    # The second submit must still be waiting on the first tail.
    assert not done.wait(timeout=0.5)
    let_first_finish.set()
    assert done.wait(timeout=5.0)
    pipeline.drain(timeout=5.0)
    thread.join(timeout=5.0)
    assert order == ["first", "second"]


def test_pipeline_failure_does_not_leak_into_next_batch():
    """A raising tail is swallowed by drain so it cannot fail the next job."""
    pipeline = _SavePipeline()

    def boom() -> None:
        raise RuntimeError("tail exploded")

    pipeline.submit(boom)
    pipeline.drain(timeout=5.0)  # must not raise

    ran: list[str] = []
    pipeline.submit(lambda: ran.append("next"))
    pipeline.drain(timeout=5.0)
    assert ran == ["next"]


def test_pipeline_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ROBOMITUBA_POLAR_SAVE_PIPELINE", raising=False)
    assert _SavePipeline().enabled is False
    monkeypatch.setenv("ROBOMITUBA_POLAR_SAVE_PIPELINE", "1")
    assert _SavePipeline().enabled is True
