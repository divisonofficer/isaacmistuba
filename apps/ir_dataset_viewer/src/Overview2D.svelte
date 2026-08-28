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
  function bounds() {
    const min = overview.bounds.min, max = overview.bounds.max;
    return { minX: min[0], maxX: max[0], minZ: min[2], maxZ: max[2] };
  }
  function map(x: number, z: number, rect: DOMRect) {
    const b = bounds(), padding = 32;
    const scale = Math.min((rect.width - padding * 2) / Math.max(b.maxX - b.minX, .1), (rect.height - padding * 2) / Math.max(b.maxZ - b.minZ, .1)) * zoom;
    return { x: (x - (b.minX + b.maxX) / 2) * scale + rect.width / 2 + panX,
      y: (z - (b.minZ + b.maxZ) / 2) * -scale + rect.height / 2 + panY, scale };
  }
  function draw() {
    if (!canvas) return; const rect = canvas.getBoundingClientRect(); if (!rect.width || !rect.height) return;
    const dpr = devicePixelRatio || 1; canvas.width = Math.floor(rect.width * dpr); canvas.height = Math.floor(rect.height * dpr);
    const ctx = canvas.getContext('2d'); if (!ctx) return; ctx.scale(dpr, dpr); ctx.clearRect(0, 0, rect.width, rect.height);
    const first = map(0, 0, rect), b = bounds();
    ctx.fillStyle = '#061019'; ctx.fillRect(0, 0, rect.width, rect.height);
    if (footprint && overview.traversability) {
      const t = overview.traversability; const a = map(Number(t.origin?.[0] ?? b.minX), Number(t.origin?.[2] ?? b.minZ), rect);
      ctx.globalAlpha = .25; ctx.drawImage(footprint, a.x, a.y - Number(t.height) * first.scale * Number(t.resolution_m), Number(t.width) * first.scale * Number(t.resolution_m), Number(t.height) * first.scale * Number(t.resolution_m)); ctx.globalAlpha = 1;
    }
    ctx.strokeStyle = '#38505e'; ctx.lineWidth = 1;
    for (const edge of overview.edges) { const a = overview.nodes.find(n => n.viewpoint_id === edge.source), d = overview.nodes.find(n => n.viewpoint_id === edge.target); if (a && d) { const p = map(a.origin[0], a.origin[2], rect), q = map(d.origin[0], d.origin[2], rect); ctx.beginPath(); ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke(); } }
    for (const node of overview.nodes) { const p = map(node.origin[0], node.origin[2], rect); ctx.fillStyle = '#8fa9b9'; ctx.fillRect(p.x-2,p.y-2,4,4); }
    for (const pose of overview.poses) { if (!visible(pose)) continue; const p = map(pose.origin[0], pose.origin[2], rect), target = map(pose.target[0], pose.target[2], rect); const dx = target.x-p.x, dy=target.y-p.y, length=Math.hypot(dx,dy) || 1; const reach = Math.min(38, Math.max(12, first.scale * .7)); const half = Math.tan((pose.fov_deg * Math.PI / 180)/2) * reach; ctx.strokeStyle=color(pose.lighting_id); ctx.globalAlpha=pose.frame_id===selectedFrameId?1:.42; ctx.lineWidth=pose.frame_id===selectedFrameId?2:1; ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(p.x+dx/length*reach-dy/length*half,p.y+dy/length*reach+dx/length*half);ctx.moveTo(p.x,p.y);ctx.lineTo(p.x+dx/length*reach+dy/length*half,p.y+dy/length*reach-dx/length*half);ctx.stroke();ctx.globalAlpha=1; }
  }
  function nearest(event: PointerEvent): OverviewPose | null { if (!canvas) return null; const rect=canvas.getBoundingClientRect(); let best: OverviewPose|null=null, distance=14; for(const pose of overview.poses){if(!visible(pose))continue;const p=map(pose.origin[0],pose.origin[2],rect),d=Math.hypot(event.clientX-rect.left-p.x,event.clientY-rect.top-p.y);if(d<distance){best=pose;distance=d;}} return best; }
  function pointerdown(e: PointerEvent) { dragging=true;moved=false;start={x:e.clientX,y:e.clientY,panX,panY};canvas?.setPointerCapture(e.pointerId); }
  function pointermove(e: PointerEvent) { if(dragging){const dx=e.clientX-start.x,dy=e.clientY-start.y;moved ||= Math.abs(dx)+Math.abs(dy)>3;panX=start.panX+dx;panY=start.panY+dy;draw();} else onHover(nearest(e)); }
  function pointerup(e: PointerEvent) { dragging=false;canvas?.releasePointerCapture(e.pointerId);if(!moved){const pose=nearest(e);if(pose)onSelect(pose);} }
  function wheel(e: WheelEvent){e.preventDefault();zoom=Math.max(.3,Math.min(20,zoom*Math.exp(-e.deltaY*.001)));draw();}
  onMount(() => { if(traversabilityUrl){footprint=new Image();footprint.onload=draw;footprint.src=traversabilityUrl;} const observer=new ResizeObserver(draw);if(canvas)observer.observe(canvas);draw();return()=>observer.disconnect(); });
  $effect(() => { overview; selectedFrameId; lightingFilter; zoom; panX; panY; draw(); });
</script>

<canvas bind:this={canvas} class="overview-canvas" aria-label="Bird-eye camera overview" onpointerdown={pointerdown} onpointermove={pointermove} onpointerup={pointerup} onpointerleave={() => !dragging && onHover(null)} onwheel={wheel}></canvas>
