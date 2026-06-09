<script lang="ts">
	import { opticalNavObservationModalityUrl } from '$lib/api';

	interface Props {
		hotCameraPose: any;
		hotCameraPoses: any[];
		activeHotCameraId: string;
		activeRigSensorOption: any;
		activeCameraFrustum: any;
		activeRenderModality: string;
		probeRendering: boolean;
		probeError: string;
		probeResult: any;
		activeRigSensorId: string;
		selectedProjectId: string;
		sceneId: string;
		editorObjectsCount: number;
		editorEmitterCount: number;
		editorMaterialCount: number;
		renderSceneStats: any;
		renderSceneStatsLoading: boolean;
		showRoomShell: boolean;
		roomShell: any;
		rigMountHeightM: number;
		authoringMap: any;
		hasScene: boolean;
		loading: boolean;
		onRunProbe: () => void;
		onRefreshBatch: () => void;
		onRefreshStats: () => void;
		onSetShowRoomShell: (v: boolean) => void;
		onSelectHotCamera: (id: string) => void;
	}

	let {
		hotCameraPose, hotCameraPoses, activeHotCameraId,
		activeRigSensorOption, activeCameraFrustum, activeRenderModality,
		probeRendering, probeError, probeResult, activeRigSensorId,
		selectedProjectId, sceneId,
		editorObjectsCount, editorEmitterCount, editorMaterialCount,
		renderSceneStats, renderSceneStatsLoading,
		showRoomShell, roomShell, rigMountHeightM, authoringMap,
		hasScene, loading,
		onRunProbe, onRefreshBatch, onRefreshStats, onSetShowRoomShell, onSelectHotCamera,
	}: Props = $props();
</script>

<section class="rail-section rail-tool-panel preview-panel">
	<div class="rail-title">Hot Camera Preview</div>
	<div class="probe-info">
		<p class="probe-empty">Click-drag on the 3D view to place the preview camera and set yaw.</p>
		<div>Rig sensor: {activeRigSensorOption?.label ?? activeRigSensorId ?? 'default'}</div>
		<div>Modality: {activeRenderModality}</div>
		<div>FOV: {Number(activeCameraFrustum?.fov_deg ?? 70).toFixed(0)}°</div>
		<div>Height: {rigMountHeightM.toFixed(2)} m</div>
		{#if hotCameraPose}
			<div>Pose: x={hotCameraPose.x?.toFixed?.(2) ?? hotCameraPose.x} z={hotCameraPose.z?.toFixed?.(2) ?? hotCameraPose.z}</div>
			<div>Yaw: {hotCameraPose.yaw_deg?.toFixed?.(1) ?? hotCameraPose.yaw_deg}°</div>
		{:else}
			<p class="probe-empty">No hot camera placed yet.</p>
		{/if}
	</div>
	<div class="probe-actions">
		<span class="chip-dim">{activeRigSensorId || 'rig sensor'}</span>
		<button class="button button-primary" disabled={probeRendering || !hotCameraPose} onclick={onRunProbe}>
			{probeRendering ? 'Rendering…' : 'Render now'}
		</button>
	</div>
	{#if probeError}
		<div class="probe-error">{probeError}</div>
	{/if}
	{#if hotCameraPoses.length > 0}
		<div class="probe-history">
			<div class="probe-result-meta">Preview cameras</div>
			{#each hotCameraPoses as cam, i}
				<button
					type="button"
					class={`button button-subtle full ${cam.preview_id === activeHotCameraId ? 'active' : ''}`}
					onclick={() => onSelectHotCamera(cam.preview_id)}
				>
					#{i + 1} · x={cam.x?.toFixed?.(2) ?? cam.x} z={cam.z?.toFixed?.(2) ?? cam.z} · yaw={cam.yaw_deg?.toFixed?.(1) ?? cam.yaw_deg}°
					{cam.rendered ? ' · rendered' : ''}
				</button>
			{/each}
		</div>
	{/if}
	{#if probeResult}
		<div class="probe-result">
			<div class="probe-result-meta">Batch {probeResult.batch_id.slice(0, 8)}… · {probeResult.vp_id}/{probeResult.heading_id}</div>
			<img class="probe-result-img"
				src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, probeResult.vp_id, probeResult.heading_id, probeResult.modality, probeResult.sensor_id ?? activeRigSensorId)}
				alt={`probe ${probeResult.modality}`} loading="lazy"
				onerror={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = '0.3'; }} />
			<button class="button button-subtle" onclick={onRefreshBatch}>Refresh batch status</button>
		</div>
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
	<div class="sync-row"><span>Measured polarized BSDFs</span><span>{renderSceneStats?.measured_polarized_count ?? '—'}</span></div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>Active rig</span><span>{authoringMap?.camera_rig?.rig_id ?? '—'}</span></div>
	<div class="sync-row"><span>Rig mount height</span><span>{rigMountHeightM.toFixed(2)} m</span></div>
	<div class="sync-row"><span>Ceiling height</span><span>{Number(authoringMap?.settings?.default_wall_height_m ?? 2.4).toFixed(2)} m</span></div>
	<div class="sync-row">
		<label class="footprint-toggle">
			<input type="checkbox" checked={showRoomShell}
				onchange={(e) => onSetShowRoomShell((e.currentTarget as HTMLInputElement).checked)} />
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
	.preview-panel { display: grid; gap: var(--space-3); }

	.probe-mode-row { display: grid; gap: 4px; font-size: var(--font-size-sm); }

	.probe-mode-row label { display: flex; gap: 6px; align-items: center; }

	.probe-mode-stub { color: var(--muted-strong); }

	.probe-info { display: grid; gap: 4px; font-size: var(--font-size-sm); padding: var(--space-2); background: var(--surface-1); border-radius: var(--radius-sm); }

	.probe-info.probe-form { grid-template-columns: repeat(2, 1fr); }

	.probe-info.probe-form label { display: grid; gap: 2px; font-size: var(--font-size-xs); }

	.probe-info.probe-form input { padding: 2px 4px; border: 1px solid var(--border); border-radius: var(--radius-sm); }

	.probe-empty { margin: 4px 0 0 0; color: var(--muted-strong); font-size: var(--font-size-xs); }

	.probe-actions { display: flex; gap: var(--space-2); align-items: center; }

	.probe-error { color: var(--danger); background: var(--danger-soft); padding: var(--space-2); border-radius: var(--radius-sm); font-size: var(--font-size-xs); }

	.probe-result { display: grid; gap: var(--space-2); }

	.probe-result-meta { font-size: var(--font-size-xs); color: var(--muted-strong); }

	.probe-result-img { width: 100%; max-height: 280px; object-fit: contain; background: #0f172a; border-radius: var(--radius-sm); }

	.sync-inspector { display: grid; gap: 6px; }

	.sync-row { display: flex; justify-content: space-between; font-size: var(--font-size-xs); padding: 2px 0; }

	.sync-row.warn { color: var(--danger); font-weight: 600; }

	.sync-row .mono { font-family: monospace; max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	.sync-divider { height: 1px; background: var(--border); margin: 4px 0; }

	.sync-actions { display: flex; gap: var(--space-2); margin-top: var(--space-2); }
</style>
