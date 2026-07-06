<script lang="ts">
	// Editor load/sync status dashboard. Turns the opaque "Loading episodes…" pill
	// into an expandable checklist so the user can see exactly which resources are
	// loaded / pending / failed (and thus what is blocking Save Map or Render), plus
	// the live render-scene sync progress (object/mesh cache) that otherwise gets
	// buried after a Save Map + browser refresh.
	type ResourceState = 'idle' | 'loading' | 'ready' | 'error';

	let {
		resourceStatus = {} as Record<string, ResourceState>,
		resourceError = {} as Record<string, string>,
		syncStatus = null as any,
		// Live render-scene sync progress (mesh cache / IOR injection etc.) — the same
		// stream the in-canvas chip shows. Feeding it here keeps the bottom dashboard
		// live during Save Map instead of frozen at the persisted sync_status.
		syncProgress = null as { processed: number; total: number; label: string; stage: string } | null,
		syncRunning = false as boolean,
		syncStageLabel = '' as string,
		onRetry = undefined as ((key: string) => void) | undefined,
		onRetryAll = undefined as (() => void) | undefined,
	} = $props();

	// Resource → human label, grouped by concern. Keys must match +page ResourceKey.
	const GROUPS: { title: string; items: { key: string; label: string }[] }[] = [
		{ title: 'Core', items: [
			{ key: 'project', label: 'Project' },
			{ key: 'authoringMap', label: 'Scene map' },
			{ key: 'graph', label: 'Viewpoint graph' },
			{ key: 'episodes', label: 'Episodes' },
			{ key: 'renderReadiness', label: 'Render readiness' },
			{ key: 'renderConfig', label: 'Render config' },
		] },
		{ title: 'Assets', items: [
			{ key: 'mapAssets', label: 'Map assets' },
			{ key: 'envmaps', label: 'Envmaps' },
			{ key: 'perturbation', label: 'Optical perturbation' },
		] },
		{ title: 'Render cache', items: [
			{ key: 'renderSceneStats', label: 'Render stats' },
			{ key: 'xmlSceneIndex', label: 'XML scene index' },
			{ key: 'materializationAudit', label: 'Material audit' },
			{ key: 'roomShell', label: 'Room shell' },
		] },
	];
	const ALL_KEYS = GROUPS.flatMap((g) => g.items.map((i) => i.key));

	const st = (k: string): ResourceState => (resourceStatus?.[k] ?? 'idle');
	const counts = $derived.by(() => {
		let loading = 0, ready = 0, error = 0, total = 0;
		for (const k of ALL_KEYS) {
			const s = st(k);
			if (s === 'idle') continue;
			total++;
			if (s === 'loading') loading++;
			else if (s === 'ready') ready++;
			else if (s === 'error') error++;
		}
		return { loading, ready, error, total };
	});

	// Render-scene sync (object/mesh cache). The live `syncRunning`/`syncProgress`
	// stream is authoritative while a Save Map / sync is in flight; the persisted
	// `sync_status` is the fallback at rest.
	const syncState = $derived(String(syncStatus?.render_scene_status ?? syncStatus?.render_scene ?? ''));
	// A finished sync writes render_scene:"synced" but older daemons left the
	// render_scene_status flag stuck at "syncing" — treat an at-rest completed sync
	// as done so the progress banner clears without re-syncing (live syncRunning still
	// wins while a Save Map is actually in flight).
	const syncDone = $derived(
		syncStatus?.render_scene === 'synced' || syncStatus?.render_scene_status === 'synced',
	);
	const syncing = $derived(Boolean(syncRunning) || (syncState === 'syncing' && !syncDone));
	const syncMessage = $derived(String(syncStatus?.message ?? ''));
	// Live "<stage> · <processed>/<total> · <label>" line built from syncProgress.
	const syncLive = $derived.by(() => {
		if (!syncRunning || !syncProgress) return '';
		const p = syncProgress;
		const base = syncStageLabel || p.stage || 'syncing';
		const frac = p.total ? ` · ${p.processed}/${p.total}` : '';
		const lbl = p.label ? ` · ${p.label}` : '';
		return `${base}${frac}${lbl}`;
	});
	const syncPct = $derived(
		syncRunning && syncProgress && syncProgress.total > 0
			? Math.min(100, Math.round((syncProgress.processed / syncProgress.total) * 100))
			: null
	);

	const active = $derived(counts.loading > 0 || syncing);
	const hasError = $derived(counts.error > 0);

	// "Done!" moment: linger briefly after the last activity clears.
	let doneLinger = $state(false);
	let _wasActive = $state(false);
	let _timer: ReturnType<typeof setTimeout> | null = null;
	$effect(() => {
		const a = active;
		if (a) { _wasActive = true; doneLinger = false; if (_timer) { clearTimeout(_timer); _timer = null; } }
		else if (_wasActive) {
			_wasActive = false;
			if (!hasError) {
				doneLinger = true;
				_timer = setTimeout(() => { doneLinger = false; _timer = null; }, 3500);
			}
		}
	});

	let open = $state(false);
	const visible = $derived(active || hasError || doneLinger || open);

	const summary = $derived.by(() => {
		if (hasError) return `${counts.error} failed · ${counts.ready}/${counts.total} ready`;
		if (counts.loading) return `Loading… ${counts.ready}/${counts.total} ready${syncing ? ' · sync' : ''}`;
		if (syncing) return syncLive ? `Sync · ${syncLive}` : 'Render sync running…';
		if (doneLinger) return 'All ready';
		return `${counts.ready}/${counts.total} ready`;
	});

	function icon(s: ResourceState): string {
		return s === 'ready' ? '✓' : s === 'error' ? '✕' : s === 'loading' ? '' : '·';
	}
</script>

{#if visible}
	<div class="status-dash" class:has-error={hasError} class:is-done={doneLinger && !active && !hasError}>
		<div class="status-dash-head">
			<button type="button" class="sd-toggle" onclick={() => (open = !open)} aria-expanded={open}>
				{#if hasError}
					<span class="sd-dot error" aria-hidden="true"></span>
				{:else if active}
					<span class="loading-spinner" aria-hidden="true"></span>
				{:else}
					<span class="sd-dot ready" aria-hidden="true"></span>
				{/if}
				<span class="sd-summary">{doneLinger && !active && !hasError ? '✓ ' : ''}{summary}</span>
				<span class="sd-chev">{open ? '▾' : '▸'}</span>
			</button>
			{#if hasError && onRetryAll}
				<button type="button" class="sd-retry-all" onclick={() => onRetryAll?.()}>Retry all</button>
			{/if}
		</div>

		{#if open}
			<div class="status-dash-body">
				{#each GROUPS as g}
					<div class="sd-group">{g.title}</div>
					{#each g.items as it}
						{@const s = st(it.key)}
						<div class="sd-row sd-{s}">
							<span class="sd-icon">
								{#if s === 'loading'}<span class="loading-spinner sm" aria-hidden="true"></span>{:else}{icon(s)}{/if}
							</span>
							<span class="sd-label">{it.label}</span>
							{#if s === 'error'}
								<span class="sd-msg">{resourceError?.[it.key] ?? 'failed'}</span>
								{#if onRetry}<button type="button" class="sd-retry" onclick={() => onRetry?.(it.key)}>Retry</button>{/if}
							{:else if s === 'idle'}
								<span class="sd-msg dim">—</span>
							{/if}
						</div>
					{/each}
				{/each}

				{#if syncStatus || syncRunning}
					<div class="sd-group">Render-scene sync (object cache · IOR)</div>
					<div class="sd-row" class:sd-loading={syncing} class:sd-ready={!syncRunning && syncDone}>
						<span class="sd-icon">
							{#if syncing}<span class="loading-spinner sm" aria-hidden="true"></span>{:else}{syncDone ? '✓' : '·'}{/if}
						</span>
						<span class="sd-label">Render scene</span>
						<span class="sd-msg">{syncRunning ? (syncLive || 'syncing…') : (syncDone ? 'synced' : (syncState === 'syncing' ? (syncMessage || 'syncing…') : (syncStatus?.render_scene ?? 'pending')))}</span>
					</div>
					{#if syncPct !== null}
						<div class="sd-progress"><div class="sd-progress-fill" style={`width:${syncPct}%`}></div></div>
					{/if}
					{#if syncStatus?.isaac_stage}
						<div class="sd-row" class:sd-ready={syncStatus.isaac_stage === 'synced'}>
							<span class="sd-icon">{syncStatus.isaac_stage === 'synced' ? '✓' : '·'}</span>
							<span class="sd-label">Isaac stage</span>
							<span class="sd-msg">{syncStatus.isaac_stage}</span>
						</div>
					{/if}
				{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	.status-dash {
		position: relative;
		min-width: 240px;
		max-width: 420px;
		background: var(--surface-1, #fff);
		border: 1px solid var(--border, #d9dde3);
		border-radius: 8px;
		box-shadow: 0 4px 16px rgba(15, 23, 42, 0.12);
		font-size: 12px;
		overflow: hidden;
	}
	.status-dash.has-error { border-color: #dc2626; }
	.status-dash.is-done { border-color: #16a34a; }
	.status-dash-head { display: flex; align-items: center; gap: 6px; padding-right: 8px; }
	.sd-toggle {
		display: flex; align-items: center; gap: 8px; flex: 1;
		padding: 7px 10px; border: 0; background: transparent;
		cursor: pointer; text-align: left; color: var(--text, #1f2937);
	}
	.sd-toggle:hover { background: var(--surface-2, #f1f5f9); }
	.sd-summary { flex: 1; font-weight: 600; }
	.sd-chev { color: var(--text-dim, #94a3b8); }
	.sd-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
	.sd-dot.ready { background: #16a34a; }
	.sd-dot.error { background: #dc2626; }
	.status-dash-body { padding: 4px 0 8px; border-top: 1px solid var(--border, #e5e7eb); max-height: 320px; overflow-y: auto; }
	.sd-group {
		padding: 6px 10px 2px; font-size: 10px; font-weight: 700;
		letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-dim, #94a3b8);
	}
	.sd-row { display: flex; align-items: center; gap: 8px; padding: 3px 10px; }
	.sd-icon { width: 14px; text-align: center; flex: none; color: var(--text-dim, #94a3b8); }
	.sd-row.sd-ready .sd-icon { color: #16a34a; }
	.sd-row.sd-error .sd-icon { color: #dc2626; }
	.sd-label { flex: none; min-width: 110px; color: var(--text, #1f2937); }
	.sd-msg { flex: 1; color: var(--text-dim, #64748b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.sd-row.sd-error .sd-msg { color: #dc2626; }
	.sd-msg.dim { opacity: 0.5; }
	.sd-progress { height: 4px; margin: 1px 10px 4px; background: var(--surface-2, #e5e7eb); border-radius: 3px; overflow: hidden; }
	.sd-progress-fill { height: 100%; background: var(--brand, #2f7bf6); border-radius: 3px; transition: width 0.15s linear; }
	.loading-spinner.sm { width: 11px; height: 11px; border-width: 2px; }
	.sd-retry, .sd-retry-all {
		flex: none; border: 1px solid var(--border, #d9dde3); background: var(--surface-1, #fff);
		border-radius: 5px; padding: 1px 7px; font-size: 11px; cursor: pointer; color: var(--text, #1f2937);
	}
	.sd-retry:hover, .sd-retry-all:hover { background: var(--surface-2, #f1f5f9); }
	.sd-retry-all { color: #dc2626; border-color: #fca5a5; }
</style>
