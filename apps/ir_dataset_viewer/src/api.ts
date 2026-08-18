export type Origin = { kind: 'bean' | 'out'; name: string; path: string };
export type ModalityGroup = { id: string; label: string; modalities: string[] };
export type DatasetSummary = {
  dataset_id: string; name: string; fingerprint: string; frame_count: number; viewpoint_count: number;
  width: number; height: number; modalities: string[]; modality_groups: ModalityGroup[];
  origins: Origin[]; primary_origin: string; published: boolean; publishable: boolean;
  qc: Record<string, unknown>; warnings: string[]; scene_statistics: SceneStatisticsCompact;
};
export type SceneStatisticsCompact = { known: boolean; density_class: 'sparse'|'moderate'|'dense'|'unknown'; metal_class?: 'balanced-metal'|'metal-rich'|'metal-sparse'|'unknown'; unknown_reason?: string | null; room_type?: string | null; requested_furnishing_density?: string | null; content_audit_status?: string | null; object_count?: number | null; nonstructural_object_count?: number | null; room_area_m2?: number | null; nonstructural_objects_per_m2?: number | null; selected_visible_object_median?: number | null; selected_nonstructural_fraction_median?: number | null; selected_sparse_pose_fraction?: number | null; selected_pose_count?: number | null; material_mix_profile?: string | null; high_metallic_material_count?: number | null; texture_metallic_material_count?: number | null; high_metallic_valid_pixel_fraction?: number | null; metallic_visibility_pose_fraction?: number | null; dominant_metal_object_ratio?: number | null; material_mix_status?: string | null; material_visibility_status?: string | null };
export type SceneCatalog = { scenes: DatasetSummary[]; total: number; filtered: number; distribution: Record<string, number>; medians: { objects_per_m2: number | null; visible_objects: number | null; total_objects: number | null; nonstructural_objects: number | null; room_area_m2: number | null }; facets: { room_types: string[]; origins: string[]; audit_statuses: string[] } };
export type FrameCompact = { frame_id: string; heading_deg: number; available: string[] };
export type Viewpoint = { viewpoint_id: string; frames: FrameCompact[] };
export type FrameDetail = { dataset: DatasetSummary; frame: Record<string, any>; available: Record<string, boolean> };
export type PixelResponse = { x: number; y: number; values: Record<string, { available: boolean; value?: unknown; unit?: string }> };
export type OverviewPose = { frame_id: string; viewpoint_id: string; heading_deg: number; origin: number[]; target: number[]; up: number[]; fov_deg: number; aspect: number; lighting_id: string };
export type SceneOverview = { schema: string; dataset_id: string; dataset_fingerprint: string; coordinate_system: string; graph_available: boolean; traversability_available: boolean; fallback: boolean; bounds: { min: number[]; max: number[] }; nodes: { viewpoint_id: string; origin: number[]; clearance_m?: number }[]; edges: { source: string; target: string }[]; poses: OverviewPose[]; lighting_ids: string[]; traversability?: { path: string; origin?: number[]; resolution_m: number; width: number; height: number; row_axis: string }; proxy_mesh?: { path: string; sha256: string; triangles: number; byte_count: number; bounds: { min: number[]; max: number[] }; coordinate_system: string; compiler_version: string; semantic_groups: string[] } };
export type PublishJob = {
  job_id: string; name: string; status: string; stage: string; files_done: number; files_total: number;
  bytes_done: number; bytes_total: number; speed_bytes_s: number; eta_s: number | null; error?: string | null;
};

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).error ?? message; } catch { /* response is not JSON */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const listDatasets = (refresh = false) =>
  fetch(`/api/datasets${refresh ? '?refresh=1' : ''}`).then(json<{ datasets: DatasetSummary[]; errors: unknown[] }>);
export const listScenes = (params: Record<string, string> = {}) => fetch(`/api/scenes?${new URLSearchParams(params)}`).then(json<SceneCatalog>);
export const getScene = (id: string) => fetch(`/api/scenes/${encodeURIComponent(id)}`).then(json<{ scene: DatasetSummary; statistics: Record<string, unknown> | null; browse_url: string }>);
export const getDataset = (id: string) => fetch(`/api/datasets/${encodeURIComponent(id)}`).then(json<any>);
export const getViewpoints = (id: string) =>
  fetch(`/api/datasets/${encodeURIComponent(id)}/viewpoints`).then(json<{ viewpoints: Viewpoint[] }>);
export const getFrame = (id: string, frame: string) =>
  fetch(`/api/datasets/${encodeURIComponent(id)}/frames/${encodeURIComponent(frame)}`).then(json<FrameDetail>);
export function previewUrl(id: string, frame: string, modality: string, controls: DisplayControls, profile: 'primary' | 'comparison' | 'hover' = 'primary'): string {
  const q = new URLSearchParams({ ev: String(controls.ev), min: String(controls.minimum), max: String(controls.maximum) });
  if (profile === 'comparison') q.set('max_width', '384');
  if (profile === 'hover') q.set('max_width', '256');
  q.set('format', 'auto');
  if (controls.overlay) { q.set('overlay', controls.overlay); q.set('opacity', String(controls.overlayOpacity)); }
  return `/api/datasets/${encodeURIComponent(id)}/frames/${encodeURIComponent(frame)}/preview/${encodeURIComponent(modality)}?${q}`;
}
export const getOverview = (id: string) => fetch(`/api/datasets/${encodeURIComponent(id)}/overview`).then(json<SceneOverview>);
export const overviewTraversabilityUrl = (id: string) => `/api/datasets/${encodeURIComponent(id)}/overview/traversability`;
export const overviewMeshUrl = (id: string) => `/api/datasets/${encodeURIComponent(id)}/overview/mesh`;
export const getPixels = (id: string, frame: string, x: number, y: number, modalities: string[]) => {
  const q = new URLSearchParams({ x: String(x), y: String(y), modalities: modalities.join(',') });
  return fetch(`/api/datasets/${encodeURIComponent(id)}/frames/${encodeURIComponent(frame)}/pixels?${q}`).then(json<PixelResponse>);
};
export const publishDataset = (dataset_id: string, name: string) => fetch('/api/publish', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dataset_id, name })
}).then(json<PublishJob>);
export const getPublishJob = (id: string) => fetch(`/api/publish/${encodeURIComponent(id)}`).then(json<PublishJob>);
export const cancelPublishJob = (id: string) => fetch(`/api/publish/${encodeURIComponent(id)}/cancel`, { method: 'POST' }).then(json<PublishJob>);

export type ControllerJob = {
  job_id: string; status: string; stage: string; priority: number; created_at: string; updated_at: string;
  started_at?: string | null; finished_at?: string | null; error?: string | null; pid?: number | null;
  request: Record<string, any>; paths: Record<string, string>; stage_results: Record<string, any>; external_import_pids?: number[];
  stage_progress?: Record<string, { completed: number; total: number; percent: number; label?: string; checkpointed?: boolean; estimated?: boolean;
    phase?: string; phase_index?: number; phase_count?: number; local_completed?: number | null; local_total?: number | null; object_count?: number | null; lighting_groups?: Record<string, unknown> }>;
  resource_class?: string | null; resource_state?: string; queue_position?: number | null; resource_gpu_indices?: number[];
  desired_gpu_indices?: number[]; draining_gpu_indices?: number[]; eligible_gpu_indices?: number[];
};
export type RecoveryPlan = { job_id: string; recommended_rerun_from: string | null; insertable_stages: string[]; can_resume: boolean;
  stages: { stage: string; state: 'Verified' | 'Missing' | 'Stale' | 'Failed' | 'Pending'; resource_class: string; selected: boolean }[] };
export type GPUOwner = { job_id: string; dataset_name?: string; stage: string; lease_state: 'assigned' | 'desired' | 'draining' };
export type GPU = { index: number; name: string; memory_used_mib: number; memory_total_mib: number; utilization_pct: number;
  eligible: boolean; reserved: boolean; owners?: GPUOwner[] };
export type ControllerStatus = { jobs: ControllerJob[]; queue: string[]; active_job_id?: string | null; gpu_inventory: GPU[];
  gpu_pool?: number[]; resource_config?: Record<string, any> };
export type ControllerRequest = {
  source_mode: 'generate' | 'existing' | 'augmentation'; dataset_name: string; scene_id?: string; gpu_indices: number[];
  width: number; height: number; fov: number; rgb_spp: number; nir_spp: number;
  flash_energy_scale: number; ambient_fill_energy_scale: number;
  illumination_diversity?: boolean; paired_fraction?: number;
  pose_budget: number;
  camera_policy?: 'content_aware_v2' | 'coverage_v1'; content_profile?: 'balanced' | 'anchor_rich' | 'structural' | 'research_balanced'; material_mix_profile?: 'specular_inverse_balanced_v1'; max_quality_variations?: number;
  adaptive_pose_budget?: boolean; sparse_negative_fraction?: number; max_headings_per_node?: number;
  graph_max_nodes: number; graph_heading_count: number; graph_min_node_spacing: number; graph_robot_radius: number;
  archetype?: string; room_type?: string; density?: string; generation_stage?: string; seed?: string; existing_output?: string;
  legacy_dataset_name?: string;
  variation_id?: number; anchor_richness?: 'minimal' | 'balanced' | 'rich' | 'storage'; surface_clutter?: 'low' | 'balanced' | 'rich' | 'storage';
};
export const getControllerStatus = (signal?: AbortSignal) =>
  fetch('/api/controller/status', { signal }).then(json<ControllerStatus>);
export const listControllerJobs = () => fetch('/api/controller/jobs').then(json<{ jobs: ControllerJob[]; queue: string[]; active_job_id?: string | null }>);
export const getControllerLog = (id: string, signal?: AbortSignal) =>
  fetch(`/api/controller/jobs/${encodeURIComponent(id)}/log?tail=120`, { signal }).then(json<{ lines: string[] }>);
export const getRecoveryPlan = (id: string) => fetch(`/api/controller/jobs/${encodeURIComponent(id)}/recovery-plan`).then(json<RecoveryPlan>);
export const listInfinigenOutputs = (signal?: AbortSignal) =>
  fetch('/api/controller/infinigen-outputs', { signal }).then(json<{ outputs: { relative_path: string; scene_blend: string }[] }>);
export const submitControllerJob = (body: ControllerRequest) => fetch('/api/controller/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(json<ControllerJob>);
export const controllerJobAction = (id: string, action: 'cancel' | 'retry' | 'resume' | 'adopt' | 'priority', body: Record<string, unknown> = {}) =>
  fetch(`/api/controller/jobs/${encodeURIComponent(id)}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(json<ControllerJob>);

export type DisplayControls = { ev: number; minimum: number; maximum: number; overlay: string; overlayOpacity: number };
