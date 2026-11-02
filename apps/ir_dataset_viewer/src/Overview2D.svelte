<script lang="ts">
  import { onMount } from 'svelte';
  import type { SceneOverview, OverviewPose } from './api';

  interface Props {
    overview: SceneOverview;
    selectedFrameId: string;
    lightingFilter: string;
    traversabilityUrl?: string;
    onSelect: (pose: OverviewPose) => void;
    onHover: (pose: OverviewPose | null) => void;
  }
  let { overview, selectedFrameId, lightingFilter, traversabilityUrl = '', onSelect, onHover }: Props = $props();
  let canvas = $state<HTMLCanvasElement>();
  let zoom = $state(1); let panX = $state(0); let panY = $state(0);
  let dragging = false; let moved = false; let start = { x: 0, y: 0, panX: 0, panY: 0 };
  let footprint: HTMLImageElement | null = null;
  const colors = ['#59d5cf', '#f0b25b', '#a884f5', '#e2759c', '#83c985', '#7aa7e7'];
  function color(id: string) { return colors[Math.abs([...id].reduce((a, c) => a * 31 + c.charCodeAt(0), 7)) % colors.length]; }
  function visible(pose: OverviewPose) { return lightingFilter === 'all' || pose.lighting_id === lightingFilter; }
  function rasterOrigin() {
    const raw = overview.traversability?.origin ?? [];
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
  function map(x: number, z: number, rect: DOMRect) {
    const b = bounds(), padding = 32;
    const scale = Math.min((rect.width - padding * 2) / Math.max(b.maxX - b.minX, .1), (rect.height - padding * 2) / Math.max(b.maxZ - b.minZ, .1)) * zoom;
    return { x: (x - (b.minX + b.maxX) / 2) * scale + rect.width / 2 + panX,
      y: (z - (b.minZ + b.maxZ) / 2) * -scale + rect.height / 2 + panY, scale };
  }
  function draw() {
    if (!canvas) return; const rect = canvas.getBoundingClientRect(); if (!rect.width || !rect.height) return;
    const dpr = devicePixelRatio || 1, width = Math.floor(rect.width * dpr), height = Math.floor(rect.height * dpr);
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const ctx = canvas.getContext('2d'); if (!ctx) return; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, rect.width, rect.height);
    const first = map(0, 0, rect), b = bounds();
    ctx.fillStyle = '#061019'; ctx.fillRect(0, 0, rect.width, rect.height);
    if (footprint && overview.traversability) {
      const t = overview.traversability; const origin = rasterOrigin(); const a = map(origin.x, origin.z, rect);
      const width = Number(t.width) * first.scale * Number(t.resolution_m), height = Number(t.height) * first.scale * Number(t.resolution_m);
      ctx.globalAlpha = .25; ctx.drawImage(footprint, a.x, a.y, width, -height); ctx.globalAlpha = 1;
    }
    ctx.strokeStyle = '#38505e'; ctx.lineWidth = 1;
    for (const edge of overview.edges) { const a = overview.nodes.find(n => n.viewpoint_id === edge.source), d = overview.nodes.find(n => n.viewpoint_id === edge.target); if (a && d) { const p = map(a.origin[0], a.origin[2], rect), q = map(d.origin[0], d.origin[2], rect); ctx.beginPath(); ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke(); } }
    for (const node of overview.nodes) { const p = map(node.origin[0], node.origin[2], rect); ctx.fillStyle = '#8fa9b9'; ctx.fillRect(p.x-2,p.y-2,4,4); }
    for (const pose of overview.poses) {
      if (!visible(pose)) continue;
      const p = map(pose.origin[0], pose.origin[2], rect), target = map(pose.target[0], pose.target[2], rect);
      const dx = target.x - p.x, dy = target.y - p.y, length = Math.hypot(dx, dy) || 1;
      const ux = dx / length, uy = dy / length, selected = pose.frame_id === selectedFrameId;
      const reach = Math.min(38, Math.max(12, first.scale * .7));
      const half = Math.tan((pose.fov_deg * Math.PI / 180) / 2) * reach;
      const tint = color(pose.lighting_id);
      ctx.strokeStyle = tint; ctx.fillStyle = tint; ctx.globalAlpha = selected ? .96 : .42; ctx.lineWidth = selected ? 2.2 : 1;
      // Camera FOV plus an arrowed centre ray: the ray is the actual heading,
      // so its direction stays clear even with a very wide FOV.
      ctx.beginPath();
      ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + ux * reach - uy * half, p.y + uy * reach + ux * half);
      ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + ux * reach + uy * half, p.y + uy * reach - ux * half);
      ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + ux * reach, p.y + uy * reach); ctx.stroke();
      const tipX = p.x + ux * reach, tipY = p.y + uy * reach;
      const arrow = selected ? 5.5 : 3.5;
      ctx.beginPath(); ctx.moveTo(tipX, tipY);
      ctx.lineTo(tipX - ux * arrow - uy * arrow * .65, tipY - uy * arrow + ux * arrow * .65);
      ctx.lineTo(tipX - ux * arrow + uy * arrow * .65, tipY - uy * arrow - ux * arrow * .65);
      ctx.closePath(); ctx.fill();
      ctx.globalAlpha = 1;
    }
  }
  function nearest(event: PointerEvent): OverviewPose | null { if (!canvas) return null; const rect=canvas.getBoundingClientRect(); let best: OverviewPose|null=null, distance=14; for(const pose of overview.poses){if(!visible(pose))continue;const p=map(pose.origin[0],pose.origin[2],rect),d=Math.hypot(event.clientX-rect.left-p.x,event.clientY-rect.top-p.y);if(d<distance){best=pose;distance=d;}} return best; }
  function pointerdown(e: PointerEvent) {
    // Ordinary left-clicks are selection-only. Restrict pan to the middle
    // button so small click/touch jitter can never accumulate a drifting map.
    if (e.button !== 1) { dragging = false; moved = false; return; }
    dragging = true; moved = false; start = { x: e.clientX, y: e.clientY, panX, panY }; canvas?.setPointerCapture(e.pointerId);
  }
  function pointermove(e: PointerEvent) { if(dragging){const dx=e.clientX-start.x,dy=e.clientY-start.y;moved ||= Math.abs(dx)+Math.abs(dy)>3;panX=start.panX+dx;panY=start.panY+dy;draw();} else onHover(nearest(e)); }
  function finishPointer(e: PointerEvent) {
    if (!dragging) return;
    dragging = false;
    if (canvas?.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
    if (!moved) { const pose = nearest(e); if (pose) onSelect(pose); }
  }
  function pointerup(e: PointerEvent) {
    if (dragging) finishPointer(e);
    else { const pose = nearest(e); if (pose) onSelect(pose); }
  }
  function pointercancel(e: PointerEvent) { if (dragging) { dragging = false; if (canvas?.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId); } }
  function wheel(e: WheelEvent) {
    e.preventDefault(); if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const previous = zoom, next = Math.max(.3, Math.min(20, previous * Math.exp(-e.deltaY * .001)));
    // Preserve the world point under the cursor instead of letting zoom shift the map upward.
    const ratio = next / previous, localX = e.clientX - rect.left - rect.width / 2, localY = e.clientY - rect.top - rect.height / 2;
    panX = localX - (localX - panX) * ratio; panY = localY - (localY - panY) * ratio;
    zoom = next; draw();
  }
  onMount(() => { if(traversabilityUrl){footprint=new Image();footprint.onload=draw;footprint.src=traversabilityUrl;} const observer=new ResizeObserver(draw);const target=canvas?.parentElement;if(target)observer.observe(target);draw();return()=>observer.disconnect(); });
  $effect(() => { overview; selectedFrameId; lightingFilter; zoom; panX; panY; draw(); });
</script>

<canvas bind:this={canvas} class="overview-canvas" aria-label="Bird-eye camera overview" onpointerdown={pointerdown} onpointermove={pointermove} onpointerup={pointerup} onpointercancel={pointercancel} onlostpointercapture={() => { dragging = false; }} onpointerleave={() => !dragging && onHover(null)} onwheel={wheel}></canvas>
