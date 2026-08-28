import { describe, expect, it } from 'vitest';

import { liveViewerHost, MITSUBA_FROZEN_VIEWER } from './liveViewerProfiles';

describe('Mitsuba frozen viewer profile', () => {
	it('defaults to the unified live-viewer daemon', () => {
		expect(MITSUBA_FROZEN_VIEWER.port).toBe(8767);
		expect(liveViewerHost('', 'render.example')).toBe('render.example:8767');
	});

	it('preserves an explicit endpoint override', () => {
		expect(liveViewerHost('gpu-box:9000', 'render.example')).toBe('gpu-box:9000');
	});
});
