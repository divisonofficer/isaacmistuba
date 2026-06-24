/**
 * Shared client for the `/api/ws/job-status` WebSocket.
 *
 * Backend pushes `{ jobs: [...], log_tails: { job_id: [lines...] } }` whenever
 * the job status cache invalidates (submit / state change / completion).
 * Multiple pages can subscribe; we hold a single connection regardless of
 * subscriber count and reconnect automatically.
 *
 * Replaces the per-page setInterval that fetched batch state + logs every few
 * seconds — a single graph_sweep batch with 5 active sub-batches was firing
 * ~10 HTTP requests/second from datasets/+page.svelte.
 */
export interface JobStatusMessage {
	jobs: any[];
	log_tails: Record<string, string[]>;
}

type Listener = (msg: JobStatusMessage) => void;

const RECONNECT_BASE_MS = 3000;
const RECONNECT_MAX_MS = 30000;
const HIDDEN_MULTIPLIER = 4;
let _ws: WebSocket | null = null;
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _reconnectAttempt = 0;
let _last: JobStatusMessage | null = null;
const _listeners = new Set<Listener>();

function _connect() {
	if (typeof window === 'undefined') return;
	if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return;
	if (_reconnectTimer !== null) {
		clearTimeout(_reconnectTimer);
		_reconnectTimer = null;
	}
	const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
	let ws: WebSocket;
	try {
		ws = new WebSocket(`${proto}//${location.host}/api/ws/job-status`);
	} catch {
		_scheduleReconnect();
		return;
	}
	_ws = ws;
	ws.onopen = () => {
		_reconnectAttempt = 0;
	};
	ws.onmessage = (ev) => {
		try {
			const parsed = JSON.parse(typeof ev.data === 'string' ? ev.data : '');
			const msg: JobStatusMessage = {
				jobs: Array.isArray(parsed?.jobs) ? parsed.jobs : [],
				log_tails: parsed?.log_tails && typeof parsed.log_tails === 'object' ? parsed.log_tails : {},
			};
			_last = msg;
			for (const fn of _listeners) {
				try { fn(msg); } catch { /* listener failure must not break others */ }
			}
		} catch { /* malformed frame — ignore */ }
	};
	ws.onerror = () => { /* surfaced via onclose */ };
	ws.onclose = () => {
		if (_ws === ws) _ws = null;
		if (_listeners.size > 0) _scheduleReconnect();
	};
}

function _scheduleReconnect() {
	if (_reconnectTimer !== null) return;
	const hidden = typeof document !== 'undefined' && document.visibilityState !== 'visible';
	const attempt = Math.min(_reconnectAttempt, 4);
	const baseDelay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * (2 ** attempt));
	const delay = hidden ? Math.min(RECONNECT_MAX_MS * HIDDEN_MULTIPLIER, baseDelay * HIDDEN_MULTIPLIER) : baseDelay;
	_reconnectAttempt += 1;
	_reconnectTimer = setTimeout(() => {
		_reconnectTimer = null;
		if (_listeners.size > 0) _connect();
	}, delay);
}

/**
 * Subscribe to job-status updates. Returns an unsubscribe function.
 * If a message has already been received, the listener is invoked synchronously
 * with the most recent value so callers don't have to wait for the next push.
 */
export function subscribeJobStatus(listener: Listener): () => void {
	_listeners.add(listener);
	if (_listeners.size === 1) _connect();
	if (_last) {
		try { listener(_last); } catch { /* listener failure — ignore */ }
	}
	return () => {
		_listeners.delete(listener);
		if (_listeners.size === 0) {
			if (_reconnectTimer !== null) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
			if (_ws) { try { _ws.close(); } catch { /* noop */ } _ws = null; }
			_reconnectAttempt = 0;
			_last = null;
		}
	};
}
