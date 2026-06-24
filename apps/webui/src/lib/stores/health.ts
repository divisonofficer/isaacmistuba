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
const OFFLINE_AFTER_FAILURES = 4;
const STALE_GRACE_MS = 30000;

export const backendOffline = writable<boolean>(false);
export const backendOfflineReason = writable<string>('');

export const healthStore = readable<HealthData | null>(null, (set) => {
	let timer: ReturnType<typeof setTimeout>;
	let aborted = false;
	let consecutiveFailures = 0;
	let lastOkAt = 0;
	let lastData: HealthData | null = null;

	async function poll() {
		if (aborted) return;
		const isActive = lastData?.worker_state === 'running' || lastData?.active_isaac_command != null;
		const timeoutMs = isActive ? TIMEOUT_ACTIVE : TIMEOUT_IDLE;
		const ctrl = new AbortController();
		const tId = setTimeout(() => ctrl.abort(), timeoutMs);
		try {
			const res = await fetch('/health', { signal: ctrl.signal });
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = (await res.json()) as HealthData;
			if (!aborted) {
				lastData = data;
				lastOkAt = Date.now();
				set(data);
				consecutiveFailures = 0;
				backendOffline.set(false);
				backendOfflineReason.set('');
			}
			const nextActive = data.worker_state === 'running' || data.active_isaac_command != null;
			const baseMs = nextActive ? POLL_ACTIVE : POLL_IDLE;
			const hidden = typeof document !== 'undefined' && document.visibilityState !== 'visible';
			timer = setTimeout(poll, hidden ? baseMs * HIDDEN_MULTIPLIER : baseMs);
		} catch (e) {
			consecutiveFailures += 1;
			const err = e as Error;
			const isTimeout = err?.message === 'The operation was aborted.' || err?.name === 'AbortError';
			const recentlyHealthy = lastOkAt > 0 && Date.now() - lastOkAt < STALE_GRACE_MS;
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
				timer = setTimeout(poll, failHidden ? failBase * HIDDEN_MULTIPLIER : failBase);
			}
		} finally {
			clearTimeout(tId);
		}
	}

	poll();

	return () => {
		aborted = true;
		clearTimeout(timer);
	};
});
