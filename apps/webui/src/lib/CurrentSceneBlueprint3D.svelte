<script lang="ts">
	import { onMount } from 'svelte';
	import * as THREE from 'three';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
	import { getSceneDiagram3D } from '$lib/api';
	import { lang } from '$lib/stores/lang';

	type BoundsPayload = {
		min: number[];
		max: number[];
		size: number[];
		center: number[];
	};

	type DiagramObject = {
		id: string;
		path?: string;
		label: string;
		kind: string;
		category: string;
		selected?: boolean;
		bounds: BoundsPayload;
	};

	type DiagramRobot = {
		path: string;
		label: string;
		translation?: number[] | null;
		selected?: boolean;
	};

	type DiagramRoom = {
		id: string;
		label: string;
		object_count: number;
		bounds: BoundsPayload;
	};

	type DiagramManifest = {
		scene_id: string;
		status: string;
		reason?: string | null;
		simplification_mode?: string;
		objects: DiagramObject[];
		robots: DiagramRobot[];
		rooms?: DiagramRoom[];
		active_viewport_camera?: Record<string, unknown> | null;
		summary?: {
			scene_bounds?: BoundsPayload;
			object_count_total?: number;
			object_count_included?: number;
			object_count_omitted?: number;
		};
	};

	let {
		sceneId = null,
		selectedPath = null,
		selectedPaths = null,
		activeCamera = null
	}: {
		sceneId?: string | null;
		selectedPath?: string | null;
		selectedPaths?: string[] | null;
		activeCamera?: Record<string, unknown> | null;
	} = $props();

	const L = $derived($lang);

	const PALETTE: Record<string, { fill: string; opacity: number; edge: string }> = {
		floor: { fill: '#f7f8fb', opacity: 0.95, edge: '#d8dde8' },
		shell: { fill: '#d7dde5', opacity: 0.58, edge: '#b7bfcb' },
		roof:  { fill: '#e6e9ef', opacity: 0.32, edge: '#bcc4cf' },
		glass: { fill: '#d8f1ff', opacity: 0.42, edge: '#92d4f3' },
		furniture: { fill: '#bcc4cf', opacity: 0.82, edge: '#96a1af' },
		props: { fill: '#c7cdd6', opacity: 0.76, edge: '#aab3bf' },
		robot: { fill: '#f6b15e', opacity: 0.95, edge: '#d88f3b' },
		other: { fill: '#d6dbe2', opacity: 0.72, edge: '#b0b8c3' }
	};

	type ViewMode = 'iso' | 'top';
	let viewMode = $state<ViewMode>('iso');
	let hideRoof = $state(true);
	let sliceMaxY = $state<number | null>(null); // null = OFF, value = clip everything above
	let sectionBox = $state<BoundsPayload | null>(null);
	let focusMenuOpen = $state(false);

	let host = $state<HTMLDivElement | null>(null);
	let manifest = $state<DiagramManifest | null>(null);
	let loading = $state(false);
	let errorMessage = $state('');

	let renderer: any = null;
	let scene3D: any = null;
	let camera3D: any = null;
	let controls: any = null;
	let resizeObserver: ResizeObserver | null = null;
	let animationFrame = 0;
	let rootGroup: any = null;
	let sceneBounds: BoundsPayload | null = null;

	const selectedSet = $derived(
		new Set<string>(
			selectedPaths && selectedPaths.length
				? selectedPaths
				: (selectedPath ? [selectedPath] : [])
		)
	);

	function rgb(hex: string): any {
		return new THREE.Color(hex);
	}

	function styleFor(category: string) {
		return PALETTE[category] ?? PALETTE.other;
	}

	function aabbIntersects(a: BoundsPayload, b: BoundsPayload): boolean {
		return a.min[0] <= b.max[0] && a.max[0] >= b.min[0]
			&& a.min[1] <= b.max[1] && a.max[1] >= b.min[1]
			&& a.min[2] <= b.max[2] && a.max[2] >= b.min[2];
	}

	function expandBounds(b: BoundsPayload, padding: number): BoundsPayload {
		const min = [b.min[0] - padding, b.min[1] - padding, b.min[2] - padding];
		const max = [b.max[0] + padding, b.max[1] + padding, b.max[2] + padding];
		return {
			min, max,
			size: [max[0]-min[0], max[1]-min[1], max[2]-min[2]],
			center: [(min[0]+max[0])/2, (min[1]+max[1])/2, (min[2]+max[2])/2]
		};
	}

	function unionBounds(items: { bounds: BoundsPayload }[]): BoundsPayload | null {
		if (!items.length) return null;
		const min = [Infinity, Infinity, Infinity];
		const max = [-Infinity, -Infinity, -Infinity];
		for (const it of items) {
			for (let i = 0; i < 3; i++) {
				if (it.bounds.min[i] < min[i]) min[i] = it.bounds.min[i];
				if (it.bounds.max[i] > max[i]) max[i] = it.bounds.max[i];
			}
		}
		return {
			min, max,
			size: [Math.max(0.1, max[0]-min[0]), Math.max(0.1, max[1]-min[1]), Math.max(0.1, max[2]-min[2])],
			center: [(min[0]+max[0])/2, (min[1]+max[1])/2, (min[2]+max[2])/2]
		};
	}

	function labelTexture(text: string, bg = '#2f7bf6', fg = '#ffffff') {
		const canvas = document.createElement('canvas');
		const ctx = canvas.getContext('2d');
		if (!ctx) return null;
		const fontSize = 28;
		ctx.font = `600 ${fontSize}px sans-serif`;
		const width = Math.ceil(ctx.measureText(text).width + 28);
		const height = 48;
		canvas.width = width * 2;
		canvas.height = height * 2;
		ctx.scale(2, 2);
		ctx.font = `600 ${fontSize}px sans-serif`;
		ctx.fillStyle = bg;
		ctx.beginPath();
		ctx.roundRect(0, 0, width, height, 12);
		ctx.fill();
		ctx.fillStyle = fg;
		ctx.textAlign = 'center';
		ctx.textBaseline = 'middle';
		ctx.fillText(text, width / 2, height / 2 + 1);
		const texture = new THREE.CanvasTexture(canvas);
		texture.needsUpdate = true;
		return { texture, width, height };
	}

	function addLabel(group: any, text: string, position: any, scale = 1) {
		const result = labelTexture(text);
		if (!result) return;
		const material = new THREE.SpriteMaterial({ map: result.texture, transparent: true, depthTest: false });
		const sprite = new THREE.Sprite(material);
		sprite.position.copy(position);
		sprite.scale.set((result.width / 42) * scale, (result.height / 42) * scale, 1);
		group.add(sprite);
	}

	function disposeObject(object: any) {
		object.traverse((child: any) => {
			const mesh = child as any;
			if (mesh.geometry) mesh.geometry.dispose();
			const material = (mesh.material ?? null) as any[] | any | null;
			if (Array.isArray(material)) {
				for (const item of material) item.dispose();
			} else {
				material?.dispose();
			}
			const spriteMaterial = child instanceof THREE.Sprite ? child.material : null;
			const map = (spriteMaterial as any)?.map;
			map?.dispose();
		});
	}

	function ensureThree() {
		if (!host || renderer) return;
		renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
		renderer.setClearColor('#f7f8fb', 1);
		host.appendChild(renderer.domElement);

		scene3D = new THREE.Scene();
		scene3D.background = rgb('#f7f8fb');

		camera3D = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 2000);
		camera3D.position.set(12, 14, 12);
		camera3D.up.set(0, 1, 0);

		controls = new OrbitControls(camera3D, renderer.domElement);
		controls.enableRotate = false;
		controls.enablePan = true;
		controls.enableDamping = true;
		controls.screenSpacePanning = true;
		controls.zoomSpeed = 0.95;
		controls.minZoom = 0.35;
		controls.maxZoom = 8;

		rootGroup = new THREE.Group();
		scene3D.add(rootGroup);

		const ambient = new THREE.AmbientLight('#ffffff', 1.15);
		const directional = new THREE.DirectionalLight('#d8dde8', 1.25);
		directional.position.set(16, 26, 12);
		scene3D.add(ambient, directional);

		const renderLoop = () => {
			animationFrame = requestAnimationFrame(renderLoop);
			controls?.update();
			renderer?.render(scene3D!, camera3D!);
		};
		renderLoop();

		const resize = () => {
			if (!host || !renderer || !camera3D) return;
			const width = Math.max(1, host.clientWidth);
			const height = Math.max(1, host.clientHeight);
			renderer.setSize(width, height, false);
			const aspect = width / height;
			const bounds = sceneBounds ?? manifest?.summary?.scene_bounds ?? null;
			const span = bounds ? Math.max(bounds.size[0], bounds.size[1] * 1.6, bounds.size[2]) : 12;
			camera3D.left = -span * aspect * 0.6;
			camera3D.right = span * aspect * 0.6;
			camera3D.top = span * 0.6;
			camera3D.bottom = -span * 0.6;
			camera3D.updateProjectionMatrix();
		};
		resizeObserver = new ResizeObserver(resize);
		resizeObserver.observe(host);
		resize();
	}

	function frameScene(bounds: BoundsPayload | null) {
		if (!camera3D || !controls) return;
		const center = bounds ? new THREE.Vector3(bounds.center[0], bounds.center[1], bounds.center[2]) : new THREE.Vector3(0, 0, 0);
		const span = bounds ? Math.max(bounds.size[0], bounds.size[1] * 1.8, bounds.size[2]) : 12;
		if (viewMode === 'top') {
			camera3D.position.copy(center.clone().add(new THREE.Vector3(0, span * 2.0, 0.001)));
			camera3D.up.set(0, 0, -1);
		} else {
			camera3D.position.copy(center.clone().add(new THREE.Vector3(span * 0.95, span * 1.1, span * 0.9)));
			camera3D.up.set(0, 1, 0);
		}
		controls.target.copy(center);
		controls.update();
		sceneBounds = bounds;
		if (host && renderer) {
			const event = new Event('resize');
			window.dispatchEvent(event);
		}
	}

	function addGrid(bounds: BoundsPayload | null) {
		if (!rootGroup) return;
		const center = bounds ? new THREE.Vector3(bounds.center[0], bounds.center[1], bounds.center[2]) : new THREE.Vector3();
		const span = bounds ? Math.max(bounds.size[0], bounds.size[2]) : 10;
		const grid = new THREE.GridHelper(Math.max(span * 1.35, 6), 18, rgb('#dbe2ec'), rgb('#edf1f6'));
		grid.position.set(center.x, (bounds?.min[1] ?? 0) - 0.02, center.z);
		rootGroup.add(grid);

		const plate = new THREE.Mesh(
			new THREE.BoxGeometry(Math.max(span * 1.1, 4), 0.02, Math.max(span * 1.1, 4)),
			new THREE.MeshStandardMaterial({
				color: rgb('#fbfcfe'),
				transparent: true,
				opacity: 0.95,
				roughness: 1,
				metalness: 0
			})
		);
		plate.position.set(center.x, (bounds?.min[1] ?? 0) - 0.03, center.z);
		rootGroup.add(plate);
	}

	function addProxyObject(item: DiagramObject) {
		if (!rootGroup) return;
		const style = styleFor(item.category);
		const size = item.bounds.size;
		const center = item.bounds.center;
		const height = Math.max(size[1], item.category === 'shell' ? 0.16 : 0.08);
		const geometry = new THREE.BoxGeometry(Math.max(size[0], 0.08), height, Math.max(size[2], 0.08));
		const isHit = item.selected || (item.path ? selectedSet.has(item.path) : false)
			|| (selectedPath != null && item.path != null && (item.path === selectedPath || selectedPath.startsWith(`${item.path}/`)));
		const material = new THREE.MeshStandardMaterial({
			color: rgb(style.fill),
			transparent: true,
			opacity: style.opacity,
			roughness: 1,
			metalness: 0,
			emissive: isHit ? rgb('#c8ddff') : rgb('#000000'),
			emissiveIntensity: isHit ? 0.35 : 0
		});
		const mesh = new THREE.Mesh(geometry, material);
		mesh.position.set(center[0], center[1], center[2]);
		rootGroup.add(mesh);

		const edges = new THREE.LineSegments(
			new THREE.EdgesGeometry(geometry),
			new THREE.LineBasicMaterial({
				color: rgb(style.edge),
				transparent: true,
				opacity: item.category === 'shell' ? 0.7 : 0.5
			})
		);
		edges.position.copy(mesh.position);
		rootGroup.add(edges);
	}

	function addRobotMarker(robot: DiagramRobot) {
		if (!rootGroup || !Array.isArray(robot.translation) || robot.translation.length < 3) return;
		const [x, y, z] = robot.translation.map((value) => Number(value) || 0);
		const material = new THREE.MeshStandardMaterial({
			color: rgb('#f1a14b'),
			roughness: 0.95,
			metalness: 0
		});
		const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.24, 0.26, 18), material);
		mesh.position.set(x, y + 0.16, z);
		rootGroup.add(mesh);
		if (robot.selected) {
			const ring = new THREE.Mesh(
				new THREE.TorusGeometry(0.32, 0.025, 10, 40),
				new THREE.MeshBasicMaterial({ color: rgb('#f59e0b') })
			);
			ring.rotation.x = Math.PI / 2;
			ring.position.set(x, y + 0.03, z);
			rootGroup.add(ring);
		}
	}

	function addCameraMarker(cameraPayload: Record<string, unknown> | null | undefined) {
		if (!rootGroup || !cameraPayload) return;
		const originArray = Array.isArray(cameraPayload.origin) ? cameraPayload.origin : null;
		const targetArray = Array.isArray(cameraPayload.target) ? cameraPayload.target : null;
		const upArray = Array.isArray(cameraPayload.up) ? cameraPayload.up : [0, 1, 0];
		if (!originArray || !targetArray || originArray.length < 3 || targetArray.length < 3) return;
		const origin = new THREE.Vector3(Number(originArray[0]) || 0, Number(originArray[1]) || 0, Number(originArray[2]) || 0);
		const target = new THREE.Vector3(Number(targetArray[0]) || 0, Number(targetArray[1]) || 0, Number(targetArray[2]) || 0);
		const up = new THREE.Vector3(Number(upArray[0]) || 0, Number(upArray[1]) || 1, Number(upArray[2]) || 0).normalize();
		const forward = target.clone().sub(origin).normalize();
		if (forward.lengthSq() < 1e-6) return;
		let right = new THREE.Vector3().crossVectors(forward, up).normalize();
		if (right.lengthSq() < 1e-6) right = new THREE.Vector3(1, 0, 0);
		const correctedUp = new THREE.Vector3().crossVectors(right, forward).normalize();
		const sceneSpan = sceneBounds ? Math.max(sceneBounds.size[0], sceneBounds.size[2], sceneBounds.size[1]) : 12;
		const reach = Math.max(1.6, sceneSpan * 0.22);
		const half = THREE.MathUtils.degToRad((Number(cameraPayload.fov_deg) || 60) * 0.5);
		const spread = Math.tan(half) * reach * 0.55;
		const farCenter = origin.clone().add(forward.clone().multiplyScalar(reach));
		const corners = [
			farCenter.clone().add(right.clone().multiplyScalar(spread)).add(correctedUp.clone().multiplyScalar(spread * 0.35)),
			farCenter.clone().add(right.clone().multiplyScalar(-spread)).add(correctedUp.clone().multiplyScalar(spread * 0.35)),
			farCenter.clone().add(right.clone().multiplyScalar(spread)).add(correctedUp.clone().multiplyScalar(-spread * 0.35)),
			farCenter.clone().add(right.clone().multiplyScalar(-spread)).add(correctedUp.clone().multiplyScalar(-spread * 0.35))
		];
		const marker = new THREE.Mesh(
			new THREE.SphereGeometry(0.12, 16, 16),
			new THREE.MeshBasicMaterial({ color: rgb('#2f7bf6') })
		);
		marker.position.copy(origin);
		rootGroup.add(marker);

		for (const corner of corners) {
			const line = new THREE.Line(
				new THREE.BufferGeometry().setFromPoints([origin, corner]),
				new THREE.LineBasicMaterial({ color: rgb('#35b968'), transparent: true, opacity: 0.85 })
			);
			rootGroup.add(line);
		}
		for (let index = 0; index < corners.length; index += 1) {
			const next = corners[(index + 1) % corners.length];
			const line = new THREE.Line(
				new THREE.BufferGeometry().setFromPoints([corners[index], next]),
				new THREE.LineBasicMaterial({ color: rgb('#9fdcb7'), transparent: true, opacity: 0.55 })
			);
			rootGroup.add(line);
		}
		addLabel(rootGroup, String(cameraPayload.name ?? cameraPayload.sensor_id ?? 'camera'), origin.clone().add(new THREE.Vector3(0, 0.6, 0)), 0.82);
	}

	function addSectionBox(box: BoundsPayload) {
		if (!rootGroup) return;
		const size = [
			Math.max(0.05, box.max[0] - box.min[0]),
			Math.max(0.05, box.max[1] - box.min[1]),
			Math.max(0.05, box.max[2] - box.min[2])
		];
		const geom = new THREE.BoxGeometry(size[0], size[1], size[2]);
		const mat = new THREE.LineBasicMaterial({ color: rgb('#f59e0b'), transparent: true, opacity: 0.85 });
		const wire = new THREE.LineSegments(new THREE.EdgesGeometry(geom), mat);
		wire.position.set(box.center[0], box.center[1], box.center[2]);
		rootGroup.add(wire);
	}

	function rebuildScene() {
		if (!rootGroup || !scene3D) return;
		for (const child of [...rootGroup.children]) {
			rootGroup.remove(child);
			disposeObject(child);
		}
		const bounds = manifest?.summary?.scene_bounds ?? null;
		addGrid(bounds);
		for (const item of manifest?.objects ?? []) {
			if (hideRoof && item.category === 'roof') continue;
			if (sliceMaxY !== null && item.bounds.min[1] > sliceMaxY) continue;
			if (sectionBox && !aabbIntersects(item.bounds, sectionBox)) continue;
			addProxyObject(item);
		}
		for (const robot of manifest?.robots ?? []) {
			addRobotMarker(robot);
		}
		addCameraMarker(activeCamera ?? manifest?.active_viewport_camera ?? null);
		if (sectionBox) addSectionBox(sectionBox);
	}

	async function loadManifest(id: string | null) {
		if (!id) {
			manifest = null;
			errorMessage = '';
			return;
		}
		loading = true;
		errorMessage = '';
		try {
			manifest = await getSceneDiagram3D(id) as DiagramManifest;
		} catch (error) {
			manifest = null;
			errorMessage = error instanceof Error ? error.message : 'Failed to load 3D blueprint';
		} finally {
			loading = false;
		}
	}

	function resetView() {
		viewMode = 'iso';
		hideRoof = true;
		sliceMaxY = null;
		sectionBox = null;
		focusMenuOpen = false;
		frameScene(manifest?.summary?.scene_bounds ?? null);
	}

	function applyFocus(target: BoundsPayload | null, padding = 0.6) {
		focusMenuOpen = false;
		if (!target) return;
		sectionBox = expandBounds(target, padding);
		frameScene(sectionBox);
	}

	function focusOnRobot() {
		const r = manifest?.robots?.[0];
		if (!r || !Array.isArray(r.translation)) return;
		const [x, y, z] = r.translation.map((v) => Number(v) || 0);
		applyFocus({
			min: [x - 1.5, y - 0.2, z - 1.5],
			max: [x + 1.5, y + 1.5, z + 1.5],
			size: [3, 1.7, 3],
			center: [x, y + 0.65, z]
		}, 0);
	}

	function focusOnGlass() {
		const items = (manifest?.objects ?? []).filter((o) => o.category === 'glass');
		applyFocus(unionBounds(items));
	}

	function focusOnSelected() {
		if (!selectedSet.size) return;
		const items = (manifest?.objects ?? []).filter((o) => o.path && selectedSet.has(o.path));
		applyFocus(unionBounds(items));
	}

	function focusOnRoom(room: DiagramRoom) {
		applyFocus(room.bounds, 0);
	}

	const heightSliderMin = $derived(Number(manifest?.summary?.scene_bounds?.min[1] ?? 0).toFixed(2));
	const heightSliderMax = $derived(Number(manifest?.summary?.scene_bounds?.max[1] ?? 4).toFixed(2));
	const heightSliderValue = $derived(sliceMaxY ?? Number(manifest?.summary?.scene_bounds?.max[1] ?? 4));
	const sliceLabel = $derived(sliceMaxY === null
		? (L === 'kr' ? '전체 높이' : 'Full height')
		: `${(sliceMaxY).toFixed(1)} m`);

	const focusableRooms = $derived(manifest?.rooms ?? []);
	const hasGlass = $derived((manifest?.objects ?? []).some((o) => o.category === 'glass'));
	const hasRobot = $derived((manifest?.robots ?? []).length > 0 && manifest?.robots?.[0].translation != null);
	const selectedCount = $derived(selectedSet.size);

	onMount(() => {
		ensureThree();
		return () => {
			if (animationFrame) cancelAnimationFrame(animationFrame);
			resizeObserver?.disconnect();
			controls?.dispose();
			if (rootGroup) {
				disposeObject(rootGroup);
			}
			renderer?.dispose();
			renderer?.domElement.remove();
			renderer = null;
			scene3D = null;
			camera3D = null;
			controls = null;
			rootGroup = null;
		};
	});

	$effect(() => {
		sceneId;
		void loadManifest(sceneId);
	});

	$effect(() => {
		manifest;
		selectedPath;
		selectedPaths;
		activeCamera;
		hideRoof;
		sliceMaxY;
		sectionBox;
		if (renderer) rebuildScene();
	});

	$effect(() => {
		viewMode;
		manifest;
		if (renderer && manifest) frameScene(sceneBounds ?? manifest.summary?.scene_bounds ?? null);
	});
</script>

<div class="bp3d-shell">
	<div class="bp3d-stage" bind:this={host}>
		<div class="bp3d-toolbar">
			<div class="bp3d-segment" role="tablist" aria-label="View mode">
				<button type="button" class="bp3d-seg-btn" class:active={viewMode === 'iso'} onclick={() => (viewMode = 'iso')}>Iso</button>
				<button type="button" class="bp3d-seg-btn" class:active={viewMode === 'top'} onclick={() => (viewMode = 'top')}>Top</button>
			</div>
			<label class="bp3d-check">
				<input type="checkbox" bind:checked={hideRoof} />
				{L === 'kr' ? '지붕 숨김' : 'Hide roof'}
			</label>
			<label class="bp3d-slice">
				<span class="bp3d-slice-label">{L === 'kr' ? '높이' : 'Height'} <span class="bp3d-slice-value">{sliceLabel}</span></span>
				<input
					type="range"
					min={heightSliderMin}
					max={heightSliderMax}
					step="0.1"
					value={heightSliderValue}
					oninput={(e) => {
						const v = Number((e.target as HTMLInputElement).value);
						const max = Number(manifest?.summary?.scene_bounds?.max[1] ?? 4);
						sliceMaxY = v >= max - 0.05 ? null : v;
					}}
				/>
			</label>
			<div class="bp3d-focus-wrap">
				<button type="button" class="bp3d-focus-btn" onclick={() => (focusMenuOpen = !focusMenuOpen)}>
					Focus ▾
				</button>
				{#if focusMenuOpen}
					<div class="bp3d-focus-menu" role="menu">
						<button type="button" disabled={!hasRobot} onclick={focusOnRobot}>🤖 {L === 'kr' ? '로봇' : 'Robot'}</button>
						<button type="button" disabled={!hasGlass} onclick={focusOnGlass}>🧊 {L === 'kr' ? '유리/투명' : 'Glass'}</button>
						<button type="button" disabled={selectedCount === 0} onclick={focusOnSelected}>
							🎯 {L === 'kr' ? '선택된 오브젝트' : 'Selected'} {selectedCount > 0 ? `(${selectedCount})` : ''}
						</button>
						{#if focusableRooms.length}
							<div class="bp3d-focus-divider"></div>
							<div class="bp3d-focus-section">{L === 'kr' ? '방' : 'Rooms'}</div>
							{#each focusableRooms.slice(0, 8) as room (room.id)}
								<button type="button" onclick={() => focusOnRoom(room)}>🏠 {room.label} <span class="muted">({room.object_count})</span></button>
							{/each}
						{/if}
						<div class="bp3d-focus-divider"></div>
						<button type="button" onclick={resetView}>↺ {L === 'kr' ? '전체 보기' : 'Reset'}</button>
					</div>
				{/if}
			</div>
			<button class="bp3d-reset" type="button" onclick={resetView}>Reset</button>
		</div>
		{#if loading}
			<div class="bp3d-overlay">Loading blueprint…</div>
		{:else if errorMessage}
			<div class="bp3d-overlay bp3d-overlay-error">{errorMessage}</div>
		{:else if !manifest || manifest.status === 'unavailable' || manifest.status === 'empty'}
			<div class="bp3d-overlay">
				<div>3D blueprint unavailable for this scene.</div>
				{#if manifest?.reason}
					<div class="bp3d-overlay-sub">{manifest.reason}</div>
				{/if}
			</div>
		{:else if manifest.status === 'partial'}
			<div class="bp3d-note">Partial preview</div>
		{/if}
	</div>
</div>

<style>
	.bp3d-shell {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background:
			linear-gradient(180deg, rgba(255,255,255,0.95), rgba(247,248,251,0.92)),
			radial-gradient(circle at top left, rgba(47,123,246,0.06), transparent 34%);
		border-radius: var(--radius-sm);
		border: 1px solid var(--panel-border);
		overflow: hidden;
	}
	.bp3d-stage {
		position: relative;
		flex: 1;
		min-height: 20rem;
	}
	.bp3d-stage :global(canvas) {
		display: block;
		width: 100%;
		height: 100%;
	}
	.bp3d-toolbar {
		position: absolute;
		top: 0.55rem;
		left: 0.6rem;
		right: 0.6rem;
		z-index: 4;
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
		padding: 0.35rem 0.55rem;
		background: rgba(255,255,255,0.86);
		border: 1px solid var(--panel-border);
		border-radius: 0.55rem;
		backdrop-filter: blur(6px);
		font-size: 0.74rem;
	}
	.bp3d-segment {
		display: inline-flex;
		border: 1px solid var(--panel-border);
		border-radius: 0.4rem;
		overflow: hidden;
	}
	.bp3d-seg-btn {
		appearance: none;
		border: none;
		background: transparent;
		padding: 0.18rem 0.55rem;
		font: inherit;
		font-size: 0.72rem;
		cursor: pointer;
		color: var(--muted-strong);
	}
	.bp3d-seg-btn.active {
		background: var(--brand, #2f7bf6);
		color: #fff;
	}
	.bp3d-check {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		cursor: pointer;
		user-select: none;
	}
	.bp3d-check input { margin: 0; }
	.bp3d-slice {
		display: inline-flex;
		flex-direction: column;
		gap: 0.1rem;
		min-width: 9rem;
	}
	.bp3d-slice-label {
		font-size: 0.66rem;
		color: var(--muted);
		display: flex;
		justify-content: space-between;
	}
	.bp3d-slice-value { color: var(--text); font-weight: 600; }
	.bp3d-slice input[type='range'] { width: 100%; }
	.bp3d-focus-wrap { position: relative; }
	.bp3d-focus-btn,
	.bp3d-reset {
		appearance: none;
		border: 1px solid var(--panel-border);
		background: var(--panel, #fff);
		color: var(--text);
		border-radius: 0.4rem;
		padding: 0.2rem 0.55rem;
		font: inherit;
		font-size: 0.72rem;
		cursor: pointer;
	}
	.bp3d-reset { margin-left: auto; }
	.bp3d-focus-menu {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		min-width: 12rem;
		background: var(--panel, #fff);
		border: 1px solid var(--panel-border);
		border-radius: 0.45rem;
		box-shadow: 0 12px 28px rgba(15,23,42,0.12);
		padding: 0.25rem;
		display: flex;
		flex-direction: column;
		gap: 1px;
		z-index: 5;
	}
	.bp3d-focus-menu button {
		appearance: none;
		border: none;
		background: transparent;
		text-align: left;
		padding: 0.3rem 0.5rem;
		border-radius: 0.3rem;
		font: inherit;
		font-size: 0.74rem;
		cursor: pointer;
		color: var(--text);
	}
	.bp3d-focus-menu button:hover:not(:disabled) {
		background: var(--brand-soft, rgba(47,123,246,0.08));
	}
	.bp3d-focus-menu button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.bp3d-focus-divider {
		height: 1px;
		background: var(--panel-border);
		margin: 0.25rem 0;
	}
	.bp3d-focus-section {
		font-size: 0.6rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--muted);
		padding: 0.2rem 0.5rem 0.05rem;
	}
	.muted { color: var(--muted); }
	.bp3d-overlay,
	.bp3d-note {
		position: absolute;
		z-index: 2;
	}
	.bp3d-overlay {
		inset: 0;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		align-items: center;
		justify-content: center;
		background: rgba(247,248,251,0.74);
		color: var(--muted-strong);
		font-size: 0.88rem;
		font-weight: 600;
	}
	.bp3d-overlay-error {
		color: var(--danger);
	}
	.bp3d-overlay-sub {
		font-size: 0.72rem;
		font-weight: 500;
		color: var(--muted);
	}
	.bp3d-note {
		bottom: 0.65rem;
		right: 0.7rem;
		padding: 0.22rem 0.52rem;
		border-radius: 999px;
		background: rgba(245,158,11,0.15);
		color: #b45309;
		font-size: 0.72rem;
		font-weight: 700;
	}
</style>
