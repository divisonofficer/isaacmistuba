<script lang="ts">
	import { Camera, ChevronDown, ExternalLink, Radio, RefreshCw, Settings2 } from '@lucide/svelte';
	import { InspectorSection, MetricCard, ProgressBar, SegmentedControl } from '$lib/components';
	import { formatRenderSpp, formatResolution, formatRigVec, normalizeRigRenderSettings, sensorMountHeight } from '$lib/datasets/sensorHelpers';
	import {
		batchScopeEstimate,
		defaultBatchScope,
		renderCampaignSummary,
		type BatchScope,
		type RenderVariant,
		type SensorInspectorTab,
		type TestRenderTarget,
	} from '$lib/datasets/sensorPresentation';

	interface SensorInspectorState {
		caps: any;
		renderSceneSynced: boolean;
		renderSyncMessage?: string;
		globalCameraRig: any;
		globalCameraRigStatus?: string;
		globalCameraRigError?: string;
		rigSensorOptions: any[];
		activeRigSensorId: string;
		selectedRigSensorIds: string[];
		activeRigSensorOption: any;
		selectedSensorNode: any;
		selectedSensorNodeId: string;
		selectedSensorHeightM: number;
		observationScan: any;
		sensorRenderResult: any;
		probeResult: any;
		renderingViewpoint: boolean;
		probeRendering: boolean;
		probeError?: string;
		hotCameraPose: any;
		frustumMode: string;
		ambientRadiance: number;
		unifiedSpectral?: boolean;
		useLodScene?: boolean;
		renderConfig: any;
		sceneStateText?: string;
		cameraSpecText?: string;
		loading: boolean;
		selectedProjectId: string;
		sceneId: string;
		hasScene: boolean;
		hasGraph: boolean;
		graphNodeCount: number;
		headingsPerNode: number;
		navigationSupportReady: boolean;
		navigationSupportReadOnly: boolean;
		legacyRenderBlocked: boolean;
		navigationSupportViewCount: number;
		navigationSupportPlanLabel: string;
		navigationSupportPlanReady: boolean;
		navigationSupportRenderSubmitting: boolean;
		episodeNodesAvailable: boolean;
		episodePathNodeCount: number;
		renderVariant: RenderVariant;
		perturbationEnabled: boolean;
		perturbedRenderReady: boolean;
		perturbedRenderStale: boolean;
		renderMissingOnly: boolean;
		polarSampleSweepEnabled: boolean;
		polarSampleSweepSubmitting: boolean;
		polarFullSweepEnabled: boolean;
		polarFullSweepSubmitting: boolean;
		renderSensorProgress: any[];
	}

	interface SensorInspectorActions {
		onLoadGlobalCameraRig: () => void;
		onSyncRenderScene: () => void;
		onSelectRigSensor: (sensorId: string) => void;
		onSetRigSweepSensors: (sensorIds: string[]) => void;
		onSetFrustumMode: (mode: string) => void;
		onLoadRenderConfig: () => void;
		onSetAmbientRadiance: (value: number) => void;
		onSetUnifiedSpectral: (value: boolean) => void;
		onSetUseLodScene: (value: boolean) => void;
		onRenderViewpoint: () => void;
		onRunProbe: () => void;
		onRenderEpisodes: (mode: 'graph_sweep' | 'episode_nodes') => void;
		onRenderNavigationSupport: () => void;
		onSubmitPolarSampleSweep: () => void;
		onSubmitPolarFullSweep: () => void;
		onSetRenderVariant: (variant: RenderVariant) => void;
		onSetRenderMissingOnly: (value: boolean) => void;
		onOpenPreview: () => void;
		onOpenMonitor: () => void;
	}

	interface Props {
		sensorState: SensorInspectorState;
		sensorActions: SensorInspectorActions;
	}

	let { sensorState, sensorActions: actions }: Props = $props();
	let tab = $state<SensorInspectorTab>('test');
	let testTarget = $state<TestRenderTarget>('viewpoint');
	let batchScope = $state<BatchScope>('full_graph');
	let batchScopeInitialized = $state(false);
	let polarMode = $state<'sample' | 'full'>('sample');
	let batchManageOpen = $state(false);

	const activeSensor = $derived(sensorState.activeRigSensorOption ?? sensorState.rigSensorOptions.find((option) => option.sensor_id === sensorState.activeRigSensorId) ?? null);
	const activeSensorData = $derived(activeSensor?.sensor ?? {});
	const batchSensorIds = $derived(
		sensorState.selectedRigSensorIds?.length
			? sensorState.selectedRigSensorIds.map(String)
			: (sensorState.activeRigSensorId ? [sensorState.activeRigSensorId] : []),
	);
	const campaign = $derived(renderCampaignSummary(sensorState.renderSensorProgress));
	const scopeEstimate = $derived(batchScopeEstimate({
		scope: batchScope,
		navigationSupportViews: sensorState.navigationSupportViewCount,
		graphNodeCount: sensorState.graphNodeCount,
		headingsPerNode: sensorState.headingsPerNode,
		episodePathNodeCount: sensorState.episodePathNodeCount,
		sensorCount: batchSensorIds.length,
		polarMode,
		coverage: sensorState.renderSensorProgress,
		selectedSensorIds: batchScope === 'polar_evaluation' ? ['polar_cam'] : batchSensorIds,
		variant: sensorState.renderVariant,
	}));
	const selectedViewpointScan = $derived(sensorState.observationScan?.viewpoints?.[sensorState.selectedSensorNodeId] ?? null);
	const hasGraphViewpoint = $derived(Boolean(sensorState.selectedSensorNode && !sensorState.selectedSensorNode?.isCustom));
	const latestTestResult = $derived(sensorState.probeResult ?? sensorState.sensorRenderResult ?? null);
	const normalScope = $derived(batchScope !== 'polar_evaluation');
	const fullGraphBlockedBySupport = $derived(sensorState.legacyRenderBlocked);
	const scopeTabs = $derived([
		{ id: 'navigation_support', label: 'Navigation Support', disabled: !sensorState.navigationSupportReady },
		{ id: 'full_graph', label: 'Full graph', disabled: !sensorState.hasGraph || fullGraphBlockedBySupport },
		{ id: 'episode_path', label: 'Episode path', disabled: !sensorState.episodeNodesAvailable || fullGraphBlockedBySupport },
		{ id: 'polar_evaluation', label: 'Polar evaluation', disabled: !sensorState.polarSampleSweepEnabled && !sensorState.polarFullSweepEnabled },
	]);

	$effect(() => {
		if (!batchScopeInitialized) {
			batchScope = defaultBatchScope({ navigationSupportReady: sensorState.navigationSupportReady, hasGraph: sensorState.hasGraph });
			batchScopeInitialized = true;
		}
	});

	function selectBatchSensor(sensorId: string, checked: boolean) {
		const current = new Set(batchSensorIds);
		if (checked) current.add(sensorId);
		else current.delete(sensorId);
		actions.onSetRigSweepSensors([...current]);
	}

	function runBatch() {
		if (batchScope === 'navigation_support') actions.onRenderNavigationSupport();
		else if (batchScope === 'full_graph') actions.onRenderEpisodes('graph_sweep');
		else if (batchScope === 'episode_path') actions.onRenderEpisodes('episode_nodes');
		else if (polarMode === 'sample') actions.onSubmitPolarSampleSweep();
		else actions.onSubmitPolarFullSweep();
	}

	function batchActionDisabled() {
		if (batchScope === 'navigation_support') return !sensorState.caps?.renderNavigationSupport?.enabled || !sensorState.navigationSupportPlanReady || sensorState.navigationSupportRenderSubmitting;
		if (batchScope === 'full_graph') return !sensorState.caps?.renderSweepAll?.enabled || fullGraphBlockedBySupport;
		if (batchScope === 'episode_path') return !sensorState.caps?.renderEpisodePath?.enabled || fullGraphBlockedBySupport;
		return polarMode === 'sample' ? !sensorState.polarSampleSweepEnabled || sensorState.polarSampleSweepSubmitting : !sensorState.polarFullSweepEnabled || sensorState.polarFullSweepSubmitting;
	}

	function batchActionLabel() {
		if (batchScope === 'navigation_support') {
			if (sensorState.navigationSupportReadOnly) return 'Archived support plan (read-only)';
			return sensorState.navigationSupportRenderSubmitting ? 'Submitting support plan…' : `Render ${sensorState.navigationSupportPlanLabel}`;
		}
		if (batchScope === 'full_graph') return sensorState.renderMissingOnly ? 'Render graph · missing only' : 'Render full graph';
		if (batchScope === 'episode_path') return sensorState.renderMissingOnly ? 'Render episode path · missing only' : 'Render episode path';
		if (polarMode === 'sample') return sensorState.polarSampleSweepSubmitting ? 'Planning polar sample…' : 'Run Polar Sample';
		return sensorState.polarFullSweepSubmitting ? 'Submitting Polar Full…' : 'Run Polar Full';
	}

	function scopeReason() {
		if (batchScope === 'navigation_support' && !sensorState.navigationSupportReady) return 'Build Navigation Support in Paths before using its render plan.';
		if (batchScope === 'navigation_support' && sensorState.navigationSupportReadOnly) return 'This is the recovered 2,454-view L0 render-plan overlay. Its completed/running campaign is visible here, but it cannot accept new renders or episodes after the place graph was edited.';
		if ((batchScope === 'full_graph' || batchScope === 'episode_path') && fullGraphBlockedBySupport) return 'This scene has a certified Navigation Support plan. Legacy graph and episode sweeps are intentionally unavailable.';
		if (batchScope === 'episode_path' && !sensorState.episodeNodesAvailable) return 'Select an episode with graph path nodes first.';
		if (batchScope === 'polar_evaluation' && !sensorState.polarSampleSweepEnabled && !sensorState.polarFullSweepEnabled) return 'Polar evaluation requires a synced graph scene, prepared perturbation, and polar_cam.';
		return '';
	}

	function closeOnEscape(event: KeyboardEvent) {
		if (event.key === 'Escape') batchManageOpen = false;
	}
</script>

<svelte:window onkeydown={closeOnEscape} />

<div class="sensors-inspector">
	<header class="inspector-heading">
		<div>
			<p>Sensors</p>
			<h2>Sensor Rendering Workspace</h2>
		</div>
		<span class:ready={sensorState.renderSceneSynced} class="state-chip">{sensorState.renderSceneSynced ? 'Ready' : 'Sync required'}</span>
	</header>

	{#if !sensorState.renderSceneSynced}
		<div class="sync-alert" role="alert">
			<div><strong>Render scene not synced</strong><span>{sensorState.renderSyncMessage || 'Sync the scene before submitting previews or sweeps.'}</span></div>
			<button class="button button-primary" disabled={sensorState.loading || !sensorState.selectedProjectId || !sensorState.hasScene} onclick={actions.onSyncRenderScene}>Sync Render Scene</button>
		</div>
	{/if}

	<InspectorSection title="Camera context">
		<div class="context-head">
			<div><strong>{sensorState.globalCameraRig?.name ?? 'Robot camera rig'}</strong><span>{sensorState.rigSensorOptions.length} cameras · {sensorState.globalCameraRig?.base_frame ?? 'base_link'}</span></div>
			<div class="context-actions"><a class="icon-link" href="/camera_rig" title="Open Camera Rig Editor"><ExternalLink size={15} /><span>Edit rig</span></a><button class="icon-button" aria-label="Reload camera rig" title="Reload camera rig" disabled={sensorState.loading} onclick={actions.onLoadGlobalCameraRig}><RefreshCw size={15} /></button></div>
		</div>
		{#if sensorState.globalCameraRigError}<p class="error-copy">{sensorState.globalCameraRigError}</p>{:else if sensorState.globalCameraRigStatus}<p class="help">{sensorState.globalCameraRigStatus}</p>{/if}
		<label class="field">Active camera
			<select value={sensorState.activeRigSensorId} onchange={(event) => actions.onSelectRigSensor((event.currentTarget as HTMLSelectElement).value)}>
				{#each sensorState.rigSensorOptions as option (option.sensor_id)}<option value={option.sensor_id}>{option.label} · {option.modality}</option>{/each}
			</select>
		</label>
		{#if activeSensor}
			<div class="camera-summary"><Radio size={16} /><span><strong>{activeSensor.label}</strong> · {activeSensor.modality}</span><small>{Number(activeSensorData.fov_deg ?? activeSensorData.intrinsics?.fov_h_deg ?? 0).toFixed(0)}° · {formatResolution(activeSensorData.resolution ?? activeSensorData.intrinsics?.resolution)} · h {sensorMountHeight(activeSensorData).toFixed(2)} m · {formatRenderSpp(activeSensorData)}</small></div>
		{/if}
		<div class="batch-context">
			<div><strong>Batch cameras</strong><span>{batchSensorIds.length}/{sensorState.rigSensorOptions.length} selected</span></div>
			<div class="batch-manage">
				<button class="button button-ghost" aria-expanded={batchManageOpen} onclick={() => batchManageOpen = !batchManageOpen}>Manage <ChevronDown size={15} /></button>
				{#if batchManageOpen}
					<div class="manage-popover" role="dialog" aria-label="Manage batch cameras">
						<header><strong>Batch cameras</strong><button class="icon-button" aria-label="Close batch camera list" onclick={() => batchManageOpen = false}>×</button></header>
						<div class="popover-actions"><button class="button button-ghost" onclick={() => actions.onSetRigSweepSensors(sensorState.rigSensorOptions.map((option) => String(option.sensor_id)))}>All</button><button class="button button-ghost" onclick={() => actions.onSetRigSweepSensors(sensorState.activeRigSensorId ? [sensorState.activeRigSensorId] : [])}>Active only</button></div>
						<div class="camera-check-list">{#each sensorState.rigSensorOptions as option (option.sensor_id)}<label><input type="checkbox" checked={batchSensorIds.includes(String(option.sensor_id))} onchange={(event) => selectBatchSensor(String(option.sensor_id), (event.currentTarget as HTMLInputElement).checked)} /><span><strong>{option.label}</strong><small>{option.modality}</small></span></label>{/each}</div>
						<button class="button button-primary popover-done" onclick={() => batchManageOpen = false}>Done</button>
					</div>
				{/if}
			</div>
		</div>
	</InspectorSection>

	<SegmentedControl items={[{ id: 'test', label: 'Test Render' }, { id: 'batch', label: 'Batch' }, { id: 'profiles', label: 'Profiles' }]} value={tab} ariaLabel="Sensor rendering workflow" onchange={(value) => tab = value as SensorInspectorTab} />

	{#if tab === 'test'}
		<InspectorSection title="Test render">
			<SegmentedControl items={[{ id: 'viewpoint', label: 'Graph viewpoint' }, { id: 'hot_camera', label: 'Hot camera' }]} value={testTarget} ariaLabel="Test render position" onchange={(value) => testTarget = value as TestRenderTarget} />
			{#if testTarget === 'viewpoint'}
				{#if hasGraphViewpoint}
					<div class="target-card"><Camera size={17} /><div><strong>{sensorState.selectedSensorNodeId}</strong><span>x {Number(sensorState.selectedSensorNode.position?.[0] ?? 0).toFixed(2)} · z {Number(sensorState.selectedSensorNode.position?.[1] ?? 0).toFixed(2)} · {sensorState.headingsPerNode} headings</span></div>{#if selectedViewpointScan}<em>{selectedViewpointScan.completed ?? 0}/{selectedViewpointScan.total ?? 0} rendered</em>{/if}</div>
					<label class="field compact">Sensor rays<select value={sensorState.frustumMode} onchange={(event) => actions.onSetFrustumMode((event.currentTarget as HTMLSelectElement).value)}><option value="none">None</option><option value="view-aligned">View-aligned</option><option value="selected">Selected only</option></select></label>
					<button class="button button-primary full" disabled={!sensorState.caps?.renderSweepNode?.enabled || sensorState.renderingViewpoint} title={sensorState.caps?.renderSweepNode?.reason} onclick={actions.onRenderViewpoint}>{sensorState.renderingViewpoint ? 'Submitting…' : 'Render this viewpoint'}</button>
				{:else}<p class="empty">Select a blue graph viewpoint on the canvas to run a viewpoint test.</p>{/if}
			{:else}
				{#if sensorState.hotCameraPose}
					<div class="target-card"><Camera size={17} /><div><strong>Hot camera</strong><span>x {Number(sensorState.hotCameraPose.x ?? 0).toFixed(2)} · z {Number(sensorState.hotCameraPose.z ?? 0).toFixed(2)} · yaw {Number(sensorState.hotCameraPose.yaw_deg ?? 0).toFixed(1)}°</span></div></div>
					<button class="button button-primary full" disabled={!sensorState.caps?.runProbe?.enabled || sensorState.probeRendering} title={sensorState.caps?.runProbe?.reason} onclick={actions.onRunProbe}>{sensorState.probeRendering ? 'Submitting…' : 'Render preview'}</button>
				{:else}<p class="empty">No existing hot camera. Place one in the Map/Preview workflow, then return here to render it.</p>{/if}
			{/if}
			{#if sensorState.probeError}<p class="error-copy">{sensorState.probeError}</p>{/if}
			{#if latestTestResult}<div class="test-result"><span><strong>Submitted</strong> · {latestTestResult.batch_id?.slice?.(0, 12) ?? 'batch pending'}</span><button class="button button-ghost" onclick={actions.onOpenPreview}>Open in Preview</button></div>{/if}
		</InspectorSection>
	{:else if tab === 'batch'}
		<InspectorSection title="Batch render">
			<SegmentedControl items={scopeTabs} value={batchScope} ariaLabel="Batch render scope" onchange={(value) => batchScope = value as BatchScope} />
			{#if scopeReason()}<p class="help warn">{scopeReason()}</p>{/if}
			{#if normalScope}
				<div class="scope-summary"><strong>{batchScope === 'navigation_support' ? sensorState.navigationSupportPlanLabel : batchScope === 'episode_path' ? 'Selected episode path' : 'All graph viewpoint headings'}</strong><span>{scopeEstimate.total.toLocaleString()} estimated {scopeEstimate.label} · {batchSensorIds.length} camera{batchSensorIds.length === 1 ? '' : 's'}</span></div>
				<label class="check-row"><input type="checkbox" checked={sensorState.renderMissingOnly} onchange={(event) => actions.onSetRenderMissingOnly((event.currentTarget as HTMLInputElement).checked)} /><span><strong>Only missing renders</strong><small>Skip completed observations when the selected scope supports it.</small></span></label>
				<div class="variant-control"><span>Variant</span><div>{#each ['base', 'perturbed', 'both'] as variant}{@const blocked = variant !== 'base' && (!sensorState.perturbationEnabled || !sensorState.perturbedRenderReady)}{@const blockedReason = !sensorState.perturbationEnabled ? 'Enable Optical Perturbation before rendering this variant.' : sensorState.perturbedRenderStale ? 'Perturbed scene is stale. Sync Render Scene.' : 'Prepare the perturbed render scene first.'}<button class:active={sensorState.renderVariant === variant} disabled={blocked} title={blocked ? blockedReason : ''} onclick={() => actions.onSetRenderVariant(variant as RenderVariant)}>{variant}</button>{/each}</div></div>
				{#if !sensorState.perturbationEnabled}<p class="help">Enable Optical Perturbation to submit perturbed or paired renders.</p>{:else if !sensorState.perturbedRenderReady}<p class="help warn">{sensorState.perturbedRenderStale ? 'Perturbed scene is stale. Sync Render Scene to refresh it.' : 'Prepare the perturbed render scene before selecting its variant.'}</p>{/if}
			{:else}
				<div class="scope-summary polar-summary"><strong>{polarMode === 'sample' ? 'Polar sample · 10 selected views' : 'Polar full · all graph views'}</strong><span>{polarMode === 'sample' ? 'perturbed passive → active-polar · 20 phases' : `base → perturbed passive → active-polar · ${scopeEstimate.total.toLocaleString()} phases`}</span></div>
				<SegmentedControl items={[{ id: 'sample', label: 'Sample' }, { id: 'full', label: 'Full' }]} value={polarMode} ariaLabel="Polar evaluation extent" onchange={(value) => polarMode = value as 'sample' | 'full'} />
				<p class="help">Polar evaluation uses <strong>polar_cam</strong> and its fixed transport sequence. Full runs deliberately do not skip existing observations.</p>
			{/if}
			<div class="submission-summary"><span>{scopeEstimate.exact ? `${scopeEstimate.completed.toLocaleString()} / ${scopeEstimate.total.toLocaleString()} covered` : `${scopeEstimate.total.toLocaleString()} estimated ${scopeEstimate.label}`}</span><strong>{scopeEstimate.exact ? `${scopeEstimate.missing?.toLocaleString()} missing` : 'Final count resolves on submit'}</strong></div>
			<button class="button button-primary full" disabled={batchActionDisabled()} title={scopeReason()} onclick={runBatch}>{batchActionLabel()}</button>
		</InspectorSection>
	{:else}
		<InspectorSection title="Current render profile">
			<div class="metric-grid"><MetricCard label="Resolution" value={formatResolution(activeSensorData.resolution ?? activeSensorData.intrinsics?.resolution)} /><MetricCard label="FOV" value={`${Number(activeSensorData.fov_deg ?? activeSensorData.intrinsics?.fov_h_deg ?? 0).toFixed(0)}°`} /><MetricCard label="SPP" value={normalizeRigRenderSettings(activeSensorData.render, activeSensorData.canonical_sensor_type ?? activeSensorData.sensor_type).path_spp} detail={formatRenderSpp(activeSensorData)} /></div>
			<div class="profile-grid"><label class="field">Ambient radiance<input type="number" min="0" max="20" step="0.1" value={sensorState.ambientRadiance} oninput={(event) => actions.onSetAmbientRadiance(Number((event.currentTarget as HTMLInputElement).value))} /></label><div class="readonly-profile"><span>Mount</span><strong>{formatRigVec(activeSensorData.mount?.xyz_m)} m</strong></div></div>
			<label class="check-row"><input type="checkbox" checked={sensorState.unifiedSpectral} onchange={(event) => actions.onSetUnifiedSpectral((event.currentTarget as HTMLInputElement).checked)} /><span><strong>Unified spectral-polar scene</strong><small>Reuse one resident scene for RGB, NIR, and polarization when available.</small></span></label>
			<label class="check-row"><input type="checkbox" checked={sensorState.useLodScene} onchange={(event) => actions.onSetUseLodScene((event.currentTarget as HTMLInputElement).checked)} /><span><strong>Mesh LOD</strong><small>Use the synced decimated scene when it is available.</small></span></label>
			<div class="profile-link"><Settings2 size={16} /><span>pBRDF band and measured scope are managed in Settings.</span><a href="/settings">Open Settings</a></div>
			<div class="config-status"><span>{sensorState.renderConfig?.source ? `Render config · ${sensorState.renderConfig.source}` : 'Render config not loaded'}</span><button class="button button-ghost" onclick={actions.onLoadRenderConfig}>Reload config</button></div>
		</InspectorSection>
	{/if}

	<footer class="active-render">
		<div class="active-render-head"><div><p>Active render</p><strong>{sensorState.navigationSupportReady ? 'Navigation Support scene campaign' : 'Scene render campaign'}</strong></div><button class="button button-ghost" onclick={actions.onOpenMonitor}>Open Monitor</button></div>
		{#if campaign.total > 0}
			<div class="campaign-count"><strong>{campaign.completed.toLocaleString()} / {campaign.total.toLocaleString()}</strong><span>{campaign.failed ? `${campaign.failed} failed` : 'No failed tasks'}</span></div>
			<ProgressBar value={campaign.percent} tone={campaign.failed ? 'warning' : 'primary'} />
			<div class="campaign-states"><span>{campaign.running} running</span><span>{campaign.queued} queued</span><span>{campaign.failed} failed</span></div>
		{:else}<p class="help">No scene campaign is recorded yet. Submit a batch to start coverage tracking.</p>{/if}
	</footer>
</div>

<style>
	.sensors-inspector { display: grid; min-width: 0; max-width: 100%; gap: var(--space-4); overflow-x: clip; padding: var(--space-4); }
	.inspector-heading, .context-head, .batch-context, .active-render-head, .campaign-count, .sync-alert, .test-result, .config-status, .profile-link { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: var(--space-3); }
	.inspector-heading p, .active-render p { margin: 0 0 2px; color: var(--muted); font-size: var(--font-size-2xs); font-weight: var(--font-weight-bold); letter-spacing: var(--letter-spacing-wide); text-transform: uppercase; }
	.inspector-heading h2 { margin: 0; color: var(--text); font-size: var(--font-size-lg); line-height: 1.2; }
	.state-chip { flex: 0 0 auto; border-radius: var(--radius-pill); background: var(--warning-soft); color: var(--warning-strong); padding: 4px 8px; font-size: var(--font-size-2xs); font-weight: var(--font-weight-bold); }
	.state-chip.ready { background: var(--success-soft); color: var(--success-strong); }
	.sync-alert { align-items: flex-start; border: 1px solid var(--warning-border); border-radius: var(--radius-md); background: var(--warning-soft); padding: var(--space-3); }
	.sync-alert > div { display: grid; min-width: 0; gap: 3px; }
	.sync-alert span, .context-head span, .batch-context span, .camera-summary small, .target-card span, .scope-summary span, .check-row small, .help, .campaign-count span, .campaign-states { color: var(--muted-strong); font-size: var(--font-size-xs); line-height: 1.4; overflow-wrap: anywhere; }
	.sync-alert .button { flex: 0 0 auto; white-space: nowrap; }
	.context-head > div, .batch-context > div { display: grid; min-width: 0; gap: 2px; }
	.context-actions, .popover-actions { display: flex !important; align-items: center; gap: var(--space-2); }
	.icon-link { display: inline-flex; align-items: center; gap: 4px; color: var(--brand-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); text-decoration: none; white-space: nowrap; }
	.icon-button { display: inline-grid; width: 2rem; height: 2rem; place-items: center; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--panel); color: var(--text); cursor: pointer; }
	.icon-button:disabled { cursor: not-allowed; opacity: .5; }
	.field { display: grid; min-width: 0; gap: 5px; color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); }
	.field select, .field input { box-sizing: border-box; width: 100%; min-width: 0; min-height: 2.35rem; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--panel); color: var(--text); padding: 0 var(--space-3); font: inherit; }
	.camera-summary, .target-card { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--space-2); align-items: start; border: 1px solid var(--panel-border); border-radius: var(--radius-md); background: var(--surface-2); padding: var(--space-3); }
	.camera-summary span, .camera-summary small, .target-card div { min-width: 0; overflow-wrap: anywhere; }
	.camera-summary small { grid-column: 2; }
	.batch-context { position: relative; border-top: 1px solid var(--panel-border); padding-top: var(--space-3); }
	.batch-manage { position: relative; }
	.button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; }
	.manage-popover { position: absolute; z-index: 30; top: calc(100% + var(--space-2)); right: 0; display: grid; width: min(304px, calc(100vw - 48px)); gap: var(--space-3); border: 1px solid var(--panel-border); border-radius: var(--radius-md); background: var(--panel); box-shadow: var(--shadow-lg); padding: var(--space-3); }
	.manage-popover header { display: flex; align-items: center; justify-content: space-between; }
	.camera-check-list { display: grid; max-height: 12.5rem; overflow: auto; border-top: 1px solid var(--panel-border); border-bottom: 1px solid var(--panel-border); }
	.camera-check-list label { display: flex; min-width: 0; gap: var(--space-2); padding: var(--space-2) 0; }
	.camera-check-list span { display: grid; min-width: 0; gap: 2px; }
	.camera-check-list small { color: var(--muted); font-size: var(--font-size-2xs); }
	.popover-done { width: 100%; }
	.full { width: 100%; }
	.empty { margin: 0; border: 1px dashed var(--panel-border); border-radius: var(--radius-md); color: var(--muted-strong); padding: var(--space-3); font-size: var(--font-size-xs); line-height: 1.45; }
	.target-card { grid-template-columns: auto minmax(0, 1fr) auto; }
	.target-card div { display: grid; gap: 2px; }
	.target-card em { align-self: center; color: var(--muted-strong); font-size: var(--font-size-2xs); font-style: normal; white-space: nowrap; }
	.compact { max-width: 12rem; }
	.test-result, .submission-summary { border: 1px solid var(--success-border); border-radius: var(--radius-sm); background: var(--success-soft); color: var(--success-strong); padding: var(--space-2) var(--space-3); font-size: var(--font-size-xs); }
	.scope-summary { display: grid; gap: 3px; border: 1px solid var(--panel-border); border-radius: var(--radius-md); background: var(--surface-2); padding: var(--space-3); }
	.polar-summary { border-color: var(--brand-border); background: var(--brand-soft); }
	.check-row { display: flex; min-width: 0; align-items: flex-start; gap: var(--space-2); }
	.check-row span { display: grid; min-width: 0; gap: 2px; }
	.variant-control { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); }
	.variant-control > div { display: inline-flex; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); overflow: hidden; }
	.variant-control button { border: 0; border-right: 1px solid var(--panel-border); background: var(--panel); color: var(--muted-strong); padding: 6px 8px; cursor: pointer; font-size: var(--font-size-xs); }
	.variant-control button:last-child { border-right: 0; }
	.variant-control button.active { background: var(--brand); color: var(--on-brand); }
	.variant-control button:disabled { cursor: not-allowed; opacity: .45; }
	.warn { color: var(--warning-strong); }
	.submission-summary { display: flex; justify-content: space-between; gap: var(--space-2); border-color: var(--panel-border); background: var(--surface-2); color: var(--muted-strong); }
	.metric-grid, .profile-grid { display: grid; min-width: 0; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-2); }
	.profile-grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
	.readonly-profile { display: grid; min-width: 0; gap: 5px; color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); }
	.readonly-profile strong { overflow-wrap: anywhere; color: var(--text); font-size: var(--font-size-sm); }
	.profile-link { align-items: flex-start; border-top: 1px solid var(--panel-border); padding-top: var(--space-3); }
	.profile-link span { flex: 1; min-width: 0; color: var(--muted-strong); font-size: var(--font-size-xs); }
	.profile-link a { color: var(--brand-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); white-space: nowrap; }
	.config-status { color: var(--muted-strong); font-size: var(--font-size-xs); }
	.active-render { display: grid; min-width: 0; gap: var(--space-2); border: 1px solid var(--panel-border); border-radius: var(--radius-md); background: var(--surface-2); padding: var(--space-3); }
	.active-render-head strong, .campaign-count strong { color: var(--text); font-size: var(--font-size-sm); }
	.campaign-states { display: flex; flex-wrap: wrap; gap: var(--space-3); }
	.error-copy { margin: 0; color: var(--danger-strong); font-size: var(--font-size-xs); line-height: 1.4; overflow-wrap: anywhere; }
	@media (max-width: 520px) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .context-actions .icon-link span { display: none; } }
</style>
