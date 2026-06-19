export type BuiltInAssetBounds = {
	size: [number, number, number];
	min?: [number, number, number];
	max?: [number, number, number];
};

export type BuiltInBuildAsset = {
	id: string;
	label: string;
	tool: string;
	category: string;
	bounds: BuiltInAssetBounds;
	hint: string;
};

export type BuiltInPrimitivePlaceAsset = {
	kind: 'primitive';
	id: string;
	label: string;
	tool: 'chair' | 'table' | 'plant' | 'camera';
	category: string;
	group: string;
	bounds: BuiltInAssetBounds;
};

export type BuiltInRichPlaceAsset = {
	kind: 'rich_asset';
	id: string;
	asset_id: string;
	label: string;
	category: string;
	group: string;
	placement: 'point';
	source_ref: string;
	source_path?: string;
	usd_ref?: string;
	source_format?: 'usd_prim' | 'glb';
	source_dataset: 'MooreLane' | 'DigitalTwinCatalog';
	material_hint?: string;
	bounds: BuiltInAssetBounds;
	default_scale?: number;
	default_rotation?: number;
	license_ref?: string;
	metadata_ref?: string;
	tags?: string[];
};

export type BuiltInPlaceAsset = BuiltInPrimitivePlaceAsset | BuiltInRichPlaceAsset;

export type BuiltInPlaceAssetGroup = {
	id: string;
	label: string;
	assets: BuiltInPlaceAsset[];
};

const MOORELANE_USD_REF = 'assets/moorelane/Intel_mooreLane_v1_2_0/Intel_mooreLane/USD/MooreLane_ASWF_0623.usda';

export const builtInBuildAssets: BuiltInBuildAsset[] = [
	{ id: 'wall', label: 'Wall', tool: 'wall', category: 'shell', bounds: { size: [1.2, 2.4, 0.15] }, hint: 'line placement' },
	{ id: 'glass_wall', label: 'Glass Wall', tool: 'glass_wall', category: 'glass', bounds: { size: [1.2, 1.4, 0.08] }, hint: 'line placement' },
	{ id: 'mirror_wall', label: 'Mirror Wall', tool: 'mirror_wall', category: 'mirror', bounds: { size: [1.2, 1.4, 0.08] }, hint: 'line placement' },
	{ id: 'traversable', label: 'Walkable Floor', tool: 'traversable', category: 'floor', bounds: { size: [1.2, 0.04, 1.0] }, hint: 'drag region' },
	{ id: 'goal', label: 'Goal Region', tool: 'goal', category: 'goal', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' },
	{ id: 'start', label: 'Start Region', tool: 'start', category: 'start', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' },
	{ id: 'hazard', label: 'Hazard Region', tool: 'hazard', category: 'hazard', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' },
	{ id: 'forbidden', label: 'Blocked Region', tool: 'forbidden', category: 'forbidden', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' },
	{ id: 'stop_before', label: 'Stop-before Region', tool: 'stop_before', category: 'goal', bounds: { size: [0.8, 0.04, 0.8] }, hint: 'drag region' }
];

const primitivePlaceAssets: BuiltInPrimitivePlaceAsset[] = [
	{ kind: 'primitive', id: 'chair', label: 'Chair', tool: 'chair', category: 'furniture', group: 'Debug Proxies', bounds: { size: [0.45, 0.8, 0.45] } },
	{ kind: 'primitive', id: 'table', label: 'Table', tool: 'table', category: 'furniture', group: 'Debug Proxies', bounds: { size: [0.9, 0.72, 0.55] } },
	{ kind: 'primitive', id: 'plant', label: 'Plant', tool: 'plant', category: 'plant', group: 'Debug Proxies', bounds: { size: [0.35, 0.9, 0.35] } },
	{ kind: 'primitive', id: 'camera', label: 'Camera', tool: 'camera', category: 'electronics', group: 'Debug Proxies', bounds: { size: [0.1, 0.15, 0.1] } }
];

function moorelaneAsset(
	assetId: string,
	label: string,
	sourcePath: string,
	category: string,
	group: string,
	size: [number, number, number],
	materialHint: string,
	tags: string[] = []
): BuiltInRichPlaceAsset {
	return {
		kind: 'rich_asset',
		id: `builtin_${assetId}`,
		asset_id: assetId,
		label,
		category,
		group,
		placement: 'point',
		usd_ref: MOORELANE_USD_REF,
		source_ref: `${MOORELANE_USD_REF}#${sourcePath}`,
		source_path: sourcePath,
		source_format: 'usd_prim',
		source_dataset: 'MooreLane',
		material_hint: materialHint,
		bounds: { size, min: [-size[0] / 2, 0, -size[2] / 2], max: [size[0] / 2, size[1], size[2] / 2] },
		tags: ['builtin', 'moorelane', ...tags]
	};
}

function dtcAsset(
	name: string,
	label: string,
	category: string,
	group: string,
	size: [number, number, number],
	materialHint: string,
	tags: string[] = []
): BuiltInRichPlaceAsset {
	const sourceRef = `vendor_datasets/dtc_objects/${name}/3d-asset.glb`;
	return {
		kind: 'rich_asset',
		id: `builtin_dtc_${name}`,
		asset_id: `builtin_dtc_${name}`,
		label,
		category,
		group,
		placement: 'point',
		source_ref: sourceRef,
		source_format: 'glb',
		source_dataset: 'DigitalTwinCatalog',
		material_hint: materialHint,
		bounds: { size, min: [-size[0] / 2, 0, -size[2] / 2], max: [size[0] / 2, size[1], size[2] / 2] },
		default_scale: 1,
		default_rotation: 0,
		metadata_ref: `vendor_datasets/dtc_objects/${name}/metadata.json`,
		license_ref: `vendor_datasets/dtc_objects/${name}/CC_BY-SA.txt`,
		tags: ['builtin', 'dtc', 'glb', ...tags]
	};
}

const moorelanePlaceAssets: BuiltInRichPlaceAsset[] = [
	moorelaneAsset('moorelane_living_main_couch', 'Main Couch', '/ROOT/Living/Props_sitting/MainCouch', 'furniture', 'Furniture', [2.4, 0.9, 1.0], 'fabric', ['couch', 'living']),
	moorelaneAsset('moorelane_living_accent_armchair', 'Accent Armchair', '/ROOT/Living/Props_sitting/AccentArmChair', 'furniture', 'Office Furniture', [0.9, 1.0, 0.9], 'fabric', ['chair', 'living', 'office_chair']),
	moorelaneAsset('moorelane_living_armchair_pair', 'Armchair Pair', '/ROOT/Living/Props_sitting/ArmChairsPair', 'furniture', 'Furniture', [1.8, 1.0, 0.9], 'fabric', ['chair', 'living']),
	moorelaneAsset('moorelane_living_coffee_table', 'Coffee Table With Props', '/ROOT/Living/Props_sitting/CoffeeTableGrp', 'furniture', 'Furniture', [1.3, 0.6, 0.75], 'wood', ['table', 'living']),
	moorelaneAsset('moorelane_living_left_side_table', 'Left Side Table', '/ROOT/Living/Props_sitting/leftSideTable', 'furniture', 'Furniture', [0.55, 0.6, 0.55], 'wood', ['table']),
	moorelaneAsset('moorelane_living_right_side_table', 'Right Side Table', '/ROOT/Living/Props_sitting/rightSideTable', 'furniture', 'Furniture', [0.55, 0.6, 0.55], 'wood', ['table']),
	moorelaneAsset('moorelane_dining_table_set', 'Conference Table Set', '/ROOT/DiningRoom/Table', 'furniture', 'Office Furniture', [3.0, 1.0, 1.6], 'wood', ['table', 'dining', 'conference']),
	moorelaneAsset('moorelane_dining_sideboard_left', 'Office Storage Sideboard', '/ROOT/DiningRoom/Sideboard_left', 'furniture', 'Office Furniture', [1.6, 0.9, 0.45], 'wood', ['sideboard', 'cabinet', 'storage']),
	moorelaneAsset('moorelane_dining_sideboard_right', 'Office Storage Sideboard B', '/ROOT/DiningRoom/Sideboard_right', 'furniture', 'Office Furniture', [1.6, 0.9, 0.45], 'wood', ['sideboard', 'cabinet', 'storage']),
	moorelaneAsset('moorelane_kitchen_bar_chairs', 'Bar Chair Set', '/ROOT/Kitchen/Props_kitchen/barChairs', 'furniture', 'Office Furniture', [1.2, 1.1, 0.6], 'wood', ['chair', 'kitchen', 'breakout']),
	moorelaneAsset('moorelane_entry_benches', 'Entry Bench Pair', '/ROOT/Kitchen/Props_entry/EntryBenches', 'furniture', 'Furniture', [1.7, 0.5, 0.45], 'wood', ['bench']),
	moorelaneAsset('moorelane_living_bookshelf_books', 'Bookshelf Books', '/ROOT/Living/Props_sitting/BookshelfBooks', 'object', 'Office Furniture', [1.2, 1.2, 0.35], 'wood', ['books', 'bookshelf', 'storage']),
	moorelaneAsset('moorelane_living_potted_palm', 'Potted Palm', '/ROOT/Living/Props_sitting/pottedPalm', 'plant', 'Decor', [0.9, 1.9, 0.9], 'plant', ['plant']),
	moorelaneAsset('moorelane_living_branch_pot', 'Branch Pot', '/ROOT/Living/Props_sitting/CoffeeTableBase1', 'plant', 'Decor', [0.55, 0.95, 0.55], 'plant', ['plant']),
	moorelaneAsset('moorelane_living_small_lamp', 'Small Living Lamp', '/ROOT/Living/Props_sitting/Lamps', 'electronics', 'Lighting', [0.35, 0.8, 0.35], 'pbrdf_2020:brass', ['lamp', 'light']),
	moorelaneAsset('moorelane_living_firewood_set', 'Firewood Set', '/ROOT/Living/Props_sitting/FireAccessories', 'object', 'Decor', [0.8, 0.6, 0.45], 'wood', ['fireplace']),
	moorelaneAsset('moorelane_living_rug', 'Living Room Rug', '/ROOT/Living/Props_sitting/CarpetMain', 'floor', 'Decor', [2.2, 0.04, 1.6], 'fabric', ['rug']),
	moorelaneAsset('moorelane_dining_centerpiece', 'Dining Centerpiece', '/ROOT/DiningRoom/Centerpiece', 'object', 'Decor', [0.9, 0.65, 0.6], 'glass', ['tabletop']),
	moorelaneAsset('moorelane_studio_camera', 'Studio Camera Prop', '/ROOT/Studio/Props_Cameras', 'electronics', 'Office Electronics', [0.45, 0.35, 0.35], 'pbrdf_2020:chrome', ['studio', 'electronics']),
	moorelaneAsset('moorelane_studio_books', 'Studio Book Stack', '/ROOT/Studio/Props_studio/studioBooks', 'object', 'Office Furniture', [0.5, 0.25, 0.35], 'wood', ['books', 'tabletop']),
	moorelaneAsset('moorelane_dining_chandelier', 'Ceiling Chandelier', '/ROOT/DiningRoom/Candlerlier', 'electronics', 'Lighting', [1.2, 0.8, 1.2], 'pbrdf_2020:brass', ['light', 'chandelier', 'ceiling']),
	moorelaneAsset('moorelane_glass_door', 'Glass Door Panel', '/ROOT/glass/Glazing_glassALL/GLASS/geo/glass_door', 'glass', 'Reflective Surfaces', [1.0, 2.3, 0.05], 'clear_glass', ['glass', 'door', 'transparent', 'hazard']),
	moorelaneAsset('moorelane_glass_front_left', 'Office Glass Partition', '/ROOT/glass/Glazing_glassALL/GLASS/geo/glass_frontL', 'glass', 'Reflective Surfaces', [1.4, 2.5, 0.05], 'clear_glass', ['glass', 'window', 'partition', 'transparent']),
	moorelaneAsset('moorelane_glass_studio_door', 'Studio Glass Door', '/ROOT/glass/Glazing_glassALL/GLASS/geo/glass_studioDoor', 'glass', 'Reflective Surfaces', [1.0, 2.3, 0.05], 'clear_glass', ['glass', 'studio', 'door', 'transparent'])
];

const dtcPlaceAssets: BuiltInRichPlaceAsset[] = [
	dtcAsset('TeaPot_B06Y4KYFHT_White', 'White Teapot', 'kitchenware', 'Kitchen Props', [0.28, 0.22, 0.22], 'ceramic', ['teapot']),
	dtcAsset('Dutch_Oven_B0B125TQG2_White', 'White Dutch Oven', 'kitchenware', 'Kitchen Props', [0.36, 0.24, 0.32], 'ceramic', ['pot']),
	dtcAsset('Bowl_B0BQL5YBF2_Green_TU', 'Green Bowl', 'kitchenware', 'Kitchen Props', [0.22, 0.11, 0.22], 'ceramic', ['bowl']),
	dtcAsset('Dish_B07ZK7JG6D_Blue', 'Blue Dish', 'kitchenware', 'Kitchen Props', [0.28, 0.05, 0.28], 'ceramic', ['dish']),
	dtcAsset('Cup_B0CYL5PSR3_Orange', 'Orange Cup', 'kitchenware', 'Kitchen Props', [0.1, 0.13, 0.1], 'ceramic', ['cup']),
	dtcAsset('Kitchen_Spoon_D146567C_Green_1', 'Green Kitchen Spoon', 'kitchenware', 'Kitchen Props', [0.28, 0.04, 0.07], 'plastic', ['spoon']),
	dtcAsset('Knife_B0CHSG2M7H_Green', 'Green Knife', 'kitchenware', 'Kitchen Props', [0.3, 0.04, 0.05], 'plastic', ['knife']),
	dtcAsset('FakeFruit_B09992T572_Mangosteen', 'Tabletop Fruit Prop', 'object', 'Kitchen Props', [0.1, 0.09, 0.1], 'organic', ['fruit', 'tabletop']),
	dtcAsset('Bottle_Toy_SqueezeFancyTomatoKetchup_C1F9906C', 'Squeeze Bottle Prop', 'object', 'Kitchen Props', [0.08, 0.22, 0.08], 'plastic', ['bottle']),
	dtcAsset('Can_Toy_B0912QLQKC_CreamSoda', 'Toy Can Prop', 'object', 'Kitchen Props', [0.07, 0.12, 0.07], 'metal', ['can']),
	dtcAsset('Marker_B08X27CJBT_Orange_TU', 'Orange Marker', 'office', 'Office Electronics', [0.16, 0.03, 0.03], 'pbrdf_2020:peek', ['marker', 'office']),
	dtcAsset('Hammer_B0058EDQ5Y_SwissHammer', 'Hammer', 'tool', 'Tools and Office', [0.32, 0.12, 0.05], 'metal', ['tool']),
	dtcAsset('Dumbbell_B0045HLAMQ_Blue', 'Blue Dumbbell', 'object', 'Tools and Office', [0.26, 0.12, 0.12], 'metal', ['weight']),
	dtcAsset('Key_B00XZ9O69E_Transponder', 'Key Prop', 'object', 'Tools and Office', [0.08, 0.02, 0.04], 'metal', ['key']),
	dtcAsset('AirDuster', 'Air Duster', 'object', 'Safety', [0.08, 0.24, 0.08], 'pbrdf_2020:chrome', ['canister', 'office', 'placeholder_fire_extinguisher']),
	dtcAsset('Shampoo_B0CKQ5VJP8_Black', 'Black Bottle', 'object', 'Decor', [0.08, 0.22, 0.08], 'plastic', ['bottle']),
	dtcAsset('Vase_B0BQYN236S_TallBlue_1', 'Tall Blue Vase', 'object', 'Decor', [0.18, 0.45, 0.18], 'ceramic', ['vase']),
	dtcAsset('Pottery_B081N2QL49_Red', 'Red Pottery', 'object', 'Decor', [0.22, 0.26, 0.22], 'ceramic', ['pottery']),
	dtcAsset('Candle_B00GCILD64_Blue', 'Blue Candle', 'object', 'Decor', [0.09, 0.12, 0.09], 'wax', ['candle']),
	dtcAsset('Speaker_B08H82ZRS2_Black_1', 'Black Speaker', 'electronics', 'Office Electronics', [0.22, 0.16, 0.12], 'pbrdf_2020:black_billiard', ['speaker', 'electronics'])
];

export const builtInRichPlaceAssets: BuiltInRichPlaceAsset[] = [...moorelanePlaceAssets, ...dtcPlaceAssets];

const groupOrder = ['Debug Proxies'];
export const builtInPlaceAssets: BuiltInPlaceAsset[] = [...primitivePlaceAssets];

export const builtInPlaceAssetGroups: BuiltInPlaceAssetGroup[] = groupOrder
	.map((label) => ({
		id: label.toLowerCase().replace(/[^a-z0-9]+/g, '_'),
		label,
		assets: builtInPlaceAssets.filter((asset) => asset.group === label)
	}))
	.filter((group) => group.assets.length > 0);
