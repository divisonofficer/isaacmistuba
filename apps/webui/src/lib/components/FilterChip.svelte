<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		selected?: boolean;
		disabled?: boolean;
		label?: string;
		ariaLabel?: string;
		onclick?: (event: MouseEvent) => void;
		children?: Snippet;
	}

	let { selected = false, disabled = false, label, ariaLabel, onclick, children }: Props = $props();
</script>

<button type="button" class="filter-chip" class:selected {disabled} aria-pressed={selected} aria-label={ariaLabel} {onclick}>
	{#if children}{@render children()}{:else}{label}{/if}
</button>

<style>
	.filter-chip { min-height: 1.85rem; padding: 0 var(--space-3); border: 1px solid var(--panel-border); border-radius: var(--radius-pill); background: var(--panel); color: var(--muted-strong); cursor: pointer; font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); }
	.filter-chip:hover:not(:disabled) { border-color: var(--brand); color: var(--brand-strong); }
	.filter-chip.selected { border-color: var(--brand); background: var(--brand-soft); color: var(--brand-strong); }
	.filter-chip:disabled { cursor: not-allowed; opacity: 0.45; }
</style>
