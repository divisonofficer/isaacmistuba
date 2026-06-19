/**
 * PR2: per-scene mesh_cache OBJ → THREE.BufferGeometry cache.
 *
 * Mirrors the layered design of `primMeshCache.ts` (memory LRU + IndexedDB),
 * but the payload is a parsed BufferGeometry produced by Three.js OBJLoader.
 * Backed by `GET /scenes/<id>/mesh-cache/<filename>` (see opticalNavMeshCacheUrl).
 *
 * Key scheme:
 *   `obj-mesh-cache-v1:${projectId}/${sceneId}#${filename}`
 *
 * mesh_cache OBJs are hash-named (`<digest>.obj`) so their content is
 * effectively immutable; we cache aggressively and only invalidate when the
 * filename itself changes.
 */
import * as THREE from 'three';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { opticalNavMeshCacheUrl } from '$lib/api';

type ThreeBufferGeometry = any;
type ThreeGroup = any;
type ThreeObject3D = any;
type ThreeMesh = any;

const CACHE_VERSION = 'obj-mesh-cache-v3-head-size';
// Distinct DB name from primMeshCache's `robomituba-opticalnav`. Both caches
// opened the same DB at version 1 and each created only its own store in
// onupgradeneeded — whichever ran first won, and the second cache's store was
// never created, so transactions failed with "object stores was not found".
const DB_NAME = 'robomituba-opticalnav-obj';
const STORE_NAME = 'obj_mesh';
const MAX_MEMORY_ENTRIES = 96;
const MAX_IDB_AGE_MS = 14 * 24 * 60 * 60 * 1000;

type SerializedGeometry = {
	positions: Float32Array;
	normals?: Float32Array;
	uvs?: Float32Array;
	indices?: Uint32Array;
	bbox?: { min: [number, number, number]; max: [number, number, number] };
};

type CacheRecord = {
	key: string;
	serialized: SerializedGeometry;
	updatedAt: number;
};

const memory = new Map<string, ThreeBufferGeometry | null>();
const pending = new Map<string, Promise<ThreeBufferGeometry | null>>();
let dbPromise: Promise<IDBDatabase | null> | null = null;

const _loader = new OBJLoader();

// Burst protection: with 100+ OBJ shapes per scene and individual files in the
// MB–10s of MB range, firing every fetch in parallel was hammering the daemon
// (browser console saw 1300+ requests / 1.7 GB in a single sync, the daemon's
// health endpoint timing out). Cap in-flight network fetches; queued waiters
// run as slots free up.
const MAX_CONCURRENT_FETCHES = 2;
let _inflight = 0;
const _waiters: Array<() => void> = [];

async function _acquireSlot(): Promise<void> {
	if (_inflight < MAX_CONCURRENT_FETCHES) {
		_inflight++;
		return;
	}
	await new Promise<void>((resolve) => _waiters.push(resolve));
	_inflight++;
}

function _releaseSlot() {
	_inflight = Math.max(0, _inflight - 1);
	const next = _waiters.shift();
	if (next) next();
}

// Size guard: huge meshes (e.g. Main Couch 65 MB) blow up memory and stall
// rendering with no visual benefit at editor scale. Skip the preview fetch and
// let the caller draw a placeholder; the render path still uses the full OBJ.
const MAX_OBJ_BYTES_FOR_PREVIEW = 16 * 1024 * 1024;

export function objMeshCacheKey(projectId: string, sceneId: string, filename: string): string {
	return `${CACHE_VERSION}:${projectId}/${sceneId}#${filename}`;
}

export function getCachedObjMeshGeometry(key: string): ThreeBufferGeometry | null | undefined {
	return memory.get(key);
}

/**
 * Fetch + parse + cache an OBJ file from the daemon's mesh-cache endpoint.
 * Returns a deduplicated BufferGeometry; callers should clone-on-use if they
 * intend to mutate it (the editor draws each shape from the same source mesh).
 *
 * Returns `null` on fetch / parse failure so callers can fall back to a
 * placeholder box without re-trying every rebuild.
 */
export async function loadObjMeshGeometry(
	projectId: string,
	sceneId: string,
	filename: string,
): Promise<ThreeBufferGeometry | null> {
	const key = objMeshCacheKey(projectId, sceneId, filename);
	if (memory.has(key)) return memory.get(key) ?? null;
	if (pending.has(key)) return pending.get(key) ?? null;

	const task = (async () => {
		// Memory miss → check IndexedDB.
		const stored = await readIdb(key);
		if (stored) {
			// Size guard for IDB-cached entries too: an OBJ written before the
			// threshold was introduced (or before it was tightened) would
			// otherwise bypass the fetch-time guard. positions is the dominant
			// payload; reject roughly above half the OBJ-text threshold (binary
			// is denser than the text form).
			const posBytes = stored.serialized.positions?.byteLength ?? 0;
			if (posBytes > MAX_OBJ_BYTES_FOR_PREVIEW / 2) {
				void deleteIdb(key);
				setMemory(key, null);
				return null;
			}
			const geo = deserializeGeometry(stored.serialized);
			setMemory(key, geo);
			return geo;
		}
		// IDB miss → HEAD size check, then fetch + parse through a small
		// semaphore. A failed OBJ request used to be retried on every scene rebuild,
		// producing long bursts of ERR_CONTENT_LENGTH_MISMATCH in Chrome. Cache
		// misses as null for this page lifetime so placeholders stay cheap.
		await _acquireSlot();
		try {
			const url = opticalNavMeshCacheUrl(projectId, sceneId, filename);
			const headLen = await fetchObjContentLength(url);
			if (Number.isFinite(headLen) && headLen > MAX_OBJ_BYTES_FOR_PREVIEW) {
				setMemory(key, null);
				return null;
			}

			const res = await fetch(url, { headers: { Accept: 'text/plain' } });
			if (!res.ok) {
				setMemory(key, null);
				return null;
			}
			const cl = res.headers.get('content-length');
			const len = cl ? Number(cl) : NaN;
			if (Number.isFinite(len) && len > MAX_OBJ_BYTES_FOR_PREVIEW) {
				try { res.body?.cancel(); } catch { /* noop */ }
				setMemory(key, null);
				return null;
			}
			const text = await res.text();
			const geo = parseObjToGeometry(text);
			if (!geo) {
				setMemory(key, null);
				return null;
			}
			setMemory(key, geo);
			const serialized = serializeGeometry(geo);
			if (serialized) void writeIdb({ key, serialized, updatedAt: Date.now() });
			return geo;
		} catch {
			setMemory(key, null);
			return null;
		} finally {
			_releaseSlot();
		}
	})();

	pending.set(key, task);
	try {
		return await task;
	} finally {
		pending.delete(key);
	}
}

async function fetchObjContentLength(url: string): Promise<number> {
	try {
		const res = await fetch(url, { method: 'HEAD' });
		if (!res.ok) return NaN;
		const cl = res.headers.get('content-length');
		const len = cl ? Number(cl) : NaN;
		return Number.isFinite(len) ? len : NaN;
	} catch {
		return NaN;
	}
}

function parseObjToGeometry(text: string): ThreeBufferGeometry | null {
	let group: ThreeGroup | null = null;
	try {
		group = _loader.parse(text);
	} catch {
		return null;
	}
	if (!group) return null;
	// OBJLoader returns a Group whose children are Mesh objects. Most mesh_cache
	// OBJs are single-group; merge children into one geometry when there are
	// multiple, otherwise just hand the only geometry back.
	const geometries: ThreeBufferGeometry[] = [];
	group.traverse((child: ThreeObject3D) => {
		const mesh = child as ThreeMesh;
		if (mesh.isMesh && mesh.geometry) {
			geometries.push(mesh.geometry as ThreeBufferGeometry);
		}
	});
	if (geometries.length === 0) return null;
	if (geometries.length === 1) {
		const g = geometries[0];
		g.computeBoundingBox();
		if (!g.attributes.normal) g.computeVertexNormals();
		return g;
	}
	// Many shapes: concatenate via simple position-only merge so a missing
	// normal/uv on one sub-mesh doesn't poison the whole. We don't lean on
	// BufferGeometryUtils to avoid the extra import for the rare multi-mesh case.
	const merged = mergeGeometriesByPosition(geometries);
	merged.computeBoundingBox();
	if (!merged.attributes.normal) merged.computeVertexNormals();
	return merged;
}

function mergeGeometriesByPosition(geos: ThreeBufferGeometry[]): ThreeBufferGeometry {
	let total = 0;
	for (const g of geos) {
		const pos = g.getAttribute('position');
		if (pos) total += pos.count;
	}
	const positions = new Float32Array(total * 3);
	let offset = 0;
	for (const g of geos) {
		const pos = g.getAttribute('position');
		if (!pos) continue;
		positions.set(pos.array as ArrayLike<number>, offset);
		offset += pos.count * 3;
	}
	const out = new THREE.BufferGeometry();
	out.setAttribute('position', new THREE.BufferAttribute(positions, 3));
	return out;
}

function serializeGeometry(g: ThreeBufferGeometry): SerializedGeometry | null {
	const pos = g.getAttribute('position');
	if (!pos) return null;
	const positions = new Float32Array(pos.array as ArrayLike<number>);
	const out: SerializedGeometry = { positions };
	const normal = g.getAttribute('normal');
	if (normal) out.normals = new Float32Array(normal.array as ArrayLike<number>);
	const uv = g.getAttribute('uv');
	if (uv) out.uvs = new Float32Array(uv.array as ArrayLike<number>);
	const idx = g.getIndex();
	if (idx) out.indices = new Uint32Array(idx.array as ArrayLike<number>);
	const bbox = g.boundingBox;
	if (bbox) {
		out.bbox = {
			min: [bbox.min.x, bbox.min.y, bbox.min.z],
			max: [bbox.max.x, bbox.max.y, bbox.max.z],
		};
	}
	return out;
}

function deserializeGeometry(s: SerializedGeometry): ThreeBufferGeometry {
	const g = new THREE.BufferGeometry();
	g.setAttribute('position', new THREE.BufferAttribute(s.positions, 3));
	if (s.normals) g.setAttribute('normal', new THREE.BufferAttribute(s.normals, 3));
	if (s.uvs) g.setAttribute('uv', new THREE.BufferAttribute(s.uvs, 2));
	if (s.indices) g.setIndex(new THREE.BufferAttribute(s.indices, 1));
	if (s.bbox) {
		g.boundingBox = new THREE.Box3(
			new THREE.Vector3(...s.bbox.min),
			new THREE.Vector3(...s.bbox.max),
		);
	}
	if (!s.normals) g.computeVertexNormals();
	return g;
}

function setMemory(key: string, geo: ThreeBufferGeometry | null) {
	if (memory.has(key)) memory.delete(key);
	memory.set(key, geo);
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

async function deleteIdb(key: string): Promise<void> {
	const db = await openDb();
	if (!db) return;
	await new Promise<void>((resolve) => {
		const tx = db.transaction(STORE_NAME, 'readwrite');
		tx.objectStore(STORE_NAME).delete(key);
		tx.oncomplete = () => resolve();
		tx.onerror = () => resolve();
		tx.onabort = () => resolve();
	});
}
