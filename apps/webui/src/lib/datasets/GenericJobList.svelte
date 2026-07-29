<script lang="ts">
	import {
		buildGenericJobRows,
		jobPhaseLabel,
		jobSensorIds,
		jobSensorSummary,
		jobStageLabel,
		jobStatusClass,
		jobVariantLabel,
		normalizeJobStatus,
	} from '$lib/datasets/batchHelpers';

	interface Props {
		activeBatch: any;
		selectedBatchJobId: string;
		onSelectBatchJob: (job: any) => void;
	}

	let { activeBatch, selectedBatchJobId, onSelectBatchJob }: Props = $props();
	const rows = $derived(buildGenericJobRows(activeBatch));
</script>

{#if rows.length > 0}
	<div class="generic-list">
		<div class="generic-head">
			<span>Job</span>
			<span>Target</span>
			<span>Variant</span>
			<span>Phase / sensors</span>
			<span>Status</span>
			<span>Stage</span>
		</div>
		{#each rows as job}
			<button
				type="button"
				class={`generic-row ${job.job_id === selectedBatchJobId ? 'selected' : ''}`}
				onclick={() => onSelectBatchJob(job)}
			>
				<span title={job.job_id}>{String(job.job_id ?? '').slice(-16)}</span>
				<span>{job.preview_id ?? job.node_id ?? job.episode_id ?? 'custom'}</span>
				<span>{jobVariantLabel(job)}</span>
				<span title={jobSensorIds(job).join(', ')}>{jobPhaseLabel(job)} · {jobSensorSummary(job)}</span>
				<span class={`js-chip ${jobStatusClass(job)}`}>{normalizeJobStatus(job)}</span>
				<span>{jobStageLabel(job) || '-'}</span>
			</button>
		{/each}
	</div>
{:else}
	<div class="empty">No render jobs match these filters.</div>
{/if}

<style>
	.generic-list {
		display: grid;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		overflow: auto;
	}
	.generic-head,
	.generic-row {
		display: grid;
		grid-template-columns: minmax(140px, 1.1fr) minmax(105px, 0.8fr) 82px minmax(150px, 1fr) 88px minmax(110px, 0.8fr);
		gap: var(--space-2);
		align-items: center;
		min-width: 820px;
		padding: 7px var(--space-3);
		font-size: var(--font-size-xs);
	}
	.generic-head {
		position: sticky;
		top: 0;
		z-index: 1;
		background: var(--surface-2);
		color: var(--muted-strong);
		font-weight: 700;
	}
	.generic-row {
		border: 0;
		border-top: 1px solid var(--panel-border);
		background: transparent;
		color: var(--text);
		text-align: left;
		cursor: pointer;
	}
	.generic-row:hover,
	.generic-row.selected { background: var(--surface-2); }
	.generic-row span {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.js-chip {
		justify-self: start;
		padding: 1px 6px;
		border-radius: 99px;
		font-size: 10px;
		font-weight: 700;
	}
	.js-done { background: #d1fae5; color: #065f46; }
	.js-running { background: #dbeafe; color: #1e40af; }
	.js-queued { background: #fef3c7; color: #92400e; }
	.js-failed { background: #fee2e2; color: #991b1b; }
	.js-cancelled { background: #e2e8f0; color: #475569; }
	.js-unknown { background: #f1f5f9; color: var(--muted-strong); }
	.empty {
		padding: var(--space-4);
		border: 1px dashed var(--panel-border);
		border-radius: var(--radius-md);
		color: var(--muted);
	}
</style>
