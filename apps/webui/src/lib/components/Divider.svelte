<script lang="ts">
	interface Props {
		orientation?: 'horizontal' | 'vertical';
		variant?: 'solid' | 'dashed';
		spacing?: 'sm' | 'md' | 'lg' | 'none';
		label?: string;
	}

	let {
		orientation = 'horizontal',
		variant = 'solid',
		spacing = 'md',
		label
	}: Props = $props();
</script>

{#if label && orientation === 'horizontal'}
	<div
		class="divider divider-labeled divider-{variant} divider-spacing-{spacing}"
		role="separator"
		aria-orientation="horizontal"
	>
		<span class="divider-label">{label}</span>
	</div>
{:else}
	<hr
		class="divider divider-{orientation} divider-{variant} divider-spacing-{spacing}"
		aria-orientation={orientation}
	/>
{/if}

<style>
	.divider {
		border: none;
		background: transparent;
		flex-shrink: 0;
	}
	.divider-horizontal {
		width: 100%;
		height: 0;
		border-top: 1px solid var(--panel-border);
	}
	.divider-vertical {
		display: inline-block;
		width: 0;
		height: 1.25rem;
		border-left: 1px solid var(--panel-border);
		vertical-align: middle;
	}
	.divider-dashed.divider-horizontal { border-top-style: dashed; }
	.divider-dashed.divider-vertical   { border-left-style: dashed; }

	.divider-spacing-none { margin: 0; }
	.divider-spacing-sm   { margin: var(--space-2) 0; }
	.divider-spacing-md   { margin: var(--space-4) 0; }
	.divider-spacing-lg   { margin: var(--space-6) 0; }

	.divider-labeled {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		color: var(--muted);
		font-size: var(--font-size-xs);
		text-transform: uppercase;
		letter-spacing: var(--letter-spacing-wide);
	}
	.divider-labeled::before,
	.divider-labeled::after {
		content: '';
		flex: 1 1 auto;
		border-top: 1px solid var(--panel-border);
	}
	.divider-labeled.divider-dashed::before,
	.divider-labeled.divider-dashed::after { border-top-style: dashed; }
	.divider-label { white-space: nowrap; }
</style>
