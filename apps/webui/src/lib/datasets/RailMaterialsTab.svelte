<script lang="ts">
	import { getObjectMaterialView } from '$lib/api';
	import MaterialInspector from '$lib/datasets/MaterialInspector.svelte';
	import { opticalIorLabel, polarimetricBrdfLabel, rgbCss } from '$lib/datasets/materialHelpers';

	interface Props {
		projectId: string | null | undefined;
		sceneId: string | null | undefined;
	}
	let { projectId, sceneId }: Props = $props();

	let payload = $state<any>(null);
	let loading = $state(false);
	let error = $state('');
	let search = $state('');
	let selectedId = $state<string | null>(null);
	let reqSeq = 0;

	$effect(() => {
		const pid = projectId;
		const sid = sceneId;
		if (!pid || !sid) {
			payload = null;
			return;
		}
		const seq = ++reqSeq;
		loading = true;
		error = '';
		getObjectMaterialView(pid, sid, {})
			.then((res) => {
				if (seq !== reqSeq) return;
				payload = res;
				loading = false;
				// keep selection if still present, else default to first
				const ids = (res?.materials ?? []).map((m: any) => m.material_id);
				if (!selectedId || !ids.includes(selectedId)) selectedId = ids[0] ?? null;
			})
			.catch((err) => {
				if (seq !== reqSeq) return;
				error = String(err?.message ?? err);
				payload = null;
				loading = false;
			});
	});

	const materials = $derived((payload?.materials ?? []) as any[]);
	const filtered = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return materials;
		return materials.filter((m) =>
			`${m.material_id} ${m.material?.optical_class ?? ''} ${m.material?.bsdf_strategy ?? ''}`
				.toLowerCase()
				.includes(q),
		);
	});
	const selectedRow = $derived(materials.find((m) => m.material_id === selectedId) ?? null);
	// The inspector renders a full view payload directly; merge in the top-level mode.
	const selectedResolved = $derived(
		selectedRow ? { ...selectedRow, bsdf_mode: payload?.bsdf_mode, injection_enabled: payload?.injection_enabled } : null,
	);

	function shortLabel(id: string): string {
		return String(id ?? '').replace(/^shader_/, '').replace(/\.\d+$/, '');
	}
</script>

<section class="rail-section rail-tool-panel">
	<div class="rail-title">Materials</div>
	<div class="mt-sub">
		Scene material catalog · IOR / metal eta-k resolved as rendered
		{#if payload?.bsdf_mode}<span class="mt-mode">mode: {payload.bsdf_mode}</span>{/if}
	</div>

	{#if error}
		<div class="mt-error">failed to load materials: {error}</div>
	{:else if loading && !payload}
		<div class="mt-muted">loading scene materials…</div>
	{:else if materials.length === 0}
		<div class="mt-muted">No materials in this scene's authoring map.</div>
	{:else}
		<input
			class="mt-search"
			placeholder="filter materials…"
			value={search}
			oninput={(e) => (search = (e.currentTarget as HTMLInputElement).value)}
		/>
		<div class="mt-count">{filtered.length} / {materials.length}</div>
		<div class="mt-list">
			{#each filtered as m (m.material_id)}
				{@const sw = rgbCss(m.material?.base_color)}
				<button
					class="mt-row"
					class:active={m.material_id === selectedId}
					onclick={() => (selectedId = m.material_id)}
				>
					<span class="mt-sw" style={sw ? `background:${sw}` : ''}></span>
					<span class="mt-name">{shortLabel(m.material_id)}</span>
					<span class="mt-tags">
						<span class="mt-chip">{polarimetricBrdfLabel(m.material?.bsdf_strategy)}</span>
						<span class="mt-ior">{opticalIorLabel(m.optical_resolution)}</span>
					</span>
				</button>
			{/each}
		</div>

		{#if selectedResolved}
			<MaterialInspector {projectId} {sceneId} materialId={selectedId} resolved={selectedResolved} />
		{/if}
	{/if}
</section>

<style>
	.mt-sub {
		font-size: 11.5px;
		color: var(--muted, #667085);
		margin-top: 2px;
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.mt-mode {
		font-family: ui-monospace, Menlo, Consolas, monospace;
	}
	.mt-search {
		width: 100%;
		margin-top: 10px;
		padding: 6px 8px;
		border: 1px solid var(--line, #d9dee8);
		border-radius: 6px;
		font-size: 12.5px;
	}
	.mt-count {
		font-size: 11px;
		color: var(--muted, #667085);
		margin: 6px 0 4px;
	}
	.mt-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-height: 34vh;
		overflow-y: auto;
		margin-bottom: 10px;
	}
	.mt-row {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 5px 7px;
		border: 1px solid transparent;
		border-radius: 6px;
		background: transparent;
		cursor: pointer;
		text-align: left;
		font-size: 12.5px;
	}
	.mt-row:hover {
		background: #f3f6fb;
	}
	.mt-row.active {
		background: #eef2ff;
		border-color: #c7d2fe;
	}
	.mt-sw {
		width: 16px;
		height: 16px;
		border-radius: 4px;
		border: 1px solid var(--line, #d9dee8);
		flex: 0 0 auto;
		background:
			repeating-conic-gradient(#eee 0% 25%, #fff 0% 50%) 50% / 8px 8px;
	}
	.mt-name {
		flex: 1 1 auto;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.mt-tags {
		display: flex;
		align-items: center;
		gap: 6px;
		flex: 0 0 auto;
	}
	.mt-chip {
		padding: 1px 6px;
		border-radius: 999px;
		background: #eef2ff;
		color: #3538cd;
		font-size: 10.5px;
	}
	.mt-ior {
		font-size: 10.5px;
		color: var(--muted, #667085);
		font-family: ui-monospace, Menlo, Consolas, monospace;
	}
	.mt-muted,
	.mt-error {
		font-size: 12px;
		color: var(--muted, #667085);
		margin-top: 8px;
	}
	.mt-error {
		color: #b42318;
	}
</style>
