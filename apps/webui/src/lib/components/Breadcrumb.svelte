<script lang="ts">
	import type { BreadcrumbItem } from './types';

	interface Props {
		items: BreadcrumbItem[];
		separator?: string;
		ariaLabel?: string;
	}

	let { items, separator = '/', ariaLabel = 'Breadcrumb' }: Props = $props();
</script>

<nav class="bc" aria-label={ariaLabel}>
	<ol>
		{#each items as item, i (i)}
			{@const isLast = i === items.length - 1}
			<li class="bc-item">
				{#if item.href && !isLast}
					<a href={item.href} class="bc-link">{item.label}</a>
				{:else}
					<span class="bc-current" aria-current={isLast ? 'page' : undefined}>{item.label}</span>
				{/if}
				{#if !isLast}
					<span class="bc-sep" aria-hidden="true">{separator}</span>
				{/if}
			</li>
		{/each}
	</ol>
</nav>

<style>
	.bc { font-size: var(--font-size-xs); color: var(--muted); }
	.bc ol {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1);
	}
	.bc-item { display: inline-flex; align-items: center; gap: var(--space-2); }
	.bc-link {
		color: var(--muted-strong);
		text-decoration: none;
		transition: color var(--duration-fast) var(--easing-standard);
	}
	.bc-link:hover { color: var(--brand-strong); text-decoration: underline; }
	.bc-current { color: var(--text); font-weight: var(--font-weight-semibold); }
	.bc-sep { color: var(--muted); }
</style>
