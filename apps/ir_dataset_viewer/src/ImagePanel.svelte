<script lang="ts">
  import { onMount } from 'svelte';
  export type ViewTransform = { zoom: number; offsetX: number; offsetY: number };
  type Cursor = { x: number; y: number } | null;
  interface Props {
    title: string; url: string; fallbackUrl?: string; width: number; height: number; available?: boolean;
    transform: ViewTransform; cursor: Cursor;
    onTransform: (value: ViewTransform) => void;
    onProbe: (x: number, y: number) => void;
    onPreviewLoaded?: (stage: 'fallback' | 'full') => void;
    eager?: boolean;
  }
  let { title, url, fallbackUrl = '', width, height, available = true, transform, cursor, onTransform, onProbe, onPreviewLoaded, eager = false }: Props = $props();
  let svg = $state<SVGSVGElement>();
  let stage = $state<HTMLDivElement>();
  let dragging = $state(false);
  let moved = false;
  let lastX = 0; let lastY = 0;
  let intersected = $state(false);
  let displayUrl = $state('');
  let promotionToken = 0;
  let imageHref = $derived(intersected ? displayUrl : '');
  const viewX = $derived((width - width / transform.zoom) / 2 + transform.offsetX);
  const viewY = $derived((height - height / transform.zoom) / 2 + transform.offsetY);

  function imagePoint(event: MouseEvent): { x: number; y: number } | null {
    if (!svg) return null;
    const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    const matrix = svg.getScreenCTM()?.inverse();
    if (!matrix) return null;
    const result = point.matrixTransform(matrix);
    return { x: Math.max(0, Math.min(width - 1, Math.floor(result.x))), y: Math.max(0, Math.min(height - 1, Math.floor(result.y))) };
  }
  function pointerDown(event: PointerEvent) {
    dragging = true; moved = false; lastX = event.clientX; lastY = event.clientY;
    stage?.setPointerCapture(event.pointerId);
  }
  function pointerMove(event: PointerEvent) {
    if (!dragging) return;
    if (Math.abs(event.clientX - lastX) > 1 || Math.abs(event.clientY - lastY) > 1) moved = true;
    const rect = svg?.getBoundingClientRect();
    if (!rect) return;
    const dx = (event.clientX - lastX) * width / Math.max(rect.width, 1) / transform.zoom;
    const dy = (event.clientY - lastY) * height / Math.max(rect.height, 1) / transform.zoom;
    lastX = event.clientX; lastY = event.clientY;
    onTransform({ ...transform, offsetX: transform.offsetX - dx, offsetY: transform.offsetY - dy });
  }
  function pointerUp(event: PointerEvent) { dragging = false; stage?.releasePointerCapture(event.pointerId); }
  function click(event: MouseEvent) {
    if (moved) return;
    const point = imagePoint(event); if (point) onProbe(point.x, point.y);
  }
  function wheel(event: WheelEvent) {
    event.preventDefault();
    const zoom = Math.max(1, Math.min(16, transform.zoom * Math.exp(-event.deltaY * 0.0015)));
    onTransform({ ...transform, zoom });
  }
  $effect(() => {
    const token = ++promotionToken;
    const first = intersected ? (fallbackUrl || url) : '';
    displayUrl = first;
    if (!first || !url || first === url) return;
    const full = new Image();
    full.onload = () => { if (token === promotionToken) { displayUrl = url; onPreviewLoaded?.('full'); } };
    full.src = url;
  });
  onMount(() => {
    if (eager) { intersected = true; return; }
    if (!stage) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) { intersected = true; observer.disconnect(); }
    }, { rootMargin: '180px' });
    observer.observe(stage);
    return () => observer.disconnect();
  });
</script>

<section class="image-panel">
  <header>{title}<span>{transform.zoom.toFixed(1)}×</span></header>
  <div bind:this={stage} class="image-stage" class:dragging role="button" tabindex="0"
    aria-label={`${title} interactive image viewer`} onpointerdown={pointerDown} onpointermove={pointerMove}
    onpointerup={pointerUp} onpointercancel={pointerUp} onclick={click} onwheel={wheel}
    onkeydown={(event) => event.key === 'Enter' && cursor && onProbe(cursor.x, cursor.y)}>
    {#if available}
      <svg bind:this={svg} viewBox={`${viewX} ${viewY} ${width / transform.zoom} ${height / transform.zoom}`}
        preserveAspectRatio="xMidYMid meet" role="img" aria-label={title}>
        {#if imageHref}<image href={imageHref} x="0" y="0" width={width} height={height} onload={() => { if (displayUrl === fallbackUrl && fallbackUrl !== url) onPreviewLoaded?.('fallback'); else if (displayUrl === url) onPreviewLoaded?.('full'); }} />{:else}<text x={width / 2} y={height / 2} text-anchor="middle" class="loading">Preview pending</text>{/if}
        {#if cursor}
          <line x1={cursor.x} y1="0" x2={cursor.x} y2={height} class="crosshair" vector-effect="non-scaling-stroke" />
          <line x1="0" y1={cursor.y} x2={width} y2={cursor.y} class="crosshair" vector-effect="non-scaling-stroke" />
        {/if}
      </svg>
    {:else}<div class="unavailable">Artifact unavailable</div>{/if}
  </div>
</section>
