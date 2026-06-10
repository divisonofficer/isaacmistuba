/**
 * Per-export-job WebSocket client.
 *
 * The daemon pushes status frames to `/api/ws/opticalnav-export?job_id=<id>`
 * for every stage transition + every ~200ms during the heavy zip/collect
 * phases. We open one connection per job_id (no singleton sharing — each job
 * has its own lifecycle and subscribers shouldn't cross-talk).
 *
 * Pattern adapted from `jobStatusWs.ts`.
 */
import type { ExportJobStatus } from '$lib/datasets/services/exportJobsService';

type Listener = (msg: ExportJobStatus) => void;

interface JobConnection {
	ws: WebSocket | null;
	listeners: Set<Listener>;
	last: ExportJobStatus | null;
	reconnectTimer: ReturnType<typeof setTimeout> | null;
}

const RECONNECT_DELAY_MS = 2000;
const _connections = new Map<string, JobConnection>();

function _connect(jobId: string, conn: JobConnection) {
	if (typeof window === 'undefined') return;
	if (conn.ws && (conn.ws.readyState === WebSocket.OPEN || conn.ws.readyState === WebSocket.CONNECTING)) return;
	if (conn.reconnectTimer !== null) {
		clearTimeout(conn.reconnectTimer);
		conn.reconnectTimer = null;
	}
	const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
	let ws: WebSocket;
	try {
		ws = new WebSocket(`${proto}//${location.host}/api/ws/opticalnav-export?job_id=${encodeURIComponent(jobId)}`);
	} catch {
		_scheduleReconnect(jobId, conn);
		return;
	}
	conn.ws = ws;
	ws.onmessage = (ev) => {
		try {
			const parsed = JSON.parse(typeof ev.data === 'string' ? ev.data : '');
			const msg: ExportJobStatus = parsed as ExportJobStatus;
			conn.last = msg;
			for (const fn of conn.listeners) {
				try { fn(msg); } catch { /* listener failure isolated */ }
			}
		} catch { /* ignore malformed frame */ }
	};
	ws.onerror = () => { /* surfaced via onclose */ };
	ws.onclose = () => {
		if (conn.ws === ws) conn.ws = null;
		if (conn.listeners.size > 0) _scheduleReconnect(jobId, conn);
	};
}

function _scheduleReconnect(jobId: string, conn: JobConnection) {
	if (conn.reconnectTimer !== null) return;
	conn.reconnectTimer = setTimeout(() => {
		conn.reconnectTimer = null;
		if (conn.listeners.size > 0) _connect(jobId, conn);
	}, RECONNECT_DELAY_MS);
}

export function subscribeExportJob(jobId: string, listener: Listener): () => void {
	let conn = _connections.get(jobId);
	if (!conn) {
		conn = { ws: null, listeners: new Set(), last: null, reconnectTimer: null };
		_connections.set(jobId, conn);
	}
	conn.listeners.add(listener);
	if (conn.listeners.size === 1) _connect(jobId, conn);
	if (conn.last) {
		try { listener(conn.last); } catch { /* ignore */ }
	}
	return () => {
		conn!.listeners.delete(listener);
		if (conn!.listeners.size === 0) {
			if (conn!.reconnectTimer !== null) { clearTimeout(conn!.reconnectTimer); conn!.reconnectTimer = null; }
			if (conn!.ws) { try { conn!.ws.close(); } catch { /* noop */ } conn!.ws = null; }
			_connections.delete(jobId);
		}
	};
}
