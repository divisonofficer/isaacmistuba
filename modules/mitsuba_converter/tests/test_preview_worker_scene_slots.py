from __future__ import annotations

import json
import os

from mitsuba_converter import preview_worker


def test_slot_holder_with_dead_pid_is_stale() -> None:
    assert preview_worker._slot_holder_is_stale({"pid": -1, "heartbeat_at": 100.0}, now=101.0, stale_after_s=120.0)


def test_slot_holder_with_old_heartbeat_is_stale(monkeypatch) -> None:
    monkeypatch.setattr(preview_worker, "_pid_is_alive", lambda pid: True)

    assert preview_worker._slot_holder_is_stale({"pid": 123, "heartbeat_at": 100.0}, now=300.0, stale_after_s=120.0)


def test_slot_holder_with_fresh_heartbeat_is_not_stale(monkeypatch) -> None:
    monkeypatch.setattr(preview_worker, "_pid_is_alive", lambda pid: True)

    assert not preview_worker._slot_holder_is_stale({"pid": 123, "heartbeat_at": 250.0}, now=300.0, stale_after_s=120.0)


def test_clear_stale_scene_load_slot_removes_dead_holder(tmp_path) -> None:
    slot = tmp_path / "slot_0"
    slot.mkdir()
    (slot / "holder.json").write_text(json.dumps({"pid": -1, "heartbeat_at": 100.0}), encoding="utf-8")

    assert preview_worker._clear_stale_scene_load_slot(slot, now=101.0, stale_after_s=120.0)
    assert not slot.exists()


def test_clear_stale_scene_load_slot_keeps_fresh_live_holder(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(preview_worker, "_pid_is_alive", lambda pid: True)
    slot = tmp_path / "slot_0"
    slot.mkdir()
    (slot / "holder.json").write_text(json.dumps({"pid": os.getpid(), "heartbeat_at": 250.0}), encoding="utf-8")

    assert not preview_worker._clear_stale_scene_load_slot(slot, now=300.0, stale_after_s=120.0)
    assert slot.exists()
    assert (slot / "holder.json").exists()


def test_scene_load_stale_after_uses_timeout_plus_buffer(monkeypatch) -> None:
    monkeypatch.setenv("ROBOMITUBA_SCENE_LOAD_TIMEOUT_S", "900")

    assert preview_worker._scene_load_stale_after_s() == 960.0


def test_scene_load_stale_after_has_minimum(monkeypatch) -> None:
    monkeypatch.setenv("ROBOMITUBA_SCENE_LOAD_TIMEOUT_S", "10")

    assert preview_worker._scene_load_stale_after_s() == 120.0
