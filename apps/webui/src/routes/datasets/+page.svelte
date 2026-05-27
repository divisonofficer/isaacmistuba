<script lang="ts">
	import { onMount } from 'svelte';
	import AssetThumb3D from '$lib/AssetThumb3D.svelte';
	import MapEditor3D from '$lib/MapEditor3D.svelte';
	import { sceneBottomSnippet, sceneRailSnippet } from '$lib/stores/scenePortals';
	import { bottomPanelCollapsed, toggleBottomPanel } from '$lib/stores/shell';
	import {
		addOpticalNavScene,
		attachOpticalNavSceneUsd,
		buildOpticalNavMap,
		buildOpticalNavViewpointGraph,
		compileOpticalNavAuthoringMap,
		createOpticalNavProject,
		evaluateOpticalNavDataset,
		exportOpticalNavDataset,
		getOpticalNavEditorGeometry,
		getOpticalNavAuthoringMap,
		getOpticalNavGraphRenderBatch,
		getOpticalNavEpisode,
		getOpticalNavProject,
		getOpticalNavRenderBatch,
		getOpticalNavViewpointGraph,
		getSceneAnnotation,
		listOpticalNavEpisodes,
		listOpticalNavProjects,
		listOpticalNavUsdCandidates,
		materialLibrary,
		planOpticalNavGraphEpisodes,
		planOpticalNavEpisodes,
		renderOpticalNavEpisodes,
		saveOpticalNavAuthoringMap,
		saveSceneAnnotation,
		syncOpticalNavIsaacStage,
		syncOpticalNavRenderScene,
		sweepOpticalNavViewpointGraph,
		validateOpticalNavDataset
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
	const builtInBuildAssets = [
		{ id: 'glass_wall', label: 'Glass Wall', tool: 'glass_wall', category: 'glass', bounds: { size: [1.2, 1.4, 0.08] }, hint: 'line placement' },
		{ id: 'mirror_wall', label: 'Mirror Wall', tool: 'mirror_wall', category: 'mirror', bounds: { size: [1.2, 1.4, 0.08] }, hint: 'line placement' },
		{ id: 'traversable', label: 'Walkable Floor', tool: 'traversable', category: 'floor', bounds: { size: [1.2, 0.04, 1.0] }, hint: 'drag region' },
		{ id: 'goal', label: 'Goal Region', tool: 'goal', category: 'goal', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' },
		{ id: 'start', label: 'Start Region', tool: 'start', category: 'start', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' },
		{ id: 'hazard', label: 'Hazard Region', tool: 'hazard', category: 'hazard', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' },
		{ id: 'forbidden', label: 'Blocked Region', tool: 'forbidden', category: 'forbidden', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' },
		{ id: 'stop_before', label: 'Stop-before Region', tool: 'stop_before', category: 'goal', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' }
	];
	const builtInPlaceAssets = [
		{ id: 'chair', label: 'Chair', tool: 'chair', category: 'furniture', bounds: { size: [0.45, 0.8, 0.45] } },
		{ id: 'table', label: 'Table', tool: 'table', category: 'furniture', bounds: { size: [0.9, 0.72, 0.55] } },
		{ id: 'plant', label: 'Plant', tool: 'plant', category: 'object', bounds: { size: [0.35, 0.9, 0.35] } }
	];

	let loading = $state(false);
	let error = $state('');
	let info = $state('');
	let projects = $state<any[]>([]);
	let selectedProjectId = $state('');
	let project = $state<any>(null);
	let episodes = $state<any[]>([]);
	let selectedEpisodeId = $state('');
	let selectedEpisode = $state<any>(null);
	let episodeSearch = $state('');
	let selectedSensorNodeId = $state('');
	let activeModalityTab = $state('rgb');
	let sensorRenderResult = $state<any>(null);
	let renderingViewpoint = $state(false);

	let renderBatch = $state<any>(null);
	let renderBatchId = $state('');
	let graphBatch = $state<any>(null);
	let graphBatchId = $state('');

	let projectName = $state('OpticalNav-v0.2');
	let sceneId = $state('glass_corridor_001');
	let usdRef = $state('scenes/glass_corridor_001/scene.usd');
	let annotationText = $state('');
	let resolution = $state(0.05);
	let mapWidth = $state(6);
	let mapHeight = $state(4);
	let episodeCount = $state(80);
	let splits = $state('train:60,val_seen:10,val_unseen:10');
	let instructionTypes = $state('goal_only,hazard_aware,ambiguous');
	let graphScenarios = $state('goal_only,hazard_aware,stop_before_glass,detour');
	let seed = $state(0);
	let backend = $state('daemon');
	let renderMode = $state('graph_sweep');
	let renderSplit = $state('train');
	let maxNodes = $state(300);
	let headingCount = $state(12);
	let minNodeSpacing = $state(0.5);
	let robotRadius = $state(0.25);
	let kNeighbors = $state(8);
	let maxEdgeLength = $state(1.5);
	let selectedModalities = $state(['rgb', 'depth', 'active_nir_intensity', 'hazard_mask']);
	let sceneStateText = $state('');
	let cameraSpecText = $state('');
	let validationReport = $state<any>(null);
	let evaluationReport = $state<any>(null);
	let exportResult = $state<any>(null);
	let mapResult = $state<any>(null);
	let planResult = $state<any>(null);
	let graphResult = $state<any>(null);
	let graphPayload = $state<any>(null);
	let editor3DStatus = $state('');
	let editorGeometryPayload = $state<any>(null);
	let editorGeometryCatalogStatus = $state('USD asset catalog not loaded.');
	let editorGeometryCatalogKey = '';
	let selectedUsdAssetId = $state('');
	let usdCandidates = $state<any[]>([]);
	let selectedMoorelaneUsdRef = $state('');
	let usdCandidateStatus = $state('USD candidates not loaded.');
	let materialGroups = $state<any[]>([]);
	let materialLibraryStatus = $state('Material library not loaded.');
	let authoringMap = $state<any>(null);
	let authoringMapText = $state('');
	let compileResult = $state<any>(null);
	let syncResult = $state<any>(null);
	let isaacSyncResult = $state<any>(null);
	let authoringMapDirty = $state(false);
	let inspectorError = $state('');
	let selectedAuthoringId = $state('');
	type PlacementTool =
		| 'select'
		| 'glass_wall'
		| 'mirror_wall'
		| 'chair'
		| 'table'
		| 'plant'
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
		graphEdges: true
	});

	type PageMode = 'build' | 'place' | 'paths' | 'sensor' | 'sim' | 'export';
	let pageMode = $state<PageMode>('build');
	// MapEditor3D still uses 'simulate' for its internal pointer guards
	const mapEditorMode = $derived(pageMode === 'sim' ? 'simulate' : pageMode);

	type GhostGeom = { type: 'line'; x1: number; y1: number; x2: number; y2: number; valid: boolean }
		| { type: 'rect'; minX: number; minY: number; maxX: number; maxY: number; valid: boolean }
		| { type: 'point'; x: number; y: number; valid: boolean };
	let draftGhost = $state<GhostGeom | null>(null);

	let undoStack = $state<any[]>([]);
	let redoStack = $state<any[]>([]);
	const MAX_UNDO = 50;

	let robotPos = $state<{ x: number; y: number } | null>(null);
	let robotAnimTimer: ReturnType<typeof setInterval> | null = null;

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
	let activityLog = $state<ActivityEntry[]>([
		{
			id: 0,
			ts: new Date().toLocaleTimeString(),
			level: 'info',
			source: 'datasets',
			message: 'Dataset authoring ready. Start with project and scene setup.'
		}
	]);

	const projectScenes = $derived(project?.scenes ?? []);
	const splitCounts = $derived(project?.split_counts ?? {});
	const currentScene = $derived(projectScenes.find((item: any) => item.scene_id === sceneId) ?? null);
	const hasScene = $derived(Boolean(currentScene));
	const currentUsdRef = $derived(String(currentScene ? (currentScene.usd_ref || '') : (usdRef || '')));
	const hasPersistedAuthoringMap = $derived(Boolean(currentScene?.authoring_map_exists));
	const hasAuthoringMap = $derived(Boolean(hasPersistedAuthoringMap || authoringMap));
	const hasMap = $derived(Boolean(currentScene?.map_exists));
	const hasGraph = $derived(Boolean(currentScene?.viewpoint_graph_exists));
	const hasEpisodes = $derived(episodes.length > 0);
	const renderSceneSynced = $derived(currentScene?.sync_status?.render_scene === 'synced');
	const renderConfigReady = $derived(Boolean(renderSceneSynced && sceneStateText.trim() && cameraSpecText.trim()));
	const validationPassed = $derived(Boolean(validationReport && validationReport.ok !== false));
	const authoringObjects = $derived(authoringMap?.objects ?? []);
	const authoringRegions = $derived(authoringMap?.regions ?? []);
	const graphNodes = $derived(graphPayload?.nodes ?? []);
	const graphEdges = $derived(graphPayload?.edges ?? []);
	const selectedSensorNode = $derived(
		graphNodes.find((n: any) => n.node_id === selectedSensorNodeId) ?? null
	);
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
	const usdAssetCandidates = $derived((editorGeometryPayload?.objects ?? [])
		.filter((item: any) => item.category !== 'floor')
		.slice(0, 36));
	const selectedUsdAsset = $derived(usdAssetCandidates.find((item: any) => item.id === selectedUsdAssetId) ?? usdAssetCandidates[0] ?? null);
	const usdEditorReadiness = $derived.by(() => {
		if (!currentUsdRef) return { label: 'No USD attached', level: 'blocked' };
		if (editorGeometryPayload?.status === 'ready') return { label: 'USD proxy geometry ready', level: 'ready' };
		const reason = String(editorGeometryPayload?.reason ?? editorGeometryCatalogStatus ?? '');
		if (reason.toLowerCase().includes('does not exist')) return { label: 'USD path missing', level: 'blocked' };
		if (reason.toLowerCase().includes('pxr') || reason.toLowerCase().includes('unavailable')) return { label: 'USD extractor unavailable', level: 'blocked' };
		return { label: 'USD attached', level: 'pending' };
	});
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
			materials: [
				{ material_id: 'clear_glass', category: 'transparent' },
				{ material_id: 'mirror', category: 'reflective' },
				{ material_id: 'painted_wall', category: 'opaque' },
				{ material_id: 'wood', category: 'opaque' }
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

	function setAuthoringMapPayload(payload: any, dirty = true) {
		authoringMap = payload;
		authoringMapText = JSON.stringify(payload, null, 2);
		authoringMapDirty = dirty;
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
		if (!found) return [...materials, { material_id: materialId, category: 'custom', params: {} }];
		const { group, material } = found;
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

	function updateSelectedNavigation(field: string, value: unknown) {
		replaceSelectedAuthoringItem((item) => ({
			...item,
			navigation: {
				...(item.navigation ?? {}),
				[field]: field === 'hazard_type' && !value ? null : value
			}
		}));
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

	function dragLineHandle(id: string, handle: 'line_start' | 'line_end', point: { x: number; y: number }) {
		if (!authoringMap) return;
		if (selectedAuthoringId !== id) selectedAuthoringId = id;
		const objects = (authoringMap.objects ?? []).map((item: any) => {
			if (item.id !== id || item.geometry?.type !== 'line') return item;
			const geometry = { ...(item.geometry ?? {}) };
			if (handle === 'line_start') geometry.start = [clampMapNumber(point.x, 'x'), clampMapNumber(point.y, 'y')];
			else geometry.end = [clampMapNumber(point.x, 'x'), clampMapNumber(point.y, 'y')];
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

	function friendlyUsdCatalogMessage(payload: any) {
		if (!currentUsdRef) return 'No USD scene is attached to this OpticalNav scene.';
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

	async function loadEditorGeometryCatalog(force = false) {
		const key = `${selectedProjectId}:${sceneId}:${currentUsdRef}`;
		if (!selectedProjectId || !sceneId || (!force && key === editorGeometryCatalogKey)) return;
		editorGeometryCatalogKey = key;
		try {
			editorGeometryCatalogStatus = 'Loading USD asset proxies...';
			const payload = await getOpticalNavEditorGeometry(selectedProjectId, sceneId);
			editorGeometryPayload = payload;
			editorGeometryCatalogStatus = friendlyUsdCatalogMessage(payload);
			const count = (payload.objects ?? []).filter((item: any) => item.category !== 'floor').length;
			if (!selectedUsdAssetId && count) {
				const first = (payload.objects ?? []).find((item: any) => item.category !== 'floor');
				selectedUsdAssetId = first?.id ?? '';
			}
		} catch (err) {
			editorGeometryPayload = null;
			editorGeometryCatalogStatus = err instanceof Error ? `USD asset catalog unavailable: ${err.message}` : 'USD asset catalog unavailable.';
		}
	}

	function usdAssetLabel(asset: any) {
		return String(asset?.label || asset?.source_path || asset?.id || 'USD object').split('/').pop();
	}

	function placementHintForTool(tool: string) {
		if (tool === 'glass_wall' || tool === 'mirror_wall') return 'line placement';
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
		type: 'glass_wall' | 'mirror_wall',
		start: { x: number; y: number },
		end: { x: number; y: number }
	) {
		pushHistory();
		const map = ensureAuthoringMap();
		const id = nextAuthoringId(type);
		const isGlass = type === 'glass_wall';
		const object = {
			id,
			type,
			label: isGlass ? 'Glass wall' : 'Mirror wall',
			placement: 'line',
			geometry: {
				type: 'line',
				start: [start.x, start.y],
				end: [end.x, end.y],
				height_m: 2.4,
				thickness_m: 0.08
			},
			material: isGlass ? 'clear_glass' : 'mirror',
			navigation: {
				blocks_navigation: true,
				hazard_type: isGlass ? 'transparent_obstacle' : 'reflective_obstacle',
				include_in_hazard_mask: true,
				instruction_candidate: true,
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

	function addUsdAssetObject(center: { x: number; y: number }) {
		if (!selectedUsdAsset) {
			pushActivity('warn', 'asset-catalog', 'Select a USD asset before placing.');
			return;
		}
		pushHistory();
		const map = ensureAuthoringMap();
		const type = typeForUsdAsset(selectedUsdAsset);
		const id = nextAuthoringId(type);
		const sourceRef = `${editorGeometryPayload?.usd_ref ?? currentUsdRef}#${selectedUsdAsset.source_path ?? selectedUsdAsset.id}`;
		const size = selectedUsdAsset.bounds?.size ?? [0.35, 0.5, 0.35];
		const object = {
			id,
			type,
			label: usdAssetLabel(selectedUsdAsset),
			placement: 'point',
			geometry: {
				type: 'point',
				center: [center.x, center.y],
				yaw_deg: 0
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
				created_by: 'webui_usd_asset_catalog',
				asset_id: selectedUsdAsset.id,
				asset_category: selectedUsdAsset.category,
				asset_source_path: selectedUsdAsset.source_path,
				proxy_size: size
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
	function handleGroundPointerDown(point: { x: number; y: number }) {
		contextMenu = null;
		if (placementTool === 'select') {
			selectedAuthoringId = '';
			return;
		}
		if (placementTool === 'chair' || placementTool === 'table' || placementTool === 'plant') {
			addPointObject(placementTool, point);
			return;
		}
		if (placementTool === 'usd_asset') {
			addUsdAssetObject(point);
			return;
		}
		if (placementTool === 'glass_wall' || placementTool === 'mirror_wall') {
			if (!draftPoint) {
				draftPoint = point;
				linePreview = point;
			} else {
				const distance = Math.hypot(point.x - draftPoint.x, point.y - draftPoint.y);
				if (distance >= 0.1) addWallObject(placementTool, draftPoint, point);
				draftPoint = null;
				linePreview = null;
			}
			return;
		}
		dragStart = point;
		dragPreview = point;
	}

	function handleGroundPointerMove(point: { x: number; y: number }) {
		if (point.x < 0 || point.y < 0) { draftGhost = null; return; } // mouseleave sentinel
		if (draftPoint && (placementTool === 'glass_wall' || placementTool === 'mirror_wall')) {
			linePreview = point;
		}
		if (dragStart) {
			dragPreview = point;
		}
		const inBounds = point.x > 0.05 && point.x < 5.95 && point.y > 0.05 && point.y < 3.95;
		if (placementTool === 'glass_wall' || placementTool === 'mirror_wall') {
			if (draftPoint) {
				draftGhost = { type: 'line', x1: draftPoint.x, y1: draftPoint.y, x2: point.x, y2: point.y, valid: inBounds };
			} else {
				draftGhost = { type: 'point', x: point.x, y: point.y, valid: inBounds };
			}
		} else if (placementTool === 'chair' || placementTool === 'table' || placementTool === 'plant' || placementTool === 'usd_asset') {
			draftGhost = { type: 'point', x: point.x, y: point.y, valid: inBounds };
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

	function handleGroundPointerUp(point: { x: number; y: number }) {
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
		pageMode = 'sim';
		placementTool = 'select';
		pushActivity('info', 'preview', `Preview pose set near ${selectedAuthoringId}. Sensor render preview still requires render config.`);
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
		if ((event.key === 'Delete' || event.key === 'Backspace') && selectedAuthoringId) {
			const target = event.target as HTMLElement | null;
			if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return;
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
		pageMode = 'sim';
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

	const tabToMode: Record<string, PageMode> = { scene: 'build', plan: 'paths', render: 'sensor', review: 'export' };
	async function runPrimaryAction() {
		const readiness = currentReadiness;
		pageMode = tabToMode[readiness.tab] ?? 'build';
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
		pushActivity('info', source, 'Request started.');
		try {
			const result = await fn();
			if (success) info = success;
			pushActivity('ok', source, success ?? 'Request completed.', result);
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
		await refreshEpisodes();
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
			'Map overlay loaded.',
			'authoring-map:load'
		);
		if (data) setAuthoringMapPayload(data, false);
	}

	async function saveAuthoringMap() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before saving the map overlay.')) return;
		let payload: unknown;
		try {
			payload = currentAuthoringMap();
		} catch (err) {
			error = `Invalid authoring_map JSON: ${errorMessage(err)}`;
			pushActivity('error', 'authoring-map:save', error);
			return;
		}
		const data = await run(
			() => saveOpticalNavAuthoringMap(selectedProjectId, sceneId, payload),
			'Map overlay saved.',
			'authoring-map:save'
		);
		if (data?.authoring_map) setAuthoringMapPayload(data.authoring_map, false);
		await refreshProject();
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
		const data = await run(
			() => buildOpticalNavMap(selectedProjectId, sceneId, { resolution: Number(resolution) }),
			'Traversable grid built.',
			'map:build'
		);
		if (data) mapResult = data;
		await refreshProject();
	}

	async function syncRenderScene() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasScene, 'Add the scene before syncing render scene.')) return;
		const data = await run(
			() => syncOpticalNavRenderScene(selectedProjectId, sceneId, {}),
			'Render-scene sync checked.',
			'sync:render-scene'
		);
		if (data) syncResult = data;
		await refreshProject();
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

	async function buildGraph() {
		if (!requireReady(Boolean(selectedProjectId), 'Create or select a project first.')) return;
		if (!requireReady(hasMap, 'Build the traversable grid before building a viewpoint graph.')) return;
		const data = await run(
			() =>
				buildOpticalNavViewpointGraph(selectedProjectId, sceneId, {
					max_nodes: Number(maxNodes),
					heading_count: Number(headingCount),
					min_node_spacing_m: Number(minNodeSpacing),
					robot_radius_m: Number(robotRadius),
					k_neighbors: Number(kNeighbors),
					max_edge_length_m: Number(maxEdgeLength),
					seed: Number(seed)
				}),
			'Viewpoint graph built.',
			'graph:build'
		);
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

	async function renderSensorViewpoint() {
		if (!selectedSensorNode || !selectedProjectId || !sceneId) return;
		renderingViewpoint = true;
		sensorRenderResult = null;
		const body = {
			modalities: [activeModalityTab],
			node_ids: [selectedSensorNode.node_id],
			backend
		};
		try {
			const data = await sweepOpticalNavViewpointGraph(selectedProjectId, sceneId, body);
			if (data?.batch_id) {
				graphBatchId = data.batch_id;
				graphBatch = data;
				sensorRenderResult = { batch_id: data.batch_id, status: 'submitted' };
				pushActivity('ok', 'sensor:render', `Render submitted: batch ${data.batch_id}`);
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
		const body: Record<string, unknown> = {
			modalities: selectedModalities,
			backend
		};
		if (scene_state) body.scene_state = scene_state;
		if (camera_spec) body.camera_spec = camera_spec;
		if (renderMode === 'graph_sweep') {
			if (!sceneId) return;
			const data = await run(() => sweepOpticalNavViewpointGraph(selectedProjectId, sceneId, body), 'Graph sensor sweep submitted.', 'graph:sweep');
			if (data?.batch_id) {
				graphBatchId = data.batch_id;
				graphBatch = data;
			}
		} else {
			body.split = renderSplit;
			const data = await run(() => renderOpticalNavEpisodes(selectedProjectId, body), 'Episode render request submitted.', 'episodes:render');
			if (data?.batch_id) {
				renderBatchId = data.batch_id;
				renderBatch = data;
			}
		}
		await refreshEpisodes();
	}

	async function refreshBatch() {
		if (!selectedProjectId) return;
		if (renderMode === 'graph_sweep') {
			if (!graphBatchId) return;
			const data = await run(() => getOpticalNavGraphRenderBatch(selectedProjectId, graphBatchId), undefined, 'batch:graph');
			if (data) graphBatch = data;
		} else {
			if (!renderBatchId) return;
			const data = await run(() => getOpticalNavRenderBatch(selectedProjectId, renderBatchId), undefined, 'batch:episodes');
			if (data) renderBatch = data;
		}
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
		const params = new URLSearchParams(window.location.search);
		const initProject = params.get('project') ?? '';
		const initScene = params.get('scene') ?? '';
		if (initProject) selectedProjectId = initProject;
		if (initScene) sceneId = initScene;
		refreshProjects(initProject || selectedProjectId);
		loadMaterialLibrary();
		loadUsdCandidates();
	});

	$effect(() => {
		const p = selectedProjectId;
		const s = sceneId;
		const url = new URL(window.location.href);
		if (p) url.searchParams.set('project', p); else url.searchParams.delete('project');
		if (s) url.searchParams.set('scene', s); else url.searchParams.delete('scene');
		history.replaceState(history.state, '', url.toString());
	});

	$effect(() => {
		selectedProjectId;
		sceneId;
		currentUsdRef;
		void loadEditorGeometryCatalog();
	});

	async function setPageMode(mode: PageMode) {
		if (mode !== 'sim') stopRobotAnimation();
		pageMode = mode;
		placementTool = 'select';
		draftPoint = null;
		linePreview = null;
		dragStart = null;
		dragPreview = null;
		draftGhost = null;
		if (!selectedProjectId) return;
		if (mode === 'sim') {
			if (!hasMap && hasScene) await buildMap();
			if (!hasGraph && hasMap) await buildGraph();
			if (graphPayload?.nodes?.length) {
				startRobotAnimation();
			} else if (hasGraph) {
				await loadGraph();
				startRobotAnimation();
			}
			return;
		}
		if ((mode === 'paths' || mode === 'sensor') && !graphPayload && hasGraph) {
			await loadGraph();
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
			<button class:ready={hasScene} onclick={() => (pageMode = 'build')}>Scene {hasScene ? 'ready' : 'missing'}</button>
			<button class:ready={hasAuthoringMap} onclick={() => (pageMode = 'build')}>Overlay {hasAuthoringMap ? 'ready' : 'missing'}</button>
			<button class:ready={hasMap} onclick={() => (pageMode = 'paths')}>Map {hasMap ? 'ready' : 'missing'}</button>
			<button class:ready={hasGraph} onclick={() => (pageMode = 'paths')}>Viewpoint graph {hasGraph ? 'ready' : 'missing'}</button>
			<button class:ready={hasEpisodes} onclick={() => (pageMode = 'export')}>Episodes {hasEpisodes ? episodes.length : 'missing'}</button>
			<button class:ready={renderSceneSynced} onclick={() => (pageMode = 'build')}>Render scene {renderSceneSynced ? 'synced' : 'pending'}</button>
			<button class:ready={renderConfigReady} onclick={() => (pageMode = 'sensor')}>Render config {renderConfigReady ? 'ready' : 'missing'}</button>
		</section>
	{/if}

		<section class="map-editor-fullbleed">
			<!-- 3D canvas fills the entire section -->
			<MapEditor3D
				projectId={selectedProjectId}
				{sceneId}
				geometryKey={currentUsdRef}
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
				onObjectSelect={(id) => {
					const isNode = graphNodes.some((n: any) => n.node_id === id);
					if (isNode && pageMode === 'sensor') {
						selectedSensorNodeId = id;
						sensorRenderResult = null;
					} else {
						selectAuthoringItem(id);
					}
				}}
				onObjectContextMenu={handleContextMenu}
				onHandleDrag={dragLineHandle}
				highlightedPath={selectedEpisodePath}
				mapBounds={{ w: mapWidth, h: mapHeight }}
				onStatus={(message) => (editor3DStatus = message)}
			/>

			<!-- Floating top bar: project badge + modes + undo/redo + view presets -->
			<div class="map-float-top">
				<!-- Project badge (collapsed from hidden strip) -->
				{#if selectedProjectId}
					<span class="map-proj-badge">{selectedProjectId}</span>
					<div class="map-float-sep"></div>
				{/if}
				<div class="map-float-modes">
					<button class:active={pageMode === 'build'} onclick={() => setPageMode('build')}>Build</button>
					<button class:active={pageMode === 'place'} onclick={() => setPageMode('place')}>Place</button>
					<button class:active={pageMode === 'paths'} onclick={() => setPageMode('paths')}>Paths</button>
					<button class:active={pageMode === 'sensor'} onclick={() => setPageMode('sensor')}>Sensor</button>
					<button class:active={pageMode === 'sim'} onclick={() => setPageMode('sim')}>Sim</button>
					<button class:active={pageMode === 'export'} onclick={() => setPageMode('export')}>Export</button>
				</div>
				<div class="map-float-sep"></div>
				<button class="map-float-btn" title="Undo (Ctrl+Z)" disabled={!undoStack.length} onclick={undo}>↩</button>
				<button class="map-float-btn" title="Redo (Ctrl+Y)" disabled={!redoStack.length} onclick={redo}>↪</button>
				<div class="map-float-sep"></div>
				<span class="map-float-hint">
					{#if pageMode === 'sim'}
						Simulating · Esc to exit
					{:else if placementTool === 'glass_wall' || placementTool === 'mirror_wall'}
						{draftPoint ? 'Click end point · Esc cancel' : `Placing ${placementTool.replace('_', ' ')} · click start`}
					{:else if ['chair','table','plant','usd_asset'].includes(placementTool)}
						Click to place {placementTool === 'usd_asset' ? usdAssetLabel(selectedUsdAsset) : placementTool} · Esc cancel
					{:else if placementTool !== 'select'}
						Drag rectangle · Esc cancel
					{:else}
						Right-drag orbit · Wheel zoom · Left-click select
					{/if}
				</span>
				<div style="flex:1"></div>
			</div>

			<!-- Floating left palette -->
			<div class="map-float-palette">
				<button class:active={placementTool === 'select'} class="pbutton" title="Select (V)" onclick={() => { placementTool = 'select'; draftPoint = null; }}>⬚</button>
				{#if pageMode === 'build'}
					<div class="pgroup-sep"></div>
					<span class="palette-mini-label">Build</span>
				{:else if pageMode === 'place'}
					<div class="pgroup-sep"></div>
					<span class="palette-mini-label">Place</span>
				{/if}
				{#if pageMode !== 'sim'}
					<div class="pgroup-sep"></div>
					<button class="pbutton pbutton-danger" title="Delete selected (Del)" disabled={!selectedAuthoringId} onclick={deleteSelectedAuthoringItem}>⌫</button>
				{/if}
			</div>

			{#if pageMode === 'build'}
				<div class="map-float-asset-catalog build-catalog">
					<div class="catalog-head">
						<div>
							<div class="panel-label">Build Catalog</div>
							<small>Structure and navigation layers.</small>
						</div>
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
			{:else if pageMode === 'place'}
				<div class="map-float-asset-catalog">
					<div class="catalog-head">
						<div>
							<div class="panel-label">Place Catalog</div>
							<small>Furniture, landmarks, and imported USD objects.</small>
						</div>
						<button class="button button-subtle" title="Reload USD proxy catalog" onclick={() => loadEditorGeometryCatalog(true)}>↺</button>
					</div>
					<div class="asset-section-title">Built-in Assets</div>
					<div class="asset-card-list">
						{#each builtInPlaceAssets as asset}
							<button
								class:selected={placementTool === asset.tool}
								class="asset-card"
								title={asset.label}
								onclick={() => selectBuiltInAsset(asset.tool)}
							>
								<AssetThumb3D category={asset.category} assetType={asset.tool} bounds={asset.bounds} selected={placementTool === asset.tool} />
								<span>{asset.label}</span>
								<small>{placementHintForTool(asset.tool)}</small>
							</button>
						{/each}
					</div>
					<div class="catalog-divider"></div>
					<div class="asset-section-title">USD Assets</div>
					<div class="usd-readiness" class:ready={usdEditorReadiness.level === 'ready'}>
						<span>{usdEditorReadiness.label}</span>
						{#if editorGeometryPayload?.extractor && editorGeometryPayload.status !== 'ready'}
							<details>
								<summary>Advanced extractor details</summary>
								<pre>{JSON.stringify(editorGeometryPayload.extractor, null, 2)}</pre>
							</details>
						{/if}
					</div>
					{#if !currentUsdRef}
						<div class="attach-usd-box">
							<p>No USD scene is attached to this OpticalNav scene.</p>
							<label>
								<span>Moorelane USD</span>
								<select bind:value={selectedMoorelaneUsdRef}>
									{#each usdCandidates as candidate}
										<option value={candidate.usd_ref}>{candidate.label}</option>
									{/each}
								</select>
							</label>
							<small>{usdCandidateStatus}</small>
							<div class="action-row">
								<button class="button button-primary" disabled={!selectedMoorelaneUsdRef || loading} onclick={() => attachUsdScene(selectedMoorelaneUsdRef)}>Attach Moorelane USD</button>
								<button class="button button-subtle" onclick={loadUsdCandidates}>Reload Candidates</button>
							</div>
						</div>
					{/if}
					{#if usdAssetCandidates.length}
						<div class="asset-card-list">
							{#each usdAssetCandidates as asset}
								<button
									class:selected={selectedUsdAssetId === asset.id}
									class="asset-card"
									title={asset.source_path}
									onclick={() => { selectedUsdAssetId = asset.id; placementTool = 'usd_asset'; draftPoint = null; }}
								>
									<AssetThumb3D category={asset.category} bounds={asset.bounds} selected={selectedUsdAssetId === asset.id} />
									<span>{usdAssetLabel(asset)}</span>
									<small>{asset.category}</small>
								</button>
							{/each}
						</div>
					{:else}
						<div class="attach-usd-box muted">
							<p>{currentUsdRef ? 'No USD object proxies are available yet.' : 'Attach a Moorelane USD scene to populate this catalog.'}</p>
							{#if currentUsdRef}
								<div class="action-row">
									<button class="button button-subtle" onclick={() => loadEditorGeometryCatalog(true)}>Reload Geometry</button>
									<button class="button button-subtle" onclick={() => { editorGeometryPayload = null; editorGeometryCatalogStatus = 'Using empty editor floor.'; }}>Use Empty Editor Floor</button>
								</div>
							{/if}
						</div>
					{/if}
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
					</div>
				</div>
			{/if}

			<!-- Sensor mode: viewpoint render panel -->
			{#if pageMode === 'sensor'}
				<div class="map-float-inspector sensor-panel">
					{#if selectedSensorNode}
						<div class="panel-label">Viewpoint</div>
						<div class="sensor-node-id">{selectedSensorNodeId}</div>
						<div class="sensor-pos">x={selectedSensorNode.position?.[0]?.toFixed(2)} z={selectedSensorNode.position?.[1]?.toFixed(2)}</div>
						<!-- Modality tabs -->
						<div class="modality-tabs">
							{#each ['rgb','depth','active_nir_intensity','hazard_mask'] as mod}
								<button class:active-tab={activeModalityTab === mod} onclick={() => { activeModalityTab = mod; sensorRenderResult = null; }}>{mod}</button>
							{/each}
						</div>
						{#if sensorRenderResult}
							<div class="sensor-result">
								<span class="chip-ok">Batch {sensorRenderResult.batch_id?.slice(0,8)}...</span>
								<button class="button button-subtle" onclick={refreshBatch}>Refresh</button>
							</div>
							{#if graphBatch?.progress}
								<div class="sensor-progress">{graphBatch.progress.completed}/{graphBatch.progress.total} rendered</div>
							{/if}
						{/if}
						<button class="button button-primary full" disabled={renderingViewpoint || !selectedProjectId || !hasGraph} onclick={renderSensorViewpoint}>
							{renderingViewpoint ? 'Rendering...' : 'Render this viewpoint'}
						</button>
						<button class="button button-subtle full" disabled={loading || !selectedProjectId || !hasGraph} onclick={renderEpisodes}>
							Render all viewpoints
						</button>
					{:else}
						<div class="sensor-hint">Click a viewpoint (blue dot) to select it</div>
					{/if}
				</div>
			{/if}

			<!-- Floating right inspector (only when item selected in build/place mode) -->
			{#if selectedAuthoringItem && (pageMode === 'build' || pageMode === 'place')}
				<div class="map-float-inspector">
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
					<label>
						<span>label</span>
						<input
							value={selectedAuthoringItem.label ?? ''}
							oninput={(event) => updateSelectedField('label', (event.currentTarget as HTMLInputElement).value)}
						/>
					</label>
					{#if selectedAuthoringKind === 'object'}
						{#if selectedAuthoringItem.source_ref}
							<div class="material-info">
								<strong>USD source</strong>
								<small>{selectedAuthoringItem.source_ref}</small>
							</div>
						{/if}
						<label>
							<span>material</span>
							<select
								value={selectedAuthoringItem.material ?? ''}
								onchange={(event) => updateSelectedMaterial((event.currentTarget as HTMLSelectElement).value)}
							>
								<option value="">none</option>
								<optgroup label="OpticalNav presets">
									{#each materialPresetIds as mat}
										<option value={mat}>{mat}</option>
									{/each}
								</optgroup>
								{#each materialGroups as group}
									{#if group.materials?.length}
										<optgroup label={`${group.display_name ?? group.dataset_id} (${group.dataset_id})`}>
											{#each group.materials as mat}
												<option value={materialValue(group, mat)}>{materialOptionLabel(mat)}</option>
											{/each}
										</optgroup>
									{/if}
								{/each}
							</select>
						</label>
						{#if selectedMaterialInfo}
							<div class="material-info">
								<strong>{selectedMaterialInfo.label}</strong>
								<span>{selectedMaterialInfo.detail}</span>
								{#if selectedMaterialInfo.native_file}<small>{selectedMaterialInfo.native_file}</small>{/if}
							</div>
						{:else}
							<p class="inline-hint">{materialLibraryStatus}</p>
						{/if}
						{#if selectedMaterialSuggestion}
							<p class="suggestion">{selectedMaterialSuggestion}</p>
						{/if}
					{/if}
					<div class="preset-row">
						<button class="button button-subtle" onclick={() => applyInspectorPreset('glass')}>Glass</button>
						<button class="button button-subtle" onclick={() => applyInspectorPreset('mirror')}>Mirror</button>
						<button class="button button-subtle" onclick={() => applyInspectorPreset('landmark')}>Landmark</button>
						<button class="button button-subtle" onclick={() => applyInspectorPreset('traversable')}>Walkable</button>
					</div>
					<details class="inspector-section geometry-advanced">
						<summary>Advanced geometry</summary>
						<p class="inline-hint">Use the scene handles for common edits. Numeric values are for precise adjustment.</p>
						{#if selectedAuthoringItem.geometry?.type === 'point'}
							<div class="geometry-grid">
								<label><span>Position X</span><input type="number" min="0" max="6" step="0.01" value={selectedAuthoringItem.geometry.center?.[0] ?? 0} oninput={(event) => updateSelectedPointGeometry('x', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Position Y</span><input type="number" min="0" max="4" step="0.01" value={selectedAuthoringItem.geometry.center?.[1] ?? 0} oninput={(event) => updateSelectedPointGeometry('y', (event.currentTarget as HTMLInputElement).value)} /></label>
								<label><span>Yaw</span><input type="number" step="1" value={selectedAuthoringItem.geometry.yaw_deg ?? 0} oninput={(event) => updateSelectedPointGeometry('yaw_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
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
					<button class="button button-subtle full danger" onclick={deleteSelectedAuthoringItem}>Delete {selectedAuthoringId}</button>
				</div>
			{/if}

			<!-- Floating bottom status bar -->
			<div class="map-float-status">
				<span>{authoringSummary.objects}obj</span>
				<span>{authoringSummary.regions}reg</span>
				<span>{authoringSummary.glass}glass</span>
				<span class:ready={usdEditorReadiness.level === 'ready'}>{usdEditorReadiness.label}</span>
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
							<select class="scene-select" value={sceneId} onchange={(e) => { sceneId = e.currentTarget.value; loadAuthoringMap(); episodes = []; selectedEpisode = null; selectedEpisodeId = ''; graphPayload = null; }}>
								{#each projectScenes as item}
									<option value={item.scene_id}>{item.scene_id}</option>
								{/each}
							</select>
						</label>
					{/if}
					<label><span>scene_id</span><input bind:value={sceneId} /></label>
					<label><span>usd_ref</span><input bind:value={usdRef} /></label>
					<label>
						<span>Moorelane USD</span>
						<select bind:value={selectedMoorelaneUsdRef}>
							{#each usdCandidates as candidate}
								<option value={candidate.usd_ref}>{candidate.label}</option>
							{/each}
						</select>
					</label>
					<div class="geometry-grid">
						<label><span>map W (m)</span><input type="number" min="1" max="100" step="0.5" bind:value={mapWidth} /></label>
						<label><span>map H (m)</span><input type="number" min="1" max="100" step="0.5" bind:value={mapHeight} /></label>
					</div>
					<div class="action-row">
						<button class="button button-subtle" disabled={!selectedProjectId || loading} onclick={addScene}>Add Scene</button>
						<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || !selectedMoorelaneUsdRef || loading} onclick={() => attachUsdScene(selectedMoorelaneUsdRef)}>Attach USD</button>
						<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || loading} onclick={() => loadEditorGeometryCatalog(true)}>Reload Geometry</button>
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
							<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || loading} onclick={syncRenderScene}>Check Sync</button>
						</div>
					{/if}
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
					<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || loading} onclick={buildMap}>
						{hasMap ? 'Rebuild Grid' : 'Build Grid'}
					</button>
					<!-- Viewpoint graph -->
					<div class="panel-label mt-2">Viewpoint Graph</div>
					<div class="geometry-grid">
						<label><span>max nodes</span><input type="number" min="1" bind:value={maxNodes} /></label>
						<label><span>headings</span><input type="number" min="1" bind:value={headingCount} /></label>
						<label><span>spacing m</span><input type="number" step="0.05" min="0" bind:value={minNodeSpacing} /></label>
						<label><span>robot r</span><input type="number" step="0.05" min="0" bind:value={robotRadius} /></label>
					</div>
					<button class="button button-subtle" disabled={!selectedProjectId || !hasMap || loading} onclick={buildGraph}>
						{hasGraph ? 'Rebuild Graph' : 'Build Graph'}
					</button>
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
			<button role="menuitem" onclick={() => { applyInspectorPreset('glass'); closeContextMenu(); }}>Set: Glass hazard</button>
			<button role="menuitem" onclick={() => { applyInspectorPreset('mirror'); closeContextMenu(); }}>Set: Mirror hazard</button>
			<button role="menuitem" onclick={() => { applyInspectorPreset('landmark'); closeContextMenu(); }}>Set: Landmark goal</button>
		{/if}
		<hr />
		<button role="menuitem" onclick={previewFromSelected}>Preview from here</button>
		<button role="menuitem" onclick={() => createRegionAroundSelected('start')}>Set as robot start</button>
		<button role="menuitem" onclick={() => createRegionAroundSelected('goal')}>Set as goal</button>
		<hr />
		<button role="menuitem" class="danger" onclick={contextMenuDelete}>Delete</button>
	</div>
{/if}

{#snippet datasetRailContent()}
	<div class="dataset-rail">
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
	</div>
{/snippet}

{#snippet datasetBottomContent()}
	<div class="dataset-bottom">
		<div class="dataset-bottom-head">
			<button class="bottom-toggle" onclick={toggleBottomPanel} aria-label="Toggle bottom panel">
				{$bottomPanelCollapsed ? 'Show' : 'Hide'}
			</button>
			<div>
				<div class="bottom-title">OpticalNav 작업 로그</div>
				<div class="bottom-subtitle">
					{#if activeBatch}
						{activeBatch.batch_id ?? 'batch'} · {bottomProgress?.completed ?? 0}/{bottomProgress?.total ?? 0} complete · {bottomProgress?.failed ?? 0} failed
					{:else}
						API 요청, guard, render batch 진행 상태
					{/if}
				</div>
			</div>
			{#if activeBatch}
				<button class="button button-subtle bottom-refresh" disabled={loading} onclick={refreshBatch}>Refresh Batch</button>
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
						<span>batch {activeBatch?.batch_id ?? '-'}</span>
						<span>total {bottomProgress?.total ?? 0}</span>
						<span>done {bottomProgress?.completed ?? 0}</span>
						<span>failed {bottomProgress?.failed ?? 0}</span>
					</div>
				</section>

				<section class="activity-log" aria-label="OpticalNav activity log">
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
		min-height: 0;
		background: var(--surface-1);
		color: var(--text);
	}
	.dataset-bottom-head {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 46px;
		padding: var(--space-2) var(--space-3);
		border-bottom: 1px solid var(--panel-border);
	}
	.bottom-toggle {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-2);
		color: var(--muted-strong);
		height: 28px;
		padding: 0 var(--space-2);
	}
	.bottom-title {
		font-size: var(--font-size-sm);
		font-weight: 700;
	}
	.bottom-subtitle {
		margin-top: 2px;
		color: var(--muted);
		font-size: var(--font-size-xs);
	}
	.bottom-refresh { margin-left: auto; }
	.dataset-bottom-body {
		display: grid;
		grid-template-columns: 360px minmax(0, 1fr);
		gap: var(--space-3);
		min-height: 0;
		padding: var(--space-3);
	}
	.bottom-progress {
		display: grid;
		gap: var(--space-2);
		align-content: start;
		border-right: 1px solid var(--panel-border);
		padding-right: var(--space-3);
	}
	.progress-head, .progress-metrics {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
		color: var(--muted-strong);
		font-size: var(--font-size-xs);
	}
	.progress-metrics {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
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

	/* Floating left palette */
	.map-float-palette {
		position: absolute;
		top: 54px;
		left: 10px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 3px;
		padding: 6px 5px;
		background: rgba(255, 255, 255, 0.92);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		backdrop-filter: blur(10px);
		z-index: 10;
		box-shadow: 0 1px 4px rgba(0,0,0,0.08);
	}
	.pbutton {
		width: 34px;
		height: 34px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: transparent;
		cursor: pointer;
		font-size: 14px;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--text);
		font-weight: 600;
	}
	.pbutton:hover { background: var(--hover-bg); }
	.pbutton.active { border-color: var(--brand); background: #eff6ff; color: var(--brand); }
	.pbutton:disabled { opacity: 0.35; cursor: default; }
	.pbutton-glass { color: #3b82f6; }
	.pbutton-mirror { color: #64748b; }
	.pbutton-traversable { color: #22c55e; }
	.pbutton-goal { color: #f59e0b; }
	.pbutton-hazard { color: #f97316; }
	.pbutton-forbidden { color: #dc2626; }
	.pbutton-plant { color: #16a34a; }
	.pbutton-danger { color: #dc2626; }
	.palette-mini-label {
		writing-mode: vertical-rl;
		text-orientation: mixed;
		color: var(--text-muted);
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0;
		text-transform: uppercase;
	}
	.map-float-asset-catalog {
		position: absolute;
		left: 76px;
		top: 156px;
		z-index: 12;
		width: 250px;
		max-height: min(460px, calc(100vh - 250px));
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
	.asset-section-title {
		margin: 8px 2px 6px;
		color: var(--brand);
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.12em;
		text-transform: uppercase;
	}
	.catalog-divider {
		height: 1px;
		background: var(--panel-border);
		margin: 10px 0;
	}
	.usd-readiness {
		border: 1px solid #fed7aa;
		border-radius: 10px;
		background: #fff7ed;
		color: #9a3412;
		font-size: 11px;
		font-weight: 700;
		padding: 8px;
		margin-bottom: 8px;
	}
	.usd-readiness.ready {
		border-color: #bbf7d0;
		background: #f0fdf4;
		color: #166534;
	}
	.usd-readiness details {
		margin-top: 6px;
		font-weight: 500;
	}
	.usd-readiness pre {
		white-space: pre-wrap;
		overflow: auto;
		margin: 6px 0 0;
		color: var(--text-muted);
		font-size: 10px;
	}
	.attach-usd-box {
		display: grid;
		gap: 8px;
		border: 1px solid var(--panel-border);
		border-radius: 12px;
		background: rgba(248,250,252,0.86);
		padding: 10px;
		margin-bottom: 8px;
	}
	.attach-usd-box.muted {
		background: rgba(255,251,235,0.86);
		color: #92400e;
	}
	.attach-usd-box p {
		margin: 0;
		color: inherit;
		font-size: 12px;
	}
	.attach-usd-box label {
		display: grid;
		gap: 4px;
		font-size: 11px;
		color: var(--text-muted);
	}
	.attach-usd-box select {
		width: 100%;
		border: 1px solid var(--panel-border);
		border-radius: 8px;
		background: #fff;
		padding: 7px;
		color: var(--text);
	}
	.asset-card-list {
		display: grid;
		gap: 7px;
	}
	.asset-card {
		display: grid;
		grid-template-columns: 42px 1fr;
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
	.asset-card :global(.asset-thumb) {
		grid-row: 1 / span 2;
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
	.sensor-panel .sensor-node-id { font-family: monospace; font-size: var(--font-size-xs); color: var(--text-muted); word-break: break-all; }
	.sensor-panel .sensor-pos { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
	.sensor-panel .modality-tabs { display: flex; gap: 4px; flex-wrap: wrap; }
	.sensor-panel .modality-tabs button {
		padding: 3px 8px; font-size: 11px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm);
		background: none; cursor: pointer; color: var(--text-muted);
	}
	.sensor-panel .modality-tabs button.active-tab { background: var(--accent); color: #fff; border-color: var(--accent); }
	.sensor-panel .sensor-result { display: flex; align-items: center; gap: 6px; }
	.sensor-panel .sensor-progress { font-size: 11px; color: var(--text-muted); }
	.sensor-panel .sensor-hint { font-size: var(--font-size-xs); color: var(--text-muted); padding: 12px 0; text-align: center; }
	.sensor-panel .full { width: 100%; }

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
	.map-float-inspector .geometry-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
	.map-float-inspector button.full { width: 100%; }
	.map-float-inspector button.danger { color: #dc2626; border-color: #fca5a5; }
	.map-float-inspector button.danger:hover { background: #fef2f2; }
</style>
