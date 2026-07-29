<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { listOpticalNavProjects, getOpticalNavProject } from '$lib/api';
	import InfinigenGeneratePanel from '$lib/datasets/InfinigenGeneratePanel.svelte';

	type SceneRow = {
		project_id: string;
		scene_id: string;
		render_scene?: string;
		annotation_ok?: boolean;
		node_count?: number;
		object_count?: number | null;
		area_m2?: number | null;
		updated_mtime?: number | null;
		updated_at?: string | null;
	};

	type SortKey = 'name' | 'date' | 'objects' | 'area';

	let projects = $state<any[]>([]);
	let scenes = $state<SceneRow[]>([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let genProjectId = $state('');
	let showGenerate = $state(false);
	let sortKey = $state<SortKey>('name');
	let sortDir = $state<'asc' | 'desc'>('asc');

	async function load() {
		loading = true;
		error = '';
		try {
			const pr = await listOpticalNavProjects();
			projects = pr.projects ?? [];
			if (!genProjectId && projects.length) genProjectId = projects[0].project_id;
			const rows: SceneRow[] = [];
			for (const p of projects) {
				try {
					const detail = await getOpticalNavProject(p.project_id);
					for (const s of detail.scenes ?? []) {
						rows.push({
							project_id: p.project_id,
							scene_id: s.scene_id,
							render_scene: s.sync_status?.render_scene ?? s.sync_status?.render_scene_status,
							annotation_ok: s.annotation_ok,
							node_count: s.viewpoint_graph?.node_count,
							object_count: s.object_count,
							area_m2: s.area_m2,
							updated_mtime: s.updated_mtime,
							updated_at: s.updated_at
						});
					}
				} catch {
					/* skip unreadable project */
				}
			}
			scenes = rows;
		} catch (e) {
			error = String(e);
		}
		loading = false;
	}
	onMount(load);

	function setSort(key: SortKey) {
		if (sortKey === key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else { sortKey = key; sortDir = key === 'name' ? 'asc' : 'desc'; }
	}

	const rows = $derived.by(() => {
		const q = search.trim().toLowerCase();
		const filtered = scenes.filter(
			(s) => !q || s.scene_id.toLowerCase().includes(q) || s.project_id.toLowerCase().includes(q)
		);
		const dir = sortDir === 'asc' ? 1 : -1;
		const val = (s: SceneRow): number | string =>
			sortKey === 'name' ? s.scene_id.toLowerCase()
			: sortKey === 'date' ? (s.updated_mtime ?? 0)
			: sortKey === 'objects' ? (s.object_count ?? -1)
			: (s.area_m2 ?? -1);
		return [...filtered].sort((a, b) => {
			const av = val(a), bv = val(b);
			if (av < bv) return -dir;
			if (av > bv) return dir;
			return a.scene_id.localeCompare(b.scene_id);
		});
	});

	function openEditor(row: SceneRow) {
		goto(`/datasets?project=${encodeURIComponent(row.project_id)}&scene=${encodeURIComponent(row.scene_id)}`);
	}

	const fmtDate = (iso?: string | null) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—');
	const arrow = (key: SortKey) => (sortKey !== key ? '' : sortDir === 'asc' ? ' ▲' : ' ▼');
</script>

<div class="page">
	<header class="page-head">
		<div>
			<h1>Nav Dataset Scenes</h1>
			<p class="sub">OpticalNav 데이터셋 씬 목록. 헤더를 클릭해 정렬하고, 행을 클릭하면 에디터로 이동합니다.</p>
		</div>
		<div class="head-actions">
			<input class="search" placeholder="scene / project 검색" bind:value={search} />
			<button class="button button-subtle" onclick={load} disabled={loading}>{loading ? '…' : '새로고침'}</button>
			<button class="button button-primary" onclick={() => (showGenerate = !showGenerate)}>
				{showGenerate ? '생성 패널 닫기' : '＋ 씬 생성'}
			</button>
		</div>
	</header>

	{#if showGenerate}
		<section class="gen-card">
			<label class="gen-project">
				<span>대상 프로젝트</span>
				<select bind:value={genProjectId}>
					{#each projects as p}<option value={p.project_id}>{p.project_id}</option>{/each}
				</select>
			</label>
			<InfinigenGeneratePanel projectId={genProjectId} onDone={load} />
		</section>
	{/if}

	{#if error}<p class="err">{error}</p>{/if}

	{#if loading}
		<p class="muted">불러오는 중…</p>
	{:else if rows.length === 0}
		<p class="muted">씬이 없습니다. "＋ 씬 생성" 으로 첫 씬을 만들어 보세요.</p>
	{:else}
		<div class="count">{rows.length} scenes</div>
		<table class="scene-table">
			<thead>
				<tr>
					<th class="sortable" onclick={() => setSort('name')}>이름{arrow('name')}</th>
					<th>project</th>
					<th class="sortable num" onclick={() => setSort('objects')}>오브젝트{arrow('objects')}</th>
					<th class="sortable num" onclick={() => setSort('area')}>넓이(㎡){arrow('area')}</th>
					<th class="num">nodes</th>
					<th class="sortable" onclick={() => setSort('date')}>수정일{arrow('date')}</th>
					<th>상태</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as row (row.project_id + '/' + row.scene_id)}
					<tr onclick={() => openEditor(row)} title="에디터에서 열기">
						<td class="name">{row.scene_id}</td>
						<td class="dim">{row.project_id}</td>
						<td class="num">{row.object_count ?? '—'}</td>
						<td class="num">{row.area_m2 ?? '—'}</td>
						<td class="num">{row.node_count ?? '—'}</td>
						<td class="dim">{fmtDate(row.updated_at)}</td>
						<td>
							<span class="badge" data-on={row.annotation_ok ? '1' : '0'}>{row.annotation_ok ? 'ann ✓' : 'ann —'}</span>
							<span class="badge" data-rs={row.render_scene ?? 'pending'}>{row.render_scene ?? 'pending'}</span>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.page { padding: 20px 24px; max-width: 1200px; margin: 0 auto; }
	.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
	.page-head h1 { margin: 0 0 4px; font-size: 22px; }
	.sub { margin: 0; font-size: 13px; opacity: 0.7; max-width: 64ch; }
	.head-actions { display: flex; gap: 8px; align-items: center; }
	.search { padding: 6px 10px; min-width: 200px; }
	.gen-card { margin-top: 16px; padding: 14px; border: 1px solid var(--line, #d9dee8); border-radius: 8px; background: var(--paper, #fff); }
	.gen-project { display: flex; flex-direction: column; gap: 2px; font-size: 12px; margin-bottom: 10px; max-width: 320px; }
	.gen-project span { opacity: 0.7; }
	.count { margin: 16px 0 6px; font-size: 12px; opacity: 0.6; }
	.scene-table { width: 100%; border-collapse: collapse; font-size: 13px; }
	.scene-table th, .scene-table td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--line, #e6eaf1); }
	.scene-table th { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.6; user-select: none; }
	.scene-table th.sortable { cursor: pointer; }
	.scene-table th.sortable:hover { opacity: 1; color: var(--accent, #1d5fd1); }
	.scene-table th.num, .scene-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
	.scene-table tbody tr { cursor: pointer; }
	.scene-table tbody tr:hover { background: rgba(47, 123, 246, 0.06); }
	.scene-table td.name { font-weight: 600; word-break: break-all; }
	.scene-table td.dim { opacity: 0.65; }
	.badge { font-size: 10px; padding: 1px 7px; border-radius: 10px; background: #eef2f7; color: #334; margin-right: 4px; }
	.badge[data-on='1'] { background: #e3f3ea; color: #087443; }
	.badge[data-rs='synced'] { background: #e3f3ea; color: #087443; }
	.err { color: #c0392b; }
	.muted { opacity: 0.6; margin-top: 20px; }
</style>
