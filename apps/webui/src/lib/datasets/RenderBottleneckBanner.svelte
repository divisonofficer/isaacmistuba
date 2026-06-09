<script lang="ts">
	import { buildBottleneckSummary } from '$lib/datasets/batchHelpers';

	interface Props {
		activeBatch: any;
		health: any;
	}

	let { activeBatch, health }: Props = $props();
	const bottleneck = $derived(buildBottleneckSummary(activeBatch, health));
</script>

<section class={`bottleneck tone-${bottleneck.tone}`}>
	<div>
		<strong>{bottleneck.title}</strong>
		<p>{bottleneck.message}</p>
	</div>
</section>

<style>
	.bottleneck {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		padding: var(--space-3);
	}
	.bottleneck strong { display: block; color: var(--text); font-size: var(--font-size-sm); }
	.bottleneck p { margin: var(--space-1) 0 0; color: var(--muted-strong); font-size: var(--font-size-xs); }
	.bottleneck.tone-failed { border-color: color-mix(in srgb, var(--danger, #dc2626) 40%, var(--panel-border)); }
	.bottleneck.tone-running { border-color: color-mix(in srgb, var(--accent, #2f6fed) 35%, var(--panel-border)); }
	.bottleneck.tone-queued { border-color: #facc15; }
</style>
