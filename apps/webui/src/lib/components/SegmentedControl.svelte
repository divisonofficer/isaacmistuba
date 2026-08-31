<script lang="ts">
	import type { TabItem } from './types';

	interface Props {
		items: TabItem[];
		value: string;
		ariaLabel?: string;
		onchange: (id: string) => void;
	}

	let { items, value, ariaLabel = 'Segmented control', onchange }: Props = $props();

	function onKeydown(event: KeyboardEvent, index: number) {
		if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
		event.preventDefault();
		const enabled = items.map((item, itemIndex) => ({ item, itemIndex })).filter(({ item }) => !item.disabled);
		if (!enabled.length) return;
		const current = Math.max(0, enabled.findIndex(({ itemIndex }) => itemIndex === index));
		const target = event.key === 'Home' ? enabled[0]
			: event.key === 'End' ? enabled[enabled.length - 1]
			: enabled[(current + (event.key === 'ArrowRight' ? 1 : -1) + enabled.length) % enabled.length];
		onchange(target.item.id);
		const currentButton = event.currentTarget as HTMLButtonElement | null;
		const buttons = (currentButton?.parentElement?.querySelectorAll('button') ?? []);
		(buttons[target.itemIndex] as HTMLButtonElement | undefined)?.focus();
	}
</script>

<div class="segmented-control" role="radiogroup" aria-label={ariaLabel}>
	{#each items as item, index (item.id)}
		<button
			type="button"
			role="radio"
			aria-checked={value === item.id}
			class:active={value === item.id}
			disabled={item.disabled}
			onclick={() => !item.disabled && onchange(item.id)}
			onkeydown={(event) => onKeydown(event, index)}
		>{item.label}</button>
	{/each}
</div>

<style>
	.segmented-control { display: inline-flex; gap: 2px; padding: 3px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-2); }
	button { min-height: 1.9rem; padding: 0 var(--space-3); border: 0; border-radius: calc(var(--radius-sm) - 2px); background: transparent; color: var(--muted-strong); cursor: pointer; font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); }
	button.active { background: var(--panel); color: var(--brand-strong); box-shadow: var(--shadow-xs); }
	button:disabled { cursor: not-allowed; opacity: 0.45; }
</style>
