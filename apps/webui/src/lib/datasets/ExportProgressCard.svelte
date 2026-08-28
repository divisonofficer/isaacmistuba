<script lang="ts">
	import type { ExportJobStatus } from '$lib/datasets/services/exportJobsService';

	let {
		job,
		onCancel,
	}: {
		job: ExportJobStatus;
		onCancel?: () => void;
	} = $props();

	const STAGES = [
		{ key: 'scope', label: 'Scope' },
		{ key: 'validate', label: 'Validate' },
		{ key: 'select_episodes', label: 'Episodes' },
		{ key: 'build_manifest', label: 'Manifest' },
		{ key: 'generate_thumbnails', label: 'Thumbnails' },
		{ key: 'collect_files', label: 'Resolve' },
		{ key: 'zip_files', label: 'Direct archive' },
		{ key: 'finalize', label: 'Finalize' },
		{ key: 'upload', label: 'Upload' },
		{ key: 'verify_remote', label: 'Verify' },
	];

	const currentStageIdx = $derived(STAGES.findIndex((s) => s.key === (job?.stage ?? '')));
	type EstimateGroup = {
		source_bytes?: number;
		core_estimated_bytes?: number;
		polar_extension_estimated_bytes?: number;
	};
	const sizeEstimate = $derived(job?.summary?.size_estimate ?? null);
	const estimateVariantRows = $derived(Object.entries(sizeEstimate?.breakdown?.by_variant ?? {}) as Array<[string, EstimateGroup]>);
	const estimateSensorRows = $derived(Object.entries(sizeEstimate?.breakdown?.by_sensor ?? {}) as Array<[string, EstimateGroup]>);
	const percent = $derived(() => {
		const t = job?.total ?? 0;
		const c = job?.current ?? 0;
		if (!t) return 0;
		return Math.min(100, Math.round((c / t) * 100));
	});
	const bytesPercent = $derived(() => {
		const t = job?.bytes_total ?? 0;
		const c = job?.bytes_current ?? 0;
		if (!t) return 0;
		return Math.min(100, Math.round((c / t) * 100));
	});

	function fmtBytes(b: number | undefined): string {
		if (!b || b < 0) return '0 B';
		if (b < 1024) return `${b} B`;
		if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
		if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
		return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
	}
</script>

<div class="export-progress-card">
	<div class="ep-head">
		<div>
			<div class="ep-title">Exporting <strong>{job.scene_id ?? '—'}</strong></div>
			<div class="ep-sub">Stage {currentStageIdx + 1} / {STAGES.length} · {job.stage_label ?? job.stage ?? '—'}</div>
		</div>
		{#if onCancel && (job.status === 'running' || job.status === 'queued')}
			<button type="button" class="button button-subtle" onclick={onCancel}>Cancel</button>
		{/if}
	</div>

	<div class="ep-stage-row">
		{#each STAGES as st, i}
			<div
				class="ep-pill"
				class:done={i < currentStageIdx}
				class:active={i === currentStageIdx}
			>
				{i + 1}. {st.label}
			</div>
		{/each}
	</div>

	{#if (job.total ?? 0) > 0}
		<div class="ep-bar-wrap">
			<div class="ep-bar" style="width:{percent()}%"></div>
		</div>
		<div class="ep-counters">
			<span><strong>{job.current ?? 0}</strong> / {job.total ?? 0} files</span>
			{#if (job.bytes_total ?? 0) > 0}
				<span>{fmtBytes(job.bytes_current)} / {fmtBytes(job.bytes_total)} ({bytesPercent()}%)</span>
			{/if}
		</div>
	{/if}

	{#if sizeEstimate}
		<div class="ep-message">
			Estimate: Core {fmtBytes(sizeEstimate.core_estimated_bytes)}
			{#if (sizeEstimate.polar_extension_estimated_bytes ?? 0) > 0}
				+ Polar {fmtBytes(sizeEstimate.polar_extension_estimated_bytes)}
			{/if}
			= {fmtBytes(sizeEstimate.single_estimated_bytes)}
			<span class="ep-legacy">(selected legacy inputs: {fmtBytes(sizeEstimate.legacy_selected_bytes ?? sizeEstimate.source_bytes)})</span>
		</div>
		{#if estimateVariantRows.length}
			<div class="ep-breakdown" aria-label="Export size estimate by variant">
				{#each estimateVariantRows as [variant, values]}
					<span>{variant}: {fmtBytes(values.source_bytes ?? 0)} → {fmtBytes((values.core_estimated_bytes ?? 0) + (values.polar_extension_estimated_bytes ?? 0))}</span>
				{/each}
			</div>
		{/if}
		{#if estimateSensorRows.length}
			<details class="ep-breakdown-details">
				<summary>Sensor/modality estimate</summary>
				<div class="ep-breakdown">
					{#each estimateSensorRows as [sensor, values]}
						<span>{sensor}: {fmtBytes(values.source_bytes ?? 0)} → {fmtBytes((values.core_estimated_bytes ?? 0) + (values.polar_extension_estimated_bytes ?? 0))}</span>
					{/each}
				</div>
			</details>
		{/if}
	{/if}

	{#if job.current_file}
		<div class="ep-current-file" title={job.current_file}>📄 {job.current_file}</div>
	{:else if job.message}
		<div class="ep-message">{job.message}</div>
	{/if}
	{#if job.remote_dir}
		<div class="ep-current-file" title={job.remote_dir}>☁ {job.remote_dir}</div>
	{/if}
	{#if job.upload_rate || job.upload_eta}
		<div class="ep-message">Google Drive: {job.upload_rate ?? 'transferring'}{job.upload_eta ? ` · ETA ${job.upload_eta}` : ''}</div>
	{/if}

	{#if job.status === 'cancelled'}
		<div class="ep-status cancelled">Cancelled.</div>
	{:else if job.status === 'failed'}
		<div class="ep-status failed">Failed: {job.error ?? 'unknown error'}</div>
	{/if}
</div>

<style>
	.export-progress-card { display: flex; flex-direction: column; gap: 8px; padding: 12px; background: var(--sub, #f8fafc); border: 1px solid var(--line, #e2e8f0); border-radius: 8px; min-width: 0; max-width: 100%; box-sizing: border-box; overflow: hidden; }
	.ep-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
	.ep-title { font-size: 13px; font-weight: 700; color: var(--text-primary, #1f2937); }
	.ep-sub { font-size: 11px; color: var(--text-muted, #64748b); margin-top: 2px; }
	.ep-stage-row { display: flex; flex-wrap: wrap; gap: 4px; min-width: 0; }
	.ep-pill { font-size: 10px; padding: 2px 6px; border-radius: 99px; background: rgba(0,0,0,0.04); color: var(--text-muted, #64748b); border: 1px solid var(--line, #e2e8f0); }
	.ep-pill.done { background: #d1fae5; color: #065f46; border-color: #a7f3d0; }
	.ep-pill.active { background: #dbeafe; color: #1e40af; border-color: #93c5fd; font-weight: 700; }
	.ep-bar-wrap { width: 100%; height: 8px; background: rgba(0,0,0,0.05); border-radius: 4px; overflow: hidden; }
	.ep-bar { height: 100%; background: linear-gradient(90deg, #3b82f6, #2563eb); transition: width 150ms ease; }
	.ep-counters { display: flex; gap: 12px; font-size: 11px; color: var(--text-muted, #64748b); flex-wrap: wrap; }
	.ep-current-file { font-size: 10px; color: var(--text-muted, #64748b); font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 4px 6px; background: rgba(0,0,0,0.04); border-radius: 4px; max-width: 100%; min-width: 0; box-sizing: border-box; }
	.ep-message { font-size: 11px; color: var(--text-muted, #64748b); font-style: italic; overflow-wrap: anywhere; }
	.ep-legacy { display: block; margin-top: 2px; font-size: 10px; }
	.ep-breakdown { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 10px; color: var(--text-muted, #64748b); }
	.ep-breakdown span { font-family: monospace; }
	.ep-breakdown-details { font-size: 10px; color: var(--text-muted, #64748b); }
	.ep-breakdown-details summary { cursor: pointer; margin-bottom: 4px; }
	.ep-status { font-size: 11px; padding: 6px 8px; border-radius: 4px; }
	.ep-status.cancelled { background: #fef3c7; color: #92400e; }
	.ep-status.failed { background: #fee2e2; color: #991b1b; }
</style>
