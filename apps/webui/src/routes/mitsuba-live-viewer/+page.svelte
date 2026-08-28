<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { opticalNavLivePreviewWsUrl } from '$lib/api';
	import { MITSUBA_FROZEN_VIEWER, liveViewerHost } from '$lib/liveViewerProfiles';

	type Pose = { x: number; y: number; z: number; yaw_deg: number; pitch_deg: number; fov_deg: number };
	type Connection = 'offline' | 'connecting' | 'warming' | 'recording' | 'ready' | 'reloading' | 'error';
	type LoadEstimate = {
		texture_count: number; shape_count: number; first_frame_lower_s: number; first_frame_upper_s: number;
		load_lower_s: number; load_upper_s: number; record_lower_s: number; record_upper_s: number;
	};
	const LOAD_STEPS = [
		{ phase: 'variant', label: 'CUDA renderer' },
		{ phase: 'materials', label: 'Frozen BSDF compatibility' },
		{ phase: 'scene', label: 'Geometry and textures' },
		{ phase: 'sensor', label: 'Camera and film' },
		{ phase: 'freeze', label: 'Frozen CUDA graph' },
		{ phase: 'record', label: 'First-frame recording' }
	] as const;
	const LIVE_SPP_VALUES = [1, 2, 4, 8, 16, 32, 64, 128, 256] as const;
	const LIVE_RESOLUTION_VALUES = [
		{ width: 256, height: 192 }, { width: 384, height: 288 }, { width: 512, height: 384 },
		{ width: 640, height: 360 }, { width: 640, height: 480 }, { width: 768, height: 576 }, { width: 1024, height: 768 }
	] as const;

	let canvas: HTMLCanvasElement;
	let projectId = $state('opticalnav-v0.2');
	let sceneId = $state('infinigen_indoor_002');
	let liveHost = $state('');
	let endpoint = $state('—');
	let pose = $state<Pose>({ x: 0, y: 1.5, z: 0, yaw_deg: 0, pitch_deg: 0, fov_deg: 70 });
	let connection = $state<Connection>('offline');
	let error = $state('');
	let revision = $state('—');
	let renderMs = $state(0); let dispatchMs = $state(0); let evalMs = $state(0); let encodeMs = $state(0); let ipcMs = $state(0);
	let rendererMode = $state('—'); let frozenStage = $state('—'); let recordMs = $state(0); let replayMs = $state(0); let frameSize = $state('—');
	let requestedSpp = $state(1); let appliedSpp = $state(1); let requestedResolution = $state<{ width: number; height: number }>({ width: 640, height: 360 });
	let progressDetail = $state('Connecting to Mitsuba daemon'); let progressPhase = $state('connecting'); let progressStartedAt = $state(0); let progressSeconds = $state(0); let loadEstimate = $state<LoadEstimate | null>(null);
	let displayFps = $state(0); let lastFrameAt = 0; let lastSequence = -1; let frameUrl = $state('');
	let ws: WebSocket | null = null; let animation = 0; let lastTick = 0; const keys = new Set<string>(); let lastSent = 0;

	function selectedHost() { return liveViewerHost(liveHost, location.hostname || '127.0.0.1'); }
	function coldStartEstimateText() {
		if (!loadEstimate) return 'Cold-start time is being estimated from the scene XML.';
		const { first_frame_lower_s: lower, first_frame_upper_s: upper, texture_count: textures, shape_count: shapes } = loadEstimate;
		if (progressSeconds > upper) return `Past the ${lower}–${upper} s cold-start range; texture upload or CUDA compilation is still running.`;
		return `Cold-start estimate ${lower}–${upper} s · ${textures.toLocaleString()} textures · ${shapes.toLocaleString()} shapes.`;
	}
	function stepState(phase: string) {
		const current = LOAD_STEPS.findIndex((step) => step.phase === progressPhase);
		const index = LOAD_STEPS.findIndex((step) => step.phase === phase);
		if (progressPhase === 'estimate' || progressPhase === 'connecting') return 'pending';
		if (current < 0) return 'pending';
		return index < current ? 'done' : index === current ? 'active' : 'pending';
	}
	function rasterizationUrl() {
		const query = new URLSearchParams({
			project_id: projectId, scene_id: sceneId,
			x: String(pose.x), y: String(pose.y), z: String(pose.z),
			yaw: String(pose.yaw_deg), pitch: String(pose.pitch_deg), fov: String(pose.fov_deg)
		});
		return `/live-viewer?${query}`;
	}
	function openRasterization() { location.assign(rasterizationUrl()); }
	function sendCamera(force = false) {
		if (!ws || ws.readyState !== WebSocket.OPEN) return;
		const now = performance.now(); if (!force && now - lastSent < 33) return;
		lastSent = now; ws.send(JSON.stringify({ type: 'camera', ...pose }));
	}

	function boundedSpp(value: unknown) { const parsed = Number(value); return LIVE_SPP_VALUES.includes(parsed as (typeof LIVE_SPP_VALUES)[number]) ? parsed : 1; }
	function sppSliderIndex(value: number) { return Math.max(0, LIVE_SPP_VALUES.indexOf(boundedSpp(value) as (typeof LIVE_SPP_VALUES)[number])); }
	function setSppFromSlider(event: Event) { const index = Number((event.currentTarget as HTMLInputElement).value); requestedSpp = LIVE_SPP_VALUES[Math.max(0, Math.min(LIVE_SPP_VALUES.length - 1, index))]; }
	function resolutionSliderIndex(value: { width: number; height: number }) { const index = LIVE_RESOLUTION_VALUES.findIndex((item) => item.width === value.width && item.height === value.height); return Math.max(0, index); }
	function setResolutionFromSlider(event: Event) { const index = Number((event.currentTarget as HTMLInputElement).value); requestedResolution = LIVE_RESOLUTION_VALUES[Math.max(0, Math.min(LIVE_RESOLUTION_VALUES.length - 1, index))]; }
	function connect() {
		ws?.close(); error = ''; connection = 'connecting'; progressDetail = 'Connecting to Mitsuba daemon'; progressPhase = 'connecting'; loadEstimate = null; progressStartedAt = performance.now(); progressSeconds = 0; lastSequence = -1; endpoint = selectedHost();
		requestedSpp = boundedSpp(requestedSpp); ws = new WebSocket(opticalNavLivePreviewWsUrl(projectId, sceneId, endpoint, requestedSpp, requestedResolution, 'frozen')); ws.binaryType = 'arraybuffer';
		ws.onopen = () => sendCamera(true);
		ws.onmessage = (event) => {
			if (typeof event.data === 'string') {
				try {
					const message = JSON.parse(event.data);
					if (message.type === 'status') { if (message.state === 'warming' || message.state === 'recording') connection = message.state; progressPhase = String(message.phase ?? progressPhase); progressDetail = String(message.detail ?? 'Preparing renderer'); if (message.estimate && typeof message.estimate === 'object') loadEstimate = message.estimate as LoadEstimate; if (!progressStartedAt) progressStartedAt = performance.now(); }
					if (message.type === 'ready') { connection = 'ready'; progressPhase = 'record'; progressDetail = 'Renderer prepared; producing the first frame'; revision = String(message.revision ?? '—'); rendererMode = String(message.renderer_mode ?? rendererMode); appliedSpp = Number(message.spp ?? appliedSpp); }
					if (message.type === 'error') { connection = 'error'; error = String(message.message ?? 'Renderer error'); }
				} catch { /* Ignore malformed status frames. */ }
				return;
			}
			const data = new Uint8Array(event.data as ArrayBuffer); if (data.byteLength < 5) return;
			const headerLength = new DataView(data.buffer, data.byteOffset, 4).getUint32(0, false); if (headerLength <= 0 || 4 + headerLength >= data.byteLength) return;
			try {
				const header = JSON.parse(new TextDecoder().decode(data.subarray(4, 4 + headerLength))); if (Number(header.sequence) <= lastSequence) return;
				lastSequence = Number(header.sequence); renderMs = Number(header.render_ms ?? 0); dispatchMs = Number(header.dispatch_ms ?? 0); evalMs = Number(header.eval_ms ?? 0); encodeMs = Number(header.encode_ms ?? 0); ipcMs = Number(header.ipc_ms ?? 0);
				rendererMode = String(header.renderer_mode ?? rendererMode); frozenStage = String(header.frozen_stage ?? frozenStage); recordMs = Number(header.record_ms ?? 0); replayMs = Number(header.replay_ms ?? 0); frameSize = `${header.width ?? '?'}×${header.height ?? '?'}`; revision = String(header.revision ?? revision); connection = 'ready'; progressPhase = 'record'; progressDetail = 'First frame ready'; progressSeconds = 0;
				const now = performance.now(); if (lastFrameAt) displayFps = 1000 / Math.max(1, now - lastFrameAt); lastFrameAt = now;
				const next = URL.createObjectURL(new Blob([data.slice(4 + headerLength)], { type: 'image/jpeg' })); if (frameUrl) URL.revokeObjectURL(frameUrl); frameUrl = next;
			} catch { /* Ignore malformed binary frames. */ }
		};
		ws.onclose = (event) => { if (connection !== 'error') { connection = 'error'; error = `Live preview socket closed (code ${event.code}${event.reason ? `: ${event.reason}` : ''}).`; } };
		ws.onerror = () => { connection = 'error'; error = 'Live preview connection failed.'; };
	}

	function reload() { if (ws?.readyState === WebSocket.OPEN) { connection = 'reloading'; ws.send(JSON.stringify({ type: 'reload' })); } }
	function onMouseMove(event: MouseEvent) { if (document.pointerLockElement !== canvas) return; pose = { ...pose, yaw_deg: pose.yaw_deg + event.movementX * 0.13, pitch_deg: Math.max(-89, Math.min(89, pose.pitch_deg - event.movementY * 0.13)) }; sendCamera(); }
	function tick(now: number) {
		const dt = Math.min(0.05, (now - lastTick) / 1000 || 0); lastTick = now; const speed = (keys.has('ShiftLeft') || keys.has('ShiftRight') ? 8 : 2.5) * dt; const yaw = pose.yaw_deg * Math.PI / 180; const forward = { x: Math.sin(yaw), z: -Math.cos(yaw) }; const right = { x: Math.cos(yaw), z: Math.sin(yaw) }; let { x, y, z } = pose;
		if (keys.has('KeyW')) { x += forward.x * speed; z += forward.z * speed; } if (keys.has('KeyS')) { x -= forward.x * speed; z -= forward.z * speed; } if (keys.has('KeyA')) { x -= right.x * speed; z -= right.z * speed; } if (keys.has('KeyD')) { x += right.x * speed; z += right.z * speed; } if (keys.has('KeyQ')) y -= speed; if (keys.has('KeyE')) y += speed;
		if (x !== pose.x || y !== pose.y || z !== pose.z) { pose = { ...pose, x, y, z }; sendCamera(); } animation = requestAnimationFrame(tick);
	}

	onMount(() => {
		const params = new URLSearchParams(location.search); projectId = params.get('project_id') || projectId; sceneId = params.get('scene_id') || sceneId; liveHost = params.get('live_host') || liveHost; requestedSpp = boundedSpp(params.get('spp') || requestedSpp); const requestedWidth = Number(params.get('width')); const requestedHeight = Number(params.get('height')); if (LIVE_RESOLUTION_VALUES.some((item) => item.width === requestedWidth && item.height === requestedHeight)) requestedResolution = { width: requestedWidth, height: requestedHeight };
		if (params.get('backend') === 'raster') { location.replace(rasterizationUrl()); return; }
		const keyDown = (event: KeyboardEvent) => keys.add(event.code); const keyUp = (event: KeyboardEvent) => keys.delete(event.code); const progressTimer = window.setInterval(() => { if (progressStartedAt && connection !== 'ready' && connection !== 'error') progressSeconds = (performance.now() - progressStartedAt) / 1000; }, 200); window.addEventListener('mousemove', onMouseMove); window.addEventListener('keydown', keyDown); window.addEventListener('keyup', keyUp); lastTick = performance.now(); animation = requestAnimationFrame(tick); connect();
		return () => { window.clearInterval(progressTimer); window.removeEventListener('mousemove', onMouseMove); window.removeEventListener('keydown', keyDown); window.removeEventListener('keyup', keyUp); };
	});
	onDestroy(() => { if (typeof cancelAnimationFrame !== 'undefined' && animation) cancelAnimationFrame(animation); ws?.close(); if (frameUrl) URL.revokeObjectURL(frameUrl); });
</script>

<svelte:head><title>Mitsuba Live Viewer</title></svelte:head>
<main class="viewer">
	{#if frameUrl}<img class="frame" src={frameUrl} alt="Live Mitsuba RGB render" />{:else}<div class="empty"><span class="spinner"></span><div class="loading"><strong>{connection === 'recording' ? 'Recording frozen CUDA graph' : 'Preparing Mitsuba first frame'}</strong><span>{progressDetail} · {progressSeconds.toFixed(1)} s</span><span class="estimate">{coldStartEstimateText()}</span><ol class="timeline">{#each LOAD_STEPS as step}<li class:done={stepState(step.phase) === 'done'} class:active={stepState(step.phase) === 'active'}>{step.label}</li>{/each}</ol></div></div>{/if}
	<canvas bind:this={canvas} class="input" aria-label="Mitsuba live viewer camera controls" onclick={() => canvas.requestPointerLock()}></canvas>
	<section class="hud">
		<strong>LIVE MITSUBA · FROZEN</strong><span class:bad={connection === 'error'}>{connection}</span><span>{sceneId} · {endpoint}</span><span>{frameSize} · {appliedSpp} spp · {displayFps.toFixed(1)} fps · {renderMs.toFixed(1)} ms</span>
		<span>dispatch {dispatchMs.toFixed(1)} ms · GPU eval {evalMs.toFixed(1)} ms · JPEG {encodeMs.toFixed(1)} ms · IPC {ipcMs.toFixed(1)} ms</span><span>{rendererMode} · {frozenStage}{recordMs ? ` · record ${recordMs.toFixed(1)} ms` : ''}{replayMs ? ` · replay ${replayMs.toFixed(1)} ms` : ''}</span><span>FOV {pose.fov_deg.toFixed(0)}° · x {pose.x.toFixed(2)} y {pose.y.toFixed(2)} z {pose.z.toFixed(2)}</span><span>rev {revision}</span>
		{#if error}<span class="error">{error}</span>{/if}
	</section>
	<section class="controls">
		<div class="profiles"><button class="active" title={MITSUBA_FROZEN_VIEWER.description}>Mitsuba Frozen · :{MITSUBA_FROZEN_VIEWER.port}</button><button onclick={openRasterization} title="Browser WebGL source-mesh preview">Rasterization</button></div>
		<label>Project <input bind:value={projectId} /></label><label>Scene <input bind:value={sceneId} /></label><label>Resolution <input type="range" min="0" max={LIVE_RESOLUTION_VALUES.length - 1} step="1" value={resolutionSliderIndex(requestedResolution)} oninput={setResolutionFromSlider} /> {requestedResolution.width}×{requestedResolution.height}</label><label>SPP <input type="range" min="0" max={LIVE_SPP_VALUES.length - 1} step="1" value={sppSliderIndex(requestedSpp)} oninput={setSppFromSlider} /> {requestedSpp}</label><label>Viewer host <input bind:value={liveHost} placeholder={`default: :${MITSUBA_FROZEN_VIEWER.port}`} /></label>
		<button onclick={connect}>Reconnect</button><button onclick={reload}>Reload scene</button><span>Click image · WASD move · Q/E up/down · Shift fast · mouse look · Esc release</span>
	</section>
</main>

<style>
	.viewer { position: fixed; inset: 0; z-index: 9999; overflow: hidden; background: #030712; color: #e5e7eb; font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; }.frame { width: 100%; height: 100%; object-fit: contain; image-rendering: auto; display: block; }.empty { height: 100%; display: flex; align-items: center; justify-content: center; gap: 12px; color: #cbd5e1; text-align: left; }.loading { display: grid; gap: 7px; max-width: 440px; }.estimate { color: #93c5fd; }.timeline { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 5px 14px; padding: 8px 0 0 20px; margin: 0; color: #64748b; }.timeline li.active { color: #f8fafc; }.timeline li.done { color: #6ee7b7; }.spinner { width: 22px; height: 22px; border: 3px solid #334155; border-top-color: #60a5fa; border-radius: 50%; animation: spin 0.8s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }.input { position: absolute; inset: 0; width: 100%; height: 100%; cursor: crosshair; outline: none; }.hud, .controls { position: absolute; display: grid; gap: 5px; padding: 10px 12px; background: rgb(2 6 23 / 82%); border: 1px solid rgb(148 163 184 / 35%); border-radius: 6px; backdrop-filter: blur(4px); }.hud { top: 14px; left: 14px; max-width: min(760px, calc(100vw - 28px)); }.controls { left: 14px; bottom: 14px; max-width: min(680px, calc(100vw - 28px)); }.profiles { display: flex; gap: 6px; }.controls button { width: max-content; background: #1d4ed8; color: white; border: 0; border-radius: 4px; padding: 6px 9px; cursor: pointer; }.controls button.active { background: #047857; outline: 1px solid #6ee7b7; }.controls label { display: flex; gap: 6px; align-items: center; }.controls input { min-width: 180px; background: #0f172a; color: inherit; border: 1px solid #475569; border-radius: 3px; padding: 3px 5px; }.bad, .error { color: #fca5a5; }
</style>
