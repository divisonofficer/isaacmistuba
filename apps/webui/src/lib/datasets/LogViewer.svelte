<script lang="ts">
	import { normalizeLogRows, type LogLevel, type LogScope } from '$lib/datasets/batchHelpers';

	interface Props {
		batchLogEntries: any[];
		selectedBatchJobLog: string[];
		activityLog: any[];
		selectedJobId: string;
	}

	let { batchLogEntries, selectedBatchJobLog, activityLog, selectedJobId }: Props = $props();
	let scope = $state<'all' | LogScope>('all');
	let level = $state<'all' | LogLevel>('all');
	let query = $state('');
	const rows = $derived(normalizeLogRows({ batchLogEntries, selectedBatchJobLog, activityLog, selectedJobId }));
	const filteredRows = $derived(rows.filter((row) => {
		if (scope !== 'all' && row.scope !== scope) return false;
		if (level !== 'all' && row.level !== level) return false;
		const q = query.trim().toLowerCase();
		if (q && !`${row.source} ${row.job_id} ${row.message}`.toLowerCase().includes(q)) return false;
		return true;
	}));
</script>

<section class="log-viewer">
	<div class="log-toolbar">
		<label>
			<span>Scope</span>
			<select bind:value={scope}>
				<option value="all">All</option>
				<option value="batch">Batch</option>
				<option value="selected">Selected Job</option>
				<option value="ui">UI</option>
			</select>
		</label>
		<label>
			<span>Level</span>
			<select bind:value={level}>
				<option value="all">All</option>
				<option value="error">Errors</option>
				<option value="warning">Warnings</option>
				<option value="info">Info</option>
			</select>
		</label>
		<label class="search">
			<span>Search</span>
			<input bind:value={query} placeholder="message, job_id..." />
		</label>
	</div>
	<div class="log-table">
		<div class="log-head">
			<span>Time</span>
			<span>Level</span>
			<span>Scope</span>
			<span>Source</span>
			<span>Message</span>
		</div>
		{#each filteredRows as row}
			<div class={`log-row level-${row.level}`}>
				<span>{row.ts || '-'}</span>
				<span>{row.level}</span>
				<span>{row.scope}</span>
				<span title={row.job_id || row.source}>{row.job_id ? row.job_id.slice(-12) : row.source}</span>
				<span>{row.message}</span>
			</div>
		{:else}
			<div class="empty">No log rows match the current filters.</div>
		{/each}
	</div>
</section>

<style>
	.log-viewer { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: var(--space-3); min-height: 0; }
	.log-toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: end;
	}
	label { display: grid; gap: 3px; font-size: 10px; color: var(--muted); }
	select,
	input {
		height: 30px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--text);
		padding: 0 var(--space-2);
	}
	.search { flex: 1 1 260px; }
	.log-table {
		min-height: 0;
		overflow: auto;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
	}
	.log-head,
	.log-row {
		display: grid;
		grid-template-columns: 82px 70px 82px 130px minmax(0, 1fr);
		gap: var(--space-2);
		align-items: start;
		padding: 6px var(--space-3);
		font-size: var(--font-size-xs);
	}
	.log-head {
		position: sticky;
		top: 0;
		background: var(--surface-2);
		color: var(--muted-strong);
		font-weight: 700;
		z-index: 1;
	}
	.log-row { border-top: 1px solid var(--panel-border); }
	.log-row span { min-width: 0; overflow-wrap: anywhere; }
	.level-error { color: #991b1b; }
	.level-warning { color: #92400e; }
	.empty { padding: var(--space-4); color: var(--muted); }
</style>
