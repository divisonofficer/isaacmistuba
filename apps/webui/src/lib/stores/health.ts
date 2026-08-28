import { readable, writable } from 'svelte/store';

export interface HealthData {
	status: string;
	worker_state: string;
	active_stage: string | null;
	queue_length: number;
	variant: string;
	base_url: string;
	isaac_connected: boolean;
	active_isaac_command: Record<string, unknown> | null;
	[key: string]: unknown;
}

const POLL_IDLE = 8000;
const POLL_ACTIVE = 3000;
const POLL_OFFLINE = 6000;
const HIDDEN_MULTIPLIER = 4;
const TIMEOUT_IDLE = 8000;
const TIMEOUT_ACTIVE = 12000;
const OFFLINE_AFTER_FAILURES = 6;
// A heavy scene load can temporarily delay the low-priority /health request
// even while graph summaries and render APIs are answering normally. Do not
// turn that into a full-screen outage after one short quiet window.
const STALE_GRACE_MS = 90000;

let lastBackendReachableAt = 0;

export const backendOffline = writable<boolean>(false);
export const backendOfflineReason = writable<string>('');
export const backendReconnecting = writable<boolean>(false);

// Set while the shared health store has an active subscriber (the application
// shell). Keeping the probe here lets the shell offer a real reconnect action
// without reloading the page and discarding editor state.
let requestImmediateHealthProbe: (() => Promise<boolean>) | null = null;

export async function reconnectBackend(): Promise<boolean> {
	if (!requestImmediateHealthProbe) return false;
	backendReconnecting.set(true);
	try {
		return await requestImmediateHealthProbe();
	} finally {
		backendReconnecting.set(false);
	}
}

/**
 * Record a successful response from any daemon API, not just /health.
 *
 * The browser has a finite per-origin connection pool. During a large sweep,
 * a queued health request can time out while a graph-batch summary has already
 * proved the daemon is alive. Shared API success must therefore keep the
 * non-blocking monitor alive.
 */
export function noteBackendReachable(): void {
	lastBackendReachableAt = Date.now();
	backendOffline.set(false);
	backendOfflineReason.set('');
}

export const healthStore = readable<HealthData | null>(null, (set) => {
	let timer: ReturnType<typeof setTimeout>;
	let aborted = false;
	let consecutiveFailures = 0;
	let lastOkAt = 0;
	let lastData: HealthData | null = null;

	function schedule(delayMs: number) {
		clearTimeout(timer);
		timer = setTimeout(poll, delayMs);
	}

	async function poll(): Promise<boolean> {
		if (aborted) return false;
		const isActive = lastData?.worker_state === 'running' || lastData?.active_isaac_command != null;
		const timeoutMs = isActive ? TIMEOUT_ACTIVE : TIMEOUT_IDLE;
		const ctrl = new AbortController();
		const tId = setTimeout(() => ctrl.abort(), timeoutMs);
		try {
			// Do not let a browser reuse a response across a daemon restart. A new
			// probe is cheap and is the authoritative signal for clearing offline UI.
			const res = await fetch('/health', {
				signal: ctrl.signal,
				cache: 'no-store',
				headers: { 'Cache-Control': 'no-cache' }
			});
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = (await res.json()) as HealthData;
			if (!aborted) {
				lastData = data;
				lastOkAt = Date.now();
				set(data);
				consecutiveFailures = 0;
				noteBackendReachable();
			}
			const nextActive = data.worker_state === 'running' || data.active_isaac_command != null;
			const baseMs = nextActive ? POLL_ACTIVE : POLL_IDLE;
			const hidden = typeof document !== 'undefined' && document.visibilityState !== 'visible';
			if (!aborted) schedule(hidden ? baseMs * HIDDEN_MULTIPLIER : baseMs);
			return true;
		} catch (e) {
			consecutiveFailures += 1;
			const err = e as Error;
			const isTimeout = err?.message === 'The operation was aborted.' || err?.name === 'AbortError';
			const mostRecentSuccess = Math.max(lastOkAt, lastBackendReachableAt);
			const recentlyHealthy = mostRecentSuccess > 0 && Date.now() - mostRecentSuccess < STALE_GRACE_MS;
			if (!aborted && !(isTimeout && recentlyHealthy)) {
				backendOfflineReason.set(isTimeout ? 'health check delayed' : err?.message ?? 'connection refused');
			}
			if (!aborted && consecutiveFailures >= OFFLINE_AFTER_FAILURES && !recentlyHealthy) {
				backendOffline.set(true);
				backendOfflineReason.set(
					isTimeout
						? 'timeout'
						: err?.message ?? 'connection refused'
				);
			}
			if (!aborted) {
				const failBase = isTimeout && recentlyHealthy ? POLL_IDLE : POLL_OFFLINE;
				const failHidden = typeof document !== 'undefined' && document.visibilityState !== 'visible';
				schedule(failHidden ? failBase * HIDDEN_MULTIPLIER : failBase);
			}
			return false;
		} finally {
			clearTimeout(tId);
		}
	}

	const forcePoll = async (): Promise<boolean> => {
		clearTimeout(timer);
		return poll();
	};
	requestImmediateHealthProbe = forcePoll;

	const onVisibilityChange = () => {
		if (!aborted && document.visibilityState === 'visible') void forcePoll();
	};
	const onBrowserOnline = () => {
		if (!aborted) void forcePoll();
	};
	if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibilityChange);
	if (typeof window !== 'undefined') window.addEventListener('online', onBrowserOnline);

	void poll();

	return () => {
		aborted = true;
		clearTimeout(timer);
		if (requestImmediateHealthProbe === forcePoll) requestImmediateHealthProbe = null;
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibilityChange);
		if (typeof window !== 'undefined') window.removeEventListener('online', onBrowserOnline);
	};
});
