export const POLAR_SAMPLE_COUNT = 10;
export const POLAR_SAMPLE_VARIANTS = ['perturbed', 'perturbed_active_polar'] as const;
export const POLAR_FULL_VARIANTS = ['base', 'perturbed', 'perturbed_active_polar'] as const;

export type PolarSamplePlan = {
	submission_group_id: string;
	selection_manifest_ref: string;
	view_keys: Array<{ node_id: string; heading_id: string }>;
};

export function polarSampleSweepReady(input: {
	projectId: string;
	hasGraph: boolean;
	renderSceneSynced: boolean;
	perturbedRenderReady: boolean;
	hasPolarCamera: boolean;
	inFlight: boolean;
}): boolean {
	return Boolean(
		input.projectId && input.hasGraph && input.renderSceneSynced
		&& input.perturbedRenderReady && input.hasPolarCamera && !input.inFlight
	);
}

export function newPolarSampleSubmissionGroup(): string {
	return `polar-sample-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function polarSampleSweepPayloads(plan: PolarSamplePlan, previousVariantBatchId?: string): Array<Record<string, unknown>> {
	if (plan.view_keys.length !== POLAR_SAMPLE_COUNT) {
		throw new Error(`Polar Sample Sweep requires exactly ${POLAR_SAMPLE_COUNT} views.`);
	}
	const viewKeys = plan.view_keys.map(({ node_id, heading_id }) => ({ node_id, heading_id }));
	const unique = new Set(viewKeys.map(({ node_id, heading_id }) => `${node_id}/${heading_id}`));
	if (unique.size !== POLAR_SAMPLE_COUNT) throw new Error('Polar Sample Sweep views must be unique.');
	return POLAR_SAMPLE_VARIANTS.map((scene_variant_key, index) => ({
		view_keys: viewKeys,
		sensor_scope: 'selected',
		sensor_ids: ['polar_cam'],
		variant: 'cuda_ad_rgb_polarized',
		render_settings: { polar_color_mode: 'rgb_stokes_12' },
		scene_variant_key,
		submission_group_id: plan.submission_group_id,
		polar_sample_selection_manifest_ref: plan.selection_manifest_ref,
		variant_sequence_index: index,
		variant_sequence_total: POLAR_SAMPLE_VARIANTS.length,
		...(index && previousVariantBatchId ? { previous_variant_batch_id: previousVariantBatchId } : {}),
	}));
}

/** Payload contract for the deliberately explicit all-view polar production sweep.
 * Batch IDs are filled in by the caller as each predecessor is registered. */
export function polarFullSweepPayloads(submissionGroupId: string): Array<Record<string, unknown>> {
	if (!submissionGroupId) throw new Error('Polar Full Sweep requires a submission group.');
	return POLAR_FULL_VARIANTS.map((scene_variant_key, index) => ({
		sensor_scope: 'selected',
		sensor_ids: ['polar_cam'],
		variant: 'cuda_ad_rgb_polarized',
		render_settings: { polar_color_mode: 'rgb_stokes_12' },
		scene_variant_key,
		submission_group_id: submissionGroupId,
		variant_sequence_index: index,
		variant_sequence_total: POLAR_FULL_VARIANTS.length,
	}));
}
