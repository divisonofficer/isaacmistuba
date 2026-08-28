<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    controllerJobAction, getControllerLog, getControllerStatus, getRecoveryPlan, listInfinigenOutputs, submitControllerJob,
    type ControllerJob, type ControllerRequest, type ControllerStatus, type GPU, type RecoveryPlan
  } from './api';

  let { onBrowse }: { onBrowse: () => void } = $props();
  let tab = $state<'create' | 'jobs'>('create');
  let status = $state<ControllerStatus>({ jobs: [], queue: [], gpu_inventory: [] });
  let outputs = $state<{ relative_path: string; scene_blend: string }[]>([]);
  let error = $state(''); let loading = $state(false); let selectedJob = $state<ControllerJob | null>(null); let log = $state<string[]>([]);
  let sourceMode = $state<'generate' | 'existing' | 'augmentation'>('generate'); let datasetNameOverride = $state(''); let legacyDatasetName = $state('');
  let sceneIdOverride = $state(''); let archetype = $state('single_room'); let roomType = $state('kitchen');
  let density = $state('family_home'); let generationStage = $state('full'); let seed = $state('today'); let existingOutput = $state('');
  let variationId = $state(0); let anchorRichness = $state<'minimal' | 'balanced' | 'rich' | 'storage'>('rich');
  let surfaceClutter = $state<'low' | 'balanced' | 'rich' | 'storage'>('rich');
  let cameraPolicy = $state<'content_aware_v2' | 'coverage_v1'>('content_aware_v2');
  let contentProfile = $state<'balanced' | 'anchor_rich' | 'structural' | 'research_balanced'>('research_balanced'); let adaptivePoseBudget = $state(true);
  let irMaterialProfile = $state<'standard' | 'principled_rich_v1'>('principled_rich_v1');
  let width = $state(684); let height = $state(512); let fov = $state(60); let rgbSpp = $state(4000); let nirSpp = $state(2000);
  let nirPassive = $state(true);
  // 160 leaves content-aware sampling room to satisfy the strict 100-pose
  // floor without restoring the former graph-wide 1,000+ frame renders.
  let flashScale = $state(1); let fillScale = $state(1); let poseBudget = $state(160); let gpuIndices = $state<number[]>([]);
  let structuralRematerialize = $state(false);
  let hybridPropPbr = $state(true); let propPbrTarget = $state(0.70);
  let structuralLibrary = $state<'cc0_structural_v1' | 'texturecan_structural_v1' | 'texturecan_structural_extended_v1'>('cc0_structural_v1');
  let materialVariantId = $state('structural_cc0_v1'); let materialSeed = $state(0);
  const structuralLibraries = {
    cc0_structural_v1: {
      registry: '/bean/ir_pbr_assets/cc0_structural_v1/registry.lock.json', root: '/bean/ir_pbr_assets/cc0_structural_v1',
      label: 'Existing CC0 structural v1', detail: 'Legacy curated dielectric structural set.',
    },
    texturecan_structural_v1: {
      registry: '/bean/ir_pbr_assets/texturecan_structural_v1/registry.lock.json', root: '/bean/ir_pbr_assets/texturecan_structural_v1',
      label: 'TextureCan structural v1', detail: 'Human-approved explicit roles; selected metal wall/panel maps retain metallic GT.',
    },
    texturecan_structural_extended_v1: {
      registry: '/bean/ir_pbr_assets/texturecan_structural_extended_v1/registry.lock.json', root: '/bean/ir_pbr_assets/texturecan_structural_extended_v1',
      label: 'TextureCan structural extended v1', detail: 'Independent 100-material, role-curated 2K structural set; meter-repeat scales and effective GT sockets are locked.',
    },
  } as const;
  const structuralLibraryConfig = $derived(structuralLibraries[structuralLibrary]);
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let refreshInFlight = false; let disposed = false; let requestAbort: AbortController | null = null;
  let lastLogRefreshMs = 0;
  let illuminationDiversity = $state(true); let pairedFraction = $state(0.20);
  let graphMaxNodes = $state(70); let graphHeadingCount = $state(24); let graphMinNodeSpacing = $state(0.25); let graphRobotRadius = $state(0.30);
  let recovery = $state<RecoveryPlan | null>(null); let recoveryJob = $state<ControllerJob | null>(null);
  let showHiddenJobs = $state(false);
  const roomTypes = [
    'living-room', 'bedroom', 'kitchen', 'bathroom', 'dining-room', 'closet',
    'hallway', 'garage', 'balcony', 'utility', 'staircase-room', 'warehouse',
    'office', 'meeting-room', 'open-office', 'break-room', 'restroom', 'factory-office'
  ];
  type TqdmProgress = { label: string; percent: number; completed: number; total: number; elapsed: string; eta: string; rate: string; detail: string };
  type PipelineStep = { id: string; label: string; status: 'complete' | 'active' | 'pending'; progress: number | null; milestone: number };
  type StageProgress = NonNullable<ControllerJob['stage_progress']>[string];
  const infinigenPhaseWeights: ReadonlyArray<readonly [string, number]> = [
    ['sky_lighting', 0.2], ['solve_rooms', 0.8], ['solve_large', 22.0], ['populate_intermediate_pholders', 0.5],
    ['solve_medium', 28.0], ['solve_small', 10.0], ['populate_assets', 16.0], ['floating_objs', 16.0],
    ['room_doors', 0.5], ['room_windows', 0.3], ['room_stairs', 0.1], ['room_walls', 0.2], ['room_floors', 0.3],
    ['room_ceilings', 0.1], ['invisible_room_ceilings', 0.2], ['overhead_cam', 0.2], ['hide_other_rooms', 0.1], ['Writing output blendfile', 4.5],
  ];
  const tqdmProgress = $derived(
    selectedJob?.resource_state === 'running' || (selectedJob?.external_import_pids?.length ?? 0) > 0
      ? parseTqdm(log, selectedJob?.stage ?? '')
      : null
  );
  const pipelineSteps = $derived(selectedJob ? buildPipelineSteps(selectedJob, tqdmProgress) : []);
  const globalProgress = $derived(pipelineSteps.length ? pipelineSteps.reduce((sum, step) => sum + step.milestone, 0) / pipelineSteps.length : 0);
  const sceneSeedPreview = $derived(seed === 'today' || !seed.trim() ? kstDateSeed() : seed === 'random' ? 'random' : seed.trim());
  const existingSceneStem = $derived(existingOutput
    ? existingOutput.split('/').filter(Boolean).at(-2)?.replace(/^kr_/, '') ?? 'existing_scene'
    : 'existing_scene');
  const suggestedSceneId = $derived(sourceMode === 'generate'
    ? `infinigen_${archetype}${archetype === 'single_room' ? `_${roomType.replaceAll('-', '_')}` : ''}_${sceneSeedPreview}_v${variationId.toString().padStart(2, '0')}`
    : `infinigen_${existingSceneStem}`);
  const effectiveSceneId = $derived(sceneIdOverride.trim() || suggestedSceneId);
  const suggestedDatasetName = $derived(`${effectiveSceneId}_rgb_active_passive_nir_v2`);
  const effectiveDatasetName = $derived(datasetNameOverride.trim() || suggestedDatasetName);
  const variationPoseEstimate = $derived(Math.round(poseBudget / 5));
  const illuminationFrameEstimate = $derived(illuminationDiversity ? poseBudget * 2 : poseBudget);

  onMount(() => { void poll(); });
  onDestroy(() => {
    disposed = true;
    if (pollTimer) clearTimeout(pollTimer);
    requestAbort?.abort();
  });
  async function poll() {
    await refresh();
    // Schedule the next poll only after this one has settled. This prevents a
    // slow filesystem scan or a busy controller from creating a request pileup.
    if (!disposed) pollTimer = setTimeout(() => void poll(), 4000);
  }
  async function refresh() {
    if (refreshInFlight) return;
    refreshInFlight = true;
    const controller = new AbortController();
    requestAbort = controller;
    try {
      const next = await getControllerStatus(controller.signal, showHiddenJobs);
      if (disposed || controller.signal.aborted) return;
      status = next;
      if (!gpuIndices.length) gpuIndices = next.gpu_pool?.length
        ? [...next.gpu_pool]
        : next.gpu_inventory.filter((gpu) => gpu.eligible).map((gpu) => gpu.index);
      // This filesystem glob is only useful for the Existing-output chooser.
      // Do not repeatedly scan it while creating a new Infinigen scene.
      if (tab === 'create' && sourceMode === 'existing' && !outputs.length) {
        outputs = (await listInfinigenOutputs(controller.signal)).outputs;
      }
      // Logs are sizeable JSONL tails; keep the live Jobs view responsive
      // without making every controller status poll fetch them again.
      if (selectedJob && tab === 'jobs' && Date.now() - lastLogRefreshMs >= 8000) {
        selectedJob = next.jobs.find((job) => job.job_id === selectedJob?.job_id) ?? selectedJob;
        log = (await getControllerLog(selectedJob.job_id, controller.signal)).lines;
        lastLogRefreshMs = Date.now();
      }
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) error = String(cause);
    } finally {
      if (requestAbort === controller) requestAbort = null;
      refreshInFlight = false;
    }
  }
  function toggleGpu(index: number) { gpuIndices = gpuIndices.includes(index) ? gpuIndices.filter((item) => item !== index) : [...gpuIndices, index].sort((a,b) => a-b); }
  function kstDateSeed(): string {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? '';
    return `${part('year')}${part('month')}${part('day')}`;
  }
  function randomDateSeed(): string {
    const value = crypto.getRandomValues(new Uint32Array(1))[0] % 100_000_000;
    return value.toString().padStart(8, '0');
  }
  function generatedSceneId(concreteSeed: string): string {
    return `infinigen_${archetype}${archetype === 'single_room' ? `_${roomType.replaceAll('-', '_')}` : ''}_${concreteSeed}_v${variationId.toString().padStart(2, '0')}`;
  }
  function resetIdentityFieldsAfterSubmit(submittedMode: 'generate' | 'existing' | 'augmentation') {
    // These values are overrides, not durable render preferences. Leaving them
    // populated disables the derived naming rule for the next queued job.
    datasetNameOverride = '';
    sceneIdOverride = '';
    existingOutput = '';
    seed = 'today';
    if (submittedMode === 'generate') variationId += 1;
  }
  async function submit() {
    loading = true; error = '';
    try {
      const request: ControllerRequest = { source_mode: sourceMode, dataset_name: effectiveDatasetName, gpu_indices: gpuIndices,
        room_type: roomType,
        width, height, fov, rgb_spp: rgbSpp, nir_spp: nirSpp, nir_passive: nirPassive, flash_energy_scale: flashScale, ambient_fill_energy_scale: fillScale, pose_budget: poseBudget,
        illumination_diversity: illuminationDiversity, paired_fraction: pairedFraction, min_unique_pose_count: 100,
        illumination_pairing_policy: 'reference_subset_v2',
        graph_max_nodes: graphMaxNodes, graph_heading_count: graphHeadingCount, graph_min_node_spacing: graphMinNodeSpacing, graph_robot_radius: graphRobotRadius,
        camera_policy: cameraPolicy, content_profile: contentProfile, ir_material_profile: irMaterialProfile,
        material_mix_profile: 'physically_constrained_metal_v1', max_quality_variations: 4, adaptive_pose_budget: adaptivePoseBudget,
        sparse_negative_fraction: 0.15, max_headings_per_node: 6,
        structural_rematerialize: structuralRematerialize, hybrid_prop_pbr: hybridPropPbr, prop_pbr_target: propPbrTarget };
      if (structuralRematerialize) Object.assign(request, {
        structural_pbr_registry: structuralLibraryConfig.registry, structural_pbr_registry_root: structuralLibraryConfig.root,
        material_variant_id: materialVariantId, material_seed: materialSeed,
        parent_scene_id: sourceMode === 'generate' ? '' : effectiveSceneId,
      });
      if (sourceMode === 'generate') {
        // Resolve deferred seeds once at submission so the generated output
        // directory and OpticalNav ID cannot diverge, even across a controller
        // restart between generation and import.
        const concreteSeed = seed === 'random' ? randomDateSeed() : (seed === 'today' || !seed.trim() ? kstDateSeed() : seed.trim());
        request.scene_id = sceneIdOverride.trim() || generatedSceneId(concreteSeed);
        Object.assign(request, { archetype, room_type: roomType, density, generation_stage: generationStage, seed: concreteSeed,
          variation_id: variationId, anchor_richness: anchorRichness, surface_clutter: surfaceClutter });
      } else if (sourceMode === 'existing') {
        request.scene_id = effectiveSceneId;
        request.existing_output = existingOutput;
      } else {
        request.legacy_dataset_name = legacyDatasetName;
      }
      const submittedMode = sourceMode;
      selectedJob = await submitControllerJob(request);
      resetIdentityFieldsAfterSubmit(submittedMode);
      tab = 'jobs'; await refresh();
    } catch (cause) { error = cause instanceof Error ? cause.message : String(cause); }
    finally { loading = false; }
  }
  async function action(job: ControllerJob, kind: 'cancel' | 'replan' | 'retry' | 'retry-showcase' | 'resume' | 'adopt' | 'priority' | 'hide' | 'unhide') {
    if (kind === 'resume') { await openRecovery(job); return; }
    try { await controllerJobAction(job.job_id, kind, kind === 'priority' ? { priority: job.priority + 1 } : {}); await refresh(); }
    catch (cause) { error = String(cause); }
  }
  async function toggleHiddenJobs() {
    showHiddenJobs = !showHiddenJobs;
    await refresh();
  }
  async function openRecovery(job: ControllerJob) {
    try { recoveryJob = job; recovery = await getRecoveryPlan(job.job_id); }
    catch (cause) { error = String(cause); }
  }
  async function resumeRecovery(custom = false) {
    if (!recovery || !recoveryJob) return;
    try {
      const insert = custom ? recovery.stages.filter((item) => item.selected && item.state === 'Missing').map((item) => item.stage) : [];
      await controllerJobAction(recoveryJob.job_id, 'resume', { mode: custom ? 'custom' : 'recommended', insert_stages: insert,
        rerun_from: custom ? recovery.recommended_rerun_from : null });
      recovery = null; recoveryJob = null; await refresh();
    } catch (cause) { error = String(cause); }
  }
  async function selectJob(job: ControllerJob) {
    selectedJob = job; tab = 'jobs';
    try { log = (await getControllerLog(job.job_id)).lines; lastLogRefreshMs = Date.now(); } catch (cause) { error = String(cause); }
  }
  function formatKst(value: string | null | undefined): string {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const parts = new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).formatToParts(date);
    const get = (name: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === name)?.value ?? '';
    return `${get('year')}년 ${get('month')} ${get('day')} ${get('hour')}:${get('minute')}:${get('second')} KST`;
  }
  function waitingForResource(job: ControllerJob): boolean {
    return ['waiting_resource', 'waiting_cpu', 'waiting_gpu'].includes(job.resource_state ?? '');
  }
  function resourceLabel(job: ControllerJob): string {
    const usage = status.resource_config?.usage?.[job.resource_class ?? ''];
    const slots = usage ? ` · slots ${usage.used}/${usage.limit}` : '';
    if (job.resource_state === 'waiting_gpu') return `GPU queue #${job.queue_position ?? '—'} · requested ${job.request.gpu_indices?.join(', ')}${slots}`;
    if (job.resource_class === 'blender_bootstrap') return `bootstrap import slot${slots}`;
    if (job.resource_class === 'blender_bake') return `final bake GPU${slots}`;
    if (job.resource_class === 'blender_prepare') return `Blender prepare slot${slots}`;
    if (job.resource_class === 'infinigen_generate') return 'Infinigen slot';
    if (job.resource_class === 'cpu_light') return 'CPU slot';
    if (job.resource_class === 'gpu_render') return 'GPU slot';
    return 'resource slot';
  }
  function displayStatus(job: ControllerJob): { label: string; className: string; detail: string } {
    if ((job.external_import_pids?.length ?? 0) > 0) {
      return { label: 'external import', className: 'external', detail: `import · external PID ${job.external_import_pids?.join(', ')}` };
    }
    if (['queued', 'running'].includes(job.status) && waitingForResource(job)) {
      return { label: 'waiting', className: 'waiting', detail: `queued · waiting for ${resourceLabel(job)}` };
    }
    if (job.status === 'running') {
      const assigned = job.resource_gpu_indices?.length ? ` · assigned ${job.resource_gpu_indices.join(',')}` : '';
      const desired = job.desired_gpu_indices?.length ? ` · desired ${job.desired_gpu_indices.join(',')}` : '';
      const draining = job.draining_gpu_indices?.length ? ` · draining ${job.draining_gpu_indices.join(',')}` : '';
      return { label: 'running', className: 'running', detail: `${job.stage}${assigned}${desired}${draining}` };
    }
    return { label: job.status, className: job.status, detail: `${job.stage} · GPU ${job.request.gpu_indices?.join(', ')}` };
  }
  function parseTqdm(lines: string[], activeStage: string): TqdmProgress | null {
    let latest: TqdmProgress | null = null;
    for (const serialized of lines) {
      try {
        const event = JSON.parse(serialized);
        if (event.event !== 'output' || typeof event.line !== 'string') continue;
        if (event.stage !== activeStage) continue;
        // tqdm: "export: 55%|█████▌ | 22/40 [03:14<03:06, 10.34s/obj, FloorLamp…]"
        const match = event.line.match(/^\s*([^:]+):\s*(\d+(?:\.\d+)?)%\|.*?\|\s*(\d+)\/(\d+)\s+\[([^<\]]+)<([^,\]]+),\s*([^,\]]+)(?:,\s*(.*))?\]\s*$/);
        if (!match) continue;
        latest = {
          label: match[1].trim(), percent: Number(match[2]), completed: Number(match[3]), total: Number(match[4]),
          elapsed: match[5].trim(), eta: match[6].trim(), rate: match[7].trim(), detail: (match[8] ?? '').trim(),
        };
      } catch { /* event log can contain a legacy non-JSON line */ }
    }
    return latest;
  }
  function solverPhasePercent(measured: StageProgress | undefined): number | null {
    if (measured?.phase_percent != null) return measured.phase_percent;
    if (measured?.local_total && measured.local_total > 0 && measured.local_completed != null) {
      return Math.min(100, Math.max(0, 100 * measured.local_completed / measured.local_total));
    }
    return null;
  }
  function generationMilestone(measured: StageProgress | undefined): number | null {
    if (!measured) return null;
    const phaseIndex = infinigenPhaseWeights.findIndex(([phase]) => phase === measured.phase);
    if (phaseIndex < 0) return measured.percent ?? null;
    return infinigenPhaseWeights.slice(0, phaseIndex).reduce((sum, [, weight]) => sum + weight, 0);
  }
  function buildPipelineSteps(job: ControllerJob, local: TqdmProgress | null): PipelineStep[] {
    const all = [
      ['generate', 'Infinigen 생성'], ['showcase_composition', 'IR showcase composition · derived blend'], ['import', 'Bootstrap import · no texture bake'], ['scene_content_audit', 'Scene content audit'],
      ['navigation_compile', 'Navigation graph compile'], ['material_extract', 'Source material analysis · extract'], ['material_canonicalize', 'Source material analysis · canonicalize'], ['showcase_raster_probe', '160×120 showcase raster probe'], ['showcase_acceptance', 'Anchor multi-view acceptance'], ['view_probe', 'Candidate visibility probe'], ['lighting_asset_audit', 'HDRI bank audit'], ['view_plan', 'Anchor-centric IR render plan'], ['scene_quality_gate', 'Content density gate'], ['geometry', 'IR LOD + final PBR bake'], ['structural_rematerialize', 'Interior structural CC0 PBR override'], ['structural_quality_audit', 'Structural physical-material quality gate'], ['overview_proxy', 'Scene overview proxy'],
      ['principled_prepare', 'Principled Stage 2'], ['material_mix_audit', 'Specular material-mix audit'], ['qc_render', 'Stage 0 render'],
      ['qc_verify', 'Stage 0 QC'], ['full_render', 'Full rolling render'],
      ['full_verify', 'Full QC'], ['dataset_utility_audit', 'Dataset utility audit'], ['publish', 'Immutable publish'],
    ] as const;
    const revisionRelevant = job.request.pipeline_revision === 'ir-content-aware-v2' ? all : all.filter(([id]) => !['scene_content_audit', 'view_probe', 'scene_quality_gate', 'material_mix_audit', 'dataset_utility_audit'].includes(id));
    const showcaseRelevant = job.request.ir_composition_profile === 'inverse_rendering_showcase_v1' ? revisionRelevant : revisionRelevant.filter(([id]) => !['showcase_composition', 'showcase_raster_probe', 'showcase_acceptance'].includes(id));
    const lightingRelevant = job.request.illumination_diversity ? showcaseRelevant : showcaseRelevant.filter(([id]) => id !== 'lighting_asset_audit');
    const materialRelevant = job.request.structural_rematerialize ? lightingRelevant : lightingRelevant.filter(([id]) => id !== 'structural_rematerialize');
    const qualityRelevant = job.request.content_profile === 'research_balanced' && job.request.source_mode === 'generate' ? materialRelevant : materialRelevant.filter(([id]) => !['scene_quality_gate', 'material_mix_audit'].includes(id));
    const relevant = job.request.source_mode === 'augmentation'
      ? qualityRelevant.filter(([id]) => ['lighting_asset_audit','view_plan','overview_proxy','principled_prepare','qc_render','qc_verify','full_render','full_verify','publish'].includes(id))
      : (job.request.source_mode === 'existing' ? qualityRelevant.filter(([id]) => id !== 'generate') : qualityRelevant);
    return relevant.map(([id, label]) => {
      const result = job.stage_results?.[id];
      const measured = job.stage_progress?.[id];
      const phasePercent = id === 'generate' ? solverPhasePercent(measured) : null;
      const milestonePercent = id === 'generate' ? generationMilestone(measured) : measured?.percent;
      const progressPercent = id === 'generate' && phasePercent != null ? phasePercent : milestonePercent;
      const displayLabel = id === 'view_plan' && result?.actual_pose_count != null
        ? `${label} · ${result.actual_pose_count}/${result.requested_pose_count} poses · ${result.lighting_group_count} lights${result?.showcase ? ` · ${result.showcase.camera_set_count} anchor sets` : ''}`
        : (id === 'generate' && measured?.phase ? `${label} · ${measured.phase}${phasePercent != null ? ` · current solver ${phasePercent.toFixed(0)}%` : ''} · completed phases ${milestonePercent?.toFixed(0) ?? '…'}%`
          : (measured?.lighting_groups ? `${label} · ${Object.keys(measured.lighting_groups).length} lighting groups` : label));
      if (result?.status === 'succeeded' || (job.status === 'succeeded' && id === 'publish')) return { id, label: displayLabel, status: 'complete', progress: 100, milestone: 100 };
      if ((job.stage === id && job.status === 'running') || (id === 'import' && (job.external_import_pids?.length ?? 0) > 0)) return { id, label: displayLabel, status: 'active', progress: progressPercent ?? local?.percent ?? null, milestone: milestonePercent ?? 0 };
      return { id, label: displayLabel, status: 'pending', progress: 0, milestone: 0 };
    });
  }
</script>

<section class="control-center">
  <header class="control-header"><div><h2>IR Dataset Control Center</h2><p>독립 pipeline queue · bake/render는 할당 GPU 단위로 조정됩니다.</p></div><button onclick={refresh}>Refresh</button></header>
  {#if error}<div class="control-error">{error}<button onclick={() => error = ''}>×</button></div>{/if}
  <nav class="control-tabs"><button class:active={tab === 'create'} onclick={() => tab = 'create'}>Create job</button><button class:active={tab === 'jobs'} onclick={() => tab = 'jobs'}>Jobs ({status.jobs.length})</button><button onclick={onBrowse}>Browse datasets</button>{#if status.hidden_job_count}<button class="secondary" onclick={toggleHiddenJobs}>{showHiddenJobs ? 'Hide archived' : `Show archived (${status.hidden_job_count})`}</button>{/if}</nav>

  {#if tab === 'create'}
    <div class="wizard-grid">
      <section class="wizard-card"><h3>1. Scene source</h3>
        <div class="choice"><button class:active={sourceMode === 'generate'} onclick={() => sourceMode = 'generate'}>New Infinigen</button><button class:active={sourceMode === 'existing'} onclick={() => { sourceMode = 'existing'; void refresh(); }}>Existing output</button><button class:active={sourceMode === 'augmentation'} onclick={() => sourceMode = 'augmentation'}>Augment legacy dataset</button></div>
        {#if sourceMode === 'generate'}
          <label>Archetype<select bind:value={archetype}><option value="single_room">Single room</option><option value="apartment">Apartment</option></select><small>Modern Office OpticalNav 생성은 <code>scripts/infinigen_wizard.py --archetype office</code>에서만 지원합니다.</small></label>
          {#if archetype === 'single_room'}<label>Room type<select bind:value={roomType}>{#each roomTypes as item}<option value={item}>{item}</option>{/each}</select></label>{/if}
          <label>Furnishing density<select bind:value={density}><option>model_house</option><option>normal_lived_in</option><option>family_home</option><option>storage_heavy</option></select></label>
          <div class="field-row"><label>Anchor richness<select bind:value={anchorRichness}><option>minimal</option><option>balanced</option><option>rich</option><option>storage</option></select></label><label>Surface clutter<select bind:value={surfaceClutter}><option>low</option><option>balanced</option><option>rich</option><option>storage</option></select></label></div>
          <label>Variation ID<input type="number" min="0" bind:value={variationId} /><small>같은 logical seed에서도 방 타입·variation에 따라 effective seed가 달라집니다.</small></label>
          <label>Generation stage<select bind:value={generationStage}><option value="full">full</option><option value="layout">layout</option></select></label>
          <label>Seed<input bind:value={seed} placeholder="today / random / 8 digits" /></label>
        {:else if sourceMode === 'existing'}
          <label>Generated output<select bind:value={existingOutput}><option value="">Select scene.blend output</option>{#each outputs as item}<option value={item.relative_path}>{item.relative_path}</option>{/each}</select></label>
          <label>Scene room type<select bind:value={roomType}>{#each roomTypes as item}<option value={item}>{item}</option>{/each}</select><small>기존 scene에도 room-content gate를 적용하기 위한 의미 유형입니다.</small></label>
        {:else}
          <label>Legacy dataset name<input bind:value={legacyDatasetName} placeholder="kitchen_rgb_active_nir_realistic_v1" /><small>bean/work/out IR roots에서 읽기 전용 Stage 1 geometry와 source graph를 찾습니다. 새 dataset 이름으로 paired illumination Stage 2/3만 생성합니다.</small></label>
        {/if}
        <label>OpticalNav scene ID<input value={effectiveSceneId} oninput={(event) => sceneIdOverride = event.currentTarget.value === suggestedSceneId ? '' : event.currentTarget.value} /><small>{sceneIdOverride ? '사용자 지정 ID' : `자동 할당 · ${suggestedSceneId}${seed === 'random' ? ' (제출 시 random이 실제 8자리 seed로 확정됨)' : ''}`}</small></label>
      </section>
      <section class="wizard-card"><h3>2. Dataset render</h3>
        <label>Dataset name<input value={effectiveDatasetName} oninput={(event) => datasetNameOverride = event.currentTarget.value === suggestedDatasetName ? '' : event.currentTarget.value} /><small>{datasetNameOverride ? '사용자 지정 이름' : `scene ID에서 자동 할당 · ${suggestedDatasetName}`}</small></label>
        <div class="field-row"><label>Width<input type="number" bind:value={width} /></label><label>Height<input type="number" bind:value={height} /></label></div>
        <div class="field-row"><label>Horizontal FOV<input type="number" step="0.1" bind:value={fov} /></label><label>RGB SPP<input type="number" bind:value={rgbSpp} /></label><label>NIR SPP<input type="number" bind:value={nirSpp} /></label></div>
        <div class="field-row"><label>Flash scale<input type="number" step="0.1" bind:value={flashScale} /></label><label>Fill scale<input type="number" step="0.1" bind:value={fillScale} /></label></div>
        <label><input type="checkbox" bind:checked={nirPassive} /> Passive NIR + active−passive difference <small>flash-off NIR is rendered with the same scene/light state; both linear EXR sidecars are retained.</small></label>
        <h4>Illumination diversity</h4>
        <label><input type="checkbox" bind:checked={illuminationDiversity} /> Reference-subset 6-condition v2</label>
        {#if illuminationDiversity}<div class="field-note">Reference-subset lighting pairs<small>Reference neutral은 base pose {poseBudget}개를 모두 렌더합니다. 나머지 5개 조명은 base pose를 겹치지 않게 약 {variationPoseEstimate}개씩 나눠 렌더하므로, 모든 variation frame에 정확히 대응하는 reference frame이 있습니다. 예상 총 {illuminationFrameEstimate} frames.</small></div>{/if}
        <label>Camera policy<select bind:value={cameraPolicy}><option value="content_aware_v2">Content-aware v2</option><option value="coverage_v1">Coverage v1</option></select></label>
          <label>Content profile<select bind:value={contentProfile}><option value="research_balanced">Research balanced</option><option value="balanced">balanced</option><option value="anchor_rich">anchor rich</option><option value="structural">structural</option></select><small>family_home + rich anchors/clutter를 최소로 적용합니다. 밀도·pose·metal GT gate 미달 시 최대 4 variation을 자동 재생성합니다.</small></label>
          <label>IR material profile<select bind:value={irMaterialProfile}><option value="principled_rich_v1">Principled rich v1</option><option value="standard">Standard Infinigen</option></select><small>principled_rich_v1은 새 Infinigen 생성에서만 metal-capable pool에 conductor/near-binary coverage material을 추가합니다. 기본 Infinigen 분포는 변경하지 않습니다.</small></label>
          {#if contentProfile === 'research_balanced'}<div class="material-contract"><b>MetallicContractV2 · physically constrained</b><small>dielectric=0 · conductor=1 · coverage-mixed는 shared near-binary mask · Non-Color linear metallic · high-metal coverage 3–12% · 서로 다른 visible metal material ≥2 · 단일 material 독점 ≤50%</small></div>{/if}
        {#if sourceMode !== 'augmentation'}
          <section class:enabled={structuralRematerialize} class="structural-override-card">
            <label class="check"><input type="checkbox" bind:checked={structuralRematerialize} /> Structural PBR override (optional)</label>
            <small>원본 Infinigen 및 Stage 1은 읽기 전용입니다. 실내 wall/floor/ceiling/column/panel slot만 교체하며 furniture·appliance·prop·door/window/glass는 제외합니다.</small>
            {#if structuralRematerialize}
              <div class="field-row"><label>Library<select bind:value={structuralLibrary} onchange={() => { materialVariantId = structuralLibrary; }}><option value="cc0_structural_v1">{structuralLibraries.cc0_structural_v1.label}</option><option value="texturecan_structural_v1">{structuralLibraries.texturecan_structural_v1.label}</option><option value="texturecan_structural_extended_v1">{structuralLibraries.texturecan_structural_extended_v1.label}</option></select></label><label>Variant ID<input bind:value={materialVariantId} /></label><label>Material seed<input type="number" bind:value={materialSeed} /></label></div>
              <code>{structuralLibraryConfig.registry}</code><small>{structuralLibraryConfig.detail} TextureCan registry는 review+scale finalization 전에는 선택해도 job preflight에서 시작되지 않습니다.</small><small>Stage 0에서 structural coverage, normal/roughness variation 및 metallic GT alignment를 함께 검증합니다.</small>
            {/if}
          </section>
        {/if}
        <section class:enabled={hybridPropPbr} class="structural-override-card">
          <label class="check"><input type="checkbox" bind:checked={hybridPropPbr} /> Small-prop PBR coverage (hybrid v1)</label>
          <small>Opaque source slots retain strict source provenance. Unresolved eligible props receive a deterministic curated opaque profile and are marked remediated, never source-valid.</small>
          {#if hybridPropPbr}<label>Stage 0 train-valid small-prop target <b>{Math.round(propPbrTarget * 100)}%</b><input type="range" min="0.5" max="0.9" step="0.05" bind:value={propPbrTarget} /></label>{/if}
        </section>
        <label><input type="checkbox" bind:checked={adaptivePoseBudget} /> Adaptive pose budget</label>
        <label>Maximum camera poses <b>{poseBudget}</b><input type="range" min="160" max="400" step="20" bind:value={poseBudget} /><small>독립 pose는 최소 100개가 hard gate입니다. 후보가 부족한 scene은 렌더하지 않고 실패 처리하며, lighting-expanded frame 수로 대체하지 않습니다.</small></label>
        <h4>IR camera graph</h4><div class="field-row"><label>Max nodes<input type="number" min="1" max="2000" bind:value={graphMaxNodes} /></label><label>Headings / node<input type="number" min="1" max="72" bind:value={graphHeadingCount} /></label></div>
        <div class="field-row"><label>Node spacing (m)<input type="number" min="0.05" max="5" step="0.05" bind:value={graphMinNodeSpacing} /></label><label>Robot radius (m)<input type="number" min="0.05" max="2" step="0.05" bind:value={graphRobotRadius} /></label></div><small>Kitchen-validated default · 약 70 nodes × 24 headings에서 pose budget만큼 coverage sampling</small>
        <h4>Eligible GPU pool</h4><div class="gpu-list">{#each status.gpu_inventory as gpu}<button class:active={gpuIndices.includes(gpu.index)} disabled={!gpu.eligible} onclick={() => toggleGpu(gpu.index)}><b>GPU {gpu.index}</b> {gpu.name}<small>{gpu.memory_used_mib}/{gpu.memory_total_mib} MiB · {gpu.utilization_pct}% {gpu.owners?.length ? `· ${gpu.owners.map((owner) => `${owner.stage}:${owner.lease_state}`).join(', ')}` : gpu.eligible ? '· idle' : '· outside IR pool'}</small></button>{/each}</div>
      </section>
        <aside class="wizard-card summary"><h3>3. Pipeline</h3><ol><li>Generate / import · {irMaterialProfile}</li><li>Bootstrap import · no texture bake</li><li>Room content contract audit</li><li>Navigation graph + candidate visibility probe</li><li>Content-aware render plan</li><li>Source material analysis + MetallicContractV2 audit</li><li>IR LOD + final PBR bake</li>{#if structuralRematerialize}<li>Interior-structure-only {structuralLibrary.startsWith('texturecan_') ? 'TextureCan' : 'CC0'} PBR override</li>{/if}{#if hybridPropPbr}<li>Hybrid small-prop PBR remediation</li>{/if}<li>Principled Stage 2 v4</li>{#if nirPassive}<li>RGB + active NIR + passive NIR + active−passive</li>{/if}<li>QC, rolling render, utility gate, immutable publish</li></ol>{#if structuralRematerialize}<div class="override-summary"><b>Structural variant</b><span>{materialVariantId} · seed {materialSeed}</span><small>{structuralLibrary.startsWith('texturecan_') ? 'approved dielectric and metal mappings drive both Principled inputs and GT AOVs.' : 'legacy override is dielectric-only; native full-layout objects supply metallic cues.'}</small></div>{/if}<code>/bean/ir_dataset_work/{effectiveDatasetName}</code><code>/bean/ir_dataset/{effectiveDatasetName}</code><button class="primary" disabled={loading || !effectiveDatasetName || !gpuIndices.length || (sourceMode === 'existing' && !existingOutput) || (sourceMode === 'augmentation' && !legacyDatasetName)} onclick={submit}>{loading ? 'Submitting…' : 'Queue pipeline job'}</button></aside>
    </div>
  {:else}
        <div class="jobs-layout"><section class="job-list">{#if !status.jobs.length}<p>{showHiddenJobs ? 'No archived jobs.' : 'No active or recoverable jobs. Failed quality-gate attempts are archived.'}</p>{/if}{#each status.jobs as job}<article class:hidden-job={job.hidden_from_ui} class:active={selectedJob?.job_id === job.job_id}><button class="job-select" onclick={() => selectJob(job)}><header><b>{job.request.scene_id ?? job.request.dataset_name}</b><span class={`status ${displayStatus(job).className}`}>{job.hidden_from_ui ? 'archived' : displayStatus(job).label}</span></header><p>{job.request.dataset_name} · {displayStatus(job).detail}</p><small>{job.hidden_reason ?? job.error ?? `최근 갱신 · ${formatKst(job.updated_at)}`}</small></button><footer>{#if job.status === 'queued'}<button onclick={() => action(job, 'priority')}>Priority +</button>{/if}{#if (job.stage === 'full_render' || (job.status === 'interrupted' && job.request.camera_policy === 'coverage_v1' && job.request.illumination_diversity)) && ['running','failed','cancelled','interrupted'].includes(job.status)}<button onclick={() => action(job, 'replan')}>Apply corrected plan &amp; resume</button>{/if}{#if ['failed','cancelled','interrupted'].includes(job.status) && job.request.content_profile === 'research_balanced' && job.request.source_mode === 'generate' && job.request.archetype === 'single_room' && job.request.ir_composition_profile !== 'inverse_rendering_showcase_v1'}<button onclick={() => action(job, 'retry-showcase')}>Retry with showcase profile</button>{/if}{#if job.status === 'queued' || job.status === 'running'}<button onclick={() => action(job, 'cancel')}>Cancel</button>{/if}{#if ['failed','cancelled','interrupted'].includes(job.status) && (job.external_import_pids?.length ?? 0) > 0}<button onclick={() => action(job, 'adopt')}>Attach running import</button>{:else if ['failed','cancelled','interrupted'].includes(job.status)}<button onclick={() => action(job, 'resume')}>Resume safely</button>{/if}{#if job.status === 'failed' || job.status === 'cancelled'}<button onclick={() => action(job, job.hidden_from_ui ? 'unhide' : 'hide')}>{job.hidden_from_ui ? 'Restore to list' : 'Archive card'}</button>{/if}</footer></article>{/each}</section>
    <section class="job-detail">{#if selectedJob}<h3>{selectedJob.request.scene_id ?? selectedJob.request.dataset_name}</h3><p><b>{displayStatus(selectedJob).label}</b> · {displayStatus(selectedJob).detail}</p><p class="dataset-binding">Dataset · <code>{selectedJob.request.dataset_name}</code></p><div class="gpu-leases"><span>eligible</span><code>{selectedJob.eligible_gpu_indices?.join(', ') || '—'}</code><span>assigned</span><code>{selectedJob.resource_gpu_indices?.join(', ') || '—'}</code><span>desired</span><code>{selectedJob.desired_gpu_indices?.join(', ') || '—'}</code><span>draining</span><code>{selectedJob.draining_gpu_indices?.join(', ') || '—'}</code></div>{#if selectedJob.external_import_pids?.length}<div class="external-import">기존 controller가 시작한 importer가 계속 작업 중입니다. 이 프로세스가 끝날 때까지 Resume safely는 잠깁니다.</div>{/if}{#if waitingForResource(selectedJob)}<div class="resource-waiting">현재 GPU worker lease가 없습니다. 다음 단계가 {resourceLabel(selectedJob)}을 확보할 때까지 queue에서 대기 중입니다.</div>{/if}<div class="job-times"><span>생성</span><time>{formatKst(selectedJob.created_at)}</time><span>시작</span><time>{formatKst(selectedJob.started_at)}</time><span>최근 갱신</span><time>{formatKst(selectedJob.updated_at)}</time><span>완료</span><time>{formatKst(selectedJob.finished_at)}</time></div><section class="pipeline-progress"><header><b>Pipeline milestones</b><strong>{globalProgress.toFixed(1)}%</strong></header><progress max="100" value={globalProgress}></progress><div class="stage-grid">{#each pipelineSteps as step}<div class={`stage-step ${step.status}`}><span>{step.label}</span><b>{step.status === 'complete' ? '완료' : step.status === 'active' ? `${step.progress?.toFixed(0) ?? '…'}%` : '대기'}</b><progress max="100" value={step.progress ?? undefined}></progress></div>{/each}</div>{#if selectedJob.stage_progress?.geometry}<small class="checkpoint-progress">Geometry checkpoints · {selectedJob.stage_progress.geometry.completed} / {selectedJob.stage_progress.geometry.total} units · crash-safe resume</small>{/if}</section>{#if selectedJob.stage === 'generate' && selectedJob.stage_progress?.generate}<section class="tqdm-card"><header><b>Infinigen · {selectedJob.stage_progress.generate.phase}</b><strong>{solverPhasePercent(selectedJob.stage_progress.generate) != null ? `current solver ${solverPhasePercent(selectedJob.stage_progress.generate)?.toFixed(0)}% · ` : ''}completed phases {generationMilestone(selectedJob.stage_progress.generate)?.toFixed(0) ?? '…'}%</strong></header><progress max="100" value={solverPhasePercent(selectedJob.stage_progress.generate) ?? 0}></progress><div><span>phase {selectedJob.stage_progress.generate.phase_index}/{selectedJob.stage_progress.generate.phase_count}</span>{#if selectedJob.stage_progress.generate.local_total}<span>local annealing {selectedJob.stage_progress.generate.local_completed}/{selectedJob.stage_progress.generate.local_total}{solverPhasePercent(selectedJob.stage_progress.generate) != null ? ` (${solverPhasePercent(selectedJob.stage_progress.generate)?.toFixed(1)}%)` : ''}</span>{/if}{#if selectedJob.stage_progress.generate.object_count != null}<span>objects {selectedJob.stage_progress.generate.object_count}</span>{/if}<span>solver pass는 같은 phase 안에서 재시작될 수 있음</span></div></section>{/if}{#if tqdmProgress}<section class="tqdm-card"><header><b>{tqdmProgress.label}</b><strong>{tqdmProgress.percent.toFixed(0)}%</strong></header><progress max={tqdmProgress.total} value={tqdmProgress.completed}></progress><div><span>{tqdmProgress.completed} / {tqdmProgress.total}</span><span>경과 {tqdmProgress.elapsed}</span><span>예상 {tqdmProgress.eta}</span><span>{tqdmProgress.rate}</span></div>{#if tqdmProgress.detail}<small>현재 · {tqdmProgress.detail}</small>{/if}</section>{/if}{#if selectedJob.error && !selectedJob.external_import_pids?.length}<pre class="job-failure">{selectedJob.error}</pre>{/if}<h4>Artifacts</h4>{#each Object.entries(selectedJob.paths) as [name,path]}<div><span>{name}</span><code>{path}</code></div>{/each}<details class="log-details"><summary>Raw event log ({log.length})</summary><pre>{log.join('\n')}</pre></details>{:else}<p>Select a job to inspect its progress and logs.</p>{/if}</section></div>
  {/if}
</section>
{#if selectedJob && ['queued', 'running'].includes(selectedJob.status) && selectedJob.resource_state === 'waiting_gpu'}
  <div class="gpu-queue-banner">GPU queue #{selectedJob.queue_position ?? '—'} · requested GPU {selectedJob.request.gpu_indices?.join(', ')}</div>
{/if}
{#if recovery}
  <div class="recovery-backdrop">
    <dialog open class="recovery-dialog" aria-label="Recovery plan">
      <header><h3>Recovery plan</h3><button onclick={() => { recovery = null; recoveryJob = null; }}>×</button></header>
      <p>검증된 artifact는 재사용하고, 누락된 prerequisite부터 재개합니다.</p>
      <div class="recovery-stages">{#each recovery.stages as stage}<label class:missing={stage.state === 'Missing'}><input type="checkbox" bind:checked={stage.selected} disabled={stage.state === 'Verified'} /> <b>{stage.stage}</b><span>{stage.state} · {stage.resource_class}</span></label>{/each}</div>
      <p>권장 시작 단계: <b>{recovery.recommended_rerun_from ?? '없음'}</b></p>
      <footer><button onclick={() => resumeRecovery(false)}>Recommended recovery</button><button class="primary" onclick={() => resumeRecovery(true)}>Insert missing steps and resume</button></footer>
    </dialog>
  </div>
{/if}
