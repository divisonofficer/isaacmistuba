<script lang="ts">
	// Sync Inspector — render-scene vs authoring-map parity + BSDF injection status.
	// Extracted into its own tab (was duplicated in Sensors + Preview, and only
	// loaded after visiting Preview). The parent triggers the render-scene-stats
	// fetch when this tab is active.
	interface Props {
		renderSceneStats: any;
		renderSceneStatsLoading: boolean;
		sceneId: string;
		editorObjectsCount: number;
		editorEmitterCount: number;
		editorMaterialCount: number;
		authoringMap: any;
		rigMountHeightM: number;
		showRoomShell: boolean;
		roomShell: any;
		refreshEnabled: boolean;
		refreshReason: string;
		onSetShowRoomShell: (v: boolean) => void;
		onRefreshStats: () => void;
	}
	let {
		renderSceneStats, renderSceneStatsLoading, sceneId, editorObjectsCount, editorEmitterCount,
		editorMaterialCount, authoringMap, rigMountHeightM, showRoomShell, roomShell,
		refreshEnabled, refreshReason, onSetShowRoomShell, onRefreshStats,
	}: Props = $props();

	// Infinigen PBR re-bake: the daemon runs no Blender, so we surface the exact
	// CLI command (source blend from render-scene stats) for the user to run.
	let bakeCmdShown = $state(false);
	let bakeCmdCopied = $state(false);
	const bakeCmd = $derived(
		renderSceneStats?.infinigen_source_blend
			? `bash apps/run_infinigen_import.sh "${renderSceneStats.infinigen_source_blend}" --scene-id ${sceneId} --bake-only`
			: ''
	);
	async function copyBakeCmd() {
		bakeCmdShown = true;
		try {
			await navigator.clipboard.writeText(bakeCmd);
			bakeCmdCopied = true;
			setTimeout(() => (bakeCmdCopied = false), 2000);
		} catch {
			/* clipboard blocked — command still shown for manual copy */
		}
	}
</script>

<section class="rail-section rail-tool-panel sync-inspector">
	<div class="rail-title">Sync Inspector</div>
	{#if renderSceneStats == null}
		<div class="sync-hint">Loading render-scene stats…</div>
	{/if}
	<div class="sync-row"><span>Authoring objects</span><span>{editorObjectsCount}</span></div>
	<div class="sync-row"><span>Render shapes (XML)</span><span>{renderSceneStats?.shape_count ?? '—'}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.exists && renderSceneStats.obj_shape_count === 0 && editorObjectsCount > 0}>
		<span>Real USD meshes (OBJ)</span><span>{renderSceneStats?.obj_shape_count ?? '—'}</span>
	</div>
	<div class="sync-row"><span>Cube fallbacks</span><span>{renderSceneStats?.cube_shape_count ?? '—'}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.exists && editorObjectsCount > 0 && renderSceneStats.shape_count < editorObjectsCount}>
		<span>Δ object mismatch</span>
		<span>{renderSceneStats?.shape_count != null ? renderSceneStats.shape_count - editorObjectsCount : '—'}</span>
	</div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>is_emitter=true objects</span><span>{editorEmitterCount}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.exists && renderSceneStats.area_emitter_count !== editorEmitterCount}>
		<span>Area emitters (XML)</span><span>{renderSceneStats?.area_emitter_count ?? '—'}</span>
	</div>
	<div class="sync-row"><span>Environment (envmap)</span><span>{renderSceneStats?.envmap_count ?? '—'}</span></div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>Authoring materials</span><span>{editorMaterialCount}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.raw_hpbrdf_refs > 0}>
		<span>Raw .hpbrdf refs (heavy)</span><span>{renderSceneStats?.raw_hpbrdf_refs ?? '—'}</span>
	</div>
	<div class="sync-row"><span>Channel-split refs</span><span>{renderSceneStats?.channel_split_refs ?? '—'}</span></div>
	<div class="sync-row"><span>Measured BSDFs</span><span>{renderSceneStats?.measured_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Measured candidates</span><span>{renderSceneStats?.measured_candidates ?? '—'}</span></div>
	<div class="sync-row"><span>Default measured on</span><span>{renderSceneStats?.measured_enabled_default ?? '—'}</span></div>
	<div class="sync-row"><span>Default suppressed</span><span>{renderSceneStats?.measured_suppressed_default ?? '—'}</span></div>
	<div class="sync-row"><span>Analytic BSDFs</span><span>{renderSceneStats?.analytic_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Analytic polar+RGB</span><span>{renderSceneStats?.analytic_polar_rgb_count ?? '—'}</span></div>
	<div class="sync-row" class:warn={renderSceneStats?.invalid_analytic_fallback_count > 0}>
		<span>Invalid analytic fallback</span><span>{renderSceneStats?.invalid_analytic_fallback_count ?? '—'}</span>
	</div>
	<div class="sync-row"><span>Diffuse-like analytic</span><span>{renderSceneStats?.diffuse_like_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Specular analytic</span><span>{renderSceneStats?.specular_like_bsdf_count ?? '—'}</span></div>
	<div class="sync-row"><span>Measured polarized BSDFs</span><span>{renderSceneStats?.measured_polarized_count ?? '—'}</span></div>
	<div class="sync-divider"></div>
	<div class="sync-row inj-head"><span>🔬 BSDF injection (improved render)</span></div>
	<div class="sync-row"><span>BSDF mode (env)</span><span>{renderSceneStats?.bsdf_mode ?? '—'}</span></div>
	<div class="sync-row" class:warn={renderSceneStats != null && !renderSceneStats.bsdf_injection_active}>
		<span>IOR / metal linking</span>
		<span>{renderSceneStats == null ? '—' : renderSceneStats.bsdf_injection_active ? '✓ injected' : 'legacy (hardcoded)'}</span>
	</div>
	<div class="sync-row"><span>Injected metals (real eta-k)</span><span>{renderSceneStats?.injected_metal_count ?? '—'}</span></div>
	<div class="sync-row"><span>Per-material IOR variants</span><span>{renderSceneStats?.per_material_ior_variants ?? '—'}</span></div>
	<div class="sync-row"><span>pplastic texture-α (per-texel rough)</span><span>{renderSceneStats?.pplastic_texture_alpha_count ?? '—'}</span></div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>Active rig</span><span>{authoringMap?.camera_rig?.rig_id ?? '—'}</span></div>
	<div class="sync-row"><span>Rig mount height</span><span>{rigMountHeightM.toFixed(2)} m</span></div>
	<div class="sync-row"><span>Ceiling height</span><span>{Number(authoringMap?.settings?.default_wall_height_m ?? 2.4).toFixed(2)} m</span></div>
	<div class="sync-row">
		<label class="footprint-toggle">
			<input type="checkbox" checked={showRoomShell} onchange={(e) => onSetShowRoomShell((e.currentTarget as HTMLInputElement).checked)} />
			Show auto room shell
		</label>
		<span>{roomShell?.shapes?.length ?? 0} shapes</span>
	</div>
	<div class="sync-divider"></div>
	<div class="sync-row"><span>XML file</span><span class="mono">{renderSceneStats?.path ? renderSceneStats.path.split('/').slice(-2).join('/') : 'not generated'}</span></div>
	<div class="sync-row"><span>XML size</span><span>{renderSceneStats?.size_bytes != null ? Math.round(renderSceneStats.size_bytes / 1024) + ' KB' : '—'}</span></div>
	<div class="sync-row"><span>Last sync</span><span class="mono">{renderSceneStats?.modified_at?.slice(0, 19).replace('T', ' ') ?? '—'}</span></div>
	{#if renderSceneStats?.infinigen_import_root}
		<div class="sync-divider"></div>
		<div class="sync-row" class:warn={!renderSceneStats.pbr_baked}>
			<span>Infinigen PBR maps</span>
			<span>{renderSceneStats.pbr_baked ? `baked · rough ${renderSceneStats.pbr_baked_roughness_count ?? 0}/${renderSceneStats.infinigen_unit_count ?? 0}` : 'albedo only'}</span>
		</div>
		{#if renderSceneStats.pbr_baked}
			<div class="sync-row"><span>· normal / metallic</span><span>{renderSceneStats.pbr_baked_normal_count ?? 0} / {renderSceneStats.pbr_baked_metallic_count ?? 0}</span></div>
		{/if}
		{#if renderSceneStats.infinigen_source_blend}
			<div class="sync-actions">
				<button class="button button-subtle" onclick={copyBakeCmd}>{bakeCmdCopied ? 'Copied ✓' : (renderSceneStats.pbr_baked ? 'Re-bake PBR — copy cmd' : 'Bake PBR — copy cmd')}</button>
			</div>
			{#if bakeCmdShown}<pre class="bake-cmd">{bakeCmd}</pre>{/if}
		{/if}
	{/if}
	<div class="sync-actions">
		<button class="button button-subtle" disabled={!refreshEnabled} title={refreshReason} onclick={onRefreshStats}>
			{renderSceneStatsLoading ? 'Loading…' : 'Refresh stats'}
		</button>
	</div>
</section>

<style>
	.rail-section { border-bottom: 1px solid var(--panel-border); padding-bottom: var(--space-3); }
	.rail-title { margin-bottom: var(--space-2); color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: 700; text-transform: uppercase; }
	.sync-inspector { display: grid; gap: 6px; }
	.sync-hint { font-size: var(--font-size-xs, 11px); color: var(--muted, #6b7280); }
	.sync-row { display: flex; justify-content: space-between; gap: 10px; font-size: var(--font-size-xs, 11px); padding: 2px 0; }
	.sync-row.warn { color: var(--danger, #dc2626); font-weight: 600; }
	.sync-row.inj-head { font-weight: 700; opacity: 0.85; margin-top: 2px; }
	.sync-row .mono { font-family: monospace; max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.sync-divider { height: 1px; background: var(--border, #e5e7eb); margin: 4px 0; }
	.sync-actions { display: flex; gap: var(--space-2, 6px); margin-top: var(--space-2, 6px); }
	.footprint-toggle { display: flex; align-items: center; gap: 6px; font-size: var(--font-size-xs, 11px); cursor: pointer; }
	.footprint-toggle input { margin: 0; }
	.bake-cmd { margin: 4px 0 0; padding: 6px; font-family: monospace; font-size: 10px; white-space: pre-wrap; word-break: break-all; background: var(--code-bg, #f3f4f6); border-radius: 4px; }
</style>
