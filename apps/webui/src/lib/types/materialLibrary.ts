export type CategoryKey =
	| 'metal'
	| 'plastic'
	| 'dielectric'
	| 'principled'
	| 'fluid'
	| 'fabric'
	| 'other';

export type DownloadStatus = 'available' | 'needs_patch' | 'not_downloaded';

export type PreviewStatus = 'baked' | 'cached' | 'missing' | 'failed' | 'stale';

export type PreviewMeta = {
	material_id: string;
	display_name?: string;
	category?: CategoryKey;
	rendered_at: string;
	preview_preset: string;
	resolution: [number, number];
	spp: number;
	mitsuba_variant: string;
	mitsuba_version: string;
	source_version: string;
	rig_hash: string;
};

export type LibrarySummary = {
	total: number;
	downloaded: number;
	preview_ok: number;
	preview_failed: number;
	errors: number;
};

export type MatEntry = {
	material_id: string;
	display_name: string;
	native_file: string;
	status: DownloadStatus;
	download_url: string | null;
	kind?: 'curated' | 'measured';
	category?: CategoryKey;
	description?: string;
	preview_baked?: boolean;
	preview_status: PreviewStatus;
	preview_mtime: string | null;
	preview_meta: PreviewMeta | null;
	download_size_bytes: number | null;
};

export type DatasetGroup = {
	dataset_id: string;
	display_name: string;
	paper_title?: string;
	venue?: string;
	source_url?: string;
	swatch_hue?: number;
	mitsuba_strategy?: string;
	patch_required?: boolean;
	capabilities?: { polarization: boolean; nir: boolean; spectral_range_nm: [number, number] };
	materials: MatEntry[];
	summary: LibrarySummary;
};

export type LibraryResponse = {
	groups: DatasetGroup[];
	summary: LibrarySummary;
};
