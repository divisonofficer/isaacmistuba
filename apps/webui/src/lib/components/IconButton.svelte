<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Size, Tone } from './types';

	interface Props {
		ariaLabel: string;
		size?: Size;
		tone?: Tone;
		variant?: 'subtle' | 'ghost' | 'solid';
		disabled?: boolean;
		pressed?: boolean;
		title?: string;
		onclick?: (e: MouseEvent) => void;
		icon?: Snippet;
		children?: Snippet;
	}

	let {
		ariaLabel,
		size = 'md',
		tone = 'neutral',
		variant = 'ghost',
		disabled = false,
		pressed,
		title,
		onclick,
		icon,
		children
	}: Props = $props();
</script>

<button
	type="button"
	class="icon-btn icon-btn-{size} icon-btn-{variant}"
	data-tone={tone}
	{disabled}
	{title}
	aria-label={ariaLabel}
	aria-pressed={pressed}
	{onclick}
>
	{#if icon}{@render icon()}{:else if children}{@render children()}{/if}
</button>

<style>
	.icon-btn {
		appearance: none;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--muted-strong);
		cursor: pointer;
		transition:
			background-color var(--duration-fast) var(--easing-standard),
			color var(--duration-fast) var(--easing-standard);
	}
	.icon-btn:focus-visible {
		outline: 2px solid var(--brand);
		outline-offset: 2px;
	}
	.icon-btn[disabled] {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.icon-btn-sm { width: 1.75rem; height: 1.75rem; font-size: var(--font-size-xs); }
	.icon-btn-md { width: 2.25rem; height: 2.25rem; font-size: var(--font-size-sm); }
	.icon-btn-lg { width: 2.75rem; height: 2.75rem; font-size: var(--font-size-md); }

	.icon-btn-ghost:hover:not([disabled]) {
		background: var(--brand-soft);
		color: var(--brand-strong);
	}
	.icon-btn-subtle {
		background: var(--surface-2);
		border-color: var(--panel-border);
	}
	.icon-btn-subtle:hover:not([disabled]) {
		background: var(--brand-soft);
	}
	.icon-btn-solid[data-tone='success'] { background: var(--success); color: #fff; border-color: var(--success); }
	.icon-btn-solid[data-tone='warning'] { background: var(--warning); color: #fff; border-color: var(--warning); }
	.icon-btn-solid[data-tone='danger']  { background: var(--danger);  color: #fff; border-color: var(--danger); }
	.icon-btn-solid[data-tone='active']  { background: var(--brand);   color: #fff; border-color: var(--brand); }
	.icon-btn-solid[data-tone='info']    { background: var(--cyan);    color: #fff; border-color: var(--cyan); }
	.icon-btn-solid[data-tone='neutral'] { background: var(--muted);   color: #fff; border-color: var(--muted); }
</style>
