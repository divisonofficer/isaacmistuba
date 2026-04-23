<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Size, Tone } from './types';

	interface Props {
		tone?: Tone;
		variant?: 'solid' | 'soft' | 'outline';
		size?: Exclude<Size, 'lg'>;
		dot?: boolean;
		pulse?: boolean;
		label?: string;
		title?: string;
		children?: Snippet;
	}

	let {
		tone = 'neutral',
		variant = 'soft',
		size = 'md',
		dot = false,
		pulse = false,
		label,
		title,
		children
	}: Props = $props();
</script>

<span
	class="chip chip-{size} chip-{variant}"
	data-tone={tone}
	{title}
	role="status"
>
	{#if dot}<span class="chip-dot" class:chip-dot-pulse={pulse}></span>{/if}
	{#if children}{@render children()}{:else if label}{label}{/if}
</span>

<style>
	.chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-pill);
		font-weight: var(--font-weight-semibold);
		line-height: var(--line-height-tight);
		white-space: nowrap;
	}
	.chip-sm { font-size: var(--font-size-2xs); padding: 2px var(--space-2); }
	.chip-md { font-size: var(--font-size-xs);  padding: 4px var(--space-3); }

	.chip-dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-circle);
		background: currentColor;
		flex-shrink: 0;
	}
	.chip-dot-pulse {
		animation: chip-pulse 1.6s ease-in-out infinite;
	}
	@keyframes chip-pulse {
		0%, 100% { opacity: 1; transform: scale(1); }
		50%      { opacity: 0.45; transform: scale(0.8); }
	}

	/* Soft (default) — light background, tone-colored text */
	.chip-soft[data-tone='success'] { background: var(--success-soft); color: var(--success); }
	.chip-soft[data-tone='warning'] { background: var(--warning-soft); color: var(--warning); }
	.chip-soft[data-tone='danger']  { background: var(--danger-soft);  color: var(--danger); }
	.chip-soft[data-tone='active']  { background: var(--brand-soft);   color: var(--brand-strong); }
	.chip-soft[data-tone='info']    { background: var(--cyan-soft);    color: var(--cyan); }
	.chip-soft[data-tone='neutral'] { background: var(--surface-2);    color: var(--muted-strong); }

	/* Solid — full color background, white text */
	.chip-solid[data-tone='success'] { background: var(--success); color: #fff; }
	.chip-solid[data-tone='warning'] { background: var(--warning); color: #fff; }
	.chip-solid[data-tone='danger']  { background: var(--danger);  color: #fff; }
	.chip-solid[data-tone='active']  { background: var(--brand);   color: #fff; }
	.chip-solid[data-tone='info']    { background: var(--cyan);    color: #fff; }
	.chip-solid[data-tone='neutral'] { background: var(--muted-strong); color: #fff; }

	/* Outline — bordered, tone-colored text */
	.chip-outline { background: transparent; }
	.chip-outline[data-tone='success'] { color: var(--success); border-color: var(--success); }
	.chip-outline[data-tone='warning'] { color: var(--warning); border-color: var(--warning); }
	.chip-outline[data-tone='danger']  { color: var(--danger);  border-color: var(--danger); }
	.chip-outline[data-tone='active']  { color: var(--brand-strong); border-color: var(--brand); }
	.chip-outline[data-tone='info']    { color: var(--cyan);    border-color: var(--cyan); }
	.chip-outline[data-tone='neutral'] { color: var(--muted-strong); border-color: var(--panel-border-strong); }
</style>
