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
  let width = $state(684); let height = $state(512); let fov = $state(60); let rgbSpp = $state(4000); let nirSpp = $state(2000);
  let flashScale = $state(1); let fillScale = $state(1); let poseBudget = $state(400); let gpuIndices = $state<number[]>([]);
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let refreshInFlight = false; let disposed = false; let requestAbort: AbortController | null = null;
  let lastLogRefreshMs = 0;
  let illuminationDiversity = $state(true); let pairedFraction = $state(0.25);
  let graphMaxNodes = $state(70); let graphHeadingCount = $state(24); let graphMinNodeSpacing = $state(0.25); let graphRobotRadius = $state(0.30);
  let recovery = $state<RecoveryPlan | null>(null); let recoveryJob = $state<ControllerJob | null>(null);
  const roomTypes = [
    'living-room', 'bedroom', 'kitchen', 'bathroom', 'dining-room', 'closet',
    'hallway', 'garage', 'balcony', 'utility', 'staircase-room', 'warehouse',
    'office', 'meeting-room', 'open-office', 'break-room', 'restroom', 'factory-office'
  ];
  type TqdmProgress = { label: string; percent: number; completed: number; total: number; elapsed: string; eta: string; rate: string; detail: string };
  type PipelineStep = { id: string; label: string; status: 'complete' | 'active' | 'pending'; progress: number | null };
  const tqdmProgress = $derived(
    selectedJob?.resource_state === 'running' || (selectedJob?.external_import_pids?.length ?? 0) > 0
      ? parseTqdm(log, selectedJob?.stage ?? '')
      : null
  );
  const pipelineSteps = $derived(selectedJob ? buildPipelineSteps(selectedJob, tqdmProgress) : []);
  const globalProgress = $derived(pipelineSteps.length ? pipelineSteps.reduce((sum, step) => sum + (step.progress ?? 0), 0) / pipelineSteps.length : 0);
  const sceneSeedPreview = $derived(seed === 'today' || !seed.trim() ? kstDateSeed() : seed === 'random' ? 'random' : seed.trim());
  const existingSceneStem = $derived(existingOutput
    ? existingOutput.split('/').filter(Boolean).at(-2)?.replace(/^kr_/, '') ?? 'existing_scene'
    : 'existing_scene');
  const suggestedSceneId = $derived(sourceMode === 'generate'
    ? `infinigen_${archetype}${archetype === 'single_room' ? `_${roomType.replaceAll('-', '_')}` : ''}_${sceneSeedPreview}_v${variationId.toString().padStart(2, '0')}`
    : `infinigen_${existingSceneStem}`);
  const effectiveSceneId = $derived(sceneIdOverride.trim() || suggestedSceneId);
  const suggestedDatasetName = $derived(`${effectiveSceneId}_rgb_active_nir_v2`);
  const effectiveDatasetName = $derived(datasetNameOverride.trim() || suggestedDatasetName);
  const pairedPoseEstimate = $derived(Math.max(1, Math.round(poseBudget * pairedFraction)));
  const illuminationFrameEstimate = $derived(illuminationDiversity ? pairedPoseEstimate * 6 + (poseBudget - pairedPoseEstimate) : poseBudget);

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
      const next = await getControllerStatus(controller.signal);
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
        width, height, fov, rgb_spp: rgbSpp, nir_spp: nirSpp, flash_energy_scale: flashScale, ambient_fill_energy_scale: fillScale, pose_budget: poseBudget,
        illumination_diversity: illuminationDiversity, paired_fraction: pairedFraction,
        graph_max_nodes: graphMaxNodes, graph_heading_count: graphHeadingCount, graph_min_node_spacing: graphMinNodeSpacing, graph_robot_radius: graphRobotRadius,
        camera_policy: cameraPolicy, content_profile: contentProfile, material_mix_profile: 'specular_inverse_balanced_v1', max_quality_variations: 4, adaptive_pose_budget: adaptivePoseBudget,
        sparse_negative_fraction: 0.15, max_headings_per_node: 6 };
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
  async function action(job: ControllerJob, kind: 'cancel' | 'retry' | 'resume' | 'adopt' | 'priority') {
    if (kind === 'resume') { await openRecovery(job); return; }
    try { await controllerJobAction(job.job_id, kind, kind === 'priority' ? { priority: job.priority + 1 } : {}); await refresh(); }
    catch (cause) { error = String(cause); }
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
    if (waitingForResource(job)) {
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
  function buildPipelineSteps(job: ControllerJob, local: TqdmProgress | null): PipelineStep[] {
    const all = [
      ['generate', 'Infinigen 생성'], ['import', 'Bootstrap import · no texture bake'], ['scene_content_audit', 'Scene content audit'],
      ['navigation_compile', 'Navigation graph compile'], ['view_probe', 'Candidate visibility probe'], ['material_extract', 'Source material analysis · extract'],
      ['material_canonicalize', 'Source material analysis · canonicalize'], ['lighting_asset_audit', 'HDRI bank audit'], ['view_plan', 'Content-aware IR render plan'], ['scene_quality_gate', 'Content density gate'], ['geometry', 'IR LOD + final PBR bake'], ['overview_proxy', 'Scene overview proxy'],
      ['principled_prepare', 'Principled Stage 2'], ['material_mix_audit', 'Specular material-mix audit'], ['qc_render', 'Stage 0 render'],
      ['qc_verify', 'Stage 0 QC'], ['full_render', 'Full rolling render'],
      ['full_verify', 'Full QC'], ['dataset_utility_audit', 'Dataset utility audit'], ['publish', 'Immutable publish'],
    ] as const;
    const revisionRelevant = job.request.pipeline_revision === 'ir-content-aware-v2' ? all : all.filter(([id]) => !['scene_content_audit', 'view_probe', 'scene_quality_gate', 'material_mix_audit', 'dataset_utility_audit'].includes(id));
    const lightingRelevant = job.request.illumination_diversity ? revisionRelevant : revisionRelevant.filter(([id]) => id !== 'lighting_asset_audit');
    const qualityRelevant = job.request.content_profile === 'research_balanced' && job.request.source_mode === 'generate' ? lightingRelevant : lightingRelevant.filter(([id]) => !['scene_quality_gate', 'material_mix_audit'].includes(id));
    const relevant = job.request.source_mode === 'augmentation'
      ? qualityRelevant.filter(([id]) => ['lighting_asset_audit','view_plan','overview_proxy','principled_prepare','qc_render','qc_verify','full_render','full_verify','publish'].includes(id))
      : (job.request.source_mode === 'existing' ? qualityRelevant.filter(([id]) => id !== 'generate') : qualityRelevant);
    return relevant.map(([id, label]) => {
      const result = job.stage_results?.[id];
      const measured = job.stage_progress?.[id];
      const displayLabel = id === 'view_plan' && result?.actual_pose_count != null
        ? `${label} · ${result.actual_pose_count}/${result.requested_pose_count} poses · ${result.lighting_group_count} lights`
        : (id === 'generate' && measured?.phase ? `${label} · ${measured.phase}`
          : (measured?.lighting_groups ? `${label} · ${Object.keys(measured.lighting_groups).length} lighting groups` : label));
      if (result?.status === 'succeeded' || (job.status === 'succeeded' && id === 'publish')) return { id, label: displayLabel, status: 'complete', progress: 100 };
      if ((job.stage === id && job.status === 'running') || (id === 'import' && (job.external_import_pids?.length ?? 0) > 0)) return { id, label: displayLabel, status: 'active', progress: measured?.percent ?? local?.percent ?? null };
      return { id, label: displayLabel, status: 'pending', progress: 0 };
    });
  }
</script>

<section class="control-center">
  <header class="control-header"><div><h2>IR Dataset Control Center</h2><p>독립 pipeline queue · bake/render는 할당 GPU 단위로 조정됩니다.</p></div><button onclick={refresh}>Refresh</button></header>
  {#if error}<div class="control-error">{error}<button onclick={() => error = ''}>×</button></div>{/if}
  <nav class="control-tabs"><button class:active={tab === 'create'} onclick={() => tab = 'create'}>Create job</button><button class:active={tab === 'jobs'} onclick={() => tab = 'jobs'}>Jobs ({status.jobs.length})</button><button onclick={onBrowse}>Browse datasets</button></nav>

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
        <h4>Illumination diversity</h4>
        <label><input type="checkbox" bind:checked={illuminationDiversity} /> Paired 6-condition v1</label>
        {#if illuminationDiversity}<label>Paired pose subset <b>{Math.round(pairedFraction * 100)}%</b><input type="range" min="0.05" max="1" step="0.05" bind:value={pairedFraction} /><small>{pairedPoseEstimate} paired poses × 6 conditions + {poseBudget - pairedPoseEstimate} single poses = 약 {illuminationFrameEstimate} frames. HDRI bank: 4 repo-owned CC0 assets.</small></label>{/if}
        <label>Camera policy<select bind:value={cameraPolicy}><option value="content_aware_v2">Content-aware v2</option><option value="coverage_v1">Coverage v1</option></select></label>
          <label>Content profile<select bind:value={contentProfile}><option value="research_balanced">Research balanced</option><option value="balanced">balanced</option><option value="anchor_rich">anchor rich</option><option value="structural">structural</option></select><small>family_home + rich anchors/clutter를 최소로 적용합니다. 밀도·pose·metal GT gate 미달 시 최대 4 variation을 자동 재생성합니다.</small></label>
          {#if contentProfile === 'research_balanced'}<div class="material-contract"><b>Material mix · Specular inverse balanced</b><small>effective metallic ≥ 0.7 · fallback/surrogate 제외 · Stage 0 valid pixel coverage 3–12% · QC frame visibility ≥50% · glass/transmission 제외, opaque non-metal 유지</small></div>{/if}
        <label><input type="checkbox" bind:checked={adaptivePoseBudget} /> Adaptive pose budget</label>
        <label>Maximum camera poses <b>{poseBudget}</b><input type="range" min="160" max="400" step="20" bind:value={poseBudget} /><small>60% informative · 25% structural context · sparse negative ≤15%; scene capacity can reduce the actual count.</small></label>
        <h4>IR camera graph</h4><div class="field-row"><label>Max nodes<input type="number" min="1" max="2000" bind:value={graphMaxNodes} /></label><label>Headings / node<input type="number" min="1" max="72" bind:value={graphHeadingCount} /></label></div>
        <div class="field-row"><label>Node spacing (m)<input type="number" min="0.05" max="5" step="0.05" bind:value={graphMinNodeSpacing} /></label><label>Robot radius (m)<input type="number" min="0.05" max="2" step="0.05" bind:value={graphRobotRadius} /></label></div><small>Kitchen-validated default · 약 70 nodes × 24 headings에서 pose budget만큼 coverage sampling</small>
        <h4>Eligible GPU pool</h4><div class="gpu-list">{#each status.gpu_inventory as gpu}<button class:active={gpuIndices.includes(gpu.index)} disabled={!gpu.eligible} onclick={() => toggleGpu(gpu.index)}><b>GPU {gpu.index}</b> {gpu.name}<small>{gpu.memory_used_mib}/{gpu.memory_total_mib} MiB · {gpu.utilization_pct}% {gpu.owners?.length ? `· ${gpu.owners.map((owner) => `${owner.stage}:${owner.lease_state}`).join(', ')}` : gpu.eligible ? '· idle' : '· outside IR pool'}</small></button>{/each}</div>
      </section>
      <aside class="wizard-card summary"><h3>3. Pipeline</h3><ol><li>Bootstrap import · no texture bake</li><li>Room content contract audit</li><li>Navigation graph + candidate visibility probe</li><li>Content-aware render plan</li><li>Source material analysis</li><li>IR LOD + final PBR bake</li><li>v2 Principled Stage 2</li><li>QC, rolling render, utility gate, immutable publish</li></ol><code>/bean/ir_dataset_work/{effectiveDatasetName}</code><code>/bean/ir_dataset/{effectiveDatasetName}</code><button class="primary" disabled={loading || !effectiveDatasetName || !gpuIndices.length || (sourceMode === 'existing' && !existingOutput) || (sourceMode === 'augmentation' && !legacyDatasetName)} onclick={submit}>{loading ? 'Submitting…' : 'Queue pipeline job'}</button></aside>
    </div>
  {:else}
    <div class="jobs-layout"><section class="job-list">{#if !status.jobs.length}<p>No jobs queued.</p>{/if}{#each status.jobs as job}<article class:active={selectedJob?.job_id === job.job_id}><button class="job-select" onclick={() => selectJob(job)}><header><b>{job.request.scene_id ?? job.request.dataset_name}</b><span class={`status ${displayStatus(job).className}`}>{displayStatus(job).label}</span></header><p>{job.request.dataset_name} · {displayStatus(job).detail}</p><small>{job.error ?? `최근 갱신 · ${formatKst(job.updated_at)}`}</small></button><footer>{#if job.status === 'queued'}<button onclick={() => action(job, 'priority')}>Priority +</button>{/if}{#if job.status === 'queued' || job.status === 'running'}<button onclick={() => action(job, 'cancel')}>Cancel</button>{/if}{#if ['failed','cancelled','interrupted'].includes(job.status) && (job.external_import_pids?.length ?? 0) > 0}<button onclick={() => action(job, 'adopt')}>Attach running import</button>{:else if ['failed','cancelled','interrupted'].includes(job.status)}<button onclick={() => action(job, 'resume')}>Resume safely</button>{/if}</footer></article>{/each}</section>
    <section class="job-detail">{#if selectedJob}<h3>{selectedJob.request.scene_id ?? selectedJob.request.dataset_name}</h3><p><b>{displayStatus(selectedJob).label}</b> · {displayStatus(selectedJob).detail}</p><p class="dataset-binding">Dataset · <code>{selectedJob.request.dataset_name}</code></p><div class="gpu-leases"><span>eligible</span><code>{selectedJob.eligible_gpu_indices?.join(', ') || '—'}</code><span>assigned</span><code>{selectedJob.resource_gpu_indices?.join(', ') || '—'}</code><span>desired</span><code>{selectedJob.desired_gpu_indices?.join(', ') || '—'}</code><span>draining</span><code>{selectedJob.draining_gpu_indices?.join(', ') || '—'}</code></div>{#if selectedJob.external_import_pids?.length}<div class="external-import">기존 controller가 시작한 importer가 계속 작업 중입니다. 이 프로세스가 끝날 때까지 Resume safely는 잠깁니다.</div>{/if}{#if waitingForResource(selectedJob)}<div class="resource-waiting">현재 GPU worker lease가 없습니다. 다음 단계가 {resourceLabel(selectedJob)}을 확보할 때까지 queue에서 대기 중입니다.</div>{/if}<div class="job-times"><span>생성</span><time>{formatKst(selectedJob.created_at)}</time><span>시작</span><time>{formatKst(selectedJob.started_at)}</time><span>최근 갱신</span><time>{formatKst(selectedJob.updated_at)}</time><span>완료</span><time>{formatKst(selectedJob.finished_at)}</time></div><section class="pipeline-progress"><header><b>Pipeline progress</b><strong>{globalProgress.toFixed(1)}%</strong></header><progress max="100" value={globalProgress}></progress><div class="stage-grid">{#each pipelineSteps as step}<div class={`stage-step ${step.status}`}><span>{step.label}</span><b>{step.status === 'complete' ? '완료' : step.status === 'active' ? `${step.progress?.toFixed(0) ?? '…'}%` : '대기'}</b><progress max="100" value={step.progress ?? undefined}></progress></div>{/each}</div>{#if selectedJob.stage_progress?.geometry}<small class="checkpoint-progress">Geometry checkpoints · {selectedJob.stage_progress.geometry.completed} / {selectedJob.stage_progress.geometry.total} units · crash-safe resume</small>{/if}</section>{#if selectedJob.stage === 'generate' && selectedJob.stage_progress?.generate}<section class="tqdm-card"><header><b>Infinigen · {selectedJob.stage_progress.generate.phase}</b><strong>약 {selectedJob.stage_progress.generate.percent.toFixed(0)}%</strong></header><progress max="100" value={selectedJob.stage_progress.generate.percent}></progress><div><span>phase {selectedJob.stage_progress.generate.phase_index}/{selectedJob.stage_progress.generate.phase_count}</span>{#if selectedJob.stage_progress.generate.local_total}<span>local annealing {selectedJob.stage_progress.generate.local_completed}/{selectedJob.stage_progress.generate.local_total}</span>{/if}{#if selectedJob.stage_progress.generate.object_count != null}<span>objects {selectedJob.stage_progress.generate.object_count}</span>{/if}<span>전체 값은 phase 기반 추정</span></div></section>{/if}{#if tqdmProgress}<section class="tqdm-card"><header><b>{tqdmProgress.label}</b><strong>{tqdmProgress.percent.toFixed(0)}%</strong></header><progress max={tqdmProgress.total} value={tqdmProgress.completed}></progress><div><span>{tqdmProgress.completed} / {tqdmProgress.total}</span><span>경과 {tqdmProgress.elapsed}</span><span>예상 {tqdmProgress.eta}</span><span>{tqdmProgress.rate}</span></div>{#if tqdmProgress.detail}<small>현재 · {tqdmProgress.detail}</small>{/if}</section>{/if}{#if selectedJob.error && !selectedJob.external_import_pids?.length}<pre class="job-failure">{selectedJob.error}</pre>{/if}<h4>Artifacts</h4>{#each Object.entries(selectedJob.paths) as [name,path]}<div><span>{name}</span><code>{path}</code></div>{/each}<details class="log-details"><summary>Raw event log ({log.length})</summary><pre>{log.join('\n')}</pre></details>{:else}<p>Select a job to inspect its progress and logs.</p>{/if}</section></div>
  {/if}
</section>
{#if selectedJob?.resource_state === 'waiting_gpu'}
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
