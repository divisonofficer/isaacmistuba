#!/usr/bin/env bash
set -eu
cd /jarvis/project/robomituba
export CUDA_VISIBLE_DEVICES=
blender_python=/root/miniconda3/envs/infinigen/bin/python
out_dir=/tmp/claude-0/s/codex_pkgs/pkg_c
mkdir -p "$out_dir"
for spec in S37:convS_corner:47312701 S38:liquorS_wine:47312801 S39:brickS_resto:47312901; do
 IFS=: read -r tag scene_tag seed <<< "$spec"
 flock /tmp/claude-0/objreal/blender_test.lock "$blender_python" tools/infinigen/ratio1_pkg_c_launch.py "out/infinigen_v2/kr_${scene_tag}_${seed}/full/scene_mat2_activity.blend" --tag "$tag" --out "$out_dir/$tag" > "$out_dir/${tag}.log" 2>&1
 if [ "$tag" = S37 ]; then python3 tools/infinigen/ratio1_pkg_c_pixels.py; fi
done
