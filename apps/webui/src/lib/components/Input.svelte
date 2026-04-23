<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Size, Tone } from './types';

	interface Props {
		value?: string;
		type?: 'text' | 'search' | 'email' | 'password' | 'number' | 'tel' | 'url';
		placeholder?: string;
		size?: Size;
		tone?: Tone;
		disabled?: boolean;
		readonly?: boolean;
		invalid?: boolean;
		ariaLabel?: string;
		id?: string;
		name?: string;
		onchange?: (e: Event) => void;
		oninput?: (e: Event) => void;
		leading?: Snippet;
		trailing?: Snippet;
	}

	let {
		value = $bindable(''),
		type = 'text',
		placeholder,
		size = 'md',
		tone = 'neutral',
		disabled = false,
		readonly = false,
		invalid = false,
		ariaLabel,
		id,
		name,
		onchange,
		oninput,
		leading,
		trailing
	}: Props = $props();
</script>

<div
	class="input-wrap input-{size}"
	data-tone={invalid ? 'danger' : tone}
	class:input-disabled={disabled}
>
	{#if leading}<span class="input-affix">{@render leading()}</span>{/if}
	<input
		{type}
		{placeholder}
		{disabled}
		{readonly}
		{id}
		{name}
		aria-label={ariaLabel}
		aria-invalid={invalid || undefined}
		bind:value
		{onchange}
		{oninput}
	/>
	{#if trailing}<span class="input-affix">{@render trailing()}</span>{/if}
</div>

<style>
	.input-wrap {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		background: var(--panel);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		padding: 0 var(--space-3);
		transition:
			border-color var(--duration-fast) var(--easing-standard),
			box-shadow var(--duration-fast) var(--easing-standard);
	}
	.input-wrap:focus-within {
		border-color: var(--brand);
		box-shadow: 0 0 0 3px var(--brand-soft);
	}
	.input-wrap[data-tone='danger'] { border-color: var(--danger); }
	.input-wrap[data-tone='danger']:focus-within { box-shadow: 0 0 0 3px var(--danger-soft); }
	.input-wrap[data-tone='success'] { border-color: var(--success); }
	.input-wrap[data-tone='warning'] { border-color: var(--warning); }
	.input-disabled { opacity: 0.6; cursor: not-allowed; }
	.input-affix { color: var(--muted); display: inline-flex; }

	.input-sm { height: 1.75rem; font-size: var(--font-size-xs); }
	.input-md { height: 2.25rem; font-size: var(--font-size-sm); }
	.input-lg { height: 2.75rem; font-size: var(--font-size-md); }

	input {
		flex: 1 1 auto;
		min-width: 0;
		border: none;
		outline: none;
		background: transparent;
		color: var(--text);
		font: inherit;
		padding: 0;
	}
	input::placeholder { color: var(--muted); }
	input:disabled { cursor: not-allowed; }
</style>
