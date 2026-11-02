<script lang="ts">
	interface Props {
		checked?: boolean;
		disabled?: boolean;
		label: string;
		onchange?: (checked: boolean) => void;
	}

	let { checked = $bindable(false), disabled = false, label, onchange }: Props = $props();
</script>

<label class="toggle-switch" class:disabled>
	<input type="checkbox" bind:checked {disabled} onchange={() => onchange?.(checked)} />
	<span class="toggle-track" aria-hidden="true"><span class="toggle-thumb"></span></span>
	<span>{label}</span>
</label>

<style>
	.toggle-switch { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--muted-strong); cursor: pointer; font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); }
	input { position: absolute; opacity: 0; pointer-events: none; }
	.toggle-track { width: 2rem; height: 1.2rem; padding: 2px; border-radius: var(--radius-pill); background: var(--panel-border-strong); transition: background-color var(--duration-fast) var(--easing-standard); }
	.toggle-thumb { display: block; width: 0.95rem; height: 0.95rem; border-radius: 50%; background: var(--panel); box-shadow: var(--shadow-xs); transition: transform var(--duration-fast) var(--easing-standard); }
	input:checked + .toggle-track { background: var(--brand); }
	input:checked + .toggle-track .toggle-thumb { transform: translateX(0.8rem); }
	input:focus-visible + .toggle-track { outline: 2px solid var(--brand); outline-offset: 2px; }
	.disabled { cursor: not-allowed; opacity: 0.45; }
</style>
