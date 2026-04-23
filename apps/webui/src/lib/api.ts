const json = (r: Response) => {
	if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
	return r.json();
};

const post = (url: string, body?: unknown) =>
	fetch(url, {
		method: 'POST',
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
export const smokeRender = (sceneId: string) =>
	post('/api/tests/smoke-render', { scene_id: sceneId });

export const listScenes = () => fetch('/api/scenes').then(json);
export const getScene = (id: string) => fetch(`/api/scenes/${id}`).then(json);
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
export const materialPreviewUrl = (bsdfType: string) =>
	`/api/material-preview/preset/${bsdfType}`;
export const measuredMaterialPreviewUrl = (datasetId: string, materialId: string) =>
	`/api/material-preview/measured/${datasetId}/${materialId}`;

export const submitRender = (payload: unknown) => post('/render', payload);

export const downloadDataset = (datasetId: string) =>
	post('/api/dataset-download', { dataset_id: datasetId });
export const getDatasetDownloadStatus = (jobId: string) =>
	fetch(`/api/dataset-download/status?job_id=${encodeURIComponent(jobId)}`).then(json);
