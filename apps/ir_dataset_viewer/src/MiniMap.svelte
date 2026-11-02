<script lang="ts">
  import { onMount } from 'svelte';
  import type { OverviewPose, SceneOverview } from './api';

  interface Props {
    overview: SceneOverview;
    selectedFrameId: string;
    traversabilityUrl?: string;
    onSelect: (pose: OverviewPose) => void;
  }
  let { overview, selectedFrameId, traversabilityUrl = '', onSelect }: Props = $props();
  let canvas = $state<HTMLCanvasElement>();
  let footprint: HTMLImageElement | null = null;
  let zoom = $state(1);
  let panX = $state(0); let panY = $state(0);
  let panTargetX = 0, panTargetY = 0, panRaf: number | null = null;
  let dragging = $state(false); let moved = $state(false);
  let dragStart = $state({ x: 0, y: 0, panX: 0, panY: 0 });

  function rasterOrigin() {
    const raw = overview.traversability?.origin ?? [];
    // Navigation grids store their planar origin as [x, z]; scene vectors use
    // [x, y, z]. Accept both contracts so the raster and pose coordinates share
    // one x/z plane.
    return { x: Number(raw[0] ?? overview.bounds.min[0]), z: Number(raw.length >= 3 ? raw[2] : raw[1] ?? overview.bounds.min[2]) };
  }
  function bounds() {
    const min = overview.bounds.min, max = overview.bounds.max;
    let minX = min[0], maxX = max[0], minZ = min[2], maxZ = max[2];
    for (const point of [...overview.nodes, ...overview.poses]) { minX = Math.min(minX, point.origin[0]); maxX = Math.max(maxX, point.origin[0]); minZ = Math.min(minZ, point.origin[2]); maxZ = Math.max(maxZ, point.origin[2]); }
    const t = overview.traversability;
    if (t) { const origin = rasterOrigin(), width = Number(t.width) * Number(t.resolution_m), height = Number(t.height) * Number(t.resolution_m); minX = Math.min(minX, origin.x); maxX = Math.max(maxX, origin.x + width); minZ = Math.min(minZ, origin.z); maxZ = Math.max(maxZ, origin.z + height); }
    return { minX, maxX, minZ, maxZ };
  }
  function projector(rect: DOMRect) {
    // Build this once per frame: drawing every pose/edge must not repeatedly
    // scan the complete overview just to recover identical bounds.
    const b = bounds(), padding = 11;
    const scale = Math.min((rect.width - padding * 2) / Math.max(b.maxX - b.minX, .1),
      (rect.height - padding * 2) / Math.max(b.maxZ - b.minZ, .1)) * zoom;
    return { scale, map: (x: number, z: number) => ({
      x: (x - (b.minX + b.maxX) / 2) * scale + rect.width / 2 + panX,
      y: (z - (b.minZ + b.maxZ) / 2) * -scale + rect.height / 2 + panY,
    }) };
  }
  function draw() {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const dpr = devicePixelRatio || 1, width = Math.floor(rect.width * dpr), height = Math.floor(rect.height * dpr);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width; canvas.height = height;
    }
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = '#f7f7f9'; ctx.fillRect(0, 0, rect.width, rect.height);
    const project = projector(rect);
    if (footprint && overview.traversability) {
      const t = overview.traversability;
      const gridOrigin = rasterOrigin(); const origin = project.map(gridOrigin.x, gridOrigin.z);
      const width = Number(t.width) * project.scale * Number(t.resolution_m);
      const height = Number(t.height) * project.scale * Number(t.resolution_m);
      ctx.globalAlpha = .28;
      // Grid row 0 is the lowest world-z row, while canvas y grows downward.
      ctx.drawImage(footprint, origin.x, origin.y, width, -height);
      ctx.globalAlpha = 1;
    }
    ctx.strokeStyle = 'rgba(29,29,31,.22)'; ctx.lineWidth = 1;
    const nodes = new Map(overview.nodes.map((node) => [node.viewpoint_id, node]));
    for (const edge of overview.edges) {
      const source = nodes.get(edge.source), target = nodes.get(edge.target);
      if (!source || !target) continue;
      const a = project.map(source.origin[0], source.origin[2]), d = project.map(target.origin[0], target.origin[2]);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(d.x, d.y); ctx.stroke();
    }
    for (const pose of overview.poses) {
      const p = project.map(pose.origin[0], pose.origin[2]);
      const selected = pose.frame_id === selectedFrameId;
      ctx.fillStyle = selected ? '#0071e3' : '#7d7d83';
      ctx.beginPath(); ctx.arc(p.x, p.y, selected ? 4.4 : 2.3, 0, Math.PI * 2); ctx.fill();
      if (selected) {
        // Keep the compact map readable: the active camera alone gets a
        // heading arrow, derived from the same origin/target pose as Bird-eye.
        const target = project.map(pose.target[0], pose.target[2]);
        const dx = target.x - p.x, dy = target.y - p.y, length = Math.hypot(dx, dy) || 1;
        const ux = dx / length, uy = dy / length, reach = 13, tipX = p.x + ux * reach, tipY = p.y + uy * reach;
        ctx.strokeStyle = '#0071e3'; ctx.fillStyle = '#0071e3'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(tipX, tipY); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(tipX, tipY);
        ctx.lineTo(tipX - ux * 4.5 - uy * 3, tipY - uy * 4.5 + ux * 3);
        ctx.lineTo(tipX - ux * 4.5 + uy * 3, tipY - uy * 4.5 - ux * 3);
        ctx.closePath(); ctx.fill();
        ctx.strokeStyle = 'rgba(0,113,227,.22)'; ctx.lineWidth = 5; ctx.beginPath(); ctx.arc(p.x, p.y, 6.7, 0, Math.PI * 2); ctx.stroke();
      }
    }
  }
  function nearest(event: PointerEvent) {
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect(), project = projector(rect); let best: OverviewPose | null = null, distance = Number.POSITIVE_INFINITY;
    for (const pose of overview.poses) {
      const p = project.map(pose.origin[0], pose.origin[2]);
      const d = Math.hypot(event.clientX - rect.left - p.x, event.clientY - rect.top - p.y);
      if (d < distance) { best = pose; distance = d; }
    }
    return best;
  }
  function settlePan() {
    const dx = panTargetX - panX, dy = panTargetY - panY;
    if (Math.abs(dx) < .15 && Math.abs(dy) < .15) { panX = panTargetX; panY = panTargetY; panRaf = null; return; }
    panX += dx * .18; panY += dy * .18; panRaf = requestAnimationFrame(settlePan);
  }
  function queuePan() { if (panRaf === null) panRaf = requestAnimationFrame(settlePan); }
  function selectAt(event: PointerEvent) { const pose = nearest(event); if (pose) onSelect(pose); }
  function pointerdown(event: PointerEvent) {
    dragging = true; moved = false; dragStart = { x: event.clientX, y: event.clientY, panX: panTargetX, panY: panTargetY };
    canvas?.setPointerCapture(event.pointerId);
  }
  function pointermove(event: PointerEvent) {
    if (!dragging) return;
    const dx = event.clientX - dragStart.x, dy = event.clientY - dragStart.y;
    moved ||= Math.abs(dx) + Math.abs(dy) > 3;
    panTargetX = dragStart.panX + dx; panTargetY = dragStart.panY + dy; queuePan();
  }
  function pointerup(event: PointerEvent) {
    if (!dragging) return; dragging = false;
    if (canvas?.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (!moved) selectAt(event); else queuePan();
  }
  function pointercancel(event: PointerEvent) { if (dragging) { dragging = false; if (canvas?.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId); } }
  function wheel(event: WheelEvent) {
    event.preventDefault(); if (!canvas) return;
    const rect = canvas.getBoundingClientRect(), before = zoom, after = Math.max(.55, Math.min(8, before * Math.exp(-event.deltaY * .0015)));
    const ratio = after / before, localX = event.clientX - rect.left - rect.width / 2, localY = event.clientY - rect.top - rect.height / 2;
    panX = localX - (localX - panX) * ratio; panY = localY - (localY - panY) * ratio; panTargetX = panX; panTargetY = panY; zoom = after;
  }
  onMount(() => {
    const target = canvas?.parentElement?.parentElement;
    const observer = new ResizeObserver(draw);
    if (target) observer.observe(target); draw();
    return () => { observer.disconnect(); if (panRaf !== null) cancelAnimationFrame(panRaf); };
  });
  $effect(() => {
    const url = traversabilityUrl; footprint = null;
    if (url) { const image = new Image(); image.onload = () => { if (footprint === image) draw(); }; footprint = image; image.src = url; }
    draw();
  });
  $effect(() => { overview.dataset_id; zoom = 1; panX = 0; panY = 0; panTargetX = 0; panTargetY = 0; });
  $effect(() => { overview; selectedFrameId; zoom; panX; panY; draw(); });
</script>

<div class="minimap-interactive">
  <canvas bind:this={canvas} class:dragging class="minimap-canvas" aria-label="Bird-eye scene minimap; scroll to zoom, drag to pan, and click to select a viewpoint" onpointerdown={pointerdown} onpointermove={pointermove} onpointerup={pointerup} onpointercancel={pointercancel} onlostpointercapture={() => { dragging = false; }} onwheel={wheel}></canvas>
  <span class="minimap-zoom" aria-hidden="true">{Math.round(zoom * 100)}%</span>
</div>
