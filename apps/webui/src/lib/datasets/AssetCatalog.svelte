<script lang="ts">
	import AssetThumb3D from '$lib/AssetThumb3D.svelte';
	import { builtInThumbType, placementHintForTool, usdAssetLabel } from '$lib/datasets/authoringHelpers';
	import type { BuiltInPlaceAsset } from '$lib/opticalnavBuiltInAssets';
	import { opticalNavAssetThumbnailUrl } from '$lib/api';

	interface Props {
		pageMode: string;
		placementTool: string;
		selectedAuthoringId: string;
		builtInBuildAssets: any[];
		builtInPlaceAssetGroups: { label: string; assets: BuiltInPlaceAsset[] }[];
		selectedUsdAssetId: string;
		usdCatalogSearch: string;
		mapAssets: any[];
		mapAssetStatus: string;
		usdAssetCandidates: any[];
		libraryDisplayLimit: number;
		selectedProjectId: string;
		assetThumbRefreshTick: number;
		onSelectTool: (tool: string) => void;
		onDelete: () => void;
		onSelectBuiltInPlaceAsset: (asset: BuiltInPlaceAsset) => void;
		onSelectUsdAsset: (assetId: string) => void;
		onSearchChange: (v: string) => void;
	}

	let {
		pageMode, placementTool, selectedAuthoringId,
		builtInBuildAssets, builtInPlaceAssetGroups,
		selectedUsdAssetId, usdCatalogSearch,
		mapAssets, mapAssetStatus, usdAssetCandidates,
		libraryDisplayLimit, selectedProjectId, assetThumbRefreshTick,
		onSelectTool, onDelete, onSelectBuiltInPlaceAsset, onSelectUsdAsset, onSearchChange,
	}: Props = $props();

	const primitiveTool = (asset: BuiltInPlaceAsset) =>
		asset.kind === 'primitive' ? asset.tool : 'select';
</script>

{#if pageMode === 'map'}
	<div class="map-float-asset-catalog build-catalog">
		<div class="catalog-head">
			<div>
				<div class="panel-label">Build Catalog</div>
				<small>Structure and navigation layers.</small>
			</div>
		</div>
		<div class="catalog-tools">
			<button class:active={placementTool === 'select'} onclick={() => onSelectTool('select')}>Select</button>
			<button class="danger" disabled={!selectedAuthoringId} onclick={onDelete}>Delete</button>
		</div>
		<div class="asset-card-list">
			{#each builtInBuildAssets as asset}
				<button
					class:selected={placementTool === asset.tool}
					class="asset-card"
					title={asset.label}
					onclick={() => onSelectTool(asset.tool)}
				>
					<AssetThumb3D category={asset.category} assetType={asset.tool} bounds={asset.bounds} selected={placementTool === asset.tool} />
					<span>{asset.label}</span>
					<small>{asset.hint}</small>
				</button>
			{/each}
		</div>
	</div>
{:else if pageMode === 'objects'}
	<div class="map-float-asset-catalog">
		<div class="catalog-head">
			<div>
				<div class="panel-label">Place Catalog</div>
				<small>Furniture and landmarks.</small>
			</div>
		</div>
		<div class="catalog-tools">
			<button class:active={placementTool === 'select'} onclick={() => onSelectTool('select')}>Select</button>
			<button class="danger" disabled={!selectedAuthoringId} onclick={onDelete}>Delete</button>
		</div>
		<div class="asset-section-title">Verified Library Assets</div>
		<input class="asset-search" type="search" placeholder="Search {mapAssets.length} assets..." value={usdCatalogSearch} oninput={(e) => onSearchChange((e.currentTarget as HTMLInputElement).value)} />
		{#if !usdCatalogSearch.trim() && mapAssets.length > libraryDisplayLimit}
			<small class="catalog-status">Showing {libraryDisplayLimit} of {mapAssets.length} — search to filter all</small>
		{:else}
			<small class="catalog-status">{mapAssetStatus}</small>
		{/if}
		<div class="asset-card-list library-assets">
			{#each usdAssetCandidates as asset}
				{@const assetId = asset.asset_id ?? asset.id}
				<button
					class:selected={selectedUsdAssetId === assetId && placementTool === 'usd_asset'}
					class="asset-card"
					title={asset.source_path}
					onclick={() => onSelectUsdAsset(assetId)}
				>
					<div class="asset-thumb-img" aria-hidden="true">
						<img
							src={selectedProjectId ? `${opticalNavAssetThumbnailUrl(selectedProjectId, assetId)}&r=${assetThumbRefreshTick}` : ''}
							alt=""
							loading="lazy"
							draggable="false"
						/>
					</div>
					<span>{usdAssetLabel(asset)}</span>
					<small>{asset.render_readiness ?? asset.category} · {asset.placement}</small>
				</button>
			{/each}
			{#if usdAssetCandidates.length === 0}
				<div class="catalog-empty">
					No selected USD assets yet.
					<a href="/assets">Open Asset Library</a>
				</div>
			{/if}
		</div>
		{#if builtInPlaceAssetGroups.length}
			<div class="catalog-divider"></div>
			<div class="asset-section-title">Debug Proxies</div>
			{#each builtInPlaceAssetGroups as group}
				<div class="asset-subsection-title">{group.label}</div>
				<div class="asset-card-list debug-proxies">
					{#each group.assets as asset}
						{@const tool = primitiveTool(asset)}
						{@const primitiveSelected = asset.kind === 'primitive' && placementTool === tool}
						<button
							class:selected={primitiveSelected}
							class="asset-card debug-card"
							title={`${asset.label} · debug proxy`}
							onclick={() => onSelectBuiltInPlaceAsset(asset)}
						>
							<AssetThumb3D category={asset.category} assetType={builtInThumbType(asset)} bounds={asset.bounds} selected={primitiveSelected} />
							<span>{asset.label}</span>
							<small>{placementHintForTool(tool)}</small>
						</button>
					{/each}
				</div>
			{/each}
		{/if}
	</div>
{/if}

<style>
	.map-float-asset-catalog {
			position: absolute;
			left: 20px;
			top: 86px;
			z-index: 12;
			width: 292px;
			max-height: min(640px, calc(100vh - 180px));
			overflow: auto;
			border: 1px solid var(--panel-border);
			border-radius: 16px;
			background: rgba(255,255,255,0.92);
			box-shadow: 0 18px 45px rgba(15,23,42,0.14);
			backdrop-filter: blur(14px);
			padding: 10px;
		}

	.catalog-head {
			display: flex;
			align-items: flex-start;
			justify-content: space-between;
			gap: 8px;
			margin-bottom: 8px;
		}

	.catalog-head small {
			color: var(--muted-strong);
			font-size: 11px;
		}

	.catalog-tools {
			display: grid;
			grid-template-columns: 1fr 1fr;
			gap: 8px;
			margin-bottom: 10px;
		}

	.catalog-tools button {
			border: 1px solid var(--panel-border);
			border-radius: 10px;
			background: rgba(248,250,252,0.82);
			color: var(--text);
			font-weight: 800;
			padding: 8px 10px;
			cursor: pointer;
		}

	.catalog-tools button.active {
			border-color: var(--brand);
			background: #eff6ff;
			color: var(--brand);
		}

	.catalog-tools button.danger {
			color: var(--danger);
		}

	.catalog-tools button:disabled {
			opacity: 0.42;
			cursor: default;
		}

	.asset-section-title {
			margin: 8px 2px 6px;
			color: var(--brand);
			font-size: 11px;
			font-weight: 800;
			letter-spacing: 0.12em;
			text-transform: uppercase;
		}

	.asset-subsection-title {
			margin: 8px 2px 5px;
			color: var(--muted);
			font-size: 11px;
			font-weight: 800;
		}

	.catalog-divider {
			height: 1px;
			background: var(--panel-border);
			margin: 10px 0;
		}

	.asset-card-list {
			display: grid;
			gap: 7px;
		}

	.library-assets {
			max-height: 390px;
			overflow: auto;
			padding-right: 2px;
		}


	.debug-proxies {
		max-height: 180px;
		overflow: auto;
	}

	.debug-card {
		opacity: 0.72;
	}

	.asset-search {
			width: 100%;
			border: 1px solid var(--panel-border);
			border-radius: 10px;
			background: #fff;
			color: var(--text);
			padding: 7px 9px;
		}

	.catalog-status {
			display: block;
			margin: 5px 2px;
			color: var(--text-muted);
		}

	.catalog-empty {
			display: grid;
			gap: 6px;
			border: 1px dashed var(--panel-border);
			border-radius: 10px;
			color: var(--text-muted);
			padding: var(--space-3);
			font-size: var(--font-size-xs);
			text-align: center;
		}

	.catalog-empty a {
			color: var(--brand);
			font-weight: 800;
		}

	.asset-card {
			display: grid;
			grid-template-columns: 58px minmax(0, 1fr);
			grid-template-rows: auto auto;
			column-gap: 9px;
			row-gap: 2px;
			align-items: start;
			min-height: 72px;
			border: 1px solid var(--panel-border);
			border-radius: 10px;
			background: rgba(248,250,252,0.78);
			padding: 8px;
			text-align: left;
			cursor: pointer;
		}

	.asset-card:hover,
		.asset-card.selected {
			border-color: var(--brand);
			background: #eff6ff;
		}

	.asset-card :global(.asset-thumb),
		.asset-thumb-img {
			grid-row: 1 / span 2;
		}

	.asset-card :global(.asset-thumb) {
			width: 58px;
			height: 58px;
		}

	.asset-thumb-img {
			width: 58px;
			height: 58px;
			border-radius: 8px;
			background: linear-gradient(180deg, rgba(248,250,252,0.96), rgba(226,232,240,0.9));
			overflow: hidden;
			flex-shrink: 0;
		}

	.asset-thumb-img img {
			display: block;
			width: 100%;
			height: 100%;
			border-radius: inherit;
			object-fit: contain;
		}

	.asset-card span,
		.asset-card small {
			overflow: hidden;
		}

	.asset-card span {
			color: var(--text);
			font-size: 12.5px;
			font-weight: 800;
			line-height: 1.2;
			display: -webkit-box;
			line-clamp: 2;
			-webkit-line-clamp: 2;
			-webkit-box-orient: vertical;
		}

	.asset-card small {
			color: var(--text-muted);
			font-size: 10px;
			line-height: 1.25;
			white-space: normal;
		}
</style>
