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

	onMount(() => {
		stopTheme = initTheme();
		startDebugPolling();
	});
	onDestroy(() => {
		stopDebugPolling();
		stopTheme?.();
	});

	const NAV = [
		{ en: 'Operations',     kr: '운영 홈',         href: '/',               icon: '🏠' },
		{ en: 'Current Session', kr: '현재 세션',      href: '/current-scene',  icon: '📍' },
		{ en: 'Jobs · Queue',   kr: '작업·큐',         href: '/jobs',           icon: '📋' },
		{ en: 'Scene Registry', kr: '장면 레지스트리', href: '/scenes',         icon: '🎬' },
		{ en: 'Bridge Status',  kr: '연동 상태',       href: '/bridge',         icon: '🌉' },
		{ en: 'System · Workers', kr: '시스템·워커',   href: '/system',         icon: '🖥' },
		{ en: 'Guide',          kr: '가이드',          href: '/guide',          icon: '📘' },
		{ en: 'Settings',       kr: '설정',            href: '/settings',       icon: '⚙' }
	];

	function isActive(href: string) {
		const p = $page.url.pathname;
		return href === '/' ? p === '/' : p.startsWith(href);
	}

	const isCurrentScene = $derived($page.url.pathname.startsWith('/current-scene'));

	function positionPopover(e: Event) {
		const item = (e.target as HTMLElement).closest('.hsi-item') as HTMLElement | null;
		if (!item) return;
		const btn = item.querySelector('.hsi-btn') as HTMLElement | null;
		if (!btn) return;
		const rect = btn.getBoundingClientRect();
		item.style.setProperty('--pop-top', `${rect.bottom + 8}px`);
		item.style.setProperty('--pop-left', `${rect.left}px`);
	}

	async function handleSmokeRender() {
		const sceneId = prompt('Smoke render — scene ID:');
		if (!sceneId) return;
		try { await smokeRender(sceneId); } catch {}
	}

	function toggleLang() {
		lang.set($lang === 'kr' ? 'en' : 'kr');
	}

	type GpuInfo = {
		index?: number;
		util_pct?: number;
		mem_used_mb?: number;
		mem_total_mb?: number;
	};

	function healthGpus(value: unknown): GpuInfo[] {
		return Array.isArray(value) ? (value as GpuInfo[]) : [];
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
				<span class="eyebrow">Robomituba</span>
				<span class="shell-brand-title">Control Plane</span>
			</a>
		</div>

		<div
			class="shell-topbar-status"
			role="presentation"
			onmouseover={positionPopover}
			onfocus={positionPopover}
			onfocusin={positionPopover}
		>
			{#if $healthStore}
				{@const h = $healthStore}
				{@const gpus = healthGpus(h.gpus)}
				<div class="hsi-item">
					<button class="hsi-btn" type="button" aria-label="Daemon">
						<div class="hsi-icon-wrap">
							<span class="hsi-glyph">🖥</span>
							<span class="hsi-state-dot hsi-dot-ok"></span>
						</div>
					</button>
					<div class="hsi-popover">
						<div class="hsi-pop-label">Daemon</div>
						<div class="hsi-pop-value hp-ok">running</div>
					</div>
				</div>

				<div class="hsi-item">
					<button class="hsi-btn" type="button" aria-label="Worker">
						<div class="hsi-icon-wrap">
							<span class="hsi-glyph">⚙️</span>
							<span class="hsi-state-dot {h.worker_state === 'running' ? 'hsi-dot-running' : 'hsi-dot-idle'}"></span>
						</div>
					</button>
					<div class="hsi-popover">
						<div class="hsi-pop-label">Worker</div>
						<div class="hsi-pop-value {h.worker_state === 'running' ? 'hp-warn' : 'hp-ok'}">{h.worker_state}</div>
					</div>
				</div>

				<div class="hsi-item">
					<button class="hsi-btn" type="button" aria-label="Queue">
						<div class="hsi-icon-wrap">
							<span class="hsi-glyph">≡</span>
							{#if h.queue_length > 0}
								<span class="hsi-badge">{h.queue_length}</span>
							{:else}
								<span class="hsi-badge hsi-badge-zero">·</span>
							{/if}
						</div>
					</button>
					<div class="hsi-popover">
						<div class="hsi-pop-label">Queue</div>
						<div class="hsi-pop-value">{h.queue_length} jobs</div>
					</div>
				</div>

				<div class="hsi-item">
					<button class="hsi-btn" type="button" aria-label="Renderer variant">
						<span class="mono" style="font-size:0.7rem">{h.variant?.split('_')[0] ?? '?'}</span>
					</button>
					<div class="hsi-popover">
						<div class="hsi-pop-label">Renderer</div>
						<div class="hsi-pop-value mono">{h.variant}</div>
					</div>
				</div>

				{#if gpus.length > 0}
					{@const gpu = gpus[0]}
					{@const util = gpu.util_pct ?? 0}
					<div class="hsi-item">
						<button class="hsi-btn" type="button" aria-label="GPU">
							<div class="hsi-icon-wrap" style="position:relative">
								<span class="hsi-glyph" style="font-size:0.72rem;font-weight:700;letter-spacing:-0.02em">GPU</span>
								<span class="hsi-state-dot {util > 80 ? 'hsi-dot-running' : util > 10 ? 'hsi-dot-ok' : 'hsi-dot-idle'}"></span>
							</div>
						</button>
						<div class="hsi-popover">
							<div class="hsi-pop-label">GPU {gpu.index ?? 0}</div>
							<div class="hsi-pop-value {util > 80 ? 'hp-warn' : 'hp-ok'}">{util}% util</div>
							<div class="hsi-pop-value mono" style="font-size:0.72rem">{gpu.mem_used_mb} / {gpu.mem_total_mb} MB</div>
							{#if gpus.length > 1}
								{#each gpus.slice(1) as g}
									<div class="hsi-pop-label" style="margin-top:0.3rem">GPU {g.index}</div>
									<div class="hsi-pop-value">{g.util_pct}% · {g.mem_used_mb}/{g.mem_total_mb} MB</div>
								{/each}
							{/if}
						</div>
					</div>
				{/if}

				<div class="hsi-item">
					<button class="hsi-btn" type="button" aria-label="Isaac Sim">
						<div class="hsi-icon-wrap">
							<span class="hsi-glyph">🤖</span>
							<span class="hsi-state-dot {h.isaac_connected ? 'hsi-dot-ok' : 'hsi-dot-idle'}"></span>
						</div>
					</button>
					<div class="hsi-popover">
						<div class="hsi-pop-label">Isaac Sim</div>
						<div class="hsi-pop-value {h.isaac_connected ? 'hp-ok' : 'hp-err'}">{h.isaac_connected ? 'connected' : 'disconnected'}</div>
					</div>
				</div>
			{/if}
		</div>

		<div class="shell-topbar-actions">
			<button
				class="button button-subtle text-xs"
				type="button"
				onclick={toggleLang}
				title="Toggle language"
				aria-label="Toggle language"
			>{$lang === 'kr' ? '한국어' : 'EN'}</button>
			<button
				class="button button-subtle text-xs"
				type="button"
				onclick={handleSmokeRender}
				title="Smoke render"
			>🧪 Smoke</button>
			<button
				class="button button-subtle text-xs"
				type="button"
				onclick={toggleRightRail}
				aria-expanded={!$rightRailCollapsed}
				title={$rightRailCollapsed ? 'Expand right rail' : 'Collapse right rail'}
				aria-label={$rightRailCollapsed ? 'Expand right rail' : 'Collapse right rail'}
			>{$rightRailCollapsed ? '◀ Rail' : 'Rail ▶'}</button>
			<a class="button button-subtle text-xs" href="/settings" title="Settings" aria-label="Settings">⚙</a>
		</div>
	</header>

	<aside class="shell-nav">
		<nav class="nav-list">
			{#each NAV as item}
				<a href={item.href} class="nav-link {isActive(item.href) ? 'nav-link-active' : ''}">
					<span>{item.icon} {$lang === 'kr' ? item.kr : item.en}</span>
					{#if isActive(item.href)}<span style="font-size:0.7rem;opacity:0.5">▶</span>{/if}
				</a>
			{/each}

			{#if $healthStore?.isaac_scene_id}
				{@const sceneHref = `/scenes/${$healthStore.isaac_scene_id}`}
				<a href={sceneHref} class="nav-link {isActive(sceneHref) ? 'nav-link-active' : ''} nav-link-pinned">
					<span>📍 {$lang === 'kr' ? '활성 씬' : 'Active Scene'}</span>
					<span class="status-dot status-green live" style="width:0.5rem;height:0.5rem"></span>
				</a>
			{/if}
		</nav>
	</aside>

	<main class="shell-main">
		<div class="shell-workspace">
			<div class="page-content" style:display={isCurrentScene ? 'none' : undefined}>
				{@render children()}
			</div>
			<div class="page-content page-content-tight" style:display={isCurrentScene ? undefined : 'none'}>
				<CurrentScenePanel />
			</div>
		</div>

		<section class="shell-bottom" aria-label="Bottom panel">
			<header class="shell-bottom-header">
				<span class="shell-pane-label">{$lang === 'kr' ? '하단 패널' : 'Bottom Panel'}</span>
				<button
					class="shell-pane-toggle"
					type="button"
					onclick={toggleBottomPanel}
					aria-expanded={!$bottomPanelCollapsed}
					aria-label={$bottomPanelCollapsed ? 'Expand bottom panel' : 'Collapse bottom panel'}
				>{$bottomPanelCollapsed ? '▲' : '▼'}</button>
			</header>
			{#if !$bottomPanelCollapsed}
				<div class="shell-bottom-content">
					{#if $sceneBottomSnippet}
						{@render $sceneBottomSnippet()}
					{:else}
						<p class="muted text-xs" style="padding: 0.5rem 0.75rem">
							{$lang === 'kr'
								? '작업 큐, 최근 로그, 선택 상세, 렌더 이력이 이곳에 표시됩니다.'
								: 'Job queue, recent logs, selection detail, and render history will surface here.'}
						</p>
					{/if}
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
