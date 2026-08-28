export type Origin = { kind: 'bean' | 'out'; name: string; path: string };
export type ModalityGroup = { id: string; label: string; modalities: string[] };
export type DatasetSummary = {
  dataset_id: string; name: string; fingerprint: string; frame_count: number; viewpoint_count: number;
  created_at_ns?: number; updated_at_ns?: number;
  width: number; height: number; modalities: string[]; modality_groups: ModalityGroup[];
  origins: Origin[]; primary_origin: string; published: boolean; publishable: boolean;
  qc: Record<string, unknown>; warnings: string[]; scene_statistics: SceneStatisticsCompact;
  scene_review: SceneReviewCompact;
  readiness_label: ReadinessLabelCompact;
};
export type SceneReviewCompact = { known: boolean; review_tier: 'A'|'B'|'C'|'D'|'unknown'; density_class?: string; physical_pose_count?: number; paired_pose_count?: number; paired_pose_ratio?: number; lighting_condition_count?: number; deprecation_candidate?: boolean; requires_visual_qa?: boolean; rationale?: string[] };
export type ReadinessLabelCompact = { known: boolean; status: 'below_target'|'unverified'|'unlabeled'; profile?: string; labels?: string[]; findings?: string[]; recommendation?: string; label_digest?: string; visible_median?: number | null };
export type SceneStatisticsCompact = { known: boolean; density_class: 'sparse'|'moderate'|'dense'|'unknown'; metal_class?: 'balanced-metal'|'metal-rich'|'metal-sparse'|'unknown'; unknown_reason?: string | null; room_type?: string | null; requested_furnishing_density?: string | null; content_audit_status?: string | null; object_count?: number | null; nonstructural_object_count?: number | null; room_area_m2?: number | null; nonstructural_objects_per_m2?: number | null; selected_visible_object_median?: number | null; selected_nonstructural_fraction_median?: number | null; selected_sparse_pose_fraction?: number | null; selected_pose_count?: number | null; material_mix_profile?: string | null; high_metallic_material_count?: number | null; texture_metallic_material_count?: number | null; high_metallic_valid_pixel_fraction?: number | null; metallic_visibility_pose_fraction?: number | null; dominant_metal_object_ratio?: number | null; material_mix_status?: string | null; material_visibility_status?: string | null };
export type SceneCatalog = { scenes: DatasetSummary[]; total: number; filtered: number; distribution: Record<string, number>; review_distribution?: Record<string, number>; medians: { objects_per_m2: number | null; visible_objects: number | null; total_objects: number | null; nonstructural_objects: number | null; room_area_m2: number | null }; facets: { room_types: string[]; origins: string[]; audit_statuses: string[]; review_tiers?: string[] } };
export type FrameCompact = { frame_id: string; heading_deg: number; available: string[]; lighting_id?: string; anchor_id?: string | null; pose_key?: string };
export type HeadingGroup = { heading_key: string; heading_deg: number; anchor_id?: string | null; frames: FrameCompact[]; lighting_ids?: string[] };
export type Viewpoint = { viewpoint_id: string; frames: FrameCompact[]; headings?: HeadingGroup[]; pose_count?: number; lighting_ids?: string[] };
export type FrameDetail = { dataset: DatasetSummary; frame: Record<string, any>; available: Record<string, boolean>; legacy_diffuse_warning?: string | null };
export type BrowseBootstrap = { dataset: DatasetSummary; viewpoints: Viewpoint[]; selected_viewpoint_id: string | null; selected_frame_id: string | null; index_cache: 'hit' | 'miss' | string };
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

/**
 * Browse state is relatively large (a full viewpoint × frame topology) but
 * immutable for a published dataset.  Previously every trip `Scenes →
 * Browse` rebuilt that topology over HTTP, despite it already existing in the
 * same tab.  Keep a bounded, per-tab cache here instead of relying on browser
 * HTTP caching: the API intentionally keeps work datasets short-lived.
 */
type SessionEntry<T> = { value: T; expiresAt: number };
const sessionValues = new Map<string, SessionEntry<unknown>>();
const sessionInflight = new Map<string, Promise<unknown>>();
const SESSION_CACHE_LIMIT = 96;
const PUBLISHED_TTL_MS = 30 * 60 * 1000;
const WORK_TTL_MS = 8 * 1000;
const CATALOG_TTL_MS = 20 * 1000;

function remember<T>(key: string, value: T, ttlMs: number): T {
  sessionValues.delete(key); // Map order is our LRU order.
  sessionValues.set(key, { value, expiresAt: Date.now() + ttlMs });
  while (sessionValues.size > SESSION_CACHE_LIMIT) sessionValues.delete(sessionValues.keys().next().value!);
  return value;
}

function cacheTtl(value: unknown, fallback: number): number {
  const dataset = (value as { dataset?: DatasetSummary } | null)?.dataset;
  return dataset?.published ? PUBLISHED_TTL_MS : fallback;
}

function abortable<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'));
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(new DOMException('The operation was aborted.', 'AbortError'));
    signal.addEventListener('abort', abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}

function cachedJson<T>(key: string, url: string, ttlMs: number, signal?: AbortSignal): Promise<T> {
  const cached = sessionValues.get(key) as SessionEntry<T> | undefined;
  if (cached && cached.expiresAt > Date.now()) {
    // Refresh LRU position without extending freshness.  A busy work dataset
    // will still be revalidated promptly, while a published dataset stays fast.
    sessionValues.delete(key); sessionValues.set(key, cached);
    return abortable(Promise.resolve(cached.value), signal);
  }
  if (cached) sessionValues.delete(key);
  let request = sessionInflight.get(key) as Promise<T> | undefined;
  if (!request) {
    request = fetch(url).then(json<T>).then((value) => remember(key, value, cacheTtl(value, ttlMs)));
    sessionInflight.set(key, request);
    void request.finally(() => sessionInflight.delete(key));
  }
  return abortable(request, signal);
}

function selectedBrowse(payload: BrowseBootstrap, options: { viewpoint?: string; frame?: string }): BrowseBootstrap {
  const requestedFrame = options.frame ?? '';
  const requestedViewpoint = options.viewpoint ?? '';
  const viewpoints = payload.viewpoints ?? [];
  const view = viewpoints.find((item) => item.viewpoint_id === requestedViewpoint)
    ?? viewpoints.find((item) => item.frames.some((frame) => frame.frame_id === requestedFrame))
    ?? viewpoints.find((item) => item.viewpoint_id === payload.selected_viewpoint_id)
    ?? viewpoints[0];
  const frame = view?.frames.find((item) => item.frame_id === requestedFrame)
    ?? view?.frames.find((item) => item.frame_id === payload.selected_frame_id)
    ?? view?.frames[0];
  return { ...payload, selected_viewpoint_id: view?.viewpoint_id ?? null, selected_frame_id: frame?.frame_id ?? null };
}

/** Clear tab-local browse metadata after an explicit Refresh or publish. */
export function invalidateDatasetSessionCache(datasetId?: string): void {
  if (!datasetId) { sessionValues.clear(); return; }
  for (const key of [...sessionValues.keys()]) {
    if (key.includes(`:${datasetId}`)) sessionValues.delete(key);
  }
}

export const listDatasets = (refresh = false) => {
  if (refresh) invalidateDatasetSessionCache();
  return cachedJson<{ datasets: DatasetSummary[]; errors: unknown[] }>('catalog:datasets', `/api/datasets${refresh ? '?refresh=1' : ''}`, CATALOG_TTL_MS);
};
export const listScenes = (params: Record<string, string> = {}, refresh = false) => {
  const query = new URLSearchParams(params).toString();
  const key = `catalog:scenes:${query}`;
  if (refresh) sessionValues.delete(key);
  return cachedJson<SceneCatalog>(key, `/api/scenes?${query}`, CATALOG_TTL_MS);
};
export const getScene = (id: string) => fetch(`/api/scenes/${encodeURIComponent(id)}`).then(json<{ scene: DatasetSummary; statistics: Record<string, unknown> | null; browse_url: string }>);
export const getDataset = (id: string, signal?: AbortSignal) =>
  cachedJson<any>(`dataset:${id}`, `/api/datasets/${encodeURIComponent(id)}`, WORK_TTL_MS, signal);
export const getViewpoints = (id: string) =>
  cachedJson<{ viewpoints: Viewpoint[] }>(`viewpoints:${id}`, `/api/datasets/${encodeURIComponent(id)}/viewpoints`, WORK_TTL_MS);
export const getBrowse = (id: string, options: { viewpoint?: string; frame?: string } = {}, signal?: AbortSignal) => {
  // The complete topology is identical regardless of the requested initial
  // frame.  Resolve that small selection client-side so the cache key is the
  // dataset only, rather than one entry per heading/frame URL.
  return cachedJson<BrowseBootstrap>(`browse:${id}`, `/api/datasets/${encodeURIComponent(id)}/browse`, WORK_TTL_MS, signal)
    .then((payload) => selectedBrowse(payload, options));
};
export const getFrame = (id: string, frame: string, signal?: AbortSignal) =>
  cachedJson<FrameDetail>(`frame:${id}:${frame}`, `/api/datasets/${encodeURIComponent(id)}/frames/${encodeURIComponent(frame)}`, WORK_TTL_MS, signal);
export type PreviewPriority = 'interactive' | 'comparison' | 'prefetch';
export function previewUrl(id: string, frame: string, modality: string, controls: DisplayControls,
  profile: 'primary' | 'comparison' | 'hover' = 'primary', priority?: PreviewPriority): string {
  const q = new URLSearchParams({ ev: String(controls.ev), min: String(controls.minimum), max: String(controls.maximum) });
  if (profile === 'comparison') q.set('max_width', '384');
  if (profile === 'hover') q.set('max_width', '256');
  q.set('format', 'auto');
  q.set('priority', priority ?? (profile === 'primary' ? 'interactive' : profile === 'comparison' ? 'comparison' : 'prefetch'));
  if (controls.overlay) { q.set('overlay', controls.overlay); q.set('opacity', String(controls.overlayOpacity)); }
  return `/api/datasets/${encodeURIComponent(id)}/frames/${encodeURIComponent(frame)}/preview/${encodeURIComponent(modality)}?${q}`;
}
export const getOverview = (id: string) => cachedJson<SceneOverview>(`overview:${id}`, `/api/datasets/${encodeURIComponent(id)}/overview`, WORK_TTL_MS);
export const overviewTraversabilityUrl = (id: string) => `/api/datasets/${encodeURIComponent(id)}/overview/traversability`;
export const overviewMeshUrl = (id: string) => `/api/datasets/${encodeURIComponent(id)}/overview/mesh`;
export const getPixels = (id: string, frame: string, x: number, y: number, modalities: string[], signal?: AbortSignal) => {
  const q = new URLSearchParams({ x: String(x), y: String(y), modalities: modalities.join(',') });
  return fetch(`/api/datasets/${encodeURIComponent(id)}/frames/${encodeURIComponent(frame)}/pixels?${q}`, { signal }).then(json<PixelResponse>);
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
    phase?: string; phase_index?: number; phase_count?: number; local_completed?: number | null; local_total?: number | null; phase_percent?: number | null; object_count?: number | null; lighting_groups?: Record<string, unknown> }>;
  resource_class?: string | null; resource_state?: string; queue_position?: number | null; resource_gpu_indices?: number[];
  desired_gpu_indices?: number[]; draining_gpu_indices?: number[]; eligible_gpu_indices?: number[];
  hidden_from_ui?: boolean; hidden_reason?: string | null;
};
export type RecoveryPlan = { job_id: string; recommended_rerun_from: string | null; insertable_stages: string[]; can_resume: boolean;
  stages: { stage: string; state: 'Verified' | 'Missing' | 'Stale' | 'Failed' | 'Pending'; resource_class: string; selected: boolean }[] };
export type GPUOwner = { job_id: string; dataset_name?: string; stage: string; lease_state: 'assigned' | 'desired' | 'draining' };
export type GPU = { index: number; name: string; memory_used_mib: number; memory_total_mib: number; utilization_pct: number;
  eligible: boolean; reserved: boolean; owners?: GPUOwner[] };
export type ControllerStatus = { jobs: ControllerJob[]; queue: string[]; active_job_id?: string | null; gpu_inventory: GPU[];
  hidden_job_count?: number; include_hidden?: boolean;
  gpu_pool?: number[]; resource_config?: Record<string, any> };
export type ControllerRequest = {
  source_mode: 'generate' | 'existing' | 'augmentation' | 'nir_passive_backfill'; dataset_name: string; scene_id?: string; gpu_indices: number[];
  backfill_dataset?: string; prepared_scene_dir?: string; backfill_limit?: number; priority?: number;
  width: number; height: number; fov: number; rgb_spp: number; nir_spp: number;
  nir_passive?: boolean;
  flash_energy_scale: number; ambient_fill_energy_scale: number;
  illumination_diversity?: boolean; paired_fraction?: number; illumination_pairing_policy?: 'legacy_six_way_v1'|'reference_subset_v2';
  pose_budget: number;
  min_unique_pose_count?: number;
  camera_policy?: 'content_aware_v2' | 'coverage_v1'; content_profile?: 'balanced' | 'anchor_rich' | 'structural' | 'research_balanced'; ir_composition_profile?: 'inverse_rendering_showcase_v1';
  ir_material_profile?: 'standard' | 'principled_rich_v1'; material_mix_profile?: 'physically_constrained_metal_v1'; max_quality_variations?: number; max_showcase_composition_attempts?: number;
  adaptive_pose_budget?: boolean; sparse_negative_fraction?: number; max_headings_per_node?: number;
  graph_max_nodes: number; graph_heading_count: number; graph_min_node_spacing: number; graph_robot_radius: number;
  archetype?: string; room_type?: string; density?: string; generation_stage?: string; seed?: string; existing_output?: string;
  legacy_dataset_name?: string;
  variation_id?: number; anchor_richness?: 'minimal' | 'balanced' | 'rich' | 'storage'; surface_clutter?: 'low' | 'balanced' | 'rich' | 'storage';
  structural_rematerialize?: boolean; structural_pbr_registry?: string; structural_pbr_registry_root?: string;
  material_variant_id?: string; material_seed?: number; parent_scene_id?: string;
  hybrid_prop_pbr?: boolean; prop_pbr_target?: number; prop_pbr_seed?: number;
};
export const getControllerStatus = (signal?: AbortSignal, includeHidden = false) =>
  fetch(`/api/controller/status${includeHidden ? '?include_hidden=1' : ''}`, { signal }).then(json<ControllerStatus>);
export const listControllerJobs = (includeHidden = false) => fetch(`/api/controller/jobs${includeHidden ? '?include_hidden=1' : ''}`).then(json<{ jobs: ControllerJob[]; queue: string[]; active_job_id?: string | null; hidden_job_count?: number; include_hidden?: boolean }>);
export const getControllerLog = (id: string, signal?: AbortSignal) =>
  fetch(`/api/controller/jobs/${encodeURIComponent(id)}/log?tail=120`, { signal }).then(json<{ lines: string[] }>);
export const getRecoveryPlan = (id: string) => fetch(`/api/controller/jobs/${encodeURIComponent(id)}/recovery-plan`).then(json<RecoveryPlan>);
export const listInfinigenOutputs = (signal?: AbortSignal) =>
  fetch('/api/controller/infinigen-outputs', { signal }).then(json<{ outputs: { relative_path: string; scene_blend: string }[] }>);
export const submitControllerJob = (body: ControllerRequest) => fetch('/api/controller/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(json<ControllerJob>);
export const controllerJobAction = (id: string, action: 'cancel' | 'replan' | 'retry' | 'retry-showcase' | 'resume' | 'adopt' | 'priority' | 'hide' | 'unhide', body: Record<string, unknown> = {}) =>
  fetch(`/api/controller/jobs/${encodeURIComponent(id)}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(json<ControllerJob>);

export type DisplayControls = { ev: number; minimum: number; maximum: number; overlay: string; overlayOpacity: number };
