<script lang="ts">
	import {
		sensorRenderChipLabel,
		formatRigVec,
		formatResolution,
		formatRenderSpp,
		headingHasSensorModality,
	} from '$lib/datasets/sensorHelpers';
	import { buildBatchJobGrid } from '$lib/datasets/batchHelpers';
	import { opticalNavObservationModalityUrl } from '$lib/api';

	interface Props {
		renderSceneSynced: boolean;
		globalCameraRig: any;
		globalCameraRigStatus: string;
		globalCameraRigError: string;
		rigSensorOptions: any[];
		activeRigSensorId: string;
		selectedSensorNode: any;
		selectedSensorNodeId: string;
		selectedCustomSensorNode: any;
		selectedSensorHeightM: number;
		sceneStateText: string;
		cameraSpecText: string;
		renderConfig: any;
		observationScan: any;
		graphBatch: any;
		sensorRenderResult: any;
		renderingViewpoint: boolean;
		placingSensor: boolean;
		frustumMode: string;
		ambientRadiance: number;
		activeModalityTab: string;
		activeRigSensorOption: any;
		rigMountHeightM: number;
		authoringMap: any;
		selectedProjectId: string;
		sceneId: string;
		loading: boolean;
		hasScene: boolean;
		hasGraph: boolean;
		renderSceneStats: any;
		renderSceneStatsLoading: boolean;
		showRoomShell: boolean;
		roomShell: any;
		editorObjectsCount: number;
		editorEmitterCount: number;
		editorMaterialCount: number;
		onLoadGlobalCameraRig: () => void;
		onSelectRigSensor: (sensorId: string) => void;
		onSetFrustumMode: (mode: string) => void;
		onTogglePlacingSensor: () => void;
		onRemoveCustomSensor: (id: string) => void;
		onCustomSensorHeadingChange: (id: string, deg: number) => void;
		onLoadRenderConfig: () => void;
		onSetSensorHeight: (h: number) => void;
		onSetAmbientRadiance: (v: number) => void;
		onClearNodeObservations: (id: string) => void;
		onClearAllObservations: () => void;
		onRenderViewpoint: () => void;
		onRenderEpisodes: () => void;
		onRenderEpisodeNodes?: () => void;
		renderMissingOnly?: boolean;
		onSetRenderMissingOnly?: (value: boolean) => void;
		episodeNodesAvailable?: boolean;
		episodePathNodeCount?: number;
		headingsPerNode?: number;
		onRefreshBatch: () => void;
		onRefreshStats: () => void;
		onSetShowRoomShell: (v: boolean) => void;
	}

	let {
		renderSceneSynced, globalCameraRig, globalCameraRigStatus, globalCameraRigError,
		rigSensorOptions, activeRigSensorId, selectedSensorNode, selectedSensorNodeId,
		selectedCustomSensorNode, selectedSensorHeightM,
		sceneStateText, cameraSpecText, renderConfig,
		observationScan, graphBatch, sensorRenderResult, renderingViewpoint,
		placingSensor, frustumMode, ambientRadiance, activeModalityTab,
		activeRigSensorOption, rigMountHeightM, authoringMap,
		selectedProjectId, sceneId, loading, hasScene, hasGraph,
		renderSceneStats, renderSceneStatsLoading, showRoomShell, roomShell,
		editorObjectsCount, editorEmitterCount, editorMaterialCount,
		onLoadGlobalCameraRig, onSelectRigSensor, onSetFrustumMode, onTogglePlacingSensor,
		onRemoveCustomSensor, onCustomSensorHeadingChange, onLoadRenderConfig,
		onSetSensorHeight, onSetAmbientRadiance, onClearNodeObservations, onClearAllObservations,
		onRenderViewpoint, onRenderEpisodes, onRenderEpisodeNodes,
		renderMissingOnly = true, onSetRenderMissingOnly,
		episodeNodesAvailable = false, episodePathNodeCount = 0, headingsPerNode = 0,
		onRefreshBatch, onRefreshStats, onSetShowRoomShell,
	}: Props = $props();

	const vpScan = $derived(observationScan?.viewpoints?.[selectedSensorNodeId]);
	const vpCompleted = $derived(
		vpScan?.completed ?? (graphBatch
			? (buildBatchJobGrid(graphBatch).rows.find((r: any) => r.nid === selectedSensorNodeId)?.cells?.filter((c: any) => c?.status?.status === 'completed')?.length ?? 0)
			: 0)
	);
	const vpTotal = $derived(vpScan?.total ?? graphBatch?.progress?.total ?? 0);
</script>

<section class="rail-section rail-tool-panel sensor-panel">
	<div class="rail-title">Sensor Render</div>
	{#if !renderSceneSynced}
		<div class="sensor-sync-warning">
			<span>Render scene not synced</span>
		</div>
	{/if}

	<div class="camera-rig-panel">
		<div class="rail-title">Robot Camera Rig</div>
		<div class="render-profile-row">
			<span class="chip-dim">{globalCameraRig?.base_frame ?? authoringMap?.camera_rig?.base_frame ?? 'base_link'}</span>
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
		<select class="sensor-rays-select" value={frustumMode} onchange={(e) => onSetFrustumMode((e.currentTarget as HTMLSelectElement).value)}>
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
			onclick={onTogglePlacingSensor}
		>
			{placingSensor ? 'Click on floor to place...' : '+ Add Sensor Camera'}
		</button>
	</div>

	{#if selectedSensorNode}
		<div class="rail-title">
			{(selectedSensorNode as any).isCustom ? 'Custom Camera' : 'Graph Viewpoint'}
		</div>
		<div class="sensor-node-id">{selectedSensorNodeId}</div>
		<div class="sensor-pos">x={selectedSensorNode.position?.[0]?.toFixed(2)} z={selectedSensorNode.position?.[1]?.toFixed(2)}</div>
		{#if selectedCustomSensorNode}
			<label class="sensor-heading-label">
				<span>Heading {selectedCustomSensorNode.headingDeg}°</span>
				<input type="range" min="0" max="359" step="5"
					value={selectedCustomSensorNode.headingDeg}
					oninput={(e) => onCustomSensorHeadingChange(selectedSensorNodeId, Number((e.currentTarget as HTMLInputElement).value))}
				/>
			</label>
			<button class="button button-subtle full sensor-del" onclick={() => onRemoveCustomSensor(selectedSensorNodeId)}>
				Remove
			</button>
		{/if}
		<div class="modality-tabs rig-derived-tabs" title="Derived from Robot Camera Rig sensors">
			{#each rigSensorOptions as option}
				<button class:active-tab={activeRigSensorId === option.sensor_id} onclick={() => onSelectRigSensor(option.sensor_id)}>
					<span>{option.label}</span>
					<small>{sensorRenderChipLabel(option)}</small>
				</button>
			{/each}
		</div>
		<div class="sensor-config-row">
			{#if sceneStateText.trim() && cameraSpecText.trim()}
				<span class="chip-ok">Config ready ({renderConfig?.source ?? 'custom'})</span>
			{:else}
				<span class="chip-warn">No render config</span>
			{/if}
			<button class="button button-subtle" onclick={onLoadRenderConfig} title="Auto-load render config from scene catalog">Load</button>
		</div>
		<div class="sensor-config-row">
			<label class="sensor-height-label" title={selectedSensorNodeId ? 'Per-viewpoint override (rig default = ' + rigMountHeightM.toFixed(2) + 'm)' : 'Rig defaults are read-only here. Edit them in /camera_rig.'}>
				Camera height (m) {selectedSensorNodeId ? `· ${selectedSensorNodeId}` : `· ${activeRigSensorOption?.label ?? 'rig sensor'}`}
			</label>
			<input type="number" class="sensor-height-input" min="0.05" max="8" step="0.05"
				value={selectedSensorHeightM}
				oninput={(e) => onSetSensorHeight(Number((e.currentTarget as HTMLInputElement).value))}
			/>
		</div>
		<div class="sensor-config-row">
			<label class="sensor-height-label">Ambient light</label>
			<input type="number" class="sensor-height-input" min="0" max="20" step="0.1"
				value={ambientRadiance}
				oninput={(e) => onSetAmbientRadiance(Number((e.currentTarget as HTMLInputElement).value))}
				title="Fallback constant radiance injected when the scene has no emitters"
			/>
		</div>
		{#if vpTotal > 0}
			<div class="sensor-obs-header">
				<span class="sensor-progress">{vpCompleted}/{vpTotal} rendered</span>
				{#if vpCompleted > 0}
					<button class="button button-subtle" onclick={() => onClearNodeObservations(selectedSensorNodeId)}>Clear</button>
				{/if}
			</div>
		{/if}
		{#if vpScan?.headings && Object.keys(vpScan.headings).length > 0}
			<div class="obs-heading-gallery">
				{#each Object.entries(vpScan.headings).sort(([a], [b]) => a.localeCompare(b)) as [hid, hinfo]}
					{@const hdata = hinfo as any}
					{@const hasModality = headingHasSensorModality(hdata, activeModalityTab)}
					{#if hasModality}
						<img
							class="obs-thumb"
							src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, selectedSensorNodeId, hid, activeModalityTab, activeRigSensorId)}
							alt={`${hid} ${activeModalityTab}`}
							title={`${hid} · ${activeRigSensorId || 'legacy'} · ${activeModalityTab}`}
							loading="lazy"
						/>
					{:else}
						<div class="obs-thumb obs-thumb-empty" title={`${hid} · ${activeModalityTab} not rendered`}>
							<span>{parseInt(hid.replace('h_', '')) || 0}°</span>
						</div>
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
			disabled={renderingViewpoint || !selectedProjectId || !renderSceneSynced || (!(selectedSensorNode as any).isCustom && !hasGraph) || (!sceneStateText.trim() || !cameraSpecText.trim())}
			onclick={onRenderViewpoint}>
			{renderingViewpoint ? 'Sweeping...' : 'Graph Sweep · this viewpoint'}
		</button>
		<label class="sensor-resume-row" title="Skip viewpoints/headings that already have consolidated outputs or a completed bridge-job manifest.">
			<input type="checkbox" checked={renderMissingOnly} onchange={(e) => onSetRenderMissingOnly?.((e.currentTarget as HTMLInputElement).checked)} />
			<span>Only missing renders</span>
		</label>
		<button class="button button-subtle full" disabled={loading || !selectedProjectId || !renderSceneSynced || !hasGraph} onclick={onRenderEpisodes}>
			{renderMissingOnly ? 'Graph Sweep · missing only' : 'Graph Sweep · all viewpoints'}
		</button>
		{#if onRenderEpisodeNodes}
			<button class="button button-subtle full"
				disabled={loading || !selectedProjectId || !renderSceneSynced || !hasGraph || !episodeNodesAvailable}
				title={!episodeNodesAvailable ? 'Select a graph-based episode with path nodes' : ''}
				onclick={onRenderEpisodeNodes}>
				{#if episodeNodesAvailable && episodePathNodeCount > 0}
					Graph Sweep · episode path ({episodePathNodeCount}{headingsPerNode > 0 ? ` × ${headingsPerNode}` : ''} jobs)
				{:else}
					Graph Sweep · episode path
				{/if}
			</button>
		{/if}
	{:else}
		<div class="sensor-hint">Click a viewpoint (blue dot) to select it</div>
		{#if observationScan?.viewpoints}
			{@const totalCompleted = Object.values(observationScan.viewpoints as Record<string, any>).reduce((s: number, vp: any) => s + (vp.completed ?? 0), 0)}
			{@const totalHeadings = Object.values(observationScan.viewpoints as Record<string, any>).reduce((s: number, vp: any) => s + (vp.total ?? 0), 0)}
			{#if totalHeadings > 0}
				<div class="sensor-obs-header">
					<span class="sensor-progress">{totalCompleted}/{totalHeadings} total renders</span>
					{#if totalCompleted > 0}
						<button class="button button-subtle" onclick={onClearAllObservations}>Clear all</button>
					{/if}
				</div>
			{/if}
		{/if}
	{/if}
</section>

<section class="rail-section rail-tool-panel sync-inspector">
	<div class="rail-title">Sync Inspector</div>
	<div class="sync-row"><span>Authoring objects</span><span>{editorObjectsCount}</span></div>
	<div class="sync-row"><span>Render shapes (XML)</span><span>{renderSceneStats?.shape_count ?? '—'}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.exists && renderSceneStats.obj_shape_count === 0 && editorObjectsCount > 0}>
		<span>Real USD meshes (OBJ)</span><span>{renderSceneStats?.obj_shape_count ?? '—'}</span>
	</div>
	<div class="sync-row"><span>Cube fallbacks</span><span>{renderSceneStats?.cube_shape_count ?? '—'}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.exists && editorObjectsCount > 0 && renderSceneStats.shape_count < editorObjectsCount}>
		<span>Δ object mismatch</span>
		<span>{renderSceneStats?.shape_count != null ? renderSceneStats.shape_count - editorObjectsCount : '—'}</span>
	</div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>is_emitter=true objects</span><span>{editorEmitterCount}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.exists && renderSceneStats.area_emitter_count !== editorEmitterCount}>
		<span>Area emitters (XML)</span><span>{renderSceneStats?.area_emitter_count ?? '—'}</span>
	</div>
	<div class="sync-row"><span>Environment (envmap)</span><span>{renderSceneStats?.envmap_count ?? '—'}</span></div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>Authoring materials</span><span>{editorMaterialCount}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.raw_hpbrdf_refs > 0}>
		<span>Raw .hpbrdf refs (heavy)</span><span>{renderSceneStats?.raw_hpbrdf_refs ?? '—'}</span>
	</div>
	<div class="sync-row"><span>Channel-split refs</span><span>{renderSceneStats?.channel_split_refs ?? '—'}</span></div>
	<div class="sync-row"><span>Measured BSDFs</span><span>{renderSceneStats?.measured_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Analytic BSDFs</span><span>{renderSceneStats?.analytic_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Diffuse-like analytic</span><span>{renderSceneStats?.diffuse_like_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Specular analytic</span><span>{renderSceneStats?.specular_like_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Measured polarized BSDFs</span><span>{renderSceneStats?.measured_polarized_count ?? '—'}</span></div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>Active rig</span><span>{authoringMap?.camera_rig?.rig_id ?? '—'}</span></div>
	<div class="sync-row"><span>Rig mount height</span><span>{rigMountHeightM.toFixed(2)} m</span></div>
	<div class="sync-row"><span>Ceiling height</span><span>{Number(authoringMap?.settings?.default_wall_height_m ?? 2.4).toFixed(2)} m</span></div>
	<div class="sync-row">
		<label class="footprint-toggle">
			<input type="checkbox" checked={showRoomShell} onchange={(e) => onSetShowRoomShell((e.currentTarget as HTMLInputElement).checked)} />
			Show auto room shell
		</label>
		<span>{roomShell?.shapes?.length ?? 0} shapes</span>
	</div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>XML file</span><span class="mono">{renderSceneStats?.path ? renderSceneStats.path.split('/').slice(-2).join('/') : 'not generated'}</span></div>
	<div class="sync-row"><span>XML size</span><span>{renderSceneStats?.size_bytes != null ? Math.round(renderSceneStats.size_bytes / 1024) + ' KB' : '—'}</span></div>
	<div class="sync-row"><span>Last sync</span><span class="mono">{renderSceneStats?.modified_at?.slice(0, 19).replace('T', ' ') ?? '—'}</span></div>
	<div class="sync-actions">
		<button class="button button-subtle" disabled={renderSceneStatsLoading} onclick={onRefreshStats}>
			{renderSceneStatsLoading ? 'Loading…' : 'Refresh stats'}
		</button>
	</div>
</section>

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

	/* Sync Inspector — mirrored from RailPreviewTab so the same component used in
	   this tab actually renders with spacing/dividers. Svelte CSS is component-scoped
	   so styles from the other file don't apply here. */
	.sync-inspector { display: grid; gap: 6px; }
	.sync-row { display: flex; justify-content: space-between; gap: 10px; font-size: var(--font-size-xs, 11px); padding: 2px 0; }
	.sync-row.warn { color: var(--danger, #dc2626); font-weight: 600; }
	.sync-row .mono { font-family: monospace; max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.sync-divider { height: 1px; background: var(--border, #e5e7eb); margin: 4px 0; }
	.sync-actions { display: flex; gap: var(--space-2, 6px); margin-top: var(--space-2, 6px); }
	.footprint-toggle { display: flex; align-items: center; gap: 6px; font-size: var(--font-size-xs, 11px); cursor: pointer; }
	.footprint-toggle input { margin: 0; }
</style>
