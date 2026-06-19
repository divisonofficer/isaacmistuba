<script lang="ts">
	import { onMount } from 'svelte';
	import AssetThumb3D from '$lib/AssetThumb3D.svelte';
	import MapEditor3D from '$lib/MapEditor3D.svelte';
	import {
		builtInBuildAssets,
		builtInPlaceAssetGroups,
		type BuiltInPlaceAsset
	} from '$lib/opticalnavBuiltInAssets';
	import { assetVM } from '$lib/datasets/vm/AssetVM.svelte';
	import { sceneBottomSnippet, sceneRailSnippet } from '$lib/stores/scenePortals';
	import { bottomPanelCollapsed, bottomPanelMode, toggleBottomPanel } from '$lib/stores/shell';
	import {
		cameraRigSensorTypeToLegacyModality,
		legacySensorFromCameraRigSensor,
		normalizeRigRenderSettings,
		sensorMountHeight,
		robotMountForRender,
		sensorRenderModality,
		sensorRenderChipLabel,
		headingHasSensorModality,
		formatRigVec,
		formatResolution,
		formatRenderSpp,
		positiveInt,
		POLAR_PREVIEW_MODALITIES,
		isPolarRenderModality,
	} from '$lib/datasets/sensorHelpers';
	import { computeWorkflowReadiness } from '$lib/datasets/workflowHelpers';
	import * as validationService from '$lib/datasets/services/validationService';
	import * as episodeService from '$lib/datasets/services/episodeService';
	import * as exportJobsService from '$lib/datasets/services/exportJobsService';
	import { subscribeExportJob } from '$lib/stores/exportJobWs';
	import * as walkabilityService from '$lib/datasets/services/walkabilityService';
	import * as graphService from '$lib/datasets/services/graphService';
	import * as renderService from '$lib/datasets/services/renderService';
	import * as assetService from '$lib/datasets/services/assetService';
	import * as authoringMapService from '$lib/datasets/services/authoringMapService';
	import * as projectService from '$lib/datasets/services/projectService';
	import {
		mergeBatch,
		applyJobStatusUpdates,
		logTailsToBatchEntries,
		isGraphSweepRenderMode,
		errorMessage,
		errorPayload,
	} from '$lib/datasets/batchHelpers';
	import { subscribeJobStatus, type JobStatusMessage } from '$lib/stores/jobStatusWs';
	import ExportPanel from '$lib/datasets/ExportPanel.svelte';
	import SensorsPanel from '$lib/datasets/SensorsPanel.svelte';
	import InspectorPanel from '$lib/datasets/InspectorPanel.svelte';
	import AssetCatalog from '$lib/datasets/AssetCatalog.svelte';
	import RailStatusTab from '$lib/datasets/RailStatusTab.svelte';
	import RailExportTab from '$lib/datasets/RailExportTab.svelte';
	import RailLightsTab from '$lib/datasets/RailLightsTab.svelte';
	import RailPreviewTab from '$lib/datasets/RailPreviewTab.svelte';
	import BottomPanel from '$lib/datasets/BottomPanel.svelte';
	import RailSceneTab from '$lib/datasets/RailSceneTab.svelte';
	import RailSensorsTab from '$lib/datasets/RailSensorsTab.svelte';
	import RailPathsTab from '$lib/datasets/RailPathsTab.svelte';
	import RailSelectedTab from '$lib/datasets/RailSelectedTab.svelte';
	import {
		makeStarterAuthoringMap,
		makeVisibleStarterAuthoringMap,
		rectangleFromPoints,
		usdAssetLabel,
		typeForUsdAsset,
		placementHintForTool,
		builtInThumbType,
	} from '$lib/datasets/authoringHelpers';
	import {
		clampMapNumber as _clampMapNumber,
		svgPoint as _svgPoint,
		snapLineEndpoint as _snapLineEndpoint,
		nextAuthoringId as _nextAuthoringId,
		getItemCenter,
		rectangleStyle,
		isRegionLayerVisible as _isRegionLayerVisible,
		isObjectLayerVisible as _isObjectLayerVisible,
	} from '$lib/datasets/mapEditorHelpers';
	import {
		MATERIAL_PRESET_IDS,
		EMITTER_KEYWORD_RE,
		objectLooksLikeEmitter,
		materialValue,
		materialOptionLabel,
		materialCategoryFromText,
		materialTagsFor,
		recommendedMaterialCategory,
		findMaterialOption,
		materialPreviewSource,
		materialDisplayLabel,
		materialInfo,
		ensureAuthoringMaterial,
		buildMaterialCards,
		filterMaterialCards,
		materialMatchesSearch,
		materialSuggestion as _materialSuggestion,
		optionalJson,
		envmapSizeLabel,
		fileToDataBase64,
	} from '$lib/datasets/materialHelpers';
	import {
		addOpticalNavScene,
		attachOpticalNavSceneUsd,
		buildOpticalNavMap,
		buildOpticalNavViewpointGraph,
		graphBuildProgressWsUrl,
		compileOpticalNavAuthoringMap,
		createOpticalNavProject,
		evaluateOpticalNavDataset,
		exportOpticalNavDataset,
		getOpticalNavEditorGeometry,
		getOpticalNavAuthoringMap,
		getOpticalNavGraphRenderBatch,
		getOpticalNavEpisode,
		getOpticalNavMapAssets,
		getOpticalNavProject,
		getOpticalNavRenderBatch,
		getOpticalNavViewpointGraph,
		getSceneAnnotation,
		curatedMaterialPreviewUrl,
		listOpticalNavEpisodes,
		listOpticalNavProjects,
		listOpticalNavUsdCandidates,
		materialLibrary,
		materialPreviewUrl,
		measuredMaterialPreviewUrl,
		planOpticalNavGraphEpisodes,
		planOpticalNavEpisodes,
		renderOpticalNavEpisodes,
		saveOpticalNavAuthoringMap,
		saveSceneAnnotation,
		syncOpticalNavIsaacStage,
		syncOpticalNavRenderScene,
		opticalNavSyncProgressWsUrl,
		sweepOpticalNavViewpointGraph,
		deleteOpticalNavObservations,
		validateOpticalNavDataset,
		opticalNavAssetThumbnailUrl,
		getOpticalNavRenderConfig,
		getOpticalNavRenderReadiness,
		listOpticalNavEnvmaps,
		saveOpticalNavRenderConfig,
		uploadOpticalNavEnvmap,
		getOpticalNavGraphBatchLogs,
		scanOpticalNavObservations,
		getOpticalNavRenderSceneStats,
		getOpticalNavMaterializationAudit,
		getOpticalNavXmlSceneIndex,
		getOpticalNavRoomShell,
		addOpticalNavGraphNode,
		deleteOpticalNavGraphNode,
		getOpticalNavWalkabilityOverlay,
		paintOpticalNavWalkabilityOverlay,
		clearOpticalNavWalkabilityOverlay,
		opticalNavWalkabilityOverlayPngUrl,
		getOpticalNavTraversableGridMeta,
		opticalNavTraversableGridPngUrl,
		opticalNavEnvmapPreviewUrl,
		checkOpticalNavGraphEdge,
		regenerateOpticalNavGraphRegion,
		addOpticalNavGraphEdge,
		deleteOpticalNavGraphEdge,
		opticalNavObservationRgbUrl,
		opticalNavObservationModalityUrl,
		getJobLog,
		retryJob as retryRenderJob,
		cancelJob,
		getCameraRig,
		type CameraRig,
		type CameraRigRenderSettings,
		type CameraRigSensor
	} from '$lib/api';

	const availableModalities = [
		{ id: 'rgb', label: 'RGB', enabled: true },
		{ id: 'depth', label: 'Depth', enabled: true },
		{ id: 'active_nir_intensity', label: 'Active NIR-like', enabled: true },
		{ id: 'hazard_mask', label: 'Hazard Mask', enabled: true },
		{ id: 'polarization', label: 'Polarization', enabled: false },
		{ id: 'lidar_like', label: 'LiDAR-like', enabled: false }
	];
	const materialPresetIds = MATERIAL_PRESET_IDS;
	const hazardTypes = ['', 'transparent_obstacle', 'reflective_obstacle', 'hazard_region', 'forbidden_region', 'glass_door'];
	// Read URL params at declaration time — must happen before any $effect fires
	const _urlInit = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : new URLSearchParams();

	let loading = $state(false);
	let error = $state('');
	let info = $state('');
	let projects = $state<any[]>([]);
	function _ssGet(key: string): string | null {
		if (typeof window === 'undefined') return null;
		try { return window.sessionStorage.getItem(key); } catch { return null; }
	}
	let selectedProjectId = $state(_urlInit.get('project') ?? _ssGet('opticalnav:lastProject') ?? '');
	let project = $state<any>(null);
	let episodes = $state<any[]>([]);
	let selectedEpisodeId = $state('');
	let selectedEpisode = $state<any>(null);
	let episodeSearch = $state('');
	let selectedSensorNodeId = $state('');
	let activeModalityTab = $state('rgb');
	let activeRigSensorId = $state('');
	// assetVM.globalCameraRig, assetVM.globalCameraRigStatus, assetVM.globalCameraRigError → assetVM
	let sensorRenderResult = $state<any>(null);
	let frustumMode = $state<'none' | 'view-aligned' | 'selected'>('view-aligned');
	let renderingViewpoint = $state(false);
	type CustomSensorNode = { id: string; x: number; z: number; headingDeg: number; height_m?: number };
	let customSensorNodes = $state<CustomSensorNode[]>([]);
	let placingSensor = $state(false);
	// Per-graph-viewpoint height overrides ({vp_id: height_m}). Empty entries inherit
	// the rig mount height (camera_rig.sensors[0].mount.xyz_m[1]).
	let graphNodeHeights = $state<Record<string, number>>({});

	let renderBatch = $state<any>(null);
	let renderBatchId = $state('');
	let graphBatch = $state<any>(null);
	let graphBatchId = $state('');
	let graphBatchIds = $state<string[]>([]); // all batch IDs submitted this session

	// sessionStorage key for active render batches, scoped per (project, scene)
	// so jumping between scenes shows the right pending work.
	function _batchStorageKey(): string | null {
		if (typeof window === 'undefined') return null;
		if (!selectedProjectId || !sceneId) return null;
		return `opticalnav:batches:${selectedProjectId}:${sceneId}`;
	}
	$effect(() => {
		const key = _batchStorageKey();
		if (!key) return;
		// Add-only: deletion happens explicitly when a batch terminates (see
		// startBatchPolling). This prevents scene switches from blowing away
		// persistence — when the dropdown handler clears graphBatchIds for the
		// new scene, we don't want that to delete the previous scene's stored ids
		// before the restore effect can rehydrate them.
		if (graphBatchIds.length === 0) return;
		try {
			window.sessionStorage.setItem(key, JSON.stringify({ ids: graphBatchIds, current: graphBatchId }));
		} catch { /* silent */ }
	});

	// Restore active render batches whenever the (project, scene) selection lands
	// on a pair that has persisted work — fires on mount and on scene switches.
	let _lastRestoredBatchKey = '';
	$effect(() => {
		const key = _batchStorageKey();
		if (!key || key === _lastRestoredBatchKey) return;
		_lastRestoredBatchKey = key;
		try {
			const raw = window.sessionStorage.getItem(key);
			if (!raw) return;
			const data = JSON.parse(raw) as { ids?: string[]; current?: string };
			const ids = Array.isArray(data?.ids) ? data.ids.filter(Boolean) : [];
			if (!ids.length) return;
			graphBatchIds = [...new Set([...graphBatchIds, ...ids])];
			if (!graphBatchId && data.current) graphBatchId = data.current;
			// Kick polling so the user sees live status/logs again. `refreshBatch`
			// will mark stopped jobs as finished and stop the timer.
			startBatchPolling();
		} catch { /* silent */ }
	});

	let observationScan = $state<any>(null);
	/** Last-touched height; used as default for newly-placed cameras & the rig mount editor. */
	let cameraHeightM = $state(1.0);
	/** Ref to the MapEditor3D component (used by Preview tab to grab the current orbit camera). */
	let mapEditorRef = $state<any>(null);
	// ─── Hot Camera Preview (Preview tab) ───────────────────────────────────
	let probeRendering = $state(false);
	let probeResult = $state<{ batch_id: string; vp_id: string; heading_id: string; modality: string; modalities?: string[]; is_polar?: boolean; sensor_id?: string; submittedAt: number } | null>(null);
	let probeError = $state('');
	type HotCameraPose = {
		preview_id: string;
		x: number;
		z: number;
		yaw_deg: number;
		height_m: number;
		batch_id?: string;
		vp_id?: string;
		heading_id?: string;
		modality?: string;
		sensor_id?: string;
		rendered?: boolean;
	};
	let hotCameraPoses = $state<HotCameraPose[]>([]);
	let activeHotCameraId = $state('');
	let renderSceneStats = $state<any>(null);
	let renderSceneStatsLoading = $state(false);
	let roomShell = $state<any>(null);
	let showRoomShell = $state(true);
	// Tracks whether the user has explicitly toggled the viewer overlay since the
	// last scene/refresh. When false, the viewer default mirrors the authoring
	// flag (roomShell.enabled) so disabling the render shell also hides the editor
	// overlay by default.
	let _showRoomShellUserTouched = $state(false);
	let syncProgress = $state<{ processed: number; total: number; label: string; stage: string } | null>(null);
	let syncRunning = $state(false);
	async function refreshRoomShell() {
		if (!selectedProjectId || !sceneId) { roomShell = null; return; }
		try {
			const res = await renderService.fetchRoomShell(selectedProjectId, sceneId);
			roomShell = res?.room_shell ?? null;
			if (!_showRoomShellUserTouched && roomShell && typeof roomShell.enabled === 'boolean') {
				showRoomShell = roomShell.enabled;
			}
		} catch (err) { roomShell = null; }
	}
	$effect(() => {
		if (selectedProjectId && sceneId) refreshRoomShell();
	});
	async function refreshRenderSceneStats() {
		if (!selectedProjectId || !sceneId) return;
		renderSceneStatsLoading = true;
		try {
			renderSceneStats = await renderService.fetchRenderSceneStats(selectedProjectId, sceneId);
		} catch (err) {
			renderSceneStats = { exists: false, error: errorMessage(err) };
		} finally {
			renderSceneStatsLoading = false;
		}
	}

	// PR1: per-object materialization audit + XML scene index. Surfaced in the Sync
	// Inspector so the user can see which objects rendered as real meshes vs cube
	// fallbacks (and why), and so the editor preview can later read shapes from XML.
	let materializationAudit = $state<any>(null);
	let xmlSceneIndex = $state<any>(null);
	async function refreshMaterializationAudit() {
		if (!selectedProjectId || !sceneId) { materializationAudit = null; return; }
		try {
			materializationAudit = await renderService.fetchMaterializationAudit(selectedProjectId, sceneId);
		} catch { materializationAudit = null; }
	}
	async function refreshXmlSceneIndex() {
		if (!selectedProjectId || !sceneId) { xmlSceneIndex = null; return; }
		try {
			xmlSceneIndex = await renderService.fetchXmlSceneIndex(selectedProjectId, sceneId);
		} catch { xmlSceneIndex = null; }
	}
	$effect(() => {
		if (selectedProjectId && sceneId) {
			refreshMaterializationAudit();
			refreshXmlSceneIndex();
		}
	});

	// PR2: opt-in toggle for the XML-native editor preview. Persisted in session
	// storage so reloading the page keeps the user's choice. Default flipped to ON
	// — render-side mesh_cache is the source of truth and the editor should mirror
	// it out of the box. Only an explicit '0' (user opted out) keeps it off.
	const _SS_XML_NATIVE_PREVIEW = 'opticalnav:xmlNativePreview';
	let xmlNativePreviewEnabled = $state(_ssGet(_SS_XML_NATIVE_PREVIEW) !== '0');

	// PR2.5a': compare xml_scene_index.xml_mtime_ns vs the render_scene.xml stat
	// surfaced by /render-scene-stats. If they differ by more than 5 seconds the
	// index is older than the current XML — meshes the editor draws may not match
	// the renderer. Warn instead of silently misleading.
	const xmlIndexStale = $derived.by(() => {
		const ns = Number(xmlSceneIndex?.xml_mtime_ns);
		const isoStat = renderSceneStats?.modified_at;
		if (!ns || !isoStat) return false;
		const idxMs = ns / 1_000_000;
		const xmlMs = Date.parse(isoStat);
		if (!Number.isFinite(xmlMs)) return false;
		return Math.abs(idxMs - xmlMs) > 5000;
	});
	let _xmlStaleWarnedAt = 0;
	$effect(() => {
		if (xmlIndexStale && Date.now() - _xmlStaleWarnedAt > 30_000) {
			_xmlStaleWarnedAt = Date.now();
			console.warn('[XML-native preview] xml_scene_index.json is older than render_scene.xml — meshes shown in the editor may not reflect the current sync. Run Sync Render Scene to refresh.');
		}
	});
	$effect(() => {
		if (typeof window === 'undefined') return;
		try {
			window.sessionStorage.setItem(_SS_XML_NATIVE_PREVIEW, xmlNativePreviewEnabled ? '1' : '0');
		} catch { /* silent */ }
	});

	$effect(() => {
		if (railTab === 'preview' && selectedProjectId && sceneId) {
			refreshRenderSceneStats();
		}
	});
	let ambientRadiance = $state(1.0);
	let lightboxUrl = $state('');
	let lightboxLabel = $state('');

	let projectName = $state('OpticalNav-v0.2');
	let sceneId = $state(_urlInit.get('scene') ?? _ssGet('opticalnav:lastScene') ?? 'glass_corridor_001');
	let usdRef = $state('scenes/glass_corridor_001/scene.usd');

	// URL captures ?project= and ?scene= for shareable links; sessionStorage acts
	// as a fallback when the user navigates to a different route and back to
	// /datasets (which loses the query string). Both layers feed the same init
	// fallback chain: URL → sessionStorage → hard-coded default.
	const _SS_PROJECT_KEY = 'opticalnav:lastProject';
	const _SS_SCENE_KEY = 'opticalnav:lastScene';
	$effect(() => {
		if (typeof window === 'undefined') return;
		try {
			if (selectedProjectId) window.sessionStorage.setItem(_SS_PROJECT_KEY, selectedProjectId);
			if (sceneId) window.sessionStorage.setItem(_SS_SCENE_KEY, sceneId);
		} catch { /* silent */ }
	});

	let annotationText = $state('');
	let resolution = $state(0.05);
	let mapWidth = $state(6);
	let mapHeight = $state(4);
	let layoutDx = $state(0);
	let layoutDy = $state(0);
	// Auto-expand map bounds when USD geometry loads
	$effect(() => {
		const b = assetVM.editorGeometryPayload?.bounds;
		if (!b?.size) return;
		const sx = Number(b.size[0] ?? 0);
		const sz = Number(b.size[2] ?? 0);
		if (sx > mapWidth + 0.1) mapWidth = Math.ceil(sx);
		if (sz > mapHeight + 0.1) mapHeight = Math.ceil(sz);
	});
	let episodeCount = $state(80);
	let splits = $state('train:60,val_seen:10,val_unseen:10');
	let instructionTypes = $state('goal_only,hazard_aware,ambiguous');
	let graphScenarios = $state('goal_only,hazard_aware,stop_before_glass,detour');
	let seed = $state(0);
	let backend = $state('daemon');
	let renderMode = $state('graph_sweep');
	let renderMissingOnly = $state(true);
	let renderSplit = $state('train');
	let maxNodes = $state(300);
	let minClearance = $state(0.1);
	let showFootprint = $state(false);
	// Single source of truth for map-click interaction. Only one mode at a time.
	type PathsInteractionMode = 'select' | 'place_node' | 'paint_walkable' | 'paint_blocked' | 'paint_erase' | 'select_region' | 'add_edge' | 'inspect_edge' | 'remove_node';
	let pathsMode = $state<PathsInteractionMode>('select');
	// Derived flags consumed by the rest of the code (preserves call sites).
	const addNodeMode = $derived(pathsMode === 'place_node');
	const paintMode = $derived(
		pathsMode === 'paint_walkable' ? 'walkable'
		: pathsMode === 'paint_blocked' ? 'blocked'
		: pathsMode === 'paint_erase' ? 'erase'
		: 'none' as 'none' | 'walkable' | 'blocked' | 'erase'
	);
	const regionSelectMode = $derived(pathsMode === 'select_region');
	const addEdgeMode = $derived(pathsMode === 'add_edge');
	const edgeInspectorMode = $derived(pathsMode === 'inspect_edge');
	const removeNodeMode = $derived(pathsMode === 'remove_node');
	// Multi-select node removal (object-overlap cleanup). Declared before the
	// mode-change effect so it can be cleared there.
	let removeSelection = $state<Set<string>>(new Set());
	let removeMarginM = $state(0);
	let removePassHeightM = $state(1.2);
	let findingOverlapping = $state(false);
	let removingNodes = $state(false);
	// Reset pending selections whenever the mode changes — avoids stale state.
	$effect(() => {
		pathsMode;
		pendingEdgeSource = '';
		edgeInspectorSource = '';
		pendingRegionBbox = null;
		edgeCheckResult = null;
		removeSelection = new Set();
	});
	let paintRadiusM = $state(0.3);
	let walkabilityOverlayMeta = $state<any>(null);
	let walkabilityOverlayVersion = $state(0);  // bump to bust THREE texture cache
	let pendingRegionBbox = $state<[number, number, number, number] | null>(null);
	let pendingEdgeSource = $state('');
	// Traversable mask overlay (red = real obstacle, orange = inflation halo)
	let showTraversableMask = $state(false);
	let traversableMeta = $state<any>(null);
	let traversableVersion = $state(0);
	async function refreshTraversableMeta() {
		if (!selectedProjectId || !sceneId) { traversableMeta = null; return; }
		try {
			traversableMeta = await walkabilityService.fetchTraversableMeta(selectedProjectId, sceneId, Number(robotRadius));
			traversableVersion = traversableVersion + 1;
		} catch (err) { traversableMeta = null; }
	}
	$effect(() => {
		if (pageMode === 'paths' && showTraversableMask) refreshTraversableMeta();
	});
	let edgeInspectorSource = $state('');
	let edgeCheckResult = $state<any>(null);
	function handleInspectorFirstNode(nid: string) {
		edgeInspectorSource = nid;
		edgeCheckResult = null;
		pushActivity('info', 'edge:inspect', `Pick second node to diagnose…`);
	}
	async function handleInspectorSecondNode(source: string, target: string) {
		edgeInspectorSource = '';
		try {
			edgeCheckResult = await graphService.checkEdge(selectedProjectId, sceneId, source, target, {
				robotRadiusM: Number(robotRadius),
				maxEdgeLengthM: Number(maxEdgeLength),
			});
		} catch (err) {
			pushActivity('error', 'edge:inspect', errorMessage(err));
		}
	}
	async function addEdgeAnyway() {
		if (!edgeCheckResult?.source || !edgeCheckResult?.target) return;
		try {
			await graphService.addEdge(selectedProjectId, sceneId, edgeCheckResult.source, edgeCheckResult.target);
			pushActivity('ok', 'edge:inspect', `Edge created: ${edgeCheckResult.source} ↔ ${edgeCheckResult.target}`);
			await loadGraph();
			edgeCheckResult = null;
		} catch (err) {
			pushActivity('error', 'edge:inspect', errorMessage(err));
		}
	}
	// Note: mutual exclusion is now implicit because pathsMode is a single-select radio.
	let headingCount = $state(12);
	let minNodeSpacing = $state(0.5);
	let robotRadius = $state(0.25);
	let kNeighbors = $state(8);
	let maxEdgeLength = $state(1.5);
	let selectedModalities = $state(['rgb', 'depth', 'active_nir_intensity', 'hazard_mask']);
	let sceneStateText = $state('');
	let cameraSpecText = $state('');
	let renderConfig = $state<any>(null);
	let renderConfigError = $state('');
	let selectedBatchJobId = $state('');
	let selectedBatchJobLog = $state<string[]>([]);
	let selectedBatchJobLoading = $state(false);
	let validationReport = $state<any>(null);
	let evaluationReport = $state<any>(null);
	let exportResult = $state<any>(null);
	// Default ON: a partial sweep is the common case during dataset authoring;
	// shipping only rendered episodes keeps the exported dataset coherent.
	let exportOnlyCompleted = $state(true);
	// Default ON: validate/export should focus on the scene the user is
	// editing. Other scenes in the same project may have broken sync state
	// that has nothing to do with the current work.
	let exportCurrentSceneOnly = $state(true);
	// Opt-in: produce a per-episode RGB strip folder for visual inspection.
	let exportIncludeThumbnails = $state(false);
	// Default ON — include every heading at each waypoint (full panorama
	// context). OFF restricts to just the (vp, heading) pairs the episode
	// visits along its GT path (much slimmer bundle).
	let exportPanoramaObservations = $state(true);
	let exportPngOnly = $state(true);          // default to the lighter PNG-only bundle (no EXR)
	let exportIncludeBirdseye = $state(true);  // include a top-down bird's-eye summary PNG
	// Active scene-bundle export job — populated when user clicks Export.
	let activeExportJob = $state<import('$lib/datasets/services/exportJobsService').ExportJobStatus | null>(null);
	let _exportJobUnsub: (() => void) | null = null;
	let mapResult = $state<any>(null);
	let buildingMap = $state(false);
	let planResult = $state<any>(null);
	let graphResult = $state<any>(null);
	let buildingGraph = $state(false);
	let graphBuildProgress = $state<{ stage: string; progress: number; status: string } | null>(null);
	let graphRebuildConfirmOpen = $state(false);
	let graphPayload = $state<any>(null);
	let editor3DStatus = $state('');
	// editorGeometryPayload, editorGeometryCatalogStatus, editorGeometryRefreshToken,
	// assetThumbRefreshTick, selectedUsdAssetId, mapAssets, mapAssetStatus,
	// usdCandidates, selectedMoorelaneUsdRef, usdCandidateStatus,
	// materialGroups, materialLibraryStatus → assetVM
	let inspectorTab = $state<'object' | 'material'>('object');
	let materialPickerSearch = $state('');
	let materialPickerCategory = $state('recommended');
	let materialPickerCollection = $state('all');
	let materialPreviewValue = $state('');
	let lastInspectorItemId = '';
	let authoringMap = $state<any>(null);
	let authoringMapText = $state('');
	let compileResult = $state<any>(null);
	let syncResult = $state<any>(null);
	let renderReadiness = $state<any>(null);
	// envmapFiles, envmapUploading → assetVM
	let isaacSyncResult = $state<any>(null);
	let authoringMapDirty = $state(false);
	let inspectorError = $state('');
	let selectedAuthoringId = $state('');
	type PlacementTool =
		| 'select'
		| 'wall'
		| 'glass_wall'
		| 'mirror_wall'
		| 'chair'
		| 'table'
		| 'plant'
		| 'camera'
		| 'usd_asset'
		| 'traversable'
		| 'goal'
		| 'hazard'
		| 'start'
		| 'forbidden'
		| 'stop_before';
	let placementTool = $state<PlacementTool>('select');
	let draftPoint = $state<{ x: number; y: number } | null>(null);
	let linePreview = $state<{ x: number; y: number } | null>(null);
	let dragStart = $state<{ x: number; y: number } | null>(null);
	let dragPreview = $state<{ x: number; y: number } | null>(null);
	let objectTransformMode = $state(true);
	let surfaceSnapEnabled = $state(true);
	let gridSnapEnabled = $state(true);
	let transformGridSizeM = $state(0.05);
	let transformAngleSnapDeg = $state(15);
	let visibleLayers = $state({
		objects: true,
		traversable: true,
		goals: true,
		hazards: true,
		graphNodes: true,
		graphEdges: true,
		usdBackground: false
	});

	type PageMode = 'map' | 'objects' | 'paths' | 'sensors' | 'lights' | 'preview' | 'export';
	let pageMode = $state<PageMode>('map');
	type RailTab = 'selected' | 'scene' | 'paths' | 'sensors' | 'lights' | 'preview' | 'export' | 'status';
	let railTab = $state<RailTab>('scene');
	let lastRailSyncedPageMode: PageMode = 'map';
	let lastRailSelectedId = '';
	function activateRailTab(tab: RailTab) {
		railTab = tab;
		if (tab === 'paths') pageMode = 'paths';
		else if (tab === 'sensors') pageMode = 'sensors';
		else if (tab === 'lights') pageMode = 'lights';
		else if (tab === 'preview') pageMode = 'preview';
		else if (tab === 'export') pageMode = 'export';
		else if (tab === 'selected' && pageMode !== 'map' && pageMode !== 'objects') pageMode = 'map';
	}
	$effect(() => {
		if (pageMode === lastRailSyncedPageMode) return;
		lastRailSyncedPageMode = pageMode;
		if (pageMode === 'paths') railTab = 'paths';
		else if (pageMode === 'sensors') railTab = 'sensors';
		else if (pageMode === 'lights') railTab = 'lights';
		else if (pageMode === 'preview') railTab = 'preview';
		else if (pageMode === 'export') railTab = 'export';
		else if (railTab === 'paths') railTab = selectedAuthoringItem ? 'selected' : 'scene';
	});
	$effect(() => {
		const selectedId = selectedAuthoringItem?.id ?? '';
		if (selectedId && selectedId !== lastRailSelectedId) {
			lastRailSelectedId = selectedId;
			railTab = 'selected';
		} else if (!selectedId && lastRailSelectedId) {
			lastRailSelectedId = '';
			if (railTab === 'selected') railTab = 'scene';
		}
	});
	// MapEditor3D expects the legacy mode names. Map new tab names back to the
	// behaviour the 3D editor already implements.
	const mapEditorMode = $derived(
		pageMode === 'map' ? 'build'
		: pageMode === 'objects' ? 'place'
		: pageMode === 'sensors' ? 'sensor'
		: pageMode === 'lights' ? 'sensor'  // lights re-use sensor pointer rules (no drag-to-place)
		: pageMode === 'preview' ? 'sensor'
		: pageMode
	);

	type GhostGeom = { type: 'line'; x1: number; y1: number; x2: number; y2: number; valid: boolean }
		| { type: 'rect'; minX: number; minY: number; maxX: number; maxY: number; valid: boolean }
		| { type: 'point'; x: number; y: number; valid: boolean; sourcePath?: string; assetCat?: string; normalizedYMin?: number; baseHeightM?: number; proxySize?: [number, number, number] };
	let draftGhost = $state<GhostGeom | null>(null);

	let undoStack = $state<any[]>([]);
	let redoStack = $state<any[]>([]);
	const MAX_UNDO = 50;

	let robotPos = $state<{ x: number; y: number } | null>(null);
	let robotAnimTimer: ReturnType<typeof setInterval> | null = null;
	let batchPollTimer: ReturnType<typeof setInterval> | null = null;

	let contextMenu = $state<{ x: number; y: number; targetId: string; targetType: 'object' | 'region' } | null>(null);
	type ActivityEntry = {
		id: number;
		ts: string;
		level: 'info' | 'ok' | 'warn' | 'error';
		source: string;
		message: string;
		detail?: string;
	};
	let activitySeq = 0;
	let activityLog = $state<ActivityEntry[]>([{
		id: 0,
		ts: new Date().toLocaleTimeString(),
		level: 'info',
		source: 'datasets',
		message: 'Dataset authoring ready. Start with project and scene setup.'
	}]);
	let batchLogEntries = $state<{ job_id: string; line: string }[]>([]);

	const projectScenes = $derived(project?.scenes ?? []);
	const splitCounts = $derived(project?.split_counts ?? {});
	const currentScene = $derived(projectScenes.find((item: any) => item.scene_id === sceneId) ?? null);
	const hasScene = $derived(Boolean(currentScene));
	const currentUsdRef = $derived(String(currentScene ? (currentScene.usd_ref || '') : (usdRef || '')));
	const currentUsdPathMissing = $derived(Boolean(currentUsdRef && currentScene?.usd_exists === false));
	const hasPersistedAuthoringMap = $derived(Boolean(currentScene?.authoring_map_exists));
	const hasAuthoringMap = $derived(Boolean(hasPersistedAuthoringMap || authoringMap));
	const hasMap = $derived(Boolean(currentScene?.map_exists));
	const hasGraph = $derived(Boolean(currentScene?.viewpoint_graph_exists));
	const hasEpisodes = $derived(episodes.length > 0);
	const renderReadinessSummary = $derived(currentScene?.render_readiness ?? null);
	const effectiveRenderReadiness = $derived(renderReadiness ?? syncResult?.render_readiness ?? renderReadinessSummary);
	const currentRenderSceneStatus = $derived(String(currentScene?.sync_status?.render_scene ?? ''));
	const renderReadinessOk = $derived(Boolean(effectiveRenderReadiness?.ok));
	// Local readiness alone is not enough: annotation compile or async sync can
	// invalidate render-scene artifacts after a previous OK response.
	const renderSceneSynced = $derived(renderReadinessOk && currentRenderSceneStatus === 'synced');
	const renderConfigReady = $derived(Boolean(renderSceneSynced && sceneStateText.trim() && cameraSpecText.trim()));
	const validationPassed = $derived(Boolean(validationReport && validationReport.ok !== false));
	const authoringObjects = $derived(authoringMap?.objects ?? []);
	const authoringRegions = $derived(authoringMap?.regions ?? []);
	const graphNodes = $derived(graphPayload?.nodes ?? []);
	const graphEdges = $derived(graphPayload?.edges ?? []);
	const selectedSensorNode = $derived(
		graphNodes.find((n: any) => n.node_id === selectedSensorNodeId)
		?? (customSensorNodes.find(n => n.id === selectedSensorNodeId)
			? { node_id: selectedSensorNodeId, position: [customSensorNodes.find(n => n.id === selectedSensorNodeId)!.x, customSensorNodes.find(n => n.id === selectedSensorNodeId)!.z], isCustom: true }
			: null)
	);
	const selectedCustomSensorNode = $derived(customSensorNodes.find(n => n.id === selectedSensorNodeId) ?? null);
	const rigSensorOptions = $derived.by(() => {
		const sensors = ((assetVM.globalCameraRig?.sensors?.length
			? assetVM.globalCameraRig.sensors.map((sensor) => legacySensorFromCameraRigSensor(sensor, assetVM.globalCameraRig?.base_frame))
			: authoringMap?.camera_rig?.sensors?.length
				? authoringMap.camera_rig.sensors
				: makeStarterAuthoringMap(sceneId).camera_rig.sensors) ?? []) as any[];
		return sensors.map((sensor: any, index: number) => {
			const sensorId = String(sensor?.sensor_id || `sensor_${index + 1}`);
			const renderModality = sensorRenderModality(sensor);
			return {
				sensor_id: sensorId,
				label: String(sensor?.label || sensorId),
				modality: String(sensor?.modality || 'rgb'),
				render_modality: renderModality,
				sensor
			};
		});
	});
	const activeRigSensorOption = $derived(rigSensorOptions.find((item: any) => item.sensor_id === activeRigSensorId) ?? rigSensorOptions[0] ?? null);
	const activeRenderModality = $derived(String(activeRigSensorOption?.render_modality ?? activeModalityTab ?? 'rgb'));
	const activeCameraFrustum = $derived.by(() => {
		const sensor: any = activeRigSensorOption?.sensor ?? {};
		const rawResolution = Array.isArray(sensor.resolution) ? sensor.resolution : sensor.intrinsics?.resolution;
		const resolution = Array.isArray(rawResolution) && rawResolution.length >= 2
			? [Number(rawResolution[0] ?? 1280), Number(rawResolution[1] ?? 720)]
			: [1280, 720];
		return {
			fov_deg: Number(sensor.fov_deg ?? sensor.intrinsics?.fov_h_deg ?? 70),
			fov_v_deg: Number(sensor.fov_v_deg ?? sensor.intrinsics?.fov_v_deg ?? 0) || undefined,
			resolution,
		};
	});
	const activeHotCameraPose = $derived(
		(activeHotCameraId ? hotCameraPoses.find((item) => item.preview_id === activeHotCameraId) : null)
			?? hotCameraPoses[hotCameraPoses.length - 1]
			?? null
	);
	const hotCameraOverlays = $derived.by(() => {
		return hotCameraPoses.map((pose) => {
			const vp = pose.vp_id;
			const hid = pose.heading_id;
			const modality = pose.modality ?? activeRenderModality;
			const sensorId = pose.sensor_id ?? activeRigSensorId;
			const job = (graphBatch?.jobs ?? []).find((item: any) => item.preview_id === pose.preview_id);
			const completed = isRenderJobComplete(job);
			return {
				id: pose.preview_id,
				x: pose.x,
				z: pose.z,
				yaw_deg: pose.yaw_deg,
				height_m: pose.height_m,
				fov_deg: activeCameraFrustum.fov_deg,
				fov_v_deg: activeCameraFrustum.fov_v_deg,
				resolution: activeCameraFrustum.resolution,
				label: completed ? 'Hot preview' : 'Hot camera',
				imageUrl: completed && vp && hid
					? opticalNavObservationModalityUrl(selectedProjectId, sceneId, vp, hid, modality, sensorId)
					: '',
				vpId: vp,
				headingId: hid,
				active: pose.preview_id === activeHotCameraPose?.preview_id,
			};
		});
	});
	$effect(() => {
		if (!rigSensorOptions.length) return;
		const selected = rigSensorOptions.find((item: any) => item.sensor_id === activeRigSensorId) ?? rigSensorOptions[0];
		if (!selected) return;
		if (activeRigSensorId !== selected.sensor_id) activeRigSensorId = selected.sensor_id;
		if (activeModalityTab !== selected.render_modality) activeModalityTab = selected.render_modality;
	});
	/** Active rig sensor mount height. Used as default before per-viewpoint overrides. */
	const rigMountHeightM = $derived<number>(
		sensorMountHeight(activeRigSensorOption?.sensor ?? (assetVM.globalCameraRig?.sensors?.[0] ? legacySensorFromCameraRigSensor(assetVM.globalCameraRig.sensors[0]) : authoringMap?.camera_rig?.sensors?.[0])) || cameraHeightM
	);
	/** Height to render the currently-selected viewpoint at (per-vp override > rig default). */
	const selectedSensorHeightM = $derived<number>(
		!selectedSensorNodeId
			? rigMountHeightM
			: selectedCustomSensorNode
				? (selectedCustomSensorNode.height_m ?? rigMountHeightM)
				: (graphNodeHeights[selectedSensorNodeId] ?? rigMountHeightM)
	);
	function setSelectedSensorHeight(value: number) {
		const h = Math.max(0.05, Math.min(8.0, Number(value) || 0));
		cameraHeightM = h;
		if (!selectedSensorNodeId) {
			info = 'Rig mount height is read-only here. Edit it in /camera_rig, or select a viewpoint to override render height.';
			return;
		}
		if (selectedCustomSensorNode) {
			customSensorNodes = customSensorNodes.map(n => n.id === selectedSensorNodeId ? { ...n, height_m: h } : n);
		} else {
			graphNodeHeights = { ...graphNodeHeights, [selectedSensorNodeId]: h };
		}
	}
	const filteredEpisodes = $derived(
		episodeSearch.trim() ? episodes.filter((ep: any) => ep.episode_id?.includes(episodeSearch)) : episodes
	);
	const selectedEpisodePath = $derived.by(() => {
		if (!selectedEpisode?.path_nodes?.length) return null;
		const coords: [number, number][] = [];
		for (const id of selectedEpisode.path_nodes) {
			const n = graphNodes.find((node: any) => node.node_id === id);
			if (n?.position) coords.push([n.position[0], n.position[1]]);
		}
		return coords.length >= 2 ? coords : null;
	});
	const allEpisodePaths = $derived.by((): { coords: [number, number][]; hasHazard: boolean }[] => {
		if (!graphNodes.length || !episodes.length) return [];
		return episodes.flatMap((ep: any) => {
			if (!ep.path_nodes?.length) return [];
			const coords: [number, number][] = [];
			for (const id of ep.path_nodes) {
				const n = graphNodes.find((node: any) => node.node_id === id);
				if (n?.position) coords.push([n.position[0], n.position[1]]);
			}
			if (coords.length < 2) return [];
			return [{ coords, hasHazard: Boolean(ep.hazard_collision) }];
		});
	});
	const selectedAuthoringItem = $derived(
		[...authoringObjects, ...authoringRegions].find((item: any) => item.id === selectedAuthoringId) ?? null
	);
	const selectedAuthoringKind = $derived(
		authoringObjects.some((item: any) => item.id === selectedAuthoringId)
			? 'object'
			: authoringRegions.some((item: any) => item.id === selectedAuthoringId)
				? 'region'
				: ''
	);
	const selectedMaterialSuggestion = $derived(materialSuggestion(selectedAuthoringItem));
	const selectedMaterialInfo = $derived(materialInfo(selectedAuthoringItem?.material, assetVM.materialGroups));
	// materialCards, materialCollections, usdAssetSelectionPool, usdAssetCandidates,
	// selectedUsdAsset → assetVM
	const materialCollections = $derived(
		[...new Map(assetVM.materialCards.filter((item: any) => item.collection !== 'preset').map((item: any) => [item.collection, item.collectionLabel])).entries()]
	);
	const filteredMaterialCards = $derived(filterMaterialCards(assetVM.materialCards, selectedAuthoringItem, { search: materialPickerSearch, collection: materialPickerCollection, category: materialPickerCategory }));
	const materialPreviewEntry = $derived(
		assetVM.materialCards.find((item: any) => item.value === (materialPreviewValue || selectedAuthoringItem?.material))
		?? filteredMaterialCards[0]
		?? assetVM.materialCards[0]
		?? null
	);
	const authoringSummary = $derived({
		objects: authoringObjects.length,
		regions: authoringRegions.length,
		glass: authoringObjects.filter((item: any) => item.type === 'glass_wall').length,
		goals: authoringRegions.filter((item: any) => item.type === 'goal').length,
		traversable: authoringRegions.filter((item: any) => item.type === 'traversable').length
	});
	const hasAuthoringContent = $derived(authoringSummary.objects + authoringSummary.regions > 0);
	const activeBatch = $derived(isGraphSweepRenderMode(renderMode) ? graphBatch : renderBatch);
	// Episode path sweep is only meaningful when an episode with explicit graph
	// nodes is loaded. trajectory-only episodes have no path_nodes to filter on.
	const episodeNodesAvailable = $derived(
		Boolean(
			selectedEpisode &&
			(selectedEpisode.navigation_mode ?? 'trajectory') === 'viewpoint_graph' &&
			Array.isArray(selectedEpisode.path_nodes) &&
			selectedEpisode.path_nodes.length > 0
		)
	);
	const episodePathNodeCount = $derived(
		episodeNodesAvailable ? (selectedEpisode.path_nodes as string[]).length : 0
	);
	const selectedEpisodeSummary = $derived(
		selectedEpisode
			? {
					episode_id: selectedEpisode.episode_id,
					mode: selectedEpisode.navigation_mode ?? 'trajectory',
					split: selectedEpisode.split,
					timesteps: selectedEpisode.timesteps?.length ?? 0,
					path_nodes: selectedEpisode.path_nodes?.length ?? 0,
					observation_refs: selectedEpisode.observation_refs?.length ?? 0
				}
			: null
	);
	const graphPayloadSummary = $derived(
		graphPayload
			? {
					graph_id: graphPayload.graph_id,
					node_count: graphPayload.nodes?.length ?? 0,
					edge_count: graphPayload.edges?.length ?? 0,
					heading_count: graphPayload.node_heading_count,
					hazard_edge_count: graphPayload.edges?.filter((edge: any) => edge.hazard_crossing).length ?? 0
				}
			: null
	);
	const exportPath = $derived(
		exportResult?.download_url ??
			exportResult?.artifact_path ??
			exportResult?.zip_path ??
			exportResult?.path ??
			''
	);
	const currentReadiness = $derived(computeWorkflowReadiness({
		selectedProjectId, hasScene, hasAuthoringMap, hasAuthoringContent,
		hasPersistedAuthoringMap, authoringMapDirty, currentScene,
		hasMap, hasGraph, hasEpisodes, renderSceneSynced, renderConfigReady,
		validationReport, validationPassed,
	}));

	// _mergeIntoBatch, buildBatchJobGrid, jobStatusClass, jobStageLabel, stageIndex,
	// progressPercent, compactDetail, errorMessage, errorPayload → $lib/datasets/batchHelpers

	const selectedBatchJob = $derived(
		selectedBatchJobId
			? (activeBatch?.jobs ?? []).find((job: any) => job.job_id === selectedBatchJobId) ?? null
			: null
	);
	function isRenderJobComplete(job: any): boolean {
		const status = String(job?.status?.status ?? job?.status ?? '');
		return status === 'completed' || status === 'succeeded';
	}
	const selectedBatchJobImageUrl = $derived.by(() => {
		if (!selectedBatchJob || !isRenderJobComplete(selectedBatchJob)) return '';
		const nodeId = String(selectedBatchJob.preview_id ?? selectedBatchJob.node_id ?? '');
		const headingId = String(selectedBatchJob.heading_id ?? '');
		if (!nodeId || !headingId) return '';
		const modality = String(selectedBatchJob.modality ?? activeRenderModality);
		const sensorId = String(selectedBatchJob.sensor_id ?? activeRigSensorId);
		return opticalNavObservationModalityUrl(selectedProjectId, sceneId, nodeId, headingId, modality, sensorId);
	});

	async function selectBatchJob(job: any) {
		if (!job?.job_id) return;
		selectedBatchJobId = job.job_id;
		selectedBatchJobLog = [];
		selectedBatchJobLoading = true;
		try {
			await refreshSelectedBatchJobLog(job.job_id);
		} catch {
			selectedBatchJobLog = [];
		} finally {
			selectedBatchJobLoading = false;
		}
	}

	async function refreshSelectedBatchJobLog(jobId = selectedBatchJobId) {
		if (!jobId) return;
		const data = await getJobLog(jobId, 200);
		selectedBatchJobLog = Array.isArray(data?.lines) ? data.lines.map((line: unknown) => String(line)) : [];
	}

	async function cancelStaleBatchJobs() {
		const jobs: any[] = activeBatch?.jobs ?? [];
		const stale = jobs.filter((job: any) => {
			const status = String(job?.status?.status ?? '');
			return status === 'running' || status === 'queued' || status === 'pending';
		});
		if (!stale.length) {
			pushActivity('info', 'batch', 'No stale jobs to cancel.');
			return;
		}
		let cancelled = 0;
		for (const job of stale) {
			try {
				await cancelJob(job.job_id);
				cancelled += 1;
			} catch {
				// best effort
			}
		}
		pushActivity('ok', 'batch', `Cancelled ${cancelled} stale job(s).`);
		await refreshBatch();
	}

	async function retryBatchJob(job: any) {
		if (!job?.job_id) return;
		try {
			await retryRenderJob(job.job_id);
			pushActivity('ok', 'batch:retry', `Retry requested for ${job.job_id?.slice(-8)}`);
		} catch (err) {
			pushActivity('error', 'batch:retry', errorMessage(err));
		}
		await refreshBatch();
	}

	async function cancelBatchJob(job: any) {
		if (!job?.job_id) return;
		try {
			await cancelJob(job.job_id);
			pushActivity('ok', 'batch:cancel', `Cancel requested for ${job.job_id?.slice(-8)}`);
		} catch (err) {
			pushActivity('error', 'batch:cancel', errorMessage(err));
		}
		await refreshBatch();
	}

	function pushActivity(level: ActivityEntry['level'], source: string, message: string, detail?: unknown) {
		activitySeq += 1;
		const detailText =
			detail == null ? undefined : typeof detail === 'string' ? detail : JSON.stringify(detail);
		activityLog = [
			{
				id: activitySeq,
				ts: new Date().toLocaleTimeString(),
				level,
				source,
				message,
				detail: detailText
			},
			...activityLog
		].slice(0, 80);
	}

	function requireReady(condition: boolean, message: string): boolean {
		if (condition) return true;
		error = message;
		info = '';
		pushActivity('warn', 'guard', message);
		return false;
	}

	// makeStarterAuthoringMap, makeVisibleStarterAuthoringMap → $lib/datasets/authoringHelpers

	function createStarterOverlay() {
		setAuthoringMapPayload(makeVisibleStarterAuthoringMap(sceneId));
		selectedAuthoringId = 'glass_wall_001';
		placementTool = 'select';
		draftPoint = null;
		linePreview = null;
		dragStart = null;
		dragPreview = null;
		pushActivity('ok', 'map-editor', 'Starter overlay created with traversable, glass, mirror, and goal layers.');
	}

	function pushHistory() {
		if (!authoringMap) return;
		undoStack = [...undoStack.slice(-MAX_UNDO), JSON.parse(JSON.stringify(authoringMap))];
		redoStack = [];
	}

	function undo() {
		if (!undoStack.length) return;
		redoStack = [...redoStack, JSON.parse(JSON.stringify(authoringMap))];
		const prev = undoStack[undoStack.length - 1];
		undoStack = undoStack.slice(0, -1);
		authoringMap = prev;
		authoringMapText = JSON.stringify(prev, null, 2);
		authoringMapDirty = true;
	}

	function redo() {
		if (!redoStack.length) return;
		undoStack = [...undoStack, JSON.parse(JSON.stringify(authoringMap))];
		const next = redoStack[redoStack.length - 1];
		redoStack = redoStack.slice(0, -1);
		authoringMap = next;
		authoringMapText = JSON.stringify(next, null, 2);
		authoringMapDirty = true;
	}

	function _normalizeMaterialIds(payload: any): any {
		if (!payload) return payload;
		const fix = (id: string | null | undefined) => {
			if (!id) return id;
			const m = /^([a-z_0-9]+)\/([a-z_0-9]+)$/.exec(id);
			return m ? `${m[1]}:${m[2]}` : id;
		};
		const objects = (payload.objects ?? []).map((o: any) => o.material ? { ...o, material: fix(o.material) } : o);
		const regions = (payload.regions ?? []).map((r: any) => r.material ? { ...r, material: fix(r.material) } : r);
		return { ...payload, objects, regions };
	}

	function withRenderDefaults(payload: any) {
		const starter = makeStarterAuthoringMap(sceneId);
		return {
			...payload,
			environment: { ...(starter.environment ?? {}), ...(payload?.environment ?? {}) },
			camera_rig: {
				...(starter.camera_rig ?? {}),
				...(payload?.camera_rig ?? {}),
				sensors: payload?.camera_rig?.sensors?.length ? payload.camera_rig.sensors : starter.camera_rig.sensors
			}
		};
	}

	function setAuthoringMapPayload(payload: any, dirty = true) {
		const normalized = withRenderDefaults(_normalizeMaterialIds(payload));
		authoringMap = normalized;
		authoringMapText = JSON.stringify(normalized, null, 2);
		authoringMapDirty = dirty;
		const savedW = Number(normalized?.settings?.map_w);
		const savedH = Number(normalized?.settings?.map_h);
		if (savedW > 0) mapWidth = savedW;
		if (savedH > 0) mapHeight = savedH;
	}

	function currentAuthoringMap() {
		const text = String(authoringMapText || '').trim();
		if (text) return withRenderDefaults(JSON.parse(text));
		return ensureAuthoringMap();
	}

	function ensureAuthoringMap() {
		if (authoringMap) return authoringMap;
		const starter = makeStarterAuthoringMap(sceneId);
		setAuthoringMapPayload(starter, true);
		return starter;
	}

	// State-bound wrappers around mapEditorHelpers pure functions
	function nextAuthoringId(type: string) {
		const ids = [
			...((authoringMap?.objects ?? []).map((item: any) => String(item.id ?? ''))),
			...((authoringMap?.regions ?? []).map((item: any) => String(item.id ?? '')))
		];
		return _nextAuthoringId(type, ids);
	}

	function svgPoint(event: PointerEvent): { x: number; y: number } {
		return _svgPoint(event, mapWidth, mapHeight);
	}

	function selectBuiltInAsset(tool: string) {
		placementTool = tool as PlacementTool;
		draftPoint = null;
		linePreview = null;
		dragStart = null;
		dragPreview = null;
	}

	function selectBuiltInPlaceAsset(asset: BuiltInPlaceAsset) {
		if (asset.kind === 'primitive') {
			selectBuiltInAsset(asset.tool);
			return;
		}
		assetVM.selectedUsdAssetId = asset.asset_id;
		placementTool = 'usd_asset';
		draftPoint = null;
		linePreview = null;
		dragStart = null;
		dragPreview = null;
	}

	function markAuthoringJsonDirty() {
		authoringMapDirty = true;
	}

	function setMapWidthFromInput(value: unknown) {
		const next = clampMapNumber(value, 'positive', mapWidth);
		if (next > 0 && next !== mapWidth) {
			mapWidth = next;
			markAuthoringJsonDirty();
		}
	}

	function setMapHeightFromInput(value: unknown) {
		const next = clampMapNumber(value, 'positive', mapHeight);
		if (next > 0 && next !== mapHeight) {
			mapHeight = next;
			markAuthoringJsonDirty();
		}
	}

	function clampMapNumber(value: unknown, axis: 'x' | 'y' | 'yaw' | 'positive', fallback = 0) {
		return _clampMapNumber(value, axis, mapWidth, mapHeight, fallback);
	}

	function replaceSelectedAuthoringItem(updater: (item: any) => any) {
		if (!authoringMap || !selectedAuthoringId) return;
		pushHistory();
		inspectorError = '';
		const objects = (authoringMap.objects ?? []).map((item: any) => (item.id === selectedAuthoringId ? updater(item) : item));
		const regions = (authoringMap.regions ?? []).map((item: any) => (item.id === selectedAuthoringId ? updater(item) : item));
		setAuthoringMapPayload({ ...authoringMap, objects, regions }, true);
	}

	function replaceAuthoringObjectLive(id: string, updater: (item: any) => any) {
		if (!authoringMap || !id) return;
		inspectorError = '';
		const objects = (authoringMap.objects ?? []).map((item: any) => (item.id === id ? updater(item) : item));
		const regions = (authoringMap.regions ?? []).map((item: any) => (item.id === id ? updater(item) : item));
		setAuthoringMapPayload({ ...authoringMap, objects, regions }, true);
	}

	function updateSelectedField(field: string, value: unknown) {
		replaceSelectedAuthoringItem((item) => ({ ...item, [field]: value }));
	}

	// objectLooksLikeEmitter, kelvinToRgb, rgbToKelvinApprox — moved to $lib/datasets/materialHelpers
	const detectedEmitterIds = $derived<Set<string>>(
		new Set((authoringMap?.objects ?? []).filter(objectLooksLikeEmitter).map((o: any) => o.id))
	);
	const detectedEmitterCount = $derived(detectedEmitterIds.size);
	const enabledEmitterCount = $derived(
		(authoringMap?.objects ?? []).filter((o: any) => o?.is_emitter).length
	);
	const editorObjectsCount = $derived((authoringMap?.objects ?? []).length);
	const editorEmitterCount = $derived((authoringMap?.objects ?? []).filter((o: any) => o?.is_emitter).length);
	const editorMaterialCount = $derived((authoringMap?.materials ?? []).length);
	function setEmitters(ids: Set<string>, enabled: boolean) {
		if (!authoringMap) return;
		pushHistory();
		const objects = (authoringMap.objects ?? []).map((item: any) =>
			ids.has(item.id) ? { ...item, is_emitter: enabled } : item
		);
		setAuthoringMapPayload({ ...authoringMap, objects }, true);
		pushActivity(enabled ? 'ok' : 'info', 'lights', `${enabled ? 'Enabled' : 'Disabled'} ${ids.size} light source candidate(s).`);
	}
	function enableAllDetectedEmitters() {
		setEmitters(detectedEmitterIds, true);
	}
	function disableAllEmitters() {
		const ids = new Set<string>((authoringMap?.objects ?? []).filter((item: any) => item?.is_emitter).map((item: any) => String(item.id)));
		setEmitters(ids, false);
	}
	async function handleToggleEmitter(lightId: string, isOn: boolean) {
		if (!authoringMap) return;
		const objects = (authoringMap.objects ?? []).map((o: any) => o.id === lightId ? { ...o, is_emitter: isOn } : o);
		setAuthoringMapPayload({ ...authoringMap, objects }, true);
		await saveAuthoringMap();
	}
	function handleSetEmitterIntensity(lightId: string, intensity: number) {
		if (!authoringMap) return;
		const objects = (authoringMap.objects ?? []).map((o: any) => o.id === lightId ? { ...o, emitter_intensity: intensity } : o);
		setAuthoringMapPayload({ ...authoringMap, objects }, true);
	}
	function handleSetEmitterRadiance(lightId: string, rgb: [number, number, number]) {
		if (!authoringMap) return;
		const objects = (authoringMap.objects ?? []).map((o: any) => o.id === lightId ? { ...o, emitter_radiance: rgb } : o);
		setAuthoringMapPayload({ ...authoringMap, objects }, true);
	}
	function handleSetEmitterHeight(lightId: string, height: number) {
		if (!authoringMap) return;
		const objects = (authoringMap.objects ?? []).map((o: any) => o.id === lightId ? { ...o, geometry: { ...(o.geometry ?? {}), base_height_m: height } } : o);
		setAuthoringMapPayload({ ...authoringMap, objects }, true);
	}
	const selectedObjectGuide = $derived.by(() => {
		const item = selectedAuthoringItem;
		if (!item) return null;
		const geom = item.geometry ?? {};
		const center2d = geom.center ?? geom.start;
		if (!Array.isArray(center2d) || center2d.length < 2) return null;
		const size = Array.isArray(geom.size_m) && geom.size_m.length >= 3
			? [Number(geom.size_m[0]), Number(geom.size_m[1]), Number(geom.size_m[2])]
			: [0.5, 1.0, 0.5];
		const baseY = Number(geom.base_height_m ?? 0);
		const cy = baseY + size[1] / 2;
		return {
			center: [Number(center2d[0]), cy, Number(center2d[1])] as [number, number, number],
			size: [size[0], size[1], size[2]] as [number, number, number],
			label: item.label ?? item.id ?? 'object',
		};
	});
	// kelvinToRgb … ensureAuthoringMaterial → $lib/datasets/materialHelpers

	function updateSelectedMaterial(value: string) {
		if (!authoringMap || !selectedAuthoringId) return;
		pushHistory();
		inspectorError = '';
		const material = value || null;
		const objects = (authoringMap.objects ?? []).map((item: any) => (item.id === selectedAuthoringId ? { ...item, material } : item));
		const regions = (authoringMap.regions ?? []).map((item: any) => (item.id === selectedAuthoringId ? { ...item, material } : item));
		const materials = material ? ensureAuthoringMaterial(material, authoringMap.materials ?? [], assetVM.materialGroups) : (authoringMap.materials ?? []);
		setAuthoringMapPayload({ ...authoringMap, objects, regions, materials }, true);
	}

	function chooseMaterial(value: string) {
		materialPreviewValue = value;
		updateSelectedMaterial(value);
	}

	function applyMaterialWithSuggestedTags(value: string) {
		if (!authoringMap || !selectedAuthoringId) return;
		pushHistory();
		inspectorError = '';
		const card = assetVM.materialCards.find((item: any) => item.value === value);
		const semanticCategory = card?.category ?? materialCategoryFromText(value, 'all');
		const material = value || null;
		const applyTo = (item: any) => {
			if (item.id !== selectedAuthoringId) return item;
			const navigation = { ...(item.navigation ?? {}) };
			if (semanticCategory === 'glass') {
				Object.assign(navigation, {
					blocks_navigation: true,
					hazard_type: 'transparent_obstacle',
					include_in_hazard_mask: true,
					instruction_candidate: true,
					goal_candidate: false
				});
			} else if (semanticCategory === 'mirror') {
				Object.assign(navigation, {
					blocks_navigation: true,
					hazard_type: 'reflective_obstacle',
					include_in_hazard_mask: true,
					instruction_candidate: true,
					goal_candidate: false
				});
			} else if (semanticCategory === 'floor') {
				Object.assign(navigation, {
					blocks_navigation: false,
					hazard_type: null,
					include_in_hazard_mask: false
				});
			} else if (semanticCategory === 'furniture') {
				Object.assign(navigation, {
					blocks_navigation: true,
					hazard_type: null,
					include_in_hazard_mask: false,
					instruction_candidate: true,
					goal_candidate: true
				});
			}
			return { ...item, material, navigation };
		};
		const objects = (authoringMap.objects ?? []).map(applyTo);
		const regions = (authoringMap.regions ?? []).map(applyTo);
		const materials = material ? ensureAuthoringMaterial(material, authoringMap.materials ?? [], assetVM.materialGroups) : (authoringMap.materials ?? []);
		setAuthoringMapPayload({ ...authoringMap, objects, regions, materials }, true);
		pushActivity('ok', 'material', `Applied ${materialDisplayLabel(value, assetVM.materialGroups)} with suggested tags.`);
	}

	function updateSelectedNavigation(field: string, value: unknown) {
		replaceSelectedAuthoringItem((item) => ({
			...item,
			navigation: {
				...(item.navigation ?? {}),
				[field]: field === 'hazard_type' && !value ? null : value
			}
		}));
	}

	function updateEnvironmentField(field: string, value: unknown) {
		if (!authoringMap) setAuthoringMapPayload(makeStarterAuthoringMap(sceneId));
		const current = authoringMap ?? makeStarterAuthoringMap(sceneId);
		const environment = { ...(current.environment ?? {}) };
		if (field === 'radiance') environment.radiance = String(value).split(',').map((v) => Number(v.trim())).filter((v) => Number.isFinite(v)).slice(0, 3);
		else if (['intensity', 'rotation_deg'].includes(field)) environment[field] = Number(value);
		else if (field === 'background_visible') environment[field] = Boolean(value);
		else environment[field] = value;
		setAuthoringMapPayload({ ...current, environment }, true);
	}

	function updateSettingsField(field: string, value: unknown) {
		if (!authoringMap) setAuthoringMapPayload(makeStarterAuthoringMap(sceneId));
		const current = authoringMap ?? makeStarterAuthoringMap(sceneId);
		const settings = { ...(current.settings ?? {}) };
		if (field === 'room_shell_enabled') settings[field] = Boolean(value);
		else if (['grid_size_m', 'default_wall_height_m', 'default_wall_thickness_m'].includes(field)) settings[field] = Number(value);
		else settings[field] = value;
		setAuthoringMapPayload({ ...current, settings }, true);
	}

	// envmapSizeLabel, fileToDataBase64 → materialHelpers.ts (imported above)

	async function loadEnvmaps() {
		await assetVM.loadEnvmaps(selectedProjectId, sceneId);
	}

	async function uploadEnvmapFromInput(input: HTMLInputElement) {
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before uploading an environment map.')) return;
		const suffix = file.name.split('.').pop()?.toLowerCase() ?? '';
		if (!['exr', 'hdr', 'png', 'jpg', 'jpeg'].includes(suffix)) {
			pushActivity('warn', 'envmap', 'Use an EXR, HDR, PNG, JPG, or JPEG environment map.');
			return;
		}
		try {
			const dataBase64 = await fileToDataBase64(file);
			const data = await assetVM.uploadEnvmap(selectedProjectId, sceneId, {
				filename: file.name,
				contentType: file.type || undefined,
				dataBase64,
			});
			if (data?.envmap_ref) {
				const current = authoringMap ?? makeStarterAuthoringMap(sceneId);
				const nextMap = {
					...current,
					environment: {
						...(current.environment ?? {}),
						mode: 'envmap',
						envmap_ref: data.envmap_ref
					},
					settings: { ...(current.settings ?? {}), map_w: mapWidth, map_h: mapHeight }
				};
				setAuthoringMapPayload(nextMap, true);
				const saved = await authoringMapService.saveAuthoringMap(selectedProjectId, sceneId, nextMap);
				if (saved?.authoring_map) setAuthoringMapPayload(saved.authoring_map, false);
				syncResult = null;
				renderReadiness = null;
			}
			pushActivity('ok', 'envmap', `Uploaded ${data?.filename ?? file.name} (${envmapSizeLabel(data?.size_bytes || file.size)}).`);
			await loadEnvmaps();
		} catch (err) {
			pushActivity('error', 'envmap', errorMessage(err));
		}
	}

	// sensor helpers → $lib/datasets/batchHelpers or sensorHelpers

	async function loadGlobalCameraRig() {
		assetVM.globalCameraRigError = '';
		assetVM.globalCameraRigStatus = 'Loading camera rig preset...';
		try {
			const rig = await assetService.fetchCameraRig('ranger_mini_default');
			assetVM.globalCameraRig = rig;
			assetVM.globalCameraRigStatus = `Using ${rig.label || rig.rig_id} (${rig.sensors?.length ?? 0} sensors) from global Camera Rig preset.`;
			if (rig.sensors?.length && !rig.sensors.some((sensor) => sensor.sensor_id === activeRigSensorId)) {
				activeRigSensorId = rig.sensors[0].sensor_id;
			}
			pushActivity('ok', 'camera-rig', `Loaded ${rig.rig_id} for dataset render sensor specs.`);
		} catch (err) {
			assetVM.globalCameraRig = null;
			assetVM.globalCameraRigError = errorMessage(err);
			assetVM.globalCameraRigStatus = 'Global Camera Rig preset unavailable; falling back to legacy authoring map sensors.';
			pushActivity('warn', 'camera-rig', assetVM.globalCameraRigStatus, err);
		}
	}

	function updateCameraRigSensor(_index: number, _field: string, _value: unknown) {
		pushActivity('warn', 'camera-rig', 'Dataset sensor editing is disabled. Use /camera_rig to edit the robot rig preset.');
	}

	function addCameraRigSensor(modality = 'rgb') {
		pushActivity('warn', 'camera-rig', `Cannot add ${modality} from Dataset Sensors. Open /camera_rig and save the rig preset.`);
	}

	function removeCameraRigSensor(index: number) {
		pushActivity('warn', 'camera-rig', `Cannot remove rig sensor ${index + 1} from Dataset Sensors. Open /camera_rig to edit the preset.`);
	}

	// sensorRenderModality, sensorRenderChipLabel, headingHasSensorModality → $lib/datasets/sensorHelpers

	function selectRigRenderSensor(sensorId: string) {
		const option = rigSensorOptions.find((item: any) => item.sensor_id === sensorId) ?? rigSensorOptions[0];
		if (!option) return;
		activeRigSensorId = option.sensor_id;
		activeModalityTab = option.render_modality;
		sensorRenderResult = null;
	}

	function cameraSpecFromRigSensor(sensor: any, baseSpec: any) {
		if (!sensor) return baseSpec;
		const sensorId = String(sensor.sensor_id || 'opticalnav_front_cam');
		const rawResolution = Array.isArray(sensor.resolution) ? sensor.resolution : sensor.intrinsics?.resolution;
		const resolution = Array.isArray(rawResolution) && rawResolution.length >= 2
			? [Math.max(1, Number(rawResolution[0]) || 1280), Math.max(1, Number(rawResolution[1]) || 720)]
			: [1280, 720];
		const base = baseSpec && typeof baseSpec === 'object' ? { ...baseSpec } : {};
		const renderMount = robotMountForRender(sensor, rigMountHeightM);
		const rigId = String(assetVM.globalCameraRig?.rig_id ?? authoringMap?.camera_rig?.rig_id ?? 'mobile_base_default');
		const baseFrame = String(sensor?.mount?.parent_frame ?? assetVM.globalCameraRig?.base_frame ?? authoringMap?.camera_rig?.base_frame ?? 'base_link');
		const renderModality = sensorRenderModality(sensor);
		const extras: any = {
			...(base.extras ?? {}),
			robot_mount: renderMount,
			camera_rig_id: rigId,
			base_frame: baseFrame,
			source_sensor_modality: sensor.modality ?? 'rgb',
			render_modality: renderModality,
			camera_rig_source: sensor?.source_schema === 'camera_rig_v1' ? 'global_json_preset' : 'legacy_authoring_map',
			canonical_sensor_type: sensor?.canonical_sensor_type ?? sensor?.sensor_type ?? null,
			canonical_modalities: sensor?.modalities ?? []
		};
		if (sensor.active_emitter) extras.active_emitter = sensor.active_emitter;
		if (sensor.polarization) extras.polarization = sensor.polarization;
		if (sensor.lidar) extras.lidar = sensor.lidar;
		if (sensor.render) extras.render = sensor.render;
		return {
			...base,
			camera_id: sensorId,
			name: String(sensor.label || sensorId),
			camera_to_world: base.camera_to_world ?? [1, 0, 0, 0, 0, 1, 0, rigMountHeightM, 0, 0, 1, 0, 0, 0, 0, 1],
			fov_deg: Number(sensor.fov_deg ?? sensor.intrinsics?.fov_h_deg ?? base.fov_deg ?? 70),
			resolution,
			sensor_modality: String(sensor.modality ?? 'rgb'),
			sensor_sync_group: String(sensor.sensor_sync_group ?? base.sensor_sync_group ?? 'default'),
			calibration_ref: sensor.calibration_ref ?? base.calibration_ref ?? null,
			extras
		};
	}

	function renderSettingsFromRigSensor(sensor: any): Record<string, unknown> {
		const settings: Record<string, unknown> = { ambient_radiance: ambientRadiance };
		const render = normalizeRigRenderSettings(sensor?.render, String(sensor?.canonical_sensor_type ?? sensor?.sensor_type ?? 'rgb_camera'));
		settings.path_spp = render.path_spp;
		settings.aov_spp = render.aov_spp;
		settings.polar_spp = render.polar_spp;
		if (render.samples_per_pass != null) settings.samples_per_pass = render.samples_per_pass;
		return settings;
	}

	function updateSelectedDimension(field: 'size_x' | 'size_y' | 'size_z' | 'base_height_m' | 'pitch_deg' | 'roll_deg' | 'scale_x' | 'scale_y' | 'scale_z', value: unknown) {
		replaceSelectedAuthoringItem((item) => {
			const geometry = { ...(item.geometry ?? {}) };
			const size = [...(geometry.size_m ?? [0.5, 1.2, 0.5])];
			const scale = [...(geometry.scale ?? [1, 1, 1])];
			if (field === 'size_x') size[0] = clampMapNumber(value, 'positive', size[0]);
			else if (field === 'size_y') size[1] = clampMapNumber(value, 'positive', size[1]);
			else if (field === 'size_z') size[2] = clampMapNumber(value, 'positive', size[2]);
			else if (field === 'scale_x') scale[0] = clampMapNumber(value, 'positive', scale[0]);
			else if (field === 'scale_y') scale[1] = clampMapNumber(value, 'positive', scale[1]);
			else if (field === 'scale_z') scale[2] = clampMapNumber(value, 'positive', scale[2]);
			else geometry[field] = Number(value);
			return { ...item, geometry: { ...geometry, size_m: size, scale } };
		});
	}

	function updateSelectedPointGeometry(field: 'x' | 'y' | 'yaw_deg', value: unknown) {
		replaceSelectedAuthoringItem((item) => {
			const geometry = { ...(item.geometry ?? {}), type: 'point' };
			const center = [...(geometry.center ?? [0, 0])];
			if (field === 'x') center[0] = clampMapNumber(value, 'x', center[0] ?? 0);
			if (field === 'y') center[1] = clampMapNumber(value, 'y', center[1] ?? 0);
			return {
				...item,
				geometry: {
					...geometry,
					center,
					yaw_deg: field === 'yaw_deg' ? clampMapNumber(value, 'yaw', geometry.yaw_deg ?? 0) : geometry.yaw_deg ?? 0
				}
			};
		});
	}

	function rotateSelectedPoint(deltaDeg: number) {
		const item = selectedAuthoringItem;
		if (!item || item.geometry?.type !== 'point') return;
		const current = Number(item.geometry?.yaw_deg ?? 0);
		updateSelectedPointGeometry('yaw_deg', current + deltaDeg);
		pushActivity('ok', 'map-editor', `Rotated ${selectedAuthoringId} ${deltaDeg > 0 ? '+' : ''}${deltaDeg}°.`);
	}

	let activeObjectTransformId = '';
	let activeObjectTransformChanged = false;
	function handleObjectTransform(
		id: string,
		patch: { center?: [number, number]; base_height_m?: number; yaw_deg?: number },
		reason: 'drag_start' | 'drag_move' | 'drag_end' | 'height_move' | 'yaw_move'
	) {
		if (!id) return;
		if (reason === 'drag_start') {
			pushHistory();
			activeObjectTransformId = id;
			activeObjectTransformChanged = false;
			return;
		}
		if (reason === 'drag_end') {
			if (activeObjectTransformId === id && activeObjectTransformChanged) {
				pushActivity('ok', 'map-editor', `Moved ${id}.`);
			}
			activeObjectTransformId = '';
			activeObjectTransformChanged = false;
			return;
		}
		if (!patch || (!patch.center && patch.base_height_m == null && patch.yaw_deg == null)) return;
		activeObjectTransformChanged = true;
		replaceAuthoringObjectLive(id, (item) => {
			const geometry = { ...(item.geometry ?? {}), type: 'point' };
			const nextGeometry = { ...geometry };
			if (patch.center) {
				nextGeometry.center = [
					clampMapNumber(patch.center[0], 'x', geometry.center?.[0] ?? 0),
					clampMapNumber(patch.center[1], 'y', geometry.center?.[1] ?? 0)
				];
			}
			if (patch.base_height_m != null) {
				nextGeometry.base_height_m = Number(Math.max(0, Number(patch.base_height_m) || 0).toFixed(3));
			}
			if (patch.yaw_deg != null) {
				nextGeometry.yaw_deg = clampMapNumber(patch.yaw_deg, 'yaw', geometry.yaw_deg ?? 0);
			}
			return { ...item, geometry: nextGeometry };
		});
	}

	function updateSelectedLineGeometry(field: 'start_x' | 'start_y' | 'end_x' | 'end_y' | 'height_m' | 'thickness_m', value: unknown) {
		replaceSelectedAuthoringItem((item) => {
			const geometry = { ...(item.geometry ?? {}), type: 'line' };
			const start = [...(geometry.start ?? [0, 0])];
			const end = [...(geometry.end ?? [0, 0])];
			if (field === 'start_x') start[0] = clampMapNumber(value, 'x', start[0] ?? 0);
			if (field === 'start_y') start[1] = clampMapNumber(value, 'y', start[1] ?? 0);
			if (field === 'end_x') end[0] = clampMapNumber(value, 'x', end[0] ?? 0);
			if (field === 'end_y') end[1] = clampMapNumber(value, 'y', end[1] ?? 0);
			return {
				...item,
				geometry: {
					...geometry,
					start,
					end,
					height_m: field === 'height_m' ? clampMapNumber(value, 'positive', geometry.height_m ?? 2.4) : geometry.height_m ?? 2.4,
					thickness_m: field === 'thickness_m' ? clampMapNumber(value, 'positive', geometry.thickness_m ?? 0.08) : geometry.thickness_m ?? 0.08
				}
			};
		});
	}

	function snapLineEndpoint(
		rawPt: { x: number; y: number },
		fixedPt: [number, number] | null | undefined,
		shiftKey: boolean
	): [number, number] {
		return _snapLineEndpoint(rawPt, fixedPt, shiftKey, mapWidth, mapHeight);
	}

	function dragLineHandle(id: string, handle: 'line_start' | 'line_end', point: { x: number; y: number }, shiftKey = false) {
		if (!authoringMap) return;
		if (selectedAuthoringId !== id) selectedAuthoringId = id;
		const objects = (authoringMap.objects ?? []).map((item: any) => {
			if (item.id !== id || item.geometry?.type !== 'line') return item;
			const geometry = { ...(item.geometry ?? {}) };
			if (handle === 'line_start') {
				geometry.start = snapLineEndpoint(point, geometry.end, shiftKey);
			} else {
				geometry.end = snapLineEndpoint(point, geometry.start, shiftKey);
			}
			return { ...item, geometry };
		});
		setAuthoringMapPayload({ ...authoringMap, objects }, true);
	}

	// Drag a corner of a rectangle region (e.g. the traversable floor) to resize it
	// directly in the 3D editor. Mirrors dragLineHandle but writes region bounds.
	function dragRegionHandle(
		id: string,
		handle: 'rect_x0z0' | 'rect_x1z0' | 'rect_x0z1' | 'rect_x1z1',
		point: { x: number; y: number },
		_shiftKey = false
	) {
		if (!authoringMap) return;
		if (selectedAuthoringId !== id) selectedAuthoringId = id;
		const GAP = 0.1;
		const round = (n: number) => Number(n.toFixed(3));
		const px = round(point.x);
		const pz = round(point.y);
		const regions = (authoringMap.regions ?? []).map((item: any) => {
			if (item.id !== id || item.geometry?.type !== 'rectangle') return item;
			let [x0, z0, x1, z1] = [...(item.geometry?.bounds ?? [0, 0, 1, 1])].map(Number);
			if (handle === 'rect_x0z0') { x0 = Math.min(px, x1 - GAP); z0 = Math.min(pz, z1 - GAP); }
			else if (handle === 'rect_x1z0') { x1 = Math.max(px, x0 + GAP); z0 = Math.min(pz, z1 - GAP); }
			else if (handle === 'rect_x0z1') { x0 = Math.min(px, x1 - GAP); z1 = Math.max(pz, z0 + GAP); }
			else if (handle === 'rect_x1z1') { x1 = Math.max(px, x0 + GAP); z1 = Math.max(pz, z0 + GAP); }
			return { ...item, geometry: { ...(item.geometry ?? {}), type: 'rectangle', bounds: [x0, z0, x1, z1] } };
		});
		setAuthoringMapPayload({ ...authoringMap, regions }, true);
	}

	// Shift a single geometry block (point/line/rectangle) by (dx, dy) in-plane.
	function shiftGeometry(g: any, dx: number, dy: number): any {
		if (!g) return g;
		const out = { ...g };
		const sh = (v: any, d: number) => Number((Number(v) + d).toFixed(4));
		if (Array.isArray(g.center) && g.center.length >= 2)
			out.center = [sh(g.center[0], dx), sh(g.center[1], dy), ...g.center.slice(2)];
		if (Array.isArray(g.start) && g.start.length >= 2)
			out.start = [sh(g.start[0], dx), sh(g.start[1], dy), ...g.start.slice(2)];
		if (Array.isArray(g.end) && g.end.length >= 2)
			out.end = [sh(g.end[0], dx), sh(g.end[1], dy), ...g.end.slice(2)];
		if (Array.isArray(g.bounds) && g.bounds.length >= 4)
			out.bounds = [sh(g.bounds[0], dx), sh(g.bounds[1], dy), sh(g.bounds[2], dx), sh(g.bounds[3], dy)];
		return out;
	}

	// Translate the whole layout (every object + region) by (dx, dy). Lets the user
	// make room past the origin without re-placing each item. Camera rig mounts are
	// relative to their sensor pose and environment is global, so both are untouched.
	function translateLayout(dx: number, dy: number) {
		if (!authoringMap || (!dx && !dy)) return;
		const objects = (authoringMap.objects ?? []).map((o: any) => ({ ...o, geometry: shiftGeometry(o.geometry, dx, dy) }));
		const regions = (authoringMap.regions ?? []).map((o: any) => ({ ...o, geometry: shiftGeometry(o.geometry, dx, dy) }));
		setAuthoringMapPayload({ ...authoringMap, objects, regions }, true);
	}

	// Shift the layout so its min corner sits at +margin (no negative coords remain).
	function normalizeLayoutToPositive(margin = 0.5) {
		if (!authoringMap) return;
		let minX = Infinity, minY = Infinity;
		const consider = (x: any, y: any) => {
			const nx = Number(x), ny = Number(y);
			if (Number.isFinite(nx)) minX = Math.min(minX, nx);
			if (Number.isFinite(ny)) minY = Math.min(minY, ny);
		};
		for (const o of [...(authoringMap.objects ?? []), ...(authoringMap.regions ?? [])]) {
			const g = o?.geometry;
			if (!g) continue;
			if (Array.isArray(g.center)) consider(g.center[0], g.center[1]);
			if (Array.isArray(g.start)) consider(g.start[0], g.start[1]);
			if (Array.isArray(g.end)) consider(g.end[0], g.end[1]);
			if (Array.isArray(g.bounds)) { consider(g.bounds[0], g.bounds[1]); consider(g.bounds[2], g.bounds[3]); }
		}
		if (!Number.isFinite(minX) || !Number.isFinite(minY)) return;
		const dx = Number((margin - minX).toFixed(4));
		const dy = Number((margin - minY).toFixed(4));
		if (!dx && !dy) return;
		translateLayout(dx, dy);
	}

	function updateSelectedRectangleBound(index: number, value: unknown) {
		const item = selectedAuthoringItem;
		const existing = [...(item?.geometry?.bounds ?? [0, 0, 1, 1])];
		const proposed = [...existing];
		proposed[index] = clampMapNumber(value, index === 0 || index === 2 ? 'x' : 'y', existing[index] ?? 0);
		if (proposed[2] <= proposed[0] || proposed[3] <= proposed[1]) {
			inspectorError = 'Rectangle bounds must keep max_x > min_x and max_y > min_y.';
			return;
		}
		replaceSelectedAuthoringItem((current) => ({
			...current,
			geometry: {
				...(current.geometry ?? {}),
				type: 'rectangle',
				bounds: proposed
			}
		}));
	}

	function applyInspectorPreset(preset: 'glass' | 'mirror' | 'landmark' | 'traversable' | 'forbidden') {
		replaceSelectedAuthoringItem((item) => {
			const navigation = { ...(item.navigation ?? {}) };
			let material = item.material ?? null;
			if (preset === 'glass') {
				material = 'clear_glass';
				Object.assign(navigation, {
					blocks_navigation: true,
					hazard_type: 'transparent_obstacle',
					include_in_hazard_mask: true,
					instruction_candidate: true,
					goal_candidate: false
				});
			} else if (preset === 'mirror') {
				material = 'mirror';
				Object.assign(navigation, {
					blocks_navigation: true,
					hazard_type: 'reflective_obstacle',
					include_in_hazard_mask: true,
					instruction_candidate: true,
					goal_candidate: false
				});
			} else if (preset === 'landmark') {
				Object.assign(navigation, {
					blocks_navigation: true,
					hazard_type: null,
					include_in_hazard_mask: false,
					instruction_candidate: true,
					goal_candidate: true
				});
			} else if (preset === 'traversable') {
				Object.assign(navigation, {
					blocks_navigation: false,
					hazard_type: null,
					include_in_hazard_mask: false,
					instruction_candidate: false,
					goal_candidate: false
				});
			} else if (preset === 'forbidden') {
				Object.assign(navigation, {
					blocks_navigation: true,
					hazard_type: 'forbidden_region',
					include_in_hazard_mask: true
				});
			}
			const next = { ...item, navigation };
			if (selectedAuthoringKind === 'object' || 'material' in item) {
				(next as any).material = material;
			}
			return next;
		});
		pushActivity('ok', 'inspector', `Applied ${preset} preset to ${selectedAuthoringId}.`);
	}

	// materialSuggestion → materialHelpers.ts (state-bound wrapper):
	function materialSuggestion(item: any) { return _materialSuggestion(item, assetVM.materialGroups); }

	async function loadMaterialLibrary() {
		await assetVM.loadMaterialLibrary();
	}

	async function loadUsdCandidates() {
		await assetVM.loadUsdCandidates();
	}

	async function loadMapAssets() {
		await assetVM.loadMapAssets(selectedProjectId);
	}

	function friendlyUsdCatalogMessage(payload: any) {
		if (!currentUsdRef) return 'No USD scene is attached to this OpticalNav scene.';
		if (currentUsdPathMissing) return currentScene?.usd_error || 'Attached USD path does not exist. Choose another Moorelane USD file.';
		if (payload?.status === 'ready') {
			const count = (payload.objects ?? []).filter((item: any) => item.category !== 'floor').length;
			return `${count} USD proxy assets loaded.`;
		}
		const reason = String(payload?.reason ?? '');
		if (reason.includes('does not exist')) return 'Attached USD path does not exist. Choose another Moorelane USD file.';
		if (reason.toLowerCase().includes('pxr') || reason.toLowerCase().includes('unavailable')) {
			return 'USD proxy extraction is unavailable in the daemon runtime. Use cached geometry or Isaac-side extraction.';
		}
		return reason ? `USD asset catalog unavailable: ${reason}` : 'USD asset catalog unavailable.';
	}

	async function loadEditorGeometryCatalog(force = false, refreshExtraction = false) {
		await assetVM.loadEditorGeometryCatalog(selectedProjectId, sceneId, currentUsdRef, { force, refreshExtraction });
		assetVM.editorGeometryCatalogStatus = friendlyUsdCatalogMessage(assetVM.editorGeometryPayload);
	}

	async function extractUsdProxies() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before extracting USD proxies.')) return;
		if (!requireReady(Boolean(currentUsdRef), 'Attach a USD scene before extracting proxies.')) return;
		pushActivity('info', 'usd-extract', 'Extracting USD proxy geometry.');
		await loadEditorGeometryCatalog(true, true);
		const count = (assetVM.editorGeometryPayload?.objects ?? []).filter((item: any) => item.category !== 'floor').length;
		if (assetVM.editorGeometryPayload?.status === 'ready') {
			pushActivity('ok', 'usd-extract', `USD proxy geometry ready with ${count} placeable objects.`);
		} else {
			pushActivity('warn', 'usd-extract', friendlyUsdCatalogMessage(assetVM.editorGeometryPayload), assetVM.editorGeometryPayload?.extractor);
		}
	}

	// usdAssetLabel, placementHintForTool, builtInThumbType, typeForUsdAsset, rectangleFromPoints → $lib/datasets/authoringHelpers

	function addWallObject(
		type: 'wall' | 'glass_wall' | 'mirror_wall',
		start: { x: number; y: number },
		end: { x: number; y: number }
	) {
		pushHistory();
		const map = ensureAuthoringMap();
		const id = nextAuthoringId(type);
		const isGlass = type === 'glass_wall';
		const isWall = type === 'wall';
		const label = isWall ? 'Wall' : isGlass ? 'Glass wall' : 'Mirror wall';
		const material = isWall ? 'painted_wall' : isGlass ? 'clear_glass' : 'mirror';
		const hazardType = isWall ? null : isGlass ? 'transparent_obstacle' : 'reflective_obstacle';
		const object = {
			id,
			type,
			label,
			placement: 'line',
			geometry: {
				type: 'line',
				start: [start.x, start.y],
				end: [end.x, end.y],
				height_m: 2.4,
				thickness_m: isWall ? 0.15 : 0.08
			},
			material,
			navigation: {
				blocks_navigation: true,
				hazard_type: hazardType,
				include_in_hazard_mask: !isWall,
				instruction_candidate: !isWall,
				goal_candidate: false
			},
			metadata: {
				created_by: 'webui_map_editor'
			}
		};
		setAuthoringMapPayload({ ...map, objects: [...(map.objects ?? []), object] });
		selectedAuthoringId = id;
		pushActivity('ok', 'map-editor', `Added ${id}.`);
	}

	function addPointObject(type: 'chair' | 'table' | 'plant', center: { x: number; y: number }, baseHeightM = 0) {
		pushHistory();
		const map = ensureAuthoringMap();
		const id = nextAuthoringId(type);
		const object = {
			id,
			type,
			label: type === 'chair' ? 'Chair landmark' : type === 'table' ? 'Table landmark' : 'Plant landmark',
			placement: 'point',
			geometry: {
				type: 'point',
				center: [center.x, center.y],
				yaw_deg: 0,
				base_height_m: Number(Math.max(0, baseHeightM).toFixed(3))
			},
			material: type === 'plant' ? 'fabric' : type === 'table' ? 'wood' : 'fabric',
			navigation: {
				blocks_navigation: true,
				hazard_type: null,
				include_in_hazard_mask: false,
				instruction_candidate: true,
				goal_candidate: true
			},
			metadata: {
				created_by: 'webui_map_editor'
			}
		};
		setAuthoringMapPayload({ ...map, objects: [...(map.objects ?? []), object] });
		selectedAuthoringId = id;
		placementTool = 'select';
		pushActivity('ok', 'map-editor', `Added ${id}.`);
	}

	function addCameraObject(center: { x: number; y: number }, baseHeightM = 0) {
		pushHistory();
		const map = ensureAuthoringMap();
		const id = nextAuthoringId('camera');
		const object = {
			id,
			type: 'camera',
			label: 'Camera',
			placement: 'point',
			geometry: { type: 'point', center: [center.x, center.y], yaw_deg: 0, base_height_m: Number(Math.max(0, baseHeightM).toFixed(3)) },
			material: null,
			navigation: { blocks_navigation: false, hazard_type: null, include_in_hazard_mask: false, instruction_candidate: false, goal_candidate: false },
			metadata: { created_by: 'webui_map_editor', fov_deg: 90, resolution: [1440, 1080] }
		};
		setAuthoringMapPayload({ ...map, objects: [...(map.objects ?? []), object] });
		selectedAuthoringId = id;
		placementTool = 'select';
		pushActivity('ok', 'map-editor', `Added camera ${id}.`);
	}

	function addUsdAssetObject(center: { x: number; y: number }, baseHeightM = 0) {
		const selectedUsdAsset = assetVM.selectedUsdAsset;
		if (!selectedUsdAsset) {
			pushActivity('warn', 'asset-catalog', 'Select a USD asset before placing.');
			return;
		}
		pushHistory();
		const map = ensureAuthoringMap();
		const type = typeForUsdAsset(selectedUsdAsset);
		const id = nextAuthoringId(type);
		const sourceRef = selectedUsdAsset.source_ref ?? `${selectedUsdAsset.usd_ref ?? currentUsdRef}#${selectedUsdAsset.source_path ?? selectedUsdAsset.asset_id ?? selectedUsdAsset.id}`;
		const scale = Number(selectedUsdAsset.default_scale ?? 1);
		const rawSize = selectedUsdAsset.bounds?.size ?? [0.35, 0.5, 0.35];
		const size = Array.isArray(rawSize) ? rawSize.map((value: any) => Number(value) * scale) : [0.35, 0.5, 0.35];
		const sourceFormat = selectedUsdAsset.source_format ?? (String(sourceRef).toLowerCase().endsWith('.glb') ? 'glb' : 'usd_prim');
		const assetSourcePath = sourceFormat === 'glb' ? sourceRef : selectedUsdAsset.source_path;
		const object = {
			id,
			type,
			label: usdAssetLabel(selectedUsdAsset),
			placement: 'point',
			geometry: {
				type: 'point',
				center: [center.x, center.y],
				yaw_deg: Number(selectedUsdAsset.default_rotation ?? 0),
				base_height_m: Number(Math.max(0, baseHeightM).toFixed(3))
			},
			material: selectedUsdAsset.material_hint ?? (type === 'table' ? 'wood' : 'fabric'),
			source_ref: sourceRef,
			navigation: {
				blocks_navigation: true,
				hazard_type: null,
				include_in_hazard_mask: false,
				instruction_candidate: true,
				goal_candidate: true
			},
			metadata: {
				created_by: selectedUsdAsset.kind === 'rich_asset' ? 'built_in_asset_catalog' : 'asset_library',
				asset_id: selectedUsdAsset.asset_id ?? selectedUsdAsset.id,
				asset_category: selectedUsdAsset.category,
				asset_source_path: assetSourcePath,
				asset_source_ref: sourceRef,
				asset_source_format: sourceFormat,
				asset_source_dataset: selectedUsdAsset.source_dataset,
				asset_glb_ref: sourceFormat === 'glb' ? sourceRef : undefined,
				asset_license_ref: selectedUsdAsset.license_ref,
				asset_metadata_ref: selectedUsdAsset.metadata_ref,
				render_readiness: selectedUsdAsset.render_readiness,
				readiness_reason: selectedUsdAsset.readiness_reason,
				usable_by_agent: selectedUsdAsset.usable_by_agent,
				proxy_size: size,
				normalized_y_min: selectedUsdAsset.bounds?.min?.[1] ?? 0
			}
		};
		const materials = object.material ? ensureAuthoringMaterial(object.material, map.materials ?? [], assetVM.materialGroups) : (map.materials ?? []);
		setAuthoringMapPayload({ ...map, materials, objects: [...(map.objects ?? []), object] });
		selectedAuthoringId = id;
		placementTool = 'select';
		pushActivity('ok', 'asset-catalog', `Placed ${id} from ${sourceRef}.`);
	}

	function addRegion(type: 'traversable' | 'goal' | 'hazard' | 'start' | 'forbidden' | 'stop_before', bounds: number[]) {
		pushHistory();
		const map = ensureAuthoringMap();
		const id = nextAuthoringId(type);
		const isHazard = type === 'hazard' || type === 'forbidden';
		const isGoalLike = type === 'goal' || type === 'stop_before';
		const region = {
			id,
			type,
			label:
				type === 'goal'
					? 'Goal region'
					: type === 'start'
						? 'Start region'
						: type === 'hazard'
							? 'Hazard region'
							: type === 'forbidden'
								? 'Forbidden region'
								: type === 'stop_before'
									? 'Stop-before region'
									: 'Traversable region',
			placement: 'rectangle',
			geometry: {
				type: 'rectangle',
				bounds
			},
			navigation: {
				blocks_navigation: type === 'forbidden',
				hazard_type: isHazard ? (type === 'forbidden' ? 'forbidden_region' : 'hazard_region') : null,
				include_in_hazard_mask: isHazard,
				instruction_candidate: isGoalLike,
				goal_candidate: isGoalLike
			},
			metadata: {
				created_by: 'webui_map_editor'
			}
		};
		setAuthoringMapPayload({ ...map, regions: [...(map.regions ?? []), region] });
		selectedAuthoringId = id;
		pushActivity('ok', 'map-editor', `Added ${id}.`);
	}

	// SVG-based handlers (kept for reference, but 3D component calls the world-coord versions below)
	function onMapPointerDown(event: PointerEvent) {
		const point = svgPoint(event);
		handleGroundPointerDown(point);
	}

	function onMapPointerMove(event: PointerEvent) {
		const point = svgPoint(event);
		handleGroundPointerMove(point);
	}

	function isRectanglePlacementTool(
		tool: PlacementTool
	): tool is 'traversable' | 'goal' | 'hazard' | 'start' | 'forbidden' | 'stop_before' {
		return ['traversable', 'goal', 'hazard', 'start', 'forbidden', 'stop_before'].includes(tool);
	}

	function onMapPointerUp(event: PointerEvent) {
		const end = svgPoint(event);
		handleGroundPointerUp(end);
	}

	// World-coordinate handlers (used by MapEditor3D callbacks)
	function handleGroundPointerDown(point: { x: number; y: number }, shiftKey = false, placement: { base_height_m?: number; snap_label?: string } = {}) {
		contextMenu = null;
		const baseHeightM = surfaceSnapEnabled ? Number(placement?.base_height_m ?? 0) : 0;
		if (pageMode === 'sensors' && placingSensor) {
			const id = `custom_${Date.now()}`;
			customSensorNodes = [...customSensorNodes, { id, x: point.x, z: point.y, headingDeg: 0 }];
			selectedSensorNodeId = id;
			sensorRenderResult = null;
			placingSensor = false;
			return;
		}
		if (placementTool === 'select') {
			selectedAuthoringId = '';
			return;
		}
		if (placementTool === 'chair' || placementTool === 'table' || placementTool === 'plant') {
			addPointObject(placementTool, point, baseHeightM);
			return;
		}
		if (placementTool === 'camera') {
			addCameraObject(point, baseHeightM);
			return;
		}
		if (placementTool === 'usd_asset') {
			addUsdAssetObject(point, baseHeightM);
			return;
		}
		if (placementTool === 'wall' || placementTool === 'glass_wall' || placementTool === 'mirror_wall') {
			if (!draftPoint) {
				draftPoint = point;
				linePreview = point;
			} else {
				const [ex, ey] = snapLineEndpoint(point, [draftPoint.x, draftPoint.y], shiftKey);
				const snapped = { x: ex, y: ey };
				const distance = Math.hypot(snapped.x - draftPoint.x, snapped.y - draftPoint.y);
				if (distance >= 0.1) addWallObject(placementTool, draftPoint, snapped);
				draftPoint = null;
				linePreview = null;
			}
			return;
		}
		dragStart = point;
		dragPreview = point;
	}

	function handleGroundPointerMove(point: { x: number; y: number }, shiftKey = false) {
		if (point.x < 0 || point.y < 0) { draftGhost = null; return; } // mouseleave sentinel
		if (draftPoint && (placementTool === 'wall' || placementTool === 'glass_wall' || placementTool === 'mirror_wall')) {
			const [sx, sy] = snapLineEndpoint(point, [draftPoint.x, draftPoint.y], shiftKey);
			linePreview = { x: sx, y: sy };
		}
		if (dragStart) {
			dragPreview = point;
		}
		const inBounds = point.x > 0.05 && point.x < 5.95 && point.y > 0.05 && point.y < 3.95;
		if (placementTool === 'wall' || placementTool === 'glass_wall' || placementTool === 'mirror_wall') {
			if (draftPoint) {
				const [sx, sy] = snapLineEndpoint(point, [draftPoint.x, draftPoint.y], shiftKey);
				draftGhost = { type: 'line', x1: draftPoint.x, y1: draftPoint.y, x2: sx, y2: sy, valid: inBounds };
			} else {
				draftGhost = { type: 'point', x: point.x, y: point.y, valid: inBounds };
			}
		} else if (placementTool === 'chair' || placementTool === 'table' || placementTool === 'plant' || placementTool === 'camera' || placementTool === 'usd_asset') {
			const selectedAsset = assetVM.selectedUsdAsset;
			const sp = placementTool === 'usd_asset'
				? (selectedAsset?.source_format === 'glb' ? (selectedAsset?.source_ref ?? undefined) : (selectedAsset?.source_path ?? undefined))
				: undefined;
			const ac = placementTool === 'usd_asset' ? (assetVM.selectedUsdAsset?.category ?? undefined) : undefined;
			const ghostYMin = placementTool === 'usd_asset' ? (assetVM.selectedUsdAsset?.bounds?.min?.[1] ?? 0) : undefined;
			const rawSize = placementTool === 'usd_asset' ? (assetVM.selectedUsdAsset?.bounds?.size ?? assetVM.selectedUsdAsset?.default_proxy_size ?? undefined) : undefined;
			const proxySize = Array.isArray(rawSize) && rawSize.length >= 3
				? [Number(rawSize[0]) || 0.4, Number(rawSize[1]) || 0.5, Number(rawSize[2]) || 0.4] as [number, number, number]
				: undefined;
			draftGhost = { type: 'point', x: point.x, y: point.y, valid: inBounds, sourcePath: sp, assetCat: ac, normalizedYMin: ghostYMin, proxySize };
		} else if (isRectanglePlacementTool(placementTool)) {
			if (dragStart) {
				const b = rectangleFromPoints(dragStart, point);
				const tooSmall = Math.abs(b[2] - b[0]) < 0.15 || Math.abs(b[3] - b[1]) < 0.15;
				draftGhost = { type: 'rect', minX: b[0], minY: b[1], maxX: b[2], maxY: b[3], valid: inBounds && !tooSmall };
			} else {
				draftGhost = { type: 'point', x: point.x, y: point.y, valid: inBounds };
			}
		} else {
			draftGhost = null;
		}
	}

	function handleGroundPointerUp(point: { x: number; y: number }, _shiftKey = false) {
		if (!dragStart || !isRectanglePlacementTool(placementTool)) return;
		const bounds = rectangleFromPoints(dragStart, point);
		dragStart = null;
		dragPreview = null;
		if (Math.abs(bounds[2] - bounds[0]) < 0.15 || Math.abs(bounds[3] - bounds[1]) < 0.15) {
			pushActivity('warn', 'map-editor', 'Region too small; drag a larger rectangle.');
			return;
		}
		addRegion(placementTool, bounds);
	}

	function selectAuthoringItem(id: string) {
		contextMenu = null;
		selectedAuthoringId = id;
		placementTool = 'select';
	}

	function selectAuthoringItemFromKey(event: KeyboardEvent, id: string) {
		if (event.key !== 'Enter' && event.key !== ' ') return;
		event.preventDefault();
		selectAuthoringItem(id);
	}

	function deleteSelectedAuthoringItem() {
		if (!selectedAuthoringId || !authoringMap) return;
		pushHistory();
		setAuthoringMapPayload({
			...authoringMap,
			objects: (authoringMap.objects ?? []).filter((item: any) => item.id !== selectedAuthoringId),
			regions: (authoringMap.regions ?? []).filter((item: any) => item.id !== selectedAuthoringId)
		});
		pushActivity('ok', 'map-editor', `Deleted ${selectedAuthoringId}.`);
		selectedAuthoringId = '';
	}

	function selectedItemCenter(item = selectedAuthoringItem): { x: number; y: number } | null {
		return getItemCenter(item);
	}

	function normalizeYawDeg(value: unknown, fallback = 0): number {
		const raw = Number(value);
		const yaw = Number.isFinite(raw) ? raw : fallback;
		return Number((((yaw % 360) + 360) % 360).toFixed(1));
	}

	function editorViewYawDeg(): number | null {
		const cam = mapEditorRef?.getCurrentCamera?.();
		if (!cam) return null;
		const fx = Number(cam.target?.[0] ?? 0) - Number(cam.origin?.[0] ?? 0);
		const fz = Number(cam.target?.[2] ?? 0) - Number(cam.origin?.[2] ?? 0);
		if (!Number.isFinite(fx) || !Number.isFinite(fz) || Math.hypot(fx, fz) < 1e-6) return null;
		return normalizeYawDeg((Math.atan2(fx, -fz) * 180) / Math.PI);
	}

	function createHotCameraPreviewPose(center: { x: number; y: number }, opts: { idPrefix?: string; yaw_deg?: number | null; source?: string } = {}) {
		const selectedYaw = selectedAuthoringItem?.geometry?.yaw_deg;
		const yaw = normalizeYawDeg(
			opts.yaw_deg ?? editorViewYawDeg() ?? selectedYaw ?? activeHotCameraPose?.yaw_deg ?? 0
		);
		const previewId = `${opts.idPrefix ?? 'probe'}_${Date.now()}`;
		const nextPose: HotCameraPose = {
			preview_id: previewId,
			x: Number(center.x.toFixed(3)),
			z: Number(center.y.toFixed(3)),
			yaw_deg: yaw,
			height_m: rigMountHeightM,
			modality: activeRenderModality,
			sensor_id: activeRigSensorId,
			rendered: false,
		};
		hotCameraPoses = [...hotCameraPoses, nextPose];
		activeHotCameraId = previewId;
		probeError = '';
		probeResult = null;
		pageMode = 'preview';
		lastRailSelectedId = selectedAuthoringItem?.id ?? lastRailSelectedId;
		railTab = 'preview';
		pushActivity('info', 'preview:hot-camera', `${opts.source ?? 'Hot camera'} placed at x=${nextPose.x.toFixed(2)} z=${nextPose.z.toFixed(2)} yaw=${nextPose.yaw_deg.toFixed(1)}.`);
		return nextPose;
	}

	function previewFromSelected() {
		const center = selectedItemCenter();
		if (!center) return;
		stopRobotAnimation();
		robotPos = center;
		placementTool = 'select';
		createHotCameraPreviewPose(center, { idPrefix: 'preview_from_here', source: `Preview from ${selectedAuthoringId || 'selection'}` });
		closeContextMenu();
	}

	function createRegionAroundSelected(type: 'start' | 'goal') {
		const center = selectedItemCenter();
		if (!center) return;
		const half = type === 'start' ? 0.28 : 0.35;
		addRegion(type, [
			clampMapNumber(center.x - half, 'x'),
			clampMapNumber(center.y - half, 'y'),
			clampMapNumber(center.x + half, 'x'),
			clampMapNumber(center.y + half, 'y')
		]);
		pushActivity('ok', 'map-editor', `Created ${type} region from ${selectedAuthoringId}.`);
		closeContextMenu();
	}

	function handleEditorKeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		const isTyping = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.tagName === 'SELECT';
		if (event.key === 'Escape') {
			draftPoint = null;
			linePreview = null;
			dragStart = null;
			dragPreview = null;
			draftGhost = null;
			placementTool = 'select';
			contextMenu = null;
		}
		if (event.ctrlKey && event.key === 'z') {
			event.preventDefault();
			undo();
			return;
		}
		if (event.ctrlKey && (event.key === 'y' || (event.shiftKey && event.key === 'z'))) {
			event.preventDefault();
			redo();
			return;
		}
		if (!isTyping && selectedAuthoringItem?.geometry?.type === 'point') {
			if (event.key.toLowerCase() === 'q') {
				event.preventDefault();
				rotateSelectedPoint(-45);
				return;
			}
			if (event.key.toLowerCase() === 'e') {
				event.preventDefault();
				rotateSelectedPoint(45);
				return;
			}
			if (event.key === '[') {
				event.preventDefault();
				rotateSelectedPoint(-15);
				return;
			}
			if (event.key === ']') {
				event.preventDefault();
				rotateSelectedPoint(15);
				return;
			}
		}
		if ((event.key === 'Delete' || event.key === 'Backspace') && selectedAuthoringId) {
			if (isTyping) return;
			deleteSelectedAuthoringItem();
		}
	}

	function stopRobotAnimation() {
		if (robotAnimTimer !== null) {
			clearInterval(robotAnimTimer);
			robotAnimTimer = null;
		}
		robotPos = null;
	}

	function startRobotAnimation() {
		stopRobotAnimation();
		const nodes = graphPayload?.nodes ?? [];
		if (!nodes.length) return;
		let step = 0;
		const update = () => {
			const node = nodes[step % nodes.length];
			if (node) robotPos = { x: node.position?.[0] ?? 0, y: node.position?.[1] ?? 0 };
			step = (step + 1) % nodes.length;
		};
		update();
		robotAnimTimer = setInterval(update, 400);
	}

	async function enterSimulateMode() {
		// Sim mode merged into 'preview' tab; only robot animation kept.
		pageMode = 'preview';
		placementTool = 'select';
		draftPoint = null;
		linePreview = null;
		dragStart = null;
		dragPreview = null;
		draftGhost = null;
		if (!hasMap && selectedProjectId && hasScene) await buildMap();
		if (!hasGraph && selectedProjectId && hasMap) await buildGraph();
		if (graphPayload?.nodes?.length) {
			startRobotAnimation();
		} else if (selectedProjectId && hasGraph) {
			await loadGraph();
			startRobotAnimation();
		}
	}

	function leaveSimulateMode(mode: PageMode) {
		stopRobotAnimation();
		pageMode = mode;
	}

	function handleContextMenu(event: MouseEvent, id: string, type: 'object' | 'region') {
		event.preventDefault();
		selectAuthoringItem(id);
		contextMenu = { x: event.clientX, y: event.clientY, targetId: id, targetType: type };
	}

	function closeContextMenu() {
		contextMenu = null;
	}

	function contextMenuDelete() {
		closeContextMenu();
		deleteSelectedAuthoringItem();
	}

	function contextMenuDuplicate() {
		if (!authoringMap || !selectedAuthoringId) { closeContextMenu(); return; }
		pushHistory();
		const all = [...(authoringMap.objects ?? []), ...(authoringMap.regions ?? [])];
		const source = all.find((item: any) => item.id === selectedAuthoringId);
		if (!source) { closeContextMenu(); return; }
		const newId = nextAuthoringId(source.type ?? 'item');
		const copy = { ...JSON.parse(JSON.stringify(source)), id: newId };
		if (copy.geometry?.type === 'line') {
			copy.geometry.start = [(copy.geometry.start?.[0] ?? 0) + 0.15, (copy.geometry.start?.[1] ?? 0) + 0.15];
			copy.geometry.end = [(copy.geometry.end?.[0] ?? 0) + 0.15, (copy.geometry.end?.[1] ?? 0) + 0.15];
		} else if (copy.geometry?.type === 'point') {
			copy.geometry.center = [(copy.geometry.center?.[0] ?? 0) + 0.15, (copy.geometry.center?.[1] ?? 0) + 0.15];
		} else if (copy.geometry?.type === 'rectangle') {
			copy.geometry.bounds = copy.geometry.bounds?.map((v: number, i: number) => v + (i < 2 ? 0.15 : 0.15));
		}
		const isObject = (authoringMap.objects ?? []).some((item: any) => item.id === selectedAuthoringId);
		const payload = isObject
			? { ...authoringMap, objects: [...(authoringMap.objects ?? []), copy] }
			: { ...authoringMap, regions: [...(authoringMap.regions ?? []), copy] };
		setAuthoringMapPayload(payload);
		selectedAuthoringId = newId;
		closeContextMenu();
		pushActivity('ok', 'map-editor', `Duplicated ${selectedAuthoringId} → ${newId}.`);
	}

	// rectangleStyle, isRegionLayerVisible, isObjectLayerVisible → mapEditorHelpers (imported above)
	// State-bound wrappers:
	function isRegionLayerVisible(type: string) { return _isRegionLayerVisible(type, visibleLayers); }
	function isObjectLayerVisible(type: string) { return _isObjectLayerVisible(type, visibleLayers); }

	function graphNode(nodeId: string) {
		return graphNodes.find((node: any) => node.node_id === nodeId);
	}

	function toggleLayer(layer: keyof typeof visibleLayers) {
		visibleLayers = { ...visibleLayers, [layer]: !visibleLayers[layer] };
	}

	// readinessState() → workflowHelpers.ts (computeWorkflowReadiness)
	// currentReadiness $derived is declared above near line 881

	const tabToMode: Record<string, PageMode> = { scene: 'map', plan: 'paths', render: 'sensors', review: 'export' };
	async function runPrimaryAction() {
		const readiness = currentReadiness;
		pageMode = tabToMode[readiness.tab] ?? 'map';
		if (readiness.kind === 'create_project') return createProject();
		if (readiness.kind === 'add_scene') return addScene();
		if (readiness.kind === 'create_overlay') {
			createStarterOverlay();
			return;
		}
		if (readiness.kind === 'save_overlay') return saveAuthoringMap();
		if (readiness.kind === 'compile_annotation') return compileAuthoringMap();
		if (readiness.kind === 'build_map') return buildMap();
		if (readiness.kind === 'build_graph') return buildGraph();
		if (readiness.kind === 'plan_graph_episodes') return planGraphEpisodes();
		if (readiness.kind === 'sync_render_scene') return syncRenderScene();
		if (readiness.kind === 'configure_render') {
			pushActivity('warn', 'render-config', 'Render config required: provide scene state and camera spec.');
			return;
		}
		if (readiness.kind === 'validate') return validateDataset(false);
		if (readiness.kind === 'export') return exportDataset();
	}

	async function run<T>(fn: () => Promise<T>, success?: string, source = 'api'): Promise<T | undefined> {
		loading = true;
		error = '';
		info = '';
		const silent = success === undefined;
		if (!silent) pushActivity('info', source, 'Request started.');
		try {
			const result = await fn();
			if (success) { info = success; pushActivity('ok', source, success, result); }
			return result;
		} catch (err) {
			error = errorMessage(err);
			pushActivity('error', source, error, errorPayload(err));
			return undefined;
		} finally {
			loading = false;
		}
	}

	async function refreshProjects(selectId = selectedProjectId) {
		const data = await run(() => projectService.fetchProjects(), undefined, 'projects:list');
		if (!data) return;
		projects = data.projects ?? [];
		if (selectId && projects.some((item) => item.project_id === selectId)) {
			selectedProjectId = selectId;
		} else if (!selectedProjectId && projects.length) {
			selectedProjectId = projects[0].project_id;
		}
		if (selectedProjectId) await refreshProject();
	}

	async function refreshProject() {
		if (!selectedProjectId) return;
		const data = await run(() => projectService.fetchProject(selectedProjectId), undefined, 'project:detail');
		if (!data) return;
		project = data;
		if (!sceneId && data.scenes?.length) sceneId = data.scenes[0].scene_id;
		const scene = data.scenes?.find((item: any) => item.scene_id === sceneId);
		if (scene?.usd_ref) usdRef = scene.usd_ref;
		await loadMapAssets();
		await loadEnvmaps();
		await refreshEpisodes();
		// Auto-load authoring map if one exists on the server and we have nothing in memory yet.
		// Guard: skip if authoringMap is already populated (e.g. unsaved edits in this session).
		if (scene?.authoring_map_exists && !authoringMap) {
			const mapData = await run(
				() => authoringMapService.fetchAuthoringMap(selectedProjectId, sceneId),
				undefined,
				'authoring-map:load'
			);
			if (mapData) setAuthoringMapPayload(mapData, false);
		}
		await loadRenderReadiness();
		// Load render config if not already populated
		if (!sceneStateText.trim()) await loadRenderConfig();
	}

	async function createProject() {
		const data = await run(
			() =>
				projectService.createProject({ name: projectName }),
			'Project created.',
			'project:create'
		);
		if (data?.project_id) await refreshProjects(data.project_id);
	}

	async function addScene() {
		if (!selectedProjectId) return;
		const data = await run(
			() => projectService.addScene(selectedProjectId, { sceneId, usdRef }),
			'Scene added with starter annotation.',
			'scene:add'
		);
		if (data?.annotation) annotationText = JSON.stringify(data.annotation, null, 2);
		await refreshProject();
	}

	async function attachUsdScene(ref = assetVM.selectedMoorelaneUsdRef || usdRef) {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before attaching USD.')) return;
		const nextRef = String(ref || '').trim();
		if (!requireReady(Boolean(nextRef), 'Choose a USD file before attaching it.')) return;
		const data = await run(
			() => projectService.attachUsdScene(selectedProjectId, sceneId, nextRef),
			'USD scene attached.',
			'scene:usd-ref'
		);
		if (data?.usd_ref) usdRef = data.usd_ref;
		assetVM.editorGeometryPayload = null;
		await refreshProject();
		await loadEditorGeometryCatalog(true);
	}

	async function loadAuthoringMap() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before loading the map overlay.')) return;
		const data = await run(
			() => authoringMapService.fetchAuthoringMap(selectedProjectId, sceneId),
			undefined,
			'authoring-map:load'
		);
		if (data) setAuthoringMapPayload(data, false);
		await loadEnvmaps();
	}

	async function saveAuthoringMap(options: { updateRenderReadiness?: boolean; deferRenderSync?: boolean } = {}): Promise<boolean> {
		const updateRenderReadiness = options.updateRenderReadiness !== false;
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return false;
		if (!requireReady(hasScene, 'Add the scene before saving the map overlay.')) return false;
		let payload: any;
		try {
			payload = currentAuthoringMap();
		} catch (err) {
			error = `Invalid authoring_map JSON: ${errorMessage(err)}`;
			pushActivity('error', 'authoring-map:save', error);
			return false;
		}
		payload = {
			...payload,
			settings: { ...(payload.settings ?? {}), map_w: mapWidth, map_h: mapHeight },
			...(options.deferRenderSync ? { defer_render_scene_sync: true } : {}),
		};
		const data = await run(
			() => authoringMapService.saveAuthoringMap(selectedProjectId, sceneId, payload),
			'Map overlay saved.',
			'authoring-map:save'
		);
		if (!data) return false;
		if (data?.authoring_map) setAuthoringMapPayload(data.authoring_map, false);
		// Phase 3: PUT /authoring-map now regenerates render_scene.xml automatically.
		// Update render readiness from the response so Sync button is no longer needed.
		if (updateRenderReadiness && data?.render_readiness) {
			syncResult = null;
			renderReadiness = data.render_readiness;
			if (data.render_readiness.ok === false) {
				pushActivity('warn', 'render-readiness', 'Map saved, but render readiness is blocked.', data.render_readiness);
			}
		}
		await refreshProject();
		// Reload render config (sceneStateText/cameraSpecText) if XML was freshly generated.
		if (updateRenderReadiness && data?.render_readiness?.ok && !sceneStateText.trim()) await loadRenderConfig();
		return true;
	}

	async function saveMap() {
		const saved = await saveAuthoringMap({ updateRenderReadiness: false, deferRenderSync: true });
		if (!saved) return;
		// Phase 3 readiness split: Save Map is now render-only. The render sync
		// path no longer needs scene_annotation.json (backend builds a minimal
		// SceneAnnotation when missing). Dataset compile, which requires a
		// traversable region, is a separate user action exposed elsewhere — no
		// point gating render iteration on it. Users still get explicit access
		// via the "Compile annotation" button.
		await syncRenderScene();
	}

	async function compileAuthoringMap(): Promise<boolean> {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return false;
		if (!requireReady(hasScene, 'Add the scene before compiling annotation.')) return false;
		if (!requireReady(hasAuthoringMap, 'Create or load a map overlay before compiling annotation.')) return false;
		const data = await run(
			() => authoringMapService.compileAuthoringMap(selectedProjectId, sceneId),
			'Map overlay compiled to scene_annotation.json.',
			'authoring-map:compile'
		);
		if (!data) return false;
		if (data) {
			compileResult = data;
			if (data.annotation) annotationText = JSON.stringify(data.annotation, null, 2);
			syncResult = null;
			renderReadiness = null;
			sceneStateText = '';
			cameraSpecText = '';
		}
		await refreshProject();
		return true;
	}

	async function loadAnnotation() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before loading annotation.')) return;
		const data = await run(() => authoringMapService.fetchAnnotation(selectedProjectId, sceneId), undefined, 'annotation:load');
		if (data) annotationText = JSON.stringify(data, null, 2);
	}

	async function saveAnnotation() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before saving annotation.')) return;
		let payload: unknown;
		try {
			payload = JSON.parse(annotationText);
		} catch (err) {
			error = `Invalid annotation JSON: ${errorMessage(err)}`;
			return;
		}
		await run(() => authoringMapService.saveAnnotation(selectedProjectId, sceneId, payload), 'Annotation saved and validated.', 'annotation:save');
		await refreshProject();
	}

	async function buildMap() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add and validate the scene before building a traversable grid.')) return;
		buildingMap = true;
		const data = await run(
			() => walkabilityService.buildTraversableMap(selectedProjectId, sceneId, Number(resolution)),
			'Traversable grid built.',
			'map:build'
		);
		buildingMap = false;
		if (data) mapResult = data;
		await refreshProject();
	}

	async function syncRenderScene() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before syncing render scene.')) return;
		syncRunning = true;
		syncProgress = { processed: 0, total: 0, label: 'starting', stage: 'queued' };
		try {
			const result = await renderService.syncRenderScene(
				selectedProjectId, sceneId, {},
				(p) => { syncProgress = p; }
			);
			await _finalizeSyncResult(result);
		} catch (err) {
			pushActivity('error', 'sync:render-scene', errorMessage(err));
		} finally {
			syncRunning = false;
			syncProgress = null;
		}
	}
	async function _finalizeSyncResult(data: any) {
		if (data) {
			syncResult = data;
			renderReadiness = data.render_readiness ?? null;
			const mes = data.mesh_extraction_stats;
			if (mes && typeof mes === 'object') {
				const attached = mes.mesh_attached ?? 0;
				const fallback = mes.cube_fallback ?? 0;
				const elapsedMs = mes.extraction_time_ms ?? 0;
				pushActivity('info', 'sync:meshes', `${attached} OBJ meshes attached · ${fallback} cube fallbacks · ${(elapsedMs / 1000).toFixed(1)}s`);
			}
			await refreshRenderSceneStats();
			await refreshRoomShell();
		}
		await refreshProject();
		if (data?.ok) await loadRenderConfig();
	}

	async function loadRenderReadiness() {
		if (!selectedProjectId || !sceneId) return;
		try {
			renderReadiness = await renderService.fetchRenderReadiness(selectedProjectId, sceneId);
		} catch {
			renderReadiness = null;
		}
	}

	async function loadRenderConfig() {
		if (!selectedProjectId || !sceneId) return;
		try {
			const data = await renderService.fetchRenderConfig(selectedProjectId, sceneId);
			if (data?.ok && data.scene_state && data.camera_spec) {
				renderConfig = data;
				renderConfigError = '';
				sceneStateText = JSON.stringify(data.scene_state, null, 2);
				cameraSpecText = JSON.stringify(data.camera_spec, null, 2);
			} else if (data && !data.ok) {
				renderConfigError = data.error ?? 'No render config available';
			}
		} catch (err: any) {
			renderConfigError = err?.message ?? 'Failed to load render config';
		}
	}

	async function saveRenderConfig() {
		if (!selectedProjectId || !sceneId) return;
		try {
			const scene_state = JSON.parse(sceneStateText);
			const camera_spec = JSON.parse(cameraSpecText);
			const data = await renderService.saveRenderConfig(selectedProjectId, sceneId, scene_state, camera_spec);
			if (data?.ok) {
				renderConfig = data;
				pushActivity('ok', 'render-config', 'Render config saved.');
			}
		} catch (err) {
			pushActivity('error', 'render-config', `Save failed: ${errorMessage(err)}`);
		}
	}

	async function syncIsaacStage() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before syncing Isaac stage.')) return;
		if (!requireReady(renderSceneSynced, 'Sync render scene before syncing the Isaac stage.')) return;
		const data = await run(
			() => renderService.syncIsaacStage(selectedProjectId, sceneId),
			'Isaac stage sync command queued.',
			'sync:isaac-stage'
		);
		if (data) isaacSyncResult = data;
		await refreshProject();
	}

	function requestBuildGraph() {
		if (hasGraph) {
			graphRebuildConfirmOpen = true;
			return;
		}
		void buildGraph();
	}

	function confirmGraphRebuild() {
		graphRebuildConfirmOpen = false;
		void buildGraph();
	}

	function cancelGraphRebuild() {
		graphRebuildConfirmOpen = false;
	}

	async function buildGraph() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasMap, 'Build the traversable grid before building a viewpoint graph.')) return;
		buildingGraph = true;
		graphBuildProgress = null;
		const data = await run(
			() => graphService.buildGraph(selectedProjectId, sceneId, {
				maxNodes: Number(maxNodes), headingCount: Number(headingCount),
				minNodeSpacingM: Number(minNodeSpacing), robotRadiusM: Number(robotRadius),
				minClearanceM: Number(minClearance), kNeighbors: Number(kNeighbors),
				maxEdgeLengthM: Number(maxEdgeLength), resolution: Number(resolution), seed: Number(seed),
			}, (p) => { graphBuildProgress = p; }),
			'Viewpoint graph built.',
			'graph:build'
		);
		buildingGraph = false;
		graphBuildProgress = null;
		if (data) graphResult = data;
		await refreshProject();
		if (data) await loadGraph();
	}

	async function loadGraph() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasGraph, 'Build the viewpoint graph before loading graph JSON.')) return;
		const data = await run(() => graphService.fetchGraph(selectedProjectId, sceneId), undefined, 'graph:load');
		if (data) graphPayload = data;
	}

	async function scanObservations() {
		if (!selectedProjectId || !sceneId) return;
		try {
			const data = await episodeService.scanObservations(selectedProjectId, sceneId);
			if (data) observationScan = data;
		} catch (_) {
			// ignore scan errors silently
		}
	}

	async function clearNodeObservations(nodeId: string) {
		if (!selectedProjectId || !sceneId) return;
		try {
			await episodeService.clearNodeObservations(selectedProjectId, sceneId, nodeId);
			pushActivity('ok', 'sensor:clear', `Renders cleared for ${nodeId}`);
		} catch (err) {
			pushActivity('error', 'sensor:clear', errorMessage(err));
		}
		await scanObservations();
	}

	async function clearAllObservations() {
		if (!selectedProjectId || !sceneId) return;
		if (!confirm('씬의 모든 렌더 결과를 삭제하시겠습니까?')) return;
		try {
			await episodeService.clearAllObservations(selectedProjectId, sceneId);
			pushActivity('ok', 'scene:clear_renders', 'All renders cleared.');
		} catch (err) {
			pushActivity('error', 'scene:clear_renders', errorMessage(err));
		}
		await scanObservations();
	}

	function hasNodeObservations(nodeId: string | undefined): boolean {
		if (!nodeId) return false;
		return (observationScan?.viewpoints?.[nodeId]?.completed ?? 0) > 0;
	}

	async function planEpisodes() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasMap, 'Build the traversable grid before planning v0.1 episodes.')) return;
		const splitObject = Object.fromEntries(
			splits.split(',').map((part) => {
				const [name, value] = part.split(':');
				return [name.trim(), Number(value)];
			})
		);
		const data = await run(
			() => episodeService.planEpisodes(selectedProjectId, {
				sceneId, numPairs: Number(episodeCount), splits: splitObject,
				instructionTypes: instructionTypes.split(',').map((s) => s.trim()).filter(Boolean),
				modalities: selectedModalities, seed: Number(seed),
			}),
			'Episodes planned.',
			'episodes:plan-v0.1'
		);
		if (data) planResult = data;
		await refreshProject();
	}

	function clearEpisodes() {
		episodes = [];
		selectedEpisode = null;
		selectedEpisodeId = '';
		pushActivity('info', 'episodes', 'Episodes cleared. Regenerate when ready.');
	}

	async function planGraphEpisodes() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasGraph, 'Build the viewpoint graph before planning graph episodes.')) return;
		const splitObject = Object.fromEntries(
			splits.split(',').map((part) => {
				const [name, value] = part.split(':');
				return [name.trim(), Number(value)];
			})
		);
		const data = await run(
			() => episodeService.planGraphEpisodes(selectedProjectId, {
				sceneId, numPairs: Number(episodeCount), splits: splitObject,
				scenarios: graphScenarios.split(',').map((s) => s.trim()).filter(Boolean),
				modalities: selectedModalities, seed: Number(seed),
			}),
			'Graph episodes planned.',
			'episodes:plan-graph'
		);
		if (data) planResult = data;
		await refreshProject();
	}

	async function refreshEpisodes() {
		if (!selectedProjectId) return;
		const data = await run(() => episodeService.fetchEpisodes(selectedProjectId), undefined, 'episodes:list');
		if (!data) return;
		const all: any[] = data.episodes ?? [];
		episodes = sceneId ? all.filter((ep: any) => !ep.scene_id || ep.scene_id === sceneId) : all;
		if (!selectedEpisodeId && episodes.length) selectedEpisodeId = episodes[0].episode_id;
	}

	async function loadEpisode(id = selectedEpisodeId) {
		if (!selectedProjectId || !id) return;
		selectedEpisodeId = id;
		if (!graphPayload && hasGraph) await loadGraph();
		const data = await run(() => episodeService.fetchEpisode(selectedProjectId, id), undefined, 'episode:detail');
		if (data) selectedEpisode = data;
	}

	function updateHotCameraFromDrag(pose: { x: number; z: number; yaw_deg: number; final?: boolean }) {
		const active = activeHotCameraPose;
		const shouldCreate = !active || Boolean(active.rendered || active.batch_id);
		const previewId = shouldCreate ? `probe_${Date.now()}` : active.preview_id;
		const nextPose: HotCameraPose = {
			...(shouldCreate ? {} : active),
			preview_id: previewId,
			x: Number(pose.x.toFixed(3)),
			z: Number(pose.z.toFixed(3)),
			yaw_deg: normalizeYawDeg(pose.yaw_deg),
			height_m: rigMountHeightM,
			modality: activeRenderModality,
			sensor_id: activeRigSensorId,
			rendered: false,
		};
		hotCameraPoses = shouldCreate
			? [...hotCameraPoses, nextPose]
			: hotCameraPoses.map((item) => item.preview_id === previewId ? nextPose : item);
		activeHotCameraId = previewId;
		probeError = '';
	}

	async function renderHotCameraPreview() {
		const hotCameraPose = activeHotCameraPose;
		if (!hotCameraPose) { probeError = 'Click-drag on the 3D view to place a hot camera first.'; return; }
		if (!selectedProjectId || !sceneId) { probeError = 'Select a project + scene first.'; return; }
		if (!renderSceneSynced) { probeError = 'Render readiness is blocked. Sync Render Scene first.'; return; }
		let scene_state: unknown;
		let camera_spec: unknown;
		try {
			scene_state = optionalJson(sceneStateText);
			camera_spec = optionalJson(cameraSpecText);
		} catch (err) {
			probeError = `Invalid render config: ${errorMessage(err)}`;
			return;
		}
		const activeCameraSpec = cameraSpecFromRigSensor(activeRigSensorOption?.sensor, camera_spec);
		const vpId = hotCameraPose.preview_id;
		const headingId = 'h0';
		// Polarization sensors render the full set of Stokes representations so the
		// preview can show them side by side instead of a single grayscale image.
		const isPolarPreview = isPolarRenderModality(activeRenderModality);
		const previewModalities = isPolarPreview
			? POLAR_PREVIEW_MODALITIES.map((m) => m.id)
			: [activeRenderModality];
		const body: Record<string, unknown> = {
			modalities: previewModalities,
			backend,
			camera_height_m: rigMountHeightM,
			render_settings: renderSettingsFromRigSensor(activeRigSensorOption?.sensor),
			custom_positions: [{
				node_id: vpId,
				heading_id: headingId,
				preview_id: vpId,
				render_mode: 'preview_probe',
				x: hotCameraPose.x,
				y: hotCameraPose.z,
				yaw_deg: hotCameraPose.yaw_deg,
				height_m: rigMountHeightM,
			}],
		};
		if (scene_state) body.scene_state = scene_state;
		if (activeCameraSpec) body.camera_spec = activeCameraSpec;
		probeRendering = true;
		try {
			const data = await renderService.sweepViewpointGraph(selectedProjectId, sceneId, body);
			if (data?.batch_id) {
				graphBatchId = data.batch_id;
				graphBatchIds = [...new Set([...graphBatchIds, data.batch_id])];
				graphBatch = mergeBatch(graphBatch, data);
				const renderedPose: HotCameraPose = {
					...hotCameraPose,
					batch_id: data.batch_id,
					vp_id: vpId,
					heading_id: headingId,
					modality: activeRenderModality,
					sensor_id: activeRigSensorId,
					rendered: true,
				};
				hotCameraPoses = hotCameraPoses.map((item) => item.preview_id === vpId ? renderedPose : item);
				activeHotCameraId = vpId;
				probeResult = { batch_id: data.batch_id, vp_id: vpId, heading_id: headingId, modality: activeRenderModality, modalities: previewModalities, is_polar: isPolarPreview, sensor_id: activeRigSensorId, submittedAt: Date.now() };
				pushActivity('ok', 'preview:probe', `Hot camera submitted → batch ${data.batch_id}`);
				startBatchPolling();
				const job = data.jobs?.find((item: any) => item.preview_id === vpId) ?? data.jobs?.[0];
				if (job) void selectBatchJob(job);
			}
		} catch (err) {
			probeError = errorMessage(err);
			pushActivity('error', 'preview:probe', probeError);
		} finally {
			probeRendering = false;
		}
	}

	async function handleAddNodeAtFloor(x: number, z: number) {
		if (!selectedProjectId || !sceneId) return;
		try {
			const data = await graphService.addGraphNode(selectedProjectId, sceneId, x, z, Number(headingCount));
			if (data?.node_id) {
				pushActivity('ok', 'graph:add-node', `Added ${data.node_id} at (${x.toFixed(2)}, ${z.toFixed(2)})`);
				await loadGraph();
			}
		} catch (err) {
			pushActivity('error', 'graph:add-node', errorMessage(err));
		}
	}
	async function refreshWalkabilityOverlay() {
		if (!selectedProjectId || !sceneId) return;
		try {
			walkabilityOverlayMeta = await walkabilityService.fetchWalkabilityOverlay(selectedProjectId, sceneId);
			walkabilityOverlayVersion = walkabilityOverlayVersion + 1;
		} catch (err) {
			walkabilityOverlayMeta = null;
		}
	}
	$effect(() => {
		if (pageMode === 'paths' && selectedProjectId && sceneId) refreshWalkabilityOverlay();
	});
	async function handlePaintStroke(points: Array<[number, number]>) {
		if (paintMode === 'none' || !selectedProjectId || !sceneId) return;
		try {
			const res = await walkabilityService.paintWalkability(selectedProjectId, sceneId, paintMode as 'walkable' | 'blocked' | 'erase', paintRadiusM, points);
			if (res?.ok) {
				walkabilityOverlayMeta = { ...(walkabilityOverlayMeta ?? {}), stats: res.stats, has_overlay: true };
				walkabilityOverlayVersion = walkabilityOverlayVersion + 1;
			}
		} catch (err) {
			pushActivity('error', 'paths:paint', errorMessage(err));
		}
	}
	async function clearWalkabilityOverlay() {
		if (!selectedProjectId || !sceneId) return;
		try {
			await walkabilityService.clearWalkabilityOverlay(selectedProjectId, sceneId);
			walkabilityOverlayMeta = { has_overlay: false };
			walkabilityOverlayVersion = walkabilityOverlayVersion + 1;
			pushActivity('ok', 'paths:paint', 'Walkability overlay cleared.');
		} catch (err) {
			pushActivity('error', 'paths:paint', errorMessage(err));
		}
	}
	async function rebuildRegion() {
		if (!pendingRegionBbox || !selectedProjectId || !sceneId) return;
		try {
			const res = await graphService.rebuildRegion(selectedProjectId, sceneId, {
				bbox: pendingRegionBbox,
				maxNodes: Number(maxNodes), minNodeSpacingM: Number(minNodeSpacing),
				robotRadiusM: Number(robotRadius), minClearanceM: Number(minClearance),
				headingCount: Number(headingCount), seed: Number(seed),
			});
			pushActivity('ok', 'graph:regen-region', `Region rebuilt: +${res.added_nodes ?? 0} / -${res.removed_nodes ?? 0} nodes, -${res.removed_edges ?? 0} edges`);
			await loadGraph();
			pendingRegionBbox = null;
		} catch (err) {
			pushActivity('error', 'graph:regen-region', errorMessage(err));
		}
	}
	function handleEdgeFirstNode(nodeId: string) {
		pendingEdgeSource = nodeId;
		pushActivity('info', 'graph:add-edge', `First node: ${nodeId}. Click target node…`);
	}
	async function handleEdgeSecondNode(source: string, target: string) {
		try {
			const res = await graphService.addEdge(selectedProjectId, sceneId, source, target);
			if (res?.edge_id) {
				pushActivity('ok', 'graph:add-edge', `${source} → ${target} (${res.edge_id})`);
				await loadGraph();
			}
		} catch (err) {
			pushActivity('error', 'graph:add-edge', errorMessage(err));
		} finally {
			pendingEdgeSource = '';
		}
	}

	async function deleteSelectedGraphNode() {
		if (!selectedSensorNode || (selectedSensorNode as any).isCustom) return;
		if (!selectedProjectId || !sceneId) return;
		const nid = selectedSensorNode.node_id;
		try {
			await graphService.deleteGraphNode(selectedProjectId, sceneId, nid);
			pushActivity('ok', 'graph:delete-node', `Deleted ${nid}`);
			selectedSensorNodeId = '';
			await loadGraph();
		} catch (err) {
			pushActivity('error', 'graph:delete-node', errorMessage(err));
		}
	}
	async function handleDeleteGraphEdge(edgeId: string) {
		try {
			await graphService.deleteEdge(selectedProjectId, sceneId, edgeId);
			await loadGraph();
		} catch (err) { pushActivity('error', 'graph:edge-del', errorMessage(err)); }
	}
	let rebuildingEdges = $state(false);
	async function rebuildGraphEdges() {
		if (!selectedProjectId || !sceneId) return;
		rebuildingEdges = true;
		try {
			const res = await graphService.rebuildGraphEdges(selectedProjectId, sceneId);
			pushActivity('ok', 'graph:rebuild-edges', `Edges rebuilt (${res?.edge_count ?? '?'} edges, nodes kept)`);
			await loadGraph();
		} catch (err) {
			pushActivity('error', 'graph:rebuild-edges', errorMessage(err));
		} finally {
			rebuildingEdges = false;
		}
	}
	// ── Multi-select node removal handlers ──
	function toggleRemoveNode(nodeId: string) {
		const next = new Set(removeSelection);
		if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
		removeSelection = next;
	}
	function addRemoveNodes(nodeIds: string[]) {
		const next = new Set(removeSelection);
		for (const id of nodeIds) next.add(id);
		removeSelection = next;
	}
	function clearRemoveSelection() { removeSelection = new Set(); }
	async function findOverlappingNodes() {
		if (!selectedProjectId || !sceneId) return;
		findingOverlapping = true;
		try {
			const ids = await graphService.findOverlappingNodes(selectedProjectId, sceneId, { marginM: Number(removeMarginM) || 0, robotHeightM: Number(removePassHeightM) || 1.2 });
			removeSelection = new Set(ids);
			pushActivity('ok', 'graph:overlap', `${ids.length} overlapping node(s) selected`);
		} catch (err) {
			pushActivity('error', 'graph:overlap', errorMessage(err));
		} finally {
			findingOverlapping = false;
		}
	}
	async function removeSelectedGraphNodes() {
		if (!selectedProjectId || !sceneId || removeSelection.size === 0) return;
		const ids = Array.from(removeSelection);
		removingNodes = true;
		try {
			const res = await graphService.deleteGraphNodes(selectedProjectId, sceneId, ids);
			pushActivity('ok', 'graph:remove-nodes', `Removed ${res?.removed_count ?? ids.length} node(s)`);
			removeSelection = new Set();
			await loadGraph();
		} catch (err) {
			pushActivity('error', 'graph:remove-nodes', errorMessage(err));
		} finally {
			removingNodes = false;
		}
	}
	async function renderSensorViewpoint() {
		if (!selectedSensorNode || !selectedProjectId || !sceneId) return;
		if (!requireReady(renderSceneSynced, 'Render readiness is blocked. Sync Render Scene and resolve readiness errors.')) return;
		renderingViewpoint = true;
		sensorRenderResult = null;
		const isCustom = (selectedSensorNode as any).isCustom;
		const customNode = selectedCustomSensorNode;
		let scene_state: unknown;
		let camera_spec: unknown;
		try {
			scene_state = optionalJson(sceneStateText);
			camera_spec = optionalJson(cameraSpecText);
		} catch (err) {
			pushActivity('error', 'sensor:render', `Invalid render config JSON: ${errorMessage(err)}`);
			renderingViewpoint = false;
			return;
		}
		const activeCameraSpec = cameraSpecFromRigSensor(activeRigSensorOption?.sensor, camera_spec);
		const body: Record<string, unknown> = {
			modalities: [activeRenderModality],
			backend,
			camera_height_m: rigMountHeightM,
			render_settings: renderSettingsFromRigSensor(activeRigSensorOption?.sensor)
		};
		if (scene_state) body.scene_state = scene_state;
		if (activeCameraSpec) body.camera_spec = activeCameraSpec;
		if (isCustom && customNode) {
			body.custom_positions = [{ x: customNode.x, y: customNode.z, yaw_deg: customNode.headingDeg, height_m: customNode.height_m ?? rigMountHeightM }];
		} else {
			body.node_ids = [selectedSensorNode.node_id];
			const h = graphNodeHeights[selectedSensorNode.node_id];
			if (typeof h === 'number') body.node_heights = { [selectedSensorNode.node_id]: h };
		}
		try {
			const data = await renderService.sweepViewpointGraph(selectedProjectId, sceneId, body);
			if (data?.batch_id) {
				graphBatchId = data.batch_id;
				graphBatchIds = [...new Set([...graphBatchIds, data.batch_id])];
				graphBatch = mergeBatch(graphBatch, data);
				sensorRenderResult = { batch_id: data.batch_id, status: 'submitted' };
				pushActivity('ok', 'sensor:render', `Render submitted: batch ${data.batch_id}`);
				startBatchPolling();
			}
		} catch (err) {
			pushActivity('error', 'sensor:render', errorMessage(err));
		} finally {
			renderingViewpoint = false;
		}
	}

	function toggleModality(id: string) {
		selectedModalities = selectedModalities.includes(id)
			? selectedModalities.filter((item) => item !== id)
			: [...selectedModalities, id];
	}

	async function renderEpisodes(modeOverride?: 'graph_sweep' | 'episode_nodes' | 'episodes') {
		// Persist the chosen mode in state so downstream code (WS subscribe,
		// batch grid, refreshBatch) treats this submission consistently.
		if (modeOverride && modeOverride !== renderMode) renderMode = modeOverride;
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (renderMode === 'graph_sweep' && !requireReady(hasGraph, 'Build the viewpoint graph before running Sensor Sweep.')) return;
		if (renderMode === 'episode_nodes') {
			if (!requireReady(hasGraph, 'Build the viewpoint graph before running Episode Path Sweep.')) return;
			if (!requireReady(episodeNodesAvailable, 'Select a graph-based episode with path nodes before running Episode Path Sweep.')) return;
		}
		if (!requireReady(renderSceneSynced, 'Render readiness is blocked. Sync Render Scene and resolve readiness errors.')) return;
		if (renderMode === 'episodes' && !requireReady(hasEpisodes, 'Plan episodes before rendering episode timesteps.')) return;
		let scene_state: unknown;
		let camera_spec: unknown;
		try {
			scene_state = optionalJson(sceneStateText);
			camera_spec = optionalJson(cameraSpecText);
		} catch (err) {
			error = `Invalid render config JSON: ${errorMessage(err)}`;
			return;
		}
		const activeCameraSpec = cameraSpecFromRigSensor(activeRigSensorOption?.sensor, camera_spec);
		const body: Record<string, unknown> = {
			modalities: [activeRenderModality],
			backend,
			camera_height_m: rigMountHeightM,
			render_settings: renderSettingsFromRigSensor(activeRigSensorOption?.sensor)
		};
		if (scene_state) body.scene_state = scene_state;
		if (activeCameraSpec) body.camera_spec = activeCameraSpec;
		if (Object.keys(graphNodeHeights).length) body.node_heights = { ...graphNodeHeights };
		if (isGraphSweepRenderMode(renderMode)) {
			if (!sceneId) return;
			body.skip_existing_observations = renderMissingOnly;
			if (renderMode === 'episode_nodes') {
				// Filter to the selected episode's graph nodes; backend's
				// build_sweep_render_requests already honours node_ids.
				body.node_ids = [...(selectedEpisode!.path_nodes as string[])];
				body.source_episode_id = selectedEpisodeId;
			}
			const successMsg = renderMode === 'episode_nodes'
				? 'Episode path sweep submitted.'
				: 'Graph sensor sweep submitted.';
			const data = await run(() => renderService.sweepViewpointGraph(selectedProjectId, sceneId, body), successMsg, 'graph:sweep');
			if (data?.batch_id) {
				graphBatchId = data.batch_id;
				graphBatchIds = [...new Set([...graphBatchIds, data.batch_id])];
				graphBatch = mergeBatch(graphBatch, data);
				startBatchPolling();
			}
		} else {
			body.split = renderSplit;
			const data = await run(() => renderService.renderEpisodes(selectedProjectId, body), 'Episode render request submitted.', 'episodes:render');
			if (data?.batch_id) {
				renderBatchId = data.batch_id;
				renderBatch = data;
				startBatchPolling();
			}
		}
		await refreshEpisodes();
	}

	async function refreshBatch() {
		if (!selectedProjectId) return;
		if (isGraphSweepRenderMode(renderMode)) {
			if (!graphBatchIds.length) return;
			const prevCompleted = graphBatch?.progress?.completed ?? 0;
			const batches = await Promise.all(
				graphBatchIds.map(id => renderService.fetchGraphBatch(selectedProjectId, id).catch(() => null))
			);
			let merged: any = null;
			for (const b of batches) {
				if (b) merged = merged ? mergeBatch(merged, b) : b;
			}
			if (merged) graphBatch = merged;
			_refreshBatchLogs();
			if (selectedBatchJobId) void refreshSelectedBatchJobLog().catch(() => {});
			if ((merged?.progress?.completed ?? 0) !== prevCompleted) scanObservations();
		} else {
			if (!renderBatchId) return;
			const data = await run(() => renderService.fetchRenderBatch(selectedProjectId, renderBatchId), undefined, 'batch:episodes');
			if (data) renderBatch = data;
		}
	}

	// WS-driven batch tracking for graph_sweep. Subscribes to /api/ws/job-status
	// instead of polling fetchGraphBatch + fetchBatchLogs every 4s. The WS frame
	// carries the same data (job statuses + log tails) but only on actual
	// changes, eliminating the ~2 HTTP/req × active_batch_count × 4s burst that
	// stalled the daemon.
	let _jobStatusUnsub: (() => void) | null = null;
	let _jobStatusPrevCompleted = 0;

	function _onJobStatusUpdate(msg: JobStatusMessage) {
		// Batch log feed first — runs even before the batch metadata fetch has
		// completed, so log lines start flowing immediately.
		const batchJobIds = new Set<string>(
			Array.isArray(graphBatch?.jobs)
				? graphBatch.jobs.map((j: any) => String(j?.job_id ?? ''))
				: []
		);
		if (batchJobIds.size > 0) {
			batchLogEntries = logTailsToBatchEntries(batchJobIds, msg.log_tails);
		}
		if (selectedBatchJobId) {
			const tail = msg.log_tails?.[selectedBatchJobId];
			if (Array.isArray(tail) && tail.length) selectedBatchJobLog = tail.map((line) => String(line));
		}
		// Diagnostic snapshot for "WS shows succeeded but UI doesn't follow" —
		// the WS payload carries the last 250 jobs across all scenes, so a
		// succeeded entry in the frame may legitimately belong to a different
		// batch. This counter lets us tell the two cases apart in DevTools:
		// `window.__jobStatusDebug` shows the last frame summary.
		if (typeof window !== 'undefined') {
			const wsIds = (msg.jobs ?? []).map((j: any) => String(j?.job_id ?? ''));
			const matched = wsIds.filter((id) => batchJobIds.has(id));
			const succeededInBatch = (msg.jobs ?? []).filter(
				(j: any) => batchJobIds.has(String(j?.job_id ?? '')) && String(j?.status ?? '') === 'succeeded'
			).length;
			(window as any).__jobStatusDebug = {
				at: new Date().toISOString(),
				ws_jobs_total: wsIds.length,
				batch_jobs_total: batchJobIds.size,
				matched_in_batch: matched.length,
				succeeded_in_batch_frame: succeededInBatch,
				batch_completed: graphBatch?.progress?.completed ?? 0,
				batch_total: graphBatch?.progress?.total ?? 0,
				sample_batch_id: [...batchJobIds][0] ?? null,
				sample_ws_ids_first_3: wsIds.slice(0, 3),
			};
		}
		if (!graphBatch || batchJobIds.size === 0) return;
		// Status update. Always reassign graphBatch even when applyJobStatusUpdates
		// returns the same reference: $derived chains (activeBatch → selectedBatchJob)
		// must re-fire so the per-job stage badge follows the WS-pushed
		// progress_stage. The status object is reshaped from the flat WS record
		// into the nested form the batch UI expects.
		const prevCompletedBeforeUpdate = graphBatch?.progress?.completed ?? 0;
		graphBatch = applyJobStatusUpdates(graphBatch, msg.jobs);
		const completed = graphBatch?.progress?.completed ?? 0;
		// observationScan reflects the on-disk count of rendered modalities per
		// viewpoint (what drives "X/Y rendered" badges). It only refreshes via
		// scanObservations() — the listener used to gate that on a strict
		// inequality with _jobStatusPrevCompleted, which missed the first WS
		// frame after restoring a batch (the gate was pre-seeded to the same
		// value by startBatchPolling's initial fetch). Trigger whenever the
		// in-frame delta is non-zero, or when we see any succeeded/failed
		// progress beyond the previous frame.
		// Be aggressive about triggering scanObservations — the gate used to
		// require a strict increment in `completed`, but the listener may see
		// the same value across multiple frames (and we still want a fresh
		// scan because the per-VP on-disk count may have changed even without
		// changing the total). Always fire when WS reports any succeeded jobs
		// for our batch; the endpoint is cheap (single disk walk) and the
		// HTTP traffic stays orders of magnitude lower than the old 4s poll.
		const succeededInBatch = (msg.jobs ?? []).filter(
			(j: any) => batchJobIds.has(String(j?.job_id ?? '')) && String(j?.status ?? '') === 'succeeded'
		).length;
		if (succeededInBatch > 0 || completed !== _jobStatusPrevCompleted) {
			_jobStatusPrevCompleted = completed;
			void scanObservations().catch(() => {});
			// Belt-and-suspenders: also refetch batch via HTTP. The in-listener
			// `graphBatch = applyJobStatusUpdates(...)` correctly reaches the new
			// `progress.completed` value (verified via window.__jobStatusDebug),
			// but multiple downstream components weren't visibly following until
			// the user hit Refresh — which is exactly what refreshBatch does.
			// Trigger only when the WS frame carries fresh succeeded entries,
			// so this is bounded by actual completions, not a fixed cadence.
			void refreshBatch().catch(() => {});
		}
		if (typeof window !== 'undefined') {
			(window as any).__jobStatusDebug = {
				...((window as any).__jobStatusDebug ?? {}),
				last_listener_completed: completed,
				prev_completed_seen: prevCompletedBeforeUpdate,
				scan_fired: succeededInBatch > 0 || completed !== _jobStatusPrevCompleted,
				succeeded_count_in_frame: succeededInBatch,
			};
		}
		const status = graphBatch?.status;
		if (status === 'building') return;
		const total = graphBatch?.progress?.total ?? 0;
		const done = completed + (graphBatch?.progress?.failed ?? 0);
		if (status === 'error' || (total > 0 && done >= total)) {
			stopBatchPolling();
			const key = _batchStorageKey();
			if (key) { try { window.sessionStorage.removeItem(key); } catch { /* silent */ } }
		}
	}

	function stopBatchPolling() {
		if (batchPollTimer !== null) {
			clearInterval(batchPollTimer);
			batchPollTimer = null;
		}
		if (_jobStatusUnsub !== null) {
			_jobStatusUnsub();
			_jobStatusUnsub = null;
		}
	}

	async function startBatchPolling() {
		stopBatchPolling();
		if (isGraphSweepRenderMode(renderMode)) {
			// Ensure batch metadata (graph_id / node_id / heading_id / preview_id)
			// AND the full job_id list are present *before* subscribing — the WS
			// listener short-circuits when graphBatch.jobs is empty, so a frame
			// arriving in that gap would be dropped and the user would see no
			// updates until the next status change. The submit response is often
			// just a stub (no jobs yet) because the daemon enqueues asynchronously;
			// awaiting fetch closes that race.
			if (!graphBatch || !Array.isArray(graphBatch.jobs) || graphBatch.jobs.length === 0) {
				await refreshBatch().catch(() => {});
				// The daemon's submission thread populates batch.json shortly after
				// the synchronous handler returns. Retry once with a small delay
				// when the first fetch caught the stub.
				if (!graphBatch?.jobs?.length) {
					await new Promise((r) => setTimeout(r, 750));
					await refreshBatch().catch(() => {});
				}
			}
			_jobStatusPrevCompleted = graphBatch?.progress?.completed ?? 0;
			_jobStatusUnsub = subscribeJobStatus(_onJobStatusUpdate);
			return;
		}
		// Episode mode: keep the 4s poll, but skip when tab is hidden so a
		// backgrounded page doesn't keep hitting the daemon.
		batchPollTimer = setInterval(async () => {
			if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
			await refreshBatch();
			const batch = renderBatch;
			const status = batch?.status;
			if (status === 'building') return;
			const total = batch?.progress?.total ?? 0;
			const done = (batch?.progress?.completed ?? 0) + (batch?.progress?.failed ?? 0);
			if (status === 'error' || (total > 0 && done >= total)) {
				stopBatchPolling();
				const key = _batchStorageKey();
				if (key) { try { window.sessionStorage.removeItem(key); } catch { /* silent */ } }
			}
		}, 4000);
	}

	async function _refreshBatchLogs() {
		// Retained for the one-shot manual refresh on the existing refreshBatch()
		// path; the WS-driven flow updates batchLogEntries directly without HTTP.
		if (!selectedProjectId || !isGraphSweepRenderMode(renderMode)) return;
		const ids = [...new Set([graphBatchId, ...graphBatchIds].filter(Boolean))];
		if (!ids.length) return;
		try {
			const batches = await Promise.all(ids.map((id) => renderService.fetchBatchLogs(selectedProjectId, id, 20).catch(() => null)));
			batchLogEntries = batches.flatMap((data: any) => Array.isArray(data?.entries) ? data.entries : []);
		} catch { /* silent */ }
	}

	async function validateDataset(requireObservations = false) {
		if (!selectedProjectId) return;
		const sceneScope = exportCurrentSceneOnly && sceneId ? [sceneId] : null;
		const data = await run(
			() => validationService.validateDataset(selectedProjectId, {
				require_observations: requireObservations,
				scene_ids: sceneScope,
			}),
			'Dataset validation completed.',
			'dataset:validate'
		);
		if (data) validationReport = data;
	}

	async function evaluateDataset() {
		if (!selectedProjectId) return;
		const data = await run(
			() => validationService.evaluateDataset(selectedProjectId),
			'Evaluation completed.',
			'dataset:evaluate'
		);
		if (data) evaluationReport = data;
	}

	// Light-weight heuristic for the count hint — exact judgement (file existence)
	// is done backend-side, so this can drift slightly while a sweep is still
	// flushing observation files to disk. Good enough to show "X of Y" before
	// submit; the real numbers come back in `exportResult.episode_count` /
	// `total_episode_count_on_disk`.
	const exportableEpisodeCount = $derived(
		episodes
			.filter((ep: any) => !exportCurrentSceneOnly || !sceneId || ep?.scene_id === sceneId)
			.filter((ep: any) => {
				// Backend now computes observation_complete from the
				// consolidated observations dir (disk-truth), matching the
				// exporter's is_episode_complete. Falls back to the legacy
				// refs.length / path_nodes.length heuristic if an older
				// daemon hasn't been updated yet.
				if (typeof ep?.observation_complete === 'boolean') return ep.observation_complete;
				const pathNodes = Array.isArray(ep?.path_nodes) ? ep.path_nodes : [];
				const refs = Array.isArray(ep?.observation_refs) ? ep.observation_refs : [];
				if (!pathNodes.length) return refs.length > 0;
				return refs.length >= pathNodes.length;
			}).length
	);
	const scopedEpisodeCount = $derived(
		exportCurrentSceneOnly && sceneId
			? episodes.filter((ep: any) => ep?.scene_id === sceneId).length
			: episodes.length
	);

	async function exportDataset() {
		if (!selectedProjectId || !sceneId) return;
		// Scene-bundle export: always tied to the current scene. The submit
		// returns immediately with a job_id; progress arrives over WS.
		try {
			const accepted = await exportJobsService.submitExportJob(selectedProjectId, {
				scene_id: sceneId,
				only_completed: exportOnlyCompleted,
				include_episode_thumbnails: exportIncludeThumbnails,
				panorama_observations: exportPanoramaObservations,
				png_only: exportPngOnly,
				include_birdseye: exportIncludeBirdseye,
			});
			const jobId = (accepted as any)?.job_id;
			if (!jobId) return;
			activeExportJob = { job_id: jobId, scene_id: sceneId, status: 'queued' };
			if (_exportJobUnsub) { _exportJobUnsub(); _exportJobUnsub = null; }
			_exportJobUnsub = subscribeExportJob(jobId, (msg) => { activeExportJob = msg; });
		} catch (err) {
			error = `Export submit failed: ${errorMessage(err)}`;
		}
	}

	async function cancelActiveExportJob() {
		if (!selectedProjectId || !activeExportJob?.job_id) return;
		try { await exportJobsService.cancelExportJob(selectedProjectId, activeExportJob.job_id); }
		catch { /* silent */ }
	}

	function resetExportJob() {
		if (_exportJobUnsub) { _exportJobUnsub(); _exportJobUnsub = null; }
		activeExportJob = null;
	}

	$effect(() => {
		sceneRailSnippet.set(datasetRailContent);
		sceneBottomSnippet.set(datasetBottomContent);
		return () => {
			sceneRailSnippet.set(null);
			sceneBottomSnippet.set(null);
		};
	});

	// 3D canvas is always visible — prevent page scroll to avoid orbit/zoom gesture conflicts
	$effect(() => {
		const el = document.querySelector('.page-content') as HTMLElement | null;
		if (!el) return;
		el.style.overflowY = 'hidden';
		el.style.paddingTop = '0';
		el.style.paddingBottom = '0';
		return () => {
			el.style.overflowY = '';
			el.style.paddingTop = '';
			el.style.paddingBottom = '';
		};
	});

	onMount(() => {
		// selectedProjectId and sceneId are already initialized from URL at declaration time
		refreshProjects(selectedProjectId);
		loadGlobalCameraRig();
		loadMaterialLibrary();
		let ticks = 0;
			const thumbTimer = window.setInterval(() => {
				ticks += 1;
				assetVM.bumpAssetThumbTick();
				if (ticks >= 12) window.clearInterval(thumbTimer);
			}, 2500);
		return () => {
			window.clearInterval(thumbTimer);
			// Release the job-status WS subscription when the page unmounts so a
			// route change doesn't leave the connection (and its keepalive churn)
			// dangling.
			stopBatchPolling();
		};
	});

	$effect(() => {
		const currentId = selectedAuthoringItem?.id ?? '';
		if (currentId !== lastInspectorItemId) {
			lastInspectorItemId = currentId;
			inspectorTab = 'object';
			materialPreviewValue = selectedAuthoringItem?.material ?? '';
			materialPickerCategory = recommendedMaterialCategory(selectedAuthoringItem);
			materialPickerCollection = 'all';
			materialPickerSearch = '';
		}
	});

	$effect(() => {
		const p = selectedProjectId;
		const s = sceneId;
		const url = new URL(window.location.href);
		if (p) url.searchParams.set('project', p); else url.searchParams.delete('project');
		if (s) url.searchParams.set('scene', s); else url.searchParams.delete('scene');
		history.replaceState(history.state, '', url.toString());
	});


	async function setPageMode(mode: PageMode) {
		if (mode !== 'preview') stopRobotAnimation();
		pageMode = mode;
		placementTool = 'select';
		draftPoint = null;
		linePreview = null;
		dragStart = null;
		dragPreview = null;
		draftGhost = null;
		if (!selectedProjectId) return;
		if (mode === 'preview') {
			if (!hasMap && hasScene) await buildMap();
			if (!hasGraph && hasMap) await buildGraph();
			if (graphPayload?.nodes?.length) {
				startRobotAnimation();
			} else if (hasGraph) {
				await loadGraph();
				startRobotAnimation();
			}
		}
		if ((mode === 'paths' || mode === 'sensors' || mode === 'preview') && !graphPayload && hasGraph) {
			await loadGraph();
		}
		if (mode === 'sensors' || mode === 'preview') {
			scanObservations();
		}
		if (mode === 'export') {
			// ExportPanel's "Exporting X of Y" hint and the exportable filter
			// both depend on observationScan to detect rendered episode paths.
			// Without this trigger the count stays at 0 on a fresh page load
			// when the user lands directly on the Export tab.
			if (episodes.length === 0) await refreshEpisodes();
			scanObservations();
		}
		if (mode === 'paths' && episodes.length === 0) {
			await refreshEpisodes();
		}
		if (mode === 'export' && episodes.length === 0) {
			await refreshEpisodes();
		}
	}
</script>

<svelte:head>
	<title>Dataset Authoring</title>
</svelte:head>

<svelte:window onkeydown={handleEditorKeydown} />

{#snippet environmentPanel()}
	{@const env = authoringMap?.environment ?? {}}
	{@const mode = env.mode ?? 'constant'}
	{@const envmapRef = env.envmap_ref ?? ''}
		{@const selectedEnvmap = assetVM.envmapFiles.find((f: any) => f.envmap_ref === envmapRef)}
	{@const shellOn = authoringMap?.settings?.room_shell_enabled ?? true}
	{@const floorOn = authoringMap?.settings?.auto_floor_enabled ?? true}
	{@const ceilingOn = authoringMap?.settings?.auto_ceiling_enabled ?? (authoringMap?.settings?.room_shell_enabled ?? true)}
	<div class="env-section">
		<div class="env-section-title">Lighting source</div>
		<div class="env-radio-row">
			<label class="env-radio"><input type="radio" name="env-mode" value="constant" checked={mode === 'constant'} onchange={() => updateEnvironmentField('mode', 'constant')} /> Constant</label>
			<label class="env-radio"><input type="radio" name="env-mode" value="envmap" checked={mode === 'envmap'} onchange={() => updateEnvironmentField('mode', 'envmap')} /> Envmap</label>
		</div>

		{#if mode === 'constant'}
			<div class="env-fields-grid">
				<label><span>RGB</span><input value={(env.radiance ?? [0.8, 0.8, 0.85]).join(', ')} oninput={(event) => updateEnvironmentField('radiance', (event.currentTarget as HTMLInputElement).value)} /></label>
				<label><span>Intensity</span><input type="number" min="0" step="0.1" value={env.intensity ?? 1} oninput={(event) => updateEnvironmentField('intensity', (event.currentTarget as HTMLInputElement).value)} /></label>
			</div>
		{:else}
			<div class="env-envmap-row">
				<select class="env-envmap-select" value={envmapRef} onchange={(event) => updateEnvironmentField('envmap_ref', (event.currentTarget as HTMLSelectElement).value || null)}>
					<option value="">— Select uploaded envmap —</option>
					{#each assetVM.envmapFiles as item}
						<option value={item.envmap_ref}>{item.filename}{#if item.size_bytes} · {envmapSizeLabel(item.size_bytes)}{/if}</option>
					{/each}
				</select>
				<label class="env-upload-button">
						<input type="file" accept=".exr,.hdr,.png,.jpg,.jpeg,image/png,image/jpeg" disabled={assetVM.envmapUploading || !selectedProjectId || !hasScene} onchange={(event) => uploadEnvmapFromInput(event.currentTarget as HTMLInputElement)} />
						<span>{assetVM.envmapUploading ? 'Uploading…' : 'Upload new'}</span>
				</label>
			</div>
			{#if selectedEnvmap}
				<div class="env-envmap-preview">
					{#if selectedEnvmap.previewable && selectedProjectId && sceneId}
						<img src={opticalNavEnvmapPreviewUrl(selectedProjectId, sceneId, selectedEnvmap.filename)} alt={selectedEnvmap.filename} />
					{:else}
						<div class="env-envmap-placeholder">EXR/HDR preview not available in browser</div>
					{/if}
					<div class="env-envmap-meta">
						<div class="env-envmap-filename" title={selectedEnvmap.envmap_ref}>{selectedEnvmap.filename}</div>
						<div class="env-envmap-sub">{envmapSizeLabel(selectedEnvmap.size_bytes)}</div>
					</div>
				</div>
			{:else if envmapRef}
				<div class="hint-row">⚠ envmap_ref is set but not in the uploaded list. Re-upload or fix the path.</div>
			{/if}
			<div class="env-fields-grid">
				<label><span>Intensity</span><input type="number" min="0" step="0.1" value={env.intensity ?? 1} oninput={(event) => updateEnvironmentField('intensity', (event.currentTarget as HTMLInputElement).value)} /></label>
				<label><span>Rotation°</span><input type="number" step="1" value={env.rotation_deg ?? 0} oninput={(event) => updateEnvironmentField('rotation_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
			</div>
		{/if}
	</div>

	<div class="env-section">
		<div class="env-section-title">Scene enclosure</div>
		<label class="inline-check enclosure-toggle">
			<input type="checkbox" checked={floorOn} onchange={(event) => updateSettingsField('auto_floor_enabled', (event.currentTarget as HTMLInputElement).checked)} />
			<span><strong>Auto floor</strong><span class="env-toggle-sub">Keep a base floor visible for editing and rendering.</span></span>
		</label>
		<label class="inline-check enclosure-toggle">
			<input type="checkbox" checked={ceilingOn} onchange={(event) => updateSettingsField('auto_ceiling_enabled', (event.currentTarget as HTMLInputElement).checked)} />
			<span><strong>Auto ceiling</strong><span class="env-toggle-sub">Cap the room with a ceiling (enclosure + light bounce), independent of the walls.</span></span>
		</label>
		<label class="inline-check enclosure-toggle">
			<input type="checkbox" checked={shellOn} onchange={(event) => updateSettingsField('room_shell_enabled', (event.currentTarget as HTMLInputElement).checked)} />
			<span><strong>Perimeter walls</strong><span class="env-toggle-sub">Add simple boundary walls around the map. Turn off to reveal the environment through glass walls / windows.</span></span>
		</label>
		{#if mode === 'envmap' && shellOn}
			<div class="hint-row">💡 Turn off Perimeter walls so the envmap shows through glass walls / windows. Keep Auto ceiling for an enclosed room.</div>
		{:else if !shellOn && !ceilingOn && !floorOn && mode === 'constant'}
			<div class="hint-row">⚠ Floor + walls + ceiling all off under constant lighting → scene will render almost empty. Switch to envmap.</div>
		{:else if !shellOn && !ceilingOn && mode === 'constant'}
			<div class="hint-row">⚠ Walls + ceiling off + constant lighting → flat. Consider switching to envmap.</div>
		{/if}
	</div>
{/snippet}

{#snippet renderGeometryPanel()}
	{@const summary = materializationAudit?.summary}
	{@const fallbackRecords = (materializationAudit?.objects ?? []).filter((o: any) => o.status === 'fallback_cube')}
	{@const breakdown = materializationAudit?.fallback_breakdown ?? {}}
	{@const materialBreakdown = materializationAudit?.material_extraction_breakdown ?? {}}
	{@const materialProblemRecords = (materializationAudit?.objects ?? []).filter((o: any) => {
		const s = o?.extras?.extracted_material_status;
		return s && s !== 'ok' && s !== 'n/a';
	})}
	{#if summary}
		<div class="render-geometry-panel">
			<div class="render-geometry-header">
				<span class="render-geometry-title">Render geometry</span>
				<span class="render-geometry-chip render-geometry-chip-ok">{summary.obj_shapes ?? 0} OBJ meshes</span>
				{#if (summary.fallback_cubes ?? 0) > 0}
					<span class="render-geometry-chip render-geometry-chip-warn">{summary.fallback_cubes} fallback cubes</span>
				{/if}
				{#if (summary.emitter_cubes ?? 0) > 0}
					<span class="render-geometry-chip render-geometry-chip-dim">{summary.emitter_cubes} emitter cubes</span>
				{/if}
				{#if (summary.wall_cubes ?? 0) > 0}
					<span class="render-geometry-chip render-geometry-chip-dim">{summary.wall_cubes} wall cubes</span>
				{/if}
			</div>
			{#if Object.keys(breakdown).length}
				<div class="render-geometry-breakdown">
					{#each Object.entries(breakdown) as [reason, count]}
						<span class="render-geometry-reason">{reason}: {count}</span>
					{/each}
				</div>
			{/if}
			{#if fallbackRecords.length}
				<details class="render-geometry-fallbacks">
					<summary>Show fallback objects ({fallbackRecords.length})</summary>
					<ul>
						{#each fallbackRecords.slice(0, 50) as fb}
							<li>
								<button class="link-button" onclick={() => { selectedAuthoringId = fb.object_id ?? fb.shape_id; }}>
									<strong>{fb.object_id ?? fb.shape_id}</strong>
								</button>
								<span class="render-geometry-reason">{fb.reason ?? 'unknown'}</span>
								{#if fb.source_ref}
									<small>{fb.source_ref}</small>
								{/if}
							</li>
						{/each}
					</ul>
				</details>
			{/if}
			{#if Object.keys(materialBreakdown).length}
				<div class="render-geometry-header" style="margin-top:8px;">
					<span class="render-geometry-title">Material extraction</span>
					{#if (materialBreakdown.ok ?? 0) > 0}
						<span class="render-geometry-chip render-geometry-chip-ok">{materialBreakdown.ok} ok</span>
					{/if}
					{#each Object.entries(materialBreakdown).filter(([k]) => k !== 'ok') as [status, count]}
						<span class="render-geometry-chip render-geometry-chip-warn">{count} {status}</span>
					{/each}
				</div>
				{#if materialProblemRecords.length}
					<details class="render-geometry-fallbacks">
						<summary>Show material problems ({materialProblemRecords.length})</summary>
						<ul>
							{#each materialProblemRecords.slice(0, 50) as mp}
								<li>
									<button class="link-button" onclick={() => { selectedAuthoringId = mp.object_id ?? mp.shape_id; }}>
										<strong>{mp.object_id ?? mp.shape_id}</strong>
									</button>
									<span class="render-geometry-reason">{mp?.extras?.extracted_material_status ?? 'unknown'}</span>
									{#if mp?.extras?.extracted_material_summary?.base_color_factor}
										<small>RGB {mp.extras.extracted_material_summary.base_color_factor.map((c: number) => Number(c).toFixed(2)).join(', ')}</small>
									{/if}
								</li>
							{/each}
						</ul>
					</details>
				{/if}
			{/if}
			<label class="xml-native-preview-toggle">
				<input
					type="checkbox"
					checked={xmlNativePreviewEnabled}
					onchange={(e) => { xmlNativePreviewEnabled = (e.currentTarget as HTMLInputElement).checked; }}
				/>
				<span>
					<strong>XML-native preview</strong>
					<small>Render editor objects from the same mesh_cache OBJ files Mitsuba uses.</small>
				</span>
			</label>
			{#if xmlNativePreviewEnabled && xmlIndexStale}
				<div class="hint-row">⚠ XML index may be stale. Re-sync render scene so the editor reflects the current mesh_cache.</div>
			{/if}
		</div>
	{/if}
{/snippet}

<div
	class="dataset-page"
	class:bottom-open={!$bottomPanelCollapsed}
	class:bottom-closed={$bottomPanelCollapsed}
	class:bottom-maximized={$bottomPanelMode === 'maximized'}
	class:scene-active={true}
>
	<header class="page-header">
		<div>
			<div class="panel-label">OpticalNav-v0.2</div>
			<h1>Dataset Authoring</h1>
			<p>Sensor-rich viewpoint graph with cached multi-modal observation sweeps.</p>
		</div>
		<div class={`primary-next status-${currentReadiness.status}`}>
			<div>
				<div class="panel-label">Current step</div>
				<strong>{currentReadiness.step}</strong>
				<p>{currentReadiness.message}</p>
			</div>
			<button class="button button-primary" disabled={loading} onclick={runPrimaryAction}>{currentReadiness.action}</button>
		</div>
	</header>

	{#if error}<div class="notice error">{error}</div>{/if}
	{#if info}<div class="notice ok">{info}</div>{/if}

	<section class="panel project-strip">
		<label>
			<span>Project selector</span>
			<select bind:value={selectedProjectId} onchange={refreshProject}>
				<option value="">No project</option>
				{#each projects as item}
					<option value={item.project_id}>{item.project_id}</option>
				{/each}
			</select>
		</label>
		<label>
			<span>Project name</span>
			<input bind:value={projectName} />
		</label>
		<label>
			<span>Dataset type</span>
			<input value="Synthetic fine-tuning dataset" readonly />
		</label>
		<label>
			<span>Robot profile</span>
			<input value="mobile_base_front_camera" readonly />
		</label>
		<button class="button button-primary" disabled={loading} onclick={createProject}>Create Project</button>
	</section>

	{#if selectedProjectId}
		<section class="panel readiness-strip">
			<button class:ready={hasScene} onclick={() => (pageMode = 'map')}>Scene {hasScene ? 'ready' : 'missing'}</button>
			<button class:ready={hasAuthoringMap} onclick={() => (pageMode = 'map')}>Overlay {hasAuthoringMap ? 'ready' : 'missing'}</button>
			<button class:ready={hasMap} onclick={() => (pageMode = 'paths')}>Map {hasMap ? 'ready' : 'missing'}</button>
			<button class:ready={hasGraph} onclick={() => (pageMode = 'paths')}>Viewpoint graph {hasGraph ? 'ready' : 'missing'}</button>
			<button class:ready={hasEpisodes} onclick={() => (pageMode = 'export')}>Episodes {hasEpisodes ? episodes.length : 'missing'}</button>
			<button class:ready={renderSceneSynced} onclick={() => (pageMode = 'map')}>Render scene {renderSceneSynced ? 'synced' : 'pending'}</button>
			<button class:ready={renderConfigReady} onclick={() => (pageMode = 'sensors')}>Render config {renderConfigReady ? 'ready' : 'missing'}</button>
		</section>
	{/if}

		<section class="map-editor-fullbleed">
			<!-- 3D canvas fills the entire section -->
			<MapEditor3D
				bind:this={mapEditorRef}
				projectId={selectedProjectId}
				{sceneId}
					geometryKey={`${currentUsdRef}:${assetVM.editorGeometryRefreshToken}`}
				{authoringObjects}
				{authoringRegions}
				{graphNodes}
				{graphEdges}
				selectedId={selectedAuthoringId}
				{visibleLayers}
				{draftGhost}
				{robotPos}
				editorMode={mapEditorMode}
				{placementTool}
				{draftPoint}
				{objectTransformMode}
				{surfaceSnapEnabled}
				gridSnapEnabled={gridSnapEnabled}
				gridSizeM={transformGridSizeM}
				angleSnapDeg={transformAngleSnapDeg}
				onGroundPointerDown={handleGroundPointerDown}
				onGroundPointerMove={handleGroundPointerMove}
				onGroundPointerUp={handleGroundPointerUp}
				onObjectTransform={handleObjectTransform}
					preloadSourcePath={placementTool === 'usd_asset' ? (assetVM.selectedUsdAsset?.source_format === 'glb' ? (assetVM.selectedUsdAsset?.source_ref ?? assetVM.selectedUsdAsset?.glb_ref ?? '') : (assetVM.selectedUsdAsset?.source_path ?? '')) : ''}
					preloadUsdRef={placementTool === 'usd_asset' && assetVM.selectedUsdAsset?.source_format !== 'glb' ? (assetVM.selectedUsdAsset?.usd_ref ?? '') : ''}
				customSensorNodes={customSensorNodes.map(n => ({ id: n.id, x: n.x, z: n.z, headingDeg: n.headingDeg, selected: n.id === selectedSensorNodeId }))}
			cameraHeight={cameraHeightM}
				onObjectSelect={(id) => {
					const isNode = graphNodes.some((n: any) => n.node_id === id);
					const isCustom = customSensorNodes.some(n => n.id === id);
					if ((isNode || isCustom) && pageMode === 'sensors') {
						selectedSensorNodeId = id;
						sensorRenderResult = null;
						placingSensor = false;
					} else {
						selectAuthoringItem(id);
					}
				}}
				onObjectContextMenu={handleContextMenu}
				onHandleDrag={dragLineHandle}
				onRegionResize={dragRegionHandle}
				highlightedPath={selectedEpisodePath}
				allEpisodePaths={pageMode === 'export' ? allEpisodePaths : []}
				mapBounds={{ w: mapWidth, h: mapHeight }}
				onStatus={(message) => (editor3DStatus = message)}
				observationScan={pageMode === 'sensors' ? observationScan : null}
				frustumMode={pageMode === 'sensors' ? frustumMode : 'none'}
				frustumModality={activeRenderModality}
				frustumSensorId={activeRigSensorId}
				frustumIntrinsics={activeCameraFrustum}
				hotCameraPlacement={pageMode === 'preview'}
				previewCameraOverlay={hotCameraOverlays}
				onHotCameraDrag={updateHotCameraFromDrag}
				wallHeight={Number(authoringMap?.settings?.default_wall_height_m ?? 2.4)}
				footprintInflationM={showFootprint ? Number(robotRadius) + Number(minClearance) : 0}
				addNodeMode={pageMode === 'paths' && addNodeMode}
				onAddNodeClick={(x, z) => handleAddNodeAtFloor(x, z)}
				eyeHeightM={selectedSensorHeightM}
				selectedObjectGuide={selectedObjectGuide}
				paintMode={pageMode === 'paths' ? paintMode : 'none'}
				paintRadiusM={paintRadiusM}
				onPaintStroke={(points) => handlePaintStroke(points)}
				walkabilityOverlayUrl={pageMode === 'paths' && walkabilityOverlayMeta?.has_overlay
					? `${opticalNavWalkabilityOverlayPngUrl(selectedProjectId, sceneId)}?v=${walkabilityOverlayVersion}`
					: null}
				walkabilityOverlayBbox={pageMode === 'paths' && walkabilityOverlayMeta?.grid_spec ? [
					Number(walkabilityOverlayMeta.grid_spec.origin?.[0] ?? 0),
					Number(walkabilityOverlayMeta.grid_spec.origin?.[1] ?? 0),
					Number(walkabilityOverlayMeta.grid_spec.origin?.[0] ?? 0) + Number(walkabilityOverlayMeta.grid_spec.width ?? 0) * Number(walkabilityOverlayMeta.grid_spec.resolution ?? 1),
					Number(walkabilityOverlayMeta.grid_spec.origin?.[1] ?? 0) + Number(walkabilityOverlayMeta.grid_spec.height ?? 0) * Number(walkabilityOverlayMeta.grid_spec.resolution ?? 1)
				] as [number, number, number, number] : null}
				regionSelectMode={pageMode === 'paths' && regionSelectMode}
				onRegionSelected={(bbox) => { pendingRegionBbox = bbox; pathsMode = 'select'; }}
				addEdgeMode={pageMode === 'paths' && (addEdgeMode || edgeInspectorMode)}
				onEdgeFirstNode={(nid) => edgeInspectorMode ? handleInspectorFirstNode(nid) : handleEdgeFirstNode(nid)}
				onEdgeSecondNode={(src, tgt) => edgeInspectorMode ? handleInspectorSecondNode(src, tgt) : handleEdgeSecondNode(src, tgt)}
				removeNodeMode={pageMode === 'paths' && removeNodeMode}
				removeSelection={removeSelection}
				onNodeToggle={toggleRemoveNode}
				onNodesBoxSelect={addRemoveNodes}
				addEdgeGhostColor={edgeInspectorMode ? 0xa855f7 : 0x22c55e}
				addEdgeMaxLengthM={Number(maxEdgeLength)}
				roomShell={roomShell}
				showRoomShell={showRoomShell}
				{xmlSceneIndex}
				{xmlNativePreviewEnabled}
				opticalNavProjectId={selectedProjectId}
				opticalNavSceneId={sceneId}
				graphComponents={graphPayload?.components ?? null}
				traversableOverlayUrl={pageMode === 'paths' && showTraversableMask && traversableMeta?.png_url ? `${traversableMeta.png_url}&v=${traversableVersion}` : null}
				traversableOverlayBbox={pageMode === 'paths' && showTraversableMask && traversableMeta?.bbox ? traversableMeta.bbox : null}
				onFrustumClick={(vpId, headingId) => {
					lightboxUrl = opticalNavObservationModalityUrl(selectedProjectId, sceneId, vpId, headingId, activeRenderModality, activeRigSensorId);
					lightboxLabel = `${vpId} · ${headingId} · ${activeRigSensorId || 'legacy'} · ${activeRenderModality}`;
				}}
			/>

			<!-- Floating top bar: project badge + modes + undo/redo + view presets -->
			<div class="map-float-top">
				<!-- Project badge (collapsed from hidden strip) -->
				{#if selectedProjectId}
					<span class="map-proj-badge">{selectedProjectId}</span>
					<div class="map-float-sep"></div>
				{/if}
				<div class="map-float-modes">
					<button class:active={pageMode === 'map'} onclick={() => setPageMode('map')}>Map</button>
					<button class:active={pageMode === 'objects'} onclick={() => setPageMode('objects')}>Objects</button>
					<button class:active={pageMode === 'paths'} onclick={() => setPageMode('paths')}>Paths</button>
					<button class:active={pageMode === 'sensors'} onclick={() => setPageMode('sensors')}>Sensors</button>
					<button class:active={pageMode === 'lights'} onclick={() => setPageMode('lights')}>Lights</button>
					<button class:active={pageMode === 'preview'} onclick={() => setPageMode('preview')}>Preview</button>
					<button class:active={pageMode === 'export'} onclick={() => setPageMode('export')}>Export</button>
				</div>
				<div class="map-float-sep"></div>
				<button class="map-float-btn" title="Undo (Ctrl+Z)" disabled={!undoStack.length} onclick={undo}>↩</button>
				<button class="map-float-btn" title="Redo (Ctrl+Y)" disabled={!redoStack.length} onclick={redo}>↪</button>
				<div class="map-float-sep"></div>
				{#if syncRunning}
					<span class="sync-progress-chip" title={syncProgress?.stage ?? ''}>
						⟳ Syncing {syncProgress?.processed ?? 0}/{syncProgress?.total ?? 0}
						{#if syncProgress?.label}· {syncProgress.label}{/if}
					</span>
					<div class="map-float-sep"></div>
				{/if}
				<span class="map-float-hint">
					{#if pageMode === 'preview'}
						Simulating · Esc to exit
					{:else if placementTool === 'wall' || placementTool === 'glass_wall' || placementTool === 'mirror_wall'}
						{draftPoint ? 'Click end point · Esc cancel' : `Placing ${placementTool.replace('_', ' ')} · click start`}
					{:else if ['chair','table','plant','camera','usd_asset'].includes(placementTool)}
							Click to place {placementTool === 'usd_asset' ? usdAssetLabel(assetVM.selectedUsdAsset) : placementTool} · Esc cancel
					{:else if placementTool !== 'select'}
						Drag rectangle · Esc cancel
					{:else}
						Right-drag orbit · Wheel zoom · Left-click select
					{/if}
				</span>
				<div style="flex:1"></div>
			</div>

			<AssetCatalog
				{pageMode}
				{placementTool} {selectedAuthoringId}
				{builtInBuildAssets} {builtInPlaceAssetGroups}
					selectedUsdAssetId={assetVM.selectedUsdAssetId}
					usdCatalogSearch={assetVM.usdCatalogSearch}
					mapAssets={assetVM.mapAssets}
					mapAssetStatus={assetVM.mapAssetStatus}
					usdAssetCandidates={assetVM.usdAssetCandidates}
					libraryDisplayLimit={40}
					{selectedProjectId}
					assetThumbRefreshTick={assetVM.assetThumbRefreshTick}
				onSelectTool={(tool) => { placementTool = tool as PlacementTool; draftPoint = null; linePreview = null; }}
				onDelete={deleteSelectedAuthoringItem}
				onSelectBuiltInPlaceAsset={selectBuiltInPlaceAsset}
					onSelectUsdAsset={(id) => { assetVM.selectedUsdAssetId = id; placementTool = 'usd_asset'; draftPoint = null; }}
					onSearchChange={(v) => (assetVM.usdCatalogSearch = v)}
			/>

			<!-- Paths mode: episode list panel -->
			{#if pageMode === 'paths'}
				<div class="map-float-inspector paths-panel">
					<div class="panel-label">Episodes ({filteredEpisodes.length})</div>
					<input class="episode-search" type="search" placeholder="Search..." bind:value={episodeSearch} />
					<div class="episode-list">
						{#each filteredEpisodes as ep}
							<div
								class="episode-row"
								class:selected={selectedEpisodeId === ep.episode_id}
								role="button"
								tabindex="0"
								onclick={() => loadEpisode(ep.episode_id)}
								onkeydown={(e) => e.key === 'Enter' && loadEpisode(ep.episode_id)}
							>
								<span class="ep-id">{ep.episode_id}</span>
								<span class="ep-mode">{ep.navigation_mode ?? 'traj'}</span>
								{#if ep.hazard_collision}<span class="badge-hazard">⚠</span>{/if}
							</div>
						{/each}
						{#if filteredEpisodes.length === 0}
							<div class="episode-empty">{episodes.length === 0 ? 'No episodes yet.' : 'No matches.'}</div>
						{/if}
					</div>
					<div class="episode-generate-bar">
						<input type="number" min="1" bind:value={episodeCount} title="Count" />
						<button class="button button-primary" disabled={!selectedProjectId || !hasGraph || loading} onclick={planGraphEpisodes}>+ Generate</button>
						{#if episodes.length > 0}
							<button class="button button-subtle" onclick={clearEpisodes} title="Clear all episodes">✕</button>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Sensor mode: viewpoint render panel -->
			{#if pageMode === 'sensors'}
					<SensorsPanel
						{renderSceneSynced} {loading} {selectedProjectId} {hasScene} {hasGraph}
						globalCameraRig={assetVM.globalCameraRig}
						globalCameraRigStatus={assetVM.globalCameraRigStatus}
						globalCameraRigError={assetVM.globalCameraRigError}
					{rigSensorOptions} {activeRigSensorId}
					bind:frustumMode bind:placingSensor bind:selectedSensorNodeId
					{selectedSensorNode} {selectedCustomSensorNode}
					{sceneId} {sceneStateText} {cameraSpecText}
					{renderConfig} {renderConfigError}
					{observationScan} bind:activeModalityTab
					{sensorRenderResult} {renderingViewpoint}
					onLoadGlobalCameraRig={loadGlobalCameraRig}
					onSyncRenderScene={syncRenderScene}
					onSelectRigRenderSensor={selectRigRenderSensor}
					onLoadRenderConfig={loadRenderConfig}
					onOptionalJson={optionalJson}
					onRenderSensorViewpoint={renderSensorViewpoint}
					onRenderEpisodes={() => renderEpisodes('graph_sweep')}
					onRenderEpisodeNodes={() => renderEpisodes('episode_nodes')}
					{episodeNodesAvailable}
					{episodePathNodeCount}
					{renderMissingOnly}
					onSetRenderMissingOnly={(v) => (renderMissingOnly = v)}
					headingsPerNode={graphPayload?.node_heading_count ?? 0}
					onRefreshBatch={refreshBatch}
					onRemoveCustomSensor={(id) => { customSensorNodes = customSensorNodes.filter(n => n.id !== id); }}
					onCustomSensorHeadingChange={(id, deg) => { customSensorNodes = customSensorNodes.map(n => n.id === id ? {...n, headingDeg: deg} : n); sensorRenderResult = null; }}
				/>
			{/if}

			<!-- Export mode panel -->
			{#if pageMode === 'export'}
				<ExportPanel
					{hasScene} {hasMap} {hasGraph} {hasEpisodes} {validationPassed}
					{effectiveRenderReadiness} {validationReport} {graphPayloadSummary}
					{splitCounts} {allEpisodePaths} {exportPath} {loading}
					episodesCount={scopedEpisodeCount}
					bind:onlyCompleted={exportOnlyCompleted}
					bind:currentSceneOnly={exportCurrentSceneOnly}
					bind:includeThumbnails={exportIncludeThumbnails}
					bind:panoramaObservations={exportPanoramaObservations}
				bind:pngOnly={exportPngOnly}
				bind:includeBirdseye={exportIncludeBirdseye}
					currentSceneId={sceneId}
					{exportableEpisodeCount}
					exportSummary={exportResult}
					{activeExportJob}
					onValidate={() => validateDataset(false)}
					onExport={exportDataset}
					onCancelExport={cancelActiveExportJob}
					onResetExport={resetExportJob}
				/>
			{/if}

			<!-- Floating right inspector (only when item selected in build/place mode) -->
			{#if selectedAuthoringItem && (pageMode === 'map' || pageMode === 'objects')}
				<InspectorPanel
					item={selectedAuthoringItem}
					itemKind={selectedAuthoringKind}
					dirty={authoringMapDirty}
					{inspectorError} {inspectorTab}
						materialGroups={assetVM.materialGroups} {selectedMaterialInfo} {selectedMaterialSuggestion}
					{materialPickerSearch} {materialPickerCollection} {materialPickerCategory}
					{filteredMaterialCards} {materialCollections} {materialPreviewEntry}
						{materialPreviewValue} materialLibraryStatus={assetVM.materialLibraryStatus}
					{detectedEmitterIds} {hazardTypes}
					{surfaceSnapEnabled} {gridSnapEnabled}
					{transformGridSizeM} {transformAngleSnapDeg}
					onUpdateField={updateSelectedField}
					onUpdateNavigation={updateSelectedNavigation}
					onUpdatePointGeometry={(f, v) => updateSelectedPointGeometry(f as any, v)}
					onUpdateLineGeometry={(f, v) => updateSelectedLineGeometry(f as any, v)}
					onUpdateRectangleBound={updateSelectedRectangleBound}
					onUpdateDimension={(f, v) => updateSelectedDimension(f as any, v)}
					onApplyPreset={(p) => applyInspectorPreset(p as any)}
					onRotatePoint={rotateSelectedPoint}
					onChooseMaterial={chooseMaterial}
					onApplyMaterialWithTags={applyMaterialWithSuggestedTags}
					onDelete={deleteSelectedAuthoringItem}
					onSetInspectorTab={(tab) => (inspectorTab = tab as 'object' | 'material')}
					onSetMaterialPreviewValue={(v) => (materialPreviewValue = v)}
					onSetMaterialPickerSearch={(v) => (materialPickerSearch = v)}
					onSetMaterialPickerCollection={(v) => (materialPickerCollection = v)}
					onSetMaterialPickerCategory={(v) => (materialPickerCategory = v)}
					onSetSurfaceSnapEnabled={(v) => (surfaceSnapEnabled = v)}
					onSetGridSnapEnabled={(v) => (gridSnapEnabled = v)}
					onSetTransformGridSizeM={(v) => (transformGridSizeM = v)}
					onSetTransformAngleSnapDeg={(v) => (transformAngleSnapDeg = v)}
				/>
			{/if}

			<!-- Floating bottom status bar -->
			<div class="map-float-status">
				<span>{authoringSummary.objects}obj</span>
				<span>{authoringSummary.regions}reg</span>
				<span>{authoringSummary.glass}glass</span>
				{#if editor3DStatus}<span>{editor3DStatus}</span>{/if}
				{#if graphPayloadSummary}<span>{graphPayloadSummary.node_count}nodes</span>{/if}
				<span class="map-status-sep"></span>
				<label title="Objects"><input type="checkbox" checked={visibleLayers.objects} onchange={() => toggleLayer('objects')} /> Obj</label>
				<label title="Walkable Area"><input type="checkbox" checked={visibleLayers.traversable} onchange={() => toggleLayer('traversable')} /> Walk</label>
				<label title="Goals"><input type="checkbox" checked={visibleLayers.goals} onchange={() => toggleLayer('goals')} /> Goals</label>
				<label title="Hazards"><input type="checkbox" checked={visibleLayers.hazards} onchange={() => toggleLayer('hazards')} /> Haz</label>
				<label title="Viewpoints"><input type="checkbox" checked={visibleLayers.graphNodes} onchange={() => toggleLayer('graphNodes')} /> VP</label>
				<label title="Path Links"><input type="checkbox" checked={visibleLayers.graphEdges} onchange={() => toggleLayer('graphEdges')} /> Links</label>
				{#if undoStack.length}<span class="map-status-undo">{undoStack.length} undos</span>{/if}
			</div>

			<!-- Floating ⚙ scene settings button + panel -->
			<details class="map-float-settings">
				<summary>⚙ Scene</summary>
				<div class="map-settings-body">
					{#if projectScenes.length > 0}
						<label>
							<span>scene</span>
							<select class="scene-select" value={sceneId} onchange={(e) => { sceneId = e.currentTarget.value; sceneStateText = ''; cameraSpecText = ''; renderConfig = null; syncResult = null; renderReadiness = null; renderConfigError = ''; loadAuthoringMap(); loadRenderConfig(); episodes = []; selectedEpisode = null; selectedEpisodeId = ''; graphPayload = null; observationScan = null; graphBatch = null; graphBatchId = ''; graphBatchIds = []; stopBatchPolling(); _showRoomShellUserTouched = false; if (pageMode === 'sensors') scanObservations(); }}>
								{#each projectScenes as item}
									<option value={item.scene_id}>{item.scene_id}</option>
								{/each}
							</select>
						</label>
					{/if}
					<label><span>scene_id</span><input bind:value={sceneId} /></label>
					<div class="geometry-grid">
						<label><span>map W (m)</span><input type="number" min="1" max="2000" step="1" bind:value={mapWidth} /></label>
						<label><span>map H (m)</span><input type="number" min="1" max="2000" step="1" bind:value={mapHeight} /></label>
					</div>
					{#if hasScene}
						<div class="translate-layout">
							<span class="translate-layout-title">Translate layout (m)</span>
							<div class="geometry-grid">
								<label><span>Δx (east+)</span><input type="number" step="0.1" bind:value={layoutDx} /></label>
								<label><span>Δy (north+)</span><input type="number" step="0.1" bind:value={layoutDy} /></label>
							</div>
							<div class="action-row">
								<button class="button button-subtle" disabled={loading || (!layoutDx && !layoutDy)} onclick={() => { translateLayout(Number(layoutDx) || 0, Number(layoutDy) || 0); layoutDx = 0; layoutDy = 0; }}>Apply shift</button>
								<button class="button button-subtle" disabled={loading} onclick={() => normalizeLayoutToPositive()}>Normalize to ≥0</button>
							</div>
							<span class="translate-layout-sub">Shifts every object &amp; region. Use to make room past the origin (negative editing is also allowed). Then bump map W/H and Save Map.</span>
						</div>
					{/if}
					<div class="action-row">
						<button class="button button-subtle" disabled={!selectedProjectId || loading} onclick={addScene}>Add Scene</button>
						<button class="button button-primary" disabled={!selectedProjectId || !hasScene || loading} onclick={saveMap}>
							{authoringMapDirty ? '● ' : ''}Save Map
						</button>
					</div>
					{#if authoringMapDirty}<p class="inline-hint">Unsaved changes.</p>{/if}
					{#if currentScene?.sync_status}
						<div class="sync-card">
							<div class="panel-label">Sync</div>
							<div class:ready={currentScene.sync_status.render_scene === 'synced'}>Render {currentScene.sync_status.render_scene ?? 'pending'}</div>
							<div class:ready={currentScene.sync_status.isaac_stage === 'synced'}>Isaac {currentScene.sync_status.isaac_stage ?? 'pending'}</div>
							<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || loading} onclick={syncRenderScene} style="display:none">Sync Render Scene</button>
						</div>
					{/if}

					{#if detectedEmitterCount > 0}
						<div class="emitter-bulk-card">
							<div class="panel-label">🔆 Light fixtures</div>
							<div class="emitter-bulk-row">
								<span>{enabledEmitterCount}/{detectedEmitterCount} enabled</span>
								<button class="button button-subtle" disabled={enabledEmitterCount >= detectedEmitterCount} onclick={enableAllDetectedEmitters}>Enable all</button>
								{#if enabledEmitterCount > 0}
									<button class="button button-subtle" onclick={disableAllEmitters}>Disable all</button>
								{/if}
							</div>
						</div>
					{/if}

					<details open class="render-ready-panel">
						<summary>Environment / Render readiness</summary>
						{@render environmentPanel()}
						<div class="render-profile-row">
							<span class="chip-ok">GPU-only</span>
							<span class="chip-ok">Scene reuse</span>
							<span class="chip-dim">Texture max{effectiveRenderReadiness?.texture_profile ?? currentScene?.render_readiness?.texture_profile ?? 1024}</span>
						</div>
						{#if effectiveRenderReadiness}
							<div class="export-validation" class:validation-ok={effectiveRenderReadiness.ok} class:validation-fail={!effectiveRenderReadiness.ok}>
								Render readiness: {effectiveRenderReadiness.status ?? (effectiveRenderReadiness.ok ? 'ready' : 'blocked')}
								{#if effectiveRenderReadiness.error_count != null}<span class="val-errors"> · {effectiveRenderReadiness.error_count} error(s)</span>{/if}
							</div>
							{#if !effectiveRenderReadiness.ok && effectiveRenderReadiness.errors?.length}
								<div class="readiness-errors">
									{#each effectiveRenderReadiness.errors as err}
										<div class="readiness-error-item">
											<span class="readiness-error-label">{err.label ?? err.key}:</span>
											<span class="readiness-error-msg">{err.message}</span>
										</div>
									{/each}
								</div>
							{/if}
						{/if}
						{@render renderGeometryPanel()}
					</details>
					<details>
						<summary>authoring_map.json</summary>
						<textarea class="code-editor small" bind:value={authoringMapText} oninput={markAuthoringJsonDirty} placeholder="authoring_map.json"></textarea>
					</details>
					<details>
						<summary>scene_annotation.json</summary>
						<div class="action-row mt-2">
							<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || loading} onclick={loadAnnotation}>Load</button>
							<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || loading} onclick={saveAnnotation}>Validate</button>
						</div>
						<textarea class="code-editor small" bind:value={annotationText} placeholder="scene_annotation.json"></textarea>
					</details>
				</div>
			</details>

			<!-- Floating ⊞ Paths panel (map + graph + episodes) -->
			<details class="map-float-settings map-float-paths">
				<summary>⊞ Paths</summary>
				<div class="map-settings-body">
					<!-- Status chips -->
					<div class="path-status-chips">
						<span class:chip-ok={hasMap} class:chip-off={!hasMap}>Map {hasMap ? 'ready' : 'missing'}</span>
						<span class:chip-ok={hasGraph} class:chip-off={!hasGraph}>Graph {hasGraph ? 'ready' : 'missing'}</span>
						{#if graphPayloadSummary}<span class="chip-ok">{graphPayloadSummary.node_count}n · {graphPayloadSummary.edge_count}e</span>{/if}
					</div>
					<!-- Grid map -->
					<div class="panel-label">Traversable Grid</div>
					<label><span>resolution m</span><input type="number" step="0.01" min="0.01" bind:value={resolution} /></label>
					<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || buildingMap} onclick={buildMap}>
						{#if buildingMap}<span class="spinner-xs"></span> Building...{:else}{hasMap ? 'Rebuild Grid' : 'Build Grid'}{/if}
					</button>
					{#if mapResult}
						<div class="build-result-row">
							<span class="chip-ok">Grid ready</span>
							{#if mapResult.cell_count}<span class="chip-dim">{mapResult.cell_count} cells</span>{/if}
							{#if mapResult.traversable_ratio != null}<span class="chip-dim">{(mapResult.traversable_ratio * 100).toFixed(0)}% walkable</span>{/if}
						</div>
					{/if}
					<!-- Viewpoint graph -->
					<div class="panel-label mt-2">Viewpoint Graph</div>
					<div class="geometry-grid">
						<label><span>max nodes</span><input type="number" min="1" bind:value={maxNodes} /></label>
						<label><span>headings</span><input type="number" min="1" bind:value={headingCount} /></label>
						<label><span>spacing m</span><input type="number" step="0.05" min="0" bind:value={minNodeSpacing} /></label>
						<label><span>robot r</span><input type="number" step="0.05" min="0" bind:value={robotRadius} /></label>
					</div>
					<button class="button button-subtle" disabled={!selectedProjectId || !hasMap || buildingGraph} onclick={requestBuildGraph}>
						{#if buildingGraph}<span class="spinner-xs"></span>{#if graphBuildProgress} {graphBuildProgress.stage === 'edges' ? 'Edges' : 'Nodes'} {Math.round(graphBuildProgress.progress * 100)}%{:else} Building...{/if}{:else}{hasGraph ? 'Rebuild Graph' : 'Build Graph'}{/if}
					</button>
					{#if graphResult || graphPayloadSummary}
						<div class="build-result-row">
							<span class="chip-ok">Graph ready</span>
							<span class="chip-dim">{graphPayloadSummary?.node_count ?? graphResult?.node_count ?? '?'}n</span>
							<span class="chip-dim">{graphPayloadSummary?.edge_count ?? graphResult?.edge_count ?? '?'}e</span>
							{#if (graphPayloadSummary?.hazard_edge_count ?? graphResult?.hazard_edge_count ?? 0) > 0}
								<span class="chip-warn">{graphPayloadSummary?.hazard_edge_count ?? graphResult?.hazard_edge_count} hazard</span>
							{/if}
						</div>
					{/if}
					<!-- Episodes -->
					<div class="panel-label mt-2">Episodes</div>
					<label><span>num pairs</span><input type="number" min="1" bind:value={episodeCount} /></label>
					<button class="button button-primary" disabled={!selectedProjectId || !hasGraph || loading} onclick={planGraphEpisodes}>
						Generate Episodes
					</button>
					{#if splitCounts.train != null}
						<div class="path-status-chips mt-1">
							<span class="chip-ok">train {splitCounts.train}</span>
							<span class="chip-ok">val_seen {splitCounts.val_seen ?? 0}</span>
							<span class="chip-ok">val_unseen {splitCounts.val_unseen ?? 0}</span>
						</div>
					{/if}
				</div>
			</details>

			<!-- Map start card overlay (when empty) -->
			{#if !hasAuthoringContent}
				<div class="map-start-card">
					<div>
						<strong>{selectedProjectId ? 'No map overlay yet' : 'Map editor'}</strong>
						<span>
							{#if !selectedProjectId}Create or select a project to start editing.
							{:else if !hasScene}Add a scene, then create a starter overlay.
							{:else}Create a starter layout or place objects with the palette.
							{/if}
						</span>
					</div>
					<button class="button button-primary" onclick={createStarterOverlay}>Create Starter Overlay</button>
				</div>
			{/if}

		</section>
		<!-- /scene tab -->
</div>

{#if lightboxUrl}
	<div class="lightbox-overlay" role="dialog" onclick={() => { lightboxUrl = ''; lightboxLabel = ''; }}>
		<div class="lightbox-inner" role="presentation" onclick={(e) => e.stopPropagation()}>
			<div class="lightbox-header">
				<span>{lightboxLabel}</span>
				<button class="lightbox-close" onclick={() => { lightboxUrl = ''; lightboxLabel = ''; }}>✕</button>
			</div>
			<img src={lightboxUrl} alt={lightboxLabel} class="lightbox-img" />
		</div>
	</div>
{/if}

{#if graphRebuildConfirmOpen}
	<div class="confirm-overlay" role="dialog" aria-modal="true" tabindex="-1">
		<div class="confirm-dialog">
			<div class="confirm-title">Rebuild viewpoint graph?</div>
			<p>
				This will overwrite the current viewpoint graph using the current traversable grid settings, robot footprint, and sampling parameters.
			</p>
			<div class="confirm-facts">
				<span>{graphPayloadSummary?.node_count ?? currentScene?.viewpoint_graph?.node_count ?? 0} existing nodes</span>
				<span>{graphPayloadSummary?.edge_count ?? currentScene?.viewpoint_graph?.edge_count ?? 0} existing edges</span>
				<span>seed {seed}</span>
			</div>
			<div class="confirm-actions">
				<button class="button button-subtle" onclick={cancelGraphRebuild}>No</button>
				<button class="button button-primary" onclick={confirmGraphRebuild}>Yes, rebuild</button>
			</div>
		</div>
	</div>
{/if}

{#if contextMenu}
	<div
		class="context-menu"
		style={`left: ${contextMenu.x}px; top: ${contextMenu.y}px`}
		role="menu"
	>
		<div class="context-menu-title">{contextMenu.targetId}</div>
		<hr />
		<button role="menuitem" onclick={contextMenuDuplicate}>Duplicate</button>
		{#if contextMenu.targetType === 'object'}
			<button role="menuitem" onclick={() => { rotateSelectedPoint(-45); closeContextMenu(); }}>Rotate left 45°</button>
			<button role="menuitem" onclick={() => { rotateSelectedPoint(45); closeContextMenu(); }}>Rotate right 45°</button>
			<hr />
			<button role="menuitem" onclick={() => { applyInspectorPreset('glass'); closeContextMenu(); }}>Set: Glass hazard</button>
			<button role="menuitem" onclick={() => { applyInspectorPreset('mirror'); closeContextMenu(); }}>Set: Mirror hazard</button>
			<button role="menuitem" onclick={() => { applyInspectorPreset('landmark'); closeContextMenu(); }}>Set: Landmark goal</button>
		{/if}
		<hr />
		<button role="menuitem" onclick={previewFromSelected}>Preview from here</button>
		<button role="menuitem" onclick={() => createRegionAroundSelected('start')}>Set as robot start</button>
		<button role="menuitem" onclick={() => createRegionAroundSelected('goal')}>Set as goal</button>
		{#if contextMenu.targetType !== 'object' && hasNodeObservations(contextMenu.targetId)}
			<hr />
			<button role="menuitem" onclick={() => { clearNodeObservations(contextMenu!.targetId); closeContextMenu(); }}>Clear renders</button>
		{/if}
		<hr />
		<button role="menuitem" class="danger" onclick={contextMenuDelete}>Delete</button>
	</div>
{/if}

{#snippet datasetRailContent()}
	<div class="dataset-rail">
		<div class="rail-tabbar" aria-label="Right panel tabs">
			{#if selectedAuthoringItem}
				<button class:active={railTab === 'selected'} onclick={() => activateRailTab('selected')}>Selected</button>
			{/if}
			<button class:active={railTab === 'scene'} onclick={() => activateRailTab('scene')}>Scene</button>
			{#if pageMode === 'paths'}
				<button class:active={railTab === 'paths'} onclick={() => activateRailTab('paths')}>Paths</button>
			{/if}
			<button class:active={railTab === 'sensors'} onclick={() => activateRailTab('sensors')}>Sensors</button>
			<button class:active={railTab === 'lights'} onclick={() => activateRailTab('lights')}>Lights</button>
			<button class:active={railTab === 'preview'} onclick={() => activateRailTab('preview')}>Preview</button>
			<button class:active={railTab === 'export'} onclick={() => activateRailTab('export')}>Export</button>
			<button class:active={railTab === 'status'} onclick={() => activateRailTab('status')}>Status</button>
		</div>

		{#if railTab === 'selected' && selectedAuthoringItem}
			<RailSelectedTab
				item={selectedAuthoringItem}
				itemKind={selectedAuthoringKind}
				itemId={selectedAuthoringId}
				dirty={authoringMapDirty}
				{inspectorTab} {inspectorError}
					materialGroups={assetVM.materialGroups} {selectedMaterialInfo} {selectedMaterialSuggestion}
				{materialPickerSearch} {materialPickerCollection} {materialPickerCategory}
				{filteredMaterialCards} {materialCollections} {materialPreviewEntry}
					{materialPreviewValue} materialLibraryStatus={assetVM.materialLibraryStatus}
				{detectedEmitterIds} {hazardTypes}
				{surfaceSnapEnabled} {gridSnapEnabled} {transformGridSizeM} {transformAngleSnapDeg}
				onUpdateField={updateSelectedField}
				onUpdateNavigation={updateSelectedNavigation}
				onUpdatePointGeometry={(f, v) => updateSelectedPointGeometry(f as any, v)}
				onUpdateLineGeometry={(f, v) => updateSelectedLineGeometry(f as any, v)}
				onUpdateRectangleBound={updateSelectedRectangleBound}
				onUpdateDimension={(f, v) => updateSelectedDimension(f as any, v)}
				onApplyPreset={(p) => applyInspectorPreset(p as any)}
				onRotatePoint={rotateSelectedPoint}
				onChooseMaterial={chooseMaterial}
				onApplyMaterialWithTags={applyMaterialWithSuggestedTags}
				onDelete={deleteSelectedAuthoringItem}
				onSetInspectorTab={(tab) => (inspectorTab = tab as 'object' | 'material')}
				onSetMaterialPreviewValue={(v) => (materialPreviewValue = v)}
				onSetMaterialPickerSearch={(v) => (materialPickerSearch = v)}
				onSetMaterialPickerCollection={(v) => (materialPickerCollection = v)}
				onSetMaterialPickerCategory={(v) => (materialPickerCategory = v)}
				onSetSurfaceSnapEnabled={(v) => (surfaceSnapEnabled = v)}
				onSetGridSnapEnabled={(v) => (gridSnapEnabled = v)}
				onSetTransformGridSizeM={(v) => (transformGridSizeM = v)}
				onSetTransformAngleSnapDeg={(v) => (transformAngleSnapDeg = v)}
			/>
		{/if}

		{#if railTab === 'paths'}
			<RailPathsTab
				{hasMap} {hasGraph} {hasScene} {selectedProjectId} {sceneId} {loading}
				{buildingMap} {buildingGraph} {graphBuildProgress} {graphResult} {mapResult}
				{graphPayloadSummary} {graphPayload} graphNodes={graphNodes} graphEdges={graphEdges}
				{pathsMode} {paintRadiusM} {pendingEdgeSource} {edgeInspectorSource}
				{pendingRegionBbox} {walkabilityOverlayMeta} {traversableMeta}
				{showTraversableMask} {showFootprint} {edgeCheckResult}
				{filteredEpisodes} {episodes} {episodeSearch} {episodeCount}
				{selectedEpisodeId} {splitCounts}
				{robotRadius} {minClearance} {resolution}
				{maxNodes} {headingCount} {minNodeSpacing} {selectedSensorNode}
				onBuildMap={buildMap}
				onRequestBuildGraph={requestBuildGraph}
				onRebuildEdges={rebuildGraphEdges}
				rebuildingEdges={rebuildingEdges}
				onSetPathsMode={(m) => (pathsMode = m as PathsInteractionMode)}
				onSetPaintRadius={(r) => (paintRadiusM = r)}
				onRebuildRegion={rebuildRegion}
				onClearRegion={() => (pendingRegionBbox = null)}
				onClearWalkabilityOverlay={clearWalkabilityOverlay}
				onRefreshTraversableMeta={refreshTraversableMeta}
				onSetShowFootprint={(v) => (showFootprint = v)}
				onSetShowTraversableMask={(v) => (showTraversableMask = v)}
				onAddEdgeAnyway={addEdgeAnyway}
				onDismissEdgeCheck={() => (edgeCheckResult = null)}
				onDeleteGraphEdge={handleDeleteGraphEdge}
				onDeleteGraphNode={deleteSelectedGraphNode}
				removeSelectionCount={removeSelection.size}
				removeMarginM={removeMarginM}
				removePassHeightM={removePassHeightM}
				findingOverlapping={findingOverlapping}
				removingNodes={removingNodes}
				onFindOverlapping={findOverlappingNodes}
				onRemoveSelectedNodes={removeSelectedGraphNodes}
				onClearRemoveSelection={clearRemoveSelection}
				onSetRemoveMargin={(v) => (removeMarginM = v)}
				onSetRemovePassHeight={(v) => (removePassHeightM = v)}
				onLoadEpisode={loadEpisode}
				onGenerateEpisodes={planGraphEpisodes}
				onClearEpisodes={clearEpisodes}
				onSetEpisodeSearch={(v) => (episodeSearch = v)}
				onSetEpisodeCount={(n) => (episodeCount = n)}
				onSetRobotRadius={(v) => (robotRadius = v)}
				onSetMinClearance={(v) => (minClearance = v)}
				onSetResolution={(v) => (resolution = v)}
				onSetMaxNodes={(n) => (maxNodes = n)}
				onSetHeadingCount={(n) => (headingCount = n)}
				onSetMinNodeSpacing={(v) => (minNodeSpacing = v)}
				onRenderEpisodeNodes={() => renderEpisodes('episode_nodes')}
				{episodeNodesAvailable}
				{episodePathNodeCount}
				{renderMissingOnly}
				onSetRenderMissingOnly={(v) => (renderMissingOnly = v)}
				headingsPerNode={graphPayload?.node_heading_count ?? 0}
				{renderSceneSynced}
			/>
		{/if}

			{#if railTab === 'sensors'}
				<RailSensorsTab
					{renderSceneSynced}
					globalCameraRig={assetVM.globalCameraRig}
					globalCameraRigStatus={assetVM.globalCameraRigStatus}
					globalCameraRigError={assetVM.globalCameraRigError}
				{rigSensorOptions} {activeRigSensorId} {selectedSensorNode} {selectedSensorNodeId}
				{selectedCustomSensorNode} {selectedSensorHeightM}
				{sceneStateText} {cameraSpecText} {renderConfig}
				{observationScan} {graphBatch} {sensorRenderResult} {renderingViewpoint}
				{placingSensor} {frustumMode} {ambientRadiance} {activeModalityTab}
				{activeRigSensorOption} {rigMountHeightM} {authoringMap}
				{selectedProjectId} {sceneId} {loading} {hasScene} {hasGraph}
				{renderSceneStats} {renderSceneStatsLoading}
				{showRoomShell} {roomShell}
				{editorObjectsCount} {editorEmitterCount} {editorMaterialCount}
				onLoadGlobalCameraRig={loadGlobalCameraRig}
				onSelectRigSensor={selectRigRenderSensor}
				onSetFrustumMode={(m) => (frustumMode = m as 'none' | 'view-aligned' | 'selected')}
				onTogglePlacingSensor={() => { placingSensor = !placingSensor; selectedSensorNodeId = ''; }}
				onRemoveCustomSensor={(id) => { customSensorNodes = customSensorNodes.filter(n => n.id !== id); selectedSensorNodeId = ''; }}
				onCustomSensorHeadingChange={(id, deg) => { customSensorNodes = customSensorNodes.map(n => n.id === id ? {...n, headingDeg: deg} : n); sensorRenderResult = null; }}
				onLoadRenderConfig={loadRenderConfig}
				onSetSensorHeight={setSelectedSensorHeight}
				onSetAmbientRadiance={(v) => (ambientRadiance = v)}
				onClearNodeObservations={clearNodeObservations}
				onClearAllObservations={clearAllObservations}
				onRenderViewpoint={renderSensorViewpoint}
				onRenderEpisodes={() => renderEpisodes('graph_sweep')}
				onRenderEpisodeNodes={() => renderEpisodes('episode_nodes')}
				{episodeNodesAvailable}
				{episodePathNodeCount}
				{renderMissingOnly}
				onSetRenderMissingOnly={(v) => (renderMissingOnly = v)}
				headingsPerNode={graphPayload?.node_heading_count ?? 0}
				onRefreshBatch={() => refreshBatch()}
				onRefreshStats={refreshRenderSceneStats}
				onSetShowRoomShell={(v) => { showRoomShell = v; _showRoomShellUserTouched = true; }}
			/>
		{/if}

		{#if railTab === 'lights'}
			<RailLightsTab
				{authoringMap} {detectedEmitterIds} {detectedEmitterCount} {enabledEmitterCount}
				{hasScene} {loading}
				onEnableAll={enableAllDetectedEmitters}
				onDisableAll={disableAllEmitters}
				onToggleEmitter={handleToggleEmitter}
				onSetEmitterIntensity={handleSetEmitterIntensity}
				onSetEmitterRadiance={handleSetEmitterRadiance}
				onSetEmitterHeight={handleSetEmitterHeight}
				onSave={saveAuthoringMap}
			/>
		{/if}

		{#if railTab === 'preview'}
			<RailPreviewTab
				hotCameraPose={activeHotCameraPose}
				{hotCameraPoses} {activeHotCameraId}
				{activeRigSensorOption} {activeCameraFrustum} {activeRenderModality}
				{probeRendering} {probeError} {probeResult} {activeRigSensorId}
				{selectedProjectId} {sceneId}
				{editorObjectsCount} {editorEmitterCount} {editorMaterialCount}
				{renderSceneStats} {renderSceneStatsLoading}
				{showRoomShell} {roomShell} {rigMountHeightM} {authoringMap}
				{hasScene} {loading}
				onRunProbe={renderHotCameraPreview}
				onRefreshBatch={() => refreshBatch()}
				onRefreshStats={refreshRenderSceneStats}
				onSetShowRoomShell={(v) => { showRoomShell = v; _showRoomShellUserTouched = true; }}
				onSelectHotCamera={(id) => { activeHotCameraId = id; }}
			/>
		{/if}

		{#if railTab === 'export'}
			<RailExportTab
				{hasScene} {hasMap} {hasGraph} {hasEpisodes} {validationPassed}
				{renderSceneSynced} {effectiveRenderReadiness} {currentScene}
				{rigSensorOptions} {graphPayloadSummary}
				episodesCount={scopedEpisodeCount}
				{splitCounts} {allEpisodePaths} {validationReport} {exportPath}
				{selectedProjectId} {loading}
				bind:onlyCompleted={exportOnlyCompleted}
				bind:currentSceneOnly={exportCurrentSceneOnly}
				bind:includeThumbnails={exportIncludeThumbnails}
				bind:panoramaObservations={exportPanoramaObservations}
				bind:pngOnly={exportPngOnly}
				bind:includeBirdseye={exportIncludeBirdseye}
				currentSceneId={sceneId}
				{exportableEpisodeCount}
				exportSummary={exportResult}
				{activeExportJob}
				onValidate={() => validateDataset(false)}
				onExport={exportDataset}
				onCancelExport={cancelActiveExportJob}
				onResetExport={resetExportJob}
			/>
		{/if}

		{#if railTab === 'scene'}
			<RailSceneTab
				{sceneId} {projectScenes} {selectedProjectId} {hasScene}
				{authoringMapDirty} {authoringMapText} {annotationText}
				{authoringMap} {currentScene} {detectedEmitterCount} {enabledEmitterCount}
				{effectiveRenderReadiness} {mapWidth} {mapHeight} {loading}
					envmapFiles={assetVM.envmapFiles}
					envmapUploading={assetVM.envmapUploading}
				onSceneChange={(id) => { sceneId = id; sceneStateText = ''; cameraSpecText = ''; renderConfig = null; syncResult = null; renderReadiness = null; renderConfigError = ''; loadAuthoringMap(); loadRenderConfig(); episodes = []; selectedEpisode = null; selectedEpisodeId = ''; graphPayload = null; observationScan = null; graphBatch = null; graphBatchId = ''; graphBatchIds = []; stopBatchPolling(); _showRoomShellUserTouched = false; if (pageMode === 'sensors') scanObservations(); }}
				onSetMapWidth={setMapWidthFromInput}
				onSetMapHeight={setMapHeightFromInput}
				onTranslateLayout={translateLayout}
				onNormalizeLayout={() => normalizeLayoutToPositive()}
				onAddScene={addScene}
				onSaveMap={saveMap}
				onEnableAllEmitters={enableAllDetectedEmitters}
				onDisableAllEmitters={disableAllEmitters}
				onUpdateEnvironmentField={updateEnvironmentField}
				onUpdateSettingsField={updateSettingsField}
				onUploadEnvmap={uploadEnvmapFromInput}
				onMarkAuthoringJsonDirty={markAuthoringJsonDirty}
				onAuthoringMapTextChange={(v) => (authoringMapText = v)}
				onAnnotationTextChange={(v) => (annotationText = v)}
				onLoadAnnotation={loadAnnotation}
				onSaveAnnotation={saveAnnotation}
			/>
		{/if}

	</div>
{/snippet}

{#snippet datasetBottomContent()}
	<BottomPanel
		bottomPanelCollapsed={$bottomPanelCollapsed}
		{activeBatch} {renderMode}
		{selectedBatchJobId} {selectedBatchJob} {selectedBatchJobLog} {selectedBatchJobLoading}
		{selectedBatchJobImageUrl}
		{batchLogEntries} {activityLog} {loading}
		onTogglePanel={toggleBottomPanel}
		onRefreshBatch={refreshBatch}
		onSelectBatchJob={selectBatchJob}
		onCancelStaleBatchJobs={cancelStaleBatchJobs}
		onCloseJobDetail={() => { selectedBatchJobId = ''; selectedBatchJobLog = []; }}
		onRetryJob={retryBatchJob}
		onCancelJob={cancelBatchJob}
		onRefreshSelectedJobLog={() => refreshSelectedBatchJobLog()}
	/>
{/snippet}

<style>
	:global {

	/* --- Mode bar --- */
	.mode-bar {
		display: flex;
		gap: var(--space-1);
		align-items: center;
		padding: var(--space-1) var(--space-2);
		background: var(--surface-2, #f1f5f9);
		border-bottom: 1px solid var(--panel-border);
	}
	.mode-bar button {
		padding: 3px 10px;
		font-size: var(--font-size-sm);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		background: transparent;
		cursor: pointer;
		color: var(--muted-strong);
	}
	.mode-bar button.active {
		background: var(--surface-1);
		border-color: var(--panel-border);
		color: var(--fg);
		font-weight: 600;
	}
	.mode-separator { flex: 1; }
	.palette-sep {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		color: var(--muted);
		letter-spacing: 0.05em;
		margin-left: var(--space-1);
	}
	.palette-hint { font-size: var(--font-size-xs); color: var(--muted); margin-left: var(--space-2); }
	.undo-indicator { font-size: 10px; color: var(--muted); }
	.advanced-details { display: inline; }
	.advanced-details summary { font-size: var(--font-size-xs); color: var(--muted-strong); cursor: pointer; }
	.mt-2 { margin-top: var(--space-2); }

	/* --- Context menu --- */
	.lightbox-overlay {
		position: fixed; inset: 0; z-index: 2000; background: rgba(0,0,0,0.75);
		display: flex; align-items: center; justify-content: center;
	}
	.lightbox-inner {
		background: var(--surface-0, #1e1e2e); border-radius: 8px; overflow: hidden;
		max-width: 90vw; max-height: 90vh; display: flex; flex-direction: column;
		box-shadow: 0 8px 32px rgba(0,0,0,0.5);
	}
	.lightbox-header {
		display: flex; align-items: center; justify-content: space-between;
		padding: 8px 12px; background: var(--surface-1, #2a2a3a);
		font-size: 12px; font-family: monospace; color: var(--text-muted);
	}
	.lightbox-close { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 16px; padding: 0 4px; }
	.lightbox-img { max-width: 100%; max-height: calc(90vh - 40px); object-fit: contain; display: block; }

	.confirm-overlay {
		position: fixed;
		inset: 0;
		z-index: 2100;
		display: grid;
		place-items: center;
		padding: var(--space-4);
		background: rgba(15, 23, 42, 0.42);
		backdrop-filter: blur(4px);
	}
	.confirm-dialog {
		width: min(440px, calc(100vw - 32px));
		display: grid;
		gap: var(--space-3);
		padding: var(--space-4);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-0);
		color: var(--text-primary);
		box-shadow: 0 18px 48px rgba(15, 23, 42, 0.24);
	}
	.confirm-title {
		font-size: var(--font-size-lg);
		font-weight: 800;
	}
	.confirm-dialog p {
		margin: 0;
		color: var(--text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.45;
	}
	.confirm-facts {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.confirm-facts span {
		padding: 3px 8px;
		border: 1px solid var(--panel-border);
		border-radius: 999px;
		background: var(--surface-1);
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.confirm-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
	}

	.context-menu {
		position: fixed;
		z-index: 1000;
		background: var(--surface-0, #fff);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		box-shadow: 0 4px 16px rgba(0,0,0,0.15);
		padding: var(--space-1) 0;
		min-width: 180px;
	}
	.context-menu-title {
		padding: var(--space-1) var(--space-3);
		font-size: var(--font-size-xs);
		font-weight: 600;
		color: var(--muted-strong);
	}
	.context-menu hr { border: none; border-top: 1px solid var(--panel-border); margin: var(--space-1) 0; }
	.context-menu button {
		display: block;
		width: 100%;
		padding: 5px var(--space-3);
		text-align: left;
		background: none;
		border: none;
		cursor: pointer;
		font-size: var(--font-size-sm);
		color: var(--fg);
	}
	.context-menu button:hover { background: var(--surface-2, #f1f5f9); }
	.context-menu button.danger { color: var(--danger); }

	.dataset-page {
		display: grid;
		gap: var(--space-4);
		padding-bottom: 96px;
	}
	.dataset-page.bottom-open {
		padding-bottom: 360px;
	}
	.dataset-page.bottom-maximized {
		padding-bottom: 70vh;
	}
	/* When map editor is active: fixed height, no scroll, flex column */
	.dataset-page.scene-active {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-4) 0;
		height: 100%;
		min-height: 0;
	}
	/* Collapse strips and header — canvas fills the space */
	.dataset-page.scene-active > header.page-header,
	.dataset-page.scene-active .project-strip,
	.dataset-page.scene-active .readiness-strip { display: none; }
	.dataset-page.scene-active :global(.tabs-bar) { flex: 0 0 auto; }
	.page-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); }
	.page-header p { margin: var(--space-1) 0 0; color: var(--muted); }
	h1 { margin: 0; font-size: var(--font-size-2xl); letter-spacing: 0; }
	.header-actions, .action-row { display: flex; gap: var(--space-2); flex-wrap: wrap; align-items: center; }
	.primary-next {
		display: grid;
		grid-template-columns: minmax(260px, 1fr) auto;
		gap: var(--space-3);
		align-items: center;
		min-width: min(560px, 48vw);
		padding: var(--space-3);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		box-shadow: var(--shadow-sm);
	}
	.primary-next strong {
		display: block;
		margin-top: 2px;
		font-size: var(--font-size-lg);
	}
	.primary-next p {
		margin: var(--space-1) 0 0;
		color: var(--muted-strong);
		font-size: var(--font-size-sm);
	}
	.primary-next.status-blocked {
		border-color: #f4c26f;
		background: #fff8e8;
	}
	.primary-next.status-failed {
		border-color: #f0b4b4;
		background: var(--danger-soft);
	}
	.project-strip { display: grid; grid-template-columns: 1.1fr 1fr 1.2fr 1fr auto; gap: var(--space-3); align-items: end; }
	.readiness-strip { display: flex; gap: var(--space-2); flex-wrap: wrap; }
	.readiness-strip button {
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--muted-strong);
	}
	.readiness-strip button.ready {
		border-color: var(--tool-traversable);
		background: var(--tool-traversable-soft);
		color: var(--tool-traversable);
	}
	label { display: grid; gap: var(--space-1); font-size: var(--font-size-xs); color: var(--muted-strong); }
	input, select, textarea {
		min-width: 0;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--text);
		font: inherit;
	}
	input, select { height: 34px; padding: 0 var(--space-3); }
	textarea { min-height: 72px; padding: var(--space-2); resize: vertical; }
	.code-editor { min-height: 340px; font-family: var(--font-mono); font-size: var(--font-size-xs); }
	.code-editor.small { min-height: 180px; }
	.tab-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(340px, 0.8fr); gap: var(--space-4); }
	.scene-canvas, .map-panel { min-height: 430px; }
	.stack { display: grid; gap: var(--space-3); align-content: start; }
	.canvas-toolbar {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-bottom: var(--space-3);
	}
	.tool {
		min-height: 34px;
		border: 1px solid var(--panel-border);
		background: var(--surface-1);
		color: var(--muted-strong);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-2);
		white-space: nowrap;
		font-size: var(--font-size-sm);
	}
	.tool.active { border-color: var(--brand); color: var(--brand-strong); background: var(--brand-soft); }
	.tool.danger { color: var(--danger); }
	.tool-glass.active { border-color: var(--tool-glass); color: var(--tool-glass); background: var(--tool-glass-soft); }
	.tool-mirror.active { border-color: var(--muted); color: #334155; background: #f1f5f9; }
	.tool-traversable.active { border-color: var(--tool-traversable); color: var(--tool-traversable); background: var(--tool-traversable-soft); }
	.tool-goal.active { border-color: var(--tool-goal); color: var(--tool-goal); background: var(--tool-goal-soft); }
	.tool-hazard.active { border-color: var(--tool-hazard); color: var(--tool-hazard); background: var(--tool-hazard-soft); }
	.tool-forbidden.active { border-color: var(--danger); color: #8a1c1c; background: var(--danger-soft); }
	.editor-help {
		margin-bottom: var(--space-3);
		color: var(--muted-strong);
		font-size: var(--font-size-sm);
	}
	.layer-toggles {
		display: flex;
		gap: var(--space-2);
		flex-wrap: nowrap;
		overflow-x: auto;
		margin-bottom: var(--space-3);
		padding-bottom: 2px;
	}
	.layer-toggles label {
		display: flex;
		grid-template-columns: none;
		align-items: center;
		gap: 6px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		padding: var(--space-1) var(--space-2);
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.layer-toggles input {
		width: 14px;
		height: 14px;
		padding: 0;
	}
	.map-canvas-wrap {
		position: relative;
	}
	.authoring-map {
		width: 100%;
		height: clamp(300px, 38vh, 440px);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		cursor: crosshair;
		touch-action: none;
		display: block;
	}
	.dataset-page.bottom-open .authoring-map {
		height: clamp(260px, 32vh, 360px);
	}
	.map-editor-panel {
		position: relative;
	}
	.map-start-card {
		position: absolute;
		top: var(--space-3);
		left: var(--space-3);
		right: var(--space-3);
		z-index: 2;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3);
		border: 1px solid #bfdbfe;
		border-radius: var(--radius-md);
		background: #eff6ff;
		color: #1e3a8a;
	}
	.map-start-card strong {
		display: block;
		font-size: var(--font-size-sm);
	}
	.map-start-card span {
		display: block;
		margin-top: 2px;
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.floorplan-outline {
		fill: rgba(248, 250, 252, 0.72);
		stroke: var(--muted);
		stroke-width: 1.5;
		stroke-dasharray: 8 6;
		pointer-events: none;
	}
	.map-axis-label {
		fill: var(--muted-strong);
		font-size: 12px;
		font-weight: 700;
		pointer-events: none;
	}
	.empty-map-cta {
		position: absolute;
		left: 50%;
		top: 56%;
		transform: translate(-50%, -50%);
		display: grid;
		gap: var(--space-3);
		width: min(360px, calc(100% - 64px));
		padding: var(--space-4);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: rgba(255, 255, 255, 0.94);
		box-shadow: var(--shadow-md);
	}
	.empty-map-cta strong {
		display: block;
		font-size: var(--font-size-lg);
	}
	.empty-map-cta span {
		display: block;
		margin-top: var(--space-1);
		color: var(--muted-strong);
		font-size: var(--font-size-sm);
	}
	.inline-hint {
		margin: 0;
		color: var(--tool-hazard);
		font-size: var(--font-size-xs);
	}
	.map-line {
		stroke: var(--tool-glass);
		stroke-width: 8;
		stroke-linecap: round;
		filter: drop-shadow(0 1px 2px rgba(15, 23, 42, 0.18));
		cursor: pointer;
	}
	.map-line.mirror_wall { stroke: var(--muted); }
	.map-line.selected { stroke: var(--brand); stroke-width: 11; }
	.map-line.draft-line {
		stroke-dasharray: 10 6;
		opacity: 0.65;
		pointer-events: none;
		cursor: none;
		filter: none;
	}
	.map-region {
		stroke-width: 2;
		cursor: pointer;
	}
	.region-traversable {
		fill: rgba(54, 164, 92, 0.18);
		stroke: var(--tool-traversable);
	}
	.region-goal {
		fill: rgba(47, 128, 237, 0.18);
		stroke: var(--tool-goal);
	}
	.region-start {
		fill: rgba(79, 70, 229, 0.14);
		stroke: #4f46e5;
	}
	.region-stop {
		fill: rgba(14, 165, 233, 0.16);
		stroke: #0284c7;
	}
	.region-hazard {
		fill: rgba(221, 122, 34, 0.18);
		stroke: var(--tool-hazard);
	}
	.region-forbidden {
		fill: rgba(197, 48, 48, 0.16);
		stroke: var(--danger);
	}
	.region-generic {
		fill: rgba(100, 116, 139, 0.12);
		stroke: var(--muted-strong);
	}
	.map-region.selected {
		stroke-width: 4;
	}
	.map-region.draft {
		fill: rgba(47, 128, 237, 0.1);
		stroke: var(--brand);
		stroke-dasharray: 8 6;
		pointer-events: none;
	}
	.map-point {
		cursor: pointer;
		filter: drop-shadow(0 1px 2px rgba(15, 23, 42, 0.18));
	}
	.map-point circle {
		fill: #ffffff;
		stroke: var(--muted-strong);
		stroke-width: 2;
	}
	.map-point text {
		fill: #334155;
		font-size: 11px;
		font-weight: 800;
		text-anchor: middle;
		pointer-events: none;
	}
	.map-point.chair circle { stroke: #7c3aed; }
	.map-point.table circle { stroke: var(--tool-hazard); }
	.map-point.plant circle { stroke: #15803d; }
	.map-point.selected circle {
		fill: var(--brand-soft);
		stroke: var(--brand);
		stroke-width: 4;
	}
	.graph-edge {
		stroke: rgba(71, 85, 105, 0.38);
		stroke-width: 2;
		pointer-events: none;
	}
	.graph-edge.hazard {
		stroke: rgba(221, 122, 34, 0.72);
		stroke-dasharray: 6 5;
	}
	.graph-node {
		fill: #2563eb;
		stroke: var(--surface-1);
		stroke-width: 2;
		pointer-events: none;
	}
	.graph-node.hazard-adjacent {
		fill: var(--tool-hazard);
	}
	.draft-point {
		fill: var(--brand);
		stroke: var(--surface-1);
		stroke-width: 3;
		pointer-events: none;
	}
	.editor-metrics {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-3);
	}
	.editor-metrics span {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-2);
		background: var(--surface-1);
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.inspector {
		display: grid;
		gap: var(--space-3);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		padding: var(--space-3);
		background: var(--surface-1);
	}


	.geometry-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-2);
	}


	.inline-error {
		margin: 0;
		color: #b42318;
		font-size: var(--font-size-xs);
	}
	.requirement-card {
		display: grid;
		gap: var(--space-2);
		border: 1px solid #f4c26f;
		border-radius: var(--radius-md);
		background: #fff8e8;
		padding: var(--space-3);
	}
	.requirement-card div:not(.panel-label) {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
		color: var(--tool-hazard);
		font-size: var(--font-size-sm);
	}
	.requirement-card div.ready {
		color: var(--tool-traversable);
	}
	.requirement-card p {
		margin: 0;
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.sync-card {
		display: grid;
		gap: var(--space-2);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		padding: var(--space-3);
	}
	.sync-card div:not(.panel-label) {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
		color: var(--tool-hazard);
		font-size: var(--font-size-sm);
	}
	.sync-card div.ready {
		color: var(--tool-traversable);
	}
	.sync-card p {
		margin: 0;
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.emitter-bulk-card {
		display: grid;
		gap: var(--space-2);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		padding: var(--space-3);
	}
	.emitter-bulk-row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}
	.emitter-hint {
		margin: 0 0 var(--space-2) 0;
		padding: var(--space-2);
		background: var(--warning-soft);
		color: var(--tool-hazard);
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
	}


	.paint-mode-row { display: grid; gap: 4px; font-size: var(--font-size-xs); }
	.paint-mode-row label { display: flex; gap: 6px; align-items: center; }


	.sync-progress-chip {
		display: inline-flex;
		gap: 6px;
		align-items: center;
		padding: 2px 8px;
		font-size: var(--font-size-xs);
		color: #b45309;
		background: var(--warning-soft);
		border-radius: var(--radius-sm);
		white-space: nowrap;
	}
	details {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
		background: var(--surface-1);
	}
	details summary {
		cursor: pointer;
		color: var(--muted-strong);
		font-weight: 700;
	}
	.scene-placeholder {
		position: relative;
		height: 360px;
		background: linear-gradient(180deg, var(--surface-2), var(--surface-1));
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.floor-band { position: absolute; left: 6%; right: 6%; top: 46%; height: 24%; background: #f4f6f3; border: 1px solid #c6ccc3; }
	.glass-panel { position: absolute; left: 44%; top: 18%; width: 9%; height: 66%; border: 2px solid var(--tool-glass); background: rgba(91, 183, 197, 0.16); }
	.goal-dot { position: absolute; right: 22%; top: 50%; width: 18px; height: 18px; border-radius: 50%; background: var(--tool-traversable); }
	.hazard-zone { position: absolute; left: 39%; top: 39%; width: 18%; height: 28%; border: 2px solid var(--tool-hazard); background: rgba(221, 122, 34, 0.18); }
	.map-grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 2px; height: 320px; }
	.map-grid div { background: #f7faf7; border: 1px solid #d6ddd4; }
	.map-grid .cell-obstacle { background: #1f2933; }
	.map-grid .cell-hazard { background: var(--tool-hazard); }
	.map-grid .cell-start { background: var(--tool-goal); }
	.map-grid .cell-goal { background: var(--tool-traversable); }
	.render-grid, .review-grid { display: grid; grid-template-columns: 0.8fr 1fr 1fr; gap: var(--space-4); }
	.modality-list { display: grid; gap: var(--space-2); margin-top: var(--space-3); }
	.modality-list label { grid-template-columns: auto 1fr; align-items: center; color: var(--text); }
	.modality-list label.disabled { opacity: 0.45; }
	.segmented { display: grid; grid-template-columns: 1fr 1fr; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); overflow: hidden; }
	.segmented button { border: 0; padding: var(--space-2); background: var(--surface-1); color: var(--muted-strong); }
	.segmented button.active { background: var(--brand-soft); color: var(--brand-strong); }
	.full { width: 100%; }
	.log-list, .empty, .metric-row { display: grid; gap: var(--space-2); margin-top: var(--space-3); color: var(--muted-strong); }
	tr.active-row { background: var(--brand-soft); }
	.scene-select { flex: 1; min-width: 0; padding: 2px 6px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--panel); color: var(--text); font-size: 0.85rem; }
	.button-icon { padding: 2px 7px; font-size: 1rem; line-height: 1; min-width: unset; }
	.metric-row { grid-template-columns: repeat(3, 1fr); }
	.metric-row span { padding: var(--space-2); border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-1); }
	.notice { border-radius: var(--radius-sm); padding: var(--space-2) var(--space-3); }
	.notice.error { background: var(--danger-soft); color: var(--danger); border: 1px solid #f0b4b4; }
	.notice.ok { background: var(--tool-traversable-soft); color: var(--tool-traversable); border: 1px solid var(--tool-traversable); }
	pre {
		max-height: 360px;
		overflow: auto;
		padding: var(--space-3);
		border-radius: var(--radius-sm);
		border: 1px solid var(--panel-border);
		background: var(--surface-1);
		font-size: var(--font-size-xs);
	}
	.episode-json pre { max-height: 620px; }
	.preview-tile { min-height: 64px; display: grid; place-items: center; border: 1px solid var(--panel-border); background: var(--surface-1); border-radius: var(--radius-sm); color: var(--muted-strong); }
	.timestep-preview { display: grid; gap: var(--space-2); align-content: start; }
	.table tr { cursor: pointer; }
	.dataset-rail {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-3);
		color: var(--text);
	}
	.rail-tabbar {
		position: sticky;
		top: 0;
		z-index: 2;
		display: flex;
		flex-wrap: nowrap;
		gap: 2px;
		overflow-x: auto;
		padding: 0 0 1px;
		border-bottom: 1px solid var(--panel-border);
		background: var(--surface-1);
	}
	.rail-tabbar button {
		flex: 1 0 68px;
		min-width: 64px;
		border: 1px solid var(--panel-border);
		border-bottom: 0;
		border-radius: 8px 8px 0 0;
		background: var(--surface-2);
		color: var(--text-muted);
		padding: 5px 8px 6px;
		font-size: 11px;
		font-weight: 400;
		cursor: pointer;
		white-space: nowrap;
	}
	.rail-tabbar button.active {
		border-color: var(--brand);
		background: var(--surface-1);
		color: var(--brand);
		box-shadow: inset 0 2px 0 var(--brand);
	}
	.rail-tabbar button:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.rail-tool-panel {
		display: grid;
		gap: var(--space-2);
		align-content: start;
	}


	.dataset-rail .inspector-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-2);
	}
	.dataset-rail .inspector-id {
		color: var(--text-muted);
		font-family: monospace;
		font-size: var(--font-size-xs);
		overflow-wrap: anywhere;
	}
	.dataset-rail .inspector-badges,
	.dataset-rail .preset-row {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}
	.dataset-rail .inspector-badges span {
		padding: 1px 6px;
		background: var(--hover-bg);
		border-radius: 99px;
		color: var(--text-muted);
		font-size: 10px;
	}
	.dataset-rail .inspector-section {
		border-top: 1px solid var(--panel-border);
		padding-top: var(--space-2);
	}
	.dataset-rail .geometry-advanced summary {
		cursor: pointer;
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
		font-weight: 800;
	}
	.dataset-rail .flag-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 4px;
		font-size: var(--font-size-xs);
	}
	.dataset-rail .geometry-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 4px;
	}
	.dataset-rail .rotation-row { margin-top: 2px; }
	.dataset-rail .snap-controls { margin-top: 4px; gap: 4px; }
	.dataset-rail button.full { width: 100%; }
	.dataset-rail button.danger {
		color: var(--danger);
		border-color: #fca5a5;
	}
	.dataset-rail button.danger:hover { background: var(--danger-soft); }
	.dataset-rail .material-grid-browser {
		grid-template-columns: minmax(0, 1fr);
		gap: 8px;
	}
	.dataset-rail .material-picker-top {
		grid-template-columns: minmax(0, 1fr);
	}
	.dataset-rail .material-category-tabs {
		flex-wrap: wrap;
		overflow-x: visible;
	}
	.dataset-rail .material-category-tabs button {
		flex: 1 0 auto;
		padding: 5px 7px;
		font-size: 10px;
	}
	.dataset-rail .material-preview-panel {
		order: -1;
		grid-template-columns: 116px minmax(0, 1fr);
		align-items: start;
	}
	.dataset-rail .material-large-preview,
	.dataset-rail .material-large-empty {
		grid-row: 1 / span 4;
		aspect-ratio: 1 / 1;
	}
	.dataset-rail .material-preview-panel h3 {
		font-size: 14px;
	}
	.dataset-rail .material-preview-panel p {
		white-space: normal;
	}
	.dataset-rail .material-metadata {
		grid-column: 1 / -1;
	}
	.dataset-rail .material-action-row {
		grid-column: 1 / -1;
	}
	.dataset-rail .material-card-grid {
		grid-template-columns: repeat(2, minmax(0, 1fr));
		max-height: 520px;
	}
	.dataset-rail .material-card-grid button {
		grid-template-rows: 64px auto auto auto;
	}
	.dataset-rail .material-card-grid img,
	.dataset-rail .material-card-grid .material-empty-thumb {
		height: 64px;
	}
	.rail-section {
		border-bottom: 1px solid var(--panel-border);
		padding-bottom: var(--space-3);
	}
	.rail-section:last-child { border-bottom: 0; }
	.rail-title {
		margin-bottom: var(--space-2);
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0;
	}


	@keyframes pulse-cell {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}


	@media (max-width: 1100px) {
		.project-strip, .tab-grid, .render-grid, .review-grid { grid-template-columns: 1fr; }
		.page-header { align-items: flex-start; flex-direction: column; }
		.map-start-card { align-items: stretch; flex-direction: column; }
		.dataset-bottom-body { grid-template-columns: 1fr; }
		.bottom-progress { border-right: 0; border-bottom: 1px solid var(--panel-border); padding-right: 0; padding-bottom: var(--space-3); }
		.activity-row { grid-template-columns: 70px 120px minmax(0, 1fr); }
		.activity-detail { grid-column: 3; }
	}

	/* ── 3D map editor full-bleed layout ─────────────────────────────── */
	.map-editor-fullbleed {
		position: relative;
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		flex-direction: column;
		border-radius: var(--radius-md);
		overflow: hidden;
		background: #f1f5f9;
	}

	/* Floating top bar */
	.map-float-top {
		position: absolute;
		top: 10px;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 10px;
		background: rgba(255, 255, 255, 0.92);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		backdrop-filter: blur(10px);
		z-index: 10;
		box-shadow: 0 1px 4px rgba(0,0,0,0.08);
		white-space: nowrap;
	}
	.map-float-modes {
		display: flex;
		gap: 2px;
	}
	.map-float-modes button {
		padding: 3px 10px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: transparent;
		font-size: var(--font-size-xs);
		cursor: pointer;
		color: var(--text-muted);
	}
	.map-float-modes button.active {
		background: var(--brand);
		border-color: var(--brand);
		color: #fff;
	}
	.map-float-btn {
		width: 28px;
		height: 28px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: transparent;
		cursor: pointer;
		font-size: 14px;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--text);
	}
	.map-float-btn:disabled { opacity: 0.35; cursor: default; }
	.map-float-btn:hover:not(:disabled) { background: var(--hover-bg); }
	.map-float-sep {
		width: 1px;
		height: 20px;
		background: var(--panel-border);
		margin: 0 2px;
	}
	.map-float-hint {
		font-size: var(--font-size-xs);
		color: var(--text-muted);
		padding-left: 4px;
	}


	.pgroup-sep {
		width: 24px;
		height: 1px;
		background: var(--panel-border);
		margin: 2px 0;
	}

	/* Floating right inspector */
	.map-float-inspector {
		position: absolute;
		top: 54px;
		right: 10px;
		width: 260px;
		max-height: calc(100% - 80px);
		overflow-y: auto;
		background: rgba(255, 255, 255, 0.95);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		padding: var(--space-3);
		backdrop-filter: blur(10px);
		z-index: 10;
		box-shadow: 0 2px 8px rgba(0,0,0,0.1);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.map-float-inspector.material-panel {
		width: min(720px, calc(100% - 24px));
	}


	.readiness-errors { margin-top: 4px; display: flex; flex-direction: column; gap: 3px; }
	.readiness-error-item { font-size: 11px; color: var(--danger); line-height: 1.4; }
	.readiness-error-label { font-weight: 600; margin-right: 4px; }
	.readiness-error-msg { color: #7f1d1d; }


	.export-validation { font-size: 11px; padding: 4px 8px; border-radius: 4px; margin-top: 6px; }
	.export-validation.validation-ok { background: #dcfce7; color: #166534; }
	.export-validation.validation-fail { background: #fee2e2; color: #991b1b; }
	.val-errors { opacity: 0.8; }


	/* Floating bottom status bar */
	.map-float-status {
		position: absolute;
		bottom: 10px;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 12px;
		background: rgba(255, 255, 255, 0.88);
		border: 1px solid var(--panel-border);
		border-radius: 99px;
		backdrop-filter: blur(8px);
		z-index: 10;
		font-size: var(--font-size-xs);
		color: var(--text-muted);
		box-shadow: 0 1px 4px rgba(0,0,0,0.06);
		white-space: nowrap;
	}
	.map-float-status label {
		display: flex;
		align-items: center;
		gap: 3px;
		cursor: pointer;
		color: var(--text-muted);
	}
	.map-status-sep {
		width: 1px;
		height: 14px;
		background: var(--panel-border);
	}
	.map-status-undo {
		color: var(--brand);
		font-weight: 600;
	}

	/* Project badge in top bar */
	.map-proj-badge {
		font-size: var(--font-size-xs);
		font-weight: 600;
		color: var(--text);
		padding: 2px 8px;
		background: var(--hover-bg);
		border-radius: 99px;
		border: 1px solid var(--panel-border);
		max-width: 140px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* Tab navigation in top bar */
	.map-float-tabnav {
		padding: 3px 10px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: transparent;
		font-size: var(--font-size-xs);
		cursor: pointer;
		color: var(--text-muted);
	}
	.map-float-tabnav:hover { background: var(--hover-bg); color: var(--text); }

	/* Floating ⚙ scene settings */
	.map-float-settings {
		position: absolute;
		top: 10px;
		right: 10px;
		z-index: 10;
	}
	/* Paths panel: offset left from scene panel */
	.map-float-paths {
		right: calc(10px + 80px + 8px); /* 80px scene button width + 8px gap */
	}
	.map-float-settings > summary {
		padding: 4px 10px;
		background: rgba(255, 255, 255, 0.92);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		backdrop-filter: blur(10px);
		cursor: pointer;
		font-size: var(--font-size-xs);
		color: var(--text-muted);
		list-style: none;
		user-select: none;
		box-shadow: 0 1px 4px rgba(0,0,0,0.08);
	}
	.map-float-settings > summary::-webkit-details-marker { display: none; }
	.map-settings-body {
		margin-top: 4px;
		width: 280px;
		max-height: 60vh;
		overflow-y: auto;
		background: rgba(255, 255, 255, 0.97);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		padding: var(--space-3);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		box-shadow: 0 4px 12px rgba(0,0,0,0.1);
	}

	.map-float-inspector,
	.map-float-settings {
		display: none;
	}

	/* Start card (centered overlay) */
	.map-start-card {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		z-index: 5;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-4);
		border: 1px solid #bfdbfe;
		border-radius: var(--radius-md);
		background: rgba(239, 246, 255, 0.96);
		color: #1e3a8a;
		text-align: center;
		backdrop-filter: blur(6px);
		max-width: 340px;
	}
	.map-start-card strong {
		display: block;
		font-size: var(--font-size-sm);
	}
	.map-start-card span {
		display: block;
		margin-top: 2px;
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}

	/* Path status chips */
	.path-status-chips {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}
	.path-status-chips span {
		padding: 2px 7px;
		border-radius: 99px;
		font-size: 10px;
		font-weight: 500;
	}
	.chip-ok { background: #dcfce7; color: #166534; }
	.chip-off { background: #f1f5f9; color: var(--muted); }
	.chip-warn { background: var(--warning-soft); color: var(--tool-hazard); padding: 1px 7px; border-radius: 99px; font-size: 10px; font-weight: 500; }
	.config-scene-ref { font-size: 10px; color: var(--muted-strong); padding: 2px 4px; background: #f1f5f9; border-radius: 4px; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; margin: 2px 0; }
	.config-scene-error { color: var(--danger); background: var(--danger-soft); }
	.chip-dim { background: #f1f5f9; color: var(--muted-strong); padding: 1px 7px; border-radius: 99px; font-size: 10px; font-weight: 500; }
	.hint-row { font-size: 11px; color: var(--muted-strong); background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px 8px; margin: 4px 0; }
	.render-geometry-panel { margin-top: 8px; padding: 8px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 11px; color: #334155; }
	.render-geometry-header { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
	.render-geometry-title { font-size: 11px; font-weight: 600; color: #1e293b; text-transform: uppercase; letter-spacing: 0.04em; }
	.render-geometry-chip { padding: 1px 7px; border-radius: 99px; font-size: 10px; font-weight: 500; }
	.render-geometry-chip-ok { background: #dcfce7; color: #166534; }
	.render-geometry-chip-warn { background: var(--warning-soft); color: var(--tool-hazard); }
	.render-geometry-chip-dim { background: #f1f5f9; color: var(--muted-strong); }
	.render-geometry-breakdown { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
	.render-geometry-reason { font-size: 10px; color: var(--muted-strong); background: #fff; padding: 1px 6px; border-radius: 4px; border: 1px solid #e2e8f0; }
	.render-geometry-fallbacks { margin-top: 6px; }
	.render-geometry-fallbacks summary { cursor: pointer; font-size: 11px; color: var(--muted-strong); }
	.render-geometry-fallbacks ul { list-style: none; padding: 4px 0 0 0; margin: 0; max-height: 220px; overflow: auto; }
	.render-geometry-fallbacks li { padding: 3px 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
	.render-geometry-fallbacks li small { font-size: 10px; color: var(--muted); word-break: break-all; }
	.link-button { background: none; border: none; cursor: pointer; padding: 0; color: #1d4ed8; font-size: 11px; text-decoration: underline; }
	.xml-native-preview-toggle { display: flex; align-items: flex-start; gap: 8px; margin-top: 8px; padding: 6px; background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; cursor: pointer; font-size: 12px; }
	.xml-native-preview-toggle > span { display: flex; flex-direction: column; gap: 1px; }
	.xml-native-preview-toggle strong { font-size: 12px; font-weight: 600; color: #1e293b; }
	.xml-native-preview-toggle small { font-size: 11px; color: #64748b; font-weight: 400; }
	.env-section { padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
	.env-section:last-child { border-bottom: none; }
	.env-section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--muted-strong); letter-spacing: 0.04em; margin-bottom: 6px; }
	.env-radio-row { display: flex; gap: 16px; margin-bottom: 8px; }
	.env-radio { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
	.env-fields-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }
	.env-fields-grid label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
	.env-fields-grid label span { color: var(--muted-strong); font-size: 11px; }
	.env-envmap-row { display: flex; gap: 8px; margin-bottom: 8px; }
	.env-envmap-select { flex: 1; min-width: 0; }
	.env-upload-button { position: relative; display: inline-flex; align-items: center; padding: 4px 10px; background: #e2e8f0; border-radius: 6px; font-size: 12px; cursor: pointer; white-space: nowrap; }
	.env-upload-button input[type="file"] { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
	.env-envmap-preview { display: flex; gap: 8px; align-items: center; padding: 6px; background: #f8fafc; border-radius: 6px; margin-bottom: 8px; }
	.env-envmap-preview img { width: 120px; height: 60px; object-fit: cover; border-radius: 4px; background: #1e293b; }
	.env-envmap-placeholder { width: 120px; height: 60px; display: flex; align-items: center; justify-content: center; font-size: 10px; color: var(--muted-strong); background: #e2e8f0; border-radius: 4px; text-align: center; padding: 4px; }
	.env-envmap-meta { flex: 1; min-width: 0; }
	.env-envmap-filename { font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.env-envmap-sub { font-size: 11px; color: var(--muted-strong); }
	.inline-check { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; cursor: pointer; }


	.env-toggle-sub { font-size: 11px; color: var(--muted-strong); font-weight: 400; }
	.translate-layout { display: flex; flex-direction: column; gap: var(--space-1); margin-top: var(--space-2); padding-top: var(--space-2); border-top: 1px solid var(--border-subtle, rgba(148,163,184,0.25)); }
	.translate-layout-title { font-size: 12px; font-weight: 600; color: var(--muted-strong); }
	.translate-layout-sub { font-size: 11px; color: var(--muted-strong); font-weight: 400; }
	.inline-check input[type="checkbox"] { flex: 0 0 auto; }
	.build-result-row { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; align-items: center; }
	.spinner-xs {
		display: inline-block;
		width: 10px; height: 10px;
		border: 2px solid currentColor;
		border-top-color: transparent;
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
		vertical-align: middle;
	}
	@keyframes spin { to { transform: rotate(360deg); } }
	.mt-1 { margin-top: 4px; }

	/* Inspector inside floating panel */
	.map-float-inspector .inspector-head { display: flex; justify-content: space-between; align-items: flex-start; }
	.map-float-inspector .inspector-id { font-size: var(--font-size-xs); color: var(--text-muted); font-family: monospace; }
	.map-float-inspector .inspector-badges { display: flex; gap: 4px; flex-wrap: wrap; }
	.map-float-inspector .inspector-badges span {
		padding: 1px 6px;
		background: var(--hover-bg);
		border-radius: 99px;
		font-size: 10px;
		color: var(--text-muted);
	}
	.map-float-inspector .inspector-section { border-top: 1px solid var(--panel-border); padding-top: var(--space-2); }
	.map-float-inspector .geometry-advanced summary {
		cursor: pointer;
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
		font-weight: 800;
	}
	.map-float-inspector .flag-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; font-size: var(--font-size-xs); }
	.map-float-inspector .preset-row { display: flex; gap: 4px; flex-wrap: wrap; }
	.map-float-inspector .rotation-row { margin-top: 2px; }
	.map-float-inspector .snap-controls { margin-top: 4px; gap: 4px; }
	.map-float-inspector .geometry-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
	.map-float-inspector button.full { width: 100%; }
	.map-float-inspector button.danger { color: var(--danger); border-color: #fca5a5; }
	.map-float-inspector button.danger:hover { background: var(--danger-soft); }

	}
</style>
