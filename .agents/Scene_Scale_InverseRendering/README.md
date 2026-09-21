# Scene_Scale_InverseRendering (IR)

Scene-scale inverse rendering: render multimodal PBR corpora (HSSD hover video, ABO
environments) and train memory-IR models on them (scene_ir_ff, memory_ir).

| Agent | Owns | GPUs |
|---|---|---|
| IR_PIPELINE_ORCHESTER | v13 training + eval; corpus consumer | 4,5,7 |
| IR_DATASET_HSSD_ORCHESTER | render_hover_v1 corpus, hssd_blender_ir tree | 0,2,3 |
| IR_DATASET_ABO_ORCHESTER | abo_cornell_env_v1 corpus | 1,6 |
| IR_DATASET_INFINIGEN_ORCHESTER | Infinigen-sourced IR corpus: generate, import, stage, render, review tooling | none |
| IR_DATASET_VIEWER_ORCHESTER | apps/ir_dataset_viewer (Codex thread) | none |
| IR_DATASET_INFINIGEN_ORCHESTER | Infinigen IR corpora, scripts/infinigen_*, import tooling | none |

Workers: SONNET_WORKER_1 and SONNET_WORKER_2 from `../shared_workers/`.

ABO corpora on /bean/ir_dataset: abo_cornell_v2, abo_cornell_video_v1, abo_cornell_env_v1;
`abo_v1` is an object index, not a corpus; `abo_cornell_v1` does not exist.

Dependency chain: HSSD/ABO .done scenes → v3 manifests → v13 training. Corpus
orchesters must notify IR_PIPELINE_ORCHESTER before removing any .done scene.
