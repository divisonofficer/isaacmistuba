/**
 * Episode planning, loading, and observation management service.
 * Wraps API calls — no state management.
 */

import {
	listOpticalNavEpisodes,
	getOpticalNavEpisode,
	planOpticalNavEpisodes,
	planOpticalNavGraphEpisodes,
	planOpticalNavAdaptiveRouteMotionEpisodes,
	planOpticalNavNavigationSupportEpisodes,
	validateOpticalNavGraphEpisodes,
	scanOpticalNavObservations,
	deleteOpticalNavObservations,
	graphBuildProgressWsUrl,
} from '$lib/api';

export type EpisodeWriteMode = "append" | "replace_scene";

export interface PlanEpisodesParams {
	sceneId: string;
	numPairs: number;
	splits: Record<string, number>;
	instructionTypes: string[];
	modalities: string[];
	seed: number;
	writeMode?: EpisodeWriteMode;
}

export interface PlanGraphEpisodesParams {
	sceneId: string;
	numPairs: number;
	splits: Record<string, number>;
	scenarios: string[];
	modalities: string[];
	seed: number;
	writeMode?: EpisodeWriteMode;
}

export interface PlanAdaptiveRouteMotionEpisodesParams {
	sceneId: string;
	numPairs: number;
	splits: Record<string, number>;
	modalities: string[];
	seed: number;
	writeMode?: EpisodeWriteMode;
	allowIncompleteCoverage?: boolean;
}

/** Which part of the executable graph episodes may use. See navigation_support.ROUTE_SCOPES. */
export type NavigationSupportRouteScope = 'blueprint' | 'blueprint_band' | 'global';

export interface PlanNavigationSupportEpisodesParams {
	sceneId: string;
	numPairs: number;
	splits: Record<string, number>;
	modalities: string[];
	seed: number;
	writeMode?: EpisodeWriteMode;
	minForwardActions?: number;
	maxForwardActions?: number;
	routeScope?: NavigationSupportRouteScope;
	/** Minimum/maximum actual travelled distance (sum of each move_forward transition's own distance_m), not an estimate from action count. */
	minDistanceM?: number;
	maxDistanceM?: number;
	/** Reject episodes walking more than this multiple of the free-space shortest path. */
	maxDetourRatio?: number;
}

export async function fetchEpisodes(projectId: string, sceneId: string, split?: string, cursor?: string) {
	return listOpticalNavEpisodes(projectId, sceneId, split, cursor);
}

export async function fetchEpisode(projectId: string, sceneId: string, episodeId: string) {
	return getOpticalNavEpisode(projectId, sceneId, episodeId);
}

export async function planEpisodes(projectId: string, params: PlanEpisodesParams) {
	return planOpticalNavEpisodes(projectId, params.sceneId, {
		num_pairs: params.numPairs,
		splits: params.splits,
		instruction_types: params.instructionTypes,
		modalities: params.modalities,
		seed: params.seed,
		write_mode: params.writeMode ?? "append",
	});
}

export async function planGraphEpisodes(projectId: string, params: PlanGraphEpisodesParams) {
	return planOpticalNavGraphEpisodes(projectId, params.sceneId, {
		num_pairs: params.numPairs,
		splits: params.splits,
		scenarios: params.scenarios,
		modalities: params.modalities,
		seed: params.seed,
		write_mode: params.writeMode ?? "append",
	});
}

export async function planAdaptiveRouteMotionEpisodes(projectId: string, params: PlanAdaptiveRouteMotionEpisodesParams) {
	return planOpticalNavAdaptiveRouteMotionEpisodes(projectId, params.sceneId, {
		num_pairs: params.numPairs,
		splits: params.splits,
		modalities: params.modalities,
		seed: params.seed,
		write_mode: params.writeMode ?? "append",
		allow_incomplete_coverage: Boolean(params.allowIncompleteCoverage),
	});
}

/** Sample episodes only from a fully built, pre-renderable v4 support graph.
 *
 * Sampling runs server-side and can take a while on a dense graph, so the
 * daemon streams each accepted episode over the shared build-progress socket;
 * `onProgress` receives those counts.
 */
export async function planNavigationSupportEpisodes(
	projectId: string,
	params: PlanNavigationSupportEpisodesParams,
	onProgress?: (planned: number, target: number) => void,
) {
	let ws: WebSocket | null = null;
	if (onProgress) {
		try {
			ws = new WebSocket(graphBuildProgressWsUrl(projectId, params.sceneId));
			ws.onmessage = (ev) => {
				try {
					const msg = JSON.parse(ev.data);
					if (msg?.stage === 'episodes' && msg?.detail) {
						onProgress(Number(msg.detail.planned ?? 0), Number(msg.detail.target ?? params.numPairs));
					}
				} catch {}
			};
			ws.onerror = () => {};
		} catch {}
	}
	try {
		return await planOpticalNavNavigationSupportEpisodes(projectId, params.sceneId, {
		num_pairs: params.numPairs,
		splits: params.splits,
		modalities: params.modalities,
		seed: params.seed,
		write_mode: params.writeMode ?? "append",
		min_forward_actions: params.minForwardActions ?? 4,
		max_forward_actions: params.maxForwardActions ?? 48,
		route_scope: params.routeScope ?? "blueprint",
		...(params.minDistanceM !== undefined ? { min_distance_m: params.minDistanceM } : {}),
		...(params.maxDistanceM !== undefined ? { max_distance_m: params.maxDistanceM } : {}),
		...(params.maxDetourRatio !== undefined ? { max_detour_ratio: params.maxDetourRatio } : {}),
		});
	} finally {
		if (ws) { try { ws.close(); } catch {} }
	}
}

export async function scanObservations(projectId: string, sceneId: string) {
	return scanOpticalNavObservations(projectId, sceneId);
}

export async function clearNodeObservations(projectId: string, sceneId: string, nodeId: string) {
	return deleteOpticalNavObservations(projectId, sceneId, [nodeId]);
}

export async function clearAllObservations(projectId: string, sceneId: string) {
	return deleteOpticalNavObservations(projectId, sceneId, null);
}

/**
 * Audit graph episodes for stale references (deleted nodes/edges or edges disabled by
 * the glass/mirror overlay). Pass `del=true` to prune the stale episode files.
 */
export async function validateGraphEpisodes(projectId: string, sceneId: string, del = false) {
	return validateOpticalNavGraphEpisodes(projectId, sceneId, { delete: del });
}
