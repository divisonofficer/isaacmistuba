import { getOpticalNavPrimMesh } from '$lib/api';

export type PrimMeshPayload = {
	vertices?: number[];
	indices?: number[];
	bounds?: unknown;
	cache_key?: unknown;
	[key: string]: unknown;
};

const CACHE_VERSION = 'prim-mesh-cache-v1';
const DB_NAME = 'robomituba-opticalnav';
const STORE_NAME = 'prim_mesh';
const MAX_MEMORY_ENTRIES = 96;
const MAX_IDB_AGE_MS = 14 * 24 * 60 * 60 * 1000;

type CacheRecord = {
	key: string;
	payload: PrimMeshPayload;
	updatedAt: number;
};

const memory = new Map<string, PrimMeshPayload | null>();
const pending = new Map<string, Promise<PrimMeshPayload | null>>();
let dbPromise: Promise<IDBDatabase | null> | null = null;

export function primMeshCacheKey(projectId: string, sceneId: string, sourcePath: string, usdRef = '') {
	const assetRef = usdRef ? `${usdRef}#${sourcePath}` : `${projectId}/${sceneId}#${sourcePath}`;
	return `${CACHE_VERSION}:${assetRef}`;
}

export function getCachedPrimMeshPayload(key: string): PrimMeshPayload | null | undefined {
	return memory.get(key);
}

export async function loadCachedPrimMeshPayload(
	projectId: string,
	sceneId: string,
	sourcePath: string,
	usdRef = ''
): Promise<PrimMeshPayload | null> {
	const key = primMeshCacheKey(projectId, sceneId, sourcePath, usdRef);
	if (memory.has(key)) return memory.get(key) ?? null;
	if (pending.has(key)) return pending.get(key) ?? null;

	const task = (async () => {
		const stored = await readIdb(key);
		if (stored) {
			setMemory(key, stored.payload);
			return stored.payload;
		}

		try {
			const payload = (await getOpticalNavPrimMesh(projectId, sceneId, sourcePath, usdRef || undefined)) as PrimMeshPayload;
			if (hasMesh(payload)) {
				setMemory(key, payload);
				void writeIdb({ key, payload, updatedAt: Date.now() });
				return payload;
			}
		} catch {
			// Cache the miss for this page lifetime so repeated rebuilds don't hammer the backend.
		}
		setMemory(key, null);
		return null;
	})();

	pending.set(key, task);
	try {
		return await task;
	} finally {
		pending.delete(key);
	}
}

function hasMesh(payload: PrimMeshPayload | null | undefined): boolean {
	return Boolean(
		payload &&
			Array.isArray(payload.vertices) &&
			Array.isArray(payload.indices) &&
			payload.vertices.length > 0 &&
			payload.indices.length > 0
	);
}

function setMemory(key: string, payload: PrimMeshPayload | null) {
	if (memory.has(key)) memory.delete(key);
	memory.set(key, payload);
	while (memory.size > MAX_MEMORY_ENTRIES) {
		const oldest = memory.keys().next().value;
		if (!oldest) break;
		memory.delete(oldest);
	}
}

function openDb(): Promise<IDBDatabase | null> {
	if (typeof indexedDB === 'undefined') return Promise.resolve(null);
	if (dbPromise) return dbPromise;
	dbPromise = new Promise((resolve) => {
		const request = indexedDB.open(DB_NAME, 1);
		request.onupgradeneeded = () => {
			const db = request.result;
			if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: 'key' });
		};
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => resolve(null);
		request.onblocked = () => resolve(null);
	});
	return dbPromise;
}

async function readIdb(key: string): Promise<CacheRecord | null> {
	const db = await openDb();
	if (!db) return null;
	return new Promise((resolve) => {
		const tx = db.transaction(STORE_NAME, 'readonly');
		const request = tx.objectStore(STORE_NAME).get(key);
		request.onsuccess = () => {
			const record = request.result as CacheRecord | undefined;
			if (!record || Date.now() - Number(record.updatedAt || 0) > MAX_IDB_AGE_MS) {
				resolve(null);
				return;
			}
			resolve(record);
		};
		request.onerror = () => resolve(null);
	});
}

async function writeIdb(record: CacheRecord): Promise<void> {
	const db = await openDb();
	if (!db) return;
	await new Promise<void>((resolve) => {
		const tx = db.transaction(STORE_NAME, 'readwrite');
		tx.objectStore(STORE_NAME).put(record);
		tx.oncomplete = () => resolve();
		tx.onerror = () => resolve();
		tx.onabort = () => resolve();
	});
}
