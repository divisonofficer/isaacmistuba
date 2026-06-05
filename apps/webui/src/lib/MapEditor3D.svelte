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

	type GhostGeom =
		| { type: 'line'; x1: number; y1: number; x2: number; y2: number; valid: boolean }
		| { type: 'rect'; minX: number; minY: number; maxX: number; maxY: number; valid: boolean }
		| { type: 'point'; x: number; y: number; valid: boolean; sourcePath?: string; assetCat?: string; normalizedYMin?: number };

	type VisibleLayers = {
		objects: boolean;
		traversable: boolean;
		goals: boolean;
		hazards: boolean;
		graphNodes: boolean;
		graphEdges: boolean;
		usdBackground?: boolean;
	};

	let {
		projectId = '',
		sceneId = '',
		geometryKey = '',
		authoringObjects = [],
		authoringRegions = [],
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
		onStatus,
		observationScan = null,
		onFrustumClick,
		frustumMode = 'view-aligned' as 'none' | 'view-aligned' | 'selected',
		frustumModality = 'rgb',
		frustumSensorId = '',
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
		roomShell = null as { wall_height_m: number; wall_thickness_m: number; bounds: number[]; shapes: Array<{ role: string; center: [number, number, number]; size: [number, number, number] }> } | null,
		showRoomShell = true,
		graphComponents = null as Record<string, number> | null,
		traversableOverlayUrl = null as string | null,
		traversableOverlayBbox = null as [number, number, number, number] | null,
		addEdgeGhostColor = 0x22c55e,
		addEdgeMaxLengthM = 1.5
	}: {
		projectId?: string;
		sceneId?: string;
		geometryKey?: string;
		authoringObjects: any[];
		authoringRegions: any[];
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
		onGroundPointerDown?: (pt: { x: number; y: number }, shiftKey: boolean) => void;
		onGroundPointerMove?: (pt: { x: number; y: number }, shiftKey: boolean) => void;
		onGroundPointerUp?: (pt: { x: number; y: number }, shiftKey: boolean) => void;
		onObjectSelect?: (id: string) => void;
		onObjectContextMenu?: (event: MouseEvent, id: string, type: 'object' | 'region') => void;
		onHandleDrag?: (id: string, handle: 'line_start' | 'line_end', pt: { x: number; y: number }, shiftKey: boolean) => void;
		onStatus?: (message: string) => void;
		observationScan?: any;
		onFrustumClick?: (vpId: string, headingId: string) => void;
		frustumMode?: 'none' | 'view-aligned' | 'selected';
		frustumModality?: string;
		frustumSensorId?: string;
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
		roomShell?: { wall_height_m: number; wall_thickness_m: number; bounds: number[]; shapes: Array<{ role: string; center: [number, number, number]; size: [number, number, number] }> } | null;
		showRoomShell?: boolean;
		graphComponents?: Record<string, number> | null;
		traversableOverlayUrl?: string | null;
		traversableOverlayBbox?: [number, number, number, number] | null;
		addEdgeGhostColor?: number;
		addEdgeMaxLengthM?: number;
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
	let dragHandle: { id: string; handle: 'line_start' | 'line_end' } | null = null;
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

	function getHitObject(event: PointerEvent | MouseEvent): { id: string; type: 'object' | 'region'; handle?: 'line_start' | 'line_end' } | null {
		if (!renderer || !camera || !selectableObjects.length) return null;
		const rect = renderer.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((event.clientX - rect.left) / rect.width) * 2 - 1,
			-((event.clientY - rect.top) / rect.height) * 2 + 1
		);
		raycaster.setFromCamera(ndc, camera);
		const hits = raycaster.intersectObjects(selectableObjects, true);
		if (!hits.length) return null;
		let obj: any = hits[0].object;
		while (obj.parent && !obj.userData.id) obj = obj.parent;
		if (obj.userData.id) return { id: obj.userData.id as string, type: (obj.userData.itemType as 'object' | 'region') ?? 'object', handle: obj.userData.handle };
		return null;
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

	function clampAuthoringPoint(x: number, z: number): { x: number; y: number } {
		const bounds = editorGeometry?.bounds;
		const mn = bounds?.min ?? [0, 0, 0];
		const mx = bounds?.max ?? [mapBounds?.w ?? 6, 0, mapBounds?.h ?? 4];
		return {
			x: Math.max(Number(mn[0] ?? 0), Math.min(Number(mx[0] ?? 6), Number(x.toFixed(3)))),
			y: Math.max(Number(mn[2] ?? 0), Math.min(Number(mx[2] ?? 4), Number(z.toFixed(3))))
		};
	}

	function usdRefFromSourceRef(sourceRef: unknown): string {
		return typeof sourceRef === 'string' ? sourceRef.split('#')[0] : '';
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

	function buildPointObject(obj: any): any | null {
		const center = obj.geometry?.center;
		if (!center) return null;
		const [x, z] = center;
		const proxy = obj.metadata?.proxy_size;
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
			body.position.set(0, 0.07, 0);
			group.add(body);
			const cone = new THREE.Mesh(
				new THREE.ConeGeometry(0.04, 0.12, 4),
				new THREE.MeshStandardMaterial({ color: 0xf59e0b, roughness: 0.4 })
			);
			cone.rotation.x = -Math.PI / 2;
			cone.position.set(0, 0.07, 0.1);
			group.add(cone);
			return group;
		}
		if (!Array.isArray(proxy) && ['chair', 'table', 'plant'].includes(obj.type)) {
			buildBuiltInPointShape(obj, group);
		} else {
				const sourcePath: string | undefined = obj.metadata?.asset_source_path;
				const usdRef = usdRefFromSourceRef(obj.source_ref);
				const cachedGeo = sourcePath ? primMeshCache.get(primMeshKey(sourcePath, usdRef)) : undefined;
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
				const worldY: number = Number(obj.metadata?.normalized_y_min ?? 0);
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
				const worldY: number = Number(obj.metadata?.normalized_y_min ?? 0);
				addProxyBox(group, [sx, h, sz], [0, worldY + h / 2, 0], color);
			}
		}
		// Emitter halo: small yellow translucent sphere + ring to mark enabled light sources.
		if (obj.is_emitter) {
			const haloY = Number(obj.metadata?.normalized_y_min ?? 0) + 0.08;
			const halo = new THREE.Mesh(
				new THREE.SphereGeometry(0.18, 16, 12),
				new THREE.MeshBasicMaterial({ color: 0xfde047, transparent: true, opacity: 0.35, depthWrite: false })
			);
			halo.position.set(0, haloY, 0);
			halo.userData = { itemType: 'emitter_halo' };
			group.add(halo);
			const ring = new THREE.Mesh(
				new THREE.RingGeometry(0.22, 0.28, 24),
				new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.9, side: THREE.DoubleSide })
			);
			ring.rotation.x = -Math.PI / 2;
			ring.position.set(0, haloY - 0.06, 0);
			ring.userData = { itemType: 'emitter_halo' };
			group.add(ring);
		}
		return group;
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

		const floorGeo = new THREE.BoxGeometry(fw, 0.02, fh);
		const floorMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 1, metalness: 0, transparent: true, opacity: 0.92 });
		const floorMesh = new THREE.Mesh(floorGeo, floorMat);
		floorMesh.position.set(fcx, 0.001, fcz);
		floorMesh.userData = { floorTarget: true };
		baseGroup.add(floorMesh);
		floorTargets.push(floorMesh);

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
			for (const sh of roomShell.shapes) {
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
		selectableObjects = [];
		clearGroup(rootGroup);

		// Regions
		for (const region of authoringRegions) {
			if (!isRegionVisible(region.type)) continue;
			const mesh = buildRegion(region);
			if (!mesh) continue;
			rootGroup.add(mesh);
			selectableObjects.push(mesh);
			if (selectedId === region.id) addSelectionEdges(mesh.geometry, mesh.position.clone().setY(0.003), mesh.rotation.clone());
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
			for (const obj of authoringObjects) {
				let mesh: any = null;
				if (obj.geometry?.type === 'line') mesh = buildWall(obj);
				else if (obj.geometry?.type === 'point') mesh = buildPointObject(obj);
				if (!mesh) continue;
				rootGroup.add(mesh);
				selectableObjects.push(mesh);
				if (selectedId === obj.id) {
					if (mesh.geometry) addSelectionEdges(mesh.geometry, mesh.position.clone(), mesh.rotation.clone());
					else addSelectionBox(mesh);
					addLineHandles(obj);
				}
			}
		}

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
				const geo = new THREE.SphereGeometry(isSensor ? 0.09 : 0.06, 8, 8);
				const mat = new THREE.MeshBasicMaterial({
					color: isSensor ? 0xf59e0b : isHazard ? 0xf97316 : componentColor
				});
				const sphere = new THREE.Mesh(geo, mat);
				sphere.position.set(node.position?.[0] ?? 0, 0.06, node.position?.[1] ?? 0);
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
			if (cachedGeo) {
				const ghostMat = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.55, depthWrite: false });
				const mesh = new THREE.Mesh(cachedGeo, ghostMat);
				const box = new THREE.Box3().setFromBufferAttribute(cachedGeo.attributes.position as any);
				const ghostWorldY = (draftGhost as any).normalizedYMin ?? 0;
				mesh.position.set(draftGhost.x, ghostWorldY - box.min.y, draftGhost.y);
				ghostGroup.add(mesh);
			} else {
				const geo = new THREE.SphereGeometry(0.14, 10, 10);
				const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity });
				const sphere = new THREE.Mesh(geo, mat);
				sphere.position.set(draftGhost.x, 0.14, draftGhost.y);
				ghostGroup.add(sphere);
			}
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

	// ─── pointer events ───────────────────────────────────────────────────
	function getFrustumHit(event: PointerEvent | MouseEvent): { vpId: string; headingId: string } | null {
		if (!renderer || !camera || !frustumSelectables.length) return null;
		const rect = renderer.domElement.getBoundingClientRect();
		const ndc = new THREE.Vector2(
			((event.clientX - rect.left) / rect.width) * 2 - 1,
			-((event.clientY - rect.top) / rect.height) * 2 + 1
		);
		raycaster.setFromCamera(ndc, camera);
		const hits = raycaster.intersectObjects(frustumSelectables, false);
		if (!hits.length) return null;
		const ud = hits[0].object.userData;
		if (ud?.frustum && ud.vpId && ud.headingId) return { vpId: ud.vpId, headingId: ud.headingId };
		return null;
	}

	function onPointerDown(event: PointerEvent) {
		host?.focus();
		if (event.button !== 0) return;
		if (editorMode === 'simulate') return;
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
		// Default: object selection.
		const hit = getHitObject(event);
		if (hit?.handle && placementTool === 'select') {
			dragHandle = { id: hit.id, handle: hit.handle };
			if (controls) controls.enabled = false;
			onObjectSelect?.(hit.id);
			return;
		}
		if (hit && placementTool === 'select') {
			onObjectSelect?.(hit.id);
			return;
		}
		const pt = getWorldPoint(event);
		if (!pt) return;
		onGroundPointerDown?.(pt, event.shiftKey);
	}

	let edgeFirstNodeId = '';
	let edgeGhostMesh: any = null;
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
			onHandleDrag?.(dragHandle.id, dragHandle.handle, pt, event.shiftKey);
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
		if (regionSelectMode && regionStart && pt) {
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
		const color = endIsNode
			? (dist <= addEdgeMaxLengthM ? 0x22c55e : 0xef4444)
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
		if (regionSelectMode && regionStart && regionEnd) {
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
				onRegionSelected?.([minX, minZ, maxX, maxZ]);
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
		if (hit) onObjectContextMenu?.(event, hit.id, hit.type);
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
		primMeshPending.add(key);
		try {
			const data = await loadCachedPrimMeshPayload(projectId, sceneId, sourcePath, usdRef || undefined);
			primMeshCache.set(key, geometryFromPrimPayload(data));
		} catch {
			primMeshCache.set(key, null);
		} finally {
			primMeshPending.delete(key);
			primMeshCacheVersion += 1; // trigger re-render
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
		// Queue mesh loads for USD objects not yet cached
		for (const obj of authoringObjects) {
			const sourcePath = obj?.metadata?.asset_source_path;
			const usdRef = typeof obj.source_ref === 'string' ? obj.source_ref.split('#')[0] : '';
			const key = sourcePath ? primMeshKey(sourcePath, usdRef) : '';
			if (!sourcePath || primMeshCache.has(key) || primMeshPending.has(key)) continue;
			void loadPrimMesh(sourcePath, usdRef);
		}
	});

	$effect(() => {
		authoringObjects;
		authoringRegions;
		graphNodes;
		graphEdges;
		selectedId;
		visibleLayers;
		highlightedPath;
		allEpisodePaths;
		customSensorNodes;
		primMeshCacheVersion; // re-render when new meshes arrive
		if (renderer) rebuildScene();
	});

	$effect(() => {
		draftGhost;
		draftPoint;
		editorMode;
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
		vpId: string, modality: string, sensorId = ''
	) {
		const key = `${vpId}/${headingId}/${modality}/${sensorId || '_'}`;
		// Reuse existing group if already built (avoids texture reload on view-aligned updates)
		if (frustumHeadingMap.has(key)) {
			const existing = frustumHeadingMap.get(key);
			frustumGroup.add(existing);
			if (hasModality) frustumSelectables.push(...existing.children.filter((c: any) => c.isMesh && c.userData.frustum));
			return;
		}

		const displayDist = 0.5;
		const fovYRad = (60 * Math.PI) / 180;
		const aspect = 4 / 3;
		const halfH = Math.tan(fovYRad / 2) * displayDist;
		const halfW = halfH * aspect;
		const camY = cameraHeight;

		const yaw = (yawDeg * Math.PI) / 180;
		const origin = new THREE.Vector3(nx, camY, nz);
		const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
		const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
		const up = new THREE.Vector3(0, 1, 0);
		const negRight = right.clone().negate();
		const negFwd = fwd.clone().negate();

		const center = origin.clone().addScaledVector(fwd, displayDist);
		const group = new THREE.Group();
		group.userData = { vpId, headingId, yawDeg };

		if (!hasModality) {
			// Short direction ray only for missing renders
			const tip = origin.clone().addScaledVector(fwd, displayDist * 0.6);
			const rayGeo = new THREE.BufferGeometry().setFromPoints([origin, tip]);
			group.add(new THREE.LineSegments(rayGeo, new THREE.LineBasicMaterial({ color: 0x64748b, transparent: true, opacity: 0.5 })));
		} else {
			const tl = center.clone().addScaledVector(right, -halfW).addScaledVector(up, halfH);
			const tr = center.clone().addScaledVector(right, halfW).addScaledVector(up, halfH);
			const bl = center.clone().addScaledVector(right, -halfW).addScaledVector(up, -halfH);
			const br = center.clone().addScaledVector(right, halfW).addScaledVector(up, -halfH);

			const linePoints = [origin, tl, origin, tr, origin, bl, origin, br, tl, tr, tr, br, br, bl, bl, tl];
			const lineGeo = new THREE.BufferGeometry().setFromPoints(linePoints);
			group.add(new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.9 })));

			const url = opticalNavObservationModalityUrl(projectId, sceneId, vpId, headingId, modality, sensorId);
			let texture = textureCache.get(url);
			if (!texture) {
				texture = new THREE.TextureLoader().load(url);
				(texture as any).colorSpace = modality === 'rgb' ? 'srgb' : '';
				textureCache.set(url, texture);
			}
			const rotMat = new THREE.Matrix4().makeBasis(right, up, negFwd);
			const plane = new THREE.Mesh(
				new THREE.PlaneGeometry(halfW * 2, halfH * 2),
				new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide })
			);
			plane.position.copy(center);
			plane.quaternion.setFromRotationMatrix(rotMat);
			plane.userData = { frustum: true, vpId, headingId, hasRgb: true };
			group.add(plane);
			frustumSelectables.push(plane);
		}

		frustumHeadingMap.set(key, group);
		frustumGroup.add(group);
	}

	function updateFrustumVisibility() {
		if (!frustumGroup || frustumMode !== 'view-aligned') return;
		const viewYaw = getCameraYawDeg();

		// Group cached heading groups by vpId, but only consider current modality's entries.
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

			if (frustumMode === 'selected') {
				if (vpId !== selectedId) continue;
				for (let i = 0; i < hdEntries.length; i++) {
					const [headingId, hdata] = hdEntries[i];
					buildFrustumForHeading(nx, nz, headingId, hdDegs[i], hasHeadingModality(hdata, modalityKey), vpId, frustumModality, activeSensorId);
				}
			} else {
				// view-aligned: build ALL headings but only show the nearest one.
				// This populates frustumHeadingMap so camera rotation can toggle .visible
				// without any geometry/texture operations (no flicker).
				const nearestDeg = nearestHeadingDeg(viewYaw, hdDegs);
				for (let i = 0; i < hdEntries.length; i++) {
					const [headingId, hdata] = hdEntries[i];
					buildFrustumForHeading(nx, nz, headingId, hdDegs[i], hasHeadingModality(hdata, modalityKey), vpId, frustumModality, activeSensorId);
					const grp = frustumHeadingMap.get(`${vpId}/${headingId}/${frustumModality}/${activeSensorId || '_'}`);
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
