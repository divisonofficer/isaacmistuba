<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title?: string;
		eyebrow?: string;
		padding?: 'none' | 'sm' | 'md' | 'lg';
		elevation?: 'none' | 'sm' | 'md' | 'lg';
		bordered?: boolean;
		children?: Snippet;
		header?: Snippet;
		footer?: Snippet;
		actions?: Snippet;
	}

	let {
		title,
		eyebrow,
		padding = 'md',
		elevation = 'sm',
		bordered = true,
		children,
		header,
		footer,
		actions
	}: Props = $props();
</script>

<section
	class="card card-elev-{elevation} card-pad-{padding}"
	class:card-bordered={bordered}
>
	{#if header || title || eyebrow || actions}
		<header class="card-header">
			<div class="card-header-text">
				{#if header}
					{@render header()}
				{:else}
					{#if eyebrow}<span class="card-eyebrow">{eyebrow}</span>{/if}
					{#if title}<h3 class="card-title">{title}</h3>{/if}
				{/if}
			</div>
			{#if actions}<div class="card-actions">{@render actions()}</div>{/if}
		</header>
	{/if}

	{#if children}
		<div class="card-body">{@render children()}</div>
	{/if}

	{#if footer}
		<footer class="card-footer">{@render footer()}</footer>
	{/if}
</section>

<style>
	.card {
		display: flex;
		flex-direction: column;
		background: var(--panel);
		border-radius: var(--radius-lg);
		min-width: 0;
	}
	.card-bordered { border: 1px solid var(--panel-border); }
	.card-elev-none { box-shadow: var(--shadow-flat); }
	.card-elev-sm { box-shadow: var(--shadow-sm); }
	.card-elev-md { box-shadow: var(--shadow-md); }
	.card-elev-lg { box-shadow: var(--shadow-lg); }

	.card-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-4) var(--space-4) var(--space-3);
	}
	.card-header-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
	.card-eyebrow {
		font-size: var(--font-size-2xs);
		font-weight: var(--font-weight-semibold);
		text-transform: uppercase;
		letter-spacing: var(--letter-spacing-eyebrow);
		color: var(--brand-strong);
	}
	.card-title {
		font-size: var(--font-size-md);
		font-weight: var(--font-weight-semibold);
		letter-spacing: var(--letter-spacing-tight);
		color: var(--text);
		margin: 0;
	}
	.card-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex: 0 0 auto;
	}
	.card-body { min-width: 0; }
	.card-footer {
		border-top: 1px solid var(--panel-border);
		padding: var(--space-3) var(--space-4);
	}

	.card-pad-none .card-body { padding: 0; }
	.card-pad-sm   .card-body { padding: var(--space-3); }
	.card-pad-md   .card-body { padding: var(--space-4); }
	.card-pad-lg   .card-body { padding: var(--space-6); }

	.card-pad-none .card-header { padding: 0; }
	.card-pad-sm   .card-header { padding: var(--space-3) var(--space-3) var(--space-2); }
</style>
