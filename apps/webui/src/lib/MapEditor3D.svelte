<script lang="ts">
	import { onMount } from 'svelte';
	import * as THREE from 'three';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
	import { getOpticalNavEditorGeometry, opticalNavObservationRgbUrl, opticalNavObservationModalityUrl } from '$lib/api';
	import {
		getCachedPrimMeshPayload,
		loadCachedPrimMeshPayload,
		primMeshCacheKey,
		type PrimMeshPayload
	} from '$lib/primMeshCache';
	import {
		getCachedObjMeshGeometry,
		getObjMeshCacheStats,
		loadObjMeshGeometry,
		objMeshCacheKey,
		type ObjMeshCacheStats,
	} from '$lib/objMeshCache';

	type GhostGeom =
		| { type: 'line'; x1: number; y1: number; x2: number; y2: number; valid: boolean }
		| { type: 'rect'; minX: number; minY: number; maxX: number; maxY: number; valid: boolean }
		| { type: 'point'; x: number; y: number; valid: boolean; sourcePath?: string; assetCat?: string; normalizedYMin?: number; baseHeightM?: number; proxySize?: [number, number, number] };

	type ObjectTransformPatch = {
		center?: [number, number];
		base_height_m?: number;
		yaw_deg?: number;
	};
	type ObjectTransformReason = 'drag_start' | 'drag_move' | 'drag_end' | 'height_move' | 'yaw_move';
	type ObjectGizmoHandle = 'move_xz' | 'move_y' | 'yaw';
	type RectHandle = 'rect_x0z0' | 'rect_x1z0' | 'rect_x0z1' | 'rect_x1z1';

	type VisibleLayers = {
		objects: boolean;
		traversable: boolean;
		goals: boolean;
		hazards: boolean;
		graphNodes: boolean;
		graphEdges: boolean;
		usdBackground?: boolean;
	};
	type CameraFrustumIntrinsics = {
		fov_deg?: number;
		fov_v_deg?: number;
		resolution?: number[];
	};
	type PreviewCameraOverlay = {
		id: string;
		x: number;
		z: number;
		yaw_deg: number;
		height_m: number;
		fov_deg?: number;
		fov_v_deg?: number;
		resolution?: number[];
		label?: string;
		imageUrl?: string;
		vpId?: string;
		headingId?: string;
		active?: boolean;
	};
	type EditorMeshStats = {
		xml_native_enabled: boolean;
		authoring_objects: number;
		xml_matched: number;
		mesh_loaded: number;
		placeholder_loading: number;
		placeholder_cached_null: number;
		architecture_proxy: number;
		xml_fallback_shape: number;
		authoring_proxy_fallback: number;
		pickable: number;
		non_pickable: number;
		cache: ObjMeshCacheStats;
	};
	type XmlSceneShape = {
		shape_id: string;
		object_id?: string;
		shape_type: string;
		mesh_path?: string | null;
		preview_mesh_path?: string | null;
		preview_mesh_faces?: number;
		source_mesh_faces?: number;
		preview_mesh_status?: 'ready' | 'skipped_small' | 'architecture_proxy' | 'failed' | 'unavailable' | string;
		preview_mesh_reason?: string | null;
		editor_layer?: 'object' | 'architecture' | 'floor' | 'shell' | string;
		editor_pickable?: boolean;
		editor_proxy?: { kind?: string; bounds?: { min?: number[]; max?: number[]; size?: number[]; center?: number[] } | null; material_hint?: string | null };
		transform?: { translate?: number[]; scale?: number[]; rotate_y_deg?: number };
		xml_role?: string;
		material_id?: string;
		fallback?: boolean;
	};

	let {
		projectId = '',
		sceneId = '',
		geometryKey = '',
		authoringObjects = [],
		authoringRegions = [],
		perturbationObjects = [],
		perturbationEnabled = false,
		graphNodes = [],
		graphEdges = [],
		selectedId = '',
		visibleLayers,
		draftGhost = null,
		robotPos = null,
		editorMode = 'build',
		placementTool = 'select',
		draftPoint = null,
		highlightedPath = null,
		allEpisodePaths = [],
		mapBounds = { w: 6, h: 4 },
		customSensorNodes = [],
		preloadSourcePath = '',
		preloadUsdRef = '',
		onGroundPointerDown,
		onGroundPointerMove,
		onGroundPointerUp,
		onObjectSelect,
		onObjectContextMenu,
		onHandleDrag,
		onRegionResize,
		onStatus,
		onMeshStats,
		observationScan = null,
		onFrustumClick,
		frustumMode = 'view-aligned' as 'none' | 'view-aligned' | 'selected',
		frustumModality = 'rgb',
		frustumSensorId = '',
		frustumIntrinsics = null,
		hotCameraPlacement = false,
		previewCameraOverlay = null,
		onHotCameraDrag,
		cameraHeight = 1.0,
		wallHeight = 2.4,
		footprintInflationM = 0,
		addNodeMode = false,
		onAddNodeClick,
		showGuides = { floor: true, ceiling: true, eyeHeight: true, objectBbox: true },
		eyeHeightM = 0,
		selectedObjectGuide = null,
		paintMode = 'none' as 'none' | 'walkable' | 'blocked' | 'erase',
		paintRadiusM = 0.25,
		onPaintStroke,
		walkabilityOverlayUrl = null as string | null,
		walkabilityOverlayBbox = null as [number, number, number, number] | null,
		regionSelectMode = false,
		onRegionSelected,
		addEdgeMode = false,
		onEdgeFirstNode,
		onEdgeSecondNode,
		removeNodeMode = false,
		removeSelection = new Set<string>() as Set<string>,
		onNodeToggle,
		onNodesBoxSelect,
		roomShell = null as {
			wall_height_m: number;
			wall_thickness_m: number;
			bounds: number[];
			shapes: Array<{ role: string; center: [number, number, number]; size: [number, number, number] }>;
			floor_slabs?: Array<{ role: 'floor'; id?: string; region_id?: string | null; center: [number, number, number]; size: [number, number, number]; material_id?: string }>;
			auto_floor_enabled?: boolean;
			default_floor_material_id?: string;
			walls_enabled?: boolean;
			ceiling_enabled?: boolean;
		} | null,
		showRoomShell = true,
		// PR2: when enabled, look up each authoring object in xmlSceneIndex.shapes
		// and prefer the real mesh_cache OBJ over the proxy box. Opt-in default off.
		xmlNativePreviewEnabled = false,
		xmlSceneIndex = null as {
			scene_id?: string;
			xml_path?: string;
			xml_mtime_ns?: number;
			shapes?: Array<{
				shape_id: string;
				object_id?: string;
				shape_type: string;
				mesh_path?: string | null;
				preview_mesh_path?: string | null;
				preview_mesh_status?: string;
				editor_layer?: string;
				editor_pickable?: boolean;
				editor_proxy?: XmlSceneShape['editor_proxy'];
				preview_mesh_faces?: number;
				source_mesh_faces?: number;
				transform?: { translate?: number[]; scale?: number[]; rotate_y_deg?: number };
				xml_role?: string;
				material_id?: string;
				fallback?: boolean;
			}>;
		} | null,
		opticalNavProjectId = '',
		opticalNavSceneId = '',
		graphComponents = null as Record<string, number> | null,
		traversableOverlayUrl = null as string | null,
		traversableOverlayBbox = null as [number, number, number, number] | null,
		addEdgeGhostColor = 0x22c55e,
		addEdgeMaxLengthM = 1.5,
		objectTransformMode = true,
		surfaceSnapEnabled = true,
		gridSnapEnabled = true,
		gridSizeM = 0.05,
		angleSnapDeg = 15,
		onObjectTransform
	}: {
		projectId?: string;
		sceneId?: string;
		geometryKey?: string;
		authoringObjects: any[];
		authoringRegions: any[];
		perturbationObjects?: any[];
		perturbationEnabled?: boolean;
		graphNodes: any[];
		graphEdges: any[];
		selectedId: string;
		visibleLayers: VisibleLayers;
		draftGhost?: GhostGeom | null;
		robotPos?: { x: number; y: number } | null;
		editorMode?: string;
		placementTool?: string;
		draftPoint?: { x: number; y: number } | null;
		highlightedPath?: [number, number][] | null;
		allEpisodePaths?: { coords: [number, number][]; hasHazard: boolean }[];
		mapBounds?: { w: number; h: number };
		customSensorNodes?: { id: string; x: number; z: number; headingDeg: number; selected: boolean }[];
		preloadSourcePath?: string;
		preloadUsdRef?: string;
		onGroundPointerDown?: (pt: { x: number; y: number }, shiftKey: boolean, placement?: { base_height_m?: number; snap_label?: string }) => void;
		onGroundPointerMove?: (pt: { x: number; y: number }, shiftKey: boolean) => void;
		onGroundPointerUp?: (pt: { x: number; y: number }, shiftKey: boolean) => void;
		onObjectSelect?: (id: string) => void;
		onObjectContextMenu?: (event: MouseEvent, id: string, type: 'object' | 'region') => void;
		onHandleDrag?: (id: string, handle: 'line_start' | 'line_end', pt: { x: number; y: number }, shiftKey: boolean) => void;
		onRegionResize?: (id: string, handle: RectHandle, pt: { x: number; y: number }, shiftKey: boolean) => void;
		onStatus?: (message: string) => void;
		onMeshStats?: (stats: EditorMeshStats) => void;
		observationScan?: any;
		onFrustumClick?: (vpId: string, headingId: string) => void;
		frustumMode?: 'none' | 'view-aligned' | 'selected';
		frustumModality?: string;
		frustumSensorId?: string;
		frustumIntrinsics?: CameraFrustumIntrinsics | null;
		hotCameraPlacement?: boolean;
		previewCameraOverlay?: PreviewCameraOverlay | PreviewCameraOverlay[] | null;
		onHotCameraDrag?: (pose: { x: number; z: number; yaw_deg: number; final?: boolean }) => void;
		cameraHeight?: number;
		wallHeight?: number;
		footprintInflationM?: number;
		addNodeMode?: boolean;
		onAddNodeClick?: (x: number, z: number) => void;
		showGuides?: { floor: boolean; ceiling: boolean; eyeHeight: boolean; objectBbox: boolean };
		eyeHeightM?: number;
		selectedObjectGuide?: { center: [number, number, number]; size: [number, number, number]; label: string } | null;
		paintMode?: 'none' | 'walkable' | 'blocked' | 'erase';
		paintRadiusM?: number;
		onPaintStroke?: (points: Array<[number, number]>) => void;
		walkabilityOverlayUrl?: string | null;
		walkabilityOverlayBbox?: [number, number, number, number] | null;
		regionSelectMode?: boolean;
		onRegionSelected?: (bbox: [number, number, number, number]) => void;
		addEdgeMode?: boolean;
		onEdgeFirstNode?: (nodeId: string) => void;
		onEdgeSecondNode?: (sourceId: string, targetId: string) => void;
		removeNodeMode?: boolean;
		removeSelection?: Set<string>;
		onNodeToggle?: (nodeId: string) => void;
		onNodesBoxSelect?: (nodeIds: string[]) => void;
		roomShell?: {
			wall_height_m: number;
			wall_thickness_m: number;
			bounds: number[];
			shapes: Array<{ role: string; center: [number, number, number]; size: [number, number, number] }>;
			floor_slabs?: Array<{ role: 'floor'; id?: string; region_id?: string | null; center: [number, number, number]; size: [number, number, number]; material_id?: string }>;
			auto_floor_enabled?: boolean;
			default_floor_material_id?: string;
			walls_enabled?: boolean;
			ceiling_enabled?: boolean;
		} | null;
		showRoomShell?: boolean;
		xmlNativePreviewEnabled?: boolean;
		xmlSceneIndex?: {
			scene_id?: string;
			xml_path?: string;
			xml_mtime_ns?: number;
			shapes?: Array<{
				shape_id: string;
				object_id?: string;
				shape_type: string;
				mesh_path?: string | null;
				preview_mesh_path?: string | null;
				preview_mesh_status?: string;
				editor_layer?: string;
				editor_pickable?: boolean;
				editor_proxy?: XmlSceneShape['editor_proxy'];
				preview_mesh_faces?: number;
				source_mesh_faces?: number;
				transform?: { translate?: number[]; scale?: number[]; rotate_y_deg?: number };
				xml_role?: string;
				material_id?: string;
				fallback?: boolean;
			}>;
		} | null;
		opticalNavProjectId?: string;
		opticalNavSceneId?: string;
		graphComponents?: Record<string, number> | null;
		traversableOverlayUrl?: string | null;
		traversableOverlayBbox?: [number, number, number, number] | null;
		addEdgeGhostColor?: number;
		addEdgeMaxLengthM?: number;
		objectTransformMode?: boolean;
		surfaceSnapEnabled?: boolean;
		gridSnapEnabled?: boolean;
		gridSizeM?: number;
		angleSnapDeg?: number;
		onObjectTransform?: (id: string, patch: ObjectTransformPatch, reason: ObjectTransformReason) => void;
	} = $props();

	let host = $state<HTMLDivElement | null>(null);

	let renderer: any = null;
	let scene3D: any = null;
	let camera: any = null;
	let controls: any = null;
	let rootGroup: any = null;
	let baseGroup: any = null;
	let ghostGroup: any = null;
	let robotGroup: any = null;
	let hoverGroup: any = null;
	let frustumGroup: any = null;
	let frustumSelectables: any[] = [];
	// Per-heading group cache: `${vpId}/${headingId}/${modality}/${sensorId}` → THREE.Group
	// Kept alive across view-aligned camera rotations so textures don't flicker.
	let frustumHeadingMap = new Map<string, any>();
	const textureCache = new Map<string, any>(); // url → THREE.Texture

	// Viewport-aware frustum image lazy load: only vps within the camera's
	// view frustum AND closer than this distance get their preview image
	// fetched. Out-of-view vps still render a ray stub so the topology is
	// visible — they just don't consume connection slots. Adjustable via
	// the FRUSTUM_IMAGE_MAX_DIST env tweak below (kept short to avoid
	// loading 100s of distant vps when the user zooms out to overview).
	const FRUSTUM_IMAGE_MAX_DIST = 8.0;
	// Reusable scratch objects so the per-frame viewport check doesn't allocate.
	const _viewProjMatrix = new THREE.Matrix4();
	const _viewFrustum = new THREE.Frustum();
	const _vpPoint = new THREE.Vector3();
	function _refreshViewFrustum(): void {
		if (!camera) return;
		_viewProjMatrix.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
		_viewFrustum.setFromProjectionMatrix(_viewProjMatrix);
	}
	function _vpShouldLoadImage(nx: number, ny: number, nz: number): boolean {
		if (!camera) return true;  // fail-open if camera not ready yet
		_vpPoint.set(nx, ny, nz);
		const d = camera.position.distanceTo(_vpPoint);
		if (d > FRUSTUM_IMAGE_MAX_DIST) return false;
		return _viewFrustum.containsPoint(_vpPoint);
	}

	// Debounced rebuild on camera change — coalesces drag/zoom bursts.
	let _viewportRefreshTimer: ReturnType<typeof setTimeout> | null = null;
	function scheduleViewportFrustumRefresh(): void {
		if (_viewportRefreshTimer) clearTimeout(_viewportRefreshTimer);
		_viewportRefreshTimer = setTimeout(() => {
			_viewportRefreshTimer = null;
			if (frustumGroup) updateFrustums();
		}, 200);
	}

	// Frustum-image texture loads are concurrency-capped so the browser's
	// 6-conn/origin limit doesn't get drained by a 1000-job sweep — leaves
	// at least 2 slots for polling (health, log, events, WS upgrade).
	const FRUSTUM_TEXTURE_CONCURRENCY = 4;
	let frustumTextureActiveLoads = 0;
	const frustumTextureQueue: Array<() => void> = [];
	function acquireFrustumSlot(): Promise<void> {
		if (frustumTextureActiveLoads < FRUSTUM_TEXTURE_CONCURRENCY) {
			frustumTextureActiveLoads += 1;
			return Promise.resolve();
		}
		return new Promise<void>((resolve) => {
			frustumTextureQueue.push(() => {
				frustumTextureActiveLoads += 1;
				resolve();
			});
		});
	}
	function releaseFrustumSlot(): void {
		frustumTextureActiveLoads -= 1;
		const next = frustumTextureQueue.shift();
		if (next) next();
	}
	let hoveredObjectId = '';
	let resizeObserver: ResizeObserver | null = null;
	let lastFrameMs = 0;

	// USD prim mesh cache: stable prim key → BufferGeometry (null = load failed or no mesh)
	const primMeshCache = new Map<string, any>();
	const primMeshPending = new Set<string>();
	let primMeshCacheVersion = $state(0); // incremented on cache update to trigger re-render
	let animationFrame = 0;
	let selectableObjects: any[] = [];
	let floorTargets: any[] = [];
	let editorGeometry = $state<any>(null);
	let editorGeometryStatus = $state('fallback empty floor');
	let loadedGeometryKey = '';

	const raycaster = new THREE.Raycaster();
	const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

	let rightDragStartPos: { x: number; y: number } | null = null;
	let dragHandle: { id: string; handle: 'line_start' | 'line_end' | RectHandle } | null = null;
	let objectDrag: {
		id: string;
		handle: ObjectGizmoHandle;
		startCenter: [number, number];
		startBaseHeight: number;
		startYaw: number;
		startClientY: number;
	} | null = null;
	const movementKeys = new Set<string>();

	// ─── coordinate helpers ───────────────────────────────────────────────
	function getWorldPoint(event: PointerEvent | MouseEvent): { x: number; y: number } | null {
		if (!renderer || !camera) return null;
		const rect = renderer.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((event.clientX - rect.left) / rect.width) * 2 - 1,
			-((event.clientY - rect.top) / rect.height) * 2 + 1
		);
		raycaster.setFromCamera(ndc, camera);
		if (floorTargets.length) {
			const hits = raycaster.intersectObjects(floorTargets, true);
			if (hits.length) {
				const pt = hits[0].point;
				return clampAuthoringPoint(pt.x, pt.z);
			}
		}
		const pt = new THREE.Vector3();
		if (!raycaster.ray.intersectPlane(groundPlane, pt)) return null;
		return clampAuthoringPoint(pt.x, pt.z);
	}

	type HitPick = { id: string; type: 'object' | 'region' | 'object_gizmo'; handle?: 'line_start' | 'line_end' | ObjectGizmoHandle | RectHandle };

	// Resolve raycast hits to id-bearing picks, nearest first, deduped by id+handle.
	// Returning all overlapping picks lets the caller cycle through occluded objects
	// (e.g. an open door sitting on a wall) instead of being stuck on the topmost one.
	function getHitCandidates(event: PointerEvent | MouseEvent): HitPick[] {
		if (!renderer || !camera || !selectableObjects.length) return [];
		const rect = renderer.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((event.clientX - rect.left) / rect.width) * 2 - 1,
			-((event.clientY - rect.top) / rect.height) * 2 + 1
		);
		raycaster.setFromCamera(ndc, camera);
		const hits = raycaster.intersectObjects(selectableObjects, true);
		const picks: HitPick[] = [];
		const seen = new Set<string>();
		for (const h of hits) {
			let obj: any = h.object;
			while (obj.parent && !obj.userData.id) obj = obj.parent;
			if (!obj.userData?.id) continue;
			const id = obj.userData.id as string;
			const handle = obj.userData.handle;
			const key = `${id}::${handle ?? ''}`;
			if (seen.has(key)) continue;
			seen.add(key);
			picks.push({ id, type: (obj.userData.itemType as 'object' | 'region' | 'object_gizmo') ?? 'object', handle });
		}
		return picks;
	}

	function getHitObject(event: PointerEvent | MouseEvent): HitPick | null {
		return getHitCandidates(event)[0] ?? null;
	}

	// Cycle-select state: repeated clicks at ~the same screen point step through the
	// stack of overlapping objects so occluded items become reachable.
	let lastPickNdc: { x: number; y: number } | null = null;
	let pickCycleIndex = 0;

	function getClickPick(event: PointerEvent | MouseEvent): HitPick | null {
		const candidates = getHitCandidates(event);
		if (!candidates.length) { lastPickNdc = null; pickCycleIndex = 0; return null; }
		// A handle under the cursor always wins (drag interaction), no cycling.
		if (candidates[0].handle) { lastPickNdc = null; pickCycleIndex = 0; return candidates[0]; }
		const rect = renderer?.domElement?.getBoundingClientRect();
		const here = rect ? { x: event.clientX - rect.left, y: event.clientY - rect.top } : { x: event.clientX, y: event.clientY };
		const sameSpot = lastPickNdc && Math.hypot(here.x - lastPickNdc.x, here.y - lastPickNdc.y) <= 6;
		// Only body picks (no handle) participate in the cycle.
		const bodies = candidates.filter((c) => !c.handle);
		if (!bodies.length) { lastPickNdc = here; pickCycleIndex = 0; return candidates[0]; }
		pickCycleIndex = sameSpot ? (pickCycleIndex + 1) % bodies.length : 0;
		lastPickNdc = here;
		if (bodies.length > 1) {
			onStatus?.(`${bodies.length} overlapping — click again to cycle (${pickCycleIndex + 1}/${bodies.length})`);
		}
		return bodies[pickCycleIndex];
	}

	function pointObjectById(id: string): any | null {
		return authoringObjects.find((obj: any) => obj?.id === id && obj?.geometry?.type === 'point') ?? null;
	}

	function isRenderOnlyLightProxy(obj: any): boolean {
		const id = String(obj?.id ?? '');
		const kind = String(obj?.metadata?.kind ?? '');
		const emitterShape = String(obj?.emitter_shape ?? '');
		return kind === 'room_softbox'
			|| id.startsWith('light_softbox_')
			|| (emitterShape === 'ceiling_panel' && !obj?.source_ref);
	}

	function snapScalar(value: number, step: number): number {
		if (!Number.isFinite(step) || step <= 0) return value;
		return Number((Math.round(value / step) * step).toFixed(3));
	}

	function movementSnapStep(event: PointerEvent | MouseEvent): number {
		if (!gridSnapEnabled || event.altKey) return 0;
		const base = Math.max(0.001, Number(gridSizeM) || 0.05);
		return event.shiftKey ? base / 5 : base;
	}

	function angleSnapStep(event: PointerEvent | MouseEvent): number {
		if (!gridSnapEnabled || event.altKey) return 0;
		const base = Math.max(1, Number(angleSnapDeg) || 15);
		return event.shiftKey ? Math.max(1, base / 3) : base;
	}

	function objectProxySize(obj: any): [number, number, number] {
		const geomSize = obj?.geometry?.size_m;
		const proxy = obj?.metadata?.proxy_size;
		const raw = Array.isArray(geomSize) && geomSize.length >= 3 ? geomSize
			: Array.isArray(proxy) && proxy.length >= 3 ? proxy
			: obj?.type === 'table' ? [0.76, 0.58, 0.50]
			: obj?.type === 'chair' ? [0.46, 0.90, 0.42]
			: obj?.type === 'plant' ? [0.44, 0.90, 0.44]
			: obj?.type === 'camera' ? [0.14, 0.12, 0.18]
			: [0.50, 0.50, 0.50];
		return [
			Math.max(0.04, Number(raw[0]) || 0.5),
			Math.max(0.04, Number(raw[1]) || 0.5),
			Math.max(0.04, Number(raw[2]) || 0.5)
		];
	}

	function objectBaseHeight(obj: any): number {
		return Math.max(0, Number(obj?.geometry?.base_height_m ?? 0) || 0);
	}

	function objectSurfaceTargets(excludeId = '') {
		const targets: Array<{ id: string; label: string; height: number; minX: number; maxX: number; minZ: number; maxZ: number }> = [{
			id: '__floor__',
			label: 'Floor',
			height: 0,
			minX: -Infinity,
			maxX: Infinity,
			minZ: -Infinity,
			maxZ: Infinity
		}];
		for (const obj of authoringObjects) {
			if (!obj || obj.id === excludeId || obj.geometry?.type !== 'point') continue;
			if (isRenderOnlyLightProxy(obj)) continue;
			const center = obj.geometry?.center;
			if (!Array.isArray(center) || center.length < 2) continue;
			const [sx, sy, sz] = objectProxySize(obj);
			const top = objectBaseHeight(obj) + sy;
			if (!Number.isFinite(top) || top <= 0.03) continue;
			targets.push({
				id: String(obj.id),
				label: String(obj.label || obj.id),
				height: Number(top.toFixed(3)),
				minX: Number(center[0]) - sx / 2,
				maxX: Number(center[0]) + sx / 2,
				minZ: Number(center[1]) - sz / 2,
				maxZ: Number(center[1]) + sz / 2
			});
		}
		return targets;
	}

	function surfaceSnapForPoint(pt: { x: number; y: number }, excludeId = '', fallbackHeight = 0): { base_height_m: number; snap_label: string } {
		if (!surfaceSnapEnabled) {
			return { base_height_m: Math.max(0, fallbackHeight), snap_label: 'Free Height' };
		}
		let best = objectSurfaceTargets(excludeId)[0];
		for (const target of objectSurfaceTargets(excludeId)) {
			if (pt.x < target.minX || pt.x > target.maxX || pt.y < target.minZ || pt.y > target.maxZ) continue;
			if (!best || target.height >= best.height) best = target;
		}
		const height = Number(Math.max(0, best?.height ?? 0).toFixed(3));
		return { base_height_m: height, snap_label: best?.id === '__floor__' ? 'Floor' : `On ${best.label}` };
	}

	function snapPointXZ(pt: { x: number; y: number }, event: PointerEvent | MouseEvent): { x: number; y: number } {
		const step = movementSnapStep(event);
		if (!step) return pt;
		return clampAuthoringPoint(snapScalar(pt.x, step), snapScalar(pt.y, step));
	}

	// ─── colour helpers ───────────────────────────────────────────────────
	function regionColor(type: string): number {
		const m: Record<string, number> = {
			traversable: 0x22c55e, goal: 0xfbbf24, hazard: 0xf97316,
			start: 0x3b82f6, forbidden: 0xdc2626, stop_before: 0xa855f7
		};
		return m[type] ?? 0xaaaaaa;
	}

	function regionOpacity(type: string): number {
		const m: Record<string, number> = {
			traversable: 0.18, goal: 0.38, hazard: 0.38, start: 0.25, forbidden: 0.38, stop_before: 0.32
		};
		return m[type] ?? 0.25;
	}

	function pointColor(type: string): number {
		const m: Record<string, number> = { chair: 0x94a3b8, table: 0x92400e, plant: 0x166534, landmark: 0x64748b, camera: 0xf59e0b };
		return m[type] ?? 0x888888;
	}

	// Phase 1: per-region floor hint colours. Used by render-floor-slab preview meshes
	// so the editor signals which traversable region got which material without running
	// the real Mitsuba BSDF.
	function floorMaterialColor(materialId: string | null | undefined): number {
		const id = String(materialId ?? '').toLowerCase();
		if (id.includes('wood')) return 0x8b5a2b;
		if (id.includes('tile') || id.includes('ceramic')) return 0xcbd5e1;
		if (id.includes('fabric') || id.includes('carpet')) return 0xd97706;
		if (id.includes('glass')) return 0x93c5fd;
		if (id.includes('mirror') || id.includes('metal')) return 0x94a3b8;
		if (id.includes('concrete')) return 0x9ca3af;
		return 0xb8a98a;
	}

	function usdProxyColor(category: string): number {
		const m: Record<string, number> = {
			floor: 0xe2e8f0,
			shell: 0x94a3b8,
			glass: 0x67e8f9,
			mirror: 0x64748b,
			furniture: 0xa16207,
			object: 0x94a3b8
		};
		return m[category] ?? 0x94a3b8;
	}

	function boundsCenter(bounds: any): [number, number, number] {
		if (bounds?.center?.length >= 3) return bounds.center;
		const mn = bounds?.min ?? [0, 0, 0];
		const mx = bounds?.max ?? [0, 0, 0];
		return [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2];
	}

	function boundsSize(bounds: any): [number, number, number] {
		if (bounds?.size?.length >= 3) return bounds.size;
		const mn = bounds?.min ?? [0, 0, 0];
		const mx = bounds?.max ?? [0.001, 0.001, 0.001];
		return [Math.max(0.001, mx[0] - mn[0]), Math.max(0.001, mx[1] - mn[1]), Math.max(0.001, mx[2] - mn[2])];
	}

	// Bounding box of all authored content (object centres ±size, region bounds).
	// Used so editing/preview placement can reach the real content even when it sits
	// at negative coords far from the origin (e.g. imported Infinigen rooms at y≈-14).
	function contentExtent(): { minX: number; minZ: number; maxX: number; maxZ: number } | null {
		let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
		const grow = (x: number, z: number) => {
			minX = Math.min(minX, x); minZ = Math.min(minZ, z);
			maxX = Math.max(maxX, x); maxZ = Math.max(maxZ, z);
		};
		for (const obj of authoringObjects) {
			if (isRenderOnlyLightProxy(obj)) continue;
			const g = obj?.geometry;
			const c = g?.center;
			if (Array.isArray(c) && c.length >= 2) {
				const s = Array.isArray(g?.size_m) ? g.size_m : [0.5, 0, 0.5];
				const hx = Math.max(0.25, Number(s[0] ?? 0.5) / 2), hz = Math.max(0.25, Number(s[2] ?? s[1] ?? 0.5) / 2);
				grow(Number(c[0]) - hx, Number(c[1]) - hz); grow(Number(c[0]) + hx, Number(c[1]) + hz);
			} else if (Array.isArray(g?.start) && Array.isArray(g?.end)) {
				grow(Number(g.start[0]), Number(g.start[1])); grow(Number(g.end[0]), Number(g.end[1]));
			}
		}
		for (const reg of authoringRegions) {
			const b = reg?.geometry?.bounds;
			if (Array.isArray(b) && b.length >= 4) { grow(Number(b[0]), Number(b[1])); grow(Number(b[2]), Number(b[3])); }
		}
		return Number.isFinite(minX) ? { minX, minZ, maxX, maxZ } : null;
	}

	function clampAuthoringPoint(x: number, z: number): { x: number; y: number } {
		const bounds = editorGeometry?.bounds;
		const mn = bounds?.min ?? [0, 0, 0];
		const mx = bounds?.max ?? [mapBounds?.w ?? 6, 0, mapBounds?.h ?? 4];
		// Editable range = union of (editor/USD bounds), (mapBounds) and the actual
		// authored content extent, all padded by one map-side. This lets placement &
		// "Preview from here" reach content in negative space (backend supports signed
		// coords) without pinning to the origin or a small default map size.
		const pad = Math.max(mapBounds?.w ?? 6, mapBounds?.h ?? 4, 1);
		const ext = contentExtent();
		const loX = Math.min(Number(mn[0] ?? 0), ext?.minX ?? 0, 0) - pad;
		const hiX = Math.max(Number(mx[0] ?? 6), ext?.maxX ?? 0, 0) + pad;
		const loZ = Math.min(Number(mn[2] ?? 0), ext?.minZ ?? 0, 0) - pad;
		const hiZ = Math.max(Number(mx[2] ?? 4), ext?.maxZ ?? 0, 0) + pad;
		return {
			x: Math.max(loX, Math.min(hiX, Number(x.toFixed(3)))),
			y: Math.max(loZ, Math.min(hiZ, Number(z.toFixed(3))))
		};
	}

	function isGlbRef(value: unknown): boolean {
		return typeof value === 'string' && /\.(glb|gltf)$/i.test(value.split('?')[0]);
	}

	function usdRefFromSourceRef(sourceRef: unknown): string {
		if (isGlbRef(sourceRef)) return '';
		return typeof sourceRef === 'string' ? sourceRef.split('#')[0] : '';
	}

	// Derive the prim path from a ``source_ref`` like ``assets/foo.usda#/ROOT/...``
	// when ``metadata.asset_source_path`` is missing. Historical authoring_maps
	// (e.g. moorelane_kitchen_001) only carry the combined source_ref, so the
	// editor would otherwise fall straight to fallback boxes even though the
	// USD prim is reachable through the same API.
	function primPathFromSourceRef(sourceRef: unknown): string {
		if (typeof sourceRef !== 'string') return '';
		const hashIdx = sourceRef.indexOf('#');
		return hashIdx >= 0 ? sourceRef.slice(hashIdx + 1) : '';
	}

	function effectiveAssetSourcePath(obj: any): string | undefined {
		const sourceRef = typeof obj?.source_ref === 'string' ? obj.source_ref : '';
		const format = String(obj?.metadata?.asset_source_format ?? '').toLowerCase();
		if (format === 'glb' || isGlbRef(sourceRef) || isGlbRef(obj?.metadata?.asset_glb_ref)) {
			const glbRef = obj?.metadata?.asset_glb_ref ?? obj?.metadata?.asset_source_ref ?? sourceRef;
			return typeof glbRef === 'string' && glbRef ? glbRef : undefined;
		}
		const stored = obj?.metadata?.asset_source_path;
		if (typeof stored === 'string' && stored) return stored;
		const derived = primPathFromSourceRef(sourceRef);
		return derived || undefined;
	}

	function primMeshKey(sourcePath: string, usdRef = ''): string {
		return primMeshCacheKey(projectId, sceneId, sourcePath, usdRef);
	}

	function geometryFromPrimPayload(payload: PrimMeshPayload | null): any | null {
		if (!payload?.vertices || !payload?.indices || payload.vertices.length === 0 || payload.indices.length === 0) return null;
		const geo = new THREE.BufferGeometry();
		geo.setAttribute('position', new THREE.Float32BufferAttribute(payload.vertices, 3));
		geo.setIndex(new THREE.Uint32BufferAttribute(payload.indices, 1));
		geo.computeVertexNormals();
		return geo;
	}

	function isRegionVisible(type: string): boolean {
		if (type === 'goal' || type === 'start' || type === 'stop_before') return visibleLayers.goals;
		if (type === 'traversable') return visibleLayers.traversable;
		return visibleLayers.hazards;
	}

	function isTextInputTarget(target: EventTarget | null): boolean {
		if (!(target instanceof HTMLElement)) return false;
		const tag = target.tagName.toLowerCase();
		return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable;
	}

	function setMovementKey(event: KeyboardEvent, pressed: boolean) {
		if (isTextInputTarget(event.target)) return;
		const key = event.key.toLowerCase();
		if (!['w', 'a', 's', 'd'].includes(key)) return;
		event.preventDefault();
		if (pressed) movementKeys.add(key);
		else movementKeys.delete(key);
	}

	function clearMovementKeys() {
		movementKeys.clear();
	}

	function updateKeyboardCamera(dt: number) {
		if (!camera || !controls || !movementKeys.size || dragHandle) return;
		const forward = new THREE.Vector3();
		camera.getWorldDirection(forward);
		forward.y = 0;
		if (forward.lengthSq() < 1e-6) {
			forward.copy(camera.up);
			forward.y = 0;
		}
		if (forward.lengthSq() < 1e-6) forward.set(0, 0, 1);
		forward.normalize();

		const right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).normalize();
		const delta = new THREE.Vector3();
		if (movementKeys.has('w')) delta.add(forward);
		if (movementKeys.has('s')) delta.sub(forward);
		if (movementKeys.has('d')) delta.add(right);
		if (movementKeys.has('a')) delta.sub(right);
		if (delta.lengthSq() < 1e-6) return;

		const distance = Math.max(1, camera.position.distanceTo(controls.target));
		const speed = Math.min(14, Math.max(2.5, distance * 0.85));
		delta.normalize().multiplyScalar(speed * dt);
		camera.position.add(delta);
		controls.target.add(delta);
		controls.update();
	}

	// ─── object builders ──────────────────────────────────────────────────
	function buildRegion(region: any): any | null {
		const b = region.geometry?.bounds;
		if (!b) return null;
		const [minX, minY, maxX, maxY] = b;
		const w = maxX - minX;
		const d = maxY - minY;
		if (w < 0.01 || d < 0.01) return null;
		const geo = new THREE.PlaneGeometry(w, d);
		const mat = new THREE.MeshBasicMaterial({
			color: regionColor(region.type),
			transparent: true,
			opacity: regionOpacity(region.type),
			side: THREE.DoubleSide,
			depthWrite: false
		});
		const mesh = new THREE.Mesh(geo, mat);
		mesh.rotation.x = -Math.PI / 2;
		mesh.position.set(minX + w / 2, 0.001, minY + d / 2);
		mesh.userData = { id: region.id, itemType: 'region' };
		return mesh;
	}

	function buildWall(obj: any): any | null {
		const g = obj.geometry;
		if (g?.type !== 'line') return null;
		const [sx, sz] = g.start ?? [0, 0];
		const [ex, ez] = g.end ?? [0, 0];
		const height = g.height_m ?? 2.4;
		const thickness = g.thickness_m ?? 0.08;
		const dx = ex - sx;
		const dz = ez - sz;
		const length = Math.hypot(dx, dz);
		if (length < 0.01) return null;
		const angle = Math.atan2(dx, dz);
		let mat: any;
		if (obj.type === 'glass_wall') {
			mat = new THREE.MeshPhysicalMaterial({
				color: 0x88bbff, transparent: true, opacity: 0.35,
				roughness: 0.05, metalness: 0, side: THREE.DoubleSide
			});
		} else if (obj.type === 'wall') {
			mat = new THREE.MeshStandardMaterial({
				color: 0x94a3b8, roughness: 0.85, metalness: 0
			});
		} else {
			mat = new THREE.MeshStandardMaterial({
				color: 0xd4d4d8, roughness: 0.05, metalness: 0.9
			});
		}
		const geo = new THREE.BoxGeometry(thickness, height, length);
		const mesh = new THREE.Mesh(geo, mat);
		mesh.position.set((sx + ex) / 2, height / 2, (sz + ez) / 2);
		mesh.rotation.y = angle;
		mesh.userData = { id: obj.id, itemType: 'object' };
		return mesh;
	}

	function addProxyBox(group: any, size: [number, number, number], pos: [number, number, number], color: number, materialOptions: Record<string, any> = {}) {
		const geo = new THREE.BoxGeometry(size[0], size[1], size[2]);
		const { physical, ...restOpts } = materialOptions;
		const material = physical
			? new THREE.MeshPhysicalMaterial({ color, transparent: true, opacity: 0.35, roughness: 0.04 })
			: new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0, ...restOpts });
		const mesh = new THREE.Mesh(geo, material);
		mesh.position.set(pos[0], pos[1], pos[2]);
		group.add(mesh);
		return mesh;
	}

	function buildBuiltInPointShape(obj: any, group: any) {
		const color = pointColor(obj.type);
		if (obj.type === 'chair') {
			addProxyBox(group, [0.46, 0.12, 0.42], [0, 0.32, 0], color);
			addProxyBox(group, [0.46, 0.58, 0.10], [0, 0.60, -0.20], color);
			for (const x of [-0.17, 0.17]) for (const z of [-0.14, 0.14]) addProxyBox(group, [0.07, 0.32, 0.07], [x, 0.16, z], color);
			return;
		}
		if (obj.type === 'table') {
			addProxyBox(group, [0.76, 0.12, 0.50], [0, 0.52, 0], color);
			for (const x of [-0.29, 0.29]) for (const z of [-0.18, 0.18]) addProxyBox(group, [0.07, 0.50, 0.07], [x, 0.25, z], color);
			return;
		}
		if (obj.type === 'plant') {
			addProxyBox(group, [0.28, 0.34, 0.28], [0, 0.17, 0], 0x64748b);
			addProxyBox(group, [0.12, 0.34, 0.12], [0, 0.48, 0], 0x166534);
			addProxyBox(group, [0.44, 0.34, 0.44], [0, 0.72, 0], 0x15803d);
		}
	}

	// PR2: map of object_id (or shape_id when unmaterialized) → XML shape record.
	// Built once per rebuildScene() so the authoring object loop can do O(1) lookups.
	let _xmlShapeIndex = new Map<string, XmlSceneShape>();
	const _objMeshLoadPending = new Set<string>();
	function rebuildXmlShapeIndex(): void {
		_xmlShapeIndex = new Map();
		const shapes = xmlSceneIndex?.shapes ?? [];
		for (const sh of shapes) {
			// xml_role-tagged shapes (floor / shell_*) are drawn by other code paths;
			// only authoring object shapes go into this lookup.
			if (sh.xml_role && (sh.xml_role === 'floor' || sh.xml_role.startsWith('shell'))) continue;
			const key = sh.object_id || sh.shape_id;
			if (key) _xmlShapeIndex.set(key, sh as XmlSceneShape);
		}
	}


	function buildArchitectureProxyFromXmlShape(sh: XmlSceneShape, colorHint: number): any {
		const proxy = sh.editor_proxy ?? {};
		const kind = String(proxy.kind ?? sh.editor_layer ?? 'architecture').toLowerCase();
		const bounds = proxy.bounds ?? null;
		const sizeRaw = Array.isArray(bounds?.size) && bounds!.size!.length >= 3 ? bounds!.size! : null;
		const centerRaw = Array.isArray(bounds?.center) && bounds!.center!.length >= 3 ? bounds!.center! : null;
		let sx = Math.max(0.02, Number(sizeRaw?.[0] ?? 0.8));
		let sy = Math.max(0.02, Number(sizeRaw?.[1] ?? 0.08));
		let sz = Math.max(0.02, Number(sizeRaw?.[2] ?? 0.8));
		if (kind === 'floor' || kind === 'ground' || kind === 'slab') sy = Math.min(Math.max(sy, 0.015), 0.05);
		const color = kind.includes('glass') ? 0x67e8f9
			: kind.includes('floor') || kind.includes('ground') || kind.includes('slab') ? floorMaterialColor(proxy.material_hint ?? sh.material_id)
			: kind.includes('ceiling') || kind.includes('roof') ? 0xcbd5e1
			: colorHint || 0x94a3b8;
		const opacity = kind.includes('floor') || kind.includes('ground') || kind.includes('slab') ? 0.34
			: kind.includes('glass') ? 0.22
			: 0.18;
		const group = new THREE.Group();
		const geo = new THREE.BoxGeometry(sx, sy, sz);
		const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false });
		const mesh = new THREE.Mesh(geo, mat);
		const cx = Number(centerRaw?.[0] ?? 0);
		const cy = Number(centerRaw?.[1] ?? sy / 2);
		const cz = Number(centerRaw?.[2] ?? 0);
		mesh.position.set(cx, cy, cz);
		mesh.userData = {
			id: sh.object_id ?? sh.shape_id,
			itemType: 'architecture',
			editor_pickable: false,
			xml_shape_id: sh.shape_id,
			xml_role: sh.xml_role ?? null,
			architecture_kind: kind,
		};
		group.add(mesh);
		const edges = new THREE.LineSegments(
			new THREE.EdgesGeometry(geo),
			new THREE.LineBasicMaterial({ color, transparent: true, opacity: Math.min(0.65, opacity + 0.22) })
		);
		edges.position.copy(mesh.position);
		edges.userData = { ...mesh.userData, itemType: 'architecture_edges' };
		group.add(edges);
		if (kind.includes('floor') || kind.includes('ground') || kind.includes('slab')) floorTargets.push(mesh);
		group.userData = { ...mesh.userData, editor_preview_state: 'architecture_proxy' };
		return group;
	}

	// PR2: when the toggle is on, build the editor mesh from xml_scene_index.shapes
	// directly. Returns null when no XML shape matches (caller falls back to the
	// existing buildPointObject / buildWall path). When the underlying OBJ is not
	// yet loaded into objMeshCache, we render a placeholder cube sized from the
	// XML scale and kick off a background fetch — the next rebuildScene() picks up
	// the resolved geometry from cache automatically.
	function buildObjectFromXmlShape(obj: any): any | null {
		if (!xmlNativePreviewEnabled) return null;
		if (isRenderOnlyLightProxy(obj)) return null;
		const sh = _xmlShapeIndex.get(obj.id);
		if (!sh) return null;
		const t = sh.transform ?? {};
		const sc = Array.isArray(t.scale) ? t.scale : [1, 1, 1];
		// Position / rotation comes from the LIVE authoring object, not the
		// xml_scene_index transform — the index reflects sync-time placement and
		// drifts the moment the user drags or rotates the object in the editor.
		// xml index is consulted only for mesh_path / shape_type / material.
		const center = obj.geometry?.center;
		if (!Array.isArray(center) || center.length < 2) return null;
		const baseHeight = objectBaseHeight(obj);
		const yaw = (obj.geometry?.yaw_deg ?? 0) as number;
		const group = new THREE.Group();
		group.position.set(Number(center[0]) || 0, baseHeight, Number(center[1]) || 0);
		if (Math.abs(yaw) > 1e-5) group.rotation.y = (yaw * Math.PI) / 180;

		const colorHint = sh.material_id ? floorMaterialColor(sh.material_id) : 0xb8b3a8;
		const meshPath = sh.preview_mesh_path || sh.mesh_path;
		if ((sh.editor_layer === 'architecture' || sh.preview_mesh_status === 'architecture_proxy') && !meshPath) {
			const arch = buildArchitectureProxyFromXmlShape(sh, colorHint);
			arch.position.copy(group.position);
			arch.rotation.copy(group.rotation);
			return arch;
		}
		const isMesh = sh.shape_type === 'obj' && !!meshPath;
		let mesh: any;
		let editorPreviewState = 'xml_unknown';
		if (isMesh) {
			const filename = (meshPath as string).split('/').pop() || meshPath as string;
			const key = objMeshCacheKey(opticalNavProjectId, opticalNavSceneId, filename);
			const cached = getCachedObjMeshGeometry(key);
			if (cached) {
				editorPreviewState = 'mesh_cached';
				const isArchitecture = sh.editor_layer === 'architecture';
				const mat = new THREE.MeshStandardMaterial({
					color: colorHint,
					roughness: 0.85,
					metalness: 0,
					transparent: isArchitecture,
					opacity: isArchitecture ? 0.42 : 1,
					depthWrite: !isArchitecture,
				});
				mesh = new THREE.Mesh(cached, mat);
			} else {
				editorPreviewState = cached === null ? 'placeholder_cached_null' : 'placeholder_loading';
				// Placeholder cube; kick off the async fetch + bump primMeshCacheVersion-style
				// retrigger by setting _xmlNativePreviewVersion so rebuildScene re-runs.
				const authoredSize = Array.isArray(obj?.geometry?.size_m) ? obj.geometry.size_m : null;
				const phSize = authoredSize && authoredSize.length >= 3
					? [
						Math.max(0.02, Number(authoredSize[0]) || 0.25),
						Math.max(0.02, Number(authoredSize[1]) || 0.25),
						Math.max(0.02, Number(authoredSize[2]) || 0.25),
					]
					: [
						Math.max(0.05, (Number(sc[0]) || 0.18) * 2),
						Math.max(0.05, (Number(sc[1]) || 0.18) * 2),
						Math.max(0.05, (Number(sc[2]) || 0.18) * 2),
					];
				const ph = new THREE.BoxGeometry(
					phSize[0],
					phSize[1],
					phSize[2],
				);
				const mat = new THREE.MeshStandardMaterial({
					color: colorHint, roughness: 1, metalness: 0,
					transparent: true, opacity: 0.55,
				});
				mesh = new THREE.Mesh(ph, mat);
				// Schedule an async load; on completion, bump the version state so the
				// reactive $effect fires rebuildScene() again to swap in the real mesh.
				if (opticalNavProjectId && opticalNavSceneId && cached === undefined && !_objMeshLoadPending.has(key)) {
					_objMeshLoadPending.add(key);
					void loadObjMeshGeometry(opticalNavProjectId, opticalNavSceneId, filename)
						.then((geo) => { if (geo) scheduleXmlNativePreviewRefresh(); })
						.finally(() => { _objMeshLoadPending.delete(key); });
				}
			}
		} else {
			editorPreviewState = sh.fallback ? 'xml_fallback_shape' : 'xml_primitive_shape';
			// shape_type cube/sphere/etc. — size from XML scale (BoxGeometry takes full extent).
			const sx = Math.max(0.01, (Number(sc[0]) || 0.5) * 2);
			const sy = Math.max(0.01, (Number(sc[1]) || 0.5) * 2);
			const sz = Math.max(0.01, (Number(sc[2]) || 0.5) * 2);
			const geo = new THREE.BoxGeometry(sx, sy, sz);
			const mat = new THREE.MeshStandardMaterial({
				color: colorHint, roughness: 1, metalness: 0,
				transparent: true, opacity: sh.fallback ? 0.55 : 0.85,
			});
			mesh = new THREE.Mesh(geo, mat);
		}
		// Bottom-align the mesh to the group origin (which sits at base_height_m),
		// matching the renderer (object bottom at base_height_m); otherwise a
		// centred box is half-buried below the floor.
		if (mesh?.geometry) {
			mesh.geometry.computeBoundingBox?.();
			const _bb = mesh.geometry.boundingBox;
			if (_bb) mesh.position.y = -_bb.min.y;
		}
		const isArchitectureMesh = sh.editor_layer === 'architecture';
		mesh.userData = {
			id: sh.object_id ?? sh.shape_id,
			itemType: isArchitectureMesh ? 'architecture' : 'object',
			editor_pickable: sh.editor_pickable !== false,
			xml_shape_id: sh.shape_id,
			xml_role: sh.xml_role ?? null,
			architecture_kind: sh.editor_proxy?.kind ?? null,
			editor_preview_state: editorPreviewState,
			editor_mesh_path: meshPath ?? null,
		};
		if (isArchitectureMesh && String(sh.editor_proxy?.kind ?? '').toLowerCase().includes('floor')) floorTargets.push(mesh);
		group.add(mesh);
		group.userData = { ...mesh.userData };
		return group;
	}

	// Bumped whenever an async OBJ load resolves so rebuildScene() re-runs and the
	// placeholder cube swaps to the real mesh. Must be reactive ($state) — a plain
	// `let` won't trigger the $effect that watches it, so placeholders would stay
	// forever and every object would look like a fallback box.
	let _xmlNativePreviewVersion = $state(0);
	let _xmlNativePreviewRefreshTimer: ReturnType<typeof setTimeout> | null = null;
	function scheduleXmlNativePreviewRefresh() {
		if (_xmlNativePreviewRefreshTimer !== null) return;
		_xmlNativePreviewRefreshTimer = setTimeout(() => {
			_xmlNativePreviewRefreshTimer = null;
			_xmlNativePreviewVersion++;
		}, 120);
	}

	function buildPointObject(obj: any): any | null {
		const center = obj.geometry?.center;
		if (!center) return null;
		const [x, z] = center;
		const proxy = obj.metadata?.proxy_size;
		const baseHeight = objectBaseHeight(obj);
		const group = new THREE.Group();
		group.position.set(x, 0, z);
		group.rotation.y = ((obj.geometry?.yaw_deg ?? 0) * Math.PI) / 180;
		group.userData = { id: obj.id, itemType: 'object' };
		if (obj.type === 'camera') {
			// Pyramid/cone facing +Z (forward direction)
			const body = new THREE.Mesh(
				new THREE.BoxGeometry(0.08, 0.06, 0.1),
				new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.6 })
			);
			body.position.set(0, baseHeight + 0.07, 0);
			group.add(body);
			const cone = new THREE.Mesh(
				new THREE.ConeGeometry(0.04, 0.12, 4),
				new THREE.MeshStandardMaterial({ color: 0xf59e0b, roughness: 0.4 })
			);
			cone.rotation.x = -Math.PI / 2;
			cone.position.set(0, baseHeight + 0.07, 0.1);
			group.add(cone);
			return group;
		}
		// Preview source priority for points (XML-native toggle is handled one level
		// up in rebuildScene). For toggle-off path:
		//   1) USD prim mesh from primMeshCache → real geometry (covers most USD-import
		//      objects including chair / table / plant when they have a source_ref)
		//   2) buildBuiltInPointShape primitives → only for the no-asset case
		//   3) Generic proxy box → unknown type with no mesh
		// Historical order put step 2 first for hardcoded types, masking real USD
		// prim meshes for moorelane chairs/tables. Now the built-in shape only fires
		// when no USD prim mesh is reachable.
		const _sourcePath: string | undefined = effectiveAssetSourcePath(obj);
		const _usdRef = usdRefFromSourceRef(obj.source_ref);
		const _cachedGeoPeek = _sourcePath ? primMeshCache.get(primMeshKey(_sourcePath, _usdRef)) : undefined;
		const _hasUsdMeshOrIsLoadable = !!_cachedGeoPeek || !!_sourcePath;
		if (isRenderOnlyLightProxy(obj)) return null;
		if (!Array.isArray(proxy) && ['chair', 'table', 'plant'].includes(obj.type) && !_hasUsdMeshOrIsLoadable) {
			const shapeGroup = new THREE.Group();
			shapeGroup.position.y = baseHeight;
			group.add(shapeGroup);
			buildBuiltInPointShape(obj, shapeGroup);
		} else {
				const sourcePath: string | undefined = _sourcePath;
				const usdRef = _usdRef;
				const cachedGeo = _cachedGeoPeek;
			if (cachedGeo) {
				// Render actual USD mesh geometry
				const usdCat = obj.metadata?.asset_category ?? 'object';
				const color = usdProxyColor(usdCat);
				const mat = new THREE.MeshStandardMaterial({
					color,
					roughness: usdCat === 'mirror' ? 0.12 : usdCat === 'glass' ? 0.04 : 0.65,
					metalness: usdCat === 'mirror' ? 0.8 : 0,
					transparent: usdCat === 'glass',
					opacity: usdCat === 'glass' ? 0.55 : 1.0,
				});
				const mesh = new THREE.Mesh(cachedGeo, mat);
				// Place mesh at correct world height using normalized_y_min from USD metadata.
				// normalized_y_min is the object's bottom height above its room floor (meters).
				// box.min.y is the prim-local mesh bottom (may be non-zero if prim origin ≠ bottom).
				const worldY: number = baseHeight + Number(obj.metadata?.normalized_y_min ?? 0);
				const box = new THREE.Box3().setFromBufferAttribute(cachedGeo.attributes.position as any);
				mesh.position.y = worldY - box.min.y;
				group.add(mesh);
			} else {
				// Fallback proxy box (shown while mesh loads or if prim has no geometry)
				const sx = Array.isArray(proxy) ? Math.max(0.16, Math.min(1.2, Number(proxy[0] ?? 0.35))) : 0.35;
				const h = Array.isArray(proxy) ? Math.max(0.18, Math.min(1.8, Number(proxy[1] ?? 0.5))) : 0.5;
				const sz = Array.isArray(proxy) ? Math.max(0.16, Math.min(1.2, Number(proxy[2] ?? 0.35))) : 0.35;
				const usdCat = obj.metadata?.asset_category;
				const color = usdCat ? usdProxyColor(usdCat) : pointColor(obj.type);
				const worldY: number = baseHeight + Number(obj.metadata?.normalized_y_min ?? 0);
				addProxyBox(group, [sx, h, sz], [0, worldY + h / 2, 0], color);
			}
		}
		return group;
	}

	function addEmitterOverlayForObject(obj: any): void {
		if (!rootGroup || !obj?.is_emitter || obj.geometry?.type !== 'point') return;
		const center = obj.geometry?.center;
		if (!Array.isArray(center) || center.length < 2) return;
		const baseHeight = objectBaseHeight(obj);
		const normalizedYMin = Number(obj.metadata?.normalized_y_min ?? 0);
		const authoredHeight = Number(obj.geometry?.base_height_m ?? baseHeight);
		const objectHeight = objectProxySize(obj)[1];
		const haloY = Math.max(baseHeight + normalizedYMin + 0.12, authoredHeight + objectHeight + 0.08);
		const group = new THREE.Group();
		group.position.set(Number(center[0]) || 0, haloY, Number(center[1]) || 0);
		group.userData = { id: obj.id, itemType: 'emitter_halo' };

		const glow = new THREE.Mesh(
			new THREE.SphereGeometry(0.2, 18, 12),
			new THREE.MeshBasicMaterial({
				color: 0xfde047,
				transparent: true,
				opacity: 0.42,
				depthTest: false,
				depthWrite: false,
			})
		);
		glow.renderOrder = 80;
		glow.userData = { id: obj.id, itemType: 'emitter_halo' };
		group.add(glow);

		const ring = new THREE.Mesh(
			new THREE.RingGeometry(0.24, 0.31, 32),
			new THREE.MeshBasicMaterial({
				color: 0xf59e0b,
				transparent: true,
				opacity: 0.95,
				side: THREE.DoubleSide,
				depthTest: false,
				depthWrite: false,
			})
		);
		ring.rotation.x = -Math.PI / 2;
		ring.position.y = -0.04;
		ring.renderOrder = 81;
		ring.userData = { id: obj.id, itemType: 'emitter_halo' };
		group.add(ring);

		rootGroup.add(group);
	}

	function addSelectionEdges(geo: any, pos: any, rot: any) {
		if (!rootGroup) return;
		const edges = new THREE.LineSegments(
			new THREE.EdgesGeometry(geo),
			new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.95 })
		);
		edges.position.copy(pos);
		edges.rotation.copy(rot);
		rootGroup.add(edges);
	}

	function addSelectionBox(target: any) {
		if (!rootGroup) return;
		const box = new THREE.Box3().setFromObject(target);
		const size = new THREE.Vector3();
		const center = new THREE.Vector3();
		box.getSize(size);
		box.getCenter(center);
		if (!Number.isFinite(size.x) || size.x <= 0) return;
		const geo = new THREE.BoxGeometry(size.x + 0.03, size.y + 0.03, size.z + 0.03);
		const edges = new THREE.LineSegments(
			new THREE.EdgesGeometry(geo),
			new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.95 })
		);
		edges.position.copy(center);
		rootGroup.add(edges);
	}

	function surfaceLabelForObject(obj: any): string {
		const center = obj?.geometry?.center;
		if (!Array.isArray(center) || center.length < 2) return 'Free Height';
		const base = objectBaseHeight(obj);
		const snap = surfaceSnapForPoint({ x: Number(center[0]), y: Number(center[1]) }, String(obj.id), base);
		if (Math.abs(snap.base_height_m - base) <= 0.03) return snap.snap_label;
		return base <= 0.03 ? 'Floor' : `Free Height · ${base.toFixed(2)}m`;
	}

	function addObjectTransformGizmo(obj: any) {
		if (!rootGroup || obj?.geometry?.type !== 'point') return;
		const center = obj.geometry?.center;
		if (!Array.isArray(center) || center.length < 2) return;
		const [sx, sy, sz] = objectProxySize(obj);
		const base = objectBaseHeight(obj);
		const x = Number(center[0]) || 0;
		const z = Number(center[1]) || 0;
		const footprintW = Math.max(0.22, sx + 0.16);
		const footprintD = Math.max(0.22, sz + 0.16);

		const footprint = new THREE.Mesh(
			new THREE.PlaneGeometry(footprintW, footprintD),
			new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.14, side: THREE.DoubleSide, depthWrite: false })
		);
		footprint.rotation.x = -Math.PI / 2;
		footprint.rotation.z = -(((obj.geometry?.yaw_deg ?? 0) * Math.PI) / 180);
		footprint.position.set(x, base + 0.012, z);
		footprint.userData = { id: obj.id, itemType: 'object_gizmo', handle: 'move_xz' };
		rootGroup.add(footprint);
		selectableObjects.push(footprint);

		const yTop = base + sy;
		const yHandle = new THREE.Group();
		yHandle.userData = { id: obj.id, itemType: 'object_gizmo', handle: 'move_y' };
		const shaft = new THREE.Mesh(
			new THREE.CylinderGeometry(0.018, 0.018, 0.58, 10),
			new THREE.MeshBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.85 })
		);
		shaft.position.set(0, 0.29, 0);
		yHandle.add(shaft);
		const cone = new THREE.Mesh(
			new THREE.ConeGeometry(0.06, 0.14, 16),
			new THREE.MeshBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.9 })
		);
		cone.position.set(0, 0.64, 0);
		yHandle.add(cone);
		yHandle.position.set(x, yTop + 0.04, z);
		rootGroup.add(yHandle);
		selectableObjects.push(yHandle);

		const ringRadius = Math.max(0.22, Math.max(sx, sz) * 0.65);
		const yawRing = new THREE.Mesh(
			new THREE.TorusGeometry(ringRadius, 0.018, 8, 64),
			new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.9 })
		);
		yawRing.rotation.x = Math.PI / 2;
		yawRing.position.set(x, yTop + 0.12, z);
		yawRing.userData = { id: obj.id, itemType: 'object_gizmo', handle: 'yaw' };
		rootGroup.add(yawRing);
		selectableObjects.push(yawRing);

		if (base > 0.02) {
			const line = new THREE.Line(
				new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x, 0.012, z), new THREE.Vector3(x, base, z)]),
				new THREE.LineBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.65 })
			);
			rootGroup.add(line);
		}
		const label = _makeTextSprite(surfaceLabelForObject(obj), base <= 0.03 ? '#475569' : '#15803d');
		label.position.set(x + footprintW * 0.35, yTop + 0.38, z);
		rootGroup.add(label);
	}

	function addLineHandles(obj: any) {
		if (!rootGroup || obj.geometry?.type !== 'line') return;
		const points = [
			{ handle: 'line_start' as const, value: obj.geometry.start },
			{ handle: 'line_end' as const, value: obj.geometry.end }
		];
		for (const item of points) {
			if (!Array.isArray(item.value)) continue;
			const geo = new THREE.SphereGeometry(0.09, 14, 14);
			const mat = new THREE.MeshBasicMaterial({ color: 0xf59e0b });
			const sphere = new THREE.Mesh(geo, mat);
			sphere.position.set(item.value[0], 0.12, item.value[1]);
			sphere.userData = { id: obj.id, itemType: 'object', handle: item.handle };
			rootGroup.add(sphere);
			selectableObjects.push(sphere);
		}
	}

	// Corner drag handles for a selected rectangle region (e.g. traversable floor).
	// Lets the user resize the green floor directly in 3D — mirrors addLineHandles.
	function addRectHandles(region: any) {
		if (!rootGroup || region.geometry?.type !== 'rectangle') return;
		const b = region.geometry?.bounds;
		if (!Array.isArray(b) || b.length < 4) return;
		const [x0, z0, x1, z1] = b.map((v: any) => Number(v));
		const corners: Array<{ handle: RectHandle; x: number; z: number }> = [
			{ handle: 'rect_x0z0', x: x0, z: z0 },
			{ handle: 'rect_x1z0', x: x1, z: z0 },
			{ handle: 'rect_x0z1', x: x0, z: z1 },
			{ handle: 'rect_x1z1', x: x1, z: z1 }
		];
		for (const c of corners) {
			if (!Number.isFinite(c.x) || !Number.isFinite(c.z)) continue;
			const geo = new THREE.SphereGeometry(0.11, 14, 14);
			const mat = new THREE.MeshBasicMaterial({ color: 0x22c55e });
			const sphere = new THREE.Mesh(geo, mat);
			sphere.position.set(c.x, 0.14, c.z);
			sphere.userData = { id: region.id, itemType: 'region', handle: c.handle };
			rootGroup.add(sphere);
			selectableObjects.push(sphere);
		}
	}

	// ─── scene lifecycle ──────────────────────────────────────────────────
	function clearGroup(group: any) {
		if (!group) return;
		for (const child of [...group.children]) {
			group.remove(child);
			disposeNode(child);
		}
	}

	function _makeTextSprite(text: string, color: string = '#334155'): any {
		const canvas = document.createElement('canvas');
		const padX = 8, padY = 4;
		const fontSize = 28;
		const ctx = canvas.getContext('2d')!;
		ctx.font = `${fontSize}px sans-serif`;
		const w = Math.ceil(ctx.measureText(text).width) + padX * 2;
		const h = fontSize + padY * 2;
		canvas.width = w;
		canvas.height = h;
		const ctx2 = canvas.getContext('2d')!;
		ctx2.font = `${fontSize}px sans-serif`;
		ctx2.fillStyle = 'rgba(255,255,255,0.85)';
		ctx2.fillRect(0, 0, w, h);
		ctx2.fillStyle = color;
		ctx2.textBaseline = 'top';
		ctx2.fillText(text, padX, padY);
		const tex = new THREE.CanvasTexture(canvas);
		const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
		const sprite = new THREE.Sprite(mat);
		const scale = 0.012;
		sprite.scale.set(w * scale, h * scale, 1);
		sprite.userData = { itemType: 'guide_text' };
		return sprite;
	}

	function addEnvironment() {
		if (!baseGroup) return;
		clearGroup(baseGroup);
		floorTargets = [];

		const w = mapBounds?.w ?? 6;
		const h = mapBounds?.h ?? 4;

		// Expand floor to cover all placed authoring objects (they may extend beyond mapBounds)
		let minX = 0, minZ = 0, maxX = w, maxZ = h;
		for (const obj of authoringObjects) {
			if (isRenderOnlyLightProxy(obj)) continue;
			const c = obj?.geometry?.center;
			if (Array.isArray(c) && c.length >= 2) {
				const pad = 1.5;
				minX = Math.min(minX, c[0] - pad);
				minZ = Math.min(minZ, c[1] - pad);
				maxX = Math.max(maxX, c[0] + pad);
				maxZ = Math.max(maxZ, c[1] + pad);
			}
		}
		for (const reg of authoringRegions) {
			const b = reg?.geometry?.bounds;
			if (Array.isArray(b) && b.length >= 4) {
				const pad = 0.5;
				minX = Math.min(minX, b[0] - pad);
				minZ = Math.min(minZ, b[1] - pad);
				maxX = Math.max(maxX, b[2] + pad);
				maxZ = Math.max(maxZ, b[3] + pad);
			}
		}
		// Snap to origin (don't go negative unless content forces it)
		minX = Math.min(minX, 0);
		minZ = Math.min(minZ, 0);
		const fw = Math.max(maxX - minX, 0.5);
		const fh = Math.max(maxZ - minZ, 0.5);
		const fcx = minX + fw / 2;
		const fcz = minZ + fh / 2;

		// Editor ground plane — pure picking surface. When render floor slabs are
		// present we keep it almost invisible (just a raycast target); otherwise
		// it doubles as a faint floor reference. Always sits below the render
		// slabs so it never z-fights with them (slab tops at y=0, this at y=-0.02).
		const hasRenderFloorSlabs = Boolean(roomShell?.floor_slabs?.length);
		const floorGeo = new THREE.BoxGeometry(fw, 0.01, fh);
		const floorMat = new THREE.MeshStandardMaterial({
			color: 0xf8fafc, roughness: 1, metalness: 0,
			transparent: true,
			opacity: hasRenderFloorSlabs ? 0.04 : 0.28,
			depthWrite: false,
		});
		const floorMesh = new THREE.Mesh(floorGeo, floorMat);
		floorMesh.position.set(fcx, -0.02, fcz);
		floorMesh.userData = { floorTarget: true, editorGround: true };
		baseGroup.add(floorMesh);
		floorTargets.push(floorMesh);

		// Per-region render floor slabs (Phase 1) — 1:1 with the XML floor shapes.
		// Each slab uses a material-derived hint colour so the editor previews the
		// scene's floor variety without running Mitsuba.
		if (roomShell?.floor_slabs?.length) {
			for (const slab of roomShell.floor_slabs) {
				const [sx_w, sy_w, sz_w] = slab.size;
				if (!(sx_w > 0 && sy_w > 0 && sz_w > 0)) continue;
				const [cx_w, cy_w, cz_w] = slab.center;
				const hex = floorMaterialColor(slab.material_id);
				const slabGeo = new THREE.BoxGeometry(sx_w, sy_w, sz_w);
				const slabMat = new THREE.MeshStandardMaterial({
					color: hex, roughness: 0.9, metalness: 0,
					transparent: true, opacity: 0.78,
				});
				const slabMesh = new THREE.Mesh(slabGeo, slabMat);
				slabMesh.position.set(cx_w, cy_w, cz_w);
				slabMesh.userData = {
					id: slab.region_id ?? slab.id,
					itemType: 'region',
					role: 'region_floor',
					material_id: slab.material_id,
				};
				baseGroup.add(slabMesh);
				selectableObjects.push(slabMesh);
				floorTargets.push(slabMesh);
				const edges = new THREE.LineSegments(
					new THREE.EdgesGeometry(slabGeo),
					new THREE.LineBasicMaterial({ color: 0x475569, transparent: true, opacity: 0.35 }),
				);
				edges.position.copy(slabMesh.position);
				edges.userData = { id: slab.region_id ?? slab.id, itemType: 'region', role: 'region_floor_edges' };
				baseGroup.add(edges);
			}
		}

		// Walkability overlay PNG (user-painted walkable/blocked regions).
		if (walkabilityOverlayUrl && walkabilityOverlayBbox) {
			const [ox0, oz0, ox1, oz1] = walkabilityOverlayBbox;
			const ow = Math.max(0.1, ox1 - ox0);
			const oh = Math.max(0.1, oz1 - oz0);
			const tex = new THREE.TextureLoader().load(walkabilityOverlayUrl + (walkabilityOverlayUrl.includes('?') ? '&' : '?') + 't=' + Date.now());
			(tex as any).colorSpace = 'srgb';
			(tex as any).magFilter = THREE.NearestFilter;
			(tex as any).minFilter = THREE.NearestFilter;
			const overlayMat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.55, depthWrite: false });
			const overlayPlane = new THREE.Mesh(new THREE.PlaneGeometry(ow, oh), overlayMat);
			overlayPlane.rotation.x = -Math.PI / 2;
			overlayPlane.position.set((ox0 + ox1) / 2, 0.014, (oz0 + oz1) / 2);
			overlayPlane.userData = { itemType: 'walkability_overlay' };
			baseGroup.add(overlayPlane);
		}

		// Inflated traversable mask: red = real obstacle, orange = robot-radius halo.
		if (traversableOverlayUrl && traversableOverlayBbox) {
			const [tx0, tz0, tx1, tz1] = traversableOverlayBbox;
			const tw = Math.max(0.1, tx1 - tx0);
			const th = Math.max(0.1, tz1 - tz0);
			const tex = new THREE.TextureLoader().load(traversableOverlayUrl + (traversableOverlayUrl.includes('?') ? '&' : '?') + 't=' + Date.now());
			(tex as any).colorSpace = 'srgb';
			(tex as any).magFilter = THREE.NearestFilter;
			(tex as any).minFilter = THREE.NearestFilter;
			const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.6, depthWrite: false });
			const plane = new THREE.Mesh(new THREE.PlaneGeometry(tw, th), mat);
			plane.rotation.x = -Math.PI / 2;
			plane.position.set((tx0 + tx1) / 2, 0.013, (tz0 + tz1) / 2);
			plane.userData = { itemType: 'traversable_overlay' };
			baseGroup.add(plane);
		}

		const gridSize = Math.max(fw, fh) * 1.5;
		const gridDivs = Math.min(80, Math.max(20, Math.round(gridSize / 0.25)));
		const grid = new THREE.GridHelper(gridSize, gridDivs, 0xcbd5e1, 0xe2e8f0);
		grid.position.set(fcx, 0.002, fcz);
		baseGroup.add(grid);

		// Authoring area outline: prefer editorGeometry.bounds, fall back to mapBounds
		const eb = editorGeometry?.bounds;
		const bMin = eb?.min ?? [0, 0, 0];
		const bMax = eb?.max ?? [w, 0, h];
		const bW = Math.max(0.1, Number(bMax[0]) - Number(bMin[0]));
		const bH = Math.max(0.1, Number(bMax[2]) - Number(bMin[2]));
		const bCenter = [Number(bMin[0]) + bW / 2, 0, Number(bMin[2]) + bH / 2];
		const bSize = [bW, 0.005, bH];

		if (visibleLayers.usdBackground) {
			for (const obj of editorGeometry?.objects ?? []) {
				if (obj.category === 'floor') continue;
				const size = boundsSize(obj.bounds);
				const center = boundsCenter(obj.bounds);
				const category = obj.category ?? 'object';
				const geo = new THREE.BoxGeometry(Math.max(0.01, size[0]), Math.max(0.01, size[1]), Math.max(0.01, size[2]));
				const mat = new THREE.MeshStandardMaterial({
					color: usdProxyColor(category),
					transparent: true,
					opacity: category === 'glass' ? 0.28 : category === 'mirror' ? 0.42 : 0.22,
					roughness: category === 'mirror' ? 0.15 : 0.85,
					metalness: category === 'mirror' ? 0.55 : 0
				});
				const mesh = new THREE.Mesh(geo, mat);
				mesh.position.set(center[0], center[1], center[2]);
				mesh.userData = { readOnlyUsd: true, sourcePath: obj.source_path };
				baseGroup.add(mesh);
				const edges = new THREE.LineSegments(
					new THREE.EdgesGeometry(geo),
					new THREE.LineBasicMaterial({ color: usdProxyColor(category), transparent: true, opacity: 0.42 })
				);
				edges.position.copy(mesh.position);
				baseGroup.add(edges);
			}
		}

		const outlineGeo = new THREE.BoxGeometry(6, 0.005, 4);
		const outline = new THREE.LineSegments(
			new THREE.EdgesGeometry(outlineGeo),
			new THREE.LineBasicMaterial({ color: 0x94a3b8, transparent: true, opacity: 0.7 })
		);
		outline.scale.set(Math.max(0.001, bSize[0] / 6), 1, Math.max(0.001, bSize[2] / 4));
		outline.position.set(bCenter[0], 0.006, bCenter[2]);
		baseGroup.add(outline);

		// Floor label
		if (showGuides.floor) {
			const floorLabel = _makeTextSprite('Floor · y=0.00');
			floorLabel.position.set(bCenter[0] - bSize[0] / 2 + 0.3, 0.05, bCenter[2] - bSize[2] / 2 + 0.3);
			baseGroup.add(floorLabel);
		}

		// Eye-height plane: translucent plane + label at the active camera height.
		if (showGuides.eyeHeight && eyeHeightM > 0 && eyeHeightM < wallHeight) {
			const eyeFill = new THREE.Mesh(
				new THREE.PlaneGeometry(1, 1),
				new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.06, side: THREE.DoubleSide, depthWrite: false })
			);
			eyeFill.rotation.x = -Math.PI / 2;
			eyeFill.scale.set(bSize[0], bSize[2], 1);
			eyeFill.position.set(bCenter[0], eyeHeightM, bCenter[2]);
			eyeFill.userData = { itemType: 'guide_eye' };
			baseGroup.add(eyeFill);
			const eyeLabel = _makeTextSprite(`Eye · y=${eyeHeightM.toFixed(2)}m`, '#1e40af');
			eyeLabel.position.set(bCenter[0] - bSize[0] / 2 + 0.3, eyeHeightM + 0.05, bCenter[2] - bSize[2] / 2 + 0.3);
			baseGroup.add(eyeLabel);
		}

		// Selected object bbox + height label
		if (showGuides.objectBbox && selectedObjectGuide) {
			const g = selectedObjectGuide;
			const bboxGeo = new THREE.BoxGeometry(Math.max(0.05, g.size[0]), Math.max(0.05, g.size[1]), Math.max(0.05, g.size[2]));
			const bboxEdges = new THREE.LineSegments(
				new THREE.EdgesGeometry(bboxGeo),
				new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.9 })
			);
			bboxEdges.position.set(g.center[0], g.center[1], g.center[2]);
			bboxEdges.userData = { itemType: 'guide_bbox' };
			baseGroup.add(bboxEdges);
			const labelText = `${g.label} · h=${g.size[1].toFixed(2)}m`;
			const lbl = _makeTextSprite(labelText, '#92400e');
			lbl.position.set(g.center[0], g.center[1] + g.size[1] / 2 + 0.1, g.center[2]);
			baseGroup.add(lbl);
		}

		// Auto room shell: the 6 cubes that the Mitsuba renderer adds for floor /
		// ceiling slab + 4 perimeter walls. Surface them in the editor so the user
		// understands "where do these big walls come from?".
		if (showRoomShell && roomShell?.shapes?.length) {
			const wallMat = new THREE.MeshBasicMaterial({ color: 0x94a3b8, transparent: true, opacity: 0.18, depthWrite: false });
			const slabMat = new THREE.MeshBasicMaterial({ color: 0xcbd5e1, transparent: true, opacity: 0.10, depthWrite: false });
			// Ceiling and perimeter walls are gated independently (mirrors the renderer
			// in render_daemon.py). Skip the preview cubes that the scene won't emit so
			// the editor matches the render. Default true when the flags are absent.
			const wallsOn = roomShell.walls_enabled ?? true;
			const ceilingOn = roomShell.ceiling_enabled ?? wallsOn;
			for (const sh of roomShell.shapes) {
				if (sh.role === 'ceiling' && !ceilingOn) continue;
				if (sh.role !== 'ceiling' && sh.role !== 'floor' && !wallsOn) continue;
				const [cx_w, cy_w, cz_w] = sh.center;
				const [sx_w, sy_w, sz_w] = sh.size;
				if (!(sx_w > 0 && sy_w > 0 && sz_w > 0)) continue;
				const isSlab = sh.role === 'floor' || sh.role === 'ceiling';
				const geo = new THREE.BoxGeometry(sx_w, sy_w, sz_w);
				const mesh = new THREE.Mesh(geo, (isSlab ? slabMat : wallMat).clone());
				mesh.position.set(cx_w, cy_w, cz_w);
				mesh.userData = { itemType: 'room_shell', role: sh.role };
				baseGroup.add(mesh);
				const edges = new THREE.LineSegments(
					new THREE.EdgesGeometry(geo),
					new THREE.LineBasicMaterial({ color: 0x475569, transparent: true, opacity: 0.55 })
				);
				edges.position.copy(mesh.position);
				edges.userData = { itemType: 'room_shell_edges' };
				baseGroup.add(edges);
				// Label
				const labelText = (() => {
					if (sh.role === 'floor') return `Auto floor · y=${cy_w.toFixed(2)}m`;
					if (sh.role === 'ceiling') return `Auto ceiling · y=${cy_w.toFixed(2)}m`;
					const dirs: Record<string, string> = { wall_n: 'N wall', wall_s: 'S wall', wall_e: 'E wall', wall_w: 'W wall' };
					const dir = dirs[sh.role] ?? 'wall';
					return `${dir} · ${Math.max(sx_w, sz_w).toFixed(1)}m × ${sy_w.toFixed(2)}m`;
				})();
				const labelColor = isSlab ? '#475569' : '#1f2937';
				const sprite = _makeTextSprite(labelText, labelColor);
				const labelY = isSlab ? cy_w + 0.05 : cy_w + sy_w / 2 + 0.05;
				sprite.position.set(cx_w, labelY, cz_w);
				baseGroup.add(sprite);
			}
		}

		// Robot footprint inflation overlay: red translucent outline inset from the
		// floor by `footprintInflationM` on every side. Approximation only — does not
		// account for interior obstacles.
		if (footprintInflationM > 0) {
			const insetW = Math.max(0.1, bSize[0] - footprintInflationM * 2);
			const insetH = Math.max(0.1, bSize[2] - footprintInflationM * 2);
			const insetGeo = new THREE.BoxGeometry(6, 0.005, 4);
			const insetOutline = new THREE.LineSegments(
				new THREE.EdgesGeometry(insetGeo),
				new THREE.LineBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.55 })
			);
			insetOutline.scale.set(insetW / 6, 1, insetH / 4);
			insetOutline.position.set(bCenter[0], 0.008, bCenter[2]);
			insetOutline.userData = { footprint: true };
			baseGroup.add(insetOutline);
		}

		// Translucent ceiling outline at wall_h — informs users that the render scene
		// has a sealed ceiling that affects lighting, without occluding the 3D view.
		if (wallHeight > 0) {
			const ceilingGeo = new THREE.BoxGeometry(6, 0.005, 4);
			const ceilingOutline = new THREE.LineSegments(
				new THREE.EdgesGeometry(ceilingGeo),
				new THREE.LineBasicMaterial({ color: 0x64748b, transparent: true, opacity: 0.25 })
			);
			ceilingOutline.scale.set(Math.max(0.001, bSize[0] / 6), 1, Math.max(0.001, bSize[2] / 4));
			ceilingOutline.position.set(bCenter[0], wallHeight, bCenter[2]);
			ceilingOutline.userData = { ceiling: true };
			baseGroup.add(ceilingOutline);
			if (showGuides.ceiling) {
				const ceilingLabel = _makeTextSprite(`Ceiling · y=${wallHeight.toFixed(2)}m`, '#475569');
				ceilingLabel.position.set(bCenter[0] - bSize[0] / 2 + 0.3, wallHeight + 0.05, bCenter[2] - bSize[2] / 2 + 0.3);
				baseGroup.add(ceilingLabel);
			}
			// Optional very faint translucent fill so the plane is hintable even from below.
			const ceilingFill = new THREE.Mesh(
				new THREE.PlaneGeometry(1, 1),
				new THREE.MeshBasicMaterial({ color: 0xcbd5e1, transparent: true, opacity: 0.05, side: THREE.DoubleSide, depthWrite: false })
			);
			ceilingFill.rotation.x = -Math.PI / 2;
			ceilingFill.scale.set(bSize[0], bSize[2], 1);
			ceilingFill.position.set(bCenter[0], wallHeight - 0.002, bCenter[2]);
			ceilingFill.userData = { ceiling: true };
			baseGroup.add(ceilingFill);
		}
	}

	function rebuildScene() {
		if (!rootGroup || !scene3D) return;
		const editorMeshStats: EditorMeshStats = {
			xml_native_enabled: xmlNativePreviewEnabled,
			authoring_objects: authoringObjects.length,
			xml_matched: 0,
			mesh_loaded: 0,
			placeholder_loading: 0,
			placeholder_cached_null: 0,
			architecture_proxy: 0,
			xml_fallback_shape: 0,
			authoring_proxy_fallback: 0,
			pickable: 0,
			non_pickable: 0,
			cache: getObjMeshCacheStats(),
		};
		selectableObjects = [];
		clearGroup(rootGroup);

		// Regions
		for (const region of authoringRegions) {
			if (!isRegionVisible(region.type)) continue;
			const mesh = buildRegion(region);
			if (!mesh) continue;
			rootGroup.add(mesh);
			selectableObjects.push(mesh);
			if (selectedId === region.id) {
				addSelectionEdges(mesh.geometry, mesh.position.clone().setY(0.003), mesh.rotation.clone());
				addRectHandles(region);
			}
		}

		// Graph edges
		if (visibleLayers.graphEdges) {
			for (const edge of graphEdges) {
				const s = graphNodes.find((n: any) => n.node_id === edge.source);
				const t = graphNodes.find((n: any) => n.node_id === edge.target);
				if (!s || !t) continue;
				const pts = [
					new THREE.Vector3(s.position?.[0] ?? 0, 0.04, s.position?.[1] ?? 0),
					new THREE.Vector3(t.position?.[0] ?? 0, 0.04, t.position?.[1] ?? 0)
				];
				const isManual = Boolean(edge.extras?.manual);
				const line = new THREE.Line(
					new THREE.BufferGeometry().setFromPoints(pts),
					new THREE.LineBasicMaterial({
						color: edge.hazard_crossing ? 0xf97316 : isManual ? 0xa855f7 : 0x6366f1,
						transparent: true, opacity: isManual ? 0.9 : 0.55,
						linewidth: isManual ? 2 : 1,
					})
				);
				line.userData = { id: edge.edge_id, itemType: 'edge', manual: isManual };
				rootGroup.add(line);
			}
		}

		// Objects (walls + points)
		if (visibleLayers.objects) {
			rebuildXmlShapeIndex();
			for (const obj of authoringObjects) {
				let mesh: any = null;
				let builtFromXml = false;
				if (isRenderOnlyLightProxy(obj)) continue;
				const matchedXmlShape = xmlNativePreviewEnabled && _xmlShapeIndex.has(obj.id);
				if (matchedXmlShape) editorMeshStats.xml_matched++;
				// PR2: when the XML-native preview toggle is on, draw from the actual
				// render-side mesh first. authoringObjects without a matching XML shape
				// (placement-only items, edits not yet synced) fall through to the
				// existing buildWall / buildPointObject path.
				if (xmlNativePreviewEnabled) {
					mesh = buildObjectFromXmlShape(obj);
					builtFromXml = !!mesh;
				}
				if (!mesh) {
					if (obj.geometry?.type === 'line') mesh = buildWall(obj);
					else if (obj.geometry?.type === 'point') mesh = buildPointObject(obj);
				}
				if (!mesh) continue;
				if (!builtFromXml && xmlNativePreviewEnabled) editorMeshStats.authoring_proxy_fallback++;
				const previewState = String(mesh?.userData?.editor_preview_state ?? '');
				if (previewState === 'mesh_cached') editorMeshStats.mesh_loaded++;
				else if (previewState === 'placeholder_loading') editorMeshStats.placeholder_loading++;
				else if (previewState === 'placeholder_cached_null') editorMeshStats.placeholder_cached_null++;
				else if (previewState === 'architecture_proxy') editorMeshStats.architecture_proxy++;
				else if (previewState === 'xml_fallback_shape') editorMeshStats.xml_fallback_shape++;
				rootGroup.add(mesh);
				// Glass/windows render as see-through architecture but stay clickable so the
				// user can select a window to inspect its material. This fallback keeps them
				// pickable even with editor_geometry generated before the daemon-side fix.
				const _archKind = String(mesh?.userData?.architecture_kind ?? '').toLowerCase();
				const editorPickable = mesh?.userData?.editor_pickable !== false
					|| _archKind.includes('glass') || _archKind.includes('window');
				if (editorPickable) { selectableObjects.push(mesh); editorMeshStats.pickable++; }
				else editorMeshStats.non_pickable++;
				if (editorPickable && selectedId === obj.id) {
					if (mesh.geometry) addSelectionEdges(mesh.geometry, mesh.position.clone(), mesh.rotation.clone());
					else addSelectionBox(mesh);
					addLineHandles(obj);
					if (objectTransformMode && obj.geometry?.type === 'point') addObjectTransformGizmo(obj);
				}
			}
			for (const obj of authoringObjects) addEmitterOverlayForObject(obj);
		}

		// Optical perturbation overlay (separate, toggleable layer): render the
		// auto-placed mirror_wall / glass_wall line objects so the user can see and
		// judge placement in the editor. buildWall already styles glass (blue) and
		// mirror (metallic); we tag them + a faint emissive so the overlay reads as
		// distinct from base walls. Display-only (not pushed to selectableObjects).
		if (perturbationEnabled) {
			for (const obj of perturbationObjects) {
				if (obj?.geometry?.type !== 'line') continue;
				const mesh = buildWall(obj);
				if (!mesh) continue;
				mesh.userData = { ...(mesh.userData || {}), perturbation: true };
				try {
					if (mesh.material && mesh.material.emissive)
						mesh.material.emissive = new THREE.Color(obj.type === 'mirror_wall' ? 0x335577 : 0x224466);
				} catch { /* material has no emissive — fine */ }
				rootGroup.add(mesh);
			}
		}

		editorMeshStats.cache = getObjMeshCacheStats();
		onMeshStats?.(editorMeshStats);

		// Graph nodes
		if (visibleLayers.graphNodes) {
			// Stable component → color palette for disconnected pieces.
			const componentPalette = [0x6366f1, 0xef4444, 0xfbbf24, 0xa855f7, 0x14b8a6, 0xec4899, 0x84cc16];
			for (const node of graphNodes) {
				const isHazard = node.tags?.includes('hazard_adjacent');
				const isSensor = editorMode === 'sensor';
				const componentIdx = graphComponents?.[node.node_id];
				const componentColor = (typeof componentIdx === 'number' && componentIdx > 0)
					? componentPalette[componentIdx % componentPalette.length]
					: 0x6366f1;
				// Nodes flagged for removal render large + red regardless of component.
				const markedForRemoval = removeSelection?.has?.(node.node_id) ?? false;
				const baseRadius = isSensor ? 0.09 : 0.06;
				const geo = new THREE.SphereGeometry(markedForRemoval ? baseRadius * 1.8 : baseRadius, 8, 8);
				const mat = new THREE.MeshBasicMaterial({
					color: markedForRemoval ? 0xdc2626 : isSensor ? 0xf59e0b : isHazard ? 0xf97316 : componentColor
				});
				const sphere = new THREE.Mesh(geo, mat);
				sphere.position.set(node.position?.[0] ?? 0, markedForRemoval ? 0.09 : 0.06, node.position?.[1] ?? 0);
				sphere.userData = { id: node.node_id, itemType: 'node' };
				rootGroup.add(sphere);
				selectableObjects.push(sphere);
			}
		}

		// All episode paths (export mode overview) — dim gray/red polylines
		for (const ep of allEpisodePaths) {
			if (ep.coords.length < 2) continue;
			const pts = ep.coords.map(([x, z]: [number, number]) => new THREE.Vector3(x, 0.08, z));
			const line = new THREE.Line(
				new THREE.BufferGeometry().setFromPoints(pts),
				new THREE.LineBasicMaterial({
					color: ep.hasHazard ? 0xfca5a5 : 0x94a3b8,
					transparent: true,
					opacity: ep.hasHazard ? 0.45 : 0.3
				})
			);
			rootGroup.add(line);
		}

		// Highlighted episode path — yellow polyline above graph edges
		if (highlightedPath && highlightedPath.length >= 2) {
			const pts = highlightedPath.map(([x, z]: [number, number]) => new THREE.Vector3(x, 0.1, z));
			const line = new THREE.Line(
				new THREE.BufferGeometry().setFromPoints(pts),
				new THREE.LineBasicMaterial({ color: 0xfbbf24, linewidth: 3 })
			);
			rootGroup.add(line);
			for (const pt of pts) {
				const dot = new THREE.Mesh(
					new THREE.SphereGeometry(0.07, 8, 8),
					new THREE.MeshBasicMaterial({ color: 0xfbbf24 })
				);
				dot.position.copy(pt);
				rootGroup.add(dot);
			}
		}

		// Custom sensor camera markers
		for (const csn of customSensorNodes) {
			const yaw = (csn.headingDeg * Math.PI) / 180;
			// Body sphere
			const body = new THREE.Mesh(
				new THREE.SphereGeometry(0.12, 10, 10),
				new THREE.MeshBasicMaterial({ color: csn.selected ? 0xffffff : 0x22d3ee })
			);
			body.position.set(csn.x, 0.12, csn.z);
			body.userData = { id: csn.id, itemType: 'node' };
			selectableObjects.push(body);
			rootGroup.add(body);
			// Direction cone
			const cone = new THREE.Mesh(
				new THREE.ConeGeometry(0.07, 0.22, 4),
				new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.7 })
			);
			cone.rotation.z = -Math.PI / 2;
			cone.position.set(csn.x + Math.sin(yaw) * 0.18, 0.12, csn.z + Math.cos(yaw) * 0.18);
			cone.rotation.y = -yaw;
			rootGroup.add(cone);
			// Ring if selected
			if (csn.selected) {
				const ring = new THREE.Mesh(
					new THREE.RingGeometry(0.15, 0.19, 20),
					new THREE.MeshBasicMaterial({ color: 0x22d3ee, side: THREE.DoubleSide })
				);
				ring.rotation.x = -Math.PI / 2;
				ring.position.set(csn.x, 0.02, csn.z);
				rootGroup.add(ring);
			}
		}
	}

	function updateGhost() {
		if (!ghostGroup) return;
		for (const child of [...ghostGroup.children]) {
			ghostGroup.remove(child);
			disposeNode(child);
		}
		if (!draftGhost || editorMode === 'simulate') return;

		const color = draftGhost.valid ? 0x22c55e : 0xef4444;
		const opacity = 0.42;

		if (draftGhost.type === 'line') {
			const { x1, y1: z1, x2, y2: z2 } = draftGhost;
			const len = Math.hypot(x2 - x1, z2 - z1);
			if (len < 0.01) return;
			const height = 2.4;
			const angle = Math.atan2(x2 - x1, z2 - z1);
			const geo = new THREE.BoxGeometry(0.08, height, len);
			const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide });
			const mesh = new THREE.Mesh(geo, mat);
			mesh.position.set((x1 + x2) / 2, height / 2, (z1 + z2) / 2);
			mesh.rotation.y = angle;
			ghostGroup.add(mesh);
			const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color }));
			edges.position.copy(mesh.position);
			edges.rotation.copy(mesh.rotation);
			ghostGroup.add(edges);
		} else if (draftGhost.type === 'rect') {
			const w = draftGhost.maxX - draftGhost.minX;
			const d = draftGhost.maxY - draftGhost.minY;
			if (w < 0.01 || d < 0.01) return;
			const geo = new THREE.PlaneGeometry(w, d);
			const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false });
			const mesh = new THREE.Mesh(geo, mat);
			mesh.rotation.x = -Math.PI / 2;
			mesh.position.set(draftGhost.minX + w / 2, 0.005, draftGhost.minY + d / 2);
			ghostGroup.add(mesh);
		} else if (draftGhost.type === 'point') {
				const sp = (draftGhost as any).sourcePath as string | undefined;
				const cachedGeo = sp ? primMeshCache.get(primMeshKey(sp, preloadUsdRef)) : undefined;
				const snap = surfaceSnapForPoint({ x: draftGhost.x, y: draftGhost.y }, '', Number((draftGhost as any).baseHeightM ?? 0));
				const baseHeight = Number((draftGhost as any).baseHeightM ?? snap.base_height_m ?? 0);
			if (cachedGeo) {
				const ghostMat = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.55, depthWrite: false });
				const mesh = new THREE.Mesh(cachedGeo, ghostMat);
				const box = new THREE.Box3().setFromBufferAttribute(cachedGeo.attributes.position as any);
				const ghostWorldY = baseHeight + ((draftGhost as any).normalizedYMin ?? 0);
				mesh.position.set(draftGhost.x, ghostWorldY - box.min.y, draftGhost.y);
				ghostGroup.add(mesh);
			} else {
				const geo = new THREE.SphereGeometry(0.14, 10, 10);
				const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity });
				const sphere = new THREE.Mesh(geo, mat);
				sphere.position.set(draftGhost.x, baseHeight + 0.14, draftGhost.y);
				ghostGroup.add(sphere);
			}
			const proxy = (draftGhost as any).proxySize;
			const sx = Array.isArray(proxy) ? Math.max(0.12, Number(proxy[0]) || 0.4) : 0.4;
			const sz = Array.isArray(proxy) ? Math.max(0.12, Number(proxy[2]) || 0.4) : 0.4;
			const footprint = new THREE.Mesh(
				new THREE.PlaneGeometry(sx, sz),
				new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false })
			);
			footprint.rotation.x = -Math.PI / 2;
			footprint.position.set(draftGhost.x, baseHeight + 0.01, draftGhost.y);
			ghostGroup.add(footprint);
			const label = _makeTextSprite(snap.snap_label ?? 'Floor', baseHeight > 0.03 ? '#15803d' : '#475569');
			label.position.set(draftGhost.x + 0.24, baseHeight + 0.45, draftGhost.y);
			ghostGroup.add(label);
		}

		// Draft point indicator (first click for line tools)
		if (draftPoint) {
			const geo = new THREE.SphereGeometry(0.1, 10, 10);
			const mat = new THREE.MeshBasicMaterial({ color: 0xf59e0b });
			const sphere = new THREE.Mesh(geo, mat);
			sphere.position.set(draftPoint.x, 0.1, draftPoint.y);
			ghostGroup.add(sphere);
		}
	}

	function updateRobot() {
		if (!robotGroup) return;
		for (const child of [...robotGroup.children]) {
			robotGroup.remove(child);
			disposeNode(child);
		}
		if (editorMode !== 'simulate' || !robotPos) return;
		const geo = new THREE.CylinderGeometry(0.18, 0.22, 0.38, 16);
		const mat = new THREE.MeshBasicMaterial({ color: 0x3b82f6 });
		const body = new THREE.Mesh(geo, mat);
		body.position.set(robotPos.x, 0.22, robotPos.y);
		robotGroup.add(body);
		const ringGeo = new THREE.TorusGeometry(0.35, 0.025, 10, 36);
		const ringMat = new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.38 });
		const ring = new THREE.Mesh(ringGeo, ringMat);
		ring.rotation.x = Math.PI / 2;
		ring.position.set(robotPos.x, 0.02, robotPos.y);
		robotGroup.add(ring);
	}

	function disposeNode(node: any) {
		node.traverse?.((child: any) => {
			child.geometry?.dispose();
			if (Array.isArray(child.material)) child.material.forEach((m: any) => m.dispose());
			else child.material?.dispose();
		});
	}

	// ─── Three.js init ────────────────────────────────────────────────────
	function ensureThree() {
		if (!host || renderer) return;

		renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
		renderer.setClearColor(0xf1f5f9, 1);
		host.appendChild(renderer.domElement);

		scene3D = new THREE.Scene();
		scene3D.background = new THREE.Color(0xf1f5f9);

		camera = new THREE.PerspectiveCamera(45, 1, 0.1, 200);
		camera.position.set(3, 8, -3);
		camera.lookAt(3, 0, 2);

		controls = new OrbitControls(camera, renderer.domElement);
		controls.target.set(3, 0, 2);
		controls.enableDamping = true;
		controls.dampingFactor = 0.08;
		controls.minDistance = 1;
		controls.maxDistance = 22;
		controls.maxPolarAngle = Math.PI / 2.1;
		controls.screenSpacePanning = false;
		controls.mouseButtons = {
			LEFT: undefined as any,
			MIDDLE: THREE.MOUSE.DOLLY,
			RIGHT: THREE.MOUSE.ROTATE
		};
		controls.touches = {
			ONE: THREE.TOUCH.ROTATE,
			TWO: THREE.TOUCH.DOLLY_PAN
		};
		controls.update();
		controls.addEventListener('change', () => {
			if (frustumMode === 'view-aligned') updateFrustumVisibility();
			// Viewport-aware image lazy load: camera moved → re-evaluate which vps
			// are in view and load their preview images. Debounced so a drag burst
			// triggers exactly one rebuild after the user pauses.
			scheduleViewportFrustumRefresh();
		});

		baseGroup = new THREE.Group();
		rootGroup = new THREE.Group();
		ghostGroup = new THREE.Group();
		robotGroup = new THREE.Group();
		hoverGroup = new THREE.Group();
		frustumGroup = new THREE.Group();
		scene3D.add(baseGroup, rootGroup, ghostGroup, robotGroup, hoverGroup, frustumGroup);

		const ambient = new THREE.AmbientLight(0xffffff, 0.8);
		const dir = new THREE.DirectionalLight(0xffffff, 0.85);
		dir.position.set(6, 12, 3);
		scene3D.add(ambient, dir);

		const loop = (now = performance.now()) => {
			animationFrame = requestAnimationFrame(loop);
			const dt = lastFrameMs > 0 ? Math.min(0.05, Math.max(0, (now - lastFrameMs) / 1000)) : 0;
			lastFrameMs = now;
			updateKeyboardCamera(dt);
			controls?.update();
			renderer?.render(scene3D!, camera!);
		};
		loop();

		const resize = () => {
			if (!host || !renderer || !camera) return;
			const w = Math.max(1, host.clientWidth);
			const h = Math.max(1, host.clientHeight);
			renderer.setSize(w, h, false);
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
		};
		resizeObserver = new ResizeObserver(resize);
		resizeObserver.observe(host);
		resize();
		addEnvironment();
	}

	// ─── view presets ─────────────────────────────────────────────────────
	export function setViewTopDown() {
		if (!camera || !controls) return;
		camera.position.set(3, 12, 2.0001);
		camera.up.set(0, 0, -1);
		controls.target.set(3, 0, 2);
		controls.update();
	}

	export function setViewIso() {
		if (!camera || !controls) return;
		camera.up.set(0, 1, 0);
		camera.position.set(3, 8, -3);
		controls.target.set(3, 0, 2);
		controls.update();
	}

	export function setViewSide() {
		if (!camera || !controls) return;
		camera.up.set(0, 1, 0);
		camera.position.set(-4, 3, 2);
		controls.target.set(3, 0, 2);
		controls.update();
	}

	/** Snapshot of the orbit camera in world coords. Used by the Preview tab to
	 *  render the current editor view through Mitsuba. */
	export function getCurrentCamera(): { origin: [number, number, number]; target: [number, number, number]; up: [number, number, number]; fov_deg: number; aspect: number } | null {
		if (!camera || !controls) return null;
		const o = camera.position;
		const t = controls.target;
		const u = camera.up;
		return {
			origin: [o.x, o.y, o.z],
			target: [t.x, t.y, t.z],
			up: [u.x, u.y, u.z],
			fov_deg: camera.fov,
			aspect: camera.aspect,
		};
	}

	function startObjectTransform(id: string, handle: ObjectGizmoHandle, event: PointerEvent) {
		const obj = pointObjectById(id);
		const center = obj?.geometry?.center;
		if (!obj || !Array.isArray(center) || center.length < 2) return false;
		objectDrag = {
			id,
			handle,
			startCenter: [Number(center[0]) || 0, Number(center[1]) || 0],
			startBaseHeight: objectBaseHeight(obj),
			startYaw: Number(obj.geometry?.yaw_deg ?? 0) || 0,
			startClientY: event.clientY
		};
		if (controls) controls.enabled = false;
		if (renderer) renderer.domElement.style.cursor = handle === 'move_y' ? 'ns-resize' : handle === 'yaw' ? 'crosshair' : 'grabbing';
		onObjectTransform?.(id, {}, 'drag_start');
		return true;
	}

	function updateObjectTransform(event: PointerEvent) {
		if (!objectDrag) return;
		const { id, handle, startBaseHeight, startYaw, startClientY } = objectDrag;
		if (handle === 'move_xz') {
			const pt = getWorldPoint(event);
			if (!pt) return;
			const snapped = snapPointXZ(pt, event);
			const patch: ObjectTransformPatch = { center: [snapped.x, snapped.y] };
			if (surfaceSnapEnabled && !event.altKey) {
				const surface = surfaceSnapForPoint(snapped, id, startBaseHeight);
				patch.base_height_m = surface.base_height_m;
			} else {
				patch.base_height_m = startBaseHeight;
			}
			onObjectTransform?.(id, patch, 'drag_move');
			return;
		}
		if (handle === 'move_y') {
			const sensitivity = event.shiftKey ? 0.003 : 0.01;
			let height = Math.max(0, startBaseHeight + (startClientY - event.clientY) * sensitivity);
			const step = movementSnapStep(event);
			if (step) height = snapScalar(height, step);
			onObjectTransform?.(id, { base_height_m: Number(height.toFixed(3)) }, 'height_move');
			return;
		}
		if (handle === 'yaw') {
			const pt = getWorldPoint(event);
			const obj = pointObjectById(id);
			const center = obj?.geometry?.center ?? objectDrag.startCenter;
			if (!pt || !Array.isArray(center)) return;
			const dx = pt.x - Number(center[0]);
			const dz = pt.y - Number(center[1]);
			if (Math.hypot(dx, dz) < 0.03) return;
			let yaw = (Math.atan2(dx, dz) * 180) / Math.PI;
			const step = angleSnapStep(event);
			if (step) yaw = snapScalar(yaw, step);
			yaw = Number((((yaw % 360) + 360) % 360).toFixed(1));
			if (!Number.isFinite(yaw)) yaw = startYaw;
			onObjectTransform?.(id, { yaw_deg: yaw }, 'yaw_move');
		}
	}

	function finishObjectTransform() {
		if (!objectDrag) return;
		const id = objectDrag.id;
		objectDrag = null;
		if (controls) controls.enabled = true;
		if (renderer) renderer.domElement.style.cursor = '';
		onObjectTransform?.(id, {}, 'drag_end');
	}

	// ─── pointer events ───────────────────────────────────────────────────
	function objectAndParentsVisible(obj: any): boolean {
		let n = obj;
		while (n) {
			if (n.visible === false) return false;
			n = n.parent;
		}
		return true;
	}

	function previewOverlayList(): PreviewCameraOverlay[] {
		if (!previewCameraOverlay) return [];
		return Array.isArray(previewCameraOverlay) ? previewCameraOverlay : [previewCameraOverlay];
	}

	function activePreviewOverlay(): PreviewCameraOverlay | null {
		const overlays = previewOverlayList();
		return overlays.find((item) => item.active) ?? overlays[overlays.length - 1] ?? null;
	}

	function frustumHalfExtents(distance: number, intrinsics: CameraFrustumIntrinsics | null = frustumIntrinsics) {
		const resolution = Array.isArray(intrinsics?.resolution) && intrinsics!.resolution.length >= 2
			? intrinsics!.resolution
			: [4, 3];
		const aspect = Math.max(0.1, (Number(resolution[0]) || 4) / Math.max(1, Number(resolution[1]) || 3));
		const fovH = Math.max(1, Math.min(175, Number(intrinsics?.fov_deg ?? 70)));
		const fovV = Number(intrinsics?.fov_v_deg ?? 0) > 0
			? Math.max(1, Math.min(175, Number(intrinsics?.fov_v_deg)))
			: (Math.atan(Math.tan((fovH * Math.PI / 180) / 2) / aspect) * 2 * 180 / Math.PI);
		return {
			halfW: Math.tan((fovH * Math.PI / 180) / 2) * distance,
			halfH: Math.tan((fovV * Math.PI / 180) / 2) * distance,
		};
	}

	function buildCameraFrustumGroup(args: {
		x: number; z: number; yawDeg: number; height: number; hasImage?: boolean;
		imageUrl?: string; vpId?: string; headingId?: string; intrinsics?: CameraFrustumIntrinsics | null;
		color?: number; opacity?: number;
	}) {
		const displayDist = 0.5;
		const { halfW, halfH } = frustumHalfExtents(displayDist, args.intrinsics ?? frustumIntrinsics);
		const yaw = (args.yawDeg * Math.PI) / 180;
		const origin = new THREE.Vector3(args.x, args.height, args.z);
		const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
		const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
		const up = new THREE.Vector3(0, 1, 0);
		const negFwd = fwd.clone().negate();
		const center = origin.clone().addScaledVector(fwd, displayDist);
		const group = new THREE.Group();
		const tl = center.clone().addScaledVector(right, -halfW).addScaledVector(up, halfH);
		const tr = center.clone().addScaledVector(right, halfW).addScaledVector(up, halfH);
		const bl = center.clone().addScaledVector(right, -halfW).addScaledVector(up, -halfH);
		const br = center.clone().addScaledVector(right, halfW).addScaledVector(up, -halfH);
		const linePoints = [origin, tl, origin, tr, origin, bl, origin, br, tl, tr, tr, br, br, bl, bl, tl];
		group.add(new THREE.LineSegments(
			new THREE.BufferGeometry().setFromPoints(linePoints),
			new THREE.LineBasicMaterial({ color: args.color ?? 0x38bdf8, transparent: true, opacity: args.opacity ?? 0.9 })
		));
		if (args.hasImage && args.imageUrl) {
			const url = args.imageUrl;
			let texture = textureCache.get(url);
			if (!texture) {
				// Insert a placeholder Texture object into the cache immediately so any
				// concurrent buildCameraFrustumGroup calls for the same URL share it.
				// The real bitmap is fetched through acquireFrustumSlot — when it
				// finishes we swap .image and flip needsUpdate so every plane already
				// bound to this Texture picks the bytes up on the next frame.
				texture = new THREE.Texture();
				(texture as any).colorSpace = 'srgb';
				textureCache.set(url, texture);
				acquireFrustumSlot().then(() => {
					new THREE.TextureLoader().load(
						url,
						(loaded: any) => {
							try {
								texture.image = loaded.image;
								(texture as any).colorSpace = 'srgb';
								texture.needsUpdate = true;
							} finally {
								releaseFrustumSlot();
							}
						},
						undefined,
						() => { releaseFrustumSlot(); },
					);
				});
			}
			const rotMat = new THREE.Matrix4().makeBasis(right, up, negFwd);
			const plane = new THREE.Mesh(
				new THREE.PlaneGeometry(halfW * 2, halfH * 2),
				new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide })
			);
			plane.position.copy(center);
			plane.quaternion.setFromRotationMatrix(rotMat);
			plane.userData = { frustum: true, vpId: args.vpId, headingId: args.headingId, hasRgb: true };
			group.add(plane);
			if (args.vpId && args.headingId) frustumSelectables.push(plane);
		}
		return group;
	}

	function getFrustumHit(event: PointerEvent | MouseEvent): { vpId: string; headingId: string } | null {
		if (!renderer || !camera || !frustumSelectables.length) return null;
		const rect = renderer.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((event.clientX - rect.left) / rect.width) * 2 - 1,
			-((event.clientY - rect.top) / rect.height) * 2 + 1
		);
		raycaster.setFromCamera(ndc, camera);
		const hits = raycaster.intersectObjects(frustumSelectables.filter(objectAndParentsVisible), false);
		if (!hits.length) return null;
		const ud = hits[0].object.userData;
		if (ud?.frustum && ud.vpId && ud.headingId) return { vpId: ud.vpId, headingId: ud.headingId };
		return null;
	}

	function onPointerDown(event: PointerEvent) {
		host?.focus();
		if (event.button !== 0) return;
		if (editorMode === 'simulate') return;
		if (hotCameraPlacement) {
			const pt = getWorldPoint(event);
			if (!pt) return;
			hotCameraDragStart = { x: pt.x, z: pt.y };
			if (controls) controls.enabled = false;
			onHotCameraDrag?.({ x: pt.x, z: pt.y, yaw_deg: activePreviewOverlay()?.yaw_deg ?? 0 });
			return;
		}
		// Check frustum click first
		const fHit = getFrustumHit(event);
		if (fHit) {
			onFrustumClick?.(fHit.vpId, fHit.headingId);
			return;
		}
		// addEdgeMode: must come before the generic object-select hit, otherwise the
		// node click is consumed by onObjectSelect and never reaches the edge logic.
		if (addEdgeMode) {
			const nid = _hitGraphNodeId(event);
			if (nid) {
				if (!edgeFirstNodeId) {
					edgeFirstNodeId = nid;
					onEdgeFirstNode?.(nid);
				} else if (nid !== edgeFirstNodeId) {
					const src = edgeFirstNodeId;
					edgeFirstNodeId = '';
					if (edgeGhostMesh) { hoverGroup?.remove(edgeGhostMesh); edgeGhostMesh = null; }
					onEdgeSecondNode?.(src, nid);
				}
			}
			// Always swallow click while in add-edge mode to avoid selecting objects.
			return;
		}
		// Other floor-driven modes also take priority: clicks on the floor (or even
		// on a node sphere — we ignore the hit and use the world point) should drive
		// the mode, not change selection.
		if (removeNodeMode) {
			// Click a node to toggle it in/out of the removal set; drag empty floor to box-select.
			const nid = _hitGraphNodeId(event);
			if (nid) { onNodeToggle?.(nid); return; }
			const pt = getWorldPoint(event);
			if (!pt) return;
			regionStart = { x: pt.x, y: pt.y };
			regionEnd = { x: pt.x, y: pt.y };
			if (controls) controls.enabled = false;
			return;
		}
		if (paintMode !== 'none' || regionSelectMode || addNodeMode) {
			const pt = getWorldPoint(event);
			if (!pt) return;
			if (paintMode !== 'none') {
				paintActive = true;
				paintStrokeBuffer = [[pt.x, pt.y]];
				if (controls) controls.enabled = false;
				return;
			}
			if (regionSelectMode) {
				regionStart = { x: pt.x, y: pt.y };
				regionEnd = { x: pt.x, y: pt.y };
				if (controls) controls.enabled = false;
				return;
			}
			if (addNodeMode) {
				onAddNodeClick?.(pt.x, pt.y);
				return;
			}
		}
		// Default: object selection (cycle-select through overlapping objects).
		const hit = getClickPick(event);
		if (hit?.handle && placementTool === 'select') {
			onObjectSelect?.(hit.id);
			if (hit.type === 'object_gizmo' && objectTransformMode && ['move_xz', 'move_y', 'yaw'].includes(String(hit.handle))) {
				startObjectTransform(hit.id, hit.handle as ObjectGizmoHandle, event);
				return;
			}
			if (hit.handle === 'line_start' || hit.handle === 'line_end') {
				dragHandle = { id: hit.id, handle: hit.handle };
				if (controls) controls.enabled = false;
			} else if (typeof hit.handle === 'string' && hit.handle.startsWith('rect_')) {
				dragHandle = { id: hit.id, handle: hit.handle as RectHandle };
				if (controls) controls.enabled = false;
			}
			return;
		}
		if (hit && placementTool === 'select') {
			onObjectSelect?.(hit.id);
			if (objectTransformMode && hit.id === selectedId && hit.type === 'object' && pointObjectById(hit.id)) {
				startObjectTransform(hit.id, 'move_xz', event);
			}
			return;
		}
		const pt = getWorldPoint(event);
		if (!pt) return;
		onGroundPointerDown?.(pt, event.shiftKey, surfaceSnapForPoint(pt));
	}

	let edgeFirstNodeId = '';
	let edgeGhostMesh: any = null;
	let hotCameraDragStart: { x: number; z: number } | null = null;
	let paintActive = false;
	let paintStrokeBuffer: Array<[number, number]> = [];
	let paintCursorMesh: any = null;
	let regionStart: { x: number; y: number } | null = null;
	let regionEnd: { x: number; y: number } | null = null;
	let regionPreviewMesh: any = null;

	function _hitGraphNodeId(event: PointerEvent | MouseEvent): string | null {
		if (!renderer || !camera || !selectableObjects.length) return null;
		const rect = renderer.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((event.clientX - rect.left) / rect.width) * 2 - 1,
			-((event.clientY - rect.top) / rect.height) * 2 + 1
		);
		raycaster.setFromCamera(ndc, camera);
		const hits = raycaster.intersectObjects(selectableObjects, true);
		for (const h of hits) {
			let o: any = h.object;
			while (o && !o.userData?.id) o = o.parent;
			if (o?.userData?.itemType === 'node' && o.userData.id) return String(o.userData.id);
		}
		return null;
	}

	function onPointerMove(event: PointerEvent) {
		if (editorMode === 'simulate') return;
		if (hotCameraDragStart) {
			const pt = getWorldPoint(event);
			if (!pt) return;
			const dx = pt.x - hotCameraDragStart.x;
			const dz = pt.y - hotCameraDragStart.z;
			const yaw = Math.hypot(dx, dz) < 0.03
				? (activePreviewOverlay()?.yaw_deg ?? 0)
				: (Math.atan2(-dx, -dz) * 180) / Math.PI;
			onHotCameraDrag?.({ x: hotCameraDragStart.x, z: hotCameraDragStart.z, yaw_deg: yaw });
			return;
		}
		if (objectDrag) {
			updateObjectTransform(event);
			return;
		}

		// Frustum hover cursor
		if (getFrustumHit(event)) {
			if (renderer) renderer.domElement.style.cursor = 'pointer';
		}

		// Hover highlight
		const hit = getHitObject(event);
		const newHoveredId = hit?.id ?? '';
		if (newHoveredId !== hoveredObjectId) {
			hoveredObjectId = newHoveredId;
			if (hoverGroup) clearGroup(hoverGroup);
			if (renderer) renderer.domElement.style.cursor = newHoveredId ? 'pointer' : '';
			if (newHoveredId && hoverGroup) {
				const hitMesh = selectableObjects.find(o => {
					let n: any = o;
					while (n && !n.userData?.id) n = n.parent;
					return n?.userData?.id === newHoveredId;
				});
				if (hitMesh) {
					const box = new THREE.Box3().setFromObject(hitMesh);
					const size = new THREE.Vector3();
					const center = new THREE.Vector3();
					box.getSize(size);
					box.getCenter(center);
					if (size.x > 0 && Number.isFinite(size.x)) {
						const geo = new THREE.BoxGeometry(size.x + 0.05, size.y + 0.05, size.z + 0.05);
						const edges = new THREE.LineSegments(
							new THREE.EdgesGeometry(geo),
							new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.9 })
						);
						edges.position.copy(center);
						hoverGroup.add(edges);
					}
				}
			}
		}

		const pt = getWorldPoint(event);
		if (pt && dragHandle) {
			if (dragHandle.handle === 'line_start' || dragHandle.handle === 'line_end') {
				onHandleDrag?.(dragHandle.id, dragHandle.handle, pt, event.shiftKey);
			} else {
				onRegionResize?.(dragHandle.id, dragHandle.handle, pt, event.shiftKey);
			}
			return;
		}
		// Paint mode: show brush ring at cursor + sample positions while pressed.
		if (paintMode !== 'none' && hoverGroup) {
			if (pt) _updatePaintCursor(pt.x, pt.y);
			if (paintActive && pt) {
				const last = paintStrokeBuffer[paintStrokeBuffer.length - 1];
				const minDist = Math.max(0.05, paintRadiusM * 0.4);
				if (!last || Math.hypot(pt.x - last[0], pt.y - last[1]) >= minDist) {
					paintStrokeBuffer.push([pt.x, pt.y]);
				}
			}
		}
		if ((regionSelectMode || removeNodeMode) && regionStart && pt) {
			regionEnd = { x: pt.x, y: pt.y };
			_updateRegionPreview();
		}
		// Add-edge ghost line from source to cursor (or hovered node).
		if (addEdgeMode && edgeFirstNodeId && pt) {
			const hoverNid = _hitGraphNodeId(event);
			_updateEdgeGhost(edgeFirstNodeId, hoverNid, pt.x, pt.y);
		}
		if (pt) onGroundPointerMove?.(pt, event.shiftKey);
	}

	function _updateEdgeGhost(sourceId: string, hoverNodeId: string | null, cx: number, cz: number) {
		if (!hoverGroup) return;
		if (edgeGhostMesh) {
			hoverGroup.remove(edgeGhostMesh);
			(edgeGhostMesh.geometry as any)?.dispose?.();
			(edgeGhostMesh.material as any)?.dispose?.();
			edgeGhostMesh = null;
		}
		const src = graphNodes.find((n: any) => n.node_id === sourceId);
		if (!src) return;
		const sx = src.position?.[0] ?? 0;
		const sz = src.position?.[1] ?? 0;
		let ex = cx, ez = cz;
		let endIsNode = false;
		if (hoverNodeId && hoverNodeId !== sourceId) {
			const tgt = graphNodes.find((n: any) => n.node_id === hoverNodeId);
			if (tgt) {
				ex = tgt.position?.[0] ?? cx;
				ez = tgt.position?.[1] ?? cz;
				endIsNode = true;
			}
		}
		const dist = Math.hypot(ex - sx, ez - sz);
		// Use the mode's ghost color for a valid endpoint (green=add, purple=inspect,
		// red=remove); over-length always reds out as an "auto-build won't link this"
		// affordance (only meaningful for add mode — remove ignores length).
		const color = endIsNode
			? (dist <= addEdgeMaxLengthM ? addEdgeGhostColor : 0xef4444)
			: addEdgeGhostColor;
		const pts = [new THREE.Vector3(sx, 0.05, sz), new THREE.Vector3(ex, 0.05, ez)];
		const line = new THREE.Line(
			new THREE.BufferGeometry().setFromPoints(pts),
			new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.85 })
		);
		line.userData = { itemType: 'edge_ghost' };
		hoverGroup.add(line);
		edgeGhostMesh = line;
	}

	function _updatePaintCursor(x: number, z: number) {
		if (!hoverGroup) return;
		if (paintCursorMesh) {
			hoverGroup.remove(paintCursorMesh);
			(paintCursorMesh.geometry as any)?.dispose?.();
			(paintCursorMesh.material as any)?.dispose?.();
			paintCursorMesh = null;
		}
		const color = paintMode === 'walkable' ? 0x22c55e : paintMode === 'blocked' ? 0xef4444 : 0x94a3b8;
		const ring = new THREE.Mesh(
			new THREE.RingGeometry(paintRadiusM * 0.92, paintRadiusM, 32),
			new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.7, side: THREE.DoubleSide, depthWrite: false })
		);
		ring.rotation.x = -Math.PI / 2;
		ring.position.set(x, 0.015, z);
		ring.userData = { itemType: 'paint_cursor' };
		hoverGroup.add(ring);
		paintCursorMesh = ring;
	}

	function _updateRegionPreview() {
		if (!hoverGroup || !regionStart || !regionEnd) return;
		if (regionPreviewMesh) {
			hoverGroup.remove(regionPreviewMesh);
			(regionPreviewMesh.geometry as any)?.dispose?.();
			(regionPreviewMesh.material as any)?.dispose?.();
			regionPreviewMesh = null;
		}
		const minX = Math.min(regionStart.x, regionEnd.x);
		const maxX = Math.max(regionStart.x, regionEnd.x);
		const minZ = Math.min(regionStart.y, regionEnd.y);
		const maxZ = Math.max(regionStart.y, regionEnd.y);
		const w = Math.max(0.05, maxX - minX);
		const d = Math.max(0.05, maxZ - minZ);
		const geo = new THREE.BoxGeometry(w, 0.005, d);
		const mesh = new THREE.LineSegments(
			new THREE.EdgesGeometry(geo),
			new THREE.LineBasicMaterial({ color: 0xa855f7, transparent: true, opacity: 0.95 })
		);
		mesh.position.set((minX + maxX) / 2, 0.02, (minZ + maxZ) / 2);
		mesh.userData = { itemType: 'region_preview' };
		hoverGroup.add(mesh);
		regionPreviewMesh = mesh;
	}

	function onPointerUp(event: PointerEvent) {
		if (event.button !== 0) return;
		if (editorMode === 'simulate') return;
		if (hotCameraDragStart) {
			const pt = getWorldPoint(event);
			const start = hotCameraDragStart;
			hotCameraDragStart = null;
			if (controls) controls.enabled = true;
			if (pt) {
				const dx = pt.x - start.x;
				const dz = pt.y - start.z;
				const yaw = Math.hypot(dx, dz) < 0.03
					? (activePreviewOverlay()?.yaw_deg ?? 0)
					: (Math.atan2(-dx, -dz) * 180) / Math.PI;
				onHotCameraDrag?.({ x: start.x, z: start.z, yaw_deg: yaw, final: true });
			}
			return;
		}
		if (objectDrag) {
			finishObjectTransform();
			return;
		}
		if (dragHandle) {
			dragHandle = null;
			if (controls) controls.enabled = true;
			return;
		}
		if (paintActive) {
			paintActive = false;
			if (controls) controls.enabled = true;
			if (paintStrokeBuffer.length > 0) {
				onPaintStroke?.(paintStrokeBuffer.slice());
			}
			paintStrokeBuffer = [];
			return;
		}
		if ((regionSelectMode || removeNodeMode) && regionStart && regionEnd) {
			const a = regionStart, b = regionEnd;
			regionStart = null;
			regionEnd = null;
			if (regionPreviewMesh) {
				hoverGroup?.remove(regionPreviewMesh);
				(regionPreviewMesh.geometry as any)?.dispose?.();
				(regionPreviewMesh.material as any)?.dispose?.();
				regionPreviewMesh = null;
			}
			if (controls) controls.enabled = true;
			const minX = Math.min(a.x, b.x), maxX = Math.max(a.x, b.x);
			const minZ = Math.min(a.y, b.y), maxZ = Math.max(a.y, b.y);
			if (Math.abs(maxX - minX) > 0.1 && Math.abs(maxZ - minZ) > 0.1) {
				if (removeNodeMode) {
					const ids = graphNodes
						.filter((node: any) => {
							const x = node.position?.[0] ?? 0, z = node.position?.[1] ?? 0;
							return x >= minX && x <= maxX && z >= minZ && z <= maxZ;
						})
						.map((node: any) => node.node_id);
					if (ids.length) onNodesBoxSelect?.(ids);
				} else {
					onRegionSelected?.([minX, minZ, maxX, maxZ]);
				}
			}
			return;
		}
		const pt = getWorldPoint(event);
		if (pt) onGroundPointerUp?.(pt, event.shiftKey);
	}

	function onMouseDown(event: MouseEvent) {
		host?.focus();
		if (event.button === 2) rightDragStartPos = { x: event.clientX, y: event.clientY };
	}

	function onContextMenu(event: MouseEvent) {
		event.preventDefault();
		if (rightDragStartPos) {
			const dist = Math.hypot(event.clientX - rightDragStartPos.x, event.clientY - rightDragStartPos.y);
			rightDragStartPos = null;
			if (dist > 8) return;
		}
		const hit = getHitObject(event);
		if (hit && hit.type !== 'object_gizmo') onObjectContextMenu?.(event, hit.id, hit.type);
	}

	function onMouseLeave() {
		onGroundPointerMove?.({ x: -1, y: -1 }, false);
		hoveredObjectId = '';
		if (hoverGroup) clearGroup(hoverGroup);
		if (renderer) renderer.domElement.style.cursor = '';
	}

	function onKeyDown(event: KeyboardEvent) {
		setMovementKey(event, true);
	}

	function onKeyUp(event: KeyboardEvent) {
		setMovementKey(event, false);
	}

	async function loadEditorGeometry() {
		const key = `${projectId}:${sceneId}:${geometryKey}`;
		if (!projectId || !sceneId || key === loadedGeometryKey) return;
		loadedGeometryKey = key;
		try {
			editorGeometryStatus = 'Loading USD proxy geometry...';
			onStatus?.(editorGeometryStatus);
			const payload = await getOpticalNavEditorGeometry(projectId, sceneId);
			editorGeometry = payload;
			if (payload?.status === 'ready') {
				editorGeometryStatus = payload.cached ? 'USD geometry ready (cached proxy boxes)' : 'USD geometry ready (proxy boxes)';
			} else {
				const reason = String(payload?.reason ?? '');
				if (reason.includes('usd_ref missing')) {
					editorGeometryStatus = 'No USD attached; using empty editor floor';
				} else if (reason.includes('does not exist')) {
					editorGeometryStatus = 'USD path missing; using empty editor floor';
				} else if (reason.toLowerCase().includes('pxr') || reason.toLowerCase().includes('unavailable')) {
					editorGeometryStatus = 'USD extractor unavailable; using empty editor floor';
				} else {
					editorGeometryStatus = 'USD unavailable; using empty editor floor';
				}
			}
			onStatus?.(editorGeometryStatus);
		} catch (error) {
			editorGeometry = null;
			editorGeometryStatus = error instanceof Error ? `USD unavailable: ${error.message}` : 'USD unavailable: fallback empty floor';
			onStatus?.(editorGeometryStatus);
		}
	}

	// ─── Svelte 5 reactivity ──────────────────────────────────────────────
	onMount(() => {
		ensureThree();
			return () => {
				if (animationFrame) cancelAnimationFrame(animationFrame);
				if (_xmlNativePreviewRefreshTimer !== null) {
					clearTimeout(_xmlNativePreviewRefreshTimer);
					_xmlNativePreviewRefreshTimer = null;
				}
				clearMovementKeys();
				resizeObserver?.disconnect();
			controls?.dispose();
			if (baseGroup) disposeNode(baseGroup);
			if (rootGroup) disposeNode(rootGroup);
			if (ghostGroup) disposeNode(ghostGroup);
			if (robotGroup) disposeNode(robotGroup);
			renderer?.forceContextLoss();
			renderer?.dispose();
			renderer?.domElement?.remove();
			renderer = null;
			scene3D = null;
			camera = null;
			controls = null;
			baseGroup = null;
			rootGroup = null;
			ghostGroup = null;
			robotGroup = null;
		};
	});


	$effect(() => {
		editorGeometry;
		editorGeometryStatus;
		mapBounds;
		authoringObjects;
		authoringRegions;
		footprintInflationM;
		wallHeight;
		eyeHeightM;
		showGuides;
		selectedObjectGuide;
		walkabilityOverlayUrl;
		walkabilityOverlayBbox;
		roomShell;
		showRoomShell;
		traversableOverlayUrl;
		traversableOverlayBbox;
		if (renderer) addEnvironment();
	});

	// Max concurrent /prim-mesh requests. The first request in a batch causes the
	// server to open the USD stage; subsequent requests in the same batch benefit
	// from the cached stage. Keeping this low avoids hammering the daemon with
	// hundreds of simultaneous Stage.Open calls before the cache is warm.
	const PRIM_MESH_CONCURRENCY = 6;
	let primMeshActiveLoads = $state(0);

	async function loadPrimMesh(sourcePath: string, usdRef: string) {
		const key = primMeshKey(sourcePath, usdRef);
		if (primMeshPending.has(key) || primMeshCache.has(key)) return;
		if (!projectId || !sceneId) return;
		const memoryPayload = getCachedPrimMeshPayload(key);
		if (memoryPayload !== undefined) {
			primMeshCache.set(key, geometryFromPrimPayload(memoryPayload));
			primMeshCacheVersion += 1;
			return;
		}
		// Concurrency gate: skip this call if too many loads are in-flight.
		// The $effect that calls us re-runs on each primMeshCacheVersion bump,
		// so deferred items will be picked up as slots free up.
		if (primMeshActiveLoads >= PRIM_MESH_CONCURRENCY) return;
		primMeshActiveLoads += 1;
		primMeshPending.add(key);
		try {
			const data = await loadCachedPrimMeshPayload(projectId, sceneId, sourcePath, usdRef || undefined);
			primMeshCache.set(key, geometryFromPrimPayload(data));
		} catch {
			primMeshCache.set(key, null);
		} finally {
			primMeshPending.delete(key);
			primMeshActiveLoads -= 1;
			primMeshCacheVersion += 1; // trigger re-render + continues queued loads
		}
	}

	$effect(() => {
		// Preload mesh for the currently selected palette asset
		const key = preloadSourcePath ? primMeshKey(preloadSourcePath, preloadUsdRef) : '';
		if (preloadSourcePath && !primMeshCache.has(key) && !primMeshPending.has(key)) {
			void loadPrimMesh(preloadSourcePath, preloadUsdRef);
		}
	});

	$effect(() => {
		// Queue mesh loads for USD objects not yet cached (concurrency-limited).
		// Re-runs on primMeshCacheVersion so each completed load drains the queue.
		primMeshCacheVersion;
		for (const obj of authoringObjects) {
			const sourcePath = effectiveAssetSourcePath(obj);
			const usdRef = usdRefFromSourceRef(obj.source_ref);
			const key = sourcePath ? primMeshKey(sourcePath, usdRef) : '';
			if (!sourcePath || primMeshCache.has(key) || primMeshPending.has(key)) continue;
			if (primMeshActiveLoads >= PRIM_MESH_CONCURRENCY) break; // wait for slots to free
			void loadPrimMesh(sourcePath, usdRef);
		}
	});

	$effect(() => {
		authoringObjects;
		authoringRegions;
		perturbationObjects;
		perturbationEnabled;
		graphNodes;
		graphEdges;
		selectedId;
		removeSelection; // re-color node spheres when the removal set changes
		removeNodeMode;
		visibleLayers;
		highlightedPath;
		allEpisodePaths;
		customSensorNodes;
		primMeshCacheVersion; // re-render when new meshes arrive
		_xmlNativePreviewVersion; // PR2: re-render when async OBJ load resolves
		xmlNativePreviewEnabled;
		xmlSceneIndex;
		objectTransformMode;
		surfaceSnapEnabled;
		gridSnapEnabled;
		gridSizeM;
		angleSnapDeg;
		if (renderer) rebuildScene();
	});

	$effect(() => {
		draftGhost;
		draftPoint;
		editorMode;
		surfaceSnapEnabled;
		primMeshCacheVersion; // refresh ghost when mesh arrives in cache
		if (renderer) updateGhost();
	});

	$effect(() => {
		robotPos;
		editorMode;
		if (renderer) updateRobot();
	});

	function nearestHeadingDeg(viewYawDeg: number, degs: number[]): number {
		if (!degs.length) return 0;
		const norm = (a: number) => ((a % 360) + 360) % 360;
		const diff = (a: number, b: number) => { const d = Math.abs(norm(a) - norm(b)); return Math.min(d, 360 - d); };
		return degs.reduce((best, h) => diff(h, viewYawDeg) < diff(best, viewYawDeg) ? h : best);
	}

	function getCameraYawDeg(): number {
		if (!camera) return 0;
		const dir = new THREE.Vector3();
		camera.getWorldDirection(dir);
		// Camera convention: yaw=0 → fwd=(-sin0,0,-cos0)=(0,0,-1).
		// getWorldDirection gives orbit camera's look direction (≈+Z when looking into scene).
		// To select the heading whose image faces the orbit camera, add 180° so orbit-yaw=0
		// selects heading yaw=180° (fwd=+Z), whose image plane BackSide faces the orbit camera.
		return ((Math.atan2(dir.x, dir.z) * 180 / Math.PI) + 360 + 180) % 360;
	}

	function buildFrustumForHeading(
		nx: number, nz: number, headingId: string, yawDeg: number, hasModality: boolean,
		vpId: string, modality: string, sensorId = '', loadImage = true,
	) {
		// Cache key includes loadImage so an out-of-view ray-only stub can be
		// replaced by a full image-bearing frustum when the camera moves close.
		const key = `${vpId}/${headingId}/${modality}/${sensorId || '_'}/${hasModality && loadImage ? 'img' : 'ray'}`;
		// Reuse existing group if already built (avoids texture reload on view-aligned updates)
		if (frustumHeadingMap.has(key)) {
			const existing = frustumHeadingMap.get(key);
			frustumGroup.add(existing);
			if (hasModality && loadImage) frustumSelectables.push(...existing.children.filter((c: any) => c.isMesh && c.userData.frustum));
			return;
		}

		const camY = cameraHeight;

		const yaw = (yawDeg * Math.PI) / 180;
		const origin = new THREE.Vector3(nx, camY, nz);
		const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));

		const group = new THREE.Group();
		group.userData = { vpId, headingId, yawDeg };

		if (!hasModality || !loadImage) {
			// Short direction ray — either no render exists OR the vp is out of
			// view / too far. The latter case lets the topology stay visible
			// without consuming a connection slot for the image fetch.
			const displayDist = 0.5;
			const tip = origin.clone().addScaledVector(fwd, displayDist * 0.6);
			const rayGeo = new THREE.BufferGeometry().setFromPoints([origin, tip]);
			const rayColor = !hasModality ? 0x64748b : 0x3b82f6;
			group.add(new THREE.LineSegments(rayGeo, new THREE.LineBasicMaterial({ color: rayColor, transparent: true, opacity: 0.5 })));
		} else {
			const url = opticalNavObservationModalityUrl(projectId, sceneId, vpId, headingId, modality, sensorId);
			group.add(buildCameraFrustumGroup({
				x: nx,
				z: nz,
				yawDeg,
				height: camY,
				hasImage: true,
				imageUrl: url,
				vpId,
				headingId,
				intrinsics: frustumIntrinsics,
			}));
		}

		frustumHeadingMap.set(key, group);
		frustumGroup.add(group);
	}

	function updateFrustumVisibility() {
		if (!frustumGroup || frustumMode !== 'view-aligned') return;
		const viewYaw = getCameraYawDeg();

		// Group cached heading groups by vpId, but only consider current modality's entries.
		// Cache key shape: `${vpId}/${headingId}/${modality}/${sensorId|_}/${img|ray}`
		const byVp = new Map<string, Array<{ key: string; yawDeg: number; group: any }>>();
		for (const [key, group] of frustumHeadingMap.entries()) {
			const parts = key.split('/');
			const mod = parts[2];
			if (mod !== frustumModality) continue;
			const vpId = parts[0];
			if (!byVp.has(vpId)) byVp.set(vpId, []);
			byVp.get(vpId)!.push({ key, yawDeg: group.userData.yawDeg as number, group });
		}

		for (const entries of byVp.values()) {
			const nearestDeg = nearestHeadingDeg(viewYaw, entries.map(e => e.yawDeg));
			for (const { yawDeg, group } of entries) {
				group.visible = yawDeg === nearestDeg;
			}
		}
	}

	function updateFrustums() {
		if (!frustumGroup) return;
		// Detach heading groups from frustumGroup but keep them in the map so textures survive.
		// Rings and roses (non-heading children) are disposed.
		for (const child of [...frustumGroup.children]) {
			const isHeadingGroup = child.userData?.headingId !== undefined;
			frustumGroup.remove(child);
			if (!isHeadingGroup) {
				// Ring / rose geometry — dispose
				if ((child as any).geometry) (child as any).geometry.dispose();
				const mat = (child as any).material;
				if (mat) mat.dispose();
			}
		}
		// Dispose old heading groups (texture cache owns textures, so only geometry/mat)
		for (const [, group] of frustumHeadingMap.entries()) {
			for (const child of [...group.children]) {
				group.remove(child);
				if ((child as any).geometry) (child as any).geometry.dispose();
				const mat = (child as any).material;
				if (mat) mat.dispose(); // intentionally NOT disposing mat.map
			}
		}
		frustumHeadingMap.clear();
		frustumSelectables = [];
		for (const overlay of previewOverlayList()) {
			const group = buildCameraFrustumGroup({
				x: Number(overlay.x) || 0,
				z: Number(overlay.z) || 0,
				yawDeg: Number(overlay.yaw_deg) || 0,
				height: Number(overlay.height_m ?? cameraHeight) || cameraHeight,
				hasImage: Boolean(overlay.imageUrl),
				imageUrl: overlay.imageUrl,
				vpId: overlay.vpId,
				headingId: overlay.headingId,
				intrinsics: overlay,
				color: overlay.active ? 0xf59e0b : overlay.imageUrl ? 0x38bdf8 : 0x94a3b8,
				opacity: overlay.active ? 0.98 : 0.7,
			});
			group.userData = { previewCamera: true, id: overlay.id };
			frustumGroup.add(group);
		}
		const scan = observationScan;
		if (!scan?.viewpoints) return;

		const baseY = 0.04;
		const roseR = 0.18;

		// Build node position + yaw lookup maps
		const nodePosMap = new Map<string, [number, number]>();
		const yawMap = new Map<string, Map<string, number>>(); // vpId → headingId → yaw_deg
		for (const node of graphNodes) {
			if (!node.node_id || !node.position) continue;
			nodePosMap.set(node.node_id, node.position);
			if (node.headings) {
				const hm = new Map<string, number>();
				for (const h of node.headings) hm.set(h.heading_id, Number(h.yaw_deg ?? 0));
				yawMap.set(node.node_id, hm);
			}
		}
		// Custom sensor nodes: backend assigns "custom_0", "custom_1", ... by index order.
		for (let i = 0; i < customSensorNodes.length; i++) {
			const csn = customSensorNodes[i];
			const key = `custom_${i}`;
			nodePosMap.set(key, [csn.x, csn.z]);
			yawMap.set(key, new Map([['h0', csn.headingDeg]]));
		}

		const viewYaw = frustumMode === 'view-aligned' ? getCameraYawDeg() : 0;
		const activeSensorId = String(frustumSensorId || '');
		// Refresh the cached view frustum once per updateFrustums call so each
		// vp's viewport visibility check is O(1) and consistent within the pass.
		_refreshViewFrustum();

		function hasHeadingModality(hdata: any, modalityKey: string): boolean {
			const sensors = hdata?.sensors;
			if (activeSensorId && sensors && typeof sensors === 'object') {
				return Boolean(sensors[activeSensorId]?.[modalityKey]);
			}
			if (activeSensorId && sensors && typeof sensors === 'object') {
				return false;
			}
			return Boolean(hdata?.[modalityKey]);
		}

		for (const [vpId, vpData] of Object.entries(scan.viewpoints as Record<string, any>)) {
			const pos = nodePosMap.get(vpId);
			if (!pos) continue;
			const [nx, nz] = pos;
			const headings = vpData.headings as Record<string, any>;
			if (!headings) continue;

			// Completion ring (per active modality)
			const totalH = Object.keys(headings).length;
			const modalityKey = `has_${frustumModality}`;
			const doneH = Object.values(headings).filter((h: any) => hasHeadingModality(h, modalityKey)).length;
			if (totalH > 0) {
				const ringColor = doneH === totalH ? 0x22c55e : doneH > 0 ? 0xfbbf24 : 0xcbd5e1;
				const ring = new THREE.Mesh(
					new THREE.RingGeometry(0.11, 0.15, 24),
					new THREE.MeshBasicMaterial({ color: ringColor, side: THREE.DoubleSide, transparent: true, opacity: 0.85 })
				);
				ring.rotation.x = -Math.PI / 2;
				ring.position.set(nx, baseY, nz);
				frustumGroup.add(ring);
			}

			// Sensor rose: small radial segments per heading showing render status (per active modality)
			for (const [headingId, hdata] of Object.entries(headings)) {
				const hYawDeg = yawMap.get(vpId)?.get(headingId) ?? parseInt(headingId.replace('h_', '')) ?? 0;
				const hYaw = (hYawDeg * Math.PI) / 180;
				const hasModality = hasHeadingModality(hdata, modalityKey);
				const segColor = hasModality ? 0x3b82f6 : 0x94a3b8;
				// Camera forward: fwd = (-sin(yaw), 0, -cos(yaw)) — same direction as frustum
				const roseGeo = new THREE.BufferGeometry().setFromPoints([
					new THREE.Vector3(nx, baseY + 0.01, nz),
					new THREE.Vector3(nx - Math.sin(hYaw) * roseR, baseY + 0.01, nz - Math.cos(hYaw) * roseR)
				]);
				frustumGroup.add(new THREE.LineSegments(roseGeo, new THREE.LineBasicMaterial({ color: segColor, transparent: true, opacity: hasModality ? 0.8 : 0.4 })));
			}

			if (frustumMode === 'none') continue;

			const hdEntries = Object.entries(headings);
			const hdDegs = hdEntries.map(([hid]) => yawMap.get(vpId)?.get(hid) ?? parseInt(hid.replace('h_', '')) ?? 0);

			// One viewport check per vp — every heading at this vp shares it.
			// 'selected' mode is always loaded (user explicitly pinned it).
			const loadImage = frustumMode === 'selected'
				? (vpId === selectedId)
				: _vpShouldLoadImage(nx, cameraHeight, nz);
			if (frustumMode === 'selected') {
				if (vpId !== selectedId) continue;
				for (let i = 0; i < hdEntries.length; i++) {
					const [headingId, hdata] = hdEntries[i];
					buildFrustumForHeading(nx, nz, headingId, hdDegs[i], hasHeadingModality(hdata, modalityKey), vpId, frustumModality, activeSensorId, loadImage);
				}
			} else {
				// view-aligned: build ALL headings but only show the nearest one.
				// This populates frustumHeadingMap so camera rotation can toggle .visible
				// without any geometry/texture operations (no flicker).
				const nearestDeg = nearestHeadingDeg(viewYaw, hdDegs);
				for (let i = 0; i < hdEntries.length; i++) {
					const [headingId, hdata] = hdEntries[i];
					buildFrustumForHeading(nx, nz, headingId, hdDegs[i], hasHeadingModality(hdata, modalityKey), vpId, frustumModality, activeSensorId, loadImage);
					const keySuffix = hasHeadingModality(hdata, modalityKey) && loadImage ? 'img' : 'ray';
					const grp = frustumHeadingMap.get(`${vpId}/${headingId}/${frustumModality}/${activeSensorId || '_'}/${keySuffix}`);
					if (grp) grp.visible = (hdDegs[i] === nearestDeg);
				}
			}
		}
	}

	$effect(() => {
		observationScan;
		graphNodes;
		frustumMode;
		frustumModality;
		frustumSensorId;
		frustumIntrinsics;
		previewCameraOverlay;
		selectedId;
		if (renderer) updateFrustums();
	});
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions, a11y_no_noninteractive_tabindex -->
<div
	class="map3d-host"
	bind:this={host}
	onpointerdown={onPointerDown}
	onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onmousedown={onMouseDown}
		onkeydown={onKeyDown}
		onkeyup={onKeyUp}
		onblur={clearMovementKeys}
		oncontextmenu={onContextMenu}
	onmouseleave={onMouseLeave}
	role="application"
	tabindex="0"
	aria-label="3D map editor canvas"
>
	<div class="usd-status" class:warn={editorGeometry?.status !== 'ready'}>
		<span>{editorGeometry?.status === 'ready' ? 'USD geometry ready' : 'Fallback floor'}</span>
		<small>{editorGeometryStatus}</small>
	</div>
</div>

<style>
	.map3d-host {
		position: absolute;
		inset: 0;
		cursor: crosshair;
	}
	.map3d-host :global(canvas) {
		display: block;
		width: 100% !important;
		height: 100% !important;
	}
	.usd-status {
		position: absolute;
		left: 16px;
		bottom: 16px;
		z-index: 2;
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-width: min(520px, calc(100% - 32px));
		padding: 8px 10px;
		border: 1px solid rgba(37, 99, 235, 0.18);
		border-radius: 10px;
		background: rgba(255, 255, 255, 0.86);
		backdrop-filter: blur(10px);
		color: #1e40af;
		font-size: 12px;
		pointer-events: none;
	}
	.usd-status.warn {
		border-color: rgba(245, 158, 11, 0.28);
		color: #92400e;
	}
	.usd-status span {
		font-weight: 800;
	}
	.usd-status small {
		color: inherit;
		opacity: 0.76;
	}
</style>
