import { writable, get } from 'svelte/store';
import { isaacCommand } from '$lib/api';
import { healthStore } from './health';

export const cmdPending = writable<string | null>(null);
export const cmdMsg = writable<string>('');

export const currentSceneIdStore = writable<string | null>(null);
export const currentSceneStore = writable<Record<string, unknown> | null>(null);

export async function runCmd(cmd: string, sceneIdOverride?: string) {
	const fromHealth = get(healthStore)?.isaac_scene_id;
	const fromSummary = get(currentSceneIdStore);
	const sceneId =
		sceneIdOverride ??
		(typeof fromHealth === 'string' ? fromHealth : null) ??
		fromSummary;
	if (!sceneId || typeof sceneId !== 'string') return;
	if (get(cmdPending)) return;
	cmdPending.set(cmd);
	cmdMsg.set('');
	try {
		await isaacCommand(cmd, sceneId);
		cmdMsg.set(`${cmd} sent`);
	} catch (e: unknown) {
		cmdMsg.set((e as Error).message ?? 'error');
	} finally {
		cmdPending.set(null);
	}
}
