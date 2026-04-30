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

// Source of the preview render — present on hpBRDF entries:
//   "channel_split" → daemon will use the per-wavelength .pbrdf mirror
//                     (~200 MB / channel, safe for shared GPUs).
//   "monolithic"    → only the legacy 13 GB .hpbrdf is available; this
//                     path OOMs on shared GPUs and is deprecated.
//   "missing"       → no source data on disk; download or mirror first.
export type PreviewSource = 'channel_split' | 'monolithic' | 'missing';

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
	// Channel-split mirror state — only set for hpBRDF entries.
	channels_dir?: string | null;
	preview_source?: PreviewSource;
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
