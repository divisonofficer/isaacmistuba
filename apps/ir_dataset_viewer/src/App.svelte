<script lang="ts">
  import { onMount } from 'svelte';
  import ImagePanel, { type ViewTransform } from './ImagePanel.svelte';
  import Overview2D from './Overview2D.svelte';
  import Overview3D from './Overview3D.svelte';
  import ControlCenter from './ControlCenter.svelte';
  import SceneCatalog from './SceneCatalog.svelte';
  import {
    cancelPublishJob, getBrowse, getDataset, getFrame, getPixels, getPublishJob, listDatasets, invalidateDatasetSessionCache,
    previewUrl, publishDataset, getOverview, overviewTraversabilityUrl, overviewMeshUrl, type DatasetSummary, type DisplayControls, type FrameCompact,
    type FrameDetail, type PixelResponse, type PublishJob, type Viewpoint, type SceneOverview, type OverviewPose, type HeadingGroup
  } from './api';

  let datasets = $state<DatasetSummary[]>([]);
  let selectedDatasetId = $state('');
  let datasetDetail = $state<any>(null);
  let viewpoints = $state<Viewpoint[]>([]);
  let selectedViewpointId = $state('');
  let selectedFrameId = $state('');
  let selectedHeadingKey = $state('');
  let selectedLightingId = $state('');
  // Camera heading is the physical pose axis; lighting is an orthogonal
  // capture axis.  Keep an explicit filter so the frame navigator never
  // makes the two look like one combined heading list.
  let frameLightingFilter = $state('all');
  let headingNavigationMode = $state<'heading' | 'lighting'>('heading');
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
  let sceneCatalogRefreshNonce = $state(0);
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
  let idlePrefetchTimer: ReturnType<typeof setTimeout> | null = null;
  let prefetchEpoch = 0;
  let controlsDragging = $state(false);
  let prefetchTrigger = $state(0);
  let frameTransitionStarted = 0;
  let viewerMetrics = $state({ bootstrap_ms: 0, preview_first_ms: 0, preview_full_ms: 0,
    prefetch_dispatched: 0, prefetch_cancelled: 0, prefetch_cache_hits: 0, prefetch_completed: 0 });
  let datasetAbort: AbortController | null = null;
  let frameAbort: AbortController | null = null;
  let pixelAbort: AbortController | null = null;
  let prefetchAbort: AbortController | null = null;

  // Keep the viewer usable when an older/partially published dataset has no
  // catalog-level modality_groups.  The frame endpoint is authoritative for
  // the artifacts that actually exist, so its `available` map is folded into
  // the selector once the first frame is loaded.
  const modalityGroupDefinitions = [
    { id: 'observation', label: 'Observation', modalities: ['rgb', 'nir_active', 'nir_passive', 'nir_active_minus_passive'] },
    { id: 'pbr', label: 'PBR', modalities: ['base_color_rgb', 'base_color_nir', 'roughness', 'metallic'] },
    { id: 'geometry', label: 'Geometry', modalities: ['normal_geometry_world', 'normal_shading_world', 'depth', 'range'] },
    { id: 'id', label: 'ID', modalities: ['object_id', 'material_id'] },
    { id: 'mask', label: 'Mask', modalities: ['train_pbr_valid_mask', 'remediated_pbr_mask', 'pbr_provenance_class', 'fallback_mask', 'replacement_mask', 'source_valid_mask', 'gt_defined_mask', 'primary_eval_valid_mask', 'diffuse_transport_valid_rgb', 'diffuse_transport_valid_nir', 'diffuse_shading_valid_rgb', 'diffuse_shading_valid_nir'] },
    { id: 'diffuse', label: 'Diffuse transport', modalities: ['diffuse_transport_rgb', 'diffuse_transport_nir', 'diffuse_reflectance_rgb', 'diffuse_reflectance_nir', 'diffuse_component_rgb', 'diffuse_component_nir'] },
  ];
  const modalityLabels: Record<string, string> = {
    diffuse_transport_rgb: 'diffuse transport (RGB)', diffuse_transport_nir: 'diffuse transport (NIR)',
    diffuse_reflectance_rgb: 'diffuse reflectance (RGB)', diffuse_reflectance_nir: 'diffuse reflectance (NIR)',
    diffuse_component_rgb: 'diffuse component (RGB)', diffuse_component_nir: 'diffuse component (NIR)',
    diffuse_shading_rgb: 'legacy reflectance-normalized diagnostic (RGB)',
    diffuse_shading_nir: 'legacy reflectance-normalized diagnostic (NIR)',
    legacy_diffuse_component_corrected_rgb: 'legacy virtual corrected component (RGB)',
    legacy_diffuse_component_corrected_nir: 'legacy virtual corrected component (NIR)',
    nir_active: 'NIR active',
    nir_passive: 'NIR passive',
    nir_active_minus_passive: 'Flash only (active − passive)',
  };
  function modalityLabel(name: string): string {
    if (frameDetail?.legacy_diffuse_warning && name.startsWith('diffuse_component_')) {
      return name.endsWith('_nir') ? 'legacy diffuse transport (NIR)' : 'legacy diffuse transport (RGB)';
    }
    return modalityLabels[name] ?? name;
  }
  function extractModalities(value: any): string[] {
    const raw = value?.modalities ?? value?.dataset?.modalities ?? [];
    return Array.isArray(raw) ? raw.map(String).filter(Boolean) : [];
  }
  function buildModalityGroups(modalities: string[]) {
    const available = new Set(modalities);
    const result = modalityGroupDefinitions
      .map((group) => ({ ...group, modalities: group.modalities.filter((name) => available.has(name)) }))
      .filter((group) => group.modalities.length > 0);
    const known = new Set(result.flatMap((group) => group.modalities));
    const other = modalities.filter((name) => !known.has(name)).sort();
    if (other.length) result.push({ id: 'other', label: 'Other', modalities: other });
    return result;
  }

  const selectedDataset = $derived(datasets.find((item) => item.dataset_id === selectedDatasetId) ?? null);
  const selectedViewpoint = $derived(viewpoints.find((item) => item.viewpoint_id === selectedViewpointId) ?? null);
  const frames = $derived(selectedViewpoint?.frames ?? []);
  const headingGroups = $derived(selectedViewpoint?.headings ?? []);
  const selectedHeading = $derived(headingGroups.find((item) => item.heading_key === selectedHeadingKey) ?? headingGroups[0] ?? null);
  const lightingIds = $derived(Array.from(new Set(frames.map((item) => item.lighting_id || 'legacy'))).sort());
  const visibleHeadingGroups = $derived(headingGroups.filter((group) => frameLightingFilter === 'all' || group.frames.some((item) => (item.lighting_id || 'legacy') === frameLightingFilter)));
  const headingFrames = $derived(selectedHeading?.frames.filter((item) => frameLightingFilter === 'all' || (item.lighting_id || 'legacy') === frameLightingFilter) ?? frames);
  const lightingHeadingGroups = $derived(
    lightingIds.map((lightingId) => ({
      lightingId,
      frames: frames.filter((item) => (item.lighting_id || 'legacy') === lightingId),
      headings: headingGroups
        .map((group) => ({ ...group, frames: group.frames.filter((item) => (item.lighting_id || 'legacy') === lightingId) }))
        .filter((group) => group.frames.length > 0),
    })).filter((group) => group.frames.length > 0)
  );
  const selectedLightingGroup = $derived(lightingHeadingGroups.find((group) => group.lightingId === selectedLightingId) ?? lightingHeadingGroups[0] ?? null);
  const selectedFrame = $derived(frames.find((item) => item.frame_id === selectedFrameId) ?? null);
  const filteredViewpoints = $derived(viewpoints.filter((item) => item.viewpoint_id.toLowerCase().includes(search.toLowerCase())));
  const frameAvailableModalities = $derived(
    Array.from(new Set([
      ...(selectedFrame?.available ?? []),
      ...Object.entries(frameDetail?.available ?? {}).filter(([, available]) => Boolean(available)).map(([name]) => name),
    ]))
  );
  const datasetModalities = $derived(Array.from(new Set([
    ...extractModalities(datasetDetail), ...extractModalities(selectedDataset), ...frameAvailableModalities,
  ])));
  const groups = $derived(buildModalityGroups(datasetModalities));
  const imageWidth = $derived(Number(frameDetail?.frame?.width ?? datasetDetail?.width ?? selectedDataset?.width ?? 684));
  const imageHeight = $derived(Number(frameDetail?.frame?.height ?? datasetDetail?.height ?? selectedDataset?.height ?? 512));
  const maskModalities = $derived(datasetModalities.filter((name) => name.endsWith('_mask') || name.includes('valid')));
  const comparisonPinned = $derived(pinned.filter((name) => name !== modality));
  const structuralOverride = $derived(datasetDetail?.contract?.structural_rematerialization ?? frameDetail?.frame?.structural_rematerialization ?? null);

  onMount(() => {
    window.addEventListener('keydown', onKey);
    void loadCatalog();
    return () => {
      window.removeEventListener('keydown', onKey);
      if (publishTimer) clearInterval(publishTimer);
      datasetAbort?.abort(); frameAbort?.abort(); pixelAbort?.abort(); invalidatePrefetch();
    };
  });

  async function run<T>(fn: () => Promise<T>): Promise<T | null> {
    busy = true; error = '';
    try { return await fn(); }
    catch (cause) { error = cause instanceof Error ? cause.message : String(cause); return null; }
    finally { busy = false; }
  }

  async function loadCatalog(refresh = false) {
    if (refresh) invalidateDatasetSessionCache();
    const payload = await run(() => listDatasets(refresh));
    if (!payload) return;
    datasets = payload.datasets;
    const url = new URLSearchParams(location.search); const urlId = url.get('dataset');
    const requestedViewMode = url.get('view');
    if (requestedViewMode === 'bird' || requestedViewMode === '3d') viewMode = requestedViewMode;
    if (url.get('group') === 'lighting') headingNavigationMode = 'lighting';
    const choice = datasets.find((item) => item.dataset_id === (selectedDatasetId || urlId)) ?? datasets[0];
    if (choice) {
      const requestedId = selectedDatasetId || urlId || '';
      await selectDataset(choice.dataset_id);
      // A retired dataset can remain in a browser tab's query string after
      // it has been removed from the catalog.  Canonicalize that stale URL
      // immediately, otherwise old frame/previews keep targeting the hidden
      // fingerprint and every modality reports a confusing 404.
      if (requestedId && requestedId !== choice.dataset_id && selectedDatasetId === choice.dataset_id) {
        const canonical = new URLSearchParams(location.search);
        canonical.set('dataset', choice.dataset_id);
        if (!selectedFrameId) { canonical.delete('viewpoint'); canonical.delete('frame'); }
        history.replaceState(null, '', `${location.pathname}?${canonical}`);
      }
    } else {
      // Empty catalog (for example while all visible datasets are archived)
      // must not leave a removed dataset selected in the UI state.
      selectedDatasetId = '';
      datasetDetail = null; viewpoints = []; selectedViewpointId = ''; selectedFrameId = '';
      history.replaceState(null, '', `${location.pathname}?view=${viewMode}`);
    }
  }

  function refreshWorkspace() {
    if (workspace === 'scenes') {
      // SceneCatalog is intentionally retained across Scene ↔ Browse
      // navigation.  Ask that persistent component to revalidate only when
      // the user explicitly clicks Refresh.
      sceneCatalogRefreshNonce += 1;
      return;
    }
    void loadCatalog(true);
  }

  async function selectDataset(id: string) {
    datasetAbort?.abort(); frameAbort?.abort(); pixelAbort?.abort(); invalidatePrefetch();
    const controller = new AbortController(); datasetAbort = controller;
    selectedDatasetId = id; cursor = null; pixelData = null; frameDetail = null; overview = null; hoveredPose = null; transform = { zoom: 1, offsetX: 0, offsetY: 0 };
    const params = new URLSearchParams(location.search);
    let bootstrap;
    try {
      const started = performance.now();
      bootstrap = await getBrowse(id, { viewpoint: params.get('viewpoint') ?? '', frame: params.get('frame') ?? '' }, controller.signal);
      viewerMetrics.bootstrap_ms = performance.now() - started;
      console.debug('[ir-viewer] browse bootstrap', { ms: viewerMetrics.bootstrap_ms });
    } catch (cause) {
      if ((cause as DOMException)?.name !== 'AbortError') error = cause instanceof Error ? cause.message : String(cause);
      return;
    }
    if (controller.signal.aborted || selectedDatasetId !== id) return;
    datasetDetail = bootstrap.dataset; viewpoints = bootstrap.viewpoints; publishName = bootstrap.dataset.name;
    const requestedModality = params.get('modality');
    const detailModalities = extractModalities(bootstrap.dataset);
    if (requestedModality && detailModalities.includes(requestedModality)) modality = requestedModality;
    const requestedViewpoint = params.get('viewpoint');
    const requestedFrame = params.get('frame');
    const view = viewpoints.find((item) => item.viewpoint_id === bootstrap.selected_viewpoint_id)
      ?? viewpoints.find((item) => item.viewpoint_id === requestedViewpoint)
      ?? viewpoints.find((item) => item.frames.some((frame) => frame.frame_id === requestedFrame)) ?? viewpoints[0];
    if (view) {
      selectedViewpointId = view.viewpoint_id;
      const requestedLightingId = requestedFrame?.match(/__l_(.+)$/)?.[1] ?? '';
      selectedHeadingKey = view.headings?.find((group) => group.frames.some((item) => item.frame_id === requestedFrame))?.heading_key
        ?? view.headings?.[0]?.heading_key ?? '';
      selectedLightingId = requestedLightingId || view.headings?.[0]?.frames?.[0]?.lighting_id || '';
      const exact = requestedFrame ? view.frames.find((item) => item.frame_id === requestedFrame) : null;
      // Prefer the same lighting condition when a stale plan changed the
      // heading encoding (for example __h_015__l_side_key_v1 -> __h_214__a_*).
      const requestedLighting = requestedFrame?.match(/__l_(.+)$/)?.[1];
      const lightingMatch = requestedLighting
        ? view.frames.find((item) => item.frame_id.endsWith(`__l_${requestedLighting}`))
        : null;
      const frame = view.frames.find((item) => item.frame_id === bootstrap.selected_frame_id) ?? exact ?? lightingMatch ?? view.frames[0];
      if (frame) {
        const staleFrame = Boolean(requestedFrame && !exact);
        selectFrame(frame.frame_id);
        if (staleFrame) {
          // Frame plans are immutable and may be regenerated with different
          // headings/lighting suffixes. A stale URL must not make a valid
          // dataset look incompatible; keep the requested viewpoint and open
          // its first currently indexed frame, then canonicalize the URL.
          error = `Requested frame “${requestedFrame}” is not in this dataset; opened ${frame.frame_id}.`;
        }
      }
    }
    if (!detailModalities.includes(modality) && detailModalities.length) modality = detailModalities[0];
    if (detailModalities.includes('nir_passive')) {
      pinned = ['nir_active', 'nir_passive', 'nir_active_minus_passive', 'roughness', 'metallic']
        .filter((name) => detailModalities.includes(name));
    } else {
      pinned = pinned.filter((name) => detailModalities.includes(name));
    }
    if (pinned.length < 2 && detailModalities.length) pinned = detailModalities.slice(0, 4);
    syncUrl();
  }

  async function selectViewpoint(id: string) {
    selectedViewpointId = id; cursor = null; pixelData = null;
    const view = viewpoints.find((item) => item.viewpoint_id === id);
    frameLightingFilter = 'all';
    selectedHeadingKey = view?.headings?.[0]?.heading_key ?? '';
    selectedLightingId = view?.headings?.[0]?.frames?.[0]?.lighting_id ?? '';
    const first = view?.headings?.[0]?.frames?.[0] ?? view?.frames[0];
    if (first) selectFrame(first.frame_id);
  }

  async function selectHeading(key: string) {
    selectedHeadingKey = key;
    const group = headingGroups.find((item) => item.heading_key === key);
    const candidates = group?.frames.filter((item) => frameLightingFilter === 'all' || (item.lighting_id || 'legacy') === frameLightingFilter) ?? [];
    selectedLightingId = candidates[0]?.lighting_id ?? group?.frames?.[0]?.lighting_id ?? '';
    const first = candidates[0] ?? group?.frames?.[0];
    if (first) selectFrame(first.frame_id);
  }

  async function selectLighting(id: string) {
    selectedLightingId = id;
    const frame = headingFrames.find((item) => (item.lighting_id || 'legacy') === id) ?? headingFrames[0];
    if (frame) selectFrame(frame.frame_id);
  }

  async function setFrameLightingFilter(id: string) {
    frameLightingFilter = id;
    const group = visibleHeadingGroups.find((item) => item.heading_key === selectedHeadingKey) ?? visibleHeadingGroups[0];
    if (!group) return;
    if (group.heading_key !== selectedHeadingKey) selectedHeadingKey = group.heading_key;
    const frame = group.frames.find((item) => (item.lighting_id || 'legacy') === id) ?? group.frames[0];
    if (frame) selectFrame(frame.frame_id);
  }

  async function selectLightingGroup(id: string) {
    headingNavigationMode = 'lighting';
    frameLightingFilter = id;
    selectedLightingId = id;
    const group = lightingHeadingGroups.find((item) => item.lightingId === id);
    const heading = group?.headings.find((item) => item.heading_key === selectedHeadingKey) ?? group?.headings[0];
    if (heading) selectedHeadingKey = heading.heading_key;
    const frame = heading?.frames[0] ?? group?.frames[0];
    if (frame) selectFrame(frame.frame_id);
  }

  function setHeadingNavigationMode(mode: 'heading' | 'lighting') {
    headingNavigationMode = mode;
    syncUrl();
  }

  function selectFrame(id: string) {
    frameAbort?.abort(); pixelAbort?.abort(); invalidatePrefetch();
    frameTransitionStarted = performance.now();
    viewerMetrics.preview_first_ms = 0; viewerMetrics.preview_full_ms = 0;
    selectedFrameId = id; cursor = null; pixelData = null;
    frameDetail = null;
    const frame = frames.find((item) => item.frame_id === id);
    if (frame) {
      selectedHeadingKey = frame.pose_key || selectedHeadingKey;
      selectedLightingId = frame.lighting_id || 'legacy';
    }
    syncUrl();
    if (metadataOpen) void ensureFrameDetail();
  }

  async function ensureDatasetDetail() {
    if (datasetDetail?.contract && datasetDetail?.dataset_id === selectedDatasetId) return;
    datasetAbort?.abort(); const controller = new AbortController(); datasetAbort = controller;
    try {
      const detail = await getDataset(selectedDatasetId, controller.signal);
      if (!controller.signal.aborted && detail.dataset_id === selectedDatasetId) datasetDetail = detail;
    } catch (cause) {
      if ((cause as DOMException)?.name !== 'AbortError') error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function ensureFrameDetail() {
    if (!selectedDatasetId || !selectedFrameId || frameDetail?.frame?.frame_id === selectedFrameId) return;
    frameAbort?.abort(); const controller = new AbortController(); frameAbort = controller;
    const id = selectedFrameId;
    try {
      const detail = await getFrame(selectedDatasetId, id, controller.signal);
      if (!controller.signal.aborted && selectedFrameId === id) frameDetail = detail;
    } catch (cause) {
      if ((cause as DOMException)?.name !== 'AbortError') error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  function invalidatePrefetch() {
    prefetchEpoch += 1;
    if (idlePrefetchTimer) { clearTimeout(idlePrefetchTimer); idlePrefetchTimer = null; }
    if (prefetchAbort) { prefetchAbort.abort(); prefetchAbort = null; viewerMetrics.prefetch_cancelled += 1; }
  }

  async function fetchPrefetches(urls: string[], epoch: number, controller: AbortController) {
    for (const url of urls) {
      if (controller.signal.aborted || epoch !== prefetchEpoch) return;
      try {
        const response = await fetch(url, { signal: controller.signal, cache: 'force-cache' });
        if (response.ok && epoch === prefetchEpoch) {
          viewerMetrics.prefetch_completed += 1;
          if ((response.headers.get('X-IR-Preview-Cache') || 'miss') !== 'miss') viewerMetrics.prefetch_cache_hits += 1;
        }
      } catch { /* aborts are expected when users move to the next heading */ }
    }
  }

  function startIdlePrefetch(frameId: string, epoch: number) {
    const view = viewpoints.find((item) => item.viewpoint_id === selectedViewpointId);
    const current = view?.frames.find((item) => item.frame_id === frameId);
    if (!view || !current || !selectedDatasetId) return;
    const lighting = current.lighting_id || 'legacy';
    const ordered = (view.headings ?? []).filter((group) => group.frames.some((item) => (item.lighting_id || 'legacy') === lighting));
    const index = ordered.findIndex((group) => group.frames.some((item) => item.frame_id === frameId));
    if (index < 0) return;
    const next = ordered[index + 1]?.frames.find((item) => (item.lighting_id || 'legacy') === lighting);
    const previous = ordered[index - 1]?.frames.find((item) => (item.lighting_id || 'legacy') === lighting);
    const urlsFor = (frame: FrameCompact | undefined, names: string[]) => frame ? names
      .filter((name) => frame.available.includes(name))
      .map((name) => previewUrl(selectedDatasetId, frame.frame_id, name, previewControls, 'comparison', 'prefetch')) : [];
    // One serialized idle stream preserves the intended next-heading-first
    // policy and never competes with an interactive browser image request.
    const urls = [
      ...urlsFor(next, ['rgb', 'nir_active']),
      ...urlsFor(next, ['roughness', 'metallic']),
      ...urlsFor(previous, ['rgb', 'nir_active']),
      ...urlsFor(previous, ['roughness', 'metallic']),
    ];
    if (!urls.length || epoch !== prefetchEpoch) return;
    const controller = new AbortController(); prefetchAbort = controller;
    viewerMetrics.prefetch_dispatched += urls.length;
    void fetchPrefetches(urls, epoch, controller);
  }

  function scheduleIdlePrefetch() {
    invalidatePrefetch();
    if (!selectedFrameId || controlsDragging) return;
    const epoch = prefetchEpoch;
    const frameId = selectedFrameId;
    idlePrefetchTimer = setTimeout(() => {
      idlePrefetchTimer = null;
      if (!controlsDragging && epoch === prefetchEpoch && selectedFrameId === frameId) startIdlePrefetch(frameId, epoch);
    }, 300);
  }

  function beginControlDrag() { controlsDragging = true; invalidatePrefetch(); }
  function endControlDrag() { controlsDragging = false; prefetchTrigger += 1; }
  function recordPreview(stage: 'fallback' | 'full') {
    if (!frameTransitionStarted) return;
    const elapsed = performance.now() - frameTransitionStarted;
    if (stage === 'fallback' && !viewerMetrics.preview_first_ms) viewerMetrics.preview_first_ms = elapsed;
    if (stage === 'full') viewerMetrics.preview_full_ms = elapsed;
    console.debug('[ir-viewer] preview', { stage, ms: elapsed, frame: selectedFrameId });
  }

  function syncUrl() {
    const q = new URLSearchParams();
    if (selectedDatasetId) q.set('dataset', selectedDatasetId);
    if (selectedViewpointId) q.set('viewpoint', selectedViewpointId);
    if (selectedFrameId) q.set('frame', selectedFrameId);
    q.set('modality', modality);
    q.set('view', viewMode);
    q.set('group', headingNavigationMode);
    history.replaceState(null, '', `${location.pathname}?${q}`);
  }

  function setModality(name: string) { modality = name; syncUrl(); }
  function togglePinned(name: string) {
    if (pinned.includes(name)) { if (pinned.length > 2) pinned = pinned.filter((item) => item !== name); }
    else if (pinned.length < 6) pinned = [...pinned, name];
  }
  function resetView() { transform = { zoom: 1, offsetX: 0, offsetY: 0 }; }
  function artifactAvailable(name: string): boolean {
    if (selectedFrame?.available?.includes(name)) return true;
    return frameDetail?.frame?.frame_id === selectedFrameId && Boolean(frameDetail.available?.[name]);
  }
  function imageUrl(name: string, profile: 'primary' | 'comparison' | 'hover' = 'primary'): string {
    const priority = profile === 'primary' ? 'interactive' : profile === 'comparison' ? 'comparison' : 'prefetch';
    return selectedDatasetId && selectedFrameId ? previewUrl(selectedDatasetId, selectedFrameId, name, previewControls, profile, priority) : '';
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

  $effect(() => {
    selectedFrameId; selectedViewpointId; selectedLightingId; modality; prefetchTrigger;
    previewControls.ev; previewControls.minimum; previewControls.maximum; previewControls.overlay; previewControls.overlayOpacity;
    scheduleIdlePrefetch();
  });

  async function probe(x: number, y: number) {
    cursor = { x, y };
    const extras = ['object_id', 'material_id', 'source_valid_mask', 'replacement_mask', 'fallback_mask', 'primary_eval_valid_mask'];
    const names = [...new Set([modality, ...pinned, ...extras])].filter((name) => datasetModalities.includes(name));
    pixelAbort?.abort(); const controller = new AbortController(); pixelAbort = controller;
    try {
      const result = await getPixels(selectedDatasetId, selectedFrameId, x, y, names, controller.signal);
      if (!controller.signal.aborted && cursor?.x === x && cursor?.y === y) pixelData = result;
    } catch (cause) {
      if ((cause as DOMException)?.name !== 'AbortError') error = cause instanceof Error ? cause.message : String(cause);
    }
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
    <button onclick={refreshWorkspace}>Refresh</button>
  </div>
</header>

{#if error}<div class="error-banner">{error}<button onclick={() => error = ''}>×</button></div>{/if}

<!-- Keep the Scene catalog mounted while any workspace is open. Its own
     explicit Refresh is the only normal revalidation path. -->
<section hidden={workspace !== 'scenes'}>
  <SceneCatalog active={workspace === 'scenes'} refreshNonce={sceneCatalogRefreshNonce}
    onBrowse={(id) => { workspace = 'browse'; void selectDataset(id); }} />
</section>

{#if workspace === 'control'}
  <ControlCenter onBrowse={() => workspace = 'browse'} />
{:else}
<main class="shell" hidden={workspace !== 'browse'}>
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
          <span>{view.viewpoint_id}</span><small>{view.pose_count ?? view.headings?.length ?? view.frames.length} poses · {(view.lighting_ids ?? []).length || 1} lighting</small>
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
      <div class="navigator-mode" aria-label="Frame grouping mode">
        <button class:active={headingNavigationMode === 'heading'} onclick={() => setHeadingNavigationMode('heading')}>Group by heading</button>
        <button class:active={headingNavigationMode === 'lighting'} onclick={() => setHeadingNavigationMode('lighting')}>Group by lighting</button>
      </div>
      {#if headingNavigationMode === 'heading'}
        <div class="headings" aria-label="Physical camera headings">
          {#each visibleHeadingGroups as group}<button class:active={group.heading_key === selectedHeadingKey} onclick={() => selectHeading(group.heading_key)} title={group.anchor_id ? `anchor ${group.anchor_id}` : ''}>{group.heading_deg}°{#if group.anchor_id} · {group.anchor_id.slice(0, 8)}{/if}<small>{group.frames.length} lighting</small></button>{/each}
        </div>
      {:else}
        <div class="headings lighting-groups" aria-label="Lighting condition groups">
          {#each lightingHeadingGroups as group}<button class:active={group.lightingId === selectedLightingId} onclick={() => selectLightingGroup(group.lightingId)}><b>{group.lightingId.replace(/_v1$/, '').replaceAll('_', ' ')}</b><small>{group.headings.length} headings · {group.frames.length} frames</small></button>{/each}
        </div>
      {/if}
      <button onclick={() => stepFrame(1)}>→</button>
    </div>
    <div class="lighting-filterbar">
      <span>Physical headings <b>{headingGroups.length}</b></span>
      <span>Lighting captures <b>{lightingIds.length || 1}</b></span>
      <label>Show lighting
        <select value={frameLightingFilter} onchange={(event) => setFrameLightingFilter(event.currentTarget.value)}>
          <option value="all">All conditions</option>
          {#each lightingIds as lighting}<option value={lighting}>{lighting.replace(/_v1$/, '').replaceAll('_', ' ')}</option>{/each}
        </select>
      </label>
    </div>
    {#if headingNavigationMode === 'lighting' && selectedLightingGroup}
      <div class="lightingbar"><span>Headings <small>({selectedLightingGroup.lightingId.replace(/_v1$/, '').replaceAll('_', ' ')})</small></span>{#each selectedLightingGroup.headings as group}<button class:active={group.heading_key === selectedHeadingKey} onclick={() => { frameLightingFilter = selectedLightingGroup.lightingId; selectHeading(group.heading_key); }}>{group.heading_deg}°<small>{group.frames.length} frame</small></button>{/each}</div>
    {:else if selectedHeading}
      <div class="lightingbar"><span>Lighting condition <small>(heading fixed)</small></span>{#each selectedHeading.frames as frame}<button class:active={(frame.lighting_id || 'legacy') === selectedLightingId} onclick={() => selectLighting(frame.lighting_id || 'legacy')} title={frame.frame_id}>{(frame.lighting_id || 'legacy').replace(/_v1$/, '').replaceAll('_', ' ')}</button>{/each}</div>
    {/if}

    <div class="toolbar">
      <span class="frame-title">{selectedFrameId || 'No frame'}</span>
      <label>EV <input type="range" min="-8" max="8" step="0.25" bind:value={controls.ev} onpointerdown={beginControlDrag} onpointerup={endControlDrag} onpointercancel={endControlDrag} /><output>{Number(controls.ev).toFixed(2)}</output></label>
      <label>Depth max <input type="number" min="0.1" step="0.5" bind:value={controls.maximum} /></label>
      <label>Overlay <select bind:value={controls.overlay}><option value="">None</option>{#each maskModalities as name}<option value={name}>{name}</option>{/each}</select></label>
      <label>Opacity <input type="range" min="0" max="1" step="0.05" bind:value={controls.overlayOpacity} onpointerdown={beginControlDrag} onpointerup={endControlDrag} onpointercancel={endControlDrag} /></label>
      <button onclick={resetView}>Reset view (0)</button>
      <button onclick={() => { metadataOpen = !metadataOpen; if (metadataOpen) { void ensureDatasetDetail(); void ensureFrameDetail(); } }}>Metadata</button>
    </div>

    <nav class="modalities">
      {#each groups as group}
        <div><span>{group.label}</span>{#each group.modalities as name}
          <button class:active={name === modality} onclick={() => setModality(name)} title={name}>{modalityLabel(name)}</button>
          <button class="pin" class:pinned={pinned.includes(name)} title="Toggle comparison" onclick={() => togglePinned(name)}>+</button>
        {/each}</div>
      {/each}
      {#if groups.length === 0 && datasetModalities.length === 0}
        <span class="modalities-empty">No modality metadata yet; select a frame to load available artifacts.</span>
      {/if}
    </nav>
    {#if frameDetail?.legacy_diffuse_warning}
      <p class="legacy-warning">{frameDetail.legacy_diffuse_warning}</p>
    {/if}

    {#if selectedDataset && selectedFrameId}
      <div class="primary-view">
        <ImagePanel title={modalityLabel(modality)} url={imageUrl(modality, 'primary')} fallbackUrl={imageUrl(modality, 'comparison')} width={imageWidth} height={imageHeight} eager
          available={artifactAvailable(modality)} {transform} {cursor}
          onTransform={(value) => transform = value} onProbe={probe} onPreviewLoaded={recordPreview} />
        <aside class="pixel-panel">
          <h3>Raw pixel</h3>
          {#if pixelData}
            <div class="coords">x {pixelData.x} · y {pixelData.y}</div>
            {#each Object.entries(pixelData.values) as [name, item]}
              <div class="pixel-row"><span title={name}>{modalityLabel(name)}</span><b>{item.available ? valueText(item.value) : '—'}</b><small>{item.unit ?? ''}</small></div>
            {/each}
          {:else}<p>Click an image to inspect exact source values.</p>{/if}
        </aside>
      </div>
      <section class="compare-section">
        <header><h2>Synced comparison</h2><span>{comparisonPinned.length}/5 additional modalities</span></header>
        <div class="compare-grid">
          {#each comparisonPinned as name}
            <ImagePanel title={modalityLabel(name)} url={imageUrl(name, 'comparison')} width={imageWidth} height={imageHeight}
              available={artifactAvailable(name)} {transform} {cursor}
              onTransform={(value) => transform = value} onProbe={probe} />
          {/each}
        </div>
      </section>
    {:else if busy && !selectedDataset}<div class="empty">Loading dataset catalog…</div>
    {:else if !selectedDataset}<div class="empty">No compatible Principled v2 dataset found.</div>
    {:else if !selectedFrameId}<div class="empty">This dataset has no selectable frame.</div>{/if}
    {/if}
  </section>

  {#if metadataOpen && frameDetail}
    <aside class="metadata-drawer">
      <header><strong>Frame metadata</strong><button onclick={() => metadataOpen = false}>×</button></header>
      <h3>Camera</h3><pre>{JSON.stringify(frameDetail.frame.camera, null, 2)}</pre>
      <h3>Intrinsics</h3><pre>{JSON.stringify(frameDetail.frame.intrinsics, null, 2)}</pre>
      <h3>Timing / QC</h3><pre>{JSON.stringify({ timings_s: frameDetail.frame.timings_s, nir_qc: frameDetail.frame.nir_qc, nir_passive_qc: frameDetail.frame.nir_passive_qc, nir_difference_qc: frameDetail.frame.nir_difference_qc, diffuse_decomposition_qc: frameDetail.frame.diffuse_decomposition_qc }, null, 2)}</pre>
      <h3>Viewer transfer</h3><pre>{JSON.stringify(viewerMetrics, null, 2)}</pre>
      <h3>Scene-scale IR readiness</h3><pre>{JSON.stringify(datasetDetail?.readiness ?? frameDetail.dataset.readiness_label, null, 2)}</pre>
      {#if structuralOverride}<h3>Structural PBR override</h3><pre>{JSON.stringify(structuralOverride, null, 2)}</pre>{/if}
      <h3>Artifact contract</h3><pre>{JSON.stringify(datasetDetail?.contract, null, 2)}</pre>
    </aside>
  {/if}
</main>
{/if}
