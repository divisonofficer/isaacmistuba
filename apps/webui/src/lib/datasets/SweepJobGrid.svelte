<script lang="ts">
	import { jobStageLabel, jobStatusClass } from '$lib/datasets/batchHelpers';

	interface Props {
		batchJobGrid: any;
		selectedBatchJobId: string;
		onSelectBatchJob: (job: any) => void;
		mode?: 'lanes' | 'compact';
	}

	let { batchJobGrid, selectedBatchJobId, onSelectBatchJob, mode = 'lanes' }: Props = $props();

	function nodeLabel(nodeId: string): string {
		return String(nodeId).replace(/^vp_0*/, 'vp_').replace(/^custom_/, 'c') || String(nodeId).slice(-4);
	}

	function runTime(value: string): string {
		if (!value) return '';
		const date = new Date(value);
		return Number.isNaN(date.getTime())
			? ''
			: date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	function jobTitle(job: any): string {
		if (!job) return 'No job';
		const sensors = Array.isArray(job.sensor_ids) ? job.sensor_ids.join(', ') : (job.sensor_id ?? 'sensor');
		return `${job.node_id ?? job.preview_id ?? ''} ${job.heading_id ?? ''} · ${job.scene_variant_key ?? ''} ${job.phase ?? ''} · ${sensors} · ${jobStageLabel(job)}`;
	}

	function cellTitle(cell: any): string {
		if (!cell?.jobs?.length) return 'No jobs';
		const counts = new Map<string, number>();
		for (const job of cell.jobs) {
			const stage = jobStageLabel(job) || 'unknown';
			counts.set(stage, (counts.get(stage) ?? 0) + 1);
		}
		return `${cell.jobs.length} jobs · ${[...counts.entries()].map(([stage, count]) => `${stage} ${count}`).join(', ')}`;
	}

	function cellSelected(cell: any): boolean {
		return Boolean(cell?.jobs?.some((job: any) => job.job_id === selectedBatchJobId));
	}
</script>

{#if batchJobGrid.rows.length > 0}
	<div
		class="batch-job-grid"
		class:compact={mode === 'compact'}
		style={`--heading-count: ${Math.max(1, batchJobGrid.headings.length)}`}
	>
		<div class="bjg-header">
			<span class="bjg-row-label">{mode === 'lanes' ? 'Viewpoint / render lane' : 'Viewpoint / heading'}</span>
			{#each batchJobGrid.headings as heading}
				<span class="bjg-heading-label" title={heading}>{parseInt(String(heading).replace('h_', '')) || 0}</span>
			{/each}
		</div>

		{#each batchJobGrid.rows as row}
			{#if mode === 'lanes'}
				{#each row.lanes as entry, laneIndex}
					<div class="bjg-row lane-row" class:node-start={laneIndex === 0}>
						<div class="bjg-row-label lane-label" title={`${row.nid} · ${entry.lane.batchId}`}>
							{#if laneIndex === 0}<strong>{nodeLabel(row.nid)}</strong>{:else}<span class="node-spacer"></span>{/if}
							<span>{entry.lane.label}</span>
							{#if runTime(entry.lane.createdAt)}<small>{runTime(entry.lane.createdAt)}</small>{/if}
						</div>
						{#each entry.cells as job}
							<button
								type="button"
								class={`bjg-cell ${job ? jobStatusClass(job) : 'js-unknown'}${job?.job_id === selectedBatchJobId ? ' bjg-selected' : ''}`}
								title={jobTitle(job)}
								aria-label={jobTitle(job)}
								disabled={!job}
								onclick={() => { if (job) onSelectBatchJob(job); }}
							></button>
						{/each}
					</div>
				{/each}
			{:else}
				<div class="bjg-row compact-row">
					<strong class="bjg-row-label" title={row.nid}>{nodeLabel(row.nid)}</strong>
					{#each row.cells as cell}
						<button
							type="button"
							class={`bjg-cell compact-cell ${cell.representative ? jobStatusClass(cell.representative) : 'js-unknown'}${cellSelected(cell) ? ' bjg-selected' : ''}`}
							title={cellTitle(cell)}
							aria-label={cellTitle(cell)}
							disabled={!cell.representative}
							onclick={() => { if (cell.representative) onSelectBatchJob(cell.representative); }}
						>
							{#if cell.jobs.length > 1}<span class="job-count">{cell.jobs.length}</span>{/if}
						</button>
					{/each}
				</div>
			{/if}
		{/each}
	</div>
{:else}
	<div class="empty">No graph sweep jobs match these filters.</div>
{/if}

<style>
	.batch-job-grid {
		display: grid;
		align-content: start;
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
		grid-template-columns: 248px repeat(var(--heading-count, 12), 24px);
		gap: 3px;
		align-items: center;
		min-width: max-content;
	}
	.batch-job-grid.compact .bjg-header,
	.batch-job-grid.compact .bjg-row {
		grid-template-columns: 132px repeat(var(--heading-count, 12), 24px);
	}
	.bjg-header {
		position: sticky;
		top: 0;
		z-index: 2;
		min-height: 22px;
		background: var(--surface-1);
	}
	.bjg-row {
		min-height: 24px;
	}
	.lane-row.node-start {
		margin-top: 4px;
		padding-top: 4px;
		border-top: 1px solid var(--panel-border);
	}
	.bjg-heading-label,
	.bjg-row-label {
		min-width: 0;
		overflow: hidden;
		color: var(--muted-strong);
		font-size: 10px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.lane-label {
		display: grid;
		grid-template-columns: 52px minmax(0, 1fr) 34px;
		gap: 6px;
		align-items: center;
	}
	.lane-label strong,
	.compact-row > strong {
		color: var(--text);
		font-size: 11px;
	}
	.lane-label span {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.lane-label small {
		color: var(--muted);
		font-size: 9px;
		text-align: right;
	}
	.node-spacer {
		display: block;
	}
	.bjg-cell {
		position: relative;
		width: 20px;
		height: 20px;
		padding: 0;
		border: 1px solid var(--panel-border);
		border-radius: 50%;
		background: var(--surface-3, #e5e7eb);
		cursor: pointer;
	}
	.compact-cell {
		border-radius: 5px;
	}
	.bjg-cell:disabled {
		cursor: default;
		opacity: 0.28;
	}
	.bjg-selected {
		outline: 2px solid var(--accent, #2f6fed);
		outline-offset: 1px;
	}
	.job-count {
		position: absolute;
		right: -5px;
		top: -6px;
		display: grid;
		place-items: center;
		min-width: 13px;
		height: 13px;
		padding: 0 2px;
		border: 1px solid var(--surface-1);
		border-radius: 7px;
		background: var(--text);
		color: var(--surface-1);
		font-size: 8px;
		font-weight: 700;
		line-height: 1;
	}
	.js-done { background: #22c55e; }
	.js-running { background: #3b82f6; }
	.js-queued { background: #facc15; }
	.js-failed { background: #ef4444; }
	.js-cancelled { background: #94a3b8; }
	.js-unknown { background: #cbd5e1; }
	.empty {
		padding: var(--space-4);
		border: 1px dashed var(--panel-border);
		border-radius: var(--radius-md);
		color: var(--muted);
	}
	@media (max-width: 760px) {
		.bjg-header,
		.bjg-row {
			grid-template-columns: 210px repeat(var(--heading-count, 12), 24px);
		}
	}
</style>
