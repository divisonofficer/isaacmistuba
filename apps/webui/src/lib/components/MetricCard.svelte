<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		value: string | number;
		tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'active';
		detail?: string;
		children?: Snippet;
	}

	let { label, value, tone = 'neutral', detail, children }: Props = $props();
</script>

<section class="metric-card" data-tone={tone}>
	<span class="metric-label">{label}</span>
	<strong>{value}</strong>
	{#if detail}<span class="metric-detail">{detail}</span>{/if}
	{#if children}<div class="metric-extra">{@render children()}</div>{/if}
</section>

<style>
	.metric-card { display: grid; align-content: start; gap: 2px; min-width: 0; padding: var(--space-3); border: 1px solid var(--panel-border); border-radius: var(--radius-md); background: var(--surface-2); }
	.metric-label { color: var(--muted); font-size: var(--font-size-2xs); font-weight: var(--font-weight-bold); letter-spacing: var(--letter-spacing-wide); text-transform: uppercase; }
	strong { overflow: hidden; color: var(--text); font-size: var(--font-size-lg); line-height: var(--line-height-snug); text-overflow: ellipsis; white-space: nowrap; }
	.metric-detail { color: var(--muted-strong); font-size: var(--font-size-xs); }
	.metric-card[data-tone='success'] strong { color: var(--success); }
	.metric-card[data-tone='warning'] strong { color: var(--warning); }
	.metric-card[data-tone='danger'] strong { color: var(--danger); }
	.metric-card[data-tone='active'] strong { color: var(--brand-strong); }
	.metric-extra { margin-top: var(--space-1); }
</style>
