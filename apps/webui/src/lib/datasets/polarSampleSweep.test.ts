import { describe, expect, it } from 'vitest';
import { polarFullSweepPayloads, polarSampleSweepPayloads, polarSampleSweepReady } from './polarSampleSweep';

const plan = {
	submission_group_id: 'polar-sample-test',
	selection_manifest_ref: 'graph_render_batches/polar-sample-test.polar-sample-selection.json',
	view_keys: Array.from({ length: 10 }, (_, index) => ({ node_id: `vp_${index}`, heading_id: 'h_000' })),
};

describe('polar sample sweep', () => {
	it('requires the graph, render scene, prepared perturbation, and polar camera', () => {
		const ready = { projectId: 'project', hasGraph: true, renderSceneSynced: true, perturbedRenderReady: true, hasPolarCamera: true, inFlight: false };
		expect(polarSampleSweepReady(ready)).toBe(true);
		expect(polarSampleSweepReady({ ...ready, inFlight: true })).toBe(false);
		expect(polarSampleSweepReady({ ...ready, hasPolarCamera: false })).toBe(false);
	});

	it('builds passive then dependent active-polar payloads for exactly ten unique views', () => {
		const [passive, active] = polarSampleSweepPayloads(plan, 'passive-batch');
		expect(passive.scene_variant_key).toBe('perturbed');
		expect(active.scene_variant_key).toBe('perturbed_active_polar');
		expect(active.previous_variant_batch_id).toBe('passive-batch');
		for (const payload of [passive, active]) {
			expect(payload.sensor_ids).toEqual(['polar_cam']);
			expect(payload.variant).toBe('cuda_ad_rgb_polarized');
			expect(payload.render_settings).toEqual({ polar_color_mode: 'rgb_stokes_12' });
			expect(payload.view_keys).toHaveLength(10);
		}
	});

	it('builds the full base → passive → active-polar contract for all graph views', () => {
		const payloads = polarFullSweepPayloads('polar-full-test');
		expect(payloads.map((payload) => payload.scene_variant_key)).toEqual(['base', 'perturbed', 'perturbed_active_polar']);
		for (const payload of payloads) {
			expect(payload.sensor_ids).toEqual(['polar_cam']);
			expect(payload.variant).toBe('cuda_ad_rgb_polarized');
			expect(payload.render_settings).toEqual({ polar_color_mode: 'rgb_stokes_12' });
			expect(payload.submission_group_id).toBe('polar-full-test');
		}
	});
});
