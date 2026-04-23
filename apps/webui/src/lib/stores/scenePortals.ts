import { writable } from 'svelte/store';
import type { Snippet } from 'svelte';

export const sceneRailSnippet = writable<Snippet | null>(null);
export const sceneBottomSnippet = writable<Snippet | null>(null);
