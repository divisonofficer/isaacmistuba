<script lang="ts">
	import type { KeyValueItem } from './types';

	interface Props {
		items: KeyValueItem[];
		layout?: 'rows' | 'columns';
		size?: 'sm' | 'md';
		dense?: boolean;
	}

	let {
		items,
		layout = 'rows',
		size = 'md',
		dense = false
	}: Props = $props();
</script>

<dl
	class="kv kv-{layout} kv-{size}"
	class:kv-dense={dense}
>
	{#each items as item, i (i)}
		<div class="kv-row">
			<dt class="kv-key">{item.key}</dt>
			<dd
				class="kv-value"
				class:kv-mono={item.mono}
				data-tone={item.tone}
			>{item.value}</dd>
		</div>
	{/each}
</dl>

<style>
	.kv { margin: 0; padding: 0; }
	.kv-rows .kv-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-bottom: 1px dashed var(--panel-border);
	}
	.kv-rows .kv-row:last-child { border-bottom: none; }
	.kv-rows.kv-dense .kv-row { padding: var(--space-1) 0; }

	.kv-columns {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-2) var(--space-4);
	}
	.kv-columns .kv-row { display: contents; }

	.kv-key {
		font-size: var(--font-size-xs);
		color: var(--muted);
		font-weight: var(--font-weight-medium);
		margin: 0;
	}
	.kv-value {
		margin: 0;
		font-weight: var(--font-weight-semibold);
		color: var(--text);
		text-align: right;
	}
	.kv-columns .kv-value { text-align: left; }
	.kv-mono { font-family: var(--font-mono); font-size: var(--font-size-xs); }

	.kv-sm { font-size: var(--font-size-xs); }
	.kv-md { font-size: var(--font-size-sm); }

	.kv-value[data-tone='success'] { color: var(--success); }
	.kv-value[data-tone='warning'] { color: var(--warning); }
	.kv-value[data-tone='danger']  { color: var(--danger); }
	.kv-value[data-tone='active']  { color: var(--brand-strong); }
	.kv-value[data-tone='info']    { color: var(--cyan); }
	.kv-value[data-tone='neutral'] { color: var(--muted-strong); }
</style>
