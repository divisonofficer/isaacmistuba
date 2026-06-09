<script lang="ts">
	import { materialPreviewSource, materialDisplayLabel } from '$lib/datasets/materialHelpers';

	interface Props {
		item: any;
		itemKind: string;
		dirty: boolean;
		inspectorError: string;
		inspectorTab: string;
		materialGroups: any[];
		selectedMaterialInfo: any;
		selectedMaterialSuggestion: string;
		materialPickerSearch: string;
		materialPickerCollection: string;
		materialPickerCategory: string;
		filteredMaterialCards: any[];
		materialCollections: [string, string][];
		materialPreviewEntry: any;
		materialPreviewValue: string;
		materialLibraryStatus: string;
		detectedEmitterIds: Set<string>;
		hazardTypes: string[];
		surfaceSnapEnabled: boolean;
		gridSnapEnabled: boolean;
		transformGridSizeM: number;
		transformAngleSnapDeg: number;
		onUpdateField: (field: string, value: unknown) => void;
		onUpdateNavigation: (field: string, value: unknown) => void;
		onUpdatePointGeometry: (field: string, value: unknown) => void;
		onUpdateLineGeometry: (field: string, value: unknown) => void;
		onUpdateRectangleBound: (index: number, value: unknown) => void;
		onUpdateDimension: (field: string, value: unknown) => void;
		onApplyPreset: (preset: string) => void;
		onRotatePoint: (deg: number) => void;
		onChooseMaterial: (value: string) => void;
		onApplyMaterialWithTags: (value: string) => void;
		onDelete: () => void;
		onSetInspectorTab: (tab: string) => void;
		onSetMaterialPreviewValue: (value: string) => void;
		onSetMaterialPickerSearch: (v: string) => void;
		onSetMaterialPickerCollection: (v: string) => void;
		onSetMaterialPickerCategory: (v: string) => void;
		onSetSurfaceSnapEnabled: (v: boolean) => void;
		onSetGridSnapEnabled: (v: boolean) => void;
		onSetTransformGridSizeM: (v: number) => void;
		onSetTransformAngleSnapDeg: (v: number) => void;
	}

	let {
		item, itemKind, dirty, inspectorError, inspectorTab,
		materialGroups, selectedMaterialInfo, selectedMaterialSuggestion,
		materialPickerSearch, materialPickerCollection, materialPickerCategory,
		filteredMaterialCards, materialCollections, materialPreviewEntry,
		materialPreviewValue, materialLibraryStatus,
		detectedEmitterIds, hazardTypes,
		surfaceSnapEnabled, gridSnapEnabled, transformGridSizeM, transformAngleSnapDeg,
		onUpdateField, onUpdateNavigation, onUpdatePointGeometry,
		onUpdateLineGeometry, onUpdateRectangleBound, onUpdateDimension,
		onApplyPreset, onRotatePoint, onChooseMaterial, onApplyMaterialWithTags,
		onDelete, onSetInspectorTab, onSetMaterialPreviewValue,
		onSetMaterialPickerSearch, onSetMaterialPickerCollection, onSetMaterialPickerCategory,
		onSetSurfaceSnapEnabled, onSetGridSnapEnabled,
		onSetTransformGridSizeM, onSetTransformAngleSnapDeg,
	}: Props = $props();
</script>

<div class="map-float-inspector" class:material-panel={inspectorTab === 'material'}>
	<div class="inspector-head">
		<div>
			<div class="panel-label">Selected</div>
			<div class="inspector-id">{item.id}</div>
		</div>
		{#if dirty}<span class="dirty-pill">Unsaved</span>{/if}
	</div>
	<div class="inspector-badges">
		<span>{itemKind || 'item'}</span>
		<span>{item.type}</span>
	</div>
	<div class="inspector-tabs">
		<button class:active={inspectorTab === 'object'} onclick={() => onSetInspectorTab('object')}>Object</button>
		<button class:active={inspectorTab === 'material'} disabled={itemKind !== 'object'} onclick={() => onSetInspectorTab('material')}>Material</button>
	</div>

	{#if inspectorTab === 'object'}
		<label>
			<span>label</span>
			<input
				value={item.label ?? ''}
				oninput={(event) => onUpdateField('label', (event.currentTarget as HTMLInputElement).value)}
			/>
		</label>
		{#if itemKind === 'object'}
			<div class="material-summary-row">
				{#if materialPreviewSource(item.material, materialGroups)}
					<img src={materialPreviewSource(item.material, materialGroups)} alt="" loading="lazy" />
				{:else}
					<span class="material-empty-thumb">none</span>
				{/if}
				<div>
					<div class="material-mini-label">Material</div>
					<strong>{materialDisplayLabel(item.material, materialGroups)}</strong>
					<small>{selectedMaterialInfo?.kind ?? 'preset/custom'}</small>
				</div>
				<button class="button button-subtle" onclick={() => onSetInspectorTab('material')}>Change</button>
			</div>
			{#if item.source_ref}
				<div class="material-info">
					<strong>USD source</strong>
					<small>{item.source_ref}</small>
				</div>
			{/if}
		{/if}
		<div class="preset-row">
			<button class="button button-subtle" onclick={() => onApplyPreset('glass')}>Glass</button>
			<button class="button button-subtle" onclick={() => onApplyPreset('mirror')}>Mirror</button>
			<button class="button button-subtle" onclick={() => onApplyPreset('landmark')}>Landmark</button>
			<button class="button button-subtle" onclick={() => onApplyPreset('traversable')}>Walkable</button>
		</div>
		{#if item.geometry?.type === 'point'}
			<div class="rotation-row">
				<button title="Rotate left 45° (Q)" onclick={() => onRotatePoint(-45)}>↺ 45°</button>
				<div>
					<strong>{Math.round(item.geometry.yaw_deg ?? 0)}°</strong>
					<small>Q/E rotate · [/]</small>
				</div>
				<button title="Rotate right 45° (E)" onclick={() => onRotatePoint(45)}>45° ↻</button>
			</div>
			<div class="snap-controls">
				<label><input type="checkbox" checked={surfaceSnapEnabled} onchange={(e) => onSetSurfaceSnapEnabled((e.currentTarget as HTMLInputElement).checked)} /> Surface snap</label>
				<label><input type="checkbox" checked={gridSnapEnabled} onchange={(e) => onSetGridSnapEnabled((e.currentTarget as HTMLInputElement).checked)} /> Grid snap</label>
				<label><span>Grid</span><input type="number" min="0.005" step="0.005" value={transformGridSizeM} oninput={(e) => onSetTransformGridSizeM(Math.max(0.005, Number((e.currentTarget as HTMLInputElement).value) || 0.05))} /></label>
				<label><span>Angle</span><input type="number" min="1" step="1" value={transformAngleSnapDeg} oninput={(e) => onSetTransformAngleSnapDeg(Math.max(1, Number((e.currentTarget as HTMLInputElement).value) || 15))} /></label>
				<button class="button button-subtle" onclick={() => onUpdateDimension('base_height_m', 0)}>Reset height</button>
			</div>
		{/if}
		<details class="inspector-section geometry-advanced">
			<summary>Advanced geometry</summary>
			<p class="inline-hint">Use the scene handles for common edits. Numeric values are for precise adjustment.</p>
			{#if item.geometry?.type === 'point'}
				<div class="geometry-grid">
					<label><span>Position X</span><input type="number" min="0" max="6" step="0.01" value={item.geometry.center?.[0] ?? 0} oninput={(e) => onUpdatePointGeometry('x', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Position Y</span><input type="number" min="0" max="4" step="0.01" value={item.geometry.center?.[1] ?? 0} oninput={(e) => onUpdatePointGeometry('y', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Yaw</span><input type="number" step="1" value={item.geometry.yaw_deg ?? 0} oninput={(e) => onUpdatePointGeometry('yaw_deg', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Width</span><input type="number" min="0.01" step="0.01" value={item.geometry.size_m?.[0] ?? 0.5} oninput={(e) => onUpdateDimension('size_x', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Height</span><input type="number" min="0.01" step="0.01" value={item.geometry.size_m?.[1] ?? 1.2} oninput={(e) => onUpdateDimension('size_y', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Depth</span><input type="number" min="0.01" step="0.01" value={item.geometry.size_m?.[2] ?? 0.5} oninput={(e) => onUpdateDimension('size_z', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Base H</span><input type="number" step="0.01" value={item.geometry.base_height_m ?? 0} oninput={(e) => onUpdateDimension('base_height_m', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Pitch</span><input type="number" step="1" value={item.geometry.pitch_deg ?? 0} oninput={(e) => onUpdateDimension('pitch_deg', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Roll</span><input type="number" step="1" value={item.geometry.roll_deg ?? 0} oninput={(e) => onUpdateDimension('roll_deg', (e.currentTarget as HTMLInputElement).value)} /></label>
				</div>
			{:else if item.geometry?.type === 'line'}
				<div class="geometry-grid">
					<label><span>Start X</span><input type="number" min="0" max="6" step="0.01" value={item.geometry.start?.[0] ?? 0} oninput={(e) => onUpdateLineGeometry('start_x', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Start Y</span><input type="number" min="0" max="4" step="0.01" value={item.geometry.start?.[1] ?? 0} oninput={(e) => onUpdateLineGeometry('start_y', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>End X</span><input type="number" min="0" max="6" step="0.01" value={item.geometry.end?.[0] ?? 0} oninput={(e) => onUpdateLineGeometry('end_x', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>End Y</span><input type="number" min="0" max="4" step="0.01" value={item.geometry.end?.[1] ?? 0} oninput={(e) => onUpdateLineGeometry('end_y', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Height</span><input type="number" min="0.001" step="0.1" value={item.geometry.height_m ?? 2.4} oninput={(e) => onUpdateLineGeometry('height_m', (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>Thickness</span><input type="number" min="0.001" step="0.01" value={item.geometry.thickness_m ?? 0.08} oninput={(e) => onUpdateLineGeometry('thickness_m', (e.currentTarget as HTMLInputElement).value)} /></label>
				</div>
			{:else if item.geometry?.type === 'rectangle'}
				<div class="geometry-grid">
					<label><span>x0</span><input type="number" min="0" max="6" step="0.01" value={item.geometry.bounds?.[0] ?? 0} oninput={(e) => onUpdateRectangleBound(0, (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>y0</span><input type="number" min="0" max="4" step="0.01" value={item.geometry.bounds?.[1] ?? 0} oninput={(e) => onUpdateRectangleBound(1, (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>x1</span><input type="number" min="0" max="6" step="0.01" value={item.geometry.bounds?.[2] ?? 1} oninput={(e) => onUpdateRectangleBound(2, (e.currentTarget as HTMLInputElement).value)} /></label>
					<label><span>y1</span><input type="number" min="0" max="4" step="0.01" value={item.geometry.bounds?.[3] ?? 1} oninput={(e) => onUpdateRectangleBound(3, (e.currentTarget as HTMLInputElement).value)} /></label>
				</div>
			{/if}
			{#if inspectorError}<p class="inline-error">{inspectorError}</p>{/if}
		</details>
		{#if itemKind === 'region' && item.type === 'traversable'}
			<div class="inspector-section region-floor-material">
				<div class="panel-label">Floor material</div>
				<select
					value={item.floor_material_id ?? ''}
					onchange={(e) => onUpdateField('floor_material_id', (e.currentTarget as HTMLSelectElement).value || null)}
				>
					<option value="">— Use scene default —</option>
					<optgroup label="Presets">
						<option value="default_floor">default_floor</option>
						<option value="wood">wood</option>
						<option value="tile">tile</option>
						<option value="fabric">fabric</option>
					</optgroup>
					{#each materialGroups ?? [] as group}
						{#if (group.materials ?? []).length}
							<optgroup label={group.collection_label ?? group.dataset_id ?? 'Catalog'}>
								{#each group.materials as material}
									{@const v = (group.dataset_id && material.material_id) ? `${group.dataset_id}:${material.material_id}` : (material.material_id ?? '')}
									{#if v}
										<option value={v}>{material.display_name ?? material.material_id ?? v}</option>
									{/if}
								{/each}
							</optgroup>
						{/if}
					{/each}
				</select>
				<small class="floor-material-hint">Renders as a per-region floor slab when Auto floor is enabled.</small>
			</div>
		{/if}
		<div class="inspector-section">
			<div class="panel-label">Navigation</div>
			<div class="flag-grid">
				<label><input type="checkbox" checked={item.navigation?.blocks_navigation ?? false} onchange={(e) => onUpdateNavigation('blocks_navigation', (e.currentTarget as HTMLInputElement).checked)} /> Blocks robot</label>
				<label><input type="checkbox" checked={item.navigation?.include_in_hazard_mask ?? false} onchange={(e) => onUpdateNavigation('include_in_hazard_mask', (e.currentTarget as HTMLInputElement).checked)} /> Hazard mask</label>
				<label><input type="checkbox" checked={item.navigation?.instruction_candidate ?? false} onchange={(e) => onUpdateNavigation('instruction_candidate', (e.currentTarget as HTMLInputElement).checked)} /> Instruction</label>
				<label><input type="checkbox" checked={item.navigation?.goal_candidate ?? false} onchange={(e) => onUpdateNavigation('goal_candidate', (e.currentTarget as HTMLInputElement).checked)} /> Goal</label>
			</div>
			<label>
				<span>hazard_type</span>
				<select value={item.navigation?.hazard_type ?? ''} onchange={(e) => onUpdateNavigation('hazard_type', (e.currentTarget as HTMLSelectElement).value)}>
					{#each hazardTypes as ht}
						<option value={ht}>{ht || 'none'}</option>
					{/each}
				</select>
			</label>
		</div>
		<div class="inspector-section">
			<div class="panel-label">Light source</div>
			{#if detectedEmitterIds.has(item.id) && !item.is_emitter}
				<p class="emitter-hint">🔆 Detected light fixture — enable to render as an area emitter.</p>
			{/if}
			<label class="flag-grid"><input type="checkbox" checked={item.is_emitter ?? false} onchange={(e) => onUpdateField('is_emitter', (e.currentTarget as HTMLInputElement).checked)} /> Use as light source</label>
			{#if item.is_emitter}
				<label>
					<span>Intensity ({(item.emitter_intensity ?? 1.0).toFixed(2)}×)</span>
					<input type="range" min="0.1" max="20" step="0.1"
						value={item.emitter_intensity ?? 1.0}
						oninput={(e) => onUpdateField('emitter_intensity', parseFloat((e.currentTarget as HTMLInputElement).value))}
					/>
				</label>
			{/if}
		</div>
		<button class="button button-subtle full danger" onclick={onDelete}>Delete {item.id}</button>
	{:else}
		<div class="material-workspace">
			<div class="material-picker-top">
				<input class="material-search" placeholder="Search material name, tag, collection..." value={materialPickerSearch} oninput={(e) => onSetMaterialPickerSearch((e.currentTarget as HTMLInputElement).value)} />
				<select value={materialPickerCollection} onchange={(e) => onSetMaterialPickerCollection((e.currentTarget as HTMLSelectElement).value)}>
					<option value="all">All collections</option>
					<option value="preset">Presets</option>
					{#each materialCollections as [collectionId, collectionLabel]}
						<option value={collectionId}>{collectionLabel}</option>
					{/each}
				</select>
			</div>
			<div class="material-category-tabs">
				{#each ['recommended','glass','mirror','wall','floor','furniture','hazard','all'] as category}
					<button class:active={materialPickerCategory === category} onclick={() => onSetMaterialPickerCategory(category)}>{category}</button>
				{/each}
			</div>
			<div class="material-grid-browser">
				<div class="material-card-grid">
					<button class:selected={!item.material && !materialPreviewValue} onclick={() => onChooseMaterial('')}>
						<span class="material-empty-thumb">none</span>
						<strong>No material</strong>
						<small>clear override</small>
					</button>
					{#each filteredMaterialCards as card}
						<button class:selected={(materialPreviewValue || item.material) === card.value} onclick={() => onSetMaterialPreviewValue(card.value)}>
							{#if card.preview}<img src={card.preview} alt="" loading="lazy" />{:else}<span class="material-empty-thumb">none</span>{/if}
							<strong>{card.label}</strong>
							<small>{card.collectionLabel}</small>
							<div class="material-tag-row">
								{#each card.tags.slice(0, 3) as tag}<span>{tag}</span>{/each}
							</div>
						</button>
					{/each}
				</div>
				<div class="material-preview-panel">
					{#if materialPreviewEntry}
						{#if materialPreviewEntry.preview}<img class="material-large-preview" src={materialPreviewEntry.preview} alt="" loading="lazy" />{:else}<span class="material-large-empty">No preview</span>{/if}
						<h3>{materialPreviewEntry.label}</h3>
						<p>{materialPreviewEntry.collectionLabel} · {materialPreviewEntry.kind} · {materialPreviewEntry.status}</p>
						<div class="material-tag-row expanded">
							{#each materialPreviewEntry.tags as tag}<span>{tag}</span>{/each}
						</div>
						<div class="material-metadata">
							<div><span>Category</span><strong>{materialPreviewEntry.category}</strong></div>
							<div><span>RGB</span><strong>ready</strong></div>
							<div><span>Polarization</span><strong>{materialPreviewEntry.tags.includes('polarization-ready') ? 'ready' : 'proxy'}</strong></div>
							<div><span>NIR-like</span><strong>{materialPreviewEntry.tags.includes('NIR-ready') ? 'ready' : 'proxy'}</strong></div>
						</div>
						{#if selectedMaterialSuggestion}<p class="suggestion">{selectedMaterialSuggestion}</p>{/if}
						<div class="material-action-row">
							<button class="button button-subtle" onclick={() => onChooseMaterial(materialPreviewEntry.value)}>Apply Material</button>
							<button class="button button-primary" onclick={() => onApplyMaterialWithTags(materialPreviewEntry.value)}>Apply + Suggested Tags</button>
						</div>
					{:else}
						<div class="material-empty-state">No matching materials. {materialLibraryStatus}</div>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.inspector-head {
			display: flex;
			align-items: flex-start;
			justify-content: space-between;
			gap: var(--space-3);
		}

	.inspector-id {
			margin-top: 2px;
			color: var(--text);
			font-family: var(--font-mono);
			font-size: var(--font-size-xs);
			overflow-wrap: anywhere;
		}

	.dirty-pill {
			border: 1px solid #f4c26f;
			border-radius: 999px;
			background: #fff8e8;
			color: var(--tool-hazard);
			font-size: var(--font-size-xs);
			font-weight: 700;
			padding: 2px var(--space-2);
			white-space: nowrap;
		}

	.inspector-badges {
			display: flex;
			flex-wrap: wrap;
			gap: var(--space-1);
		}

	.inspector-badges span {
			border: 1px solid var(--panel-border);
			border-radius: 999px;
			background: var(--surface-2);
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
			padding: 2px var(--space-2);
		}

	.preset-row {
			display: flex;
			flex-wrap: wrap;
			gap: var(--space-2);
		}

	.preset-row .button {
			height: 30px;
			padding-inline: var(--space-2);
			font-size: var(--font-size-xs);
		}

	.rotation-row {
			display: grid;
			grid-template-columns: 1fr auto 1fr;
			align-items: center;
			gap: var(--space-2);
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: var(--surface-1);
			padding: var(--space-2);
		}

	.rotation-row button {
			min-height: 34px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: var(--panel);
			color: var(--text);
			font-weight: 800;
			cursor: pointer;
		}

	.rotation-row button:hover { background: var(--hover-bg); }

	.rotation-row div {
			display: grid;
			justify-items: center;
			gap: 1px;
			min-width: 54px;
		}

	.rotation-row strong {
			color: var(--brand);
			font-size: var(--font-size-md);
		}

	.rotation-row small {
			color: var(--text-muted);
			font-size: 10px;
			white-space: nowrap;
		}

	.snap-controls {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: var(--space-2);
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: var(--surface-1);
			padding: var(--space-2);
		}

	.snap-controls label {
			display: flex;
			align-items: center;
			gap: 6px;
			min-width: 0;
			font-size: var(--font-size-xs);
			font-weight: 800;
			color: var(--muted-strong);
		}

	.snap-controls label:has(input[type='number']) {
			display: grid;
			grid-template-columns: auto minmax(0, 1fr);
		}

	.snap-controls input[type='number'] {
			min-width: 0;
			height: 30px;
		}

	.snap-controls .button {
			grid-column: 1 / -1;
			min-height: 30px;
		}

	.inspector-section {
			display: grid;
			gap: var(--space-2);
			padding-top: var(--space-2);
			border-top: 1px solid var(--panel-border);
		}

	.flag-grid {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: var(--space-2);
		}

	.flag-grid label {
			display: flex;
			grid-template-columns: none;
			align-items: center;
			gap: 6px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			padding: var(--space-1) var(--space-2);
			background: var(--surface-2);
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
		}

	.flag-grid input {
			width: 14px;
			height: 14px;
			padding: 0;
		}

	.suggestion {
			margin: 0;
			border: 1px solid #bfdbfe;
			border-radius: var(--radius-sm);
			background: #eff6ff;
			color: #1e3a8a;
			padding: var(--space-2);
			font-size: var(--font-size-xs);
		}

	.material-info {
			display: grid;
			gap: 2px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: rgba(248, 250, 252, 0.92);
			padding: var(--space-2);
			font-size: var(--font-size-xs);
		}

	.material-info strong {
			color: var(--text);
			font-size: 12px;
		}

	.material-info span {
			color: var(--muted-strong);
		}

	.material-info small {
			overflow: hidden;
			color: var(--text-muted);
			text-overflow: ellipsis;
			white-space: nowrap;
		}

	.material-mini-label {
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
			font-weight: 700;
		}

	.material-summary-row {
			display: grid;
			grid-template-columns: 44px minmax(0, 1fr) auto;
			align-items: center;
			gap: 9px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: rgba(248,250,252,0.92);
			padding: 6px;
		}

	.material-summary-row img,
		.material-empty-thumb {
			width: 44px;
			height: 44px;
			border-radius: var(--radius-sm);
			object-fit: cover;
			background: #f1f5f9;
			border: 1px solid var(--panel-border);
		}

	.material-empty-thumb {
			display: grid;
			place-items: center;
			color: var(--text-muted);
			font-size: 10px;
			font-weight: 800;
			text-transform: uppercase;
		}

	.material-summary-row strong {
			color: var(--text);
			font-size: 12px;
			line-height: 1.15;
		}

	.material-summary-row small {
			color: var(--text-muted);
			font-size: 10px;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}

	.material-summary-row div {
			display: grid;
			gap: 2px;
			min-width: 0;
		}

	.inspector-tabs {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: 6px;
		}

	.inspector-tabs button,
		.material-category-tabs button {
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: var(--surface-1);
			color: var(--text-muted);
			padding: 6px;
			font-weight: 800;
			cursor: pointer;
		}

	.inspector-tabs button.active,
		.material-category-tabs button.active {
			border-color: var(--brand);
			background: #eff6ff;
			color: var(--brand);
		}

	.inspector-tabs button:disabled {
			cursor: not-allowed;
			opacity: 0.45;
		}

	.material-workspace {
			display: grid;
			gap: 8px;
			min-height: 0;
		}

	.material-picker-top {
			display: grid;
			grid-template-columns: minmax(0, 1fr) minmax(120px, 0.45fr);
			gap: 6px;
		}

	.material-search {
			width: 100%;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			padding: 7px 9px;
			background: #fff;
			color: var(--text);
		}

	.material-picker-top select {
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: #fff;
			color: var(--text);
			padding: 7px;
			min-width: 0;
		}

	.material-category-tabs {
			display: flex;
			gap: 5px;
			overflow-x: auto;
			padding-bottom: 2px;
		}

	.material-category-tabs button {
			white-space: nowrap;
			text-transform: capitalize;
			font-size: 11px;
			padding-inline: 8px;
		}

	.material-grid-browser {
			display: grid;
			grid-template-columns: minmax(0, 1.2fr) minmax(170px, 0.8fr);
			gap: 10px;
			min-height: 0;
		}

	.material-card-grid {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			align-content: start;
			gap: 8px;
			max-height: calc(100vh - 300px);
			overflow: auto;
			padding-right: 2px;
		}

	.material-card-grid button {
			display: grid;
			grid-template-rows: 74px auto auto auto;
			gap: 4px;
			min-width: 0;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: rgba(248,250,252,0.94);
			color: var(--text);
			padding: 7px;
			text-align: left;
			cursor: pointer;
		}

	.material-card-grid button:hover,
		.material-card-grid button.selected {
			border-color: var(--brand);
			background: #eff6ff;
		}

	.material-card-grid img,
		.material-card-grid .material-empty-thumb {
			width: 100%;
			height: 74px;
			object-fit: cover;
			border-radius: var(--radius-sm);
		}

	.material-card-grid strong {
			overflow: hidden;
			color: var(--text);
			font-size: 12px;
			line-height: 1.2;
			text-overflow: ellipsis;
			white-space: nowrap;
		}

	.material-card-grid small,
		.material-preview-panel p {
			overflow: hidden;
			color: var(--text-muted);
			font-size: 10px;
			text-overflow: ellipsis;
			white-space: nowrap;
			margin: 0;
		}

	.material-tag-row {
			display: flex;
			flex-wrap: wrap;
			gap: 3px;
			min-width: 0;
		}

	.material-tag-row span {
			border: 1px solid var(--panel-border);
			border-radius: 999px;
			background: #fff;
			color: var(--text-muted);
			font-size: 9px;
			line-height: 1;
			padding: 3px 5px;
		}

	.material-tag-row.expanded span {
			font-size: 10px;
		}

	.material-preview-panel {
			display: grid;
			align-content: start;
			gap: 8px;
			min-width: 0;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: rgba(248,250,252,0.92);
			padding: 8px;
		}

	.material-empty-state {
			display: grid;
			place-items: center;
			min-height: 160px;
			border: 1px dashed var(--panel-border);
			border-radius: 10px;
			color: var(--text-muted);
			font-size: var(--font-size-xs);
		}

	.material-large-preview,
		.material-large-empty {
			width: 100%;
			aspect-ratio: 1 / 1;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: #f1f5f9;
			object-fit: cover;
		}

	.material-large-empty {
			display: grid;
			place-items: center;
			color: var(--text-muted);
			font-size: var(--font-size-xs);
		}

	.material-preview-panel h3 {
			margin: 0;
			color: var(--text);
			font-size: 15px;
			line-height: 1.2;
		}

	.material-metadata {
			display: grid;
			grid-template-columns: 1fr 1fr;
			gap: 5px;
		}

	.material-metadata div {
			display: grid;
			gap: 1px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: #fff;
			padding: 6px;
		}

	.material-metadata span {
			color: var(--text-muted);
			font-size: 10px;
		}

	.material-metadata strong {
			color: var(--text);
			font-size: 11px;
		}

	.material-action-row {
			display: grid;
			grid-template-columns: 1fr 1fr;
			gap: 6px;
		}

	.dataset-rail .inspector-head {
			display: flex;
			justify-content: space-between;
			align-items: flex-start;
			gap: var(--space-2);
		}

	.dataset-rail .inspector-id {
			color: var(--text-muted);
			font-family: monospace;
			font-size: var(--font-size-xs);
			overflow-wrap: anywhere;
		}

	.dataset-rail .inspector-badges,
		.dataset-rail .preset-row {
			display: flex;
			gap: 4px;
			flex-wrap: wrap;
		}

	.dataset-rail .inspector-badges span {
			padding: 1px 6px;
			background: var(--hover-bg);
			border-radius: 99px;
			color: var(--text-muted);
			font-size: 10px;
		}

	.dataset-rail .inspector-section {
			border-top: 1px solid var(--panel-border);
			padding-top: var(--space-2);
		}

	.dataset-rail .geometry-advanced summary {
			cursor: pointer;
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
			font-weight: 800;
		}

	.dataset-rail .flag-grid {
			display: grid;
			grid-template-columns: 1fr 1fr;
			gap: 4px;
			font-size: var(--font-size-xs);
		}

	.dataset-rail .rotation-row { margin-top: 2px; }

	.dataset-rail .snap-controls { margin-top: 4px; gap: 4px; }

	.dataset-rail .material-grid-browser {
			grid-template-columns: minmax(0, 1fr);
			gap: 8px;
		}

	.dataset-rail .material-picker-top {
			grid-template-columns: minmax(0, 1fr);
		}

	.dataset-rail .material-category-tabs {
			flex-wrap: wrap;
			overflow-x: visible;
		}

	.dataset-rail .material-category-tabs button {
			flex: 1 0 auto;
			padding: 5px 7px;
			font-size: 10px;
		}

	.dataset-rail .material-preview-panel {
			order: -1;
			grid-template-columns: 116px minmax(0, 1fr);
			align-items: start;
		}

	.dataset-rail .material-large-preview,
		.dataset-rail .material-large-empty {
			grid-row: 1 / span 4;
			aspect-ratio: 1 / 1;
		}

	.dataset-rail .material-preview-panel h3 {
			font-size: 14px;
		}

	.dataset-rail .material-preview-panel p {
			white-space: normal;
		}

	.dataset-rail .material-metadata {
			grid-column: 1 / -1;
		}

	.dataset-rail .material-action-row {
			grid-column: 1 / -1;
		}

	.dataset-rail .material-card-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
			max-height: 520px;
		}

	.dataset-rail .material-card-grid button {
			grid-template-rows: 64px auto auto auto;
		}

	.dataset-rail .material-card-grid img,
		.dataset-rail .material-card-grid .material-empty-thumb {
			height: 64px;
		}

	/* Floating right inspector */
	.map-float-inspector {
			position: absolute;
			top: 54px;
			right: 10px;
			width: 260px;
			max-height: calc(100% - 80px);
			overflow-y: auto;
			background: rgba(255, 255, 255, 0.95);
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-md);
			padding: var(--space-3);
			backdrop-filter: blur(10px);
			z-index: 10;
			box-shadow: 0 2px 8px rgba(0,0,0,0.1);
			display: flex;
			flex-direction: column;
			gap: var(--space-2);
		}

	.map-float-inspector.material-panel {
			width: min(720px, calc(100% - 24px));
		}

	.map-float-inspector,
		.map-float-settings {
			display: none;
		}

	/* Inspector inside floating panel */
	.map-float-inspector .inspector-head { display: flex; justify-content: space-between; align-items: flex-start; }

	.map-float-inspector .inspector-id { font-size: var(--font-size-xs); color: var(--text-muted); font-family: monospace; }

	.map-float-inspector .inspector-badges { display: flex; gap: 4px; flex-wrap: wrap; }

	.map-float-inspector .inspector-badges span {
			padding: 1px 6px;
			background: var(--hover-bg);
			border-radius: 99px;
			font-size: 10px;
			color: var(--text-muted);
		}

	.map-float-inspector .inspector-section { border-top: 1px solid var(--panel-border); padding-top: var(--space-2); }

	.map-float-inspector .geometry-advanced summary {
			cursor: pointer;
			color: var(--muted-strong);
			font-size: var(--font-size-xs);
			font-weight: 800;
		}

	.map-float-inspector .flag-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; font-size: var(--font-size-xs); }

	.map-float-inspector .preset-row { display: flex; gap: 4px; flex-wrap: wrap; }

	.map-float-inspector .rotation-row { margin-top: 2px; }

	.map-float-inspector .snap-controls { margin-top: 4px; gap: 4px; }

	.map-float-inspector .geometry-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }

	.map-float-inspector button.full { width: 100%; }

	.map-float-inspector button.danger { color: var(--danger); border-color: #fca5a5; }

	.map-float-inspector button.danger:hover { background: var(--danger-soft); }
</style>
