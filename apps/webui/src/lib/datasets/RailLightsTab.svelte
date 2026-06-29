<script lang="ts">
	import { kelvinToRgb, rgbToKelvinApprox } from '$lib/datasets/materialHelpers';
	import type { Capabilities } from '$lib/datasets/capabilityHelpers';

	interface Props {
		caps: Capabilities;
		authoringMap: any;
		detectedEmitterIds: Set<string>;
		detectedEmitterCount: number;
		enabledEmitterCount: number;
		hasScene: boolean;
		saving: boolean;
		onEnableAll: () => void;
		onDisableAll: () => void;
		onToggleEmitter: (lightId: string, isOn: boolean) => Promise<void>;
		onSetEmitterIntensity: (lightId: string, intensity: number) => void;
		onSetEmitterRadiance: (lightId: string, rgb: [number, number, number]) => void;
		onSetEmitterHeight: (lightId: string, height: number) => void;
		onSave: () => void;
	}

	let {
		caps,
		authoringMap, detectedEmitterIds, detectedEmitterCount, enabledEmitterCount,
		hasScene, saving,
		onEnableAll, onDisableAll, onToggleEmitter,
		onSetEmitterIntensity, onSetEmitterRadiance, onSetEmitterHeight, onSave,
	}: Props = $props();

	const emitterObjects = $derived(
		(authoringMap?.objects ?? []).filter((o: any) => detectedEmitterIds.has(o.id) || o.is_emitter)
	);

	// Ceiling lights = emitters mounted at ceiling height (matches the importer's
	// synthesis threshold), plus anything labelled "ceiling" or synthesized. These
	// get bulk on / brightness controls so a whole scene's overhead lighting can be
	// driven together instead of one fixture at a time.
	const CEILING_MIN_H = 2.0;
	const ceilingLights = $derived(
		emitterObjects.filter((o: any) =>
			/ceiling/i.test(String(o.label ?? '')) ||
			o.metadata?.synthesized === true ||
			Number(o.geometry?.base_height_m ?? 0) >= CEILING_MIN_H
		)
	);
	const ceilingOnCount = $derived(ceilingLights.filter((o: any) => o.is_emitter).length);
	// Representative brightness for the bulk slider: the first lit ceiling fixture.
	const ceilingIntensityValue = $derived.by(() => {
		const lit = ceilingLights.find((o: any) => o.is_emitter);
		return lit ? Number(lit.emitter_intensity ?? 1.0) : 1.0;
	});
	// Live drag value (display only); null when not dragging so the slider tracks
	// the actual fixture intensity. The bulk apply happens on release (onchange).
	let ceilingDragValue = $state<number | null>(null);
	const ceilingSliderValue = $derived(ceilingDragValue ?? ceilingIntensityValue);

	async function enableAllCeiling() {
		for (const o of ceilingLights) {
			if (!o.is_emitter) await onToggleEmitter(o.id, true);
		}
	}
	function setAllCeilingIntensity(v: number) {
		for (const o of ceilingLights) {
			if (o.is_emitter) onSetEmitterIntensity(o.id, v);
		}
	}
</script>

<section class="rail-section rail-tool-panel lights-panel">
	<div class="rail-title">Lights</div>
	{#if detectedEmitterCount > 0}
		<div class="emitter-bulk-row">
			<span>{enabledEmitterCount}/{detectedEmitterCount} fixtures enabled</span>
			<button class="button button-subtle" disabled={!caps.enableEmitters.enabled} title={caps.enableEmitters.reason} onclick={onEnableAll}>Enable all</button>
			{#if enabledEmitterCount > 0}
				<button class="button button-subtle" onclick={onDisableAll}>Disable all</button>
			{/if}
		</div>
		{#if ceilingLights.length > 0}
			<div class="emitter-bulk-row ceiling-bulk-row">
				<span class="ceiling-icon" title="Ceiling lights">☀</span>
				<span>천장등 {ceilingOnCount}/{ceilingLights.length}</span>
				<button class="button button-subtle" disabled={ceilingOnCount >= ceilingLights.length} onclick={enableAllCeiling}>Ceiling on</button>
				<label class="ceiling-dim" title="모든 천장등 밝기 일괄 조절 (놓을 때 적용)">
					<input type="range" min="0.1" max="20" step="0.1"
						value={ceilingSliderValue}
						disabled={ceilingOnCount === 0}
						oninput={(e) => (ceilingDragValue = Number((e.currentTarget as HTMLInputElement).value))}
						onchange={(e) => { setAllCeilingIntensity(Number((e.currentTarget as HTMLInputElement).value)); ceilingDragValue = null; }}
					/>
					<span class="ceiling-dim-val">{ceilingSliderValue.toFixed(1)}×</span>
				</label>
			</div>
		{/if}
	{:else}
		<p class="probe-empty">No light-keyword objects detected in this scene's authoring map.</p>
	{/if}
	<div class="lights-list">
		{#each emitterObjects as light (light.id)}
			<div class="light-item" class:enabled={light.is_emitter}>
				<label class="light-toggle">
					<input type="checkbox" checked={light.is_emitter ?? false}
						onchange={async (e) => onToggleEmitter(light.id, (e.currentTarget as HTMLInputElement).checked)} />
					<span class="light-label">{light.label || light.id}</span>
				</label>
				{#if light.is_emitter}
					<input type="range" class="light-intensity" min="0.1" max="20" step="0.1"
						value={light.emitter_intensity ?? 1.0}
						title={`Intensity: ${(light.emitter_intensity ?? 1.0).toFixed(1)}×`}
						oninput={(e) => onSetEmitterIntensity(light.id, Number((e.currentTarget as HTMLInputElement).value))}
					/>
				{/if}
			</div>
			{#if light.is_emitter}
				{@const kelvin = light.emitter_radiance ? rgbToKelvinApprox(light.emitter_radiance) : 3000}
				{@const swatch = kelvinToRgb(kelvin)}
				<div class="light-aux-row">
					<span class="light-color-swatch"
						style:background={`rgb(${Math.round(swatch[0] * 255)},${Math.round(swatch[1] * 255)},${Math.round(swatch[2] * 255)})`}
						title={`${kelvin}K`}></span>
					<input type="range" class="light-temp" min="1500" max="10000" step="100"
						value={kelvin}
						title={`Color temp: ${kelvin}K`}
						oninput={(e) => {
							const k = Number((e.currentTarget as HTMLInputElement).value);
							onSetEmitterRadiance(light.id, kelvinToRgb(k));
						}}
					/>
					<label class="light-height-label">h<input type="number" class="light-height" min="0.05" max="4" step="0.05"
						value={Number(light.geometry?.base_height_m ?? 0)}
						title="Height (base_height_m)"
						oninput={(e) => {
							const h = Math.max(0, Math.min(8, Number((e.currentTarget as HTMLInputElement).value)));
							onSetEmitterHeight(light.id, h);
						}}
					/></label>
				</div>
			{/if}
		{:else}
			<p class="probe-empty">Toggle "Use as light source" on individual landmarks (or use Enable all above).</p>
		{/each}
	</div>
	<div class="sync-actions">
		<button class="button button-subtle" disabled={!caps.saveLights.enabled} title={caps.saveLights.reason} onclick={onSave}>Save</button>
	</div>
</section>

<style>
	.emitter-bulk-row {
			display: flex;
			align-items: center;
			gap: var(--space-2);
			font-size: var(--font-size-sm);
		}

	.ceiling-bulk-row { flex-wrap: wrap; padding: 4px 6px; border-radius: var(--radius-sm); background: var(--warning-soft); }

	.ceiling-icon { font-size: var(--font-size-sm); }

	.ceiling-dim { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 120px; }

	.ceiling-dim input[type='range'] { flex: 1; }

	.ceiling-dim-val { min-width: 34px; text-align: right; font-variant-numeric: tabular-nums; }

	.lights-panel { display: grid; gap: var(--space-2); }

	.lights-list { display: grid; gap: 4px; max-height: 360px; overflow-y: auto; padding-right: 4px; }

	.light-item { display: grid; grid-template-columns: 1fr 90px; gap: 6px; align-items: center; padding: 4px 6px; border-radius: var(--radius-sm); background: var(--surface-1); font-size: var(--font-size-xs); }

	.light-item.enabled { background: var(--warning-soft); }

	.light-toggle { display: flex; gap: 6px; align-items: center; overflow: hidden; }

	.light-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	.light-intensity { width: 100%; }

	.light-aux-row { grid-column: 1 / -1; display: grid; grid-template-columns: 20px 1fr 70px; gap: 6px; align-items: center; padding: 2px 6px 4px; font-size: var(--font-size-xs); }

	.light-color-swatch { width: 18px; height: 18px; border-radius: 50%; border: 1px solid var(--border); }

	.light-temp { width: 100%; }

	.light-height-label { display: flex; align-items: center; gap: 2px; }

	.light-height { width: 50px; padding: 1px 4px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 11px; }
</style>
