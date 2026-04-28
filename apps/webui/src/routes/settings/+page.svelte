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

	const SPP_PRESETS = [256, 1024, 2048, 4096, 8192, 16384];

	onMount(async () => {
		try {
			const r = await getUserSettings();
			overrides = (r?.settings?.dataset_storage_overrides as StorageOverrides) ?? {};
			const spp = r?.settings?.material_preview_spp;
			previewSpp = typeof spp === 'number' ? spp : '';
			settingsPath = String(r?.settings_path ?? '');
		} catch {
			// ignore — leave defaults
		} finally {
			loading = false;
		}
	});

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
	@media (max-width: 640px) {
		.settings-storage-row {
			grid-template-columns: 1fr;
			gap: 0.35rem;
		}
	}
</style>
