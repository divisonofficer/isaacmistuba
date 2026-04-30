<script lang="ts">
	import { measuredModalities, type Modality } from '$lib/api';

	type Props = {
		datasetId: string;
		materialId: string;
		previewSize?: number;
		// Bumped by the parent to refetch after a re-render finishes (so the
		// post-Phase-9 manifest replaces the legacy single-composite list).
		refreshKey?: number;
	};
	let { datasetId, materialId, previewSize = 192, refreshKey = 0 }: Props = $props();

	let modalities = $state<Modality[] | null>(null);
	let needsRerender = $state(false);
	let error = $state<string | null>(null);

	async function fetchModalities() {
		modalities = null;
		error = null;
		try {
			const resp = await measuredModalities(datasetId, materialId, previewSize);
			modalities = resp.modalities ?? [];
			needsRerender = Boolean((resp as { needs_rerender?: boolean }).needs_rerender);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	$effect(() => {
		// Re-run on material/dataset change AND on refreshKey bump.
		void datasetId;
		void materialId;
		void refreshKey;
		fetchModalities();
	});

	// Composite first (RGB then NIR, per user: "RGB 따로 NIR 따로"), then
	// spectral bands sorted by wavelength asc, then polar (Phase 13).
	// Inside composite: non-NIR entries (i.e. the visible-RGB composite)
	// come before NIR, since NIR is conceptually a secondary primary view.
	const ordered = $derived.by(() => {
		const list = modalities ?? [];
		const composite = list
			.filter((m) => m.group === 'composite')
			.slice()
			.sort((a, b) => Number(Boolean(a.is_nir)) - Number(Boolean(b.is_nir)));
		const spectral = list
			.filter((m) => m.group === 'spectral')
			.slice()
			.sort((a, b) => (a.wavelength_nm ?? 0) - (b.wavelength_nm ?? 0));
		const polar = list.filter((m) => m.group === 'polar');
		return [
			{ key: 'composite', label: 'RGB / NIR', items: composite },
			{ key: 'spectral', label: '스펙트럼 밴드', items: spectral },
			{ key: 'polar', label: '편광 (Stokes)', items: polar },
		].filter((s) => s.items.length > 0);
	});
</script>

<div class="mod-grid">
	{#if error}
		<div class="mod-grid-empty err">로드 실패: {error}</div>
	{:else if modalities === null}
		<div class="mod-grid-empty">불러오는 중…</div>
	{:else if modalities.length === 0 && needsRerender}
		<div class="mod-grid-hint">
			이 재질·오브젝트 조합의 프리뷰가 아직 없습니다.<br />
			카드의 ⋯ → <strong>프리뷰 재렌더</strong> 를 누르면 채널별 보기가 채워집니다.
		</div>
	{:else if modalities.length === 0}
		<div class="mod-grid-empty">표시할 모달리티가 없습니다.</div>
	{:else}
		{#if needsRerender}
			<!-- Pre-Phase-9 cache: the daemon synthesised one composite entry
			     from the legacy flat PNG. Per-band PNGs only appear after the
			     user re-renders this material. -->
			<div class="mod-grid-hint">
				기존 캐시 (RGB+NIR 합성만). 채널별 보기는 “프리뷰 재렌더링” 후 표시됩니다.
			</div>
		{/if}
		{#each ordered as section (section.key)}
			<section class="mod-grid-section">
				<div class="mod-grid-section-label">{section.label}</div>
				<div class="mod-grid-tiles">
					{#each section.items as m (m.url)}
						<a class="mod-grid-tile" href={m.url} target="_blank" rel="noopener" title={m.label}>
							<div class="mod-grid-thumb">
								<img src={m.url} alt={m.label} loading="lazy" />
							</div>
							<div class="mod-grid-tile-label">
								{m.label}
								{#if m.is_nir}
									<span class="mod-grid-nir">NIR</span>
								{/if}
							</div>
						</a>
					{/each}
				</div>
			</section>
		{/each}
	{/if}
</div>

<style>
	.mod-grid {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.mod-grid-empty {
		padding: 0.75rem 0;
		text-align: center;
		color: var(--ink-muted, #6b7280);
		font-size: 0.78rem;
	}
	.mod-grid-empty.err {
		color: #b91c1c;
	}
	.mod-grid-hint {
		font-size: 0.7rem;
		color: #b45309;
		background: #fff4e2;
		border-radius: 6px;
		padding: 0.35rem 0.55rem;
	}
	.mod-grid-section {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.mod-grid-section-label {
		font-size: 0.65rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--ink-muted, #6b7280);
	}
	.mod-grid-tiles {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
		gap: 0.4rem;
	}
	.mod-grid-tile {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		text-decoration: none;
		color: inherit;
		border-radius: 6px;
		padding: 0.25rem;
		transition: background 0.1s ease;
	}
	.mod-grid-tile:hover {
		background: var(--brand-soft, rgba(58, 122, 254, 0.08));
	}
	.mod-grid-thumb {
		aspect-ratio: 1;
		border-radius: 6px;
		background: #f7f7f5;
		overflow: hidden;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.mod-grid-thumb img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.mod-grid-tile-label {
		font-size: 0.65rem;
		text-align: center;
		color: var(--ink-strong, #1f2330);
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 0.25rem;
		line-height: 1.15;
	}
	.mod-grid-nir {
		font-size: 0.55rem;
		padding: 0.02rem 0.25rem;
		border-radius: 999px;
		background: rgba(185, 28, 28, 0.12);
		color: #b91c1c;
	}
</style>
