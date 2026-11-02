<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		open?: boolean;
		children?: Snippet;
		actions?: Snippet;
	}

	let { title, open = true, children, actions }: Props = $props();
</script>

<section class="inspector-section">
	<header class="inspector-section-head">
		<h3>{title}</h3>
		{#if actions}<div class="inspector-section-actions">{@render actions()}</div>{/if}
	</header>
	{#if open && children}<div class="inspector-section-body">{@render children()}</div>{/if}
</section>

<style>
	.inspector-section { border-bottom: 1px solid var(--panel-border); padding: var(--space-3) 0; }
	.inspector-section:last-child { border-bottom: 0; }
	.inspector-section-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
	h3 { margin: 0; color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-bold); letter-spacing: var(--letter-spacing-wide); text-transform: uppercase; }
	.inspector-section-actions { display: flex; gap: var(--space-2); }
	.inspector-section-body { display: grid; gap: var(--space-3); margin-top: var(--space-3); }
</style>
