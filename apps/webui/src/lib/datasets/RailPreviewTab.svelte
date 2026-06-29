<script lang="ts">
	import { opticalNavObservationModalityUrl } from '$lib/api';
	import { POLAR_PREVIEW_MODALITIES } from '$lib/datasets/sensorHelpers';
	import type { Capabilities } from '$lib/datasets/capabilityHelpers';

	interface Props {
		caps: Capabilities;
		hotCameraPose: any;
		hotCameraPoses: any[];
		activeHotCameraId: string;
		activeRigSensorOption: any;
		activeCameraFrustum: any;
		activeRenderModality: string;
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
		onRefreshBatch: () => void;
		onRefreshStats: () => void;
		onSetShowRoomShell: (v: boolean) => void;
		onSelectHotCamera: (id: string) => void;
	}

	let {
		caps,
		hotCameraPose, hotCameraPoses, activeHotCameraId,
		activeRigSensorOption, activeCameraFrustum, activeRenderModality,
		probeResult, activeRigSensorId,
		selectedProjectId, sceneId,
		editorObjectsCount, editorEmitterCount, editorMaterialCount,
		renderSceneStats, renderSceneStatsLoading,
		showRoomShell, roomShell, rigMountHeightM, authoringMap,
		onRefreshBatch, onRefreshStats, onSetShowRoomShell, onSelectHotCamera,
	}: Props = $props();

	// Infinigen PBR re-bake: the daemon runs no Blender, so we surface the exact
	// CLI command (source blend from render-scene stats) for the user to run.
	let bakeCmdShown = $state(false);
	let bakeCmdCopied = $state(false);
	const bakeCmd = $derived(
		renderSceneStats?.infinigen_source_blend
			? `bash apps/run_infinigen_import.sh "${renderSceneStats.infinigen_source_blend}" --scene-id ${sceneId} --bake-only`
			: ''
	);
	async function copyBakeCmd() {
		bakeCmdShown = true;
		try {
			await navigator.clipboard.writeText(bakeCmd);
			bakeCmdCopied = true;
			setTimeout(() => (bakeCmdCopied = false), 2000);
		} catch {
			/* clipboard blocked — command still shown for manual copy */
		}
	}
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
			{#if probeResult.is_polar}
				<div class="polar-grid">
					{#each POLAR_PREVIEW_MODALITIES as rep}
						<figure class="polar-cell">
							<img
								src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, probeResult.vp_id, probeResult.heading_id, rep.id, probeResult.sensor_id ?? activeRigSensorId)}
								alt={`probe ${rep.id}`} loading="lazy"
								onerror={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = '0.25'; }} />
							<figcaption>{rep.label}</figcaption>
						</figure>
					{/each}
				</div>
			{:else}
				<img class="probe-result-img"
					src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, probeResult.vp_id, probeResult.heading_id, probeResult.modality, probeResult.sensor_id ?? activeRigSensorId)}
					alt={`probe ${probeResult.modality}`} loading="lazy"
					onerror={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = '0.3'; }} />
			{/if}
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
	{#if renderSceneStats?.infinigen_import_root}
		<div class="sync-divider"></div>
		<div class="sync-row" class:warn={!renderSceneStats.pbr_baked}>
			<span>Infinigen PBR maps</span>
			<span>{renderSceneStats.pbr_baked ? `baked · rough ${renderSceneStats.pbr_baked_roughness_count ?? 0}/${renderSceneStats.infinigen_unit_count ?? 0}` : 'albedo only'}</span>
		</div>
		{#if renderSceneStats.pbr_baked}
			<div class="sync-row"><span>· normal / metallic</span><span>{renderSceneStats.pbr_baked_normal_count ?? 0} / {renderSceneStats.pbr_baked_metallic_count ?? 0}</span></div>
		{/if}
		{#if renderSceneStats.infinigen_source_blend}
			<div class="sync-actions">
				<button class="button button-subtle" onclick={copyBakeCmd}>{bakeCmdCopied ? 'Copied ✓' : (renderSceneStats.pbr_baked ? 'Re-bake PBR — copy cmd' : 'Bake PBR — copy cmd')}</button>
			</div>
			{#if bakeCmdShown}<pre class="bake-cmd">{bakeCmd}</pre>{/if}
		{/if}
	{/if}
	<div class="sync-actions">
		<button class="button button-subtle" disabled={!caps.refreshStats.enabled} title={caps.refreshStats.reason} onclick={onRefreshStats}>
			{renderSceneStatsLoading ? 'Loading…' : 'Refresh stats'}
		</button>
	</div>
</section>

<style>
	.preview-panel { display: grid; gap: var(--space-3); }

	.probe-info { display: grid; gap: 4px; font-size: var(--font-size-sm); padding: var(--space-2); background: var(--surface-1); border-radius: var(--radius-sm); }

	.probe-empty { margin: 4px 0 0 0; color: var(--muted-strong); font-size: var(--font-size-xs); }

	.probe-result { display: grid; gap: var(--space-2); }

	.probe-result-meta { font-size: var(--font-size-xs); color: var(--muted-strong); }

	.probe-result-img { width: 100%; max-height: 280px; object-fit: contain; background: #0f172a; border-radius: var(--radius-sm); }

	.polar-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-2); }
	.polar-cell { margin: 0; display: grid; gap: 2px; }
	.polar-cell img { width: 100%; aspect-ratio: 4 / 3; object-fit: contain; background: #0f172a; border-radius: var(--radius-sm); }
	.polar-cell figcaption { font-size: var(--font-size-xs); color: var(--muted-strong); text-align: center; }

	.sync-inspector { display: grid; gap: 6px; }

	.sync-row { display: flex; justify-content: space-between; font-size: var(--font-size-xs); padding: 2px 0; }

	.sync-row.warn { color: var(--danger); font-weight: 600; }

	.sync-row .mono { font-family: monospace; max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	.sync-divider { height: 1px; background: var(--border); margin: 4px 0; }
	.bake-cmd { font-family: monospace; font-size: 10px; white-space: pre-wrap; word-break: break-all; background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 6px; margin: 4px 0 0 0; }

	.sync-actions { display: flex; gap: var(--space-2); margin-top: var(--space-2); }
</style>
