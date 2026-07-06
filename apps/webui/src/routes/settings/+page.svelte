<script lang="ts">
	import { onMount } from 'svelte';
	import { healthStore } from '$lib/stores/health';
	import { lang } from '$lib/stores/lang';
	import { setTheme, theme } from '$lib/stores/theme';
	import { getUserSettings, setUserSettings } from '$lib/api';

	type StorageOverrides = Record<string, string>;
	type DatasetRow = { id: string; label: string; hint: string; placeholder: string };

	const DATASETS: DatasetRow[] = [
		{
			id: 'hpbrdf_2025',
			label: 'hpBRDF (KAIST SIGGRAPH Asia 2025)',
			hint: '14 files × ~13 GB ≈ 182 GB total. WSL: /mnt/d/... 권장.',
			placeholder: '/mnt/d/hpbrdf'
		}
	];

	let overrides = $state<StorageOverrides>({});
	let settingsPath = $state<string>('');
	let previewSpp = $state<number | ''>('');
	let loading = $state(true);
	let saving = $state(false);
	let saveMsg = $state<string>('');

	// Render / BSDF preferences (daemon-side). bsdf_mode + texture cap take effect
	// on the next sync/render; pBRDF band + measured scope are picked up by the
	// dataset editor's render requests.
	let bsdfMode = $state<string>('');        // '' = follow launcher env default
	let textureRes = $state<number | ''>('');  // '' = daemon default
	let pbrdfBand = $state<string>('single');
	let measuredScope = $state<string>('analytic_only');
	let savingRender = $state(false);
	let renderMsg = $state<string>('');

	const SPP_PRESETS = [256, 1024, 2048, 4096, 8192, 16384];
	const TEX_PRESETS = [256, 512, 1024, 2048, 4096];
	const BSDF_MODES = [
		{ id: '', label: 'default (launcher env)' },
		{ id: 'legacy', label: 'legacy — hardcoded int_ior=1.5 / Al' },
		{ id: 'injected', label: 'injected — per-material IOR + real metal eta-k' },
		{ id: 'measured', label: 'measured — measured pBRDF reference' }
	];
	const PBRDF_BANDS = [
		{ id: 'rgb', label: 'rgb · 3-band (full colour)' },
		{ id: 'hybrid', label: 'hybrid · achromatic→1, coloured→3' },
		{ id: 'single', label: 'single · 1-band ×albedo' }
	];
	const MEASURED_SCOPES = [
		{ id: 'analytic_only', label: 'analytic-only · 0 measured (default)' },
		{ id: 'analytic_priority', label: 'analytic-priority · anchors only' },
		{ id: 'budgeted_measured', label: 'budgeted · up to 3' },
		{ id: 'measured_full', label: 'full measured · HQ' }
	];

	onMount(async () => {
		try {
			const r = await getUserSettings();
			overrides = (r?.settings?.dataset_storage_overrides as StorageOverrides) ?? {};
			const spp = r?.settings?.material_preview_spp;
			previewSpp = typeof spp === 'number' ? spp : '';
			bsdfMode = typeof r?.settings?.bsdf_mode === 'string' ? r.settings.bsdf_mode : '';
			const tr = r?.settings?.texture_max_resolution;
			textureRes = typeof tr === 'number' ? tr : '';
			pbrdfBand = typeof r?.settings?.pbrdf_band_mode === 'string' ? r.settings.pbrdf_band_mode : 'single';
			measuredScope = typeof r?.settings?.measured_scope === 'string' ? r.settings.measured_scope : 'analytic_only';
			settingsPath = String(r?.settings_path ?? '');
		} catch {
			// ignore — leave defaults
		} finally {
			loading = false;
		}
	});

	async function saveRender() {
		savingRender = true;
		renderMsg = '';
		try {
			await setUserSettings({
				bsdf_mode: bsdfMode || null,
				texture_max_resolution: typeof textureRes === 'number' && textureRes > 0 ? textureRes : null,
				pbrdf_band_mode: pbrdfBand,
				measured_scope: measuredScope
			});
			renderMsg = $lang === 'kr' ? '저장됨 · 다음 sync/render부터 적용' : 'Saved — applies to the next sync/render';
		} catch (e: unknown) {
			renderMsg = (e as Error).message ?? 'error';
		} finally {
			savingRender = false;
			setTimeout(() => { renderMsg = ''; }, 3000);
		}
	}

	async function save() {
		saving = true;
		saveMsg = '';
		try {
			const cleaned: StorageOverrides = {};
			for (const [k, v] of Object.entries(overrides)) {
				const t = (v ?? '').trim();
				if (t) cleaned[k] = t;
			}
			const sppValue = typeof previewSpp === 'number' && previewSpp > 0 ? previewSpp : null;
			await setUserSettings({
				dataset_storage_overrides: cleaned,
				material_preview_spp: sppValue
			});
			overrides = cleaned;
			saveMsg = $lang === 'kr' ? '저장됨' : 'Saved';
		} catch (e: unknown) {
			saveMsg = (e as Error).message ?? 'error';
		} finally {
			saving = false;
			setTimeout(() => { saveMsg = ''; }, 2500);
		}
	}
</script>

<div class="grid lg:grid-cols-3 gap-4 mt-4">
	<div class="panel">
		<div class="panel-label">{$lang === 'kr' ? '언어' : 'Language'}</div>
		<div class="settings-row mt-3">
			<button
				class="button {$lang === 'en' ? 'button-primary' : 'button-subtle'} text-sm"
				onclick={() => lang.set('en')}
			>
				English
			</button>
			<button
				class="button {$lang === 'kr' ? 'button-primary' : 'button-subtle'} text-sm"
				onclick={() => lang.set('kr')}
			>
				한국어
			</button>
		</div>
	</div>

	<div class="panel">
		<div class="panel-label">{$lang === 'kr' ? '테마' : 'Theme'}</div>
		<div class="settings-row mt-3" role="group" aria-label="Theme mode">
			<button
				class="button {$theme === 'light' ? 'button-primary' : 'button-subtle'} text-sm"
				aria-pressed={$theme === 'light'}
				onclick={() => setTheme('light')}
			>
				{$lang === 'kr' ? '라이트' : 'Light'}
			</button>
			<button
				class="button {$theme === 'dark' ? 'button-primary' : 'button-subtle'} text-sm"
				aria-pressed={$theme === 'dark'}
				onclick={() => setTheme('dark')}
			>
				{$lang === 'kr' ? '다크' : 'Dark'}
			</button>
		</div>
		<p class="muted text-xs mt-3">
			{$lang === 'kr' ? '라이트 모드를 기본으로 저장합니다.' : 'Light mode remains the default for new sessions.'}
		</p>
	</div>

	{#if $healthStore}
		{@const h = $healthStore}
		<div class="panel">
			<div class="panel-label">{$lang === 'kr' ? '런타임 정보' : 'Runtime Info'}</div>
			<div class="kv-list mt-3 text-sm">
				<div><span>Base URL</span><span class="mono text-xs">{h.base_url}</span></div>
				<div><span>Variant</span><span class="mono">{h.variant}</span></div>
				<div><span>{$lang === 'kr' ? '워커 상태' : 'Worker'}</span><span>{h.worker_state}</span></div>
				<div><span>{$lang === 'kr' ? '큐' : 'Queue'}</span><span>{h.queue_length} jobs</span></div>
			</div>
		</div>
	{/if}
</div>

<div class="panel mt-4">
	<div class="panel-label">{$lang === 'kr' ? '렌더 / BSDF' : 'Render / BSDF'}</div>
	<p class="muted text-xs mt-2">
		{$lang === 'kr'
			? 'render_scene.xml 생성(sync) 및 렌더에 적용되는 daemon 설정. BSDF mode / 텍스처 캡은 저장 즉시 os.environ에 반영되어 다음 sync/render부터 적용됩니다(재시작 불필요). pBRDF band / measured scope는 dataset editor의 렌더 요청에 사용됩니다.'
			: 'Daemon-side settings applied at render_scene.xml sync + render time. BSDF mode / texture cap are mirrored into the daemon env on save (next sync/render, no restart). pBRDF band / measured scope feed the dataset editor render requests.'}
	</p>
	{#if !loading}
		<div class="settings-render-grid mt-3">
			<label class="settings-render-row">
				<span class="settings-storage-name">BSDF mode</span>
				<select class="settings-storage-input" bind:value={bsdfMode}>
					{#each BSDF_MODES as m}<option value={m.id}>{m.label}</option>{/each}
				</select>
			</label>

			<label class="settings-render-row">
				<span class="settings-storage-name">{$lang === 'kr' ? '텍스처 최대 해상도' : 'Texture max resolution'}</span>
				<div style="display:flex;gap:0.4rem;flex-wrap:wrap;align-items:center">
					<input class="settings-storage-input mono" type="number" min="128" max="8192" step="128"
						placeholder={$lang === 'kr' ? '기본값' : 'default'} bind:value={textureRes} style="width:8rem" />
					{#each TEX_PRESETS as v}
						<button class="button {textureRes === v ? 'button-primary' : 'button-subtle'} text-xs" onclick={() => (textureRes = v)}>{v}</button>
					{/each}
					<button class="button {textureRes === '' ? 'button-primary' : 'button-subtle'} text-xs" onclick={() => (textureRes = '')}>{$lang === 'kr' ? '기본값' : 'default'}</button>
				</div>
			</label>

			<label class="settings-render-row">
				<span class="settings-storage-name">pBRDF band</span>
				<select class="settings-storage-input" bind:value={pbrdfBand}>
					{#each PBRDF_BANDS as b}<option value={b.id}>{b.label}</option>{/each}
				</select>
			</label>

			<label class="settings-render-row">
				<span class="settings-storage-name">Measured scope</span>
				<select class="settings-storage-input" bind:value={measuredScope}>
					{#each MEASURED_SCOPES as s}<option value={s.id}>{s.label}</option>{/each}
				</select>
			</label>
		</div>
		<div class="settings-row mt-3" style="align-items:center;gap:0.6rem">
			<button class="button button-primary text-sm" onclick={saveRender} disabled={savingRender}>
				{savingRender ? '…' : ($lang === 'kr' ? '저장' : 'Save')}
			</button>
			{#if renderMsg}<span class="muted text-xs">{renderMsg}</span>{/if}
		</div>
	{/if}
</div>

<div class="panel mt-4">
	<div class="panel-label">{$lang === 'kr' ? '데이터셋 저장 경로' : 'Dataset Storage Paths'}</div>
	<p class="muted text-xs mt-2">
		{$lang === 'kr'
			? '큰 데이터셋(예: hpBRDF, ~182 GB)을 다른 디스크에 받고 싶을 때 절대 경로로 지정하세요. 비워두면 기본 위치(repo 안 data/<dataset>/) 에 받습니다.'
			: 'Override the install location for large datasets. Leave blank to use the repo default (data/<dataset>/).'}
	</p>
	{#if loading}
		<p class="muted text-xs mt-3">{$lang === 'kr' ? '불러오는 중…' : 'Loading…'}</p>
	{:else}
		<div class="settings-storage-list mt-3">
			{#each DATASETS as ds (ds.id)}
				<div class="settings-storage-row">
					<div class="settings-storage-meta">
						<div class="settings-storage-name">{ds.label}</div>
						<div class="muted text-xs">{ds.hint}</div>
					</div>
					<input
						class="settings-storage-input mono"
						type="text"
						placeholder={ds.placeholder}
						bind:value={overrides[ds.id]}
						spellcheck="false"
					/>
				</div>
			{/each}
		</div>
		<div class="settings-row mt-3" style="align-items:center;gap:0.6rem">
			<button class="button button-primary text-sm" onclick={save} disabled={saving}>
				{saving ? '…' : ($lang === 'kr' ? '저장' : 'Save')}
			</button>
			{#if saveMsg}<span class="muted text-xs">{saveMsg}</span>{/if}
			{#if settingsPath}
				<span class="muted text-xs" style="margin-left:auto">
					{$lang === 'kr' ? '설정 파일' : 'Config'}: <span class="mono">{settingsPath}</span>
				</span>
			{/if}
		</div>
	{/if}
</div>

<div class="panel mt-4">
	<div class="panel-label">{$lang === 'kr' ? '재질 프리뷰 품질 (spp)' : 'Material Preview Quality (spp)'}</div>
	<p class="muted text-xs mt-2">
		{$lang === 'kr'
			? 'Mitsuba sphere preview 의 samples per pixel. 높을수록 노이즈가 줄지만 GPU 시간이 비례해서 늘어요. 비워두면 기본값 (큐레이션 2048 / 측정 384) 을 사용합니다.'
			: 'Samples per pixel for the sphere preview render. Higher = less noise, longer GPU time. Leave blank to use the per-type defaults (curated 2048 / measured 384).'}
	</p>
	{#if !loading}
		<div class="settings-row mt-3" style="align-items:center;gap:0.6rem;flex-wrap:wrap">
			<input
				class="settings-storage-input mono"
				type="number"
				min="16"
				max="16384"
				step="64"
				placeholder={$lang === 'kr' ? '기본값 사용' : 'use default'}
				bind:value={previewSpp}
				style="width:9rem"
			/>
			<div style="display:flex;gap:0.3rem;flex-wrap:wrap">
				{#each SPP_PRESETS as v}
					<button
						class="button {previewSpp === v ? 'button-primary' : 'button-subtle'} text-xs"
						onclick={() => (previewSpp = v)}
					>{v}</button>
				{/each}
				<button
					class="button {previewSpp === '' ? 'button-primary' : 'button-subtle'} text-xs"
					onclick={() => (previewSpp = '')}
				>{$lang === 'kr' ? '기본값' : 'default'}</button>
			</div>
			<button class="button button-primary text-sm" onclick={save} disabled={saving}
				style="margin-left:auto">
				{saving ? '…' : ($lang === 'kr' ? '저장' : 'Save')}
			</button>
		</div>
		<p class="muted text-xs mt-2">
			{$lang === 'kr'
				? '※ 저장 후 재질 카드에서 ⋯ → 「프리뷰 재렌더」 를 눌러 새 spp 값으로 다시 렌더링하세요.'
				: 'After saving, use a card\'s ⋯ → "Re-render preview" to regenerate at the new spp.'}
		</p>
	{/if}
</div>

<style>
	.settings-storage-list {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}
	.settings-storage-row {
		display: grid;
		grid-template-columns: minmax(12rem, 1fr) minmax(14rem, 2fr);
		align-items: center;
		gap: 1rem;
	}
	.settings-storage-meta {
		min-width: 0;
	}
	.settings-storage-name {
		font-weight: 600;
		font-size: 0.85rem;
		color: var(--text);
	}
	.settings-storage-input {
		appearance: none;
		width: 100%;
		padding: 0.45rem 0.6rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm, 0.4rem);
		background: var(--panel-deep, var(--panel));
		color: var(--text);
		font-size: 0.82rem;
	}
	.settings-storage-input:focus {
		outline: none;
		border-color: var(--brand);
		box-shadow: 0 0 0 2px rgba(47, 123, 246, 0.15);
	}
	.settings-render-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.9rem 1.2rem;
	}
	.settings-render-row {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		min-width: 0;
	}
	@media (max-width: 720px) {
		.settings-render-grid { grid-template-columns: 1fr; }
	}
	@media (max-width: 640px) {
		.settings-storage-row {
			grid-template-columns: 1fr;
			gap: 0.35rem;
		}
	}
</style>
