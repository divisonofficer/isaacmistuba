<script lang="ts">
	import { getObjectMaterialView } from '$lib/api';
	import {
		customMaterialInfo, rgbCss, bakedAtlasUrlFor,
		opticalIorLabel, polarimetricBrdfLabel,
	} from '$lib/datasets/materialHelpers';

	interface Props {
		projectId: string | null | undefined;
		sceneId: string | null | undefined;
		materialId?: string | null;
		objectId?: string | null;
		/** Object source_ref: fallback for atlas thumbnails before the fetch resolves. */
		sourceRef?: string | null;
		/** The authoring material entry (for an instant label/colour render). */
		entry?: any;
		/** Pre-resolved view payload (list-mode row): render directly, skip the fetch. */
		resolved?: any;
	}

	let {
		projectId, sceneId, materialId = null, objectId = null,
		sourceRef = null, entry = null, resolved = null,
	}: Props = $props();

	// Instant, synchronous summary from the inline authoring entry (no round-trip).
	const localInfo = $derived(customMaterialInfo(entry));

	let fetched = $state<any>(null);
	let loading = $state(false);
	let error = $state('');
	// When a caller supplies a pre-resolved payload, render it and skip fetching.
	const view = $derived(resolved ?? fetched);
	// Monotonic token so a slow response for a previously-selected material can't
	// overwrite the current one.
	let reqSeq = 0;

	$effect(() => {
		if (resolved) {
			error = '';
			return;
		}
		const pid = projectId;
		const sid = sceneId;
		const mid = materialId;
		const oid = objectId;
		if (!pid || !sid || (!mid && !oid)) {
			fetched = null;
			error = '';
			return;
		}
		const seq = ++reqSeq;
		loading = true;
		error = '';
		getObjectMaterialView(pid, sid, { materialId: mid, objectId: oid })
			.then((res) => {
				if (seq !== reqSeq) return;
				fetched = res;
				loading = false;
			})
			.catch((err) => {
				if (seq !== reqSeq) return;
				error = String(err?.message ?? err);
				fetched = null;
				loading = false;
			});
	});

	const mat = $derived(view?.material ?? null);
	const optics = $derived(view?.optical_resolution ?? null);
	const measured = $derived(view?.measured_candidate ?? null);
	const injectedMode = $derived(view?.bsdf_mode === 'injected');

	// Atlas tiles: prefer server-resolved urls (carry an `exists` flag); otherwise
	// derive client-side from source_ref (the <img> 404s gracefully to the swatch).
	const atlases = $derived.by(() => {
		const kinds: ('albedo' | 'roughness' | 'normal')[] = ['albedo', 'roughness', 'normal'];
		const server = view?.atlases ?? null;
		const src = server?.source_ref ?? sourceRef;
		return kinds.map((kind) => {
			const s = server?.[kind];
			return {
				kind,
				url: s?.url ?? bakedAtlasUrlFor(src, kind),
				exists: s?.exists ?? null,
			};
		});
	});

	const swatch = $derived(rgbCss(mat?.base_color ?? localInfo?.baseColor ?? null));
	const label = $derived(localInfo?.label ?? materialId ?? '—');
	const bsdfLabel = $derived(
		polarimetricBrdfLabel(mat?.bsdf_strategy) || localInfo?.bsdfLabel || '',
	);

	function hideImg(e: Event) {
		(e.currentTarget as HTMLImageElement).style.display = 'none';
	}
</script>

<section class="mat-inspector">
	<div class="mi-head">
		<span class="mi-swatch" style={swatch ? `background:${swatch}` : ''}></span>
		<div class="mi-title">
			<strong>{label}</strong>
			<div class="mi-chips">
				{#if mat?.optical_class || localInfo?.opticalClassLabel}
					<span class="chip">{mat?.optical_class ?? localInfo?.opticalClassLabel}</span>
				{/if}
				{#if bsdfLabel}<span class="chip chip-bsdf">{bsdfLabel}</span>{/if}
				{#if mat?.polarization_capable ?? localInfo?.polarization}
					<span class="chip chip-polar">polarization</span>
				{/if}
			</div>
		</div>
	</div>

	{#if error}
		<div class="mi-error">material view failed: {error}</div>
	{:else if !view && loading}
		<div class="mi-muted">resolving optical constants…</div>
	{:else if view}
		<div class="mi-grid">
			<div class="mi-row">
				<span class="mi-key">Optical</span>
				<span class="mi-val">
					{#if optics}
						{#if optics.applies_as === 'conductor'}
							<span class="chip chip-metal">metal · {optics.conductor_preset}</span>
							<span class="mi-dim">eta-k preset</span>
						{:else}
							<strong>{opticalIorLabel(optics)}</strong>
						{/if}
					{/if}
				</span>
			</div>
			<div class="mi-row">
				<span class="mi-key">Polarimetric BRDF</span>
				<span class="mi-val">
					<code>{mat?.polarimetric_brdf ?? '—'}</code>
					{#if mat?.polarization_source}<span class="mi-dim">· {mat.polarization_source}</span>{/if}
				</span>
			</div>
			<div class="mi-row">
				<span class="mi-key">Roughness / Metallic</span>
				<span class="mi-val mi-dim">
					{mat?.roughness ?? '—'} / {mat?.metallic ?? '—'}
				</span>
			</div>
			{#if measured}
				<div class="mi-row">
					<span class="mi-key">Measured pBRDF</span>
					<span class="mi-val">
						<strong>{measured.dataset_id}:{measured.material_id}</strong>
						{#if measured.channels_dir}<div class="mi-path">{measured.channels_dir}</div>{/if}
					</span>
				</div>
			{/if}
		</div>

		{#if !injectedMode && optics}
			<div class="mi-note">
				IOR / eta-k above apply when <code>ROBOMITUBA_BSDF_MODE=injected</code>
				(current: <code>{view.bsdf_mode}</code>).
			</div>
		{/if}

		<div class="mi-atlas-label">Baked atlases</div>
		<div class="mi-atlases">
			{#each atlases as a (a.kind)}
				<div class="mi-atlas" class:missing={a.exists === false}>
					<span class="mi-atlas-thumb" style={swatch ? `background:${swatch}` : ''}>
						{#if a.url && a.exists !== false}
							<img src={a.url} alt={a.kind} loading="lazy" onerror={hideImg} />
						{/if}
					</span>
					<small>{a.kind}{#if a.exists === false} · none{/if}</small>
				</div>
			{/each}
		</div>
	{:else}
		<div class="mi-muted">No material selected.</div>
	{/if}
</section>

<style>
	.mat-inspector {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 12px;
		border: 1px solid var(--line, #d9dee8);
		border-radius: 8px;
		background: var(--paper, #fff);
		font-size: 13px;
	}
	.mi-head {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.mi-swatch {
		width: 34px;
		height: 34px;
		border-radius: 6px;
		border: 1px solid var(--line, #d9dee8);
		flex: 0 0 auto;
		background:
			repeating-conic-gradient(#eee 0% 25%, #fff 0% 50%) 50% / 12px 12px;
	}
	.mi-title strong {
		display: block;
		font-size: 13.5px;
		word-break: break-all;
	}
	.mi-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 3px;
	}
	.chip {
		display: inline-block;
		padding: 1px 7px;
		border-radius: 999px;
		border: 1px solid var(--line, #d9dee8);
		background: #f3f6fb;
		color: #475467;
		font-size: 11px;
	}
	.chip-bsdf {
		background: #eef2ff;
		color: #3538cd;
		border-color: #c7d2fe;
	}
	.chip-polar {
		background: #ecfdf3;
		color: #067647;
		border-color: #abefc6;
	}
	.chip-metal {
		background: #fff7ed;
		color: #9a3412;
		border-color: #fed7aa;
	}
	.mi-grid {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.mi-row {
		display: grid;
		grid-template-columns: 130px 1fr;
		gap: 8px;
		align-items: baseline;
	}
	.mi-key {
		color: var(--muted, #667085);
		font-size: 11.5px;
	}
	.mi-val code,
	.mi-val strong {
		font-size: 12.5px;
	}
	.mi-dim {
		color: var(--muted, #667085);
		font-size: 11.5px;
	}
	.mi-path {
		font-family: ui-monospace, Menlo, Consolas, monospace;
		font-size: 11px;
		color: var(--muted, #667085);
		word-break: break-all;
		margin-top: 2px;
	}
	.mi-note {
		font-size: 11.5px;
		color: #9a3412;
		background: #fff7ed;
		border-left: 3px solid #fdba74;
		border-radius: 0 5px 5px 0;
		padding: 6px 9px;
	}
	.mi-note code {
		font-size: 11px;
	}
	.mi-atlas-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--muted, #667085);
		font-weight: 700;
	}
	.mi-atlases {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 8px;
	}
	.mi-atlas {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
	}
	.mi-atlas.missing {
		opacity: 0.45;
	}
	.mi-atlas-thumb {
		width: 100%;
		aspect-ratio: 1;
		border-radius: 6px;
		border: 1px solid var(--line, #d9dee8);
		overflow: hidden;
		display: block;
	}
	.mi-atlas-thumb img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.mi-atlas small {
		font-size: 10.5px;
		color: var(--muted, #667085);
	}
	.mi-muted,
	.mi-error {
		font-size: 12px;
		color: var(--muted, #667085);
	}
	.mi-error {
		color: #b42318;
	}
</style>
