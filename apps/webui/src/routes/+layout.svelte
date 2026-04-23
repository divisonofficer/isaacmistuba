<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { healthStore, backendOffline, backendOfflineReason } from '$lib/stores/health';
	import { debugToasts, startDebugPolling, stopDebugPolling, kindIcon } from '$lib/stores/debugEvents';
	import { lang } from '$lib/stores/lang';
	import { initTheme } from '$lib/stores/theme';
	import { rightRailCollapsed, bottomPanelCollapsed, toggleRightRail, toggleBottomPanel } from '$lib/stores/shell';
	import { sceneRailSnippet, sceneBottomSnippet } from '$lib/stores/scenePortals';
	import { onMount, onDestroy } from 'svelte';
	import { smokeRender } from '$lib/api';
	import CurrentScenePanel from '$lib/CurrentScenePanel.svelte';

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
		{ en: 'Scene Registry',   kr: '장면 레지스트리',  href: '/scenes',         icon: '🎬' },
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
</script>

<svelte:head><title>Robomituba Control Plane</title></svelte:head>

<div
	class="shell"
	data-rail={$rightRailCollapsed ? 'collapsed' : 'open'}
	data-bottom={$bottomPanelCollapsed ? 'collapsed' : 'open'}
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
							? '작업 큐, 최근 로그, 선택 상세, 렌더 이력이 이곳에 표시됩니다.'
							: 'Job queue, recent logs, selection detail, and render history will surface here.'}
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
