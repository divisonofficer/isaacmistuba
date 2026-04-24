<script lang="ts">
	import type { Snippet } from 'svelte';

	type Position = 'top' | 'bottom' | 'left' | 'right';

	interface Props {
		text: string;
		position?: Position;
		/** Delay before showing, in ms. */
		delay?: number;
		/** When true, do not render the tooltip at all (e.g. text is empty). */
		disabled?: boolean;
		children: Snippet;
	}

	let { text, position = 'top', delay = 180, disabled = false, children }: Props = $props();
	let visible = $state(false);
	let timer: ReturnType<typeof setTimeout> | undefined;

	function show() {
		clearTimeout(timer);
		if (disabled || !text) return;
		timer = setTimeout(() => { visible = true; }, delay);
	}
	function hide() {
		clearTimeout(timer);
		visible = false;
	}
</script>

<span
	class="tooltip-wrap"
	onmouseenter={show}
	onmouseleave={hide}
	onfocusin={show}
	onfocusout={hide}
>
	{@render children()}
	{#if visible && text}
		<span class="tooltip" data-position={position} role="tooltip">{text}</span>
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
		background: var(--text);
		color: var(--panel);
		padding: 0.35rem 0.55rem;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
		font-weight: 500;
		line-height: 1.3;
		max-width: 18rem;
		text-align: center;
		pointer-events: none;
		box-shadow: var(--shadow-md);
		animation: tooltip-in 120ms ease-out;
	}
	.tooltip[data-position='top'] {
		bottom: calc(100% + 6px);
		left: 50%;
		transform: translateX(-50%);
	}
	.tooltip[data-position='bottom'] {
		top: calc(100% + 6px);
		left: 50%;
		transform: translateX(-50%);
	}
	.tooltip[data-position='left'] {
		right: calc(100% + 6px);
		top: 50%;
		transform: translateY(-50%);
	}
	.tooltip[data-position='right'] {
		left: calc(100% + 6px);
		top: 50%;
		transform: translateY(-50%);
	}
	@keyframes tooltip-in {
		from { opacity: 0; transform: translate(var(--tt-x, -50%), -2px); }
		to   { opacity: 1; }
	}
</style>
