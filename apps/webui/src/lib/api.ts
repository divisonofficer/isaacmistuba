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
export const createOpticalNavProject = (payload: OpticalNavProjectCreate) =>
	post('/api/opticalnav/projects', payload);
export const getOpticalNavProject = (projectId: string) =>
	fetch(opticalProject(projectId)).then(json);
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
export const getOpticalNavEditorGeometry = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/editor-geometry`).then(json);
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
export const getOpticalNavViewpointGraph = (projectId: string, sceneId: string) =>
	fetch(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph`).then(json);
export const sweepOpticalNavViewpointGraph = (projectId: string, sceneId: string, payload: unknown) =>
	post(`${opticalProject(projectId)}/scenes/${encodeURIComponent(sceneId)}/graph/sweep`, payload);
export const getOpticalNavGraphRenderBatch = (projectId: string, batchId: string) =>
	fetch(`${opticalProject(projectId)}/graph-render-batches/${encodeURIComponent(batchId)}`).then(json);
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
export const validateOpticalNavDataset = (projectId: string, payload: { require_observations?: boolean }) =>
	post(`${opticalProject(projectId)}/validate`, payload);
export const evaluateOpticalNavDataset = (projectId: string, payload: { policy?: string; success_radius?: number }) =>
	post(`${opticalProject(projectId)}/evaluate`, payload);
export const exportOpticalNavDataset = (projectId: string, payload: { zip?: boolean }) =>
	post(`${opticalProject(projectId)}/export`, payload);
