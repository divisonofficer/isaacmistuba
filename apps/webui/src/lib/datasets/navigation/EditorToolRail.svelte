<script lang="ts">
	import { onMount } from 'svelte';
	import { Brush, ChevronDown, CircleDotDashed, Eye, Layers3, Link2, MapPin, MousePointer2, MoreHorizontal, Paintbrush, ScanLine, Trash2, X } from '@lucide/svelte';
	import type { NavigationActions, NavigationState } from './types';

	interface Props {
		navigationState: NavigationState;
		navigationActions: NavigationActions;
	}

	let { navigationState, navigationActions }: Props = $props();
	let openMenu = $state<'paint' | 'edge' | 'more' | 'layers' | null>(null);
	let railElement = $state<HTMLElement | null>(null);

	const setMode = (mode: string) => {
		navigationActions.onSetPathsMode?.(mode);
		openMenu = null;
	};

	onMount(() => {
		const close = (event: KeyboardEvent) => {
			if (event.key === 'Escape') openMenu = null;
		};
		window.addEventListener('keydown', close);
		const clickAway = (event: PointerEvent) => {
			if (railElement && !railElement.contains(event.target as Node)) openMenu = null;
		};
		window.addEventListener('pointerdown', clickAway);
		return () => {
			window.removeEventListener('keydown', close);
			window.removeEventListener('pointerdown', clickAway);
		};
	});
</script>

<aside class="tool-rail" aria-label="Path editing tools" bind:this={railElement}>
	<button class:active={navigationState.pathsMode === 'select'} title="Select" aria-label="Select" onclick={() => setMode('select')}><MousePointer2 size={18} /></button>
	<button class:active={navigationState.pathsMode === 'place_node'} title="Place graph node" aria-label="Place graph node" onclick={() => setMode('place_node')}><MapPin size={18} /></button>
	<div class="tool-group">
		<button class:active={String(navigationState.pathsMode).startsWith('paint_')} title="Paint traversability" aria-label="Paint traversability" onclick={() => openMenu = openMenu === 'paint' ? null : 'paint'}><Paintbrush size={18} /></button>
		{#if openMenu === 'paint'}
			<div class="tool-popover" role="menu">
				<strong>Paint traversability</strong>
				<button role="menuitem" onclick={() => setMode('paint_walkable')}><Brush size={15} /> Walkable</button>
				<button role="menuitem" onclick={() => setMode('paint_blocked')}><Brush size={15} /> Blocked</button>
				<button role="menuitem" onclick={() => setMode('paint_erase')}><X size={15} /> Erase</button>
				<label>Brush radius <input type="number" min="0.05" max="2" step="0.05" value={navigationState.paintRadiusM} oninput={(event) => navigationActions.onSetPaintRadius?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
			</div>
		{/if}
	</div>
	<div class="tool-group">
		<button class:active={['add_edge', 'remove_edge', 'inspect_edge'].includes(navigationState.pathsMode)} title="Edit place links" aria-label="Edit place links" onclick={() => openMenu = openMenu === 'edge' ? null : 'edge'}><Link2 size={18} /></button>
		{#if openMenu === 'edge'}
			<div class="tool-popover" role="menu">
				<strong>Place links</strong>
				<button role="menuitem" onclick={() => setMode('add_edge')}><Link2 size={15} /> Add</button>
				<button role="menuitem" onclick={() => setMode('remove_edge')}><Trash2 size={15} /> Remove</button>
				<button role="menuitem" onclick={() => setMode('inspect_edge')}><ScanLine size={15} /> Inspect</button>
			</div>
		{/if}
	</div>
	<button class:active={navigationState.pathsMode === 'blueprint_pair'} title="Create route blueprint" aria-label="Create route blueprint" onclick={() => setMode('blueprint_pair')}><CircleDotDashed size={18} /></button>
	<button class:active={navigationState.pathsMode === 'inspect_edge'} title="Inspect edge" aria-label="Inspect edge" onclick={() => setMode('inspect_edge')}><Eye size={18} /></button>
	<div class="tool-spacer"></div>
	<div class="tool-group">
		<button class:active={openMenu === 'layers'} title="Layers" aria-label="Layers" onclick={() => openMenu = openMenu === 'layers' ? null : 'layers'}><Layers3 size={18} /></button>
		{#if openMenu === 'layers'}
			<div class="tool-popover layer-popover" role="menu">
				<strong>Navigation layers</strong>
				<label><input type="checkbox" checked={navigationState.showFootprint} onchange={(event) => navigationActions.onSetShowFootprint?.((event.currentTarget as HTMLInputElement).checked)} /> Footprint inflation</label>
				<label><input type="checkbox" checked={navigationState.showTraversableMask} onchange={(event) => { navigationActions.onSetShowTraversableMask?.((event.currentTarget as HTMLInputElement).checked); navigationActions.onRefreshTraversableMeta?.(); }} /> Inflated obstacle mask</label>
			</div>
		{/if}
	</div>
	<div class="tool-group">
		<button class:active={openMenu === 'more'} title="More tools" aria-label="More tools" onclick={() => openMenu = openMenu === 'more' ? null : 'more'}><MoreHorizontal size={18} /></button>
		{#if openMenu === 'more'}
			<div class="tool-popover" role="menu">
				<strong>More tools</strong>
				<button role="menuitem" onclick={() => setMode('select_region')}>Select rebuild region</button>
				<button role="menuitem" onclick={() => setMode('remove_node')}>Remove nodes</button>
				<button role="menuitem" onclick={() => navigationActions.onFindOverlapping?.()}>Find overlapping nodes</button>
			</div>
		{/if}
	</div>
</aside>

<style>
	.tool-rail { position: absolute; z-index: 18; top: 5.25rem; left: 1rem; display: grid; gap: 4px; width: 2.65rem; padding: 6px; border: 1px solid color-mix(in srgb, var(--panel-border) 82%, transparent); border-radius: var(--radius-lg); background: color-mix(in srgb, var(--panel) 86%, transparent); box-shadow: var(--shadow-md); backdrop-filter: blur(14px); }
	.tool-rail > button, .tool-group > button { display: grid; width: 2.15rem; height: 2.15rem; place-items: center; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--muted-strong); cursor: pointer; }
	.tool-rail button:hover, .tool-rail button.active { background: var(--brand-container); color: var(--brand-strong); }
	.tool-group { position: relative; }
	.tool-spacer { height: 0.35rem; }
	.tool-popover { position: absolute; top: 0; left: calc(100% + 8px); display: grid; gap: 6px; min-width: 12.5rem; padding: 10px; border: 1px solid var(--panel-border); border-radius: var(--radius-md); background: var(--panel); box-shadow: var(--shadow-lg); color: var(--text); font-size: var(--font-size-xs); }
	.tool-popover strong { color: var(--muted-strong); font-size: var(--font-size-2xs); letter-spacing: var(--letter-spacing-wide); text-transform: uppercase; }
	.tool-popover button { display: flex; align-items: center; gap: 7px; width: auto; height: 2rem; padding: 0 7px; text-align: left; }
	.tool-popover label { display: grid; gap: 4px; color: var(--muted-strong); }
	.tool-popover input[type='number'] { width: 100%; min-width: 0; box-sizing: border-box; }
	.layer-popover label { display: flex; align-items: center; gap: 7px; }
	@media (max-width: 1440px) { .tool-rail { left: .5rem; } }
</style>
