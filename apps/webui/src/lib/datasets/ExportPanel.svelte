<script lang="ts">
	import ExportProgressCard from './ExportProgressCard.svelte';
	import ExportResultCard from './ExportResultCard.svelte';
	import type {
		ExportCameraInventoryItem,
		ExportJobStatus,
	} from '$lib/datasets/services/exportJobsService';
	import type { Capabilities } from '$lib/datasets/capabilityHelpers';

	let {
		caps,
		hasScene,
		hasMap,
		hasGraph,
		hasEpisodes,
		validationPassed,
		effectiveRenderReadiness,
		validationReport,
		graphPayloadSummary,
		splitCounts,
		allEpisodePaths,
		exportPath,
		loading,
		episodesCount,
		onlyCompleted = $bindable(true),
		currentSceneOnly = $bindable(true),
		includeThumbnails = $bindable(false),
		panoramaObservations = $bindable(true),
		exportProfile = $bindable<'compact_with_polar_extension' | 'single_lossless_core' | 'navigation_only' | 'png_stokes_core' | 'legacy_full'>('compact_with_polar_extension'),
		pngOnly = $bindable(true),
		includeBirdseye = $bindable(true),
		includeEpisodeBirdseye = $bindable(false),
		evalPerturbation = $bindable(false),
		uploadToGoogleDrive = $bindable(false),
		uploadDestinationSubpath = $bindable('dataset/opticalnav'),
		cameraInventory = [],
		selectedCameraIds = [],
		currentSceneId = '',
		exportableEpisodeCount = 0,
		exportSummary = null,
		activeExportJob = null,
		onValidate,
		onExport,
		onCancelExport,
		onResumeExport,
		onResetExport,
		onCameraSelectionChange,
	}: {
		caps: Capabilities;
		hasScene: boolean;
		hasMap: boolean;
		hasGraph: boolean;
		hasEpisodes: boolean;
		validationPassed: boolean;
		effectiveRenderReadiness: any;
		validationReport: any;
		graphPayloadSummary: any;
		splitCounts: any;
		allEpisodePaths: any[];
		exportPath: string;
		loading: boolean;
		episodesCount: number;
		onlyCompleted?: boolean;
		currentSceneOnly?: boolean;
		includeThumbnails?: boolean;
		panoramaObservations?: boolean;
		exportProfile?: 'compact_with_polar_extension' | 'single_lossless_core' | 'navigation_only' | 'png_stokes_core' | 'legacy_full';
		pngOnly?: boolean;
		includeBirdseye?: boolean;
		includeEpisodeBirdseye?: boolean;
		evalPerturbation?: boolean;
		uploadToGoogleDrive?: boolean;
		uploadDestinationSubpath?: string;
		cameraInventory?: ExportCameraInventoryItem[];
		selectedCameraIds?: string[];
		currentSceneId?: string;
		exportableEpisodeCount?: number;
		exportSummary?: any;
		activeExportJob?: ExportJobStatus | null;
		onValidate: () => void;
		onExport: () => void;
		onCancelExport?: () => void;
		onResumeExport?: () => void;
		onResetExport?: () => void;
		onCameraSelectionChange: (cameraIds: string[]) => void;
	} = $props();

	const jobInFlight = $derived(
		activeExportJob && (activeExportJob.status === 'queued' || activeExportJob.status === 'running')
	);
	const jobDone = $derived(
		activeExportJob && activeExportJob.status === 'succeeded'
	);
	const cameraSelectionEmpty = $derived(cameraInventory.length > 0 && selectedCameraIds.length === 0);

	function setAllCameras() {
		onCameraSelectionChange(cameraInventory.map((item) => item.sensor_id));
	}

	function setRgbCameras() {
		onCameraSelectionChange(
			cameraInventory
				.filter((item) => item.modalities.includes('rgb'))
				.map((item) => item.sensor_id)
		);
	}

	function toggleCamera(sensorId: string) {
		const next = selectedCameraIds.includes(sensorId)
			? selectedCameraIds.filter((id) => id !== sensorId)
			: [...selectedCameraIds, sensorId];
		onCameraSelectionChange(next);
	}
</script>

<div class="map-float-inspector export-panel">
	<div class="panel-label">Export Readiness</div>
	<div class="export-readiness-list">
		<div class="readiness-item" class:ok={hasScene}>
			<span class="readiness-dot"></span><span>Scene</span>
		</div>
		<div class="readiness-item" class:ok={hasMap}>
			<span class="readiness-dot"></span><span>Traversable grid</span>
		</div>
		<div class="readiness-item" class:ok={hasGraph}>
			<span class="readiness-dot"></span><span>Viewpoint graph</span>
		</div>
		<div class="readiness-item" class:ok={hasEpisodes}>
			<span class="readiness-dot"></span><span>Episodes ({episodesCount})</span>
		</div>
		<div class="readiness-item" class:ok={validationPassed}>
			<span class="readiness-dot"></span><span>Validated</span>
		</div>
	</div>
	{#if effectiveRenderReadiness?.errors?.length}
		<div class="readiness-errors">
			{#each effectiveRenderReadiness.errors.slice(0, 4) as item}
				<div>{item.label ?? item.key}: {item.message}</div>
			{/each}
		</div>
	{/if}
	{#if graphPayloadSummary}
		<div class="panel-label mt-2">Dataset Stats</div>
		<div class="export-stats">
			<div class="stat-row"><span>Viewpoints</span><span>{graphPayloadSummary.node_count}</span></div>
			<div class="stat-row"><span>Edges</span><span>{graphPayloadSummary.edge_count}</span></div>
			<div class="stat-row"><span>Hazard edges</span><span>{graphPayloadSummary.hazard_edge_count ?? 0}</span></div>
			<div class="stat-row"><span>Episodes</span><span>{episodesCount}</span></div>
			{#if splitCounts?.train != null}
				<div class="stat-row"><span>Train</span><span>{splitCounts.train}</span></div>
				<div class="stat-row"><span>Val seen</span><span>{splitCounts.val_seen ?? 0}</span></div>
				<div class="stat-row"><span>Val unseen</span><span>{splitCounts.val_unseen ?? 0}</span></div>
			{/if}
		</div>
	{/if}
	{#if allEpisodePaths.length > 0}
		<div class="export-path-legend mt-2">
			<span class="legend-swatch normal"></span><span>Normal path</span>
			<span class="legend-swatch hazard"></span><span>Hazard path ({allEpisodePaths.filter(p => p.hasHazard).length})</span>
		</div>
	{/if}
	{#if validationReport}
		<div class="export-validation" class:validation-ok={validationReport.ok !== false} class:validation-fail={validationReport.ok === false}>
			Validation: {validationReport.ok !== false ? 'passed' : 'failed'}
			{#if validationReport.errors?.length}<span class="val-errors"> · {validationReport.errors.length} error(s)</span>{/if}
			{#if validationReport.scene_ids?.length}
				<div class="val-scope">scope: {(validationReport.scene_ids as string[]).join(', ')}</div>
			{/if}
		</div>
		{#if validationReport.errors?.length}
			<div class="val-error-list">
				{#each (validationReport.errors as string[]).slice(0, 5) as err}
					<div class="val-error-row">{err}</div>
				{/each}
				{#if validationReport.errors.length > 5}
					<details class="val-error-more">
						<summary>+ {validationReport.errors.length - 5} more</summary>
						{#each (validationReport.errors as string[]).slice(5) as err}
							<div class="val-error-row">{err}</div>
						{/each}
					</details>
				{/if}
			</div>
		{/if}
	{/if}
	<button class="button button-subtle full mt-2" disabled={!caps.validate.enabled} title={caps.validate.reason} onclick={onValidate}>
		{loading ? 'Validating...' : 'Validate Dataset'}
	</button>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={currentSceneOnly} />
		<span>Current scene only</span>
	</label>
	<div class="export-filter-hint">
		Scope: {currentSceneOnly && currentSceneId ? currentSceneId : 'all scenes in project'}
	</div>
	<div class="export-camera-head">
		<div class="panel-label">Cameras</div>
		{#if cameraInventory.length > 0}
			<div class="export-camera-actions">
				<button type="button" class="button button-subtle" disabled={Boolean(jobInFlight)} onclick={setAllCameras}>Select all</button>
				<button type="button" class="button button-subtle" disabled={Boolean(jobInFlight)} onclick={setRgbCameras}>RGB only</button>
			</div>
		{/if}
	</div>
	{#if cameraInventory.length > 0}
		<div class="export-camera-list">
			{#each cameraInventory as camera (camera.sensor_id)}
				<label class="export-camera-row">
					<input
						type="checkbox"
						checked={selectedCameraIds.includes(camera.sensor_id)}
						disabled={Boolean(jobInFlight)}
						onchange={() => toggleCamera(camera.sensor_id)}
					/>
					<span class="export-camera-info">
						<strong>{camera.sensor_id}</strong>
						<span>{camera.observation_count} views</span>
					</span>
					<span class="export-camera-modalities">
						{camera.modalities.length ? camera.modalities.join(' · ') : 'other'}
					</span>
				</label>
			{/each}
		</div>
		<div class="export-filter-hint" class:camera-selection-error={cameraSelectionEmpty}>
			{cameraSelectionEmpty
				? 'Select at least one camera.'
				: `${selectedCameraIds.length} of ${cameraInventory.length} cameras selected`}
		</div>
	{:else}
		<div class="export-filter-hint">No rendered cameras found. Metadata-only export remains available.</div>
	{/if}
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={onlyCompleted} />
		<span>Only rendered episodes</span>
	</label>
	<div class="export-filter-hint">
		{#if onlyCompleted}
			Exporting <strong>{exportableEpisodeCount}</strong> of {episodesCount} episodes
		{:else}
			Exporting all {episodesCount} episodes (incomplete episodes will have missing observations)
		{/if}
	</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={panoramaObservations} />
		<span>Full panorama observations</span>
	</label>
	<div class="export-filter-hint">
		{#if panoramaObservations}
			각 waypoint 의 <strong>모든 heading</strong> (파노라마) 을 포함합니다.
		{:else}
			GT 경로가 지나는 <strong>(vp, heading)</strong> 만 포함 (slimmer bundle).
		{/if}
	</div>
	<div class="panel-label mt-2">Bundle profile</div>
	<label class="export-filter-row">
		<span>Output</span>
		<select bind:value={exportProfile} onchange={() => { if (exportProfile === 'legacy_full') pngOnly = false; }} disabled={Boolean(jobInFlight)}>
			<option value="compact_with_polar_extension">Core + Polar extension</option>
			<option value="single_lossless_core">Single lossless core</option>
			<option value="navigation_only">Navigation only</option>
			<option value="png_stokes_core">PNG + canonical Stokes</option>
			<option value="legacy_full">Legacy full</option>
		</select>
	</label>
	<div class="export-filter-hint">
		{#if exportProfile === 'compact_with_polar_extension'}
			Lossless RGB WebP + one polar thumbnail in Core ZIP. Float32 Stokes core is a separate optional ZIP.
		{:else if exportProfile === 'single_lossless_core'}
			One ZIP with lossless RGB WebP, polar thumbnails, and compact float32 Stokes core.
		{:else if exportProfile === 'navigation_only'}
			Smallest bundle: navigation RGB plus polar thumbnails; no Stokes raw payload.
		{:else if exportProfile === 'png_stokes_core'}
			Source camera PNGs and all polar PNGs, with canonical float32 Stokes core; RGB EXR/raw buffers are excluded.
		{:else}
			Compatibility export: source PNG and full legacy Stokes NPZ.
		{/if}
	</div>
	{#if exportProfile === 'legacy_full'}
		<label class="export-filter-row">
			<input type="checkbox" bind:checked={pngOnly} />
			<span>Exclude EXR/HDR</span>
		</label>
		<div class="export-filter-hint">{pngOnly ? 'EXR/HDR excluded. Legacy Stokes NPZ remains included.' : 'EXR/HDR included - large and slow.'}</div>
	{:else}
		<div class="export-filter-hint">Profile estimate is recorded before collection; PNG-only does not control Polar raw in compact profiles.</div>
	{/if}
	<div class="panel-label mt-2">Delivery</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={uploadToGoogleDrive} disabled={Boolean(jobInFlight)} />
		<span>Upload to Google Drive</span>
	</label>
	{#if uploadToGoogleDrive}
		<label class="export-filter-row">
			<span>Drive folder</span>
			<input class="export-path-input" bind:value={uploadDestinationSubpath} disabled={Boolean(jobInFlight)} />
		</label>
		<div class="export-filter-hint">A new scene/job subfolder is created under this configured Google Drive path.</div>
	{/if}
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={includeBirdseye} />
		<span>Bird's-eye summary</span>
	</label>
	<div class="export-filter-hint">grid + viewpoint graph + episode 경로의 top-down 요약 PNG 를 포함합니다.</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={includeEpisodeBirdseye} />
		<span>Per-episode path maps</span>
	</label>
	<div class="export-filter-hint">episode별 경로 bird's-eye PNG (episodes_birdseye/) 를 추가로 생성합니다.</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={evalPerturbation} />
		<span>Eval perturbation pair</span>
	</label>
	<div class="export-filter-hint">거울/유리 변형 렌더(observations_perturbed/)를 동봉해 base↔perturbed 페어 eval 번들을 만듭니다.</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={includeThumbnails} />
		<span>Include episode thumbnails</span>
	</label>
	<div class="export-filter-hint">
		{#if includeThumbnails}
			thumbnails/&lt;episode&gt;/ 폴더에 GT 경로의 RGB 만 순서대로 모아 저장됩니다.
		{:else}
			썸네일 디렉터리 생성하지 않습니다.
		{/if}
	</div>

	{#if jobInFlight}
		<ExportProgressCard job={activeExportJob!} onCancel={onCancelExport} />
	{:else if jobDone}
		<ExportResultCard job={activeExportJob!} onReset={onResetExport} />
	{:else}
		<button
			class="button button-primary full"
			disabled={!caps.export.enabled || cameraSelectionEmpty}
			title={cameraSelectionEmpty ? 'Select at least one camera.' : caps.export.reason}
			onclick={onExport}
		>
			{loading ? 'Submitting…' : 'Export Dataset'}
		</button>
	{#if activeExportJob && (activeExportJob.status === 'failed' || activeExportJob.status === 'cancelled' || activeExportJob.status === 'interrupted')}
		<div class="export-summary" class:val-fail={activeExportJob.status === 'failed'}>
			{activeExportJob.status === 'failed'
				? `Failed: ${activeExportJob.error ?? 'unknown error'}`
				: activeExportJob.status === 'interrupted'
					? 'Interrupted. Local archives and verified remote files are retained.'
					: 'Cancelled.'}
				{#if activeExportJob.resume_available && onResumeExport}
					<button type="button" class="button button-primary" onclick={onResumeExport}>Resume upload/export</button>
				{/if}
				<button type="button" class="button button-subtle" onclick={onResetExport}>Dismiss</button>
			</div>
		{/if}
	{/if}
	{#if exportPath}
		<div class="export-path-display">
			<span class="chip-ok">Exported</span>
			<span class="export-path-text" title={exportPath}>{exportPath.split('/').slice(-2).join('/')}</span>
		</div>
	{/if}
</div>

<style>
	/* Floating right inspector */
	.map-float-inspector {
			position: absolute;
			top: 54px;
			right: 10px;
			width: 260px;
			max-height: calc(100% - 80px);
			overflow-y: auto;
			background: rgba(255, 255, 255, 0.95);
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-md);
			padding: var(--space-3);
			backdrop-filter: blur(10px);
			z-index: 10;
			box-shadow: 0 2px 8px rgba(0,0,0,0.1);
			display: flex;
			flex-direction: column;
			gap: var(--space-2);
		}

	.map-float-inspector.material-panel {
			width: min(720px, calc(100% - 24px));
		}

	/* Export mode panel */
	.export-panel .full { width: 100%; }

	.export-readiness-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }

	.readiness-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); }

	.readiness-item.ok { color: #166534; }

	.readiness-dot { width: 8px; height: 8px; border-radius: 50%; background: #cbd5e1; flex-shrink: 0; }

	.readiness-item.ok .readiness-dot { background: #22c55e; }

	.readiness-errors { margin-top: 4px; display: flex; flex-direction: column; gap: 3px; }

	.export-stats { display: flex; flex-direction: column; gap: 2px; margin: 4px 0 8px; }

	.stat-row { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); padding: 1px 0; }

	.stat-row span:last-child { font-weight: 600; color: var(--text-primary); }

	.export-path-legend { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-muted); flex-wrap: wrap; }

	.legend-swatch { width: 20px; height: 3px; border-radius: 2px; flex-shrink: 0; }

	.legend-swatch.normal { background: var(--muted); }

	.legend-swatch.hazard { background: #fca5a5; }

	.export-validation { font-size: 11px; padding: 4px 8px; border-radius: 4px; margin-top: 6px; }

	.export-validation.validation-ok { background: #dcfce7; color: #166534; }

	.export-validation.validation-fail { background: #fee2e2; color: #991b1b; }

	.val-errors { opacity: 0.8; }

	.export-path-display { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; overflow: hidden; }

	.export-path-text { color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

	.export-filter-row { display: flex; align-items: center; gap: 6px; margin-top: 8px; font-size: 12px; color: var(--text-primary); cursor: pointer; }
	.export-filter-row input { margin: 0; }
	.export-filter-hint { font-size: 11px; color: var(--text-muted); margin: 2px 0 6px; }
	.export-path-input { min-width: 0; flex: 1; font: inherit; font-size: 11px; padding: 3px 5px; }
	.export-camera-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 6px; }
	.export-camera-actions { display: flex; gap: 4px; }
	.export-camera-actions .button { min-height: 24px; padding: 2px 7px; font-size: 10px; }
	.export-camera-list { display: flex; flex-direction: column; border-top: 1px solid var(--panel-border); }
	.export-camera-row { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; align-items: center; gap: 6px; min-height: 38px; border-bottom: 1px solid var(--panel-border); cursor: pointer; }
	.export-camera-row input { margin: 0; }
	.export-camera-info { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
	.export-camera-info strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
	.export-camera-info span { color: var(--text-muted); font-size: 10px; }
	.export-camera-modalities { max-width: 86px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); font-size: 9px; text-align: right; }
	.camera-selection-error { color: var(--danger, #b91c1c); font-weight: 600; }
	.export-summary { font-size: 11px; color: var(--text-muted); margin-top: 6px; padding: 4px 8px; background: var(--hover-bg, #f5f5f7); border-radius: 4px; }
	.val-scope { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
	.val-error-list { margin-top: 4px; display: flex; flex-direction: column; gap: 2px; }
	.val-error-row { font-size: 11px; color: #991b1b; background: #fef2f2; border-left: 2px solid #fca5a5; padding: 3px 6px; border-radius: 3px; word-break: break-word; }
	.val-error-more { margin-top: 2px; font-size: 11px; }
	.val-error-more summary { cursor: pointer; color: var(--text-muted); }
	.val-error-more > .val-error-row { margin-top: 2px; }

	.map-float-inspector,
		.map-float-settings {
			display: none;
		}

	/* Inspector inside floating panel */
	.map-float-inspector .inspector-head { display: flex; justify-content: space-between; align-items: flex-start; }

	.map-float-inspector .inspector-id { font-size: var(--font-size-xs); color: var(--text-muted); font-family: monospace; }

	.map-float-inspector .inspector-badges { display: flex; gap: 4px; flex-wrap: wrap; }

	.map-float-inspector .inspector-badges span {
			padding: 1px 6px;
			background: var(--hover-bg);
			border-radius: 99px;
			font-size: 10px;
			color: var(--text-muted);
		}

	.map-float-inspector .inspector-section { border-top: 1px solid var(--panel-border); padding-top: var(--space-2); }

	.map-float-inspector .geometry-advanced summary {
			cursor: pointer;
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
			font-weight: 800;
		}

	.map-float-inspector .flag-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; font-size: var(--font-size-xs); }

	.map-float-inspector .preset-row { display: flex; gap: 4px; flex-wrap: wrap; }

	.map-float-inspector .rotation-row { margin-top: 2px; }

	.map-float-inspector .snap-controls { margin-top: 4px; gap: 4px; }

	.map-float-inspector .geometry-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }

	.map-float-inspector button.full { width: 100%; }

	.map-float-inspector button.danger { color: var(--danger); border-color: #fca5a5; }

	.map-float-inspector button.danger:hover { background: var(--danger-soft); }
</style>
