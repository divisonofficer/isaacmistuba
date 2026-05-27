<script lang="ts">
	import { onMount } from 'svelte';
	import * as THREE from 'three';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
	import { getOpticalNavEditorGeometry } from '$lib/api';

	type GhostGeom =
		| { type: 'line'; x1: number; y1: number; x2: number; y2: number; valid: boolean }
		| { type: 'rect'; minX: number; minY: number; maxX: number; maxY: number; valid: boolean }
		| { type: 'point'; x: number; y: number; valid: boolean };

	type VisibleLayers = {
		objects: boolean;
		traversable: boolean;
		goals: boolean;
		hazards: boolean;
		graphNodes: boolean;
		graphEdges: boolean;
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
		mapBounds = { w: 6, h: 4 },
		onGroundPointerDown,
		onGroundPointerMove,
		onGroundPointerUp,
		onObjectSelect,
		onObjectContextMenu,
		onHandleDrag,
		onStatus
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
		mapBounds?: { w: number; h: number };
		onGroundPointerDown?: (pt: { x: number; y: number }) => void;
		onGroundPointerMove?: (pt: { x: number; y: number }) => void;
		onGroundPointerUp?: (pt: { x: number; y: number }) => void;
		onObjectSelect?: (id: string) => void;
		onObjectContextMenu?: (event: MouseEvent, id: string, type: 'object' | 'region') => void;
		onHandleDrag?: (id: string, handle: 'line_start' | 'line_end', pt: { x: number; y: number }) => void;
		onStatus?: (message: string) => void;
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
	let resizeObserver: ResizeObserver | null = null;
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
		const m: Record<string, number> = { chair: 0x94a3b8, table: 0x92400e, plant: 0x166534, landmark: 0x64748b };
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

	function isRegionVisible(type: string): boolean {
		if (type === 'goal' || type === 'start' || type === 'stop_before') return visibleLayers.goals;
		if (type === 'traversable') return visibleLayers.traversable;
		return visibleLayers.hazards;
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

	function buildPointObject(obj: any): any | null {
		const center = obj.geometry?.center;
		if (!center) return null;
		const [x, z] = center;
		const proxy = obj.metadata?.proxy_size;
		const sx = Array.isArray(proxy) ? Math.max(0.16, Math.min(1.2, Number(proxy[0] ?? 0.35))) : 0.35;
		const h = Array.isArray(proxy) ? Math.max(0.18, Math.min(1.8, Number(proxy[1] ?? 0.5))) : (obj.type === 'table' ? 0.75 : 0.5);
		const sz = Array.isArray(proxy) ? Math.max(0.16, Math.min(1.2, Number(proxy[2] ?? 0.35))) : 0.35;
		const geo = new THREE.BoxGeometry(sx, h, sz);
		const mat = new THREE.MeshStandardMaterial({ color: pointColor(obj.type), roughness: 0.8, metalness: 0 });
		const mesh = new THREE.Mesh(geo, mat);
		mesh.position.set(x, h / 2, z);
		mesh.userData = { id: obj.id, itemType: 'object' };
		return mesh;
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

	function addEnvironment() {
		if (!baseGroup) return;
		clearGroup(baseGroup);
		floorTargets = [];

		const w = mapBounds?.w ?? 6;
		const h = mapBounds?.h ?? 4;
		const bounds = editorGeometry?.bounds ?? { min: [0, 0, 0], max: [w, 0.1, h], center: [w/2, 0.05, h/2], size: [w, 0.1, h] };
		const bMin = bounds.min ?? [0, 0, 0];
		const bSize = boundsSize(bounds);
		const bCenter = boundsCenter(bounds);
		const floorPlanes = editorGeometry?.floor_planes?.length ? editorGeometry.floor_planes : [
			{ id: 'floor_fallback', bounds: { min: [bMin[0], 0, bMin[2]], max: [bMin[0] + bSize[0], 0.05, bMin[2] + bSize[2]] } }
		];

		for (const floor of floorPlanes) {
			const size = boundsSize(floor.bounds);
			const center = boundsCenter(floor.bounds);
			const geo = new THREE.BoxGeometry(Math.max(0.001, size[0]), Math.max(0.02, size[1]), Math.max(0.001, size[2]));
			const mat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 1, metalness: 0, transparent: true, opacity: 0.92 });
			const mesh = new THREE.Mesh(geo, mat);
			mesh.position.set(center[0], Math.max(0.001, center[1]), center[2]);
			mesh.userData = { floorTarget: true, sourceId: floor.id };
			baseGroup.add(mesh);
			floorTargets.push(mesh);
		}

		const grid = new THREE.GridHelper(10, 40, 0xcbd5e1, 0xe2e8f0);
		grid.position.set(bCenter[0], 0.002, bCenter[2]);
		baseGroup.add(grid);

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

		const outlineGeo = new THREE.BoxGeometry(6, 0.005, 4);
		const outline = new THREE.LineSegments(
			new THREE.EdgesGeometry(outlineGeo),
			new THREE.LineBasicMaterial({ color: 0x94a3b8, transparent: true, opacity: 0.7 })
		);
		outline.scale.set(Math.max(0.001, bSize[0] / 6), 1, Math.max(0.001, bSize[2] / 4));
		outline.position.set(bCenter[0], 0.006, bCenter[2]);
		baseGroup.add(outline);
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
				const line = new THREE.Line(
					new THREE.BufferGeometry().setFromPoints(pts),
					new THREE.LineBasicMaterial({
						color: edge.hazard_crossing ? 0xf97316 : 0x6366f1,
						transparent: true, opacity: 0.55
					})
				);
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
					addSelectionEdges(mesh.geometry, mesh.position.clone(), mesh.rotation.clone());
					addLineHandles(obj);
				}
			}
		}

		// Graph nodes
		if (visibleLayers.graphNodes) {
			for (const node of graphNodes) {
				const isHazard = node.tags?.includes('hazard_adjacent');
				const isSensor = editorMode === 'sensor';
				const geo = new THREE.SphereGeometry(isSensor ? 0.09 : 0.06, 8, 8);
				const mat = new THREE.MeshBasicMaterial({
					color: isSensor ? 0xf59e0b : isHazard ? 0xf97316 : 0x6366f1
				});
				const sphere = new THREE.Mesh(geo, mat);
				sphere.position.set(node.position?.[0] ?? 0, 0.06, node.position?.[1] ?? 0);
				sphere.userData = { id: node.node_id, itemType: 'node' };
				rootGroup.add(sphere);
				selectableObjects.push(sphere);
			}
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
			const geo = new THREE.SphereGeometry(0.14, 10, 10);
			const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity });
			const sphere = new THREE.Mesh(geo, mat);
			sphere.position.set(draftGhost.x, 0.14, draftGhost.y);
			ghostGroup.add(sphere);
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

		baseGroup = new THREE.Group();
		rootGroup = new THREE.Group();
		ghostGroup = new THREE.Group();
		robotGroup = new THREE.Group();
		scene3D.add(baseGroup, rootGroup, ghostGroup, robotGroup);

		const ambient = new THREE.AmbientLight(0xffffff, 0.8);
		const dir = new THREE.DirectionalLight(0xffffff, 0.85);
		dir.position.set(6, 12, 3);
		scene3D.add(ambient, dir);

		const loop = () => {
			animationFrame = requestAnimationFrame(loop);
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

	// ─── pointer events ───────────────────────────────────────────────────
	function onPointerDown(event: PointerEvent) {
		if (event.button !== 0) return;
		if (editorMode === 'simulate') return;
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
		if (pt) onGroundPointerDown?.(pt);
	}

	function onPointerMove(event: PointerEvent) {
		if (editorMode === 'simulate') return;
		const pt = getWorldPoint(event);
		if (pt && dragHandle) {
			onHandleDrag?.(dragHandle.id, dragHandle.handle, pt);
			return;
		}
		if (pt) onGroundPointerMove?.(pt);
	}

	function onPointerUp(event: PointerEvent) {
		if (event.button !== 0) return;
		if (editorMode === 'simulate') return;
		if (dragHandle) {
			dragHandle = null;
			if (controls) controls.enabled = true;
			return;
		}
		const pt = getWorldPoint(event);
		if (pt) onGroundPointerUp?.(pt);
	}

	function onMouseDown(event: MouseEvent) {
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
		onGroundPointerMove?.({ x: -1, y: -1 });
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
		void loadEditorGeometry();
		return () => {
			if (animationFrame) cancelAnimationFrame(animationFrame);
			resizeObserver?.disconnect();
			controls?.dispose();
			if (baseGroup) disposeNode(baseGroup);
			if (rootGroup) disposeNode(rootGroup);
			if (ghostGroup) disposeNode(ghostGroup);
			if (robotGroup) disposeNode(robotGroup);
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
		projectId;
		sceneId;
		void loadEditorGeometry();
	});

	$effect(() => {
		editorGeometry;
		editorGeometryStatus;
		mapBounds;
		if (renderer) addEnvironment();
	});

	$effect(() => {
		authoringObjects;
		authoringRegions;
		graphNodes;
		graphEdges;
		selectedId;
		visibleLayers;
		highlightedPath;
		if (renderer) rebuildScene();
	});

	$effect(() => {
		draftGhost;
		draftPoint;
		editorMode;
		if (renderer) updateGhost();
	});

	$effect(() => {
		robotPos;
		editorMode;
		if (renderer) updateRobot();
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
