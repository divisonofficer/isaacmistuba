<script lang="ts">
	import ExportProgressCard from './ExportProgressCard.svelte';
	import ExportResultCard from './ExportResultCard.svelte';
	import type { ExportJobStatus } from '$lib/datasets/services/exportJobsService';
	import type { Capabilities } from '$lib/datasets/capabilityHelpers';

	interface Props {
		caps: Capabilities;
		hasScene: boolean;
		hasMap: boolean;
		hasGraph: boolean;
		hasEpisodes: boolean;
		validationPassed: boolean;
		renderSceneSynced: boolean;
		effectiveRenderReadiness: any;
		currentScene: any;
		rigSensorOptions: any[];
		graphPayloadSummary: any;
		episodesCount: number;
		splitCounts: any;
		allEpisodePaths: any[];
		validationReport: any;
		exportPath: string;
		selectedProjectId: string;
		loading: boolean;
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
		currentSceneId?: string;
		exportableEpisodeCount?: number;
		exportSummary?: any;
		activeExportJob?: ExportJobStatus | null;
		onValidate: () => void;
		onExport: () => void;
		onCancelExport?: () => void;
		onResumeExport?: () => void;
		onResetExport?: () => void;
	}

	let {
		caps,
		hasScene, hasMap, hasGraph, hasEpisodes, validationPassed,
		renderSceneSynced, effectiveRenderReadiness, currentScene,
		rigSensorOptions, graphPayloadSummary, episodesCount, splitCounts,
		allEpisodePaths, validationReport, exportPath,
		selectedProjectId, loading,
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
		currentSceneId = '',
		exportableEpisodeCount = 0,
		exportSummary = null,
		activeExportJob = null,
		onValidate, onExport, onCancelExport, onResumeExport, onResetExport,
	}: Props = $props();

	const jobInFlight = $derived(
		activeExportJob && (activeExportJob.status === 'queued' || activeExportJob.status === 'running')
	);
	const jobDone = $derived(activeExportJob && activeExportJob.status === 'succeeded');
</script>

<section class="rail-section rail-tool-panel export-panel" style="min-width:0; overflow:hidden;">
	<div class="rail-title">Export Readiness</div>
	<div class="export-readiness-list">
		<div class="readiness-item" class:ok={hasScene}><span class="readiness-dot"></span><span>Scene</span></div>
		<div class="readiness-item" class:ok={renderSceneSynced}><span class="readiness-dot"></span><span>Render readiness {renderSceneSynced ? 'ready' : 'blocked'}</span></div>
		<div class="readiness-item" class:ok={Boolean(effectiveRenderReadiness?.xml_path || currentScene?.render_scene_xml_ref)}><span class="readiness-dot"></span><span>render_scene.xml</span></div>
		<div class="readiness-item" class:ok={Boolean(rigSensorOptions.some((s: any) => s.modality === 'rgb'))}><span class="readiness-dot"></span><span>RGB camera rig</span></div>
		<div class="readiness-item" class:ok={hasMap}><span class="readiness-dot"></span><span>Traversable grid</span></div>
		<div class="readiness-item" class:ok={hasGraph}><span class="readiness-dot"></span><span>Viewpoint graph</span></div>
		<div class="readiness-item" class:ok={hasEpisodes}><span class="readiness-dot"></span><span>Episodes ({episodesCount})</span></div>
		<div class="readiness-item" class:ok={validationPassed}><span class="readiness-dot"></span><span>Validated</span></div>
	</div>
	{#if graphPayloadSummary}
		<div class="rail-title mt-2">Dataset Stats</div>
		<div class="export-stats">
			<div class="stat-row"><span>Viewpoints</span><span>{graphPayloadSummary.node_count}</span></div>
			<div class="stat-row"><span>Edges</span><span>{graphPayloadSummary.edge_count}</span></div>
			<div class="stat-row"><span>Hazard edges</span><span>{graphPayloadSummary.hazard_edge_count ?? 0}</span></div>
			<div class="stat-row"><span>Episodes</span><span>{episodesCount}</span></div>
			{#if splitCounts.train != null}
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
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={onlyCompleted} />
		<span>Only rendered episodes</span>
	</label>
	<div class="export-filter-hint">
		{#if onlyCompleted}
			Exporting <strong>{exportableEpisodeCount}</strong> of {episodesCount} episodes
		{:else}
			Exporting all {episodesCount} episodes
		{/if}
	</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={panoramaObservations} />
		<span>Full panorama observations</span>
	</label>
	<div class="export-filter-hint">
		{#if panoramaObservations}
			모든 heading 포함
		{:else}
			GT (vp, heading) 만 (slim)
		{/if}
	</div>
	<div class="rail-title mt-2">Bundle profile</div>
	<label class="export-filter-row">
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
			Small Core ZIP plus a lossless float32 Stokes extension.
		{:else if exportProfile === 'single_lossless_core'}
			One ZIP contains compact lossless Stokes core data.
		{:else if exportProfile === 'navigation_only'}
			No Stokes raw payload; thumbnails only.
		{:else if exportProfile === 'png_stokes_core'}
			Source camera PNGs and all polar PNGs, with canonical float32 Stokes core; RGB EXR/raw buffers are excluded.
		{:else}
			Original PNG and legacy full Stokes NPZ compatibility mode.
		{/if}
	</div>
	{#if exportProfile === 'legacy_full'}
		<label class="export-filter-row">
			<input type="checkbox" bind:checked={pngOnly} />
			<span>Exclude EXR/HDR</span>
		</label>
	{:else}
		<div class="export-filter-hint">PNG-only does not decide Polar raw in compact profiles.</div>
	{/if}
	<div class="rail-title mt-2">Delivery</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={uploadToGoogleDrive} disabled={Boolean(jobInFlight)} />
		<span>Upload to Google Drive</span>
	</label>
	{#if uploadToGoogleDrive}
		<label class="export-filter-row">
			<span>Drive folder</span>
			<input class="export-path-input" bind:value={uploadDestinationSubpath} disabled={Boolean(jobInFlight)} />
		</label>
		<div class="export-filter-hint">A unique scene/job folder is created below this path.</div>
	{/if}
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={includeBirdseye} />
		<span>Bird's-eye summary</span>
	</label>
	<div class="export-filter-hint">top-down grid + graph + 경로 요약 PNG</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={includeEpisodeBirdseye} />
		<span>Per-episode path maps</span>
	</label>
	<div class="export-filter-hint">episode별 경로 bird's-eye PNG (episodes_birdseye/)</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={evalPerturbation} />
		<span>Eval perturbation pair</span>
	</label>
	<div class="export-filter-hint">거울/유리 변형 렌더(observations_perturbed/) 동봉 — base↔perturbed 페어 eval</div>
	<label class="export-filter-row">
		<input type="checkbox" bind:checked={includeThumbnails} />
		<span>Include episode thumbnails</span>
	</label>
	{#if jobInFlight}
		<ExportProgressCard job={activeExportJob!} onCancel={onCancelExport} />
	{:else if jobDone}
		<ExportResultCard job={activeExportJob!} onReset={onResetExport} />
	{:else}
		<button
			class="button button-primary full"
			disabled={!caps.export.enabled}
			title={caps.export.reason}
			onclick={onExport}
		>
			{loading ? 'Submitting…' : 'Export Dataset'}
		</button>
		{#if activeExportJob && (activeExportJob.status === 'failed' || activeExportJob.status === 'cancelled' || activeExportJob.status === 'interrupted')}
			<div class="export-summary-line">
				{activeExportJob.status === 'failed'
					? `Failed: ${activeExportJob.error ?? 'unknown'}`
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
</section>

<style>
	/* Export mode panel */
	.export-panel .full { width: 100%; }

	.export-readiness-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }

	.readiness-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); }

	.readiness-item.ok { color: #166534; }

	.readiness-dot { width: 8px; height: 8px; border-radius: 50%; background: #cbd5e1; flex-shrink: 0; }

	.readiness-item.ok .readiness-dot { background: #22c55e; }

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

	.export-filter-row { display: flex; align-items: center; gap: 6px; margin-top: 8px; font-size: 12px; cursor: pointer; }
	.export-filter-row input { margin: 0; }
	.export-filter-hint { font-size: 11px; color: var(--text-muted); margin: 2px 0 6px; }
	.export-path-input { min-width: 0; flex: 1; font: inherit; font-size: 11px; padding: 3px 5px; }
	.export-summary-line { font-size: 11px; color: var(--text-muted); margin-top: 6px; padding: 4px 8px; background: var(--hover-bg, rgba(0,0,0,0.04)); border-radius: 4px; }
	.val-scope { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
	.val-error-list { margin-top: 4px; display: flex; flex-direction: column; gap: 2px; }
	.val-error-row { font-size: 11px; color: #991b1b; background: #fef2f2; border-left: 2px solid #fca5a5; padding: 3px 6px; border-radius: 3px; word-break: break-word; }
	.val-error-more { margin-top: 2px; font-size: 11px; }
	.val-error-more summary { cursor: pointer; color: var(--text-muted); }
	.val-error-more > .val-error-row { margin-top: 2px; }
</style>
