<script lang="ts">
	import type { Capabilities } from '$lib/datasets/capabilityHelpers';
	interface Props {
		caps: Capabilities;
		hasMap: boolean;
		hasGraph: boolean;
		hasScene: boolean;
		selectedProjectId: string;
		sceneId: string;
		loading: boolean;
		buildingMap: boolean;
		buildingGraph: boolean;
		graphBuildProgress: any;
		graphResult: any;
		mapResult: any;
		graphPayloadSummary: any;
		graphPayload: any;
		graphNodes: any[];
		graphEdges: any[];
		pathsMode: string;
		paintRadiusM: number;
		pendingEdgeSource: string;
		edgeInspectorSource: string;
		pendingRegionBbox: any;
		walkabilityOverlayMeta: any;
		traversableMeta: any;
		showTraversableMask: boolean;
		showFootprint: boolean;
		edgeCheckResult: any;
		filteredEpisodes: any[];
		episodes: any[];
		episodeSearch: string;
		episodeCount: number;
		selectedEpisodeId: string;
		splitCounts: any;
		robotRadius: number;
		minClearance: number;
		resolution: number;
		maxNodes: number;
		headingCount: number;
		minNodeSpacing: number;
		selectedSensorNode: any;
		onBuildMap: () => void;
		onRequestBuildGraph: () => void;
		onRebuildEdges?: () => void;
		rebuildingEdges?: boolean;
		onSetPathsMode: (mode: string) => void;
		onSetPaintRadius: (r: number) => void;
		onRebuildRegion: () => void;
		onClearRegion: () => void;
		onClearWalkabilityOverlay: () => void;
		onRefreshTraversableMeta: () => void;
		onSetShowFootprint: (v: boolean) => void;
		onSetShowTraversableMask: (v: boolean) => void;
		onAddEdgeAnyway: () => void;
		onDismissEdgeCheck: () => void;
		onDeleteGraphEdge: (edgeId: string) => void;
		onDeleteGraphNode: () => void;
		onLoadEpisode: (id: string) => void;
		onGenerateEpisodes: () => void;
		onClearEpisodes: () => void;
		onValidateEpisodes?: () => void;
		onPruneStaleEpisodes?: () => void;
		staleEpisodeReport?: any;
		validatingEpisodes?: boolean;
		onSetEpisodeSearch: (v: string) => void;
		onSetEpisodeCount: (n: number) => void;
		onSetRobotRadius: (v: number) => void;
		onSetMinClearance: (v: number) => void;
		onSetResolution: (v: number) => void;
		onSetMaxNodes: (n: number) => void;
		onSetHeadingCount: (n: number) => void;
		onSetMinNodeSpacing: (v: number) => void;
		// Render the selected episode's path nodes directly from this tab so
		// the user doesn't have to round-trip through Sensors to start a sweep.
		onRenderEpisodeNodes?: () => void;
		renderMissingOnly?: boolean;
		onSetRenderMissingOnly?: (value: boolean) => void;
		selectedRigSensorCount?: number;
		episodeNodesAvailable?: boolean;
		episodePathNodeCount?: number;
		headingsPerNode?: number;
		renderSceneSynced?: boolean;
		// Multi-select node removal (object-overlap cleanup).
		removeSelectionCount?: number;
		removeMarginM?: number;
		removePassHeightM?: number;
		findingOverlapping?: boolean;
		removingNodes?: boolean;
		onFindOverlapping?: () => void;
		onRemoveSelectedNodes?: () => void;
		onClearRemoveSelection?: () => void;
		onSetRemoveMargin?: (v: number) => void;
		onSetRemovePassHeight?: (v: number) => void;
	}

	const COMPONENT_COLORS = ['#6366f1','#ef4444','#fbbf24','#a855f7','#14b8a6','#ec4899','#84cc16'];

	let {
		caps,
		hasMap, hasGraph, hasScene, selectedProjectId, sceneId, loading,
		buildingMap, buildingGraph, graphBuildProgress, graphResult, mapResult,
		graphPayloadSummary, graphPayload, graphNodes, graphEdges,
		pathsMode, paintRadiusM, pendingEdgeSource, edgeInspectorSource,
		pendingRegionBbox, walkabilityOverlayMeta, traversableMeta,
		showTraversableMask, showFootprint, edgeCheckResult,
		filteredEpisodes, episodes, episodeSearch, episodeCount,
		selectedEpisodeId, splitCounts, robotRadius, minClearance, resolution,
		maxNodes, headingCount, minNodeSpacing, selectedSensorNode,
		onBuildMap, onRequestBuildGraph, onRebuildEdges, rebuildingEdges = false, onSetPathsMode, onSetPaintRadius,
		onRebuildRegion, onClearRegion, onClearWalkabilityOverlay, onRefreshTraversableMeta,
		onSetShowFootprint, onSetShowTraversableMask, onAddEdgeAnyway, onDismissEdgeCheck,
		onDeleteGraphEdge, onDeleteGraphNode, onLoadEpisode, onGenerateEpisodes,
		onClearEpisodes, onValidateEpisodes, onPruneStaleEpisodes,
		staleEpisodeReport = null, validatingEpisodes = false,
		onSetEpisodeSearch, onSetEpisodeCount,
		onSetRobotRadius, onSetMinClearance, onSetResolution,
		onSetMaxNodes, onSetHeadingCount, onSetMinNodeSpacing,
		onRenderEpisodeNodes,
		renderMissingOnly = true, onSetRenderMissingOnly,
		selectedRigSensorCount = 1,
		episodeNodesAvailable = false, episodePathNodeCount = 0, headingsPerNode = 0,
		renderSceneSynced = false,
		removeSelectionCount = 0, removeMarginM = 0, removePassHeightM = 1.2, findingOverlapping = false, removingNodes = false,
		onFindOverlapping, onRemoveSelectedNodes, onClearRemoveSelection, onSetRemoveMargin, onSetRemovePassHeight,
	}: Props = $props();
</script>

<!-- Detailed footprint / interaction / edge diagnostics panel -->
<section class="rail-section rail-tool-panel footprint-panel">
	<div class="rail-title">Robot footprint</div>
	<div class="footprint-grid">
		<label><span>Robot radius (m)</span><input type="number" min="0" max="2" step="0.05" value={robotRadius} oninput={(e) => onSetRobotRadius(Number((e.currentTarget as HTMLInputElement).value))} /></label>
		<label><span>Min clearance (m)</span><input type="number" min="0" max="2" step="0.05" value={minClearance} oninput={(e) => onSetMinClearance(Number((e.currentTarget as HTMLInputElement).value))} /></label>
	</div>
	<div class="footprint-info">Total inflated: <strong>{(Number(robotRadius) + Number(minClearance)).toFixed(2)} m</strong></div>
	<label class="footprint-toggle"><input type="checkbox" checked={showFootprint} onchange={(e) => onSetShowFootprint((e.currentTarget as HTMLInputElement).checked)} /> Show inflation overlay (3D view)</label>
	<div class="rail-title mt-2">Traversable grid</div>
	<label><span>Resolution (m)</span><input type="number" step="0.01" min="0.01" value={resolution} oninput={(e) => onSetResolution(Number((e.currentTarget as HTMLInputElement).value))} /></label>
	<button class="button button-subtle" disabled={!caps.buildMap.enabled} title={caps.buildMap.reason} onclick={onBuildMap}>
		{#if buildingMap}<span class="spinner-xs"></span> Building...{:else}{hasMap ? 'Rebuild grid' : 'Build grid'}{/if}
	</button>
	<div class="rail-title mt-2">Viewpoint graph</div>
	<button class="button button-subtle" disabled={!caps.buildGraph.enabled} title={caps.buildGraph.reason} onclick={onRequestBuildGraph}>
		{buildingGraph ? 'Rebuilding…' : 'Rebuild graph'}
	</button>
	<button class="button button-subtle" disabled={!caps.rebuildEdges.enabled} onclick={() => onRebuildEdges?.()} title={caps.rebuildEdges.reason || "Re-run edge building over the current node set (keeps all auto + manual nodes; reconnects manual nodes and drops edges that cross glass/furniture)."}>
		{rebuildingEdges ? 'Rebuilding edges…' : 'Rebuild edges (keep nodes)'}
	</button>
	{#if selectedSensorNode && !(selectedSensorNode as any).isCustom}
		<button class="button button-subtle danger" onclick={onDeleteGraphNode}>
			Delete {selectedSensorNode.node_id}
		</button>
	{/if}
</section>

<section class="rail-section rail-tool-panel footprint-panel">
	<div class="rail-title">Map interaction</div>
	<div class="mode-radio-group">
		{#each [
			{ value: 'select', label: '🖱 Select', title: 'Default. Click nodes or objects to select; orbit/zoom the 3D view.' },
			{ value: 'place_node', label: '📍 Place node', title: 'Click anywhere on the floor to insert a new viewpoint node at that (x, z). Node gets default headings.' },
			{ value: 'paint_walkable', label: 'Paint walkable', title: 'Drag on the floor to mark cells as walkable (force traversable). Survives map rebuilds.', swatch: 'walkable' },
			{ value: 'paint_blocked', label: 'Paint blocked', title: 'Drag on the floor to mark cells as blocked (force non-traversable). Useful for closing off areas the planner should not use.', swatch: 'blocked' },
			{ value: 'paint_erase', label: '🧽 Erase paint', title: 'Drag to clear walkability paint marks in that area (restore the auto-computed mask).' },
			{ value: 'select_region', label: '▭ Select region', title: 'Drag a rectangle on the floor to select an area, then click "Rebuild this region" to re-sample only that area viewpoints.' },
			{ value: 'add_edge', label: '⤴ Add edge', title: 'Click two graph nodes in sequence to create a manual edge between them (shown in purple).' },
			{ value: 'remove_edge', label: '✂ Remove edge', title: 'Click the two endpoints of an existing edge to delete it (works for auto + manual edges). Ghost line shows red.' },
			{ value: 'inspect_edge', label: '🔍 Inspect edge', title: 'Click two graph nodes to diagnose why no edge exists between them (distance, blocking cells, hazard).' },
			{ value: 'remove_node', label: '🗑 Remove nodes', title: 'Box-drag and/or click graph nodes to mark them for removal (e.g. vertices sitting on furniture). Use "Find overlapping" to auto-select, then Remove.' },
		] as item}
			<label class="mode-radio" title={item.title}>
				<input type="radio" name="pathsMode" value={item.value} checked={pathsMode === item.value} onchange={() => onSetPathsMode(item.value)} />
				<span>{#if item.swatch}<span class="paint-swatch {item.swatch}"></span>{/if}{item.label}</span>
			</label>
		{/each}
	</div>
	{#if pathsMode !== 'select'}
		<div class="mode-active-banner">
			{#if pathsMode === 'place_node'}Click on the floor to place a node…
			{:else if pathsMode.startsWith('paint_')}Drag on the floor (brush radius {paintRadiusM} m)…
			{:else if pathsMode === 'select_region'}Drag a rectangle on the floor…
			{:else if pathsMode === 'add_edge'}{pendingEdgeSource ? `Source: ${pendingEdgeSource} · click target…` : 'Click first node…'}
			{:else if pathsMode === 'remove_edge'}{pendingEdgeSource ? `Endpoint: ${pendingEdgeSource} · click the other endpoint to delete…` : 'Click first endpoint of the edge to remove…'}
			{:else if pathsMode === 'inspect_edge'}{edgeInspectorSource ? `Source: ${edgeInspectorSource} · click target to diagnose…` : 'Click first node…'}
			{:else if pathsMode === 'remove_node'}{removeSelectionCount ? `${removeSelectionCount} node(s) marked · box-drag or click to add/remove` : 'Box-drag a rectangle or click nodes to mark for removal…'}
			{/if}
		</div>
	{/if}
	{#if pathsMode === 'remove_node'}
		<div class="remove-node-panel">
			<label class="footprint-toggle">
				<span>Overlap margin (m)</span>
				<input type="number" min="0" max="2" step="0.05" value={removeMarginM} oninput={(e) => onSetRemoveMargin?.(Number((e.currentTarget as HTMLInputElement).value))} class="paint-radius" />
			</label>
			<label class="footprint-toggle" title="Objects mounted at/above this height (e.g. ceiling lights) are ignored — the robot passes under them.">
				<span>Pass-under height (m)</span>
				<input type="number" min="0" max="3" step="0.1" value={removePassHeightM} oninput={(e) => onSetRemovePassHeight?.(Number((e.currentTarget as HTMLInputElement).value))} class="paint-radius" />
			</label>
			<button class="button button-subtle" disabled={!caps.findOverlapping.enabled} title={caps.findOverlapping.reason} onclick={() => onFindOverlapping?.()}>
				{findingOverlapping ? 'Finding…' : '⊙ Find overlapping nodes'}
			</button>
			<div class="footprint-info">Marked for removal: <strong>{removeSelectionCount}</strong></div>
			<button class="button button-subtle danger" disabled={!caps.removeNodes.enabled} title={caps.removeNodes.reason} onclick={() => onRemoveSelectedNodes?.()}>
				{removingNodes ? 'Removing…' : `Remove ${removeSelectionCount} node(s)`}
			</button>
			<button class="button button-subtle" disabled={!removeSelectionCount} onclick={() => onClearRemoveSelection?.()}>Clear selection</button>
		</div>
	{/if}
	{#if pathsMode.startsWith('paint_')}
		<label class="footprint-toggle">
			<span>Brush radius (m)</span>
			<input type="number" min="0.05" max="2" step="0.05" value={paintRadiusM} oninput={(e) => onSetPaintRadius(Number((e.currentTarget as HTMLInputElement).value))} class="paint-radius" />
		</label>
	{/if}
	{#if walkabilityOverlayMeta?.stats?.walkable_cells || walkabilityOverlayMeta?.stats?.blocked_cells}
		<div class="paint-info">
			<span class="chip-ok">walkable paint: {walkabilityOverlayMeta.stats.walkable_cells ?? 0}</span>
			<span class="chip-warn">blocked paint: {walkabilityOverlayMeta.stats.blocked_cells ?? 0}</span>
			<button class="button button-subtle danger" onclick={onClearWalkabilityOverlay}>Clear</button>
		</div>
	{/if}
	{#if pendingRegionBbox}
		<div class="paint-info">Region: [{pendingRegionBbox[0].toFixed(1)}, {pendingRegionBbox[1].toFixed(1)} → {pendingRegionBbox[2].toFixed(1)}, {pendingRegionBbox[3].toFixed(1)}]</div>
		<button class="button button-subtle" onclick={onRebuildRegion}>Rebuild this region</button>
		<button class="button button-subtle" onclick={onClearRegion}>Cancel selection</button>
	{/if}
</section>

<section class="rail-section rail-tool-panel footprint-panel">
	<div class="rail-title">Display layers</div>
	<label class="footprint-toggle" title="Show a translucent red ring inset from the floor by (robot_radius + min_clearance), approximating where the robot can't go.">
		<input type="checkbox" checked={showFootprint} onchange={(e) => onSetShowFootprint((e.currentTarget as HTMLInputElement).checked)} />
		<span>Footprint inflation outline</span>
	</label>
	<label class="footprint-toggle" title="Overlay the inflated traversable grid on the floor: red = real obstacles, orange = robot-radius halo.">
		<input type="checkbox" checked={showTraversableMask} onchange={(e) => { onSetShowTraversableMask((e.currentTarget as HTMLInputElement).checked); onRefreshTraversableMeta(); }} />
		<span>Inflated obstacles mask</span>
	</label>
	{#if showTraversableMask && traversableMeta?.stats}
		<div class="paint-info">
			<span class="chip-warn">obstacles: {traversableMeta.stats.raw_obstacle_cells ?? 0}</span>
			<span class="inflation-halo-chip">inflation halo: {traversableMeta.stats.inflation_only_cells ?? 0}</span>
		</div>
	{/if}
</section>

<section class="rail-section rail-tool-panel footprint-panel">
	<div class="rail-title">Edge diagnostics</div>
	{#if edgeCheckResult}
		<div class="edge-diag">
			<div class="edge-diag-title">{edgeCheckResult.source} ↔ {edgeCheckResult.target}</div>
			<div>Distance: <strong>{edgeCheckResult.distance_m?.toFixed(2)} m</strong> {edgeCheckResult.within_max_edge_length ? '✓' : `✗ (max ${edgeCheckResult.max_edge_length_m} m)`}</div>
			<div>Line check: {edgeCheckResult.blocked_cell_count > 0 ? `⚠ ${edgeCheckResult.blocked_cell_count} cells blocked` : '✓ clear'}</div>
			{#if edgeCheckResult.first_blocked_cell}
				<div class="edge-diag-detail">
					First blocked at world ({edgeCheckResult.first_blocked_cell.world?.[0]?.toFixed(2)}, {edgeCheckResult.first_blocked_cell.world?.[1]?.toFixed(2)})
					· {edgeCheckResult.first_blocked_cell.reason === 'raw_obstacle' ? 'real obstacle' : edgeCheckResult.first_blocked_cell.reason === 'inflation_halo' ? 'robot-radius halo' : edgeCheckResult.first_blocked_cell.reason}
				</div>
			{/if}
			<div>Hazard crossing: {edgeCheckResult.hazard_crossing ? '⚠ yes' : 'no'}</div>
			<div class="edge-diag-verdict" class:ok={edgeCheckResult.would_connect}>
				{edgeCheckResult.would_connect ? '✓ Would connect on next graph build' : `✗ ${edgeCheckResult.reason}`}
			</div>
			<div class="edge-diag-actions">
				<button class="button button-subtle" onclick={onAddEdgeAnyway}>Add edge anyway</button>
				<button class="button button-subtle" onclick={onDismissEdgeCheck}>Dismiss</button>
			</div>
		</div>
	{/if}
	{#if graphPayload?.component_summary && graphPayload.component_summary.length > 0}
		<div class="footprint-divider"></div>
		<div class="panel-label">Connectivity</div>
		<div class="paint-info">
			{graphPayload.component_summary.length} component{graphPayload.component_summary.length === 1 ? '' : 's'} · {graphNodes.length} nodes total
		</div>
		{#each graphPayload.component_summary.slice(0, 5) as comp}
			<div class="component-row">
				<span class="component-dot" style:background={COMPONENT_COLORS[comp.index % COMPONENT_COLORS.length]}></span>
				<span>{comp.size} node{comp.size === 1 ? '' : 's'}{comp.index === 0 ? ' (main)' : comp.size === 1 ? ' (isolated)' : ''}</span>
			</div>
		{/each}
	{/if}
	{#if graphEdges?.some?.((e: any) => e?.extras?.manual)}
		<div class="footprint-divider"></div>
		<div class="panel-label">Manual edges</div>
		<div class="lights-list">
			{#each graphEdges.filter((e: any) => e?.extras?.manual) as me (me.edge_id)}
				<div class="light-item">
					<span class="light-label">{me.source} → {me.target}</span>
					<button class="button button-subtle danger" onclick={() => onDeleteGraphEdge(me.edge_id)}>Delete</button>
				</div>
			{/each}
		</div>
	{/if}
</section>

<section class="rail-section rail-tool-panel paths-panel">
	<div class="rail-title">Episodes ({filteredEpisodes.length})</div>
	<input class="episode-search" type="search" placeholder="Search..." value={episodeSearch} oninput={(e) => onSetEpisodeSearch((e.currentTarget as HTMLInputElement).value)} />
	<div class="episode-list">
		{#each filteredEpisodes as ep}
			<div
				class="episode-row"
				class:selected={selectedEpisodeId === ep.episode_id}
				role="button"
				tabindex="0"
				onclick={() => onLoadEpisode(ep.episode_id)}
				onkeydown={(e) => e.key === 'Enter' && onLoadEpisode(ep.episode_id)}
			>
				<span class="ep-id">{ep.episode_id}</span>
				<span class="ep-mode">{ep.navigation_mode ?? 'traj'}</span>
				{#if ep.hazard_collision}<span class="badge-hazard">⚠</span>{/if}
			</div>
		{/each}
		{#if filteredEpisodes.length === 0}
			<div class="episode-empty">{episodes.length === 0 ? 'No episodes yet.' : 'No matches.'}</div>
		{/if}
	</div>
	<div class="episode-generate-bar">
		<input type="number" min="1" value={episodeCount} oninput={(e) => onSetEpisodeCount(Number((e.currentTarget as HTMLInputElement).value))} title="Count" />
		<button class="button button-primary" disabled={!caps.generateEpisodes.enabled} title={caps.generateEpisodes.reason} onclick={onGenerateEpisodes}>+ Generate</button>
		{#if episodes.length > 0}
			<button class="button button-subtle" onclick={onClearEpisodes} title="Clear all episodes">✕</button>
		{/if}
	</div>
	{#if onValidateEpisodes && episodes.length > 0}
		<div class="episode-validate-bar">
			<button class="button button-subtle" disabled={!caps.validateEpisodes.enabled} onclick={() => onValidateEpisodes?.()}
				title={caps.validateEpisodes.reason || "Check whether any episode path uses a node/edge you removed, or an edge disabled by the glass/mirror overlay."}>
				{validatingEpisodes ? 'Checking…' : '✓ Validate episodes'}
			</button>
			{#if staleEpisodeReport}
				{#if (staleEpisodeReport.stale_count ?? 0) > 0}
					<div class="episode-stale-warn">
						⚠ {staleEpisodeReport.stale_count} stale of {staleEpisodeReport.checked} — path uses removed/disabled edges
						<button class="button button-subtle danger" disabled={validatingEpisodes} title={validatingEpisodes ? 'Checking…' : ''} onclick={() => onPruneStaleEpisodes?.()}>
							Remove {staleEpisodeReport.stale_count} stale
						</button>
					</div>
				{:else}
					<div class="episode-stale-ok">✓ All {staleEpisodeReport.checked} graph episodes valid</div>
				{/if}
			{/if}
		</div>
	{/if}
	{#if onRenderEpisodeNodes && selectedEpisodeId}
		<label class="sensor-resume-row" title="Skip episode path viewpoints/headings that already have outputs.">
			<input type="checkbox" checked={renderMissingOnly} onchange={(e) => onSetRenderMissingOnly?.((e.currentTarget as HTMLInputElement).checked)} />
			<span>Only missing renders</span>
		</label>
		<div class="sensor-sweep-summary">Sweep sensors: {Math.max(1, selectedRigSensorCount)} selected</div>
		<button class="button button-primary full episode-render-btn"
			disabled={!caps.renderEpisodePath.enabled}
			title={caps.renderEpisodePath.reason}
			onclick={onRenderEpisodeNodes}>
			{#if episodeNodesAvailable && episodePathNodeCount > 0}
				▶ Render episode path ({episodePathNodeCount}{headingsPerNode > 0 ? ` × ${headingsPerNode}` : ''} jobs)
			{:else}
				▶ Render episode path
			{/if}
		</button>
	{/if}
</section>

<!-- Condensed Paths panel: grid / graph / episode generation summary -->
<section class="rail-section rail-tool-panel">
	<details open>
		<summary class="rail-summary">Paths</summary>
		<div class="map-settings-body rail-settings-body">
			<div class="path-status-chips">
				<span class:chip-ok={hasMap} class:chip-off={!hasMap}>Map {hasMap ? 'ready' : 'missing'}</span>
				<span class:chip-ok={hasGraph} class:chip-off={!hasGraph}>Graph {hasGraph ? 'ready' : 'missing'}</span>
				{#if graphPayloadSummary}<span class="chip-ok">{graphPayloadSummary.node_count}n · {graphPayloadSummary.edge_count}e</span>{/if}
			</div>
			<div class="rail-title">Traversable Grid</div>
			<label><span>resolution m</span><input type="number" step="0.01" min="0.01" value={resolution} oninput={(e) => onSetResolution(Number((e.currentTarget as HTMLInputElement).value))} /></label>
			<button class="button button-subtle" disabled={!caps.buildMap.enabled} title={caps.buildMap.reason} onclick={onBuildMap}>
				{#if buildingMap}<span class="spinner-xs"></span> Building...{:else}{hasMap ? 'Rebuild Grid' : 'Build Grid'}{/if}
			</button>
			{#if mapResult}
				<div class="build-result-row">
					<span class="chip-ok">Grid ready</span>
					{#if mapResult.cell_count}<span class="chip-dim">{mapResult.cell_count} cells</span>{/if}
					{#if mapResult.traversable_ratio != null}<span class="chip-dim">{(mapResult.traversable_ratio * 100).toFixed(0)}% walkable</span>{/if}
				</div>
			{/if}
			<div class="rail-title mt-2">Viewpoint Graph</div>
			<div class="geometry-grid">
				<label><span>max nodes</span><input type="number" min="1" value={maxNodes} oninput={(e) => onSetMaxNodes(Number((e.currentTarget as HTMLInputElement).value))} /></label>
				<label><span>headings</span><input type="number" min="1" value={headingCount} oninput={(e) => onSetHeadingCount(Number((e.currentTarget as HTMLInputElement).value))} /></label>
				<label><span>spacing m</span><input type="number" step="0.05" min="0" value={minNodeSpacing} oninput={(e) => onSetMinNodeSpacing(Number((e.currentTarget as HTMLInputElement).value))} /></label>
				<label><span>robot r</span><input type="number" step="0.05" min="0" value={robotRadius} oninput={(e) => onSetRobotRadius(Number((e.currentTarget as HTMLInputElement).value))} /></label>
			</div>
			<button class="button button-subtle" disabled={!caps.buildGraph.enabled} title={caps.buildGraph.reason} onclick={onRequestBuildGraph}>
				{#if buildingGraph}<span class="spinner-xs"></span>{#if graphBuildProgress} {graphBuildProgress.stage === 'edges' ? 'Edges' : 'Nodes'} {Math.round(graphBuildProgress.progress * 100)}%{:else} Building...{/if}{:else}{hasGraph ? 'Rebuild Graph' : 'Build Graph'}{/if}
			</button>
			{#if graphResult || graphPayloadSummary}
				<div class="build-result-row">
					<span class="chip-ok">Graph ready</span>
					<span class="chip-dim">{graphPayloadSummary?.node_count ?? graphResult?.node_count ?? '?'}n</span>
					<span class="chip-dim">{graphPayloadSummary?.edge_count ?? graphResult?.edge_count ?? '?'}e</span>
					{#if (graphPayloadSummary?.hazard_edge_count ?? graphResult?.hazard_edge_count ?? 0) > 0}
						<span class="chip-warn">{graphPayloadSummary?.hazard_edge_count ?? graphResult?.hazard_edge_count} hazard</span>
					{/if}
				</div>
			{/if}
			<div class="rail-title mt-2">Episodes</div>
			<label><span>num pairs</span><input type="number" min="1" value={episodeCount} oninput={(e) => onSetEpisodeCount(Number((e.currentTarget as HTMLInputElement).value))} /></label>
			<button class="button button-primary" disabled={!caps.generateEpisodes.enabled} title={caps.generateEpisodes.reason} onclick={onGenerateEpisodes}>
				Generate Episodes
			</button>
			{#if splitCounts.train != null}
				<div class="path-status-chips mt-1">
					<span class="chip-ok">train {splitCounts.train}</span>
					<span class="chip-ok">val_seen {splitCounts.val_seen ?? 0}</span>
					<span class="chip-ok">val_unseen {splitCounts.val_unseen ?? 0}</span>
				</div>
			{/if}
		</div>
	</details>
</section>

<style>
	.footprint-panel { display: grid; gap: var(--space-2); }

	.footprint-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2); }

	.footprint-grid label { display: grid; gap: 2px; font-size: var(--font-size-xs); }

	.footprint-grid input { padding: 2px 4px; border: 1px solid var(--border); border-radius: var(--radius-sm); }

	.footprint-info { font-size: var(--font-size-xs); color: var(--muted-strong); }

	.footprint-toggle { display: flex; gap: 6px; align-items: center; font-size: var(--font-size-xs); }

	.footprint-divider { height: 1px; background: var(--border); margin: 4px 0; }

	.paint-swatch { width: 14px; height: 14px; border-radius: 50%; border: 1px solid var(--border); }

	.paint-swatch.walkable { background: #22c55e; }

	.paint-swatch.blocked { background: #ef4444; }

	.paint-radius { width: 70px; }

	.paint-info { display: flex; gap: 6px; align-items: center; font-size: var(--font-size-xs); }

	.component-row { display: flex; gap: 6px; align-items: center; font-size: var(--font-size-xs); padding: 2px 0; }

	.component-dot { width: 12px; height: 12px; border-radius: 50%; border: 1px solid var(--border); }

	.mode-radio-group { display: grid; gap: 2px; }

	.mode-radio {
			display: flex;
			gap: 8px;
			align-items: center;
			padding: 4px 6px;
			border-radius: var(--radius-sm);
			cursor: pointer;
			font-size: var(--font-size-sm);
		}

	.mode-radio:hover { background: var(--surface-1); }

	.mode-radio input[type="radio"] { margin: 0; cursor: pointer; }

	.mode-radio span { display: flex; gap: 6px; align-items: center; }

	.mode-active-banner {
			padding: 6px 10px;
			background: #dbeafe;
			color: #1e40af;
			border-radius: var(--radius-sm);
			font-size: var(--font-size-xs);
			border-left: 3px solid #3b82f6;
		}

	.edge-diag { display: grid; gap: 4px; padding: var(--space-2); background: var(--surface-1); border-radius: var(--radius-sm); font-size: var(--font-size-xs); border: 1px solid var(--panel-border); }

	.edge-diag-title { font-weight: 600; font-family: monospace; }

	.edge-diag-detail { color: var(--muted-strong); font-style: italic; }

	.edge-diag-verdict { padding: 4px 8px; border-radius: var(--radius-sm); background: var(--danger-soft); color: var(--danger); font-weight: 600; margin-top: 4px; }

	.edge-diag-verdict.ok { background: #f0fdf4; color: #166534; }

	.edge-diag-actions { display: flex; gap: var(--space-2); margin-top: 4px; }

	/* Paths panel */
	.paths-panel .episode-search {
			width: 100%;
			padding: 4px 8px;
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			font-size: var(--font-size-xs);
		}

	.paths-panel .episode-list {
			display: flex;
			flex-direction: column;
			gap: 2px;
			max-height: 300px;
			overflow-y: auto;
		}

	.paths-panel .episode-row {
			display: flex;
			align-items: center;
			gap: 6px;
			padding: 4px 6px;
			border-radius: var(--radius-sm);
			cursor: pointer;
			font-size: var(--font-size-xs);
			color: var(--text);
		}

	.paths-panel .episode-row:hover { background: var(--hover-bg); }

	.paths-panel .episode-row.selected { background: var(--accent-subtle); color: var(--accent); font-weight: 600; }

	.paths-panel .ep-id { font-family: monospace; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	.paths-panel .ep-mode { color: var(--text-muted); font-size: 10px; }

	.paths-panel .badge-hazard { color: #f97316; }

	.paths-panel .episode-empty { color: var(--text-muted); font-size: var(--font-size-xs); padding: 8px 0; text-align: center; }

	.paths-panel .episode-generate-bar {
			display: flex;
			gap: 6px;
			align-items: center;
			border-top: 1px solid var(--panel-border);
			padding-top: var(--space-2);
		}

	.paths-panel .episode-generate-bar input { width: 60px; padding: 3px 6px; font-size: var(--font-size-xs); border: 1px solid var(--panel-border); border-radius: var(--radius-sm); }

	.paths-panel .episode-generate-bar button { flex: 1; }

	.sensor-sweep-summary {
			font-size: 11px;
			color: var(--text-muted);
			padding: 0 4px 4px;
		}

	.episode-validate-bar { display: grid; gap: 6px; margin-top: 6px; }

	.episode-stale-warn {
			display: grid;
			gap: 6px;
			font-size: var(--font-size-xs);
			color: var(--danger);
			background: var(--danger-soft);
			padding: 6px 8px;
			border-radius: var(--radius-sm);
		}

	.episode-stale-ok { font-size: var(--font-size-xs); color: #166534; }

	/* Path status chips */
	.path-status-chips {
			display: flex;
			gap: 4px;
			flex-wrap: wrap;
		}

	.path-status-chips span {
			padding: 2px 7px;
			border-radius: 99px;
			font-size: 10px;
			font-weight: 500;
		}

	.build-result-row { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; align-items: center; }
</style>
