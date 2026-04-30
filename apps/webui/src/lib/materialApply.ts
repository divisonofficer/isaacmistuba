import { applyMaterialOverridesBatch, type MaterialOverrideEntry } from '$lib/api';

export type ApplyMaterialKind =
	| { kind: 'curated'; material_id: string }
	| { kind: 'measured'; dataset_id: string; material_id: string; measured_file_path: string; mitsuba_strategy: string }
	| { kind: 'preset'; bsdf_type: string };

export type ApplyResult = {
	applied: number;
	skipped: { prim_path: string | null; reason: string }[];
	raw: unknown;
};

function entriesFor(material: ApplyMaterialKind, primPaths: string[]): MaterialOverrideEntry[] {
	return primPaths.map((prim_path) => {
		switch (material.kind) {
			case 'curated':
				return { prim_path, bsdf_type: 'curated', material_id: material.material_id };
			case 'measured':
				return {
					prim_path,
					bsdf_type: material.mitsuba_strategy,
					dataset_id: material.dataset_id,
					material_id: material.material_id,
					measured_file_path: material.measured_file_path
				};
			case 'preset':
				return { prim_path, bsdf_type: material.bsdf_type };
		}
	});
}

export async function applyMaterialToPrims(
	sceneId: string,
	primPaths: string[],
	material: ApplyMaterialKind
): Promise<ApplyResult> {
	const cleaned = primPaths.filter((p) => !!p);
	if (!cleaned.length) {
		return { applied: 0, skipped: [], raw: null };
	}
	const overrides = entriesFor(material, cleaned);
	const raw = (await applyMaterialOverridesBatch(sceneId, { overrides })) as Record<string, unknown>;
	const applied = Array.isArray(raw?.applied) ? (raw.applied as unknown[]).length : 0;
	const skipped = (Array.isArray(raw?.skipped) ? raw.skipped : []) as ApplyResult['skipped'];
	return { applied, skipped, raw };
}
