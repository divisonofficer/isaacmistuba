/**
 * Pure material helper functions extracted from datasets/+page.svelte.
 * No Svelte state here — all state deps are passed as parameters.
 */

import {
	materialPreviewUrl,
	curatedMaterialPreviewUrl,
	measuredMaterialPreviewUrl,
} from '$lib/api';

// ── Constants ────────────────────────────────────────────────────────────────

export const MATERIAL_PRESET_IDS = [
	'painted_wall',
	'clear_glass',
	'frosted_glass',
	'mirror',
	'wood',
	'fabric',
	'tile',
];

export const EMITTER_KEYWORD_RE =
	/light|lamp|bulb|lumin|fluoresc|fixture|emitter|illum|sconce|chandel|\bled\b/i;

// ── Fully pure functions (no state deps) ─────────────────────────────────────

/** Tanner Helland approximation. Returns linear RGB in [0,1] for the given Kelvin temperature. */
export function kelvinToRgb(kelvin: number): [number, number, number] {
	const t = Math.max(1000, Math.min(40000, kelvin)) / 100;
	let r: number, g: number, b: number;
	if (t <= 66) {
		r = 255;
		g = Math.max(0, 99.4708025861 * Math.log(t) - 161.1195681661);
		b = t <= 19 ? 0 : Math.max(0, 138.5177312231 * Math.log(t - 10) - 305.0447927307);
	} else {
		r = Math.max(0, 329.698727446 * Math.pow(t - 60, -0.1332047592));
		g = Math.max(0, 288.1221695283 * Math.pow(t - 60, -0.0755148492));
		b = 255;
	}
	return [Math.min(255, r) / 255, Math.min(255, g) / 255, Math.min(255, b) / 255];
}

/** Inverse: derive Kelvin from an RGB ratio. Quick 100-step scan — sufficient for UI slider sync. */
export function rgbToKelvinApprox(rgb: [number, number, number]): number {
	let best = 3000;
	let bestErr = Infinity;
	for (let k = 1500; k <= 10000; k += 100) {
		const ref = kelvinToRgb(k);
		const err = Math.abs(ref[0] - rgb[0]) + Math.abs(ref[1] - rgb[1]) + Math.abs(ref[2] - rgb[2]);
		if (err < bestErr) {
			bestErr = err;
			best = k;
		}
	}
	return best;
}

/** Returns true if the object's label or source_ref suggests it is a light fixture. */
export function objectLooksLikeEmitter(obj: any): boolean {
	const tokens = `${obj?.label ?? ''} ${obj?.source_ref ?? ''}`;
	return EMITTER_KEYWORD_RE.test(tokens);
}

export function materialValue(group: any, material: any): string {
	return `${group.dataset_id}:${material.material_id}`;
}

export function materialOptionLabel(material: any): string {
	const status = material.status && material.status !== 'available' ? ` · ${material.status}` : '';
	const source = material.preview_source ? ` · ${material.preview_source}` : '';
	return `${material.display_name ?? material.material_id}${status}${source}`;
}

export function materialCategoryFromText(value: string, fallback = 'all'): string {
	const key = value.toLowerCase();
	if (key.includes('glass') || key.includes('transparent') || key.includes('frost')) return 'glass';
	if (key.includes('mirror') || key.includes('reflect')) return 'mirror';
	if (key.includes('wall') || key.includes('paint') || key.includes('brick') || key.includes('plaster')) return 'wall';
	if (key.includes('floor') || key.includes('tile') || key.includes('carpet') || key.includes('stone')) return 'floor';
	if (key.includes('wood') || key.includes('fabric') || key.includes('leather') || key.includes('chair') || key.includes('table') || key.includes('desk') || key.includes('cabinet') || key.includes('shelf')) return 'furniture';
	if (key.includes('metal') || key.includes('chrome') || key.includes('aluminum') || key.includes('brass')) return 'mirror';
	if (key.includes('keyboard') || key.includes('mouse') || key.includes('monitor') || key.includes('screen') || key.includes('computer') || key.includes('speaker')) return 'furniture';
	if (key.includes('hazard') || key.includes('obstacle')) return 'hazard';
	if (key.includes('fire') || key.includes('extinguisher') || key.includes('alarm')) return 'hazard';
	return fallback;
}

export function materialTagsFor(category: string, group: any = {}, material: any = {}): string[] {
	const tags = new Set<string>();
	const key = `${category} ${group.dataset_id ?? ''} ${material.material_id ?? ''} ${material.display_name ?? ''} ${material.category ?? ''}`.toLowerCase();
	if (category !== 'all') tags.add(category);
	if (key.includes('glass') || key.includes('transparent')) tags.add('transparent');
	if (key.includes('mirror') || key.includes('reflect')) tags.add('reflective');
	if (key.includes('rough') || key.includes('frost')) tags.add('rough');
	if (key.includes('smooth') || key.includes('gloss')) tags.add('smooth');
	if (String(group.dataset_id ?? '').includes('hpbrdf')) {
		tags.add('polarization-ready');
		tags.add('NIR-ready');
	}
	if (String(group.dataset_id ?? '').includes('pbrdf')) tags.add('polarization-ready');
	if (category === 'glass' || category === 'mirror' || category === 'hazard') tags.add('hazard');
	if (category === 'floor') tags.add('floor-safe');
	return [...tags];
}

export function recommendedMaterialCategory(item: any): string {
	const key = `${item?.type ?? ''} ${item?.label ?? ''} ${item?.metadata?.asset_category ?? ''}`.toLowerCase();
	if (!key.trim()) return 'recommended';
	if (key.includes('glass')) return 'glass';
	if (key.includes('mirror')) return 'mirror';
	if (key.includes('wall')) return 'wall';
	if (key.includes('floor') || key.includes('traversable')) return 'floor';
	if (key.includes('chair') || key.includes('table') || key.includes('desk') || key.includes('cabinet') || key.includes('shelf') || key.includes('furniture')) return 'furniture';
	if (key.includes('keyboard') || key.includes('mouse') || key.includes('monitor') || key.includes('screen') || key.includes('computer') || key.includes('speaker')) return 'furniture';
	if (key.includes('hazard') || key.includes('fire') || key.includes('extinguisher') || key.includes('alarm')) return 'hazard';
	return 'recommended';
}

// ── Functions requiring materialGroups state ─────────────────────────────────

export function findMaterialOption(
	value: string | null | undefined,
	materialGroups: any[],
	materialPresetIds: string[] = MATERIAL_PRESET_IDS,
) {
	if (!value || materialPresetIds.includes(value)) return null;
	for (const group of materialGroups) {
		for (const material of group.materials ?? []) {
			if (materialValue(group, material) === value) return { group, material };
		}
	}
	return null;
}

export function materialPreviewSource(
	value: string | null | undefined,
	materialGroups: any[],
	materialPresetIds: string[] = MATERIAL_PRESET_IDS,
): string {
	if (!value) return '';
	if (materialPresetIds.includes(value)) return materialPreviewUrl(value);
	const found = findMaterialOption(value, materialGroups, materialPresetIds);
	if (!found) return '';
	const { group, material } = found;
	if (material.kind === 'curated' || group.dataset_id === 'curated_basic')
		return curatedMaterialPreviewUrl(material.material_id);
	return measuredMaterialPreviewUrl(group.dataset_id, material.material_id, material.native_file);
}

export function materialDisplayLabel(
	value: string | null | undefined,
	materialGroups: any[],
	materialPresetIds: string[] = MATERIAL_PRESET_IDS,
): string {
	if (!value) return 'No material';
	if (materialPresetIds.includes(value)) return value.replace(/_/g, ' ');
	const found = findMaterialOption(value, materialGroups, materialPresetIds);
	return found?.material?.display_name ?? value;
}

export function materialInfo(
	value: string | null | undefined,
	materialGroups: any[],
	materialPresetIds: string[] = MATERIAL_PRESET_IDS,
) {
	if (!value) return null;
	if (materialPresetIds.includes(value)) {
		return { kind: 'preset', label: value, detail: 'Built-in OpticalNav material preset.' };
	}
	const found = findMaterialOption(value, materialGroups, materialPresetIds);
	if (!found) return { kind: 'custom', label: value, detail: 'Registered custom authoring material.' };
	return {
		kind: found.material.kind ?? 'measured',
		label: found.material.display_name ?? found.material.material_id,
		detail: `${found.group.display_name ?? found.group.dataset_id} · ${found.material.status ?? 'unknown'} · ${found.group.mitsuba_strategy ?? 'material library'}`,
		capabilities: found.group.capabilities,
		native_file: found.material.native_file,
		preview_source: found.material.preview_source,
	};
}

// ── Per-scene (authoring-map) materials not in the global catalog ─────────────
// Infinigen-imported materials carry their full render_binding inline
// (bsdf_strategy, optical_class, baked albedo) but have no catalog id, so
// findMaterialOption misses them and the picker shows "custom / none". These
// helpers surface that inline info + a baked-atlas thumbnail instead.

const OPTICAL_CLASS_LABEL: Record<string, string> = {
	diffuse: 'Diffuse', mirror: 'Mirror', glass: 'Glass',
	metal_aluminum: 'Metal', metal_gold: 'Metal · gold', metal_steel: 'Metal · steel',
};
const BSDF_STRATEGY_LABEL: Record<string, string> = {
	pplastic: 'pplastic', roughplastic: 'roughplastic', conductor: 'mirror',
	dielectric: 'glass', roughdielectric: 'frosted glass',
	measured_polarized: 'measured pBRDF', measured: 'measured', diffuse: 'diffuse',
};

/** Find the per-scene authoring material entry (with inline render_binding) by id. */
export function findAuthoringMaterial(materialId: string | null | undefined, authoringMaterials: any[]) {
	if (!materialId || !Array.isArray(authoringMaterials)) return null;
	return authoringMaterials.find((m: any) => m?.material_id === materialId) ?? null;
}

/** Build display info (label + optical class + BSDF + polarization) from a per-scene material entry. */
export function customMaterialInfo(entry: any) {
	if (!entry) return null;
	const rb = entry.render_binding ?? {};
	const pbr = entry.params?.pbr ?? {};
	const oc = String(pbr.optical_class ?? '');
	const strat = String(rb.bsdf_strategy ?? '');
	const polarization = !!(rb.capabilities?.polarization);
	const baseColor = (rb.base_color_factor ?? pbr.base_color ?? null) as number[] | null;
	const opticalClassLabel = OPTICAL_CLASS_LABEL[oc] ?? (oc || 'custom');
	const bsdfLabel = BSDF_STRATEGY_LABEL[strat] ?? (strat || 'custom');
	const detailBits = [opticalClassLabel, bsdfLabel];
	if (polarization) detailBits.push('polarization');
	return {
		kind: 'scene',
		label: String(entry.material_id ?? '').replace(/^shader_/, '').replace(/\.\d+$/, ''),
		detail: detailBits.join(' · '),
		opticalClass: oc, opticalClassLabel,
		bsdfStrategy: strat, bsdfLabel,
		polarization, baseColor,
	};
}

/** CSS rgb() string from a linear [0,1] color triple, or '' when unavailable. */
export function rgbCss(c: number[] | null | undefined): string {
	if (!Array.isArray(c) || c.length < 3) return '';
	const f = (x: number) => Math.max(0, Math.min(255, Math.round(Number(x) * 255)));
	return `rgb(${f(c[0])}, ${f(c[1])}, ${f(c[2])})`;
}

/** Derive the baked-albedo atlas artifact URL from an object's `source_ref`.
 *  "<import>/meshes/<oid>.obj" -> "/artifacts?path=<import>/textures/<oid>_albedo.png".
 *  Returns '' when the ref doesn't match (the <img> 404s gracefully to the swatch). */
export function bakedAtlasArtifactUrl(sourceRef: string | null | undefined): string {
	if (!sourceRef) return '';
	const m = String(sourceRef).match(/^(.*)\/meshes\/(.+)\.obj$/);
	if (!m) return '';
	return `/artifacts?path=${encodeURIComponent(`${m[1]}/textures/${m[2]}_albedo.png`)}`;
}

export function ensureAuthoringMaterial(
	materialId: string,
	materials: any[],
	materialGroups: any[],
	materialPresetIds: string[] = MATERIAL_PRESET_IDS,
): any[] {
	if (
		!materialId ||
		materialPresetIds.includes(materialId) ||
		materials.some((item: any) => item.material_id === materialId)
	)
		return materials;
	const found = findMaterialOption(materialId, materialGroups, materialPresetIds);
	if (!found)
		return [
			...materials,
			{
				material_id: materialId,
				category: 'custom',
				params: {},
				render_binding: {
					kind: 'custom',
					material_id: materialId,
					bsdf_strategy: 'roughplastic',
					unresolved: true,
				},
			},
		];
	const { group, material } = found;
	const kind = material.kind === 'curated' ? 'curated' : 'measured';
	const bsdfStrategy =
		group.mitsuba_strategy || (kind === 'measured' ? 'measured_polarized' : 'roughplastic');
	return [
		...materials,
		{
			material_id: materialId,
			category: material.kind === 'curated' ? (material.category ?? 'curated') : 'measured',
			params: {
				dataset_id: group.dataset_id,
				source_material_id: material.material_id,
				display_name: material.display_name,
				native_file: material.native_file,
				status: material.status,
				kind: material.kind,
				mitsuba_strategy: group.mitsuba_strategy,
				capabilities: group.capabilities,
				preview_source: material.preview_source,
				channels_dir: material.channels_dir ?? null,
			},
			render_binding: {
				kind,
				dataset_id: group.dataset_id,
				material_id: material.material_id,
				native_file: material.native_file,
				bsdf_strategy: bsdfStrategy,
				capabilities: group.capabilities ?? {},
				preview_source: material.preview_source,
				status: material.status,
			},
		},
	];
}

export function buildMaterialCards(
	materialGroups: any[],
	materialPresetIds: string[] = MATERIAL_PRESET_IDS,
): any[] {
	const presetCards = materialPresetIds.map((id) => {
		const category = materialCategoryFromText(id, id === 'fabric' ? 'furniture' : 'all');
		return {
			value: id,
			label: id.replace(/_/g, ' '),
			subtitle: 'OpticalNav preset',
			collection: 'preset',
			collectionLabel: 'Presets',
			category,
			tags: materialTagsFor(category, { dataset_id: 'preset' }, { material_id: id }),
			status: 'ready',
			kind: 'preset',
			preview: materialPreviewUrl(id),
			material: null,
			group: null,
		};
	});
	const libraryCards = materialGroups.flatMap((group: any) =>
		(group.materials ?? []).map((material: any) => {
			const label = material.display_name ?? material.material_id;
			const category = materialCategoryFromText(
				`${label} ${material.material_id} ${material.category ?? ''} ${group.dataset_id}`,
				material.category ?? 'all',
			);
			const value = materialValue(group, material);
			return {
				value,
				label,
				subtitle: group.display_name ?? group.dataset_id,
				collection: group.dataset_id,
				collectionLabel: group.display_name ?? group.dataset_id,
				category,
				tags: materialTagsFor(category, group, material),
				status: material.status ?? 'unknown',
				kind: material.kind ?? 'measured',
				preview: materialPreviewSource(value, materialGroups, materialPresetIds),
				material,
				group,
			};
		}),
	);
	return [...presetCards, ...libraryCards];
}

// ── Functions requiring picker state ─────────────────────────────────────────

export function materialMatchesSearch(
	value: string,
	label: string,
	extra: string,
	search: string,
): boolean {
	const q = search.trim().toLowerCase();
	if (!q) return true;
	return `${value} ${label} ${extra}`.toLowerCase().includes(q);
}

export function filterMaterialCards(
	cards: any[],
	item: any,
	opts: { search: string; collection: string; category: string },
): any[] {
	const q = opts.search.trim().toLowerCase();
	const recommended = recommendedMaterialCategory(item);
	return cards
		.filter((card) => {
			if (opts.collection !== 'all' && card.collection !== opts.collection) return false;
			if (opts.category === 'recommended') {
				if (recommended !== 'recommended' && card.category !== recommended && !card.tags.includes(recommended))
					return false;
			} else if (opts.category !== 'all' && card.category !== opts.category && !card.tags.includes(opts.category)) {
				return false;
			}
			if (!q) return true;
			return `${card.value} ${card.label} ${card.subtitle} ${card.tags.join(' ')}`
				.toLowerCase()
				.includes(q);
		})
		.slice(0, 80);
}

/** Generate a human-readable suggestion string for a selected material. */
export function materialSuggestion(item: any, materialGroups: any[]): string {
	const material = item?.material;
	if (material === 'clear_glass' || material === 'frosted_glass')
		return 'Glass material selected. Apply the glass hazard preset if this surface blocks the robot.';
	if (material === 'mirror')
		return 'Mirror material selected. Apply the mirror hazard preset to include it in hazard labels.';
	if (material === 'wood' || material === 'fabric' || material === 'tile')
		return 'Opaque material selected. Use landmark goal or normal obstacle labels as needed.';
	const found = findMaterialOption(material, materialGroups);
	if (found?.group?.dataset_id === 'hpbrdf_2025')
		return 'hpBRDF material selected. This is a measured hyperspectral/polarimetric material; verify local channel availability before final sensor rendering.';
	if (found?.group?.dataset_id === 'pbrdf_2020')
		return 'pBRDF material selected. This is a measured polarimetric material; use it for optical appearance, while navigation labels still come from the hazard flags below.';
	if (found)
		return 'Measured material selected from the material library. Navigation semantics still come from the object type and flags.';
	return '';
}

/** Parse JSON text safely, returning undefined if empty or invalid. */
export function optionalJson(text: string): unknown {
	const trimmed = text.trim();
	if (!trimmed) return undefined;
	try {
		return JSON.parse(trimmed);
	} catch {
		return undefined;
	}
}

/** Format a byte count as a human-readable size string (KB / MB). */
export function envmapSizeLabel(bytes: unknown): string {
	const n = Number(bytes ?? 0);
	if (!Number.isFinite(n) || n <= 0) return '';
	if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
	return `${Math.max(1, Math.round(n / 1024))} KB`;
}

/** Read a File as a base64-encoded data string (without the data URL prefix). */
export function fileToDataBase64(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onerror = () => reject(reader.error ?? new Error('File read failed'));
		reader.onload = () => {
			const result = String(reader.result ?? '');
			resolve(result.includes(',') ? result.split(',', 2)[1] : result);
		};
		reader.readAsDataURL(file);
	});
}
