"""Manifest + thumbnails for the board's 'infinigen_2.2' gallery: every scene of the current pipeline (incl. ones with no render yet).

  python tools/infinigen/build_scene_gallery.py [--out out/scene_gallery/infinigen_2.2]
Per scene: kind, title, seed/tag, rooms + area, a readiness checklist (plan / blend / render / GT / VLM review / human score), the human score and VLM defect
counts of the newest reviewed round, 1-6 sample view thumbnails and the file paths. Scenes without a render carry status 'planned' / 'generating' and no thumbnails.
Reference photos are never copied (they stay local); only our own renders are.
"""
import argparse, glob, json, os, re, shutil, time
from pathlib import Path
from PIL import Image

REPO = Path("/jarvis/project/robomituba"); IV = REPO / "out/infinigen_v2"; O = Path("/tmp/claude-0/objreal"); VR = REPO / "out/vlm_review"
SCORES = os.environ.get("GALLERY_SCORES", "/tmp/claude-0/-jarvis-project-robomituba/2e50bd36-1d06-42cb-8d8e-829a58d12a07/scratchpad/review/scores_dump24/scores")
DATA = os.environ.get("GALLERY_DATA", "/tmp/claude-0/-jarvis-project-robomituba/2e50bd36-1d06-42cb-8d8e-829a58d12a07/scratchpad/review/data.json")
FLOORS = {"A2": ("floorA2_office", "오피스 층 A2"), "B": ("floorB_office", "오피스 층 B (복도형)"), "C": ("floorC_office", "오피스 층 C (고층 로프트)"), "D3": ("floorD3_gp", "일반의원"),
          "E3": ("floorE3_dental", "치과의원"), "F3": ("floorF3_physio", "재활·물리치료 의원"), "G": ("floorG_cafe", "카페 A (소형)"), "H": ("floorH_cafe", "카페 B (대형)"),
          "I": ("floorI_shop", "편의점"), "J": ("floorJ_wh", "창고 + 현장 사무실"), "M": ("floorM2", "식료품 마켓"), "N": ("floorN_lab", "대학 연구동 야간 복도"),
          "N2": ("floorN2_lab", "연구동 층 v2"), "O2": ("floorO2_office", "사무실 층 v2"), "P2b": ("floorP2b_apt", "아파트 v2"),
          "S28F": ("floorS28_parking", "지하 주차장 층"), "S29F": ("floorS29_lounge", "LP 라운지 층"), "PH": ("pivotHouse", "Pivot 중정 주택 (외부 세션 · 검수 중)")}
PLANNED = [("S27", "single", "대학 구내식당 홀", "docs/cafeteria_school_design_proposal.md"), ("O", "floor", "사무실 건물 한 층", "docs/office_floor_design_proposal.md"),
           ("S28", "single", "사무실 건물 지하 주차장", "docs/parking_bldg_design_proposal.md"), ("S29", "single", "LP 카페 휴게 공간", "docs/lounge_lp_cafe_design_proposal.md"),
           ("P1", "floor", "고급 아파트 모델하우스 (대리석 홀, 대형 평형)", "docs/apartment_model_design_proposal.md"),
           ("P2", "floor", "브라질식 아파트 PLANTA TIPO 08 / APTO 02 (14실)", "docs/apartment_model_design_proposal.md"),
           ("P3", "floor", "아이소메트릭 단면 아파트 (L자, 원목 슬랫 벽)", "docs/apartment_model_design_proposal.md"),
           ("P4", "floor", "테라코타 소형 2베드룸 (~55 m2)", "docs/apartment_model_design_proposal.md"),
           ("P5", "floor", "대형 4베드룸 + 서재 (~200 m2)", "docs/apartment_model_design_proposal.md")]


def human_scores():
    H = {}
    for f in glob.glob(SCORES + "/*.json"):
        n = os.path.basename(f)[:-5].split("@")
        if len(n) < 3 or n[2] == "_F":
            continue
        s = json.load(open(f)).get("s")
        if s and any(x is not None for x in s):
            H.setdefault(n[0], {}).setdefault(int(n[1][1:]), {})[n[2]] = [x for x in s if x is not None]
    return H


def review_stats(tag, rnd):
    d = VR / f"{tag}_r{rnd}"; maj = 0; codes = {}; n = 0
    for f in d.glob("*.json"):
        n += 1
        for x in json.load(open(f)).get("defects", []):
            if x["severity"] == "major":
                maj += 1; codes[x["code"]] = codes.get(x["code"], 0) + 1
    return (maj, dict(sorted(codes.items(), key=lambda kv: -kv[1])[:4]), n) if n else (None, {}, 0)


def thumbs(src, out, k):
    names = sorted(p.name for p in Path(src).glob("*_wide*.png"))
    seen, pick = set(), []
    for n in names:                              # one view per room first, then more of the same rooms
        room = re.sub(r"_wide\w*$", "", n[:-4])
        if room not in seen:
            seen.add(room); pick.append(n)
    pick += [n for n in names if n not in pick]
    out.mkdir(parents=True, exist_ok=True); res = []
    for n in pick[:k]:
        im = Image.open(Path(src) / n).convert("RGB"); im.thumbnail((480, 360)); im.save(out / (n[:-4] + ".jpg"), quality=80, optimize=True); res.append(n[:-4] + ".jpg")
    return res


DATASET_VENUE = {"officeK_open": "office_open", "officeJ_private": "office_private", "officeZ_pantry": "office_pantry", "cafeP_industrial": "cafe_industrial", "cafeP_minimal": "cafe_minimal",
                 "cafeP_chain": "cafe_chain", "cafeP_floral": "cafe_floral", "whL_storage": "warehouse_storage", "whA2_packing": "warehouse_packing", "shopL_convenience": "shop_convenience",
                 "clinicW_dental": "clinic_dental", "clinicC2_physio": "clinic_physio", "boutiqueF_flagship": "boutique_flagship", "rooftopR_dining": "rooftop_dining",
                 "winepubR_cellar": "winepub_cellar", "bookstoreR_underground": "bookstore_underground", "museumR_rotunda": "museum_rotunda", "floorC_office": "floor_office_loft",
                 "floorD3_gp": "floor_clinic_gp", "cafeteriaS_school": "cafeteria_school", "shopL_grocery": "shop_grocery", "officeK_meeting": "office_meeting", "clinicV_exam": "clinic_exam", "floorA2_office": "floor_office_open", "floorF3_physio": "floor_clinic_physio", "floorG_cafe": "floor_cafe_small", "officeK_highrise": "office_highrise", "cafeP_nordic": "cafe_nordic", "clinicB2_reception": "clinic_reception", "shopL_pharmacy": "shop_pharmacy", "floorB_office": "floor_office_private", "floorH_cafe": "floor_cafe_large", "floorE3_dental": "floor_clinic_dental", "shopL_boutique": "shop_boutique", "floorJ_wh": "floor_warehouse_packing", "floorI_shop": "floor_shop", "pivotHouse": "pivot_courtyard_house", "barS_cottage": "bar_cottage", "floorM2": "floor_market", "ramenS_counter": "ramen_counter", "cafeS_lphigh": "cafe_lp_highceiling", "floorS29_lounge": "floor_lp_lounge", "restaurantS_stillroom": "restaurant_stillroom", "floorO3_office": "floor_office_bench", "floorO5_creative": "floor_office_creative", "floorH3_hotel": "floor_hotel_rooms", "floorH2_hotel": "floor_hotel_guestrooms", "floorS28_parking": "floor_parking_lobby", "floorO4_wework": "floor_office_cowork", "floorP2b_apt": "floor_model_apartment", "bakeryS_shop": "bakery_shop", "atriumL_lounge": "atrium_lobby_lounge", "floorO2_office": "floor_office_atrium", "floorN2_lab": "floor_lab_research"}      # scene tag -> the venue token of its dataset id (two scenes can share a seed)


def dataset_state(seed, tag=None):
    """hover / walk dataset of a promoted scene: the queue line `..._v2_2_<seed>`, then the corpus dir (claim = rendering, four_pass.json = done)."""
    if not seed:
        return None
    root = Path("/bean/ir_dataset_work/hssd_ir_apartment_v2")
    try:
        ids = [l.split()[0] for l in open("/tmp/claude-0/objreal/nonhome_dataset_queue.txt") if l.strip() and not l.startswith("#") and f"_v2_2_{seed}" in l.split()[0] and l.split()[0].startswith(f"infinigen_{DATASET_VENUE.get(tag, '?')}_v2_2_")]
    except OSError:
        return None
    if not ids:
        return None
    sid = ids[0]; d = root / sid
    hv, wk = (d / "hover/four_pass.json").is_file(), (d / "walk/four_pass.json").is_file()
    state = "완료" if hv and wk else "렌더 중" if (root / ".claims_nonhome" / sid).exists() else "대기"
    return {"id": sid, "state": state, "hover": hv, "walk": wk}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(REPO / "out/scene_gallery/infinigen_2.2")); a = ap.parse_args()
    out = Path(a.out); H = human_scores(); data = json.load(open(DATA)); scenes = []
    cp_path = Path(DATA).parent / "completed.json"; completed = json.load(open(cp_path)) if cp_path.is_file() else {}     # scenes the user promoted
    for e in data:
        sid, rnd = e["id"], int(e["round"][1:])
        if e.get("grp") == "single":
            tag = e["desc"].split(" · ")[0]; kind = "single"; title = e["title"].split(" · ")[-1]
        elif sid in FLOORS:
            tag, title = FLOORS[sid]; kind = "floor"
        else:
            continue
        dirs = [d for d in sorted(IV.glob(f"kr_{tag}_[0-9]*")) if "." not in d.name]
        d = dirs[0] if dirs else None; seed = int(d.name.rsplit("_", 1)[1]) if d else None
        try:
            rooms = json.load(open(d / "full/rooms.json"))["rooms"]; area = round(sum(r["area_m2"] for r in rooms), 1)
        except Exception:
            rooms, area = [], None
        rv = O / f"rvs_{tag}_r{rnd}"; gt = O / f"gt_{tag}_r{rnd}"
        maj, codes, nrev = review_stats(tag, rnd)
        hr = H.get(sid, {}); hrnd = max(hr) if hr else None; hs = hr.get(hrnd, {}) if hrnd else {}
        vals = [v for s in hs.values() for v in s]
        status = "rendered" if rv.is_dir() else ("generating" if d else "planned")
        sd = out / "thumbs" / sid
        scenes.append({"id": sid, "kind": kind, "title": title, "tag": tag, "seed": seed, "round": rnd, "status": status, "rooms": len(rooms), "area_m2": area,
            "readiness": {"plan": bool(rooms), "blend": bool(d and (d / "full/scene_mat2_activity.blend").is_file()), "render": rv.is_dir(), "gt": gt.is_dir(), "vlm_review": nrev > 0, "human_score": bool(hs)},
            "human": {"round": hrnd, "avg": round(sum(vals) / len(vals), 2) if vals else None, "min": min(vals) if vals else None,
                      "rooms_pass": sum(1 for s in hs.values() if min(s) >= 7), "rooms_scored": len(hs)},
            "vlm": {"major": maj, "top": codes, "rooms_reviewed": nrev},
            "samples": [f"thumbs/{sid}/{n}" for n in (thumbs(rv, sd, 6 if kind == "floor" else 4) if rv.is_dir() else [])],
            "paths": {"blend": str(d / "full/scene_mat2_activity.blend") if d else None, "renders": str(rv) if rv.is_dir() else None, "gt": str(gt) if gt.is_dir() else None}})
    have = {s["id"] for s in scenes}
    for sid, (tag, title) in FLOORS.items():                    # floors the review page does not carry yet (e.g. N while it renders)
        if sid in have:
            continue
        rounds = sorted(int(m.group(1)) for p in O.glob(f"rvs_{tag}_r*") if (m := re.search(r"_r(\d+)$", p.name)))
        dirs = [d for d in sorted(IV.glob(f"kr_{tag}_[0-9]*")) if "." not in d.name]; d = dirs[0] if dirs else None
        if not d:
            continue
        rnd = rounds[-1] if rounds else None; rv = O / f"rvs_{tag}_r{rnd}" if rnd else None
        try:
            rooms = json.load(open(d / "full/rooms.json"))["rooms"]
        except Exception:
            rooms = []
        maj, codes, nrev = review_stats(tag, rnd) if rnd else (None, {}, 0)
        scenes.append({"id": sid, "kind": "floor", "title": title, "tag": tag, "seed": int(d.name.rsplit("_", 1)[1]), "round": rnd, "status": "rendered" if rv and rv.is_dir() else "generating",
            "rooms": len(rooms), "area_m2": round(sum(r["area_m2"] for r in rooms), 1) if rooms else None,
            "readiness": {"plan": bool(rooms), "blend": (d / "full/scene_mat2_activity.blend").is_file(), "render": bool(rv and rv.is_dir()), "gt": bool(rnd and (O / f"gt_{tag}_r{rnd}").is_dir()), "vlm_review": nrev > 0, "human_score": False},
            "human": {"round": None, "avg": None, "min": None, "rooms_pass": 0, "rooms_scored": 0}, "vlm": {"major": maj, "top": codes, "rooms_reviewed": nrev},
            "samples": [f"thumbs/{sid}/{n}" for n in (thumbs(rv, out / "thumbs" / sid, 6) if rv and rv.is_dir() else [])],
            "paths": {"blend": str(d / "full/scene_mat2_activity.blend"), "renders": str(rv) if rv and rv.is_dir() else None}})
    for sid, kind, title, doc in PLANNED:
        scenes.append({"id": sid, "kind": kind, "title": title, "tag": None, "seed": None, "round": None, "status": "planned", "rooms": None, "area_m2": None,
                       "readiness": {"plan": False, "blend": False, "render": False, "gt": False, "vlm_review": False, "human_score": False},
                       "human": {"round": None, "avg": None, "min": None, "rooms_pass": 0, "rooms_scored": 0}, "vlm": {"major": None, "top": {}, "rooms_reviewed": 0},
                       "samples": [], "paths": {"design_doc": doc}})
    for s_ in scenes:
        if s_["id"] == "PH":
            from pivot_courtyard_house_01.register_scene import apply_gallery_entry
            apply_gallery_entry(s_, out, thumbs)
        if s_["id"] in completed:
            s_["title"] += "  ✓ 완성"; s_["complete"] = completed[s_["id"]]
        s_["dataset"] = dataset_state(s_.get("seed"), s_.get("tag"))
    # Persist externally authored reference candidates across normal rebuilds.
    from reference_scene_pipeline.gallery_registry import merge_entries
    scenes = merge_entries(scenes, output_dir=out)
    order = {"rendered": 0, "generating": 1, "planned": 2}
    scenes.sort(key=lambda s: (order[s["status"]], -(s["human"]["avg"] or 0), s["id"]))
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps({"branch": "infinigen_2.2", "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "count": len(scenes), "scenes": scenes}, ensure_ascii=False, indent=1))
    print(len(scenes), "scenes;", sum(1 for s in scenes if s["status"] == "rendered"), "rendered;", sum(len(s["samples"]) for s in scenes), "thumbnails ->", out)


if __name__ == "__main__":
    main()
