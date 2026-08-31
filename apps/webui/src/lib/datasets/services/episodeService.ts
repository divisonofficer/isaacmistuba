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
} from '$lib/api';

export interface PlanEpisodesParams {
	sceneId: string;
	numPairs: number;
	splits: Record<string, number>;
	instructionTypes: string[];
	modalities: string[];
	seed: number;
}

export interface PlanGraphEpisodesParams {
	sceneId: string;
	numPairs: number;
	splits: Record<string, number>;
	scenarios: string[];
	modalities: string[];
	seed: number;
}

export interface PlanAdaptiveRouteMotionEpisodesParams {
	sceneId: string;
	numPairs: number;
	splits: Record<string, number>;
	modalities: string[];
	seed: number;
	allowIncompleteCoverage?: boolean;
}

export interface PlanNavigationSupportEpisodesParams {
	sceneId: string;
	numPairs: number;
	splits: Record<string, number>;
	modalities: string[];
	seed: number;
	minForwardActions?: number;
	maxForwardActions?: number;
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
	});
}

export async function planGraphEpisodes(projectId: string, params: PlanGraphEpisodesParams) {
	return planOpticalNavGraphEpisodes(projectId, params.sceneId, {
		num_pairs: params.numPairs,
		splits: params.splits,
		scenarios: params.scenarios,
		modalities: params.modalities,
		seed: params.seed,
	});
}

export async function planAdaptiveRouteMotionEpisodes(projectId: string, params: PlanAdaptiveRouteMotionEpisodesParams) {
	return planOpticalNavAdaptiveRouteMotionEpisodes(projectId, params.sceneId, {
		num_pairs: params.numPairs,
		splits: params.splits,
		modalities: params.modalities,
		seed: params.seed,
		allow_incomplete_coverage: Boolean(params.allowIncompleteCoverage),
	});
}

/** Sample episodes only from a fully built, pre-renderable v4 support graph. */
export async function planNavigationSupportEpisodes(projectId: string, params: PlanNavigationSupportEpisodesParams) {
	return planOpticalNavNavigationSupportEpisodes(projectId, params.sceneId, {
		num_pairs: params.numPairs,
		splits: params.splits,
		modalities: params.modalities,
		seed: params.seed,
		min_forward_actions: params.minForwardActions ?? 4,
		max_forward_actions: params.maxForwardActions ?? 48,
	});
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
