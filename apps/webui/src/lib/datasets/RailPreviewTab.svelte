<script lang="ts">
	import { opticalNavObservationModalityUrl } from '$lib/api';
	import { POLAR_PREVIEW_MODALITIES } from '$lib/datasets/sensorHelpers';

	interface Props {
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
		rigMountHeightM: number;
		onRefreshBatch: () => void;
		onSelectHotCamera: (id: string) => void;
	}

	let {
		hotCameraPose, hotCameraPoses, activeHotCameraId,
		activeRigSensorOption, activeCameraFrustum, activeRenderModality,
		probeResult, activeRigSensorId,
		selectedProjectId, sceneId,
		rigMountHeightM,
		onRefreshBatch, onSelectHotCamera,
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
</style>
