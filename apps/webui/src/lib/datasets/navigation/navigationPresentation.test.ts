import { describe, expect, it } from 'vitest';
import { filterBlueprints, hasSuccessfulSupportAnalysis, primaryNavigationAction } from './navigationPresentation';

describe('navigation inspector presentation', () => {
	it('orders the primary action by dependency', () => {
		expect(primaryNavigationAction({ hasMap: false, caps: { buildMap: { enabled: true } } }).id).toBe('build-grid');
		expect(primaryNavigationAction({ hasMap: true, caps: { buildGraph: { enabled: true } } }).id).toBe('build-place-graph');
		expect(primaryNavigationAction({ hasMap: true, navigationSupport: { route_blueprints: { blueprints: [{ status: 'approved' }] } } }).id).toBe('analyze-support');
		expect(primaryNavigationAction({
			hasMap: true,
			navigationSupport: { route_blueprints: { blueprints: [{ status: 'approved' }] } },
			supportAnalysis: { mode: 'analyze', summary: { support_pose_count: 32 } },
		}).id).toBe('build-support');
		expect(primaryNavigationAction({
			hasMap: false,
			navigationSupport: {
				place_graph: { nodes: [{ node_id: 'place_1' }] },
				route_blueprints: { blueprints: [{ status: 'approved' }] },
			},
		}).id).toBe('analyze-support');
	});

	it('does not unlock Build for an analysis that reports blocked routes', () => {
		const blocked = { mode: 'analyze', ok: false, analysis: { kind: 'support_corridor_unreachable' } };
		expect(hasSuccessfulSupportAnalysis(blocked)).toBe(false);
		expect(primaryNavigationAction({
			hasMap: true,
			navigationSupport: { route_blueprints: { blueprints: [{ status: 'approved' }] } },
			supportAnalysis: blocked,
		}).id).toBe('analyze-support');
	});

	it('filters blueprints without mutating the collection', () => {
		const blueprints = [{ blueprint_id: 'bp_1', status: 'approved', start_anchor_id: 'a', goal_anchor_id: 'b' }, { blueprint_id: 'bp_2', status: 'proposed', start_anchor_id: 'c', goal_anchor_id: 'd' }];
		expect(filterBlueprints(blueprints, 'bp_2', 'all')).toHaveLength(1);
		expect(filterBlueprints(blueprints, '', 'approved')).toEqual([blueprints[0]]);
	});
});
