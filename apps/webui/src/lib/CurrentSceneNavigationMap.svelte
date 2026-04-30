<script lang="ts">
	import { onMount } from 'svelte';
	import { lang } from '$lib/stores/lang';
	import { getOccupancyMap, occupancyMapPngUrl, type OccupancyMapOpts } from '$lib/api';

	type LegendEntry = { key: string; color: string; label_en: string; label_kr: string };
	type RobotEntry = {
		id?: string;
		name?: string;
		translation?: number[] | null;
	};
	type RoomEntry = {
		id: string;
		label: string;
		object_count: number;
		bounds: { min: number[]; max: number[]; size: number[]; center: number[] };
	};
	type OccupancyMap = {
		scene_id: string;
		status: string;
		cell_size?: number;
		height_min?: number;
		height_max?: number;
		width?: number;
		height?: number;
		bounds_xz?: { min: number[]; max: number[] };
		scene_bounds?: { min: number[]; max: number[]; size: number[]; center: number[] };
		robots?: RobotEntry[];
		rooms?: RoomEntry[];
		legend?: LegendEntry[];
		composite_png_url?: string;
		reason?: string;
	};

	type SelectedAabb = { min: number[]; max: number[] };

	let {
		sceneId = null,
		selectedAabbs = null
	}: {
		sceneId?: string | null;
		selectedAabbs?: SelectedAabb[] | null;
	} = $props();

	const L = $derived($lang);

	let cellSize = $state(0.05);
	let heightMin = $state(0.1);
	let heightMax = $state(1.5);
	let showFurniture = $state(true);
	let showRobot = $state(true);
	let showSelected = $state(true);

	let manifest = $state<OccupancyMap | null>(null);
	let imgSrc = $state<string | null>(null);
	let loading = $state(false);
	let errorMessage = $state('');
	let bust = $state(0);

	let host = $state<HTMLDivElement | null>(null);
	let imageEl = $state<HTMLImageElement | null>(null);
	let overlayCanvas = $state<HTMLCanvasElement | null>(null);
	let viewport = $state<HTMLDivElement | null>(null);

	let zoom = $state(1);
	let panX = $state(0);
	let panY = $state(0);
	let isPanning = false;
	let panStart = { x: 0, y: 0, px: 0, py: 0 };

	let fetchSeq = 0;
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	const opts = $derived<OccupancyMapOpts>({
		cell_size: cellSize,
		height_min: heightMin,
		height_max: heightMax,
		furniture: showFurniture
	});

	function scheduleFetch() {
		if (!sceneId) {
			manifest = null;
			imgSrc = null;
			return;
		}
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => void doFetch(), 280);
	}

	async function doFetch() {
		if (!sceneId) return;
		const seq = ++fetchSeq;
		loading = true;
		errorMessage = '';
		try {
			const res = (await getOccupancyMap(sceneId, opts)) as OccupancyMap;
			if (seq !== fetchSeq) return;
			manifest = res;
			if (res.status === 'ready') {
				bust = Date.now();
				imgSrc = `${occupancyMapPngUrl(sceneId, opts)}&_=${bust}`;
			} else {
				imgSrc = null;
			}
		} catch (e) {
			if (seq !== fetchSeq) return;
			errorMessage = e instanceof Error ? e.message : 'Failed to load navigation map';
			manifest = null;
			imgSrc = null;
		} finally {
			if (seq === fetchSeq) loading = false;
		}
	}

	function worldToImage(x: number, z: number): [number, number] | null {
		if (!manifest?.bounds_xz || !manifest.width || !manifest.height) return null;
		const [xMin, zMin] = manifest.bounds_xz.min;
		const [xMax, zMax] = manifest.bounds_xz.max;
		const w = manifest.width, h = manifest.height;
		const px = ((x - xMin) / (xMax - xMin)) * w;
		const py = ((z - zMin) / (zMax - zMin)) * h;
		return [px, py];
	}

	function drawOverlays() {
		if (!overlayCanvas || !manifest || !manifest.width || !manifest.height) return;
		overlayCanvas.width = manifest.width;
		overlayCanvas.height = manifest.height;
		const ctx = overlayCanvas.getContext('2d');
		if (!ctx) return;
		ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

		// Selection AABBs (red dashed)
		if (showSelected && selectedAabbs && selectedAabbs.length) {
			ctx.strokeStyle = '#dc2626';
			ctx.lineWidth = 2;
			ctx.setLineDash([5, 4]);
			for (const aabb of selectedAabbs) {
				const a = worldToImage(aabb.min[0], aabb.min[2]);
				const b = worldToImage(aabb.max[0], aabb.max[2]);
				if (!a || !b) continue;
				ctx.strokeRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
			}
			ctx.setLineDash([]);
		}

		// Robots
		if (showRobot && manifest.robots) {
			ctx.fillStyle = '#f59e0b';
			ctx.strokeStyle = '#b45309';
			ctx.lineWidth = 1.5;
			for (const r of manifest.robots) {
				if (!Array.isArray(r.translation) || r.translation.length < 3) continue;
				const p = worldToImage(Number(r.translation[0]), Number(r.translation[2]));
				if (!p) continue;
				ctx.beginPath();
				ctx.arc(p[0], p[1], Math.max(3, 0.25 / (manifest.cell_size ?? 0.05)), 0, Math.PI * 2);
				ctx.fill();
				ctx.stroke();
			}
		}
	}

	function onWheel(e: WheelEvent) {
		e.preventDefault();
		const factor = Math.exp(-e.deltaY * 0.0015);
		const next = Math.max(0.25, Math.min(8, zoom * factor));
		if (next === zoom || !viewport) return;
		const rect = viewport.getBoundingClientRect();
		const dx = e.clientX - rect.left - rect.width / 2 - panX;
		const dy = e.clientY - rect.top - rect.height / 2 - panY;
		const k = next / zoom - 1;
		panX -= dx * k;
		panY -= dy * k;
		zoom = next;
	}
	function onPointerDown(e: PointerEvent) {
		if (!viewport || e.button !== 0) return;
		isPanning = true;
		panStart = { x: e.clientX, y: e.clientY, px: panX, py: panY };
		viewport.setPointerCapture(e.pointerId);
	}
	function onPointerMove(e: PointerEvent) {
		if (!isPanning) return;
		panX = panStart.px + (e.clientX - panStart.x);
		panY = panStart.py + (e.clientY - panStart.y);
	}
	function onPointerUp(e: PointerEvent) {
		if (!isPanning) return;
		isPanning = false;
		viewport?.releasePointerCapture(e.pointerId);
	}
	function resetView() {
		zoom = 1;
		panX = 0;
		panY = 0;
	}

	$effect(() => {
		sceneId; cellSize; heightMin; heightMax; showFurniture;
		scheduleFetch();
	});

	$effect(() => {
		manifest; selectedAabbs; showRobot; showSelected;
		drawOverlays();
	});

	onMount(() => {
		return () => {
			if (debounceTimer) clearTimeout(debounceTimer);
		};
	});

	const visibleLegend = $derived((manifest?.legend ?? []).filter((l) =>
		showFurniture || l.key !== 'furniture'
	));
</script>

<div class="nav-shell">
	<div class="nav-toolbar">
		<label class="nav-slider">
			<span>{L === 'kr' ? '셀 크기' : 'Cell'} <strong>{cellSize.toFixed(2)} m</strong></span>
			<input type="range" min="0.02" max="0.2" step="0.01" bind:value={cellSize} />
		</label>
		<label class="nav-slider">
			<span>{L === 'kr' ? '높이 하한' : 'H-min'} <strong>{heightMin.toFixed(2)} m</strong></span>
			<input type="range" min="0" max="0.5" step="0.05" bind:value={heightMin} />
		</label>
		<label class="nav-slider">
			<span>{L === 'kr' ? '높이 상한' : 'H-max'} <strong>{heightMax.toFixed(2)} m</strong></span>
			<input type="range" min="0.3" max="3" step="0.1" bind:value={heightMax} />
		</label>
		<div class="nav-checks">
			<label><input type="checkbox" bind:checked={showFurniture} /> {L === 'kr' ? '가구' : 'Furniture'}</label>
			<label><input type="checkbox" bind:checked={showRobot} /> {L === 'kr' ? '로봇' : 'Robot'}</label>
			<label><input type="checkbox" bind:checked={showSelected} /> {L === 'kr' ? '선택' : 'Selected'}</label>
		</div>
		<button type="button" class="nav-reset" onclick={resetView}>{L === 'kr' ? '뷰 리셋' : 'Reset view'}</button>
	</div>

	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="nav-viewport"
		bind:this={viewport}
		onwheel={onWheel}
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onpointercancel={onPointerUp}
	>
		<div class="nav-canvas-wrap" style="transform: translate({panX}px, {panY}px) scale({zoom})">
			{#if imgSrc}
				<img bind:this={imageEl} src={imgSrc} alt="Occupancy map" class="nav-img" draggable="false" />
				<canvas bind:this={overlayCanvas} class="nav-overlay"></canvas>
			{/if}
		</div>
		{#if loading}
			<div class="nav-overlay-msg">{L === 'kr' ? '맵 생성 중…' : 'Building map…'}</div>
		{:else if errorMessage}
			<div class="nav-overlay-msg nav-overlay-err">{errorMessage}</div>
		{:else if !manifest || manifest.status !== 'ready'}
			<div class="nav-overlay-msg">
				<div>{L === 'kr' ? '주행 맵을 만들 수 없습니다.' : 'Navigation map unavailable.'}</div>
				{#if manifest?.reason}<div class="nav-overlay-sub">{manifest.reason}</div>{/if}
			</div>
		{/if}
	</div>

	{#if visibleLegend.length}
		<div class="nav-legend">
			{#each visibleLegend as item (item.key)}
				<span class="nav-legend-item">
					<span class="nav-legend-swatch" style="background: {item.color}"></span>
					{L === 'kr' ? item.label_kr : item.label_en}
				</span>
			{/each}
			{#if manifest?.cell_size}
				<span class="nav-legend-info">
					{manifest.width}×{manifest.height} · {manifest.cell_size.toFixed(2)} m/cell · h={(manifest.height_min ?? 0).toFixed(1)}–{(manifest.height_max ?? 0).toFixed(1)} m
				</span>
			{/if}
		</div>
	{/if}
</div>

<style>
	.nav-shell {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: var(--panel, #fff);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}
	.nav-toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: 0.55rem;
		align-items: flex-end;
		padding: 0.45rem 0.55rem;
		border-bottom: 1px solid var(--panel-border);
		background: rgba(255,255,255,0.86);
		font-size: 0.72rem;
	}
	.nav-slider {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		min-width: 8rem;
	}
	.nav-slider span {
		font-size: 0.65rem;
		color: var(--muted);
		display: flex;
		justify-content: space-between;
	}
	.nav-slider strong { color: var(--text); font-weight: 600; }
	.nav-slider input[type='range'] { width: 100%; }
	.nav-checks {
		display: inline-flex;
		gap: 0.5rem;
		flex-wrap: wrap;
		font-size: 0.72rem;
	}
	.nav-checks label {
		display: inline-flex;
		gap: 0.25rem;
		align-items: center;
		cursor: pointer;
	}
	.nav-reset {
		appearance: none;
		border: 1px solid var(--panel-border);
		background: var(--panel, #fff);
		color: var(--text);
		border-radius: 0.4rem;
		padding: 0.22rem 0.55rem;
		font: inherit;
		font-size: 0.72rem;
		cursor: pointer;
		margin-left: auto;
	}
	.nav-viewport {
		position: relative;
		flex: 1;
		min-height: 0;
		overflow: hidden;
		background:
			linear-gradient(45deg, #f3f4f6 25%, transparent 25%),
			linear-gradient(-45deg, #f3f4f6 25%, transparent 25%),
			linear-gradient(45deg, transparent 75%, #f3f4f6 75%),
			linear-gradient(-45deg, transparent 75%, #f3f4f6 75%);
		background-size: 14px 14px;
		background-position: 0 0, 0 7px, 7px -7px, -7px 0;
		background-color: #fafafa;
		cursor: grab;
		touch-action: none;
	}
	.nav-viewport:active { cursor: grabbing; }
	.nav-canvas-wrap {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		transform-origin: center;
		pointer-events: none;
	}
	.nav-img {
		image-rendering: pixelated;
		max-width: 96%;
		max-height: 96%;
		box-shadow: 0 4px 18px rgba(15,23,42,0.12);
		background: #f9fafb;
	}
	.nav-overlay {
		position: absolute;
		max-width: 96%;
		max-height: 96%;
		image-rendering: pixelated;
		pointer-events: none;
		mix-blend-mode: normal;
	}
	.nav-overlay-msg {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.3rem;
		background: rgba(250,250,250,0.78);
		color: var(--muted-strong);
		font-size: 0.85rem;
		font-weight: 600;
	}
	.nav-overlay-err { color: var(--danger, #dc2626); }
	.nav-overlay-sub { font-size: 0.7rem; font-weight: 500; color: var(--muted); }
	.nav-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
		align-items: center;
		padding: 0.35rem 0.55rem;
		border-top: 1px solid var(--panel-border);
		background: rgba(247,248,251,0.92);
		font-size: 0.7rem;
		color: var(--muted-strong);
	}
	.nav-legend-item {
		display: inline-flex;
		gap: 0.3rem;
		align-items: center;
	}
	.nav-legend-swatch {
		display: inline-block;
		width: 0.85rem;
		height: 0.85rem;
		border-radius: 0.18rem;
		border: 1px solid rgba(15,23,42,0.18);
	}
	.nav-legend-info {
		margin-left: auto;
		color: var(--muted);
		font-size: 0.66rem;
	}
</style>
