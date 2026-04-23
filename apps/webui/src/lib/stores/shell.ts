import { writable } from 'svelte/store';

export const rightRailCollapsed = writable<boolean>(false);
export const bottomPanelCollapsed = writable<boolean>(false);

export function toggleRightRail() {
	rightRailCollapsed.update((v) => !v);
}

export function toggleBottomPanel() {
	bottomPanelCollapsed.update((v) => !v);
}
