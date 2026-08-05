<script lang="ts">
	import { createEventDispatcher, onDestroy, onMount } from 'svelte';
	import * as THREE from 'three';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
	import type { CameraRig, CameraRigMeshPayload, CameraRigSensor } from '$lib/api';

	export let rig: CameraRig | null = null;
	export let meshPayload: CameraRigMeshPayload | null = null;
	export let selectedSensorId: string | null = null;

	const dispatch = createEventDispatcher<{
		select: { sensor_id: string };
		move: { sensor_id: string; xyz_m: [number, number, number] };
	}>();

	let host: HTMLDivElement;
	let renderer: any = null;
	let scene: any;
	let camera: any;
	let controls: any;
	let animationFrame = 0;
	let robotMesh: any = null;
	let floorGrid: any = null;
	let orientationGroup = new THREE.Group();
	let resizeObserver: ResizeObserver | null = null;
	let raycaster = new THREE.Raycaster();
	let pointer = new THREE.Vector2();
	let dragSensorId: string | null = null;
	let dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
	let sensorGroup = new THREE.Group();
	let lightGroup = new THREE.Group();
	let sensorObjects = new Map<string, any>();
	let sensorPickTargets: any[] = [];

	const sensorColors: Record<string, number> = {
		rgb_camera: 0x3b82f6,
		nir_camera: 0x22c55e,
		polar_camera: 0xa855f7,
		lidar_3d: 0xf59e0b
	};

	function toThree(xyz: [number, number, number]) {
		return new THREE.Vector3(xyz[0], xyz[2], xyz[1]);
	}

	function fromThree(v: any): [number, number, number] {
		return [round3(v.x), round3(v.z), round3(v.y)];
	}

	function round3(value: number) {
		return Math.round(value * 1000) / 1000;
	}

	function sensorColor(sensor: CameraRigSensor) {
		return sensorColors[sensor.sensor_type] ?? 0x64748b;
	}

	function makeTextSprite(text: string, color = '#dc2626') {
		const canvas = document.createElement('canvas');
		canvas.width = 512;
		canvas.height = 128;
		const ctx = canvas.getContext('2d');
		if (ctx) {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			ctx.fillStyle = 'rgba(255, 255, 255, 0.92)';
			ctx.strokeStyle = 'rgba(220, 38, 38, 0.72)';
			ctx.lineWidth = 6;
			roundRect(ctx, 18, 22, 476, 84, 18);
			ctx.fill();
			ctx.stroke();
			ctx.fillStyle = color;
			ctx.font = '700 44px system-ui, -apple-system, Segoe UI, sans-serif';
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			ctx.fillText(text, 256, 64);
		}
		const texture = new THREE.CanvasTexture(canvas);
		texture.colorSpace = THREE.SRGBColorSpace;
		const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
		const sprite = new THREE.Sprite(material);
		sprite.scale.set(0.42, 0.105, 1);
		return sprite;
	}

	function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
		ctx.beginPath();
		ctx.moveTo(x + r, y);
		ctx.lineTo(x + w - r, y);
		ctx.quadraticCurveTo(x + w, y, x + w, y + r);
		ctx.lineTo(x + w, y + h - r);
		ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
		ctx.lineTo(x + r, y + h);
		ctx.quadraticCurveTo(x, y + h, x, y + h - r);
		ctx.lineTo(x, y + r);
		ctx.quadraticCurveTo(x, y, x + r, y);
		ctx.closePath();
	}

	function addOrientationMarker() {
		orientationGroup.name = 'robot_front_marker';
		orientationGroup.position.set(0, 0.025, 0);
		const arrow = new THREE.ArrowHelper(
			new THREE.Vector3(0, 0, 1),
			new THREE.Vector3(0, 0, -0.44),
			0.92,
			0xdc2626,
			0.16,
			0.09
		);
		orientationGroup.add(arrow);
		const line = new THREE.Line(
			new THREE.BufferGeometry().setFromPoints([
				new THREE.Vector3(-0.18, 0, 0.42),
				new THREE.Vector3(0, 0, 0.56),
				new THREE.Vector3(0.18, 0, 0.42)
			]),
			new THREE.LineBasicMaterial({ color: 0xdc2626, transparent: true, opacity: 0.7 })
		);
		orientationGroup.add(line);
		const label = makeTextSprite('FRONT +Y');
		label.position.set(0, 0.16, 0.72);
		orientationGroup.add(label);
		scene.add(orientationGroup);
	}

	function initScene() {
		scene = new THREE.Scene();
		scene.background = new THREE.Color(0xf8fafc);
		camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100);
		camera.position.set(1.8, 1.4, 1.8);
		renderer = new THREE.WebGLRenderer({ antialias: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
		renderer.shadowMap.enabled = true;
		host.appendChild(renderer.domElement);

		controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;
		controls.target.set(0, 0.35, 0);

		const hemi = new THREE.HemisphereLight(0xffffff, 0xb6beca, 1.9);
		scene.add(hemi);
		const key = new THREE.DirectionalLight(0xffffff, 2.2);
		key.position.set(3, 5, 4);
		scene.add(key);

		floorGrid = new THREE.GridHelper(2.8, 28, 0xcbd5e1, 0xe2e8f0);
		floorGrid.position.y = -0.01;
		scene.add(floorGrid);
		addOrientationMarker();
		scene.add(sensorGroup);
		scene.add(lightGroup);

		renderer.domElement.addEventListener('pointerdown', onPointerDown);
		renderer.domElement.addEventListener('pointermove', onPointerMove);
		renderer.domElement.addEventListener('pointerup', onPointerUp);
		renderer.domElement.addEventListener('pointerleave', onPointerUp);
		resizeObserver = new ResizeObserver(resize);
		resizeObserver.observe(host);
		resize();
		animate();
	}

	function resize() {
		if (!renderer || !host) return;
		const rect = host.getBoundingClientRect();
		const width = Math.max(1, rect.width);
		const height = Math.max(1, rect.height);
		renderer.setSize(width, height, false);
		camera.aspect = width / height;
		camera.updateProjectionMatrix();
	}

	function animate() {
		animationFrame = requestAnimationFrame(animate);
		controls?.update();
		renderer?.render(scene, camera);
	}

	function clearRobotMesh() {
		if (!robotMesh) return;
		scene.remove(robotMesh);
		robotMesh.geometry.dispose();
		const material = robotMesh.material;
		if (Array.isArray(material)) material.forEach((m) => m.dispose());
		else material.dispose();
		robotMesh = null;
	}

	function rebuildRobotMesh() {
		if (!scene) return;
		clearRobotMesh();
		if (!meshPayload?.vertices?.length || !meshPayload.indices?.length) return;
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', new THREE.Float32BufferAttribute(meshPayload.vertices, 3));
		geometry.setIndex(meshPayload.indices);
		geometry.computeVertexNormals();
		geometry.computeBoundingBox();
		const material = new THREE.MeshStandardMaterial({
			color: meshPayload.status === 'ready' ? 0x334155 : 0x475569,
			roughness: 0.72,
			metalness: 0.05
		});
		robotMesh = new THREE.Mesh(geometry, material);
		robotMesh.castShadow = true;
		robotMesh.receiveShadow = true;
		scene.add(robotMesh);
		// Drop the ground grid to the robot's lowest point (wheel bottoms) so the
		// body rests on the plane instead of being half-buried: the mesh keeps the
		// base_link origin (y≈0 is mid-body), so the origin plane cuts the wheels.
		// Read straight from the computed bounding box — independent of payload shape.
		if (floorGrid && geometry.boundingBox) {
			floorGrid.position.y = geometry.boundingBox.min.y;
		}
	}

	function frustumGeometry(sensor: CameraRigSensor) {
		const near = Math.max(0.02, sensor.intrinsics.clip_near_m);
		const far = Math.min(Math.max(near + 0.05, sensor.intrinsics.clip_far_m), 1.0);
		const hFar = 2 * Math.tan(THREE.MathUtils.degToRad(sensor.intrinsics.fov_h_deg) / 2) * far;
		const vFar = 2 * Math.tan(THREE.MathUtils.degToRad(sensor.intrinsics.fov_v_deg) / 2) * far;
		const vertices = new Float32Array([
			0, 0, 0,
			-hFar / 2, -vFar / 2, far,
			hFar / 2, -vFar / 2, far,
			hFar / 2, vFar / 2, far,
			-hFar / 2, vFar / 2, far
		]);
		const indices = [
			0, 1, 0, 2, 0, 3, 0, 4,
			1, 2, 2, 3, 3, 4, 4, 1
		];
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
		geometry.setIndex(indices);
		return geometry;
	}

	function rebuildSensors() {
		if (!scene) return;
		sensorObjects.clear();
		sensorPickTargets = [];
		while (sensorGroup.children.length) {
			const child = sensorGroup.children.pop();
			if (!child) continue;
			child.traverse((obj: any) => {
				const mesh = obj;
				if (mesh.geometry) mesh.geometry.dispose();
				const material = mesh.material;
				if (Array.isArray(material)) material.forEach((m) => m.dispose());
				else material?.dispose?.();
			});
		}
		for (const sensor of rig?.sensors ?? []) {
			const group = new THREE.Group();
			group.name = sensor.sensor_id;
			group.userData.sensor_id = sensor.sensor_id;
			group.position.copy(toThree(sensor.mount.xyz_m));
			group.rotation.set(
				THREE.MathUtils.degToRad(sensor.mount.rpy_deg[0]),
				THREE.MathUtils.degToRad(sensor.mount.rpy_deg[2]),
				THREE.MathUtils.degToRad(sensor.mount.rpy_deg[1])
			);
			const selected = sensor.sensor_id === selectedSensorId;
			const color = sensorColor(sensor);
			const body = new THREE.Mesh(
				new THREE.BoxGeometry(0.08, 0.055, 0.05),
				new THREE.MeshStandardMaterial({
					color,
					emissive: selected ? color : 0x000000,
					emissiveIntensity: selected ? 0.22 : 0,
					roughness: 0.5
				})
			);
			body.userData.sensor_id = sensor.sensor_id;
			body.userData.pickable_sensor = true;
			group.add(body);
			const lens = new THREE.Mesh(
				new THREE.CylinderGeometry(0.018, 0.018, 0.018, 20),
				new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.35 })
			);
			lens.rotation.x = Math.PI / 2;
			lens.position.z = 0.035;
			lens.userData.sensor_id = sensor.sensor_id;
			lens.userData.pickable_sensor = true;
			group.add(lens);
			const hitBubble = new THREE.Mesh(
				new THREE.SphereGeometry(0.085, 16, 12),
				new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
			);
			hitBubble.userData.sensor_id = sensor.sensor_id;
			hitBubble.userData.pickable_sensor = true;
			group.add(hitBubble);
			sensorPickTargets.push(body, lens, hitBubble);
			if (sensor.sensor_type !== 'lidar_3d') {
				const line = new THREE.LineSegments(
					frustumGeometry(sensor),
					new THREE.LineBasicMaterial({ color, transparent: true, opacity: selected ? 0.85 : 0.45 })
				);
				line.userData.sensor_id = sensor.sensor_id;
				group.add(line);
			} else {
				const ring = new THREE.Mesh(
					new THREE.TorusGeometry(0.12, 0.004, 8, 72),
					new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55 })
				);
				ring.rotation.x = Math.PI / 2;
				ring.userData.sensor_id = sensor.sensor_id;
				group.add(ring);
			}
			sensorObjects.set(sensor.sensor_id, group);
			sensorGroup.add(group);
		}
	}

	// Rig-mounted active lights (RGB/NIR flash + optional linear polarizer).
	// Mount convention matches sensors (toThree + rpy z/x swap); beam points +z.
	function rebuildLights() {
		if (!scene) return;
		while (lightGroup.children.length) {
			const child = lightGroup.children.pop();
			if (!child) continue;
			child.traverse((obj: any) => {
				if (obj.geometry) obj.geometry.dispose();
				const material = obj.material;
				if (Array.isArray(material)) material.forEach((m) => m.dispose());
				else material?.dispose?.();
			});
		}
		for (const light of rig?.active_lights ?? []) {
			const group = new THREE.Group();
			group.name = light.light_id;
			group.position.copy(toThree(light.mount.xyz_m));
			group.rotation.set(
				THREE.MathUtils.degToRad(light.mount.rpy_deg[0]),
				THREE.MathUtils.degToRad(light.mount.rpy_deg[2]),
				THREE.MathUtils.degToRad(light.mount.rpy_deg[1])
			);
			const on = light.enabled !== false;
			const col = light.spectrum_kind === 'nir' ? 0xd946ef : 0xf59e0b;
			const bulb = new THREE.Mesh(
				new THREE.SphereGeometry(0.026, 16, 12),
				new THREE.MeshStandardMaterial({
					color: col,
					emissive: col,
					emissiveIntensity: on ? 0.7 : 0.12,
					roughness: 0.4
				})
			);
			group.add(bulb);
			if (light.emitter_type === 'area') {
				const s = Math.max(0.04, light.area_size_m);
				const plane = new THREE.Mesh(
					new THREE.PlaneGeometry(s * 2, s * 2),
					new THREE.MeshBasicMaterial({
						color: col,
						transparent: true,
						opacity: on ? 0.28 : 0.1,
						side: THREE.DoubleSide,
						depthWrite: false
					})
				);
				group.add(plane); // PlaneGeometry normal is +z (forward)
			} else if (light.emitter_type === 'spot') {
				const h = 0.28;
				const half = Math.min(80, Math.max(2, light.cutoff_angle_deg));
				const r = h * Math.tan(THREE.MathUtils.degToRad(half));
				const cone = new THREE.Mesh(
					new THREE.ConeGeometry(r, h, 28, 1, true),
					new THREE.MeshBasicMaterial({
						color: col,
						transparent: true,
						opacity: on ? 0.16 : 0.06,
						side: THREE.DoubleSide,
						depthWrite: false
					})
				);
				cone.rotation.x = -Math.PI / 2; // apex at emitter, opening toward +z
				cone.position.z = h / 2;
				group.add(cone);
			} else {
				const glow = new THREE.Mesh(
					new THREE.SphereGeometry(0.05, 16, 12),
					new THREE.MeshBasicMaterial({
						color: col,
						transparent: true,
						opacity: on ? 0.14 : 0.05,
						depthWrite: false
					})
				);
				group.add(glow);
			}
			if (light.polarized) {
				const ring = new THREE.Mesh(
					new THREE.TorusGeometry(0.044, 0.005, 8, 40),
					new THREE.MeshBasicMaterial({ color: 0x0ea5e9, transparent: true, opacity: 0.9 })
				);
				ring.rotation.z = THREE.MathUtils.degToRad(light.polarizer_angle_deg); // faces +z
				ring.position.z = 0.006;
				group.add(ring);
			}
			lightGroup.add(group);
		}
	}

	function updatePointer(event: PointerEvent) {
		if (!renderer) return;
		const rect = renderer.domElement.getBoundingClientRect();
		pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
		pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
	}

	function pickSensor(event: PointerEvent) {
		updatePointer(event);
		raycaster.setFromCamera(pointer, camera);
		const hits = raycaster.intersectObjects(sensorPickTargets, true);
		for (const hit of hits) {
			let obj: any = hit.object;
			while (obj) {
				const sensorId = obj.userData.sensor_id;
				if (obj.userData.pickable_sensor === true && typeof sensorId === 'string') return sensorId;
				obj = obj.parent;
			}
		}
		return null;
	}

	function onPointerDown(event: PointerEvent) {
		const sensorId = pickSensor(event);
		if (!sensorId) return;
		dispatch('select', { sensor_id: sensorId });
		dragSensorId = sensorId;
		const sensor = sensorObjects.get(sensorId);
		dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -(sensor?.position.y ?? 0));
		controls.enabled = false;
		renderer?.domElement.setPointerCapture(event.pointerId);
	}

	function onPointerMove(event: PointerEvent) {
		if (!dragSensorId) return;
		updatePointer(event);
		raycaster.setFromCamera(pointer, camera);
		const hit = new THREE.Vector3();
		if (!raycaster.ray.intersectPlane(dragPlane, hit)) return;
		const object = sensorObjects.get(dragSensorId);
		if (!object) return;
		object.position.copy(hit);
		dispatch('move', { sensor_id: dragSensorId, xyz_m: fromThree(hit) });
	}

	function onPointerUp(event: PointerEvent) {
		if (!dragSensorId) return;
		dragSensorId = null;
		controls.enabled = true;
		try {
			renderer?.domElement.releasePointerCapture(event.pointerId);
		} catch {
			/* pointer may already be released */
		}
	}

	export function setView(mode: '3d' | 'top' | 'front' | 'side') {
		if (!camera || !controls) return;
		const target = new THREE.Vector3(0, 0.35, 0);
		controls.target.copy(target);
		if (mode === 'top') camera.position.set(0, 2.8, 0.001);
		else if (mode === 'front') camera.position.set(0, 0.75, 2.6);
		else if (mode === 'side') camera.position.set(2.6, 0.75, 0);
		else camera.position.set(1.8, 1.4, 1.8);
		camera.lookAt(target);
		controls.update();
	}

	onMount(() => {
		initScene();
		return () => {
			cancelAnimationFrame(animationFrame);
			resizeObserver?.disconnect();
			if (renderer) {
				renderer.domElement.removeEventListener('pointerdown', onPointerDown);
				renderer.domElement.removeEventListener('pointermove', onPointerMove);
				renderer.domElement.removeEventListener('pointerup', onPointerUp);
				renderer.domElement.removeEventListener('pointerleave', onPointerUp);
				renderer.dispose();
				renderer.domElement.remove();
			}
		};
	});

	onDestroy(() => {
		clearRobotMesh();
		orientationGroup.traverse((obj: any) => {
			obj.geometry?.dispose?.();
			const material = obj.material;
			if (Array.isArray(material)) material.forEach((m) => m.dispose?.());
			else material?.dispose?.();
			material?.map?.dispose?.();
		});
	});

	$: if (scene && meshPayload) rebuildRobotMesh();
	$: if (scene && rig && selectedSensorId !== undefined) rebuildSensors();
	$: if (scene && rig) rebuildLights();
</script>

<div class="rig-viewport" bind:this={host}></div>

<style>
	.rig-viewport {
		position: absolute;
		inset: 0;
		overflow: hidden;
		background: #f8fafc;
	}

	.rig-viewport :global(canvas) {
		width: 100%;
		height: 100%;
		display: block;
	}
</style>
