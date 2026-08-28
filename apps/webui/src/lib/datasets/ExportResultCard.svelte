<script lang="ts">
	import type { ExportJobStatus } from '$lib/datasets/services/exportJobsService';

	let {
		job,
		onReset,
	}: {
		job: ExportJobStatus;
		onReset?: () => void;
	} = $props();

	const summary = $derived(job?.summary ?? {});
	const archives = $derived(Array.isArray(summary.archives) ? summary.archives : []);
	const upload = $derived(summary.upload ?? null);
	const remoteDir = $derived(upload?.remote_dir ?? job?.remote_dir ?? '');
	const uploadCount = $derived(Object.keys(upload?.files ?? job?.uploads ?? {}).length);

	function fmtBytes(b: number | undefined): string {
		if (!b || b < 0) return '0 B';
		if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
		if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
		return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
	}
</script>

<div class="export-result-card">
	<div class="er-head">
		<div class="er-title">✓ Export complete</div>
		<div class="er-sub">{summary.scene_id ?? job.scene_id ?? '—'}</div>
	</div>
	<div class="er-stats">
		<div><span class="er-num">{summary.episodes_exported ?? 0}</span><span class="er-label">episodes exported</span></div>
		<div><span class="er-num">{summary.episodes_skipped ?? 0}</span><span class="er-label">skipped</span></div>
		<div><span class="er-num">{summary.files_packaged ?? 0}</span><span class="er-label">files</span></div>
		<div><span class="er-num">{fmtBytes(summary.zip_size_bytes)}</span><span class="er-label">zip size</span></div>
	</div>
	{#if summary.export_profile}
		<div class="er-sub">profile: {summary.export_profile}</div>
	{/if}
	{#if remoteDir}
		<div class="er-sub">☁ Google Drive: {remoteDir}</div>
		<div class="er-sub">{uploadCount} files remote-verified</div>
	{/if}
	<div class="er-actions">
		{#if archives().length}
			{#each archives() as archive}
				<a class="button button-primary" href={archive.download_url} download>{archive.kind === 'polar_extension' ? 'Download Polar ZIP' : 'Download Core ZIP'} ({fmtBytes(archive.bytes)})</a>
			{/each}
		{:else if summary.download_url}
			<a class="button button-primary" href={summary.download_url} download>Download ZIP</a>
		{/if}
		{#if onReset}
			<button type="button" class="button button-subtle" onclick={onReset}>New export</button>
		{/if}
	</div>
	{#if archives().length}
		{#each archives() as archive}
			<div class="er-path" title={archive.zip_ref}>{archive.zip_ref}</div>
		{/each}
	{:else if summary.zip_ref}
		<div class="er-path" title={summary.zip_ref}>{summary.zip_ref}</div>
	{/if}
</div>

<style>
	.export-result-card { display: flex; flex-direction: column; gap: 10px; padding: 12px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; }
	.er-head { display: flex; flex-direction: column; gap: 2px; }
	.er-title { font-size: 14px; font-weight: 800; color: #15803d; }
	.er-sub { font-size: 11px; color: #166534; font-family: monospace; }
	.er-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
	.er-stats > div { display: flex; flex-direction: column; }
	.er-num { font-size: 18px; font-weight: 800; color: #166534; letter-spacing: -0.02em; }
	.er-label { font-size: 10px; color: #166534; text-transform: uppercase; letter-spacing: 0.06em; }
	.er-actions { display: flex; gap: 6px; flex-wrap: wrap; }
	.er-actions .button-primary { background: #16a34a; color: #fff; border-color: #15803d; }
	.er-path { font-size: 10px; color: #166534; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 4px 6px; background: rgba(22,101,52,0.07); border-radius: 4px; }
</style>
