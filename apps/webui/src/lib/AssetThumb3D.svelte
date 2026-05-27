<script lang="ts">
	import { onMount } from 'svelte';
	import * as THREE from 'three';

	let {
		category = 'object',
		assetType = '',
		bounds = null,
		selected = false
	}: {
		category?: string;
		assetType?: string;
		bounds?: any;
		selected?: boolean;
	} = $props();

	let host = $state<HTMLDivElement | null>(null);
	let renderer: any = null;
	let scene3D: any = null;
	let camera: any = null;
	let root: any = null;
	let frame = 0;

	function colorForCategory(value: string) {
		const map: Record<string, number> = {
			glass: 0x67e8f9,
			mirror: 0x64748b,
			furniture: 0x9a5a24,
			shell: 0x222222,
			floor: 0x86efac,
			goal: 0x60a5fa,
			start: 0x818cf8,
			hazard: 0xfb923c,
			forbidden: 0xef4444,
			object: 0x94a3b8
		};
		return map[value] ?? 0x94a3b8;
	}

	function sizeForBounds(payload: any): [number, number, number] {
		const raw = payload?.size ?? null;
		if (Array.isArray(raw) && raw.length >= 3) {
			const scale = Math.max(raw[0], raw[1], raw[2], 0.001);
			return [
				Math.max(0.12, raw[0] / scale),
				Math.max(0.12, raw[1] / scale),
				Math.max(0.12, raw[2] / scale)
			];
		}
		if (category === 'glass' || category === 'mirror' || category === 'shell') return [0.18, 0.9, 0.7];
		return [0.55, 0.45, 0.55];
	}

	function addBox(group: any, size: [number, number, number], pos: [number, number, number], color: number, materialOptions: Record<string, any> = {}) {
		const geo = new THREE.BoxGeometry(size[0], size[1], size[2]);
		const material = materialOptions.physical
			? new THREE.MeshPhysicalMaterial({ color, ...materialOptions })
			: new THREE.MeshStandardMaterial({ color, roughness: 0.65, metalness: 0, ...materialOptions });
		const mesh = new THREE.Mesh(geo, material);
		mesh.position.set(pos[0], pos[1], pos[2]);
		group.add(mesh);
		const edges = new THREE.LineSegments(
			new THREE.EdgesGeometry(geo),
			new THREE.LineBasicMaterial({ color: selected ? 0xf59e0b : 0x475569, transparent: true, opacity: selected ? 1 : 0.42 })
		);
		edges.position.copy(mesh.position);
		group.add(edges);
	}

	function buildThumbShape(group: any) {
		const color = colorForCategory(category);
		if (assetType === 'chair') {
			addBox(group, [0.46, 0.12, 0.42], [0, 0.32, 0], color);
			addBox(group, [0.46, 0.58, 0.10], [0, 0.60, -0.20], color);
			for (const x of [-0.17, 0.17]) for (const z of [-0.14, 0.14]) addBox(group, [0.07, 0.32, 0.07], [x, 0.16, z], color);
			return;
		}
		if (assetType === 'table') {
			addBox(group, [0.76, 0.12, 0.50], [0, 0.52, 0], color);
			for (const x of [-0.29, 0.29]) for (const z of [-0.18, 0.18]) addBox(group, [0.07, 0.50, 0.07], [x, 0.25, z], color);
			return;
		}
		if (assetType === 'plant') {
			addBox(group, [0.28, 0.34, 0.28], [0, 0.17, 0], 0x64748b);
			addBox(group, [0.12, 0.34, 0.12], [0, 0.48, 0], 0x166534);
			addBox(group, [0.44, 0.34, 0.44], [0, 0.72, 0], 0x15803d);
			return;
		}
		const size = sizeForBounds(bounds);
		const materialOptions = category === 'glass'
			? { physical: true, transparent: true, opacity: 0.38, roughness: 0.02 }
			: { roughness: category === 'mirror' ? 0.12 : 0.65, metalness: category === 'mirror' ? 0.8 : 0 };
		addBox(group, size, [0, size[1] * 0.5, 0], color, materialOptions);
	}

	function rebuild() {
		if (!root) return;
		for (const child of [...root.children]) {
			root.remove(child);
			child.geometry?.dispose?.();
			child.material?.dispose?.();
		}
		buildThumbShape(root);
	}

	function init() {
		if (!host || renderer) return;
		renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
		host.appendChild(renderer.domElement);
		scene3D = new THREE.Scene();
		camera = new THREE.PerspectiveCamera(36, 1, 0.1, 20);
		camera.position.set(1.7, 1.4, 1.8);
		camera.lookAt(0, 0.35, 0);
		root = new THREE.Group();
		root.rotation.y = -0.45;
		scene3D.add(root);
		scene3D.add(new THREE.AmbientLight(0xffffff, 1.2));
		const light = new THREE.DirectionalLight(0xffffff, 1.3);
		light.position.set(2, 4, 3);
		scene3D.add(light);
		const resize = () => {
			if (!host || !renderer || !camera) return;
			const w = Math.max(1, host.clientWidth);
			const h = Math.max(1, host.clientHeight);
			renderer.setSize(w, h, false);
			camera.aspect = w / h;
			camera.updateProjectionMatrix();
		};
		resize();
		rebuild();
		const loop = () => {
			frame = requestAnimationFrame(loop);
			root.rotation.y += 0.003;
			renderer.render(scene3D, camera);
		};
		loop();
	}

	onMount(() => {
		init();
		return () => {
			if (frame) cancelAnimationFrame(frame);
			renderer?.dispose?.();
			renderer?.domElement?.remove?.();
		};
	});

	$effect(() => {
		category;
		assetType;
		bounds;
		selected;
		if (renderer) rebuild();
	});
</script>

<div class="asset-thumb" bind:this={host} aria-hidden="true"></div>

<style>
	.asset-thumb {
		width: 42px;
		height: 42px;
		border-radius: 8px;
		background: linear-gradient(180deg, rgba(248,250,252,0.96), rgba(226,232,240,0.9));
		overflow: hidden;
	}
	.asset-thumb :global(canvas) {
		display: block;
		width: 100% !important;
		height: 100% !important;
	}
</style>
