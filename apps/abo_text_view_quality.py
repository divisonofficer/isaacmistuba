#!/usr/bin/env python3
"""Does this camera actually PRESENT the writing, or just graze it?

Not "can OCR read it". Measured against 93 human verdicts on the text screen,
the two questions come apart badly: of 57 frames a person judged well-aimed,
OCR read only a handful. The person was judging whether the camera shows the
object -- square on a real surface, at a distance where you can tell what you
are looking at -- and excluded frames that slide along a floor, look at a thin
panel edge-on, or sit behind a clock looking at its movement.

So the gate is viewing geometry, computed from the pose and the mesh without
rendering anything:

    incidence  angle between the view ray and the surface normal at the aim
               point. Square on is 0. A grazing view is most of the exclusions.
    back_face  the aim point's normal pointing away from the camera: the back
               of the clock, which is a legitimate surface and the wrong one.
    coverage   the target's projected share of the frame. A sliver between two
               panels is "on the object" and shows nothing.
    occluded   something else between the camera and the writing.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


def view_metrics(cam, aim, normal, box_lo=None, box_hi=None, hfov_deg=44.98,
                 width=720, height=540, blockers=()):
    """Geometry of one text pose. Pure maths: no scene, no render, no Blender."""
    cam = np.asarray(cam, float)
    aim = np.asarray(aim, float)
    n = np.asarray(normal, float)
    n = n / max(np.linalg.norm(n), 1e-12)
    view = aim - cam
    dist = float(np.linalg.norm(view))
    if dist < 1e-9:
        return None
    view = view / dist
    # cos between the INCOMING ray and the outward normal. Square on: the normal
    # points back at the camera, so dot(view, n) == -1.
    cos_in = float(np.dot(view, n))
    incidence_deg = math.degrees(math.acos(max(-1.0, min(1.0, -cos_in))))
    out = {"distance_m": round(dist, 4),
           "incidence_deg": round(incidence_deg, 2),
           "back_face": bool(cos_in > 0.0)}

    if box_lo is not None and box_hi is not None:
        lo, hi = np.asarray(box_lo, float), np.asarray(box_hi, float)
        corners = np.array([[x, y, z] for x in (lo[0], hi[0])
                            for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        fx = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
        fwd = view
        up0 = np.array([0.0, 0.0, 1.0])
        right = np.cross(fwd, up0)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([1.0, 0.0, 0.0])
        right = right / np.linalg.norm(right)
        up = np.cross(right, fwd)
        rel = corners - cam
        z = rel @ fwd
        # A box straddling the camera plane has no honest projected extent;
        # report it as zero coverage rather than inventing one from |z|.
        if np.all(z <= 1e-6):
            out["coverage"] = 0.0
        else:
            keep = z > 1e-6
            u = (rel[keep] @ right) / z[keep] * fx + width / 2.0
            v = -(rel[keep] @ up) / z[keep] * fx + height / 2.0
            w = max(0.0, min(width, u.max()) - max(0.0, u.min()))
            h = max(0.0, min(height, v.max()) - max(0.0, v.min()))
            out["coverage"] = round(w * h / (width * height), 4)

    for b_lo, b_hi in blockers:
        if _segment_hits_box(cam, aim, np.asarray(b_lo, float), np.asarray(b_hi, float)):
            out["occluded"] = True
            break
    else:
        out["occluded"] = False
    return out


def _segment_hits_box(p0, p1, lo, hi, eps=1e-4):
    """Slab test, with the ends pulled in so the target's own box does not count."""
    d = p1 - p0
    t0, t1 = eps, 1.0 - eps
    for axis in range(3):
        if abs(d[axis]) < 1e-12:
            if not (lo[axis] <= p0[axis] <= hi[axis]):
                return False
            continue
        a = (lo[axis] - p0[axis]) / d[axis]
        b = (hi[axis] - p0[axis]) / d[axis]
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return False
    return True


def _self_check() -> None:
    # square on a +Z face from above: incidence 0, front face
    m = view_metrics([0, 0, 1], [0, 0, 0], [0, 0, 1])
    assert m["incidence_deg"] < 1e-6 and not m["back_face"], m
    # 60 degrees off
    m = view_metrics([math.sin(math.radians(60)), 0, math.cos(math.radians(60))], [0, 0, 0], [0, 0, 1])
    assert abs(m["incidence_deg"] - 60) < 1e-6, m
    # behind the surface: the normal points away, which is the clock's back
    m = view_metrics([0, 0, -1], [0, 0, 0], [0, 0, 1])
    assert m["back_face"], m
    # coverage: a 1 m cube at 2 m should fill a believable share, not 0 or 1
    m = view_metrics([0, 0, 3], [0, 0, 0], [0, 0, 1], box_lo=[-.5, -.5, -.5], box_hi=[.5, .5, .5])
    assert 0.02 < m["coverage"] < 0.9, m["coverage"]
    # and the same cube at 20 m must cover far less than at 2 m
    far = view_metrics([0, 0, 20], [0, 0, 0], [0, 0, 1], box_lo=[-.5, -.5, -.5], box_hi=[.5, .5, .5])
    assert far["coverage"] < m["coverage"] / 4, (far["coverage"], m["coverage"])
    # occlusion: a slab across the line of sight
    m = view_metrics([0, 0, 2], [0, 0, 0], [0, 0, 1],
                     blockers=[([-1, -1, 0.9], [1, 1, 1.1])])
    assert m["occluded"], m
    m = view_metrics([0, 0, 2], [0, 0, 0], [0, 0, 1],
                     blockers=[([5, 5, 5], [6, 6, 6])])
    assert not m["occluded"], m
    print("self-check ok")


if __name__ == "__main__":
    _self_check()
