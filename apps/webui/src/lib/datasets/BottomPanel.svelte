<script lang="ts">
	import { healthStore } from '$lib/stores/health';
	import { bottomPanelMode, setBottomPanelMode, type BottomPanelMode } from '$lib/stores/shell';
	import {
		buildBatchJobGrid,
		buildRenderSummary,
		isGraphSweepRenderMode,
		jobPhase,
		jobVariant,
		normalizeJobStatus,
	} from '$lib/datasets/batchHelpers';
	import GenericJobList from '$lib/datasets/GenericJobList.svelte';
	import JobDetailDrawer from '$lib/datasets/JobDetailDrawer.svelte';
	import LogViewer from '$lib/datasets/LogViewer.svelte';
	import RenderBottleneckBanner from '$lib/datasets/RenderBottleneckBanner.svelte';
	import RenderSummaryBar from '$lib/datasets/RenderSummaryBar.svelte';
	import SweepJobGrid from '$lib/datasets/SweepJobGrid.svelte';

	interface Props {
		bottomPanelCollapsed: boolean;
		activeBatch: any;
		renderMode: string;
		selectedBatchJobId: string;
		selectedBatchJob: any;
		selectedBatchJobLog: string[];
		selectedBatchJobLoading: boolean;
		selectedBatchJobImageUrl: string;
		batchLogEntries: any[];
		activityLog: any[];
		loading: boolean;
		/** A user mutation is running. Gates Refresh/Retry instead of the broad
		 * `loading` (which is true during initial data loads too). */
		actionInFlight?: boolean;
		onTogglePanel: () => void;
		onRefreshBatch: () => void;
		onSelectBatchJob: (job: any) => void;
		onCancelStaleBatchJobs: () => void;
		onCloseJobDetail: () => void;
		onRetryJob: (job: any) => void;
		onCancelJob: (job: any) => void;
		onRefreshSelectedJobLog: () => void;
		renderVersions?: any[];
		renderSensorProgress?: any[];
		observationScan?: any;
		expectedRenderViews?: number;
		renderVersionsLoading?: boolean;
		onRefreshVersions?: () => void;
		onResumeRun?: (runId?: string) => void;
		onPromoteVersion?: (version: any) => void;
		onPruneVersion?: (version: any) => void;
	}

	let {
		bottomPanelCollapsed, activeBatch, renderMode,
		selectedBatchJobId, selectedBatchJob,
		selectedBatchJobLog, selectedBatchJobLoading, selectedBatchJobImageUrl,
		batchLogEntries, activityLog, loading, actionInFlight = false,
		onTogglePanel, onRefreshBatch, onSelectBatchJob,
		onCancelStaleBatchJobs, onCloseJobDetail,
		onRetryJob, onCancelJob, onRefreshSelectedJobLog,
		renderVersions = [], renderVersionsLoading = false, onRefreshVersions = () => {},
		renderSensorProgress = [], observationScan = null, expectedRenderViews = 0,
		onResumeRun = () => {}, onPromoteVersion = () => {}, onPruneVersion = () => {},
	}: Props = $props();

	let activeTab = $state<'overview' | 'jobs' | 'logs'>('overview');
	let jobFilter = $state<'all' | 'running' | 'failed' | 'queued'>('all');
	let graphView = $state<'grid' | 'list'>('grid');
	let gridMode = $state<'lanes' | 'compact'>('lanes');
	let variantFilter = $state('all');
	let phaseFilter = $state('all');

	const health = $derived($healthStore);
	const summary = $derived(buildRenderSummary(activeBatch, health, renderMode));
	const variantOptions = $derived(
		[...new Set((activeBatch?.jobs ?? []).map((job: any) => jobVariant(job)))].sort(),
	);
	const phaseOptions = $derived(
		[...new Set((activeBatch?.jobs ?? []).map((job: any) => jobPhase(job)))].sort(),
	);
	const filteredBatch = $derived.by(() => {
		const jobs = (activeBatch?.jobs ?? []).filter((job: any) => {
			if (jobFilter !== 'all' && normalizeJobStatus(job) !== jobFilter) return false;
			if (variantFilter !== 'all' && jobVariant(job) !== variantFilter) return false;
			if (phaseFilter !== 'all' && jobPhase(job) !== phaseFilter) return false;
			return true;
		});
		return { ...(activeBatch ?? {}), jobs };
	});
	const filteredGraphGrid = $derived(
		isGraphSweepRenderMode(renderMode)
			? buildBatchJobGrid(filteredBatch)
			: { rows: [], headings: [], counts: {}, laneCount: 0 },
	);
	const hasActiveJobs = $derived((summary.counts.running ?? 0) + (summary.counts.queued ?? 0) > 0);
	const failedJobs = $derived((activeBatch?.jobs ?? []).filter((job: any) => normalizeJobStatus(job) === 'failed'));
	const sensorCoverageRows = $derived.by(() => {
		const ledger = new Map<string, any>();
		const sensorIds = new Set<string>();
		for (const item of renderSensorProgress ?? []) {
			const sensorId = String(item?.sensor_id ?? '');
			const variant = String(item?.variant ?? 'base');
			if (!sensorId || !['base', 'perturbed'].includes(variant)) continue;
			sensorIds.add(sensorId);
			ledger.set(`${sensorId}:${variant}`, item);
		}
		const inventory = new Map<string, any>();
		for (const item of observationScan?.sensor_inventory ?? []) {
			const sensorId = String(item?.sensor_id ?? '');
			if (!sensorId) continue;
			sensorIds.add(sensorId);
			inventory.set(sensorId, item);
		}
		const inferredTotal = Math.max(
			Number(expectedRenderViews) || 0,
			...(renderSensorProgress ?? []).map((item: any) => Number(item?.total) || 0),
			...(observationScan?.sensor_inventory ?? []).flatMap((item: any) => [
				Number(item?.base_count) || 0,
				Number(item?.perturbed_count) || 0,
			]),
		);
		return [...sensorIds].sort().map((sensorId) => {
			const disk = inventory.get(sensorId) ?? {};
			const coverage = (variant: 'base' | 'perturbed') => {
				const item = ledger.get(`${sensorId}:${variant}`) ?? {};
				const diskCompleted = Number(variant === 'base' ? disk.base_count : disk.perturbed_count) || 0;
				const ledgerCompleted = Number(item.completed) || 0;
				const total = Math.max(
					inferredTotal,
					Number(item.total) || 0,
					diskCompleted,
				);
				// Legacy consolidation and immutable render versions can contain
				// disjoint views (for example 1403 old grid views plus one newly
				// rendered manual view). The exporter composes both sources, so the
				// monitor must not discard one side by taking only their maximum.
				const completed = Math.min(total, diskCompleted + ledgerCompleted);
				const running = completed >= total ? 0 : Number(item.running) || 0;
				const failed = completed >= total ? 0 : Number(item.failed) || 0;
				const queued = Math.max(0, total - completed - running - failed);
				return {
					completed, total, running, queued, failed,
					percent: total > 0 ? Math.round((completed / total) * 1000) / 10 : 0,
				};
			};
			return { sensorId, base: coverage('base'), perturbed: coverage('perturbed') };
		});
	});

	function setMode(mode: BottomPanelMode) {
		setBottomPanelMode(mode);
	}

	function retryFailedJobs() {
		for (const job of failedJobs) onRetryJob(job);
	}

	function collapsedText() {
		if (!activeBatch) return 'Render Monitor · no active batch';
		const failed = summary.counts.failed ?? 0;
		const running = summary.counts.running ?? 0;
		const queued = summary.counts.queued ?? 0;
		return `${summary.label} · ${summary.complete}/${summary.total} · ${summary.percent}% · ${running} running · ${queued} queued${failed ? ` · ${failed} failed` : ''}`;
	}
</script>

<div class="dataset-bottom" data-mode={$bottomPanelMode}>
	{#if bottomPanelCollapsed}
		<button class="collapsed-bar" type="button" onclick={onTogglePanel} aria-label="Expand render monitor">
			<span class="monitor-dot"></span>
			<strong>Render Monitor</strong>
			<span>{collapsedText()}</span>
		</button>
	{:else}
		<div class="monitor-head">
			<div class="monitor-title">
				<button class="icon-btn" onclick={onTogglePanel} aria-label="Collapse render monitor" title="Collapse">v</button>
				<strong>Render Monitor</strong>
				<span class="live-chip">LIVE</span>
			</div>
			<nav class="monitor-tabs" aria-label="Render monitor tabs">
				<button class:active={activeTab === 'overview'} onclick={() => activeTab = 'overview'}>Overview</button>
				<button class:active={activeTab === 'jobs'} onclick={() => activeTab = 'jobs'}>Jobs</button>
				<button class:active={activeTab === 'logs'} onclick={() => activeTab = 'logs'}>Logs</button>
			</nav>
			<div class="monitor-actions">
				<button class="button button-subtle" disabled={actionInFlight} onclick={onRefreshBatch}>Refresh</button>
				<button class="button button-subtle" disabled={!hasActiveJobs} onclick={onCancelStaleBatchJobs}>Cancel queued</button>
				<button class="button button-primary" disabled={failedJobs.length === 0 || actionInFlight} onclick={retryFailedJobs}>Retry failed ({failedJobs.length})</button>
				<div class="size-controls" aria-label="Panel size">
					<button class:active={$bottomPanelMode === 'expanded'} onclick={() => setMode('expanded')}>M</button>
					<button class:active={$bottomPanelMode === 'maximized'} onclick={() => setMode('maximized')}>L</button>
				</div>
			</div>
		</div>

		<div class="monitor-body" class:drawer-open={Boolean(selectedBatchJob)}>
			{#if activeTab === 'overview'}
				<div class="overview-grid">
					<RenderSummaryBar
						{activeBatch}
						{renderMode}
						{health}
						{loading}
						{onRefreshBatch}
						{onCancelStaleBatchJobs}
						onRetryFailedJobs={retryFailedJobs}
					/>
					{#if isGraphSweepRenderMode(renderMode) && sensorCoverageRows.length > 0}
						<section class="camera-coverage" aria-label="Camera render coverage">
							<div class="camera-coverage-head">
								<strong>Camera coverage</strong>
								<small>completed viewpoint × heading renders</small>
							</div>
							<div class="coverage-table">
								<div class="coverage-header">Camera</div>
								<div class="coverage-header">Base</div>
								<div class="coverage-header">Perturbed</div>
								{#each sensorCoverageRows as row}
									<code class="coverage-sensor">{row.sensorId}</code>
									{#each [row.base, row.perturbed] as cell}
										<div class:complete={cell.total > 0 && cell.completed >= cell.total} class="coverage-cell">
											<div><strong>{cell.completed}/{cell.total}</strong><span>{cell.percent}%</span></div>
											<progress max="100" value={cell.percent}></progress>
											<small>
												{cell.running} running · {cell.queued} queued
												{#if cell.failed > 0} · {cell.failed} failed{/if}
											</small>
										</div>
									{/each}
								{/each}
							</div>
						</section>
					{/if}
					<RenderBottleneckBanner {activeBatch} {health} />
					{#if isGraphSweepRenderMode(renderMode)}
						<section class="version-strip" aria-label="Versioned render artifacts">
							<div class="version-strip-head">
								<strong>Render versions</strong>
								<button class="button button-subtle" disabled={renderVersionsLoading} onclick={onRefreshVersions}>Refresh</button>
							</div>
							{#if renderVersions.length === 0}<small>No versioned runs yet.</small>{/if}
							{#each renderVersions.slice(0, 6) as version}
								<div class="version-row">
									<span class="version-status status-{version.run_status ?? version.status}">{version.run_status ?? version.status}</span>
									<span class="version-scope">{version.metadata?.scene_variant_key ?? version.metadata?.variant ?? 'base'}</span>
									<code>{version.render_version_id}</code>
									{#if version.run_progress}
										<small class="version-progress">
											{version.run_progress.completed}/{version.run_progress.total} complete
											· {version.run_counts?.running ?? 0} running
											· {version.run_counts?.queued ?? 0} queued
											{#if (version.run_counts?.failed ?? 0) > 0} · {version.run_counts.failed} failed{/if}
										</small>
									{/if}
									<small>{version.created_at ?? ''}</small>
									{#if version.run_status === 'paused' && version.run_id}
										<button class="button button-primary" disabled={actionInFlight} onclick={() => onResumeRun(String(version.run_id))}>Resume this</button>
									{/if}
									{#if version.status !== 'active'}<button class="button button-subtle" disabled={version.status === 'pruned'} onclick={() => onPromoteVersion(version)}>Promote</button>{/if}
									{#if version.status !== 'active'}<button class="button button-subtle danger" disabled={version.status === 'pruned'} onclick={() => onPruneVersion(version)}>Prune</button>{/if}
								</div>
							{/each}
						</section>
					{/if}
					{#if failedJobs.length > 0}
						<section class="failure-strip">
							<strong>Recent failures ({failedJobs.length})</strong>
							<div>
								{#each failedJobs.slice(0, 5) as job}
									<button type="button" onclick={() => onSelectBatchJob(job)}>
										<span>{job.heading_id ?? job.preview_id ?? job.node_id ?? 'job'}</span>
										<small>{String(job?.status?.error ?? job?.error ?? job?.status?.progress_stage ?? 'failed').slice(0, 90)}</small>
									</button>
								{/each}
							</div>
						</section>
					{/if}
				</div>
			{:else if activeTab === 'jobs'}
				<div class="jobs-panel">
					{#if activeBatch?.summary_only && (activeBatch?.jobs?.length ?? 0) === 0}
						<div class="empty">
							Large sweep summary mode — per-job rows are not repeatedly fetched.
							{#each activeBatch?.graph_batch_summaries ?? [] as batch}
								<span> · {batch.scene_variant_key ?? 'base'} {batch.progress?.completed ?? 0}/{batch.progress?.total ?? 0}</span>
							{/each}
						</div>
					{/if}
					<div class="jobs-toolbar">
						<div class="toolbar-left">
							{#if isGraphSweepRenderMode(renderMode)}
								<div class="segmented">
									<button class:active={graphView === 'grid'} onclick={() => graphView = 'grid'}>Grid</button>
									<button class:active={graphView === 'list'} onclick={() => graphView = 'list'}>List</button>
								</div>
								{#if graphView === 'grid'}
									<div class="segmented">
										<button class:active={gridMode === 'lanes'} onclick={() => gridMode = 'lanes'}>Lanes</button>
										<button class:active={gridMode === 'compact'} onclick={() => gridMode = 'compact'}>Compact</button>
									</div>
								{/if}
								<label class="filter-select">
									<span>Variant</span>
									<select bind:value={variantFilter} aria-label="Filter jobs by render variant">
										<option value="all">All</option>
										{#each variantOptions as variant}<option value={variant}>{variant}</option>{/each}
									</select>
								</label>
								<label class="filter-select">
									<span>Phase</span>
									<select bind:value={phaseFilter} aria-label="Filter jobs by render phase">
										<option value="all">All</option>
										{#each phaseOptions as phase}<option value={phase}>{phase}</option>{/each}
									</select>
								</label>
							{/if}
						</div>
						<div class="segmented">
							<button class:active={jobFilter === 'all'} onclick={() => jobFilter = 'all'}>All</button>
							<button class:active={jobFilter === 'running'} onclick={() => jobFilter = 'running'}>Running</button>
							<button class:active={jobFilter === 'failed'} onclick={() => jobFilter = 'failed'}>Failed</button>
							<button class:active={jobFilter === 'queued'} onclick={() => jobFilter = 'queued'}>Queued</button>
						</div>
					</div>
					{#if isGraphSweepRenderMode(renderMode) && graphView === 'grid'}
						<SweepJobGrid batchJobGrid={filteredGraphGrid} mode={gridMode} {selectedBatchJobId} {onSelectBatchJob} />
					{:else}
						<GenericJobList activeBatch={filteredBatch} {selectedBatchJobId} {onSelectBatchJob} />
					{/if}
				</div>
			{:else}
				<LogViewer {batchLogEntries} {selectedBatchJobLog} {activityLog} selectedJobId={selectedBatchJobId} />
			{/if}
		</div>

		{#if selectedBatchJob}
			<JobDetailDrawer
				job={selectedBatchJob}
				log={selectedBatchJobLog}
				loading={selectedBatchJobLoading}
				imageUrl={selectedBatchJobImageUrl}
				onClose={onCloseJobDetail}
				onRefreshLog={onRefreshSelectedJobLog}
				{onRetryJob}
				{onCancelJob}
			/>
		{/if}
	{/if}
</div>

<style>
	.dataset-bottom {
		position: relative;
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		height: 100%;
		min-height: 0;
		background: var(--surface-1);
		color: var(--text);
	}
	.collapsed-bar {
		height: 36px;
		width: 100%;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 0 var(--space-3);
		border: 0;
		background: var(--surface-1);
		color: var(--muted-strong);
		text-align: left;
		cursor: pointer;
	}
	.collapsed-bar strong { color: var(--text); }
	.monitor-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; }
	.monitor-head {
		display: grid;
		grid-template-columns: auto auto minmax(0, 1fr);
		gap: var(--space-3);
		align-items: center;
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		border-bottom: 1px solid var(--panel-border);
		background: var(--surface-1);
	}
	.monitor-title,
	.monitor-actions,
	.monitor-tabs,
	.size-controls,
	.segmented,
	.jobs-toolbar,
	.toolbar-left,
	.filter-select {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.monitor-title strong { font-size: var(--font-size-sm); }
	.live-chip {
		padding: 1px 6px;
		border-radius: 99px;
		background: #dcfce7;
		color: #166534;
		font-size: 10px;
		font-weight: 700;
	}
	.icon-btn {
		width: 26px;
		height: 26px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-2);
		color: var(--muted-strong);
		cursor: pointer;
	}
	.monitor-tabs button,
	.size-controls button,
	.segmented button {
		height: 28px;
		padding: 0 var(--space-3);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--muted-strong);
		cursor: pointer;
	}
	.monitor-tabs button.active,
	.size-controls button.active,
	.segmented button.active {
		border-color: var(--accent, #2f6fed);
		color: var(--accent, #2f6fed);
		background: color-mix(in srgb, var(--accent, #2f6fed) 8%, var(--surface-1));
	}
	.monitor-actions { justify-content: flex-end; flex-wrap: wrap; }
	.monitor-body {
		min-height: 0;
		overflow: auto;
		padding: var(--space-3);
	}
	.monitor-body.drawer-open {
		padding-right: calc(clamp(360px, 36vw, 520px) + var(--space-5));
	}
	.overview-grid { display: grid; gap: var(--space-3); }
	.camera-coverage {
		display: grid;
		gap: var(--space-2);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-2);
		padding: var(--space-3);
	}
	.camera-coverage-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); }
	.camera-coverage-head strong { font-size: var(--font-size-sm); }
	.camera-coverage-head small { color: var(--muted); }
	.coverage-table {
		display: grid;
		grid-template-columns: minmax(180px, 0.8fr) repeat(2, minmax(220px, 1fr));
		gap: 1px;
		overflow: hidden;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--panel-border);
	}
	.coverage-header, .coverage-sensor, .coverage-cell { background: var(--surface-1); padding: 8px 10px; }
	.coverage-header { color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: 700; text-transform: uppercase; }
	.coverage-sensor { display: flex; align-items: center; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
	.coverage-cell { display: grid; gap: 4px; }
	.coverage-cell > div { display: flex; justify-content: space-between; gap: var(--space-2); font-size: var(--font-size-xs); }
	.coverage-cell > div span { color: var(--muted-strong); font-weight: 700; }
	.coverage-cell.complete > div span { color: var(--success, #16a34a); }
	.coverage-cell progress { width: 100%; height: 7px; accent-color: var(--accent, #2563eb); }
	.coverage-cell.complete progress { accent-color: var(--success, #16a34a); }
	.coverage-cell small { color: var(--muted); font-size: 10px; }
	.failure-strip {
		display: grid;
		gap: var(--space-2);
		border: 1px solid color-mix(in srgb, var(--danger, #dc2626) 35%, var(--panel-border));
		border-radius: var(--radius-md);
		background: var(--surface-1);
		padding: var(--space-3);
	}
	.failure-strip strong { color: var(--text); font-size: var(--font-size-sm); }
	.failure-strip div { display: flex; flex-wrap: wrap; gap: var(--space-2); }
	.failure-strip button {
		display: grid;
		gap: 2px;
		max-width: 260px;
		border: 1px solid #fecaca;
		border-radius: var(--radius-sm);
		background: #fef2f2;
		color: #991b1b;
		padding: var(--space-2);
		text-align: left;
		cursor: pointer;
	}
	.failure-strip small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.jobs-panel {
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		gap: var(--space-3);
		min-height: 0;
		height: 100%;
	}
	.jobs-toolbar { justify-content: space-between; flex-wrap: wrap; }
	.toolbar-left { flex-wrap: wrap; }
	.filter-select {
		gap: 5px;
		color: var(--muted);
		font-size: 10px;
	}
	.filter-select select {
		height: 28px;
		max-width: 128px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--text);
		padding: 0 24px 0 7px;
		font-size: var(--font-size-xs);
	}
	@media (max-width: 1100px) {
		.monitor-head { grid-template-columns: 1fr; }
		.monitor-actions { justify-content: flex-start; }
		.monitor-body.drawer-open { padding-right: var(--space-3); }
		.coverage-table { grid-template-columns: minmax(140px, 0.7fr) repeat(2, minmax(180px, 1fr)); overflow-x: auto; }
	}

	.version-strip { margin: 0.5rem 0; padding: 0.6rem 0.75rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); }
	.version-strip-head, .version-row { display: flex; align-items: center; gap: 0.5rem; }
	.version-strip-head { justify-content: space-between; margin-bottom: 0.35rem; }
	.version-row { padding: 0.2rem 0; font-size: 0.75rem; }
	.version-row code { min-width: 12rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.version-scope { min-width: 4.5rem; font-weight: 700; color: var(--muted-strong); }
	.version-progress { min-width: 22rem; color: var(--muted-strong); white-space: nowrap; }
	.version-status { min-width: 4.5rem; text-transform: uppercase; font-size: 0.65rem; }
	.status-active { color: var(--success, #4ade80); }
	.status-staging, .status-ready { color: var(--warning, #fbbf24); }
	.status-superseded, .status-pruned { color: var(--text-muted, #94a3b8); }

</style>
