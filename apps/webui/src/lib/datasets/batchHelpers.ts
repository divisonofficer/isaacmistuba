/**
 * Pure batch job and utility helpers extracted from datasets/+page.svelte.
 */

// ── Batch merging & display ───────────────────────────────────────────────────

export type NormalizedJobStatus = 'done' | 'running' | 'queued' | 'failed' | 'cancelled' | 'unknown';

export type LogLevel = 'error' | 'warning' | 'info';
export type LogScope = 'batch' | 'selected' | 'ui';

export interface NormalizedLogRow {
	id: string;
	ts: string;
	level: LogLevel;
	scope: LogScope;
	source: string;
	job_id: string;
	message: string;
}

export function normalizeJobStatus(job: any): NormalizedJobStatus {
	const raw = String(job?.status?.status ?? job?.status ?? 'unknown').toLowerCase();
	if (raw === 'succeeded' || raw === 'completed' || raw === 'complete' || raw === 'done' || raw === 'success') return 'done';
	if (raw === 'running' || raw === 'rendering') return 'running';
	if (raw === 'queued' || raw === 'pending' || raw === 'dispatched' || raw === 'retry_queued') return 'queued';
	if (raw === 'failed' || raw === 'error') return 'failed';
	if (raw === 'cancelled' || raw === 'canceled') return 'cancelled';
	return 'unknown';
}

export function normalizedCounts(jobs: any[]): Record<NormalizedJobStatus, number> {
	const counts: Record<NormalizedJobStatus, number> = {
		done: 0,
		running: 0,
		queued: 0,
		failed: 0,
		cancelled: 0,
		unknown: 0,
	};
	for (const job of jobs) counts[normalizeJobStatus(job)] += 1;
	return counts;
}

function parseTsMs(value: unknown): number | null {
	if (typeof value !== 'string' || value.length === 0) return null;
	const parsed = Date.parse(value);
	return Number.isFinite(parsed) ? parsed : null;
}

function batchCreatedAtMs(batch: any, job?: any): number | null {
	return parseTsMs(job?.batch_created_at ?? job?.status?.batch_created_at ?? batch?.created_at);
}

function statusEventMs(status: any): number | null {
	for (const key of ['finished_at', 'completed_at', 'worker_started_at', 'started_at', 'submitted_at']) {
		const parsed = parseTsMs(status?.[key]);
		if (parsed !== null) return parsed;
	}
	return null;
}

function isTerminalNormalized(status: NormalizedJobStatus): boolean {
	return status === 'done' || status === 'failed' || status === 'cancelled';
}

function staleStatusForBatch(batch: any, job: any, status: any): boolean {
	const normalized = normalizeJobStatus({ status });
	if (!isTerminalNormalized(normalized)) return false;
	const batchMs = batchCreatedAtMs(batch, job);
	const eventMs = statusEventMs(status);
	if (batchMs === null || eventMs === null) return false;
	return eventMs < batchMs - 30_000;
}

function maskStaleStatus(batch: any, job: any): any {
	const contextualJob = {
		...job,
		source_batch_id: job?.source_batch_id ?? batch?.batch_id,
		submission_group_id: job?.submission_group_id ?? batch?.submission_group_id,
		scene_variant_key: job?.scene_variant_key ?? batch?.scene_variant_key,
		batch_created_at: job?.batch_created_at ?? batch?.created_at,
	};
	const status = (contextualJob.status && typeof contextualJob.status === 'object')
		? contextualJob.status
		: { status: contextualJob.status ?? 'unknown' };
	const batchCreated = contextualJob.batch_created_at;
	if (!staleStatusForBatch(batch, contextualJob, status)) {
		return contextualJob;
	}
	return {
		...contextualJob,
		batch_created_at: batchCreated,
		status: {
			job_id: status.job_id ?? job?.job_id,
			status: 'queued',
			progress_stage: 'queued',
			batch_created_at: batchCreated,
			stale_previous_status: status.status,
			stale_previous_finished_at: status.finished_at,
		},
	};
}

function withRecomputedProgress(batch: any, jobs: any[]): any {
	const normalized = normalizedCounts(jobs);
	const counts: Record<string, number> = { ...normalized, completed: normalized.done };
	const total = Math.max(1, jobs.length);
	return {
		...(batch ?? {}),
		jobs,
		counts,
		progress: {
			completed: normalized.done,
			failed: counts.failed,
			total: jobs.length,
			fraction: (normalized.done + normalized.failed) / total,
		},
	};
}

export function normalizeBatchForDisplay(batch: any): any {
	if (!batch || !Array.isArray(batch.jobs)) return batch;
	return withRecomputedProgress(batch, batch.jobs.map((job: any) => maskStaleStatus(batch, job)));
}

/**
 * Apply a flat job-status update (the shape pushed by `/api/ws/job-status`) to
 * an existing batch by job_id, preserving the rich batch-side metadata
 * (graph_id / node_id / heading_id / preview_id / scene_id) that the WS frame
 * doesn't carry. Only jobs present in the batch are updated — extra jobs in
 * the WS payload are ignored.
 *
 * The WS record stores its run state as a flat `status: "running" | ...`
 * field; the batch-side job nests it as `status: { status, progress_stage, ... }`.
 * We reshape into the nested form so existing readers (normalizeJobStatus,
 * jobStageLabel, etc.) keep working unchanged.
 */
export function applyJobStatusUpdates(batch: any, wsJobs: any[]): any {
	if (!batch || !Array.isArray(batch.jobs) || batch.jobs.length === 0) return batch;
	const wsById = new Map<string, any>();
	for (const ws of wsJobs ?? []) {
		const jid = String(ws?.job_id ?? '');
		if (jid) wsById.set(jid, ws);
	}
	const nextJobs = batch.jobs.map((job: any) => {
		const ws = wsById.get(String(job?.job_id ?? ''));
		if (!ws) return maskStaleStatus(batch, job);
		// Merge ws extras into existing status.extras so batch-side fields
		// (texture_profile, scene_cache_hit, etc.) survive the update.
		const prevExtras = (job?.status?.extras && typeof job.status.extras === 'object')
			? job.status.extras
			: {};
		const nestedStatus = {
			...(job?.status ?? {}),
			job_id: ws.job_id ?? job?.status?.job_id,
			status: ws.status ?? job?.status?.status,
			progress_stage: ws.progress_stage ?? job?.status?.progress_stage,
			active_stage: ws.active_stage ?? ws.progress_stage ?? job?.status?.active_stage,
			submitted_at: ws.submitted_at ?? job?.status?.submitted_at,
			started_at: ws.started_at ?? job?.status?.started_at,
			worker_started_at: ws.worker_started_at ?? job?.status?.worker_started_at,
			finished_at: ws.finished_at ?? job?.status?.finished_at,
			elapsed_s: ws.elapsed_s ?? job?.status?.elapsed_s,
			queue_wait_s: ws.queue_wait_s ?? job?.status?.queue_wait_s,
			error: ws.error ?? job?.status?.error,
			extras: { ...prevExtras, ...(ws.extras ?? {}) },
		};
		return maskStaleStatus(batch, { ...job, status: nestedStatus });
	});
	// Always return a fresh object so downstream $derived chains re-fire even
	// when the merge produced no semantic change.
	return withRecomputedProgress(batch, nextJobs);
}

/**
 * Convert `/api/ws/job-status` log_tails (per-job last-20-lines map) into the
 * `{job_id, line}[]` shape consumed by `batchLogEntries` in datasets/+page.svelte,
 * filtered to jobs present in `batchJobIds`.
 */
export function logTailsToBatchEntries(
	batchJobIds: Set<string>,
	logTails: Record<string, string[] | undefined>,
): { job_id: string; line: string }[] {
	const out: { job_id: string; line: string }[] = [];
	for (const [jid, lines] of Object.entries(logTails ?? {})) {
		if (!batchJobIds.has(jid) || !Array.isArray(lines)) continue;
		for (const line of lines) out.push({ job_id: jid, line: String(line) });
	}
	return out;
}

export function mergeBatch(existing: any, incoming: any): any {
	const jobMap = new Map<string, any>();
	for (const j of existing?.jobs ?? []) jobMap.set(j.job_id, maskStaleStatus(existing, j));
	for (const j of incoming?.jobs ?? []) jobMap.set(j.job_id, maskStaleStatus(incoming, j));
	const jobs = [...jobMap.values()];
	const batchIds = [...new Set([
		...(existing?.batch_ids ?? []),
		existing?.batch_id,
		...(incoming?.batch_ids ?? []),
		incoming?.batch_id,
	].filter(Boolean).map(String))];
	return withRecomputedProgress({ ...(incoming ?? existing ?? {}), batch_ids: batchIds }, jobs);
}

export interface BatchJobLane {
	key: string;
	label: string;
	variant: string;
	phase: string;
	sensorIds: string[];
	batchId: string;
	createdAt: string;
}

export interface BatchJobGridCell {
	jobs: any[];
	representative: any | null;
	status: NormalizedJobStatus;
}

export interface BatchJobGridRow {
	nid: string;
	cells: BatchJobGridCell[];
	lanes: { lane: BatchJobLane; cells: (any | null)[] }[];
}

export function jobVariant(job: any): string {
	const explicit = String(
		job?.scene_variant_key
		?? job?.render_variant
		?? job?.status?.extras?.scene_variant_key
		?? '',
	).trim().toLowerCase();
	if (explicit === 'template') return 'base';
	if (explicit) return explicit;
	const jobId = String(job?.job_id ?? '').toLowerCase();
	if (jobId.includes('-perturbed-')) return 'perturbed';
	if (jobId.includes('-template-')) return 'base';
	return 'base';
}

export function jobSensorIds(job: any): string[] {
	const ids: unknown[] = Array.isArray(job?.sensor_ids) && job.sensor_ids.length
		? job.sensor_ids
		: Array.isArray(job?.phase_sensor_ids) && job.phase_sensor_ids.length
			? job.phase_sensor_ids
			: job?.sensor_id ? [job.sensor_id] : Object.keys(job?.modalities_by_sensor ?? {});
	const normalized: string[] = ids.map((item) => String(item)).filter((item) => item.length > 0);
	return [...new Set<string>(normalized)];
}

function jobModalities(job: any): string[] {
	const bySensor = job?.modalities_by_sensor;
	const nested = bySensor && typeof bySensor === 'object'
		? Object.values(bySensor).flatMap((items: any) => Array.isArray(items) ? items : [])
		: [];
	const direct = Array.isArray(job?.modalities) ? job.modalities : job?.modality ? [job.modality] : [];
	return [...new Set([...nested, ...direct].map(String).filter(Boolean))];
}

export function jobPhase(job: any): string {
	const raw = String(job?.phase ?? '').trim().toLowerCase();
	if (raw && raw !== 'per_view') return raw;
	const modalities = jobModalities(job).map((item) => item.toLowerCase());
	const sensors = jobSensorIds(job).map((item) => item.toLowerCase());
	if (
		modalities.some((item) => item.includes('polar') || /^s[012](_|$)/.test(item) || item === 'dop' || item === 'aolp')
		|| sensors.some((item) => item.includes('polar'))
	) return 'polar';
	if (modalities.some((item) => item.includes('nir')) || sensors.some((item) => item.includes('nir'))) return 'nir';
	if (modalities.some((item) => item === 'rgb' || item.includes('color'))) return 'rgb';
	return raw || 'per_view';
}

export function jobPhaseLabel(job: any): string {
	const phase = jobPhase(job);
	if (phase === 'rgb') return 'RGB';
	if (phase === 'polar') return 'Polar';
	if (phase === 'nir') return 'NIR';
	if (phase === 'per_view') return 'Per view';
	return phase.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function jobVariantLabel(job: any): string {
	const variant = jobVariant(job);
	if (variant === 'base') return 'Base';
	if (variant === 'perturbed') return 'Perturbed';
	return variant.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function jobSensorSummary(job: any): string {
	const ids = jobSensorIds(job);
	if (!ids.length) return 'No sensor';
	if (ids.length === 1) return ids[0];
	return `${ids.length} sensors`;
}

const JOB_STATUS_PRIORITY: Record<NormalizedJobStatus, number> = {
	failed: 0,
	running: 1,
	queued: 2,
	unknown: 3,
	cancelled: 4,
	done: 5,
};

export function representativeJob(jobs: any[]): any | null {
	return [...jobs].sort(
		(a, b) => JOB_STATUS_PRIORITY[normalizeJobStatus(a)] - JOB_STATUS_PRIORITY[normalizeJobStatus(b)],
	)[0] ?? null;
}

function laneKeyForJob(job: any, batch: any): string {
	const sensorKey = [...jobSensorIds(job)].sort().join(',');
	const batchId = String(job?.source_batch_id ?? batch?.batch_id ?? 'legacy');
	const groupId = String(job?.submission_group_id ?? batch?.submission_group_id ?? batchId);
	return [groupId, batchId, jobVariant(job), jobPhase(job), sensorKey].join('|');
}

export function buildBatchJobGrid(batch: any): {
	rows: BatchJobGridRow[];
	headings: string[];
	counts: Record<string, number>;
	laneCount: number;
} {
	const jobs: any[] = (batch?.jobs ?? []).map((job: any) => maskStaleStatus(batch, job));
	if (!jobs.length) return { rows: [], headings: [], counts: {}, laneCount: 0 };
	const headingSet = new Set<string>();
	const nodeMap = new Map<string, Map<string, any[]>>();
	const laneMap = new Map<string, BatchJobLane>();
	for (const job of jobs) {
		const nid = String(job.preview_id ?? job.node_id ?? job.job_id ?? '');
		const hid = String(job.heading_id ?? '');
		headingSet.add(hid);
		if (!nodeMap.has(nid)) nodeMap.set(nid, new Map());
		const byHeading = nodeMap.get(nid)!;
		if (!byHeading.has(hid)) byHeading.set(hid, []);
		byHeading.get(hid)!.push(job);

		const key = laneKeyForJob(job, batch);
		if (!laneMap.has(key)) {
			const sensorIds = jobSensorIds(job);
			laneMap.set(key, {
				key,
				label: `${jobVariantLabel(job)} · ${jobPhaseLabel(job)} · ${sensorIds.length || 1} ${sensorIds.length === 1 ? 'sensor' : 'sensors'}`,
				variant: jobVariant(job),
				phase: jobPhase(job),
				sensorIds,
				batchId: String(job?.source_batch_id ?? batch?.batch_id ?? ''),
				createdAt: String(job?.batch_created_at ?? batch?.created_at ?? ''),
			});
		}
	}
	const headings = [...headingSet].sort();
	const rows = [...nodeMap.entries()].map(([nid, hMap]) => ({
		nid,
		cells: headings.map((heading) => {
			const cellJobs = hMap.get(heading) ?? [];
			const representative = representativeJob(cellJobs);
			return {
				jobs: cellJobs,
				representative,
				status: representative ? normalizeJobStatus(representative) : 'unknown',
			};
		}),
		lanes: [...laneMap.values()].map((lane) => ({
			lane,
			cells: headings.map((heading) =>
				(hMap.get(heading) ?? []).find((job: any) => laneKeyForJob(job, batch) === lane.key) ?? null
			),
		})).filter((entry) => entry.cells.some(Boolean)),
	}));
	return {
		rows,
		headings,
		counts: (batch?.counts ?? {}) as Record<string, number>,
		laneCount: laneMap.size,
	};
}

export function buildGenericJobRows(batch: any): any[] {
	return [...(batch?.jobs ?? [])].sort((a: any, b: any) => {
		const aStatus = normalizeJobStatus(a);
		const bStatus = normalizeJobStatus(b);
		const order: Record<NormalizedJobStatus, number> = {
			failed: 0,
			running: 1,
			queued: 2,
			unknown: 3,
			cancelled: 4,
			done: 5,
		};
		const statusDelta = order[aStatus] - order[bStatus];
		if (statusDelta !== 0) return statusDelta;
		return String(b?.status?.submitted_at ?? b?.submitted_at ?? '').localeCompare(String(a?.status?.submitted_at ?? a?.submitted_at ?? ''));
	});
}

// ── Job status ────────────────────────────────────────────────────────────────

export function jobStatusClass(job: any): string {
	const s = normalizeJobStatus(job);
	if (s === 'done') return 'js-done';
	if (s === 'running') return 'js-running';
	if (s === 'failed') return 'js-failed';
	if (s === 'cancelled') return 'js-cancelled';
	if (s === 'queued') return 'js-queued';
	return 'js-unknown';
}

export function jobStageLabel(job: any): string {
	return String(job?.status?.progress_stage ?? job?.status?.status ?? '');
}

export function jobRunStartedAt(job: any): string {
	return String(job?.status?.worker_started_at ?? job?.worker_started_at ?? job?.status?.extras?.worker_started_at ?? job?.status?.started_at ?? job?.started_at ?? '');
}

export function jobRunDurationSeconds(job: any, nowMs = Date.now()): number | null {
	const explicit = job?.status?.elapsed_s ?? job?.elapsed_s;
	if (typeof explicit === 'number' && Number.isFinite(explicit)) return Math.max(0, Math.round(explicit));
	const startMs = parseTsMs(jobRunStartedAt(job));
	if (startMs === null) return null;
	const endMs = parseTsMs(job?.status?.finished_at ?? job?.finished_at) ?? nowMs;
	return Math.max(0, Math.round((endMs - startMs) / 1000));
}

export function formatJobRunDuration(job: any, nowMs = Date.now()): string {
	const seconds = jobRunDurationSeconds(job, nowMs);
	return seconds === null ? '' : `${seconds}s`;
}

export const RENDER_STAGES = [
	{ key: 'queued', label: '대기' },
	{ key: 'staging_scene', label: 'XML 준비' },
	{ key: 'loading_scene', label: 'GPU 로드' },
	{ key: 'rendering', label: '렌더링' },
	{ key: 'saving_output', label: 'EXR 저장' },
	{ key: 'writing_manifest', label: '매니페스트' },
	{ key: 'complete', label: '완료' },
];

export function stageIndex(job: any): number {
	const stage = jobStageLabel(job);
	const s = normalizeJobStatus(job);
	if (s === 'done') return RENDER_STAGES.length - 1;
	if (s === 'failed' || s === 'cancelled') return -1;
	const idx = RENDER_STAGES.findIndex((r) => r.key === stage);
	return idx >= 0 ? idx : 0;
}

export function progressPercent(progress: any): number {
	const total = Number(progress?.total ?? 0);
	const completed = Number(progress?.completed ?? 0);
	if (!total) return 0;
	return Math.max(0, Math.min(100, Math.round((completed / total) * 100)));
}

export function renderModeLabel(renderMode: string): string {
	if (renderMode === 'graph_sweep') return 'Sensor Sweep';
	if (renderMode === 'episode_nodes') return 'Episode Path Sweep';
	if (renderMode === 'preview_probe' || renderMode === 'preview') return 'Hot Camera Preview';
	return 'Episode Render';
}

/**
 * True when `renderMode` produces a `graphBatch`-shaped result (per-node /
 * per-heading jobs from /opticalnav/.../graph/sweep). `episode_nodes` reuses
 * the graph sweep path with a filtered `node_ids` list — same batch / WS / UI
 * code applies. Centralised here so the gates don't drift apart.
 */
export function isGraphSweepRenderMode(renderMode: string): boolean {
	return renderMode === 'graph_sweep' || renderMode === 'episode_nodes';
}

export function buildRenderSummary(batch: any, health: any, renderMode = '') {
	const jobs: any[] = batch?.jobs ?? [];
	const supplied = batch?.summary_only && batch?.counts && typeof batch.counts === 'object'
		? batch.counts
		: null;
	const counts = supplied
		? {
			done: Number(supplied.completed ?? supplied.done ?? 0),
			running: Number(supplied.running ?? 0),
			queued: Number(supplied.queued ?? 0),
			failed: Number(supplied.failed ?? 0),
			cancelled: Number(supplied.cancelled ?? 0),
			unknown: Number(supplied.unknown ?? 0),
		}
		: normalizedCounts(jobs);
	const total = supplied ? Number(batch?.progress?.total ?? 0) : jobs.length || Number(batch?.progress?.total ?? 0) || 0;
	const complete = supplied ? Number(batch?.progress?.completed ?? 0) : counts.done || Number(batch?.progress?.completed ?? 0) || 0;
	const percent = total ? Math.round((complete / total) * 100) : 0;
	const runningJobs = jobs.filter((job) => normalizeJobStatus(job) === 'running');
	const textureProfile = jobs.find((job) => job?.status?.extras?.texture_profile || job?.status?.extras?.texture_audit?.texture_profile)?.status?.extras?.texture_profile
		?? jobs.find((job) => job?.status?.extras?.texture_audit?.texture_profile)?.status?.extras?.texture_audit?.texture_profile
		?? '';
	const cacheHits = jobs.filter((job) => job?.status?.extras?.scene_cache_hit).length;
	return {
		label: renderModeLabel(renderMode),
		batch_id: batch?.batch_id ?? '',
		total,
		complete,
		percent,
		counts,
		activeStage: String(health?.active_stage ?? runningJobs[0]?.status?.progress_stage ?? ''),
		queueLength: Number(health?.queue_length ?? counts.queued ?? 0),
		gpus: Array.isArray(health?.gpus) ? health.gpus : [],
		textureProfile,
		cacheHits,
		runningJobCount: runningJobs.length,
	};
}

export function buildBottleneckSummary(batch: any, health: any) {
	const jobs: any[] = batch?.jobs ?? [];
	if (batch?.summary_only && batch?.counts) {
		const failedCount = Number(batch.counts.failed ?? 0);
		const runningCount = Number(batch.counts.running ?? 0);
		const queuedCount = Number(batch.counts.queued ?? 0);
		const durableStatus = String(batch?.ledger_status ?? batch?.status ?? '').toLowerCase();
		if (['paused', 'error', 'failed'].includes(durableStatus)) {
			return {
				tone: failedCount > 0 ? 'failed' : 'queued',
				title: 'Sweep paused',
				message: `${queuedCount + failedCount} incomplete durable task(s). These are not currently queued on a worker.`,
			};
		}
		if (failedCount > 0) return { tone: 'failed', title: `${failedCount} failed job(s)`, message: 'Open Resume incomplete to requeue durable failed tasks.' };
		if (runningCount > 0) return { tone: 'running', title: 'Sweep is rendering', message: `${runningCount} running · ${queuedCount} queued (aggregate summary).` };
		if (queuedCount > 0) return { tone: 'queued', title: 'Queued, waiting for worker', message: `${queuedCount} job(s) queued (aggregate summary).` };
	}
	const failed = jobs.filter((job) => normalizeJobStatus(job) === 'failed');
	if (failed.length > 0) {
		const err = String(failed[0]?.status?.error ?? failed[0]?.error ?? failed[0]?.status?.progress_message ?? 'Open failed job detail for the error log.');
		return { tone: 'failed', title: `${failed.length} failed job(s)`, message: compactDetail(err) };
	}
	const running = jobs.filter((job) => normalizeJobStatus(job) === 'running');
	const queued = jobs.filter((job) => normalizeJobStatus(job) === 'queued');
	if (queued.length > 0 && running.length === 0) {
		return { tone: 'queued', title: 'Queued, waiting for worker', message: `${queued.length} job(s) queued. Backend queue length ${Number(health?.queue_length ?? queued.length)}.` };
	}
	if (running.length > 0) {
		const stageCounts = new Map<string, number>();
		for (const job of running) {
			const stage = String(job?.status?.progress_stage ?? health?.active_stage ?? 'running');
			stageCounts.set(stage, (stageCounts.get(stage) ?? 0) + 1);
		}
		const [stage, count] = [...stageCounts.entries()].sort((a, b) => b[1] - a[1])[0] ?? ['running', running.length];
		return { tone: 'running', title: `Current stage: ${stage}`, message: `${count}/${running.length} running job(s) are at this stage.` };
	}
	return { tone: 'idle', title: 'No active render bottleneck', message: jobs.length ? 'Batch is idle or terminal.' : 'No active render batch.' };
}

function parseLogLevel(text: string): LogLevel {
	const upper = text.toUpperCase();
	if (upper.includes('[ERROR]') || upper.includes(' ERROR ') || upper.startsWith('ERROR')) return 'error';
	if (upper.includes('[WARN]') || upper.includes(' WARN ') || upper.startsWith('WARN')) return 'warning';
	return 'info';
}

export function normalizeLogRows(input: { batchLogEntries?: any[]; selectedBatchJobLog?: string[]; activityLog?: any[]; selectedJobId?: string }): NormalizedLogRow[] {
	const rows: NormalizedLogRow[] = [];
	for (const [idx, entry] of (input.batchLogEntries ?? []).entries()) {
		const message = String(entry?.line ?? entry?.message ?? entry ?? '');
		rows.push({
			id: `batch-${idx}`,
			ts: String(entry?.ts ?? entry?.time ?? ''),
			level: parseLogLevel(message),
			scope: 'batch',
			source: String(entry?.source ?? 'render_daemon'),
			job_id: String(entry?.job_id ?? ''),
			message,
		});
	}
	for (const [idx, line] of (input.selectedBatchJobLog ?? []).entries()) {
		const message = String(line);
		rows.push({
			id: `selected-${idx}`,
			ts: '',
			level: parseLogLevel(message),
			scope: 'selected',
			source: 'selected job',
			job_id: input.selectedJobId ?? '',
			message,
		});
	}
	for (const entry of input.activityLog ?? []) {
		const message = String(entry?.message ?? '');
		rows.push({
			id: `ui-${entry?.id ?? rows.length}`,
			ts: String(entry?.ts ?? ''),
			level: entry?.level === 'error' ? 'error' : entry?.level === 'warn' || entry?.level === 'warning' ? 'warning' : 'info',
			scope: 'ui',
			source: String(entry?.source ?? 'ui'),
			job_id: '',
			message: entry?.detail ? `${message} ${String(entry.detail)}` : message,
		});
	}
	return rows;
}

// ── Error / display utilities ─────────────────────────────────────────────────

export function compactDetail(text?: string): string {
	if (!text) return '';
	return text.length > 180 ? `${text.slice(0, 180)}...` : text;
}

export function errorMessage(err: unknown): string {
	const payload = typeof err === 'object' && err !== null ? (err as any).payload : null;
	if (payload && typeof payload === 'object') {
		return String(
			(payload as any).message ?? (payload as any).error ?? (err instanceof Error ? err.message : 'Request failed'),
		);
	}
	return err instanceof Error ? err.message : String(err);
}

export function errorPayload(err: unknown): unknown {
	return typeof err === 'object' && err !== null && 'payload' in err
		? (err as any).payload
		: undefined;
}
