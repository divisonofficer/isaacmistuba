/**
 * Pure authoring helper functions extracted from datasets/+page.svelte.
 * No Svelte state — all state deps are passed as parameters.
 */

import type { BuiltInPlaceAsset } from '$lib/opticalnavBuiltInAssets';

// ── Authoring map factories ──────────────────────────────────────────────────

export function makeStarterAuthoringMap(sceneId: string) {
	return {
		version: 'opticalnav-authoring-map-v0.2',
		scene_id: sceneId,
		unit: 'meter',
		floorplan_ref: `/api/scenes/${sceneId}/floorplan`,
		objects: [],
		regions: [],
		environment: {
			mode: 'constant',
			radiance: [0.8, 0.8, 0.85],
			intensity: 1.0,
			rotation_deg: 0,
			background_visible: true,
		},
		camera_rig: {
			rig_id: 'mobile_base_default',
			base_frame: 'base_link',
			sensors: [
				{ sensor_id: 'rgb_front', label: 'RGB Front', modality: 'rgb', mount: { xyz_m: [0.18, 1.0, 0.0], rpy_deg: [0, 0, 0] }, fov_deg: 70, resolution: [1280, 720], clip_range: [0.05, 80], sensor_sync_group: 'default', calibration_ref: null },
				{ sensor_id: 'nir_front', label: 'NIR Front', modality: 'nir', mount: { xyz_m: [0.16, 0.98, 0.04], rpy_deg: [0, 0, 0] }, fov_deg: 70, resolution: [1280, 720], clip_range: [0.05, 80], sensor_sync_group: 'default', calibration_ref: null, active_emitter: { wavelength_nm: 850, power: 1.0 } },
				{ sensor_id: 'pol_front', label: 'Polarization Front', modality: 'polarization', mount: { xyz_m: [0.16, 1.02, -0.04], rpy_deg: [0, 0, 0] }, fov_deg: 70, resolution: [1280, 720], clip_range: [0.05, 80], sensor_sync_group: 'default', calibration_ref: null },
			],
		},
		materials: [
			{ material_id: 'clear_glass', category: 'transparent', render_binding: { kind: 'preset', bsdf_strategy: 'dielectric', capabilities: { rgb: true, nir: true, polarization: true } } },
			{ material_id: 'mirror', category: 'reflective', render_binding: { kind: 'preset', bsdf_strategy: 'conductor', capabilities: { rgb: true, nir: true, polarization: true } } },
			{ material_id: 'painted_wall', category: 'opaque', render_binding: { kind: 'preset', bsdf_strategy: 'roughplastic', capabilities: { rgb: true, nir: true, polarization: false } } },
			{ material_id: 'wood', category: 'opaque', render_binding: { kind: 'preset', bsdf_strategy: 'roughplastic', capabilities: { rgb: true, nir: true, polarization: false } } },
		],
		settings: {
			grid_size_m: 0.25,
			default_wall_height_m: 2.4,
			default_wall_thickness_m: 0.08,
		},
		metadata: {
			source: 'webui_map_editor',
		},
	};
}

export function makeVisibleStarterAuthoringMap(sceneId: string) {
	const base = makeStarterAuthoringMap(sceneId);
	return {
		...base,
		objects: [
			{
				id: 'glass_wall_001',
				type: 'glass_wall',
				label: 'Glass wall',
				placement: 'line',
				geometry: {
					type: 'line',
					start: [2.25, 0.75],
					end: [2.25, 3.25],
					height_m: 2.4,
					thickness_m: 0.08,
				},
				material: 'clear_glass',
				navigation: {
					blocks_navigation: true,
					hazard_type: 'transparent_obstacle',
					include_in_hazard_mask: true,
					instruction_candidate: true,
					goal_candidate: false,
				},
				metadata: { created_by: 'webui_starter_overlay' },
			},
			{
				id: 'mirror_wall_001',
				type: 'mirror_wall',
				label: 'Mirror wall',
				placement: 'line',
				geometry: {
					type: 'line',
					start: [0.85, 3.35],
					end: [4.9, 3.35],
					height_m: 2.4,
					thickness_m: 0.08,
				},
				material: 'mirror',
				navigation: {
					blocks_navigation: true,
					hazard_type: 'reflective_obstacle',
					include_in_hazard_mask: true,
					instruction_candidate: true,
					goal_candidate: false,
				},
				metadata: { created_by: 'webui_starter_overlay' },
			},
		],
		regions: [
			{
				id: 'traversable_001',
				type: 'traversable',
				label: 'Main floor',
				placement: 'rectangle',
				geometry: { type: 'rectangle', bounds: [0.45, 0.45, 5.55, 3.55] },
				navigation: {
					blocks_navigation: false,
					hazard_type: null,
					include_in_hazard_mask: false,
					instruction_candidate: false,
					goal_candidate: false,
				},
				metadata: { created_by: 'webui_starter_overlay' },
			},
			{
				id: 'goal_001',
				type: 'goal',
				label: 'Goal near table',
				placement: 'rectangle',
				geometry: { type: 'rectangle', bounds: [4.45, 1.15, 5.2, 1.85] },
				navigation: {
					blocks_navigation: false,
					hazard_type: null,
					include_in_hazard_mask: false,
					instruction_candidate: true,
					goal_candidate: true,
				},
				metadata: { created_by: 'webui_starter_overlay' },
			},
		],
		metadata: {
			...base.metadata,
			starter_overlay: true,
		},
	};
}

// ── Geometry helpers ─────────────────────────────────────────────────────────

export function rectangleFromPoints(
	a: { x: number; y: number },
	b: { x: number; y: number },
): number[] {
	const minX = Math.min(a.x, b.x);
	const minY = Math.min(a.y, b.y);
	const maxX = Math.max(a.x, b.x);
	const maxY = Math.max(a.y, b.y);
	return [
		Number(minX.toFixed(3)),
		Number(minY.toFixed(3)),
		Number(maxX.toFixed(3)),
		Number(maxY.toFixed(3)),
	];
}

// ── USD asset display helpers ─────────────────────────────────────────────────

export function usdAssetLabel(asset: any): string {
	return (
		String(asset?.label || asset?.source_path || asset?.id || 'USD object')
			.split('/')
			.pop() ?? 'USD object'
	);
}

export function typeForUsdAsset(asset: any): string {
	const key =
		`${asset?.label ?? ''} ${asset?.source_path ?? ''} ${asset?.category ?? ''}`.toLowerCase();
	if (key.includes('chair') || key.includes('seat')) return 'chair';
	if (key.includes('table') || key.includes('desk')) return 'table';
	if (key.includes('cabinet') || key.includes('shelf') || key.includes('bookcase') || key.includes('bookshelf') || key.includes('sideboard')) return 'shelf';
	if (key.includes('plant') || key.includes('palm') || key.includes('succulent')) return 'plant';
	return 'landmark';
}

// ── Placement tool helpers ────────────────────────────────────────────────────

export function placementHintForTool(tool: string): string {
	if (tool === 'wall' || tool === 'glass_wall' || tool === 'mirror_wall') return 'line placement';
	if (['goal', 'start', 'hazard', 'forbidden', 'stop_before', 'traversable'].includes(tool))
		return 'drag region';
	return 'point placement';
}

export function builtInThumbType(asset: BuiltInPlaceAsset): string {
	if (asset.kind === 'primitive') return asset.tool;
	return `${asset.asset_id} ${asset.label} ${(asset.tags ?? []).join(' ')}`.toLowerCase();
}
