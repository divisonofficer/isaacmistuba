<script lang="ts">
  import { listScenes, type DatasetSummary, type SceneCatalog as SceneCatalogPayload } from './api';
  interface Props {
    active: boolean;
    refreshNonce: number;
    onBrowse: (datasetId: string) => void;
  }
  let { active, refreshNonce, onBrowse }: Props = $props();
  let catalog = $state<SceneCatalogPayload | null>(null);
  let loading = $state(true), error = $state('');
  let text = $state(''), roomType = $state(''), density = $state(''), metalClass = $state(''), origin = $state(''), reviewTier = $state(''), includeUnknown = $state(true), pairedOnly = $state(false);
  let minTotal = $state(''), minPerM2 = $state(''), minArea = $state(''), maxArea = $state(''), minVisible = $state(''), sort = $state('name');
  const fmt = (v: number | null | undefined, digits = 1) => v == null ? '—' : Number(v).toFixed(digits);
  const pct = (v: number | null | undefined) => v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`;
  const s = (scene: DatasetSummary) => scene.scene_statistics;
  const edited = (scene: DatasetSummary) => {
    const ns = scene.updated_at_ns ?? scene.created_at_ns;
    if (!ns) return '—';
    const date = new Date(Number(ns) / 1_000_000);
    return Number.isNaN(date.valueOf()) ? '—' : new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric' }).format(date);
  };
  const densityOrder = ['sparse', 'moderate', 'dense', 'unknown'];
  let loadedOnce = false;
  let tierHelpOpen = $state(false);
  let handledRefreshNonce = -1;
  async function load(refresh = false) { loading = true; error = ''; try { catalog = await listScenes({ text, room_type: roomType, density_class: density, metal_class: metalClass, origin, review_tier: reviewTier, paired_only: String(pairedOnly), include_unknown: String(includeUnknown), min_total_objects: minTotal, min_objects_per_m2: minPerM2, min_area_m2: minArea, max_area_m2: maxArea, min_visible_objects: minVisible, sort }, refresh); } catch (cause) { error = cause instanceof Error ? cause.message : String(cause); } finally { loading = false; } }
  function chooseDensity(value: string) { density = density === value ? '' : value; void load(); }
  function sparseFirst() { density = 'sparse'; includeUnknown = false; sort = 'sparse'; void load(); }
  function reset() { text = ''; roomType = ''; density = ''; metalClass = ''; origin = ''; reviewTier = ''; pairedOnly = false; includeUnknown = true; minTotal = ''; minPerM2 = ''; minArea = ''; maxArea = ''; minVisible = ''; sort = 'name'; void load(); }
  // This component remains mounted while the user inspects a frame.  Entering
  // Scenes again should restore the existing list, filters, and scroll state
  // without rebuilding the catalog over HTTP.  Only the explicit Refresh
  // action advances refreshNonce and revalidates the catalog.
  $effect(() => {
    if (!active) return;
    if (!loadedOnce) {
      loadedOnce = true;
      handledRefreshNonce = refreshNonce;
      void load();
      return;
    }
    if (handledRefreshNonce !== refreshNonce) {
      handledRefreshNonce = refreshNonce;
      void load(true);
    }
  });
</script>

<main class="scene-catalog">
  <header class="scene-title"><div><h2>Scene catalog</h2><p>공간 면적, object inventory, 면적당 밀도와 camera pose 가시성을 한 번에 비교합니다.</p></div><button onclick={() => load(true)} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button></header>
  {#if catalog}
    <section class="scene-kpis"><div><b>{catalog.total}</b><span>All scenes</span></div><div><b>{catalog.total - (catalog.distribution.unknown ?? 0)}</b><span>Measured scenes</span></div><div><b>{fmt(catalog.medians.room_area_m2)} m²</b><span>Median space</span></div><div><b>{fmt(catalog.medians.total_objects, 0)}</b><span>Median objects</span></div><div><b>{fmt(catalog.medians.objects_per_m2)}</b><span>Nonstructural / m²</span></div><div><b>{fmt(catalog.medians.visible_objects)}</b><span>Visible objects / pose</span></div></section>
    <section class="scene-analytics"><article class="density-distribution"><header><b>Density distribution</b><small>Click a class to filter</small></header><div class="density-bar">{#each densityOrder as key}<button class:active={density === key} class={`density-segment ${key}`} style={`flex:${catalog.distribution[key] ?? 0}`} onclick={() => chooseDensity(key)}>{catalog.distribution[key] ?? 0}</button>{/each}</div><div class="density-legend">{#each densityOrder as key}<button class:active={density === key} class={`density ${key}`} onclick={() => chooseDensity(key)}>{key} <b>{catalog.distribution[key] ?? 0}</b></button>{/each}</div></article><article class="density-scatter"><header><b>Scene review tiers</b><button class="tier-help" onclick={() => tierHelpOpen = true}>Tier guide ⓘ</button></header><div class="density-legend review-legend">{#each ['A','B','C','D','unknown'] as key}<button class:active={reviewTier === key} onclick={() => { reviewTier = reviewTier === key ? '' : key; void load(); }}>Tier {key} <b>{catalog.review_distribution?.[key] ?? 0}</b></button>{/each}</div><p>Tier A: dense + ≥50 poses + ≥20% paired lighting. Tier B: dense but insufficient coverage. Tier C: paired but not dense. Tier D: sparse/unknown or no paired variation; inspect before explicit retirement.</p></article></section>
  {/if}
  <section class="scene-filters" aria-label="Scene catalog filters">
    <div class="filter-grid">
      <label>Search<input bind:value={text} placeholder="scene name" onkeydown={(event) => event.key === 'Enter' && load()} /></label>
      <label>Room<select bind:value={roomType}><option value="">All rooms</option>{#each catalog?.facets.room_types ?? [] as value}<option value={value}>{value}</option>{/each}</select></label>
      <label>Review tier<select bind:value={reviewTier}><option value="">All tiers</option>{#each ['A','B','C','D','unknown'] as value}<option value={value}>Tier {value}</option>{/each}</select></label>
      <label>Metal mix<select bind:value={metalClass}><option value="">All</option><option value="balanced-metal">Balanced metal</option><option value="metal-rich">Metal rich</option><option value="metal-sparse">Metal sparse</option><option value="unknown">Unknown</option></select></label>
      <label>Origin<select bind:value={origin}><option value="">All origins</option>{#each catalog?.facets.origins ?? [] as value}<option value={value}>{value}</option>{/each}</select></label>
      <label>Objects min<input type="number" min="0" placeholder="—" bind:value={minTotal}/></label>
      <label>Space min m²<input type="number" min="0" placeholder="—" bind:value={minArea}/></label>
      <label>Visible min<input type="number" min="0" step=".1" placeholder="—" bind:value={minVisible}/></label>
      <label>Sort<select bind:value={sort}><option value="name">Name</option><option value="created">Most recently created</option><option value="updated">Most recently edited</option><option value="sparse">Sparse first</option><option value="objects">Most objects</option><option value="density">Highest objects/m²</option><option value="area">Largest space</option><option value="visible">Most visible</option><option value="metal">Highest metallic coverage</option></select></label>
      <label class="check"><input type="checkbox" bind:checked={includeUnknown}/> Include unknown</label>
    </div>
    <div class="filter-actions"><button class="primary" onclick={() => load()}>Apply</button><button onclick={sparseFirst}>Sparse first</button><button onclick={reset}>Reset</button></div>
    <details class="advanced-filters"><summary>More filters</summary><div><label>Objects/m² min<input type="number" min="0" step=".1" bind:value={minPerM2}/></label><label>Space max m²<input type="number" min="0" bind:value={maxArea}/></label><label class="check"><input type="checkbox" bind:checked={pairedOnly}/> Paired lighting only</label></div></details>
  </section>
  {#if error}<p class="scene-error">{error}</p>{/if}
  <section class="scene-table"><header><span>Scene</span><span>Room / origin</span><span>Inventory</span><span>Space</span><span>Last edited ↓</span><span>Review</span></header>{#each catalog?.scenes ?? [] as scene}<button class="scene-row" onclick={() => onBrowse(scene.dataset_id)}><span><b>{scene.name}</b><small>{scene.viewpoint_count} VP · {scene.frame_count} frames</small></span><span>{s(scene).room_type ?? 'Unknown'}<small>{scene.primary_origin}</small></span><span>{s(scene).object_count ?? '—'} · {s(scene).nonstructural_object_count ?? '—'} nonstruct.<small>{fmt(s(scene).nonstructural_objects_per_m2)} objects/m²</small></span><span>{fmt(s(scene).room_area_m2)} m²<small>{fmt(s(scene).selected_visible_object_median)} visible / pose</small></span><span class="scene-edited">{edited(scene)}</span><span class="review-cell"><b class={`tier tier-${scene.scene_review?.review_tier ?? 'unknown'}`}>Tier {scene.scene_review?.review_tier ?? 'unknown'}</b><i>{s(scene).density_class}</i><i>{scene.scene_review?.physical_pose_count ?? '—'} poses</i><i>{scene.scene_review?.paired_pose_count ?? 0} paired</i></span></button>{/each}</section>
  {#if !loading && catalog?.filtered === 0}<p class="empty">No scenes match the current filters.</p>{/if}
</main>
{#if tierHelpOpen}
  <div class="tier-modal-backdrop" role="presentation" onclick={() => tierHelpOpen = false}>
    <dialog open class="tier-modal" aria-labelledby="tier-modal-title" onclick={(event) => event.stopPropagation()}>
      <h3 id="tier-modal-title">Scene review tiers</h3>
      <p>밀도, 물리 pose 수, paired-lighting 비율로 review tier를 결정합니다.</p>
      <ul><li><b>Tier A</b> dense scene with ≥50 poses and ≥20% paired lighting.</li><li><b>Tier B</b> dense scene with incomplete coverage.</li><li><b>Tier C</b> paired captures with lower density.</li><li><b>Tier D</b> sparse, unknown, or unpaired scene; retain for explicit review.</li></ul>
      <button class="primary" onclick={() => tierHelpOpen = false}>Done</button>
    </dialog>
  </div>
{/if}
