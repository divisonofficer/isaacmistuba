import { writable } from 'svelte/store';

export interface DebugEvent {
	id: number;
	kind: string;
	message: string;
	data: Record<string, unknown>;
	ts: string;
}

export const debugEvents = writable<DebugEvent[]>([]);
export const debugToasts = writable<DebugEvent[]>([]);

const POLL_MS = 6000;
const POLL_MAX_MS = 30000;
const FETCH_TIMEOUT_MS = 8000;
const HIDDEN_MULTIPLIER = 4;
const TTL_MS = 4000;
const MAX_EVENTS = 80;
const MAX_TOASTS = 4;

let latestId = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
let bootstrapped = false;
let consecutiveFailures = 0;

function kindIcon(kind: string): string {
	if (kind === 'camera') return '📷';
	if (kind === 'selection') return '🖱';
	return 'ℹ️';
}

async function poll() {
	let timeoutId: ReturnType<typeof setTimeout> | null = null;
	try {
		const ctrl = new AbortController();
		timeoutId = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
		const data = await fetch(`/api/debug/events?since=${latestId}`, { signal: ctrl.signal }).then((r) => r.json());
		consecutiveFailures = 0;
		latestId = data?.latest_id ?? latestId;
		if (data?.events?.length) {
			debugEvents.update((events) => [...events, ...data.events].slice(-MAX_EVENTS));

			if (bootstrapped) {
				const toastEvents = data.events.slice(-MAX_TOASTS);
				debugToasts.update((toasts) => [...toasts, ...toastEvents].slice(-MAX_TOASTS));
				for (const ev of toastEvents) {
					setTimeout(() => {
						debugToasts.update((toasts) => toasts.filter((t) => t.id !== ev.id));
					}, TTL_MS);
				}
			}
		}
		bootstrapped = true;
	} catch {
		consecutiveFailures += 1;
		// ignore
	} finally {
		if (timeoutId !== null) clearTimeout(timeoutId);
	}
	const hidden = typeof document !== 'undefined' && document.visibilityState !== 'visible';
	const retryMs = Math.min(POLL_MAX_MS, POLL_MS * (2 ** Math.min(consecutiveFailures, 3)));
	timer = setTimeout(poll, hidden ? retryMs * HIDDEN_MULTIPLIER : retryMs);
}

export function startDebugPolling() {
	if (timer == null) poll();
}

export function stopDebugPolling() {
	if (timer != null) {
		clearTimeout(timer);
		timer = null;
	}
}

export { kindIcon };
