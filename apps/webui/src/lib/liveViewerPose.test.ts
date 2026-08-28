import { describe, expect, it } from 'vitest';

import { initialRasterPose, initialRasterPosition, prioritizeRasterShapes, queryFiniteNumber, rasterCameraMovement, rasterInputAxes, shouldRefreshRasterManifest } from './liveViewerPose';

describe('initialRasterPosition', () => {
	it('uses the current viewpoint graph position rather than falling back to the origin', () => {
		expect(initialRasterPosition({ nodes: [
			{ node_id: 'hazard', position: [18.7, 4.2, 0], tags: ['hazard_decision_point'] },
			{ node_id: 'interior', position: [3.38, 1.52, 0], tags: [] }
		]})).toEqual({ x: 3.38, z: 1.52 });
	});

	it('keeps compatibility with legacy world coordinates', () => {
		expect(initialRasterPosition({ nodes: [{ world: [5, -2] }] })).toEqual({ x: 5, z: -2 });
	});

	it('aims the default camera from the selected viewpoint toward the graph interior', () => {
		expect(initialRasterPose({ nodes: [
			{ position: [0, 0, 0], tags: [] },
			{ position: [10, 0, 0], tags: [] }
		]})).toEqual({ x: 0, z: 0, yawDeg: 90 });
	});

	it('keeps the caller fallback when a camera query parameter is omitted', () => {
		const params = new URLSearchParams();
		expect(queryFiniteNumber(params, 'x', 20.04)).toBe(20.04);
		expect(queryFiniteNumber(params, 'fov', 70)).toBe(70);
		expect(queryFiniteNumber(new URLSearchParams('x=0'), 'x', 20.04)).toBe(0);
	});

	it('loads nearby positioned meshes first and keeps equal-distance mesh order stable', () => {
		const shapes = [
			{ id: 'far', transform: { translate: [20, 0, 0] } },
			{ id: 'near-a', transform: { translate: [1, 0, 0] } },
			{ id: 'near-b', transform: { translate: [-1, 0, 0] } },
			{ id: 'unknown' },
		];
		expect(prioritizeRasterShapes(shapes, { x: 0, z: 0 }).map((shape) => shape.id))
			.toEqual(['near-a', 'near-b', 'far', 'unknown']);
	});

	it('does not restart a pending manifest load during revision polling', () => {
		expect(shouldRefreshRasterManifest(false, 'loading', 'rev-2', '')).toBe(false);
		expect(shouldRefreshRasterManifest(false, 'reloading', 'rev-2', 'rev-1')).toBe(false);
		expect(shouldRefreshRasterManifest(false, 'ready', 'rev-2', 'rev-1')).toBe(true);
		expect(shouldRefreshRasterManifest(true, 'loading', 'rev-1', '')).toBe(true);
	});

	it('moves W and D along the camera local forward and right axes', () => {
		expect(rasterCameraMovement(0, 1, 0)).toEqual({ x: 0, y: 0, z: -1 });
		expect(rasterCameraMovement(90, 1, 0).x).toBeCloseTo(-1);
		expect(rasterCameraMovement(90, 1, 0).z).toBeCloseTo(0);
		expect(rasterCameraMovement(90, 0, 1).x).toBeCloseTo(0);
		expect(rasterCameraMovement(90, 0, 1).z).toBeCloseTo(-1);
	});

	it('maps WASD to standard first-person forward and right axes', () => {
		expect(rasterInputAxes({ w: true, s: false, a: false, d: false })).toEqual({ forward: 1, right: 0 });
		expect(rasterInputAxes({ w: false, s: false, a: true, d: false })).toEqual({ forward: 0, right: -1 });
		expect(rasterInputAxes({ w: true, s: true, a: false, d: true })).toEqual({ forward: 0, right: 1 });
	});
});
