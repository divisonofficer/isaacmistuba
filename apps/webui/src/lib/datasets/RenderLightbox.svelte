<script lang="ts">
	// Fullscreen lightbox for a rendered observation. Opens from any gallery
	// thumbnail; inside, the user can switch camera view (rig sensor), modality
	// (RGB / Stokes products), base⇄perturbed variant, and step through headings.
	import { opticalNavObservationModalityUrl } from '$lib/api';
	import { POLAR_PREVIEW_MODALITIES, isPolarRenderModality } from '$lib/datasets/sensorHelpers';

	interface SensorOption { sensor_id: string; label?: string; modality?: string; render_modality?: string; }

	interface Props {
		open: boolean;
		projectId: string;
		sceneId: string;
		vpId: string;
		heading: string;
		headings?: string[];
		sensorOptions?: SensorOption[];
		sensorId: string;
		modality: string;
		variant?: 'base' | 'perturbed';
		perturbationEnabled?: boolean;
		/** (heading, sensorId, modality) → whether that observation exists on disk. */
		hasRender?: (heading: string, sensorId: string, modality: string) => boolean;
		onClose: () => void;
	}

	let {
		open,
		projectId,
		sceneId,
		vpId,
		heading,
		headings = [],
		sensorOptions = [],
		sensorId,
		modality,
		variant = 'base',
		perturbationEnabled = false,
		hasRender,
		onClose,
	}: Props = $props();

	// Per-camera modality set: polarization cameras expose the Stokes products
	// (RGB / S1 / S2 / DoLP / AoLP); every other camera has a single native
	// modality, so we skip the modality row and link straight to its image.
	const MODALITY_LABELS: Record<string, string> = {
		rgb: 'RGB', depth: 'Depth', active_nir_intensity: 'NIR', lidar_like: 'LiDAR', polar_rgb_preview: 'RGB',
	};
	function isPolarSensor(opt?: SensorOption): boolean {
		return Boolean(opt) && (
			String(opt?.modality ?? '').toLowerCase() === 'polarization' ||
			isPolarRenderModality(opt?.render_modality)
		);
	}
	function modalitiesForSensor(sid: string): { id: string; label: string }[] {
		const opt = sensorOptions.find((s) => s.sensor_id === sid);
		if (isPolarSensor(opt)) return POLAR_PREVIEW_MODALITIES;
		const id = String(opt?.render_modality ?? 'rgb').toLowerCase();
		return [{ id, label: MODALITY_LABELS[id] ?? id.toUpperCase() }];
	}

	// Local view state — seeded from the props each time the lightbox is opened
	// for a new thumbnail, then driven by the in-modal tabs.
	let curHeading = $state('');
	let curSensor = $state('');
	let curModality = $state('');
	let curVariant = $state<'base' | 'perturbed'>('base');
	let lastOpen = false;
	$effect(() => {
		if (open && !lastOpen) {
			curHeading = heading;
			curSensor = sensorId;
			curModality = modality;
			curVariant = variant;
		}
		lastOpen = open;
	});

	const sortedHeadings = $derived([...headings].sort((a, b) => a.localeCompare(b)));
	const headingIdx = $derived(sortedHeadings.indexOf(curHeading));
	const curModalities = $derived(modalitiesForSensor(curSensor));
	// Keep the active modality valid for the selected camera (single-modality
	// cameras snap straight to their native modality when selected).
	$effect(() => {
		if (!open) return;
		if (curModalities.length && !curModalities.some((m) => m.id === curModality)) {
			curModality = curModalities[0].id;
		}
	});
	const rendered = $derived(!hasRender || hasRender(curHeading, curSensor, curModality));
	const imgUrl = $derived(
		opticalNavObservationModalityUrl(projectId, sceneId, vpId, curHeading, curModality, curSensor, curVariant)
	);
	function headingDeg(hid: string): string {
		const n = parseInt(String(hid).replace('h_', ''));
		return Number.isFinite(n) ? `${n}°` : hid;
	}
	function stepHeading(delta: number) {
		if (sortedHeadings.length === 0) return;
		const i = headingIdx < 0 ? 0 : (headingIdx + delta + sortedHeadings.length) % sortedHeadings.length;
		curHeading = sortedHeadings[i];
	}
	function onKey(e: KeyboardEvent) {
		if (!open) return;
		if (e.key === 'Escape') onClose();
		else if (e.key === 'ArrowRight') stepHeading(1);
		else if (e.key === 'ArrowLeft') stepHeading(-1);
	}
</script>

<svelte:window onkeydown={onKey} />

{#if open}
	<div class="lb-backdrop" role="presentation" onclick={onClose}>
		<div class="lb-panel" role="dialog" tabindex="-1" aria-modal="true" aria-label="Rendered observation viewer" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
			<header class="lb-head">
				<div class="lb-title">
					<strong>{vpId}</strong>
					<span class="lb-sub">{headingDeg(curHeading)} · {sensorOptions.find((s) => s.sensor_id === curSensor)?.label ?? curSensor ?? 'legacy'} · {curModalities.find((m) => m.id === curModality)?.label ?? curModality}{curVariant === 'perturbed' ? ' · mirror' : ''}</span>
				</div>
				<button class="lb-close" title="Close (Esc)" onclick={onClose}>✕</button>
			</header>

			<div class="lb-stage">
				{#if sortedHeadings.length > 1}
					<button class="lb-nav lb-prev" title="Previous heading (←)" onclick={() => stepHeading(-1)}>‹</button>
				{/if}
				{#if rendered}
					<img
						class="lb-img"
						src={imgUrl}
						alt={`${vpId} ${curHeading} ${curModality}`}
						onerror={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = '0.2'; }}
						onload={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = '1'; }}
					/>
				{:else}
					<div class="lb-empty">
						<div class="lb-empty-icon">⌀</div>
						<div>No render for this camera in this view</div>
						<div class="lb-empty-sub">{headingDeg(curHeading)} · {sensorOptions.find((s) => s.sensor_id === curSensor)?.label ?? curSensor}</div>
					</div>
				{/if}
				{#if sortedHeadings.length > 1}
					<button class="lb-nav lb-next" title="Next heading (→)" onclick={() => stepHeading(1)}>›</button>
				{/if}
			</div>

			<footer class="lb-tabs">
				{#if curModalities.length > 1}
					<div class="lb-tabrow">
						<span class="lb-tablabel">Modality</span>
						{#each curModalities as m}
							<button class="lb-tab" class:active={curModality === m.id} onclick={() => (curModality = m.id)}>{m.label}</button>
						{/each}
					</div>
				{/if}
				{#if sensorOptions.length > 0}
					<div class="lb-tabrow">
						<span class="lb-tablabel">Camera</span>
						{#each sensorOptions as s}
							<button class="lb-tab" class:active={curSensor === s.sensor_id} onclick={() => (curSensor = s.sensor_id)} title={s.modality ?? ''}>{s.label ?? s.sensor_id}</button>
						{/each}
					</div>
				{/if}
				{#if perturbationEnabled}
					<div class="lb-tabrow">
						<span class="lb-tablabel">Mirror</span>
						<button class="lb-tab" class:active={curVariant === 'base'} onclick={() => (curVariant = 'base')}>off</button>
						<button class="lb-tab" class:active={curVariant === 'perturbed'} onclick={() => (curVariant = 'perturbed')}>on</button>
					</div>
				{/if}
			</footer>
		</div>
	</div>
{/if}

<style>
	.lb-backdrop {
		position: fixed; inset: 0; z-index: 1000;
		background: rgba(2, 6, 23, 0.82);
		display: flex; align-items: center; justify-content: center;
		padding: 24px;
	}
	.lb-panel {
		display: flex; flex-direction: column;
		width: min(1100px, 96vw); max-height: 94vh;
		background: var(--surface-0, #0f172a);
		border: 1px solid var(--border, #1e293b);
		border-radius: 10px; overflow: hidden;
		box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
	}
	.lb-head {
		display: flex; align-items: center; justify-content: space-between;
		gap: 12px; padding: 10px 14px;
		border-bottom: 1px solid var(--border, #1e293b);
	}
	.lb-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
	.lb-title strong { font-size: 13px; color: var(--text, #e2e8f0); }
	.lb-sub { font-size: 11px; color: var(--text-muted, #94a3b8); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.lb-close {
		flex: none; width: 28px; height: 28px; border-radius: 6px;
		border: 1px solid var(--border, #1e293b); background: transparent;
		color: var(--text-muted, #94a3b8); cursor: pointer; font-size: 14px;
	}
	.lb-close:hover { color: var(--text, #e2e8f0); background: var(--surface-2, #1e293b); }
	.lb-stage {
		position: relative; flex: 1 1 auto; min-height: 0;
		display: flex; align-items: center; justify-content: center;
		background: #0b1120; padding: 12px;
	}
	.lb-img {
		max-width: 100%; max-height: calc(94vh - 190px);
		object-fit: contain; border-radius: 4px; transition: opacity 0.12s;
	}
	.lb-nav {
		position: absolute; top: 50%; transform: translateY(-50%);
		width: 40px; height: 56px; border: none; border-radius: 6px;
		background: rgba(15, 23, 42, 0.6); color: #e2e8f0;
		font-size: 30px; line-height: 1; cursor: pointer;
	}
	.lb-empty {
		display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
		min-height: 240px; color: var(--text-muted, #94a3b8); text-align: center; font-size: 13px;
	}
	.lb-empty-icon { font-size: 40px; opacity: 0.5; }
	.lb-empty-sub { font-size: 11px; opacity: 0.7; }
	.lb-nav:hover { background: rgba(30, 41, 59, 0.85); }
	.lb-prev { left: 10px; }
	.lb-next { right: 10px; }
	.lb-tabs {
		display: flex; flex-direction: column; gap: 6px;
		padding: 10px 14px; border-top: 1px solid var(--border, #1e293b);
	}
	.lb-tabrow { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
	.lb-tablabel { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted, #94a3b8); width: 58px; flex: none; }
	.lb-tab {
		padding: 3px 10px; border-radius: 5px; font-size: 11px; cursor: pointer;
		border: 1px solid var(--border, #334155); background: transparent;
		color: var(--text-muted, #cbd5e1);
	}
	.lb-tab:hover { border-color: var(--accent, #38bdf8); }
	.lb-tab.active { background: var(--accent, #38bdf8); border-color: var(--accent, #38bdf8); color: #04121f; font-weight: 600; }
</style>
