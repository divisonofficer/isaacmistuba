/**
 * Scene-bundle export job service.
 * Wraps the daemon's POST/GET/DELETE export-jobs endpoints.
 */

import {
	submitOpticalNavExportJob,
	getOpticalNavExportJob,
	cancelOpticalNavExportJob,
	resumeOpticalNavExportJob,
} from '$lib/api';

export interface ExportJobSubmitPayload {
	scene_id: string;
	camera_ids?: string[] | null;
	only_completed?: boolean;
	episode_ids?: string[] | null;
	include_episode_thumbnails?: boolean;
	panorama_observations?: boolean;
	png_only?: boolean;
	include_birdseye?: boolean;
	include_episode_birdseye?: boolean;
	export_profile?: 'compact_with_polar_extension' | 'single_lossless_core' | 'navigation_only' | 'png_stokes_core' | 'legacy_full';
	eval_perturbation?: boolean;
	upload?: {
		enabled: boolean;
		target: 'google_drive';
		destination_subpath?: string;
	} | null;
}

export interface ExportCameraInventoryItem {
	sensor_id: string;
	modalities: string[];
	observation_count: number;
	base_count: number;
	perturbed_count: number;
}

export interface ExportJobStatus {
	job_id: string;
	project_id?: string;
	scene_id?: string;
	export_profile?: 'compact_with_polar_extension' | 'single_lossless_core' | 'navigation_only' | 'png_stokes_core' | 'legacy_full';
	status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted' | 'unknown';
	stage?: string;
	stage_label?: string;
	current?: number;
	total?: number;
	bytes_current?: number;
	bytes_total?: number;
	message?: string;
	current_file?: string | null;
	summary?: any;
	error?: string | null;
	cancel_requested?: boolean;
	resume_available?: boolean;
	remote_dir?: string;
	upload_rate?: string;
	upload_eta?: string;
	upload_transferred?: string;
	upload_total?: string;
	uploads?: Record<string, any>;
	created_at?: string;
	updated_at?: string;
}

export async function submitExportJob(projectId: string, payload: ExportJobSubmitPayload) {
	return submitOpticalNavExportJob(projectId, payload.scene_id, payload);
}

export async function fetchExportJob(projectId: string, sceneId: string, jobId: string): Promise<ExportJobStatus> {
	return getOpticalNavExportJob(projectId, sceneId, jobId) as Promise<ExportJobStatus>;
}

export async function cancelExportJob(projectId: string, sceneId: string, jobId: string) {
	return cancelOpticalNavExportJob(projectId, sceneId, jobId);
}

export async function resumeExportJob(projectId: string, sceneId: string, jobId: string) {
	return resumeOpticalNavExportJob(projectId, sceneId, jobId);
}
