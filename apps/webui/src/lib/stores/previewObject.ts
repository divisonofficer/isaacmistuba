/**
 * Which preview object the Material Library is currently rendering with.
 * Persisted to localStorage so a refresh keeps the user's choice.
 *
 * The store value is just an `object_id` string — `'sphere'` is the safe
 * default if the daemon hasn't returned `/api/preview-objects` yet.
 * Components that consume this should always be ready for the daemon's
 * registry to NOT include the saved id (in which case we fall back to
 * sphere on the next render — the daemon's `resolve_preview_object`
 * does the same on its side).
 */
import { writable } from 'svelte/store';

const STORAGE_KEY = 'robomituba.previewObject';
const DEFAULT_OBJECT = 'sphere';

function _read(): string {
	if (typeof localStorage === 'undefined') return DEFAULT_OBJECT;
	try {
		const v = localStorage.getItem(STORAGE_KEY);
		return v && v.length > 0 ? v : DEFAULT_OBJECT;
	} catch {
		return DEFAULT_OBJECT;
	}
}

export const previewObject = writable<string>(_read());

if (typeof localStorage !== 'undefined') {
	previewObject.subscribe((v) => {
		try {
			localStorage.setItem(STORAGE_KEY, v);
		} catch {
			// Quota / private mode — silent.
		}
	});
}
