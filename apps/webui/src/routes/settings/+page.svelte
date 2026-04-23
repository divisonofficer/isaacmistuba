<script lang="ts">
	import { healthStore } from '$lib/stores/health';
	import { lang } from '$lib/stores/lang';
	import { setTheme, theme } from '$lib/stores/theme';
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
