<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import * as THREE from 'three';
	import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
	import { getOpticalNavRasterScene, getOpticalNavViewpointGraph, opticalNavMeshCacheUrl, opticalNavRasterAssetUrl } from '$lib/api';
	import { initialRasterPose, prioritizeRasterShapes, queryFiniteNumber, rasterCameraMovement, rasterInputAxes, shouldRefreshRasterManifest } from '$lib/liveViewerPose';

	type Pose = { x: number; y: number; z: number; yaw: number; pitch: number; fov: number };
	type RasterMaterial = { material_id?: string | null; bsdf_strategy: string; supported: boolean; fallback_reason?: string | null; base_color: number[]; roughness?: number; metallic?: number; ior?: number; opacity?: number; textures?: Record<string, string> };
	type RasterShape = { shape_id: string; mesh_ref: string; material_key: string; transform?: Record<string, unknown> };
	type RasterManifest = { revision: string; shapes: RasterShape[]; materials: Record<string, RasterMaterial> };

	let canvas: HTMLCanvasElement;
	let projectId = $state('opticalnav-v0.2');
	let sceneId = $state('infinigen_indoor_002');
	let pose = $state<Pose>({ x: 0, y: 1.5, z: 0, yaw: 0, pitch: 0, fov: 70 });
	let status = $state<'loading' | 'ready' | 'reloading' | 'error'>('loading');
	let error = $state(''); let revision = $state('—'); let fps = $state(0);
	let loaded = $state(0); let failed = $state(0); let total = $state(0);
	let textureLoaded = $state(0); let textureFailed = $state(0); let measuredSkipped = $state(0); let diagnostics = $state<string[]>([]);
	let completedMeshes = $derived(loaded + failed); let loadPercent = $derived(total ? Math.round((completedMeshes / total) * 100) : 0);
	let selected = $state('');
	let renderer: any; let scene: any; let camera: any; let activeGroup: any = null;
	let animation = 0; let revisionTimer: ReturnType<typeof setInterval> | null = null; let lastTick = 0; let lastFrame = 0; let currentRevision = ''; let buildToken = 0;
	const keys = new Set<string>(); const textureCache = new Map<string, Promise<any | null>>();

	function updateCamera() { if (!camera) return; camera.position.set(pose.x, pose.y, pose.z); camera.fov = pose.fov; camera.rotation.order = 'YXZ'; camera.rotation.y = THREE.MathUtils.degToRad(pose.yaw); camera.rotation.x = THREE.MathUtils.degToRad(pose.pitch); camera.updateProjectionMatrix(); }
	function disposeObject(root: any) { root?.traverse?.((node: any) => { if (!node.isMesh) return; node.geometry?.dispose?.(); for (const material of (Array.isArray(node.material) ? node.material : [node.material])) material?.dispose?.(); }); }

	async function texture(ref: string | undefined, role: string): Promise<any | null> {
		if (!ref) return null;
		const key = `${role}:${ref}`;
		if (!textureCache.has(key)) textureCache.set(key, new Promise((resolve) => new THREE.TextureLoader().load(
			opticalNavRasterAssetUrl(projectId, sceneId, ref),
			(value: any) => { value.colorSpace = role === 'base_color' ? THREE.SRGBColorSpace : THREE.NoColorSpace; textureLoaded++; resolve(value); },
			undefined,
			() => { textureFailed++; diagnostics = [...diagnostics, `texture load failed: ${ref}`].slice(-8); resolve(null); }
		)));
		return textureCache.get(key) ?? null;
	}

	async function makeMaterial(spec: RasterMaterial): Promise<any> {
		if (!spec.supported) { measuredSkipped++; return new THREE.MeshStandardMaterial({ color: 0xa21caf, roughness: 0.8, emissive: 0x26002a }); }
		const maps = await Promise.all([texture(spec.textures?.base_color, 'base_color'), texture(spec.textures?.normal, 'normal'), texture(spec.textures?.roughness, 'roughness'), texture(spec.textures?.metallic, 'metallic')]);
		const [r, g, b] = spec.base_color.length >= 3 ? spec.base_color : [0.65, 0.65, 0.65]; const dielectric = spec.bsdf_strategy === 'dielectric';
		return new THREE.MeshPhysicalMaterial({
			color: new THREE.Color(Number(r) || 0.65, Number(g) || 0.65, Number(b) || 0.65), map: maps[0], normalMap: maps[1], roughnessMap: maps[2], metalnessMap: maps[3],
			roughness: Math.max(0.025, Number(spec.roughness ?? 0.55)), metalness: spec.bsdf_strategy === 'roughconductor' ? 1 : Math.max(0, Math.min(1, Number(spec.metallic ?? 0))),
			ior: Math.max(1, Number(spec.ior ?? 1.5)), transmission: dielectric ? 0.92 : 0, opacity: Math.max(0.05, Math.min(1, Number(spec.opacity ?? 1))), transparent: dielectric || Number(spec.opacity ?? 1) < 1, side: THREE.DoubleSide,
		});
	}

	function applyTransform(group: any, transform: Record<string, unknown> = {}) {
		const translate = Array.isArray(transform.translate) ? transform.translate : [0, 0, 0]; const scale = Array.isArray(transform.scale) ? transform.scale : [1, 1, 1];
		group.position.set(Number(translate[0]) || 0, Number(translate[1]) || 0, Number(translate[2]) || 0); group.scale.set(Number(scale[0]) || 1, Number(scale[1]) || 1, Number(scale[2]) || 1);
		group.rotation.set(THREE.MathUtils.degToRad(Number(transform.rotate_x_deg) || 0), THREE.MathUtils.degToRad(Number(transform.rotate_y_deg) || 0), THREE.MathUtils.degToRad(Number(transform.rotate_z_deg) || 0));
	}

	async function loadShape(shape: RasterShape, manifest: RasterManifest, target: any, token: number) {
		const spec = manifest.materials[shape.material_key]; if (!spec) throw new Error(`missing material ${shape.material_key}`);
		const [obj, material] = await Promise.all([
			fetch(opticalNavMeshCacheUrl(projectId, sceneId, shape.mesh_ref)).then(async (response) => { if (!response.ok) throw new Error(`OBJ ${response.status}: ${shape.mesh_ref}`); return new OBJLoader().parse(await response.text()); }),
			makeMaterial(spec),
		]);
		if (token !== buildToken) { disposeObject(obj); material.dispose?.(); return; }
		obj.traverse((node: any) => { if (!node.isMesh) return; if (!node.geometry.getAttribute('normal')) node.geometry.computeVertexNormals(); node.material = material; node.castShadow = true; node.receiveShadow = true; node.userData.rasterMaterial = `${shape.shape_id} · ${spec.material_id ?? shape.material_key} · ${spec.bsdf_strategy}${spec.supported ? '' : ' · unsupported'}`; });
		applyTransform(obj, shape.transform); target.add(obj);
	}

	async function loadManifest(manifest: RasterManifest, reason: 'loading' | 'reloading') {
		const token = ++buildToken; status = reason; error = ''; loaded = 0; failed = 0; total = manifest.shapes.length; textureLoaded = 0; textureFailed = 0; measuredSkipped = 0; diagnostics = [];
		const shapes = prioritizeRasterShapes(manifest.shapes, pose);
		const nextGroup = new THREE.Group(); let nextIndex = 0;
		const previous = activeGroup; activeGroup = nextGroup; scene.add(nextGroup);
		if (previous) { scene.remove(previous); disposeObject(previous); }
		const worker = async () => { while (nextIndex < shapes.length && token === buildToken) { const shape = shapes[nextIndex++]; try { await loadShape(shape, manifest, nextGroup, token); loaded++; } catch (cause) { failed++; diagnostics = [...diagnostics, `${shape.shape_id || shape.mesh_ref}: ${String(cause)}`].slice(-8); } } };
		await Promise.all(Array.from({ length: 2 }, worker));
		if (token !== buildToken) { scene.remove(nextGroup); if (activeGroup === nextGroup) activeGroup = null; disposeObject(nextGroup); return; }
		currentRevision = manifest.revision; revision = manifest.revision; status = 'ready';
	}

	async function refresh(force = false) { try { const manifest = await getOpticalNavRasterScene(projectId, sceneId) as RasterManifest; if (shouldRefreshRasterManifest(force, status, manifest.revision, currentRevision)) await loadManifest(manifest, currentRevision ? 'reloading' : 'loading'); } catch (cause) { status = 'error'; error = cause instanceof Error ? cause.message : String(cause); } }

	async function initializePose(params: URLSearchParams) {
		if (!['x', 'y', 'z'].some((key) => params.has(key))) try { const graph = await getOpticalNavViewpointGraph(projectId, sceneId); const start = initialRasterPose(graph); if (start) pose = { ...pose, x: start.x, z: start.z, yaw: start.yawDeg }; else diagnostics = [...diagnostics, 'nav graph has no usable viewpoint; using origin']; } catch { diagnostics = [...diagnostics, 'nav graph unavailable; using origin']; }
		pose = { x: queryFiniteNumber(params, 'x', pose.x), y: queryFiniteNumber(params, 'y', pose.y), z: queryFiniteNumber(params, 'z', pose.z), yaw: queryFiniteNumber(params, 'yaw', pose.yaw), pitch: queryFiniteNumber(params, 'pitch', pose.pitch), fov: Math.max(20, Math.min(120, queryFiniteNumber(params, 'fov', pose.fov))) }; updateCamera();
	}

	function tick(now: number) {
		const dt = Math.min(0.05, (now - lastTick) / 1000 || 0); lastTick = now; const speed = (keys.has('ShiftLeft') || keys.has('ShiftRight') ? 8 : 2.5) * dt;
		const axes = rasterInputAxes({ w: keys.has('KeyW'), s: keys.has('KeyS'), a: keys.has('KeyA'), d: keys.has('KeyD') });
		const movement = rasterCameraMovement(pose.yaw, axes.forward * speed, axes.right * speed, (keys.has('KeyE') ? speed : 0) - (keys.has('KeyQ') ? speed : 0)); let { x, y, z } = pose;
		x += movement.x; y += movement.y; z += movement.z;
		if (x !== pose.x || y !== pose.y || z !== pose.z) { pose = { ...pose, x, y, z }; updateCamera(); } renderer?.render(scene, camera); if (lastFrame) fps = 1000 / Math.max(1, now - lastFrame); lastFrame = now; animation = requestAnimationFrame(tick);
	}

	function onCanvasClick(event: MouseEvent) {
		if (event.altKey && activeGroup && camera) {
			const rect = canvas.getBoundingClientRect(); const pointer = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
			const raycaster = new THREE.Raycaster(); raycaster.setFromCamera(pointer, camera); const hit = raycaster.intersectObject(activeGroup, true)[0]; selected = hit?.object?.userData?.rasterMaterial || 'no raster shape selected'; return;
		}
		canvas.requestPointerLock();
	}

	onMount(() => {
		const params = new URLSearchParams(location.search); projectId = params.get('project_id') || projectId; sceneId = params.get('scene_id') || sceneId;
		renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' }); renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.shadowMap.enabled = true; renderer.outputColorSpace = THREE.SRGBColorSpace;
		scene = new THREE.Scene(); scene.background = new THREE.Color(0x111827); camera = new THREE.PerspectiveCamera(pose.fov, 1, 0.02, 2000); scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 2.2)); const key = new THREE.DirectionalLight(0xffffff, 2.4); key.position.set(8, 12, 6); key.castShadow = true; scene.add(key); const fill = new THREE.DirectionalLight(0x9cc7ff, 0.7); fill.position.set(-8, 5, -5); scene.add(fill);
		const resize = () => { const width = innerWidth, height = innerHeight; renderer.setSize(width, height, false); camera.aspect = width / Math.max(1, height); camera.updateProjectionMatrix(); }; const mouseMove = (event: MouseEvent) => { if (document.pointerLockElement !== canvas) return; pose = { ...pose, yaw: pose.yaw - event.movementX * 0.13, pitch: Math.max(-89, Math.min(89, pose.pitch - event.movementY * 0.13)) }; updateCamera(); }; const down = (event: KeyboardEvent) => keys.add(event.code); const up = (event: KeyboardEvent) => keys.delete(event.code);
		resize(); window.addEventListener('resize', resize); window.addEventListener('mousemove', mouseMove); window.addEventListener('keydown', down); window.addEventListener('keyup', up); lastTick = performance.now(); animation = requestAnimationFrame(tick); void initializePose(params).then(() => refresh(true)); revisionTimer = setInterval(() => void refresh(false), 5000);
		return () => { window.removeEventListener('resize', resize); window.removeEventListener('mousemove', mouseMove); window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); };
	});

	onDestroy(() => { if (animation) cancelAnimationFrame(animation); if (revisionTimer) clearInterval(revisionTimer); disposeObject(activeGroup); renderer?.dispose?.(); for (const pending of textureCache.values()) void pending.then((value) => value?.dispose?.()); });
</script>

<svelte:head><title>OpticalNav Raster Free-Fly Viewer</title></svelte:head>
<main class="viewer">
	<canvas bind:this={canvas} aria-label="Raster free-fly viewer" onclick={onCanvasClick}></canvas>
	<section class="hud">
		<strong>RASTER FREE-FLY</strong><span class:bad={status === 'error'}>{status}</span><span>{sceneId} · rev {revision}</span>
		<span>{fps.toFixed(1)} fps · source meshes {loaded}/{total}{failed ? ` · failed ${failed}` : ''}</span><span>textures {textureLoaded} loaded{textureFailed ? ` · ${textureFailed} failed` : ''} · measured skip {measuredSkipped}</span>
		<span>FOV {pose.fov.toFixed(0)}° · x {pose.x.toFixed(2)} y {pose.y.toFixed(2)} z {pose.z.toFixed(2)}</span>
		{#if status === 'loading' || status === 'reloading'}
			<div class="load-progress" aria-live="polite">
				<span>{status === 'reloading' ? 'updating scene' : 'streaming scene'} · {completedMeshes}/{total} meshes · {loadPercent}%</span>
				<div class="progress-track" role="progressbar" aria-label="Raster scene loading progress" aria-valuemin="0" aria-valuemax={total} aria-valuenow={completedMeshes}><i style={`width: ${loadPercent}%`}></i></div>
				<small>{loaded ? 'Nearby geometry is visible now; remaining assets continue in the background.' : 'Fetching the nearest source meshes first…'}</small>
			</div>
		{/if}
		{#if selected}<span>selected: {selected}</span>{/if}
		{#if error}<span class="error">{error}</span>{/if}{#each diagnostics as message}<span class="diagnostic">{message}</span>{/each}
	</section>
	<section class="controls"><button onclick={() => void refresh(true)}>Reload scene</button><span>Click view · Alt+click inspect · WASD move · Q/E up/down · Shift fast · mouse look · Esc release</span><span>Source mesh + PBR debug preview · measured/polarized is intentionally unsupported</span></section>
</main>
<style>
	.viewer { position: fixed; inset: 0; overflow: hidden; background: #030712; color: #e5e7eb; font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; } canvas { width: 100%; height: 100%; display: block; cursor: crosshair; outline: none; }
	.hud, .controls { position: absolute; display: grid; gap: 5px; padding: 10px 12px; background: rgb(2 6 23 / 82%); border: 1px solid rgb(148 163 184 / 35%); border-radius: 6px; backdrop-filter: blur(4px); } .hud { top: 14px; left: 14px; max-width: min(760px, calc(100vw - 28px)); } .controls { left: 14px; bottom: 14px; max-width: min(760px, calc(100vw - 28px)); }
	.load-progress { display: grid; gap: 4px; padding-top: 3px; color: #bfdbfe; } .load-progress small { color: #cbd5e1; } .progress-track { height: 7px; overflow: hidden; border: 1px solid rgb(148 163 184 / 38%); border-radius: 999px; background: rgb(15 23 42 / 90%); } .progress-track i { display: block; height: 100%; min-width: 2px; border-radius: inherit; background: linear-gradient(90deg, #22d3ee, #2563eb); transition: width 160ms ease-out; }
	.controls button { width: max-content; background: #1d4ed8; color: white; border: 0; border-radius: 4px; padding: 6px 9px; cursor: pointer; } .bad, .error { color: #fca5a5; } .diagnostic { color: #fcd34d; overflow-wrap: anywhere; }
</style>
