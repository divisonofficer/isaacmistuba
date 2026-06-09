<script lang="ts">
	import { kelvinToRgb, rgbToKelvinApprox } from '$lib/datasets/materialHelpers';

	interface Props {
		authoringMap: any;
		detectedEmitterIds: Set<string>;
		detectedEmitterCount: number;
		enabledEmitterCount: number;
		hasScene: boolean;
		loading: boolean;
		onEnableAll: () => void;
		onDisableAll: () => void;
		onToggleEmitter: (lightId: string, isOn: boolean) => Promise<void>;
		onSetEmitterIntensity: (lightId: string, intensity: number) => void;
		onSetEmitterRadiance: (lightId: string, rgb: [number, number, number]) => void;
		onSetEmitterHeight: (lightId: string, height: number) => void;
		onSave: () => void;
	}

	let {
		authoringMap, detectedEmitterIds, detectedEmitterCount, enabledEmitterCount,
		hasScene, loading,
		onEnableAll, onDisableAll, onToggleEmitter,
		onSetEmitterIntensity, onSetEmitterRadiance, onSetEmitterHeight, onSave,
	}: Props = $props();

	const emitterObjects = $derived(
		(authoringMap?.objects ?? []).filter((o: any) => detectedEmitterIds.has(o.id) || o.is_emitter)
	);
</script>

<section class="rail-section rail-tool-panel lights-panel">
	<div class="rail-title">Lights</div>
	{#if detectedEmitterCount > 0}
		<div class="emitter-bulk-row">
			<span>{enabledEmitterCount}/{detectedEmitterCount} fixtures enabled</span>
			<button class="button button-subtle" disabled={enabledEmitterCount >= detectedEmitterCount} onclick={onEnableAll}>Enable all</button>
			{#if enabledEmitterCount > 0}
				<button class="button button-subtle" onclick={onDisableAll}>Disable all</button>
			{/if}
		</div>
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
		<button class="button button-subtle" disabled={!hasScene || loading} onclick={onSave}>Save</button>
	</div>
</section>

<style>
	.emitter-bulk-row {
			display: flex;
			align-items: center;
			gap: var(--space-2);
			font-size: var(--font-size-sm);
		}

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
