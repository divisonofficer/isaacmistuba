<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { lang } from '$lib/stores/lang';
	import { listJobs, retryJob, cancelJob, getJobLog } from '$lib/api';

	const L = $derived($lang);

	type Job = Record<string, string | number | null>;

	const STAGES = [
		{ key: 'starting',         en: 'Start',     kr: '시작' },
		{ key: 'staging_scene',    en: 'Stage XML', kr: 'XML 준비' },
		{ key: 'loading_scene',    en: 'Load GPU',  kr: 'GPU 로드' },
		{ key: 'rendering',        en: 'Render',    kr: '렌더링' },
		{ key: 'saving_output',    en: 'Save EXR',  kr: 'EXR 저장' },
		{ key: 'writing_manifest', en: 'Manifest',  kr: '매니페스트' },
		{ key: 'complete',         en: 'Done',      kr: '완료' },
	];

	const STAGE_ORDER: Record<string, number> = Object.fromEntries(STAGES.map((s, i) => [s.key, i]));

	function stageIndex(stage: string | null | undefined): number {
		if (!stage) return -1;
		if (stage in STAGE_ORDER) return STAGE_ORDER[stage];
		// sub-stages map to 'rendering'
		if (['ambient', 'active', 'polar'].includes(stage)) return STAGE_ORDER['rendering'];
		return -1;
	}

	let jobs: Job[] = $state([]);
	let filter = $state<'all' | 'running' | 'failed' | 'stuck'>('all');
	let loading = $state(true);
	let logModal = $state<{ jobId: string; lines: string[] } | null>(null);
	let logLoading = $state(false);
	let expandedLogs = $state<Record<string, string[]>>({});
	let timer: ReturnType<typeof setInterval>;

	async function refresh() {
		try { jobs = (await listJobs(100)).jobs ?? []; } catch {}
		loading = false;
	}

	async function refreshRunningLogs() {
		const running = jobs.filter(j => j.status === 'running');
		await Promise.all(running.map(async (j) => {
			try {
				const r = await getJobLog(String(j.job_id), 20);
				expandedLogs[String(j.job_id)] = r.lines ?? [];
			} catch {}
		}));
		expandedLogs = { ...expandedLogs };
	}

	onMount(async () => {
		await refresh();
		await refreshRunningLogs();
		timer = setInterval(async () => {
			await refresh();
			if (jobs.some(j => j.status === 'running')) await refreshRunningLogs();
		}, 2500);
	});
	onDestroy(() => clearInterval(timer));

	async function retry(jobId: string) {
		try { await retryJob(jobId); await refresh(); } catch {}
	}

	async function cancel(jobId: string) {
		try { await cancelJob(jobId); await refresh(); } catch {}
	}

	async function viewLog(jobId: string) {
		logLoading = true;
		logModal = { jobId, lines: [] };
		try {
			const r = await getJobLog(jobId, 500);
			logModal = { jobId, lines: r.lines ?? [] };
		} catch {
			logModal = { jobId, lines: ['Failed to load log'] };
		}
		logLoading = false;
	}

	const filtered = $derived(jobs.filter((j) => {
		if (filter === 'all') return true;
		if (filter === 'running') return j.status === 'running';
		if (filter === 'failed') return j.status === 'failed';
		if (filter === 'stuck') return j.status === 'running' && Number(j.elapsed_s ?? 0) > 600;
		return true;
	}));

	function statusClass(s: string) {
		if (s === 'succeeded') return 'badge-succeeded';
		if (s === 'failed') return 'badge-failed';
		if (s === 'running') return 'badge-running';
		if (s === 'cancelled') return 'badge-cancelled';
		return 'badge-queued';
	}

	function ago(ts: string | null) {
		if (!ts) return '—';
		const s = Math.round((Date.now() - new Date(ts).getTime()) / 1000);
		if (s < 60) return `${s}s`;
		if (s < 3600) return `${Math.round(s / 60)}m`;
		return `${Math.round(s / 3600)}h`;
	}

	function colorLine(line: string) {
		if (line.includes('[FAILED]')) return 'color:#dc2626';
		if (line.includes('[COMPLETE]')) return 'color:#16a34a';
		if (line.includes('[RUNNING]') || line.includes('[START]') || line.includes('[PROGRESS]')) return 'color:#2563eb';
		return 'opacity:0.7';
	}

	// Parse last log line for live info (camera, pass, spp)
	function parseLastLine(lines: string[]): string {
		const last = lines[lines.length - 1] ?? '';
		// Extract message part after stage column
		const m = last.match(/\]\s+\S+\s+(.*)/);
		return m ? m[1].trim() : last;
	}
</script>

<!-- Active running job — full progress card -->
{#each jobs.filter(j => j.status === 'running') as job}
	{@const jid = String(job.job_id ?? '')}
	{@const curStage = String(job.active_stage ?? job.progress_stage ?? '')}
	{@const curIdx = stageIndex(curStage)}
	{@const logLines = expandedLogs[jid] ?? []}
	<div class="panel mt-4" style="border-left:3px solid var(--color-amber,#f59e0b)">
		<div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap">
			<span class="status-dot live status-amber" style="width:0.6rem;height:0.6rem;flex-shrink:0"></span>
			<span class="mono text-xs" style="flex:1;overflow:hidden;text-overflow:ellipsis">{jid}</span>
			<span class="muted text-xs">{job.scene_id ?? '—'}</span>
			{#if job.elapsed_s != null}<span class="muted text-xs">{job.elapsed_s}s elapsed</span>{/if}
			<button class="button button-subtle text-xs" onclick={() => viewLog(jid)}>
				{L === 'kr' ? '전체 로그' : 'Full Log'}
			</button>
			<button class="button button-subtle text-xs" onclick={() => cancel(jid)}>
				{L === 'kr' ? '취소' : 'Cancel'}
			</button>
		</div>

		<!-- Stage stepper -->
		<div class="guide-stepper mt-4" style="padding:0.4rem 0 0.75rem">
			{#each STAGES as st, i}
				{@const done = i < curIdx}
				{@const active = i === curIdx}
				<div class="guide-step" style="min-width:5rem">
					<div class="guide-step-badge"
						style="{done ? 'background:var(--color-green,#16a34a)' : active ? 'background:var(--color-blue,#2563eb)' : 'background:var(--muted);opacity:0.4'}"
					>
						{done ? '✓' : active ? '▶' : i + 1}
					</div>
					<div class="guide-step-label" style="font-size:0.68rem;text-align:center;margin-top:0.3rem;{active ? 'font-weight:600' : ''}">
						{L === 'kr' ? st.kr : st.en}
					</div>
				</div>
			{/each}
		</div>

		<!-- Live log tail -->
		{#if logLines.length > 0}
			<div style="background:var(--code-bg,rgba(0,0,0,0.05));border-radius:0.4rem;padding:0.5rem 0.75rem;margin-top:0.5rem;max-height:8rem;overflow-y:auto">
				<pre style="font-size:0.72rem;line-height:1.6;margin:0;white-space:pre-wrap">{#each logLines.slice(-8) as line}<span style={colorLine(line)}>{line}{'\n'}</span>{/each}</pre>
			</div>
		{:else if curStage}
			<div class="muted text-xs mt-2">{curStage.replace(/_/g, ' ')}…</div>
		{/if}
	</div>
{/each}

<!-- Filters + refresh -->
<div class="flex items-center gap-2 mt-4" style="flex-wrap:wrap">
	{#each ['all', 'running', 'failed', 'stuck'] as f}
		<button
			class="button button-subtle text-xs {filter === f ? 'nav-link-active' : ''}"
			onclick={() => filter = f as typeof filter}
		>
			{#if f === 'all'}{L === 'kr' ? '전체' : 'All'}
			{:else if f === 'running'}{L === 'kr' ? '실행 중' : 'Running'}
			{:else if f === 'failed'}{L === 'kr' ? '실패' : 'Failed'}
			{:else}{L === 'kr' ? '지연' : 'Stuck'}{/if}
		</button>
	{/each}
	<button class="button button-subtle text-xs" onclick={refresh} style="margin-left:auto">↻</button>
</div>

{#if loading}
	<div class="muted text-sm mt-4">{L === 'kr' ? '로딩 중…' : 'Loading…'}</div>
{:else if filtered.length === 0}
	<div class="empty-state-illustrated mt-6">
		<div class="empty-icon">📋</div>
		<div class="empty-title">{L === 'kr' ? '잡 없음' : 'No jobs'}</div>
	</div>
{:else}
	<div class="table-wrap mt-4">
		<table class="table">
			<thead>
				<tr>
					<th>Job ID</th>
					<th>{L === 'kr' ? '상태' : 'Status'}</th>
					<th>{L === 'kr' ? '진행 단계' : 'Stage'}</th>
					<th>{L === 'kr' ? '씬' : 'Scene'}</th>
					<th>{L === 'kr' ? '경과' : 'Elapsed'}</th>
					<th>{L === 'kr' ? '완료' : 'Finished'}</th>
					<th>{L === 'kr' ? '동작' : 'Actions'}</th>
				</tr>
			</thead>
			<tbody>
				{#each filtered as job}
					{@const jid = String(job.job_id ?? '')}
					{@const curStage = String(job.active_stage ?? job.progress_stage ?? '')}
					<tr>
						<td class="mono text-xs" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
							{jid.slice(0, 26)}
						</td>
						<td><span class="badge {statusClass(String(job.status ?? ''))}">{job.status}</span></td>
						<td>
							{#if job.status === 'running' && curStage}
								<!-- Mini stage bar -->
								<div style="display:flex;gap:2px;align-items:center">
									{#each STAGES as st, i}
										{@const idx = stageIndex(curStage)}
										<div style="width:0.6rem;height:0.6rem;border-radius:50%;background:{i < idx ? 'var(--color-green,#16a34a)' : i === idx ? 'var(--color-blue,#2563eb)' : 'rgba(0,0,0,0.1)'}"></div>
									{/each}
									<span class="text-xs muted" style="margin-left:0.3rem">{curStage.replace(/_/g, ' ')}</span>
								</div>
							{:else}
								<span class="text-xs muted">{curStage || '—'}</span>
							{/if}
						</td>
						<td class="text-sm">{job.scene_id ?? '—'}</td>
						<td class="text-sm muted">{job.elapsed_s != null ? `${job.elapsed_s}s` : '—'}</td>
						<td class="text-sm muted">{job.finished_at ? ago(String(job.finished_at)) : '—'}</td>
						<td>
							<div class="flex gap-2">
								<button class="button button-subtle text-xs" onclick={() => viewLog(jid)}>
									{L === 'kr' ? '로그' : 'Log'}
								</button>
								{#if job.status === 'failed' || job.status === 'cancelled'}
									<button class="button button-subtle text-xs" onclick={() => retry(jid)}>
										{L === 'kr' ? '재시도' : 'Retry'}
									</button>
								{/if}
								{#if job.status === 'queued' || job.status === 'running'}
									<button class="button button-subtle text-xs" onclick={() => cancel(jid)}>
										{L === 'kr' ? '취소' : 'Cancel'}
									</button>
								{/if}
							</div>
						</td>
					</tr>
					{#if job.error}
						<tr>
							<td colspan={7} class="mono text-xs" style="padding-left:1.5rem;color:#dc2626">{job.error}</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<!-- Log modal -->
{#if logModal}
	<div
		style="position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:200;display:flex;align-items:center;justify-content:center"
		role="button" tabindex="-1"
		onclick={() => logModal = null}
		onkeydown={(e) => e.key === 'Escape' && (logModal = null)}
	>
		<div
			class="panel"
			style="width:min(860px,96vw);max-height:82vh;display:flex;flex-direction:column;gap:0"
			role="dialog"
			aria-modal="true"
			tabindex="-1"
			onclick={(e) => e.stopPropagation()}
			onkeydown={() => {}}
		>
			<div class="panel-header">
				<span class="panel-label mono text-xs">{logModal.jobId.slice(0, 30)}</span>
				<button class="button button-subtle text-xs" onclick={() => logModal = null}>✕</button>
			</div>
			<!-- Stage overview in modal -->
			{#each jobs.filter(j => String(j.job_id) === logModal!.jobId) as job}
				{@const curStage = String(job.active_stage ?? job.progress_stage ?? '')}
				{@const curIdx = stageIndex(curStage)}
				<div class="guide-stepper mt-3" style="padding:0.25rem 0 0.5rem">
					{#each STAGES as st, i}
						<div class="guide-step" style="min-width:4rem">
							<div class="guide-step-badge"
								style="width:1.4rem;height:1.4rem;font-size:0.65rem;{i < curIdx ? 'background:var(--color-green,#16a34a)' : i === curIdx ? 'background:var(--color-blue,#2563eb)' : 'background:var(--muted);opacity:0.35'}"
							>{i < curIdx ? '✓' : i === curIdx ? '▶' : i + 1}</div>
							<div class="guide-step-label" style="font-size:0.6rem;text-align:center">{L === 'kr' ? st.kr : st.en}</div>
						</div>
					{/each}
				</div>
			{/each}
			<div style="flex:1;overflow-y:auto;margin-top:0.5rem">
				{#if logLoading}
					<div class="muted text-sm">{L === 'kr' ? '로그 로딩 중…' : 'Loading log…'}</div>
				{:else}
					<pre style="font-size:0.73rem;line-height:1.65;white-space:pre-wrap;margin:0">{#each logModal.lines as line}<span style={colorLine(line)}>{line}{'\n'}</span>{/each}</pre>
				{/if}
			</div>
		</div>
	</div>
{/if}
