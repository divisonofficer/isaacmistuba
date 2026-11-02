"""pytest tools/infinigen/test_scene_loop.py -- the launch-line parser and the per-scene lock."""
import fcntl, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import scene_loop as sl

L1 = "env ROOM_FLOOR_SCUFF=1 \"GEN_ARGS=a=('uniform', 3.0, 3.3)\" RENDER_GPU=3 ARCHETYPE=office REF=/x/kit.json ./venue_pipeline_v17.sh 47310506 break-room shopL_pharmacy pharmacy > venue_shopL_pharmacy_r19.out 2>&1 && ./bg_render.sh shopL_pharmacy kr_d 3 66 > bg.out 2>&1; bash gt_round.sh shopL_pharmacy r19 47310506 3 > g.out 2>&1"
L2 = "run venue_officeJ_private.out RENDER_GPU=1 PROBE_HFOV=65 ./venue_pipeline_v16.sh 47308703 office officeJ_private office &"


def test_env_line():
    tag, rnd, r = sl.parse_line(L1)
    assert (tag, rnd, r["gpu"]) == ("shopL_pharmacy", 19, 3)
    assert r["env"]["GEN_ARGS"] == "a=('uniform', 3.0, 3.3)" and r["args"] == ["47310506", "break-room", "shopL_pharmacy", "pharmacy"]
    assert r["post"][0][:3] == ["./bg_render.sh", "shopL_pharmacy", "kr_d"]


def test_old_run_line():
    tag, rnd, r = sl.parse_line(L2)
    assert (tag, rnd, r["env"]["PROBE_HFOV"], r["args"][-1]) == ("officeJ_private", 0, "65", "office")


def test_lock_is_held(tmp_path, monkeypatch):
    monkeypatch.setattr(sl, "LOCKS", tmp_path)
    fd = os.open(tmp_path / "t.lock", os.O_CREAT | os.O_RDWR); fcntl.flock(fd, fcntl.LOCK_EX)
    assert sl.holder("t") and not sl.holder("other")
