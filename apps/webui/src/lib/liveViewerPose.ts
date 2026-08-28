export type RasterStartPosition = { x: number; z: number };
export type RasterStartPose = RasterStartPosition & { yawDeg: number };
export type RasterShapeLocation = { transform?: Record<string, unknown> };
export type RasterLoadStatus = 'loading' | 'ready' | 'reloading' | 'error';

export function queryFiniteNumber(params: URLSearchParams, key: string, fallback: number): number {
	const raw = params.get(key);
	if (raw === null || raw.trim() === '') return fallback;
	const value = Number(raw);
	return Number.isFinite(value) ? value : fallback;
}

function coordinates(candidate: Record<string, unknown>, key: 'position' | 'world'): RasterStartPosition | null {
	const value = candidate[key];
	if (!Array.isArray(value) || value.length < 2) return null;
	const x = Number(value[0]);
	const z = Number(value[1]);
	return Number.isFinite(x) && Number.isFinite(z) ? { x, z } : null;
}

/** Pick a usable free-fly start from either current or legacy viewpoint graphs. */
export function initialRasterPosition(graph: unknown): RasterStartPosition | null {
	return rasterPositions(graph)[0] ?? null;
}

/** Pick a valid start and aim it toward the viewpoint graph's interior. */
export function initialRasterPose(graph: unknown): RasterStartPose | null {
	const positions = rasterPositions(graph);
	const start = positions[0];
	if (!start) return null;
	const center = positions.reduce(
		(total, point) => ({ x: total.x + point.x, z: total.z + point.z }),
		{ x: 0, z: 0 },
	);
	center.x /= positions.length;
	center.z /= positions.length;
	const yawDeg = Math.abs(center.x - start.x) < 1e-6 && Math.abs(center.z - start.z) < 1e-6
		? 0
		: Math.atan2(center.x - start.x, -(center.z - start.z)) * 180 / Math.PI;
	return { ...start, yawDeg };
}

/**
 * Make the first visible raster preview useful: fetch geometry nearest to the
 * camera before distant pieces of a large scene. Shapes without a usable
 * translation retain their manifest order after positioned shapes.
 */
export function prioritizeRasterShapes<T extends RasterShapeLocation>(
	shapes: readonly T[],
	position: RasterStartPosition,
): T[] {
	return shapes
		.map((shape, index) => ({ shape, index, distanceSquared: rasterShapeDistanceSquared(shape, position) }))
		.sort((left, right) => left.distanceSquared - right.distanceSquared || left.index - right.index)
		.map(({ shape }) => shape);
}

/** Avoid cancelling a long scene build every revision-poll interval. */
export function shouldRefreshRasterManifest(
	force: boolean,
	status: RasterLoadStatus,
	candidateRevision: string,
	currentRevision: string,
): boolean {
	return force || (status !== 'loading' && status !== 'reloading' && candidateRevision !== currentRevision);
}

/** Convert WASD input from camera-local axes into world-space movement. */
export function rasterCameraMovement(
	yawDeg: number,
	forward: number,
	right: number,
	vertical = 0,
): { x: number; y: number; z: number } {
	const yaw = yawDeg * Math.PI / 180;
	return {
		x: -Math.sin(yaw) * forward + Math.cos(yaw) * right,
		y: vertical,
		z: -Math.cos(yaw) * forward - Math.sin(yaw) * right,
	};
}

/** Standard first-person mapping: W/S are forward/back and A/D are left/right. */
export function rasterInputAxes(input: { w: boolean; s: boolean; a: boolean; d: boolean }): { forward: number; right: number } {
	return {
		forward: Number(input.w) - Number(input.s),
		right: Number(input.d) - Number(input.a),
	};
}

function rasterPositions(graph: unknown): RasterStartPosition[] {
	if (!graph || typeof graph !== 'object' || !Array.isArray((graph as { nodes?: unknown }).nodes)) return [];
	const nodes = (graph as { nodes: unknown[] }).nodes
		.filter((node): node is Record<string, unknown> => Boolean(node) && typeof node === 'object');
	const nonHazard = nodes.filter((node) => !Array.isArray(node.tags) || !node.tags.includes('hazard_decision_point'));
	const positions: RasterStartPosition[] = [];
	for (const node of (nonHazard.length ? nonHazard : nodes)) {
		const current = coordinates(node, 'position');
		if (current) { positions.push(current); continue; }
		const legacy = coordinates(node, 'world');
		if (legacy) positions.push(legacy);
	}
	return positions;
}

function rasterShapeDistanceSquared(shape: RasterShapeLocation, position: RasterStartPosition): number {
	const translate = shape.transform?.translate;
	if (!Array.isArray(translate) || translate.length < 3) return Number.POSITIVE_INFINITY;
	const x = Number(translate[0]);
	const z = Number(translate[2]);
	if (!Number.isFinite(x) || !Number.isFinite(z)) return Number.POSITIVE_INFINITY;
	return (x - position.x) ** 2 + (z - position.z) ** 2;
}
