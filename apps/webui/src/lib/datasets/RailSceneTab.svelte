<script lang="ts">
	import { opticalNavEnvmapPreviewUrl } from '$lib/api';

	interface Props {
		sceneId: string;
		projectScenes: any[];
		selectedProjectId: string;
		hasScene: boolean;
		authoringMapDirty: boolean;
		authoringMapText: string;
		annotationText: string;
		authoringMap: any;
		currentScene: any;
		detectedEmitterCount: number;
		enabledEmitterCount: number;
		effectiveRenderReadiness: any;
		mapWidth: number;
		mapHeight: number;
		loading: boolean;
		envmapFiles: any[];
		envmapUploading: boolean;
		onSceneChange: (id: string) => void;
		onSetMapWidth: (value: number) => void;
		onSetMapHeight: (value: number) => void;
		onTranslateLayout: (dx: number, dy: number) => void;
		onNormalizeLayout: () => void;
		onAddScene: () => void;
		onSaveMap: () => void;
		onEnableAllEmitters: () => void;
		onDisableAllEmitters: () => void;
		onUpdateEnvironmentField: (key: string, value: unknown) => void;
		onUpdateSettingsField: (key: string, value: unknown) => void;
		onUploadEnvmap: (input: HTMLInputElement) => void;
		onMarkAuthoringJsonDirty: () => void;
		onAuthoringMapTextChange: (v: string) => void;
		onAnnotationTextChange: (v: string) => void;
		onLoadAnnotation: () => void;
		onSaveAnnotation: () => void;
	}

	let {
		sceneId, projectScenes, selectedProjectId, hasScene,
		authoringMapDirty, authoringMapText, annotationText,
		authoringMap, currentScene, detectedEmitterCount, enabledEmitterCount,
		effectiveRenderReadiness, mapWidth, mapHeight, loading,
		envmapFiles, envmapUploading,
		onSceneChange, onSetMapWidth, onSetMapHeight, onTranslateLayout, onNormalizeLayout,
		onAddScene, onSaveMap, onEnableAllEmitters, onDisableAllEmitters,
		onUpdateEnvironmentField, onUpdateSettingsField, onUploadEnvmap,
		onMarkAuthoringJsonDirty, onAuthoringMapTextChange, onAnnotationTextChange,
		onLoadAnnotation, onSaveAnnotation,
	}: Props = $props();

	function envmapSizeLabel(bytes: unknown): string {
		const n = Number(bytes ?? 0);
		if (!Number.isFinite(n) || n <= 0) return '';
		if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
		return `${Math.max(1, Math.round(n / 1024))} KB`;
	}

	const env = $derived(authoringMap?.environment ?? {});
	const envMode = $derived(env.mode ?? 'constant');
	const envmapRef = $derived(env.envmap_ref ?? '');
	const selectedEnvmap = $derived(envmapFiles.find((f: any) => f.envmap_ref === envmapRef));
	const shellOn = $derived(authoringMap?.settings?.room_shell_enabled ?? true);
	const floorOn = $derived(authoringMap?.settings?.auto_floor_enabled ?? true);
	const ceilingOn = $derived(authoringMap?.settings?.auto_ceiling_enabled ?? shellOn);

	let layoutDx = $state(0);
	let layoutDy = $state(0);
</script>

<section class="rail-section rail-tool-panel">
	<details open>
		<summary class="rail-summary">Scene</summary>
		<div class="map-settings-body rail-settings-body">
			{#if projectScenes.length > 0}
				<label>
					<span>scene</span>
					<select class="scene-select" value={sceneId} onchange={(e) => onSceneChange(e.currentTarget.value)}>
						{#each projectScenes as item}
							<option value={item.scene_id}>{item.scene_id}</option>
						{/each}
					</select>
				</label>
			{/if}
			<label><span>scene_id</span><input value={sceneId} oninput={(e) => onSceneChange((e.currentTarget as HTMLInputElement).value)} /></label>
			<div class="geometry-grid">
				<label><span>map W (m)</span><input type="number" min="1" max="2000" step="1" value={mapWidth} oninput={(e) => onSetMapWidth(Number((e.currentTarget as HTMLInputElement).value))} /></label>
				<label><span>map H (m)</span><input type="number" min="1" max="2000" step="1" value={mapHeight} oninput={(e) => onSetMapHeight(Number((e.currentTarget as HTMLInputElement).value))} /></label>
			</div>
			{#if hasScene}
				<div class="translate-layout">
					<span class="translate-layout-title">Translate layout (m)</span>
					<div class="geometry-grid">
						<label><span>Δx (east+)</span><input type="number" step="0.1" bind:value={layoutDx} /></label>
						<label><span>Δy (north+)</span><input type="number" step="0.1" bind:value={layoutDy} /></label>
					</div>
					<div class="action-row">
						<button class="button button-subtle" disabled={loading || (!layoutDx && !layoutDy)} onclick={() => { onTranslateLayout(Number(layoutDx) || 0, Number(layoutDy) || 0); layoutDx = 0; layoutDy = 0; }}>Apply shift</button>
						<button class="button button-subtle" disabled={loading} onclick={() => onNormalizeLayout()}>Normalize to ≥0</button>
					</div>
					<span class="translate-layout-sub">Shifts every object &amp; region together (e.g. bring a negative-coord room back to the origin). Then Save Map.</span>
				</div>
			{/if}
			<div class="action-row">
				<button class="button button-subtle" disabled={!selectedProjectId || loading} onclick={onAddScene}>Add Scene</button>
				<button class="button button-primary" disabled={!selectedProjectId || !hasScene || loading} onclick={onSaveMap}>
					{authoringMapDirty ? '● ' : ''}Save Map
				</button>
			</div>
			{#if authoringMapDirty}<p class="inline-hint">Unsaved changes.</p>{/if}
			{#if currentScene?.sync_status}
				{@const _ss = currentScene.sync_status}
				{@const _rs = _ss.render_scene_status ?? _ss.render_scene ?? 'pending'}
				<div class="sync-card">
					<div class="panel-label">Sync</div>
					<div class:ready={_ss.render_scene === 'synced'}>
						Render {_ss.render_scene ?? 'pending'}
						{#if _rs && _rs !== _ss.render_scene}<span class="sync-sub"> · {_rs}</span>{/if}
					</div>
					{#if _ss.message}<div class="sync-message">{_ss.message}</div>{/if}
					<div class:ready={_ss.isaac_stage === 'synced'}>Isaac {_ss.isaac_stage ?? 'pending'}</div>
					{#if _ss.annotation_stale}<div class="sync-stale">⚠ scene_annotation.json is stale (re-sync recommended)</div>{/if}
					{#if _ss.traversable_map_stale}<div class="sync-stale">⚠ traversable_map is stale</div>{/if}
					{#if _ss.viewpoint_graph_stale}<div class="sync-stale">⚠ viewpoint_graph is stale</div>{/if}
				</div>
			{/if}

			{#if detectedEmitterCount > 0}
				<div class="emitter-bulk-card">
					<div class="panel-label">🔆 Light fixtures</div>
					<div class="emitter-bulk-row">
						<span>{enabledEmitterCount}/{detectedEmitterCount} enabled</span>
						<button class="button button-subtle" disabled={enabledEmitterCount >= detectedEmitterCount} onclick={onEnableAllEmitters}>Enable all</button>
						{#if enabledEmitterCount > 0}
							<button class="button button-subtle" onclick={onDisableAllEmitters}>Disable all</button>
						{/if}
					</div>
				</div>
			{/if}

			<details open class="render-ready-panel">
				<summary>Environment / Render readiness</summary>

				<!-- Environment panel (inlined from snippet) -->
				<div class="env-section">
					<div class="env-section-title">Lighting source</div>
					<div class="env-radio-row">
						<label class="env-radio"><input type="radio" name="env-mode" value="constant" checked={envMode === 'constant'} onchange={() => onUpdateEnvironmentField('mode', 'constant')} /> Constant</label>
						<label class="env-radio"><input type="radio" name="env-mode" value="envmap" checked={envMode === 'envmap'} onchange={() => onUpdateEnvironmentField('mode', 'envmap')} /> Envmap</label>
					</div>
					{#if envMode === 'constant'}
						<div class="env-fields-grid">
							<label><span>RGB</span><input value={(env.radiance ?? [0.8, 0.8, 0.85]).join(', ')} oninput={(e) => onUpdateEnvironmentField('radiance', (e.currentTarget as HTMLInputElement).value)} /></label>
							<label><span>Intensity</span><input type="number" min="0" step="0.1" value={env.intensity ?? 1} oninput={(e) => onUpdateEnvironmentField('intensity', (e.currentTarget as HTMLInputElement).value)} /></label>
						</div>
					{:else}
						<div class="env-envmap-row">
							<select class="env-envmap-select" value={envmapRef} onchange={(e) => onUpdateEnvironmentField('envmap_ref', (e.currentTarget as HTMLSelectElement).value || null)}>
								<option value="">— Select uploaded envmap —</option>
								{#each envmapFiles as item}
									<option value={item.envmap_ref}>{item.filename}{#if item.size_bytes} · {envmapSizeLabel(item.size_bytes)}{/if}</option>
								{/each}
							</select>
							<label class="env-upload-button">
								<input type="file" accept=".exr,.hdr,.png,.jpg,.jpeg,image/png,image/jpeg" disabled={envmapUploading || !selectedProjectId || !hasScene} onchange={(e) => onUploadEnvmap(e.currentTarget as HTMLInputElement)} />
								<span>{envmapUploading ? 'Uploading…' : 'Upload new'}</span>
							</label>
						</div>
						{#if selectedEnvmap}
							<div class="env-envmap-preview">
								{#if selectedEnvmap.previewable && selectedProjectId && sceneId}
									<img src={opticalNavEnvmapPreviewUrl(selectedProjectId, sceneId, selectedEnvmap.filename)} alt={selectedEnvmap.filename} />
								{:else}
									<div class="env-envmap-placeholder">EXR/HDR preview not available in browser</div>
								{/if}
								<div class="env-envmap-meta">
									<div class="env-envmap-filename" title={selectedEnvmap.envmap_ref}>{selectedEnvmap.filename}</div>
									<div class="env-envmap-sub">{envmapSizeLabel(selectedEnvmap.size_bytes)}</div>
								</div>
							</div>
						{:else if envmapRef}
							<div class="hint-row">⚠ envmap_ref is set but not in the uploaded list. Re-upload or fix the path.</div>
						{/if}
						<div class="env-fields-grid">
							<label><span>Intensity</span><input type="number" min="0" step="0.1" value={env.intensity ?? 1} oninput={(e) => onUpdateEnvironmentField('intensity', (e.currentTarget as HTMLInputElement).value)} /></label>
							<label><span>Rotation°</span><input type="number" step="1" value={env.rotation_deg ?? 0} oninput={(e) => onUpdateEnvironmentField('rotation_deg', (e.currentTarget as HTMLInputElement).value)} /></label>
						</div>
					{/if}
				</div>
				<div class="env-section">
					<div class="env-section-title">Scene enclosure</div>
					<label class="inline-check enclosure-toggle">
						<input type="checkbox" checked={floorOn} onchange={(e) => onUpdateSettingsField('auto_floor_enabled', (e.currentTarget as HTMLInputElement).checked)} />
						<span><strong>Auto floor</strong><span class="env-toggle-sub">Keep a base floor visible for editing and rendering.</span></span>
					</label>
					<label class="inline-check enclosure-toggle">
						<input type="checkbox" checked={shellOn} onchange={(e) => onUpdateSettingsField('room_shell_enabled', (e.currentTarget as HTMLInputElement).checked)} />
						<span><strong>Walls &amp; ceiling</strong><span class="env-toggle-sub">Add simple boundary walls and ceiling around the map.</span></span>
					</label>
					{#if !shellOn}
					<label class="inline-check enclosure-toggle" style="margin-left:18px">
						<input type="checkbox" checked={ceilingOn} onchange={(e) => onUpdateSettingsField('auto_ceiling_enabled', (e.currentTarget as HTMLInputElement).checked)} />
						<span><strong>Ceiling only</strong><span class="env-toggle-sub">Keep the ceiling slab while walls are off (envmap lights through sides).</span></span>
					</label>
					{/if}
					{#if envMode === 'envmap' && shellOn}
						<div class="hint-row">💡 Turn off Walls &amp; ceiling so the envmap can light the scene and show as the background.</div>
					{:else if !shellOn && !floorOn && !ceilingOn && envMode === 'constant'}
						<div class="hint-row">⚠ Floor + walls/ceiling both off under constant lighting → scene will render almost empty. Switch to envmap.</div>
					{:else if !shellOn && envMode === 'constant' && !ceilingOn}
						<div class="hint-row">⚠ Walls/ceiling off + constant lighting → flat. Consider switching to envmap.</div>
					{/if}
				</div>

				<div class="render-profile-row">
					<span class="chip-ok">GPU-only</span>
					<span class="chip-ok">Scene reuse</span>
					<span class="chip-dim">Texture max{effectiveRenderReadiness?.texture_profile ?? currentScene?.render_readiness?.texture_profile ?? 1024}</span>
				</div>
				{#if effectiveRenderReadiness}
					{@const _errs = effectiveRenderReadiness.errors ?? []}
					{@const _warns = effectiveRenderReadiness.warnings ?? []}
					<div class="export-validation" class:validation-ok={effectiveRenderReadiness.ok} class:validation-fail={!effectiveRenderReadiness.ok}>
						Render readiness: {effectiveRenderReadiness.status ?? (effectiveRenderReadiness.ok ? 'ready' : 'blocked')}
						{#if _errs.length}<span class="val-errors"> · {_errs.length} error{_errs.length === 1 ? '' : 's'}</span>{/if}
						{#if _warns.length}<span class="val-warnings"> · {_warns.length} warning{_warns.length === 1 ? '' : 's'}</span>{/if}
					</div>
					{#if _errs.length}
						<div class="readiness-errors">
							{#each _errs as err}
								<div class="readiness-error-item">
									<span class="readiness-error-label">{err.label ?? err.key}:</span>
									<span class="readiness-error-msg">{err.message}</span>
								</div>
							{/each}
						</div>
					{/if}
					{#if _warns.length}
						<div class="readiness-warnings">
							{#each _warns as w}
								<div class="readiness-warning-item">
									<span class="readiness-warning-label">⚠ {w.label ?? w.key}:</span>
									<span class="readiness-warning-msg">{w.message}</span>
								</div>
							{/each}
						</div>
					{/if}
				{/if}
			</details>
			<details>
				<summary>authoring_map.json</summary>
				<textarea class="code-editor small" value={authoringMapText} oninput={(e) => { onAuthoringMapTextChange((e.currentTarget as HTMLTextAreaElement).value); onMarkAuthoringJsonDirty(); }} placeholder="authoring_map.json"></textarea>
			</details>
			<details>
				<summary>scene_annotation.json</summary>
				<div class="action-row mt-2">
					<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || loading} onclick={onLoadAnnotation}>Load</button>
					<button class="button button-subtle" disabled={!selectedProjectId || !hasScene || loading} onclick={onSaveAnnotation}>Validate</button>
				</div>
				<textarea class="code-editor small" value={annotationText} oninput={(e) => onAnnotationTextChange((e.currentTarget as HTMLTextAreaElement).value)} placeholder="scene_annotation.json"></textarea>
			</details>
		</div>
	</details>
</section>

<style>
	.sync-card {
			display: grid;
			gap: var(--space-2);
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-md);
			background: var(--surface-1);
			padding: var(--space-3);
		}

	.sync-card div:not(.panel-label) {
			display: flex;
			justify-content: space-between;
			gap: var(--space-2);
			color: var(--tool-hazard);
			font-size: var(--font-size-sm);
		}

	.sync-card div.ready {
			color: var(--tool-traversable);
		}

	.sync-card p {
			margin: 0;
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
		}

	.sync-card div.sync-message {
			display: block;
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
			line-height: 1.4;
			padding: 2px 0 0;
		}
	.sync-card div.sync-stale {
			display: block;
			color: #92400e;
			font-size: var(--font-size-xs);
			line-height: 1.4;
			padding: 1px 0 0;
		}
	.sync-card .sync-sub {
			color: var(--muted-strong);
			font-weight: 400;
		}

	.emitter-bulk-card {
			display: grid;
			gap: var(--space-2);
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-md);
			background: var(--surface-1);
			padding: var(--space-3);
		}

	.rail-summary {
			cursor: pointer;
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
			font-weight: 800;
			list-style: none;
			text-transform: uppercase;
		}

	.rail-summary::-webkit-details-marker { display: none; }

	.rail-settings-body {
			width: auto;
			max-height: none;
			overflow: visible;
			border: 0;
			border-radius: 0;
			background: transparent;
			box-shadow: none;
			padding: var(--space-2) 0 0;
		}

	.readiness-errors { margin-top: 4px; display: flex; flex-direction: column; gap: 3px; }
	.readiness-warnings { margin-top: 4px; display: flex; flex-direction: column; gap: 3px; }
	.readiness-warning-item { font-size: 11px; color: #92400e; line-height: 1.4; }
	.readiness-warning-label { font-weight: 600; margin-right: 4px; }
	.readiness-warning-msg { color: #7c2d12; }
	.val-warnings { color: #92400e; }

	.readiness-error-item { font-size: 11px; color: var(--danger); line-height: 1.4; }

	.readiness-error-label { font-weight: 600; margin-right: 4px; }

	.readiness-error-msg { color: #7f1d1d; }

	.map-settings-body {
			margin-top: 4px;
			width: 280px;
			max-height: 60vh;
			overflow-y: auto;
			background: rgba(255, 255, 255, 0.97);
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-md);
			padding: var(--space-3);
			display: flex;
			flex-direction: column;
			gap: var(--space-2);
			box-shadow: 0 4px 12px rgba(0,0,0,0.1);
		}

	.rail-settings-body {
			width: auto;
			max-height: none;
			overflow: visible;
			border: 0;
			border-radius: 0;
			background: transparent;
			box-shadow: none;
			padding: var(--space-2) 0 0;
		}

	.hint-row { font-size: 11px; color: var(--muted-strong); background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px 8px; margin: 4px 0; }

	.env-section { padding: 8px 0; border-bottom: 1px solid #f1f5f9; }

	.env-section:last-child { border-bottom: none; }

	.env-section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--muted-strong); letter-spacing: 0.04em; margin-bottom: 6px; }

	.env-radio-row { display: flex; gap: 16px; margin-bottom: 8px; }

	.env-radio { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }

	.env-fields-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }

	.env-fields-grid label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }

	.env-fields-grid label span { color: var(--muted-strong); font-size: 11px; }

	.env-envmap-row { display: flex; gap: 8px; margin-bottom: 8px; }

	.env-envmap-select { flex: 1; min-width: 0; }

	.env-upload-button { position: relative; display: inline-flex; align-items: center; padding: 4px 10px; background: #e2e8f0; border-radius: 6px; font-size: 12px; cursor: pointer; white-space: nowrap; }

	.env-upload-button input[type="file"] { position: absolute; inset: 0; opacity: 0; cursor: pointer; }

	.env-envmap-preview { display: flex; gap: 8px; align-items: center; padding: 6px; background: #f8fafc; border-radius: 6px; margin-bottom: 8px; }

	.env-envmap-preview img { width: 120px; height: 60px; object-fit: cover; border-radius: 4px; background: #1e293b; }

	.env-envmap-placeholder { width: 120px; height: 60px; display: flex; align-items: center; justify-content: center; font-size: 10px; color: var(--muted-strong); background: #e2e8f0; border-radius: 4px; text-align: center; padding: 4px; }

	.env-envmap-meta { flex: 1; min-width: 0; }

	.env-envmap-filename { font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	.env-envmap-sub { font-size: 11px; color: var(--muted-strong); }

	.enclosure-toggle { display: flex; align-items: flex-start; gap: 8px; padding: 6px 0; }

	.enclosure-toggle > span { display: flex; flex-direction: column; gap: 1px; }

	.enclosure-toggle strong { font-size: 12px; font-weight: 600; color: #1e293b; }

	.env-toggle-sub { font-size: 11px; color: var(--muted-strong); font-weight: 400; }
	.translate-layout { display: flex; flex-direction: column; gap: var(--space-1, 4px); margin-top: var(--space-2, 8px); padding-top: var(--space-2, 8px); border-top: 1px solid var(--border-subtle, rgba(148,163,184,0.25)); }
	.translate-layout-title { font-size: 12px; font-weight: 600; color: var(--muted-strong); }
	.translate-layout-sub { font-size: 11px; color: var(--muted-strong); font-weight: 400; }
</style>
