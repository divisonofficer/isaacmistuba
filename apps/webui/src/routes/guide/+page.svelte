<script lang="ts">
	import { lang } from '$lib/stores/lang';
</script>

<div class="page-content">
	<header style="margin: 1.25rem 0 1rem">
		<p class="eyebrow">{$lang === 'kr' ? '운영 매뉴얼' : 'Operations'}</p>
		<h1 class="page-title">{$lang === 'kr' ? '가이드' : 'Guide'}</h1>
		<p class="muted text-sm" style="margin-top: 0.5rem">
			{$lang === 'kr'
				? '데이터 캡처부터 멀티모달 렌더링까지 운영 절차를 모아둔 곳입니다.'
				: 'Operational procedures from capture to multimodal rendering will live here.'}
		</p>
	</header>

	<section class="panel" style="padding: 1.5rem">
		<div class="panel-label">{$lang === 'kr' ? '준비 중' : 'Coming soon'}</div>
		<p class="muted text-sm mt-3">
			{$lang === 'kr'
				? '온보딩, 캡처 절차, 모달리티 정의, 트러블슈팅 항목이 곧 채워집니다.'
				: 'Onboarding, capture flow, modality definitions, and troubleshooting will be populated.'}
		</p>
	</section>
</div>
