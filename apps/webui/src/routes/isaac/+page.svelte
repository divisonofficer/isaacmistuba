<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { lang } from '$lib/stores/lang';

	onMount(() => {
		void goto('/bridge', { replaceState: true });
	});
</script>

<div class="page-content">
	<p class="muted text-sm" style="margin-top: 2rem">
		{$lang === 'kr' ? '/bridge 로 이동 중…' : 'Redirecting to /bridge…'}
	</p>
</div>
