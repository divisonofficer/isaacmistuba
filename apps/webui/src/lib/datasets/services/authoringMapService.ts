/**
 * Authoring map load, save, and compile service.
 * Wraps API calls — no state management.
 */

import {
	getOpticalNavAuthoringMap,
	saveOpticalNavAuthoringMap,
	compileOpticalNavAuthoringMap,
	getSceneAnnotation,
	saveSceneAnnotation,
} from '$lib/api';

export async function fetchAuthoringMap(projectId: string, sceneId: string) {
	return getOpticalNavAuthoringMap(projectId, sceneId);
}

export async function saveAuthoringMap(projectId: string, sceneId: string, payload: any) {
	return saveOpticalNavAuthoringMap(projectId, sceneId, payload);
}

export async function compileAuthoringMap(projectId: string, sceneId: string) {
	return compileOpticalNavAuthoringMap(projectId, sceneId);
}

export async function fetchAnnotation(projectId: string, sceneId: string) {
	return getSceneAnnotation(projectId, sceneId);
}

export async function saveAnnotation(
	projectId: string,
	sceneId: string,
	payload: unknown
) {
	return saveSceneAnnotation(projectId, sceneId, payload);
}
