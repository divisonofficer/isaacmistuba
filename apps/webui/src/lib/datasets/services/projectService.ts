/**
 * Project and scene management service.
 * Wraps API calls — no state management.
 */

import {
	listOpticalNavProjects,
	getOpticalNavProject,
	createOpticalNavProject,
	addOpticalNavScene,
	attachOpticalNavSceneUsd,
} from '$lib/api';

export async function fetchProjects() {
	return listOpticalNavProjects();
}

export async function fetchProject(projectId: string) {
	return getOpticalNavProject(projectId);
}

export interface CreateProjectParams {
	name: string;
}

export async function createProject(params: CreateProjectParams) {
	return createOpticalNavProject({
		project_name: params.name,
		dataset_type: 'Synthetic fine-tuning dataset',
		target_scenario: 'glass / mirror / transparent partition navigation',
		robot_profile: 'mobile_base_front_camera',
	});
}

export interface AddSceneParams {
	sceneId: string;
	usdRef?: string;
}

export async function addScene(projectId: string, params: AddSceneParams) {
	return addOpticalNavScene(projectId, {
		scene_id: params.sceneId,
		usd_ref: params.usdRef,
	});
}

export async function attachUsdScene(
	projectId: string,
	sceneId: string,
	usdRef: string
) {
	return attachOpticalNavSceneUsd(projectId, sceneId, { usd_ref: usdRef });
}
