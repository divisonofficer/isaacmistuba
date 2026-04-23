<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Tone } from './types';

	interface Props {
		href: string;
		label: string;
		icon?: string;
		active?: boolean;
		badge?: string | number;
		badgeTone?: Tone;
		pinned?: boolean;
		trailing?: Snippet;
	}

	let {
		href,
		label,
		icon,
		active = false,
		badge,
		badgeTone = 'active',
		pinned = false,
		trailing
	}: Props = $props();
</script>

<a
	{href}
	class="snav"
	class:snav-active={active}
	class:snav-pinned={pinned}
	aria-current={active ? 'page' : undefined}
>
	<span class="snav-main">
		{#if icon}<span class="snav-icon" aria-hidden="true">{icon}</span>{/if}
		<span class="snav-label">{label}</span>
	</span>
	<span class="snav-trailing">
		{#if trailing}
			{@render trailing()}
		{:else if badge != null}
			<span class="snav-badge" data-tone={badgeTone}>{badge}</span>
		{:else if active}
			<span class="snav-arrow" aria-hidden="true">▶</span>
		{/if}
	</span>
</a>

<style>
	.snav {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		padding: var(--space-2) var(--space-3);
		color: var(--muted-strong);
		font-weight: var(--font-weight-semibold);
		font-size: var(--font-size-sm);
		text-decoration: none;
		transition:
			background-color var(--duration-fast) var(--easing-standard),
			color var(--duration-fast) var(--easing-standard),
			border-color var(--duration-fast) var(--easing-standard);
	}
	.snav:hover,
	.snav-active {
		background: var(--brand-soft);
		border-color: rgba(47, 123, 246, 0.18);
		color: var(--brand-strong);
	}
	.snav-pinned {
		border-color: rgba(47, 123, 246, 0.25);
		background: var(--brand-soft);
	}
	.snav-main { display: inline-flex; align-items: center; gap: var(--space-2); min-width: 0; }
	.snav-icon { font-size: var(--font-size-md); line-height: 1; flex-shrink: 0; }
	.snav-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.snav-trailing { display: inline-flex; align-items: center; flex-shrink: 0; }
	.snav-arrow { font-size: var(--font-size-2xs); opacity: 0.5; }
	.snav-badge {
		font-size: var(--font-size-2xs);
		font-weight: var(--font-weight-bold);
		padding: 2px var(--space-2);
		border-radius: var(--radius-pill);
	}
	.snav-badge[data-tone='success'] { background: var(--success-soft); color: var(--success); }
	.snav-badge[data-tone='warning'] { background: var(--warning-soft); color: var(--warning); }
	.snav-badge[data-tone='danger']  { background: var(--danger-soft);  color: var(--danger); }
	.snav-badge[data-tone='active']  { background: var(--brand-soft);   color: var(--brand-strong); }
	.snav-badge[data-tone='info']    { background: var(--cyan-soft);    color: var(--cyan); }
	.snav-badge[data-tone='neutral'] { background: var(--surface-2);    color: var(--muted-strong); }
</style>
