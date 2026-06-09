/**
 * Asset catalog, material library, environment map, and camera rig service.
 * Wraps API calls — no state management.
 */

import {
	listOpticalNavUsdCandidates,
	getOpticalNavMapAssets,
	getOpticalNavEditorGeometry,
	listOpticalNavEnvmaps,
	uploadOpticalNavEnvmap,
	getCameraRig,
	materialLibrary,
} from '$lib/api';

export async function fetchUsdCandidates() {
	return listOpticalNavUsdCandidates();
}

export async function fetchMapAssets(projectId: string) {
	return getOpticalNavMapAssets(projectId);
}

export async function fetchEditorGeometry(
	projectId: string,
	sceneId: string,
	refreshExtraction = false
) {
	return getOpticalNavEditorGeometry(projectId, sceneId, refreshExtraction);
}

export async function fetchEnvmaps(projectId: string, sceneId: string) {
	return listOpticalNavEnvmaps(projectId, sceneId);
}

export interface UploadEnvmapParams {
	filename: string;
	contentType?: string;
	dataBase64: string;
}

export async function uploadEnvmap(
	projectId: string,
	sceneId: string,
	params: UploadEnvmapParams
) {
	return uploadOpticalNavEnvmap(projectId, sceneId, {
		filename: params.filename,
		content_type: params.contentType,
		data_base64: params.dataBase64,
	});
}

export async function fetchMaterialLibrary() {
	return materialLibrary();
}

export async function fetchCameraRig(rigId = 'ranger_mini_default') {
	return getCameraRig(rigId);
}
