import { describe, expect, it } from 'vitest';
import { batchScopeEstimate, defaultBatchScope, renderCampaignSummary } from './sensorPresentation';

describe('sensor rendering presentation', () => {
	it('defaults to Navigation Support only when a certified support plan exists', () => {
		expect(defaultBatchScope({ navigationSupportReady: true, hasGraph: true })).toBe('navigation_support');
		expect(defaultBatchScope({ navigationSupportReady: false, hasGraph: true })).toBe('full_graph');
	});

	it('keeps scene campaign counts separate from an individual active batch', () => {
		expect(renderCampaignSummary([
			{ total: 10, completed: 4, running: 2, queued: 3, failed: 1 },
			{ total: 5, completed: 5, running: 0, queued: 0, failed: 0 },
		])).toEqual({ total: 15, completed: 9, running: 2, queued: 3, failed: 1, percent: 67 });
	});

	it('labels graph cardinality as an estimate when coverage is not scope-exact', () => {
		const result = batchScopeEstimate({
			scope: 'full_graph',
			graphNodeCount: 20,
			headingsPerNode: 12,
			sensorCount: 2,
			variant: 'both',
			coverage: [{ sensor_id: 'rear_cam', total: 240, completed: 200 }],
			selectedSensorIds: ['rear_cam', 'polar_cam'],
		});
		expect(result).toMatchObject({ total: 960, label: 'views', exact: false, missing: null });
	});

	it('reports an exact missing count only for a matching immutable support ledger', () => {
		const result = batchScopeEstimate({
			scope: 'navigation_support',
			navigationSupportViews: 50,
			sensorCount: 1,
			variant: 'base',
			coverage: [{ sensor_id: 'rear_cam', coverage_source: 'render_plan', total: 50, completed: 31 }],
			selectedSensorIds: ['rear_cam'],
		});
		expect(result).toMatchObject({ total: 50, exact: true, completed: 31, missing: 19 });
	});

	it('preserves the existing polar sample and full phase cardinalities', () => {
		expect(batchScopeEstimate({ scope: 'polar_evaluation', polarMode: 'sample' }).total).toBe(20);
		expect(batchScopeEstimate({
			scope: 'polar_evaluation', polarMode: 'full', graphNodeCount: 20, headingsPerNode: 12,
	}).total).toBe(720);
	});
});
