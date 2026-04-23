<script lang="ts">
	import type { TabItem } from './types';

	interface Props {
		items: TabItem[];
		value: string;
		onchange: (id: string) => void;
		size?: 'sm' | 'md';
		ariaLabel?: string;
	}

	let { items, value, onchange, size = 'md', ariaLabel = 'Tabs' }: Props = $props();

	function handleClick(id: string, disabled?: boolean) {
		if (disabled || id === value) return;
		onchange(id);
	}
</script>

<div class="tabs tabs-{size}" role="tablist" aria-label={ariaLabel}>
	{#each items as tab (tab.id)}
		{@const isActive = tab.id === value}
		<button
			type="button"
			class="tab"
			class:tab-active={isActive}
			role="tab"
			id="tab-{tab.id}"
			aria-selected={isActive}
			aria-controls="tabpanel-{tab.id}"
			tabindex={isActive ? 0 : -1}
			disabled={tab.disabled}
			onclick={() => handleClick(tab.id, tab.disabled)}
		>
			<span class="tab-label">{tab.label}</span>
			{#if tab.badge != null}
				<span class="tab-badge">{tab.badge}</span>
			{/if}
		</button>
	{/each}
</div>

<style>
	.tabs {
		display: inline-flex;
		align-items: stretch;
		gap: 2px;
		border-bottom: 1px solid var(--panel-border);
	}
	.tab {
		appearance: none;
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--muted-strong);
		font-family: inherit;
		font-weight: var(--font-weight-semibold);
		cursor: pointer;
		transition:
			color var(--duration-fast) var(--easing-standard),
			border-color var(--duration-fast) var(--easing-standard);
		margin-bottom: -1px;
	}
	.tab:focus-visible {
		outline: 2px solid var(--brand);
		outline-offset: 2px;
		border-radius: var(--radius-sm);
	}
	.tab[disabled] { opacity: 0.5; cursor: not-allowed; }
	.tab:hover:not([disabled]) { color: var(--brand-strong); }
	.tab-active {
		color: var(--brand-strong);
		border-bottom-color: var(--brand);
	}
	.tabs-sm .tab { font-size: var(--font-size-xs); padding: var(--space-2) var(--space-3); }
	.tabs-md .tab { font-size: var(--font-size-sm); padding: var(--space-3) var(--space-4); }

	.tab-badge {
		font-size: var(--font-size-2xs);
		font-weight: var(--font-weight-bold);
		padding: 1px var(--space-2);
		background: var(--surface-2);
		color: var(--muted-strong);
		border-radius: var(--radius-pill);
	}
	.tab-active .tab-badge { background: var(--brand-soft); color: var(--brand-strong); }
</style>
