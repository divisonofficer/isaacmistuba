export type SensorInspectorTab = 'test' | 'batch' | 'profiles';
export type TestRenderTarget = 'viewpoint' | 'hot_camera';
export type BatchScope = 'navigation_support' | 'full_graph' | 'episode_path' | 'polar_evaluation';
export type RenderVariant = 'base' | 'perturbed' | 'both';

export function defaultBatchScope(input: {
	navigationSupportReady?: boolean;
	hasGraph?: boolean;
}): BatchScope {
	return input.navigationSupportReady ? 'navigation_support' : 'full_graph';
}

export function renderCampaignSummary(rows: any[] | null | undefined) {
	const usable = (rows ?? []).filter((row) => Number(row?.total) > 0);
	const total = usable.reduce((sum, row) => sum + (Number(row?.total) || 0), 0);
	const completed = usable.reduce((sum, row) => sum + (Number(row?.completed) || 0), 0);
	const running = usable.reduce((sum, row) => sum + (Number(row?.running) || 0), 0);
	const queued = usable.reduce((sum, row) => sum + (Number(row?.queued) || 0), 0);
	const failed = usable.reduce((sum, row) => sum + (Number(row?.failed) || 0), 0);
	return {
		total,
		completed: Math.min(completed, total),
		running,
		queued,
		failed,
		percent: total ? Math.round(((completed + failed) / total) * 100) : 0,
	};
}

export function batchScopeEstimate(input: {
	scope: BatchScope;
	navigationSupportViews?: number;
	graphNodeCount?: number;
	headingsPerNode?: number;
	episodePathNodeCount?: number;
	sensorCount?: number;
	polarMode?: 'sample' | 'full';
	coverage?: any[];
	selectedSensorIds?: string[];
	variant?: RenderVariant;
}) {
	const sensors = Math.max(1, Number(input.sensorCount) || 1);
	const graphViews = Math.max(0, Number(input.graphNodeCount) || 0) * Math.max(0, Number(input.headingsPerNode) || 0);
	const supportViews = Math.max(0, Number(input.navigationSupportViews) || 0);
	const episodeViews = Math.max(0, Number(input.episodePathNodeCount) || 0) * Math.max(0, Number(input.headingsPerNode) || 0);
	const variants = input.variant === 'both' ? 2 : 1;
	let total = 0;
	let label = 'views';
	let exact = false;

	if (input.scope === 'navigation_support') {
		total = supportViews * sensors * variants;
		label = 'native views';
	} else if (input.scope === 'full_graph') {
		total = graphViews * sensors * variants;
	} else if (input.scope === 'episode_path') {
		total = episodeViews * sensors * variants;
	} else if (input.polarMode === 'sample') {
		total = 10 * 2;
		label = 'polar phases';
	} else {
		total = graphViews * 3;
		label = 'polar phases';
	}

	const selected = new Set((input.selectedSensorIds ?? []).map(String));
	const coverage = (input.coverage ?? []).filter((row) => selected.size === 0 || selected.has(String(row?.sensor_id ?? '')));
	const completed = coverage.reduce((sum, row) => sum + (Number(row?.completed) || 0), 0);
	const coverageTotal = coverage.reduce((sum, row) => sum + (Number(row?.total) || 0), 0);
	// Only the immutable render-plan ledger has a scope-exact completion count.
	// Legacy observation scans can overlap, so they remain an estimate in the composer.
	if (
		input.scope === 'navigation_support'
		&& total > 0
		&& coverage.length > 0
		&& coverage.every((row) => row?.coverage_source === 'render_plan')
		&& coverageTotal === total
	) exact = true;

	return {
		total,
		label,
		exact,
		completed: exact ? Math.min(completed, total) : 0,
		missing: exact ? Math.max(0, total - completed) : null,
	};
}
