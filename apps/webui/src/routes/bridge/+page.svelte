<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { lang } from '$lib/stores/lang';
	import { listIsaacCommands, listJobs, getIsaacSession, isaacCommand, smokeRender, listIsaacScenes } from '$lib/api';

	type Command = Record<string, string | null>;
	type Job = Record<string, string | null>;
	type Session = Record<string, unknown> | null;

	let commands: Command[] = $state([]);
	let jobs: Job[] = $state([]);
	let session: Session = $state(null);
	let registeredScenes: Record<string, unknown>[] = $state([]);
	let loading = $state(true);
	let timer: ReturnType<typeof setInterval>;

	const PIPELINE_STEPS = [
		{ key: 'scene_loaded',       en: 'Scene Loaded',       kr: '씬 로드',         icon: '📂' },
		{ key: 'session_connected',  en: 'Session Connected',  kr: '세션 연결',        icon: '🔗' },
		{ key: 'render_dispatched',  en: 'Render Dispatched',  kr: '렌더 디스패치',    icon: '🚀' },
		{ key: 'render_complete',    en: 'Render Complete',    kr: '렌더 완료',        icon: '✅' }
	];

	const CMD_TO_STEP: Record<string, string> = {
		load_scene: 'scene_loaded',
		connect_session: 'session_connected',
		prepare_render_ready: 'session_connected',
		render_current_view: 'render_dispatched',
		render_sensor: 'render_dispatched'
	};

	let activeSteps = $state<Set<string>>(new Set());
	let cmdPending = $state<string | null>(null);
	let cmdMsg = $state('');

	async function sendCommand(cmd: string, sceneId?: string) {
		if (cmdPending) return;
		cmdPending = cmd;
		cmdMsg = '';
		try {
			await isaacCommand(cmd, sceneId);
			cmdMsg = L === 'kr' ? `${cmd} 전송됨` : `${cmd} sent`;
			await refresh();
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally {
			cmdPending = null;
		}
	}

	async function handleSmokeRender(sceneId: string) {
		if (cmdPending) return;
		cmdPending = 'smoke';
		cmdMsg = '';
		try {
			await smokeRender(sceneId);
			cmdMsg = 'Smoke queued';
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally {
			cmdPending = null;
		}
	}

	async function refresh() {
		try {
			const [cmdRes, jobRes, sessRes, scenesRes] = await Promise.all([
				listIsaacCommands(),
				listJobs(20),
				getIsaacSession().catch(() => null),
				listIsaacScenes().catch(() => ({ scenes: [] }))
			]);
			commands = (cmdRes.commands ?? []).slice(0, 12);
			jobs = (jobRes.jobs ?? []).slice(0, 10);
			session = sessRes?.status === 'active' ? sessRes.session as Session : null;
			registeredScenes = (scenesRes.scenes ?? []).slice(0, 8);

			const steps = new Set<string>();
			for (const cmd of commands) {
				const step = CMD_TO_STEP[cmd.command_type ?? ''];
				if (step && (cmd.status === 'succeeded' || cmd.status === 'running')) steps.add(step);
			}
			if (session) steps.add('session_connected');
			if (jobs.some((j) => j.status === 'succeeded')) steps.add('render_complete');
			activeSteps = steps;
		} catch {}
		loading = false;
	}

	onMount(async () => {
		await refresh();
		timer = setInterval(refresh, 3000);
	});

	onDestroy(() => clearInterval(timer));

	function statusClass(s: string) {
		if (s === 'succeeded') return 'badge-succeeded';
		if (s === 'failed') return 'badge-failed';
		if (s === 'running') return 'badge-running';
		return 'badge-queued';
	}

	function ago(ts: string | null) {
		if (!ts) return '—';
		const s = Math.round((Date.now() - new Date(ts).getTime()) / 1000);
		if (s < 60) return `${s}s ago`;
		if (s < 3600) return `${Math.round(s / 60)}m ago`;
		return `${Math.round(s / 3600)}h ago`;
	}

	const L = $derived($lang);
</script>

<!-- Current Scene Session -->
<div class="panel mt-4">
	<div class="panel-header">
		<span class="panel-label">{L === 'kr' ? '현재 세션' : 'Current Session'}</span>
		{#if session}
			<span class="badge badge-succeeded">{L === 'kr' ? '활성' : 'active'}</span>
		{:else}
			<span class="badge badge-cancelled">{L === 'kr' ? '비활성' : 'inactive'}</span>
		{/if}
	</div>

	{#if session}
		{@const s = session as Record<string, unknown>}
		<div class="grid lg:grid-cols-4 gap-3 mt-3">
			<div class="subpanel">
				<div class="text-xs muted">{L === 'kr' ? '씬 ID' : 'Scene ID'}</div>
				<div class="text-sm" style="margin-top:0.3rem;font-weight:600">{s.scene_id ?? '—'}</div>
			</div>
			<div class="subpanel">
				<div class="text-xs muted">{L === 'kr' ? '리비전' : 'Revision'}</div>
				<div class="text-sm" style="margin-top:0.3rem;font-weight:600">{s.session_revision ?? '—'}</div>
			</div>
			<div class="subpanel">
				<div class="text-xs muted">{L === 'kr' ? '상태 동기화' : 'State Sync'}</div>
				<div class="text-sm" style="margin-top:0.3rem;font-weight:600">
					{s.state_dirty ? (L === 'kr' ? '⚠ 동기화 필요' : '⚠ dirty') : (L === 'kr' ? '✓ 동기화됨' : '✓ clean')}
				</div>
			</div>
			<div class="subpanel">
				<div class="text-xs muted">{L === 'kr' ? '열린 시각' : 'Opened'}</div>
				<div class="text-sm" style="margin-top:0.3rem">{ago(String(s.opened_at ?? ''))}</div>
			</div>
		</div>
		{#if s.scene_id}
			<div class="mt-3" style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center">
				<button class="button button-subtle text-xs" onclick={() => sendCommand('connect_session', String(s.scene_id))} disabled={!!cmdPending}>
					{cmdPending === 'connect_session' ? '…' : (L === 'kr' ? '재연결' : 'Reconnect')}
				</button>
				<button class="button button-subtle text-xs" onclick={() => sendCommand('sync_session', String(s.scene_id))} disabled={!!cmdPending}>
					{cmdPending === 'sync_session' ? '…' : (L === 'kr' ? '동기화' : 'Sync')}
				</button>
				<button class="button button-primary text-xs" onclick={() => sendCommand('render_current_view', String(s.scene_id))} disabled={!!cmdPending}>
					{cmdPending === 'render_current_view' ? '…' : (L === 'kr' ? '렌더' : 'Render')}
				</button>
				<button class="button button-subtle text-xs" onclick={() => handleSmokeRender(String(s.scene_id))} disabled={!!cmdPending}>
					{cmdPending === 'smoke' ? '…' : '🧪 Smoke'}
				</button>
				<a href="/scenes/{s.scene_id}" class="button button-subtle text-xs">
					{L === 'kr' ? '씬 상세 →' : 'Scene Detail →'}
				</a>
				{#if cmdMsg}<span class="text-xs muted">{cmdMsg}</span>{/if}
			</div>
		{/if}
	{:else}
		<div class="mt-3">
			<p class="muted text-sm" style="margin-bottom:0.75rem">
				{L === 'kr' ? 'Isaac Sim에서 세션을 열어주세요. 또는 등록된 씬에서 연결하세요.' : 'No active session. Connect from a registered scene below.'}
			</p>
			{#if registeredScenes.length > 0}
				<div class="table-wrap">
					<table class="table">
						<thead>
							<tr>
								<th>Scene ID</th>
								<th>{L === 'kr' ? '렌더 준비' : 'Render Ready'}</th>
								<th>{L === 'kr' ? '동작' : 'Action'}</th>
							</tr>
						</thead>
						<tbody>
							{#each registeredScenes as sc}
								{@const s = sc as Record<string, unknown>}
								<tr>
									<td class="mono text-xs">{s.scene_id ?? '—'}</td>
									<td>
										{#if s.render_ready}
											<span class="badge badge-succeeded">{L === 'kr' ? '준비됨' : 'ready'}</span>
										{:else}
											<span class="badge badge-queued">{L === 'kr' ? '미준비' : 'not ready'}</span>
										{/if}
									</td>
									<td style="display:flex;gap:0.4rem;flex-wrap:wrap">
										<button class="button button-primary text-xs" onclick={() => sendCommand('connect_session', String(s.scene_id))} disabled={!!cmdPending}>
											{cmdPending === 'connect_session' ? '…' : (L === 'kr' ? '연결' : 'Connect')}
										</button>
										<button class="button button-subtle text-xs" onclick={() => sendCommand('load_scene', String(s.scene_id))} disabled={!!cmdPending}>
											{cmdPending === 'load_scene' ? '…' : (L === 'kr' ? '불러오기' : 'Load')}
										</button>
										<a href="/scenes/{s.scene_id}" class="button button-subtle text-xs">→</a>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<p class="muted text-xs">{L === 'kr' ? '등록된 씬 없음. Isaac Sim에서 씬을 먼저 준비해주세요.' : 'No registered scenes. Prepare a scene from Isaac Sim first.'}</p>
			{/if}
			{#if cmdMsg}<p class="text-xs muted mt-2">{cmdMsg}</p>{/if}
		</div>
	{/if}
</div>

<!-- Pipeline track -->
<div class="panel mt-4">
	<div class="panel-label">{L === 'kr' ? '파이프라인 단계' : 'Pipeline Stages'}</div>
	<div class="guide-stepper mt-4" style="padding:0.5rem 0 1rem">
		{#each PIPELINE_STEPS as step, i}
			{@const active = activeSteps.has(step.key)}
			<div class="guide-step">
				<div class="guide-step-badge" style="{active ? '' : 'background:var(--muted);opacity:0.5'}">
					{active ? '✓' : i + 1}
				</div>
				<div class="guide-step-label">{step.icon}<br>{L === 'kr' ? step.kr : step.en}</div>
			</div>
		{/each}
	</div>
</div>

<div class="grid lg:grid-cols-[1.1fr,1fr] gap-4 mt-4">
	<!-- Isaac Commands -->
	<div class="panel">
		<div class="panel-label">{L === 'kr' ? '최근 Isaac 명령' : 'Recent Isaac Commands'}</div>
		{#if loading}
			<div class="muted text-sm mt-3">{L === 'kr' ? '로딩 중…' : 'Loading…'}</div>
		{:else if commands.length === 0}
			<div class="empty-state mt-3">{L === 'kr' ? '명령 없음' : 'No commands yet'}</div>
		{:else}
			<div class="table-wrap mt-3">
				<table class="table">
					<thead>
						<tr>
							<th>{L === 'kr' ? '유형' : 'Type'}</th>
							<th>{L === 'kr' ? '씬' : 'Scene'}</th>
							<th>{L === 'kr' ? '상태' : 'Status'}</th>
							<th>{L === 'kr' ? '단계' : 'Stage'}</th>
							<th>{L === 'kr' ? '업데이트' : 'Updated'}</th>
						</tr>
					</thead>
					<tbody>
						{#each commands as cmd}
							<tr>
								<td class="text-sm">{cmd.command_type}</td>
								<td class="text-sm muted">{cmd.scene_id ?? '—'}</td>
								<td><span class="badge {statusClass(String(cmd.status ?? ''))}">{cmd.status}</span></td>
								<td class="text-xs muted">{cmd.progress_stage ?? '—'}</td>
								<td class="text-xs muted">{ago(cmd.updated_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>

	<!-- Recent Renders -->
	<div class="panel">
		<div class="panel-label">{L === 'kr' ? '최근 렌더' : 'Recent Renders'}</div>
		{#if jobs.length === 0}
			<div class="empty-state mt-3">{L === 'kr' ? '렌더 없음' : 'No renders yet'}</div>
		{:else}
			<div class="table-wrap mt-3">
				<table class="table">
					<thead>
						<tr>
							<th>Job ID</th>
							<th>{L === 'kr' ? '상태' : 'Status'}</th>
							<th>{L === 'kr' ? '완료' : 'Finished'}</th>
						</tr>
					</thead>
					<tbody>
						{#each jobs as job}
							<tr>
								<td class="mono text-xs">{String(job.job_id ?? '').slice(0, 20)}</td>
								<td><span class="badge {statusClass(String(job.status ?? ''))}">{job.status}</span></td>
								<td class="muted text-xs">{job.finished_at ? ago(job.finished_at) : '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>
