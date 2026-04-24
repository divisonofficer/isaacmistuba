<script lang="ts">
	import { onMount } from 'svelte';
	import * as THREE from 'three';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
	import { getSceneDiagram3D } from '$lib/api';

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

	type DiagramManifest = {
		scene_id: string;
		status: string;
		reason?: string | null;
		simplification_mode?: string;
		objects: DiagramObject[];
		robots: DiagramRobot[];
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
		activeCamera = null
	}: {
		sceneId?: string | null;
		selectedPath?: string | null;
		activeCamera?: Record<string, unknown> | null;
	} = $props();

	const PALETTE: Record<string, { fill: string; opacity: number; edge: string }> = {
		floor: { fill: '#f7f8fb', opacity: 0.95, edge: '#d8dde8' },
		shell: { fill: '#d7dde5', opacity: 0.58, edge: '#b7bfcb' },
		glass: { fill: '#d8f1ff', opacity: 0.42, edge: '#92d4f3' },
		furniture: { fill: '#bcc4cf', opacity: 0.82, edge: '#96a1af' },
		props: { fill: '#c7cdd6', opacity: 0.76, edge: '#aab3bf' },
		robot: { fill: '#f6b15e', opacity: 0.95, edge: '#d88f3b' },
		other: { fill: '#d6dbe2', opacity: 0.72, edge: '#b0b8c3' }
	};

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

	function rgb(hex: string): any {
		return new THREE.Color(hex);
	}

	function styleFor(category: string) {
		return PALETTE[category] ?? PALETTE.other;
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
		camera3D.position.copy(center.clone().add(new THREE.Vector3(span * 0.95, span * 1.1, span * 0.9)));
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
		const material = new THREE.MeshStandardMaterial({
			color: rgb(style.fill),
			transparent: true,
			opacity: item.category === 'shell' || item.category === 'glass' || item.category === 'floor' ? style.opacity : style.opacity,
			roughness: 1,
			metalness: 0,
			emissive: item.selected || (selectedPath && (item.path === selectedPath || selectedPath.startsWith(`${item.path ?? ''}/`))) ? rgb('#c8ddff') : rgb('#000000'),
			emissiveIntensity: item.selected || (selectedPath && item.path && (item.path === selectedPath || selectedPath.startsWith(`${item.path}/`))) ? 0.35 : 0
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

		const wedgePoints = [origin, ...corners];
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

	function rebuildScene() {
		if (!rootGroup || !scene3D) return;
		for (const child of [...rootGroup.children]) {
			rootGroup.remove(child);
			disposeObject(child);
		}
		const bounds = manifest?.summary?.scene_bounds ?? null;
		addGrid(bounds);
		for (const item of manifest?.objects ?? []) {
			addProxyObject(item);
		}
		for (const robot of manifest?.robots ?? []) {
			addRobotMarker(robot);
		}
		addCameraMarker(activeCamera ?? manifest?.active_viewport_camera ?? null);
		frameScene(bounds);
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
		frameScene(manifest?.summary?.scene_bounds ?? null);
	}

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
		activeCamera;
		if (renderer) rebuildScene();
	});
</script>

<div class="bp3d-shell">
	<div class="bp3d-stage" bind:this={host}>
		<button class="bp3d-reset" type="button" onclick={resetView}>Reset</button>
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
	.bp3d-reset {
		appearance: none;
		border: 1px solid var(--panel-border);
		background: rgba(255,255,255,0.82);
		color: var(--text);
		border-radius: 0.45rem;
		padding: 0.25rem 0.55rem;
		font: inherit;
		font-size: 0.72rem;
		cursor: pointer;
	}
	.bp3d-stage {
		position: relative;
		flex: 1;
		min-height: 20rem;
	}
	.bp3d-reset {
		position: absolute;
		top: 0.75rem;
		right: 0.75rem;
		z-index: 3;
	}
	.bp3d-stage :global(canvas) {
		display: block;
		width: 100%;
		height: 100%;
	}
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
		top: 0.65rem;
		right: 0.7rem;
		padding: 0.22rem 0.52rem;
		border-radius: 999px;
		background: rgba(245,158,11,0.15);
		color: #b45309;
		font-size: 0.72rem;
		font-weight: 700;
	}
</style>
