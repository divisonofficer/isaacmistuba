/**
 * AssetVM — reactive ViewModel for asset catalog, material library, and camera rig.
 *
 * Owns all asset-related state (material groups, camera rig, USD catalog, envmaps).
 * Does NOT own cross-VM derived state that depends on authoring map or project context
 * (rigSensorOptions, filteredMaterialCards, selectedMaterialInfo).
 *
 * Usage:
 *   import { assetVM } from '$lib/datasets/vm/AssetVM.svelte';
 *   assetVM.loadMaterialLibrary();
 *   $derived(assetVM.materialCards)
 */

import type { CameraRig } from '$lib/api';
import { buildMaterialCards } from '$lib/datasets/materialHelpers';
import * as assetService from '$lib/datasets/services/assetService';
import { usdAssetLabel } from '$lib/datasets/authoringHelpers';
import { errorMessage } from '$lib/datasets/batchHelpers';

const LIBRARY_DISPLAY_LIMIT = 40;

class AssetVM {
	// ── Material library ──────────────────────────────────────────
	materialGroups = $state<any[]>([]);
	materialLibraryStatus = $state('Material library not loaded.');

	// ── Camera rig ────────────────────────────────────────────────
	globalCameraRig = $state<CameraRig | null>(null);
	globalCameraRigStatus = $state('Camera rig preset not loaded.');
	globalCameraRigError = $state('');

	// ── Project-scoped map assets ─────────────────────────────────
	mapAssets = $state<any[]>([]);
	mapAssetStatus = $state('No library assets loaded.');

	// ── Moorelane USD candidates ──────────────────────────────────
	usdCandidates = $state<any[]>([]);
	usdCandidateStatus = $state('USD candidates not loaded.');
	selectedMoorelaneUsdRef = $state('');

	// ── Editor geometry (USD proxy catalog) ───────────────────────
	editorGeometryPayload = $state<any>(null);
	editorGeometryCatalogStatus = $state('USD asset catalog not loaded.');
	editorGeometryRefreshToken = $state(0);
	assetThumbRefreshTick = $state(0);
	// Cache key — not reactive, used to skip redundant fetches
	#editorGeometryCatalogKey = '';

	// ── USD asset selection ───────────────────────────────────────
	selectedUsdAssetId = $state('');
	usdCatalogSearch = $state('');

	// ── Environment maps ──────────────────────────────────────────
	envmapFiles = $state<any[]>([]);
	envmapUploading = $state(false);

	// ── Derived ───────────────────────────────────────────────────
	materialCards = $derived(buildMaterialCards(this.materialGroups));

	usdAssetSelectionPool = $derived(this.mapAssets as any[]);

	#usdAssetCandidatesAll = $derived.by(() => {
		const all = (this.mapAssets as any[]).filter((item: any) => item.usable_by_agent !== false && ['texture_ready', 'analytic_ok'].includes(String(item.render_readiness ?? '')));
		if (!this.usdCatalogSearch.trim()) return all;
		const q = this.usdCatalogSearch.toLowerCase();
		return all.filter(
			(item: any) =>
				usdAssetLabel(item).toLowerCase().includes(q) ||
				(item.category ?? '').toLowerCase().includes(q) ||
				(item.source_path ?? '').toLowerCase().includes(q) ||
				(item.tags ?? []).join(' ').toLowerCase().includes(q)
		);
	});

	usdAssetCandidates = $derived(
		this.usdCatalogSearch.trim()
			? this.#usdAssetCandidatesAll
			: this.#usdAssetCandidatesAll.slice(0, LIBRARY_DISPLAY_LIMIT)
	);

	selectedUsdAsset = $derived(
		this.usdAssetSelectionPool.find(
			(item: any) => (item.asset_id ?? item.id) === this.selectedUsdAssetId
		) ??
			this.#usdAssetCandidatesAll[0] ??
			null
	);

	// ── Actions ───────────────────────────────────────────────────

	async loadMaterialLibrary() {
		try {
			const payload = await assetService.fetchMaterialLibrary();
			this.materialGroups = payload.groups ?? [];
			const count = this.materialGroups.reduce(
				(acc: number, g: any) => acc + (g.materials?.length ?? 0),
				0
			);
			this.materialLibraryStatus = `${count} library materials loaded.`;
		} catch (err) {
			this.materialGroups = [];
			this.materialLibraryStatus =
				err instanceof Error
					? `Material library unavailable: ${err.message}`
					: 'Material library unavailable.';
		}
	}

	async loadGlobalCameraRig(rigId = 'ranger_mini_default') {
		this.globalCameraRigError = '';
		this.globalCameraRigStatus = 'Loading camera rig preset...';
		try {
			const rig = await assetService.fetchCameraRig(rigId);
			this.globalCameraRig = rig;
			this.globalCameraRigStatus = `Using ${rig.label || rig.rig_id} (${rig.sensors?.length ?? 0} sensors) from global Camera Rig preset.`;
		} catch (err) {
			this.globalCameraRig = null;
			this.globalCameraRigError = errorMessage(err);
			this.globalCameraRigStatus =
				'Global Camera Rig preset unavailable; falling back to legacy authoring map sensors.';
		}
	}

	async loadUsdCandidates() {
		try {
			const payload = await assetService.fetchUsdCandidates();
			this.usdCandidates = payload.candidates ?? [];
			if (!this.selectedMoorelaneUsdRef && this.usdCandidates.length) {
				this.selectedMoorelaneUsdRef = this.usdCandidates[0].usd_ref;
			}
			this.usdCandidateStatus = `${this.usdCandidates.length} Moorelane USD files found.`;
		} catch (err) {
			this.usdCandidates = [];
			this.usdCandidateStatus =
				err instanceof Error
					? `USD candidates unavailable: ${err.message}`
					: 'USD candidates unavailable.';
		}
	}

	async loadMapAssets(projectId: string) {
		if (!projectId) {
			this.mapAssets = [];
			this.mapAssetStatus = 'Select a project to load map assets.';
			return;
		}
		try {
			const payload = await assetService.fetchMapAssets(projectId);
			this.mapAssets = payload.assets ?? [];
			this.mapAssetStatus = this.mapAssets.length
				? `${this.mapAssets.length} selected asset(s) from Asset Library.`
				: 'No assets in this project\'s Asset Library.';
			if (!this.selectedUsdAssetId && this.mapAssets.length) {
				this.selectedUsdAssetId = this.mapAssets[0].asset_id ?? this.mapAssets[0].id;
			}
			if (
				this.selectedUsdAssetId &&
				!this.mapAssets.some(
					(item: any) => (item.asset_id ?? item.id) === this.selectedUsdAssetId
				)
			) {
				this.selectedUsdAssetId = this.mapAssets[0]?.asset_id ?? this.mapAssets[0]?.id ?? '';
			}
		} catch (err) {
			this.mapAssets = [];
			this.mapAssetStatus =
				err instanceof Error ? `Map assets unavailable: ${err.message}` : 'Map assets unavailable.';
		}
	}

	async loadEditorGeometryCatalog(
		projectId: string,
		sceneId: string,
		usdRef: string,
		opts: { force?: boolean; refreshExtraction?: boolean } = {}
	) {
		const { force = false, refreshExtraction = false } = opts;
		if (!projectId || !sceneId) return;
		const key = `${projectId}:${sceneId}:${usdRef}`;
		if (!force && !refreshExtraction && key === this.#editorGeometryCatalogKey && this.editorGeometryPayload) {
			return;
		}
		this.#editorGeometryCatalogKey = key;
		try {
			this.editorGeometryCatalogStatus = refreshExtraction
				? 'Extracting USD proxy geometry...'
				: 'Loading USD asset proxies...';
			const payload = await assetService.fetchEditorGeometry(projectId, sceneId, refreshExtraction);
			this.editorGeometryPayload = payload;
			const count = (payload.objects ?? []).filter((item: any) => item.category !== 'floor').length;
			if (payload.status === 'ready') {
				this.editorGeometryCatalogStatus = `${count} USD proxy assets loaded.`;
				this.editorGeometryRefreshToken += 1;
			} else {
				this.editorGeometryCatalogStatus = 'USD asset catalog unavailable.';
			}
			if (!this.selectedUsdAssetId && count) {
				const first = (payload.objects ?? []).find((item: any) => item.category !== 'floor');
				this.selectedUsdAssetId = first?.id ?? '';
			}
		} catch (err) {
			this.editorGeometryPayload = null;
			this.editorGeometryCatalogStatus =
				err instanceof Error
					? `USD asset catalog unavailable: ${err.message}`
					: 'USD asset catalog unavailable.';
		}
	}

	async loadEnvmaps(projectId: string, sceneId: string) {
		if (!projectId || !sceneId) {
			this.envmapFiles = [];
			return;
		}
		try {
			const data = await assetService.fetchEnvmaps(projectId, sceneId);
			this.envmapFiles = data?.envmaps ?? [];
		} catch {
			this.envmapFiles = [];
		}
	}

	async uploadEnvmap(
		projectId: string,
		sceneId: string,
		params: assetService.UploadEnvmapParams
	): Promise<{ envmap_ref?: string; filename?: string; size_bytes?: number } | null> {
		this.envmapUploading = true;
		try {
			const data = await assetService.uploadEnvmap(projectId, sceneId, params);
			await this.loadEnvmaps(projectId, sceneId);
			return data ?? null;
		} finally {
			this.envmapUploading = false;
		}
	}

	bumpAssetThumbTick() {
		this.assetThumbRefreshTick += 1;
	}

	reset() {
		this.materialGroups = [];
		this.materialLibraryStatus = 'Material library not loaded.';
		this.globalCameraRig = null;
		this.globalCameraRigStatus = 'Camera rig preset not loaded.';
		this.globalCameraRigError = '';
		this.mapAssets = [];
		this.mapAssetStatus = 'No library assets loaded.';
		this.usdCandidates = [];
		this.usdCandidateStatus = 'USD candidates not loaded.';
		this.editorGeometryPayload = null;
		this.editorGeometryCatalogStatus = 'USD asset catalog not loaded.';
		this.editorGeometryRefreshToken = 0;
		this.envmapFiles = [];
		this.envmapUploading = false;
		this.#editorGeometryCatalogKey = '';
	}
}

export const assetVM = new AssetVM();
