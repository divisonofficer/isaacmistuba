/**
 * Pure sensor/camera-rig helper functions extracted from datasets/+page.svelte.
 */

import type { CameraRigSensor, CameraRigRenderSettings } from '$lib/api';

// ── Primitives ────────────────────────────────────────────────────────────────

export function positiveInt(value: unknown, fallback: number): number {
	const parsed = Number(value);
	return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : fallback;
}

// ── Modality mapping ──────────────────────────────────────────────────────────

export function cameraRigSensorTypeToLegacyModality(sensor: CameraRigSensor | any): string {
	const sensorType = String(sensor?.sensor_type ?? '').toLowerCase();
	if (sensorType === 'nir_camera') return 'nir';
	if (sensorType === 'polar_camera') return 'polarization';
	if (sensorType === 'lidar_3d') return 'lidar';
	const modalities = Array.isArray(sensor?.modalities)
		? sensor.modalities.map((m: unknown) => String(m).toLowerCase())
		: [];
	if (modalities.includes('nir_intensity') || modalities.includes('active_nir_intensity') || modalities.includes('nir'))
		return 'nir';
	if (modalities.includes('polarization') || modalities.includes('stokes')) return 'polarization';
	if (modalities.includes('lidar_point_cloud') || modalities.includes('lidar')) return 'lidar';
	return 'rgb';
}

export function sensorRenderModality(sensor: any): string {
	const modality = String(sensor?.modality ?? 'rgb').toLowerCase();
	if (modality === 'nir') return 'active_nir_intensity';
	if (modality === 'polarization') return 'polar_rgb_preview';
	if (modality === 'depth') return 'depth';
	if (modality === 'lidar') return 'lidar_like';
	return 'rgb';
}

/** Ordered polarization representations shown in the multi-channel hot-camera preview. */
export const POLAR_PREVIEW_MODALITIES: { id: string; label: string }[] = [
	{ id: 'polar_rgb_preview', label: 'RGB' },
	{ id: 's1_over_s0', label: 'S1/S0' },
	{ id: 's2_over_s0', label: 'S2/S0' },
	{ id: 'dop', label: 'DoLP' },
	{ id: 'aolp', label: 'AoLP' },
];

/** True when a render modality belongs to the polarization family (Stokes products). */
export function isPolarRenderModality(modality: unknown): boolean {
	return ['polar_rgb_preview', 's1', 's2', 's1_over_s0', 's2_over_s0', 'dop', 'aolp'].includes(
		String(modality ?? ''),
	);
}

export function sensorRenderChipLabel(option: any): string {
	const modality = String(option?.modality ?? '').toUpperCase();
	const renderModality = String(option?.render_modality ?? 'rgb');
	return modality && modality.toLowerCase() !== renderModality
		? `${modality} → ${renderModality}`
		: renderModality;
}

// ── Render settings normalization ─────────────────────────────────────────────

export function normalizeRigRenderSettings(
	render: CameraRigRenderSettings | any,
	sensorType = 'rgb_camera',
): CameraRigRenderSettings {
	const lidar = sensorType === 'lidar_3d';
	return {
		path_spp: positiveInt(render?.path_spp, lidar ? 1 : 4096),
		aov_spp: positiveInt(render?.aov_spp, lidar ? 1 : 16),
		polar_spp: positiveInt(render?.polar_spp, lidar ? 1 : 256),
		polar_visualization_policy:
			render?.polar_visualization_policy === 'raw_stokes_aolp_v1'
				? 'raw_stokes_aolp_v1'
				: render?.polar_visualization_policy === 'core_preview_v1'
					? 'core_preview_v1'
					: 'full_v1',
		samples_per_pass:
			render?.samples_per_pass == null || render?.samples_per_pass === ''
				? null
				: positiveInt(render.samples_per_pass, 1),
	};
}

// ── Mount helpers ─────────────────────────────────────────────────────────────

export function sensorMountHeight(sensor: any): number {
	const xyz = sensor?.mount?.xyz_m;
	if (!Array.isArray(xyz)) return 0;
	const heightIndex = sensor?.source_schema === 'camera_rig_v1' ? 2 : 1;
	return Number(xyz[heightIndex] ?? 0) || 0;
}

/** Convert sensor mount to sweep convention. Pass rigMountHeightM as fallback. */
export function robotMountForRender(sensor: any, mountHeightM = 1.0): any {
	const mount = sensor?.mount ?? {};
	const xyz = Array.isArray(mount.xyz_m) ? mount.xyz_m : [0, mountHeightM, 0];
	const rpy = Array.isArray(mount.rpy_deg) ? mount.rpy_deg : [0, 0, 0];
	if (sensor?.source_schema === 'camera_rig_v1') {
		return {
			...mount,
			xyz_m: [Number(xyz[0] ?? 0), Number(xyz[2] ?? mountHeightM), Number(xyz[1] ?? 0)],
			rpy_deg: [Number(rpy[0] ?? 0), Number(rpy[1] ?? 0), Number(rpy[2] ?? 0)],
			source_schema: 'camera_rig_v1',
		};
	}
	return {
		...mount,
		xyz_m: [Number(xyz[0] ?? 0), Number(xyz[1] ?? mountHeightM), Number(xyz[2] ?? 0)],
		rpy_deg: [Number(rpy[0] ?? 0), Number(rpy[1] ?? 0), Number(rpy[2] ?? 0)],
	};
}

/** Convert a camera_rig_v1 sensor to the legacy authoring-map sensor shape. */
export function legacySensorFromCameraRigSensor(
	sensor: CameraRigSensor,
	baseFrame = 'base_link',
): any {
	const modality = cameraRigSensorTypeToLegacyModality(sensor);
	const intrinsics = sensor.intrinsics ?? {};
	const mount = sensor.mount ?? { parent_frame: baseFrame, xyz_m: [0, 0, 1], rpy_deg: [0, 0, 0] };
	return {
		sensor_id: sensor.sensor_id,
		label: sensor.sensor_id,
		modality,
		enabled: sensor.enabled !== false,
		mount,
		resolution: intrinsics.resolution ?? [1280, 720],
		fov_deg: Number(intrinsics.fov_h_deg ?? 75),
		fov_v_deg: Number(intrinsics.fov_v_deg ?? 60),
		focal_length_px: Number(intrinsics.focal_length_px ?? 0),
		clip_range: [Number(intrinsics.clip_near_m ?? 0.05), Number(intrinsics.clip_far_m ?? 80)],
		sensor_sync_group: 'camera_rig',
		calibration_ref: null,
		active_emitter: sensor.nir,
		polarization: sensor.polarization,
		lidar: sensor.lidar,
		render: normalizeRigRenderSettings(sensor.render, sensor.sensor_type),
		source_schema: 'camera_rig_v1',
		canonical_sensor_type: sensor.sensor_type,
		modalities: sensor.modalities ?? [],
		intrinsics,
	};
}

// ── Observation heading helpers ───────────────────────────────────────────────

export function headingHasSensorModality(
	hdata: any,
	modality: string,
	sensorId: string | null = null,
): boolean {
	const key = `has_${modality}`;
	const sensors = hdata?.sensors;
	if (sensorId && sensors && typeof sensors === 'object') {
		return Boolean(sensors[sensorId]?.[key]);
	}
	return Boolean(hdata?.[key]);
}

// ── Display formatters ────────────────────────────────────────────────────────

export function formatRigVec(values: unknown, digits = 2): string {
	if (!Array.isArray(values)) return '-';
	return values.map((v) => Number(v ?? 0).toFixed(digits)).join(', ');
}

export function formatResolution(values: unknown): string {
	if (!Array.isArray(values) || values.length < 2) return '-';
	return `${Number(values[0] ?? 0)} × ${Number(values[1] ?? 0)}`;
}

export function formatRenderSpp(sensor: any): string {
	const render = normalizeRigRenderSettings(
		sensor?.render,
		String(sensor?.canonical_sensor_type ?? sensor?.sensor_type ?? 'rgb_camera'),
	);
	return `path ${render.path_spp} · aov ${render.aov_spp} · polar ${render.polar_spp}`;
}
