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
	import { buildBatchJobGrid } from '$lib/datasets/batchHelpers';
	import { opticalNavObservationModalityUrl } from '$lib/api';
	import type { Capabilities } from '$lib/datasets/capabilityHelpers';

	interface Props {
		caps: Capabilities;
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
		activeCameraFrustum: any;
		activeRenderModality: string;
		hotCameraPose: any;
		previewBandMode: string;
		previewMeasuredScope: string;
		probeRendering: boolean;
		probeError: string;
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
		onRunProbe: () => void;
		onRenderEpisodes: () => void;
		onRenderEpisodeNodes?: () => void;
		renderVariant?: 'base' | 'perturbed' | 'both';
		perturbationEnabled?: boolean;
		perturbedRenderReady?: boolean;
		perturbedRenderStale?: boolean;
		onSetRenderVariant?: (v: 'base' | 'perturbed' | 'both') => void;
		onSetPreviewBandMode: (v: string) => void;
		onSetPreviewMeasuredScope: (v: string) => void;
		onSetActiveModalityTab?: (v: string) => void;
		selectedRigSensorIds?: string[];
		onToggleRigSweepSensor?: (sensorId: string) => void;
		onSetRigSweepSensors?: (sensorIds: string[]) => void;
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
		caps,
		renderSceneSynced, globalCameraRig, globalCameraRigStatus, globalCameraRigError,
		rigSensorOptions, activeRigSensorId, selectedSensorNode, selectedSensorNodeId,
		selectedCustomSensorNode, selectedSensorHeightM,
		sceneStateText, cameraSpecText, renderConfig,
		observationScan, graphBatch, sensorRenderResult, renderingViewpoint,
		placingSensor, frustumMode, ambientRadiance, activeModalityTab,
		activeRigSensorOption, activeCameraFrustum, activeRenderModality,
		hotCameraPose, previewBandMode, previewMeasuredScope,
		probeRendering, probeError, rigMountHeightM, authoringMap,
		selectedProjectId, sceneId, loading, hasScene, hasGraph,
		renderSceneStats, renderSceneStatsLoading, showRoomShell, roomShell,
		editorObjectsCount, editorEmitterCount, editorMaterialCount,
		onLoadGlobalCameraRig, onSelectRigSensor, onSetFrustumMode, onTogglePlacingSensor,
		onRemoveCustomSensor, onCustomSensorHeadingChange, onLoadRenderConfig,
		onSetSensorHeight, onSetAmbientRadiance, onClearNodeObservations, onClearAllObservations,
		onRenderViewpoint, onRunProbe, onRenderEpisodes, onRenderEpisodeNodes,
		renderVariant = 'base', perturbationEnabled = false,
		perturbedRenderReady = false, perturbedRenderStale = false, onSetRenderVariant,
		onSetPreviewBandMode, onSetPreviewMeasuredScope, onSetActiveModalityTab,
		selectedRigSensorIds = [], onToggleRigSweepSensor, onSetRigSweepSensors,
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
	const isActivePolarSensor = $derived.by(() => {
		const sensor = activeRigSensorOption?.sensor ?? {};
		const sensorType = String(sensor?.canonical_sensor_type ?? sensor?.sensor_type ?? '').toLowerCase();
		const canonical = Array.isArray(sensor?.modalities) ? sensor.modalities : [];
		return sensorType === 'polar_camera'
			|| isPolarRenderModality(activeRenderModality)
			|| canonical.some((item: unknown) => isPolarRenderModality(item));
	});
	const visibleObservationModality = $derived(
		isActivePolarSensor && isPolarRenderModality(activeModalityTab)
			? activeModalityTab
			: activeRenderModality
	);
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
		<div class="rig-sensor-toolbar">
			<button class="button button-subtle" onclick={() => onSetRigSweepSensors?.(rigSensorOptions.map((option) => String(option.sensor_id)))}>
				All active
			</button>
			<button class="button button-subtle" onclick={() => onSetRigSweepSensors?.(activeRigSensorId ? [activeRigSensorId] : [])}>
				Off
			</button>
		</div>
		<div class="rig-sensor-list">
			{#each rigSensorOptions as option}
				{@const sensor = option.sensor}
				<div class="rig-sensor-card">
					<button
						class:active-tab={activeRigSensorId === option.sensor_id}
						class:selected-tab={selectedRigSensorIds.includes(String(option.sensor_id))}
						onclick={() => onToggleRigSweepSensor ? onToggleRigSweepSensor(String(option.sensor_id)) : onSelectRigSensor(String(option.sensor_id))}
					>
						<span>{option.label} · {option.modality}</span>
						<small>{selectedRigSensorIds.includes(String(option.sensor_id)) ? 'sweep on' : 'sweep off'}</small>
					</button>
					<div class="rig-sensor-tooltip" role="tooltip">
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
					</div>
				</div>
			{/each}
		</div>
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

	<div class="sensor-preview-card">
		<div class="sensor-preview-head">
			<div class="rail-title">Hot Camera Preview</div>
			<span class="chip-dim">{activeRigSensorId || 'rig sensor'}</span>
		</div>
		<div class="sensor-preview-meta">
			<span>{activeRigSensorOption?.label ?? activeRigSensorId ?? 'default'}</span>
			<span>{visibleObservationModality}</span>
			<span>{Number(activeCameraFrustum?.fov_deg ?? 70).toFixed(0)}°</span>
			<span>{rigMountHeightM.toFixed(2)} m</span>
		</div>
		{#if isActivePolarSensor}
			<div class="polar-preview-mode-row" aria-label="Polarization preview modality">
				{#each POLAR_PREVIEW_MODALITIES as modality}
					<button
						type="button"
						class:active={visibleObservationModality === modality.id}
						onclick={() => onSetActiveModalityTab?.(modality.id)}
						title={`Show ${modality.label} polarization preview products`}
					>
						{modality.label}
					</button>
				{/each}
			</div>
		{/if}
		{#if hotCameraPose}
			<div class="sensor-preview-pose">
				x={hotCameraPose.x?.toFixed?.(2) ?? hotCameraPose.x}
				z={hotCameraPose.z?.toFixed?.(2) ?? hotCameraPose.z}
				yaw={hotCameraPose.yaw_deg?.toFixed?.(1) ?? hotCameraPose.yaw_deg}°
			</div>
		{:else}
			<div class="sensor-preview-pose muted">No hot camera placed</div>
		{/if}
		<label class="band-mode-row" title="측정 pBRDF 밴드 수: single=안정적인 1밴드×albedo · hybrid=무채색 1밴드/유색 3밴드 · rgb=전부 3밴드">
			<span>pBRDF band</span>
			<select value={previewBandMode} onchange={(e) => onSetPreviewBandMode((e.currentTarget as HTMLSelectElement).value)}>
				<option value="rgb">rgb · 3-band (full colour)</option>
				<option value="hybrid">hybrid · achromatic→1, coloured→3</option>
				<option value="single">single · 1-band ×albedo</option>
			</select>
		</label>
		<label class="band-mode-row" title="Measured pBRDF 사용 범위: 기본은 analytic-priority로 배경은 polarimetric analytic fallback을 사용하고 target/anchor만 measured를 켭니다.">
			<span>Measured scope</span>
			<select value={previewMeasuredScope} onchange={(e) => onSetPreviewMeasuredScope((e.currentTarget as HTMLSelectElement).value)}>
				<option value="analytic_priority">analytic-priority · anchors only</option>
				<option value="analytic_only">analytic-only · 0 measured</option>
				<option value="budgeted_measured">budgeted · up to 3</option>
				<option value="measured_full">full measured · HQ</option>
			</select>
		</label>
		<button class="button button-primary full" disabled={!caps.runProbe.enabled} title={caps.runProbe.reason} onclick={onRunProbe}>
			{probeRendering ? 'Rendering…' : 'Render preview'}
		</button>
		{#if probeError}
			<div class="probe-error">{probeError}</div>
		{/if}
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
					{@const hasModality = headingHasSensorModality(hdata, visibleObservationModality, activeRigSensorId)}
					{#if hasModality && perturbationEnabled}
						<div class="obs-pair" title={`${hid} · base / perturbed (mirrors)`}>
							<figure><img class="obs-thumb"
								src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, selectedSensorNodeId, hid, visibleObservationModality, activeRigSensorId, 'base')}
								alt={`${hid} base`} loading="lazy" /><figcaption>off</figcaption></figure>
							<figure><img class="obs-thumb"
								src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, selectedSensorNodeId, hid, visibleObservationModality, activeRigSensorId, 'perturbed')}
								alt={`${hid} perturbed`} loading="lazy" /><figcaption>mirror</figcaption></figure>
						</div>
					{:else if hasModality}
						<img
							class="obs-thumb"
							src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, selectedSensorNodeId, hid, visibleObservationModality, activeRigSensorId)}
							alt={`${hid} ${visibleObservationModality}`}
							title={`${hid} · ${activeRigSensorId || 'legacy'} · ${visibleObservationModality}`}
							loading="lazy"
						/>
					{:else}
						<div class="obs-thumb obs-thumb-empty" title={`${hid} · ${visibleObservationModality} not rendered`}>
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
		{#if perturbationEnabled}
			<div class="render-variant-row" title="base = mirrors off · perturbed = mirrors/glass on · both = render each viewpoint twice for the eval split">
				<span>Mirror render:</span>
				{#each ['base', 'perturbed', 'both'] as v}
					{@const needsStaged = v !== 'base' && !perturbedRenderReady}
					<label class:variant-disabled={needsStaged}
						title={needsStaged ? 'perturbed render scene이 준비되지 않음 — Sync Render Scene 필요' : ''}>
						<input type="radio" name="render-variant" checked={renderVariant === v} disabled={needsStaged}
							onchange={() => onSetRenderVariant?.(v as 'base' | 'perturbed' | 'both')} /> {v}</label>
				{/each}
			</div>
			{#if !perturbedRenderReady}
				<div class="render-variant-warn">
					⚠️ perturbed 렌더 미준비 — {perturbedRenderStale
						? 'perturbation 변경 후 Sync Render Scene을 다시 실행하세요 (perturbed XML stale).'
						: 'perturbation 활성화 후 Sync Render Scene을 실행하세요.'}
				</div>
			{/if}
		{/if}
		<button class="button button-primary full"
			disabled={!caps.renderSweepNode.enabled}
			title={caps.renderSweepNode.reason}
			onclick={onRenderViewpoint}>
			{renderingViewpoint ? 'Sweeping...' : 'Graph Sweep · this viewpoint'}
		</button>
		<label class="sensor-resume-row" title="Skip viewpoints/headings that already have consolidated outputs or a completed bridge-job manifest.">
			<input type="checkbox" checked={renderMissingOnly} onchange={(e) => onSetRenderMissingOnly?.((e.currentTarget as HTMLInputElement).checked)} />
			<span>Only missing renders</span>
		</label>
		<div class="sensor-sweep-summary">Sweep sensors: {selectedRigSensorIds.length || 1} selected</div>
		<button class="button button-subtle full" disabled={!caps.renderSweepAll.enabled} title={caps.renderSweepAll.reason} onclick={onRenderEpisodes}>
			{renderMissingOnly ? 'Graph Sweep · missing only' : 'Graph Sweep · all viewpoints'}
		</button>
		{#if onRenderEpisodeNodes}
			<button class="button button-subtle full"
				disabled={!caps.renderEpisodePath.enabled}
				title={caps.renderEpisodePath.reason}
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
	<div class="sync-row"><span>Measured candidates</span><span>{renderSceneStats?.measured_candidates ?? '—'}</span></div>
	<div class="sync-row"><span>Default measured on</span><span>{renderSceneStats?.measured_enabled_default ?? '—'}</span></div>
	<div class="sync-row"><span>Default suppressed</span><span>{renderSceneStats?.measured_suppressed_default ?? '—'}</span></div>
	<div class="sync-row"><span>Analytic BSDFs</span><span>{renderSceneStats?.analytic_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Analytic polar+RGB</span><span>{renderSceneStats?.analytic_polar_rgb_count ?? '—'}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.invalid_analytic_fallback_count > 0}>
		<span>Invalid analytic fallback</span><span>{renderSceneStats?.invalid_analytic_fallback_count ?? '—'}</span>
	</div>
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
		<button class="button button-subtle" disabled={!caps.refreshStats.enabled} title={caps.refreshStats.reason} onclick={onRefreshStats}>
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

	.sensor-panel .rig-sensor-toolbar {
			display: flex;
			gap: 6px;
			align-items: center;
		}

	.sensor-panel .rig-sensor-toolbar .button {
			font-size: 11px;
			padding: 4px 9px;
		}

	.sensor-panel .rig-sensor-list {
			display: grid;
			gap: 6px;
			position: relative;
		}

	.sensor-panel .rig-sensor-card {
			position: relative;
		}

	.sensor-panel .rig-sensor-card > button {
			width: 100%;
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 8px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: #fff;
			color: var(--text-primary);
			padding: 7px 9px;
			font-weight: 700;
			text-align: left;
			cursor: pointer;
		}

	.sensor-panel .rig-sensor-card > button small {
			font-size: 10px;
			font-weight: 600;
			color: var(--text-muted);
			white-space: nowrap;
		}

	.sensor-panel .rig-sensor-card > button.selected-tab {
			background: #eff6ff;
			color: #1d4ed8;
			border-color: #60a5fa;
		}

	.sensor-panel .rig-sensor-card > button.active-tab {
			background: #2563eb;
			color: #fff;
			border-color: #2563eb;
		}

	.sensor-panel .rig-sensor-card > button.active-tab small {
			color: rgba(255, 255, 255, 0.86);
		}

	.sensor-panel .rig-sensor-tooltip {
			position: absolute;
			z-index: 30;
			left: 8px;
			right: 8px;
			top: calc(100% + 6px);
			display: none;
			padding: 8px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-md);
			background: #fff;
			box-shadow: var(--shadow-lg);
		}

	.sensor-panel .rig-sensor-card:hover .rig-sensor-tooltip,
	.sensor-panel .rig-sensor-card:focus-within .rig-sensor-tooltip {
			display: block;
		}

	.sensor-panel .rig-readonly-grid {
			margin-top: 0;
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

	.sensor-sweep-summary {
			font-size: 11px;
			color: var(--text-muted);
			padding: 0 4px 4px;
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
	.obs-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; }
	.obs-pair figure { margin: 0; position: relative; }
	.obs-pair figcaption { position: absolute; top: 1px; left: 2px; font-size: 8px; padding: 0 3px; border-radius: 2px; background: rgba(0,0,0,0.55); color: #fff; }
	.render-variant-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: var(--font-size-xs); margin: 4px 0; }
	.render-variant-row label { display: inline-flex; align-items: center; gap: 2px; }
	.render-variant-row label.variant-disabled { opacity: 0.45; cursor: not-allowed; }
	.render-variant-warn { font-size: var(--font-size-xs); color: var(--warning, #b45309); background: var(--warning-bg, #fef3c7); border-radius: 3px; padding: 3px 6px; margin: 2px 0 6px; line-height: 1.3; }

	.obs-thumb-empty { display: flex; align-items: center; justify-content: center; background: var(--surface-2, #f1f5f9); border-radius: 3px; border: 1px solid var(--border); }

	.obs-thumb-empty span { font-size: 9px; color: var(--text-muted); }

	.sensor-panel .full { width: 100%; }

	.sensor-panel .sensor-add-bar { margin-bottom: 8px; }

	.sensor-preview-card {
			display: grid;
			gap: 8px;
			margin: 8px 0 12px;
			padding: 10px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-md);
			background: var(--surface-1);
		}

	.sensor-preview-head {
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 8px;
		}

	.sensor-preview-meta {
			display: flex;
			flex-wrap: wrap;
			gap: 5px;
			font-size: 11px;
			color: var(--text-muted);
		}

	.polar-preview-mode-row {
			display: grid;
			grid-template-columns: repeat(5, minmax(0, 1fr));
			gap: 4px;
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

	.sensor-preview-meta span,
	.sensor-preview-pose {
			padding: 2px 6px;
			border-radius: var(--radius-sm);
			background: #fff;
			border: 1px solid var(--panel-border);
		}

	.sensor-preview-pose {
			font-size: 11px;
			color: var(--text-primary);
			overflow-wrap: anywhere;
		}

	.sensor-preview-pose.muted {
			color: var(--text-muted);
		}

	.band-mode-row {
			display: grid;
			grid-template-columns: 96px minmax(0, 1fr);
			align-items: center;
			gap: 8px;
		}

	.band-mode-row > span {
			font-size: 11px;
			color: var(--text-muted);
			font-weight: 700;
			white-space: nowrap;
		}

	.band-mode-row > select {
			min-width: 0;
			font-size: 12px;
		}

	.probe-error {
			color: var(--danger);
			background: var(--danger-soft);
			padding: var(--space-2);
			border-radius: var(--radius-sm);
			font-size: var(--font-size-xs);
		}

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
