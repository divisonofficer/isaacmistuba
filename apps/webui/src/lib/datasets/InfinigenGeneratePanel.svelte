<script lang="ts">
	import { onDestroy } from 'svelte';
	import { startInfinigenGenerate, getInfinigenJob, type InfinigenGenerateRequest } from '$lib/api';

	let { projectId }: { projectId: string | null | undefined } = $props();

	const ARCHETYPES = [
		{ value: 'apartment', label: '아파트 (거실 중심)' },
		{ value: 'office', label: '오피스 (복도망·수십 방)' }
	] as const;
	const DENSITIES = [
		{ value: 'model_house', label: 'model_house (거의 빈)' },
		{ value: 'normal_lived_in', label: 'normal_lived_in (보통)' },
		{ value: 'family_home', label: 'family_home (많음)' },
		{ value: 'storage_heavy', label: 'storage_heavy (창고급)' }
	] as const;

	const todaySeed = () => {
		const d = new Date();
		return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
	};

	let archetype = $state<InfinigenGenerateRequest['archetype']>('apartment');
	let density = $state<InfinigenGenerateRequest['density']>('normal_lived_in');
	let stage = $state<InfinigenGenerateRequest['stage']>('full');
	let seed = $state(todaySeed());
	let importScene = $state(true);
	let bakePbr = $state(false);

	let running = $state(false);
	let error = $state('');
	let jobId = $state<string | null>(null);
	let job = $state<any>(null);
	let timer: ReturnType<typeof setTimeout> | null = null;

	const seedValid = $derived(
		seed.trim() === '' || seed.trim() === 'today' || seed.trim() === 'random' ||
		/^\d{8}$/.test(seed.trim())
	);
	const logTail = $derived((job?.log ?? []).slice(-14) as string[]);

	function stopTimer() {
		if (timer) { clearTimeout(timer); timer = null; }
	}
	onDestroy(stopTimer);

	function poll() {
		stopTimer();
		timer = setTimeout(async () => {
			if (!projectId || !jobId) return;
			try {
				job = await getInfinigenJob(projectId, jobId);
				if (job?.status === 'succeeded' || job?.status === 'failed') {
					running = false;
					return;
				}
			} catch (e) {
				/* transient; keep polling */
			}
			poll();
		}, 1500);
	}

	async function generate() {
		if (!projectId) { error = '프로젝트를 먼저 선택하세요.'; return; }
		if (!seedValid) { error = "seed는 8자리 숫자 / 'today' / 'random' 이어야 합니다."; return; }
		error = '';
		running = true;
		job = null;
		jobId = null;
		try {
			const res = await startInfinigenGenerate(projectId, {
				archetype, density, stage,
				seed: seed.trim() || 'today',
				import_scene: importScene,
				bake_pbr: bakePbr
			});
			jobId = res.job_id;
			job = { status: 'queued', stage: 'queued', scene_id: res.scene_id, seed: res.seed };
			poll();
		} catch (e) {
			error = String(e);
			running = false;
		}
	}
</script>

<section class="infinigen-gen">
	<h4>Infinigen 씬 생성</h4>
	<p class="hint">절차적 floor plan(아파트/오피스)을 생성하고 OpticalNav scene으로 import 합니다.</p>

	<div class="grid">
		<label><span>archetype</span>
			<select bind:value={archetype} disabled={running}>
				{#each ARCHETYPES as o}<option value={o.value}>{o.label}</option>{/each}
			</select>
		</label>
		<label><span>가구 밀도</span>
			<select bind:value={density} disabled={running}>
				{#each DENSITIES as o}<option value={o.value}>{o.label}</option>{/each}
			</select>
		</label>
		<label><span>stage</span>
			<select bind:value={stage} disabled={running}>
				<option value="full">full (가구 solve)</option>
				<option value="layout">layout (벽만, 빠름)</option>
			</select>
		</label>
		<label><span>seed</span>
			<input bind:value={seed} placeholder="today / random / 8자리" disabled={running}
				class:invalid={!seedValid} />
		</label>
	</div>
	<div class="opts">
		<label class="chk"><input type="checkbox" bind:checked={importScene} disabled={running} /> import 까지 진행</label>
		<label class="chk"><input type="checkbox" bind:checked={bakePbr} disabled={running || !importScene} /> PBR bake (~4× 느림)</label>
	</div>

	<button class="button button-primary full" onclick={generate}
		disabled={running || !projectId} title={!projectId ? '프로젝트를 먼저 선택하세요' : ''}>
		{running ? '생성 중…' : 'Generate scene'}
	</button>

	{#if error}<p class="err">{error}</p>{/if}

	{#if job}
		<div class="status" data-status={job.status}>
			<span class="badge">{job.status}</span>
			<span class="stage">{job.stage ?? ''}</span>
			{#if job.scene_id}<code>{job.scene_id}</code>{/if}
		</div>
		{#if logTail.length}
			<pre class="log">{logTail.join('\n')}</pre>
		{/if}
		{#if job.status === 'succeeded'}
			<p class="ok">✓ 완료 — scene "{job.scene_id}" 준비됨. 위 scene 목록에서 새로고침 후 선택하세요.</p>
		{:else if job.status === 'failed'}
			<p class="err">✗ 실패: {job.error ?? `exit ${job.returncode}`}</p>
		{/if}
	{/if}
</section>

<style>
	.infinigen-gen { display: flex; flex-direction: column; gap: 8px; }
	.infinigen-gen h4 { margin: 0; }
	.hint { margin: 0; font-size: 12px; opacity: 0.7; }
	.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
	.grid label, .opts label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
	.grid label span { opacity: 0.7; }
	.opts { display: flex; gap: 16px; }
	.opts .chk { flex-direction: row; align-items: center; gap: 6px; }
	.full { width: 100%; }
	input.invalid { outline: 1px solid #c0392b; }
	.status { display: flex; align-items: center; gap: 8px; font-size: 12px; }
	.status .badge { padding: 1px 8px; border-radius: 10px; background: #444; color: #fff; text-transform: uppercase; font-size: 10px; }
	.status[data-status='succeeded'] .badge { background: #087443; }
	.status[data-status='failed'] .badge { background: #b3261e; }
	.status[data-status='running'] .badge, .status[data-status='queued'] .badge { background: #1d5fd1; }
	.log { max-height: 180px; overflow: auto; background: #111827; color: #e5e7eb; font-size: 11px; padding: 8px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; }
	.err { color: #c0392b; font-size: 12px; margin: 2px 0; }
	.ok { color: #087443; font-size: 12px; margin: 2px 0; }
</style>
