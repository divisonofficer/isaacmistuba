<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		eyebrow?: string;
		title: string;
		description?: string;
		actions?: Snippet;
	}

	let { eyebrow, title, description, actions }: Props = $props();
</script>

<header class="section-header">
	<div class="section-header-copy">
		{#if eyebrow}<span class="section-header-eyebrow">{eyebrow}</span>{/if}
		<h2>{title}</h2>
		{#if description}<p>{description}</p>{/if}
	</div>
	{#if actions}<div class="section-header-actions">{@render actions()}</div>{/if}
</header>

<style>
	.section-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); min-width: 0; }
	.section-header-copy { min-width: 0; }
	h2 { margin: 2px 0 0; color: var(--text); font-size: var(--font-size-xl); line-height: var(--line-height-snug); letter-spacing: var(--letter-spacing-tight); }
	p { margin: var(--space-1) 0 0; color: var(--muted); font-size: var(--font-size-sm); }
	.section-header-actions { display: flex; align-items: center; gap: var(--space-2); flex: 0 0 auto; }
</style>
