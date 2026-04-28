<script lang="ts">
	import { curatedMaterialPreviewUrl, measuredMaterialPreviewUrl } from '$lib/api';
	import type { DatasetGroup, MatEntry } from '$lib/types/materialLibrary';

	type Props = {
		mat: MatEntry;
		group: DatasetGroup;
		selected?: boolean;
		busy?: boolean;
		// Cache-buster: when this changes the <img src> gets a new ?v= suffix so
		// the browser actually re-fetches. The page bumps it after a preview
		// invalidate so the daemon's on-demand re-render is triggered.
		bust?: number;
		// Check mode: when `checkable` is true, the card shows a checkbox in
		// the corner and the page hands click events to onToggleCheck (instead
		// of opening the right-rail detail).
		checkable?: boolean;
		checked?: boolean;
		onToggleCheck?: (mat: MatEntry, group: DatasetGroup) => void;
		onSelect?: (mat: MatEntry, group: DatasetGroup) => void;
		onAction?: (action: 'rerender' | 'redownload', mat: MatEntry, group: DatasetGroup) => void;
	};
	let {
		mat,
		group,
		selected = false,
		busy = false,
		bust = 0,
		checkable = false,
		checked = false,
		onToggleCheck,
		onSelect,
		onAction
	}: Props = $props();

	let menuOpen = $state(false);

	function previewSrc(): string {
		const base =
			mat.kind === 'curated'
				? curatedMaterialPreviewUrl(mat.material_id)
				: measuredMaterialPreviewUrl(group.dataset_id, mat.material_id, mat.native_file);
		return bust > 0 ? `${base}${base.includes('?') ? '&' : '?'}v=${bust}` : base;
	}

	function downloadBadge(): { label: string; cls: string } {
		switch (mat.status) {
			case 'available':
				return { label: '다운로드 완료', cls: 'badge-ok' };
			case 'needs_patch':
				return { label: '패치 필요', cls: 'badge-warn' };
			case 'not_downloaded':
				return { label: '다운로드 누락', cls: 'badge-err' };
		}
	}

	function previewBadge(): { label: string; cls: string } {
		switch (mat.preview_status) {
			case 'baked':
				return { label: '프리뷰 완료', cls: 'badge-ok-blue' };
			case 'cached':
				return { label: '캐시됨', cls: 'badge-info' };
			case 'stale':
				return { label: '프리뷰 오래됨', cls: 'badge-warn' };
			case 'missing':
				return { label: '프리뷰 없음', cls: 'badge-muted' };
			case 'failed':
				return { label: '프리뷰 실패', cls: 'badge-err' };
		}
	}

	function handleImgError(e: Event) {
		// First fetch after invalidate often returns 202 (background render);
		// the browser treats that as an image error, so we mark the element as
		// errored. handleImgLoad below clears the flag once the eventual cached
		// PNG finally loads (via a follow-up `bust` bump from the page).
		(e.currentTarget as HTMLImageElement).dataset.previewError = 'true';
	}

	function handleImgLoad(e: Event) {
		delete (e.currentTarget as HTMLImageElement).dataset.previewError;
	}

	function handleMenu(e: MouseEvent) {
		e.stopPropagation();
		menuOpen = !menuOpen;
	}

	function handleAction(action: 'rerender' | 'redownload', e: MouseEvent) {
		e.stopPropagation();
		menuOpen = false;
		onAction?.(action, mat, group);
	}

	const dlBadge = $derived(downloadBadge());
	const pvBadge = $derived(previewBadge());
</script>

<div
	role="button"
	tabindex="0"
	class="mat-card"
	class:selected
	class:busy
	class:checked={checkable && checked}
	class:checkable
	onclick={() => (checkable ? onToggleCheck?.(mat, group) : onSelect?.(mat, group))}
	onkeydown={(e) => {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			if (checkable) onToggleCheck?.(mat, group);
			else onSelect?.(mat, group);
		}
	}}
>
	{#if checkable}
		<span class="mat-check" class:mat-check-on={checked} aria-hidden="true">
			{checked ? '✓' : ''}
		</span>
	{/if}
	<div class="mat-thumb">
		<img src={previewSrc()} alt={mat.display_name} loading="lazy" onerror={handleImgError} onload={handleImgLoad} />
		{#if busy}<div class="mat-spinner" aria-hidden="true"></div>{/if}
	</div>
	<div class="mat-meta">
		<div class="mat-name">{mat.display_name}</div>
		<div class="mat-badges">
			<span class="mat-badge {dlBadge.cls}">{dlBadge.label}</span>
			<span class="mat-badge {pvBadge.cls}">{pvBadge.label}</span>
		</div>
	</div>
	<button
		type="button"
		class="mat-menu-btn"
		aria-label="액션 메뉴"
		onclick={handleMenu}
	>⋯</button>
	{#if menuOpen}
		<div class="mat-menu" role="menu">
			<button type="button" role="menuitem" onclick={(e) => handleAction('rerender', e)}>
				프리뷰 재렌더링
			</button>
			{#if mat.kind === 'measured' && mat.download_url}
				<button type="button" role="menuitem" onclick={(e) => handleAction('redownload', e)}>
					재다운로드
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.mat-card {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0.75rem;
		/* Same #F7F7F5 as page + thumbnail + rendered PNG bg, so card / thumb /
		   floor all read as a single continuous surface. */
		background: #f7f7f5;
		cursor: pointer;
		text-align: left;
		transition: box-shadow 0.15s, border-color 0.15s, transform 0.05s;
	}
	.mat-card:hover {
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
	}
	.mat-card.selected {
		border-color: var(--brand, #3a7afe);
		box-shadow: 0 0 0 2px var(--brand-soft, rgba(58, 122, 254, 0.18));
	}
	.mat-card.busy {
		opacity: 0.7;
		cursor: wait;
	}
	.mat-card.checked {
		border-color: var(--brand, #3a7afe);
		box-shadow: 0 0 0 2px var(--brand, #3a7afe);
	}
	.mat-card.checkable {
		cursor: pointer;
	}
	.mat-check {
		position: absolute;
		top: 0.5rem;
		left: 0.5rem;
		width: 1.25rem;
		height: 1.25rem;
		border: 1.5px solid rgba(0, 0, 0, 0.25);
		background: rgba(255, 255, 255, 0.92);
		border-radius: 4px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.85rem;
		line-height: 1;
		color: transparent;
		z-index: 4;
		pointer-events: none;
	}
	.mat-check.mat-check-on {
		background: var(--brand, #3a7afe);
		border-color: var(--brand, #3a7afe);
		color: #fff;
	}
	.mat-thumb {
		position: relative;
		aspect-ratio: 1;
		overflow: hidden;
		/* Circle thumb. Combined with RGBA PNG (alpha=0 outside sphere) +
		   the .mat-thumb background = card colour, the visible content is
		   exactly the rendered sphere — no rectangular floor patch. The
		   img scale below zooms the sphere (rendered at ~32% screen radius
		   in a 192² frame) so it fills the circle edge-to-edge. */
		border-radius: 50%;
		background: #f7f7f5;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.mat-thumb img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
		/* Sphere is rendered at ~32% screen radius (camera fov=28° at
		   distance 5.77, sphere radius 0.9). Scale 1.55× → sphere fills
		   the circular thumb edge-to-edge. The translateY(2%) shifts the
		   sphere slightly down in the thumb so the rendered image's top
		   region (empty space above the sphere) gets some breathing room
		   inside the circular clip — without it the sphere top sits flush
		   against the thumb top edge and the silhouette reads as a flat
		   crop. The RGBA alpha mask keeps the silhouette anti-aliased
		   even after scale. */
		transform: scale(1.62) translateY(-2.7%);
		transform-origin: 50% 50%;
	}
	/* data-preview-error is set via JS at runtime (line 57); use :global so
	   Svelte's static CSS analyzer doesn't flag it as unused. */
	.mat-thumb :global(img[data-preview-error='true']) {
		opacity: 0.25;
	}
	.mat-spinner {
		position: absolute;
		inset: 0;
		background: rgba(255, 255, 255, 0.55);
		backdrop-filter: blur(2px);
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.mat-spinner::after {
		content: '';
		width: 1.75rem;
		height: 1.75rem;
		border: 3px solid rgba(58, 122, 254, 0.25);
		border-top-color: var(--brand, #3a7afe);
		border-radius: 50%;
		animation: mat-card-spin 0.9s linear infinite;
	}
	@keyframes mat-card-spin {
		to { transform: rotate(360deg); }
	}
	.mat-meta {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.mat-name {
		font-weight: 600;
		font-size: 0.875rem;
		line-height: 1.2;
		color: var(--ink-strong, #1f2330);
	}
	.mat-badges {
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem;
		margin-top: 0.25rem;
	}
	.mat-badge {
		font-size: 0.65rem;
		padding: 0.15rem 0.45rem;
		border-radius: 999px;
		font-weight: 500;
		white-space: nowrap;
	}
	.badge-ok {
		background: #e7f6ec;
		color: #1f7a3f;
	}
	.badge-ok-blue {
		background: #e6f0ff;
		color: #1d4ed8;
	}
	.badge-info {
		background: #eef2ff;
		color: #4338ca;
	}
	.badge-warn {
		background: #fff4e2;
		color: #b45309;
	}
	.badge-err {
		background: #fdecec;
		color: #b91c1c;
	}
	.badge-muted {
		background: #f1f3f5;
		color: #6b7280;
	}
	.mat-menu-btn {
		position: absolute;
		top: 0.5rem;
		right: 0.5rem;
		width: 1.5rem;
		height: 1.5rem;
		border: none;
		background: rgba(255, 255, 255, 0.85);
		border-radius: 6px;
		font-size: 1.1rem;
		line-height: 1;
		cursor: pointer;
		color: var(--ink-muted, #6b7280);
	}
	.mat-menu-btn:hover {
		background: #fff;
		color: var(--ink-strong, #1f2330);
	}
	.mat-menu {
		position: absolute;
		top: 2.1rem;
		right: 0.5rem;
		min-width: 9rem;
		background: #fff;
		border: 1px solid var(--border-soft, rgba(0, 0, 0, 0.08));
		border-radius: 8px;
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
		padding: 0.25rem;
		z-index: 5;
		display: flex;
		flex-direction: column;
	}
	.mat-menu button {
		text-align: left;
		padding: 0.4rem 0.6rem;
		font-size: 0.8rem;
		border: none;
		background: transparent;
		cursor: pointer;
		border-radius: 4px;
	}
	.mat-menu button:hover {
		background: var(--brand-soft, rgba(58, 122, 254, 0.08));
		color: var(--brand, #3a7afe);
	}
</style>
