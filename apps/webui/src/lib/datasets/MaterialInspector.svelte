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

	// object -> materials (1:N): an Infinigen mesh has several usemtl face groups.
	// When the endpoint returns object_materials, show a selector and render the body
	// for the active group; otherwise fall back to the single top-level material.
	const objMats = $derived((view?.object_materials ?? []) as any[]);
	const isMulti = $derived(objMats.length > 1);
	let activeIdx = $state(0);
	$effect(() => {
		// reset the active sub-material whenever the selected object/material changes
		void objectId;
		void materialId;
		activeIdx = 0;
	});
	const active = $derived(isMulti ? objMats[Math.min(activeIdx, objMats.length - 1)] : view);
	const objTotalTris = $derived(objMats.reduce((n, m) => n + (Number(m?.triangle_count) || 0), 0));
	function triPct(m: any): number {
		const t = Number(m?.triangle_count) || 0;
		return objTotalTris > 0 ? Math.round((100 * t) / objTotalTris) : 0;
	}

	const mat = $derived(active?.material ?? null);
	const optics = $derived(active?.optical_resolution ?? null);
	const measured = $derived(active?.measured_candidate ?? null);
	const injectedMode = $derived(view?.bsdf_mode === 'injected');
	const usedBy = $derived((active?.used_by ?? []) as any[]);
	const usedCount = $derived(active?.used_by_count ?? usedBy.length);

	const swatch = $derived(rgbCss(mat?.base_color ?? localInfo?.baseColor ?? null));
	function shortMat(id: unknown): string {
		return String(id ?? '')
			.replace(/^shader_/, '')
			.replace(/\.\d+$/, '');
	}

	/** Grayscale CSS colour for a scalar in [0,1] (roughness / metallic swatch fallback). */
	function grayCss(v: unknown): string {
		const n = Number(v);
		if (!Number.isFinite(n)) return '';
		const g = Math.round(Math.max(0, Math.min(1, n)) * 255);
		return `rgb(${g}, ${g}, ${g})`;
	}
	const fmt = (v: unknown) => (Number.isFinite(Number(v)) ? Number(v).toFixed(2) : null);

	// PBR map tiles: albedo/roughness/metallic. Prefer the baked atlas (server carries
	// an `exists` flag); otherwise fall back to a swatch (base colour for albedo, a
	// grayscale value for roughness/metallic) so the scalar is always visualized.
	const pbrMaps = $derived.by(() => {
		const server = active?.atlases ?? null;
		const src = server?.source_ref ?? sourceRef;
		const defs: { kind: 'albedo' | 'roughness' | 'metallic'; value: number | null; fallback: string }[] = [
			{ kind: 'albedo', value: null, fallback: swatch },
			{ kind: 'roughness', value: mat?.roughness ?? null, fallback: grayCss(mat?.roughness) },
			{ kind: 'metallic', value: mat?.metallic ?? null, fallback: grayCss(mat?.metallic) },
		];
		return defs.map((d) => {
			const s = server?.[d.kind];
			return {
				...d,
				valueLabel: fmt(d.value),
				url: s?.url ?? bakedAtlasUrlFor(src, d.kind),
				exists: s?.exists ?? null,
			};
		});
	});
	const label = $derived(
		isMulti ? shortMat(active?.material_id) : (localInfo?.label ?? materialId ?? '—'),
	);
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
		{#if isMulti}
			<div class="mi-multi">
				<div class="mi-multi-label">Object composition · {objMats.length} materials</div>
				<div class="mi-comp">
					{#each objMats as om, i (om.material_id)}
						<button
							class="mi-comp-row"
							class:active={i === activeIdx}
							onclick={() => (activeIdx = i)}
							title={om.material_id}
						>
							<span
								class="mi-comp-sw"
								style={rgbCss(om.material?.base_color) ? `background:${rgbCss(om.material?.base_color)}` : ''}
							></span>
							<span class="mi-comp-name">{shortMat(om.material_id)}</span>
							<span class="mi-comp-bsdf">{polarimetricBrdfLabel(om.material?.bsdf_strategy)}</span>
							{#if objTotalTris > 0}
								<span class="mi-comp-bar"><span class="mi-comp-fill" style="width:{triPct(om)}%"></span></span>
								<span class="mi-comp-pct">{triPct(om)}%</span>
							{/if}
						</button>
					{/each}
				</div>
				<div class="mi-multi-hint">selected material detail below</div>
			</div>
		{/if}

		<div class="mi-atlas-label">PBR maps</div>
		<div class="mi-atlases">
			{#each pbrMaps as m (m.kind)}
				<div class="mi-atlas">
					<span class="mi-atlas-thumb" style={m.fallback ? `background:${m.fallback}` : ''}>
						{#if m.url && m.exists !== false}
							<img src={m.url} alt={m.kind} loading="lazy" onerror={hideImg} />
						{/if}
					</span>
					<small>{m.kind}</small>
					<span class="mi-atlas-val">
						{#if m.valueLabel != null}{m.valueLabel}{:else if m.exists}baked{:else}—{/if}
					</span>
				</div>
			{/each}
			<!-- IOR / metal eta-k: not a texture; visualized as a value tile alongside the maps -->
			<div class="mi-atlas">
				<span
					class="mi-atlas-thumb mi-ior-tile"
					class:metal={optics?.applies_as === 'conductor'}
				>
					{#if optics}
						<span class="mi-ior-num">
							{optics.applies_as === 'conductor'
								? optics.conductor_preset
								: opticalIorLabel(optics).replace('IOR ', '')}
						</span>
					{/if}
				</span>
				<small>{optics?.applies_as === 'conductor' ? 'metal η,k' : 'IOR'}</small>
				<span class="mi-atlas-val">
					{optics?.applies_as === 'conductor' ? 'conductor' : 'dielectric'}
				</span>
			</div>
		</div>

		<div class="mi-grid">
			<div class="mi-row">
				<span class="mi-key">Polarimetric BRDF</span>
				<span class="mi-val">
					<code>{mat?.polarimetric_brdf ?? '—'}</code>
					{#if mat?.polarization_source}<span class="mi-dim">· {mat.polarization_source}</span>{/if}
				</span>
			</div>
			<div class="mi-row">
				<span class="mi-key">Used by</span>
				<span class="mi-val">
					{#if usedCount === 0}
						<span class="mi-dim">unused · orphan material (no object references it)</span>
					{:else}
						<strong>{usedCount}</strong> object{usedCount > 1 ? 's' : ''}
						<div class="mi-usedlist">
							{#each usedBy.slice(0, 8) as u (u.object_id)}
								<span class="mi-usedobj" title={u.object_id}>{u.label ?? u.object_id}</span>
							{/each}
							{#if usedCount > 8}<span class="mi-dim">+{usedCount - 8} more</span>{/if}
						</div>
					{/if}
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
				IOR / eta-k apply when <code>ROBOMITUBA_BSDF_MODE=injected</code>
				(current: <code>{view.bsdf_mode}</code>).
			</div>
		{/if}
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
	.mi-usedlist {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 4px;
	}
	.mi-usedobj {
		max-width: 100%;
		padding: 1px 6px;
		border-radius: 4px;
		background: #f3f6fb;
		border: 1px solid var(--line, #d9dee8);
		font-size: 10.5px;
		color: #344054;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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
	.mi-multi {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.mi-multi-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--muted, #667085);
		font-weight: 700;
	}
	.mi-comp {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.mi-comp-row {
		display: flex;
		align-items: center;
		gap: 7px;
		width: 100%;
		padding: 4px 7px;
		border: 1px solid transparent;
		border-radius: 6px;
		background: transparent;
		cursor: pointer;
		text-align: left;
		font-size: 12px;
	}
	.mi-comp-row:hover {
		background: #f3f6fb;
	}
	.mi-comp-row.active {
		background: #eef2ff;
		border-color: #c7d2fe;
	}
	.mi-comp-sw {
		width: 14px;
		height: 14px;
		border-radius: 3px;
		border: 1px solid var(--line, #d9dee8);
		flex: 0 0 auto;
	}
	.mi-comp-name {
		flex: 1 1 auto;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.mi-comp-bsdf {
		flex: 0 0 auto;
		padding: 0 6px;
		border-radius: 999px;
		background: #eef2ff;
		color: #3538cd;
		font-size: 10px;
	}
	.mi-comp-bar {
		flex: 0 0 46px;
		height: 6px;
		border-radius: 999px;
		background: #eaecf0;
		overflow: hidden;
	}
	.mi-comp-fill {
		display: block;
		height: 100%;
		background: #6172f3;
	}
	.mi-comp-pct {
		flex: 0 0 auto;
		width: 34px;
		text-align: right;
		font-family: ui-monospace, Menlo, Consolas, monospace;
		font-size: 10.5px;
		color: var(--muted, #667085);
	}
	.mi-multi-hint {
		font-size: 10.5px;
		color: var(--muted, #667085);
		font-style: italic;
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
		grid-template-columns: repeat(4, 1fr);
		gap: 8px;
	}
	.mi-atlas {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 3px;
		min-width: 0;
	}
	.mi-atlas-val {
		font-size: 10.5px;
		font-family: ui-monospace, Menlo, Consolas, monospace;
		color: #344054;
	}
	.mi-ior-tile {
		display: flex;
		align-items: center;
		justify-content: center;
		background: #eef2ff;
	}
	.mi-ior-tile.metal {
		background: #fff7ed;
	}
	.mi-ior-num {
		font-size: 15px;
		font-weight: 700;
		color: #3538cd;
	}
	.mi-ior-tile.metal .mi-ior-num {
		color: #9a3412;
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
