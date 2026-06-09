/**
 * Traversable grid and walkability overlay service.
 * Wraps API calls — no state management.
 */

import {
	buildOpticalNavMap,
	getOpticalNavTraversableGridMeta,
	getOpticalNavWalkabilityOverlay,
	paintOpticalNavWalkabilityOverlay,
	clearOpticalNavWalkabilityOverlay,
} from '$lib/api';

export async function buildTraversableMap(
	projectId: string,
	sceneId: string,
	resolution: number
) {
	return buildOpticalNavMap(projectId, sceneId, { resolution });
}

export async function fetchTraversableMeta(
	projectId: string,
	sceneId: string,
	robotRadiusM: number
) {
	return getOpticalNavTraversableGridMeta(projectId, sceneId, robotRadiusM);
}

export async function fetchWalkabilityOverlay(projectId: string, sceneId: string) {
	return getOpticalNavWalkabilityOverlay(projectId, sceneId);
}

export async function paintWalkability(
	projectId: string,
	sceneId: string,
	brush: 'walkable' | 'blocked' | 'erase',
	radiusM: number,
	points: Array<[number, number]>
) {
	return paintOpticalNavWalkabilityOverlay(projectId, sceneId, {
		brush,
		radius_m: radiusM,
		points,
		shape: 'stroke',
	});
}

export async function clearWalkabilityOverlay(projectId: string, sceneId: string) {
	return clearOpticalNavWalkabilityOverlay(projectId, sceneId);
}
