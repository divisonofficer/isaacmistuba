/**
 * Render scene sync, config, and batch management service.
 * Wraps API calls — no state management.
 * WebSocket-based sync uses a progress callback.
 */

import {
	getOpticalNavRenderReadiness,
	getOpticalNavRenderConfig,
	saveOpticalNavRenderConfig,
	getOpticalNavRenderSceneStats,
	getOpticalNavRoomShell,
	getOpticalNavMaterializationAudit,
	getOpticalNavXmlSceneIndex,
	syncOpticalNavRenderScene,
	opticalNavSyncProgressWsUrl,
	syncOpticalNavIsaacStage,
	getOpticalNavRenderBatch,
	getOpticalNavGraphRenderBatch,
	getOpticalNavGraphBatchLogs,
	sweepOpticalNavViewpointGraph,
	renderOpticalNavEpisodes,
} from '$lib/api';

export interface SyncProgress {
	processed: number;
	total: number;
	label: string;
	stage: string;
}

/**
 * Render-scene sync stage sequence + user-facing labels.
 *
 * Backend emits stage strings in this order — see render_daemon.py
 * `_run_render_scene_sync_inner`. Keep this in sync with backend stages.
 */
export const SYNC_STAGES = [
	'scene_sync',
	'mesh_extract',
	'stage_obj_cache',
	'preview_manifest',
	'readiness',
] as const;
export type SyncStage = (typeof SYNC_STAGES)[number] | string;

const SYNC_STAGE_LABELS_EN: Record<string, string> = {
	scene_sync: 'Preparing',
	mesh_extract: 'Extracting meshes',
	stage_obj_cache: 'Staging OBJs',
	preview_manifest: 'Building preview meshes',
	readiness: 'Verifying',
};
const SYNC_STAGE_LABELS_KR: Record<string, string> = {
	scene_sync: '장면 준비',
	mesh_extract: '메시 추출',
	stage_obj_cache: 'OBJ 캐싱',
	preview_manifest: '미리보기 메시',
	readiness: '검증',
};

export function syncStageLabel(stage: string | undefined, lang: 'kr' | 'en' = 'kr'): string {
	const key = String(stage ?? '');
	const map = lang === 'kr' ? SYNC_STAGE_LABELS_KR : SYNC_STAGE_LABELS_EN;
	return map[key] ?? key ?? '';
}

/** Index (0-based) of the current stage in SYNC_STAGES, or -1 if unknown. */
export function syncStageIndex(stage: string | undefined): number {
	const key = String(stage ?? '');
	const i = (SYNC_STAGES as readonly string[]).indexOf(key);
	return i;
}

/** Load render readiness status for a scene. */
export async function fetchRenderReadiness(projectId: string, sceneId: string) {
	return getOpticalNavRenderReadiness(projectId, sceneId);
}

/** Load render config (scene_state + camera_spec JSON) for a scene. */
export async function fetchRenderConfig(projectId: string, sceneId: string) {
	return getOpticalNavRenderConfig(projectId, sceneId);
}

/** Save a render config for a scene. */
export async function saveRenderConfig(
	projectId: string,
	sceneId: string,
	sceneState: unknown,
	cameraSpec: unknown
) {
	return saveOpticalNavRenderConfig(projectId, sceneId, { scene_state: sceneState, camera_spec: cameraSpec });
}

/** Load render scene XML statistics. */
export async function fetchRenderSceneStats(projectId: string, sceneId: string) {
	return getOpticalNavRenderSceneStats(projectId, sceneId);
}

/** Load room shell geometry for overlay visualization. */
export async function fetchRoomShell(projectId: string, sceneId: string) {
	return getOpticalNavRoomShell(projectId, sceneId);
}

/** Load materialization audit (mesh vs cube fallback stats). */
export async function fetchMaterializationAudit(projectId: string, sceneId: string) {
	return getOpticalNavMaterializationAudit(projectId, sceneId);
}

/** Load XML scene index for shape reference. */
export async function fetchXmlSceneIndex(projectId: string, sceneId: string) {
	return getOpticalNavXmlSceneIndex(projectId, sceneId);
}

/**
 * Sync the render scene with WebSocket progress updates.
 * Returns the final sync result on success.
 */
export async function syncRenderScene(
	projectId: string,
	sceneId: string,
	payload: Record<string, unknown>,
	onProgress: (p: SyncProgress) => void
) {
	const accepted = await syncOpticalNavRenderScene(projectId, sceneId, payload);
	const jobId = accepted?.sync_job_id as string | undefined;

	if (!jobId) {
		// Legacy synchronous response
		return accepted;
	}

	return new Promise<any>((resolve, reject) => {
		try {
			const ws = new WebSocket(opticalNavSyncProgressWsUrl(jobId));
			ws.onmessage = (ev) => {
				try {
					const msg = JSON.parse(ev.data);
					if (msg?.status === 'running' || msg?.status === 'started') {
						onProgress({
							processed: msg.processed ?? 0,
							total: msg.total ?? 0,
							label: msg.label ?? '',
							stage: msg.stage ?? '',
						});
					} else if (msg?.status === 'done' || msg?.status === 'error') {
						try { ws.close(); } catch {}
						if (msg.status === 'done') resolve(msg.result);
						else reject(new Error((msg.result as any)?.error || 'Sync failed'));
					}
				} catch {}
			};
			ws.onerror = () => reject(new Error('Sync progress WebSocket error'));
			ws.onclose = () => {};
		} catch (err) { reject(err as Error); }
	});
}

/** Sync the Isaac stage. */
export async function syncIsaacStage(
	projectId: string,
	sceneId: string,
	payload: Record<string, unknown> = {}
) {
	return syncOpticalNavIsaacStage(projectId, sceneId, payload);
}

/** Submit a sweep (sensor render) request for viewpoints. */
export async function sweepViewpointGraph(
	projectId: string,
	sceneId: string,
	body: Record<string, unknown>
) {
	return sweepOpticalNavViewpointGraph(projectId, sceneId, body);
}

/** Submit an episode render request. */
export async function renderEpisodes(projectId: string, body: Record<string, unknown>) {
	return renderOpticalNavEpisodes(projectId, body);
}

/** Fetch a graph render batch status. */
export async function fetchGraphBatch(projectId: string, batchId: string) {
	return getOpticalNavGraphRenderBatch(projectId, batchId);
}

/** Fetch an episode render batch status. */
export async function fetchRenderBatch(projectId: string, batchId: string) {
	return getOpticalNavRenderBatch(projectId, batchId);
}

/** Fetch batch log entries. */
export async function fetchBatchLogs(projectId: string, batchId: string, limit = 20) {
	return getOpticalNavGraphBatchLogs(projectId, batchId, limit);
}
