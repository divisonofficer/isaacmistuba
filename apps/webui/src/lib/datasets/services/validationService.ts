/**
 * Dataset validation, evaluation, and export service.
 * Wraps API calls — no state management.
 */

import {
	validateOpticalNavDataset,
	evaluateOpticalNavDataset,
	exportOpticalNavDataset,
} from '$lib/api';

export interface ValidateParams {
	require_observations?: boolean;
	// Limit validation to specific scenes. Used by the UI's "Current scene only"
	// toggle so a partly-broken scene elsewhere in the project doesn't gate
	// export of the scene the user is actively working on.
	scene_ids?: string[] | null;
}

export interface EvaluateParams {
	policy?: string;
	success_radius?: number;
}

export interface ExportParams {
	zip?: boolean;
	// When true the backend keeps only episodes whose every timestep has a
	// resolvable observation_bundle_ref — i.e. the path nodes the user has
	// actually rendered. Default ON so a partial-sweep dataset doesn't ship
	// with broken observation references.
	only_completed?: boolean;
	// Explicit allow-list. When set, episode_ids overrides only_completed for
	// inclusion (still subject to file presence checks downstream).
	episode_ids?: string[] | null;
	// Scene scope — same semantics as on ValidateParams.
	scene_ids?: string[] | null;
}

export async function validateDataset(projectId: string, params: ValidateParams = {}) {
	return validateOpticalNavDataset(projectId, params);
}

export async function evaluateDataset(projectId: string, params: EvaluateParams = {}) {
	const defaults: EvaluateParams = { policy: 'shortest_oracle', success_radius: 0.5 };
	return evaluateOpticalNavDataset(projectId, { ...defaults, ...params });
}

export async function exportDataset(projectId: string, params: ExportParams = {}) {
	const defaults: ExportParams = { zip: true, only_completed: true };
	return exportOpticalNavDataset(projectId, { ...defaults, ...params });
}
