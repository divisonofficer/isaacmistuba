<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { healthStore, backendOffline, backendOfflineReason } from '$lib/stores/health';
	import { debugToasts, startDebugPolling, stopDebugPolling, kindIcon } from '$lib/stores/debugEvents';
	import { lang } from '$lib/stores/lang';
	import { initTheme } from '$lib/stores/theme';
	import { rightRailCollapsed, bottomPanelCollapsed, bottomPanelMode, toggleRightRail, toggleBottomPanel } from '$lib/stores/shell';
	import { sceneRailSnippet, sceneBottomSnippet } from '$lib/stores/scenePortals';
	import { onMount, onDestroy } from 'svelte';
	import { smokeRender } from '$lib/api';
	import CurrentScenePanel from '$lib/CurrentScenePanel.svelte';
	import { Tooltip } from '$lib/components';
	import { cmdPending, runCmd, currentSceneIdStore, currentSceneStore } from '$lib/stores/sceneCommands';
	import {
		commandResultToasts,
		pushCommandResultToast,
		dismissCommandResultToast,
		commandTypeLabel
	} from '$lib/stores/commandResultToasts';

	let { children } = $props();
	let stopTheme: (() => void) | undefined;
	let menuOpen = $state(false);
	let lastHealthAt = $state<number>(0);

	onMount(() => {
		stopTheme = initTheme();
		startDebugPolling();
		const close = (e: MouseEvent) => {
			if (!menuOpen) return;
			const t = e.target as HTMLElement;
			if (!t.closest('.topbar-overflow')) menuOpen = false;
		};
		window.addEventListener('click', close);
		return () => window.removeEventListener('click', close);
	});
	onDestroy(() => {
		stopDebugPolling();
		stopTheme?.();
	});

	const NAV = [
		{ en: 'Operations',       kr: '운영 홈',          href: '/',               icon: '🏠' },
		{ en: 'Current Session',  kr: '현재 세션',        href: '/current-scene',  icon: '📍' },
		{ en: 'Jobs / Queue',     kr: '작업 / 큐',        href: '/jobs',           icon: '📋' },
		{ en: 'Datasets',         kr: '데이터셋',          href: '/datasets',       icon: 'DN' },
		{ en: 'Camera Rig',       kr: '카메라 리그',      href: '/camera_rig',    icon: 'CAM' },
		{ en: 'Asset Library',    kr: '에셋 라이브러리',  href: '/assets',         icon: '▣' },
		{ en: 'Scene Registry',   kr: '장면 레지스트리',  href: '/scenes',         icon: '🎬' },
		{ en: 'Material Library', kr: '재질 라이브러리',  href: '/materials',      icon: '🎨' },
		{ en: 'Bridge',           kr: '연동 상태 (Bridge)', href: '/bridge',       icon: '🌉' },
		{ en: 'System / Workers', kr: '시스템 / 워커',    href: '/system',         icon: '🖥' },
		{ en: 'Guide',            kr: '가이드',           href: '/guide',          icon: '📘' },
		{ en: 'Settings',         kr: '설정',             href: '/settings',       icon: '⚙' }
	];

	function isActive(href: string) {
		const p = $page.url.pathname;
		return href === '/' ? p === '/' : p.startsWith(href);
	}

	const isCurrentScene = $derived($page.url.pathname.startsWith('/current-scene'));

	type ChipTone = 'ok' | 'warn' | 'err' | 'idle';
	type StatusChip = { label: string; value: string; tone: ChipTone; mono?: boolean };

	function fmtAgo(ts: number, L: 'kr' | 'en'): string {
		if (!ts) return '—';
		const sec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
		if (sec < 60) return L === 'kr' ? `${sec}초 전` : `${sec}s ago`;
		const m = Math.floor(sec / 60);
		if (m < 60) return L === 'kr' ? `${m}분 전` : `${m}m ago`;
		const h = Math.floor(m / 60);
		if (h < 24) return L === 'kr' ? `${h}시간 전` : `${h}h ago`;
		return L === 'kr' ? `${Math.floor(h / 24)}일 전` : `${Math.floor(h / 24)}d ago`;
	}

	$effect(() => {
		if ($healthStore) lastHealthAt = Date.now();
	});

	const TOASTED_IDS_LIMIT = 200;
	const toastedCommandIds: string[] = [];
	const toastedCommandIdSet = new Set<string>();
	function markToasted(id: string) {
		toastedCommandIds.push(id);
		toastedCommandIdSet.add(id);
		while (toastedCommandIds.length > TOASTED_IDS_LIMIT) {
			const old = toastedCommandIds.shift();
			if (old) toastedCommandIdSet.delete(old);
		}
	}
	$effect(() => {
		const latest = $healthStore?.latest_isaac_command as Record<string, unknown> | null | undefined;
		if (!latest) return;
		const id = String(latest.command_id ?? '');
		const status = String(latest.status ?? '');
		if (!id || (status !== 'succeeded' && status !== 'failed')) return;
		if (toastedCommandIdSet.has(id)) return;
		markToasted(id);
		const cmdType = String(latest.command_type ?? '');
		const startedAt = typeof latest.created_at === 'string' ? Date.parse(latest.created_at) : NaN;
		const finishedAt = typeof latest.completed_at === 'string'
			? Date.parse(latest.completed_at)
			: typeof latest.updated_at === 'string'
				? Date.parse(latest.updated_at)
				: NaN;
		const elapsedS = Number.isFinite(startedAt) && Number.isFinite(finishedAt)
			? Math.max(0, Math.round((finishedAt - startedAt) / 1000))
			: undefined;
		pushCommandResultToast({
			id,
			kind: status === 'succeeded' ? 'success' : 'error',
			label: commandTypeLabel(cmdType, $lang),
			message: typeof latest.progress_message === 'string' ? latest.progress_message : undefined,
			elapsedS
		});
	});

	const overallChips = $derived.by((): StatusChip[] => {
		const h = $healthStore;
		const L = $lang;
		const offline = $backendOffline;
		const overall: ChipTone = offline ? 'err' : 'ok';
		const overallVal = offline ? (L === 'kr' ? '오프라인' : 'Offline') : 'Healthy';
		if (!h) {
			return [{ label: L === 'kr' ? '전역 상태' : 'Status', value: overallVal, tone: overall }];
		}
		const isaacOk = !!h.isaac_connected;
		const sceneOk = !!h.isaac_scene_id;
		const queueLen = h.queue_length ?? 0;
		const workerRunning = h.worker_state === 'running';
		const queueTone: ChipTone = queueLen === 0 ? 'ok' : queueLen > 2 ? 'err' : 'warn';
		const queueValue = L === 'kr'
			? (queueLen === 0 ? '0' : `${queueLen} 대기`)
			: (queueLen === 0 ? '0' : `${queueLen} pending`);
		const workerVal = workerRunning ? (L === 'kr' ? '작업 중' : 'Running') : (L === 'kr' ? '대기' : 'Idle');
		return [
			{ label: L === 'kr' ? '전역 상태' : 'Status', value: overallVal, tone: overall },
			{ label: 'Isaac Sim', value: isaacOk ? (L === 'kr' ? '연결됨' : 'Connected') : (L === 'kr' ? '끊김' : 'Disconnected'), tone: isaacOk ? 'ok' : 'err' },
			{ label: L === 'kr' ? '씬' : 'Scene', value: sceneOk ? (L === 'kr' ? '준비됨' : 'Ready') : '—', tone: sceneOk ? 'ok' : 'idle' },
			{ label: 'Bridge', value: isaacOk && sceneOk ? (L === 'kr' ? '정상' : 'Healthy') : (L === 'kr' ? '주의' : 'Degraded'), tone: isaacOk && sceneOk ? 'ok' : 'warn' },
			{ label: L === 'kr' ? '렌더 큐' : 'Render Queue', value: queueValue, tone: queueTone },
			{ label: L === 'kr' ? '워커' : 'Workers', value: workerVal, tone: workerRunning ? 'warn' : 'ok' }
		];
	});

	const sessionChips = $derived.by((): StatusChip[] => {
		const h = $healthStore;
		const L = $lang;
		if (!h?.isaac_scene_id) return [];
		const cmd = h.active_isaac_command as { session_id?: string; camera_name?: string; robot_name?: string } | null;
		const sessionId = cmd?.session_id;
		const camera = cmd?.camera_name;
		const robot = cmd?.robot_name;
		const chips: StatusChip[] = [
			{ label: L === 'kr' ? '현재 세션' : 'Session', value: String(h.isaac_scene_id), tone: 'ok' }
		];
		if (sessionId) chips.push({ label: 'Session ID', value: sessionId, tone: 'idle', mono: true });
		if (camera) chips.push({ label: L === 'kr' ? '카메라' : 'Camera', value: camera, tone: 'idle' });
		if (robot) chips.push({ label: L === 'kr' ? '로봇' : 'Robot', value: robot, tone: 'idle' });
		chips.push({ label: L === 'kr' ? '업데이트' : 'Updated', value: fmtAgo(lastHealthAt, L), tone: 'idle' });
		return chips;
	});

	async function handleSmokeRender() {
		const sceneId = prompt('Smoke render — scene ID:');
		if (!sceneId) return;
		try { await smokeRender(sceneId); } catch {}
	}

	function toggleLang() {
		lang.set($lang === 'kr' ? 'en' : 'kr');
	}

	const effectiveSceneId = $derived(
		(typeof $healthStore?.isaac_scene_id === 'string' ? ($healthStore.isaac_scene_id as string) : null)
		?? $currentSceneIdStore
	);
	const sessionActive = $derived(!!$healthStore?.isaac_connected && !!$healthStore?.isaac_scene_id);
	const activeIsaacCmd = $derived($healthStore?.active_isaac_command as Record<string, unknown> | null);
	const preparingNow = $derived(activeIsaacCmd?.command_type === 'prepare_render_ready');
	const syncingNow = $derived(activeIsaacCmd?.command_type === 'sync_session');
	const renderingNow = $derived(activeIsaacCmd?.command_type === 'render_current_view');

	const isConnected = $derived(!!$healthStore?.isaac_connected);
	const shapeMapReady = $derived(!!$currentSceneStore?.shape_map_exists);
	const mitsubaReady = $derived(!!$currentSceneStore?.mitsuba_scene_exists);
	const renderReady = $derived(shapeMapReady && mitsubaReady);

	type Tip = { title: string; text: string };
	const KR = $derived($lang === 'kr');

	const connectTip = $derived.by((): Tip => {
		if (isConnected)
			return KR
				? { title: '연결됨', text: 'Isaac Sim 세션이 활성 상태예요. 다음 단계로 진행할 수 있어요.' }
				: { title: 'Connected', text: 'Isaac session is active. Move on to Prepare.' };
		if ($cmdPending)
			return KR
				? { title: '잠시만요', text: '다른 명령이 진행 중이에요. 끝나면 자동으로 활성화됩니다.' }
				: { title: 'Hold on', text: 'Another command is running. This will enable when it finishes.' };
		return KR
			? {
					title: 'Isaac Sim 연결',
					text: `${effectiveSceneId} 씬으로 새 세션을 활성화합니다. 처음 연결 시 몇 초 정도 걸려요.`
				}
			: {
					title: 'Connect Isaac Sim',
					text: `Activate a session for the ${effectiveSceneId} scene. The first connect can take a few seconds.`
				};
	});

	const prepareTip = $derived.by((): Tip => {
		if (!isConnected)
			return KR
				? { title: '먼저 연결이 필요해요', text: 'Isaac Sim 에 연결되면 자동으로 장면 준비를 시작할 수 있어요.' }
				: { title: 'Connect first', text: 'After connecting to Isaac Sim you can prepare the scene here.' };
		if (preparingNow)
			return KR
				? { title: '장면 준비 중', text: '백그라운드에서 Mitsuba 씬과 Shape Map 을 만드는 중이에요. 완료되면 렌더 버튼이 활성화됩니다.' }
				: { title: 'Preparing scene', text: 'Building the Mitsuba scene + Shape Map. The Render button will light up when done.' };
		if (renderReady)
			return KR
				? { title: '준비 완료', text: 'Mitsuba 씬과 Shape Map 이 모두 준비됐어요. 바로 렌더할 수 있어요.' }
				: { title: 'Ready', text: 'Both Mitsuba scene and Shape Map are ready. You can render now.' };
		if ($cmdPending)
			return KR
				? { title: '잠시만요', text: '다른 명령이 진행 중이에요. 끝나면 다시 시도할 수 있어요.' }
				: { title: 'Hold on', text: 'Another command is running. Try again when it finishes.' };
		if (!mitsubaReady && !shapeMapReady)
			return KR
				? {
						title: '장면 준비 필요',
						text: 'Mitsuba 씬과 Shape Map 모두 아직 만들어지지 않았어요. 큰 씬은 몇 분 걸릴 수 있어요.'
					}
				: {
						title: 'Prepare scene',
						text: 'Neither Mitsuba scene nor Shape Map exist yet. Large scenes may take a few minutes.'
					};
		if (!mitsubaReady)
			return KR
				? {
						title: 'Mitsuba 씬 재생성',
						text: 'Shape Map 은 있지만 Mitsuba 씬이 비어있어요. 다시 한 번 준비를 실행해 주세요.'
					}
				: { title: 'Rebuild Mitsuba scene', text: 'Shape Map exists but the Mitsuba scene is missing — run Prepare again.' };
		return KR
			? {
					title: 'Shape Map 진행 중',
					text: 'Shape Map 빌드가 백그라운드에서 진행 중이에요. 잠시 후 다시 시도해 주세요.'
				}
			: { title: 'Shape Map building', text: 'Shape Map is being built in the background. Try again shortly.' };
	});

	const syncTip = $derived.by((): Tip => {
		if (!isConnected)
			return KR
				? { title: '먼저 연결이 필요해요', text: 'Isaac Sim 에 연결되어야 변경사항을 가져올 수 있어요.' }
				: { title: 'Connect first', text: 'Connect to Isaac Sim before syncing scene changes.' };
		if (!sessionActive)
			return KR
				? { title: '활성 세션 없음', text: '현재 동기화할 활성 세션이 없어요. 좌측에서 씬을 다시 선택해 주세요.' }
				: { title: 'No active session', text: 'There is no active session to sync. Pick a scene from the left.' };
		if (syncingNow)
			return KR
				? { title: '동기화 중', text: 'Isaac Sim 에서 카메라와 오브젝트 변경사항을 가져오는 중이에요.' }
				: { title: 'Syncing', text: 'Pulling latest camera + object changes from Isaac Sim.' };
		if ($cmdPending)
			return KR
				? { title: '잠시만요', text: '다른 명령이 진행 중이에요.' }
				: { title: 'Hold on', text: 'Another command is running.' };
		return KR
			? {
					title: '세션 동기화',
					text: 'Isaac Sim 에서 카메라 위치, 오브젝트 변환, 머티리얼 변경을 다시 가져와 렌더 결과에 반영합니다.'
				}
			: {
					title: 'Sync session',
					text: 'Pull the latest camera, transform, and material changes from Isaac Sim into the render snapshot.'
				};
	});

	const renderTip = $derived.by((): Tip => {
		if (!effectiveSceneId)
			return KR
				? { title: '활성 세션이 없어요', text: '좌측에서 씬을 선택하거나 새 세션을 시작한 뒤 다시 시도해 주세요.' }
				: { title: 'No active session', text: 'Pick a scene or start a session first, then come back.' };
		if (!isConnected)
			return KR
				? { title: '먼저 연결이 필요해요', text: '[연결] 버튼으로 Isaac Sim 세션을 활성화한 뒤 렌더할 수 있어요.' }
				: { title: 'Connect first', text: 'Activate the Isaac Sim session via [Connect], then render.' };
		if (renderingNow)
			return KR
				? {
						title: '렌더 중',
						text: '현재 뷰를 렌더하는 중이에요. 진행 상황은 우측 카드에서 단계별로 확인할 수 있어요.'
					}
				: { title: 'Rendering', text: 'Rendering the current view. Watch the right-side card for stage progress.' };
		if (preparingNow)
			return KR
				? { title: '장면 준비 진행 중', text: '준비가 끝나면 자동으로 렌더 버튼이 활성화돼요.' }
				: { title: 'Prepare in progress', text: 'Render unlocks automatically once Prepare finishes.' };
		if (!mitsubaReady && !shapeMapReady)
			return KR
				? {
						title: '장면 준비 필요',
						text: 'Mitsuba 씬과 Shape Map 이 아직 없어요. [장면 준비] 를 먼저 실행해 주세요.'
					}
				: { title: 'Prepare required', text: 'Mitsuba scene + Shape Map are missing. Run [Prepare] first.' };
		if (!mitsubaReady)
			return KR
				? { title: 'Mitsuba 씬 미생성', text: '준비를 한 번 더 실행해서 Mitsuba 씬을 만들어 주세요.' }
				: { title: 'Mitsuba scene missing', text: 'Run Prepare again to build the Mitsuba scene.' };
		if (!shapeMapReady)
			return KR
				? { title: 'Shape Map 진행 중', text: 'Shape Map 빌드가 끝나면 다시 시도할 수 있어요.' }
				: { title: 'Shape Map building', text: 'Try again once Shape Map finishes building.' };
		const workerBusy = $healthStore?.worker_state === 'running';
		if (workerBusy)
			return KR
				? { title: '워커가 작업 중', text: '다른 렌더 작업이 진행 중이에요. 큐에 자리가 비면 다시 활성화돼요.' }
				: { title: 'Worker busy', text: 'Another render job is running. The button re-enables when the queue frees up.' };
		if ($cmdPending)
			return KR
				? { title: '명령 진행 중', text: '직전 명령이 마무리되는 중이에요.' }
				: { title: 'Command in flight', text: 'A previous command is still wrapping up.' };
		return KR
			? {
					title: '현재 뷰 렌더링',
					text: 'Isaac Sim 의 현재 카메라 뷰를 Mitsuba 로 멀티모달 렌더합니다 (RGB / 노멀 / 깊이).'
				}
			: {
					title: 'Render current view',
					text: 'Render the current Isaac Sim camera view through Mitsuba (RGB / normal / depth).'
				};
	});
</script>

<svelte:head><title>Robomituba Control Plane</title></svelte:head>

<div
	class="shell"
	data-rail={$rightRailCollapsed ? 'collapsed' : 'open'}
	data-bottom={$bottomPanelCollapsed ? 'collapsed' : 'open'}
	data-bottom-mode={$bottomPanelMode}
>
	<header class="shell-topbar">
		<div class="shell-topbar-brand">
			<a href="/" class="shell-brand-link">
				<span class="shell-brand-logo">ROBOMITUBA</span>
			</a>
		</div>

		<div class="shell-topbar-status">
			{#each overallChips as chip}
				<div class="status-chip" title="{chip.label}: {chip.value}">
					<span class="status-chip-label">{chip.label}</span>
					<span class="status-chip-value">
						<span class="status-chip-dot dot-{chip.tone}"></span>
						<span class:mono={chip.mono}>{chip.value}</span>
					</span>
				</div>
			{/each}
			{#if sessionChips.length > 0}
				<div class="status-chip-divider"></div>
				{#each sessionChips as chip}
					<div class="status-chip status-chip-session" title="{chip.label}: {chip.value}">
						<span class="status-chip-label">{chip.label}</span>
						<span class="status-chip-value status-chip-value-plain">
							{#if chip.label === ($lang === 'kr' ? '현재 세션' : 'Session')}
								<span>{chip.value}</span>
								<span class="badge badge-ok">Active</span>
							{:else}
								<span class:mono={chip.mono}>{chip.value}</span>
							{/if}
						</span>
					</div>
				{/each}
			{/if}
		</div>

		{#if effectiveSceneId}
			<div class="shell-topbar-session-actions" role="toolbar" aria-label={$lang === 'kr' ? '세션 액션' : 'Session actions'}>
				<!-- 1구역: 단계 (Connect → Prepare → Sync) -->
				<div class="step-group">
					{#if isConnected}
						<Tooltip title={connectTip.title} text={connectTip.text} position="bottom">
							<span class="step-chip step-chip-done">
								<svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="2.5 6.5 5 9 9.5 3.5"/></svg>
								<span>{$lang === 'kr' ? '연결됨' : 'Connected'}</span>
							</span>
						</Tooltip>
					{:else}
						<Tooltip title={connectTip.title} text={connectTip.text} position="bottom">
							<button
								class="step-btn step-btn-active"
								onclick={() => runCmd('connect_session')}
								disabled={!!$cmdPending}
							>
								<svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 9l-2 2a2.5 2.5 0 0 1-3.5-3.5l2-2"/><path d="M9 5l2-2a2.5 2.5 0 0 1 3.5 3.5l-2 2" transform="translate(-1 -1)"/><line x1="5" y1="9" x2="9" y2="5"/></svg>
								<span>{$cmdPending === 'connect_session' ? '…' : ($lang === 'kr' ? '연결' : 'Connect')}</span>
							</button>
						</Tooltip>
					{/if}

					{#if !isConnected}
						<span class="step-divider" aria-hidden="true">›</span>
						<Tooltip title={prepareTip.title} text={prepareTip.text} position="bottom">
							<span class="step-chip step-chip-pending">
								<span>{$lang === 'kr' ? '장면 준비' : 'Prepare'}</span>
							</span>
						</Tooltip>
						<span class="step-divider" aria-hidden="true">›</span>
						<Tooltip title={syncTip.title} text={syncTip.text} position="bottom">
							<span class="step-chip step-chip-pending">
								<span>{$lang === 'kr' ? '동기화' : 'Sync'}</span>
							</span>
						</Tooltip>
					{:else}
						<span class="step-divider" aria-hidden="true">›</span>
						{#if preparingNow}
							<Tooltip title={prepareTip.title} text={prepareTip.text} position="bottom">
								<span class="step-chip step-chip-running">
									<span class="step-spinner" aria-hidden="true"></span>
									<span>{$lang === 'kr' ? '장면 준비 중' : 'Preparing'}</span>
								</span>
							</Tooltip>
						{:else if renderReady}
							<Tooltip title={prepareTip.title} text={prepareTip.text} position="bottom">
								<span class="step-chip step-chip-done">
									<svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="2.5 6.5 5 9 9.5 3.5"/></svg>
									<span>{$lang === 'kr' ? '장면 준비됨' : 'Prepared'}</span>
								</span>
							</Tooltip>
						{:else}
							<Tooltip title={prepareTip.title} text={prepareTip.text} position="bottom">
								<button
									class="step-btn"
									onclick={() => runCmd('prepare_render_ready')}
									disabled={!!$cmdPending}
								>
									<svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="7" cy="7" r="2"/><path d="M7 1v2M7 11v2M1 7h2M11 7h2M2.7 2.7l1.4 1.4M9.9 9.9l1.4 1.4M2.7 11.3l1.4-1.4M9.9 4.1l1.4-1.4"/></svg>
									<span>{$cmdPending === 'prepare_render_ready' ? '…' : ($lang === 'kr' ? '장면 준비' : 'Prepare')}</span>
								</button>
							</Tooltip>
						{/if}

						<span class="step-divider" aria-hidden="true">›</span>
						<Tooltip title={syncTip.title} text={syncTip.text} position="bottom">
							<button
								class="step-btn"
								onclick={() => runCmd('sync_session')}
								disabled={!!$cmdPending || !sessionActive}
							>
								{#if syncingNow}
									<span class="step-spinner" aria-hidden="true"></span>
								{:else}
									<svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 6.5A5 5 0 0 0 3.5 4M2 7.5A5 5 0 0 0 10.5 10"/><polyline points="12 2 12 6 8 6"/><polyline points="2 12 2 8 6 8"/></svg>
								{/if}
								<span>{$cmdPending === 'sync_session' ? '…' : ($lang === 'kr' ? '동기화' : 'Sync')}</span>
							</button>
						</Tooltip>
					{/if}
				</div>

				<!-- 2구역: 핵심 액션 (Render) -->
				<div class="step-group step-group-primary">
					<Tooltip title={renderTip.title} text={renderTip.text} position="bottom">
						<button
							class="step-render-btn"
							class:step-render-btn-running={renderingNow}
							onclick={() => runCmd('render_current_view')}
							disabled={!!$cmdPending || !sessionActive || preparingNow || renderingNow || !renderReady}
						>
							{#if renderingNow}
								<span class="step-spinner" aria-hidden="true"></span>
								<span>{$lang === 'kr' ? '렌더 중' : 'Rendering'}</span>
							{:else}
								<svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="3 2 12 7 3 12 3 2" fill="currentColor" stroke="none"/></svg>
								<span>{$cmdPending === 'render_current_view' ? '…' : ($lang === 'kr' ? '렌더' : 'Render')}</span>
							{/if}
						</button>
					</Tooltip>
				</div>
			</div>
		{/if}

		<div class="shell-topbar-actions">
			<a class="button button-subtle text-xs" href="/current-scene" title={$lang === 'kr' ? '세션 열기' : 'Open session'}>
				{$lang === 'kr' ? '세션 열기' : 'Open session'}
			</a>
			<div class="topbar-overflow">
				<button
					class="topbar-overflow-btn"
					type="button"
					aria-label="More actions"
					aria-expanded={menuOpen}
					onclick={(e) => { e.stopPropagation(); menuOpen = !menuOpen; }}
				>⋮</button>
				{#if menuOpen}
					<div class="topbar-overflow-menu" role="menu">
						<button type="button" role="menuitem" onclick={() => { toggleLang(); menuOpen = false; }}>
							🌐 {$lang === 'kr' ? '한국어' : 'English'}
						</button>
						<button type="button" role="menuitem" onclick={() => { handleSmokeRender(); menuOpen = false; }}>
							🧪 {$lang === 'kr' ? 'Smoke 렌더' : 'Smoke render'}
						</button>
						<button type="button" role="menuitem" onclick={() => { toggleRightRail(); menuOpen = false; }}>
							{$rightRailCollapsed ? '◀' : '▶'} {$lang === 'kr' ? '우측 패널' : 'Right rail'}
						</button>
						<button type="button" role="menuitem" onclick={() => { toggleBottomPanel(); menuOpen = false; }}>
							{$bottomPanelCollapsed ? '▲' : '▼'} {$lang === 'kr' ? '하단 패널' : 'Bottom panel'}
						</button>
						<a role="menuitem" href="/settings" onclick={() => { menuOpen = false; }}>
							⚙ {$lang === 'kr' ? '설정' : 'Settings'}
						</a>
					</div>
				{/if}
			</div>
		</div>
	</header>

	<aside class="shell-nav">
		<div class="shell-nav-brand">
			<a href="/" class="shell-nav-brand-link">
				<span class="shell-nav-brand-mark">▮</span>
				<span class="shell-nav-brand-stack">
					<span class="shell-nav-brand-name">ROBOMITUBA</span>
					<span class="shell-nav-brand-sub">Control Plane</span>
				</span>
			</a>
			<span class="shell-nav-status badge-tone-{$backendOffline ? 'err' : 'ok'}">
				<span class="status-chip-dot dot-{$backendOffline ? 'err' : 'ok'}"></span>
				{$backendOffline ? ($lang === 'kr' ? '오프라인' : 'Offline') : 'Healthy'}
			</span>
		</div>

		<nav class="nav-list">
			{#each NAV as item}
				<a href={item.href} class="nav-link {isActive(item.href) ? 'nav-link-active' : ''}">
					<span>{item.icon} {$lang === 'kr' ? item.kr : item.en}</span>
					{#if isActive(item.href)}<span style="font-size:0.7rem;opacity:0.5">▶</span>{/if}
				</a>
			{/each}
		</nav>

		<div class="shell-nav-foot">
			{#if $healthStore?.isaac_scene_id}
				{@const h = $healthStore}
				<a href={`/scenes/${h.isaac_scene_id}`} class="shell-nav-session" aria-label={$lang === 'kr' ? '활성 세션 요약' : 'Active session'}>
					<header class="shell-nav-session-head">
						<span class="shell-nav-session-label">{$lang === 'kr' ? '현재 세션 요약' : 'Active session'}</span>
					</header>
					<div class="shell-nav-session-row">
						<span class="shell-nav-session-name">{h.isaac_scene_id}</span>
						<span class="badge badge-ok">Active</span>
					</div>
					<dl class="shell-nav-session-kv">
						<div><dt>Variant</dt><dd class="mono">{h.variant ?? '—'}</dd></div>
						<div><dt>URL</dt><dd class="mono">{h.base_url ?? '—'}</dd></div>
					</dl>
				</a>
			{/if}
			<div class="shell-nav-footer">
				<span>© 2026 RobotSimPol</span>
				<span class="mono">v0.9.0</span>
			</div>
		</div>
	</aside>

	<main class="shell-main">
		<div class="shell-workspace">
			{#if isCurrentScene}
				<div class="page-content page-content-tight">
					<CurrentScenePanel />
				</div>
			{:else}
				<div class="page-content">
					{@render children()}
				</div>
			{/if}
		</div>

		<section class="shell-bottom" aria-label="Bottom panel">
			{#if $sceneBottomSnippet}
				{@render $sceneBottomSnippet()}
			{:else}
				<div class="shell-bottom-placeholder">
					<p class="muted text-xs">
						{$lang === 'kr'
							? '작업 라이프사이클(실행·대기·완료·실패), 최근 로그, 선택 상세, 재질이 이곳에 표시됩니다.'
							: 'Job lifecycle (running, queued, recent, failed), logs, selection detail, and materials surface here.'}
					</p>
				</div>
			{/if}
		</section>
	</main>

	<aside class="shell-rail" aria-label="Right rail">
		<header class="shell-rail-header">
			<button
				class="shell-pane-toggle"
				type="button"
				onclick={toggleRightRail}
				aria-expanded={!$rightRailCollapsed}
				aria-label={$rightRailCollapsed ? 'Expand right rail' : 'Collapse right rail'}
			>{$rightRailCollapsed ? '◀' : '▶'}</button>
			{#if !$rightRailCollapsed}
				<span class="shell-pane-label">{$lang === 'kr' ? '우측 패널' : 'Right Rail'}</span>
			{/if}
		</header>
		{#if !$rightRailCollapsed}
			<div class="shell-rail-content">
				{#if $sceneRailSnippet}
					{@render $sceneRailSnippet()}
				{:else}
					<p class="muted text-xs" style="padding: 0.75rem">
						{$lang === 'kr'
							? '인시던트, 브리지 파이프라인, 씬 정보가 이곳에 표시됩니다.'
							: 'Incidents, bridge pipeline, and scene info will surface here.'}
					</p>
				{/if}
			</div>
		{/if}
	</aside>
</div>

{#if $backendOffline}
	<div style="position:fixed;inset:0;background:rgba(15,23,42,0.75);backdrop-filter:blur(4px);z-index:10000;display:flex;align-items:center;justify-content:center;padding:1rem">
		<div style="background:var(--bg,#fff);border-radius:0.75rem;padding:2rem;max-width:28rem;width:100%;box-shadow:0 20px 50px rgba(0,0,0,0.3);border:1px solid var(--border)">
			<div style="font-size:2.5rem;text-align:center;margin-bottom:0.5rem">🔌</div>
			<h2 style="margin:0 0 0.5rem;text-align:center;font-size:1.1rem;font-weight:600">
				{$lang === 'kr' ? '백엔드에 연결할 수 없습니다' : 'Cannot Connect to Backend'}
			</h2>
			<p class="muted text-sm" style="text-align:center;margin:0 0 0.25rem">
				{$lang === 'kr' ? '데몬이 실행 중인지 확인해주세요.' : 'Please check that the daemon is running.'}
			</p>
			{#if $backendOfflineReason}
				<p class="mono muted text-xs" style="text-align:center;margin:0 0 1rem">({$backendOfflineReason})</p>
			{/if}
			<div style="display:flex;gap:0.5rem;justify-content:center;margin-top:1rem">
				<button class="button button-primary" onclick={() => location.reload()}>
					{$lang === 'kr' ? '새로고침' : 'Refresh'}
				</button>
			</div>
			<p class="muted text-xs" style="text-align:center;margin:1rem 0 0">
				{$lang === 'kr' ? '자동으로 재연결 시도 중…' : 'Auto-reconnecting…'}
			</p>
		</div>
	</div>
{/if}

{#if $debugToasts.length > 0}
	<div style="position:fixed;bottom:1.5rem;right:1.5rem;display:flex;flex-direction:column;gap:0.5rem;z-index:9999">
		{#each $debugToasts as ev (ev.id)}
			<div class="activity-snackbar" role="alert">{kindIcon(ev.kind)} {ev.message}</div>
		{/each}
	</div>
{/if}

{#if $commandResultToasts.length > 0}
	<div class="cmd-toast-region" role="status" aria-live="polite">
		{#each $commandResultToasts as t (t.id)}
			<div class="cmd-toast cmd-toast-{t.kind}">
				<span class="cmd-toast-icon" aria-hidden="true">{t.kind === 'success' ? '✓' : '✕'}</span>
				<div class="cmd-toast-body">
					<div class="cmd-toast-title">
						<span>{t.label}</span>
						<span class="cmd-toast-status">
							{#if t.kind === 'success'}
								{$lang === 'kr' ? '완료' : 'Done'}
							{:else}
								{$lang === 'kr' ? '실패' : 'Failed'}
							{/if}
							{#if t.elapsedS !== undefined} · {t.elapsedS}s{/if}
						</span>
					</div>
					{#if t.message && t.kind === 'error'}
						<div class="cmd-toast-message">{t.message}</div>
					{/if}
				</div>
				<button
					class="cmd-toast-close"
					type="button"
					aria-label={$lang === 'kr' ? '닫기' : 'Dismiss'}
					onclick={() => dismissCommandResultToast(t.id)}
				>×</button>
			</div>
		{/each}
	</div>
{/if}
