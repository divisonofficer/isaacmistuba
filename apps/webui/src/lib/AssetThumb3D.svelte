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

	let imgSrc = $state('');

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

	function addBox(group: any, size: [number, number, number], pos: [number, number, number], color: number, opts: Record<string, any> = {}, isSelected: boolean) {
		const geo = new THREE.BoxGeometry(size[0], size[1], size[2]);
		const { physical, ...restOpts } = opts;
		const material = physical
			? new THREE.MeshPhysicalMaterial({ color, ...restOpts })
			: new THREE.MeshStandardMaterial({ color, roughness: 0.65, metalness: 0, ...restOpts });
		const mesh = new THREE.Mesh(geo, material);
		mesh.position.set(pos[0], pos[1], pos[2]);
		group.add(mesh);
		const edges = new THREE.LineSegments(
			new THREE.EdgesGeometry(geo),
			new THREE.LineBasicMaterial({ color: isSelected ? 0xf59e0b : 0x475569, transparent: true, opacity: isSelected ? 1 : 0.42 })
		);
		edges.position.copy(mesh.position);
		group.add(edges);
	}

	function addCylinder(group: any, radius: number, height: number, pos: [number, number, number], color: number, opts: Record<string, any> = {}, isSelected: boolean) {
		const geo = new THREE.CylinderGeometry(radius, radius, height, 28);
		const material = new THREE.MeshStandardMaterial({ color, roughness: 0.62, metalness: 0, ...opts });
		const mesh = new THREE.Mesh(geo, material);
		mesh.position.set(pos[0], pos[1], pos[2]);
		group.add(mesh);
		if (isSelected) {
			const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.9 }));
			edges.position.copy(mesh.position);
			group.add(edges);
		}
		return mesh;
	}

	function addSphere(group: any, radius: number, pos: [number, number, number], color: number, opts: Record<string, any> = {}) {
		const geo = new THREE.SphereGeometry(radius, 24, 16);
		const material = new THREE.MeshStandardMaterial({ color, roughness: 0.58, metalness: 0, ...opts });
		const mesh = new THREE.Mesh(geo, material);
		mesh.position.set(pos[0], pos[1], pos[2]);
		group.add(mesh);
		return mesh;
	}

	function addTorus(group: any, radius: number, tube: number, pos: [number, number, number], color: number) {
		const geo = new THREE.TorusGeometry(radius, tube, 12, 32);
		const material = new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0 });
		const mesh = new THREE.Mesh(geo, material);
		mesh.position.set(pos[0], pos[1], pos[2]);
		group.add(mesh);
		return mesh;
	}

	function buildThumbShape(group: any, isSelected: boolean) {
		const color = colorForCategory(category);
		const key = assetType.toLowerCase();
		if (key.includes('chair') || key.includes('couch') || key.includes('bench') || key.includes('sideboard')) {
			addBox(group, [0.46, 0.12, 0.42], [0, 0.32, 0], color, {}, isSelected);
			addBox(group, [0.46, 0.58, 0.10], [0, 0.60, -0.20], color, {}, isSelected);
			for (const x of [-0.17, 0.17]) for (const z of [-0.14, 0.14]) addBox(group, [0.07, 0.32, 0.07], [x, 0.16, z], color, {}, isSelected);
			return;
		}
		if (key.includes('table') || key.includes('desk')) {
			addBox(group, [0.76, 0.12, 0.50], [0, 0.52, 0], color, {}, isSelected);
			for (const x of [-0.29, 0.29]) for (const z of [-0.18, 0.18]) addBox(group, [0.07, 0.50, 0.07], [x, 0.25, z], color, {}, isSelected);
			return;
		}
		if (key.includes('plant') || key.includes('palm') || key.includes('pot')) {
			addBox(group, [0.28, 0.34, 0.28], [0, 0.17, 0], 0x64748b, {}, isSelected);
			addBox(group, [0.12, 0.34, 0.12], [0, 0.48, 0], 0x166534, {}, isSelected);
			addBox(group, [0.44, 0.34, 0.44], [0, 0.72, 0], 0x15803d, {}, isSelected);
			return;
		}
		if (key.includes('teapot')) {
			addSphere(group, 0.24, [0, 0.36, 0], 0xf8fafc);
			addCylinder(group, 0.11, 0.12, [0, 0.58, 0], 0xf8fafc, {}, isSelected);
			const spout = addCylinder(group, 0.035, 0.32, [0.27, 0.42, 0], 0xf8fafc, {}, isSelected);
			spout.rotation.z = Math.PI / 2.8;
			const handle = addTorus(group, 0.17, 0.025, [-0.26, 0.42, 0], 0xf8fafc);
			handle.rotation.y = Math.PI / 2;
			return;
		}
		if (key.includes('bowl') || key.includes('dish')) {
			const bowl = addCylinder(group, 0.28, 0.12, [0, 0.22, 0], key.includes('dish') ? 0x3b82f6 : 0x22c55e, {}, isSelected);
			bowl.scale.y = key.includes('dish') ? 0.45 : 1;
			addTorus(group, 0.28, 0.018, [0, key.includes('dish') ? 0.25 : 0.3, 0], 0xf8fafc);
			return;
		}
		if (key.includes('cup') || key.includes('candle') || key.includes('can') || key.includes('bottle') || key.includes('air duster')) {
			addCylinder(group, key.includes('cup') ? 0.17 : 0.13, key.includes('bottle') ? 0.56 : 0.38, [0, key.includes('bottle') ? 0.32 : 0.25, 0], key.includes('cup') ? 0xfb923c : 0x64748b, {}, isSelected);
			if (key.includes('cup')) {
				const handle = addTorus(group, 0.11, 0.018, [0.2, 0.29, 0], 0xfb923c);
				handle.rotation.y = Math.PI / 2;
			}
			return;
		}
		if (key.includes('vase') || key.includes('pottery')) {
			addCylinder(group, 0.18, 0.52, [0, 0.32, 0], key.includes('blue') ? 0x3b82f6 : 0xb45309, {}, isSelected);
			addCylinder(group, 0.1, 0.18, [0, 0.64, 0], key.includes('blue') ? 0x60a5fa : 0xd97706, {}, isSelected);
			return;
		}
		if (key.includes('spoon') || key.includes('knife') || key.includes('marker') || key.includes('key')) {
			const metal = key.includes('knife') || key.includes('key') ? 0xcbd5e1 : key.includes('marker') ? 0xf97316 : 0x22c55e;
			addBox(group, [0.12, 0.05, 0.64], [0, 0.26, 0], metal, { metalness: key.includes('knife') || key.includes('key') ? 0.35 : 0 }, isSelected);
			if (key.includes('spoon')) addSphere(group, 0.12, [0, 0.27, 0.34], metal);
			return;
		}
		if (key.includes('hammer') || key.includes('dumbbell')) {
			addBox(group, [0.12, 0.08, 0.58], [0, 0.25, 0], 0x92400e, {}, isSelected);
			addBox(group, key.includes('hammer') ? [0.36, 0.16, 0.12] : [0.2, 0.2, 0.2], [0, 0.33, -0.25], 0x64748b, { metalness: 0.3 }, isSelected);
			if (key.includes('dumbbell')) addBox(group, [0.2, 0.2, 0.2], [0, 0.33, 0.25], 0x64748b, { metalness: 0.3 }, isSelected);
			return;
		}
		if (key.includes('speaker') || key.includes('camera')) {
			addBox(group, [0.48, 0.34, 0.24], [0, 0.32, 0], 0x1f2937, {}, isSelected);
			addCylinder(group, 0.11, 0.035, [0, 0.33, -0.13], 0x0f172a, {}, isSelected).rotation.x = Math.PI / 2;
			return;
		}
		if (key.includes('rug')) {
			addBox(group, [0.72, 0.05, 0.48], [0, 0.08, 0], 0x6ee7b7, {}, isSelected);
			return;
		}
		const size = sizeForBounds(bounds);
		const materialOpts = category === 'glass'
			? { physical: true, transparent: true, opacity: 0.38, roughness: 0.02 }
			: { roughness: category === 'mirror' ? 0.12 : 0.65, metalness: category === 'mirror' ? 0.8 : 0 };
		addBox(group, size, [0, size[1] * 0.5, 0], color, materialOpts, isSelected);
	}

	// Render a single frame off-screen and return a PNG data URL.
	// The WebGL context is created and destroyed within this call.
	function renderToDataUrl(isSelected: boolean): string {
		const SIZE = 84; // 2× for crispness at 42px CSS
		const canvas = document.createElement('canvas');
		canvas.width = SIZE;
		canvas.height = SIZE;

		let r: any = null;
		try {
			r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
			r.setPixelRatio(1);
			r.setSize(SIZE, SIZE, false);

			const sc = new THREE.Scene();
			const cam = new THREE.PerspectiveCamera(36, 1, 0.1, 20);
			cam.position.set(1.7, 1.4, 1.8);
			cam.lookAt(0, 0.35, 0);

			const root = new THREE.Group();
			root.rotation.y = -0.45;
			sc.add(root);
			sc.add(new THREE.AmbientLight(0xffffff, 1.2));
			const light = new THREE.DirectionalLight(0xffffff, 1.3);
			light.position.set(2, 4, 3);
			sc.add(light);

			buildThumbShape(root, isSelected);
			r.render(sc, cam);

			return canvas.toDataURL('image/png');
		} finally {
			r?.forceContextLoss?.();
			r?.dispose?.();
		}
	}

	// Re-render when any visual input changes
	$effect(() => {
		// Track all reactive inputs
		void category; void assetType; void bounds; void selected;
		if (typeof window === 'undefined') return;
		imgSrc = renderToDataUrl(selected);
	});

	onMount(() => {
		imgSrc = renderToDataUrl(selected);
	});
</script>

<div class="asset-thumb" aria-hidden="true">
	{#if imgSrc}
		<img src={imgSrc} alt="" draggable="false" />
	{/if}
</div>

<style>
	.asset-thumb {
		width: 100%;
		height: 100%;
		min-width: 42px;
		min-height: 42px;
		border-radius: 8px;
		background: linear-gradient(180deg, rgba(248,250,252,0.96), rgba(226,232,240,0.9));
		overflow: hidden;
		flex-shrink: 0;
	}
	.asset-thumb img {
		display: block;
		width: 100%;
		height: 100%;
		border-radius: inherit;
	}
</style>
