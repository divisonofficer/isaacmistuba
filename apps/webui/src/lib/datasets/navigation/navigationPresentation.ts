export type NavigationInspectorTab = 'setup' | 'routes' | 'support' | 'episodes';

export type PrimaryNavigationAction = {
	id: 'build-grid' | 'build-place-graph' | 'analyze-support' | 'build-support' | 'render-support';
	label: string;
	description: string;
	disabled: boolean;
};

/**
 * ``support/analyze`` is deliberately non-persistent, so the inspector keeps
 * the response in page state.  The current daemon returns ``summary`` at the
 * top level, while an older compatible daemon can put it under ``analysis``.
 * Both are a completed dry run.  A structured ``ok: false`` response is the
 * one case that must *not* unlock the destructive/materialising Build step.
 */
export function hasSuccessfulSupportAnalysis(analysis: any): boolean {
	if (!analysis || analysis.ok === false) return false;
	return Boolean(
		analysis.summary
		|| analysis.analysis?.summary
		// The mode marker is part of the HTTP contract and lets a newer WebUI
		// interoperate with an older daemon that did not include the estimate
		// summary in its response.
		|| analysis.mode === 'analyze',
	);
}

export function supportAnalysisSummary(analysis: any): any | null {
	if (!hasSuccessfulSupportAnalysis(analysis)) return null;
	return analysis?.summary ?? analysis?.analysis?.summary ?? null;
}

/** Keep the sole sticky action deterministic and easy to test. */
export function primaryNavigationAction(state: any): PrimaryNavigationAction {
	// A v4 place graph is built from the navigation motion grid and persists
	// with its own immutable digest. The broader workflow status can mark the
	// legacy grid stale after an annotation-only edit, but that must not make an
	// already reviewable Place Graph/Blueprint collection regress to “Build
	// grid” and hide the Analyze → Build Support sequence.
	const supportHasPlaceGraph = Boolean(state.navigationSupport?.place_graph?.nodes?.length);
	if (!state.hasMap && !supportHasPlaceGraph) {
		return { id: 'build-grid', label: 'Build grid', description: state.caps?.buildMap?.reason || 'Build the traversable grid first.', disabled: !state.caps?.buildMap?.enabled };
	}
	if (!state.navigationSupport) {
		return { id: 'build-place-graph', label: 'Build Place Graph', description: state.caps?.buildGraph?.reason || 'Create reviewable sparse places and routes.', disabled: !state.caps?.buildGraph?.enabled };
	}
	const approved = (state.navigationSupport?.route_blueprints?.blueprints ?? []).filter((item: any) => item.status === 'approved').length;
	if (!approved) {
		return { id: 'analyze-support', label: 'Analyze support', description: 'Approve at least one route blueprint before support can be built.', disabled: true };
	}
	if (!hasSuccessfulSupportAnalysis(state.supportAnalysis)) {
		return { id: 'analyze-support', label: 'Analyze support', description: 'Estimate native poses and coverage for approved routes.', disabled: Boolean(state.loading || state.buildingGraph) };
	}
	if (!state.supportReady) {
		return { id: 'build-support', label: 'Build Navigation Support', description: 'Materialize the approved route support plan.', disabled: Boolean(state.loading || state.buildingGraph) };
	}
	return { id: 'render-support', label: 'Render Navigation Support Plan', description: 'Submit the current native pose and heading plan.', disabled: Boolean(state.loading || state.sweepSubmissionInFlight) };
}

export function filterBlueprints(blueprints: any[], query: string, status: string): any[] {
	const needle = query.trim().toLowerCase();
	return blueprints.filter((item) => {
		if (status !== 'all' && item.status !== status) return false;
		if (!needle) return true;
		return [item.blueprint_id, item.start_anchor_id, item.goal_anchor_id, item.status]
			.some((value) => String(value ?? '').toLowerCase().includes(needle));
	});
}
