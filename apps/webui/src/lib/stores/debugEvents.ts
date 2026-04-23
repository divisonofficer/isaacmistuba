import { writable } from 'svelte/store';

export interface DebugEvent {
	id: number;
	kind: string;
	message: string;
	data: Record<string, unknown>;
	ts: string;
}

export const debugToasts = writable<DebugEvent[]>([]);

const POLL_MS = 2500;
const TTL_MS = 4000;

let latestId = 0;
let timer: ReturnType<typeof setTimeout> | null = null;

function kindIcon(kind: string): string {
	if (kind === 'camera') return '📷';
	if (kind === 'selection') return '🖱';
	return 'ℹ️';
}

async function poll() {
	try {
		const data = await fetch(`/api/debug/events?since=${latestId}`).then((r) => r.json());
		if (data?.events?.length) {
			latestId = data.latest_id ?? latestId;
			debugToasts.update((toasts) => [...toasts, ...data.events]);
			for (const ev of data.events) {
				setTimeout(() => {
					debugToasts.update((toasts) => toasts.filter((t) => t.id !== ev.id));
				}, TTL_MS);
			}
		}
	} catch {
		// ignore
	}
	timer = setTimeout(poll, POLL_MS);
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
