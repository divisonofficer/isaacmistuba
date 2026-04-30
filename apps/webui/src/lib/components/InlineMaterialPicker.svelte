<script lang="ts">
	import { lang } from '$lib/stores/lang';
	import {
		materialLibrary,
		materialPresets,
		curatedMaterialPreviewUrl,
		measuredMaterialPreviewUrl,
		materialPreviewUrl
	} from '$lib/api';
	import { applyMaterialToPrims, type ApplyMaterialKind, type ApplyResult } from '$lib/materialApply';
	import { goto } from '$app/navigation';

	type MatEntry = {
		material_id: string;
		display_name: string;
		native_file: string;
		status: string;
		kind?: 'curated';
	};
	type DatasetGroup = {
		dataset_id: string;
		display_name: string;
		mitsuba_strategy: string;
		materials: MatEntry[];
	};
	type Preset = { bsdf_type: string; title_en: string; title_kr: string };

	type Props = {
		sceneId: string | null;
		targetPrimPaths: string[];
		onApplied?: (result: ApplyResult & { displayName: string }) => void;
	};
	const { sceneId, targetPrimPaths, onApplied }: Props = $props();

	const L = $derived($lang);

	type TabKey = 'curated' | 'measured' | 'preset';
	let tab = $state<TabKey>('curated');
	let search = $state('');
	let groups = $state<DatasetGroup[]>([]);
	let presets = $state<Preset[]>([]);
	let loading = $state(true);
	let pendingId = $state<string | null>(null);
	let lastResult = $state<ApplyResult & { displayName: string } | null>(null);
	let errorMsg = $state('');

	$effect(() => {
		void (async () => {
			loading = true;
			try {
				const [lib, pres] = await Promise.all([
					materialLibrary().catch(() => ({ groups: [] })),
					materialPresets().catch(() => ({ presets: [] }))
				]);
				groups = (lib.groups ?? []) as DatasetGroup[];
				presets = (pres.presets ?? []) as Preset[];
			} finally {
				loading = false;
			}
		})();
	});

	const curatedGroup = $derived(groups.find((g) => g.dataset_id === 'curated_basic'));
	const measuredGroups = $derived(groups.filter((g) => g.dataset_id !== 'curated_basic'));

	function filterMats(mats: MatEntry[]): MatEntry[] {
		const q = search.trim().toLowerCase();
		if (!q) return mats;
		return mats.filter((m) => (m.display_name ?? '').toLowerCase().includes(q) || m.material_id.toLowerCase().includes(q));
	}
	function filterPresets(items: Preset[]): Preset[] {
		const q = search.trim().toLowerCase();
		if (!q) return items;
		return items.filter((p) =>
			(p.title_kr ?? '').toLowerCase().includes(q)
			|| (p.title_en ?? '').toLowerCase().includes(q)
			|| p.bsdf_type.toLowerCase().includes(q)
		);
	}

	async function applyOne(material: ApplyMaterialKind, displayName: string, key: string) {
		if (!sceneId || !targetPrimPaths.length || pendingId) return;
		pendingId = key;
		errorMsg = '';
		try {
			const res = await applyMaterialToPrims(sceneId, targetPrimPaths, material);
			lastResult = { ...res, displayName };
			onApplied?.(lastResult);
		} catch (e: unknown) {
			errorMsg = (e as Error).message ?? 'error';
		} finally {
			pendingId = null;
		}
	}

	function curatedKey(m: MatEntry) { return `curated:${m.material_id}`; }
	function measuredKey(g: DatasetGroup, m: MatEntry) { return `measured:${g.dataset_id}:${m.material_id}`; }
	function presetKey(p: Preset) { return `preset:${p.bsdf_type}`; }

	function openLibraryFallback() {
		const primary = targetPrimPaths[0] ?? '';
		const apply = primary ? `apply_to=${encodeURIComponent(primary)}&scene=${encodeURIComponent(sceneId ?? '')}` : '';
		goto(apply ? `/materials?${apply}` : '/materials');
	}
</script>

<div class="imp-root">
	<div class="imp-header">
		<div class="imp-target">
			{#if !targetPrimPaths.length}
				<span class="muted text-xs">{L === 'kr' ? '먼저 오브젝트를 선택하세요.' : 'Select an object first.'}</span>
			{:else if targetPrimPaths.length === 1}
				<span class="card-eyebrow">{L === 'kr' ? '재질 적용' : 'Apply material'}</span>
				<span class="mono text-xs imp-target-chip" title={targetPrimPaths[0]}>→ {targetPrimPaths[0]}</span>
			{:else}
				<span class="card-eyebrow">{L === 'kr' ? '재질 적용' : 'Apply material'}</span>
				<span class="imp-multichip">
					{L === 'kr'
						? `${targetPrimPaths.length}개 오브젝트에 적용`
						: `Apply to ${targetPrimPaths.length} objects`}
				</span>
			{/if}
		</div>
		<div class="imp-tabs" role="tablist">
			{#each [['curated','Curated'],['measured','Measured'],['preset','Preset']] as [k, lbl]}
				<button
					type="button"
					class="imp-tab"
					class:active={tab === k}
					role="tab"
					aria-selected={tab === k}
					onclick={() => (tab = k as TabKey)}
				>{lbl}</button>
			{/each}
		</div>
		<input
			type="text"
			class="imp-search"
			placeholder={L === 'kr' ? '검색…' : 'Search…'}
			bind:value={search}
		/>
		<button type="button" class="button button-subtle text-xs imp-fallback" onclick={openLibraryFallback}>
			🎨 {L === 'kr' ? '전체 라이브러리 열기' : 'Open library'}
		</button>
	</div>

	{#if errorMsg}<div class="imp-error">{errorMsg}</div>{/if}
	{#if lastResult}
		<div class="imp-toast">
			✓ {L === 'kr' ? '적용:' : 'Applied:'} <strong>{lastResult.displayName}</strong>
			· {L === 'kr' ? '성공' : 'ok'} {lastResult.applied}
			{#if lastResult.skipped.length}· {L === 'kr' ? '건너뜀' : 'skipped'} {lastResult.skipped.length}{/if}
		</div>
	{/if}

	{#if loading}
		<div class="imp-empty">{L === 'kr' ? '로딩 중…' : 'Loading…'}</div>
	{:else if !targetPrimPaths.length}
		<div class="imp-empty">{L === 'kr' ? '오브젝트가 선택되지 않았습니다.' : 'No object selected.'}</div>
	{:else if tab === 'curated'}
		{@const items = filterMats(curatedGroup?.materials ?? [])}
		{#if !items.length}
			<div class="imp-empty">{L === 'kr' ? '결과 없음' : 'No matches'}</div>
		{:else}
			<div class="imp-grid">
				{#each items as m (m.material_id)}
					{@const k = curatedKey(m)}
					<button
						type="button"
						class="imp-card"
						disabled={!!pendingId}
						title={m.display_name}
						onclick={() =>
							applyOne(
								{ kind: 'curated', material_id: m.material_id },
								m.display_name,
								k
							)
						}
					>
						<img src={curatedMaterialPreviewUrl(m.material_id)} alt="" loading="lazy" class="imp-thumb" />
						<span class="imp-label">{m.display_name}</span>
						{#if pendingId === k}<span class="imp-spin">…</span>{/if}
					</button>
				{/each}
			</div>
		{/if}
	{:else if tab === 'measured'}
		{#each measuredGroups as g (g.dataset_id)}
			{@const items = filterMats(g.materials.filter((m) => m.status === 'available'))}
			{#if items.length}
				<div class="imp-section">
					<div class="imp-section-title">{g.display_name}</div>
					<div class="imp-grid">
						{#each items as m (m.material_id)}
							{@const k = measuredKey(g, m)}
							<button
								type="button"
								class="imp-card"
								disabled={!!pendingId}
								title={m.display_name}
								onclick={() =>
									applyOne(
										{
											kind: 'measured',
											dataset_id: g.dataset_id,
											material_id: m.material_id,
											measured_file_path: m.native_file,
											mitsuba_strategy: g.mitsuba_strategy
										},
										m.display_name,
										k
									)
								}
							>
								<img src={measuredMaterialPreviewUrl(g.dataset_id, m.material_id, m.native_file)} alt="" loading="lazy" class="imp-thumb" />
								<span class="imp-label">{m.display_name}</span>
								{#if pendingId === k}<span class="imp-spin">…</span>{/if}
							</button>
						{/each}
					</div>
				</div>
			{/if}
		{/each}
	{:else}
		{@const items = filterPresets(presets)}
		{#if !items.length}
			<div class="imp-empty">{L === 'kr' ? '결과 없음' : 'No matches'}</div>
		{:else}
			<div class="imp-grid">
				{#each items as p (p.bsdf_type)}
					{@const k = presetKey(p)}
					<button
						type="button"
						class="imp-card"
						disabled={!!pendingId}
						title={L === 'kr' ? p.title_kr : p.title_en}
						onclick={() =>
							applyOne(
								{ kind: 'preset', bsdf_type: p.bsdf_type },
								L === 'kr' ? p.title_kr : p.title_en,
								k
							)
						}
					>
						<img src={materialPreviewUrl(p.bsdf_type)} alt="" loading="lazy" class="imp-thumb" />
						<span class="imp-label">{L === 'kr' ? p.title_kr : p.title_en}</span>
						{#if pendingId === k}<span class="imp-spin">…</span>{/if}
					</button>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<style>
	.imp-root {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		padding: 0.5rem 0.25rem;
		min-height: 0;
		flex: 1 1 auto;
	}
	.imp-header {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-areas:
			'target tabs'
			'search fallback';
		gap: 0.45rem;
		align-items: center;
	}
	.imp-target { grid-area: target; display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
	.imp-target-chip { background: rgba(99, 102, 241, 0.08); padding: 2px 6px; border-radius: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.imp-multichip { font-size: 0.75rem; background: rgba(34, 197, 94, 0.12); color: #166534; padding: 2px 8px; border-radius: 999px; align-self: flex-start; }
	.imp-tabs { grid-area: tabs; display: inline-flex; gap: 4px; }
	.imp-tab { font-size: 0.75rem; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border, #e5e7eb); background: transparent; cursor: pointer; }
	.imp-tab.active { background: var(--brand, #6366f1); color: #fff; border-color: var(--brand, #6366f1); }
	.imp-search { grid-area: search; padding: 6px 10px; font-size: 0.85rem; border: 1px solid var(--border, #e5e7eb); border-radius: 6px; min-width: 0; }
	.imp-fallback { grid-area: fallback; }
	.imp-empty { font-size: 0.8rem; color: var(--muted, #6b7280); padding: 1rem; text-align: center; }
	.imp-error { font-size: 0.8rem; color: #dc2626; padding: 0.4rem 0.6rem; background: rgba(220, 38, 38, 0.06); border-radius: 4px; }
	.imp-toast { font-size: 0.8rem; color: #166534; padding: 0.4rem 0.6rem; background: rgba(34, 197, 94, 0.08); border-radius: 4px; }
	.imp-section { display: flex; flex-direction: column; gap: 0.35rem; }
	.imp-section-title { font-size: 0.7rem; font-weight: 600; color: var(--muted, #6b7280); text-transform: uppercase; letter-spacing: 0.04em; padding: 0 0.25rem; }
	.imp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: 8px; overflow-y: auto; min-height: 0; max-height: 240px; }
	.imp-card { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 6px; border: 1px solid var(--border, #e5e7eb); border-radius: 6px; background: var(--panel, #fff); cursor: pointer; transition: transform 0.1s, border-color 0.1s; }
	.imp-card:hover:not(:disabled) { border-color: var(--brand, #6366f1); transform: translateY(-1px); }
	.imp-card:disabled { opacity: 0.6; cursor: progress; }
	.imp-thumb { width: 64px; height: 64px; object-fit: cover; border-radius: 4px; background: #f3f4f6; }
	.imp-label { font-size: 0.7rem; color: var(--text, #111); text-align: center; line-height: 1.1; word-break: break-word; max-width: 100%; }
	.imp-spin { position: absolute; top: 4px; right: 6px; font-size: 0.65rem; color: var(--brand, #6366f1); }
</style>
