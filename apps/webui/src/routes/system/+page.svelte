<script lang="ts">
	import { onMount } from 'svelte';
	import { health, isaacTelemetryStats } from '$lib/api';

	type HealthData = Record<string, unknown>;

	let h: HealthData | null = $state(null);
	let telemetry: Record<string, unknown> | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		try {
			[h, telemetry] = await Promise.all([
				health().catch(() => null),
				isaacTelemetryStats().catch(() => null)
			]);
		} catch {}
		loading = false;
	});

	function asRecords(value: unknown): Record<string, unknown>[] {
		return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
	}
</script>

{#if loading}
	<div class="muted text-sm mt-4">Loading system info…</div>
{:else}
	{@const envChecks = asRecords(h?.env_checks)}
	{@const stageStats = asRecords(telemetry?.stage_stats)}
	<div class="grid lg:grid-cols-3 gap-4 mt-4">
		<!-- Daemon health -->
		<div class="panel">
			<div class="panel-label">Daemon</div>
			{#if h}
				<div class="kv-list mt-3 text-sm">
					<div><span>Status</span><span class="hp-ok">running</span></div>
					<div><span>Worker</span><span>{h.worker_state}</span></div>
					<div><span>Queue</span><span>{h.queue_length} jobs</span></div>
					<div><span>Variant</span><span class="mono">{h.variant}</span></div>
					{#if h.active_stage}
						<div><span>Active Stage</span><span class="text-xs muted">{h.active_stage}</span></div>
					{/if}
				</div>
			{:else}
				<div class="empty-state mt-3">Health check failed</div>
			{/if}
		</div>

		<!-- Isaac connection -->
		<div class="panel">
			<div class="panel-label">Isaac Sim</div>
			{#if h}
				<div class="kv-list mt-3 text-sm">
					<div>
						<span>Status</span>
						<span class="{h.isaac_connected ? 'hp-ok' : 'hp-err'}">{h.isaac_connected ? 'connected' : 'disconnected'}</span>
					</div>
					{#if h.active_isaac_command}
						{@const cmd = h.active_isaac_command as Record<string, unknown>}
						<div><span>Active Command</span><span>{cmd.command_type}</span></div>
						<div><span>Command Status</span><span>{cmd.status}</span></div>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Env checks -->
		<div class="panel">
			<div class="panel-label">Environment</div>
			{#if envChecks.length}
				<div class="mt-3 stack-xs">
					{#each envChecks as check}
						{@const c = check as Record<string, string>}
						<div class="env-check env-check-{c.status === 'ok' ? 'ok' : c.status === 'warn' ? 'warn' : 'fail'}">
							<span class="env-check-icon">{c.status === 'ok' ? '✅' : c.status === 'warn' ? '⚠️' : '❌'}</span>
							<span class="env-check-label">{c.label}</span>
							{#if c.detail}<span class="env-check-detail">{c.detail}</span>{/if}
						</div>
					{/each}
				</div>
			{:else}
				<div class="empty-state mt-3">No env data</div>
			{/if}
		</div>
	</div>

	<!-- Telemetry stats -->
	{#if stageStats.length}
		<div class="panel mt-4">
			<div class="panel-label">Telemetry — Stage Stats</div>
			<div class="table-wrap mt-3">
				<table class="table">
					<thead><tr><th>Stage</th><th>Count</th><th>Success %</th><th>Avg Time</th></tr></thead>
					<tbody>
						{#each stageStats as r}
							<tr>
								<td class="text-sm">{r.stage}</td>
								<td class="text-sm">{r.count}</td>
								<td class="text-sm {Number(r.success_rate ?? 0) > 0.8 ? 'hp-ok' : 'hp-warn'}">
									{r.success_rate != null ? `${Math.round(Number(r.success_rate) * 100)}%` : '—'}
								</td>
								<td class="text-sm muted">{r.avg_elapsed_s != null ? `${Number(r.avg_elapsed_s).toFixed(1)}s` : '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
{/if}
