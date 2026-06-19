export class ApiError extends Error {
	status: number;
	statusText: string;
	payload: unknown;

	constructor(response: Response, message: string, payload: unknown) {
		super(message);
		this.name = 'ApiError';
		this.status = response.status;
		this.statusText = response.statusText;
		this.payload = payload;
	}
}

const json = async (r: Response) => {
	if (!r.ok) {
		let detail = '';
		let payload: unknown = null;
		try {
			payload = await r.clone().json();
			const body = payload as Record<string, unknown>;
			detail = body?.error ? `: ${body.error}` : body?.message ? `: ${body.message}` : `: ${JSON.stringify(payload)}`;
		} catch {
			try {
				const text = await r.text();
				payload = text;
				detail = text ? `: ${text}` : '';
			} catch {
				detail = '';
			}
		}
		throw new ApiError(r, `${r.status} ${r.statusText}${detail}`, payload);
	}
	return r.json();
};

const post = (url: string, body?: unknown) =>
	fetch(url, {
		method: 'POST',
		headers: body ? { 'Content-Type': 'application/json' } : {},
		body: body ? JSON.stringify(body) : undefined
	}).then(json);

const put = (url: string, body?: unknown) =>
	fetch(url, {
		method: 'PUT',
		headers: body ? { 'Content-Type': 'application/json' } : {},
		body: body ? JSON.stringify(body) : undefined
	}).then(json);

export const health = () => fetch('/health').then(json);
export const summary = () => fetch('/api/summary').then(json);
export const debugEvents = (since: number) =>
	fetch(`/api/debug/events?since=${since}`).then(json);

export const listJobs = (limit = 100) =>
	fetch(`/api/render-jobs?limit=${limit}`).then(json);
export const getJob = (jobId: string) => fetch(`/jobs/${jobId}`).then(json);
export const getJobLog = (jobId: string, limit = 500) =>
	fetch(`/api/render-jobs/${jobId}/log?limit=${limit}`).then(json);
export const retryJob = (jobId: string) =>
	post(`/api/render-jobs/${jobId}/retry`);
export const cancelJob = (jobId: string) =>
	post(`/jobs/${jobId}/cancel`);
export const deleteJob = (jobId: string, opts: { force?: boolean } = {}) =>
	post(`/api/render-jobs/${encodeURIComponent(jobId)}/delete${opts.force ? '?force=1' : ''}`);
export const smokeRender = (sceneId: string) =>
	post('/api/tests/smoke-render', { scene_id: sceneId });

export const listScenes = () => fetch('/api/scenes').then(json);
export const getScene = (id: string) => fetch(`/api/scenes/${id}`).then(json);
export const getSceneDiagram3D = (id: string) =>
	fetch(`/api/scenes/${encodeURIComponent(id)}/diagram-3d`).then(json);

export type OccupancyMapOpts = {
	cell_size?: number;
	height_min?: number;
	height_max?: number;
	furniture?: boolean;
};
function _occupancyQuery(opts: OccupancyMapOpts): string {
	const p = new URLSearchParams();
	if (opts.cell_size != null) p.set('cell_size', String(opts.cell_size));
	if (opts.height_min != null) p.set('height_min', String(opts.height_min));
	if (opts.height_max != null) p.set('height_max', String(opts.height_max));
	if (opts.furniture != null) p.set('furniture', opts.furniture ? '1' : '0');
	return p.toString();
}
export const getOccupancyMap = (id: string, opts: OccupancyMapOpts = {}) => {
	const q = _occupancyQuery(opts);
	const url = `/api/scenes/${encodeURIComponent(id)}/occupancy-map${q ? `?${q}` : ''}`;
	return fetch(url).then(json);
};
export const occupancyMapPngUrl = (id: string, opts: OccupancyMapOpts = {}) => {
	const q = _occupancyQuery(opts);
	return `/api/scenes/${encodeURIComponent(id)}/occupancy-map.png${q ? `?${q}` : ''}`;
};
export const sceneGeometryUrl = (sceneId: string, meshId: string) =>
	`/api/scenes/${encodeURIComponent(sceneId)}/geometry/${encodeURIComponent(meshId)}.obj`;
export const getSceneCaptures = (id: string) =>
	fetch(`/api/scenes/${id}/captures`).then(json);
export const getSceneRenderOptions = (id: string) =>
	fetch(`/api/scenes/${id}/render-options`).then(json);
export const saveSceneRenderOptions = (id: string, opts: unknown) =>
	post(`/api/scenes/${id}/render-options`, opts);
export const applyMeasuredMaterial = (id: string, payload: unknown) =>
	post(`/api/scenes/${id}/apply-measured-material`, payload);

export const listIsaacScenes = () => fetch('/api/isaac/scenes').then(json);
export const getIsaacScene = (id: string) =>
	fetch(`/api/isaac/scenes/${id}`).then(json);
export const registerIsaacScene = (payload: unknown) =>
	post('/api/isaac/scenes/register', payload);
export const listIsaacCommands = () =>
	fetch('/api/isaac/commands').then(json);
export const isaacCommand = (commandType: string, sceneId?: string, payload: Record<string, unknown> = {}) =>
	post('/api/isaac/commands', { command_type: commandType, scene_id: sceneId, payload });
export const isaacTelemetryRecent = () =>
	fetch('/api/isaac/telemetry/recent').then(json);
export const isaacTelemetryStats = () =>
	fetch('/api/isaac/telemetry/stats').then(json);

export type CameraRigSensorType = 'rgb_camera' | 'nir_camera' | 'polar_camera' | 'lidar_3d';
export type CameraRigRenderSettings = {
	path_spp: number;
	aov_spp: number;
	polar_spp: number;
	samples_per_pass?: number | null;
};
export type CameraRigSensor = {
	sensor_id: string;
	sensor_type: CameraRigSensorType;
	modalities: string[];
	enabled: boolean;
	mount: {
		parent_frame: string;
		xyz_m: [number, number, number];
		rpy_deg: [number, number, number];
	};
	intrinsics: {
		resolution: [number, number];
		fov_h_deg: number;
		fov_v_deg: number;
		focal_length_px: number;
		clip_near_m: number;
		clip_far_m: number;
	};
	render?: CameraRigRenderSettings;
	nir?: {
		wavelength_min_nm: number;
		wavelength_max_nm: number;
		active_emitter_radiance: number;
	};
	polarization?: {
		polarizer_angle_deg: number;
	};
	lidar?: {
		horizontal_samples: number;
		vertical_channels: number;
		horizontal_fov_deg: number;
		vertical_fov_min_deg: number;
		vertical_fov_max_deg: number;
		min_range_m: number;
		max_range_m: number;
		wavelength_nm: number;
	};
};
export type CameraRig = {
	rig_id: string;
	label: string;
	robot_model: 'ranger_mini_v3' | string;
	base_frame: string;
	updated_at: string;
	sensors: CameraRigSensor[];
};
export type CameraRigMeshPayload = {
	robot_model: string;
	source: string;
	status: string;
	vertices: number[];
	indices: number[];
	bounds?: {
		min: number[];
		max: number[];
		size: number[];
		center: number[];
	};
};
export const listCameraRigs = (): Promise<{ default_rig_id: string; rigs: Array<Record<string, unknown>> }> =>
	fetch('/api/camera-rigs').then(json);
export const getCameraRig = (rigId: string): Promise<CameraRig> =>
	fetch(`/api/camera-rigs/${encodeURIComponent(rigId)}`).then(json);
export const saveCameraRig = (rigId: string, rig: CameraRig): Promise<CameraRig> =>
	post(`/api/camera-rigs/${encodeURIComponent(rigId)}`, rig);
export const getCameraRigRobotMesh = (): Promise<CameraRigMeshPayload> =>
	fetch('/api/camera-rigs/ranger-mini/mesh').then(json);
export const applyCameraRigToIsaac = (rigId: string, opts: { robot_prim_path?: string; replace_existing?: boolean } = {}) =>
	isaacCommand('apply_camera_rig', undefined, {
		rig_id: rigId,
		robot_prim_path: opts.robot_prim_path,
		replace_existing: opts.replace_existing ?? true
	});

export const getIsaacSession = () => fetch('/isaac/session').then(json);
export const getIsaacSessionInventory = () => fetch('/isaac/session/inventory').then(json);

export const materialPresets = () => fetch('/api/material-presets').then(json);
export const materialLibrary = () => fetch('/api/material-library').then(json);

// Pluggable preview geometry. Pass `{ object: 'french_bread' }` to render a
// mesh instead of the default sphere. Cached PNGs are keyed per-object so
// switching back and forth doesn't clobber the other object's cache.
type PreviewObjectOpts = { object?: string };
function _objectQuery(opts?: PreviewObjectOpts): string {
	return opts?.object ? `object=${encodeURIComponent(opts.object)}` : '';
}
export const materialPreviewUrl = (bsdfType: string, opts?: PreviewObjectOpts) => {
	const q = _objectQuery(opts);
	const base = `/api/material-preview/preset/${encodeURIComponent(bsdfType)}`;
	return q ? `${base}?${q}` : base;
};
export const measuredMaterialPreviewUrl = (
	datasetId: string,
	materialId: string,
	nativeFile?: string,
	opts?: PreviewObjectOpts
) => {
	const base = `/api/material-preview/measured/${encodeURIComponent(datasetId)}/${encodeURIComponent(materialId)}`;
	const params: string[] = [];
	if (nativeFile) params.push(`file=${encodeURIComponent(nativeFile)}`);
	const q = _objectQuery(opts);
	if (q) params.push(q);
	return params.length ? `${base}?${params.join('&')}` : base;
};
export const curatedMaterialPreviewUrl = (materialId: string, opts?: PreviewObjectOpts) => {
	const q = _objectQuery(opts);
	const base = `/api/material-preview/curated/${encodeURIComponent(materialId)}`;
	return q ? `${base}?${q}` : base;
};

export type PreviewObject = {
	object_id: string;
	label_en: string;
	label_kr: string;
	icon: string;
	is_default: boolean;
};
export type PreviewObjectsResponse = {
	objects: PreviewObject[];
	default: string;
};
export const listPreviewObjects = (): Promise<PreviewObjectsResponse> =>
	fetch('/api/preview-objects').then(json);
export const applyCuratedMaterial = (sceneId: string, payload: unknown) =>
	post(`/api/scenes/${sceneId}/apply-curated-material`, payload);

export type MaterialOverrideEntry = {
	prim_path: string;
	bsdf_type: string;
	measured_file_path?: string;
	dataset_id?: string;
	material_id?: string;
};
export const applyMaterialOverridesBatch = (
	sceneId: string,
	payload: { overrides: MaterialOverrideEntry[]; replace_mode?: 'merge' | 'replace_all' }
) =>
	post(
		`/api/scenes/${encodeURIComponent(sceneId)}/material-overrides/batch`,
		{ replace_mode: 'merge', ...payload }
	);

export const submitRender = (payload: unknown) => post('/render', payload);

export const prepareBasicScene = (sceneId: string) =>
	post(`/api/scenes/${encodeURIComponent(sceneId)}/prepare-basic`);

export const downloadDataset = (datasetId: string) =>
	post('/api/dataset-download', { dataset_id: datasetId });
export const downloadDatasetForce = (datasetId: string, materialIds?: string[]) =>
	post('/api/dataset-download', { dataset_id: datasetId, force: true, material_ids: materialIds });
export const getDatasetDownloadStatus = (jobId: string) =>
	fetch(`/api/dataset-download/status?job_id=${encodeURIComponent(jobId)}`).then(json);

export const getUserSettings = () =>
	fetch('/api/user-settings').then(json);
export const setUserSettings = (payload: {
	dataset_storage_overrides?: Record<string, string>;
	material_preview_spp?: number | null;
}) => post('/api/user-settings', payload);

export const invalidateCuratedPreview = (materialId: string) =>
	post(`/api/material-preview/curated/${encodeURIComponent(materialId)}/invalidate`);
export const invalidateMeasuredPreview = (datasetId: string, materialId: string) =>
	post(
		`/api/material-preview/measured/${encodeURIComponent(datasetId)}/${encodeURIComponent(materialId)}/invalidate`
	);
export type PreviewRef =
	| { type: 'curated'; material_id: string }
	| { type: 'measured'; dataset_id: string; material_id: string };
export const batchInvalidatePreviews = (items: PreviewRef[]) =>
	post('/api/material-previews/batch-invalidate', { items });

export const materialJobs = () => fetch('/api/material-jobs').then(json);
export const clearMaterialJobs = () => post('/api/material-jobs/clear-finished');

// hpBRDF channel-split modalities — per-material list of (composite, per-band,
// future Stokes) PNGs. Returned by the daemon's /modalities endpoint and
// driven by the per-material `manifest.json` written by the renderer.
export type ModalityKind = 'composite' | 'band' | 'stokes';
export type ModalityGroup = 'composite' | 'spectral' | 'polar';
export type Modality = {
	kind: ModalityKind;
	label: string;
	group: ModalityGroup;
	url: string;
	wavelength_nm?: number;
	is_nir?: boolean;
};
export type ModalityListResponse = {
	material_id: string;
	default_url: string;
	modalities: Modality[];
};

export const measuredModalities = (
	datasetId: string,
	materialId: string,
	size = 192,
): Promise<ModalityListResponse> =>
	fetch(
		`/api/material-preview/measured/${encodeURIComponent(datasetId)}/${encodeURIComponent(materialId)}/modalities?size=${size}`,
	).then(json);

export type OpticalNavProjectCreate = {
	project_name: string;
	dataset_type?: string;
	target_scenario?: string;
	robot_profile?: string;
	modalities?: string[];
};
export type OpticalNavSceneCreate = {
	scene_id: string;
	usd_ref?: string;
};

const opticalProject = (projectId: string) =>
	`/api/opticalnav/projects/${encodeURIComponent(projectId)}`;

export const listOpticalNavProjects = () =>
	fetch('/api/opticalnav/projects').then(json);
export const listOpticalNavUsdCandidates = () =>
	fetch('/api/opticalnav/usd-candidates').then(json);
export const listOpticalNavAssetSources = () =>
	fetch('/api/opticalnav/asset-library/sources').then(json);
export const importOpticalNavAssetSource = (payload: { usd_ref?: string; source_ref?: string; glb_ref?: string; force?: boolean }) =>
	post('/api/opticalnav/asset-library/import', payload);
export const listOpticalNavAssets = (opts: { q?: string; category?: string; selected?: boolean; source_ref?: string; source_type?: string } = {}) => {
	const params = new URLSearchParams();
	if (opts.q) params.set('q', opts.q);
	if (opts.category && opts.category !== 'all') params.set('category', opts.category);
	if (opts.selected) params.set('selected', '1');
	if (opts.source_ref) params.set('source_ref', opts.source_ref);
	if (opts.source_type && opts.source_type !== 'all') params.set('source_type', opts.source_type);
	const query = params.toString();
	return fetch(`/api/opticalnav/asset-library/assets${query ? `?${query}` : ''}`).then(json);
};
export const listOpticalNavAgentAssets = (opts: { q?: string; category?: string; active?: boolean; include_unready?: boolean } = {}) => {
	const params = new URLSearchParams();
	if (opts.q) params.set('q', opts.q);
	if (opts.category && opts.category !== 'all') params.set('category', opts.category);
	if (opts.active != null) params.set('active', opts.active ? '1' : '0');
	if (opts.include_unready) params.set('include_unready', '1');
	const query = params.toString();
	return fetch(`/api/opticalnav/agent/assets${query ? `?${query}` : ''}`).then(json);
};
export const setOpticalNavAgentAssetActivation = (payload: {
	activate?: string[];
	deactivate?: string[];
	replace?: boolean;
	decisions?: Array<{ asset_id: string; active: boolean; reason?: string }>;
}) => post('/api/opticalnav/agent/assets/activation', payload);
export const updateOpticalNavAsset = (assetId: string, payload: unknown) =>
	put(`/api/opticalnav/asset-library/assets/${encodeURIComponent(assetId)}`, payload);
export const bulkSelectOpticalNavAssets = (payload: { asset_ids: string[]; selected: boolean }) =>
	post('/api/opticalnav/asset-library/assets/bulk-select', payload);
export const createOpticalNavProject = (payload: OpticalNavProjectCreate) =>
	post('/api/opticalnav/projects', payload);
export const getOpticalNavProject = (projectId: string) =>
	fetch(opticalProject(projectId)).then(json);
export const getOpticalNavMapAssets = (projectId: string) =>
	fetch(`${opticalProject(projectId)}/map-assets`).then(json);
export const opticalNavAssetThumbnailUrl = (projectId: string, assetId: string) =>
	`${opticalProject(projectId)}/map-assets/${encodeURIComponent(assetId)}/thumbnail?v=mesh_thumb_v4`;
export const addOpticalNavScene = (projectId: string, payload: OpticalNavSceneCreate) =>
	post(`${opticalProject(projectId)}/scenes`, payload);
export const attachOpticalNavSceneUsd = (projectId: string, sceneId: string, payload: { usd_ref?: string }) =>
	put(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/usd-ref`, payload);
export const getSceneAnnotation = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/annotation`).then(json);
export const saveSceneAnnotation = (projectId: string, sceneId: string, payload: unknown) =>
	put(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/annotation`, payload);
export const getOpticalNavAuthoringMap = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/authoring-map`).then(json);
export const getOpticalNavEditorGeometry = (projectId: string, sceneId: string, refresh = false) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/editor-geometry${refresh ? '?refresh=1' : ''}`).then(json);
export const getOpticalNavPrimMesh = (projectId: string, sceneId: string, sourcePath: string, usdRef?: string) => {
	const params = new URLSearchParams({ source_path: sourcePath });
	const lowerSource = sourcePath.toLowerCase();
	if (lowerSource.endsWith('.glb') || lowerSource.endsWith('.gltf')) params.set('source_ref', sourcePath);
	if (usdRef) params.set('usd_ref', usdRef);
	return fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/prim-mesh?${params}`).then(json);
};
export const saveOpticalNavAuthoringMap = (projectId: string, sceneId: string, payload: unknown) =>
	put(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/authoring-map`, payload);
export const compileOpticalNavAuthoringMap = (projectId: string, sceneId: string) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/authoring-map/compile`);
export const syncOpticalNavRenderScene = (projectId: string, sceneId: string, payload: unknown = {}) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/sync/render-scene`, payload);
export const syncOpticalNavIsaacStage = (projectId: string, sceneId: string, payload: unknown = {}) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/sync/isaac-stage`, payload);
export const buildOpticalNavMap = (projectId: string, sceneId: string, payload: { resolution: number }) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/map/build`, payload);
export const buildOpticalNavViewpointGraph = (projectId: string, sceneId: string, payload: unknown) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/build`, payload);
export const rebuildOpticalNavGraphEdges = (projectId: string, sceneId: string, payload: unknown = {}) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/rebuild-edges`, payload);
export const graphBuildProgressWsUrl = (projectId: string, sceneId: string): string => {
	const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss:' : 'ws:';
	const host = typeof location !== 'undefined' ? location.host : '127.0.0.1:8765';
	return `${proto}//${host}/api/ws/graph-build-progress?project_id=${encodeURIComponent(projectId)}&scene_id=${encodeURIComponent(sceneId)}`;
};
export const opticalNavSyncProgressWsUrl = (syncJobId: string): string => {
	const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss:' : 'ws:';
	const host = typeof location !== 'undefined' ? location.host : '127.0.0.1:8765';
	return `${proto}//${host}/api/ws/opticalnav-sync-progress?sync_job_id=${encodeURIComponent(syncJobId)}`;
};
export const getOpticalNavViewpointGraph = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph`).then(json);
export const sweepOpticalNavViewpointGraph = (projectId: string, sceneId: string, payload: unknown) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/sweep`, payload);
export const deleteOpticalNavObservations = (projectId: string, sceneId: string, nodeIds: string[] | null) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/observations`, {
		method: 'DELETE',
		headers: nodeIds ? { 'Content-Type': 'application/json' } : {},
		body: nodeIds ? JSON.stringify({ node_ids: nodeIds }) : undefined
	}).then(json);
export const getOpticalNavRenderConfig = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/render-config`).then(json);
export const getOpticalNavRenderReadiness = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/render-readiness`).then(json);
export const listOpticalNavEnvmaps = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/envmaps`).then(json);
export const uploadOpticalNavEnvmap = (projectId: string, sceneId: string, payload: { filename: string; content_type?: string; data_base64: string }) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/envmaps`, payload);
export const saveOpticalNavRenderConfig = (projectId: string, sceneId: string, payload: { scene_state: unknown; camera_spec: unknown }) =>
	put(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/render-config`, payload);
export const getOpticalNavGraphRenderBatch = (projectId: string, batchId: string) =>
	fetch(`${opticalProject(projectId)}/graph-render-batches/${encodeURIComponent(batchId)}`).then(json);
export const getOpticalNavGraphBatchLogs = (projectId: string, batchId: string, perJob = 30) =>
	fetch(`${opticalProject(projectId)}/graph-render-batches/${encodeURIComponent(batchId)}/logs?per_job=${perJob}`).then(json);
export const planOpticalNavEpisodes = (projectId: string, payload: unknown) =>
	post(`${opticalProject(projectId)}/episodes/plan`, payload);
export const planOpticalNavGraphEpisodes = (projectId: string, payload: unknown) =>
	post(`${opticalProject(projectId)}/graph/episodes/plan`, payload);
export const listOpticalNavEpisodes = (projectId: string, split?: string) =>
	fetch(`${opticalProject(projectId)}/episodes${split ? `?split=${encodeURIComponent(split)}` : ''}`).then(json);
export const getOpticalNavEpisode = (projectId: string, episodeId: string) =>
	fetch(`${opticalProject(projectId)}/episodes/${encodeURIComponent(episodeId)}`).then(json);
export const renderOpticalNavEpisodes = (projectId: string, payload: unknown) =>
	post(`${opticalProject(projectId)}/episodes/render`, payload);
export const getOpticalNavRenderBatch = (projectId: string, batchId: string) =>
	fetch(`${opticalProject(projectId)}/render-batches/${encodeURIComponent(batchId)}`).then(json);
export const scanOpticalNavObservations = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/observations-scan`).then(json);
export const getOpticalNavRenderSceneStats = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/render-scene-stats`).then(json);
// PR1: render geometry audit + XML scene index sidecars produced by Sync Render Scene.
export const getOpticalNavMaterializationAudit = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/render-scene-materialization`).then(json);
export const getOpticalNavXmlSceneIndex = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/xml-scene-index`).then(json);
// PR2: serve raw OBJ bytes from mesh_cache for the XML-native editor preview.
// xml_scene_index.shapes[].mesh_path stores absolute paths after PR1's
// _absolutize_filename_refs(); the editor reduces them to a basename and hits
// this endpoint so the browser-side OBJLoader can parse the geometry.
export const opticalNavMeshCacheUrl = (projectId: string, sceneId: string, filename: string): string =>
	`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/mesh-cache/${encodeURIComponent(filename)}`;
export const getOpticalNavRoomShell = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/room-shell`).then(json);
export const addOpticalNavGraphNode = (projectId: string, sceneId: string, payload: { x: number; y: number; heading_count?: number }) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/nodes`, payload);
export const deleteOpticalNavGraphNode = (projectId: string, sceneId: string, nodeId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/nodes/${encodeURIComponent(nodeId)}`, { method: 'DELETE' }).then(json);
export const deleteOpticalNavGraphNodes = (projectId: string, sceneId: string, nodeIds: string[]) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/nodes`, {
		method: 'DELETE',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ node_ids: nodeIds })
	}).then(json);
export const fetchOpticalNavOverlappingGraphNodes = (
	projectId: string,
	sceneId: string,
	opts?: { marginM?: number; includeWalls?: boolean; robotHeightM?: number }
) => {
	const q = new URLSearchParams();
	if (opts?.marginM != null) q.set('margin_m', String(opts.marginM));
	if (opts?.includeWalls) q.set('include_walls', '1');
	if (opts?.robotHeightM != null) q.set('robot_height_m', String(opts.robotHeightM));
	const qs = q.toString();
	return fetch(
		`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/overlapping-nodes${qs ? `?${qs}` : ''}`
	).then(json);
};
export const getOpticalNavWalkabilityOverlay = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/walkability-overlay`).then(json);
export const paintOpticalNavWalkabilityOverlay = (
	projectId: string, sceneId: string,
	payload: { brush: 'walkable' | 'blocked' | 'erase'; radius_m?: number; points?: Array<[number, number]>; shape?: 'stroke' | 'rectangle'; bbox?: [number, number, number, number] }
) => post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/walkability-overlay/paint`, payload);
export const clearOpticalNavWalkabilityOverlay = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/walkability-overlay`, { method: 'DELETE' }).then(json);
export const opticalNavWalkabilityOverlayPngUrl = (projectId: string, sceneId: string): string =>
	`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/walkability-overlay.png`;
export const getOpticalNavTraversableGridMeta = (projectId: string, sceneId: string, robotRadiusM: number) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/traversable-grid?robot_radius_m=${robotRadiusM}`).then(json);
export const opticalNavTraversableGridPngUrl = (projectId: string, sceneId: string, robotRadiusM: number): string =>
	`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/traversable-grid.png?robot_radius_m=${robotRadiusM}`;
export const opticalNavEnvmapPreviewUrl = (projectId: string, sceneId: string, filename: string): string =>
	`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/envmaps/${encodeURIComponent(filename)}`;
export const checkOpticalNavGraphEdge = (projectId: string, sceneId: string, payload: { source: string; target: string; robot_radius_m?: number; max_edge_length_m?: number }) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/edge-check`, payload);
export const regenerateOpticalNavGraphRegion = (
	projectId: string, sceneId: string,
	payload: { bbox: [number, number, number, number]; max_nodes?: number; min_node_spacing_m?: number; robot_radius_m?: number; min_clearance_m?: number; heading_count?: number; seed?: number }
) => post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/regenerate-region`, payload);
export const addOpticalNavGraphEdge = (
	projectId: string, sceneId: string,
	payload: { source: string; target: string; distance_m?: number; weight?: number }
) => post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/edges`, payload);
export const deleteOpticalNavGraphEdge = (projectId: string, sceneId: string, edgeId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/edges/${encodeURIComponent(edgeId)}`, { method: 'DELETE' }).then(json);
export const opticalNavObservationRgbUrl = (projectId: string, sceneId: string, vpId: string, headingId: string): string =>
	`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/observations/${encodeURIComponent(vpId)}/rgb?heading=${encodeURIComponent(headingId)}`;
export const opticalNavObservationModalityUrl = (projectId: string, sceneId: string, vpId: string, headingId: string, modality: string, sensorId = ''): string =>
	`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/observations/${encodeURIComponent(vpId)}/${encodeURIComponent(modality)}?heading=${encodeURIComponent(headingId)}${sensorId ? `&sensor_id=${encodeURIComponent(sensorId)}` : ''}`;
export const validateOpticalNavDataset = (
	projectId: string,
	payload: { require_observations?: boolean; scene_ids?: string[] | null },
) =>
	post(`${opticalProject(projectId)}/validate`, payload);
export const evaluateOpticalNavDataset = (projectId: string, payload: { policy?: string; success_radius?: number }) =>
	post(`${opticalProject(projectId)}/evaluate`, payload);
export const exportOpticalNavDataset = (
	projectId: string,
	payload: {
		zip?: boolean;
		episode_ids?: string[] | null;
		only_completed?: boolean;
		scene_ids?: string[] | null;
	},
) =>
	post(`${opticalProject(projectId)}/export`, payload);

// Scene-bundle export jobs — async with WS / polling progress.
export const submitOpticalNavExportJob = (
	projectId: string,
	payload: {
		scene_id: string;
		only_completed?: boolean;
		episode_ids?: string[] | null;
		include_episode_thumbnails?: boolean;
		panorama_observations?: boolean;
		png_only?: boolean;
		include_birdseye?: boolean;
	},
) => post(`${opticalProject(projectId)}/export-jobs`, payload);

export const getOpticalNavExportJob = (projectId: string, jobId: string) =>
	fetch(`${opticalProject(projectId)}/export-jobs/${encodeURIComponent(jobId)}`).then(json);

export const cancelOpticalNavExportJob = (projectId: string, jobId: string) =>
	fetch(`${opticalProject(projectId)}/export-jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' }).then(json);
