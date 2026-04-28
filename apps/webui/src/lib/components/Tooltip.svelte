<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { Snippet } from 'svelte';

	type Position = 'top' | 'bottom' | 'left' | 'right';

	interface Props {
		/** Single-line label or full body when title is empty. */
		text?: string;
		/** Optional bold heading shown above the body. */
		title?: string;
		/** Optional keyboard shortcut shown in the heading row. */
		kbd?: string;
		position?: Position;
		/** Delay before showing, in ms. */
		delay?: number;
		/** When true, do not render the tooltip at all. */
		disabled?: boolean;
		children: Snippet;
	}

	let {
		text = '',
		title = '',
		kbd = '',
		position = 'top',
		delay = 180,
		disabled = false,
		children
	}: Props = $props();
	let visible = $state(false);
	let timer: ReturnType<typeof setTimeout> | undefined;

	const hasContent = $derived(!!(title || text));

	function show() {
		clearTimeout(timer);
		if (disabled || !hasContent) return;
		timer = setTimeout(() => { visible = true; }, delay);
	}
	function hide() {
		clearTimeout(timer);
		visible = false;
	}

	onDestroy(() => {
		clearTimeout(timer);
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span
	class="tooltip-wrap"
	onmouseenter={show}
	onmouseleave={hide}
	onfocusin={show}
	onfocusout={hide}
>
	{@render children()}
	{#if visible && hasContent}
		<span class="tooltip" data-position={position} role="tooltip">
			{#if title}
				<span class="tooltip-head">
					<span class="tooltip-title">{title}</span>
					{#if kbd}<span class="tooltip-kbd">{kbd}</span>{/if}
				</span>
			{/if}
			{#if text}
				<span class="tooltip-body">{text}</span>
			{/if}
		</span>
	{/if}
</span>

<style>
	.tooltip-wrap {
		position: relative;
		display: inline-flex;
	}
	.tooltip {
		position: absolute;
		z-index: var(--z-tooltip, 1400);
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		background: var(--text);
		color: var(--panel);
		padding: 0.55rem 0.7rem;
		border-radius: var(--radius-md, 0.5rem);
		font-size: var(--font-size-sm, 0.875rem);
		font-weight: 500;
		line-height: 1.45;
		max-width: 22rem;
		min-width: 9rem;
		text-align: left;
		pointer-events: none;
		box-shadow: var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.18));
		animation: tooltip-in 130ms ease-out;
		white-space: normal;
		word-break: keep-all;
	}
	.tooltip-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.6rem;
	}
	.tooltip-title {
		font-size: var(--font-size-sm, 0.875rem);
		font-weight: 700;
		letter-spacing: -0.01em;
	}
	.tooltip-kbd {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.72rem;
		font-weight: 600;
		padding: 0.05rem 0.35rem;
		border-radius: 0.25rem;
		background: rgba(255, 255, 255, 0.14);
		color: rgba(255, 255, 255, 0.85);
	}
	.tooltip-body {
		font-size: 0.82rem;
		font-weight: 500;
		opacity: 0.92;
	}
	.tooltip[data-position='top'] {
		bottom: calc(100% + 8px);
		left: 50%;
		transform: translateX(-50%);
	}
	.tooltip[data-position='bottom'] {
		top: calc(100% + 8px);
		left: 50%;
		transform: translateX(-50%);
	}
	.tooltip[data-position='left'] {
		right: calc(100% + 8px);
		top: 50%;
		transform: translateY(-50%);
	}
	.tooltip[data-position='right'] {
		left: calc(100% + 8px);
		top: 50%;
		transform: translateY(-50%);
	}
	@keyframes tooltip-in {
		from { opacity: 0; transform: translate(var(--tt-x, -50%), -3px); }
		to   { opacity: 1; }
	}
</style>
