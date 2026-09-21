<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { getControllerStatus, type ControllerJob } from './api';

  interface Props { onOpenJobs: () => void; }
  let { onOpenJobs }: Props = $props();
  let expanded = $state(false);
  let jobs = $state<ControllerJob[]>([]);
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  const isRunning = (job: ControllerJob) => job.status === 'running' || (job.external_import_pids?.length ?? 0) > 0;
  const isWaiting = (job: ControllerJob) => job.status === 'queued' || job.resource_state?.startsWith('waiting_') === true;
  const title = (job: ControllerJob) => String(job.request.dataset_name ?? job.request.scene_id ?? job.job_id);
  function progress(job: ControllerJob) {
    const current = job.stage_progress?.[job.stage];
    if (typeof current?.percent === 'number') return Math.max(0, Math.min(100, current.percent));
    const entries = Object.values(job.stage_progress ?? {});
    const active = entries.find((item) => typeof item.percent === 'number' && item.percent > 0);
    return typeof active?.percent === 'number' ? Math.max(0, Math.min(100, active.percent)) : 0;
  }
  const running = $derived(jobs.filter(isRunning));
  const waiting = $derived(jobs.filter((job) => !isRunning(job) && isWaiting(job)));
  const visible = $derived([...running, ...waiting].slice(0, 5));

  async function refresh() {
    try { jobs = (await getControllerStatus()).jobs; } catch { /* Controller may be offline during local UI work. */ }
  }
  async function poll() { await refresh(); if (!disposed) pollTimer = setTimeout(() => void poll(), 4000); }
  onMount(() => { void poll(); });
  onDestroy(() => { disposed = true; if (pollTimer) clearTimeout(pollTimer); });
</script>

{#if visible.length}
  <aside class="mini-job-status" class:expanded aria-label="Active job status">
    <button class="mini-job-summary" aria-expanded={expanded} onclick={() => expanded = !expanded}>
      <span class="mini-job-dot"></span><b>{running.length} running · {waiting.length} waiting</b><span class="mini-job-chevron">{expanded ? '⌄' : '⌃'}</span>
    </button>
    {#if expanded}
      <div class="mini-job-list">
        {#each visible as job}
          {@const value = progress(job)}
          <button class:waiting={isWaiting(job) && !isRunning(job)} class="mini-job-row" onclick={onOpenJobs} title={`${title(job)} · ${job.stage}`}>
            <span>{title(job)}</span><b>{isWaiting(job) && !isRunning(job) ? 'waiting' : `${Math.round(value)}%`}</b>
            <progress max="100" value={value}></progress>
          </button>
        {/each}
        <button class="mini-job-open" onclick={onOpenJobs}>Open jobs</button>
      </div>
    {/if}
  </aside>
{/if}
