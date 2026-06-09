<script lang="ts">
	import { jobStageLabel, jobStatusClass } from '$lib/datasets/batchHelpers';

	interface Props {
		batchJobGrid: any;
		selectedBatchJobId: string;
		onSelectBatchJob: (job: any) => void;
	}

	let { batchJobGrid, selectedBatchJobId, onSelectBatchJob }: Props = $props();
</script>

{#if batchJobGrid.rows.length > 0}
	<div class="batch-job-grid" style={`--heading-count: ${Math.max(1, batchJobGrid.headings.length)}`} title="Each cell = one render job (viewpoint x heading)">
		{#if batchJobGrid.headings.length > 1}
			<div class="bjg-header">
				<span class="bjg-node-label">Viewpoint \ Heading</span>
				{#each batchJobGrid.headings as h}
					<span class="bjg-heading-label" title={h}>{parseInt(String(h).replace('h_','')) || 0}</span>
				{/each}
			</div>
		{/if}
		{#each batchJobGrid.rows as row}
			<div class="bjg-row">
				<span class="bjg-node-label" title={row.nid}>{String(row.nid).replace(/^vp_0*/, 'vp_').replace(/^custom_/, 'c') || String(row.nid).slice(-4)}</span>
				{#each row.cells as job}
					<button
						type="button"
						class={`bjg-cell ${job ? jobStatusClass(job) : 'js-unknown'}${job && job.job_id === selectedBatchJobId ? ' bjg-selected' : ''}`}
						title={job ? `${job.node_id ?? job.preview_id ?? ''} ${job.heading_id ?? ''} · ${jobStageLabel(job)}` : 'no job'}
						aria-label={job ? `${job.node_id ?? job.preview_id ?? ''} ${job.heading_id ?? ''} ${jobStageLabel(job)}` : 'no job'}
						disabled={!job}
						onclick={() => { if (job) onSelectBatchJob(job); }}
					></button>
				{/each}
			</div>
		{/each}
	</div>
{:else}
	<div class="empty">No graph sweep jobs in this batch.</div>
{/if}

<style>
	.batch-job-grid {
		display: grid;
		gap: 2px;
		overflow: auto;
		max-height: 100%;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		padding: var(--space-2);
	}
	.bjg-header,
	.bjg-row {
		display: grid;
		grid-template-columns: 120px repeat(var(--heading-count, 12), 24px);
		gap: 3px;
		align-items: center;
	}
	.bjg-heading-label,
	.bjg-node-label {
		font-size: 10px;
		color: var(--muted-strong);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.bjg-cell {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		border: 1px solid var(--panel-border);
		background: var(--surface-3, #e5e7eb);
		cursor: pointer;
	}
	.bjg-cell:disabled { cursor: default; opacity: 0.35; }
	.bjg-selected { outline: 2px solid var(--accent, #2f6fed); outline-offset: 1px; }
	.js-done { background: #22c55e; }
	.js-running { background: #3b82f6; }
	.js-queued { background: #facc15; }
	.js-failed { background: #ef4444; }
	.js-cancelled { background: #94a3b8; }
	.js-unknown { background: #cbd5e1; }
	.empty { color: var(--muted); padding: var(--space-4); border: 1px dashed var(--panel-border); border-radius: var(--radius-md); }
</style>
