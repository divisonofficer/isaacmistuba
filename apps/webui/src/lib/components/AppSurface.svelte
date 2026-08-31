<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		as?: 'section' | 'div' | 'article';
		tone?: 'default' | 'subtle' | 'raised';
		padding?: 'none' | 'sm' | 'md' | 'lg';
		children?: Snippet;
	}

	let { as = 'section', tone = 'default', padding = 'md', children }: Props = $props();
</script>

<svelte:element this={as} class="app-surface app-surface-{tone} app-surface-pad-{padding}">
	{#if children}{@render children()}{/if}
</svelte:element>

<style>
	.app-surface { min-width: 0; }
	.app-surface-default { background: var(--panel); }
	.app-surface-subtle { background: var(--surface-2); box-shadow: none; }
	.app-surface-raised { box-shadow: var(--shadow-md); }
	.app-surface-pad-none { padding: 0; }
	.app-surface-pad-sm { padding: var(--space-3); }
	.app-surface-pad-md { padding: var(--space-4); }
	.app-surface-pad-lg { padding: var(--space-6); }
</style>
