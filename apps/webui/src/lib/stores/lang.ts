import { writable } from 'svelte/store';
import { browser } from '$app/environment';

type Lang = 'en' | 'kr';

const STORAGE_KEY = 'robomituba_lang';

function createLangStore() {
	const initial: Lang = browser
		? ((localStorage.getItem(STORAGE_KEY) as Lang) ?? 'en')
		: 'en';

	const { subscribe, set } = writable<Lang>(initial);

	return {
		subscribe,
		set(l: Lang) {
			if (browser) localStorage.setItem(STORAGE_KEY, l);
			set(l);
		}
	};
}

export const lang = createLangStore();

/** 현재 언어에 맞는 문자열 반환 */
export function t(en: string, kr: string, currentLang: Lang): string {
	return currentLang === 'kr' ? kr : en;
}
