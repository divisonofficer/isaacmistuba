<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { lang } from '$lib/stores/lang';
	import { healthStore } from '$lib/stores/health';
	import {
		getScene, getSceneCaptures, materialPresets, materialLibrary,
		getSceneRenderOptions, saveSceneRenderOptions,
		isaacCommand, listJobs, smokeRender,
		materialPreviewUrl, applyMeasuredMaterial
	} from '$lib/api';

	const sceneId = $derived(page.params.id ?? '');
	const L = $derived($lang);

	type Preset = { bsdf_type: string; category: string; title_en: string; title_kr: string; description_en: string; description_kr: string; swatch?: string };
	type MeasuredMat = { dataset_id: string; material_id: string; label_en: string; label_kr?: string };

	let scene: Record<string, unknown> | null = $state(null);
	let captures: Record<string, unknown>[] = $state([]);
	let presets: Preset[] = $state([]);
	let measuredMats: MeasuredMat[] = $state([]);
	let recentJobs: Record<string, unknown>[] = $state([]);

	let loading = $state(true);
	let activeTab = $state('workspace');
	let matFilter = $state('all');
	let matSearch = $state('');
	let cmdPending = $state<string | null>(null);
	let cmdMsg = $state('');

	// Render options form state
	let roSpp = $state(64);
	let roWidth = $state(1280);
	let roHeight = $state(720);
	let roUpscale = $state('none');
	let roModalities = $state<Set<string>>(new Set(['rgb']));

	let refreshTimer: ReturnType<typeof setInterval>;

	const floorplanUrl = $derived(`/api/scenes/${sceneId}/floorplan`);

	async function loadData() {
		try {
			const [scRes, capRes, presRes, libRes, jobsRes] = await Promise.all([
				getScene(sceneId).catch(() => null),
				getSceneCaptures(sceneId).then(r => r.captures ?? []).catch(() => []),
				materialPresets().then(r => r.presets ?? []).catch(() => []),
				materialLibrary().then(r => r.materials ?? []).catch(() => []),
				listJobs(10).then(r => r.jobs ?? []).catch(() => [])
			]);
			scene = scRes;
			captures = capRes;
			presets = presRes;
			measuredMats = libRes;
			recentJobs = jobsRes;

			try {
				const ro = await getSceneRenderOptions(sceneId);
				if (ro) {
					roSpp = ro.spp ?? 64;
					roWidth = ro.width ?? 1280;
					roHeight = ro.height ?? 720;
					roUpscale = ro.upscale ?? 'none';
					roModalities = new Set(ro.modalities ?? ['rgb']);
				}
			} catch {}
		} catch {}
		loading = false;
	}

	async function refreshJobs() {
		try {
			recentJobs = await listJobs(10).then(r => r.jobs ?? []);
		} catch {}
	}

	onMount(async () => {
		await loadData();
		refreshTimer = setInterval(refreshJobs, 4000);
	});
	onDestroy(() => clearInterval(refreshTimer));

	async function sendCommand(cmd: string) {
		if (cmdPending) return;
		cmdPending = cmd;
		cmdMsg = '';
		try {
			await isaacCommand(cmd, sceneId as string);
			cmdMsg = L === 'kr' ? `${cmd} 전송됨` : `${cmd} sent`;
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally {
			cmdPending = null;
		}
	}

	async function handleSmokeRender() {
		if (cmdPending) return;
		cmdPending = 'smoke';
		cmdMsg = '';
		try {
			await smokeRender(sceneId as string);
			cmdMsg = L === 'kr' ? '스모크 렌더 전송됨' : 'Smoke render queued';
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally {
			cmdPending = null;
		}
	}

	async function saveRenderOptions() {
		try {
			await saveSceneRenderOptions(sceneId as string, {
				spp: roSpp, width: roWidth, height: roHeight,
				upscale: roUpscale, modalities: Array.from(roModalities)
			});
			cmdMsg = L === 'kr' ? '저장됨' : 'Saved';
		} catch {}
	}

	function toggleModality(mod: string) {
		const s = new Set(roModalities);
		if (s.has(mod)) s.delete(mod); else s.add(mod);
		roModalities = s;
	}

	async function applyPreset(preset: Preset) {
		try {
			await applyMeasuredMaterial(sceneId as string, { bsdf_type: preset.bsdf_type });
			cmdMsg = L === 'kr' ? `재질 적용: ${preset.title_kr || preset.title_en}` : `Applied: ${preset.title_en}`;
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		}
	}

	const filteredPresets = $derived(
		presets.filter(p => {
			const matchCat = matFilter === 'all' || p.category === matFilter;
			const q = matSearch.toLowerCase();
			const matchQ = !q || p.title_en.toLowerCase().includes(q) || (p.title_kr ?? '').toLowerCase().includes(q);
			return matchCat && matchQ;
		})
	);

	function statusClass(s: string) {
		if (s === 'succeeded') return 'badge-succeeded';
		if (s === 'failed') return 'badge-failed';
		if (s === 'running') return 'badge-running';
		return 'badge-queued';
	}

	function ago(ts: string) {
		if (!ts) return '—';
		const s = Math.round((Date.now() - new Date(ts).getTime()) / 1000);
		if (s < 60) return `${s}s ago`;
		if (s < 3600) return `${Math.round(s / 60)}m ago`;
		return `${Math.round(s / 3600)}h ago`;
	}

	const MODALITY_GROUPS = [
		{ label_en: 'Core', label_kr: '기본', mods: ['rgb', 'depth', 'albedo', 'sensor_depth_approx'] },
		{ label_en: 'Decomposition', label_kr: '분해', mods: ['direct_light_map', 'indirect_light_map', 'diffuse_map', 'specular_map'] },
		{ label_en: 'Polarization', label_kr: '편광', mods: ['polar_rgb_preview', 'dop', 'aolp', 's1', 's2'], note: 'polarized_cuda_mono variant 필요' },
		{ label_en: 'Active NIR', label_kr: 'Active NIR', mods: ['active_nir_intensity'] }
	];

	const isaacConnected = $derived($healthStore?.isaac_connected ?? false);
	const workerBusy = $derived($healthStore?.worker_state === 'running');
</script>

{#if loading}
	<div class="muted text-sm mt-4">{L === 'kr' ? '로딩 중…' : 'Loading…'}</div>
{:else if !scene}
	<div class="empty-state mt-6">{L === 'kr' ? '씬을 찾을 수 없음:' : 'Scene not found:'} {sceneId}</div>
{:else}
	{@const s = scene}

	<!-- Isaac Control Bar -->
	<div class="panel mt-4" style="padding:0.75rem 1rem">
		<div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap">
			<div style="display:flex;align-items:center;gap:0.4rem;margin-right:0.25rem">
				<span class="hsi-state-dot {isaacConnected ? 'hsi-dot-ok' : 'hsi-dot-idle'}" style="width:0.55rem;height:0.55rem"></span>
				<span class="text-xs muted">{isaacConnected ? (L === 'kr' ? 'Isaac 연결됨' : 'Isaac connected') : (L === 'kr' ? 'Isaac 미연결' : 'Isaac disconnected')}</span>
			</div>
			<div style="display:flex;gap:0.5rem;flex-wrap:wrap">
				<button class="button button-subtle text-xs" onclick={() => sendCommand('load_scene')} disabled={!!cmdPending}>
					{cmdPending === 'load_scene' ? '…' : (L === 'kr' ? '불러오기' : 'Load')}
				</button>
				<button class="button button-subtle text-xs" onclick={() => sendCommand('prepare_render_ready')} disabled={!!cmdPending}>
					{cmdPending === 'prepare_render_ready' ? '…' : (L === 'kr' ? '준비' : 'Prepare')}
				</button>
				<button class="button button-subtle text-xs" onclick={() => sendCommand('connect_session')} disabled={!!cmdPending}>
					{cmdPending === 'connect_session' ? '…' : (L === 'kr' ? '연결' : 'Connect')}
				</button>
				<button class="button button-subtle text-xs" onclick={() => sendCommand('sync_session')} disabled={!!cmdPending}>
					{cmdPending === 'sync_session' ? '…' : (L === 'kr' ? '동기화' : 'Sync')}
				</button>
				<button class="button button-primary text-xs" onclick={() => sendCommand('render_current_view')} disabled={!!cmdPending || workerBusy}>
					{cmdPending === 'render_current_view' ? '…' : (L === 'kr' ? '렌더' : 'Render')}
				</button>
				<button class="button button-subtle text-xs" onclick={handleSmokeRender} disabled={!!cmdPending}>
					{cmdPending === 'smoke' ? '…' : '🧪 Smoke'}
				</button>
			</div>
			{#if cmdMsg}
				<span class="text-xs muted">{cmdMsg}</span>
			{/if}
		</div>
	</div>

	<!-- Summary Cards -->
	<div class="scene-summary-grid mt-4">
		{#each [
			{ label: L === 'kr' ? '카메라' : 'Cameras', val: s.camera_count ?? 0 },
			{ label: L === 'kr' ? '메시' : 'Meshes', val: s.mesh_count ?? 0 },
			{ label: L === 'kr' ? '재질' : 'Materials', val: s.material_count ?? 0 },
			{ label: L === 'kr' ? '캡처' : 'Captures', val: captures.length }
		] as card}
			<div class="scene-summary-card">
				<div class="scene-summary-val">{card.val}</div>
				<div class="scene-summary-label">{card.label}</div>
			</div>
		{/each}
	</div>

	<!-- Scene Health Chips -->
	<div class="scene-health-chipbar mt-3">
		<span class="health-chip health-chip-{s.usd_stage_path ? 'ok' : 'err'}" title={String(s.usd_stage_path ?? 'Not registered')}>
			{s.usd_stage_path ? '✅' : '❌'} USD
		</span>
		<span class="health-chip health-chip-{s.mitsuba_scene_exists ? 'ok' : 'warn'}">
			{s.mitsuba_scene_exists ? '✅' : '⚠'} XML
		</span>
		<span class="health-chip health-chip-{s.render_ready ? 'ok' : 'warn'}">
			{s.render_ready ? '✅' : '⚠'} {L === 'kr' ? '렌더 준비' : 'Render Ready'}
		</span>
		{#if s.texture_cache_status}
			<span class="health-chip health-chip-{s.texture_cache_status === 'ready' ? 'ok' : 'warn'}">
				{s.texture_cache_status === 'ready' ? '✅' : '⚠'} Texture {String(s.texture_cache_status)}
			</span>
		{/if}
	</div>

	<!-- Tabs -->
	<div class="tab-bar mt-4">
		<button class="tab {activeTab === 'workspace' ? 'active' : ''}" onclick={() => activeTab = 'workspace'}>
			{L === 'kr' ? '작업공간' : 'Workspace'}
		</button>
		<button class="tab {activeTab === 'render' ? 'active' : ''}" onclick={() => activeTab = 'render'}>
			{L === 'kr' ? '렌더 상태' : 'Render Status'}
		</button>
		<button class="tab {activeTab === 'captures' ? 'active' : ''}" onclick={() => activeTab = 'captures'}>
			{L === 'kr' ? '캡처 기록' : 'Capture History'}
			{#if captures.length}<span class="tab-badge">{captures.length}</span>{/if}
		</button>
		<button class="tab {activeTab === 'materials' ? 'active' : ''}" onclick={() => activeTab = 'materials'}>
			{L === 'kr' ? '재질 라이브러리' : 'Materials'}
		</button>
	</div>

	<!-- Workspace Tab -->
	{#if activeTab === 'workspace'}
		<div class="grid lg:grid-cols-[1.4fr,1fr] gap-4 mt-4">
			<!-- Floorplan -->
			<div class="panel">
				<div class="panel-label">{L === 'kr' ? '장면 맵' : 'Scene Map'}</div>
				<div class="image-frame mt-3">
					<img src={floorplanUrl} alt="Floorplan" style="width:100%;height:auto" loading="lazy" />
				</div>
				<div class="mt-2" style="display:flex;gap:0.5rem">
					<a href="/api/scenes/{sceneId}/floorplan" class="button button-subtle text-xs" target="_blank">
						{L === 'kr' ? '도면 JSON' : 'Floorplan JSON'}
					</a>
				</div>
			</div>

			<!-- Info + Cameras -->
			<div style="display:flex;flex-direction:column;gap:1rem">
				<div class="panel">
					<div class="panel-label">{L === 'kr' ? '씬 정보' : 'Scene Info'}</div>
					<div class="kv-list mt-3 text-sm">
						<div><span>Scene ID</span><span class="mono">{s.scene_id}</span></div>
						{#if s.usd_stage_path}
							<div><span>USD</span><span class="mono text-xs">{s.usd_stage_path}</span></div>
						{/if}
						{#if s.mitsuba_scene_ref}
							<div><span>Mitsuba ref</span><span class="mono text-xs">{s.mitsuba_scene_ref}</span></div>
						{/if}
						{#if s.readiness_status}
							<div>
								<span>{L === 'kr' ? '상태' : 'Ready'}</span>
								<span class="badge {s.readiness_status === 'render-ready' ? 'badge-succeeded' : 'badge-queued'}">{s.readiness_status}</span>
							</div>
						{/if}
					</div>
				</div>

				{#if (s.cameras as unknown[])?.length}
					<div class="panel">
						<div class="panel-label">{L === 'kr' ? '카메라' : 'Cameras'} ({(s.cameras as unknown[]).length})</div>
						<div class="table-wrap mt-3">
							<table class="table">
								<thead><tr><th>ID</th><th>{L === 'kr' ? '유형' : 'Type'}</th><th>{L === 'kr' ? '해상도' : 'Res'}</th></tr></thead>
								<tbody>
									{#each (s.cameras as unknown[]) as cam}
										{@const c = cam as Record<string, unknown>}
										<tr>
											<td class="mono text-xs">{c.camera_id ?? c.id}</td>
											<td class="text-sm">{c.camera_type ?? '—'}</td>
											<td class="text-sm">{c.width ?? '?'}×{c.height ?? '?'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- Render Status Tab -->
	{#if activeTab === 'render'}
		<!-- Render Options -->
		<div class="panel mt-4">
			<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem">
				<span class="panel-label">{L === 'kr' ? '렌더 옵션' : 'Render Options'}</span>
				<button class="button button-subtle text-xs" onclick={saveRenderOptions}>{L === 'kr' ? '저장' : 'Save'}</button>
			</div>

			<!-- Modality groups -->
			<div style="display:flex;flex-wrap:wrap;gap:1.5rem">
				{#each MODALITY_GROUPS as group}
					<div>
						<div class="text-xs muted" style="margin-bottom:0.3rem">{L === 'kr' ? group.label_kr : group.label_en}</div>
						{#if group.note}<div class="muted" style="font-size:0.68rem;margin-bottom:0.25rem">{group.note}</div>{/if}
						<div style="display:flex;flex-wrap:wrap;gap:0.35rem">
							{#each group.mods as mod}
								<label style="display:flex;align-items:center;gap:0.3rem;font-size:0.75rem;cursor:pointer">
									<input type="checkbox" checked={roModalities.has(mod)} onchange={() => toggleModality(mod)} />
									{mod}
								</label>
							{/each}
						</div>
					</div>
				{/each}
			</div>

			<div style="display:flex;flex-wrap:wrap;gap:1.5rem;margin-top:1rem;align-items:flex-end">
				<div>
					<div class="text-xs muted" style="margin-bottom:0.3rem">SPP</div>
					<input type="number" bind:value={roSpp} min="1" max="4096" class="render-spp-input" style="width:5rem" />
				</div>
				<div>
					<div class="text-xs muted" style="margin-bottom:0.3rem">{L === 'kr' ? '해상도' : 'Resolution'}</div>
					<div style="display:flex;align-items:center;gap:0.4rem">
						<input type="number" bind:value={roWidth} min="64" max="4096" step="64" class="render-spp-input" style="width:5rem" />
						<span class="muted">×</span>
						<input type="number" bind:value={roHeight} min="64" max="4096" step="64" class="render-spp-input" style="width:5rem" />
						<button class="button button-subtle text-xs" onclick={() => { roWidth=640; roHeight=480; }}>SD</button>
						<button class="button button-subtle text-xs" onclick={() => { roWidth=1280; roHeight=720; }}>HD</button>
						<button class="button button-subtle text-xs" onclick={() => { roWidth=1920; roHeight=1080; }}>FHD</button>
					</div>
				</div>
				<div>
					<div class="text-xs muted" style="margin-bottom:0.3rem">{L === 'kr' ? '업스케일' : 'Upscale'}</div>
					<select bind:value={roUpscale} class="cap-select">
						<option value="none">None</option>
						<option value="2x_esrgan">2× Real-ESRGAN</option>
						<option value="4x_esrgan">4× Real-ESRGAN</option>
						<option value="2x_bicubic">2× Bicubic</option>
					</select>
				</div>
			</div>
		</div>

		<!-- Recent Jobs -->
		<div class="panel mt-4">
			<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem">
				<span class="panel-label">{L === 'kr' ? '최근 작업' : 'Recent Jobs'}</span>
				<a href="/jobs" class="button button-subtle text-xs">{L === 'kr' ? '전체 작업 →' : 'All Jobs →'}</a>
			</div>
			{#if recentJobs.length === 0}
				<div class="empty-state text-sm">{L === 'kr' ? '최근 렌더 이벤트가 없습니다.' : 'No recent render events.'}</div>
			{:else}
				<div class="table-wrap">
					<table class="table">
						<thead>
							<tr>
								<th>Job ID</th>
								<th>{L === 'kr' ? '상태' : 'Status'}</th>
								<th>{L === 'kr' ? '완료' : 'Finished'}</th>
							</tr>
						</thead>
						<tbody>
							{#each recentJobs as job}
								{@const j = job as Record<string, unknown>}
								<tr>
									<td class="mono text-xs">{String(j.job_id ?? '').slice(0, 20)}</td>
									<td><span class="badge {statusClass(String(j.status ?? ''))}">{j.status}</span></td>
									<td class="muted text-xs">{j.finished_at ? ago(String(j.finished_at)) : '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Capture History Tab -->
	{#if activeTab === 'captures'}
		{#if captures.length === 0}
			<div class="empty-state mt-6">{L === 'kr' ? '캡처 기록 없음' : 'No captures yet'}</div>
		{:else}
			<div class="panel mt-4">
				<div class="panel-label">{L === 'kr' ? '캡처 기록' : 'Capture History'} ({captures.length})</div>
				<div class="thumb-grid mt-3">
					{#each captures as cap}
						{@const c = cap as Record<string, unknown>}
						<div class="thumb-card">
							{#if c.rgb_path}
								<img src="/artifacts?path={c.rgb_path}" alt="capture" />
							{:else}
								<div class="thumb-empty">{L === 'kr' ? '미리보기 없음' : 'No preview'}</div>
							{/if}
							<div class="thumb-label text-xs mt-2">{ago(String(c.captured_at ?? ''))}</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{/if}

	<!-- Materials Tab -->
	{#if activeTab === 'materials'}
		<div class="panel mt-4">
			<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem">
				<span class="panel-label">{L === 'kr' ? '재질 라이브러리' : 'Material Library'}</span>
			</div>

			<!-- Filter bar -->
			<div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-bottom:0.75rem">
				<input
					class="search-input"
					placeholder={L === 'kr' ? '재질 검색…' : 'Search presets…'}
					bind:value={matSearch}
					style="width:14rem"
				/>
				<div class="filter-chips">
					{#each ['all','glass','metal','plastic','paint'] as f}
						<button class="filter-chip {matFilter === f ? 'active' : ''}" onclick={() => matFilter = f}>
							{f === 'all' ? (L === 'kr' ? '전체' : 'All') : (L === 'kr' ? { glass:'유리', metal:'금속', plastic:'플라스틱', paint:'페인트' }[f] ?? f : f)}
						</button>
					{/each}
				</div>
			</div>

			<!-- Preset grid -->
			{#if filteredPresets.length === 0}
				<div class="empty-state text-sm">{L === 'kr' ? '재질 없음' : 'No presets found'}</div>
			{:else}
				<div class="material-browser-grid">
					{#each filteredPresets as preset}
						<div
							class="material-card material-card-clickable"
							onclick={() => applyPreset(preset)}
							onkeydown={(e) => e.key === 'Enter' && applyPreset(preset)}
							tabindex="0"
							role="button"
							title="{preset.title_en} — {preset.description_en}"
						>
							<div class="material-card-head">
								<div class="material-sphere {preset.swatch ?? ''}">
									<img
										src={materialPreviewUrl(preset.bsdf_type)}
										alt={preset.title_en}
										style="display:none"
										onload={(e) => { (e.target as HTMLImageElement).style.display = 'block'; }}
										onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
									/>
								</div>
								<div>
									<div class="material-card-title">{L === 'kr' ? (preset.title_kr || preset.title_en) : preset.title_en}</div>
									<div class="material-card-meta">{preset.category}</div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Measured materials -->
			{#if measuredMats.length > 0}
				<div class="panel-label mt-4" style="margin-bottom:0.5rem">{L === 'kr' ? '측정 재질' : 'Measured Materials'}</div>
				<div class="material-browser-grid">
					{#each measuredMats as mat}
						{@const m = mat as Record<string, unknown>}
						<div
							class="material-card material-card-clickable"
							onclick={() => applyMeasuredMaterial(sceneId as string, { dataset_id: m.dataset_id, material_id: m.material_id })}
							onkeydown={(e) => e.key === 'Enter' && applyMeasuredMaterial(sceneId as string, { dataset_id: m.dataset_id, material_id: m.material_id })}
							tabindex="0"
							role="button"
						>
							<div class="material-card-head">
								<div class="material-sphere">
									<img
										src={`/api/material-preview/measured/${m.dataset_id}/${m.material_id}`}
										alt={String(m.label_en ?? '')}
										style="display:none"
										onload={(e) => { (e.target as HTMLImageElement).style.display = 'block'; }}
										onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
									/>
								</div>
								<div>
									<div class="material-card-title">{L === 'kr' ? (m.label_kr || m.label_en) : m.label_en}</div>
									<div class="material-card-meta">{m.dataset_id}</div>
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
{/if}
