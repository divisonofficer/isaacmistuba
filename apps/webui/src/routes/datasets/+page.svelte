<script lang="ts">
	import { onMount } from 'svelte';
	import AssetThumb3D from '$lib/AssetThumb3D.svelte';
	import MapEditor3D from '$lib/MapEditor3D.svelte';
	import {
		builtInBuildAssets,
		builtInPlaceAssetGroups,
		builtInRichPlaceAssets,
		type BuiltInPlaceAsset
	} from '$lib/opticalnavBuiltInAssets';
	import { sceneBottomSnippet, sceneRailSnippet } from '$lib/stores/scenePortals';
	import { bottomPanelCollapsed, toggleBottomPanel } from '$lib/stores/shell';
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
		getOpticalNavRoomShell,
		addOpticalNavGraphNode,
		deleteOpticalNavGraphNode,
		getOpticalNavWalkabilityOverlay,
		paintOpticalNavWalkabilityOverlay,
		clearOpticalNavWalkabilityOverlay,
		opticalNavWalkabilityOverlayPngUrl,
		getOpticalNavTraversableGridMeta,
		opticalNavTraversableGridPngUrl,
		checkOpticalNavGraphEdge,
		regenerateOpticalNavGraphRegion,
		addOpticalNavGraphEdge,
		deleteOpticalNavGraphEdge,
		opticalNavObservationRgbUrl,
		opticalNavObservationModalityUrl,
		getJobLog,
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
	const materialPresetIds = ['painted_wall', 'clear_glass', 'frosted_glass', 'mirror', 'wood', 'fabric', 'tile'];
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
	let globalCameraRig = $state<CameraRig | null>(null);
	let globalCameraRigStatus = $state('Camera rig preset not loaded.');
	let globalCameraRigError = $state('');
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
	// ─── Render Probe (Preview tab) ─────────────────────────────────────────
	type ProbeMode = 'selected' | 'free' | 'editor_view' | 'isaac_view';
	let probeMode = $state<ProbeMode>('selected');
	let freeProbe = $state({ x: 0, z: 0, yaw_deg: 0, height_m: 1.0 });
	let editorViewProbe = $state<{ x: number; z: number; yaw_deg: number; height_m: number } | null>(null);
	let probeRendering = $state(false);
	let probeResult = $state<{ batch_id: string; vp_id: string; heading_id: string; modality: string; sensor_id?: string; submittedAt: number } | null>(null);
	let probeError = $state('');
	let renderSceneStats = $state<any>(null);
	let renderSceneStatsLoading = $state(false);
	let roomShell = $state<any>(null);
	let showRoomShell = $state(true);
	let syncProgress = $state<{ processed: number; total: number; label: string; stage: string } | null>(null);
	let syncRunning = $state(false);
	async function refreshRoomShell() {
		if (!selectedProjectId || !sceneId) { roomShell = null; return; }
		try {
			const res = await getOpticalNavRoomShell(selectedProjectId, sceneId);
			roomShell = res?.room_shell ?? null;
		} catch (err) { roomShell = null; }
	}
	$effect(() => {
		if (selectedProjectId && sceneId) refreshRoomShell();
	});
	async function refreshRenderSceneStats() {
		if (!selectedProjectId || !sceneId) return;
		renderSceneStatsLoading = true;
		try {
			renderSceneStats = await getOpticalNavRenderSceneStats(selectedProjectId, sceneId);
		} catch (err) {
			renderSceneStats = { exists: false, error: errorMessage(err) };
		} finally {
			renderSceneStatsLoading = false;
		}
	}
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
	// Auto-expand map bounds when USD geometry loads
	$effect(() => {
		const b = editorGeometryPayload?.bounds;
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
	let renderSplit = $state('train');
	let maxNodes = $state(300);
	let minClearance = $state(0.1);
	let showFootprint = $state(false);
	// Single source of truth for map-click interaction. Only one mode at a time.
	type PathsInteractionMode = 'select' | 'place_node' | 'paint_walkable' | 'paint_blocked' | 'paint_erase' | 'select_region' | 'add_edge' | 'inspect_edge';
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
	// Reset pending selections whenever the mode changes — avoids stale state.
	$effect(() => {
		pathsMode;
		pendingEdgeSource = '';
		edgeInspectorSource = '';
		pendingRegionBbox = null;
		edgeCheckResult = null;
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
			traversableMeta = await getOpticalNavTraversableGridMeta(selectedProjectId, sceneId, Number(robotRadius));
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
			const res = await checkOpticalNavGraphEdge(selectedProjectId, sceneId, {
				source, target,
				robot_radius_m: Number(robotRadius),
				max_edge_length_m: Number(maxEdgeLength),
			});
			edgeCheckResult = res;
		} catch (err) {
			pushActivity('error', 'edge:inspect', errorMessage(err));
		}
	}
	async function addEdgeAnyway() {
		if (!edgeCheckResult?.source || !edgeCheckResult?.target) return;
		try {
			await addOpticalNavGraphEdge(selectedProjectId, sceneId, { source: edgeCheckResult.source, target: edgeCheckResult.target });
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
	let selectedBatchJobLog = $state<any[]>([]);
	let selectedBatchJobLoading = $state(false);
	let validationReport = $state<any>(null);
	let evaluationReport = $state<any>(null);
	let exportResult = $state<any>(null);
	let mapResult = $state<any>(null);
	let buildingMap = $state(false);
	let planResult = $state<any>(null);
	let graphResult = $state<any>(null);
	let buildingGraph = $state(false);
	let graphBuildProgress = $state<{ stage: string; progress: number; status: string } | null>(null);
	let graphRebuildConfirmOpen = $state(false);
	let graphPayload = $state<any>(null);
	let editor3DStatus = $state('');
	let editorGeometryPayload = $state<any>(null);
	let editorGeometryCatalogStatus = $state('USD asset catalog not loaded.');
	let editorGeometryCatalogKey = '';
	let editorGeometryRefreshToken = $state(0);
	let assetThumbRefreshTick = $state(0);
	let selectedUsdAssetId = $state('');
	let mapAssets = $state<any[]>([]);
	let mapAssetStatus = $state('No library assets loaded.');
	let usdCandidates = $state<any[]>([]);
	let selectedMoorelaneUsdRef = $state('');
	let usdCandidateStatus = $state('USD candidates not loaded.');
	let materialGroups = $state<any[]>([]);
	let materialLibraryStatus = $state('Material library not loaded.');
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
	let envmapFiles = $state<any[]>([]);
	let envmapUploading = $state(false);
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
		| { type: 'point'; x: number; y: number; valid: boolean; sourcePath?: string; assetCat?: string; normalizedYMin?: number };
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
	const renderReadinessOk = $derived(Boolean(effectiveRenderReadiness?.ok ?? (currentScene?.sync_status?.render_scene === 'synced')));
	// After Phase 3 migration, PUT /authoring-map regenerates XML automatically.
	// renderSceneSynced is true whenever render_readiness is OK — no separate sync needed.
	const renderSceneSynced = $derived(renderReadinessOk || (currentScene?.sync_status?.render_scene === 'synced'));
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
		const sensors = ((globalCameraRig?.sensors?.length
			? globalCameraRig.sensors.map((sensor) => legacySensorFromCameraRigSensor(sensor))
			: authoringMap?.camera_rig?.sensors?.length
				? authoringMap.camera_rig.sensors
				: makeStarterAuthoringMap().camera_rig.sensors) ?? []) as any[];
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
	$effect(() => {
		if (!rigSensorOptions.length) return;
		const selected = rigSensorOptions.find((item: any) => item.sensor_id === activeRigSensorId) ?? rigSensorOptions[0];
		if (!selected) return;
		if (activeRigSensorId !== selected.sensor_id) activeRigSensorId = selected.sensor_id;
		if (activeModalityTab !== selected.render_modality) activeModalityTab = selected.render_modality;
	});
	/** Active rig sensor mount height. Used as default before per-viewpoint overrides. */
	const rigMountHeightM = $derived<number>(
		sensorMountHeight(activeRigSensorOption?.sensor ?? (globalCameraRig?.sensors?.[0] ? legacySensorFromCameraRigSensor(globalCameraRig.sensors[0]) : authoringMap?.camera_rig?.sensors?.[0])) || cameraHeightM
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
	const selectedMaterialInfo = $derived(materialInfo(selectedAuthoringItem?.material));
	const materialCards = $derived(buildMaterialCards());
	const materialCollections = $derived(
		[...new Map(materialCards.filter((item: any) => item.collection !== 'preset').map((item: any) => [item.collection, item.collectionLabel])).entries()]
	);
	const filteredMaterialCards = $derived(filterMaterialCards(materialCards, selectedAuthoringItem));
	const materialPreviewEntry = $derived(
		materialCards.find((item: any) => item.value === (materialPreviewValue || selectedAuthoringItem?.material))
		?? filteredMaterialCards[0]
		?? materialCards[0]
		?? null
	);
	const LIBRARY_DISPLAY_LIMIT = 40;
	let usdCatalogSearch = $state('');
	const usdAssetSelectionPool = $derived([...builtInRichPlaceAssets, ...mapAssets]);
	const usdAssetCandidatesAll = $derived.by(() => {
		const all = mapAssets;
		if (!usdCatalogSearch.trim()) return all;
		const q = usdCatalogSearch.toLowerCase();
		return all.filter((item: any) =>
			usdAssetLabel(item).toLowerCase().includes(q) ||
			(item.category ?? '').toLowerCase().includes(q) ||
			(item.source_path ?? '').toLowerCase().includes(q) ||
			(item.tags ?? []).join(' ').toLowerCase().includes(q)
		);
	});
	// Cap at LIBRARY_DISPLAY_LIMIT when no search to avoid WebGL context flood
	const usdAssetCandidates = $derived(
		usdCatalogSearch.trim() ? usdAssetCandidatesAll : usdAssetCandidatesAll.slice(0, LIBRARY_DISPLAY_LIMIT)
	);
	const selectedUsdAsset = $derived(usdAssetSelectionPool.find((item: any) => (item.asset_id ?? item.id) === selectedUsdAssetId) ?? usdAssetCandidatesAll[0] ?? null);
	const authoringSummary = $derived({
		objects: authoringObjects.length,
		regions: authoringRegions.length,
		glass: authoringObjects.filter((item: any) => item.type === 'glass_wall').length,
		goals: authoringRegions.filter((item: any) => item.type === 'goal').length,
		traversable: authoringRegions.filter((item: any) => item.type === 'traversable').length
	});
	const hasAuthoringContent = $derived(authoringSummary.objects + authoringSummary.regions > 0);
	const activeBatch = $derived(renderMode === 'graph_sweep' ? graphBatch : renderBatch);
	const bottomProgress = $derived(activeBatch?.progress ?? null);
	const batchJobGrid = $derived(buildBatchJobGrid(activeBatch));
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
	const currentReadiness = $derived(readinessState());

	function _mergeIntoBatch(existing: any, incoming: any): any {
		const jobMap = new Map<string, any>();
		for (const j of existing?.jobs ?? []) jobMap.set(j.job_id, j);
		for (const j of incoming?.jobs ?? []) jobMap.set(j.job_id, j);
		const jobs = [...jobMap.values()];
		const counts: Record<string, number> = { queued: 0, running: 0, completed: 0, failed: 0, cancelled: 0, unknown: 0 };
		for (const j of jobs) {
			const s = String(j?.status?.status ?? j?.status ?? 'unknown');
			counts[s] = (counts[s] ?? 0) + 1;
		}
		const total = Math.max(1, jobs.length);
		return {
			...(incoming ?? existing ?? {}),
			jobs,
			counts,
			progress: { completed: counts.completed, failed: counts.failed, total: jobs.length, fraction: (counts.completed + counts.failed) / total }
		};
	}

	function buildBatchJobGrid(batch: any) {
		const jobs: any[] = batch?.jobs ?? [];
		if (!jobs.length) return { rows: [], headings: [] as string[], counts: {} as Record<string, number> };
		const headingSet = new Set<string>();
		const nodeMap = new Map<string, Map<string, any>>();
		for (const job of jobs) {
			const nid = String(job.node_id ?? job.job_id ?? '');
			const hid = String(job.heading_id ?? '');
			headingSet.add(hid);
			if (!nodeMap.has(nid)) nodeMap.set(nid, new Map());
			nodeMap.get(nid)!.set(hid, job);
		}
		const headings = [...headingSet].sort();
		const rows = [...nodeMap.entries()].map(([nid, hMap]) => ({ nid, cells: headings.map(h => hMap.get(h) ?? null) }));
		return { rows, headings, counts: (batch?.counts ?? {}) as Record<string, number> };
	}

	function jobStatusClass(job: any): string {
		const s = String(job?.status?.status ?? job?.status ?? 'unknown');
		if (s === 'completed') return 'js-done';
		if (s === 'running') return 'js-running';
		if (s === 'failed') return 'js-failed';
		if (s === 'cancelled') return 'js-cancelled';
		if (s === 'queued') return 'js-queued';
		return 'js-unknown';
	}

	function jobStageLabel(job: any): string {
		return String(job?.status?.progress_stage ?? job?.status?.status ?? '');
	}

	const RENDER_STAGES = [
		{ key: 'queued',           label: '대기' },
		{ key: 'staging_scene',    label: 'XML 준비' },
		{ key: 'loading_scene',    label: 'GPU 로드' },
		{ key: 'rendering',        label: '렌더링' },
		{ key: 'saving_output',    label: 'EXR 저장' },
		{ key: 'writing_manifest', label: '매니페스트' },
		{ key: 'complete',         label: '완료' },
	];

	function stageIndex(job: any): number {
		const stage = jobStageLabel(job);
		const s = String(job?.status?.status ?? '');
		if (s === 'succeeded') return RENDER_STAGES.length - 1;
		if (s === 'failed' || s === 'cancelled') return -1;
		const idx = RENDER_STAGES.findIndex(r => r.key === stage);
		return idx >= 0 ? idx : 0;
	}

	const selectedBatchJob = $derived(
		selectedBatchJobId
			? (activeBatch?.jobs ?? []).find((j: any) => j.job_id === selectedBatchJobId) ?? null
			: null
	);

	async function selectBatchJob(job: any) {
		if (!job?.job_id) return;
		selectedBatchJobId = job.job_id;
		selectedBatchJobLog = [];
		selectedBatchJobLoading = true;
		try {
			const data = await getJobLog(job.job_id, 200);
			selectedBatchJobLog = Array.isArray(data?.entries) ? data.entries : (Array.isArray(data) ? data : []);
		} catch {
			selectedBatchJobLog = [];
		} finally {
			selectedBatchJobLoading = false;
		}
	}

	async function cancelStaleBatchJobs() {
		const jobs: any[] = activeBatch?.jobs ?? [];
		const stale = jobs.filter((j: any) => {
			const s = String(j?.status?.status ?? '');
			return s === 'running' || s === 'queued' || s === 'pending';
		});
		if (!stale.length) { pushActivity('info', 'batch', 'No stale jobs to cancel.'); return; }
		let cancelled = 0;
		for (const j of stale) {
			try { await cancelJob(j.job_id); cancelled++; } catch { /* best-effort */ }
		}
		pushActivity('ok', 'batch', `Cancelled ${cancelled} stale job(s).`);
		await refreshBatch();
	}

	function progressPercent(progress: any) {
		const total = Number(progress?.total ?? 0);
		const completed = Number(progress?.completed ?? 0);
		if (!total) return 0;
		return Math.max(0, Math.min(100, Math.round((completed / total) * 100)));
	}

	function compactDetail(text?: string) {
		if (!text) return '';
		return text.length > 180 ? `${text.slice(0, 180)}...` : text;
	}

	function errorMessage(err: unknown) {
		const payload = typeof err === 'object' && err !== null ? (err as any).payload : null;
		if (payload && typeof payload === 'object') {
			return String((payload as any).message ?? (payload as any).error ?? (err instanceof Error ? err.message : 'Request failed'));
		}
		return err instanceof Error ? err.message : String(err);
	}

	function errorPayload(err: unknown) {
		return typeof err === 'object' && err !== null && 'payload' in err ? (err as any).payload : undefined;
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

	function makeStarterAuthoringMap() {
		return {
			version: 'opticalnav-authoring-map-v0.2',
			scene_id: sceneId,
			unit: 'meter',
			floorplan_ref: `/api/scenes/${sceneId}/floorplan`,
			objects: [],
			regions: [],
			environment: {
				mode: 'constant',
				radiance: [0.8, 0.8, 0.85],
				intensity: 1.0,
				rotation_deg: 0,
				background_visible: true
			},
			camera_rig: {
				rig_id: 'mobile_base_default',
				base_frame: 'base_link',
				sensors: [
					{ sensor_id: 'rgb_front', label: 'RGB Front', modality: 'rgb', mount: { xyz_m: [0.18, 1.0, 0.0], rpy_deg: [0, 0, 0] }, fov_deg: 70, resolution: [1280, 720], clip_range: [0.05, 80], sensor_sync_group: 'default', calibration_ref: null },
					{ sensor_id: 'nir_front', label: 'NIR Front', modality: 'nir', mount: { xyz_m: [0.16, 0.98, 0.04], rpy_deg: [0, 0, 0] }, fov_deg: 70, resolution: [1280, 720], clip_range: [0.05, 80], sensor_sync_group: 'default', calibration_ref: null, active_emitter: { wavelength_nm: 850, power: 1.0 } },
					{ sensor_id: 'pol_front', label: 'Polarization Front', modality: 'polarization', mount: { xyz_m: [0.16, 1.02, -0.04], rpy_deg: [0, 0, 0] }, fov_deg: 70, resolution: [1280, 720], clip_range: [0.05, 80], sensor_sync_group: 'default', calibration_ref: null }
				]
			},
			materials: [
				{ material_id: 'clear_glass', category: 'transparent', render_binding: { kind: 'preset', bsdf_strategy: 'dielectric', capabilities: { rgb: true, nir: true, polarization: true } } },
				{ material_id: 'mirror', category: 'reflective', render_binding: { kind: 'preset', bsdf_strategy: 'conductor', capabilities: { rgb: true, nir: true, polarization: true } } },
				{ material_id: 'painted_wall', category: 'opaque', render_binding: { kind: 'preset', bsdf_strategy: 'roughplastic', capabilities: { rgb: true, nir: true, polarization: false } } },
				{ material_id: 'wood', category: 'opaque', render_binding: { kind: 'preset', bsdf_strategy: 'roughplastic', capabilities: { rgb: true, nir: true, polarization: false } } }
			],
			settings: {
				grid_size_m: 0.25,
				default_wall_height_m: 2.4,
				default_wall_thickness_m: 0.08
			},
			metadata: {
				source: 'webui_map_editor'
			}
		};
	}

	function makeVisibleStarterAuthoringMap() {
		const base = makeStarterAuthoringMap();
		return {
			...base,
			objects: [
				{
					id: 'glass_wall_001',
					type: 'glass_wall',
					label: 'Glass wall',
					placement: 'line',
					geometry: {
						type: 'line',
						start: [2.25, 0.75],
						end: [2.25, 3.25],
						height_m: 2.4,
						thickness_m: 0.08
					},
					material: 'clear_glass',
					navigation: {
						blocks_navigation: true,
						hazard_type: 'transparent_obstacle',
						include_in_hazard_mask: true,
						instruction_candidate: true,
						goal_candidate: false
					},
					metadata: {
						created_by: 'webui_starter_overlay'
					}
				},
				{
					id: 'mirror_wall_001',
					type: 'mirror_wall',
					label: 'Mirror wall',
					placement: 'line',
					geometry: {
						type: 'line',
						start: [0.85, 3.35],
						end: [4.9, 3.35],
						height_m: 2.4,
						thickness_m: 0.08
					},
					material: 'mirror',
					navigation: {
						blocks_navigation: true,
						hazard_type: 'reflective_obstacle',
						include_in_hazard_mask: true,
						instruction_candidate: true,
						goal_candidate: false
					},
					metadata: {
						created_by: 'webui_starter_overlay'
					}
				}
			],
			regions: [
				{
					id: 'traversable_001',
					type: 'traversable',
					label: 'Main floor',
					placement: 'rectangle',
					geometry: { type: 'rectangle', bounds: [0.45, 0.45, 5.55, 3.55] },
					navigation: {
						blocks_navigation: false,
						hazard_type: null,
						include_in_hazard_mask: false,
						instruction_candidate: false,
						goal_candidate: false
					},
					metadata: {
						created_by: 'webui_starter_overlay'
					}
				},
				{
					id: 'goal_001',
					type: 'goal',
					label: 'Goal near table',
					placement: 'rectangle',
					geometry: { type: 'rectangle', bounds: [4.45, 1.15, 5.2, 1.85] },
					navigation: {
						blocks_navigation: false,
						hazard_type: null,
						include_in_hazard_mask: false,
						instruction_candidate: true,
						goal_candidate: true
					},
					metadata: {
						created_by: 'webui_starter_overlay'
					}
				}
			],
			metadata: {
				...base.metadata,
				starter_overlay: true
			}
		};
	}

	function createStarterOverlay() {
		setAuthoringMapPayload(makeVisibleStarterAuthoringMap());
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
		const starter = makeStarterAuthoringMap();
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

	function markAuthoringJsonDirty() {
		authoringMapDirty = true;
	}

	function clampMapNumber(value: unknown, axis: 'x' | 'y' | 'yaw' | 'positive', fallback = 0) {
		const numeric = Number(value);
		if (!Number.isFinite(numeric)) return fallback;
		if (axis === 'x') return Number(Math.max(0, Math.min(mapWidth, numeric)).toFixed(3));
		if (axis === 'y') return Number(Math.max(0, Math.min(mapHeight, numeric)).toFixed(3));
		if (axis === 'yaw') return Number((((numeric % 360) + 360) % 360).toFixed(1));
		return Number(Math.max(0.001, numeric).toFixed(3));
	}

	function replaceSelectedAuthoringItem(updater: (item: any) => any) {
		if (!authoringMap || !selectedAuthoringId) return;
		pushHistory();
		inspectorError = '';
		const objects = (authoringMap.objects ?? []).map((item: any) => (item.id === selectedAuthoringId ? updater(item) : item));
		const regions = (authoringMap.regions ?? []).map((item: any) => (item.id === selectedAuthoringId ? updater(item) : item));
		setAuthoringMapPayload({ ...authoringMap, objects, regions }, true);
	}

	function updateSelectedField(field: string, value: unknown) {
		replaceSelectedAuthoringItem((item) => ({ ...item, [field]: value }));
	}

	// Light-source detection: matches authoring_map.py's detect_emitter_candidates().
	const EMITTER_KEYWORD_RE = /light|lamp|bulb|lumin|fluoresc|fixture|emitter|illum|sconce|chandel|\bled\b/i;
	function objectLooksLikeEmitter(obj: any): boolean {
		const tokens = `${obj?.label ?? ''} ${obj?.source_ref ?? ''}`;
		return EMITTER_KEYWORD_RE.test(tokens);
	}
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
	/** Tanner Helland approximation. Returns linear RGB in [0,1] for the given Kelvin temperature.
	 *  Used by the Lights editor to convert a temperature slider into emitter_radiance.
	 */
	function kelvinToRgb(kelvin: number): [number, number, number] {
		const t = Math.max(1000, Math.min(40000, kelvin)) / 100;
		let r: number, g: number, b: number;
		if (t <= 66) {
			r = 255;
			g = Math.max(0, 99.4708025861 * Math.log(t) - 161.1195681661);
			b = t <= 19 ? 0 : Math.max(0, 138.5177312231 * Math.log(t - 10) - 305.0447927307);
		} else {
			r = Math.max(0, 329.698727446 * Math.pow(t - 60, -0.1332047592));
			g = Math.max(0, 288.1221695283 * Math.pow(t - 60, -0.0755148492));
			b = 255;
		}
		return [Math.min(255, r) / 255, Math.min(255, g) / 255, Math.min(255, b) / 255];
	}
	/** Inverse: derive Kelvin from an RGB ratio (used to seed the slider from stored emitter_radiance).
	 *  Quick lookup via 100-step scan — accuracy sufficient for UI slider sync. */
	function rgbToKelvinApprox(rgb: [number, number, number]): number {
		let best = 3000;
		let bestErr = Infinity;
		for (let k = 1500; k <= 10000; k += 100) {
			const ref = kelvinToRgb(k);
			const err = Math.abs(ref[0] - rgb[0]) + Math.abs(ref[1] - rgb[1]) + Math.abs(ref[2] - rgb[2]);
			if (err < bestErr) { bestErr = err; best = k; }
		}
		return best;
	}

	async function enableAllDetectedEmitters() {
		if (!authoringMap) return;
		const objects = (authoringMap.objects ?? []).map((o: any) =>
			detectedEmitterIds.has(o.id) && !o.is_emitter ? { ...o, is_emitter: true, emitter_intensity: o.emitter_intensity ?? 1.0 } : o
		);
		setAuthoringMapPayload({ ...authoringMap, objects }, true);
		await saveAuthoringMap();
	}
	async function disableAllEmitters() {
		if (!authoringMap) return;
		const objects = (authoringMap.objects ?? []).map((o: any) =>
			o.is_emitter ? { ...o, is_emitter: false } : o
		);
		setAuthoringMapPayload({ ...authoringMap, objects }, true);
		await saveAuthoringMap();
	}

	function materialValue(group: any, material: any) {
		return `${group.dataset_id}:${material.material_id}`;
	}

	function materialOptionLabel(material: any) {
		const status = material.status && material.status !== 'available' ? ` · ${material.status}` : '';
		const source = material.preview_source ? ` · ${material.preview_source}` : '';
		return `${material.display_name ?? material.material_id}${status}${source}`;
	}

	function findMaterialOption(value: string | null | undefined) {
		if (!value || materialPresetIds.includes(value)) return null;
		for (const group of materialGroups) {
			for (const material of group.materials ?? []) {
				if (materialValue(group, material) === value) return { group, material };
			}
		}
		return null;
	}

	function materialPreviewSource(value: string | null | undefined) {
		if (!value) return '';
		if (materialPresetIds.includes(value)) return materialPreviewUrl(value);
		const found = findMaterialOption(value);
		if (!found) return '';
		const { group, material } = found;
		if (material.kind === 'curated' || group.dataset_id === 'curated_basic') return curatedMaterialPreviewUrl(material.material_id);
		return measuredMaterialPreviewUrl(group.dataset_id, material.material_id, material.native_file);
	}

	function materialDisplayLabel(value: string | null | undefined) {
		if (!value) return 'No material';
		if (materialPresetIds.includes(value)) return value.replace(/_/g, ' ');
		const found = findMaterialOption(value);
		return found?.material?.display_name ?? value;
	}

	function materialCategoryFromText(value: string, fallback = 'all') {
		const key = value.toLowerCase();
		if (key.includes('glass') || key.includes('transparent') || key.includes('frost')) return 'glass';
		if (key.includes('mirror') || key.includes('reflect')) return 'mirror';
		if (key.includes('wall') || key.includes('paint') || key.includes('brick') || key.includes('plaster')) return 'wall';
		if (key.includes('floor') || key.includes('tile') || key.includes('carpet') || key.includes('stone')) return 'floor';
		if (key.includes('wood') || key.includes('fabric') || key.includes('leather') || key.includes('chair') || key.includes('table')) return 'furniture';
		if (key.includes('hazard') || key.includes('obstacle')) return 'hazard';
		return fallback;
	}

	function materialTagsFor(category: string, group: any = {}, material: any = {}) {
		const tags = new Set<string>();
		const key = `${category} ${group.dataset_id ?? ''} ${material.material_id ?? ''} ${material.display_name ?? ''} ${material.category ?? ''}`.toLowerCase();
		if (category !== 'all') tags.add(category);
		if (key.includes('glass') || key.includes('transparent')) tags.add('transparent');
		if (key.includes('mirror') || key.includes('reflect')) tags.add('reflective');
		if (key.includes('rough') || key.includes('frost')) tags.add('rough');
		if (key.includes('smooth') || key.includes('gloss')) tags.add('smooth');
		if (String(group.dataset_id ?? '').includes('hpbrdf')) {
			tags.add('polarization-ready');
			tags.add('NIR-ready');
		}
		if (String(group.dataset_id ?? '').includes('pbrdf')) tags.add('polarization-ready');
		if (category === 'glass' || category === 'mirror' || category === 'hazard') tags.add('hazard');
		if (category === 'floor') tags.add('floor-safe');
		return [...tags];
	}

	function recommendedMaterialCategory(item: any) {
		const key = `${item?.type ?? ''} ${item?.label ?? ''} ${item?.metadata?.asset_category ?? ''}`.toLowerCase();
		if (!key.trim()) return 'recommended';
		if (key.includes('glass')) return 'glass';
		if (key.includes('mirror')) return 'mirror';
		if (key.includes('wall')) return 'wall';
		if (key.includes('floor') || key.includes('traversable')) return 'floor';
		if (key.includes('chair') || key.includes('table') || key.includes('furniture')) return 'furniture';
		if (key.includes('hazard')) return 'hazard';
		return 'recommended';
	}

	function buildMaterialCards() {
		const presetCards = materialPresetIds.map((id) => {
			const category = materialCategoryFromText(id, id === 'fabric' ? 'furniture' : 'all');
			return {
				value: id,
				label: id.replace(/_/g, ' '),
				subtitle: 'OpticalNav preset',
				collection: 'preset',
				collectionLabel: 'Presets',
				category,
				tags: materialTagsFor(category, { dataset_id: 'preset' }, { material_id: id }),
				status: 'ready',
				kind: 'preset',
				preview: materialPreviewUrl(id),
				material: null,
				group: null
			};
		});
		const libraryCards = materialGroups.flatMap((group: any) =>
			(group.materials ?? []).map((material: any) => {
				const label = material.display_name ?? material.material_id;
				const category = materialCategoryFromText(`${label} ${material.material_id} ${material.category ?? ''} ${group.dataset_id}`, material.category ?? 'all');
				const value = materialValue(group, material);
				return {
					value,
					label,
					subtitle: group.display_name ?? group.dataset_id,
					collection: group.dataset_id,
					collectionLabel: group.display_name ?? group.dataset_id,
					category,
					tags: materialTagsFor(category, group, material),
					status: material.status ?? 'unknown',
					kind: material.kind ?? 'measured',
					preview: materialPreviewSource(value),
					material,
					group
				};
			})
		);
		return [...presetCards, ...libraryCards];
	}

	function materialMatchesSearch(value: string, label: string, extra = '') {
		const q = materialPickerSearch.trim().toLowerCase();
		if (!q) return true;
		return `${value} ${label} ${extra}`.toLowerCase().includes(q);
	}

	function filterMaterialCards(cards: any[], item: any) {
		const q = materialPickerSearch.trim().toLowerCase();
		const recommended = recommendedMaterialCategory(item);
		return cards
			.filter((card) => {
				if (materialPickerCollection !== 'all' && card.collection !== materialPickerCollection) return false;
				if (materialPickerCategory === 'recommended') {
					if (recommended !== 'recommended' && card.category !== recommended && !card.tags.includes(recommended)) return false;
				} else if (materialPickerCategory !== 'all' && card.category !== materialPickerCategory && !card.tags.includes(materialPickerCategory)) {
					return false;
				}
				if (!q) return true;
				return `${card.value} ${card.label} ${card.subtitle} ${card.tags.join(' ')}`.toLowerCase().includes(q);
			})
			.slice(0, 80);
	}

	function selectedMaterialPreviewSource() {
		return materialPreviewSource(selectedAuthoringItem?.material);
	}

	function materialInfo(value: string | null | undefined) {
		if (!value) return null;
		if (materialPresetIds.includes(value)) {
			return { kind: 'preset', label: value, detail: 'Built-in OpticalNav material preset.' };
		}
		const found = findMaterialOption(value);
		if (!found) return { kind: 'custom', label: value, detail: 'Registered custom authoring material.' };
		return {
			kind: found.material.kind ?? 'measured',
			label: found.material.display_name ?? found.material.material_id,
			detail: `${found.group.display_name ?? found.group.dataset_id} · ${found.material.status ?? 'unknown'} · ${found.group.mitsuba_strategy ?? 'material library'}`,
			capabilities: found.group.capabilities,
			native_file: found.material.native_file,
			preview_source: found.material.preview_source
		};
	}

	function ensureAuthoringMaterial(materialId: string, materials: any[]) {
		if (!materialId || materialPresetIds.includes(materialId) || materials.some((item: any) => item.material_id === materialId)) return materials;
		const found = findMaterialOption(materialId);
		if (!found) return [...materials, { material_id: materialId, category: 'custom', params: {}, render_binding: { kind: 'custom', material_id: materialId, bsdf_strategy: 'roughplastic', unresolved: true } }];
		const { group, material } = found;
		const kind = material.kind === 'curated' ? 'curated' : 'measured';
		const bsdfStrategy = group.mitsuba_strategy || (kind === 'measured' ? 'measured_polarized' : 'roughplastic');
		return [
			...materials,
			{
				material_id: materialId,
				category: material.kind === 'curated' ? material.category ?? 'curated' : 'measured',
				params: {
					dataset_id: group.dataset_id,
					source_material_id: material.material_id,
					display_name: material.display_name,
					native_file: material.native_file,
					status: material.status,
					kind: material.kind,
					mitsuba_strategy: group.mitsuba_strategy,
					capabilities: group.capabilities,
					preview_source: material.preview_source,
					channels_dir: material.channels_dir ?? null
				},
				render_binding: {
					kind,
					dataset_id: group.dataset_id,
					material_id: material.material_id,
					native_file: material.native_file,
					bsdf_strategy: bsdfStrategy,
					capabilities: group.capabilities ?? {},
					preview_source: material.preview_source,
					status: material.status
				}
			}
		];
	}

	function updateSelectedMaterial(value: string) {
		if (!authoringMap || !selectedAuthoringId) return;
		pushHistory();
		inspectorError = '';
		const material = value || null;
		const objects = (authoringMap.objects ?? []).map((item: any) => (item.id === selectedAuthoringId ? { ...item, material } : item));
		const regions = (authoringMap.regions ?? []).map((item: any) => (item.id === selectedAuthoringId ? { ...item, material } : item));
		const materials = material ? ensureAuthoringMaterial(material, authoringMap.materials ?? []) : (authoringMap.materials ?? []);
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
		const card = materialCards.find((item: any) => item.value === value);
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
		const materials = material ? ensureAuthoringMaterial(material, authoringMap.materials ?? []) : (authoringMap.materials ?? []);
		setAuthoringMapPayload({ ...authoringMap, objects, regions, materials }, true);
		pushActivity('ok', 'material', `Applied ${materialDisplayLabel(value)} with suggested tags.`);
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
		if (!authoringMap) setAuthoringMapPayload(makeStarterAuthoringMap());
		const current = authoringMap ?? makeStarterAuthoringMap();
		const environment = { ...(current.environment ?? {}) };
		if (field === 'radiance') environment.radiance = String(value).split(',').map((v) => Number(v.trim())).filter((v) => Number.isFinite(v)).slice(0, 3);
		else if (['intensity', 'rotation_deg'].includes(field)) environment[field] = Number(value);
		else if (field === 'background_visible') environment[field] = Boolean(value);
		else environment[field] = value;
		setAuthoringMapPayload({ ...current, environment }, true);
	}

	function envmapSizeLabel(bytes: unknown): string {
		const n = Number(bytes ?? 0);
		if (!Number.isFinite(n) || n <= 0) return '';
		if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
		return `${Math.max(1, Math.round(n / 1024))} KB`;
	}

	function fileToDataBase64(file: File): Promise<string> {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onerror = () => reject(reader.error ?? new Error('File read failed'));
			reader.onload = () => {
				const result = String(reader.result ?? '');
				resolve(result.includes(',') ? result.split(',', 2)[1] : result);
			};
			reader.readAsDataURL(file);
		});
	}

	async function loadEnvmaps() {
		if (!selectedProjectId || !sceneId) { envmapFiles = []; return; }
		try {
			const data = await listOpticalNavEnvmaps(selectedProjectId, sceneId);
			envmapFiles = data?.envmaps ?? [];
		} catch {
			envmapFiles = [];
		}
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
		envmapUploading = true;
		try {
			const dataBase64 = await fileToDataBase64(file);
			const data = await uploadOpticalNavEnvmap(selectedProjectId, sceneId, {
				filename: file.name,
				content_type: file.type || undefined,
				data_base64: dataBase64
			});
			if (data?.envmap_ref) {
				const current = authoringMap ?? makeStarterAuthoringMap();
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
				const saved = await saveOpticalNavAuthoringMap(selectedProjectId, sceneId, nextMap);
				if (saved?.authoring_map) setAuthoringMapPayload(saved.authoring_map, false);
				syncResult = null;
				renderReadiness = null;
			}
			pushActivity('ok', 'envmap', `Uploaded ${data?.filename ?? file.name} (${envmapSizeLabel(data?.size_bytes || file.size)}).`);
			await loadEnvmaps();
		} catch (err) {
			pushActivity('error', 'envmap', errorMessage(err));
		} finally {
			envmapUploading = false;
		}
	}

	function cameraRigSensorTypeToLegacyModality(sensor: CameraRigSensor | any): string {
		const sensorType = String(sensor?.sensor_type ?? '').toLowerCase();
		if (sensorType === 'nir_camera') return 'nir';
		if (sensorType === 'polar_camera') return 'polarization';
		if (sensorType === 'lidar_3d') return 'lidar';
		const modalities = Array.isArray(sensor?.modalities) ? sensor.modalities.map((m: unknown) => String(m).toLowerCase()) : [];
		if (modalities.includes('nir_intensity') || modalities.includes('active_nir_intensity') || modalities.includes('nir')) return 'nir';
		if (modalities.includes('polarization') || modalities.includes('stokes')) return 'polarization';
		if (modalities.includes('lidar_point_cloud') || modalities.includes('lidar')) return 'lidar';
		return 'rgb';
	}

	function legacySensorFromCameraRigSensor(sensor: CameraRigSensor): any {
		const modality = cameraRigSensorTypeToLegacyModality(sensor);
		const intrinsics = sensor.intrinsics ?? {};
		const mount = sensor.mount ?? { parent_frame: globalCameraRig?.base_frame ?? 'base_link', xyz_m: [0, 0, 1], rpy_deg: [0, 0, 0] };
		return {
			sensor_id: sensor.sensor_id,
			label: sensor.sensor_id,
			modality,
			enabled: sensor.enabled !== false,
			mount,
			resolution: intrinsics.resolution ?? [1280, 720],
			fov_deg: Number(intrinsics.fov_h_deg ?? 75),
			fov_v_deg: Number(intrinsics.fov_v_deg ?? 60),
			focal_length_px: Number(intrinsics.focal_length_px ?? 0),
			clip_range: [Number(intrinsics.clip_near_m ?? 0.05), Number(intrinsics.clip_far_m ?? 80)],
			sensor_sync_group: 'camera_rig',
			calibration_ref: null,
			active_emitter: sensor.nir,
			polarization: sensor.polarization,
			lidar: sensor.lidar,
			render: normalizeRigRenderSettings(sensor.render, sensor.sensor_type),
			source_schema: 'camera_rig_v1',
			canonical_sensor_type: sensor.sensor_type,
			modalities: sensor.modalities ?? [],
			intrinsics
		};
	}

	function normalizeRigRenderSettings(render: CameraRigRenderSettings | any, sensorType = 'rgb_camera'): CameraRigRenderSettings {
		const lidar = sensorType === 'lidar_3d';
		return {
			path_spp: positiveInt(render?.path_spp, lidar ? 1 : 4096),
			aov_spp: positiveInt(render?.aov_spp, lidar ? 1 : 16),
			polar_spp: positiveInt(render?.polar_spp, lidar ? 1 : 256),
			samples_per_pass: render?.samples_per_pass == null || render?.samples_per_pass === ''
				? null
				: positiveInt(render.samples_per_pass, 1)
		};
	}

	function positiveInt(value: unknown, fallback: number): number {
		const parsed = Number(value);
		return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : fallback;
	}

	function sensorMountHeight(sensor: any): number {
		const xyz = sensor?.mount?.xyz_m;
		if (!Array.isArray(xyz)) return 0;
		// CameraRig v1 is Z-up: [lateral, forward, up].
		// OpticalNav legacy sweep expects robot_mount as [lateral, height, forward].
		const heightIndex = sensor?.source_schema === 'camera_rig_v1' ? 2 : 1;
		return Number(xyz[heightIndex] ?? 0) || 0;
	}

	function robotMountForRender(sensor: any): any {
		const mount = sensor?.mount ?? {};
		const xyz = Array.isArray(mount.xyz_m) ? mount.xyz_m : [0, rigMountHeightM, 0];
		const rpy = Array.isArray(mount.rpy_deg) ? mount.rpy_deg : [0, 0, 0];
		if (sensor?.source_schema === 'camera_rig_v1') {
			return {
				...mount,
				// Convert CameraRig v1 [x lateral, y forward, z up] to sweep convention
				// [x lateral, y height, z forward].
				xyz_m: [Number(xyz[0] ?? 0), Number(xyz[2] ?? rigMountHeightM), Number(xyz[1] ?? 0)],
				rpy_deg: [Number(rpy[0] ?? 0), Number(rpy[1] ?? 0), Number(rpy[2] ?? 0)],
				source_schema: 'camera_rig_v1'
			};
		}
		return { ...mount, xyz_m: [Number(xyz[0] ?? 0), Number(xyz[1] ?? rigMountHeightM), Number(xyz[2] ?? 0)], rpy_deg: [Number(rpy[0] ?? 0), Number(rpy[1] ?? 0), Number(rpy[2] ?? 0)] };
	}

	function formatRigVec(values: unknown, digits = 2): string {
		if (!Array.isArray(values)) return '-';
		return values.map((v) => Number(v ?? 0).toFixed(digits)).join(', ');
	}

	function formatResolution(values: unknown): string {
		if (!Array.isArray(values) || values.length < 2) return '-';
		return `${Number(values[0] ?? 0)} × ${Number(values[1] ?? 0)}`;
	}

	function formatRenderSpp(sensor: any): string {
		const render = normalizeRigRenderSettings(sensor?.render, String(sensor?.canonical_sensor_type ?? sensor?.sensor_type ?? 'rgb_camera'));
		return `path ${render.path_spp} · aov ${render.aov_spp} · polar ${render.polar_spp}`;
	}

	async function loadGlobalCameraRig() {
		globalCameraRigError = '';
		globalCameraRigStatus = 'Loading camera rig preset...';
		try {
			const rig = await getCameraRig('ranger_mini_default');
			globalCameraRig = rig;
			globalCameraRigStatus = `Using ${rig.label || rig.rig_id} (${rig.sensors?.length ?? 0} sensors) from global Camera Rig preset.`;
			if (rig.sensors?.length && !rig.sensors.some((sensor) => sensor.sensor_id === activeRigSensorId)) {
				activeRigSensorId = rig.sensors[0].sensor_id;
			}
			pushActivity('ok', 'camera-rig', `Loaded ${rig.rig_id} for dataset render sensor specs.`);
		} catch (err) {
			globalCameraRig = null;
			globalCameraRigError = errorMessage(err);
			globalCameraRigStatus = 'Global Camera Rig preset unavailable; falling back to legacy authoring map sensors.';
			pushActivity('warn', 'camera-rig', globalCameraRigStatus, err);
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

	function sensorRenderModality(sensor: any): string {
		const modality = String(sensor?.modality ?? 'rgb').toLowerCase();
		if (modality === 'nir') return 'active_nir_intensity';
		if (modality === 'polarization') return 'polar_rgb_preview';
		if (modality === 'depth') return 'depth';
		if (modality === 'lidar') return 'lidar_like';
		return 'rgb';
	}

	function sensorRenderChipLabel(option: any): string {
		const modality = String(option?.modality ?? '').toUpperCase();
		const renderModality = String(option?.render_modality ?? 'rgb');
		return modality && modality.toLowerCase() !== renderModality ? `${modality} → ${renderModality}` : renderModality;
	}

	function headingHasSensorModality(hdata: any, modality: string, sensorId = activeRigSensorId): boolean {
		const key = `has_${modality}`;
		const sensors = hdata?.sensors;
		if (sensorId && sensors && typeof sensors === 'object') {
			return Boolean(sensors[sensorId]?.[key]);
		}
		return Boolean(hdata?.[key]);
	}

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
		const renderMount = robotMountForRender(sensor);
		const rigId = String(globalCameraRig?.rig_id ?? authoringMap?.camera_rig?.rig_id ?? 'mobile_base_default');
		const baseFrame = String(sensor?.mount?.parent_frame ?? globalCameraRig?.base_frame ?? authoringMap?.camera_rig?.base_frame ?? 'base_link');
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
		const x = clampMapNumber(rawPt.x, 'x');
		const y = clampMapNumber(rawPt.y, 'y');
		if (shiftKey || !fixedPt) return [x, y];
		const dx = x - fixedPt[0];
		const dy = y - fixedPt[1];
		const len = Math.sqrt(dx * dx + dy * dy);
		if (len < 0.01) return [x, y];
		// Snap to nearest 45° step (8 directions: ortho + diagonal)
		const angle = Math.atan2(dy, dx);
		const STEP = Math.PI / 4;
		const snapped = Math.round(angle / STEP) * STEP;
		return [
			clampMapNumber(fixedPt[0] + len * Math.cos(snapped), 'x'),
			clampMapNumber(fixedPt[1] + len * Math.sin(snapped), 'y'),
		];
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

	function materialSuggestion(item: any) {
		const material = item?.material;
		if (material === 'clear_glass' || material === 'frosted_glass') return 'Glass material selected. Apply the glass hazard preset if this surface blocks the robot.';
		if (material === 'mirror') return 'Mirror material selected. Apply the mirror hazard preset to include it in hazard labels.';
		if (material === 'wood' || material === 'fabric' || material === 'tile') return 'Opaque material selected. Use landmark goal or normal obstacle labels as needed.';
		const found = findMaterialOption(material);
		if (found?.group?.dataset_id === 'hpbrdf_2025') return 'hpBRDF material selected. This is a measured hyperspectral/polarimetric material; verify local channel availability before final sensor rendering.';
		if (found?.group?.dataset_id === 'pbrdf_2020') return 'pBRDF material selected. This is a measured polarimetric material; use it for optical appearance, while navigation labels still come from the hazard flags below.';
		if (found) return 'Measured material selected from the material library. Navigation semantics still come from the object type and flags.';
		return '';
	}

	async function loadMaterialLibrary() {
		try {
			const payload = await materialLibrary();
			materialGroups = payload.groups ?? [];
			const count = materialGroups.reduce((acc: number, group: any) => acc + (group.materials?.length ?? 0), 0);
			materialLibraryStatus = `${count} library materials loaded.`;
		} catch (err) {
			materialGroups = [];
			materialLibraryStatus = err instanceof Error ? `Material library unavailable: ${err.message}` : 'Material library unavailable.';
		}
	}

	async function loadUsdCandidates() {
		try {
			const payload = await listOpticalNavUsdCandidates();
			usdCandidates = payload.candidates ?? [];
			if (!selectedMoorelaneUsdRef && usdCandidates.length) selectedMoorelaneUsdRef = usdCandidates[0].usd_ref;
			usdCandidateStatus = `${usdCandidates.length} Moorelane USD files found.`;
		} catch (err) {
			usdCandidates = [];
			usdCandidateStatus = err instanceof Error ? `USD candidates unavailable: ${err.message}` : 'USD candidates unavailable.';
		}
	}

	async function loadMapAssets() {
		if (!selectedProjectId) {
			mapAssets = [];
			mapAssetStatus = 'Select a project to load map assets.';
			return;
		}
		try {
			const payload = await getOpticalNavMapAssets(selectedProjectId);
			mapAssets = payload.assets ?? [];
			mapAssetStatus = mapAssets.length
				? `${mapAssets.length} selected asset(s) from Asset Library.`
				: 'No selected USD assets. Open Asset Library to enable assets.';
			if (!selectedUsdAssetId && mapAssets.length) selectedUsdAssetId = mapAssets[0].asset_id ?? mapAssets[0].id;
			if (selectedUsdAssetId && !mapAssets.some((item: any) => (item.asset_id ?? item.id) === selectedUsdAssetId)) {
				selectedUsdAssetId = mapAssets[0]?.asset_id ?? mapAssets[0]?.id ?? '';
			}
		} catch (err) {
			mapAssets = [];
			mapAssetStatus = err instanceof Error ? `Map assets unavailable: ${err.message}` : 'Map assets unavailable.';
		}
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
		const key = `${selectedProjectId}:${sceneId}:${currentUsdRef}`;
		if (!selectedProjectId || !sceneId || (!force && !refreshExtraction && key === editorGeometryCatalogKey)) return;
		editorGeometryCatalogKey = key;
		try {
			editorGeometryCatalogStatus = refreshExtraction ? 'Extracting USD proxy geometry...' : 'Loading USD asset proxies...';
			const payload = await getOpticalNavEditorGeometry(selectedProjectId, sceneId, refreshExtraction);
			editorGeometryPayload = payload;
			editorGeometryCatalogStatus = friendlyUsdCatalogMessage(payload);
			const count = (payload.objects ?? []).filter((item: any) => item.category !== 'floor').length;
			if (payload.status === 'ready') editorGeometryRefreshToken += 1;
			if (!selectedUsdAssetId && count) {
				const first = (payload.objects ?? []).find((item: any) => item.category !== 'floor');
				selectedUsdAssetId = first?.id ?? '';
			}
		} catch (err) {
			editorGeometryPayload = null;
			editorGeometryCatalogStatus = err instanceof Error ? `USD asset catalog unavailable: ${err.message}` : 'USD asset catalog unavailable.';
		}
	}

	async function extractUsdProxies() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before extracting USD proxies.')) return;
		if (!requireReady(Boolean(currentUsdRef), 'Attach a USD scene before extracting proxies.')) return;
		pushActivity('info', 'usd-extract', 'Extracting USD proxy geometry.');
		await loadEditorGeometryCatalog(true, true);
		const count = (editorGeometryPayload?.objects ?? []).filter((item: any) => item.category !== 'floor').length;
		if (editorGeometryPayload?.status === 'ready') {
			pushActivity('ok', 'usd-extract', `USD proxy geometry ready with ${count} placeable objects.`);
		} else {
			pushActivity('warn', 'usd-extract', friendlyUsdCatalogMessage(editorGeometryPayload), editorGeometryPayload?.extractor);
		}
	}

	function usdAssetLabel(asset: any) {
		return String(asset?.label || asset?.source_path || asset?.id || 'USD object').split('/').pop() ?? 'USD object';
	}

	function placementHintForTool(tool: string) {
		if (tool === 'wall' || tool === 'glass_wall' || tool === 'mirror_wall') return 'line placement';
		if (['goal', 'start', 'hazard', 'forbidden', 'stop_before', 'traversable'].includes(tool)) return 'drag region';
		return 'point placement';
	}

	function typeForUsdAsset(asset: any) {
		const key = `${asset?.label ?? ''} ${asset?.source_path ?? ''} ${asset?.category ?? ''}`.toLowerCase();
		if (key.includes('chair') || key.includes('seat')) return 'chair';
		if (key.includes('table') || key.includes('desk')) return 'table';
		if (key.includes('plant') || key.includes('palm') || key.includes('succulent')) return 'plant';
		return 'landmark';
	}

	function selectBuiltInPlaceAsset(asset: BuiltInPlaceAsset) {
		if (asset.kind === 'rich_asset') {
			selectedUsdAssetId = asset.asset_id ?? asset.id;
			placementTool = 'usd_asset';
		} else {
			placementTool = asset.tool as PlacementTool;
		}
		draftPoint = null;
		linePreview = null;
		dragStart = null;
		dragPreview = null;
	}

	function selectBuiltInAsset(tool: string) {
		placementTool = tool as PlacementTool;
		draftPoint = null;
		linePreview = null;
		dragStart = null;
		dragPreview = null;
	}

	function currentAuthoringMap() {
		if (authoringMapText.trim()) {
			return JSON.parse(authoringMapText);
		}
		return authoringMap ?? makeStarterAuthoringMap();
	}

	function ensureAuthoringMap() {
		if (!authoringMap) setAuthoringMapPayload(makeStarterAuthoringMap());
		return authoringMap;
	}

	function nextAuthoringId(prefix: string) {
		const map = ensureAuthoringMap();
		const ids = new Set([...(map.objects ?? []), ...(map.regions ?? [])].map((item: any) => item.id));
		let index = 1;
		let id = `${prefix}_${String(index).padStart(3, '0')}`;
		while (ids.has(id)) {
			index += 1;
			id = `${prefix}_${String(index).padStart(3, '0')}`;
		}
		return id;
	}

	function svgPoint(event: PointerEvent) {
		const svg = event.currentTarget as SVGSVGElement;
		const rect = svg.getBoundingClientRect();
		const x = ((event.clientX - rect.left) / rect.width) * 6;
		const y = ((event.clientY - rect.top) / rect.height) * 4;
		return {
			x: Math.max(0, Math.min(6, Number(x.toFixed(3)))),
			y: Math.max(0, Math.min(4, Number(y.toFixed(3))))
		};
	}

	function worldX(value: number) {
		return (value / 6) * 600;
	}

	function worldY(value: number) {
		return (value / 4) * 400;
	}

	function rectangleFromPoints(a: { x: number; y: number }, b: { x: number; y: number }) {
		const minX = Math.min(a.x, b.x);
		const minY = Math.min(a.y, b.y);
		const maxX = Math.max(a.x, b.x);
		const maxY = Math.max(a.y, b.y);
		return [Number(minX.toFixed(3)), Number(minY.toFixed(3)), Number(maxX.toFixed(3)), Number(maxY.toFixed(3))];
	}

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

	function addPointObject(type: 'chair' | 'table' | 'plant', center: { x: number; y: number }) {
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
				yaw_deg: 0
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

	function addCameraObject(center: { x: number; y: number }) {
		pushHistory();
		const map = ensureAuthoringMap();
		const id = nextAuthoringId('camera');
		const object = {
			id,
			type: 'camera',
			label: 'Camera',
			placement: 'point',
			geometry: { type: 'point', center: [center.x, center.y], yaw_deg: 0 },
			material: null,
			navigation: { blocks_navigation: false, hazard_type: null, include_in_hazard_mask: false, instruction_candidate: false, goal_candidate: false },
			metadata: { created_by: 'webui_map_editor', fov_deg: 90, resolution: [1440, 1080] }
		};
		setAuthoringMapPayload({ ...map, objects: [...(map.objects ?? []), object] });
		selectedAuthoringId = id;
		placementTool = 'select';
		pushActivity('ok', 'map-editor', `Added camera ${id}.`);
	}

	function addUsdAssetObject(center: { x: number; y: number }) {
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
		const assetSourcePath = sourceFormat === 'glb' ? undefined : selectedUsdAsset.source_path;
		const object = {
			id,
			type,
			label: usdAssetLabel(selectedUsdAsset),
			placement: 'point',
			geometry: {
				type: 'point',
				center: [center.x, center.y],
				yaw_deg: Number(selectedUsdAsset.default_rotation ?? 0)
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
				proxy_size: size,
				normalized_y_min: selectedUsdAsset.bounds?.min?.[1] ?? 0
			}
		};
		const materials = object.material ? ensureAuthoringMaterial(object.material, map.materials ?? []) : (map.materials ?? []);
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
	function handleGroundPointerDown(point: { x: number; y: number }, shiftKey = false) {
		contextMenu = null;
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
			addPointObject(placementTool, point);
			return;
		}
		if (placementTool === 'camera') {
			addCameraObject(point);
			return;
		}
		if (placementTool === 'usd_asset') {
			addUsdAssetObject(point);
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
			const sp = placementTool === 'usd_asset' ? (selectedUsdAsset?.source_path ?? undefined) : undefined;
			const ac = placementTool === 'usd_asset' ? (selectedUsdAsset?.category ?? undefined) : undefined;
			const ghostYMin = placementTool === 'usd_asset' ? (selectedUsdAsset?.bounds?.min?.[1] ?? 0) : undefined;
			draftGhost = { type: 'point', x: point.x, y: point.y, valid: inBounds, sourcePath: sp, assetCat: ac, normalizedYMin: ghostYMin };
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
		const geometry = item?.geometry;
		if (!geometry) return null;
		if (geometry.type === 'point' && geometry.center) return { x: Number(geometry.center[0] ?? 0), y: Number(geometry.center[1] ?? 0) };
		if (geometry.type === 'line' && geometry.start && geometry.end) {
			return { x: (Number(geometry.start[0] ?? 0) + Number(geometry.end[0] ?? 0)) / 2, y: (Number(geometry.start[1] ?? 0) + Number(geometry.end[1] ?? 0)) / 2 };
		}
		if (geometry.type === 'rectangle' && geometry.bounds) {
			return { x: (Number(geometry.bounds[0] ?? 0) + Number(geometry.bounds[2] ?? 0)) / 2, y: (Number(geometry.bounds[1] ?? 0) + Number(geometry.bounds[3] ?? 0)) / 2 };
		}
		return null;
	}

	function previewFromSelected() {
		const center = selectedItemCenter();
		if (!center) return;
		stopRobotAnimation();
		robotPos = center;
		placementTool = 'select';
		// Create a custom sensor node at this position and switch to sensor mode
		const id = `preview_${Date.now()}`;
		customSensorNodes = [...customSensorNodes, { id, x: center.x, z: center.y, headingDeg: 0 }];
		selectedSensorNodeId = id;
		pageMode = 'sensors';
		pushActivity('info', 'preview', `Sensor placed near ${selectedAuthoringId}. Adjust heading and click "Render this viewpoint".`);
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

	function rectangleStyle(type: string) {
		if (type === 'goal') return 'region-goal';
		if (type === 'start') return 'region-start';
		if (type === 'stop_before') return 'region-stop';
		if (type === 'traversable') return 'region-traversable';
		if (type === 'hazard') return 'region-hazard';
		if (type === 'forbidden') return 'region-forbidden';
		return 'region-generic';
	}

	function isRegionLayerVisible(type: string) {
		if (type === 'goal' || type === 'start' || type === 'stop_before') return visibleLayers.goals;
		if (type === 'traversable') return visibleLayers.traversable;
		if (type === 'hazard' || type === 'forbidden' || type === 'obstacle') return visibleLayers.hazards;
		return true;
	}

	function isObjectLayerVisible(type: string) {
		if (type === 'wall') return visibleLayers.objects;
		if (type === 'glass_wall' || type === 'mirror_wall' || type === 'transparent_partition') return visibleLayers.hazards && visibleLayers.objects;
		return visibleLayers.objects;
	}

	function graphNode(nodeId: string) {
		return graphNodes.find((node: any) => node.node_id === nodeId);
	}

	function toggleLayer(layer: keyof typeof visibleLayers) {
		visibleLayers = { ...visibleLayers, [layer]: !visibleLayers[layer] };
	}

	function readinessState() {
		if (!selectedProjectId) {
			return {
				step: 'Project',
				status: 'needs_input',
				message: 'Create or select an OpticalNav project.',
				action: 'Create Project',
				tab: 'scene',
				kind: 'create_project'
			};
		}
		if (!hasScene) {
			return {
				step: 'Scene',
				status: 'needs_input',
				message: 'Add a scene before editing navigation overlays.',
				action: 'Add Scene',
				tab: 'scene',
				kind: 'add_scene'
			};
		}
		if (!hasAuthoringMap || !hasAuthoringContent) {
			return {
				step: 'Map Overlay',
				status: 'needs_input',
				message: 'Create a visible 2D map overlay with traversable, hazard, and goal layers.',
				action: 'Create Map Overlay',
				tab: 'scene',
				kind: 'create_overlay'
			};
		}
		if (!hasPersistedAuthoringMap || authoringMapDirty) {
			return {
				step: 'Map Overlay',
				status: 'ready',
				message: 'Save the edited overlay so backend compile/map/graph steps use the same source of truth.',
				action: 'Save Map Overlay',
				tab: 'scene',
				kind: 'save_overlay'
			};
		}
		if (!currentScene?.annotation_ok || currentScene?.sync_status?.annotation_stale) {
			return {
				step: 'Annotation',
				status: 'ready',
				message: currentScene?.sync_status?.annotation_stale
					? 'Map overlay changed after annotation compile. Compile again.'
					: 'Compile the map overlay into scene_annotation.json.',
				action: 'Compile Annotation',
				tab: 'scene',
				kind: 'compile_annotation'
			};
		}
		if (!hasMap || currentScene?.sync_status?.traversable_map_stale) {
			return {
				step: 'Traversable Map',
				status: 'ready',
				message: currentScene?.sync_status?.traversable_map_stale
					? 'Annotation changed after map build. Rebuild the traversable grid.'
					: 'Build the traversable grid from the compiled annotation.',
				action: 'Build Traversable Map',
				tab: 'plan',
				kind: 'build_map'
			};
		}
		if (!hasGraph || currentScene?.sync_status?.viewpoint_graph_stale) {
			return {
				step: 'Viewpoint Graph',
				status: 'ready',
				message: currentScene?.sync_status?.viewpoint_graph_stale
					? 'Traversable map changed after graph build. Rebuild the viewpoint graph.'
					: 'Build the panoramic viewpoint graph from the traversable map.',
				action: 'Build Viewpoint Graph',
				tab: 'plan',
				kind: 'build_graph'
			};
		}
		if (!hasEpisodes) {
			return {
				step: 'Episodes',
				status: 'ready',
				message: 'Generate graph episodes from the cached viewpoint graph.',
				action: 'Generate Graph Episodes',
				tab: 'plan',
				kind: 'plan_graph_episodes'
			};
		}
		if (!renderSceneSynced) {
			return {
				step: 'Render Scene Sync',
				status: 'ready',
				message: 'Sync editor overlays into render-scene artifacts before sensor sweep.',
				action: 'Sync Render Scene',
				tab: 'scene',
				kind: 'sync_render_scene'
			};
		}
		if (!renderConfigReady) {
			return {
				step: 'Sensor Sweep',
				status: 'blocked',
				message: 'Render-scene artifacts are synced, but scene state and camera spec are missing.',
				action: 'Configure Sensor Sweep',
				tab: 'render',
				kind: 'configure_render'
			};
		}
		if (!validationReport) {
			return {
				step: 'Validation',
				status: 'ready',
				message: 'Validate dataset structure before export.',
				action: 'Validate Dataset',
				tab: 'review',
				kind: 'validate'
			};
		}
		if (!validationPassed) {
			return {
				step: 'Validation',
				status: 'failed',
				message: 'Validation failed. Review errors before export.',
				action: 'Review Validation',
				tab: 'review',
				kind: 'review_validation'
			};
		}
		return {
			step: 'Export',
			status: 'ready',
			message: 'Dataset is validated and ready for packaging.',
			action: 'Export Dataset',
			tab: 'review',
			kind: 'export'
		};
	}

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
		const data = await run(() => listOpticalNavProjects(), undefined, 'projects:list');
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
		const data = await run(() => getOpticalNavProject(selectedProjectId), undefined, 'project:detail');
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
				() => getOpticalNavAuthoringMap(selectedProjectId, sceneId),
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
				createOpticalNavProject({
					project_name: projectName,
					dataset_type: 'Synthetic fine-tuning dataset',
					target_scenario: 'glass / mirror / transparent partition navigation',
					robot_profile: 'mobile_base_front_camera',
					modalities: selectedModalities
				}),
			'Project created.',
			'project:create'
		);
		if (data?.project_id) await refreshProjects(data.project_id);
	}

	async function addScene() {
		if (!selectedProjectId) return;
		const data = await run(
			() => addOpticalNavScene(selectedProjectId, { scene_id: sceneId, usd_ref: usdRef }),
			'Scene added with starter annotation.',
			'scene:add'
		);
		if (data?.annotation) annotationText = JSON.stringify(data.annotation, null, 2);
		await refreshProject();
	}

	async function attachUsdScene(ref = selectedMoorelaneUsdRef || usdRef) {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before attaching USD.')) return;
		const nextRef = String(ref || '').trim();
		if (!requireReady(Boolean(nextRef), 'Choose a USD file before attaching it.')) return;
		const data = await run(
			() => attachOpticalNavSceneUsd(selectedProjectId, sceneId, { usd_ref: nextRef }),
			'USD scene attached.',
			'scene:usd-ref'
		);
		if (data?.usd_ref) usdRef = data.usd_ref;
		editorGeometryPayload = null;
		editorGeometryCatalogKey = '';
		await refreshProject();
		await loadEditorGeometryCatalog(true);
	}

	async function loadAuthoringMap() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before loading the map overlay.')) return;
		const data = await run(
			() => getOpticalNavAuthoringMap(selectedProjectId, sceneId),
			undefined,
			'authoring-map:load'
		);
		if (data) setAuthoringMapPayload(data, false);
		await loadEnvmaps();
	}

	async function saveAuthoringMap() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before saving the map overlay.')) return;
		let payload: any;
		try {
			payload = currentAuthoringMap();
		} catch (err) {
			error = `Invalid authoring_map JSON: ${errorMessage(err)}`;
			pushActivity('error', 'authoring-map:save', error);
			return;
		}
		payload = {
			...payload,
			settings: { ...(payload.settings ?? {}), map_w: mapWidth, map_h: mapHeight }
		};
		const data = await run(
			() => saveOpticalNavAuthoringMap(selectedProjectId, sceneId, payload),
			'Map overlay saved.',
			'authoring-map:save'
		);
		if (data?.authoring_map) setAuthoringMapPayload(data.authoring_map, false);
		// Phase 3: PUT /authoring-map now regenerates render_scene.xml automatically.
		// Update render readiness from the response so Sync button is no longer needed.
		if (data?.render_readiness) renderReadiness = data.render_readiness;
		await refreshProject();
		// Reload render config (sceneStateText/cameraSpecText) if XML was freshly generated.
		if (data?.render_readiness?.ok && !sceneStateText.trim()) await loadRenderConfig();
	}

	async function saveMap() {
		await saveAuthoringMap();
		await compileAuthoringMap();
	}

	async function compileAuthoringMap() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before compiling annotation.')) return;
		if (!requireReady(hasAuthoringMap, 'Create or load a map overlay before compiling annotation.')) return;
		const data = await run(
			() => compileOpticalNavAuthoringMap(selectedProjectId, sceneId),
			'Map overlay compiled to scene_annotation.json.',
			'authoring-map:compile'
		);
		if (data) {
			compileResult = data;
			if (data.annotation) annotationText = JSON.stringify(data.annotation, null, 2);
		}
		await refreshProject();
	}

	async function loadAnnotation() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before loading annotation.')) return;
		const data = await run(() => getSceneAnnotation(selectedProjectId, sceneId), undefined, 'annotation:load');
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
		await run(() => saveSceneAnnotation(selectedProjectId, sceneId, payload), 'Annotation saved and validated.', 'annotation:save');
		await refreshProject();
	}

	async function buildMap() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add and validate the scene before building a traversable grid.')) return;
		buildingMap = true;
		const data = await run(
			() => buildOpticalNavMap(selectedProjectId, sceneId, { resolution: Number(resolution) }),
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
			const accepted = await syncOpticalNavRenderScene(selectedProjectId, sceneId, {});
			const jobId = accepted?.sync_job_id as string | undefined;
			if (!jobId) {
				// Legacy synchronous response — treat as immediate result.
				await _finalizeSyncResult(accepted);
				return;
			}
			const result = await new Promise<any>((resolve, reject) => {
				try {
					const ws = new WebSocket(opticalNavSyncProgressWsUrl(jobId));
					ws.onmessage = (ev) => {
						try {
							const msg = JSON.parse(ev.data);
							if (msg?.status === 'running' || msg?.status === 'started') {
								syncProgress = { processed: msg.processed ?? 0, total: msg.total ?? 0, label: msg.label ?? '', stage: msg.stage ?? '' };
							} else if (msg?.status === 'done' || msg?.status === 'error') {
								try { ws.close(); } catch {}
								if (msg.status === 'done') resolve(msg.result);
								else reject(new Error((msg.result && (msg.result as any).error) || 'Sync failed'));
							}
						} catch {}
					};
					ws.onerror = () => reject(new Error('Sync progress WebSocket error'));
					ws.onclose = () => { /* may close before final msg in races */ };
				} catch (err) { reject(err as Error); }
			});
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
			renderReadiness = await getOpticalNavRenderReadiness(selectedProjectId, sceneId);
		} catch {
			renderReadiness = null;
		}
	}

	async function loadRenderConfig() {
		if (!selectedProjectId || !sceneId) return;
		try {
			const data = await getOpticalNavRenderConfig(selectedProjectId, sceneId);
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
			const data = await saveOpticalNavRenderConfig(selectedProjectId, sceneId, { scene_state, camera_spec });
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
			() => syncOpticalNavIsaacStage(selectedProjectId, sceneId, {}),
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
		let progressWs: WebSocket | null = null;
		try {
			progressWs = new WebSocket(graphBuildProgressWsUrl(selectedProjectId, sceneId));
			progressWs.onmessage = (ev) => {
				try {
					const msg = JSON.parse(ev.data);
					if (msg?.status === 'building') graphBuildProgress = msg;
				} catch {}
			};
			progressWs.onerror = () => {};
		} catch {}
		const data = await run(
			() =>
				buildOpticalNavViewpointGraph(selectedProjectId, sceneId, {
					max_nodes: Number(maxNodes),
					heading_count: Number(headingCount),
					min_node_spacing_m: Number(minNodeSpacing),
					robot_radius_m: Number(robotRadius),
					min_clearance_m: Number(minClearance),
					k_neighbors: Number(kNeighbors),
					max_edge_length_m: Number(maxEdgeLength),
					resolution: Number(resolution),
					seed: Number(seed)
				}),
			'Viewpoint graph built.',
			'graph:build'
		);
		if (progressWs) { try { progressWs.close(); } catch {} progressWs = null; }
		buildingGraph = false;
		graphBuildProgress = null;
		if (data) graphResult = data;
		await refreshProject();
		if (data) await loadGraph();
	}

	async function loadGraph() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasGraph, 'Build the viewpoint graph before loading graph JSON.')) return;
		const data = await run(() => getOpticalNavViewpointGraph(selectedProjectId, sceneId), undefined, 'graph:load');
		if (data) graphPayload = data;
	}

	async function scanObservations() {
		if (!selectedProjectId || !sceneId) return;
		try {
			const data = await scanOpticalNavObservations(selectedProjectId, sceneId);
			if (data) observationScan = data;
		} catch (_) {
			// ignore scan errors silently
		}
	}

	async function clearNodeObservations(nodeId: string) {
		if (!selectedProjectId || !sceneId) return;
		try {
			await deleteOpticalNavObservations(selectedProjectId, sceneId, [nodeId]);
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
			await deleteOpticalNavObservations(selectedProjectId, sceneId, null);
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
			() =>
				planOpticalNavEpisodes(selectedProjectId, {
					scene_id: sceneId,
					num_pairs: Number(episodeCount),
					splits: splitObject,
					instruction_types: instructionTypes.split(',').map((item) => item.trim()).filter(Boolean),
					modalities: selectedModalities,
					seed: Number(seed)
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
			() =>
				planOpticalNavGraphEpisodes(selectedProjectId, {
					scene_id: sceneId,
					num_pairs: Number(episodeCount),
					splits: splitObject,
					scenarios: graphScenarios.split(',').map((item) => item.trim()).filter(Boolean),
					modalities: selectedModalities,
					seed: Number(seed)
				}),
			'Graph episodes planned.',
			'episodes:plan-graph'
		);
		if (data) planResult = data;
		await refreshProject();
	}

	async function refreshEpisodes() {
		if (!selectedProjectId) return;
		const data = await run(() => listOpticalNavEpisodes(selectedProjectId), undefined, 'episodes:list');
		if (!data) return;
		const all: any[] = data.episodes ?? [];
		// Filter to current scene if sceneId is set
		episodes = sceneId ? all.filter((ep: any) => !ep.scene_id || ep.scene_id === sceneId) : all;
		if (!selectedEpisodeId && episodes.length) selectedEpisodeId = episodes[0].episode_id;
	}

	async function loadEpisode(id = selectedEpisodeId) {
		if (!selectedProjectId || !id) return;
		selectedEpisodeId = id;
		// Ensure graph is loaded so path_nodes can be resolved to 3D positions
		if (!graphPayload && hasGraph) await loadGraph();
		const data = await run(() => getOpticalNavEpisode(selectedProjectId, id), undefined, 'episode:detail');
		if (data) selectedEpisode = data;
	}

	function captureEditorViewProbe() {
		const cam = mapEditorRef?.getCurrentCamera?.();
		if (!cam) {
			probeError = 'Map editor camera is not ready yet.';
			return;
		}
		const fx = cam.target[0] - cam.origin[0];
		const fz = cam.target[2] - cam.origin[2];
		const yawRad = Math.atan2(fx, -fz);
		editorViewProbe = {
			x: Number(cam.origin[0].toFixed(3)),
			z: Number(cam.origin[2].toFixed(3)),
			yaw_deg: Number(((yawRad * 180) / Math.PI).toFixed(2)),
			height_m: Number(Math.max(0.05, cam.origin[1]).toFixed(3)),
		};
		probeError = '';
	}
	async function handleAddNodeAtFloor(x: number, z: number) {
		if (!selectedProjectId || !sceneId) return;
		try {
			const data = await addOpticalNavGraphNode(selectedProjectId, sceneId, { x, y: z, heading_count: Number(headingCount) });
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
			walkabilityOverlayMeta = await getOpticalNavWalkabilityOverlay(selectedProjectId, sceneId);
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
			const res = await paintOpticalNavWalkabilityOverlay(selectedProjectId, sceneId, {
				brush: paintMode,
				radius_m: paintRadiusM,
				points,
				shape: 'stroke',
			});
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
			await clearOpticalNavWalkabilityOverlay(selectedProjectId, sceneId);
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
			const res = await regenerateOpticalNavGraphRegion(selectedProjectId, sceneId, {
				bbox: pendingRegionBbox,
				max_nodes: Number(maxNodes),
				min_node_spacing_m: Number(minNodeSpacing),
				robot_radius_m: Number(robotRadius),
				min_clearance_m: Number(minClearance),
				heading_count: Number(headingCount),
				seed: Number(seed),
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
			const res = await addOpticalNavGraphEdge(selectedProjectId, sceneId, { source, target });
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
			await deleteOpticalNavGraphNode(selectedProjectId, sceneId, nid);
			pushActivity('ok', 'graph:delete-node', `Deleted ${nid}`);
			selectedSensorNodeId = '';
			await loadGraph();
		} catch (err) {
			pushActivity('error', 'graph:delete-node', errorMessage(err));
		}
	}
	async function runProbeRender() {
		probeError = '';
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
		const modality = activeRenderModality;
		const body: Record<string, unknown> = {
			modalities: [modality],
			backend,
			camera_height_m: rigMountHeightM,
			render_settings: renderSettingsFromRigSensor(activeRigSensorOption?.sensor),
		};
		if (scene_state) body.scene_state = scene_state;
		if (activeCameraSpec) body.camera_spec = activeCameraSpec;

		let vp_id = 'custom_0';
		let heading_id = 'h0';
		if (probeMode === 'selected') {
			if (!selectedSensorNode) { probeError = 'Select a viewpoint or custom sensor first.'; return; }
			const isCustom = (selectedSensorNode as any).isCustom;
			const customNode = selectedCustomSensorNode;
			if (isCustom && customNode) {
				body.custom_positions = [{ x: customNode.x, y: customNode.z, yaw_deg: customNode.headingDeg, height_m: customNode.height_m ?? rigMountHeightM }];
			} else {
				body.node_ids = [selectedSensorNode.node_id];
				const h = graphNodeHeights[selectedSensorNode.node_id];
				if (typeof h === 'number') body.node_heights = { [selectedSensorNode.node_id]: h };
				vp_id = selectedSensorNode.node_id;
				heading_id = 'h_000';  // graph nodes pick first heading by default
			}
		} else if (probeMode === 'free') {
			body.custom_positions = [{ x: freeProbe.x, y: freeProbe.z, yaw_deg: freeProbe.yaw_deg, height_m: freeProbe.height_m }];
		} else if (probeMode === 'editor_view') {
			if (!editorViewProbe) captureEditorViewProbe();
			if (!editorViewProbe) return;
			body.custom_positions = [{ x: editorViewProbe.x, y: editorViewProbe.z, yaw_deg: editorViewProbe.yaw_deg, height_m: editorViewProbe.height_m }];
		} else if (probeMode === 'isaac_view') {
			probeError = 'Current Isaac View probe is not implemented yet (Slice 1 backlog).';
			return;
		}
		probeRendering = true;
		try {
			const data = await sweepOpticalNavViewpointGraph(selectedProjectId, sceneId, body);
			if (data?.batch_id) {
				probeResult = { batch_id: data.batch_id, vp_id, heading_id, modality, sensor_id: activeRigSensorId, submittedAt: Date.now() };
				graphBatchId = data.batch_id;
				graphBatchIds = [...new Set([...graphBatchIds, data.batch_id])];
				graphBatch = _mergeIntoBatch(graphBatch, data);
				pushActivity('ok', 'preview:probe', `Probe submitted (${probeMode}) → batch ${data.batch_id}`);
			}
		} catch (err) {
			probeError = errorMessage(err);
			pushActivity('error', 'preview:probe', probeError);
		} finally {
			probeRendering = false;
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
			const data = await sweepOpticalNavViewpointGraph(selectedProjectId, sceneId, body);
			if (data?.batch_id) {
				graphBatchId = data.batch_id;
				graphBatchIds = [...new Set([...graphBatchIds, data.batch_id])];
				graphBatch = _mergeIntoBatch(graphBatch, data);
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

	function optionalJson(text: string) {
		const trimmed = text.trim();
		return trimmed ? JSON.parse(trimmed) : undefined;
	}

	async function renderEpisodes() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (renderMode === 'graph_sweep' && !requireReady(hasGraph, 'Build the viewpoint graph before running Sensor Sweep.')) return;
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
		if (renderMode === 'graph_sweep') {
			if (!sceneId) return;
			const data = await run(() => sweepOpticalNavViewpointGraph(selectedProjectId, sceneId, body), 'Graph sensor sweep submitted.', 'graph:sweep');
			if (data?.batch_id) {
				graphBatchId = data.batch_id;
				graphBatchIds = [...new Set([...graphBatchIds, data.batch_id])];
				graphBatch = _mergeIntoBatch(graphBatch, data);
				startBatchPolling();
			}
		} else {
			body.split = renderSplit;
			const data = await run(() => renderOpticalNavEpisodes(selectedProjectId, body), 'Episode render request submitted.', 'episodes:render');
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
		if (renderMode === 'graph_sweep') {
			if (!graphBatchIds.length) return;
			const prevCompleted = graphBatch?.progress?.completed ?? 0;
			const batches = await Promise.all(
				graphBatchIds.map(id => getOpticalNavGraphRenderBatch(selectedProjectId, id).catch(() => null))
			);
			let merged: any = null;
			for (const b of batches) {
				if (b) merged = merged ? _mergeIntoBatch(merged, b) : b;
			}
			if (merged) graphBatch = merged;
			_refreshBatchLogs();
			if ((merged?.progress?.completed ?? 0) !== prevCompleted) scanObservations();
		} else {
			if (!renderBatchId) return;
			const data = await run(() => getOpticalNavRenderBatch(selectedProjectId, renderBatchId), undefined, 'batch:episodes');
			if (data) renderBatch = data;
		}
	}

	function stopBatchPolling() {
		if (batchPollTimer !== null) {
			clearInterval(batchPollTimer);
			batchPollTimer = null;
		}
	}

	function startBatchPolling() {
		stopBatchPolling();
		batchPollTimer = setInterval(async () => {
			await refreshBatch();
			const batch = renderMode === 'graph_sweep' ? graphBatch : renderBatch;
			// 'building': daemon is still enqueuing jobs in background — keep polling.
			// 'error': submission failed — stop polling.
			const status = batch?.status;
			if (status === 'building') return;
			const total = batch?.progress?.total ?? 0;
			const done = (batch?.progress?.completed ?? 0) + (batch?.progress?.failed ?? 0);
			if (status === 'error' || (total > 0 && done >= total)) {
				stopBatchPolling();
				// Release persisted entry — work has reached a terminal state.
				const key = _batchStorageKey();
				if (key) { try { window.sessionStorage.removeItem(key); } catch { /* silent */ } }
			}
		}, 4000);
	}

	async function _refreshBatchLogs() {
		if (!selectedProjectId || !graphBatchId || renderMode !== 'graph_sweep') return;
		try {
			const data = await getOpticalNavGraphBatchLogs(selectedProjectId, graphBatchId, 20);
			if (Array.isArray(data?.entries)) batchLogEntries = data.entries;
		} catch { /* silent */ }
	}

	async function validateDataset(requireObservations = false) {
		if (!selectedProjectId) return;
		const data = await run(
			() => validateOpticalNavDataset(selectedProjectId, { require_observations: requireObservations }),
			'Dataset validation completed.',
			'dataset:validate'
		);
		if (data) validationReport = data;
	}

	async function evaluateDataset() {
		if (!selectedProjectId) return;
		const data = await run(
			() => evaluateOpticalNavDataset(selectedProjectId, { policy: 'shortest_oracle', success_radius: 0.5 }),
			'Evaluation completed.',
			'dataset:evaluate'
		);
		if (data) evaluationReport = data;
	}

	async function exportDataset() {
		if (!selectedProjectId) return;
		const data = await run(() => exportOpticalNavDataset(selectedProjectId, { zip: true }), 'Dataset exported.', 'dataset:export');
		if (data) exportResult = data;
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
			assetThumbRefreshTick += 1;
			if (ticks >= 12) window.clearInterval(thumbTimer);
		}, 2500);
		return () => window.clearInterval(thumbTimer);
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

<div class="dataset-page" class:bottom-open={!$bottomPanelCollapsed} class:bottom-closed={$bottomPanelCollapsed} class:scene-active={true}>
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
				geometryKey={`${currentUsdRef}:${editorGeometryRefreshToken}`}
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
				onGroundPointerDown={handleGroundPointerDown}
				onGroundPointerMove={handleGroundPointerMove}
				onGroundPointerUp={handleGroundPointerUp}
				preloadSourcePath={placementTool === 'usd_asset' && selectedUsdAsset?.source_format !== 'glb' ? (selectedUsdAsset?.source_path ?? '') : ''}
				preloadUsdRef={placementTool === 'usd_asset' && selectedUsdAsset?.source_format !== 'glb' ? (selectedUsdAsset?.usd_ref ?? '') : ''}
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
				highlightedPath={selectedEpisodePath}
				allEpisodePaths={pageMode === 'export' ? allEpisodePaths : []}
				mapBounds={{ w: mapWidth, h: mapHeight }}
				onStatus={(message) => (editor3DStatus = message)}
				observationScan={pageMode === 'sensors' ? observationScan : null}
				frustumMode={pageMode === 'sensors' ? frustumMode : 'none'}
				frustumModality={activeRenderModality}
				frustumSensorId={activeRigSensorId}
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
				addEdgeGhostColor={edgeInspectorMode ? 0xa855f7 : 0x22c55e}
				addEdgeMaxLengthM={Number(maxEdgeLength)}
				roomShell={roomShell}
				showRoomShell={showRoomShell}
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
						Click to place {placementTool === 'usd_asset' ? usdAssetLabel(selectedUsdAsset) : placementTool} · Esc cancel
					{:else if placementTool !== 'select'}
						Drag rectangle · Esc cancel
					{:else}
						Right-drag orbit · Wheel zoom · Left-click select
					{/if}
				</span>
				<div style="flex:1"></div>
			</div>

			{#if pageMode === 'map'}
				<div class="map-float-asset-catalog build-catalog">
					<div class="catalog-head">
						<div>
							<div class="panel-label">Build Catalog</div>
							<small>Structure and navigation layers.</small>
						</div>
					</div>
					<div class="catalog-tools">
						<button class:active={placementTool === 'select'} onclick={() => { placementTool = 'select'; draftPoint = null; linePreview = null; }}>Select</button>
						<button class="danger" disabled={!selectedAuthoringId} onclick={deleteSelectedAuthoringItem}>Delete</button>
					</div>
					<div class="asset-card-list">
						{#each builtInBuildAssets as asset}
							<button
								class:selected={placementTool === asset.tool}
								class="asset-card"
								title={asset.label}
								onclick={() => selectBuiltInAsset(asset.tool)}
							>
								<AssetThumb3D category={asset.category} assetType={asset.tool} bounds={asset.bounds} selected={placementTool === asset.tool} />
								<span>{asset.label}</span>
								<small>{asset.hint}</small>
							</button>
						{/each}
					</div>
				</div>
			{:else if pageMode === 'objects'}
				<div class="map-float-asset-catalog">
					<div class="catalog-head">
						<div>
							<div class="panel-label">Place Catalog</div>
							<small>Furniture and landmarks.</small>
						</div>
					</div>
					<div class="catalog-tools">
						<button class:active={placementTool === 'select'} onclick={() => { placementTool = 'select'; draftPoint = null; linePreview = null; }}>Select</button>
						<button class="danger" disabled={!selectedAuthoringId} onclick={deleteSelectedAuthoringItem}>Delete</button>
					</div>
					<div class="asset-section-title">Built-in Assets</div>
					{#each builtInPlaceAssetGroups as group}
						<div class="asset-subsection-title">{group.label}</div>
						<div class="asset-card-list">
							{#each group.assets as asset}
								{@const isRichAsset = asset.kind === 'rich_asset'}
								{@const richSelected = isRichAsset && selectedUsdAssetId === asset.asset_id && placementTool === 'usd_asset'}
								{@const primitiveSelected = !isRichAsset && placementTool === asset.tool}
								<button
									class:selected={richSelected || primitiveSelected}
									class="asset-card"
									title={isRichAsset ? `${asset.label} · ${asset.source_dataset}` : asset.label}
									onclick={() => selectBuiltInPlaceAsset(asset)}
								>
									<AssetThumb3D
										category={asset.category}
										assetType={isRichAsset ? asset.category : asset.tool}
										bounds={asset.bounds}
										selected={richSelected || primitiveSelected}
									/>
									<span>{asset.label}</span>
									<small>{isRichAsset ? `${asset.source_dataset} · point placement` : placementHintForTool(asset.tool)}</small>
								</button>
							{/each}
						</div>
					{/each}
					<div class="catalog-divider"></div>
					<div class="asset-section-title">Library Assets</div>
					<input class="asset-search" type="search" placeholder="Search {mapAssets.length} assets..." bind:value={usdCatalogSearch} />
					{#if !usdCatalogSearch.trim() && mapAssets.length > LIBRARY_DISPLAY_LIMIT}
						<small class="catalog-status">Showing {LIBRARY_DISPLAY_LIMIT} of {mapAssets.length} — search to filter all</small>
					{:else}
						<small class="catalog-status">{mapAssetStatus}</small>
					{/if}
					<div class="asset-card-list library-assets">
						{#each usdAssetCandidates as asset}
							{@const assetId = asset.asset_id ?? asset.id}
							<button
								class:selected={selectedUsdAssetId === assetId && placementTool === 'usd_asset'}
								class="asset-card"
								title={asset.source_path}
								onclick={() => { selectedUsdAssetId = assetId; placementTool = 'usd_asset'; draftPoint = null; }}
							>
								<div class="asset-thumb-img" aria-hidden="true">
									<img
										src={selectedProjectId ? `${opticalNavAssetThumbnailUrl(selectedProjectId, assetId)}&r=${assetThumbRefreshTick}` : ''}
										alt=""
										loading="lazy"
										draggable="false"
									/>
								</div>
								<span>{usdAssetLabel(asset)}</span>
								<small>{asset.category} · {asset.placement}</small>
							</button>
						{/each}
						{#if usdAssetCandidates.length === 0}
							<div class="catalog-empty">
								No selected USD assets yet.
								<a href="/assets">Open Asset Library</a>
							</div>
						{/if}
					</div>
				</div>
			{/if}

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
				<div class="map-float-inspector sensor-panel">
					<!-- Render scene sync status -->
					{#if !renderSceneSynced}
						<div class="sensor-sync-warning">
							<span>Render scene not synced</span>
							<button class="button button-subtle" disabled={loading || !selectedProjectId || !hasScene} onclick={syncRenderScene} style="display:none">Sync Render Scene</button>
						</div>
					{/if}
	
				<div class="camera-rig-panel">
					<div class="rail-title">Robot Camera Rig</div>
					<div class="render-profile-row">
						<span class="chip-dim">{globalCameraRig?.base_frame ?? authoringMap?.camera_rig?.base_frame ?? 'base_link'}</span>
						<a class="button button-subtle" href="/camera_rig">Open Camera Rig Editor</a>
						<button class="button button-subtle" disabled={loading} onclick={loadGlobalCameraRig}>Reload</button>
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
				<!-- Sensor rays display mode -->
					<div class="sensor-rays-row">
						<span class="sensor-rays-label">Sensor Rays</span>
						<select class="sensor-rays-select" bind:value={frustumMode}>
							<option value="none">None</option>
							<option value="view-aligned">View-aligned</option>
							<option value="selected">Selected only</option>
						</select>
					</div>
					<!-- Add custom sensor button -->
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
							{(selectedSensorNode as any).isCustom ? 'Custom Camera' : 'Graph Viewpoint'}
						</div>
						<div class="sensor-node-id">{selectedSensorNodeId}</div>
						<div class="sensor-pos">x={selectedSensorNode.position?.[0]?.toFixed(2)} z={selectedSensorNode.position?.[1]?.toFixed(2)}</div>
						{#if selectedCustomSensorNode}
							<label class="sensor-heading-label">
								<span>Heading {selectedCustomSensorNode.headingDeg}°</span>
								<input type="range" min="0" max="359" step="5"
									bind:value={selectedCustomSensorNode.headingDeg}
									oninput={() => { customSensorNodes = [...customSensorNodes]; sensorRenderResult = null; }}
								/>
							</label>
							<button class="button button-subtle full sensor-del"
								onclick={() => { customSensorNodes = customSensorNodes.filter(n => n.id !== selectedSensorNodeId); selectedSensorNodeId = ''; }}>
								Remove
							</button>
						{/if}
						<!-- Modality tabs -->
						<div class="modality-tabs rig-derived-tabs" title="Derived from Robot Camera Rig sensors">
							{#each rigSensorOptions as option}
								<button class:active-tab={activeRigSensorId === option.sensor_id} onclick={() => selectRigRenderSensor(option.sensor_id)}>
									<span>{option.label}</span>
									<small>{sensorRenderChipLabel(option)}</small>
								</button>
							{/each}
						</div>
						<!-- Render config status -->
						<div class="sensor-config-row">
							{#if sceneStateText.trim() && cameraSpecText.trim()}
								<span class="chip-ok">Config ready ({renderConfig?.source ?? 'custom'})</span>
							{:else}
								<span class="chip-warn" title={renderConfigError || undefined}>No render config{renderConfigError ? ' ⚠' : ''}</span>
							{/if}
							<button class="button button-subtle" onclick={loadRenderConfig} title="Auto-load render config from scene catalog">Load</button>
						</div>
						{#if sceneStateText.trim()}
							{@const _ref = (optionalJson(sceneStateText) as any)?.mitsuba_scene_ref}
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
									{@const hasModality = headingHasSensorModality(hdata, activeModalityTab)}
									{#if hasModality}
										<img class="obs-thumb" src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, selectedSensorNodeId, hid, activeModalityTab, activeRigSensorId)} alt={`${hid} ${activeModalityTab}`} title={`${hid} · ${activeRigSensorId || 'legacy'} · ${activeModalityTab}`} loading="lazy" />
									{:else}
										<div class="obs-thumb obs-thumb-empty" title={`${hid} · ${activeModalityTab} not rendered`}><span>{parseInt(hid.replace('h_',''))||0}°</span></div>
									{/if}
								{/each}
							</div>
						{/if}
						{#if sensorRenderResult}
							<div class="sensor-result">
								<span class="chip-ok">Batch {sensorRenderResult.batch_id?.slice(0,8)}...</span>
								<button class="button button-subtle" onclick={refreshBatch}>Refresh</button>
							</div>
						{/if}
						<button class="button button-primary full" disabled={renderingViewpoint || !selectedProjectId || !renderSceneSynced || (!(selectedSensorNode as any).isCustom && !hasGraph) || (!sceneStateText.trim() || !cameraSpecText.trim())} onclick={renderSensorViewpoint}>
							{renderingViewpoint ? 'Sweeping...' : 'Graph Sweep · this viewpoint'}
						</button>
						<button class="button button-subtle full" disabled={loading || !selectedProjectId || !renderSceneSynced || !hasGraph} onclick={renderEpisodes}>
							Graph Sweep · all viewpoints
						</button>
					{:else}
						<div class="sensor-hint">Click a viewpoint (blue dot) to select it</div>
					{/if}
				</div>
			{/if}

			<!-- Export mode panel -->
			{#if pageMode === 'export'}
				<div class="map-float-inspector export-panel">
					<div class="panel-label">Export Readiness</div>
					<div class="export-readiness-list">
						<div class="readiness-item" class:ok={hasScene}>
							<span class="readiness-dot"></span><span>Scene</span>
						</div>
						<div class="readiness-item" class:ok={hasMap}>
							<span class="readiness-dot"></span><span>Traversable grid</span>
						</div>
						<div class="readiness-item" class:ok={hasGraph}>
							<span class="readiness-dot"></span><span>Viewpoint graph</span>
						</div>
						<div class="readiness-item" class:ok={hasEpisodes}>
							<span class="readiness-dot"></span><span>Episodes ({episodes.length})</span>
						</div>
						<div class="readiness-item" class:ok={validationPassed}>
							<span class="readiness-dot"></span><span>Validated</span>
						</div>
					</div>
					{#if effectiveRenderReadiness?.errors?.length}
					<div class="readiness-errors">
						{#each effectiveRenderReadiness.errors.slice(0, 4) as item}
							<div>{item.label ?? item.key}: {item.message}</div>
						{/each}
					</div>
				{/if}
				{#if graphPayloadSummary}
						<div class="panel-label mt-2">Dataset Stats</div>
						<div class="export-stats">
							<div class="stat-row"><span>Viewpoints</span><span>{graphPayloadSummary.node_count}</span></div>
							<div class="stat-row"><span>Edges</span><span>{graphPayloadSummary.edge_count}</span></div>
							<div class="stat-row"><span>Hazard edges</span><span>{graphPayloadSummary.hazard_edge_count ?? 0}</span></div>
							<div class="stat-row"><span>Episodes</span><span>{episodes.length}</span></div>
							{#if splitCounts.train != null}
								<div class="stat-row"><span>Train</span><span>{splitCounts.train}</span></div>
								<div class="stat-row"><span>Val seen</span><span>{splitCounts.val_seen ?? 0}</span></div>
								<div class="stat-row"><span>Val unseen</span><span>{splitCounts.val_unseen ?? 0}</span></div>
							{/if}
						</div>
					{/if}
					{#if allEpisodePaths.length > 0}
						<div class="export-path-legend mt-2">
							<span class="legend-swatch normal"></span><span>Normal path</span>
							<span class="legend-swatch hazard"></span><span>Hazard path ({allEpisodePaths.filter(p => p.hasHazard).length})</span>
						</div>
					{/if}
					{#if validationReport}
						<div class="export-validation" class:validation-ok={validationReport.ok !== false} class:validation-fail={validationReport.ok === false}>
							Validation: {validationReport.ok !== false ? 'passed' : 'failed'}
							{#if validationReport.errors?.length}<span class="val-errors"> · {validationReport.errors.length} error(s)</span>{/if}
						</div>
					{/if}
					<button class="button button-subtle full mt-2" disabled={!selectedProjectId || loading} onclick={() => validateDataset(false)}>
						{loading ? 'Validating...' : 'Validate Dataset'}
					</button>
					<button class="button button-primary full" disabled={!selectedProjectId || !hasEpisodes || loading} onclick={exportDataset}>
						{loading ? 'Exporting...' : 'Export Dataset'}
					</button>
					{#if exportPath}
						<div class="export-path-display">
							<span class="chip-ok">Exported</span>
							<span class="export-path-text" title={exportPath}>{exportPath.split('/').slice(-2).join('/')}</span>
						</div>
					{/if}
				</div>
			{/if}

			<!-- Floating right inspector (only when item selected in build/place mode) -->
			{#if selectedAuthoringItem && (pageMode === 'map' || pageMode === 'objects')}
					<div class="map-float-inspector" class:material-panel={inspectorTab === 'material'}>
						<div class="inspector-head">
							<div>
								<div class="panel-label">Selected</div>
								<div class="inspector-id">{selectedAuthoringItem.id}</div>
							</div>
							{#if authoringMapDirty}<span class="dirty-pill">Unsaved</span>{/if}
						</div>
						<div class="inspector-badges">
							<span>{selectedAuthoringKind || 'item'}</span>
							<span>{selectedAuthoringItem.type}</span>
						</div>
						<div class="inspector-tabs">
							<button class:active={inspectorTab === 'object'} onclick={() => (inspectorTab = 'object')}>Object</button>
							<button class:active={inspectorTab === 'material'} disabled={selectedAuthoringKind !== 'object'} onclick={() => (inspectorTab = 'material')}>Material</button>
						</div>
						{#if inspectorTab === 'object'}
							<label>
								<span>label</span>
								<input
									value={selectedAuthoringItem.label ?? ''}
									oninput={(event) => updateSelectedField('label', (event.currentTarget as HTMLInputElement).value)}
								/>
							</label>
							{#if selectedAuthoringKind === 'object'}
								<div class="material-summary-row">
									{#if materialPreviewSource(selectedAuthoringItem.material)}
										<img src={materialPreviewSource(selectedAuthoringItem.material)} alt="" loading="lazy" />
									{:else}
										<span class="material-empty-thumb">none</span>
									{/if}
									<div>
										<div class="material-mini-label">Material</div>
										<strong>{materialDisplayLabel(selectedAuthoringItem.material)}</strong>
										<small>{selectedMaterialInfo?.kind ?? 'preset/custom'}</small>
									</div>
									<button class="button button-subtle" onclick={() => (inspectorTab = 'material')}>Change</button>
								</div>
								{#if selectedAuthoringItem.source_ref}
									<div class="material-info">
										<strong>USD source</strong>
										<small>{selectedAuthoringItem.source_ref}</small>
									</div>
								{/if}
							{/if}
							<div class="preset-row">
								<button class="button button-subtle" onclick={() => applyInspectorPreset('glass')}>Glass</button>
								<button class="button button-subtle" onclick={() => applyInspectorPreset('mirror')}>Mirror</button>
								<button class="button button-subtle" onclick={() => applyInspectorPreset('landmark')}>Landmark</button>
								<button class="button button-subtle" onclick={() => applyInspectorPreset('traversable')}>Walkable</button>
							</div>
							{#if selectedAuthoringItem.geometry?.type === 'point'}
								<div class="rotation-row">
									<button title="Rotate left 45° (Q)" onclick={() => rotateSelectedPoint(-45)}>↺ 45°</button>
									<div>
										<strong>{Math.round(selectedAuthoringItem.geometry.yaw_deg ?? 0)}°</strong>
										<small>Q/E rotate · [/]</small>
									</div>
									<button title="Rotate right 45° (E)" onclick={() => rotateSelectedPoint(45)}>45° ↻</button>
								</div>
							{/if}
							<details class="inspector-section geometry-advanced">
								<summary>Advanced geometry</summary>
								<p class="inline-hint">Use the scene handles for common edits. Numeric values are for precise adjustment.</p>
								{#if selectedAuthoringItem.geometry?.type === 'point'}
									<div class="geometry-grid">
										<label><span>Position X</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.center?.[0] ?? 0} oninput={(event) => updateSelectedPointGeometry('x', (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>Position Y</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.center?.[1] ?? 0} oninput={(event) => updateSelectedPointGeometry('y', (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>Yaw</span><input type="number" step="1" value={selectedAuthoringItem.geometry.yaw_deg ?? 0} oninput={(event) => updateSelectedPointGeometry('yaw_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Width</span><input type="number" min="0.01" step="0.01" value={selectedAuthoringItem.geometry.size_m?.[0] ?? 0.5} oninput={(event) => updateSelectedDimension('size_x', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Height</span><input type="number" min="0.01" step="0.01" value={selectedAuthoringItem.geometry.size_m?.[1] ?? 1.2} oninput={(event) => updateSelectedDimension('size_y', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Depth</span><input type="number" min="0.01" step="0.01" value={selectedAuthoringItem.geometry.size_m?.[2] ?? 0.5} oninput={(event) => updateSelectedDimension('size_z', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Base H</span><input type="number" step="0.01" value={selectedAuthoringItem.geometry.base_height_m ?? 0} oninput={(event) => updateSelectedDimension('base_height_m', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Pitch</span><input type="number" step="1" value={selectedAuthoringItem.geometry.pitch_deg ?? 0} oninput={(event) => updateSelectedDimension('pitch_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Roll</span><input type="number" step="1" value={selectedAuthoringItem.geometry.roll_deg ?? 0} oninput={(event) => updateSelectedDimension('roll_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
									</div>
								{:else if selectedAuthoringItem.geometry?.type === 'line'}
									<div class="geometry-grid">
										<label><span>Start X</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.start?.[0] ?? 0} oninput={(event) => updateSelectedLineGeometry('start_x', (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>Start Y</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.start?.[1] ?? 0} oninput={(event) => updateSelectedLineGeometry('start_y', (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>End X</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.end?.[0] ?? 0} oninput={(event) => updateSelectedLineGeometry('end_x', (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>End Y</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.end?.[1] ?? 0} oninput={(event) => updateSelectedLineGeometry('end_y', (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>Height</span><input type="number" min="0.001" step="0.1" value={selectedAuthoringItem.geometry.height_m ?? 2.4} oninput={(event) => updateSelectedLineGeometry('height_m', (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>Thickness</span><input type="number" min="0.001" step="0.01" value={selectedAuthoringItem.geometry.thickness_m ?? 0.08} oninput={(event) => updateSelectedLineGeometry('thickness_m', (event.currentTarget as HTMLInputElement).value)} /></label>
									</div>
								{:else if selectedAuthoringItem.geometry?.type === 'rectangle'}
									<div class="geometry-grid">
										<label><span>x0</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.bounds?.[0] ?? 0} oninput={(event) => updateSelectedRectangleBound(0, (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>y0</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.bounds?.[1] ?? 0} oninput={(event) => updateSelectedRectangleBound(1, (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>x1</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.bounds?.[2] ?? 1} oninput={(event) => updateSelectedRectangleBound(2, (event.currentTarget as HTMLInputElement).value)} /></label>
										<label><span>y1</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.bounds?.[3] ?? 1} oninput={(event) => updateSelectedRectangleBound(3, (event.currentTarget as HTMLInputElement).value)} /></label>
									</div>
								{/if}
								{#if inspectorError}<p class="inline-error">{inspectorError}</p>{/if}
							</details>
							<div class="inspector-section">
								<div class="panel-label">Navigation</div>
								<div class="flag-grid">
									<label><input type="checkbox" checked={selectedAuthoringItem.navigation?.blocks_navigation ?? false} onchange={(event) => updateSelectedNavigation('blocks_navigation', (event.currentTarget as HTMLInputElement).checked)} /> Blocks robot</label>
									<label><input type="checkbox" checked={selectedAuthoringItem.navigation?.include_in_hazard_mask ?? false} onchange={(event) => updateSelectedNavigation('include_in_hazard_mask', (event.currentTarget as HTMLInputElement).checked)} /> Hazard mask</label>
									<label><input type="checkbox" checked={selectedAuthoringItem.navigation?.instruction_candidate ?? false} onchange={(event) => updateSelectedNavigation('instruction_candidate', (event.currentTarget as HTMLInputElement).checked)} /> Instruction</label>
									<label><input type="checkbox" checked={selectedAuthoringItem.navigation?.goal_candidate ?? false} onchange={(event) => updateSelectedNavigation('goal_candidate', (event.currentTarget as HTMLInputElement).checked)} /> Goal</label>
								</div>
								<label>
									<span>hazard_type</span>
									<select
										value={selectedAuthoringItem.navigation?.hazard_type ?? ''}
										onchange={(event) => updateSelectedNavigation('hazard_type', (event.currentTarget as HTMLSelectElement).value)}
									>
										{#each hazardTypes as ht}
											<option value={ht}>{ht || 'none'}</option>
										{/each}
									</select>
								</label>
							</div>
							<div class="inspector-section">
								<div class="panel-label">Light source</div>
								{#if detectedEmitterIds.has(selectedAuthoringItem.id) && !selectedAuthoringItem.is_emitter}
									<p class="emitter-hint">🔆 Detected light fixture — enable to render as an area emitter.</p>
								{/if}
								<label class="flag-grid"><input type="checkbox" checked={selectedAuthoringItem.is_emitter ?? false} onchange={(event) => updateSelectedField('is_emitter', (event.currentTarget as HTMLInputElement).checked)} /> Use as light source</label>
								{#if selectedAuthoringItem.is_emitter}
									<label>
										<span>Intensity ({(selectedAuthoringItem.emitter_intensity ?? 1.0).toFixed(2)}×)</span>
										<input type="range" min="0.1" max="20" step="0.1"
											value={selectedAuthoringItem.emitter_intensity ?? 1.0}
											oninput={(event) => updateSelectedField('emitter_intensity', parseFloat((event.currentTarget as HTMLInputElement).value))}
										/>
									</label>
								{/if}
							</div>
							<button class="button button-subtle full danger" onclick={deleteSelectedAuthoringItem}>Delete {selectedAuthoringId}</button>
						{:else}
							<div class="material-workspace">
								<div class="material-picker-top">
									<input class="material-search" placeholder="Search material name, tag, collection..." bind:value={materialPickerSearch} />
									<select bind:value={materialPickerCollection}>
										<option value="all">All collections</option>
										<option value="preset">Presets</option>
										{#each materialCollections as [collectionId, collectionLabel]}
											<option value={collectionId}>{collectionLabel}</option>
										{/each}
									</select>
								</div>
								<div class="material-category-tabs">
									{#each ['recommended','glass','mirror','wall','floor','furniture','hazard','all'] as category}
										<button class:active={materialPickerCategory === category} onclick={() => (materialPickerCategory = category)}>{category}</button>
									{/each}
								</div>
								<div class="material-grid-browser">
									<div class="material-card-grid">
										<button class:selected={!selectedAuthoringItem.material && !materialPreviewValue} onclick={() => chooseMaterial('')}>
											<span class="material-empty-thumb">none</span>
											<strong>No material</strong>
											<small>clear override</small>
										</button>
										{#each filteredMaterialCards as card}
											<button class:selected={(materialPreviewValue || selectedAuthoringItem.material) === card.value} onclick={() => (materialPreviewValue = card.value)}>
												{#if card.preview}<img src={card.preview} alt="" loading="lazy" />{:else}<span class="material-empty-thumb">none</span>{/if}
												<strong>{card.label}</strong>
												<small>{card.collectionLabel}</small>
												<div class="material-tag-row">
													{#each card.tags.slice(0, 3) as tag}<span>{tag}</span>{/each}
												</div>
											</button>
										{/each}
									</div>
									<div class="material-preview-panel">
										{#if materialPreviewEntry}
											{#if materialPreviewEntry.preview}<img class="material-large-preview" src={materialPreviewEntry.preview} alt="" loading="lazy" />{:else}<span class="material-large-empty">No preview</span>{/if}
											<h3>{materialPreviewEntry.label}</h3>
											<p>{materialPreviewEntry.collectionLabel} · {materialPreviewEntry.kind} · {materialPreviewEntry.status}</p>
											<div class="material-tag-row expanded">
												{#each materialPreviewEntry.tags as tag}<span>{tag}</span>{/each}
											</div>
											<div class="material-metadata">
												<div><span>Category</span><strong>{materialPreviewEntry.category}</strong></div>
												<div><span>RGB</span><strong>ready</strong></div>
												<div><span>Polarization</span><strong>{materialPreviewEntry.tags.includes('polarization-ready') ? 'ready' : 'proxy'}</strong></div>
												<div><span>NIR-like</span><strong>{materialPreviewEntry.tags.includes('NIR-ready') ? 'ready' : 'proxy'}</strong></div>
											</div>
											{#if selectedMaterialSuggestion}<p class="suggestion">{selectedMaterialSuggestion}</p>{/if}
											<div class="material-action-row">
												<button class="button button-subtle" onclick={() => chooseMaterial(materialPreviewEntry.value)}>Apply Material</button>
												<button class="button button-primary" onclick={() => applyMaterialWithSuggestedTags(materialPreviewEntry.value)}>Apply + Suggested Tags</button>
											</div>
										{:else}
											<div class="material-empty-state">No matching materials. {materialLibraryStatus}</div>
										{/if}
									</div>
								</div>
							</div>
						{/if}
					</div>
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
							<select class="scene-select" value={sceneId} onchange={(e) => { sceneId = e.currentTarget.value; sceneStateText = ''; cameraSpecText = ''; renderConfig = null; syncResult = null; renderReadiness = null; renderConfigError = ''; loadAuthoringMap(); loadRenderConfig(); episodes = []; selectedEpisode = null; selectedEpisodeId = ''; graphPayload = null; observationScan = null; graphBatch = null; graphBatchId = ''; graphBatchIds = []; stopBatchPolling(); if (pageMode === 'sensors') scanObservations(); }}>
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
						<div class="geometry-grid">
							<label><span>Environment</span><select value={authoringMap?.environment?.mode ?? 'constant'} onchange={(event) => updateEnvironmentField('mode', (event.currentTarget as HTMLSelectElement).value)}><option value="constant">constant</option><option value="envmap">envmap</option></select></label>
							<label><span>Intensity</span><input type="number" min="0" step="0.1" value={authoringMap?.environment?.intensity ?? 1} oninput={(event) => updateEnvironmentField('intensity', (event.currentTarget as HTMLInputElement).value)} /></label>
							<label><span>Rotation</span><input type="number" step="1" value={authoringMap?.environment?.rotation_deg ?? 0} oninput={(event) => updateEnvironmentField('rotation_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
							<label><span>RGB</span><input value={(authoringMap?.environment?.radiance ?? [0.8,0.8,0.85]).join(', ')} oninput={(event) => updateEnvironmentField('radiance', (event.currentTarget as HTMLInputElement).value)} /></label>
						</div>
						<label><span>HDR/EXR envmap ref</span><input value={authoringMap?.environment?.envmap_ref ?? ''} oninput={(event) => updateEnvironmentField('envmap_ref', (event.currentTarget as HTMLInputElement).value || null)} /></label>
						<div class="geometry-grid">
							<label><span>Upload envmap</span><input type="file" accept=".exr,.hdr,.png,.jpg,.jpeg,image/png,image/jpeg" disabled={envmapUploading || !selectedProjectId || !hasScene} onchange={(event) => uploadEnvmapFromInput(event.currentTarget as HTMLInputElement)} /></label>
							{#if envmapFiles.length}
								<label><span>Uploaded</span><select value={authoringMap?.environment?.envmap_ref ?? ''} onchange={(event) => { updateEnvironmentField('mode', 'envmap'); updateEnvironmentField('envmap_ref', (event.currentTarget as HTMLSelectElement).value || null); }}><option value="">Select envmap</option>{#each envmapFiles as item}<option value={item.envmap_ref}>{item.filename}{#if item.size_bytes} · {envmapSizeLabel(item.size_bytes)}{/if}</option>{/each}</select></label>
							{/if}
						</div>
						<label class="inline-check"><input type="checkbox" checked={authoringMap?.environment?.background_visible ?? true} onchange={(event) => updateEnvironmentField('background_visible', (event.currentTarget as HTMLInputElement).checked)} /> Background visible</label>
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
						{/if}
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
			<section class="rail-section rail-tool-panel">
				<div class="inspector-head">
					<div>
						<div class="rail-title">Selected</div>
						<div class="inspector-id">{selectedAuthoringItem.id}</div>
					</div>
					{#if authoringMapDirty}<span class="dirty-pill">Unsaved</span>{/if}
				</div>
				<div class="inspector-badges">
					<span>{selectedAuthoringKind || 'item'}</span>
					<span>{selectedAuthoringItem.type}</span>
				</div>
				<div class="inspector-tabs">
					<button class:active={inspectorTab === 'object'} onclick={() => (inspectorTab = 'object')}>Object</button>
					<button class:active={inspectorTab === 'material'} disabled={selectedAuthoringKind !== 'object'} onclick={() => (inspectorTab = 'material')}>Material</button>
				</div>

				{#if inspectorTab === 'object'}
					<label>
						<span>label</span>
						<input
							value={selectedAuthoringItem.label ?? ''}
							oninput={(event) => updateSelectedField('label', (event.currentTarget as HTMLInputElement).value)}
						/>
					</label>
					{#if selectedAuthoringKind === 'object'}
						<div class="material-summary-row">
							{#if materialPreviewSource(selectedAuthoringItem.material)}
								<img src={materialPreviewSource(selectedAuthoringItem.material)} alt="" loading="lazy" />
							{:else}
								<span class="material-empty-thumb">none</span>
							{/if}
							<div>
								<div class="material-mini-label">Material</div>
								<strong>{materialDisplayLabel(selectedAuthoringItem.material)}</strong>
								<small>{selectedMaterialInfo?.kind ?? 'preset/custom'}</small>
							</div>
							<button class="button button-subtle" onclick={() => (inspectorTab = 'material')}>Change</button>
						</div>
						{#if selectedAuthoringItem.source_ref}
							<div class="material-info">
								<strong>USD source</strong>
								<small>{selectedAuthoringItem.source_ref}</small>
							</div>
						{/if}
					{/if}
					<div class="preset-row">
						<button class="button button-subtle" onclick={() => applyInspectorPreset('glass')}>Glass</button>
						<button class="button button-subtle" onclick={() => applyInspectorPreset('mirror')}>Mirror</button>
						<button class="button button-subtle" onclick={() => applyInspectorPreset('landmark')}>Landmark</button>
						<button class="button button-subtle" onclick={() => applyInspectorPreset('traversable')}>Walkable</button>
					</div>
					{#if selectedAuthoringItem.geometry?.type === 'point'}
						<div class="rotation-row">
							<button title="Rotate left 45° (Q)" onclick={() => rotateSelectedPoint(-45)}>↺ 45°</button>
							<div>
								<strong>{Math.round(selectedAuthoringItem.geometry.yaw_deg ?? 0)}°</strong>
								<small>Q/E rotate · [/]</small>
							</div>
							<button title="Rotate right 45° (E)" onclick={() => rotateSelectedPoint(45)}>45° ↻</button>
						</div>
					{/if}
					<details class="inspector-section geometry-advanced">
						<summary>Advanced geometry</summary>
						<p class="inline-hint">Use the scene handles for common edits. Numeric values are for precise adjustment.</p>
						{#if selectedAuthoringItem.geometry?.type === 'point'}
							<div class="geometry-grid">
								<label><span>Position X</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.center?.[0] ?? 0} oninput={(event) => updateSelectedPointGeometry('x', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Position Y</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.center?.[1] ?? 0} oninput={(event) => updateSelectedPointGeometry('y', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Yaw</span><input type="number" step="1" value={selectedAuthoringItem.geometry.yaw_deg ?? 0} oninput={(event) => updateSelectedPointGeometry('yaw_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Width</span><input type="number" min="0.01" step="0.01" value={selectedAuthoringItem.geometry.size_m?.[0] ?? 0.5} oninput={(event) => updateSelectedDimension('size_x', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Height</span><input type="number" min="0.01" step="0.01" value={selectedAuthoringItem.geometry.size_m?.[1] ?? 1.2} oninput={(event) => updateSelectedDimension('size_y', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Depth</span><input type="number" min="0.01" step="0.01" value={selectedAuthoringItem.geometry.size_m?.[2] ?? 0.5} oninput={(event) => updateSelectedDimension('size_z', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Base H</span><input type="number" step="0.01" value={selectedAuthoringItem.geometry.base_height_m ?? 0} oninput={(event) => updateSelectedDimension('base_height_m', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Pitch</span><input type="number" step="1" value={selectedAuthoringItem.geometry.pitch_deg ?? 0} oninput={(event) => updateSelectedDimension('pitch_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Roll</span><input type="number" step="1" value={selectedAuthoringItem.geometry.roll_deg ?? 0} oninput={(event) => updateSelectedDimension('roll_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
							</div>
						{:else if selectedAuthoringItem.geometry?.type === 'line'}
							<div class="geometry-grid">
								<label><span>Start X</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.start?.[0] ?? 0} oninput={(event) => updateSelectedLineGeometry('start_x', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Start Y</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.start?.[1] ?? 0} oninput={(event) => updateSelectedLineGeometry('start_y', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>End X</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.end?.[0] ?? 0} oninput={(event) => updateSelectedLineGeometry('end_x', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>End Y</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.end?.[1] ?? 0} oninput={(event) => updateSelectedLineGeometry('end_y', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Height</span><input type="number" min="0.001" step="0.1" value={selectedAuthoringItem.geometry.height_m ?? 2.4} oninput={(event) => updateSelectedLineGeometry('height_m', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Thickness</span><input type="number" min="0.001" step="0.01" value={selectedAuthoringItem.geometry.thickness_m ?? 0.08} oninput={(event) => updateSelectedLineGeometry('thickness_m', (event.currentTarget as HTMLInputElement).value)} /></label>
							</div>
						{:else if selectedAuthoringItem.geometry?.type === 'rectangle'}
							<div class="geometry-grid">
								<label><span>x0</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.bounds?.[0] ?? 0} oninput={(event) => updateSelectedRectangleBound(0, (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>y0</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.bounds?.[1] ?? 0} oninput={(event) => updateSelectedRectangleBound(1, (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>x1</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.bounds?.[2] ?? 1} oninput={(event) => updateSelectedRectangleBound(2, (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>y1</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.bounds?.[3] ?? 1} oninput={(event) => updateSelectedRectangleBound(3, (event.currentTarget as HTMLInputElement).value)} /></label>
							</div>
						{/if}
						{#if inspectorError}<p class="inline-error">{inspectorError}</p>{/if}
					</details>
					<div class="inspector-section">
						<div class="rail-title">Navigation</div>
						<div class="flag-grid">
							<label><input type="checkbox" checked={selectedAuthoringItem.navigation?.blocks_navigation ?? false} onchange={(event) => updateSelectedNavigation('blocks_navigation', (event.currentTarget as HTMLInputElement).checked)} /> Blocks robot</label>
							<label><input type="checkbox" checked={selectedAuthoringItem.navigation?.include_in_hazard_mask ?? false} onchange={(event) => updateSelectedNavigation('include_in_hazard_mask', (event.currentTarget as HTMLInputElement).checked)} /> Hazard mask</label>
							<label><input type="checkbox" checked={selectedAuthoringItem.navigation?.instruction_candidate ?? false} onchange={(event) => updateSelectedNavigation('instruction_candidate', (event.currentTarget as HTMLInputElement).checked)} /> Instruction</label>
							<label><input type="checkbox" checked={selectedAuthoringItem.navigation?.goal_candidate ?? false} onchange={(event) => updateSelectedNavigation('goal_candidate', (event.currentTarget as HTMLInputElement).checked)} /> Goal</label>
						</div>
						<label>
							<span>hazard_type</span>
							<select
								value={selectedAuthoringItem.navigation?.hazard_type ?? ''}
								onchange={(event) => updateSelectedNavigation('hazard_type', (event.currentTarget as HTMLSelectElement).value)}
							>
								{#each hazardTypes as ht}
									<option value={ht}>{ht || 'none'}</option>
								{/each}
							</select>
						</label>
					</div>
					<button class="button button-subtle full danger" onclick={deleteSelectedAuthoringItem}>Delete {selectedAuthoringId}</button>
				{:else}
					<div class="material-workspace">
						<div class="material-picker-top">
							<input class="material-search" placeholder="Search material name, tag, collection..." bind:value={materialPickerSearch} />
							<select bind:value={materialPickerCollection}>
								<option value="all">All collections</option>
								<option value="preset">Presets</option>
								{#each materialCollections as [collectionId, collectionLabel]}
									<option value={collectionId}>{collectionLabel}</option>
								{/each}
							</select>
						</div>
						<div class="material-category-tabs">
							{#each ['recommended','glass','mirror','wall','floor','furniture','hazard','all'] as category}
								<button class:active={materialPickerCategory === category} onclick={() => (materialPickerCategory = category)}>{category}</button>
							{/each}
						</div>
						<div class="material-grid-browser">
							<div class="material-card-grid">
								<button class:selected={!selectedAuthoringItem.material && !materialPreviewValue} onclick={() => chooseMaterial('')}>
									<span class="material-empty-thumb">none</span>
									<strong>No material</strong>
									<small>clear override</small>
								</button>
								{#each filteredMaterialCards as card}
									<button class:selected={(materialPreviewValue || selectedAuthoringItem.material) === card.value} onclick={() => (materialPreviewValue = card.value)}>
										{#if card.preview}<img src={card.preview} alt="" loading="lazy" />{:else}<span class="material-empty-thumb">none</span>{/if}
										<strong>{card.label}</strong>
										<small>{card.collectionLabel}</small>
										<div class="material-tag-row">
											{#each card.tags.slice(0, 3) as tag}<span>{tag}</span>{/each}
										</div>
									</button>
								{/each}
							</div>
							<div class="material-preview-panel">
								{#if materialPreviewEntry}
									{#if materialPreviewEntry.preview}<img class="material-large-preview" src={materialPreviewEntry.preview} alt="" loading="lazy" />{:else}<span class="material-large-empty">No preview</span>{/if}
									<h3>{materialPreviewEntry.label}</h3>
									<p>{materialPreviewEntry.collectionLabel} · {materialPreviewEntry.kind} · {materialPreviewEntry.status}</p>
									<div class="material-tag-row expanded">
										{#each materialPreviewEntry.tags as tag}<span>{tag}</span>{/each}
									</div>
									<div class="material-metadata">
										<div><span>Category</span><strong>{materialPreviewEntry.category}</strong></div>
										<div><span>RGB</span><strong>ready</strong></div>
										<div><span>Polarization</span><strong>{materialPreviewEntry.tags.includes('polarization-ready') ? 'ready' : 'proxy'}</strong></div>
										<div><span>NIR-like</span><strong>{materialPreviewEntry.tags.includes('NIR-ready') ? 'ready' : 'proxy'}</strong></div>
									</div>
									{#if selectedMaterialSuggestion}<p class="suggestion">{selectedMaterialSuggestion}</p>{/if}
									<div class="material-action-row">
										<button class="button button-subtle" onclick={() => chooseMaterial(materialPreviewEntry.value)}>Apply Material</button>
										<button class="button button-primary" onclick={() => applyMaterialWithSuggestedTags(materialPreviewEntry.value)}>Apply + Suggested Tags</button>
									</div>
								{:else}
									<div class="material-empty-state">No matching materials. {materialLibraryStatus}</div>
								{/if}
							</div>
						</div>
					</div>
				{/if}
			</section>
		{/if}

		{#if railTab === 'paths'}
			<section class="rail-section rail-tool-panel footprint-panel">
				<div class="rail-title">Robot footprint</div>
				<div class="footprint-grid">
					<label><span>Robot radius (m)</span><input type="number" min="0" max="2" step="0.05" bind:value={robotRadius} /></label>
					<label><span>Min clearance (m)</span><input type="number" min="0" max="2" step="0.05" bind:value={minClearance} /></label>
				</div>
				<div class="footprint-info">Total inflated: <strong>{(Number(robotRadius) + Number(minClearance)).toFixed(2)} m</strong></div>
				<label class="footprint-toggle"><input type="checkbox" bind:checked={showFootprint} /> Show inflation overlay (3D view)</label>
				<div class="rail-title mt-2">Traversable grid</div>
				<label><span>Resolution (m)</span><input type="number" step="0.01" min="0.01" bind:value={resolution} /></label>
				<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || buildingMap} onclick={buildMap}>
					{#if buildingMap}<span class="spinner-xs"></span> Building...{:else}{hasMap ? 'Rebuild grid' : 'Build grid'}{/if}
				</button>
				<div class="rail-title mt-2">Viewpoint graph</div>
				<button class="button button-subtle" disabled={!hasMap || buildingGraph} onclick={requestBuildGraph}>
					{buildingGraph ? 'Rebuilding…' : 'Rebuild graph'}
				</button>
				{#if selectedSensorNode && !(selectedSensorNode as any).isCustom}
					<button class="button button-subtle danger" onclick={() => deleteSelectedGraphNode()}>
						Delete {selectedSensorNode.node_id}
					</button>
				{/if}
			</section>
			<section class="rail-section rail-tool-panel footprint-panel">
				<div class="rail-title">Map interaction</div>
				<div class="mode-radio-group">
					<label class="mode-radio" title="Default. Click nodes or objects to select; orbit/zoom the 3D view.">
						<input type="radio" name="pathsMode" value="select" bind:group={pathsMode} />
						<span>🖱 Select</span>
					</label>
					<label class="mode-radio" title="Click anywhere on the floor to insert a new viewpoint node at that (x, z). Node gets default headings.">
						<input type="radio" name="pathsMode" value="place_node" bind:group={pathsMode} />
						<span>📍 Place node</span>
					</label>
					<label class="mode-radio" title="Drag on the floor to mark cells as walkable (force traversable). Survives map rebuilds.">
						<input type="radio" name="pathsMode" value="paint_walkable" bind:group={pathsMode} />
						<span><span class="paint-swatch walkable"></span> Paint walkable</span>
					</label>
					<label class="mode-radio" title="Drag on the floor to mark cells as blocked (force non-traversable). Useful for closing off areas the planner shouldn't use.">
						<input type="radio" name="pathsMode" value="paint_blocked" bind:group={pathsMode} />
						<span><span class="paint-swatch blocked"></span> Paint blocked</span>
					</label>
					<label class="mode-radio" title="Drag to clear walkability paint marks in that area (restore the auto-computed mask).">
						<input type="radio" name="pathsMode" value="paint_erase" bind:group={pathsMode} />
						<span>🧽 Erase paint</span>
					</label>
					<label class="mode-radio" title="Drag a rectangle on the floor to select an area, then click 'Rebuild this region' to re-sample only that area's viewpoints.">
						<input type="radio" name="pathsMode" value="select_region" bind:group={pathsMode} />
						<span>▭ Select region</span>
					</label>
					<label class="mode-radio" title="Click two graph nodes in sequence to create a manual edge between them (shown in purple).">
						<input type="radio" name="pathsMode" value="add_edge" bind:group={pathsMode} />
						<span>⤴ Add edge</span>
					</label>
					<label class="mode-radio" title="Click two graph nodes to diagnose why no edge exists between them (distance, blocking cells, hazard).">
						<input type="radio" name="pathsMode" value="inspect_edge" bind:group={pathsMode} />
						<span>🔍 Inspect edge</span>
					</label>
				</div>
				{#if pathsMode !== 'select'}
					<div class="mode-active-banner">
						{#if pathsMode === 'place_node'}Click on the floor to place a node…
						{:else if pathsMode.startsWith('paint_')}Drag on the floor (brush radius {paintRadiusM} m)…
						{:else if pathsMode === 'select_region'}Drag a rectangle on the floor…
						{:else if pathsMode === 'add_edge'}{pendingEdgeSource ? `Source: ${pendingEdgeSource} · click target…` : 'Click first node…'}
						{:else if pathsMode === 'inspect_edge'}{edgeInspectorSource ? `Source: ${edgeInspectorSource} · click target to diagnose…` : 'Click first node…'}
						{/if}
					</div>
				{/if}
				{#if pathsMode.startsWith('paint_')}
					<label class="footprint-toggle">
						<span>Brush radius (m)</span>
						<input type="number" min="0.05" max="2" step="0.05" bind:value={paintRadiusM} class="paint-radius" />
					</label>
				{/if}
				{#if walkabilityOverlayMeta?.stats?.walkable_cells || walkabilityOverlayMeta?.stats?.blocked_cells}
					<div class="paint-info">
						<span class="chip-ok">walkable paint: {walkabilityOverlayMeta.stats.walkable_cells ?? 0}</span>
						<span class="chip-warn">blocked paint: {walkabilityOverlayMeta.stats.blocked_cells ?? 0}</span>
						<button class="button button-subtle danger" onclick={clearWalkabilityOverlay}>Clear</button>
					</div>
				{/if}
				{#if pendingRegionBbox}
					<div class="paint-info">Region: [{pendingRegionBbox[0].toFixed(1)}, {pendingRegionBbox[1].toFixed(1)} → {pendingRegionBbox[2].toFixed(1)}, {pendingRegionBbox[3].toFixed(1)}]</div>
					<button class="button button-subtle" onclick={rebuildRegion}>Rebuild this region</button>
					<button class="button button-subtle" onclick={() => (pendingRegionBbox = null)}>Cancel selection</button>
				{/if}
			</section>
			<section class="rail-section rail-tool-panel footprint-panel">
				<div class="rail-title">Display layers</div>
				<label class="footprint-toggle" title="Show a translucent red ring inset from the floor by (robot_radius + min_clearance), approximating where the robot can't go.">
					<input type="checkbox" bind:checked={showFootprint} />
					<span>Footprint inflation outline</span>
				</label>
				<label class="footprint-toggle" title="Overlay the inflated traversable grid on the floor: red = real obstacles, orange = robot-radius halo. Lets you see exactly why the planner blocks certain edges.">
					<input type="checkbox" bind:checked={showTraversableMask} onchange={() => refreshTraversableMeta()} />
					<span>Inflated obstacles mask</span>
				</label>
				{#if showTraversableMask && traversableMeta?.stats}
					<div class="paint-info">
						<span class="chip-warn">obstacles: {traversableMeta.stats.raw_obstacle_cells ?? 0}</span>
						<span style:background="#fef3c7" style:color="#92400e" style:padding="2px 6px" style:border-radius="4px">inflation halo: {traversableMeta.stats.inflation_only_cells ?? 0}</span>
					</div>
				{/if}
			</section>
			<section class="rail-section rail-tool-panel footprint-panel">
				<div class="rail-title">Edge diagnostics</div>
				{#if edgeCheckResult}
					<div class="edge-diag">
						<div class="edge-diag-title">{edgeCheckResult.source} ↔ {edgeCheckResult.target}</div>
						<div>Distance: <strong>{edgeCheckResult.distance_m?.toFixed(2)} m</strong> {edgeCheckResult.within_max_edge_length ? '✓' : `✗ (max ${edgeCheckResult.max_edge_length_m} m)`}</div>
						<div>Line check: {edgeCheckResult.blocked_cell_count > 0 ? `⚠ ${edgeCheckResult.blocked_cell_count} cells blocked` : '✓ clear'}</div>
						{#if edgeCheckResult.first_blocked_cell}
							<div class="edge-diag-detail">
								First blocked at world ({edgeCheckResult.first_blocked_cell.world?.[0]?.toFixed(2)}, {edgeCheckResult.first_blocked_cell.world?.[1]?.toFixed(2)})
								· {edgeCheckResult.first_blocked_cell.reason === 'raw_obstacle' ? 'real obstacle' : edgeCheckResult.first_blocked_cell.reason === 'inflation_halo' ? 'robot-radius halo' : edgeCheckResult.first_blocked_cell.reason}
							</div>
						{/if}
						<div>Hazard crossing: {edgeCheckResult.hazard_crossing ? '⚠ yes' : 'no'}</div>
						<div class="edge-diag-verdict" class:ok={edgeCheckResult.would_connect}>
							{edgeCheckResult.would_connect ? '✓ Would connect on next graph build' : `✗ ${edgeCheckResult.reason}`}
						</div>
						<div class="edge-diag-actions">
							<button class="button button-subtle" onclick={addEdgeAnyway}>Add edge anyway</button>
							<button class="button button-subtle" onclick={() => (edgeCheckResult = null)}>Dismiss</button>
						</div>
					</div>
				{/if}
				{#if graphPayload?.component_summary && graphPayload.component_summary.length > 0}
					<div class="footprint-divider"></div>
					<div class="panel-label">Connectivity</div>
					<div class="paint-info">
						{graphPayload.component_summary.length} component{graphPayload.component_summary.length === 1 ? '' : 's'} · {graphNodes.length} nodes total
					</div>
					{#each graphPayload.component_summary.slice(0, 5) as comp}
						<div class="component-row">
							<span class="component-dot" style:background={['#6366f1','#ef4444','#fbbf24','#a855f7','#14b8a6','#ec4899','#84cc16'][comp.index % 7]}></span>
							<span>{comp.size} node{comp.size === 1 ? '' : 's'}{comp.index === 0 ? ' (main)' : comp.size === 1 ? ' (isolated)' : ''}</span>
						</div>
					{/each}
				{/if}
				{#if graphEdges?.some?.((e: any) => e?.extras?.manual)}
					<div class="footprint-divider"></div>
					<div class="panel-label">Manual edges</div>
					<div class="lights-list">
						{#each graphEdges.filter((e: any) => e?.extras?.manual) as me (me.edge_id)}
							<div class="light-item">
								<span class="light-label">{me.source} → {me.target}</span>
								<button class="button button-subtle danger" onclick={async () => {
									try {
										await deleteOpticalNavGraphEdge(selectedProjectId, sceneId, me.edge_id);
										await loadGraph();
									} catch (err) { pushActivity('error', 'graph:edge-del', errorMessage(err)); }
								}}>Delete</button>
							</div>
						{/each}
					</div>
				{/if}
			</section>
			<section class="rail-section rail-tool-panel paths-panel">
				<div class="rail-title">Episodes ({filteredEpisodes.length})</div>
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
			</section>
		{/if}

		{#if railTab === 'sensors'}
			<section class="rail-section rail-tool-panel sensor-panel">
				<div class="rail-title">Sensor Render</div>
				{#if !renderSceneSynced}
					<div class="sensor-sync-warning">
						<span>Render scene not synced</span>
						<button class="button button-subtle" disabled={loading || !selectedProjectId || !hasScene} onclick={syncRenderScene} style="display:none">Sync Render Scene</button>
					</div>
				{/if}

				<div class="camera-rig-panel">
					<div class="rail-title">Robot Camera Rig</div>
					<div class="render-profile-row">
						<span class="chip-dim">{globalCameraRig?.base_frame ?? authoringMap?.camera_rig?.base_frame ?? 'base_link'}</span>
						<a class="button button-subtle" href="/camera_rig">Open Camera Rig Editor</a>
						<button class="button button-subtle" disabled={loading} onclick={loadGlobalCameraRig}>Reload</button>
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
				<!-- Sensor rays display mode -->
				<div class="sensor-rays-row">
					<span class="sensor-rays-label">Sensor Rays</span>
					<select class="sensor-rays-select" bind:value={frustumMode}>
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
					<div class="rail-title">
						{(selectedSensorNode as any).isCustom ? 'Custom Camera' : 'Graph Viewpoint'}
					</div>
					<div class="sensor-node-id">{selectedSensorNodeId}</div>
					<div class="sensor-pos">x={selectedSensorNode.position?.[0]?.toFixed(2)} z={selectedSensorNode.position?.[1]?.toFixed(2)}</div>
					{#if selectedCustomSensorNode}
						<label class="sensor-heading-label">
							<span>Heading {selectedCustomSensorNode.headingDeg}°</span>
							<input type="range" min="0" max="359" step="5"
								bind:value={selectedCustomSensorNode.headingDeg}
								oninput={() => { customSensorNodes = [...customSensorNodes]; sensorRenderResult = null; }}
							/>
						</label>
						<button class="button button-subtle full sensor-del"
							onclick={() => { customSensorNodes = customSensorNodes.filter(n => n.id !== selectedSensorNodeId); selectedSensorNodeId = ''; }}>
							Remove
						</button>
					{/if}
					<div class="modality-tabs rig-derived-tabs" title="Derived from Robot Camera Rig sensors">
						{#each rigSensorOptions as option}
							<button class:active-tab={activeRigSensorId === option.sensor_id} onclick={() => selectRigRenderSensor(option.sensor_id)}>
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
						<button class="button button-subtle" onclick={loadRenderConfig} title="Auto-load render config from scene catalog">Load</button>
					</div>
					<div class="sensor-config-row">
						<label class="sensor-height-label" title={selectedSensorNodeId ? 'Per-viewpoint override (rig default = ' + rigMountHeightM.toFixed(2) + 'm)' : 'Rig defaults are read-only here. Edit them in /camera_rig.'}>
							Camera height (m) {selectedSensorNodeId ? `· ${selectedSensorNodeId}` : `· ${activeRigSensorOption?.label ?? 'rig sensor'}`}
						</label>
						<input type="number" class="sensor-height-input" min="0.05" max="8" step="0.05"
							value={selectedSensorHeightM}
							oninput={(e) => setSelectedSensorHeight(Number((e.currentTarget as HTMLInputElement).value))}
						/>
					</div>
					<div class="sensor-config-row">
						<label class="sensor-height-label">Ambient light</label>
						<input type="number" class="sensor-height-input" min="0" max="20" step="0.1" bind:value={ambientRadiance} title="Fallback constant radiance injected when the scene has no emitters" />
					</div>
					{@const vpScan = observationScan?.viewpoints?.[selectedSensorNodeId]}
					{@const vpCompleted = vpScan?.completed ?? (graphBatch ? (buildBatchJobGrid(graphBatch).rows.find((r: any) => r.nid === selectedSensorNodeId)?.cells?.filter((c: any) => c?.status?.status === 'completed')?.length ?? 0) : 0)}
					{@const vpTotal = vpScan?.total ?? graphBatch?.progress?.total ?? 0}
					{#if vpTotal > 0}
						<div class="sensor-obs-header">
							<span class="sensor-progress">{vpCompleted}/{vpTotal} rendered</span>
							{#if vpCompleted > 0}
								<button class="button button-subtle" onclick={() => clearNodeObservations(selectedSensorNodeId)}>Clear</button>
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
							<button class="button button-subtle" onclick={refreshBatch}>Refresh</button>
						</div>
					{/if}
					<button class="button button-primary full" disabled={renderingViewpoint || !selectedProjectId || !renderSceneSynced || (!(selectedSensorNode as any).isCustom && !hasGraph) || (!sceneStateText.trim() || !cameraSpecText.trim())} onclick={renderSensorViewpoint}>
						{renderingViewpoint ? 'Sweeping...' : 'Graph Sweep · this viewpoint'}
					</button>
					<button class="button button-subtle full" disabled={loading || !selectedProjectId || !renderSceneSynced || !hasGraph} onclick={renderEpisodes}>
						Graph Sweep · all viewpoints
					</button>
				{:else}
					<div class="sensor-hint">Click a viewpoint (blue dot) to select it</div>
					{#if observationScan?.viewpoints}
						{@const totalCompleted = Object.values(observationScan.viewpoints as Record<string, any>).reduce((s: number, vp: any) => s + (vp.completed ?? 0), 0)}
						{@const totalHeadings = Object.values(observationScan.viewpoints as Record<string, any>).reduce((s: number, vp: any) => s + (vp.total ?? 0), 0)}
						{#if totalHeadings > 0}
							<div class="sensor-obs-header">
								<span class="sensor-progress">{totalCompleted}/{totalHeadings} total renders</span>
								{#if totalCompleted > 0}
									<button class="button button-subtle" onclick={clearAllObservations}>Clear all</button>
								{/if}
							</div>
						{/if}
					{/if}
				{/if}
			</section>
		{/if}

		{#if railTab === 'lights'}
			<section class="rail-section rail-tool-panel lights-panel">
				<div class="rail-title">Lights</div>
				{#if detectedEmitterCount > 0}
					<div class="emitter-bulk-row">
						<span>{enabledEmitterCount}/{detectedEmitterCount} fixtures enabled</span>
						<button class="button button-subtle" disabled={enabledEmitterCount >= detectedEmitterCount} onclick={enableAllDetectedEmitters}>Enable all</button>
						{#if enabledEmitterCount > 0}
							<button class="button button-subtle" onclick={disableAllEmitters}>Disable all</button>
						{/if}
					</div>
				{:else}
					<p class="probe-empty">No light-keyword objects detected in this scene's authoring map.</p>
				{/if}
				<div class="lights-list">
					{#each (authoringMap?.objects ?? []).filter((o: any) => detectedEmitterIds.has(o.id) || o.is_emitter) as light (light.id)}
						<div class="light-item" class:enabled={light.is_emitter}>
							<label class="light-toggle">
								<input type="checkbox" checked={light.is_emitter ?? false} onchange={async (e) => {
									if (!authoringMap) return;
									const isOn = (e.currentTarget as HTMLInputElement).checked;
									const objects = (authoringMap.objects ?? []).map((o: any) => o.id === light.id ? { ...o, is_emitter: isOn } : o);
									setAuthoringMapPayload({ ...authoringMap, objects }, true);
									await saveAuthoringMap();
								}} />
								<span class="light-label">{light.label || light.id}</span>
							</label>
							{#if light.is_emitter}
								<input type="range" class="light-intensity" min="0.1" max="20" step="0.1"
									value={light.emitter_intensity ?? 1.0}
									title={`Intensity: ${(light.emitter_intensity ?? 1.0).toFixed(1)}×`}
									oninput={(e) => {
										if (!authoringMap) return;
										const v = Number((e.currentTarget as HTMLInputElement).value);
										const objects = (authoringMap.objects ?? []).map((o: any) => o.id === light.id ? { ...o, emitter_intensity: v } : o);
										setAuthoringMapPayload({ ...authoringMap, objects }, true);
									}}
								/>
							{/if}
						</div>
						{#if light.is_emitter}
							{@const kelvin = light.emitter_radiance ? rgbToKelvinApprox(light.emitter_radiance) : 3000}
							{@const swatch = kelvinToRgb(kelvin)}
							<div class="light-aux-row">
								<span class="light-color-swatch" style:background={`rgb(${Math.round(swatch[0] * 255)},${Math.round(swatch[1] * 255)},${Math.round(swatch[2] * 255)})`} title={`${kelvin}K`}></span>
								<input type="range" class="light-temp" min="1500" max="10000" step="100"
									value={kelvin}
									title={`Color temp: ${kelvin}K`}
									oninput={(e) => {
										if (!authoringMap) return;
										const k = Number((e.currentTarget as HTMLInputElement).value);
										const rgb = kelvinToRgb(k);
										const objects = (authoringMap.objects ?? []).map((o: any) => o.id === light.id ? { ...o, emitter_radiance: rgb } : o);
										setAuthoringMapPayload({ ...authoringMap, objects }, true);
									}}
								/>
								<label class="light-height-label">h<input type="number" class="light-height" min="0.05" max="4" step="0.05"
									value={Number(light.geometry?.base_height_m ?? 0)}
									title="Height (base_height_m)"
									oninput={(e) => {
										if (!authoringMap) return;
										const h = Math.max(0, Math.min(8, Number((e.currentTarget as HTMLInputElement).value)));
										const objects = (authoringMap.objects ?? []).map((o: any) => o.id === light.id ? { ...o, geometry: { ...(o.geometry ?? {}), base_height_m: h } } : o);
										setAuthoringMapPayload({ ...authoringMap, objects }, true);
									}}
								/></label>
							</div>
						{/if}
					{:else}
						<p class="probe-empty">Toggle "Use as light source" on individual landmarks (or use Enable all above).</p>
					{/each}
				</div>
				<div class="sync-actions">
					<button class="button button-subtle" disabled={!hasScene || loading} onclick={saveAuthoringMap}>Save</button>
					<button class="button button-subtle" disabled={!hasScene || loading} onclick={syncRenderScene} style="display:none">Sync Render Scene</button>
				</div>
			</section>
		{/if}

		{#if railTab === 'preview'}
			<section class="rail-section rail-tool-panel preview-panel">
				<div class="rail-title">Render Probe</div>
				<div class="probe-mode-row">
					<label><input type="radio" bind:group={probeMode} value="selected" /> Selected viewpoint</label>
					<label><input type="radio" bind:group={probeMode} value="free" /> Free probe</label>
					<label><input type="radio" bind:group={probeMode} value="editor_view" /> Current editor view</label>
					<label class="probe-mode-stub"><input type="radio" bind:group={probeMode} value="isaac_view" disabled /> Current Isaac view (soon)</label>
				</div>
				{#if probeMode === 'selected'}
					<div class="probe-info">
						{#if selectedSensorNode}
							<div>Source: {(selectedSensorNode as any).isCustom ? 'custom sensor' : 'graph viewpoint'}</div>
							<div>ID: {selectedSensorNodeId}</div>
							<div>Pose: x={selectedSensorNode.position?.[0]?.toFixed(2)} z={selectedSensorNode.position?.[1]?.toFixed(2)}</div>
							<div>Height: {selectedSensorHeightM.toFixed(2)} m</div>
						{:else}
							<p class="probe-empty">Click a viewpoint dot or custom sensor on the map.</p>
						{/if}
					</div>
				{:else if probeMode === 'free'}
					<div class="probe-info probe-form">
						<label>x <input type="number" step="0.1" bind:value={freeProbe.x} /></label>
						<label>z <input type="number" step="0.1" bind:value={freeProbe.z} /></label>
						<label>yaw° <input type="number" step="5" bind:value={freeProbe.yaw_deg} /></label>
						<label>height <input type="number" step="0.05" min="0.05" max="8" bind:value={freeProbe.height_m} /></label>
					</div>
				{:else if probeMode === 'editor_view'}
					<div class="probe-info">
						<button class="button button-subtle" onclick={captureEditorViewProbe}>Snapshot orbit camera</button>
						{#if editorViewProbe}
							<div>x={editorViewProbe.x} z={editorViewProbe.z} yaw={editorViewProbe.yaw_deg}° h={editorViewProbe.height_m}m</div>
							<p class="probe-empty">Pitch is dropped (Mitsuba camera renders horizontal).</p>
						{:else}
							<p class="probe-empty">Orbit the 3D view, then click Snapshot.</p>
						{/if}
					</div>
				{/if}
				<div class="probe-actions">
					<span class="chip-dim">modality: {activeRenderModality}</span>
					<button class="button button-primary" disabled={probeRendering} onclick={runProbeRender}>
						{probeRendering ? 'Rendering…' : 'Render now'}
					</button>
				</div>
				{#if probeError}
					<div class="probe-error">{probeError}</div>
				{/if}
				{#if probeResult}
					<div class="probe-result">
						<div class="probe-result-meta">Batch {probeResult.batch_id.slice(0, 8)}… · {probeResult.vp_id}/{probeResult.heading_id}</div>
						<img class="probe-result-img" src={opticalNavObservationModalityUrl(selectedProjectId, sceneId, probeResult.vp_id, probeResult.heading_id, probeResult.modality, probeResult.sensor_id ?? activeRigSensorId)} alt={`probe ${probeResult.modality}`} loading="lazy"
							onerror={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = '0.3'; }} />
						<button class="button button-subtle" onclick={() => refreshBatch()}>Refresh batch status</button>
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
					<label class="footprint-toggle"><input type="checkbox" bind:checked={showRoomShell} /> Show auto room shell</label>
					<span>{roomShell?.shapes?.length ?? 0} shapes</span>
				</div>
				<div class="sync-divider"></div>
				<div class="sync-row"><span>XML file</span><span class="mono">{renderSceneStats?.path ? renderSceneStats.path.split('/').slice(-2).join('/') : 'not generated'}</span></div>
				<div class="sync-row"><span>XML size</span><span>{renderSceneStats?.size_bytes != null ? Math.round(renderSceneStats.size_bytes / 1024) + ' KB' : '—'}</span></div>
				<div class="sync-row"><span>Last sync</span><span class="mono">{renderSceneStats?.modified_at?.slice(0, 19).replace('T', ' ') ?? '—'}</span></div>
				<div class="sync-actions">
					<button class="button button-subtle" disabled={renderSceneStatsLoading} onclick={refreshRenderSceneStats}>{renderSceneStatsLoading ? 'Loading…' : 'Refresh stats'}</button>
					<button class="button button-subtle" disabled={!hasScene || loading} onclick={syncRenderScene} style="display:none">Sync Render Scene</button>
				</div>
			</section>
		{/if}

		{#if railTab === 'export'}
			<section class="rail-section rail-tool-panel export-panel">
				<div class="rail-title">Export Readiness</div>
				<div class="export-readiness-list">
					<div class="readiness-item" class:ok={hasScene}><span class="readiness-dot"></span><span>Scene</span></div>
					<div class="readiness-item" class:ok={renderSceneSynced}><span class="readiness-dot"></span><span>Render readiness {renderSceneSynced ? 'ready' : 'blocked'}</span></div>
					<div class="readiness-item" class:ok={Boolean(effectiveRenderReadiness?.xml_path || currentScene?.render_scene_xml_ref)}><span class="readiness-dot"></span><span>render_scene.xml</span></div>
					<div class="readiness-item" class:ok={Boolean(rigSensorOptions.some((s: any) => s.modality === 'rgb'))}><span class="readiness-dot"></span><span>RGB camera rig</span></div>
					<div class="readiness-item" class:ok={hasMap}><span class="readiness-dot"></span><span>Traversable grid</span></div>
					<div class="readiness-item" class:ok={hasGraph}><span class="readiness-dot"></span><span>Viewpoint graph</span></div>
					<div class="readiness-item" class:ok={hasEpisodes}><span class="readiness-dot"></span><span>Episodes ({episodes.length})</span></div>
					<div class="readiness-item" class:ok={validationPassed}><span class="readiness-dot"></span><span>Validated</span></div>
				</div>
				{#if graphPayloadSummary}
					<div class="rail-title mt-2">Dataset Stats</div>
					<div class="export-stats">
						<div class="stat-row"><span>Viewpoints</span><span>{graphPayloadSummary.node_count}</span></div>
						<div class="stat-row"><span>Edges</span><span>{graphPayloadSummary.edge_count}</span></div>
						<div class="stat-row"><span>Hazard edges</span><span>{graphPayloadSummary.hazard_edge_count ?? 0}</span></div>
						<div class="stat-row"><span>Episodes</span><span>{episodes.length}</span></div>
						{#if splitCounts.train != null}
							<div class="stat-row"><span>Train</span><span>{splitCounts.train}</span></div>
							<div class="stat-row"><span>Val seen</span><span>{splitCounts.val_seen ?? 0}</span></div>
							<div class="stat-row"><span>Val unseen</span><span>{splitCounts.val_unseen ?? 0}</span></div>
						{/if}
					</div>
				{/if}
				{#if allEpisodePaths.length > 0}
					<div class="export-path-legend mt-2">
						<span class="legend-swatch normal"></span><span>Normal path</span>
						<span class="legend-swatch hazard"></span><span>Hazard path ({allEpisodePaths.filter(p => p.hasHazard).length})</span>
					</div>
				{/if}
				{#if validationReport}
					<div class="export-validation" class:validation-ok={validationReport.ok !== false} class:validation-fail={validationReport.ok === false}>
						Validation: {validationReport.ok !== false ? 'passed' : 'failed'}
						{#if validationReport.errors?.length}<span class="val-errors"> · {validationReport.errors.length} error(s)</span>{/if}
					</div>
				{/if}
				<button class="button button-subtle full mt-2" disabled={!selectedProjectId || loading} onclick={() => validateDataset(false)}>
					{loading ? 'Validating...' : 'Validate Dataset'}
				</button>
				<button class="button button-primary full" disabled={!selectedProjectId || !hasEpisodes || loading} onclick={exportDataset}>
					{loading ? 'Exporting...' : 'Export Dataset'}
				</button>
				{#if exportPath}
					<div class="export-path-display">
						<span class="chip-ok">Exported</span>
						<span class="export-path-text" title={exportPath}>{exportPath.split('/').slice(-2).join('/')}</span>
					</div>
				{/if}
			</section>
		{/if}

		{#if railTab === 'scene'}
		<section class="rail-section rail-tool-panel">
			<details open>
				<summary class="rail-summary">Scene</summary>
				<div class="map-settings-body rail-settings-body">
					{#if projectScenes.length > 0}
						<label>
							<span>scene</span>
							<select class="scene-select" value={sceneId} onchange={(e) => { sceneId = e.currentTarget.value; sceneStateText = ''; cameraSpecText = ''; renderConfig = null; syncResult = null; renderReadiness = null; renderConfigError = ''; loadAuthoringMap(); loadRenderConfig(); episodes = []; selectedEpisode = null; selectedEpisodeId = ''; graphPayload = null; observationScan = null; graphBatch = null; graphBatchId = ''; graphBatchIds = []; stopBatchPolling(); if (pageMode === 'sensors') scanObservations(); }}>
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
						<div class="geometry-grid">
							<label><span>Environment</span><select value={authoringMap?.environment?.mode ?? 'constant'} onchange={(event) => updateEnvironmentField('mode', (event.currentTarget as HTMLSelectElement).value)}><option value="constant">constant</option><option value="envmap">envmap</option></select></label>
							<label><span>Intensity</span><input type="number" min="0" step="0.1" value={authoringMap?.environment?.intensity ?? 1} oninput={(event) => updateEnvironmentField('intensity', (event.currentTarget as HTMLInputElement).value)} /></label>
							<label><span>Rotation</span><input type="number" step="1" value={authoringMap?.environment?.rotation_deg ?? 0} oninput={(event) => updateEnvironmentField('rotation_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
							<label><span>RGB</span><input value={(authoringMap?.environment?.radiance ?? [0.8,0.8,0.85]).join(', ')} oninput={(event) => updateEnvironmentField('radiance', (event.currentTarget as HTMLInputElement).value)} /></label>
						</div>
						<label><span>HDR/EXR envmap ref</span><input value={authoringMap?.environment?.envmap_ref ?? ''} oninput={(event) => updateEnvironmentField('envmap_ref', (event.currentTarget as HTMLInputElement).value || null)} /></label>
						<div class="geometry-grid">
							<label><span>Upload envmap</span><input type="file" accept=".exr,.hdr,.png,.jpg,.jpeg,image/png,image/jpeg" disabled={envmapUploading || !selectedProjectId || !hasScene} onchange={(event) => uploadEnvmapFromInput(event.currentTarget as HTMLInputElement)} /></label>
							{#if envmapFiles.length}
								<label><span>Uploaded</span><select value={authoringMap?.environment?.envmap_ref ?? ''} onchange={(event) => { updateEnvironmentField('mode', 'envmap'); updateEnvironmentField('envmap_ref', (event.currentTarget as HTMLSelectElement).value || null); }}><option value="">Select envmap</option>{#each envmapFiles as item}<option value={item.envmap_ref}>{item.filename}{#if item.size_bytes} · {envmapSizeLabel(item.size_bytes)}{/if}</option>{/each}</select></label>
							{/if}
						</div>
						<label class="inline-check"><input type="checkbox" checked={authoringMap?.environment?.background_visible ?? true} onchange={(event) => updateEnvironmentField('background_visible', (event.currentTarget as HTMLInputElement).checked)} /> Background visible</label>
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
						{/if}
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
		</section>
		{/if}

		{#if railTab === 'paths'}
		<section class="rail-section rail-tool-panel">
			<details open>
				<summary class="rail-summary">Paths</summary>
				<div class="map-settings-body rail-settings-body">
					<div class="path-status-chips">
						<span class:chip-ok={hasMap} class:chip-off={!hasMap}>Map {hasMap ? 'ready' : 'missing'}</span>
						<span class:chip-ok={hasGraph} class:chip-off={!hasGraph}>Graph {hasGraph ? 'ready' : 'missing'}</span>
						{#if graphPayloadSummary}<span class="chip-ok">{graphPayloadSummary.node_count}n · {graphPayloadSummary.edge_count}e</span>{/if}
					</div>
					<div class="rail-title">Traversable Grid</div>
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
					<div class="rail-title mt-2">Viewpoint Graph</div>
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
					<div class="rail-title mt-2">Episodes</div>
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
		</section>
		{/if}

		{#if railTab === 'status'}
		<section class="rail-section">
			<div class="rail-title">OpticalNav Status</div>
			<div class="rail-readiness">
				<span class:ready={hasScene}>Scene</span>
				<span class:ready={hasMap}>Map</span>
				<span class:ready={hasGraph}>Graph</span>
				<span class:ready={hasEpisodes}>Episodes</span>
			</div>
		</section>

		<section class="rail-section">
			<div class="rail-title">Project</div>
			<dl class="rail-kv">
				<div><dt>ID</dt><dd>{selectedProjectId || 'No project'}</dd></div>
				<div><dt>Scene</dt><dd>{sceneId || '-'}</dd></div>
				<div><dt>Episodes</dt><dd>{episodes.length}</dd></div>
				<div><dt>Splits</dt><dd>{Object.keys(splitCounts).length ? JSON.stringify(splitCounts) : '-'}</dd></div>
			</dl>
		</section>

		{#if currentScene}
			<section class="rail-section">
				<div class="rail-title">Scene Artifacts</div>
				<dl class="rail-kv">
					<div><dt>Map overlay</dt><dd>{currentScene.authoring_map_exists || authoringMap ? 'ready' : 'missing'}</dd></div>
					<div><dt>USD</dt><dd>{currentScene.usd_ref || 'not attached'}</dd></div>
					<div><dt>Annotation</dt><dd>{currentScene.annotation_ok ? 'valid' : 'needs check'}</dd></div>
					<div><dt>Render scene</dt><dd>{currentScene.sync_status?.render_scene ?? '-'}</dd></div>
					<div><dt>Isaac stage</dt><dd>{currentScene.sync_status?.isaac_stage ?? '-'}</dd></div>
					<div><dt>Map</dt><dd>{currentScene.map_exists ? 'ready' : 'missing'}</dd></div>
					<div><dt>Graph</dt><dd>{currentScene.viewpoint_graph_exists ? 'ready' : 'missing'}</dd></div>
				</dl>
			</section>
		{/if}

		{#if graphPayloadSummary || currentScene?.viewpoint_graph}
			<section class="rail-section">
				<div class="rail-title">Viewpoint Graph</div>
				<dl class="rail-kv">
					<div><dt>Nodes</dt><dd>{graphPayloadSummary?.node_count ?? currentScene?.viewpoint_graph?.node_count ?? '-'}</dd></div>
					<div><dt>Edges</dt><dd>{graphPayloadSummary?.edge_count ?? currentScene?.viewpoint_graph?.edge_count ?? '-'}</dd></div>
					<div><dt>Headings</dt><dd>{graphPayloadSummary?.heading_count ?? currentScene?.viewpoint_graph?.heading_count ?? headingCount}</dd></div>
					<div><dt>Hazard edges</dt><dd>{graphPayloadSummary?.hazard_edge_count ?? currentScene?.viewpoint_graph?.hazard_edge_count ?? '-'}</dd></div>
				</dl>
			</section>
		{/if}

		{#if selectedEpisodeSummary}
			<section class="rail-section">
				<div class="rail-title">Selected Episode</div>
				<dl class="rail-kv">
					<div><dt>ID</dt><dd>{selectedEpisodeSummary.episode_id}</dd></div>
					<div><dt>Mode</dt><dd>{selectedEpisodeSummary.mode}</dd></div>
					<div><dt>Split</dt><dd>{selectedEpisodeSummary.split}</dd></div>
					<div><dt>Path nodes</dt><dd>{selectedEpisodeSummary.path_nodes}</dd></div>
					<div><dt>Refs</dt><dd>{selectedEpisodeSummary.observation_refs}</dd></div>
				</dl>
			</section>
		{/if}

		{#if validationReport || evaluationReport || exportPath}
			<section class="rail-section">
				<div class="rail-title">Review Output</div>
				<dl class="rail-kv">
					<div><dt>Validation</dt><dd>{validationReport ? (validationReport.ok === false ? 'failed' : 'complete') : '-'}</dd></div>
					<div><dt>Success</dt><dd>{evaluationReport?.metrics?.success_rate ?? '-'}</dd></div>
					<div><dt>SPL</dt><dd>{evaluationReport?.metrics?.spl ?? '-'}</dd></div>
					<div><dt>Export</dt><dd>{exportPath || '-'}</dd></div>
				</dl>
			</section>
		{/if}
		{/if}
	</div>
{/snippet}

{#snippet datasetBottomContent()}
	<div class="dataset-bottom">
		<!-- Floating overlay buttons — no header bar -->
		<div class="bottom-overlay-buttons">
			<button class="bottom-icon-btn" onclick={toggleBottomPanel} aria-label="Toggle bottom panel" title={$bottomPanelCollapsed ? 'Expand' : 'Collapse'}>
				{$bottomPanelCollapsed ? '▲' : '▼'}
			</button>
			{#if activeBatch && !$bottomPanelCollapsed}
				<button class="bottom-icon-btn" disabled={loading} onclick={refreshBatch} aria-label="Refresh batch" title="Refresh batch">↻</button>
			{/if}
		</div>

		{#if !$bottomPanelCollapsed}
			<div class="dataset-bottom-body">
				<section class="bottom-progress">
					<div class="progress-head">
						<span>{renderMode === 'graph_sweep' ? 'Sensor Sweep' : 'Episode Render'}</span>
						<span>{progressPercent(bottomProgress)}%</span>
					</div>
					<div class="progress-track">
						<div class="progress-fill" style={`width: ${progressPercent(bottomProgress)}%`}></div>
					</div>
					<div class="progress-metrics">
						<span>total {bottomProgress?.total ?? 0}</span>
						<span class="js-chip js-done">{batchJobGrid.counts?.completed ?? 0} done</span>
						<span class="js-chip js-running">{batchJobGrid.counts?.running ?? 0} running</span>
						<span class="js-chip js-queued">{batchJobGrid.counts?.queued ?? 0} queued</span>
						{#if (batchJobGrid.counts?.failed ?? 0) > 0}
							<span class="js-chip js-failed">{batchJobGrid.counts.failed} failed</span>
						{/if}
					</div>

					<!-- Job grid: rows=viewpoints, cols=headings -->
					{#if batchJobGrid.rows.length > 0}
						<div class="batch-job-grid" title="Each cell = one render job (viewpoint × heading)">
							{#if batchJobGrid.headings.length > 1}
								<div class="bjg-header">
									<span class="bjg-node-label"></span>
									{#each batchJobGrid.headings as h}
										<span class="bjg-heading-label" title={h}>{parseInt(h.replace('h_','')) || 0}</span>
									{/each}
								</div>
							{/if}
							{#each batchJobGrid.rows as row}
								<div class="bjg-row">
									<span class="bjg-node-label" title={row.nid}>{row.nid.replace(/^vp_0*/, '').replace(/^custom_/, 'c') || row.nid.slice(-4)}</span>
									{#each row.cells as job}
										<button
											type="button"
											class={`bjg-cell ${job ? jobStatusClass(job) : 'js-unknown'}${job && job.job_id === selectedBatchJobId ? ' bjg-selected' : ''}`}
											title={job ? `${job.node_id} ${job.heading_id} · ${jobStageLabel(job)}` : 'no job'}
											aria-label={job ? `${job.node_id} ${job.heading_id} ${jobStageLabel(job)}` : 'no job'}
											disabled={!job}
											onclick={() => { if (job) selectBatchJob(job); }}
										></button>
									{/each}
								</div>
							{/each}
						</div>
					{/if}

					<!-- Stale job controls -->
					{#if (batchJobGrid.counts?.running ?? 0) + (batchJobGrid.counts?.queued ?? 0) > 0}
						<div class="stale-controls">
							<button class="button button-subtle" onclick={cancelStaleBatchJobs}>Cancel running/queued</button>
						</div>
					{/if}

					<!-- Selected job detail -->
					{#if selectedBatchJob}
						{@const textureAudit = selectedBatchJob.status?.extras?.texture_audit}
						{@const textureProfile = selectedBatchJob.status?.extras?.texture_profile ?? textureAudit?.texture_profile}
						<div class="job-detail-panel">
							<div class="job-detail-head">
								<span class="job-detail-id" title={selectedBatchJob.job_id}>{selectedBatchJob.job_id?.slice(-16) ?? '—'}</span>
								<span class={`js-chip js-${jobStatusClass(selectedBatchJob).replace('js-', '')}`}>{String(selectedBatchJob?.status?.status ?? '')}</span>
								<button class="bjg-close" onclick={() => { selectedBatchJobId = ''; selectedBatchJobLog = []; }}>✕</button>
							</div>
							<div class="job-detail-meta">
								<span>{selectedBatchJob.node_id ?? ''}</span>
								{#if selectedBatchJob.heading_id}<span>· {selectedBatchJob.heading_id}</span>{/if}
								{#if selectedBatchJob.status?.progress_stage}<span>· {selectedBatchJob.status.progress_stage}</span>{/if}
								{#if textureProfile}<span>· Texture max{textureProfile}</span>{/if}
								{#if textureAudit?.texture_refs}<span>· Downsampled {textureAudit.downsampled_refs ?? 0}/{textureAudit.texture_refs}</span>{/if}
							</div>
							<!-- Stage timeline -->
							<div class="stage-timeline">
								{#each RENDER_STAGES as stage, i}
									{@const si = stageIndex(selectedBatchJob)}
									{@const isFailed = String(selectedBatchJob?.status?.status ?? '') === 'failed'}
									{@const done = !isFailed && si >= i}
									{@const active = !isFailed && si === i}
									{@const isCached = stage.key === 'loading_scene' && selectedBatchJob?.status?.extras?.scene_cache_hit}
									<div class={`stage-step${done ? ' done' : ''}${active ? ' active' : ''}${isFailed && si === -1 && i === 0 ? ' failed' : ''}`}>
										<div class="stage-dot"></div>
										<span>{stage.label}{#if isCached} ⚡{/if}</span>
									</div>
								{/each}
							</div>
							<!-- Log entries -->
							{#if selectedBatchJobLoading}
								<div class="job-log-row muted">Loading logs…</div>
							{:else if selectedBatchJobLog.length === 0}
								<div class="job-log-row muted">No log entries.</div>
							{:else}
								<div class="job-log-list">
									{#each selectedBatchJobLog.slice(-40) as entry}
										<div class="job-log-row">
											<span class="job-log-level">{entry.level ?? 'info'}</span>
											<span class="job-log-msg">{entry.message ?? entry.msg ?? JSON.stringify(entry)}</span>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/if}
				</section>

				<section class="activity-log" aria-label="OpticalNav activity log">
					<!-- Batch job logs from backend -->
					{#if batchLogEntries.length > 0}
						<div class="log-section-head">렌더 잡 로그</div>
						{#each batchLogEntries as entry}
							<div class="activity-row level-info batch-log-row">
								<span class="activity-source batch-log-job" title={entry.job_id}>{entry.job_id.slice(-12)}</span>
								<span class="activity-message batch-log-line">{entry.line}</span>
							</div>
						{/each}
						<div class="log-section-head">UI 이벤트</div>
					{/if}
					<!-- UI event log -->
					{#each activityLog as entry}
						<div class={`activity-row level-${entry.level}`}>
							<span class="activity-time">{entry.ts}</span>
							<span class="activity-source">{entry.source}</span>
							<span class="activity-message">{entry.message}</span>
							{#if entry.detail}
								<span class="activity-detail" title={entry.detail}>{compactDetail(entry.detail)}</span>
							{/if}
						</div>
					{/each}
				</section>
			</div>
		{/if}
	</div>
{/snippet}

<style>
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
	.context-menu button.danger { color: #dc2626; }

	.dataset-page {
		display: grid;
		gap: var(--space-4);
		padding-bottom: 96px;
	}
	.dataset-page.bottom-open {
		padding-bottom: 360px;
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
		background: #fff1f1;
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
		border-color: #abd7b5;
		background: #eef8f0;
		color: #236b35;
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
	.tool.danger { color: #9b1c1c; }
	.tool-glass.active { border-color: #5bb7c5; color: #1a6b7a; background: #e8f7fa; }
	.tool-mirror.active { border-color: #94a3b8; color: #334155; background: #f1f5f9; }
	.tool-traversable.active { border-color: #37a169; color: #1a5c38; background: #eef8f0; }
	.tool-goal.active { border-color: #2f80ed; color: #1a4a8a; background: #e8f0fd; }
	.tool-hazard.active { border-color: #dd7a22; color: #8a4a0a; background: #fff4e6; }
	.tool-forbidden.active { border-color: #c53030; color: #8a1c1c; background: #fff1f1; }
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
		color: #475569;
		font-size: var(--font-size-xs);
	}
	.floorplan-outline {
		fill: rgba(248, 250, 252, 0.72);
		stroke: #94a3b8;
		stroke-width: 1.5;
		stroke-dasharray: 8 6;
		pointer-events: none;
	}
	.map-axis-label {
		fill: #64748b;
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
		color: #9a5b00;
		font-size: var(--font-size-xs);
	}
	.map-line {
		stroke: #5bb7c5;
		stroke-width: 8;
		stroke-linecap: round;
		filter: drop-shadow(0 1px 2px rgba(15, 23, 42, 0.18));
		cursor: pointer;
	}
	.map-line.mirror_wall { stroke: #94a3b8; }
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
		stroke: #37a169;
	}
	.region-goal {
		fill: rgba(47, 128, 237, 0.18);
		stroke: #2f80ed;
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
		stroke: #dd7a22;
	}
	.region-forbidden {
		fill: rgba(197, 48, 48, 0.16);
		stroke: #c53030;
	}
	.region-generic {
		fill: rgba(100, 116, 139, 0.12);
		stroke: #64748b;
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
		stroke: #475569;
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
	.map-point.table circle { stroke: #92400e; }
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
		fill: #dd7a22;
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
	.inspector-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.inspector-id {
		margin-top: 2px;
		color: var(--text);
		font-family: var(--font-mono);
		font-size: var(--font-size-xs);
		overflow-wrap: anywhere;
	}
	.dirty-pill {
		border: 1px solid #f4c26f;
		border-radius: 999px;
		background: #fff8e8;
		color: #9a5b00;
		font-size: var(--font-size-xs);
		font-weight: 700;
		padding: 2px var(--space-2);
		white-space: nowrap;
	}
	.inspector-badges {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
	}
	.inspector-badges span {
		border: 1px solid var(--panel-border);
		border-radius: 999px;
		background: var(--surface-2);
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
		padding: 2px var(--space-2);
	}
	.preset-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.preset-row .button {
		height: 30px;
		padding-inline: var(--space-2);
		font-size: var(--font-size-xs);
	}
	.rotation-row {
		display: grid;
		grid-template-columns: 1fr auto 1fr;
		align-items: center;
		gap: var(--space-2);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		padding: var(--space-2);
	}
	.rotation-row button {
		min-height: 34px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--panel);
		color: var(--text);
		font-weight: 800;
		cursor: pointer;
	}
	.rotation-row button:hover { background: var(--hover-bg); }
	.rotation-row div {
		display: grid;
		justify-items: center;
		gap: 1px;
		min-width: 54px;
	}
	.rotation-row strong {
		color: var(--brand);
		font-size: var(--font-size-md);
	}
	.rotation-row small {
		color: var(--text-muted);
		font-size: 10px;
		white-space: nowrap;
	}
	.inspector-section {
		display: grid;
		gap: var(--space-2);
		padding-top: var(--space-2);
		border-top: 1px solid var(--panel-border);
	}
	.geometry-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-2);
	}
	.flag-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-2);
	}
	.flag-grid label {
		display: flex;
		grid-template-columns: none;
		align-items: center;
		gap: 6px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-2);
		background: var(--surface-2);
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.flag-grid input {
		width: 14px;
		height: 14px;
		padding: 0;
	}
	.suggestion {
		margin: 0;
		border: 1px solid #bfdbfe;
		border-radius: var(--radius-sm);
		background: #eff6ff;
		color: #1e3a8a;
		padding: var(--space-2);
		font-size: var(--font-size-xs);
	}
	.material-info {
		display: grid;
		gap: 2px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: rgba(248, 250, 252, 0.92);
		padding: var(--space-2);
		font-size: var(--font-size-xs);
	}
	.material-info strong {
		color: var(--text);
		font-size: 12px;
	}
	.material-info span {
		color: var(--muted-strong);
	}
	.material-info small {
		overflow: hidden;
		color: var(--text-muted);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.material-mini-label {
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
		font-weight: 700;
	}
	.material-summary-row {
		display: grid;
		grid-template-columns: 44px minmax(0, 1fr) auto;
		align-items: center;
		gap: 9px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: rgba(248,250,252,0.92);
		padding: 6px;
	}
	.material-summary-row img,
	.material-empty-thumb {
		width: 44px;
		height: 44px;
		border-radius: var(--radius-sm);
		object-fit: cover;
		background: #f1f5f9;
		border: 1px solid var(--panel-border);
	}
	.material-empty-thumb {
		display: grid;
		place-items: center;
		color: var(--text-muted);
		font-size: 10px;
		font-weight: 800;
		text-transform: uppercase;
	}
	.material-summary-row strong {
		color: var(--text);
		font-size: 12px;
		line-height: 1.15;
	}
	.material-summary-row small {
		color: var(--text-muted);
		font-size: 10px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.material-summary-row div {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.inspector-tabs {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 6px;
	}
	.inspector-tabs button,
	.material-category-tabs button {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--text-muted);
		padding: 6px;
		font-weight: 800;
		cursor: pointer;
	}
	.inspector-tabs button.active,
	.material-category-tabs button.active {
		border-color: var(--brand);
		background: #eff6ff;
		color: var(--brand);
	}
	.inspector-tabs button:disabled {
		cursor: not-allowed;
		opacity: 0.45;
	}
	.material-workspace {
		display: grid;
		gap: 8px;
		min-height: 0;
	}
	.material-picker-top {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(120px, 0.45fr);
		gap: 6px;
	}
	.material-search {
		width: 100%;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		padding: 7px 9px;
		background: #fff;
		color: var(--text);
	}
	.material-picker-top select {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: #fff;
		color: var(--text);
		padding: 7px;
		min-width: 0;
	}
	.material-category-tabs {
		display: flex;
		gap: 5px;
		overflow-x: auto;
		padding-bottom: 2px;
	}
	.material-category-tabs button {
		white-space: nowrap;
		text-transform: capitalize;
		font-size: 11px;
		padding-inline: 8px;
	}
	.material-grid-browser {
		display: grid;
		grid-template-columns: minmax(0, 1.2fr) minmax(170px, 0.8fr);
		gap: 10px;
		min-height: 0;
	}
	.material-card-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		align-content: start;
		gap: 8px;
		max-height: calc(100vh - 300px);
		overflow: auto;
		padding-right: 2px;
	}
	.material-card-grid button {
		display: grid;
		grid-template-rows: 74px auto auto auto;
		gap: 4px;
		min-width: 0;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: rgba(248,250,252,0.94);
		color: var(--text);
		padding: 7px;
		text-align: left;
		cursor: pointer;
	}
	.material-card-grid button:hover,
	.material-card-grid button.selected {
		border-color: var(--brand);
		background: #eff6ff;
	}
	.material-card-grid img,
	.material-card-grid .material-empty-thumb {
		width: 100%;
		height: 74px;
		object-fit: cover;
		border-radius: var(--radius-sm);
	}
	.material-card-grid strong {
		overflow: hidden;
		color: var(--text);
		font-size: 12px;
		line-height: 1.2;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.material-card-grid small,
	.material-preview-panel p {
		overflow: hidden;
		color: var(--text-muted);
		font-size: 10px;
		text-overflow: ellipsis;
		white-space: nowrap;
		margin: 0;
	}
	.material-tag-row {
		display: flex;
		flex-wrap: wrap;
		gap: 3px;
		min-width: 0;
	}
	.material-tag-row span {
		border: 1px solid var(--panel-border);
		border-radius: 999px;
		background: #fff;
		color: var(--text-muted);
		font-size: 9px;
		line-height: 1;
		padding: 3px 5px;
	}
	.material-tag-row.expanded span {
		font-size: 10px;
	}
	.material-preview-panel {
		display: grid;
		align-content: start;
		gap: 8px;
		min-width: 0;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: rgba(248,250,252,0.92);
		padding: 8px;
	}
	.material-empty-state {
		display: grid;
		place-items: center;
		min-height: 160px;
		border: 1px dashed var(--panel-border);
		border-radius: 10px;
		color: var(--text-muted);
		font-size: var(--font-size-xs);
	}
	.material-large-preview,
	.material-large-empty {
		width: 100%;
		aspect-ratio: 1 / 1;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: #f1f5f9;
		object-fit: cover;
	}
	.material-large-empty {
		display: grid;
		place-items: center;
		color: var(--text-muted);
		font-size: var(--font-size-xs);
	}
	.material-preview-panel h3 {
		margin: 0;
		color: var(--text);
		font-size: 15px;
		line-height: 1.2;
	}
	.material-metadata {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 5px;
	}
	.material-metadata div {
		display: grid;
		gap: 1px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: #fff;
		padding: 6px;
	}
	.material-metadata span {
		color: var(--text-muted);
		font-size: 10px;
	}
	.material-metadata strong {
		color: var(--text);
		font-size: 11px;
	}
	.material-action-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px;
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
		color: #9a5b00;
		font-size: var(--font-size-sm);
	}
	.requirement-card div.ready {
		color: #236b35;
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
		color: #9a5b00;
		font-size: var(--font-size-sm);
	}
	.sync-card div.ready {
		color: #236b35;
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
		background: #fef3c7;
		color: #92400e;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
	}
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
	.probe-error { color: #b91c1c; background: #fef2f2; padding: var(--space-2); border-radius: var(--radius-sm); font-size: var(--font-size-xs); }
	.probe-result { display: grid; gap: var(--space-2); }
	.probe-result-meta { font-size: var(--font-size-xs); color: var(--muted-strong); }
	.probe-result-img { width: 100%; max-height: 280px; object-fit: contain; background: #0f172a; border-radius: var(--radius-sm); }
	.sync-inspector { display: grid; gap: 6px; }
	.sync-row { display: flex; justify-content: space-between; font-size: var(--font-size-xs); padding: 2px 0; }
	.sync-row.warn { color: #b91c1c; font-weight: 600; }
	.sync-row .mono { font-family: monospace; max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.sync-divider { height: 1px; background: var(--border); margin: 4px 0; }
	.sync-actions { display: flex; gap: var(--space-2); margin-top: var(--space-2); }
	.lights-panel { display: grid; gap: var(--space-2); }
	.lights-list { display: grid; gap: 4px; max-height: 360px; overflow-y: auto; padding-right: 4px; }
	.light-item { display: grid; grid-template-columns: 1fr 90px; gap: 6px; align-items: center; padding: 4px 6px; border-radius: var(--radius-sm); background: var(--surface-1); font-size: var(--font-size-xs); }
	.light-item.enabled { background: #fef3c7; }
	.light-toggle { display: flex; gap: 6px; align-items: center; overflow: hidden; }
	.light-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.light-intensity { width: 100%; }
	.light-aux-row { grid-column: 1 / -1; display: grid; grid-template-columns: 20px 1fr 70px; gap: 6px; align-items: center; padding: 2px 6px 4px; font-size: var(--font-size-xs); }
	.light-color-swatch { width: 18px; height: 18px; border-radius: 50%; border: 1px solid var(--border); }
	.light-temp { width: 100%; }
	.light-height-label { display: flex; align-items: center; gap: 2px; }
	.light-height { width: 50px; padding: 1px 4px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 11px; }
	.footprint-panel { display: grid; gap: var(--space-2); }
	.footprint-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }
	.footprint-grid label { display: grid; gap: 2px; font-size: var(--font-size-xs); }
	.footprint-grid input { padding: 2px 4px; border: 1px solid var(--border); border-radius: var(--radius-sm); }
	.footprint-info { font-size: var(--font-size-xs); color: var(--muted-strong); }
	.footprint-toggle { display: flex; gap: 6px; align-items: center; font-size: var(--font-size-xs); }
	.footprint-divider { height: 1px; background: var(--border); margin: 4px 0; }
	.paint-mode-row { display: grid; gap: 4px; font-size: var(--font-size-xs); }
	.paint-mode-row label { display: flex; gap: 6px; align-items: center; }
	.paint-swatch { width: 14px; height: 14px; border-radius: 50%; border: 1px solid var(--border); }
	.paint-swatch.walkable { background: #22c55e; }
	.paint-swatch.blocked { background: #ef4444; }
	.paint-radius { width: 70px; }
	.paint-info { display: flex; gap: 6px; align-items: center; font-size: var(--font-size-xs); }
	.component-row { display: flex; gap: 6px; align-items: center; font-size: var(--font-size-xs); padding: 2px 0; }
	.component-dot { width: 12px; height: 12px; border-radius: 50%; border: 1px solid var(--border); }
	.mode-radio-group { display: grid; gap: 2px; }
	.mode-radio {
		display: flex;
		gap: 8px;
		align-items: center;
		padding: 4px 6px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--font-size-sm);
	}
	.mode-radio:hover { background: var(--surface-1); }
	.mode-radio input[type="radio"] { margin: 0; cursor: pointer; }
	.mode-radio span { display: flex; gap: 6px; align-items: center; }
	.mode-active-banner {
		padding: 6px 10px;
		background: #dbeafe;
		color: #1e40af;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
		border-left: 3px solid #3b82f6;
	}
	.edge-diag { display: grid; gap: 4px; padding: var(--space-2); background: var(--surface-1); border-radius: var(--radius-sm); font-size: var(--font-size-xs); border: 1px solid var(--panel-border); }
	.edge-diag-title { font-weight: 600; font-family: monospace; }
	.edge-diag-detail { color: var(--muted-strong); font-style: italic; }
	.edge-diag-verdict { padding: 4px 8px; border-radius: var(--radius-sm); background: #fef2f2; color: #b91c1c; font-weight: 600; margin-top: 4px; }
	.edge-diag-verdict.ok { background: #f0fdf4; color: #166534; }
	.edge-diag-actions { display: flex; gap: var(--space-2); margin-top: 4px; }
	.sync-progress-chip {
		display: inline-flex;
		gap: 6px;
		align-items: center;
		padding: 2px 8px;
		font-size: var(--font-size-xs);
		color: #b45309;
		background: #fef3c7;
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
	.glass-panel { position: absolute; left: 44%; top: 18%; width: 9%; height: 66%; border: 2px solid #5bb7c5; background: rgba(91, 183, 197, 0.16); }
	.goal-dot { position: absolute; right: 22%; top: 50%; width: 18px; height: 18px; border-radius: 50%; background: #37a169; }
	.hazard-zone { position: absolute; left: 39%; top: 39%; width: 18%; height: 28%; border: 2px solid #dd7a22; background: rgba(221, 122, 34, 0.18); }
	.map-grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 2px; height: 320px; }
	.map-grid div { background: #f7faf7; border: 1px solid #d6ddd4; }
	.map-grid .cell-obstacle { background: #1f2933; }
	.map-grid .cell-hazard { background: #dd7a22; }
	.map-grid .cell-start { background: #2f80ed; }
	.map-grid .cell-goal { background: #37a169; }
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
	.notice.error { background: #fff1f1; color: #9b1c1c; border: 1px solid #f0b4b4; }
	.notice.ok { background: #eef8f0; color: #236b35; border: 1px solid #abd7b5; }
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
	.rail-summary {
		cursor: pointer;
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
		font-weight: 800;
		list-style: none;
		text-transform: uppercase;
	}
	.rail-summary::-webkit-details-marker { display: none; }
	.rail-settings-body {
		width: auto;
		max-height: none;
		overflow: visible;
		border: 0;
		border-radius: 0;
		background: transparent;
		box-shadow: none;
		padding: var(--space-2) 0 0;
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
	.dataset-rail button.full { width: 100%; }
	.dataset-rail button.danger {
		color: #dc2626;
		border-color: #fca5a5;
	}
	.dataset-rail button.danger:hover { background: #fef2f2; }
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
	.rail-readiness {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	.rail-readiness span {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--muted-strong);
		padding: var(--space-2);
		text-align: center;
	}
	.rail-readiness span.ready {
		border-color: #abd7b5;
		background: #eef8f0;
		color: #236b35;
	}
	.rail-kv {
		display: grid;
		gap: var(--space-2);
		margin: 0;
	}
	.rail-kv div {
		display: grid;
		grid-template-columns: 88px minmax(0, 1fr);
		gap: var(--space-2);
		align-items: start;
	}
	.rail-kv dt {
		color: var(--muted);
		font-size: var(--font-size-xs);
	}
	.rail-kv dd {
		margin: 0;
		min-width: 0;
		overflow-wrap: anywhere;
		font-size: var(--font-size-xs);
		color: var(--text);
	}
	.dataset-bottom {
		display: grid;
		height: 100%;
		min-height: 32px;
		position: relative;
		background: var(--surface-1);
		color: var(--text);
	}
	/* Floating icon buttons — top-right overlay */
	.bottom-overlay-buttons {
		position: absolute;
		top: var(--space-2);
		right: var(--space-2);
		z-index: 10;
		display: flex;
		gap: var(--space-1);
	}
	.bottom-icon-btn {
		width: 26px;
		height: 26px;
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1, #fff);
		color: var(--muted-strong);
		font-size: 14px;
		cursor: pointer;
		opacity: 0.85;
		box-shadow: 0 1px 3px rgba(0,0,0,.08);
		transition: opacity 100ms;
	}
	.bottom-icon-btn:hover { opacity: 1; }
	.bottom-icon-btn:disabled { opacity: 0.4; cursor: default; }
	.dataset-bottom-body {
		display: grid;
		grid-template-columns: 360px minmax(0, 1fr);
		gap: var(--space-3);
		min-height: 0;
		overflow: hidden;
		padding: var(--space-3);
	}
	.bottom-progress {
		display: grid;
		gap: var(--space-2);
		align-content: start;
		border-right: 1px solid var(--panel-border);
		padding-right: var(--space-3);
		overflow-y: auto;
		min-height: 0;
	}
	.progress-head, .progress-metrics {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.progress-metrics {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}
	/* Job status chips */
	.js-chip { padding: 1px 6px; border-radius: 99px; font-size: 10px; font-weight: 600; }
	.js-chip.js-done { background: #d1fae5; color: #065f46; }
	.js-chip.js-running { background: #dbeafe; color: #1e40af; }
	.js-chip.js-queued { background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
	.js-chip.js-failed { background: #fee2e2; color: #991b1b; }
	/* Batch job grid */
	.batch-job-grid {
		margin-top: var(--space-2);
		overflow: auto;
		max-height: 160px;
	}
	.bjg-header, .bjg-row {
		display: flex;
		align-items: center;
		gap: 2px;
		margin-bottom: 2px;
	}
	.bjg-node-label {
		width: 28px;
		flex-shrink: 0;
		color: var(--muted);
		font-size: 9px;
		text-align: right;
		padding-right: 3px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.bjg-heading-label {
		width: 14px;
		flex-shrink: 0;
		color: var(--muted);
		font-size: 8px;
		text-align: center;
	}
	.bjg-cell {
		width: 12px;
		height: 12px;
		border: 0;
		border-radius: 2px;
		flex-shrink: 0;
		padding: 0;
		cursor: default;
		transition: opacity 80ms;
	}
	.bjg-cell:not(:disabled) { cursor: pointer; }
	.bjg-cell:hover { opacity: 0.7; }
	.bjg-cell.js-done { background: #34d399; }
	.bjg-cell.js-running { background: #60a5fa; animation: pulse-cell 1s ease-in-out infinite; }
	.bjg-cell.js-queued { background: #cbd5e1; }
	.bjg-cell.js-failed { background: #f87171; }
	.bjg-cell.js-cancelled { background: #fbbf24; }
	.bjg-cell.js-unknown { background: #e2e8f0; }
	.bjg-cell.bjg-selected { outline: 2px solid var(--brand, #6366f1); outline-offset: 1px; }
	@keyframes pulse-cell {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}
	/* Stale job controls */
	.stale-controls { margin-top: var(--space-1); }
	.stale-controls .button { font-size: 10px; padding: 2px 8px; }
	/* Job detail panel */
	.job-detail-panel {
		margin-top: var(--space-2);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		padding: var(--space-2);
		background: var(--surface-1);
		display: grid;
		gap: var(--space-2);
		font-size: var(--font-size-xs);
	}
	.job-detail-head {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.job-detail-id {
		font-family: monospace;
		font-size: 10px;
		color: var(--muted-strong);
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.job-detail-meta {
		color: var(--muted);
		font-size: 10px;
		display: flex;
		gap: 4px;
	}
	.bjg-close {
		background: none;
		border: none;
		cursor: pointer;
		color: var(--muted);
		padding: 0 2px;
		font-size: 11px;
		line-height: 1;
	}
	.bjg-close:hover { color: var(--fg); }
	/* Stage timeline */
	.stage-timeline {
		display: flex;
		gap: 2px;
		align-items: flex-start;
	}
	.stage-step {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 3px;
		flex: 1;
		color: var(--muted);
		font-size: 9px;
		text-align: center;
	}
	.stage-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: #e2e8f0;
		border: 1px solid #cbd5e1;
	}
	.stage-step.done .stage-dot { background: #34d399; border-color: #10b981; }
	.stage-step.active .stage-dot { background: #60a5fa; border-color: #3b82f6; animation: pulse-cell 1s ease-in-out infinite; }
	.stage-step.failed .stage-dot { background: #f87171; border-color: #ef4444; }
	.stage-step.done { color: var(--muted-strong); }
	.stage-step.active { color: #1d4ed8; font-weight: 600; }
	/* Job logs */
	.job-log-list {
		max-height: 100px;
		overflow-y: auto;
		display: grid;
		gap: 1px;
	}
	.job-log-row {
		display: flex;
		gap: var(--space-2);
		font-size: 10px;
		padding: 1px var(--space-1);
		background: var(--surface-2);
		color: var(--muted-strong);
	}
	.job-log-row.muted { color: var(--muted); font-style: italic; }
	.job-log-level { color: var(--muted); width: 30px; flex-shrink: 0; }
	.job-log-msg { overflow-wrap: anywhere; }
	.progress-track {
		height: 8px;
		overflow: hidden;
		border-radius: 999px;
		background: var(--surface-3);
		border: 1px solid var(--panel-border);
	}
	.progress-fill {
		height: 100%;
		background: var(--brand);
		transition: width 160ms ease;
	}
	.activity-log {
		display: grid;
		align-content: start;
		gap: 1px;
		min-height: 0;
		overflow: auto;
		font-size: var(--font-size-xs);
	}
	.activity-row {
		display: grid;
		grid-template-columns: 72px 148px minmax(180px, 0.8fr) minmax(220px, 1.2fr);
		gap: var(--space-2);
		align-items: start;
		padding: var(--space-1) var(--space-2);
		border-left: 3px solid var(--panel-border);
		background: var(--surface-2);
	}
	.activity-row.level-ok { border-left-color: #37a169; }
	.activity-row.level-warn { border-left-color: #dd7a22; }
	.activity-row.level-error { border-left-color: #c53030; }
	.activity-time, .activity-source, .activity-detail {
		color: var(--muted);
		overflow-wrap: anywhere;
	}
	.activity-message {
		color: var(--text);
		overflow-wrap: anywhere;
	}
	/* Batch log rows (backend job logs) */
	.log-section-head {
		padding: 2px var(--space-2);
		font-size: 9px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--muted);
		background: var(--surface-3, #e2e8f0);
	}
	.batch-log-row { grid-template-columns: 100px minmax(0, 1fr); border-left-color: #94a3b8; }
	.batch-log-job { font-family: monospace; font-size: 9px; }
	.batch-log-line { font-family: monospace; font-size: 10px; }
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

	.map-float-asset-catalog {
		position: absolute;
		left: 20px;
		top: 86px;
		z-index: 12;
		width: 292px;
		max-height: min(640px, calc(100vh - 180px));
		overflow: auto;
		border: 1px solid var(--panel-border);
		border-radius: 16px;
		background: rgba(255,255,255,0.92);
		box-shadow: 0 18px 45px rgba(15,23,42,0.14);
		backdrop-filter: blur(14px);
		padding: 10px;
	}
	.catalog-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 8px;
	}
	.catalog-head small {
		color: var(--muted-strong);
		font-size: 11px;
	}
	.catalog-tools {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
		margin-bottom: 10px;
	}
	.catalog-tools button {
		border: 1px solid var(--panel-border);
		border-radius: 10px;
		background: rgba(248,250,252,0.82);
		color: var(--text);
		font-weight: 800;
		padding: 8px 10px;
		cursor: pointer;
	}
	.catalog-tools button.active {
		border-color: var(--brand);
		background: #eff6ff;
		color: var(--brand);
	}
	.catalog-tools button.danger {
		color: #dc2626;
	}
	.catalog-tools button:disabled {
		opacity: 0.42;
		cursor: default;
	}
	.asset-section-title {
		margin: 8px 2px 6px;
		color: var(--brand);
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.12em;
		text-transform: uppercase;
	}
	.asset-subsection-title {
		margin: 8px 2px 5px;
		color: var(--muted);
		font-size: 11px;
		font-weight: 800;
	}
	.catalog-divider {
		height: 1px;
		background: var(--panel-border);
		margin: 10px 0;
	}
	.asset-card-list {
		display: grid;
		gap: 7px;
	}
	.library-assets {
		max-height: 310px;
		overflow: auto;
		padding-right: 2px;
	}
	.asset-search {
		width: 100%;
		border: 1px solid var(--panel-border);
		border-radius: 10px;
		background: #fff;
		color: var(--text);
		padding: 7px 9px;
	}
	.catalog-status {
		display: block;
		margin: 5px 2px;
		color: var(--text-muted);
	}
	.catalog-empty {
		display: grid;
		gap: 6px;
		border: 1px dashed var(--panel-border);
		border-radius: 10px;
		color: var(--text-muted);
		padding: var(--space-3);
		font-size: var(--font-size-xs);
		text-align: center;
	}
	.catalog-empty a {
		color: var(--brand);
		font-weight: 800;
	}
	.asset-card {
		display: grid;
		grid-template-columns: 42px 1fr auto;
		grid-template-rows: auto auto;
		column-gap: 9px;
		align-items: center;
		min-height: 56px;
		border: 1px solid var(--panel-border);
		border-radius: 10px;
		background: rgba(248,250,252,0.78);
		padding: 6px;
		text-align: left;
		cursor: pointer;
	}
	.asset-card:hover,
	.asset-card.selected {
		border-color: var(--brand);
		background: #eff6ff;
	}
	.asset-card :global(.asset-thumb),
	.asset-thumb-img {
		grid-row: 1 / span 2;
	}
	.asset-thumb-img {
		width: 42px;
		height: 42px;
		border-radius: 8px;
		background: linear-gradient(180deg, rgba(248,250,252,0.96), rgba(226,232,240,0.9));
		overflow: hidden;
		flex-shrink: 0;
	}
	.asset-thumb-img img {
		display: block;
		width: 100%;
		height: 100%;
		border-radius: inherit;
		object-fit: contain;
	}
	.asset-card span,
	.asset-card small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.asset-card span {
		color: var(--text);
		font-size: 12px;
		font-weight: 700;
	}
	.asset-card small {
		color: var(--text-muted);
		font-size: 10px;
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

	/* Paths panel */
	.paths-panel .episode-search {
		width: 100%;
		padding: 4px 8px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
	}
	.paths-panel .episode-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-height: 300px;
		overflow-y: auto;
	}
	.paths-panel .episode-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 6px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--font-size-xs);
		color: var(--text);
	}
	.paths-panel .episode-row:hover { background: var(--hover-bg); }
	.paths-panel .episode-row.selected { background: var(--accent-subtle); color: var(--accent); font-weight: 600; }
	.paths-panel .ep-id { font-family: monospace; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.paths-panel .ep-mode { color: var(--text-muted); font-size: 10px; }
	.paths-panel .badge-hazard { color: #f97316; }
	.paths-panel .episode-empty { color: var(--text-muted); font-size: var(--font-size-xs); padding: 8px 0; text-align: center; }
	.paths-panel .episode-generate-bar {
		display: flex;
		gap: 6px;
		align-items: center;
		border-top: 1px solid var(--panel-border);
		padding-top: var(--space-2);
	}
	.paths-panel .episode-generate-bar input { width: 60px; padding: 3px 6px; font-size: var(--font-size-xs); border: 1px solid var(--panel-border); border-radius: var(--radius-sm); }
	.paths-panel .episode-generate-bar button { flex: 1; }

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
		color: #92400e;
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

	/* Export mode panel */
	.export-panel .full { width: 100%; }
	.export-readiness-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
	.readiness-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); }
	.readiness-item.ok { color: #166534; }
	.readiness-dot { width: 8px; height: 8px; border-radius: 50%; background: #cbd5e1; flex-shrink: 0; }
	.readiness-item.ok .readiness-dot { background: #22c55e; }
	.export-stats { display: flex; flex-direction: column; gap: 2px; margin: 4px 0 8px; }
	.stat-row { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); padding: 1px 0; }
	.stat-row span:last-child { font-weight: 600; color: var(--text-primary); }
	.export-path-legend { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-muted); flex-wrap: wrap; }
	.legend-swatch { width: 20px; height: 3px; border-radius: 2px; flex-shrink: 0; }
	.legend-swatch.normal { background: #94a3b8; }
	.legend-swatch.hazard { background: #fca5a5; }
	.export-validation { font-size: 11px; padding: 4px 8px; border-radius: 4px; margin-top: 6px; }
	.export-validation.validation-ok { background: #dcfce7; color: #166534; }
	.export-validation.validation-fail { background: #fee2e2; color: #991b1b; }
	.val-errors { opacity: 0.8; }
	.export-path-display { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; overflow: hidden; }
	.export-path-text { color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

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
	.rail-settings-body {
		width: auto;
		max-height: none;
		overflow: visible;
		border: 0;
		border-radius: 0;
		background: transparent;
		box-shadow: none;
		padding: var(--space-2) 0 0;
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
		color: #475569;
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
	.chip-off { background: #f1f5f9; color: #94a3b8; }
	.chip-warn { background: #fef3c7; color: #92400e; padding: 1px 7px; border-radius: 99px; font-size: 10px; font-weight: 500; }
	.config-scene-ref { font-size: 10px; color: #64748b; padding: 2px 4px; background: #f1f5f9; border-radius: 4px; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; margin: 2px 0; }
	.config-scene-error { color: #b91c1c; background: #fef2f2; }
	.chip-dim { background: #f1f5f9; color: #475569; padding: 1px 7px; border-radius: 99px; font-size: 10px; font-weight: 500; }
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
	.map-float-inspector .geometry-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
	.map-float-inspector button.full { width: 100%; }
	.map-float-inspector button.danger { color: #dc2626; border-color: #fca5a5; }
	.map-float-inspector button.danger:hover { background: #fef2f2; }
</style>
