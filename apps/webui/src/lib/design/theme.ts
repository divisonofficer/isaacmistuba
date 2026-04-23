import { get, writable } from 'svelte/store';

export type ThemeMode = 'light' | 'dark';

const STORAGE_KEY = 'theme';

export const theme = writable<ThemeMode>('light');

function readStoredTheme(): ThemeMode {
	if (typeof window === 'undefined') return 'light';
	try {
		return window.localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light';
	} catch {
		return 'light';
	}
}

function writeStoredTheme(mode: ThemeMode) {
	if (typeof window === 'undefined') return;
	try {
		window.localStorage.setItem(STORAGE_KEY, mode);
	} catch {}
}

export function applyTheme(mode: ThemeMode) {
	if (typeof document === 'undefined') return;
	document.documentElement.dataset.theme = mode;
	document.documentElement.style.colorScheme = mode;
}

export function setTheme(mode: ThemeMode) {
	theme.set(mode);
	applyTheme(mode);
	writeStoredTheme(mode);
}

export function toggleTheme() {
	setTheme(get(theme) === 'dark' ? 'light' : 'dark');
}

export function initTheme() {
	const initial = readStoredTheme();
	setTheme(initial);
	return theme.subscribe((mode) => {
		applyTheme(mode);
		writeStoredTheme(mode);
	});
}
