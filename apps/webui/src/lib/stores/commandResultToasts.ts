import { writable } from 'svelte/store';

export interface CommandResultToast {
	id: string;
	kind: 'success' | 'error';
	label: string;
	message?: string;
	elapsedS?: number;
}

export const commandResultToasts = writable<CommandResultToast[]>([]);

const TTL_MS = 6500;
const MAX = 5;

export function pushCommandResultToast(t: CommandResultToast): void {
	commandResultToasts.update((list) => {
		if (list.some((x) => x.id === t.id)) return list;
		return [...list, t].slice(-MAX);
	});
	setTimeout(() => {
		commandResultToasts.update((list) => list.filter((x) => x.id !== t.id));
	}, TTL_MS);
}

export function dismissCommandResultToast(id: string): void {
	commandResultToasts.update((list) => list.filter((x) => x.id !== id));
}

const COMMAND_LABELS: Record<string, { kr: string; en: string }> = {
	connect_session:        { kr: '세션 연결',         en: 'Connect session' },
	disconnect_session:     { kr: '세션 해제',         en: 'Disconnect session' },
	sync_session:           { kr: '동기화',           en: 'Sync session' },
	prepare_render_ready:   { kr: '장면 준비',        en: 'Prepare scene' },
	render_current_view:    { kr: '현재 뷰 렌더',     en: 'Render current view' },
	render_sensor:          { kr: '센서 렌더',        en: 'Render sensor' },
	load_scene:             { kr: '장면 로드',        en: 'Load scene' },
	capture_view:           { kr: '뷰 캡처',          en: 'Capture view' }
};

export function commandTypeLabel(cmdType: string, lang: 'kr' | 'en'): string {
	const entry = COMMAND_LABELS[cmdType];
	if (entry) return lang === 'kr' ? entry.kr : entry.en;
	return cmdType.replace(/_/g, ' ');
}
