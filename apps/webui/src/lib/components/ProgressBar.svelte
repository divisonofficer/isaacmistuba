<script lang="ts">
	interface Props {
		value: number;
		label?: string;
		tone?: 'primary' | 'success' | 'warning' | 'danger';
		showValue?: boolean;
	}

	let { value, label, tone = 'primary', showValue = false }: Props = $props();
	const percent = $derived(Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0)));
</script>

<div class="progress" data-tone={tone} aria-label={label} role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={percent}>
	<div class="progress-fill" style:width={`${percent}%`}></div>
</div>
{#if showValue}<span class="progress-value">{Math.round(percent)}%</span>{/if}

<style>
	.progress { height: 0.45rem; overflow: hidden; border-radius: var(--radius-pill); background: var(--surface-3); }
	.progress-fill { height: 100%; border-radius: inherit; background: var(--brand); transition: width var(--duration-base) var(--easing-standard); }
	.progress[data-tone='success'] .progress-fill { background: var(--success); }
	.progress[data-tone='warning'] .progress-fill { background: var(--warning); }
	.progress[data-tone='danger'] .progress-fill { background: var(--danger); }
	.progress-value { color: var(--muted); font-size: var(--font-size-xs); }
</style>
