<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		hint?: string;
		error?: string;
		forId?: string;
		children?: Snippet;
	}

	let { label, hint, error, forId, children }: Props = $props();
</script>

<label class="form-field" class:invalid={Boolean(error)} for={forId}>
	<span class="form-field-label">{label}</span>
	{#if children}<span class="form-field-control">{@render children()}</span>{/if}
	{#if error}<span class="form-field-message">{error}</span>{:else if hint}<span class="form-field-hint">{hint}</span>{/if}
</label>

<style>
	.form-field { display: grid; gap: var(--space-1); color: var(--muted-strong); font-size: var(--font-size-xs); }
	.form-field-label { font-weight: var(--font-weight-semibold); }
	.form-field-control { min-width: 0; }
	.form-field-hint { color: var(--muted); }
	.form-field-message { color: var(--danger); }
</style>
