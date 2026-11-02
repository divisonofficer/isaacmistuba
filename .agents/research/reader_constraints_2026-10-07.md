# scene_ir_ff reader constraints for data reduction (IR_PIPELINE, 2026-10-07)
- Training reads: EXR rgb_linear, nir_active (HSSD/ABO = active_minus_passive file; Infinigen = nir_direct), depth;
  PNG base_color_rgb, roughness, metallic, metallic_validity, pbr_validity, normal, nir_albedo. Resized to 272 px.
- Half-float EXR OK for all three EXR channels. Use lossless ZIP/PIZ; DWAA untested in cv2 (decode-test first).
- Depth must stay EXR (PNG16 breaks _read_exr_depth). Half depth OK (mask >=50 m, GT already bf16-rounded).
- No read channel must stay float32.
- build_corpus_manifests.py lazily reads extra EXRs (e.g. mr_confidence): ask IR_PIPELINE before changing those.
- Not read by training: diffuse_*, transport, passive. BUT the tier-A/B builder reads transport (other consumer).
- Read channels: keep short side >= 272 px. Unread channels: no resolution constraint from training.
- Builder memo keyed on path+size+mtime: in-place recompress re-converts (hours for HSSD + ~40 min index).
  Keep paths/filenames stable (overlap reuse keyed by depth path). Same-name in-place rewrite safe mid-epoch.
- ckpts 118 GB: smoke dirs + checkpoint.pt (4.6 GB each, optimizer) of finished v37–v42 can go if weights_ep* kept — needs IR_PIPELINE's user.
- Loader cache: unreferenced rows prunable; IR_PIPELINE can produce the list.
