/**
 * Pure helper functions for the 2D map editor.
 * No state dependencies — all required context is passed as parameters.
 */

export type ClampAxis = 'x' | 'y' | 'yaw' | 'positive';

/** Clamp/normalise a raw numeric value to map bounds or angular range. */
export function clampMapNumber(
	value: unknown,
	axis: ClampAxis,
	mapWidth: number,
	mapHeight: number,
	fallback = 0
): number {
	const numeric = Number(value);
	if (!Number.isFinite(numeric)) return fallback;
	if (axis === 'x') return Number(Math.max(0, Math.min(mapWidth, numeric)).toFixed(3));
	if (axis === 'y') return Number(Math.max(0, Math.min(mapHeight, numeric)).toFixed(3));
	if (axis === 'yaw') return Number((((numeric % 360) + 360) % 360).toFixed(1));
	return Number(Math.max(0.001, numeric).toFixed(3));
}

/** Convert a PointerEvent on a canvas element to world-space coordinates. */
export function svgPoint(
	event: PointerEvent,
	mapWidth: number,
	mapHeight: number
): { x: number; y: number } {
	const target = event.currentTarget as Element | null;
	const rect = target?.getBoundingClientRect?.();
	if (!rect || rect.width <= 0 || rect.height <= 0) return { x: 0, y: 0 };
	const x = ((event.clientX - rect.left) / rect.width) * mapWidth;
	const y = ((event.clientY - rect.top) / rect.height) * mapHeight;
	return {
		x: clampMapNumber(x, 'x', mapWidth, mapHeight, 0),
		y: clampMapNumber(y, 'y', mapWidth, mapHeight, 0),
	};
}

/**
 * Snap a line endpoint to the nearest 45° direction from a fixed anchor.
 * When shiftKey is held or no anchor exists, returns the raw clamped point.
 */
export function snapLineEndpoint(
	rawPt: { x: number; y: number },
	fixedPt: [number, number] | null | undefined,
	shiftKey: boolean,
	mapWidth: number,
	mapHeight: number
): [number, number] {
	const x = clampMapNumber(rawPt.x, 'x', mapWidth, mapHeight);
	const y = clampMapNumber(rawPt.y, 'y', mapWidth, mapHeight);
	if (shiftKey || !fixedPt) return [x, y];
	const dx = x - fixedPt[0];
	const dy = y - fixedPt[1];
	const len = Math.sqrt(dx * dx + dy * dy);
	if (len < 0.01) return [x, y];
	const STEP = Math.PI / 4;
	const snapped = Math.round(Math.atan2(dy, dx) / STEP) * STEP;
	return [
		clampMapNumber(fixedPt[0] + len * Math.cos(snapped), 'x', mapWidth, mapHeight),
		clampMapNumber(fixedPt[1] + len * Math.sin(snapped), 'y', mapWidth, mapHeight),
	];
}

/**
 * Generate the next available ID for an authoring object of a given type.
 * IDs follow the pattern `<type>_001`, `<type>_002`, etc.
 */
export function nextAuthoringId(type: string, existingIds: string[]): string {
	const prefix = String(type || 'item').replace(/[^a-zA-Z0-9_]+/g, '_').toLowerCase();
	let maxId = 0;
	const re = new RegExp(`^${prefix}_(\\d+)$`);
	for (const id of existingIds) {
		const m = re.exec(id);
		if (m) maxId = Math.max(maxId, Number(m[1]) || 0);
	}
	return `${prefix}_${String(maxId + 1).padStart(3, '0')}`;
}

/** Get the world-space centre point of an authoring map item's geometry. */
export function getItemCenter(item: any): { x: number; y: number } | null {
	const geometry = item?.geometry;
	if (!geometry) return null;
	if (geometry.type === 'point' && geometry.center) {
		return { x: Number(geometry.center[0] ?? 0), y: Number(geometry.center[1] ?? 0) };
	}
	if (geometry.type === 'line' && geometry.start && geometry.end) {
		return {
			x: (Number(geometry.start[0] ?? 0) + Number(geometry.end[0] ?? 0)) / 2,
			y: (Number(geometry.start[1] ?? 0) + Number(geometry.end[1] ?? 0)) / 2,
		};
	}
	if (geometry.type === 'rectangle' && geometry.bounds) {
		return {
			x: (Number(geometry.bounds[0] ?? 0) + Number(geometry.bounds[2] ?? 0)) / 2,
			y: (Number(geometry.bounds[1] ?? 0) + Number(geometry.bounds[3] ?? 0)) / 2,
		};
	}
	return null;
}

/** Map an authoring region type to its CSS class name. */
export function rectangleStyle(type: string): string {
	if (type === 'goal') return 'region-goal';
	if (type === 'start') return 'region-start';
	if (type === 'stop_before') return 'region-stop';
	if (type === 'traversable') return 'region-traversable';
	if (type === 'hazard') return 'region-hazard';
	if (type === 'forbidden') return 'region-forbidden';
	return 'region-generic';
}

export interface VisibleLayers {
	objects: boolean;
	traversable: boolean;
	goals: boolean;
	hazards: boolean;
	graphNodes: boolean;
	graphEdges: boolean;
	usdBackground: boolean;
}

/** Whether a region of the given type should be rendered given current layer toggles. */
export function isRegionLayerVisible(type: string, layers: VisibleLayers): boolean {
	if (type === 'goal' || type === 'start' || type === 'stop_before') return layers.goals;
	if (type === 'traversable') return layers.traversable;
	if (type === 'hazard' || type === 'forbidden' || type === 'obstacle') return layers.hazards;
	return true;
}

/** Whether an object of the given type should be rendered given current layer toggles. */
export function isObjectLayerVisible(type: string, layers: VisibleLayers): boolean {
	if (type === 'wall') return layers.objects;
	if (
		type === 'glass_wall' ||
		type === 'mirror_wall' ||
		type === 'transparent_partition'
	) return layers.hazards && layers.objects;
	return layers.objects;
}
