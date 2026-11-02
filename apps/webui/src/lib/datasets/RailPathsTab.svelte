<script lang="ts">
	import type { Capabilities } from '$lib/datasets/capabilityHelpers';
	import { navigationSupportProgressLabel } from '$lib/datasets/services/graphService';
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
		adaptiveNavigation: any;
		navigationSupport: any;
		supportAnalysis?: any;
		blueprintStartAnchorId?: string;
		blueprintGoalAnchorId?: string;
		activeBlueprintId?: string;
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
		edgeCheckPending?: boolean;
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
		onSetBlueprintStartAnchorId?: (id: string) => void;
		onSetBlueprintGoalAnchorId?: (id: string) => void;
		onCreateManualBlueprint?: () => void;
		onSetBlueprintStatus?: (blueprintId: string, status: 'proposed' | 'approved' | 'rejected') => void;
		onApproveAllProposedBlueprints?: () => void;
		onResetApprovedBlueprints?: () => void;
		onDeleteBlueprint?: (blueprintId: string) => void;
		onSelectBlueprint?: (blueprintId: string) => void;
		onAnalyzeSupportGraph?: () => void;
		onBuildSupportGraph?: () => void;
		onRenderNavigationSupport?: () => void;
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
		onCertifyVisibleOpening: () => void;
		onDismissEdgeCheck: () => void;
		onDeleteGraphEdge: (edgeId: string) => void;
		onDeleteGraphNode: () => void;
		onLoadEpisode: (id: string) => void;
		onGenerateEpisodes: () => void;
		onGenerateRouteMotionEpisodes?: () => void;
		episodePlanProgress?: { status?: string; planned?: number; target?: number } | null;
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
		// Review-only oversized furniture scan. The parent owns the authoring map
		// mutation so the normal undo/save/sync contract stays intact.
		navigationBlockerCandidates?: any[];
		selectedNavigationBlockerIds?: Set<string>;
		navigationBlockersScanned?: boolean;
		navigationBlockersLoading?: boolean;
		onScanNavigationBlockers?: () => void;
		onToggleNavigationBlocker?: (objectId: string, selected: boolean) => void;
		onSetAllNavigationBlockers?: (selected: boolean) => void;
		onRemoveSelectedNavigationBlockers?: () => void;
		placeNodeFeedback?: { tone: 'info' | 'ok' | 'error'; message: string } | null;
		// Exact boundary pairs for the retained place-graph islands.  They are
		// review guides, not unsafe automatic links.
		placeRepairGuides?: any[];
		activePlaceRepairGuideId?: string;
		onInspectPlaceRepairGuide?: (guide: any) => void;
	}

	const COMPONENT_COLORS = ['#6366f1','#ef4444','#fbbf24','#a855f7','#14b8a6','#ec4899','#84cc16'];

	let {
		caps,
		hasMap, hasGraph, hasScene, selectedProjectId, sceneId, loading,
		buildingMap, buildingGraph, graphBuildProgress, graphResult, adaptiveNavigation, navigationSupport,
		supportAnalysis = null, blueprintStartAnchorId = '', blueprintGoalAnchorId = '', activeBlueprintId = '', mapResult,
		graphPayloadSummary, graphPayload, graphNodes, graphEdges,
		pathsMode, paintRadiusM, pendingEdgeSource, edgeInspectorSource,
		pendingRegionBbox, walkabilityOverlayMeta, traversableMeta,
		showTraversableMask, showFootprint, edgeCheckResult, edgeCheckPending = false,
		filteredEpisodes, episodes, episodeSearch, episodeCount,
		selectedEpisodeId, splitCounts, robotRadius, minClearance, resolution,
		maxNodes, headingCount, minNodeSpacing, selectedSensorNode,
		onBuildMap, onRequestBuildGraph, onSetBlueprintStartAnchorId, onSetBlueprintGoalAnchorId,
		onCreateManualBlueprint, onSetBlueprintStatus, onApproveAllProposedBlueprints, onResetApprovedBlueprints, onDeleteBlueprint, onSelectBlueprint, onAnalyzeSupportGraph,
		onBuildSupportGraph, onRenderNavigationSupport, onRebuildEdges, rebuildingEdges = false, onSetPathsMode, onSetPaintRadius,
		onRebuildRegion, onClearRegion, onClearWalkabilityOverlay, onRefreshTraversableMeta,
		onSetShowFootprint, onSetShowTraversableMask, onAddEdgeAnyway, onCertifyVisibleOpening, onDismissEdgeCheck,
		onDeleteGraphEdge, onDeleteGraphNode, onLoadEpisode, onGenerateEpisodes, onGenerateRouteMotionEpisodes, episodePlanProgress = null,
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
		navigationBlockerCandidates = [], selectedNavigationBlockerIds = new Set(), navigationBlockersScanned = false,
		navigationBlockersLoading = false, onScanNavigationBlockers, onToggleNavigationBlocker, onSetAllNavigationBlockers,
		onRemoveSelectedNavigationBlockers,
		placeNodeFeedback = null,
		placeRepairGuides = [], activePlaceRepairGuideId = '', onInspectPlaceRepairGuide,
	}: Props = $props();

	const supportBlueprints = $derived(navigationSupport?.route_blueprints?.blueprints ?? []);
	const approvedBlueprints = $derived(supportBlueprints.filter((item: any) => item.status === 'approved'));
	const supportReady = $derived(Boolean(navigationSupport?.support_graph && navigationSupport?.observation_plan));
	const retainedSealedComponents = $derived(
		navigationSupport?.place_graph?.metadata?.generation_diagnostics?.sealed_components_retained ?? [],
	);
	// The server recomputes component_summary for the *current* place graph.
	// generation diagnostics are build-time history and may still mention
	// components that the reviewer subsequently connected by manual portals.
	const disconnectedPlaceComponents = $derived(
		Array.isArray(graphPayload?.component_summary)
			? Math.max(0, graphPayload.component_summary.length - 1)
			: retainedSealedComponents.length,
	);
	const placeConnectivityReady = $derived(disconnectedPlaceComponents === 0);
	const proposedBlueprints = $derived(supportBlueprints.filter((item: any) => item.status === 'proposed'));
	const supportBlockedBlueprintIds = $derived(new Set<string>(
		(supportAnalysis?.analysis?.blocked_blueprint_ids ?? []).map((item: unknown) => String(item)),
	));
</script>

<!-- Detailed footprint / interaction / edge diagnostics panel -->
<section class="rail-section rail-tool-panel footprint-panel navigation-support-panel">
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
	<div class="footprint-divider"></div>
	<div class="rail-title">Large navigation blockers</div>
	<div class="footprint-info">Finds only review candidates: large, low furniture. Walls, doors, windows, lights, and small props are excluded; nothing is deleted automatically.</div>
	<button class="button button-subtle" disabled={!hasScene || navigationBlockersLoading} onclick={() => onScanNavigationBlockers?.()}>
		{navigationBlockersLoading ? 'Scanning blockers…' : 'Scan large blockers'}
	</button>
	{#if navigationBlockersScanned}
		{#if navigationBlockerCandidates.length}
			<div class="blocker-list" aria-label="Large navigation blocker candidates">
				{#each navigationBlockerCandidates as candidate (candidate.object_id)}
					<label class="blocker-row" title={candidate.object_id}>
						<input type="checkbox" checked={selectedNavigationBlockerIds.has(String(candidate.object_id))} onchange={(event) => onToggleNavigationBlocker?.(String(candidate.object_id), (event.currentTarget as HTMLInputElement).checked)} />
						<span class="blocker-copy"><strong>{candidate.label}</strong><small>{candidate.footprint_area_m2} m² · {candidate.max_extent_m} m · {candidate.reasons?.join(', ')}</small></span>
					</label>
				{/each}
			</div>
			<div class="blocker-actions">
				<button class="button button-subtle" onclick={() => onSetAllNavigationBlockers?.(true)}>Select all</button>
				<button class="button button-subtle" onclick={() => onSetAllNavigationBlockers?.(false)}>Clear</button>
				<button class="button button-subtle danger" disabled={selectedNavigationBlockerIds.size === 0 || navigationBlockersLoading} onclick={() => onRemoveSelectedNavigationBlockers?.()}>Remove selected ({selectedNavigationBlockerIds.size})</button>
			</div>
		{:else}
			<div class="footprint-info">No oversized removable low blockers matched the current criteria.</div>
		{/if}
		<div class="footprint-info">After a removal: <strong>Sync Render Scene → Rebuild grid → Rebuild Place Graph</strong>. The scan itself never changes geometry.</div>
	{/if}
	<div class="rail-title mt-2">Navigation Support v4</div>
	<button class="button button-subtle" disabled={!caps.buildGraph.enabled} title={caps.buildGraph.reason} onclick={onRequestBuildGraph}>
		{buildingGraph ? 'Building place graph…' : navigationSupport ? 'Rebuild Place Graph' : 'Build Place Graph'}
	</button>
	{#if buildingGraph}
		<div class="route-motion-progress" aria-live="polite">
			<div><span>{navigationSupportProgressLabel(graphBuildProgress?.stage)}</span><strong>{Math.round((graphBuildProgress?.progress ?? 0) * 100)}%</strong></div>
			<div class="route-motion-progress-track"><span style={`width: ${Math.round((graphBuildProgress?.progress ?? 0) * 100)}%`}></span></div>
			{#if graphBuildProgress?.detail?.expanded_state_count}
				<small>{graphBuildProgress.detail.expanded_state_count} action states explored</small>
			{/if}
		</div>
	{/if}
	{#if navigationSupport}
		<div class="footprint-info">Place-node and edge tools below now edit <code>place_graph.json</code>. Each topology edit resets Blueprint review and invalidates derived support lanes.</div>
		{#if navigationSupport.archived_render_plan}
			<div class="footprint-info">
				<strong>Archived render-plan overlay</strong> · <code>{navigationSupport.archived_render_plan.archive_ref}</code> · {navigationSupport.archived_render_plan.render_graph?.nodes?.length ?? 0} recovered render poses / {navigationSupport.archived_render_plan.observation_plan?.summary?.polar_observation_count ?? 0} native L0 views. Toggle <strong>Motion</strong> for the archived pose map and <strong>Obs</strong> for panorama rings. This is read-only and cannot generate episodes from the edited place graph.
			</div>
		{/if}
		{#if disconnectedPlaceComponents > 0}
			<div class="sealed-component-guide">
				<strong>{disconnectedPlaceComponents} safe disconnected component{disconnectedPlaceComponents === 1 ? '' : 's'} retained</strong>
				<span>Amber dashed map lines with green → red endpoints mark the closest repair boundary. They are not edges: use Show + check boundary, then add a direct place link only when the opening is certified.</span>
				{#if retainedSealedComponents.length}
					<div class="sealed-component-chips">{#each retainedSealedComponents as component}<span>{component.size} nodes @ {component.centroid?.[0]}, {component.centroid?.[1]}</span>{/each}</div>
				{/if}
				{#if placeRepairGuides.length}
					<div class="repair-guide-list">
						{#each placeRepairGuides as guide (guide.guide_id)}
							<div class="repair-guide-row" class:active={activePlaceRepairGuideId === guide.guide_id}>
								<div class="repair-guide-copy">
									<strong>Repair component {guide.component_index} · {guide.component_size} nodes</strong>
									<small><code>{guide.main_node_id}</code> ↔ <code>{guide.detached_node_id}</code> · nearest boundary {Number(guide.straight_line_distance_m).toFixed(2)} m</small>
								</div>
								<button class="button button-subtle" disabled={edgeCheckPending} onclick={() => onInspectPlaceRepairGuide?.(guide)}>
									{edgeCheckPending ? 'Checking boundary…' : 'Show + check boundary'}
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	{:else}
		<button class="button button-subtle" disabled={!caps.rebuildEdges.enabled} onclick={() => onRebuildEdges?.()} title={caps.rebuildEdges.reason || "Legacy-editor operation: re-run edge building over viewpoint_graph.json."}>
			{rebuildingEdges ? 'Rebuilding legacy edges…' : 'Rebuild legacy graph edges'}
		</button>
	{/if}
	{#if selectedSensorNode && !(selectedSensorNode as any).isCustom}
		<button class="button button-subtle danger" onclick={onDeleteGraphNode}>
			Delete {selectedSensorNode.node_id}
		</button>
	{/if}
</section>

<section class="rail-section rail-tool-panel footprint-panel navigation-support-panel">
	<div class="rail-title">2. Route Blueprints</div>
	{#if navigationSupport?.route_blueprints}
		<div class="footprint-info">Dotted routes are review intents only. Approve only the route pairs that must become executable lanes.</div>
		<label><span>manual start</span><select value={blueprintStartAnchorId} onchange={(e) => onSetBlueprintStartAnchorId?.((e.currentTarget as HTMLSelectElement).value)}>{#each navigationSupport.place_graph?.nodes ?? [] as node}<option value={node.node_id}>{node.node_id}</option>{/each}</select></label>
		<label><span>manual goal</span><select value={blueprintGoalAnchorId} onchange={(e) => onSetBlueprintGoalAnchorId?.((e.currentTarget as HTMLSelectElement).value)}>{#each navigationSupport.place_graph?.nodes ?? [] as node}<option value={node.node_id}>{node.node_id}</option>{/each}</select></label>
		<div class="blueprint-create-actions">
			<button class="button button-subtle" disabled={loading} title="Click this, then click a start and goal place node on the map. The second click creates a proposed blueprint." onclick={() => onSetPathsMode('blueprint_pair')}>Pick start + goal on map</button>
			<button class="button button-subtle" disabled={!blueprintStartAnchorId || !blueprintGoalAnchorId || blueprintStartAnchorId === blueprintGoalAnchorId || loading} onclick={() => onCreateManualBlueprint?.()}>Add manual blueprint</button>
		</div>
		<div class="blueprint-bulk-actions">
			<span>{approvedBlueprints.length} approved · {proposedBlueprints.length} proposed</span>
			<button class="button button-subtle" disabled={loading || !proposedBlueprints.length} title="Approve every proposed route. Explicitly rejected routes stay rejected; run Analyze Support afterwards to check the budget." onclick={() => onApproveAllProposedBlueprints?.()}>Approve all proposed</button>
			<button class="button button-subtle" disabled={loading || !approvedBlueprints.length} title="Move all approved routes back to Proposed so you can choose a smaller reviewed support set. Rejected routes remain rejected." onclick={() => onResetApprovedBlueprints?.()}>Reset approvals</button>
		</div>
		<div class="blueprint-list" aria-label="Route Blueprint review list">
			{#each supportBlueprints as blueprint}
				<div class="blueprint-row" class:selected={blueprint.blueprint_id === activeBlueprintId} class:blocked={supportBlockedBlueprintIds.has(blueprint.blueprint_id)} role="button" tabindex="0" onclick={() => onSelectBlueprint?.(blueprint.blueprint_id)} onkeydown={(event) => event.key === 'Enter' && onSelectBlueprint?.(blueprint.blueprint_id)}>
					<span class:chip-ok={blueprint.status === 'approved'} class:chip-warn={blueprint.status === 'proposed'} class="chip-dim blueprint-id" title={blueprint.blueprint_id}>{blueprint.blueprint_id}</span>
					<span class="blueprint-route" title={`${blueprint.start_anchor_id} → ${blueprint.goal_anchor_id}`}>{blueprint.start_anchor_id} → {blueprint.goal_anchor_id}</span>
					{#if supportBlockedBlueprintIds.has(blueprint.blueprint_id)}<span class="chip-warn">blocked</span>{/if}
					<div class="blueprint-actions">
						<button class="button button-subtle" disabled={loading || blueprint.status === 'approved'} onclick={(event) => { event.stopPropagation(); onSetBlueprintStatus?.(blueprint.blueprint_id, 'approved'); }}>Approve</button>
						<button class="button button-subtle" disabled={loading || blueprint.status === 'rejected'} onclick={(event) => { event.stopPropagation(); onSetBlueprintStatus?.(blueprint.blueprint_id, 'rejected'); }}>Reject</button>
						<button class="button button-subtle danger" disabled={loading} onclick={(event) => { event.stopPropagation(); onDeleteBlueprint?.(blueprint.blueprint_id); }}>Delete</button>
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<div class="footprint-info">Build Place Graph to generate reviewable routes.</div>
	{/if}
</section>

<section class="rail-section rail-tool-panel footprint-panel navigation-support-panel">
	<div class="rail-title">3. Navigation Support</div>
	<button class="button button-subtle" disabled={!approvedBlueprints.length || buildingGraph || !placeConnectivityReady} title={!placeConnectivityReady ? 'Connect every retained safe place component before analyzing executable support.' : undefined} onclick={() => onAnalyzeSupportGraph?.()}>Analyze Support</button>
	<button class="button button-primary" disabled={!approvedBlueprints.length || buildingGraph || !placeConnectivityReady} title={!placeConnectivityReady ? 'Connect every retained safe place component before building executable support.' : undefined} onclick={() => onBuildSupportGraph?.()}>Build Navigation Support</button>
	{#if supportAnalysis?.summary}
		<div class="build-result-row"><span class="chip-dim">{supportAnalysis.summary.support_pose_count} poses</span><span class="chip-dim">{supportAnalysis.summary.polar_observation_count} polar views</span><span class="chip-dim">{supportAnalysis.summary.polar_batch_count} K=4 batches</span></div>
	{/if}
	{#if supportAnalysis?.analysis?.ok === false}
		<div class="footprint-info warning"><strong>Support blocked:</strong> {supportAnalysis.analysis.place_edge_id ?? supportAnalysis.analysis.error}. {#if supportAnalysis.analysis.blocked_blueprint_ids?.length}Used by {supportAnalysis.analysis.blocked_blueprint_ids.join(', ')}. {/if}{supportAnalysis.analysis.message ?? 'Review the marked blueprints before building.'}</div>
	{/if}
	{#if Number(supportAnalysis?.generation_diagnostics?.deferred_unapproved_trunk_edge_count ?? 0) > 0}
		<div class="footprint-info">{supportAnalysis.generation_diagnostics.deferred_unapproved_trunk_edge_count} auto trunk links are deferred: they are not rendered until a Blueprint using them is approved. Review their dotted map routes, then approve only the corridors you need.</div>
	{/if}
	{#if supportReady}
		<div class="build-result-row"><span class="chip-ok">Support ready</span><span class="chip-dim">{navigationSupport.observation_plan?.summary?.polar_observation_count ?? 0}/8000 native views</span></div>
		<button class="button button-subtle" disabled={loading} onclick={() => onRenderNavigationSupport?.()}>Render Navigation Support Plan</button>
	{/if}
</section>

<section class="rail-section rail-tool-panel footprint-panel">
	<div class="rail-title">Map interaction</div>
	<div class="mode-radio-group">
		{#each [
			{ value: 'select', label: '🖱 Select', title: 'Default. Click nodes or objects to select; orbit/zoom the 3D view.' },
			{ value: 'place_node', label: '📍 Place node', title: navigationSupport ? 'Click a green, robot-safe cell at least 0.15 m from another place node. Blueprint review resets after this edit.' : 'Click anywhere on the floor to insert a new viewpoint node at that (x, z). Node gets default headings.' },
			{ value: 'paint_walkable', label: 'Paint walkable', title: 'Drag on the floor to mark cells as walkable (force traversable). Survives map rebuilds.', swatch: 'walkable' },
			{ value: 'paint_blocked', label: 'Paint blocked', title: 'Drag on the floor to mark cells as blocked (force non-traversable). Useful for closing off areas the planner should not use.', swatch: 'blocked' },
			{ value: 'paint_erase', label: '🧽 Erase paint', title: 'Drag to clear walkability paint marks in that area (restore the auto-computed mask).' },
			{ value: 'select_region', label: '▭ Select region', title: navigationSupport ? 'Legacy-only region resampling. Edit the v4 place graph with individual place nodes instead.' : 'Drag a rectangle on the floor to select an area, then click "Rebuild this region" to re-sample only that area viewpoints.' },
			{ value: 'add_edge', label: '⤴ Add edge', title: navigationSupport ? 'Click two place nodes to add a direct topology link (up to 8 m only when the complete segment is collision-free). Stage 3 expands it into 0.25 m actions.' : 'Click two graph nodes in sequence to create a manual edge between them (shown in purple).' },
			{ value: 'blueprint_pair', label: '🧭 Blueprint pair', title: navigationSupport ? 'Click a start place node, then a goal place node. The second click adds a proposed route blueprint for review.' : 'Build Navigation Support first.' },
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
			{#if pathsMode === 'place_node'}{navigationSupport ? 'Click a green safe cell ≥0.15 m from any place node…' : 'Click on the floor to place a node…'}
			{:else if pathsMode.startsWith('paint_')}Drag on the floor (brush radius {paintRadiusM} m)…
			{:else if pathsMode === 'select_region'}Drag a rectangle on the floor…
			{:else if pathsMode === 'add_edge'}{pendingEdgeSource ? `Source: ${pendingEdgeSource} · click target…` : navigationSupport ? 'Click two place nodes for a collision-checked direct topology link…' : 'Click first node…'}
			{:else if pathsMode === 'blueprint_pair'}{navigationSupport ? 'Click a start place node, then a goal place node. The route will be added as Proposed for review…' : 'Build Navigation Support first…'}
			{:else if pathsMode === 'remove_edge'}{pendingEdgeSource ? `Endpoint: ${pendingEdgeSource} · click the other endpoint to delete…` : 'Click first endpoint of the edge to remove…'}
			{:else if pathsMode === 'inspect_edge'}{edgeInspectorSource ? `Source: ${edgeInspectorSource} · click target to diagnose…` : 'Click first node…'}
			{:else if pathsMode === 'remove_node'}{removeSelectionCount ? `${removeSelectionCount} node(s) marked · box-drag or click to add/remove` : 'Box-drag a rectangle or click nodes to mark for removal…'}
			{/if}
		</div>
	{/if}
	{#if pathsMode === 'place_node' && placeNodeFeedback}
		<div class="place-node-feedback" class:ok={placeNodeFeedback.tone === 'ok'} class:error={placeNodeFeedback.tone === 'error'}>
			{placeNodeFeedback.message}
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
			<button class="button button-subtle" disabled={Boolean(navigationSupport) || !caps.findOverlapping.enabled} title={navigationSupport ? 'Overlap auto-find currently applies only to the legacy graph; select v4 place nodes on the map instead.' : caps.findOverlapping.reason} onclick={() => onFindOverlapping?.()}>
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
	{#if pendingRegionBbox && !navigationSupport}
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
			{#if edgeCheckResult.gap_run_cells > 0}
				<div class="edge-diag-detail">Threshold gap: {edgeCheckResult.gap_run_cells} cells · {(edgeCheckResult.gap_run_cells * (edgeCheckResult.generation_diagnostics?.grid_resolution_m ?? resolution)).toFixed(2)} m (allowance {edgeCheckResult.doorway_gap_m ?? 0.45} m)</div>
			{/if}
			{#if edgeCheckResult.reason === 'doorway_gap_too_wide'}
				<div class="edge-diag-detail">The opening is portal-aligned and wall-clear, but its floor-mask gap exceeds the certified doorway bound. Inspect the doorway/overlay rather than forcing an edge through it.</div>
			{:else if edgeCheckResult.reason === 'not_certified_doorway'}
				<div class="edge-diag-detail">The line leaves the safe grid without a resolved or inferred portal. {edgeCheckResult.manual_opening_eligible ? 'Body-height wall check is clear and the raw floor gap is short: you may explicitly confirm this visible opening.' : 'Add/repair the real doorway geometry, then rebuild the Place Graph.'}</div>
			{/if}
			<div class="edge-diag-verdict" class:ok={edgeCheckResult.would_connect}>
				{edgeCheckResult.would_connect ? '✓ Would connect on next graph build' : `✗ ${edgeCheckResult.reason}`}
			</div>
			<div class="edge-diag-actions">
				<button class="button button-subtle" disabled={!edgeCheckResult.would_connect} title={edgeCheckResult.would_connect ? (navigationSupport ? 'Create this direct place-topology link; Stage 3 will split it into 0.25 m actions.' : 'Create this certified edge.') : 'Unsafe segments cannot be added.'} onclick={onAddEdgeAnyway}>{navigationSupport ? 'Add direct place link' : 'Add edge anyway'}</button>
				{#if edgeCheckResult.manual_opening_eligible}
					<button class="button button-subtle" title="Record this wall-free short threshold as a user-certified open portal. Support build will revalidate its 0.25 m actions." onclick={onCertifyVisibleOpening}>Confirm visible opening…</button>
				{/if}
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
		<details class="manual-edges" open>
			<summary>Manual {navigationSupport ? 'place' : 'legacy'} edges ({graphEdges.filter((e: any) => e?.extras?.manual).length})</summary>
			<div class="manual-edge-list">
				{#each graphEdges.filter((e: any) => e?.extras?.manual) as me (me.edge_id)}
					<div class="manual-edge-row">
						<span title={`${me.source} → ${me.target}`}>{me.source} → {me.target}</span>
						<button class="button button-subtle danger" onclick={() => onDeleteGraphEdge(me.edge_id)}>Delete</button>
					</div>
				{/each}
			</div>
		</details>
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
		<button class="button button-primary" disabled={adaptiveNavigation ? false : !caps.generateEpisodes.enabled} title={adaptiveNavigation ? 'Generate validated staged-navigation episodes.' : caps.generateEpisodes.reason} onclick={adaptiveNavigation ? onGenerateRouteMotionEpisodes : onGenerateEpisodes}>
			{#if episodePlanProgress}
				{episodePlanProgress.status === 'indexing' ? 'Indexing…' : `Generating ${episodePlanProgress.planned ?? 0}/${episodePlanProgress.target ?? episodeCount}`}
			{:else}{adaptiveNavigation ? 'Generate Support Episodes' : '+ Generate'}{/if}
		</button>
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
				<span class:chip-ok={Boolean(navigationSupport || adaptiveNavigation)} class:chip-off={!navigationSupport && !adaptiveNavigation}>Navigation Support {navigationSupport || adaptiveNavigation ? 'ready' : 'missing'}</span>
				{#if navigationSupport}<span class="chip-ok">{navigationSupport.place_graph?.nodes?.length ?? 0} places · {navigationSupport.support_graph?.nodes?.length ?? 0} support</span>
				{:else if adaptiveNavigation}<span class="chip-ok">{adaptiveNavigation.anchor_graph?.nodes?.length ?? 0} places · {adaptiveNavigation.motion_graph?.nodes?.length ?? 0} support</span>
				{:else if graphPayloadSummary}<span class="chip-dim">legacy {graphPayloadSummary.node_count}n · {graphPayloadSummary.edge_count}e</span>{/if}
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
			<div class="rail-title mt-2">Navigation Support v4</div>
			<div class="geometry-grid">
				<label title="Maximum sparse global anchors. The 0.25 m action poses are generated separately along selected routes."><span>max anchors</span><input type="number" min="1" value={maxNodes} oninput={(e) => onSetMaxNodes(Number((e.currentTarget as HTMLInputElement).value))} /></label>
				<label title="Navigation Support v4 uses a fixed 24-heading, 15° action lattice after place-graph review."><span>turn lattice</span><input type="text" value="24 × 15° fixed" readonly aria-label="24 headings at 15 degrees, fixed" /></label>
				<label title="Sparse anchor spacing. This is not the forward action distance; route motion uses a fixed 0.25 m step."><span>anchor spacing m</span><input type="number" step="0.05" min="0.5" value={minNodeSpacing} oninput={(e) => onSetMinNodeSpacing(Math.max(0.5, Number((e.currentTarget as HTMLInputElement).value)))} /></label>
				<label title="Navigation Support v4 uses a 0.25 m robot radius plus its configured safety margin."><span>robot r</span><input type="number" step="0.05" min="0.25" value={robotRadius} oninput={(e) => onSetRobotRadius(Math.max(0.25, Number((e.currentTarget as HTMLInputElement).value)))} /></label>
			</div>
			<button class="button button-subtle" disabled={!caps.buildGraph.enabled} title={caps.buildGraph.reason} onclick={onRequestBuildGraph}>
				{#if buildingGraph}<span class="spinner-xs"></span> Building place graph…{:else}{navigationSupport ? 'Rebuild Place Graph' : 'Build Place Graph'}{/if}
			</button>
			{#if buildingGraph}
				<div class="route-motion-progress" aria-live="polite">
					<div><span>{navigationSupportProgressLabel(graphBuildProgress?.stage)}</span><strong>{Math.round((graphBuildProgress?.progress ?? 0) * 100)}%</strong></div>
					<div class="route-motion-progress-track"><span style={`width: ${Math.round((graphBuildProgress?.progress ?? 0) * 100)}%`}></span></div>
					{#if graphBuildProgress?.detail?.expanded_state_count}
						<small>{graphBuildProgress.detail.expanded_state_count} action states explored</small>
					{/if}
				</div>
			{/if}
			{#if navigationSupport || graphResult?.profile_id === 'adaptive_navigation_support_v4'}
				<div class="build-result-row">
					<span class="chip-ok">Place graph ready</span>
					<span class="chip-dim">{navigationSupport?.place_graph?.nodes?.length ?? graphResult?.place_node_count ?? '?'} places</span>
					<span class="chip-dim">{navigationSupport?.support_graph?.nodes?.length ?? 0} support</span>
				</div>
			{/if}
			<div class="rail-title mt-2">Episodes</div>
			<label><span>num pairs</span><input type="number" min="1" value={episodeCount} oninput={(e) => onSetEpisodeCount(Number((e.currentTarget as HTMLInputElement).value))} /></label>
			<button class="button button-primary" disabled={navigationSupport ? !supportReady : adaptiveNavigation ? false : !caps.generateEpisodes.enabled} title={navigationSupport ? (supportReady ? 'Generate validated Navigation Support episodes.' : 'Build Navigation Support after approving a Blueprint first.') : adaptiveNavigation ? 'Generate validated staged-navigation episodes.' : caps.generateEpisodes.reason} onclick={navigationSupport || adaptiveNavigation ? onGenerateRouteMotionEpisodes : onGenerateEpisodes}>
				{#if episodePlanProgress}
					{episodePlanProgress.status === 'indexing' ? 'Indexing…' : `Generating ${episodePlanProgress.planned ?? 0}/${episodePlanProgress.target ?? episodeCount}`}
				{:else}{navigationSupport || adaptiveNavigation ? 'Generate Support Episodes' : 'Generate Episodes'}{/if}
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
	.navigation-support-panel { font-size: 11px; }
	.navigation-support-panel .rail-title { font-size: 12px; }
	.navigation-support-panel label > span,
	.navigation-support-panel .footprint-info { font-size: 10px; }
	.navigation-support-panel select { min-height: 28px; font-size: 11px; }
	.navigation-support-panel .button { min-height: 28px; padding: 3px 8px; font-size: 11px; }
	.blueprint-list {
		display: grid;
		gap: 4px;
		max-height: 176px;
		overflow-y: auto;
		margin-top: 5px;
		padding-right: 2px;
	}
	.blueprint-create-actions { display: flex; gap: 5px; margin-top: 5px; }
	.blueprint-create-actions .button { flex: 1; }
	.blueprint-bulk-actions { display: flex; align-items: center; justify-content: space-between; gap: 5px; margin-top: 5px; font-size: 10px; color: var(--muted-strong); }
	.blueprint-bulk-actions .button { min-height: 24px; padding: 2px 7px; font-size: 10px; }
	.blueprint-row {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 3px 5px;
		align-items: center;
		padding: 4px 5px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		font-size: 10px;
		cursor: pointer;
	}
	.blueprint-row.selected { border-color: #f59e0b; background: #fffbeb; }
	.blueprint-row.blocked { border-color: #f59e0b; background: #fff7ed; }
	.blueprint-id { max-width: 56px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.blueprint-route { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted-strong); }
	.blueprint-actions { grid-column: 1 / -1; display: flex; gap: 4px; }
	.blueprint-actions .button { min-height: 24px; padding: 2px 7px; font-size: 10px; }
	.manual-edges { font-size: var(--font-size-xs); }
	.manual-edges summary { cursor: pointer; color: var(--muted-strong); font-weight: 600; }
	.manual-edge-list { display: grid; gap: 3px; max-height: 112px; overflow-y: auto; margin-top: 4px; }
	.manual-edge-row { display: flex; min-width: 0; align-items: center; gap: 5px; font-size: 10px; }
	.manual-edge-row > span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: monospace; }
	.manual-edge-row .button { min-height: 24px; padding: 2px 7px; font-size: 10px; }
	.blocker-list { display: grid; gap: 3px; max-height: 132px; overflow-y: auto; padding: 2px 1px; }
	.blocker-row { display: flex; gap: 6px; align-items: flex-start; padding: 4px 5px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); cursor: pointer; font-size: 10px; }
	.blocker-row input { margin-top: 2px; }
	.blocker-copy { display: grid; min-width: 0; gap: 1px; }
	.blocker-copy strong, .blocker-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.blocker-copy small { color: var(--muted-strong); font-size: 9px; }
	.blocker-actions { display: flex; gap: 4px; flex-wrap: wrap; }
	.sealed-component-guide { display: grid; gap: 3px; padding: 6px 7px; border: 1px solid #f59e0b; border-radius: var(--radius-sm); background: #fffbeb; color: #78350f; font-size: 10px; }
	.sealed-component-chips { display: flex; gap: 3px; flex-wrap: wrap; }
	.sealed-component-chips span { border-radius: 99px; padding: 1px 5px; background: #fef3c7; font-family: monospace; font-size: 9px; }
	.repair-guide-list { display: grid; gap: 4px; }
	.repair-guide-row { display: flex; align-items: center; justify-content: space-between; gap: 5px; padding: 4px 5px; border: 1px solid #fcd34d; border-radius: 5px; background: rgba(255,255,255,.62); }
	.repair-guide-row.active { border-color: #f97316; box-shadow: 0 0 0 1px rgba(249,115,22,.18); }
	.repair-guide-copy { display: grid; min-width: 0; gap: 1px; }
	.repair-guide-copy strong, .repair-guide-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.repair-guide-copy small { font-size: 9px; }
	.place-node-feedback { margin-top: 4px; padding: 5px 6px; border: 1px solid #bfdbfe; border-radius: 5px; background: #eff6ff; color: #1e3a8a; font-size: 10px; line-height: 1.35; }
	.place-node-feedback.ok { border-color: #86efac; background: #f0fdf4; color: #166534; }
	.place-node-feedback.error { border-color: #fca5a5; background: #fef2f2; color: #991b1b; }

	.route-motion-progress { display: grid; gap: 4px; padding: 6px 8px; border: 1px solid #bfdbfe; border-radius: var(--radius-sm); background: #eff6ff; font-size: var(--font-size-xs); color: #1e3a8a; }
	.route-motion-progress > div:first-child { display: flex; justify-content: space-between; gap: 8px; }
	.route-motion-progress strong { font-variant-numeric: tabular-nums; }
	.route-motion-progress small { color: #475569; }
	.route-motion-progress-track { height: 5px; overflow: hidden; border-radius: 99px; background: #bfdbfe; }
	.route-motion-progress-track > span { display: block; height: 100%; border-radius: inherit; background: #2563eb; transition: width 160ms ease-out; }
</style>
