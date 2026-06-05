<script lang="ts">
	import { onMount } from 'svelte';
	import AssetThumb3D from '$lib/AssetThumb3D.svelte';
	import {
		bulkSelectOpticalNavAssets,
		importOpticalNavAssetSource,
		listOpticalNavAssets,
		listOpticalNavAssetSources,
		updateOpticalNavAsset
	} from '$lib/api';

	let sources = $state<any[]>([]);
	let assets = $state<any[]>([]);
	let selectedSourceRef = $state('');
	let filterSourceRef = $state('');
	let selectedAssetId = $state('');
	let search = $state('');
	let category = $state('all');
	let selectedOnly = $state(false);
	let loading = $state(false);
	let message = $state('');
	let error = $state('');
	let editLabel = $state('');
	let editCategory = $state('');
	let editPlacement = $state('point');
	let editTags = $state('');
	let editDescription = $state('');
	let editActivationReason = $state('');

	const categories = ['all', 'furniture', 'kitchenware', 'electronics', 'plant', 'shell', 'glass', 'mirror', 'floor', 'object'];
	const selectedAsset = $derived(assets.find((item: any) => item.asset_id === selectedAssetId) ?? assets[0] ?? null);
	const selectedAssetIds = $derived(assets.filter((item: any) => item.selected).map((item: any) => item.asset_id));

	function statusLabel(source: any) {
		if (source.import_status === 'imported') return 'imported';
		if (source.import_status === 'stale') return 'stale';
		if (source.import_status === 'failed') return 'failed';
		return 'not imported';
	}

	function sourceTitle(source: any) {
		return source.label || source.usd_ref?.split('/').pop() || source.usd_ref;
	}

	function sourceKind(source: any) {
		if (source.source_type === 'dtc_glb_object') return 'DTC GLB object';
		return 'USD source';
	}

	function formatSize(bytes: number) {
		if (!Number.isFinite(bytes)) return '-';
		if (bytes > 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
		if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
		return `${Math.round(bytes / 1024)} KB`;
	}

	async function run<T>(fn: () => Promise<T>, ok = 'Done.') {
		loading = true;
		error = '';
		message = '';
		try {
			const data = await fn();
			message = ok;
			return data;
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
			return undefined;
		} finally {
			loading = false;
		}
	}

	async function loadSources() {
		const data = await run(() => listOpticalNavAssetSources(), '');
		if (!data) return;
		sources = data.sources ?? [];
		if (!selectedSourceRef && sources.length) selectedSourceRef = sources[0].usd_ref;
	}

	async function loadAssets() {
		const data = await run(() => listOpticalNavAssets({ q: search, category, selected: selectedOnly, source_ref: filterSourceRef }), '');
		if (!data) return;
		assets = data.assets ?? [];
		if (!selectedAssetId && assets.length) selectedAssetId = assets[0].asset_id;
		if (selectedAssetId && !assets.some((item: any) => item.asset_id === selectedAssetId)) {
			selectedAssetId = assets[0]?.asset_id ?? '';
		}
	}

	async function importSelected(force = false) {
		if (!selectedSourceRef) return;
		const data = await run(() => importOpticalNavAssetSource({ usd_ref: selectedSourceRef, force }), force ? 'Asset source re-imported.' : 'Asset source imported.');
		if (!data) return;
		await loadSources();
		filterSourceRef = selectedSourceRef;
		await loadAssets();
	}

	async function selectSource(source: any) {
		selectedSourceRef = source.usd_ref;
		filterSourceRef = source.usd_ref;
		await loadAssets();
	}

	async function saveAssetPatch(patch: Record<string, unknown>) {
		if (!selectedAsset) return;
		const data = await run(() => updateOpticalNavAsset(selectedAsset.asset_id, patch), 'Asset updated.');
		if (!data) return;
		await loadAssets();
	}

	async function toggleAsset(asset: any, selected: boolean) {
		const data = await run(
			() => updateOpticalNavAsset(asset.asset_id, {
				selected,
				activation_reason: selected ? (asset.activation_reason || editActivationReason || 'Enabled from Asset Library UI.') : (editActivationReason || 'Disabled from Asset Library UI.')
			}),
			selected ? 'Asset enabled for Map Editor.' : 'Asset hidden from Map Editor.'
		);
		if (!data) return;
		await loadAssets();
	}

	async function bulkSelected(selected: boolean) {
		const ids = assets.map((item: any) => item.asset_id);
		const data = await run(() => bulkSelectOpticalNavAssets({ asset_ids: ids, selected }), selected ? 'Visible assets enabled.' : 'Visible assets hidden.');
		if (!data) return;
		await loadAssets();
	}

	function beginEdit(asset: any) {
		if (!asset) return;
		editLabel = asset.label ?? '';
		editCategory = asset.category ?? 'object';
		editPlacement = asset.placement ?? 'point';
		editTags = (asset.tags ?? []).join(', ');
		editDescription = asset.description ?? '';
		editActivationReason = asset.activation_reason ?? '';
	}

	async function saveDetail() {
		await saveAssetPatch({
			label: editLabel,
			category: editCategory,
			placement: editPlacement,
			tags: editTags.split(',').map((item) => item.trim()).filter(Boolean),
			description: editDescription,
			activation_reason: editActivationReason
		});
	}

	$effect(() => beginEdit(selectedAsset));

	onMount(async () => {
		await loadSources();
		await loadAssets();
	});
</script>

<svelte:head>
	<title>Asset Library · Robomituba</title>
</svelte:head>

<main class="asset-page">
	<header class="asset-hero">
		<div>
			<div class="eyebrow">OPTICALNAV ASSET LIBRARY</div>
			<h1>Asset Library</h1>
			<p>Import USD scene primitives and Digital Twin Catalog GLB objects, then choose what appears in the Map Editor.</p>
		</div>
		<div class="hero-actions">
			<button class="button button-subtle" disabled={loading} onclick={loadSources}>Reload Sources</button>
			<button class="button button-primary" disabled={loading || !selectedSourceRef} onclick={() => importSelected(false)}>Import Selected Source</button>
		</div>
	</header>

	{#if error}<div class="notice error">{error}</div>{/if}
	{#if message}<div class="notice ok">{message}</div>{/if}

	<section class="asset-layout">
		<aside class="panel source-panel">
			<div class="panel-label">Asset Sources</div>
			<div class="source-filter-actions">
				<button class:active={!filterSourceRef} onclick={async () => { filterSourceRef = ''; await loadAssets(); }}>All sources</button>
				<button onclick={async () => { search = 'dtc'; filterSourceRef = ''; await loadAssets(); }}>Find DTC</button>
			</div>
			<div class="source-list">
				{#each sources as source}
					<button class:selected={filterSourceRef === source.usd_ref} onclick={() => selectSource(source)}>
						<strong>{sourceTitle(source)}</strong>
						<small>{sourceKind(source)} · {statusLabel(source)} · {source.asset_count ?? 0} assets · {formatSize(source.size_bytes)}</small>
						<span>{source.usd_ref}</span>
					</button>
				{/each}
				{#if sources.length === 0}
					<div class="empty">No USD or DTC GLB candidates found. Place DTC objects under vendor_datasets/dtc_objects/&lt;object&gt;/3d-asset.glb.</div>
				{/if}
			</div>
			<div class="source-actions">
				<button class="button button-primary" disabled={loading || !selectedSourceRef} onclick={() => importSelected(false)}>Import</button>
				<button class="button button-subtle" disabled={loading || !selectedSourceRef} onclick={() => importSelected(true)}>Re-import</button>
			</div>
		</aside>

		<section class="panel asset-table-panel">
			<div class="asset-toolbar">
				<input type="search" placeholder="Search label, source path, category, tags..." bind:value={search} oninput={loadAssets} />
				<select bind:value={category} onchange={loadAssets}>
					{#each categories as item}
						<option value={item}>{item}</option>
					{/each}
				</select>
				<label><input type="checkbox" bind:checked={selectedOnly} onchange={loadAssets} /> selected</label>
			</div>
			<div class="asset-bulk">
				<span>{assets.length} visible · {selectedAssetIds.length} selected{filterSourceRef ? ' · source filtered' : ''}</span>
				<div>
					<button class="button button-subtle" disabled={loading || assets.length === 0} onclick={() => bulkSelected(true)}>Use visible</button>
					<button class="button button-subtle" disabled={loading || assets.length === 0} onclick={() => bulkSelected(false)}>Hide visible</button>
				</div>
			</div>
			<div class="asset-list">
				{#each assets as asset}
					<div class="asset-row" class:selected={selectedAssetId === asset.asset_id} role="button" tabindex="0" onclick={() => (selectedAssetId = asset.asset_id)} onkeydown={(event) => event.key === 'Enter' && (selectedAssetId = asset.asset_id)}>
						<input type="checkbox" checked={asset.selected} onclick={(event) => event.stopPropagation()} onchange={(event) => toggleAsset(asset, event.currentTarget.checked)} />
						<div>
							<strong>{asset.label}</strong>
							<small>{asset.source_path}</small>
						</div>
						<span>{asset.category}</span>
						<span>{asset.placement}</span>
					</div>
				{/each}
				{#if assets.length === 0}
					<div class="empty">No imported assets match this filter.</div>
				{/if}
			</div>
		</section>

		<aside class="panel detail-panel">
			{#if selectedAsset}
				<div class="panel-label">Asset Detail</div>
				<div class="asset-preview">
					<AssetThumb3D category={selectedAsset.category} bounds={selectedAsset.bounds} selected={true} />
					<div>
						<strong>{selectedAsset.label}</strong>
						<small>{selectedAsset.asset_id}</small>
					</div>
				</div>
				<label><span>label</span><input bind:value={editLabel} /></label>
				<label><span>category</span><input bind:value={editCategory} /></label>
				<label>
					<span>placement</span>
					<select bind:value={editPlacement}>
						<option value="point">point</option>
						<option value="line_candidate">line_candidate</option>
					</select>
				</label>
				<label><span>tags</span><input bind:value={editTags} placeholder="chair, furniture, goal" /></label>
				<label>
					<span>LLM description</span>
					<textarea bind:value={editDescription} rows="5" placeholder="Describe what this asset is, material, approximate size, and likely use in navigation scenes."></textarea>
				</label>
				<label>
					<span>activation reason</span>
					<textarea bind:value={editActivationReason} rows="3" placeholder="Why should this asset be active or hidden for the Map Editor?"></textarea>
				</label>
				<div class="detail-facts">
					<div><span>USD</span><strong>{selectedAsset.usd_ref}</strong></div>
					<div><span>source path</span><strong>{selectedAsset.source_path}</strong></div>
					<div><span>material</span><strong>{selectedAsset.material_hint ?? '-'}</strong></div>
					<div><span>size</span><strong>{(selectedAsset.dimensions_m ?? selectedAsset.bounds?.size)?.map((v: number) => Number(v).toFixed(2)).join(' × ') ?? '-'}</strong></div>
				</div>
				<button class="button button-primary full" disabled={loading} onclick={saveDetail}>Save Detail</button>
				<button class="button button-subtle full" disabled={loading} onclick={() => toggleAsset(selectedAsset, !selectedAsset.selected)}>
					{selectedAsset.selected ? 'Hide from Map Editor' : 'Use in Map Editor'}
				</button>
			{:else}
				<div class="empty">Import a USD source and select an asset.</div>
			{/if}
		</aside>
	</section>
</main>

<style>
	.asset-page {
		display: grid;
		gap: var(--space-4);
		padding: var(--space-6);
	}
	.asset-hero,
	.asset-layout > .panel {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-lg);
		background: rgba(255,255,255,0.94);
		box-shadow: var(--shadow-soft);
	}
	.asset-hero {
		display: flex;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-5);
	}
	.eyebrow,
	.panel-label {
		color: var(--brand);
		font-size: var(--font-size-xs);
		font-weight: 900;
		letter-spacing: 0.14em;
		text-transform: uppercase;
	}
	h1 { margin: 4px 0; color: var(--text); }
	p { margin: 0; color: var(--muted-strong); }
	.hero-actions,
	.source-actions,
	.source-filter-actions,
	.asset-bulk,
	.asset-bulk div {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.asset-layout {
		display: grid;
		grid-template-columns: 300px minmax(420px, 1fr) 340px;
		gap: var(--space-4);
		min-height: 720px;
	}
	.panel {
		min-width: 0;
		padding: var(--space-4);
	}
	.source-panel,
	.detail-panel {
		display: grid;
		align-content: start;
		gap: var(--space-3);
	}
	.source-list,
	.asset-list {
		display: grid;
		gap: var(--space-2);
		overflow: auto;
	}
	.source-filter-actions button {
		flex: 1;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--muted-strong);
		padding: 8px 10px;
		cursor: pointer;
	}
	.source-filter-actions button.active {
		border-color: var(--brand);
		background: var(--brand-soft);
		color: var(--brand-strong);
	}
	.source-list { max-height: 610px; }
	.asset-list { max-height: 590px; }
	.source-list button,
	.asset-row {
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		color: var(--text);
		cursor: pointer;
	}
	.source-list button {
		display: grid;
		gap: 3px;
		padding: var(--space-3);
		text-align: left;
	}
	.source-list button.selected,
	.asset-row.selected {
		border-color: var(--brand);
		background: var(--brand-soft);
	}
	.source-list small,
	.source-list span,
	.asset-row small,
	.detail-facts span,
	.detail-facts strong,
	.asset-preview small {
		overflow: hidden;
		color: var(--text-muted);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.source-list span { font-size: var(--font-size-xs); }
	.asset-table-panel {
		display: grid;
		grid-template-rows: auto auto minmax(0, 1fr);
		gap: var(--space-3);
	}
	.asset-toolbar {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 150px auto;
		gap: var(--space-2);
		align-items: center;
	}
	input,
	select,
	textarea {
		width: 100%;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: #fff;
		color: var(--text);
		padding: 8px 10px;
	}
	textarea {
		min-height: 80px;
		resize: vertical;
		line-height: 1.35;
	}
	.asset-bulk {
		justify-content: space-between;
		color: var(--muted-strong);
	}
	.asset-row {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) 110px 120px;
		gap: var(--space-3);
		align-items: center;
		padding: var(--space-2) var(--space-3);
	}
	.asset-row input {
		width: 16px;
		height: 16px;
		padding: 0;
	}
	.asset-row > span {
		color: var(--muted-strong);
		font-size: var(--font-size-sm);
	}
	.asset-preview {
		display: grid;
		grid-template-columns: 88px minmax(0, 1fr);
		gap: var(--space-3);
		align-items: center;
	}
	.detail-panel label {
		display: grid;
		gap: 4px;
		color: var(--muted-strong);
	}
	.detail-facts {
		display: grid;
		gap: var(--space-2);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background: var(--surface-1);
		padding: var(--space-3);
	}
	.detail-facts div {
		display: grid;
		gap: 2px;
	}
	.detail-facts strong {
		color: var(--text);
		font-size: var(--font-size-xs);
	}
	.full { width: 100%; }
	.empty {
		border: 1px dashed var(--panel-border);
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		padding: var(--space-4);
		text-align: center;
	}
	.notice {
		border-radius: var(--radius-sm);
		padding: var(--space-3);
	}
	.notice.ok { background: #ecfdf3; color: #236b35; }
	.notice.error { background: #fff1f1; color: #b42318; }
	@media (max-width: 1180px) {
		.asset-layout {
			grid-template-columns: 1fr;
		}
	}
</style>
