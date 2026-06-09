<script lang="ts">
	import { RENDER_STAGES, normalizeJobStatus, stageIndex } from '$lib/datasets/batchHelpers';

	interface Props {
		job: any;
	}

	let { job }: Props = $props();
	const si = $derived(stageIndex(job));
	const status = $derived(normalizeJobStatus(job));
</script>

<div class="stage-timeline">
	{#each RENDER_STAGES as stage, i}
		{@const done = status === 'done' || (status !== 'failed' && status !== 'cancelled' && si >= i)}
		{@const active = status !== 'done' && status !== 'failed' && status !== 'cancelled' && si === i}
		{@const failed = status === 'failed' && (si < 0 ? i === 0 : i === si)}
		{@const cached = stage.key === 'loading_scene' && job?.status?.extras?.scene_cache_hit}
		<div class={`stage-step${done ? ' done' : ''}${active ? ' active' : ''}${failed ? ' failed' : ''}`}>
			<div class="stage-dot"></div>
			<span>{stage.label}{#if cached} cached{/if}</span>
		</div>
	{/each}
</div>

<style>
	.stage-timeline {
		display: grid;
		grid-template-columns: repeat(7, minmax(54px, 1fr));
		gap: var(--space-1);
		align-items: start;
	}
	.stage-step { display: grid; gap: 4px; justify-items: center; color: var(--muted); font-size: 10px; text-align: center; }
	.stage-dot { width: 10px; height: 10px; border-radius: 50%; border: 1px solid var(--panel-border); background: var(--surface-3, #e5e7eb); }
	.stage-step.done .stage-dot { background: #22c55e; border-color: #22c55e; }
	.stage-step.active .stage-dot { background: #3b82f6; border-color: #3b82f6; }
	.stage-step.failed .stage-dot { background: #ef4444; border-color: #ef4444; }
</style>
