<script lang="ts">
	import { buildRenderSummary } from '$lib/datasets/batchHelpers';

	interface Props {
		activeBatch: any;
		renderMode: string;
		health: any;
		loading: boolean;
		onRefreshBatch: () => void;
		onCancelStaleBatchJobs: () => void;
		onRetryFailedJobs: () => void;
	}

	let { activeBatch, renderMode, health, loading, onRefreshBatch, onCancelStaleBatchJobs, onRetryFailedJobs }: Props = $props();
	const summary = $derived(buildRenderSummary(activeBatch, health, renderMode));
	const failed = $derived(summary.counts.failed ?? 0);
	const active = $derived((summary.counts.running ?? 0) + (summary.counts.queued ?? 0));
	const execution = $derived(summary.execution ?? { queued: summary.counts.queued ?? 0, prefetched: 0, workerRunning: summary.counts.running ?? 0 });
	const gpuLabel = $derived(
		summary.gpus.length
			? summary.gpus.map((gpu: any) => `GPU${gpu.index} ${gpu.util_pct ?? 0}% ${gpu.mem_used_mb ?? 0}/${gpu.mem_total_mb ?? 0}MB`).join(' · ')
			: 'GPU status unavailable'
	);
</script>

<section class="render-summary">
	<div class="summary-main">
		<div class="summary-ring" aria-label={`${summary.percent}% complete`}>
			<span>{summary.percent}%</span>
		</div>
		<div class="summary-text">
			<div class="summary-title">
				<strong>{summary.label}</strong>
				{#if summary.batch_id}<span title={summary.batch_id}>· {String(summary.batch_id).slice(-18)}</span>{/if}
			</div>
			<div class="summary-progress">
				<span>{summary.complete} / {summary.total} complete</span>
				<span>{execution.workerRunning} worker running</span>
				{#if execution.prefetched > 0}<span>{execution.prefetched} prefetched</span>{/if}
				<span>{execution.queued} queued</span>
				{#if failed > 0}<span class="danger">{failed} failed</span>{/if}
			</div>
			<div class="progress-track">
				<div class="progress-fill" style={`width: ${summary.percent}%`}></div>
			</div>
		</div>
	</div>
	<div class="summary-resources">
		<div><span>Stage</span><strong>{summary.activeStage || 'idle'}</strong></div>
		<div><span>Queue</span><strong>{summary.queueLength}</strong></div>
		<div><span>Cache</span><strong>{summary.cacheHits} hit</strong></div>
		<div><span>Texture</span><strong>{summary.textureProfile ? `max${summary.textureProfile}` : 'default'}</strong></div>
		<div class="gpu-row" title={gpuLabel}><span>GPU</span><strong>{gpuLabel}</strong></div>
	</div>
	<div class="summary-actions">
		<button class="button button-subtle" disabled={loading} onclick={onRefreshBatch}>Refresh</button>
		<button class="button button-subtle" disabled={active <= 0} onclick={onCancelStaleBatchJobs}>Cancel queued/running</button>
		<button class="button button-primary" disabled={failed <= 0 || loading} onclick={onRetryFailedJobs}>Retry failed</button>
	</div>
</section>

<style>
	.render-summary {
		display: grid;
		grid-template-columns: minmax(320px, 1.15fr) minmax(280px, 1fr) auto;
		gap: var(--space-3);
		align-items: stretch;
	}
	.summary-main,
	.summary-resources {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		padding: var(--space-3);
	}
	.summary-main { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: var(--space-3); align-items: center; }
	.summary-ring {
		width: 64px;
		height: 64px;
		border-radius: 999px;
		display: grid;
		place-items: center;
		border: 6px solid var(--accent, #2f6fed);
		color: var(--text);
		font-weight: 700;
	}
	.summary-title,
	.summary-progress {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}
	.summary-title { font-size: var(--font-size-sm); color: var(--text); }
	.summary-progress { margin: var(--space-1) 0 var(--space-2); font-size: var(--font-size-xs); color: var(--muted-strong); }
	.danger { color: var(--danger, #dc2626); font-weight: 700; }
	.progress-track { height: 8px; border-radius: 999px; background: var(--surface-3, #e5e7eb); overflow: hidden; }
	.progress-fill { height: 100%; background: var(--accent, #2f6fed); border-radius: inherit; }
	.summary-resources {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-2);
		font-size: var(--font-size-xs);
	}
	.summary-resources div { min-width: 0; }
	.summary-resources span { display: block; color: var(--muted); }
	.summary-resources strong { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
	.summary-resources .gpu-row { grid-column: 1 / -1; }
	.summary-actions { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; justify-content: flex-end; }
	@media (max-width: 1200px) {
		.render-summary { grid-template-columns: 1fr; }
		.summary-actions { justify-content: flex-start; }
	}
</style>
