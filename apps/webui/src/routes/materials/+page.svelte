<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		materialLibrary,
		invalidateCuratedPreview,
		invalidateMeasuredPreview,
		batchInvalidatePreviews,
		downloadDataset,
		downloadDatasetForce,
		applyMeasuredMaterial,
		applyCuratedMaterial,
		materialJobs,
		clearMaterialJobs
	} from '$lib/api';
	import MaterialCard from '$lib/components/MaterialCard.svelte';
	import { sceneRailSnippet, sceneBottomSnippet } from '$lib/stores/scenePortals';
	import type {
		LibraryResponse,
		DatasetGroup,
		MatEntry,
		PreviewStatus
	} from '$lib/types/materialLibrary';

	let library = $state<LibraryResponse | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	let activeSetFilter = $state<string>('all');
	let activeStatusFilter = $state<'all' | 'download_missing' | 'preview_failed' | 'preview_stale'>(
		'all'
	);
	let sortKey = $state<'name' | 'recent' | 'errors_first'>('name');
	let searchQuery = $state('');

	let selected = $state<{ mat: MatEntry; group: DatasetGroup } | null>(null);
	// Check mode: when on, cards show a checkbox in the corner and clicking
	// a card toggles its checked state (instead of opening the right-rail
	// detail). Selected items can be batch-rerendered or batch-redownloaded
	// via the action bar that appears at the top of the grid.
	let checkMode = $state(false);
	let checkedKeys = $state<Set<string>>(new Set());

	function toggleChecked(mat: MatEntry, group: DatasetGroup): void {
		const key = busyKey(mat, group);
		const next = new Set(checkedKeys);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		checkedKeys = next;
	}
	function clearChecked(): void {
		checkedKeys = new Set();
	}
	function exitCheckMode(): void {
		checkMode = false;
		checkedKeys = new Set();
	}
	function checkAllVisible(): void {
		const next = new Set(checkedKeys);
		for (const { group, materials } of visibleGroups) {
			for (const mat of materials) next.add(busyKey(mat, group));
		}
		checkedKeys = next;
	}
	const checkedTargets = $derived.by(() => {
		if (!library) return [] as { mat: MatEntry; group: DatasetGroup }[];
		const out: { mat: MatEntry; group: DatasetGroup }[] = [];
		for (const g of library.groups) {
			for (const m of g.materials) {
				if (checkedKeys.has(busyKey(m, g))) out.push({ mat: m, group: g });
			}
		}
		return out;
	});

	async function batchRerenderChecked(): Promise<void> {
		if (checkedTargets.length === 0) {
			showToast('선택된 항목이 없습니다.');
			return;
		}
		const items = checkedTargets.map(({ mat, group }) =>
			mat.kind === 'curated'
				? ({ type: 'curated', material_id: mat.material_id } as const)
				: ({
						type: 'measured',
						dataset_id: group.dataset_id,
						material_id: mat.material_id
					} as const)
		);
		try {
			await batchInvalidatePreviews(items);
			const stamp = Date.now();
			const next = new Map(bustMap);
			for (const { mat, group } of checkedTargets) {
				const key = busyKey(mat, group);
				next.set(key, stamp);
				patchEntry(key, { preview_status: 'missing', preview_mtime: null });
			}
			bustMap = next;
			showToast(`${checkedTargets.length}개 프리뷰 재렌더 큐에 등록.`);
			pollJobs();
		} catch (e) {
			showToast(`배치 재렌더 실패: ${e instanceof Error ? e.message : String(e)}`, 'error');
		}
	}

	async function batchRedownloadChecked(): Promise<void> {
		const measuredTargets = checkedTargets.filter(
			(t) => t.mat.kind === 'measured' && t.mat.download_url
		);
		if (measuredTargets.length === 0) {
			showToast('재다운로드 가능한 항목이 없습니다 (measured + 다운로드 URL 필요).');
			return;
		}
		// Group by dataset_id so we send one POST per dataset with that
		// dataset's selected material_ids — `downloadDatasetForce` already
		// supports a material_ids filter.
		const byDataset = new Map<string, string[]>();
		for (const { mat, group } of measuredTargets) {
			const arr = byDataset.get(group.dataset_id) ?? [];
			arr.push(mat.material_id);
			byDataset.set(group.dataset_id, arr);
		}
		try {
			await Promise.all(
				[...byDataset.entries()].map(([ds, ids]) => downloadDatasetForce(ds, ids))
			);
			showToast(`${measuredTargets.length}개 항목 재다운로드 큐에 등록.`);
			setTimeout(reload, 1000);
		} catch (e) {
			showToast(`재다운로드 실패: ${e instanceof Error ? e.message : String(e)}`, 'error');
		}
	}
	// Per-material cache-buster: bumped after a successful invalidate so the
	// <img src> URL changes and the browser actually re-fetches (which triggers
	// the daemon's on-demand re-render). Without this the badge flips to
	// "프리뷰 없음" but no GET is ever made, so nothing renders.
	let bustMap = $state<Map<string, number>>(new Map());
	type ToastEntry = { id: number; msg: string; tone: 'info' | 'error' };
	let toasts = $state<ToastEntry[]>([]);
	let toastSeq = 0;

	// Server-managed job log. The daemon owns the source of truth — it
	// creates a job on every invalidate POST, drives the BG render, and
	// reports stage progression (queued → scene_build → rendering → saved)
	// + final status. The page polls /api/material-jobs on a short interval
	// while running jobs exist (longer when idle) so a browser refresh
	// doesn't wipe the panel.
	type JobAction = 'rerender' | 'redownload' | 'batch-rerender' | 'batch-redownload';
	type JobStatus = 'running' | 'success' | 'failed';
	type MaterialJob = {
		id: number;
		key: string;
		title: string;
		subtitle: string;
		action: JobAction;
		status: JobStatus;
		stage: string;
		stage_message: string;
		// Chunked render sub-step progress (current chunk out of progress_total).
		// progress_total = 0 means "no progress info" (e.g. measured renders
		// going through get_measured_preview which doesn't report chunks).
		progress?: number;
		progress_total?: number;
		started_at: number; // unix seconds (server clock)
		stage_updated_at: number;
		finished_at: number | null;
		error: string | null;
		// Optional byte-level progress (set by dataset downloads).
		current_done_bytes?: number;
		current_total_bytes?: number;
		current_speed_bps?: number;
	};

	function fmtBps(bps: number): string {
		if (!bps || bps <= 0) return '';
		const units = ['B', 'KB', 'MB', 'GB'];
		let n = bps;
		let i = 0;
		while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
		return `${n.toFixed(i >= 2 ? 1 : 0)} ${units[i]}/s`;
	}

	function fmtEta(remainingBytes: number, bps: number): string {
		if (!bps || bps <= 0 || remainingBytes <= 0) return '';
		const sec = Math.round(remainingBytes / bps);
		if (sec < 60) return `${sec}s`;
		if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
		return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
	}
	let serverJobs = $state<MaterialJob[]>([]);
	let nowMs = $state(Date.now()); // re-stamped each poll so elapsed tickers refresh

	const runningKeys = $derived(
		new Set(serverJobs.filter((j) => j.status === 'running').map((j) => j.key))
	);
	const jobCounts = $derived({
		running: serverJobs.filter((j) => j.status === 'running').length,
		success: serverJobs.filter((j) => j.status === 'success').length,
		failed: serverJobs.filter((j) => j.status === 'failed').length
	});

	function jobElapsed(j: MaterialJob): string {
		const endMs = j.finished_at != null ? j.finished_at * 1000 : nowMs;
		const s = Math.max(0, Math.round((endMs - j.started_at * 1000) / 1000));
		return `${s}s`;
	}
	// Track each job's previous status so we can react to running→success and
	// running→failed transitions (bump bust + patch the local entry without
	// re-fetching the whole library).
	const prevJobStatus = new Map<number, JobStatus>();
	async function pollJobs() {
		try {
			const resp = (await materialJobs()) as { jobs: MaterialJob[] };
			const incoming = resp.jobs ?? [];
			for (const j of incoming) {
				const prev = prevJobStatus.get(j.id);
				if (prev === 'running' && j.status !== 'running') {
					if (j.action === 'rerender' || j.action === 'batch-rerender') {
						const next = new Map(bustMap);
						next.set(j.key, Date.now());
						bustMap = next;
						if (j.status === 'success') {
							patchEntry(j.key, {
								preview_status: 'cached',
								preview_mtime: new Date().toISOString()
							});
						} else {
							patchEntry(j.key, { preview_status: 'failed' });
						}
					}
				}
				prevJobStatus.set(j.id, j.status);
			}
			serverJobs = incoming;
			nowMs = Date.now();
		} catch {
			// Poll failures are non-fatal — next tick will retry.
		}
	}

	async function clearFinishedJobs() {
		try {
			await clearMaterialJobs();
			await pollJobs();
		} catch (e) {
			showToast(`작업 비우기 실패: ${e instanceof Error ? e.message : String(e)}`, 'error');
		}
	}

	// apply_to query mode
	const applyTo = $derived(page.url.searchParams.get('apply_to') ?? '');
	const applyScene = $derived(page.url.searchParams.get('scene') ?? '');
	const applyMode = $derived(Boolean(applyTo && applyScene));

	async function reload() {
		loading = true;
		loadError = null;
		try {
			library = await materialLibrary();
		} catch (e: unknown) {
			loadError = e instanceof Error ? e.message : String(e);
		}
		loading = false;
	}

	onMount(() => {
		reload();
		pollJobs();
		// Adaptive polling: tight interval while a render is running so the
		// stage column reads "live", longer interval when idle so we're not
		// hammering the daemon. Cleared on unmount.
		let timer: ReturnType<typeof setTimeout>;
		const tick = () => {
			pollJobs();
			const interval = jobCounts.running > 0 ? 1500 : 5000;
			timer = setTimeout(tick, interval);
		};
		timer = setTimeout(tick, 1500);
		return () => clearTimeout(timer);
	});

	function showToast(msg: string, tone: 'info' | 'error' = 'info') {
		const id = ++toastSeq;
		toasts = [...toasts, { id, msg, tone }];
		setTimeout(() => {
			toasts = toasts.filter((t) => t.id !== id);
		}, 4000);
	}

	function busyKey(mat: MatEntry, group: DatasetGroup): string {
		return `${group.dataset_id}/${mat.material_id}`;
	}

	// Surgically patch a single MatEntry inside `library` without going back
	// to the network. Used after per-item rerender / redownload so we don't
	// have to re-fetch /api/material-library (which costs a couple hundred ms
	// and re-runs every group's stat aggregation on the daemon).
	function patchEntry(key: string, patch: Partial<MatEntry>): void {
		if (!library) return;
		library = {
			...library,
			groups: library.groups.map((g) => ({
				...g,
				materials: g.materials.map((m) =>
					busyKey(m, g) === key ? ({ ...m, ...patch } as MatEntry) : m
				)
			}))
		};
	}

	async function handleAction(
		action: 'rerender' | 'redownload',
		mat: MatEntry,
		group: DatasetGroup
	) {
		const key = busyKey(mat, group);
		try {
			if (action === 'rerender') {
				// The daemon now creates a job + spawns the BG render itself
				// on this POST. We don't track the job locally — polling
				// (pollJobs) reflects it as soon as it's registered.
				if (mat.kind === 'curated') {
					await invalidateCuratedPreview(mat.material_id);
				} else {
					await invalidateMeasuredPreview(group.dataset_id, mat.material_id);
				}
				// Optimistic local state: badge flips to "프리뷰 없음" and the
				// card's busy spinner appears as soon as the next pollJobs cycle
				// sees the running job (runningKeys.has(key) → busy=true).
				patchEntry(key, { preview_status: 'missing', preview_mtime: null });
				// Bump bust so the <img> immediately starts the GET against the
				// daemon — that returns 202 while the BG render runs. When
				// pollJobs detects running→success, it bumps bust again and
				// the second GET serves the cached PNG.
				const next = new Map(bustMap);
				next.set(key, Date.now());
				bustMap = next;
				// Trigger an immediate poll so the new job appears without
				// waiting for the next interval.
				pollJobs();
			} else if (action === 'redownload') {
				await downloadDatasetForce(group.dataset_id, [mat.material_id]);
				showToast(`${mat.display_name} 재다운로드 요청.`);
			}
		} catch (e) {
			showToast(`작업 실패: ${e instanceof Error ? e.message : String(e)}`, 'error');
		}
	}

	async function handleApplyToCurrent(mat: MatEntry, group: DatasetGroup) {
		if (!applyMode) return;
		try {
			if (mat.kind === 'curated') {
				await applyCuratedMaterial(applyScene, {
					prim_path: applyTo,
					material_id: mat.material_id
				});
			} else {
				await applyMeasuredMaterial(applyScene, {
					prim_path: applyTo,
					dataset_id: group.dataset_id,
					material_id: mat.material_id,
					measured_file_path: mat.native_file
				});
			}
			showToast('적용됨. 현재 세션으로 돌아갑니다.');
			setTimeout(() => history.back(), 800);
		} catch (e) {
			showToast(`적용 실패: ${e instanceof Error ? e.message : String(e)}`, 'error');
		}
	}

	async function batchRedownloadMissing() {
		if (!library) return;
		const datasetIds = library.groups
			.filter((g) =>
				g.materials.some((m) => m.status === 'not_downloaded' && m.download_url)
			)
			.map((g) => g.dataset_id);
		if (datasetIds.length === 0) {
			showToast('누락 항목이 없습니다.');
			return;
		}
		try {
			await Promise.all(datasetIds.map((d) => downloadDataset(d)));
			showToast(`${datasetIds.length}개 데이터셋 다운로드 요청.`);
			// Single deferred reload only after the batch finishes — downloads
			// don't have a single-item HTTP affordance to verify per-entry.
			setTimeout(reload, 1000);
		} catch (e) {
			showToast(`재다운로드 실패: ${e instanceof Error ? e.message : String(e)}`, 'error');
		}
	}

	async function batchRerenderFailed() {
		if (!library) return;
		const targets = library.groups.flatMap((g) =>
			g.materials
				.filter((m) => m.preview_status === 'failed' || m.preview_status === 'stale')
				.map((m) => ({ mat: m, group: g }))
		);
		if (targets.length === 0) {
			showToast('재렌더링할 항목이 없습니다.');
			return;
		}
		const items = targets.map(({ mat, group }) =>
			mat.kind === 'curated'
				? ({ type: 'curated', material_id: mat.material_id } as const)
				: ({
						type: 'measured',
						dataset_id: group.dataset_id,
						material_id: mat.material_id
					} as const)
		);
		try {
			await batchInvalidatePreviews(items);
			// Daemon spawns one job per item server-side; pollJobs picks them
			// up. Locally just flip the badges and bump busts so the UI is
			// instantly responsive while the BG renders run.
			const stamp = Date.now();
			const next = new Map(bustMap);
			for (const { mat, group } of targets) {
				const key = busyKey(mat, group);
				next.set(key, stamp);
				patchEntry(key, { preview_status: 'missing', preview_mtime: null });
			}
			bustMap = next;
			showToast(`${targets.length}개 프리뷰 재렌더 요청.`);
			pollJobs();
		} catch (e) {
			showToast(
				`배치 재렌더 실패: ${e instanceof Error ? e.message : String(e)}`,
				'error'
			);
		}
	}

	function sortMaterials(list: MatEntry[]): MatEntry[] {
		const sorted = [...list];
		if (sortKey === 'name') {
			sorted.sort((a, b) => a.display_name.localeCompare(b.display_name));
		} else if (sortKey === 'recent') {
			sorted.sort((a, b) => (b.preview_mtime ?? '').localeCompare(a.preview_mtime ?? ''));
		} else if (sortKey === 'errors_first') {
			const rank = (s: PreviewStatus) =>
				({ failed: 0, stale: 1, missing: 2, cached: 3, baked: 4 })[s] ?? 5;
			sorted.sort((a, b) => rank(a.preview_status) - rank(b.preview_status));
		}
		return sorted;
	}

	// Cards are grouped by BRDF research source (one section per dataset/group).
	// Filters apply within each group; groups with zero matching materials are
	// dropped so the grid stays dense.
	const visibleGroups = $derived.by(() => {
		if (!library) return [] as { group: DatasetGroup; materials: MatEntry[] }[];
		const q = searchQuery.trim().toLowerCase();
		const buckets: { group: DatasetGroup; materials: MatEntry[] }[] = [];
		for (const g of library.groups) {
			if (activeSetFilter !== 'all' && g.dataset_id !== activeSetFilter) continue;
			const mats = g.materials.filter((mat) => {
				if (activeStatusFilter === 'download_missing' && mat.status !== 'not_downloaded')
					return false;
				if (activeStatusFilter === 'preview_failed' && mat.preview_status !== 'failed')
					return false;
				if (activeStatusFilter === 'preview_stale' && mat.preview_status !== 'stale')
					return false;
				if (q) {
					const hay = `${mat.material_id} ${mat.display_name} ${g.display_name}`.toLowerCase();
					if (!hay.includes(q)) return false;
				}
				return true;
			});
			if (mats.length === 0) continue;
			buckets.push({ group: g, materials: sortMaterials(mats) });
		}
		return buckets;
	});

	const visibleCount = $derived(
		visibleGroups.reduce((sum, b) => sum + b.materials.length, 0)
	);

	// Push the detail drawer into the global right rail and the live progress
	// strip into the bottom panel. The layout already reserves these slots; on
	// /materials they host the selected-material details and any active
	// invalidate/redownload operations + transient toasts.
	$effect(() => {
		sceneRailSnippet.set(railContent);
		sceneBottomSnippet.set(bottomContent);
		return () => {
			sceneRailSnippet.set(null);
			sceneBottomSnippet.set(null);
		};
	});
</script>

<div class="page-materials">
	{#if applyMode}
		<div class="apply-bar">
			<div>
				<strong>적용 대상:</strong>
				<code>{applyTo}</code>
				<span class="apply-scene">scene={applyScene}</span>
			</div>
			<button type="button" class="btn-link" onclick={() => history.back()}>× 취소</button>
		</div>
	{/if}

	<header class="page-header">
		<div>
			<h1>재질 라이브러리</h1>
			<p class="page-sub">전역 BRDF 자산과 프리뷰 상태를 관리합니다.</p>
		</div>
		<div class="page-actions">
			<button type="button" class="btn-ghost" onclick={reload}>↻ 동기화</button>
			<button type="button" class="btn-ghost" onclick={batchRedownloadMissing}
				>⬇ 누락만 재다운로드</button
			>
			<button type="button" class="btn-ghost" onclick={batchRerenderFailed}
				>⟳ 실패 프리뷰만 재렌더링</button
			>
			<button
				type="button"
				class="btn-ghost"
				class:btn-ghost-active={checkMode}
				onclick={() => (checkMode ? exitCheckMode() : (checkMode = true))}
			>
				{checkMode ? '✕ 선택 모드 종료' : '☑ 선택 모드'}
			</button>
		</div>
	</header>

	{#if checkMode}
		<div class="check-bar" role="toolbar" aria-label="선택 항목 작업">
			<div class="check-bar-info">
				<span class="check-bar-count">{checkedKeys.size}개 선택됨</span>
				<button type="button" class="btn-link" onclick={checkAllVisible}>화면 전체 선택</button>
				<button type="button" class="btn-link" onclick={clearChecked}>선택 해제</button>
			</div>
			<div class="check-bar-actions">
				<button
					type="button"
					class="btn-ghost"
					onclick={batchRedownloadChecked}
					disabled={checkedKeys.size === 0}
				>⬇ 선택 항목 재다운로드</button>
				<button
					type="button"
					class="btn-primary"
					onclick={batchRerenderChecked}
					disabled={checkedKeys.size === 0}
				>⟳ 선택 항목 재렌더 ({checkedKeys.size})</button>
			</div>
		</div>
	{/if}

	<section class="stat-row">
		<div class="stat-card">
			<div class="stat-label">전체 재질</div>
			<div class="stat-value">{library?.summary.total ?? '–'}</div>
			<div class="stat-foot">세트 {library?.groups.length ?? '–'}개</div>
		</div>
		<div class="stat-card stat-ok">
			<div class="stat-label">다운로드 완료</div>
			<div class="stat-value">{library?.summary.downloaded ?? '–'}</div>
			<div class="stat-foot">
				{#if library && library.summary.total > 0}
					{((library.summary.downloaded / library.summary.total) * 100).toFixed(1)}%
				{:else}–{/if}
			</div>
		</div>
		<div class="stat-card stat-blue">
			<div class="stat-label">프리뷰 완료</div>
			<div class="stat-value">{library?.summary.preview_ok ?? '–'}</div>
			<div class="stat-foot">
				{#if library && library.summary.total > 0}
					{((library.summary.preview_ok / library.summary.total) * 100).toFixed(1)}%
				{:else}–{/if}
			</div>
		</div>
		<div class="stat-card stat-warn">
			<div class="stat-label">오류 / 주의</div>
			<div class="stat-value">{(library?.summary.preview_failed ?? 0) + (library?.summary.errors ?? 0)}</div>
			<div class="stat-foot">실패 {library?.summary.preview_failed ?? 0} · 주의 {library?.summary.errors ?? 0}</div>
		</div>
	</section>

	<section class="filter-row">
		<input
			type="search"
			placeholder="재질 이름 검색…"
			bind:value={searchQuery}
		/>
		<select bind:value={activeSetFilter}>
			<option value="all">세트 전체</option>
			{#each library?.groups ?? [] as g}
				<option value={g.dataset_id}>{g.display_name}</option>
			{/each}
		</select>
		<select bind:value={activeStatusFilter}>
			<option value="all">상태 전체</option>
			<option value="download_missing">다운로드 누락</option>
			<option value="preview_failed">프리뷰 실패</option>
			<option value="preview_stale">프리뷰 오래됨</option>
		</select>
		<select bind:value={sortKey}>
			<option value="name">정렬: 이름순</option>
			<option value="recent">정렬: 최근 업데이트</option>
			<option value="errors_first">정렬: 오류 우선</option>
		</select>
	</section>

	<section class="grid-area">
		{#if loading}
			<div class="empty">불러오는 중…</div>
		{:else if loadError}
			<div class="empty error">로드 실패: {loadError}</div>
		{:else if visibleCount === 0}
			<div class="empty">조건에 맞는 재질이 없습니다.</div>
		{:else}
			{#each visibleGroups as { group, materials } (group.dataset_id)}
				<section class="group-section">
					<header class="group-header">
						<div class="group-title-row">
							<h2 class="group-title">{group.display_name}</h2>
							<span class="group-count">{materials.length}개</span>
						</div>
						<div class="group-meta">
							<span class="group-id mono">{group.dataset_id}</span>
							{#if group.summary}
								<span class="group-stat">다운로드 {group.summary.downloaded}/{group.summary.total}</span>
								<span class="group-stat">프리뷰 {group.summary.preview_ok}/{group.summary.total}</span>
								{#if group.summary.preview_failed > 0}
									<span class="group-stat group-stat-warn">실패 {group.summary.preview_failed}</span>
								{/if}
							{/if}
						</div>
					</header>
					<div class="card-grid">
						{#each materials as mat (mat.material_id)}
							<MaterialCard
								{mat}
								{group}
								selected={selected?.mat.material_id === mat.material_id &&
									selected?.group.dataset_id === group.dataset_id}
								busy={runningKeys.has(busyKey(mat, group))}
								bust={bustMap.get(busyKey(mat, group)) ?? 0}
								checkable={checkMode}
								checked={checkedKeys.has(busyKey(mat, group))}
								onToggleCheck={toggleChecked}
								onSelect={(m, g) =>
									checkMode ? toggleChecked(m, g) : (selected = { mat: m, group: g })}
								onAction={handleAction}
							/>
						{/each}
					</div>
				</section>
			{/each}
		{/if}
	</section>

</div>

{#snippet railContent()}
	{#if selected}
		{@const sel = selected}
		<div class="rail-drawer">
			<header class="drawer-header">
				<div>
					<div class="drawer-title">{sel.mat.display_name}</div>
					<div class="drawer-sub">{sel.group.display_name}</div>
				</div>
				<button type="button" class="btn-close" onclick={() => (selected = null)}>×</button>
			</header>

			<dl class="drawer-meta">
				<dt>세트</dt>
				<dd>{sel.group.display_name}</dd>
				<dt>자료 ID</dt>
				<dd><code>{sel.mat.material_id}</code></dd>
				{#if sel.mat.category}
					<dt>카테고리</dt>
					<dd>{sel.mat.category}</dd>
				{/if}
				{#if sel.mat.preview_meta?.source_version}
					<dt>자료 버전</dt>
					<dd>{sel.mat.preview_meta.source_version}</dd>
				{/if}
				{#if sel.mat.download_size_bytes}
					<dt>파일 크기</dt>
					<dd>{(sel.mat.download_size_bytes / 1024 / 1024).toFixed(1)} MB</dd>
				{/if}
			</dl>

			<h3 class="drawer-section">프리뷰 정보</h3>
			<dl class="drawer-meta">
				<dt>프리셋</dt>
				<dd>{sel.mat.preview_meta?.preview_preset ?? '–'}</dd>
				<dt>해상도</dt>
				<dd>
					{sel.mat.preview_meta?.resolution
						? `${sel.mat.preview_meta.resolution[0]} × ${sel.mat.preview_meta.resolution[1]}`
						: '–'}
				</dd>
				<dt>렌더 버전</dt>
				<dd>{sel.mat.preview_meta?.mitsuba_version ?? '–'}</dd>
				<dt>마지막 프리뷰</dt>
				<dd>{sel.mat.preview_mtime ?? '–'}</dd>
				<dt>상태</dt>
				<dd class:status-warn={sel.mat.preview_status === 'stale'}>{sel.mat.preview_status}</dd>
			</dl>

			<h3 class="drawer-section">사용 정보</h3>
			<dl class="drawer-meta">
				<dt>사용 중인 씬</dt>
				<dd>–</dd>
			</dl>

			<div class="drawer-actions">
				<button type="button" class="btn-primary" onclick={() => handleAction('rerender', sel.mat, sel.group)}>
					프리뷰 재렌더링
				</button>
				{#if sel.mat.kind === 'measured' && sel.mat.download_url}
					<button type="button" class="btn-ghost" onclick={() => handleAction('redownload', sel.mat, sel.group)}>
						재다운로드
					</button>
				{/if}
				{#if applyMode}
					<button
						type="button"
						class="btn-apply"
						onclick={() => handleApplyToCurrent(sel.mat, sel.group)}
					>
						이 재질 적용
					</button>
				{/if}
			</div>
		</div>
	{:else}
		<p class="muted text-xs rail-empty">
			재질을 선택하면 상세 정보가 여기에 표시됩니다.
		</p>
	{/if}
{/snippet}

{#snippet bottomContent()}
	<div class="mat-bottom">
		<header class="mat-bottom-head">
			<div class="mat-bottom-title-row">
				<span class="mat-bottom-dot" class:active={jobCounts.running > 0}></span>
				<span class="mat-bottom-title">재질 라이브러리 작업</span>
				<span class="mat-bottom-counts">
					<span class="mat-count mat-count-running">진행 {jobCounts.running}</span>
					<span class="mat-count mat-count-success">성공 {jobCounts.success}</span>
					<span class="mat-count mat-count-failed">실패 {jobCounts.failed}</span>
				</span>
			</div>
			{#if serverJobs.length > 0}
				<button
					type="button"
					class="mat-bottom-clear"
					onclick={clearFinishedJobs}
					disabled={jobCounts.success === 0 && jobCounts.failed === 0}
				>완료 비우기</button>
			{/if}
		</header>

		<div class="mat-bottom-scroll">
		{#if serverJobs.length === 0}
			<p class="mat-bottom-empty muted text-xs">아직 실행한 작업이 없습니다. 카드의 ⋯ 메뉴 또는 상단 배치 버튼으로 시작합니다.</p>
		{:else}
			<table class="mat-bottom-table">
				<thead>
					<tr>
						<th>상태</th>
						<th>작업</th>
						<th>대상</th>
						<th>단계</th>
						<th>대상 키</th>
						<th class="num">소요</th>
					</tr>
				</thead>
				<tbody>
					{#each serverJobs as j (j.id)}
						<tr class="mat-bottom-row mat-bottom-row-{j.status}">
							<td>
								{#if j.status === 'running'}
									<span class="mat-row-status mat-row-status-running">
										<span class="mat-bottom-spinner" aria-hidden="true"></span>
										진행 중
									</span>
								{:else if j.status === 'success'}
									<span class="mat-row-status mat-row-status-success">✓ 성공</span>
								{:else}
									<span class="mat-row-status mat-row-status-failed">✕ 실패</span>
								{/if}
							</td>
							<td>{j.title}</td>
							<td>{j.subtitle}</td>
							<td class="mat-row-stage" title={j.error ?? j.stage_message}>
								<span class="mat-row-stage-label">{j.stage}</span>
								<span class="mat-row-stage-msg muted">{j.error ?? j.stage_message}</span>
								{#if j.status === 'running' && (j.progress_total ?? 0) > 0}
									{@const cur = j.progress ?? 0}
									{@const tot = j.progress_total ?? 1}
									{@const pct = Math.min(100, Math.max(0, (cur / tot) * 100))}
									<span class="mat-row-bytebar" aria-hidden="true">
										<span class="mat-row-bytebar-fill" style:width={`${pct}%`}></span>
									</span>
								{:else if j.status === 'running' && (j.current_total_bytes ?? 0) > 0}
									{@const done = j.current_done_bytes ?? 0}
									{@const total = j.current_total_bytes ?? 1}
									{@const bps = j.current_speed_bps ?? 0}
									{@const pct = Math.min(100, Math.max(0, (done / total) * 100))}
									<span class="mat-row-bytebar" aria-hidden="true">
										<span class="mat-row-bytebar-fill" style:width={`${pct}%`}></span>
									</span>
									{#if bps > 0}
										<span class="mat-row-speed muted">
											↓ {fmtBps(bps)}
											{#if total > done}· ETA {fmtEta(total - done, bps)}{/if}
										</span>
									{/if}
								{/if}
							</td>
							<td class="mono mat-row-key">{j.key}</td>
							<td class="num">{jobElapsed(j)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
		</div>

		{#if toasts.length > 0}
			<ul class="mat-bottom-toasts">
				{#each toasts as t (t.id)}
					<li class="mat-bottom-toast" class:err={t.tone === 'error'}>{t.msg}</li>
				{/each}
			</ul>
		{/if}
	</div>
{/snippet}

<style>
	.page-materials {
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		/* Match `_RIG_SPEC["preview_background"]["rgb"]` (#F7F7F5) in
		   sphere_preview.py — preview PNGs are alpha-composited over that
		   colour, so the page sheet has to be the same shade or the floor
		   patch will read as a discrete rectangle on the card. */
		background: #f7f7f5;
		min-height: 100%;
	}
	:global(.shell-workspace .page-content:has(.page-materials)) {
		background: #f7f7f5;
	}

	.apply-bar {
		position: sticky;
		top: 0;
		z-index: 10;
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.65rem 1rem;
		background: var(--brand-soft, #eef2ff);
		border: 1px solid var(--brand, #3a7afe);
		border-radius: 10px;
		font-size: 0.85rem;
	}
	.apply-bar code {
		background: rgba(255, 255, 255, 0.7);
		padding: 0.1rem 0.35rem;
		border-radius: 4px;
		margin-left: 0.25rem;
	}
	.apply-scene {
		margin-left: 0.6rem;
		opacity: 0.7;
		font-size: 0.75rem;
	}

	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.page-header h1 {
		margin: 0;
		font-size: 1.4rem;
	}
	.page-sub {
		margin: 0.2rem 0 0;
		color: var(--ink-muted, #6b7280);
		font-size: 0.85rem;
	}
	.page-actions {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	.stat-row {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 0.75rem;
	}
	.stat-card {
		padding: 0.85rem 1rem;
		background: var(--surface, #fff);
		border: 1px solid var(--border-soft, rgba(0, 0, 0, 0.08));
		border-radius: 10px;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}
	.stat-card .stat-label {
		font-size: 0.78rem;
		color: var(--ink-muted, #6b7280);
	}
	.stat-card .stat-value {
		font-size: 1.6rem;
		font-weight: 700;
		line-height: 1.1;
	}
	.stat-card .stat-foot {
		font-size: 0.72rem;
		color: var(--ink-muted, #6b7280);
	}
	.stat-ok {
		border-color: rgba(31, 122, 63, 0.3);
	}
	.stat-blue {
		border-color: rgba(29, 78, 216, 0.3);
	}
	.stat-warn {
		border-color: rgba(180, 83, 9, 0.3);
	}

	.filter-row {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
		align-items: center;
	}
	.filter-row input,
	.filter-row select {
		padding: 0.4rem 0.6rem;
		border: 1px solid var(--border-soft, rgba(0, 0, 0, 0.08));
		border-radius: 8px;
		font-size: 0.85rem;
		background: var(--surface, #fff);
	}
	.filter-row input[type='search'] {
		flex: 1 1 240px;
	}

	.grid-area {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}
	.group-section {
		display: flex;
		flex-direction: column;
		gap: 0.65rem;
	}
	.group-header {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		padding-bottom: 0.4rem;
		border-bottom: 1px solid var(--border-soft, rgba(0, 0, 0, 0.08));
	}
	.group-title-row {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
	}
	.group-title {
		margin: 0;
		font-size: 1rem;
		font-weight: 600;
		color: var(--ink-strong, #1f2330);
	}
	.group-count {
		font-size: 0.75rem;
		color: var(--ink-muted, #6b7280);
	}
	.group-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 0.65rem;
		font-size: 0.72rem;
		color: var(--ink-muted, #6b7280);
	}
	.group-id {
		opacity: 0.7;
	}
	.group-stat-warn {
		color: #b45309;
	}
	.card-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: 0.75rem;
	}
	.empty {
		padding: 3rem 1rem;
		text-align: center;
		color: var(--ink-muted, #6b7280);
		border: 1px dashed var(--border-soft, rgba(0, 0, 0, 0.08));
		border-radius: 10px;
	}
	.empty.error {
		color: #b91c1c;
		border-color: rgba(185, 28, 28, 0.3);
	}

	.rail-drawer {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 0.75rem;
	}
	.rail-empty {
		padding: 0.75rem;
	}
	.drawer-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}
	.drawer-title {
		font-weight: 600;
		font-size: 1rem;
	}
	.drawer-sub {
		font-size: 0.75rem;
		color: var(--ink-muted, #6b7280);
	}
	.btn-close {
		border: none;
		background: transparent;
		font-size: 1.3rem;
		cursor: pointer;
		color: var(--ink-muted, #6b7280);
	}
	.drawer-section {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--ink-muted, #6b7280);
		margin: 0.5rem 0 -0.25rem;
	}
	.drawer-meta {
		display: grid;
		grid-template-columns: 6rem 1fr;
		row-gap: 0.35rem;
		column-gap: 0.5rem;
		margin: 0;
		font-size: 0.8rem;
	}
	.drawer-meta dt {
		color: var(--ink-muted, #6b7280);
	}
	.drawer-meta dd {
		margin: 0;
		word-break: break-all;
	}
	.drawer-meta .status-warn {
		color: #b45309;
	}
	.drawer-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 0.5rem;
	}

	.btn-ghost,
	.btn-primary,
	.btn-apply,
	.btn-link {
		font-size: 0.8rem;
		padding: 0.4rem 0.75rem;
		border-radius: 8px;
		border: 1px solid var(--border-soft, rgba(0, 0, 0, 0.08));
		background: var(--surface, #fff);
		cursor: pointer;
	}
	.btn-ghost:hover {
		background: var(--brand-soft, rgba(58, 122, 254, 0.08));
	}
	.btn-primary {
		background: var(--brand, #3a7afe);
		color: #fff;
		border-color: var(--brand, #3a7afe);
	}
	.btn-primary:hover {
		filter: brightness(1.05);
	}
	.btn-apply {
		background: #16a34a;
		color: #fff;
		border-color: #16a34a;
	}
	.btn-apply:hover {
		filter: brightness(1.05);
	}
	.btn-link {
		background: transparent;
		border: none;
		text-decoration: underline;
		color: var(--brand, #3a7afe);
	}
	.btn-ghost-active {
		background: var(--brand-soft, rgba(58, 122, 254, 0.12));
		border-color: var(--brand, #3a7afe);
		color: var(--brand, #3a7afe);
	}
	.btn-primary:disabled,
	.btn-ghost:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.check-bar {
		position: sticky;
		top: 0;
		z-index: 5;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		padding: 0.55rem 0.85rem;
		background: var(--brand-soft, rgba(58, 122, 254, 0.08));
		border: 1px solid var(--brand, #3a7afe);
		border-radius: 10px;
	}
	.check-bar-info {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		font-size: 0.85rem;
		color: var(--ink-strong, #1f2330);
	}
	.check-bar-count {
		font-weight: 600;
	}
	.check-bar-actions {
		display: flex;
		gap: 0.5rem;
	}

	.mat-bottom {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0.6rem 0.85rem;
		font-size: 0.8rem;
		height: 100%;
		min-height: 0;
	}
	/* Header stays pinned, table scrolls inside this wrapper. The parent
	   .shell-bottom has overflow:hidden + fixed height, so we have to give
	   this wrapper min-height:0 + overflow-y:auto to actually let it
	   scroll instead of pushing the panel taller. */
	.mat-bottom-scroll {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
	}
	.mat-bottom-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.75rem;
	}
	.mat-bottom-title-row {
		display: flex;
		align-items: center;
		gap: 0.55rem;
	}
	.mat-bottom-title {
		font-weight: 600;
		color: var(--ink-strong, #1f2330);
	}
	.mat-bottom-counts {
		display: inline-flex;
		gap: 0.4rem;
		margin-left: 0.25rem;
	}
	.mat-count {
		font-size: 0.7rem;
		padding: 0.1rem 0.45rem;
		border-radius: 999px;
		background: rgba(0, 0, 0, 0.06);
		color: var(--ink-muted, #6b7280);
	}
	.mat-count-running {
		background: rgba(58, 122, 254, 0.12);
		color: var(--brand, #3a7afe);
	}
	.mat-count-success {
		background: rgba(31, 122, 63, 0.12);
		color: #1f7a3f;
	}
	.mat-count-failed {
		background: rgba(185, 28, 28, 0.12);
		color: #b91c1c;
	}
	.mat-bottom-dot {
		display: inline-block;
		width: 0.55rem;
		height: 0.55rem;
		border-radius: 999px;
		background: rgba(0, 0, 0, 0.18);
	}
	.mat-bottom-dot.active {
		background: var(--brand, #3a7afe);
		box-shadow: 0 0 0 0 rgba(58, 122, 254, 0.6);
		animation: mat-bottom-pulse 1.4s infinite;
	}
	@keyframes mat-bottom-pulse {
		0% { box-shadow: 0 0 0 0 rgba(58, 122, 254, 0.55); }
		70% { box-shadow: 0 0 0 8px rgba(58, 122, 254, 0); }
		100% { box-shadow: 0 0 0 0 rgba(58, 122, 254, 0); }
	}
	.mat-bottom-clear {
		font-size: 0.72rem;
		padding: 0.25rem 0.55rem;
		border: 1px solid var(--border-soft, rgba(0, 0, 0, 0.08));
		background: var(--surface, #fff);
		border-radius: 6px;
		cursor: pointer;
		color: var(--ink-muted, #6b7280);
	}
	.mat-bottom-clear:hover:not(:disabled) {
		background: rgba(0, 0, 0, 0.04);
		color: var(--ink-strong, #1f2330);
	}
	.mat-bottom-clear:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.mat-bottom-empty {
		padding: 0.4rem 0;
	}
	.mat-bottom-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.78rem;
	}
	.mat-bottom-table th,
	.mat-bottom-table td {
		text-align: left;
		padding: 0.3rem 0.55rem;
		border-bottom: 1px solid var(--border-soft, rgba(0, 0, 0, 0.06));
		vertical-align: middle;
	}
	.mat-bottom-table th {
		font-weight: 500;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ink-muted, #6b7280);
	}
	.mat-bottom-table td.num,
	.mat-bottom-table th.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.mat-bottom-row-running {
		background: rgba(58, 122, 254, 0.04);
	}
	.mat-bottom-row-failed {
		background: rgba(185, 28, 28, 0.04);
	}
	.mat-row-status {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		font-weight: 500;
		white-space: nowrap;
	}
	.mat-row-status-running {
		color: var(--brand, #3a7afe);
	}
	.mat-row-status-success {
		color: #1f7a3f;
	}
	.mat-row-status-failed {
		color: #b91c1c;
	}
	.mat-row-key {
		opacity: 0.6;
		font-size: 0.72rem;
	}
	.mat-row-note {
		max-width: 26rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mat-row-error {
		color: #b91c1c;
	}
	.mat-row-stage {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		max-width: 24rem;
	}
	.mat-row-stage-label {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ink-muted, #6b7280);
	}
	.mat-bottom-row-failed .mat-row-stage-label {
		color: #b91c1c;
	}
	.mat-row-stage-msg {
		font-size: 0.78rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mat-row-bytebar {
		display: block;
		width: 100%;
		max-width: 22rem;
		height: 4px;
		margin-top: 0.2rem;
		background: rgba(148, 163, 184, 0.25);
		border-radius: 2px;
		overflow: hidden;
	}
	.mat-row-bytebar-fill {
		display: block;
		height: 100%;
		background: linear-gradient(90deg, #2563eb, #3b82f6);
		transition: width 0.4s ease;
	}
	.mat-row-speed {
		display: block;
		font-size: 0.7rem;
		font-variant-numeric: tabular-nums;
		margin-top: 0.15rem;
	}
	.mat-bottom-spinner {
		display: inline-block;
		width: 0.7rem;
		height: 0.7rem;
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 50%;
		animation: mat-bottom-spin 0.8s linear infinite;
	}
	@keyframes mat-bottom-spin {
		to { transform: rotate(360deg); }
	}
	.mat-bottom-toasts {
		list-style: none;
		margin: 0;
		padding: 0.25rem 0 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}
	.mat-bottom-toast {
		padding: 0.2rem 0.55rem;
		border-radius: 6px;
		background: rgba(31, 35, 48, 0.08);
		color: var(--ink-strong, #1f2330);
		font-size: 0.75rem;
	}
	.mat-bottom-toast.err {
		background: rgba(185, 28, 28, 0.12);
		color: #b91c1c;
	}
</style>
