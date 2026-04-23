<script lang="ts">
	import { onMount } from 'svelte';
	import { summary, retryJob } from '$lib/api';
	import { healthStore } from '$lib/stores/health';

	let data: Record<string, unknown> | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		try { data = await summary(); } catch {}
		loading = false;
	});

	async function retry(jobId: string) {
		try { await retryJob(jobId); location.reload(); } catch {}
	}

	function statusClass(s: string) {
		if (s === 'succeeded') return 'badge-succeeded';
		if (s === 'failed') return 'badge-failed';
		if (s === 'running') return 'badge-running';
		return 'badge-queued';
	}

	function ago(ts: string) {
		if (!ts) return '—';
		const s = Math.round((Date.now() - new Date(ts).getTime()) / 1000);
		if (s < 60) return `${s}s ago`;
		if (s < 3600) return `${Math.round(s / 60)}m ago`;
		return `${Math.round(s / 3600)}h ago`;
	}

	function asRecords(value: unknown): Record<string, string>[] {
		return Array.isArray(value) ? (value as Record<string, string>[]) : [];
	}
</script>

{#if loading}
	<div class="muted text-sm mt-4">Loading…</div>
{:else if data}
	{@const failedJobs = asRecords(data.failed_jobs)}
	{@const recentJobs = asRecords(data.recent_jobs)}
	<!-- Queue Health -->
	<div class="grid lg:grid-cols-4 gap-4 mt-4">
		{#each [
			{ label: 'Queued', val: data.queue_length ?? 0, cls: 'metric-card-queued' },
			{ label: 'Running', val: data.active_stage ? 1 : 0, cls: 'metric-card-running' },
			{ label: 'Failed', val: failedJobs.length, cls: 'metric-card-failed' },
			{ label: 'Scenes', val: (data.scenes as unknown[])?.length ?? 0, cls: 'metric-card-scenes' }
		] as card}
			<div class="panel subpanel metric-card {card.cls}">
				<div class="panel-label">{card.label}</div>
				<div class="metric">{card.val}</div>
			</div>
		{/each}
	</div>

	<!-- Session + Bridge strip -->
	<div class="grid lg:grid-cols-[1.1fr,1fr] gap-4 mt-4">
		<div class="panel">
			<div class="panel-header">
				<span class="panel-label">Current Session</span>
				<a href="/bridge" class="text-xs link">Bridge →</a>
			</div>
			{#if data.bridge_status}
				{@const bs = data.bridge_status as Record<string, unknown>}
				<div class="mt-3 stack-xs">
					<div class="text-sm"><span class="muted">Scene:</span> {bs.scene_id ?? '—'}</div>
					<div class="text-sm"><span class="muted">Stage:</span> {bs.current_stage ?? '—'}</div>
					<div class="text-sm"><span class="muted">Isaac:</span> {bs.isaac_connected ? '✅ connected' : '⬜ disconnected'}</div>
				</div>
			{:else}
				<p class="muted text-sm mt-3">No active session</p>
			{/if}
		</div>

		<div class="panel">
			<div class="panel-label">Quick Actions</div>
			<div class="playbook-grid mt-3">
				<a href="/jobs" class="playbook-tile">
					<div class="playbook-tile-icon">📋</div>
					<div class="playbook-tile-title">Job Queue</div>
				</a>
				<a href="/bridge" class="playbook-tile">
					<div class="playbook-tile-icon">🌉</div>
					<div class="playbook-tile-title">Bridge Monitor</div>
				</a>
				<a href="/scenes" class="playbook-tile">
					<div class="playbook-tile-icon">🎬</div>
					<div class="playbook-tile-title">Scenes</div>
				</a>
				<a href="/system" class="playbook-tile">
					<div class="playbook-tile-icon">🖥</div>
					<div class="playbook-tile-title">System Check</div>
				</a>
			</div>
		</div>
	</div>

	<!-- Recent failures -->
	{#if failedJobs.length}
		<div class="panel mt-4">
			<div class="panel-label">Recent Failures</div>
			<div class="table-wrap mt-3">
				<table class="table">
					<thead>
						<tr>
							<th>Job ID</th><th>Scene</th><th>Age</th><th></th>
						</tr>
					</thead>
					<tbody>
						{#each failedJobs as j}
							<tr>
								<td class="mono text-xs">{j.job_id?.slice(0, 20)}</td>
								<td class="text-sm">{j.scene_id ?? '—'}</td>
								<td class="text-sm muted">{ago(j.finished_at ?? j.created_at)}</td>
								<td>
									<button class="button button-subtle text-xs" onclick={() => retry(j.job_id)}>Retry</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

	<!-- Recent jobs -->
	{#if recentJobs.length}
		<div class="panel mt-4">
			<div class="panel-label">Recent Activity</div>
			<div class="table-wrap mt-3">
				<table class="table">
					<thead>
						<tr><th>Job ID</th><th>Status</th><th>Scene</th><th>Age</th></tr>
					</thead>
					<tbody>
						{#each recentJobs as j}
							<tr>
								<td class="mono text-xs">{j.job_id?.slice(0, 20)}</td>
								<td><span class="badge {statusClass(j.status)}">{j.status}</span></td>
								<td class="text-sm">{j.scene_id ?? '—'}</td>
								<td class="muted text-sm">{ago(j.finished_at ?? j.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
{:else}
	<div class="empty-state mt-6">Could not load summary. Is the daemon running?</div>
{/if}
