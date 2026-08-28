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
		renderVersionGallery?: any;
		renderVersionGalleryLoading?: boolean;
		renderVersionGalleryError?: string;
		onOpenRenderVersionGallery?: (version: any) => void;
		onCloseRenderVersionGallery?: () => void;
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
		renderVersionGallery = null, renderVersionGalleryLoading = false, renderVersionGalleryError = '',
		onOpenRenderVersionGallery = () => {}, onCloseRenderVersionGallery = () => {},
		renderSensorProgress = [], observationScan = null, expectedRenderViews = 0,
		onResumeRun = () => {}, onPromoteVersion = () => {}, onPruneVersion = () => {},
	}: Props = $props();

	let activeTab = $state<'overview' | 'jobs' | 'logs'>('overview');
	let jobFilter = $state<'all' | 'running' | 'failed' | 'queued'>('all');
	let graphView = $state<'grid' | 'list'>('grid');
	let gridMode = $state<'lanes' | 'compact'>('lanes');
	let variantFilter = $state('all');
	let phaseFilter = $state('all');
	let galleryStokesComponent = $state<'s0' | 's1' | 's2' | 's3'>('s0');
	const galleryHasStokes = $derived(
		(renderVersionGallery?.captures ?? []).some((capture: any) => Boolean(capture.stokes_image_urls)),
	);
	// Successor runs deliberately do not materialize their tasks until the
	// previous variant completes.  Present the whole submission contract here,
	// otherwise a 3× polar full sweep looks like only its first batch exists.
	const polarRenderGroups = $derived.by(() => {
		const groups = new Map<string, any[]>();
		for (const version of renderVersions ?? []) {
			const metadata = version?.metadata ?? {};
			const groupId = String(metadata.submission_group_id ?? '');
			if (!groupId.startsWith('polar-')) continue;
			groups.set(groupId, [...(groups.get(groupId) ?? []), version]);
		}
		return [...groups.entries()].map(([groupId, versions]) => {
			const ordered = [...versions].sort((a, b) => Number(a?.metadata?.variant_sequence_index ?? 0) - Number(b?.metadata?.variant_sequence_index ?? 0));
			const stageTotal = Math.max(0, ...ordered.map((version) => Number(version?.run_progress?.total) || 0));
			const stageCount = Math.max(ordered.length, ...ordered.map((version) => Number(version?.metadata?.variant_sequence_total) || 0));
			const completed = ordered.reduce((sum, version) => sum + (Number(version?.run_progress?.completed) || 0), 0);
			const failed = ordered.reduce((sum, version) => sum + (Number(version?.run_progress?.failed) || 0), 0);
			return {
				groupId,
				kind: groupId.startsWith('polar-full-') ? 'Polar full sweep' : 'Polar sample sweep',
				expectedTotal: stageTotal * stageCount,
				completed,
				failed,
				stages: ordered.map((version, index) => {
					const total = Number(version?.run_progress?.total) || 0;
					const variant = String(version?.metadata?.scene_variant_key ?? version?.metadata?.variant ?? 'base');
					return {
						variant: variant === 'perturbed' ? 'passive' : variant === 'perturbed_active_polar' ? 'active' : variant,
						completed: Number(version?.run_progress?.completed) || 0,
						total,
						failed: Number(version?.run_progress?.failed) || 0,
						waiting: total === 0 && index > 0 && String(version?.run_status ?? version?.status ?? '') !== 'completed',
					};
				}),
			};
		}).sort((a, b) => b.groupId.localeCompare(a.groupId));
	});

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
							{#each polarRenderGroups.slice(0, 2) as group}
								<section class="polar-group-progress" aria-label={`${group.kind} progress`}>
									<div>
										<strong>{group.kind}</strong>
										<small>{group.completed}/{group.expectedTotal || '?'} complete{group.failed ? ` · ${group.failed} failed` : ''}</small>
									</div>
									<div class="polar-group-stages">
										{#each group.stages as stage}
											<span class:waiting={stage.waiting} class:failed={stage.failed > 0}>
												<strong>{stage.variant}</strong>
												{#if stage.waiting} waiting for predecessor
												{:else} {stage.completed}/{stage.total}{/if}
											</span>
										{/each}
									</div>
									<code>{group.groupId}</code>
								</section>
							{/each}
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
									<button class="button button-subtle" disabled={renderVersionGalleryLoading} onclick={() => onOpenRenderVersionGallery(version)}>Gallery</button>
									{#if version.run_status === 'paused' && version.run_id}
										<button class="button button-primary" disabled={actionInFlight} onclick={() => onResumeRun(String(version.run_id))}>Resume this</button>
									{/if}
									{#if version.status !== 'active'}<button class="button button-subtle" disabled={version.status === 'pruned'} onclick={() => onPromoteVersion(version)}>Promote</button>{/if}
									{#if version.status !== 'active'}<button class="button button-subtle danger" disabled={version.status === 'pruned'} onclick={() => onPruneVersion(version)}>Prune</button>{/if}
								</div>
							{/each}
							{#if renderVersionGalleryLoading}
								<div class="version-gallery-loading">Opening immutable render gallery…</div>
							{:else if renderVersionGalleryError}
								<div class="version-gallery-error">Gallery unavailable: {renderVersionGalleryError}</div>
							{:else if renderVersionGallery}
								<section class="version-gallery" aria-label="Selected render version gallery">
									<div class="version-gallery-head">
										<div>
											<strong>Render gallery</strong>
											<small>{renderVersionGallery.capture_count ?? 0} captures{renderVersionGallery.submission_group_id ? ` · group ${renderVersionGallery.submission_group_id}` : ''}</small>
										</div>
										{#if galleryHasStokes}
											<div class="stokes-picker" aria-label="Polarized RGB component">
												{#each ['s0', 's1', 's2', 's3'] as component}
													<button class:active={galleryStokesComponent === component} onclick={() => galleryStokesComponent = component as typeof galleryStokesComponent}>{component.toUpperCase()}</button>
												{/each}
											</div>
										{/if}
										<button class="button button-subtle" onclick={onCloseRenderVersionGallery}>Close</button>
									</div>
									<div class="version-gallery-grid">
										{#each renderVersionGallery.captures ?? [] as capture}
											<article class="version-capture" class:missing={!(capture.stokes_image_urls?.[galleryStokesComponent] ?? capture.image_url)}>
												{#if capture.stokes_image_urls?.[galleryStokesComponent] ?? capture.image_url}
													<a href={capture.stokes_image_urls?.[galleryStokesComponent] ?? capture.image_url} target="_blank" rel="noreferrer" title="Open full-size render">
														<img src={capture.stokes_image_urls?.[galleryStokesComponent] ?? capture.image_url} alt={`${capture.variant} ${capture.node_id} ${capture.heading_id} ${galleryStokesComponent.toUpperCase()}`} loading="lazy" />
													</a>
												{:else}
													<div class="version-capture-placeholder">{capture.state}</div>
												{/if}
												<div class="version-capture-meta">
													<strong>{capture.variant}</strong>
													<code>{capture.node_id} · {capture.heading_id}</code>
													<small>{capture.sensor_id ?? 'scene'} · {capture.has_stokes_data ? `${galleryStokesComponent.toUpperCase()} RGB${galleryStokesComponent === 's0' ? '' : ' (signed)'}` : capture.modality}</small>
												</div>
											</article>
										{/each}
									</div>
								</section>
							{/if}
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
					{#if activeBatch?.summary_only}
						<details class="large-sweep-summary">
							<summary>
								<strong>Large sweep</strong>
								<span>aggregate polling</span>
								<span>{activeBatch?.graph_batch_summaries?.length ?? 0} batches</span>
								{#if (activeBatch?.jobs?.length ?? 0) > 0}
									<span class="large-sweep-diagnostics">{activeBatch.jobs.length} diagnostic jobs</span>
								{/if}
							</summary>
							<div class="large-sweep-detail">
								<p>Per-job rows are loaded only for failed or running jobs, keeping large sweep refreshes lightweight.</p>
								<div class="large-sweep-batches">
									{#each activeBatch?.graph_batch_summaries ?? [] as batch}
										<span>
											<small>{batch.scene_variant_key ?? 'base'}</small>
											<strong>{batch.progress?.completed ?? 0}/{batch.progress?.total ?? 0}</strong>
											{#if (batch.counts?.failed ?? 0) > 0}<em>{batch.counts.failed} failed</em>{/if}
										</span>
									{/each}
								</div>
							</div>
						</details>
					{/if}
					{#if (activeBatch?.summary_errors?.length ?? 0) > 0}
						<section class="failure-strip" aria-live="polite">
							<strong>Some batch summaries could not be refreshed</strong>
							{#each activeBatch.summary_errors as summaryError}
								<small><code>{summaryError.batch_id}</code> · {summaryError.message}</small>
							{/each}
						</section>
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
					<div class="jobs-results">
						{#if isGraphSweepRenderMode(renderMode) && graphView === 'grid'}
							<SweepJobGrid batchJobGrid={filteredGraphGrid} mode={gridMode} {selectedBatchJobId} {onSelectBatchJob} />
						{:else}
							<GenericJobList activeBatch={filteredBatch} {selectedBatchJobId} {onSelectBatchJob} />
						{/if}
					</div>
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
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-height: 0;
		height: 100%;
	}
	.large-sweep-summary {
		flex: 0 0 auto;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-2);
		color: var(--muted-strong);
	}
	.large-sweep-summary summary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 32px;
		padding: 0 var(--space-3);
		cursor: pointer;
		list-style: none;
		font-size: var(--font-size-xs);
	}
	.large-sweep-summary summary::-webkit-details-marker { display: none; }
	.large-sweep-summary summary::before { content: '›'; font-size: 16px; transition: transform 120ms ease; }
	.large-sweep-summary[open] summary::before { transform: rotate(90deg); }
	.large-sweep-summary summary strong { color: var(--text); }
	.large-sweep-summary summary span { white-space: nowrap; }
	.large-sweep-diagnostics {
		margin-left: auto;
		padding: 2px 7px;
		border-radius: 999px;
		background: color-mix(in srgb, var(--warning, #f59e0b) 16%, var(--surface-1));
		color: var(--text);
		font-weight: 700;
	}
	.large-sweep-detail { padding: 0 var(--space-3) var(--space-3); }
	.large-sweep-detail p { margin: 0 0 var(--space-2); color: var(--muted); font-size: var(--font-size-xs); }
	.large-sweep-batches { display: flex; flex-wrap: wrap; gap: 6px; }
	.large-sweep-batches > span {
		display: inline-flex;
		align-items: baseline;
		gap: 5px;
		padding: 4px 7px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
	}
	.large-sweep-batches small { color: var(--muted); }
	.large-sweep-batches strong { color: var(--text); }
	.large-sweep-batches em { color: var(--danger, #dc2626); font-size: 10px; font-style: normal; }
	.jobs-results { flex: 1 1 auto; min-height: 0; }
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
	.polar-group-progress { display: grid; grid-template-columns: minmax(150px, 0.55fr) minmax(280px, 1.35fr) minmax(130px, 0.6fr); align-items: center; gap: 0.6rem; margin: 0.35rem 0; padding: 0.45rem 0.55rem; border: 1px solid #93c5fd; border-radius: 6px; background: color-mix(in srgb, var(--surface-1) 92%, #dbeafe); font-size: 0.72rem; }
	.polar-group-progress > div:first-child { display: grid; gap: 2px; }
	.polar-group-progress small, .polar-group-progress code { color: var(--muted-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.polar-group-progress code { font-size: 0.64rem; text-align: right; }
	.polar-group-stages { display: flex; flex-wrap: wrap; gap: 0.3rem; }
	.polar-group-stages span { padding: 2px 5px; border: 1px solid var(--panel-border); border-radius: 999px; background: var(--surface-1); white-space: nowrap; }
	.polar-group-stages span.waiting { color: var(--muted); border-style: dashed; }
	.polar-group-stages span.failed { color: var(--danger, #dc2626); border-color: var(--danger, #dc2626); }
	.status-active { color: var(--success, #4ade80); }
	.status-staging, .status-ready { color: var(--warning, #fbbf24); }
	.status-superseded, .status-pruned { color: var(--text-muted, #94a3b8); }
	.version-gallery-loading, .version-gallery-error {
		margin-top: var(--space-2); padding: var(--space-2); border-radius: var(--radius-sm);
		font-size: var(--font-size-xs); color: var(--muted-strong); background: var(--surface-1);
	}
	.version-gallery-error { color: var(--danger, #dc2626); }
	.version-gallery { display: grid; gap: var(--space-2); margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--panel-border); }
	.version-gallery-head { display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); }
	.version-gallery-head > div { display: grid; gap: 2px; }
	.version-gallery-head small { color: var(--muted); font-size: var(--font-size-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 50vw; }
	.stokes-picker { display: inline-flex; gap: 3px; padding: 3px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-1); }
	.stokes-picker button { min-width: 30px; border: 0; border-radius: 4px; padding: 3px 6px; color: var(--muted-strong); background: transparent; font-size: 10px; font-weight: 700; cursor: pointer; }
	.stokes-picker button:hover { background: var(--surface-2); }
	.stokes-picker button.active { color: white; background: var(--accent, #2563eb); }
	.version-gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: var(--space-2); max-height: 420px; overflow: auto; padding-right: 2px; }
	.version-capture { overflow: hidden; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-1); }
	.version-capture a { display: block; aspect-ratio: 1.35; background: #111827; }
	.version-capture img { display: block; width: 100%; height: 100%; object-fit: cover; }
	.version-capture-placeholder { display: grid; place-items: center; min-height: 118px; color: var(--muted); background: var(--surface-2); text-transform: uppercase; font-size: 11px; }
	.version-capture.missing { opacity: 0.72; }
	.version-capture-meta { display: grid; gap: 2px; padding: 6px 7px; min-width: 0; font-size: 10px; }
	.version-capture-meta strong { color: var(--text); text-transform: capitalize; }
	.version-capture-meta code, .version-capture-meta small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted-strong); }

</style>
