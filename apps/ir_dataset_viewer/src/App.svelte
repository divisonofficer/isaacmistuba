<script lang="ts">
  import { onMount } from 'svelte';
  import ImagePanel, { type ViewTransform } from './ImagePanel.svelte';
  import Overview2D from './Overview2D.svelte';
  import Overview3D from './Overview3D.svelte';
  import ControlCenter from './ControlCenter.svelte';
  import SceneCatalog from './SceneCatalog.svelte';
  import {
    cancelPublishJob, getDataset, getFrame, getPixels, getPublishJob, getViewpoints, listDatasets,
    previewUrl, publishDataset, getOverview, overviewTraversabilityUrl, overviewMeshUrl, type DatasetSummary, type DisplayControls, type FrameCompact,
    type FrameDetail, type PixelResponse, type PublishJob, type Viewpoint, type SceneOverview, type OverviewPose
  } from './api';

  let datasets = $state<DatasetSummary[]>([]);
  let selectedDatasetId = $state('');
  let datasetDetail = $state<any>(null);
  let viewpoints = $state<Viewpoint[]>([]);
  let selectedViewpointId = $state('');
  let selectedFrameId = $state('');
  let frameDetail = $state<FrameDetail | null>(null);
  let modality = $state('rgb');
  let pinned = $state<string[]>(['rgb', 'nir_active', 'roughness', 'metallic']);
  let search = $state('');
  let error = $state('');
  let busy = $state(false);
  let metadataOpen = $state(false);
  let cursor = $state<{ x: number; y: number } | null>(null);
  let pixelData = $state<PixelResponse | null>(null);
  let transform = $state<ViewTransform>({ zoom: 1, offsetX: 0, offsetY: 0 });
  let controls = $state<DisplayControls>({ ev: 0, minimum: 0, maximum: 10, overlay: '', overlayOpacity: 0.45 });
  let publishName = $state('');
  let publishJob = $state<PublishJob | null>(null);
  let publishTimer: ReturnType<typeof setInterval> | null = null;
  let workspace = $state<'browse' | 'scenes' | 'control'>('browse');
  let viewMode = $state<'frame' | 'bird' | '3d'>('frame');
  let overview = $state<SceneOverview | null>(null);
  let overviewLoading = $state(false);
  let overviewLighting = $state('all');
  let hoveredPose = $state<OverviewPose | null>(null);
  let frustumLength = $state(1.25);
  let showProxy = $state(true);
  let proxyOpacity = $state(0.88);
  let showProxyStructural = $state(true);
  let showProxyFurniture = $state(true);
  let showOverviewGraph = $state(true);
  let overviewResetNonce = $state(0);
  let previewControls = $state<DisplayControls>({ ...controls });
  let previewTimer: ReturnType<typeof setTimeout> | null = null;

  const selectedDataset = $derived(datasets.find((item) => item.dataset_id === selectedDatasetId) ?? null);
  const selectedViewpoint = $derived(viewpoints.find((item) => item.viewpoint_id === selectedViewpointId) ?? null);
  const frames = $derived(selectedViewpoint?.frames ?? []);
  const selectedFrame = $derived(frames.find((item) => item.frame_id === selectedFrameId) ?? null);
  const filteredViewpoints = $derived(viewpoints.filter((item) => item.viewpoint_id.toLowerCase().includes(search.toLowerCase())));
  const groups = $derived(selectedDataset?.modality_groups ?? []);
  const imageWidth = $derived(Number(frameDetail?.frame?.width ?? selectedDataset?.width ?? 684));
  const imageHeight = $derived(Number(frameDetail?.frame?.height ?? selectedDataset?.height ?? 512));
  const maskModalities = $derived(selectedDataset?.modalities.filter((name) => name.endsWith('_mask') || name.includes('valid')) ?? []);
  const comparisonPinned = $derived(pinned.filter((name) => name !== modality));

  onMount(() => {
    window.addEventListener('keydown', onKey);
    void loadCatalog();
    return () => {
      window.removeEventListener('keydown', onKey);
      if (publishTimer) clearInterval(publishTimer);
    };
  });

  async function run<T>(fn: () => Promise<T>): Promise<T | null> {
    busy = true; error = '';
    try { return await fn(); }
    catch (cause) { error = cause instanceof Error ? cause.message : String(cause); return null; }
    finally { busy = false; }
  }

  async function loadCatalog(refresh = false) {
    const payload = await run(() => listDatasets(refresh));
    if (!payload) return;
    datasets = payload.datasets;
    const url = new URLSearchParams(location.search); const urlId = url.get('dataset');
    const requestedViewMode = url.get('view');
    if (requestedViewMode === 'bird' || requestedViewMode === '3d') viewMode = requestedViewMode;
    const choice = datasets.find((item) => item.dataset_id === (selectedDatasetId || urlId)) ?? datasets[0];
    if (choice) await selectDataset(choice.dataset_id);
  }

  async function selectDataset(id: string) {
    selectedDatasetId = id; cursor = null; pixelData = null; overview = null; hoveredPose = null; transform = { zoom: 1, offsetX: 0, offsetY: 0 };
    const [detail, viewPayload] = await Promise.all([run(() => getDataset(id)), run(() => getViewpoints(id))]);
    if (!detail || !viewPayload) return;
    datasetDetail = detail; viewpoints = viewPayload.viewpoints; publishName = detail.name;
    const params = new URLSearchParams(location.search);
    const requestedModality = params.get('modality');
    if (requestedModality && detail.modalities.includes(requestedModality)) modality = requestedModality;
    const requestedViewpoint = params.get('viewpoint');
    const requestedFrame = params.get('frame');
    const view = viewpoints.find((item) => item.viewpoint_id === requestedViewpoint)
      ?? viewpoints.find((item) => item.frames.some((frame) => frame.frame_id === requestedFrame)) ?? viewpoints[0];
    if (view) {
      selectedViewpointId = view.viewpoint_id;
      const frame = view.frames.find((item) => item.frame_id === requestedFrame) ?? view.frames[0];
      if (frame) await selectFrame(frame.frame_id);
    }
    if (!detail.modalities.includes(modality)) modality = detail.modalities[0] ?? 'rgb';
    pinned = pinned.filter((name) => detail.modalities.includes(name));
    if (pinned.length < 2) pinned = detail.modalities.slice(0, 4);
    syncUrl();
  }

  async function selectViewpoint(id: string) {
    selectedViewpointId = id; cursor = null; pixelData = null;
    const first = viewpoints.find((item) => item.viewpoint_id === id)?.frames[0];
    if (first) await selectFrame(first.frame_id);
  }

  async function selectFrame(id: string) {
    selectedFrameId = id; cursor = null; pixelData = null;
    const detail = await run(() => getFrame(selectedDatasetId, id));
    if (detail) frameDetail = detail;
    syncUrl();
  }

  function syncUrl() {
    const q = new URLSearchParams();
    if (selectedDatasetId) q.set('dataset', selectedDatasetId);
    if (selectedViewpointId) q.set('viewpoint', selectedViewpointId);
    if (selectedFrameId) q.set('frame', selectedFrameId);
    q.set('modality', modality);
    q.set('view', viewMode);
    history.replaceState(null, '', `${location.pathname}?${q}`);
  }

  function setModality(name: string) { modality = name; syncUrl(); }
  function togglePinned(name: string) {
    if (pinned.includes(name)) { if (pinned.length > 2) pinned = pinned.filter((item) => item !== name); }
    else if (pinned.length < 6) pinned = [...pinned, name];
  }
  function resetView() { transform = { zoom: 1, offsetX: 0, offsetY: 0 }; }
  function artifactAvailable(name: string): boolean { return frameDetail?.available?.[name] ?? false; }
  function imageUrl(name: string, profile: 'primary' | 'comparison' | 'hover' = 'primary'): string {
    return selectedDatasetId && selectedFrameId ? previewUrl(selectedDatasetId, selectedFrameId, name, previewControls, profile) : '';
  }
  async function setViewMode(next: 'frame' | 'bird' | '3d') {
    viewMode = next; syncUrl();
    if (next !== 'frame' && selectedDatasetId && !overview) {
      overviewLoading = true;
      try { overview = await getOverview(selectedDatasetId); } catch (cause) { error = cause instanceof Error ? cause.message : String(cause); }
      finally { overviewLoading = false; }
    }
  }
  function selectOverviewPose(pose: OverviewPose) { void selectFrame(pose.frame_id); viewMode = 'frame'; syncUrl(); }

  $effect(() => {
    controls.ev; controls.minimum; controls.maximum; controls.overlay; controls.overlayOpacity;
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(() => { previewControls = { ...controls }; }, 150);
    return () => { if (previewTimer) clearTimeout(previewTimer); };
  });

  async function probe(x: number, y: number) {
    cursor = { x, y };
    const extras = ['object_id', 'material_id', 'source_valid_mask', 'replacement_mask', 'fallback_mask', 'primary_eval_valid_mask'];
    const names = [...new Set([modality, ...pinned, ...extras])].filter((name) => selectedDataset?.modalities.includes(name));
    const result = await run(() => getPixels(selectedDatasetId, selectedFrameId, x, y, names));
    if (result) pixelData = result;
  }

  function stepFrame(delta: number) {
    const index = frames.findIndex((item) => item.frame_id === selectedFrameId);
    if (index < 0 || frames.length === 0) return;
    void selectFrame(frames[(index + delta + frames.length) % frames.length].frame_id);
  }
  function stepViewpoint(delta: number) {
    const index = viewpoints.findIndex((item) => item.viewpoint_id === selectedViewpointId);
    if (index < 0 || viewpoints.length === 0) return;
    void selectViewpoint(viewpoints[(index + delta + viewpoints.length) % viewpoints.length].viewpoint_id);
  }
  function onKey(event: KeyboardEvent) {
    if ((event.target as HTMLElement)?.matches('input, select, textarea')) return;
    if (event.key === 'ArrowLeft') stepFrame(-1);
    else if (event.key === 'ArrowRight') stepFrame(1);
    else if (event.key === 'ArrowUp') stepViewpoint(-1);
    else if (event.key === 'ArrowDown') stepViewpoint(1);
    else if (event.key === '0') resetView();
  }

  async function startPublish() {
    if (!selectedDataset || !confirm(`Publish ${selectedDataset.name} to /bean/ir_dataset/${publishName}?\nExisting datasets are never overwritten.`)) return;
    const job = await run(() => publishDataset(selectedDataset.dataset_id, publishName));
    if (!job) return;
    publishJob = job;
    if (publishTimer) clearInterval(publishTimer);
    publishTimer = setInterval(async () => {
      if (!publishJob) return;
      const latest = await getPublishJob(publishJob.job_id).catch(() => null);
      if (!latest) return;
      publishJob = latest;
      if (['succeeded', 'failed', 'cancelled'].includes(latest.status)) {
        if (publishTimer) clearInterval(publishTimer); publishTimer = null;
        if (latest.status === 'succeeded') await loadCatalog(true);
      }
    }, 1000);
  }
  async function cancelPublish() { if (publishJob) publishJob = await cancelPublishJob(publishJob.job_id); }
  function humanBytes(value: number): string {
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; let n = value; let index = 0;
    while (n >= 1024 && index < units.length - 1) { n /= 1024; index += 1; }
    return `${n.toFixed(index ? 1 : 0)} ${units[index]}`;
  }
  function valueText(value: unknown): string {
    if (Array.isArray(value)) return `[${value.map((item) => typeof item === 'number' ? item.toFixed(5) : item).join(', ')}]`;
    return typeof value === 'number' ? value.toFixed(6) : String(value);
  }
</script>

<svelte:head><title>IR Dataset Viewer</title></svelte:head>

<header class="topbar">
  <div><strong>IR Dataset Control Center</strong><span>Principled v2 · inspect and orchestrate</span></div>
  <div class="top-actions">
    {#if busy}<span class="status working">Loading</span>{/if}
    <button class:active={workspace === 'browse'} onclick={() => workspace = 'browse'}>Browse</button>
    <button class:active={workspace === 'scenes'} onclick={() => workspace = 'scenes'}>Scenes</button>
    <button class:active={workspace === 'control'} onclick={() => workspace = 'control'}>Control center</button>
    <button onclick={() => loadCatalog(true)}>Refresh</button>
  </div>
</header>

{#if error}<div class="error-banner">{error}<button onclick={() => error = ''}>×</button></div>{/if}

{#if workspace === 'control'}
  <ControlCenter onBrowse={() => workspace = 'browse'} />
{:else if workspace === 'scenes'}
  <SceneCatalog onBrowse={(id) => { workspace = 'browse'; void selectDataset(id); }} />
{:else}
<main class="shell">
  <aside class="sidebar">
    <label>Dataset<select value={selectedDatasetId} onchange={(event) => selectDataset(event.currentTarget.value)}>
      {#each datasets as item}<option value={item.dataset_id}>{item.name} · {item.frame_count}</option>{/each}
    </select></label>
    {#if selectedDataset}
      <div class="dataset-badges">
        <span class:good={selectedDataset.published}>{selectedDataset.published ? 'Published' : `${selectedDataset.primary_origin} working`}</span>
        <span>{selectedDataset.viewpoint_count} VP</span><span>{selectedDataset.frame_count} frames</span>
      </div>
      <div class="qc-row"><span>Fallback</span><b>{(Number(selectedDataset.qc?.fallback_pixel_ratio ?? 0) * 100).toFixed(3)}%</b></div>
      <div class="qc-row"><span>Replacement</span><b>{(Number(selectedDataset.qc?.replacement_pixel_ratio ?? 0) * 100).toFixed(2)}%</b></div>
    {/if}
    <label>Find viewpoint<input placeholder="vp_000002" bind:value={search} /></label>
    <div class="view-list">
      {#each filteredViewpoints as view}
        <button class:active={view.viewpoint_id === selectedViewpointId} onclick={() => selectViewpoint(view.viewpoint_id)}>
          <span>{view.viewpoint_id}</span><small>{view.frames.length} headings</small>
        </button>
      {/each}
    </div>
    {#if selectedDataset?.publishable}
      <section class="publish-card">
        <h3>Publish to /bean</h3>
        <input bind:value={publishName} aria-label="Publish name" />
        <button class="primary" onclick={startPublish} disabled={!!publishJob && ['queued','running'].includes(publishJob.status)}>Verify & Publish</button>
        {#if publishJob}
          <div class="job-state"><b>{publishJob.stage}</b><span>{publishJob.files_done}/{publishJob.files_total}</span></div>
          <progress max={Math.max(publishJob.bytes_total, 1)} value={publishJob.bytes_done}></progress>
          <small>{humanBytes(publishJob.bytes_done)} / {humanBytes(publishJob.bytes_total)} · {humanBytes(publishJob.speed_bytes_s)}/s</small>
          {#if publishJob.error}<div class="job-error">{publishJob.error}</div>{/if}
          {#if ['queued','running'].includes(publishJob.status)}<button onclick={cancelPublish}>Cancel safely</button>{/if}
        {/if}
      </section>
    {/if}
  </aside>

  <section class="workspace">
    <div class="view-mode-bar"><button class:active={viewMode === 'frame'} onclick={() => setViewMode('frame')}>Frame</button><button class:active={viewMode === 'bird'} onclick={() => setViewMode('bird')}>Bird-eye</button><button class:active={viewMode === '3d'} onclick={() => setViewMode('3d')}>3D</button>{#if overview}<small>{overview.poses.length} poses · {overview.graph_available ? 'graph' : 'index pose fallback'}</small>{/if}</div>
    {#if viewMode !== 'frame'}
      <section class="overview-stage">
        <header><div><b>{viewMode === 'bird' ? 'Bird-eye camera coverage' : '3D camera frusta'}</b><small>{overview?.fallback ? 'Pose-only overview — a legacy dataset has no scene proxy.' : overview?.proxy_mesh ? `Scene proxy · ${overview.proxy_mesh.triangles.toLocaleString()} triangles` : 'Scene-local graph and rendered poses.'}</small></div><label>Lighting <select bind:value={overviewLighting}><option value="all">All lighting</option>{#each overview?.lighting_ids ?? [] as lighting}<option value={lighting}>{lighting}</option>{/each}</select></label>{#if viewMode === '3d'}<label>Frustum <input type="range" min="0.2" max="5" step="0.1" bind:value={frustumLength} /></label><label class="check"><input type="checkbox" bind:checked={showProxy} disabled={!overview?.proxy_mesh} /> Proxy</label><label class="check"><input type="checkbox" bind:checked={showProxyStructural} disabled={!overview?.proxy_mesh || !showProxy} /> Structure</label><label class="check"><input type="checkbox" bind:checked={showProxyFurniture} disabled={!overview?.proxy_mesh || !showProxy} /> Furniture</label><label>Proxy opacity <input type="range" min="0.1" max="1" step="0.05" bind:value={proxyOpacity} disabled={!overview?.proxy_mesh || !showProxy} /></label><label class="check"><input type="checkbox" bind:checked={showOverviewGraph} /> Graph</label><button onclick={() => overviewResetNonce += 1}>Reset 3D</button>{/if}</header>
        {#if overviewLoading}<div class="empty">Loading overview…</div>{:else if overview}
          {#if viewMode === 'bird'}<Overview2D {overview} selectedFrameId={selectedFrameId} lightingFilter={overviewLighting} traversabilityUrl={overview.traversability_available ? overviewTraversabilityUrl(selectedDatasetId) : ''} onSelect={selectOverviewPose} onHover={(pose) => hoveredPose = pose} />{:else}
            {#key `${overview.dataset_fingerprint}:${overviewLighting}:${frustumLength}:${showProxy}:${proxyOpacity}:${showProxyStructural}:${showProxyFurniture}:${showOverviewGraph}:${selectedFrameId}:${overviewResetNonce}`}<Overview3D {overview} selectedFrameId={selectedFrameId} lightingFilter={overviewLighting} {frustumLength} meshUrl={overview.proxy_mesh && showProxy ? overviewMeshUrl(selectedDatasetId) : ''} {showProxy} {proxyOpacity} showStructural={showProxyStructural} showFurniture={showProxyFurniture} showGraph={showOverviewGraph} onSelect={selectOverviewPose} onHover={(pose) => hoveredPose = pose} />{/key}
          {/if}
          {#if hoveredPose}<aside class="overview-hover"><img src={previewUrl(selectedDatasetId, hoveredPose.frame_id, 'rgb', previewControls, 'hover')} alt="RGB hover preview"/><b>{hoveredPose.viewpoint_id} · {hoveredPose.heading_deg}°</b><small>{hoveredPose.lighting_id}</small></aside>{/if}
        {:else}<div class="empty">Overview unavailable.</div>{/if}
      </section>
    {:else}
    <div class="framebar">
      <button onclick={() => stepFrame(-1)}>←</button>
      <div class="headings">
        {#each frames as frame}<button class:active={frame.frame_id === selectedFrameId} onclick={() => selectFrame(frame.frame_id)} title={frame.frame_id}>{frame.heading_deg}°{#if frame.frame_id.includes('__l_')} · {frame.frame_id.split('__l_')[1].replace(/_v1$/, '')}{/if}</button>{/each}
      </div>
      <button onclick={() => stepFrame(1)}>→</button>
    </div>

    <div class="toolbar">
      <span class="frame-title">{selectedFrameId || 'No frame'}</span>
      <label>EV <input type="range" min="-8" max="8" step="0.25" bind:value={controls.ev} /><output>{Number(controls.ev).toFixed(2)}</output></label>
      <label>Depth max <input type="number" min="0.1" step="0.5" bind:value={controls.maximum} /></label>
      <label>Overlay <select bind:value={controls.overlay}><option value="">None</option>{#each maskModalities as name}<option value={name}>{name}</option>{/each}</select></label>
      <label>Opacity <input type="range" min="0" max="1" step="0.05" bind:value={controls.overlayOpacity} /></label>
      <button onclick={resetView}>Reset view (0)</button>
      <button onclick={() => metadataOpen = !metadataOpen}>Metadata</button>
    </div>

    <nav class="modalities">
      {#each groups as group}
        <div><span>{group.label}</span>{#each group.modalities as name}
          <button class:active={name === modality} onclick={() => setModality(name)}>{name}</button>
          <button class="pin" class:pinned={pinned.includes(name)} title="Toggle comparison" onclick={() => togglePinned(name)}>+</button>
        {/each}</div>
      {/each}
    </nav>

    {#if selectedDataset && selectedFrameId}
      <div class="primary-view">
        <ImagePanel title={modality} url={imageUrl(modality, 'primary')} width={imageWidth} height={imageHeight} eager
          available={artifactAvailable(modality)} {transform} {cursor}
          onTransform={(value) => transform = value} onProbe={probe} />
        <aside class="pixel-panel">
          <h3>Raw pixel</h3>
          {#if pixelData}
            <div class="coords">x {pixelData.x} · y {pixelData.y}</div>
            {#each Object.entries(pixelData.values) as [name, item]}
              <div class="pixel-row"><span>{name}</span><b>{item.available ? valueText(item.value) : '—'}</b><small>{item.unit ?? ''}</small></div>
            {/each}
          {:else}<p>Click an image to inspect exact source values.</p>{/if}
        </aside>
      </div>
      <section class="compare-section">
        <header><h2>Synced comparison</h2><span>{comparisonPinned.length}/5 additional modalities</span></header>
        <div class="compare-grid">
          {#each comparisonPinned as name}
            <ImagePanel title={name} url={imageUrl(name, 'comparison')} width={imageWidth} height={imageHeight}
              available={artifactAvailable(name)} {transform} {cursor}
              onTransform={(value) => transform = value} onProbe={probe} />
          {/each}
        </div>
      </section>
    {:else}<div class="empty">No compatible Principled v2 dataset found.</div>{/if}
    {/if}
  </section>

  {#if metadataOpen && frameDetail}
    <aside class="metadata-drawer">
      <header><strong>Frame metadata</strong><button onclick={() => metadataOpen = false}>×</button></header>
      <h3>Camera</h3><pre>{JSON.stringify(frameDetail.frame.camera, null, 2)}</pre>
      <h3>Intrinsics</h3><pre>{JSON.stringify(frameDetail.frame.intrinsics, null, 2)}</pre>
      <h3>Timing / QC</h3><pre>{JSON.stringify({ timings_s: frameDetail.frame.timings_s, nir_qc: frameDetail.frame.nir_qc, diffuse_decomposition_qc: frameDetail.frame.diffuse_decomposition_qc }, null, 2)}</pre>
      <h3>Artifact contract</h3><pre>{JSON.stringify(datasetDetail?.contract, null, 2)}</pre>
    </aside>
  {/if}
</main>
{/if}
