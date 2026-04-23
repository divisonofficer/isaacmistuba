<script lang="ts">
	import type { LogEntry } from './types';

	interface Props {
		entries: LogEntry[];
		maxHeight?: string;
		emptyMessage?: string;
		dense?: boolean;
		showSource?: boolean;
	}

	let {
		entries,
		maxHeight = '20rem',
		emptyMessage = 'No log entries',
		dense = false,
		showSource = true
	}: Props = $props();

	function formatTs(ts: string | Date): string {
		try {
			const d = ts instanceof Date ? ts : new Date(ts);
			return d.toLocaleTimeString(undefined, { hour12: false });
		} catch {
			return String(ts);
		}
	}
</script>

<div class="loglist" class:loglist-dense={dense} style:max-height={maxHeight}>
	{#if entries.length === 0}
		<p class="loglist-empty">{emptyMessage}</p>
	{:else}
		<ol class="loglist-items">
			{#each entries as entry, i (i)}
				<li class="loglist-row" data-level={entry.level}>
					<time class="loglist-ts mono">{formatTs(entry.ts)}</time>
					<span class="loglist-level">{entry.level}</span>
					<span class="loglist-msg">{entry.message}</span>
					{#if showSource && entry.source}
						<span class="loglist-source mono">{entry.source}</span>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
</div>

<style>
	.loglist {
		background: var(--panel);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		overflow-y: auto;
		font-size: var(--font-size-xs);
	}
	.loglist-empty {
		text-align: center;
		color: var(--muted);
		padding: var(--space-6);
		margin: 0;
	}
	.loglist-items {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.loglist-row {
		display: grid;
		grid-template-columns: auto auto 1fr auto;
		align-items: baseline;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-bottom: 1px solid var(--panel-border);
	}
	.loglist-dense .loglist-row { padding: var(--space-1) var(--space-3); }
	.loglist-row:last-child { border-bottom: none; }

	.loglist-ts {
		font-size: var(--font-size-2xs);
		color: var(--muted);
		flex-shrink: 0;
	}
	.loglist-level {
		font-size: var(--font-size-2xs);
		font-weight: var(--font-weight-bold);
		text-transform: uppercase;
		letter-spacing: var(--letter-spacing-wide);
		min-width: 2.75rem;
	}
	.loglist-row[data-level='info']  .loglist-level { color: var(--cyan); }
	.loglist-row[data-level='warn']  .loglist-level { color: var(--warning); }
	.loglist-row[data-level='error'] .loglist-level { color: var(--danger); }
	.loglist-row[data-level='debug'] .loglist-level { color: var(--muted); }
	.loglist-msg { color: var(--text); word-break: break-word; }
	.loglist-source { color: var(--muted); font-size: var(--font-size-2xs); }
</style>
