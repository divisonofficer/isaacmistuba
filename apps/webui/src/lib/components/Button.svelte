<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Size, Tone } from './types';

	interface Props {
		variant?: 'primary' | 'subtle' | 'ghost' | 'tone';
		tone?: Tone;
		size?: Size;
		type?: 'button' | 'submit' | 'reset';
		disabled?: boolean;
		loading?: boolean;
		fullWidth?: boolean;
		href?: string;
		onclick?: (e: MouseEvent) => void;
		title?: string;
		ariaLabel?: string;
		children?: Snippet;
		leading?: Snippet;
		trailing?: Snippet;
	}

	let {
		variant = 'subtle',
		tone = 'active',
		size = 'md',
		type = 'button',
		disabled = false,
		loading = false,
		fullWidth = false,
		href,
		onclick,
		title,
		ariaLabel,
		children,
		leading,
		trailing
	}: Props = $props();
</script>

{#if href}
	<a
		{href}
		class="btn btn-{variant} btn-{size}"
		class:btn-fullwidth={fullWidth}
		class:btn-disabled={disabled || loading}
		data-tone={variant === 'tone' ? tone : undefined}
		aria-disabled={disabled || loading || undefined}
		{title}
		aria-label={ariaLabel}
		tabindex={disabled || loading ? -1 : undefined}
		onclick={(e) => {
			if (disabled || loading) {
				e.preventDefault();
				e.stopPropagation();
				return;
			}
			onclick?.(e);
		}}
	>
		{#if leading}<span class="btn-affix">{@render leading()}</span>{/if}
		{#if children}<span class="btn-label">{@render children()}</span>{/if}
		{#if trailing}<span class="btn-affix">{@render trailing()}</span>{/if}
	</a>
{:else}
	<button
		{type}
		class="btn btn-{variant} btn-{size}"
		class:btn-fullwidth={fullWidth}
		disabled={disabled || loading}
		data-tone={variant === 'tone' ? tone : undefined}
		{onclick}
		{title}
		aria-label={ariaLabel}
		aria-busy={loading || undefined}
	>
		{#if leading}<span class="btn-affix">{@render leading()}</span>{/if}
		{#if children}<span class="btn-label">{@render children()}</span>{/if}
		{#if trailing}<span class="btn-affix">{@render trailing()}</span>{/if}
	</button>
{/if}

<style>
	.btn {
		appearance: none;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		font-family: var(--font-sans);
		font-weight: var(--font-weight-semibold);
		line-height: var(--line-height-tight);
		cursor: pointer;
		text-decoration: none;
		white-space: nowrap;
		transition:
			background-color var(--duration-fast) var(--easing-standard),
			border-color var(--duration-fast) var(--easing-standard),
			color var(--duration-fast) var(--easing-standard);
	}
	.btn:focus-visible {
		outline: 2px solid var(--brand);
		outline-offset: 2px;
	}
	.btn[disabled],
	.btn-disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.btn-fullwidth { width: 100%; }
	.btn-affix { display: inline-flex; }

	.btn-sm {
		font-size: var(--font-size-xs);
		padding: 0 var(--space-3);
		height: 1.75rem;
	}
	.btn-md {
		font-size: var(--font-size-sm);
		padding: 0 var(--space-4);
		height: 2.25rem;
	}
	.btn-lg {
		font-size: var(--font-size-md);
		padding: 0 var(--space-5);
		height: 2.75rem;
	}

	.btn-primary {
		background: var(--brand);
		color: #fff;
		border-color: var(--brand);
	}
	.btn-primary:hover:not([disabled]) {
		background: var(--brand-strong);
		border-color: var(--brand-strong);
	}

	.btn-subtle {
		background: var(--surface-2);
		color: var(--text);
		border-color: var(--panel-border);
	}
	.btn-subtle:hover:not([disabled]) {
		background: var(--brand-soft);
		border-color: var(--panel-border-strong);
	}

	.btn-ghost {
		background: transparent;
		color: var(--muted-strong);
	}
	.btn-ghost:hover:not([disabled]) {
		background: var(--brand-soft);
		color: var(--brand-strong);
	}

	.btn-tone[data-tone='success'] { background: var(--success); color: #fff; border-color: var(--success); }
	.btn-tone[data-tone='warning'] { background: var(--warning); color: #fff; border-color: var(--warning); }
	.btn-tone[data-tone='danger']  { background: var(--danger);  color: #fff; border-color: var(--danger); }
	.btn-tone[data-tone='active']  { background: var(--brand);   color: #fff; border-color: var(--brand); }
	.btn-tone[data-tone='info']    { background: var(--cyan);    color: #fff; border-color: var(--cyan); }
	.btn-tone[data-tone='neutral'] { background: var(--muted);   color: #fff; border-color: var(--muted); }
</style>
