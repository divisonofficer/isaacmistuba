"""Where a texture's writing sits in 3D: aim point, outward normal, size.

The hover planner aims at a bounding-box centre, which is the right answer for
"show me this object" and the wrong one for "read what is printed on it". A
chair's lettering can sit on one face, off-centre, facing away from the arc.
This maps the OCR box in UV space onto the mesh and returns what a camera needs:
a point to look at, a direction to look from, and the physical height of the
writing -- which is what decides how close the camera has to be.
"""
from __future__ import annotations
import numpy as np


def anchor(scene, uv_box, min_faces=1, image=None):
    """uv_box = (u0, v0, u1, v1) in IMAGE coords, v measured DOWNWARD.

    glTF stores v downward, but trimesh flips it on load: checked against the
    raw TEXCOORD_0 accessor of B073P19S5F, trimesh_v == 1 - gltf_v exactly. So
    the box has to be flipped to match the mesh it is being compared against.

    Getting this wrong does not fail. It aims at the text's mirror image, which
    is still ON the object, so the render looks like a plausible close-up of the
    wrong part -- a tube-map poster framed square on its blank margin with the
    words just out of shot. That is what it did for every flat target.
    """
    u0, v0, u1, v1 = uv_box
    v0, v1 = 1.0 - v1, 1.0 - v0
    best = None
    for name, g in getattr(scene, "geometry", {}).items():
        uv = getattr(getattr(g, "visual", None), "uv", None)
        if uv is None or len(uv) != len(g.vertices):
            continue
        # UV is per material. A framed print carries the picture and the moulding
        # as two materials with their own atlases, so a box read off the PICTURE
        # also overlaps faces of the FRAME -- and the frame usually wins on area.
        # The camera then sits square on the moulding with the words just out of
        # shot, which renders as a plausible close-up of the wrong thing.
        if image is not None:
            mat = getattr(getattr(g, "visual", None), "material", None)
            if getattr(mat, "baseColorTexture", None) is not image:
                continue
        uv = np.asarray(uv, dtype=np.float64)
        f = np.asarray(g.faces)
        # Overlap, not centroid-in-box. A letter is often smaller than one
        # triangle, so every centroid can sit outside the box while the glyph is
        # squarely on that face -- which read as "this object has no geometry
        # for its own text".
        tu = uv[f]
        lo = tu.min(axis=1); hi = tu.max(axis=1)
        inside = (hi[:, 0] >= u0) & (lo[:, 0] <= u1) & (hi[:, 1] >= v0) & (lo[:, 1] <= v1)
        if inside.sum() < min_faces:
            continue
        T = np.eye(4)
        try:
            nodes = scene.graph.geometry_nodes.get(name) or []
            if nodes:
                T = np.asarray(scene.graph.get(nodes[0])[0], dtype=np.float64)
        except Exception:
            pass
        V = np.asarray(g.vertices)
        V = (T[:3, :3] @ V.T).T + T[:3, 3]
        sel = f[inside]
        pts = V[sel].reshape(-1, 3)
        tri = V[sel]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        area = np.linalg.norm(n, axis=1) / 2.0
        if area.sum() <= 0:
            continue
        nrm = (n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12))
        nrm = (nrm * area[:, None]).sum(axis=0)
        nrm = nrm / max(np.linalg.norm(nrm), 1e-12)
        # Metres per UV unit, from the selected faces' own 3D-to-UV area ratio.
        # The faces' bounding box is NOT the text's size: a whole panel is often
        # two triangles, so a 4-cm word and the 60-cm board it is printed on
        # would report the same extent and send the camera to the wrong distance.
        tuv = tu[inside]
        e1 = tuv[:, 1] - tuv[:, 0]; e2 = tuv[:, 2] - tuv[:, 0]
        # 2-D cross by hand: numpy 2 removed the 2-vector form of np.cross
        uv_area = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2.0
        scale_m_per_uv = float(np.sqrt(area.sum() / max(uv_area.sum(), 1e-12)))
        # The aim point is the uv box CENTRE carried onto the surface, not the
        # centroid of the faces that touch it. When one triangle pair covers a
        # whole panel -- the normal case for wall art -- a centroid returns the
        # middle of the panel however far into a corner the writing sits, and
        # the camera then frames the wrong place while still looking at the
        # object, which no render would flag.
        uc, vc = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        aim = None
        for fi in np.nonzero(inside)[0]:
            a2, b2, c2 = tu[fi]
            d = (b2[1] - c2[1]) * (a2[0] - c2[0]) + (c2[0] - b2[0]) * (a2[1] - c2[1])
            if abs(d) < 1e-12:
                continue
            w0 = ((b2[1] - c2[1]) * (uc - c2[0]) + (c2[0] - b2[0]) * (vc - c2[1])) / d
            w1 = ((c2[1] - a2[1]) * (uc - c2[0]) + (a2[0] - c2[0]) * (vc - c2[1])) / d
            w2 = 1.0 - w0 - w1
            if min(w0, w1, w2) >= -1e-9:
                aim = w0 * V[f[fi][0]] + w1 * V[f[fi][1]] + w2 * V[f[fi][2]]
                break
        if aim is None:          # centre falls in a uv seam; fall back to faces
            aim = pts.mean(axis=0)
        extent = pts.max(axis=0) - pts.min(axis=0)
        # Height of the writing on the surface: the box's v-extent scaled by how
        # much of the mesh that uv span covers. Taken from the selected faces
        # rather than the whole object, because a uv atlas is not to scale.
        cand = {"geometry": name, "faces": int(inside.sum()),
                "point": aim, "normal": nrm,
                "extent_m": extent, "diag_m": float(np.linalg.norm(extent)),
                "m_per_uv": scale_m_per_uv,
                "text_h_m": float((v1 - v0) * scale_m_per_uv),
                "text_w_m": float((u1 - u0) * scale_m_per_uv),
                "area_m2": float(area.sum())}
        if best is None or cand["area_m2"] > best["area_m2"]:
            best = cand
    return best


def _self_check() -> None:
    """A 2 m x 1 m quad whose uv fills [0,1]: a uv box of known size must come
    back as a patch of the matching size in metres, on the surface, facing +Z.

    The case that matters is the one that broke the first version: the writing
    is far smaller than the single triangle pair carrying it, so a size taken
    from the selected faces' bounding box would report the whole 2 m panel.
    """
    import numpy as np, trimesh
    v = np.array([[-1.0, -0.5, 0.0], [1.0, -0.5, 0.0], [1.0, 0.5, 0.0], [-1.0, 0.5, 0.0]])
    f = np.array([[0, 1, 2], [0, 2, 3]])
    # Mesh-space uv, i.e. what trimesh hands back: v UP. Image (0,0) is the
    # top-left, which is mesh v=1, so the quad's top-left vertex (index 3,
    # at +y) carries uv (0,1).
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    m = trimesh.Trimesh(vertices=v, faces=f, process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=uv)
    scene = trimesh.Scene({"panel": m})

    # a tenth of the width, a fifth of the height, centred
    got = anchor(scene, (0.45, 0.40, 0.55, 0.60))
    assert got is not None, "the box sits on the quad; it must find faces"
    # 2 m x 1 m over 1 uv x 1 uv -> sqrt(2/1) m per uv unit
    expect = (2.0 * 1.0 / 1.0) ** 0.5
    assert abs(got["m_per_uv"] - expect) < 1e-6, got["m_per_uv"]
    assert abs(got["text_h_m"] - 0.2 * expect) < 1e-6, got["text_h_m"]
    assert abs(got["text_w_m"] - 0.1 * expect) < 1e-6, got["text_w_m"]
    # NOT the panel: a bounding-box size would be ~2 m here
    assert got["text_h_m"] < 0.5, "size came from the faces, not the uv box"
    assert abs(abs(got["normal"][2]) - 1.0) < 1e-6, got["normal"]
    assert np.allclose(got["point"][:2], [0.0, 0.0], atol=1e-6), got["point"]

    # a box in a corner must land off-centre, and on the correct side: a flipped
    # v would mirror it to the opposite corner and still sit on the object
    # An IMAGE box at the top-left must land on the quad's top-left, +y. If the
    # flip were dropped this lands at -y: still on the panel, still renderable,
    # and wrong -- which is exactly how the bug survived a render.
    corner = anchor(scene, (0.0, 0.0, 0.2, 0.2))
    assert corner is not None
    assert corner["point"][1] > 0, f"image v=0 is the +y top edge, got {corner['point']}"
    bottom = anchor(scene, (0.0, 0.8, 0.2, 1.0))
    assert bottom is not None and bottom["point"][1] < 0, bottom["point"]

    # a box off the quad entirely has no geometry to aim at
    assert anchor(scene, (2.0, 2.0, 2.1, 2.1)) is None
    print("self-check ok")


if __name__ == "__main__":
    _self_check()
