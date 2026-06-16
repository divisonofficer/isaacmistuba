<script lang="ts">
	import JobTimeline from '$lib/datasets/JobTimeline.svelte';
	import { compactDetail, formatJobRunDuration, jobStatusClass, normalizeJobStatus } from '$lib/datasets/batchHelpers';

	interface Props {
		job: any;
		log: string[];
		loading: boolean;
		imageUrl: string;
		onClose: () => void;
		onRefreshLog: () => void;
		onRetryJob: (job: any) => void;
		onCancelJob: (job: any) => void;
	}

	let { job, log, loading, imageUrl, onClose, onRefreshLog, onRetryJob, onCancelJob }: Props = $props();
	let rawOpen = $state(false);
	const status = $derived(normalizeJobStatus(job));
	const textureAudit = $derived(job?.status?.extras?.texture_audit);
	const textureProfile = $derived(job?.status?.extras?.texture_profile ?? textureAudit?.texture_profile);
	const duration = $derived(formatJobRunDuration(job));
	const errorText = $derived(String(job?.status?.error ?? job?.error ?? ''));

	function retryCurrent() {
		if (!job?.job_id) return;
		onRetryJob(job);
	}

	function cancelCurrent() {
		if (!job?.job_id) return;
		onCancelJob(job);
	}

	async function copyJobId() {
		if (!job?.job_id || typeof navigator === 'undefined') return;
		await navigator.clipboard?.writeText(job.job_id);
	}
</script>

{#if job}
	<aside class="job-drawer" aria-label="Job detail">
		<div class="drawer-head">
			<div>
				<strong title={job.job_id}>{String(job.job_id ?? '').slice(-18)}</strong>
				<div class="drawer-sub">
					<span>{job.preview_id ?? job.node_id ?? 'custom'}</span>
					{#if job.heading_id}<span>· {job.heading_id}</span>{/if}
					<span>· {job.modality ?? 'rgb'} / {job.sensor_id ?? 'sensor'}</span>
				</div>
			</div>
			<button class="icon-btn" onclick={onClose} aria-label="Close job detail">x</button>
		</div>

		<div class="drawer-status">
			<span class={`js-chip ${jobStatusClass(job)}`}>{status}</span>
			<span>{job?.status?.progress_stage ?? '-'}</span>
		</div>

		<JobTimeline {job} />

		<div class="meta-grid">
			<div><span>GPU</span><strong>{job?.status?.extras?.target_gpu_index ?? job?.worker_gpu_index ?? '-'}</strong></div>
			<div><span>Cache</span><strong>{job?.status?.extras?.scene_cache_hit ? 'Hit' : 'Miss/unknown'}</strong></div>
			<div><span>Texture</span><strong>{textureProfile ? `max${textureProfile}` : '-'}</strong></div>
			<div><span>Duration</span><strong>{duration || '-'}</strong></div>
			{#if textureAudit?.texture_refs}
				<div class="wide"><span>Texture refs</span><strong>{textureAudit.downsampled_refs ?? 0}/{textureAudit.texture_refs} downsampled</strong></div>
			{/if}
		</div>

		{#if errorText}
			<div class="error-box">{compactDetail(errorText)}</div>
		{/if}

		{#if imageUrl}
			<img class="job-preview-img" src={imageUrl} alt="selected job preview" loading="lazy" />
		{/if}

		<div class="drawer-actions">
			<button class="button button-primary" disabled={status !== 'failed'} onclick={retryCurrent}>Retry</button>
			<button class="button button-subtle" disabled={status !== 'running' && status !== 'queued'} onclick={cancelCurrent}>Cancel</button>
			<button class="button button-subtle" onclick={onRefreshLog}>Refresh log</button>
			<button class="button button-subtle" onclick={copyJobId}>Copy id</button>
		</div>

		<details bind:open={rawOpen}>
			<summary>Raw log ({log.length} lines)</summary>
			{#if loading}
				<div class="job-log-row muted">Loading logs...</div>
			{:else if log.length === 0}
				<div class="job-log-row muted">No log entries.</div>
			{:else}
				<div class="job-log-list">
					{#each log.slice(-120) as line}
						<div class="job-log-row">{line}</div>
					{/each}
				</div>
			{/if}
		</details>
	</aside>
{/if}

<style>
	.job-drawer {
		position: absolute;
		top: calc(44px + var(--space-3));
		right: var(--space-3);
		bottom: var(--space-3);
		z-index: 15;
		width: clamp(360px, 36vw, 520px);
		display: grid;
		grid-template-rows: auto auto auto auto auto auto auto minmax(0, 1fr);
		gap: var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		box-shadow: 0 14px 40px rgba(15, 23, 42, 0.18);
		overflow: auto;
	}
	.drawer-head,
	.drawer-status,
	.drawer-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.drawer-actions .button { flex: 1 1 92px; min-width: 0; }
	.drawer-sub { margin-top: 3px; color: var(--muted-strong); font-size: var(--font-size-xs); }
	.icon-btn {
		width: 28px;
		height: 28px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-2);
		cursor: pointer;
	}
	.js-chip { padding: 2px 7px; border-radius: 99px; font-size: 10px; font-weight: 700; }
	.js-done { background: #d1fae5; color: #065f46; }
	.js-running { background: #dbeafe; color: #1e40af; }
	.js-queued { background: #fef3c7; color: #92400e; }
	.js-failed { background: #fee2e2; color: #991b1b; }
	.js-cancelled { background: #e2e8f0; color: #475569; }
	.meta-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); }
	.meta-grid div { border: 1px solid var(--panel-border); border-radius: var(--radius-sm); padding: var(--space-2); min-width: 0; }
	.meta-grid .wide { grid-column: 1 / -1; }
	.meta-grid span { display: block; color: var(--muted); font-size: 10px; }
	.meta-grid strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--font-size-xs); }
	.error-box { border: 1px solid #fecaca; background: #fef2f2; color: #991b1b; border-radius: var(--radius-sm); padding: var(--space-2); font-size: var(--font-size-xs); }
	.job-preview-img { width: 100%; border-radius: var(--radius-sm); border: 1px solid var(--panel-border); object-fit: cover; aspect-ratio: 16 / 9; background: var(--surface-2); }
	details { min-height: 0; }
	summary { cursor: pointer; color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: 700; }
	.job-log-list { margin-top: var(--space-2); display: grid; gap: 2px; max-height: 180px; overflow: auto; background: var(--surface-2); border-radius: var(--radius-sm); padding: var(--space-2); }
	.job-log-row { font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); font-size: 10px; color: var(--muted-strong); white-space: pre-wrap; overflow-wrap: anywhere; }
	.muted { color: var(--muted); }
	:global(.job-drawer .stage-timeline) {
		grid-template-columns: repeat(auto-fit, minmax(42px, 1fr));
	}
	:global(.job-drawer .stage-step) {
		font-size: 9px;
	}
	@media (max-width: 700px) {
		.job-drawer {
			left: var(--space-2);
			right: var(--space-2);
			top: calc(44px + var(--space-2));
			width: auto;
		}
	}
</style>
