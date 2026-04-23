<script lang="ts" generics="Row extends Record<string, unknown>">
	import type { Snippet } from 'svelte';
	import type { DataTableColumn } from './types';

	interface Props {
		columns: DataTableColumn<Row>[];
		rows: Row[];
		rowKey?: (row: Row, index: number) => string | number;
		loading?: boolean;
		emptyMessage?: string;
		dense?: boolean;
		stickyHeader?: boolean;
		onRowClick?: (row: Row, index: number) => void;
		cell?: Snippet<[Row, DataTableColumn<Row>]>;
	}

	let {
		columns,
		rows,
		rowKey = (_r, i) => i,
		loading = false,
		emptyMessage = 'No data',
		dense = false,
		stickyHeader = false,
		onRowClick,
		cell
	}: Props = $props();
</script>

<div class="dt-wrap" class:dt-sticky={stickyHeader}>
	<table class="dt" class:dt-dense={dense}>
		<thead>
			<tr>
				{#each columns as col (col.key)}
					<th
						style:width={col.width}
						style:text-align={col.align ?? 'left'}
					>{col.label}</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#if loading}
				<tr><td class="dt-state" colspan={columns.length}>Loading…</td></tr>
			{:else if rows.length === 0}
				<tr><td class="dt-state" colspan={columns.length}>{emptyMessage}</td></tr>
			{:else}
				{#each rows as row, i (rowKey(row, i))}
					<tr
						class:dt-clickable={!!onRowClick}
						role={onRowClick ? 'button' : undefined}
						tabindex={onRowClick ? 0 : undefined}
						onclick={onRowClick ? () => onRowClick(row, i) : undefined}
						onkeydown={onRowClick
							? (e) => {
								if (e.key !== 'Enter' && e.key !== ' ') return;
								e.preventDefault();
								onRowClick(row, i);
							}
							: undefined}
					>
						{#each columns as col (col.key)}
							<td
								style:text-align={col.align ?? 'left'}
								class:dt-mono={col.mono}
							>
								{#if cell}
									{@render cell(row, col)}
								{:else}
									{row[col.key] ?? ''}
								{/if}
							</td>
						{/each}
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
</div>

<style>
	.dt-wrap {
		width: 100%;
		overflow-x: auto;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--panel);
	}
	.dt {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--font-size-sm);
		color: var(--text);
	}
	.dt thead th {
		font-size: var(--font-size-xs);
		font-weight: var(--font-weight-semibold);
		text-transform: uppercase;
		letter-spacing: var(--letter-spacing-wide);
		color: var(--muted-strong);
		background: var(--surface-2);
		padding: var(--space-2) var(--space-3);
		border-bottom: 1px solid var(--panel-border);
		white-space: nowrap;
	}
	.dt-sticky thead th {
		position: sticky;
		top: 0;
		z-index: var(--z-sticky);
	}
	.dt tbody td {
		padding: var(--space-3) var(--space-3);
		border-bottom: 1px solid var(--panel-border);
		vertical-align: middle;
	}
	.dt tbody tr:last-child td { border-bottom: none; }
	.dt-dense tbody td { padding: var(--space-2) var(--space-3); }
	.dt-mono { font-family: var(--font-mono); font-size: var(--font-size-xs); }
	.dt-state {
		text-align: center;
		color: var(--muted);
		padding: var(--space-6);
	}
	.dt-clickable { cursor: pointer; }
	.dt-clickable:hover td { background: var(--brand-soft); }
</style>
