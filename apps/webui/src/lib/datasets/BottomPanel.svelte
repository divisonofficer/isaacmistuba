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
	import { ChevronDown } from '@lucide/svelte';

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
		renderCoverageLoading?: boolean;
		renderCoverageUpdatedAt?: number;
		observationScan?: any;
		expectedRenderViews?: number;
		renderVersionsLoading?: boolean;
		onRefreshVersions?: () => void;
		renderVersionGallery?: any;
		renderVersionGalleryLoading?: boolean;
		renderVersionGalleryError?: string;
		onOpenRenderVersionGallery?: (version: any, options?: any) => void;
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
		renderSensorProgress = [], renderCoverageLoading = false, renderCoverageUpdatedAt = 0, observationScan = null, expectedRenderViews = 0,
		onResumeRun = () => {}, onPromoteVersion = () => {}, onPruneVersion = () => {},
	}: Props = $props();

	let activeTab = $state<'overview' | 'jobs' | 'logs'>('overview');
	let jobFilter = $state<'all' | 'running' | 'failed' | 'queued'>('all');
	let graphView = $state<'grid' | 'list'>('grid');
	let gridMode = $state<'lanes' | 'compact'>('lanes');
	let variantFilter = $state('all');
	let phaseFilter = $state('all');
	type GalleryProduct =
		| 'polar_rgb_preview'
		| 'stokes_s0_rgb'
		| 'stokes_s1_r_bwr' | 'stokes_s1_g_bwr' | 'stokes_s1_b_bwr'
		| 'stokes_s2_r_bwr' | 'stokes_s2_g_bwr' | 'stokes_s2_b_bwr'
		| 'stokes_s3_r_bwr' | 'stokes_s3_g_bwr' | 'stokes_s3_b_bwr'
		| 'dop' | 'aolp';
	const galleryProducts: { id: GalleryProduct; label: string; group: 'preview' | 'stokes' | 'derived' }[] = [
		{ id: 'polar_rgb_preview', label: 'Polar RGB', group: 'preview' },
		{ id: 'stokes_s0_rgb', label: 'S0 RGB', group: 'preview' },
		{ id: 'stokes_s1_r_bwr', label: 'S1 R', group: 'stokes' },
		{ id: 'stokes_s1_g_bwr', label: 'S1 G', group: 'stokes' },
		{ id: 'stokes_s1_b_bwr', label: 'S1 B', group: 'stokes' },
		{ id: 'stokes_s2_r_bwr', label: 'S2 R', group: 'stokes' },
		{ id: 'stokes_s2_g_bwr', label: 'S2 G', group: 'stokes' },
		{ id: 'stokes_s2_b_bwr', label: 'S2 B', group: 'stokes' },
		{ id: 'stokes_s3_r_bwr', label: 'S3 R', group: 'stokes' },
		{ id: 'stokes_s3_g_bwr', label: 'S3 G', group: 'stokes' },
		{ id: 'stokes_s3_b_bwr', label: 'S3 B', group: 'stokes' },
		{ id: 'dop', label: 'DoLP', group: 'derived' },
		{ id: 'aolp', label: 'AoLP', group: 'derived' },
	];
	let galleryProduct = $state<GalleryProduct>('polar_rgb_preview');
	let gallerySelectedTaskKey = $state('');
	let galleryVariantFilter = $state('');
	let gallerySensorFilter = $state('');
	let galleryStateFilter = $state('');
	let gallerySearch = $state('');
	let galleryCursorHistory = $state<Array<string | null>>([]);
	type CoverageRateSample = {
		completed: number;
		sampledAtMs: number;
		viewsPerSecond: number | null;
	};
	let coverageRateSamples = $state<Record<string, CoverageRateSample>>({});
	const galleryCaptures = $derived(renderVersionGallery?.captures ?? []);
	const gallerySelectedCapture = $derived(
		galleryCaptures.find((capture: any) => capture.task_key === gallerySelectedTaskKey) ?? galleryCaptures[0] ?? null,
	);
	const galleryHasStokes = $derived(Boolean(gallerySelectedCapture?.has_stokes_data));
	const galleryHasAnyStokes = $derived(galleryCaptures.some((capture: any) => Boolean(capture?.has_stokes_data)));
	const galleryProductUrl = $derived(
		galleryHasStokes
			? gallerySelectedCapture?.product_urls?.[galleryProduct] ?? null
			: gallerySelectedCapture?.image_url ?? null,
	);
	const galleryVariants = $derived([
		...new Set((renderVersionGallery?.versions ?? []).map((version: any) => String(version.variant ?? '')).filter(Boolean)),
	]);
	const gallerySensors = $derived([
		...new Set(galleryCaptures.flatMap((capture: any) => capture.sensor_ids?.length ? capture.sensor_ids : capture.sensor_id ? [capture.sensor_id] : []).map(String)),
	]);
	const galleryPage = $derived(renderVersionGallery?.page ?? {});
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
	const renderCoverageUpdatedLabel = $derived.by(() => {
		if (!renderCoverageUpdatedAt) return '';
		return new Date(renderCoverageUpdatedAt).toLocaleTimeString([], {
			hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
		});
	});
	// The plan-level card summarises many jobs, but the worker only runs one at
	// a time; take its live stage/profile so the header reflects reality rather
	// than a guess derived from aggregate counts.
	const liveJob = $derived(
		(activeBatch?.jobs ?? []).find((job: any) => String(job?.status?.status ?? job?.status ?? '') === 'running') ?? null,
	);
	const liveJobStage = $derived(String(liveJob?.status?.progress_stage ?? '').trim());
	// A polar batch job carries its live render shape in progress_context (the
	// renderer publishes it there per pass); the flat extras keys are only set
	// for other job kinds. Read both so this card reports the batch actually
	// running instead of falling back to "default" / "0 hit".
	const liveProgressContext = $derived(liveJob?.status?.extras?.progress_context ?? {});
	const liveTextureProfile = $derived(
		liveJob?.status?.extras?.texture_profile
			?? liveJob?.status?.extras?.texture_audit?.texture_profile
			?? liveProgressContext?.texture_profile
			?? null,
	);
	const liveBatchSlots = $derived(
		Number(
			liveJob?.status?.extras?.stokes_heading_batch_size
				?? liveProgressContext?.resident_slots
				?? liveProgressContext?.batch_size
				?? 0,
		),
	);
	const liveCacheMode = $derived(
		liveBatchSlots >= 2
			? `stokes_k${liveBatchSlots}_batched`
			: (liveJob?.status?.extras?.cache_mode ?? null),
	);
	const renderPlanProgress = $derived.by(() => {
		const planned = (renderSensorProgress ?? []).filter((item: any) => item?.coverage_source === 'render_plan');
		if (!planned.length) return null;
		const total = planned.reduce((sum: number, item: any) => sum + (Number(item?.total) || 0), 0);
		if (!total) return null;
		const completed = planned.reduce((sum: number, item: any) => sum + (Number(item?.completed) || 0), 0);
		const running = planned.reduce((sum: number, item: any) => sum + (Number(item?.running) || 0), 0);
		const queued = planned.reduce((sum: number, item: any) => sum + (Number(item?.queued) || 0), 0);
		const failed = planned.reduce((sum: number, item: any) => sum + (Number(item?.failed) || 0), 0);
		const campaignId = String(planned[0]?.campaign_id ?? 'render-plan');
		return {
			summary_only: true,
			logical_progress: true,
			summary_label: 'Navigation Support render plan',
			batch_id: campaignId,
			// Report the stage the worker is actually in. Deriving it from the
			// running/queued counts alone claimed "rendering polarization" for
			// the whole job, including the many minutes a cold scene spends
			// uploading textures and building its OptiX BVH.
			active_stage: liveJobStage || (running > 0 ? 'rendering' : queued > 0 ? 'waiting for scheduled wave' : 'complete'),
			queue_length: queued,
			// RenderSummaryBar renders this as `max${textureProfile}`, so pass
			// the bare number (a 'max512' string rendered as "maxmax512").
			texture_profile: liveTextureProfile,
			cache_mode: liveCacheMode,
			counts: { completed, running, queued, failed, cancelled: 0, unknown: 0 },
			execution_counts: { worker_running: running, prefetched: 0, queued },
			progress: { completed, failed, total, fraction: (completed + failed) / Math.max(1, total) },
		};
	});
	const summary = $derived(buildRenderSummary(renderPlanProgress ?? activeBatch, health, renderMode));
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
	const hasActiveJobs = $derived(!renderPlanProgress && (summary.counts.running ?? 0) + (summary.counts.queued ?? 0) > 0);
	const failedJobs = $derived((activeBatch?.jobs ?? []).filter((job: any) => normalizeJobStatus(job) === 'failed'));
	const sensorCoverageRows = $derived.by(() => {
		const ledger = new Map<string, any>();
		const sensorIds = new Set<string>();
		for (const item of renderSensorProgress ?? []) {
			const sensorId = String(item?.sensor_id ?? '');
			const variant = String(item?.variant ?? 'base');
			if (!sensorId || !['base', 'perturbed', 'perturbed_active_polar'].includes(variant)) continue;
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
			const coverage = (variant: 'base' | 'perturbed' | 'perturbed_active_polar') => {
				const item = ledger.get(`${sensorId}:${variant}`) ?? {};
				const diskCompleted = Number(variant === 'base' ? disk.base_count : disk.perturbed_count) || 0;
				const ledgerCompleted = Number(item.completed) || 0;
				const planBacked = item.coverage_source === 'render_plan';
				const total = Math.max(
					inferredTotal,
					Number(item.total) || 0,
					diskCompleted,
				);
				// A plan-backed ledger already counts every logical pose-heading
				// observation, including K=4 child views. Adding the disk scan would
				// double-count those same completed files. Legacy coverage retains the
				// old disjoint-source consolidation behaviour.
				const completed = Math.min(total, planBacked ? ledgerCompleted : diskCompleted + ledgerCompleted);
				const running = completed >= total ? 0 : Number(item.running) || 0;
				const failed = completed >= total ? 0 : Number(item.failed) || 0;
				const queued = Math.max(0, total - completed - running - failed);
				return {
					completed, total, running, queued, failed,
					// The server derives this from durable attempt timestamps, so it
					// remains usable immediately after refresh and across K=4 bursts.
					etaSeconds: Number(item.eta_seconds),
					etaSource: String(item.eta_source ?? ''),
					percent: total > 0 ? Math.round((completed / total) * 1000) / 10 : 0,
				};
			};
			return { sensorId, base: coverage('base'), perturbed: coverage('perturbed'), active: coverage('perturbed_active_polar') };
		});
	});

	function coverageRateKey(sensorId: string, variant: string) {
		return `${sensorId}:${variant}`;
	}

	function coverageCells(row: any): Array<{ variant: string; cell: any }> {
		return [
			{ variant: 'base', cell: row.base },
			{ variant: 'perturbed', cell: row.perturbed },
			{ variant: 'perturbed_active_polar', cell: row.active },
		];
	}

	function isActiveCoverageCell(cell: any) {
		return Number(cell?.running) > 0 || (Number(cell?.completed) > 0 && Number(cell?.completed) < Number(cell?.total));
	}

	// Render coverage is refreshed from the durable ledger every few seconds.
	// Learn an ETA from that observed logical-view throughput instead of claiming
	// a fixed GPU rate: K=4, K=1 active polar, retries, and queue admission can
	// all change the actual rate materially.
	$effect(() => {
		const nowMs = Date.now();
		const next = { ...coverageRateSamples };
		let changed = false;
		for (const row of sensorCoverageRows) {
			for (const [variant, cell] of [
				['base', row.base],
				['perturbed', row.perturbed],
				['perturbed_active_polar', row.active],
			] as const) {
				const key = coverageRateKey(row.sensorId, variant);
				const completed = Math.max(0, Number(cell?.completed) || 0);
				const previous = coverageRateSamples[key];
				if (!previous) {
					// Start timing only once the variant is actually running. This
					// prevents a successor's waiting-for-base period from poisoning
					// its eventual measured throughput.
					if (isActiveCoverageCell(cell)) {
						next[key] = { completed, sampledAtMs: nowMs, viewsPerSecond: null };
						changed = true;
					}
					continue;
				}
				if (completed <= previous.completed) continue;
				const elapsedSeconds = Math.max(0.001, (nowMs - previous.sampledAtMs) / 1000);
				const instantaneousRate = (completed - previous.completed) / elapsedSeconds;
				// Keep the estimate stable over worker restarts while still reacting
				// to a real K=4 → K=1 phase transition.
				const viewsPerSecond = previous.viewsPerSecond === null
					? instantaneousRate
					: previous.viewsPerSecond * 0.7 + instantaneousRate * 0.3;
				next[key] = { completed, sampledAtMs: nowMs, viewsPerSecond };
				changed = true;
			}
		}
		if (changed) coverageRateSamples = next;
	});

	function formatEta(seconds: number) {
		if (!Number.isFinite(seconds) || seconds < 0) return 'estimating…';
		const wholeSeconds = Math.max(0, Math.ceil(seconds));
		if (wholeSeconds < 90) return `≈ ${wholeSeconds}s`;
		const minutes = Math.ceil(wholeSeconds / 60);
		if (minutes < 90) return `≈ ${minutes}m`;
		const hours = Math.floor(minutes / 60);
		const remainderMinutes = minutes % 60;
		return remainderMinutes ? `≈ ${hours}h ${remainderMinutes}m` : `≈ ${hours}h`;
	}

	function coverageEtaLabel(sensorId: string, variant: string, cell: any) {
		const total = Math.max(0, Number(cell?.total) || 0);
		const completed = Math.max(0, Number(cell?.completed) || 0);
		if (total > 0 && completed >= total) return 'complete';
		const durableEtaSeconds = Number(cell?.etaSeconds);
		if (Number.isFinite(durableEtaSeconds) && durableEtaSeconds >= 0) {
			return `ETA ${formatEta(durableEtaSeconds)}`;
		}
		const sample = coverageRateSamples[coverageRateKey(sensorId, variant)];
		if (sample?.viewsPerSecond && sample.viewsPerSecond > 0) {
			return `ETA ${formatEta((total - completed) / sample.viewsPerSecond)}`;
		}
		return Number(cell?.running) > 0 ? 'ETA estimating…' : 'waiting for predecessor';
	}

	function setMode(mode: BottomPanelMode) {
		setBottomPanelMode(mode);
	}

	function retryFailedJobs() {
		for (const job of failedJobs) onRetryJob(job);
	}

	function galleryProductLabel(productId: GalleryProduct) {
		return galleryProducts.find((product) => product.id === productId)?.label ?? productId;
	}

	function galleryThumbnailUrl(capture: any): string | null {
		if (galleryProduct === 'polar_rgb_preview') {
			return capture?.product_urls?.polar_rgb_preview ?? capture?.image_url ?? null;
		}
		return capture?.product_urls?.[galleryProduct] ?? null;
	}

	function galleryRequest(cursor: string | null = null) {
		return {
			limit: 24,
			cursor,
			variant: galleryVariantFilter || null,
			sensorId: gallerySensorFilter || null,
			state: galleryStateFilter || null,
			query: gallerySearch.trim() || null,
		};
	}

	function resetGalleryControls() {
		galleryProduct = 'polar_rgb_preview';
		gallerySelectedTaskKey = '';
		galleryVariantFilter = '';
		gallerySensorFilter = '';
		galleryStateFilter = '';
		gallerySearch = '';
		galleryCursorHistory = [];
	}

	function openGallery(version: any) {
		resetGalleryControls();
		onOpenRenderVersionGallery(version, galleryRequest());
	}

	function reloadGallery(cursor: string | null = null) {
		const renderVersionId = String(renderVersionGallery?.selected_render_version_id ?? '');
		if (!renderVersionId) return;
		gallerySelectedTaskKey = '';
		onOpenRenderVersionGallery({ render_version_id: renderVersionId }, galleryRequest(cursor));
	}

	function applyGalleryFilters() {
		galleryCursorHistory = [];
		reloadGallery();
	}

	function nextGalleryPage() {
		const cursor = galleryPage?.next_cursor;
		if (!cursor) return;
		galleryCursorHistory = [...galleryCursorHistory, galleryPage?.cursor ? String(galleryPage.cursor) : null];
		reloadGallery(String(cursor));
	}

	function previousGalleryPage() {
		if (!galleryCursorHistory.length) return;
		const previous = galleryCursorHistory[galleryCursorHistory.length - 1] ?? null;
		galleryCursorHistory = galleryCursorHistory.slice(0, -1);
		reloadGallery(previous);
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
				<button class="icon-btn" onclick={onTogglePanel} aria-label="Collapse render monitor" title="Collapse"><ChevronDown size={16} aria-hidden="true" /></button>
				<strong>Render Monitor</strong>
				<span class="live-chip">LIVE</span>
			</div>
			<nav class="monitor-tabs" aria-label="Render monitor tabs">
				<button class:active={activeTab === 'overview'} onclick={() => activeTab = 'overview'}>Overview</button>
				<button class:active={activeTab === 'jobs'} onclick={() => activeTab = 'jobs'}>Jobs</button>
				<button class:active={activeTab === 'logs'} onclick={() => activeTab = 'logs'}>Logs</button>
			</nav>
			<div class="monitor-actions">
				<button class="button button-subtle" disabled={actionInFlight || renderCoverageLoading} onclick={onRefreshBatch}>
					{renderCoverageLoading ? 'Refreshing…' : 'Refresh'}
				</button>
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
						progressBatch={renderPlanProgress}
						canCancel={!renderPlanProgress}
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
								<small>
									completed viewpoint × heading renders
									{#if renderCoverageLoading}
										 · updating…
									{:else if renderCoverageUpdatedLabel}
										 · checked {renderCoverageUpdatedLabel}
									{:else}
										 · waiting for first ledger read
									{/if}
								</small>
							</div>
							<div class="coverage-table">
								<div class="coverage-header">Camera</div>
								<div class="coverage-header">Base</div>
								<div class="coverage-header">Passive</div>
								<div class="coverage-header">Active polar</div>
								{#each sensorCoverageRows as row}
									<code class="coverage-sensor">{row.sensorId}</code>
									{#each coverageCells(row) as coverage}
										{@const cell = coverage.cell}
										<div class:complete={cell.total > 0 && cell.completed >= cell.total} class="coverage-cell">
											<div><strong>{cell.completed}/{cell.total}</strong><span>{cell.percent}%</span></div>
											<progress max="100" value={cell.percent}></progress>
											<small>
												{cell.running} running · {cell.queued} queued
												{#if cell.failed > 0} · {cell.failed} failed{/if}
												<span class="coverage-eta" title="Estimated from recently completed logical views; this updates as worker throughput changes.">
													· {coverageEtaLabel(row.sensorId, coverage.variant, cell)}
												</span>
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
											{version.run_progress.completed}/{version.run_progress.total} dispatch bundles
											· {version.run_counts?.running ?? 0} running
											· {version.run_counts?.queued ?? 0} queued
											{#if (version.run_counts?.failed ?? 0) > 0} · {version.run_counts.failed} failed{/if}
										</small>
									{/if}
									<small>{version.created_at ?? ''}</small>
									<button class="button button-subtle" disabled={renderVersionGalleryLoading} onclick={() => openGallery(version)}>Gallery</button>
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
											<small>{renderVersionGallery.capture_count ?? 0} view renders{renderVersionGallery.submission_group_id ? ` · group ${renderVersionGallery.submission_group_id}` : ''}</small>
										</div>
										<button class="button button-subtle" onclick={onCloseRenderVersionGallery}>Close</button>
									</div>

									<form class="gallery-toolbar" onsubmit={(event) => { event.preventDefault(); applyGalleryFilters(); }}>
										<label class="gallery-search">
											<span class="sr-only">Find a viewpoint or heading</span>
											<input bind:value={gallerySearch} placeholder="Find viewpoint or heading" />
										</label>
										<select aria-label="Filter gallery by render variant" bind:value={galleryVariantFilter}>
											<option value="">All variants</option>
											{#each galleryVariants as item}<option value={item}>{item}</option>{/each}
										</select>
										<select aria-label="Filter gallery by camera" bind:value={gallerySensorFilter}>
											<option value="">All cameras</option>
											{#each gallerySensors as item}<option value={item}>{item}</option>{/each}
										</select>
										<select aria-label="Filter gallery by task state" bind:value={galleryStateFilter}>
											<option value="">All states</option>
											{#each Object.keys(renderVersionGallery.state_counts ?? {}).sort() as item}<option value={item}>{item}</option>{/each}
										</select>
										<button class="button button-subtle" type="submit">Apply</button>
									</form>
									{#if galleryHasAnyStokes}
										<div class="gallery-visualization-picker" aria-label="Gallery visualization">
											<strong>Gallery visualization</strong>
											<div class="gallery-product-groups">
												{#each ['preview', 'stokes', 'derived'] as group}
													<div class="gallery-product-group">
														<span>{group === 'stokes' ? 'S1–S3 BWR' : group}</span>
														<div>
															{#each galleryProducts.filter((product) => product.group === group) as product}
																<button type="button" class:active={galleryProduct === product.id} onclick={() => galleryProduct = product.id}>{product.label}</button>
															{/each}
														</div>
													</div>
												{/each}
											</div>
										</div>
									{/if}
									<div class="gallery-page-note">
										<span>{galleryPage.returned ?? galleryCaptures.length} shown · page size 24 · {galleryProductLabel(galleryProduct)}</span>
										<span>Changing visualization updates every card in this page; choose a card for the exact capture metadata.</span>
									</div>

									{#if galleryCaptures.length === 0}
										<div class="version-gallery-empty">No render task matches these filters.</div>
									{:else}
										<div class="version-gallery-content">
											<div class="version-gallery-grid" aria-label="Paged render capture cards">
												{#each galleryCaptures as capture (capture.task_key)}
													{@const thumbnailUrl = galleryThumbnailUrl(capture)}
													<button
														type="button"
														class="version-capture"
														class:selected={gallerySelectedCapture?.task_key === capture.task_key}
														class:missing={!thumbnailUrl}
														onclick={() => { gallerySelectedTaskKey = String(capture.task_key ?? ''); galleryProduct = 'polar_rgb_preview'; }}
														aria-label={`Inspect ${capture.node_id} ${capture.heading_id}, ${capture.variant}, ${capture.sensor_id ?? 'scene'} `}
													>
														{#if thumbnailUrl}
															<img src={thumbnailUrl} alt={`${capture.node_id} ${capture.heading_id} ${capture.variant} ${galleryProductLabel(galleryProduct)}`} loading="lazy" />
														{:else}
															<div class="version-capture-placeholder">{capture.has_stokes_data ? 'product unavailable' : `${capture.state} · no Stokes`}</div>
														{/if}
														<div class="version-capture-meta">
															<strong>{capture.node_id} <span>· {capture.heading_id}</span></strong>
															<small>{capture.variant} · {capture.sensor_id ?? 'scene'} · {capture.state} · {galleryProductLabel(galleryProduct)}</small>
														</div>
													</button>
												{/each}
											</div>

											{#if gallerySelectedCapture}
												<aside class="gallery-detail" aria-label="Selected render detail">
													<div class="gallery-detail-head">
														<strong>{gallerySelectedCapture.node_id}</strong>
														<code>{gallerySelectedCapture.heading_id}</code>
													</div>
													<small>{gallerySelectedCapture.variant} · {gallerySelectedCapture.sensor_id ?? 'scene'} · {gallerySelectedCapture.state}</small>
													{#if galleryHasStokes}
														<div class="gallery-detail-product"><span>Viewing</span><strong>{galleryProductLabel(galleryProduct)}</strong></div>
														{#if galleryProductUrl}
															<a class="gallery-detail-image" href={galleryProductUrl} target="_blank" rel="noreferrer" title="Open full-size product">
																<img src={galleryProductUrl} alt={`${gallerySelectedCapture.node_id} ${gallerySelectedCapture.heading_id} ${galleryProduct}`} />
															</a>
														{:else}
															<div class="gallery-detail-placeholder">This product is unavailable for this capture.</div>
														{/if}
														<small class="gallery-product-note">S1–S3 cards are raw per-channel signed fields: blue = negative, white = zero, red = positive. DoLP and AoLP are derived from the same immutable Stokes NPZ.</small>
													{:else if gallerySelectedCapture.image_url}
														<a class="gallery-detail-image" href={gallerySelectedCapture.image_url} target="_blank" rel="noreferrer" title="Open full-size render"><img src={gallerySelectedCapture.image_url} alt={`${gallerySelectedCapture.node_id} ${gallerySelectedCapture.heading_id}`} /></a>
													{:else}
														<div class="gallery-detail-placeholder">No published image for this task.</div>
													{/if}
													{#if gallerySelectedCapture.error}<small class="gallery-detail-error">{gallerySelectedCapture.error}</small>{/if}
												</aside>
											{/if}
										</div>
									{/if}

									<div class="gallery-pagination">
										<button class="button button-subtle" disabled={galleryCursorHistory.length === 0 || renderVersionGalleryLoading} onclick={previousGalleryPage}>Previous</button>
										<span>{galleryCursorHistory.length + 1} page · {galleryPage.returned ?? galleryCaptures.length}/{renderVersionGallery.capture_count ?? 0} matching renders</span>
										<button class="button button-subtle" disabled={!galleryPage.next_cursor || renderVersionGalleryLoading} onclick={nextGalleryPage}>Next</button>
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
		grid-template-columns: minmax(180px, 0.8fr) repeat(3, minmax(220px, 1fr));
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
	.coverage-eta { color: var(--muted-strong); font-variant-numeric: tabular-nums; }
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
		.coverage-table { grid-template-columns: minmax(140px, 0.7fr) repeat(3, minmax(180px, 1fr)); overflow-x: auto; }
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
	.version-gallery { display: grid; min-width: 0; gap: var(--space-2); margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--panel-border); }
	.version-gallery-head { display: flex; justify-content: space-between; align-items: center; min-width: 0; gap: var(--space-3); }
	.version-gallery-head > div { display: grid; min-width: 0; gap: 2px; }
	.version-gallery-head small { color: var(--muted); font-size: var(--font-size-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 50vw; }
	.gallery-toolbar { display: grid; grid-template-columns: minmax(180px, 1.4fr) repeat(3, minmax(112px, 0.7fr)) auto; min-width: 0; gap: var(--space-2); }
	.gallery-toolbar input, .gallery-toolbar select { box-sizing: border-box; width: 100%; min-width: 0; height: 32px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); padding: 0 8px; color: var(--text); background: var(--surface-1); font: inherit; font-size: var(--font-size-xs); }
	.gallery-search { min-width: 0; }
	.gallery-visualization-picker { display: grid; grid-template-columns: 132px minmax(0, 1fr); align-items: start; min-width: 0; gap: var(--space-2); padding: var(--space-2); border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--surface-1) 88%, var(--accent, #2563eb)); }
	.gallery-visualization-picker > strong { padding-top: 4px; color: var(--text); font-size: var(--font-size-xs); }
	.gallery-page-note { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px var(--space-3); color: var(--muted); font-size: 11px; }
	.version-gallery-empty, .gallery-detail-placeholder { display: grid; min-height: 110px; place-items: center; padding: var(--space-3); color: var(--muted); text-align: center; border: 1px dashed var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-1); font-size: var(--font-size-xs); }
	.version-gallery-content { display: grid; grid-template-columns: minmax(0, 1fr) minmax(236px, 300px); align-items: start; min-width: 0; gap: var(--space-3); }
	.version-gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(136px, 1fr)); align-content: start; min-width: 0; max-height: 510px; gap: var(--space-2); overflow: auto; padding: 1px 4px 2px 1px; }
	.version-capture { display: grid; min-width: 0; overflow: hidden; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); padding: 0; color: inherit; text-align: left; background: var(--surface-1); cursor: pointer; }
	.version-capture:hover { border-color: color-mix(in srgb, var(--accent, #2563eb) 50%, var(--panel-border)); background: var(--surface-2); }
	.version-capture.selected { outline: 2px solid var(--accent, #2563eb); outline-offset: 1px; }
	.version-capture:focus-visible { outline: 3px solid color-mix(in srgb, var(--accent, #2563eb) 45%, transparent); outline-offset: 2px; }
	.version-capture img { display: block; width: 100%; aspect-ratio: 1.35; object-fit: cover; background: #111827; }
	.version-capture-placeholder { display: grid; place-items: center; min-height: 102px; color: var(--muted); background: var(--surface-2); text-transform: uppercase; font-size: 11px; }
	.version-capture.missing { opacity: 0.72; }
	.version-capture-meta { display: grid; gap: 2px; min-width: 0; padding: 6px 7px; font-size: 10px; }
	.version-capture-meta strong { overflow: hidden; color: var(--text); text-overflow: ellipsis; white-space: nowrap; }
	.version-capture-meta strong span, .version-capture-meta small { color: var(--muted-strong); font-weight: 500; }
	.version-capture-meta small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.gallery-detail { display: grid; min-width: 0; gap: var(--space-2); overflow: hidden; padding: var(--space-2); border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-1); }
	.gallery-detail-head { display: flex; align-items: baseline; justify-content: space-between; min-width: 0; gap: var(--space-2); }
	.gallery-detail-head strong, .gallery-detail-head code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.gallery-detail > small { overflow-wrap: anywhere; color: var(--muted-strong); font-size: 11px; }
	.gallery-detail-product { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-2); padding: 5px 6px; border-radius: 5px; color: var(--muted-strong); background: var(--surface-2); font-size: 11px; }
	.gallery-detail-product strong { color: var(--text); }
	.gallery-product-groups { display: grid; gap: 6px; }
	.gallery-product-group { display: grid; grid-template-columns: 74px minmax(0, 1fr); align-items: start; gap: 6px; }
	.gallery-product-group > span { padding-top: 4px; color: var(--muted); font-size: 10px; font-weight: 700; text-transform: uppercase; }
	.gallery-product-group > div { display: flex; flex-wrap: wrap; gap: 3px; min-width: 0; }
	.gallery-product-group button { min-height: 25px; border: 1px solid var(--panel-border); border-radius: 5px; padding: 2px 5px; color: var(--muted-strong); background: var(--surface-2); font-size: 10px; font-weight: 700; cursor: pointer; }
	.gallery-product-group button:hover { color: var(--text); border-color: var(--accent, #2563eb); }
	.gallery-product-group button.active { color: white; border-color: var(--accent, #2563eb); background: var(--accent, #2563eb); }
	.gallery-detail-image { display: block; overflow: hidden; border-radius: 5px; background: #111827; }
	.gallery-detail-image img { display: block; width: 100%; max-height: 328px; object-fit: contain; }
	.gallery-product-note { line-height: 1.35; }
	.gallery-detail-error { color: var(--danger, #dc2626) !important; }
	.gallery-pagination { display: flex; align-items: center; justify-content: space-between; min-width: 0; gap: var(--space-2); }
	.gallery-pagination span { min-width: 0; overflow: hidden; color: var(--muted); text-align: center; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
	@media (max-width: 1100px) {
		.gallery-toolbar { grid-template-columns: minmax(160px, 1fr) repeat(2, minmax(110px, 0.8fr)); }
		.gallery-toolbar .button { grid-column: span 1; }
		.version-gallery-content { grid-template-columns: 1fr; }
		.gallery-detail { max-width: 520px; }
	}
	@media (max-width: 720px) {
		.gallery-toolbar { grid-template-columns: 1fr 1fr; }
		.gallery-search { grid-column: 1 / -1; }
		.gallery-toolbar .button { grid-column: 1 / -1; }
		.gallery-visualization-picker { grid-template-columns: 1fr; }
		.version-gallery-grid { grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); }
	}

</style>
