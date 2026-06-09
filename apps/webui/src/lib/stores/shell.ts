import { derived, writable } from 'svelte/store';

export type BottomPanelMode = 'collapsed' | 'expanded' | 'maximized';

export const rightRailCollapsed = writable<boolean>(false);
export const bottomPanelMode = writable<BottomPanelMode>('expanded');
export const bottomPanelCollapsed = derived(bottomPanelMode, (mode) => mode === 'collapsed');

export function toggleRightRail() {
	rightRailCollapsed.update((v) => !v);
}

export function toggleBottomPanel() {
	bottomPanelMode.update((mode) => mode === 'collapsed' ? 'expanded' : 'collapsed');
}

export function setBottomPanelMode(mode: BottomPanelMode) {
	bottomPanelMode.set(mode);
}
