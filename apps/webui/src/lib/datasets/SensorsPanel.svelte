<script lang="ts">
	import {
		POLAR_PREVIEW_MODALITIES,
		sensorRenderChipLabel,
		formatRigVec,
		formatResolution,
		formatRenderSpp,
		headingHasSensorModality,
		isPolarRenderModality,
	} from '$lib/datasets/sensorHelpers';
	import { opticalNavObservationModalityUrl } from '$lib/api';

	interface Props {
		renderSceneSynced: boolean;
		loading: boolean;
		selectedProjectId: string;
		hasScene: boolean;
		hasGraph: boolean;
		globalCameraRig: any;
		globalCameraRigStatus: string;
		globalCameraRigError: string;
		rigSensorOptions: any[];
		activeRigSensorId: string;
		frustumMode: string;
		placingSensor: boolean;
		selectedSensorNodeId: string;
		selectedSensorNode: any;
		selectedCustomSensorNode: any;
		sceneId: string;
		sceneStateText: string;
		cameraSpecText: string;
		renderConfig: any;
		renderConfigError: string;
		observationScan: any;
		activeModalityTab: string;
		sensorRenderResult: any;
		renderingViewpoint: boolean;
		onLoadGlobalCameraRig: () => void;
		onSyncRenderScene: () => void;
		onSelectRigRenderSensor: (id: string) => void;
		onLoadRenderConfig: () => void;
		onOptionalJson: (text: string) => any;
		onRenderSensorViewpoint: () => void;
		onRenderEpisodes: () => void;
		onRenderEpisodeNodes?: () => void;
		renderMissingOnly?: boolean;
		onSetRenderMissingOnly?: (value: boolean) => void;
		episodeNodesAvailable?: boolean;
		episodePathNodeCount?: number;
		headingsPerNode?: number;
		sensorFindQuery?: string;
		sensorFindError?: string;
		graphNodeCount?: number;
		onFindSensor?: () => void;
		onRefreshBatch: () => void;
		onRemoveCustomSensor: (id: string) => void;
		onCustomSensorHeadingChange: (id: string, deg: number) => void;
	}
	let {
		renderSceneSynced, loading, selectedProjectId, hasScene, hasGraph,
		globalCameraRig, globalCameraRigStatus, globalCameraRigError,
		rigSensorOptions, activeRigSensorId,
		frustumMode = $bindable<string>(),
		placingSensor = $bindable<boolean>(),
		selectedSensorNodeId = $bindable<string>(),
		selectedSensorNode, selectedCustomSensorNode,
		sceneId, sceneStateText, cameraSpecText,
		renderConfig, renderConfigError,
		observationScan, activeModalityTab = $bindable<string>(),
		sensorRenderResult, renderingViewpoint,
		onLoadGlobalCameraRig, onSyncRenderScene, onSelectRigRenderSensor,
		onLoadRenderConfig, onOptionalJson,
		onRenderSensorViewpoint, onRenderEpisodes, onRenderEpisodeNodes,
		renderMissingOnly = true, onSetRenderMissingOnly,
		episodeNodesAvailable = false, episodePathNodeCount = 0, headingsPerNode = 0,
		sensorFindQuery = $bindable(''), sensorFindError = '', graphNodeCount = 0, onFindSensor,
		onRefreshBatch,
		onRemoveCustomSensor, onCustomSensorHeadingChange,
	}: Props = $props();

	const activeRigSensorOption = $derived(rigSensorOptions.find((item: any) => item.sensor_id === activeRigSensorId) ?? rigSensorOptions[0] ?? null);
	const isActivePolarSensor = $derived.by(() => {
		const sensor = activeRigSensorOption?.sensor ?? {};
		const sensorType = String(sensor?.canonical_sensor_type ?? sensor?.sensor_type ?? '').toLowerCase();
		const defaultModality = String(activeRigSensorOption?.render_modality ?? 'rgb');
		const canonical = Array.isArray(sensor?.modalities) ? sensor.modalities : [];
		return sensorType === 'polar_camera'
			|| isPolarRenderModality(defaultModality)
			|| canonical.some((item: unknown) => isPolarRenderModality(item));
	});
	const visibleObservationModality = $derived(
		isActivePolarSensor && isPolarRenderModality(activeModalityTab)
			? activeModalityTab
			: String(activeRigSensorOption?.render_modality ?? activeModalityTab ?? 'rgb')
	);
</script>

<div class="map-float-inspector sensor-panel">
	<!-- Find a viewpoint/sensor node by number and fly the editor camera to it. -->
	<div class="sensor-find">
		<input
			type="text"
			placeholder="Find sensor # (e.g. 92 or vp_000092)"
			bind:value={sensorFindQuery}
			onkeydown={(e) => { if (e.key === 'Enter') onFindSensor?.(); }}
			title={graphNodeCount ? `${graphNodeCount} viewpoints` : 'Build the viewpoint graph first'}
		/>
		<button class="button button-subtle" disabled={!hasGraph} onclick={() => onFindSensor?.()}>Find</button>
	</div>
	{#if sensorFindError}<div class="sensor-find-error">{sensorFindError}</div>{/if}

	{#if !renderSceneSynced}
		<div class="sensor-sync-warning">
			<span>Render scene not synced</span>
			<button class="button button-subtle" disabled={loading || !selectedProjectId || !hasScene} onclick={onSyncRenderScene} style="display:none">Sync Render Scene</button>
		</div>
	{/if}

	<div class="camera-rig-panel">
		<div class="rail-title">Robot Camera Rig</div>
		<div class="render-profile-row">
			<span class="chip-dim">{globalCameraRig?.base_frame ?? 'base_link'}</span>
			<a class="button button-subtle" href="/camera_rig">Open Camera Rig Editor</a>
			<button class="button button-subtle" disabled={loading} onclick={onLoadGlobalCameraRig}>Reload</button>
		</div>
		<div class="sensor-sync-warning camera-rig-readonly-note">
			<span>{globalCameraRigStatus}</span>
			{#if globalCameraRigError}<small>{globalCameraRigError}</small>{/if}
		</div>
		{#each rigSensorOptions as option, i}
			{@const sensor = option.sensor}
			<details class="rig-sensor-card" open={i === 0 || activeRigSensorId === option.sensor_id}>
				<summary>{option.label} · {option.modality}</summary>
				<div class="geometry-grid rig-readonly-grid">
					<div class="readonly-field"><span>ID</span><strong>{option.sensor_id}</strong></div>
					<div class="readonly-field"><span>Render</span><strong>{sensorRenderChipLabel(option)}</strong></div>
					<div class="readonly-field"><span>Type</span><strong>{sensor.canonical_sensor_type ?? sensor.modality ?? 'rgb'}</strong></div>
					<div class="readonly-field"><span>Parent</span><strong>{sensor.mount?.parent_frame ?? globalCameraRig?.base_frame ?? 'base_link'}</strong></div>
					<div class="readonly-field"><span>XYZ m</span><strong>{formatRigVec(sensor.mount?.xyz_m)}</strong></div>
					<div class="readonly-field"><span>RPY deg</span><strong>{formatRigVec(sensor.mount?.rpy_deg, 1)}</strong></div>
					<div class="readonly-field"><span>FOV</span><strong>{Number(sensor.fov_deg ?? sensor.intrinsics?.fov_h_deg ?? 0).toFixed(0)}°</strong></div>
					<div class="readonly-field"><span>Resolution</span><strong>{formatResolution(sensor.resolution ?? sensor.intrinsics?.resolution)}</strong></div>
					<div class="readonly-field wide"><span>SPP</span><strong>{formatRenderSpp(sensor)}</strong></div>
				</div>
			</details>
		{/each}
	</div>

	<div class="sensor-rays-row">
		<span class="sensor-rays-label">Sensor Rays</span>
		<select class="sensor-rays-select" value={frustumMode} onchange={(e) => frustumMode = (e.target as HTMLSelectElement).value}>
			<option value="none">None</option>
			<option value="view-aligned">View-aligned</option>
			<option value="selected">Selected only</option>
		</select>
	</div>

	<div class="sensor-add-bar">
		<button
			class="button full"
			class:button-primary={placingSensor}
			class:button-subtle={!placingSensor}
			onclick={() => { placingSensor = !placingSensor; selectedSensorNodeId = ''; }}
		>
			{placingSensor ? 'Click on floor to place...' : '+ Add Sensor Camera'}
		</button>
	</div>

	{#if selectedSensorNode}
		<div class="panel-label">
			{selectedSensorNode.isCustom ? 'Custom Camera' : 'Graph Viewpoint'}
		</div>
		<div class="sensor-node-id">{selectedSensorNodeId}</div>
		<div class="sensor-pos">x={selectedSensorNode.position?.[0]?.toFixed(2)} z={selectedSensorNode.position?.[1]?.toFixed(2)}</div>
		{#if selectedCustomSensorNode}
			<label class="sensor-heading-label">
				<span>Heading {selectedCustomSensorNode.headingDeg}°</span>
				<input type="range" min="0" max="359" step="5"
					value={selectedCustomSensorNode.headingDeg}
					oninput={(e) => onCustomSensorHeadingChange(selectedCustomSensorNode.id, Number((e.target as HTMLInputElement).value))}
				/>
			</label>
			<button class="button button-subtle full sensor-del"
				onclick={() => { onRemoveCustomSensor(selectedSensorNodeId); selectedSensorNodeId = ''; }}>
				Remove
			</button>
		{/if}
		<div class="modality-tabs rig-derived-tabs" title="Derived from Robot Camera Rig sensors">
			{#each rigSensorOptions as option}
				<button class:active-tab={activeRigSensorId === option.sensor_id} onclick={() => onSelectRigRenderSensor(option.sensor_id)}>
					<span>{option.label}</span>
					<small>{sensorRenderChipLabel(option)}</small>
				</button>
			{/each}
		</div>
		{#if isActivePolarSensor}
			<div class="polar-preview-mode-row" aria-label="Polarization preview modality">
				{#each POLAR_PREVIEW_MODALITIES as modality}
					<button
						type="button"
						class:active={visibleObservationModality === modality.id}
						onclick={() => activeModalityTab = modality.id}
						title={`Show ${modality.label} polarization preview products`}
					>
						{modality.label}
					</button>
				{/each}
			</div>
		{/if}
		<div class="sensor-config-row">
			{#if sceneStateText.trim() && cameraSpecText.trim()}
				<span class="chip-ok">Config ready ({renderConfig?.source ?? 'custom'})</span>
			{:else}
				<span class="chip-warn" title={renderConfigError || undefined}>No render config{renderConfigError ? ' ⚠' : ''}</span>
			{/if}
			<button class="button button-subtle" onclick={onLoadRenderConfig} title="Auto-load render config from scene catalog">Load</button>
		</div>
		{#if sceneStateText.trim()}
			{@const _ref = (onOptionalJson(sceneStateText) as any)?.mitsuba_scene_ref}
			{#if _ref}
				<div class="config-scene-ref" title={_ref}>Scene XML: {_ref.split('/').slice(-2).join('/')}</div>
			{/if}
		{:else if renderConfigError}
			<div class="config-scene-ref config-scene-error">{renderConfigError}</div>
		{/if}
		{@const vpScan2 = observationScan?.viewpoints?.[selectedSensorNodeId]}
		{@const vpCompleted2 = vpScan2?.completed ?? 0}
		{@const vpTotal2 = vpScan2?.total ?? 0}
		{#if vpTotal2 > 0}
			<div class="sensor-progress">{vpCompleted2}/{vpTotal2} rendered</div>
		{/if}
		{#if vpScan2?.headings && Object.keys(vpScan2.headings).length > 0}
			<div class="obs-heading-gallery">
				{#each Object.entries(vpScan2.headings).sort(([a], [b]) => a.localeCompare(b)) as [hid, hinfo]}
					{@const hdata = hinfo as any}
					{@const hasModality = headingHasSensorModality(hdata, visibleObservationModality, activeRigSensorId)}
					{#if hasModality}
						<img class="obs-thumb" src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, selectedSensorNodeId, hid, visibleObservationModality, activeRigSensorId)} alt={`${hid} ${visibleObservationModality}`} title={`${hid} · ${activeRigSensorId || 'legacy'} · ${visibleObservationModality}`} loading="lazy" />
					{:else}
						<div class="obs-thumb obs-thumb-empty" title={`${hid} · ${visibleObservationModality} not rendered`}><span>{parseInt(hid.replace('h_',''))||0}°</span></div>
					{/if}
				{/each}
			</div>
		{/if}
		{#if sensorRenderResult}
			<div class="sensor-result">
				<span class="chip-ok">Batch {sensorRenderResult.batch_id?.slice(0,8)}...</span>
				<button class="button button-subtle" onclick={onRefreshBatch}>Refresh</button>
			</div>
		{/if}
		<button class="button button-primary full"
			disabled={renderingViewpoint || !selectedProjectId || !renderSceneSynced || (!selectedCustomSensorNode && !hasGraph) || (!sceneStateText.trim() || !cameraSpecText.trim())}
			onclick={onRenderSensorViewpoint}>
			{renderingViewpoint ? 'Sweeping...' : 'Graph Sweep · this viewpoint'}
		</button>
		<label class="sensor-resume-row" title="Skip viewpoints/headings that already have consolidated outputs or a completed bridge-job manifest.">
			<input type="checkbox" checked={renderMissingOnly} onchange={(e) => onSetRenderMissingOnly?.((e.currentTarget as HTMLInputElement).checked)} />
			<span>Only missing renders</span>
		</label>
		<button class="button button-subtle full"
			disabled={loading || !selectedProjectId || !renderSceneSynced || !hasGraph}
			onclick={onRenderEpisodes}>
			{renderMissingOnly ? 'Graph Sweep · missing only' : 'Graph Sweep · all viewpoints'}
		</button>
		{#if onRenderEpisodeNodes}
			<button class="button button-subtle full"
				disabled={loading || !selectedProjectId || !renderSceneSynced || !hasGraph || !episodeNodesAvailable}
				title={!episodeNodesAvailable ? 'Select a graph-based episode with path nodes' : ''}
				onclick={onRenderEpisodeNodes}>
				{#if episodeNodesAvailable && episodePathNodeCount > 0}
					Graph Sweep · selected episode path ({episodePathNodeCount}{headingsPerNode > 0 ? ` × ${headingsPerNode}` : ''} jobs)
				{:else}
					Graph Sweep · selected episode path
				{/if}
			</button>
		{/if}
	{:else}
		<div class="sensor-hint">Click a viewpoint (blue dot) to select it</div>
	{/if}
</div>

<style>
	/* Sensor panel */
	.sensor-sync-warning {
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 6px;
			padding: 6px 8px;
			background: rgba(251,191,36,0.12);
			border: 1px solid rgba(251,191,36,0.4);
			border-radius: var(--radius-sm);
			font-size: var(--font-size-xs);
			margin-bottom: 8px;
			color: var(--tool-hazard);
		}

	.sensor-sync-warning.camera-rig-readonly-note {
			align-items: flex-start;
			flex-direction: column;
			background: rgba(59,130,246,0.08);
			border-color: rgba(59,130,246,0.24);
			color: #1e40af;
		}

	.sensor-sync-warning.camera-rig-readonly-note small {
			color: #991b1b;
		}

	.sensor-panel .camera-rig-panel {
			display: grid;
			gap: 8px;
			margin-bottom: 10px;
		}

	.sensor-panel .rig-sensor-card {
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: var(--surface-1);
			padding: 6px 8px;
		}

	.sensor-panel .rig-sensor-card summary {
			cursor: pointer;
			font-weight: 700;
			color: var(--text-primary);
		}

	.sensor-panel .rig-readonly-grid {
			margin-top: 6px;
		}

	.sensor-panel .readonly-field {
			display: grid;
			gap: 2px;
			min-width: 0;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: var(--surface-2);
			padding: 6px 7px;
		}

	.sensor-panel .readonly-field.wide {
			grid-column: 1 / -1;
		}

	.sensor-panel .readonly-field span {
			color: var(--text-muted);
			font-size: 10px;
			text-transform: uppercase;
		}

	.sensor-panel .readonly-field strong {
			color: var(--text-primary);
			font-size: 11px;
			font-weight: 700;
			overflow-wrap: anywhere;
		}

	.sensor-find { display: flex; gap: 6px; margin: 0 0 6px; }
	.sensor-find input { flex: 1; min-width: 0; padding: 4px 8px; font-size: var(--font-size-xs); border: 1px solid var(--border); border-radius: 6px; }
	.sensor-find-error { font-size: 11px; color: #dc2626; margin: -2px 0 6px; }

	.sensor-panel .sensor-node-id { font-family: monospace; font-size: var(--font-size-xs); color: var(--text-muted); word-break: break-all; }

	.sensor-panel .sensor-pos { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }

	.sensor-panel .modality-tabs { display: flex; gap: 4px; flex-wrap: wrap; }

	.sensor-panel .modality-tabs button {
			padding: 3px 8px; font-size: 11px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm);
			background: none; cursor: pointer; color: var(--text-muted);
		}

	.sensor-panel .rig-derived-tabs button {
			display: inline-flex; flex-direction: column; align-items: flex-start; gap: 2px; min-width: 112px;
		}

	.sensor-panel .rig-derived-tabs button small { font-size: 10px; opacity: 0.75; }

	.sensor-panel .modality-tabs button.active-tab { background: var(--accent); color: #fff; border-color: var(--accent); }

	.polar-preview-mode-row {
			display: grid;
			grid-template-columns: repeat(5, minmax(0, 1fr));
			gap: 4px;
			margin-top: 6px;
		}

	.polar-preview-mode-row button {
			min-width: 0;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: #fff;
			color: var(--text-secondary);
			padding: 5px 4px;
			font-size: 10px;
			font-weight: 700;
			cursor: pointer;
		}

	.polar-preview-mode-row button.active {
			border-color: #2563eb;
			background: #2563eb;
			color: #fff;
		}

	.sensor-panel .sensor-result { display: flex; align-items: center; gap: 6px; }

	.sensor-panel .sensor-progress { font-size: 11px; color: var(--text-muted); }

	.sensor-obs-header { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin: 4px 0; }

	.sensor-obs-header .button { font-size: 10px; padding: 2px 8px; }

	.sensor-panel .sensor-hint { font-size: var(--font-size-xs); color: var(--text-muted); padding: 12px 0; text-align: center; }

	.sensor-height-label { font-size: 11px; color: var(--text-muted); }

	.sensor-height-input { width: 60px; padding: 2px 4px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 11px; text-align: right; }

	.obs-heading-gallery { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3px; margin: 6px 0; }

	.obs-thumb { width: 100%; aspect-ratio: 4/3; object-fit: cover; border-radius: 3px; border: 1px solid var(--border); cursor: pointer; }

	.obs-thumb-empty { display: flex; align-items: center; justify-content: center; background: var(--surface-2, #f1f5f9); border-radius: 3px; border: 1px solid var(--border); }

	.obs-thumb-empty span { font-size: 9px; color: var(--text-muted); }

	.sensor-panel .full { width: 100%; }

	.sensor-panel .sensor-add-bar { margin-bottom: 8px; }

	.sensor-panel .sensor-rays-row { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-bottom: 8px; }

	.sensor-panel .sensor-rays-label { font-size: 11px; color: var(--text-muted); white-space: nowrap; }

	.sensor-panel .sensor-rays-select { flex: 1; font-size: 11px; padding: 2px 4px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 4px; color: var(--text-primary); }

	.sensor-panel .sensor-heading-label { display: flex; flex-direction: column; gap: 2px; font-size: 11px; color: var(--text-muted); margin: 6px 0; }

	.sensor-panel .sensor-heading-label input[type=range] { width: 100%; }

	.sensor-panel .sensor-del { margin-top: 2px; color: var(--text-muted); }

	.sensor-panel .sensor-config-row { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin: 6px 0; }
</style>
