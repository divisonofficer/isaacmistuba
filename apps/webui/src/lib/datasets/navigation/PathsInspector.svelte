<script lang="ts">
	import { onMount } from 'svelte';
	import { Check, ChevronDown, CircleCheck, CircleX, CircleDotDashed, FileStack, Link2, MapPin, Route, ScanLine, Search, Settings2, Trash2 } from '@lucide/svelte';
	import { InspectorSection, MetricCard, ProgressBar, SegmentedControl } from '$lib/components';
	import { navigationSupportProgressLabel } from '$lib/datasets/services/graphService';
	import { filterBlueprints, hasSuccessfulSupportAnalysis, primaryNavigationAction, supportAnalysisSummary, type NavigationInspectorTab } from './navigationPresentation';
	import type { EpisodeState, NavigationActions, NavigationState } from './types';

	interface Props {
		navigationState: NavigationState;
		episodeState: EpisodeState;
		navigationActions: NavigationActions;
	}

	let { navigationState, episodeState, navigationActions }: Props = $props();
	let tab = $state<NavigationInspectorTab>('setup');
	let routeQuery = $state('');
	let routeStatus = $state('all');
	let nodeQuery = $state('');
	let nodeFindMessage = $state('');
	let episodeBrowserOpen = $state(false);
	let advancedOpen = $state(false);
	let confirmBlueprintRegenerate = $state(false);
	let confirmEpisodeReplace = $state(false);
	// Submitting the render plan is the one primary action that spends GPU
	// hours, and it appears in the same place the Build button just occupied.
	// Never fire it straight from that shared button.
	let confirmRenderSubmit = $state(false);
	const episodeGenerationBusy = $derived(Boolean(episodeState.episodePlanProgress));

	const tabs = [
		{ id: 'setup', label: 'Setup' },
		{ id: 'routes', label: 'Routes' },
		{ id: 'support', label: 'Support' },
		{ id: 'episodes', label: 'Episodes' }
	];
	const blueprints = $derived(navigationState.navigationSupport?.route_blueprints?.blueprints ?? []);
	const selectedBlueprint = $derived(blueprints.find((item: any) => item.blueprint_id === navigationState.activeBlueprintId) ?? null);
	const filteredBlueprints = $derived(filterBlueprints(blueprints, routeQuery, routeStatus));
	const approvedCount = $derived(blueprints.filter((item: any) => item.status === 'approved').length);
	const repairGuides = $derived(navigationState.placeRepairGuides ?? []);
	const edgeReviewQueue = $derived(navigationState.edgeReviewQueue ?? []);
	const supportReady = $derived(Boolean(navigationState.supportReady));
	const analysisSummary = $derived(supportAnalysisSummary(navigationState.supportAnalysis));
	const supportAlgorithm = $derived(navigationState.supportAlgorithm ?? 'production_v1');
	const activeSupportAlgorithm = $derived(
		navigationState.navigationSupport?.support_graph?.support_algorithm_id ?? 'production_v1',
	);
	const supportAnalysisReady = $derived(
		hasSuccessfulSupportAnalysis(navigationState.supportAnalysis)
		&& String(navigationState.supportAnalysis?.support_algorithm ?? 'production_v1') === supportAlgorithm,
	);
	const supportActionBusy = $derived(Boolean(navigationState.loading || navigationState.buildingGraph));
	const navigationProgress = $derived(navigationState.buildingGraph
		? {
			label: navigationSupportProgressLabel(navigationState.graphBuildProgress?.stage),
			percent: Math.round(Number(navigationState.graphBuildProgress?.progress ?? 0) * 100),
		}
		: null);
	const canAnalyzeSupport = $derived(approvedCount > 0 && !supportActionBusy);
	const canBuildSupport = $derived(supportAnalysisReady && !navigationState.supportAnalysisStale && !supportActionBusy);
	const supportBlocker = $derived(navigationState.supportAnalysis?.ok === false
		? (navigationState.supportAnalysis?.analysis ?? navigationState.supportAnalysis)
		: null);
	const blockerGroups = $derived(
		Array.isArray(supportBlocker?.blockers) && supportBlocker.blockers.length
			? supportBlocker.blockers
			: supportBlocker ? [supportBlocker] : [],
	);
	const blockedBlueprintIds = $derived(
		Array.from(new Set([
			...(Array.isArray(supportBlocker?.blocked_blueprint_ids)
				? supportBlocker.blocked_blueprint_ids.map(String).filter(Boolean)
				: []),
			...blockerGroups.flatMap((group: any) => Array.isArray(group?.blocked_blueprint_ids)
				? group.blocked_blueprint_ids.map(String).filter(Boolean)
				: []),
		])),
	);
	const primary = $derived(primaryNavigationAction({ ...navigationState, supportReady }));

	function runPrimary() {
		if (primary.disabled) return;
		if (primary.id === 'build-grid') navigationActions.onBuildMap?.();
		else if (primary.id === 'build-place-graph') navigationActions.onRequestBuildGraph?.();
		else if (primary.id === 'analyze-support') navigationActions.onAnalyzeSupportGraph?.();
		else if (primary.id === 'review-support-blocker') reviewBlockingRoutes();
		else if (primary.id === 'build-support') navigationActions.onBuildSupportGraph?.();
		else confirmRenderSubmit = true;
	}

	function chooseRoute(id: string) {
		navigationActions.onSelectBlueprint?.(id);
	}

	function reviewBlockingRoutes() {
		// A structural blocker has no blueprint owner. Keep its edge details and
		// repair action visible instead of taking the operator to Routes.
		tab = 'support';
	}

	function reviewBlockingRoute(blueprintId: string) {
		routeStatus = 'approved';
		routeQuery = blueprintId;
		chooseRoute(blueprintId);
		tab = 'routes';
	}

	function blockerGroupLabel(group: any): string {
		switch (group?.kind) {
			case 'support_corridor_unreachable': return 'Unmaterializable corridor';
			case 'support_portal_not_open': return 'Closed portal';
			case 'blueprint_support_unreachable': return 'Route outside backbone';
			case 'blueprint_directness_exceeded': return 'Directness budget exceeded';
			case 'support_route_component_disconnected': return 'Route action states disconnected';
			case 'support_route_missing_states': return 'Route has no executable states';
			default: return 'Strict support blocker';
		}
	}

	function findNode() {
		const query = nodeQuery.trim();
		if (!query) return;
		const result = navigationActions.onFindGraphNode?.(query);
		nodeFindMessage = typeof result === 'string' ? result : `Finding ${query} on the canvas…`;
	}

	function showSupportBlockers() {
		tab = 'support';
	}

	function setRouteStatus(id: string, status: 'approved' | 'rejected', currentStatus: string) {
		// Both controls are true toggles: a second press returns the blueprint to
		// review instead of requiring a separate reset action.
		navigationActions.onSetBlueprintStatus?.(id, currentStatus === status ? 'proposed' : status);
	}

	function startBlueprintPair() {
		navigationActions.onSetPathsMode?.('blueprint_pair');
	}

	function setRepairTool(mode: string) {
		navigationActions.onSetPathsMode?.(mode);
	}

	function repairToolHint() {
		switch (navigationState.pathsMode) {
			case 'place_node': return 'Click a clear, walkable floor cell to add a place node.';
			case 'add_edge': return navigationState.pendingEdgeSource ? `Source ${navigationState.pendingEdgeSource} selected — click its target.` : 'Click two place nodes to add a collision-checked direct link.';
			case 'inspect_edge': return navigationState.edgeInspectorSource ? `Source ${navigationState.edgeInspectorSource} selected — click a target to inspect.` : 'Click two place nodes to inspect a missing boundary link.';
			case 'remove_edge': return navigationState.pendingEdgeSource ? `Endpoint ${navigationState.pendingEdgeSource} selected — click the other endpoint.` : 'Click two endpoints of a link to remove it.';
			case 'remove_node': return navigationState.removeSelectionCount ? `${navigationState.removeSelectionCount} node(s) marked. Click or box-select more nodes.` : 'Click or box-select place nodes to mark them for removal.';
			default: return '';
		}
	}

	function openingCertificationHint(result: any) {
		if (result?.reason !== 'not_certified_doorway') return '';
		if (result.manual_opening_eligible) {
			return `Eligible: no body-height wall or hazard, and the ${Number(result.raw_gap_m ?? 0).toFixed(2)} m raw floor gap is within the ${Number(result.manual_opening_max_gap_m ?? 1).toFixed(2)} m confirmation bound.`;
		}
		if (Number(result.wall_run_cells ?? 0) > 0) return `Unavailable: the candidate crosses ${result.wall_run_cells} body-height wall cell(s). Repair the actual doorway geometry instead.`;
		if (result.hazard_crossing) return 'Unavailable: the candidate crosses a hazard region.';
		const rawGap = Number(result.raw_gap_m ?? 0);
		const maxGap = Number(result.manual_opening_max_gap_m ?? 1);
		if (!(rawGap > 0)) return 'Unavailable: no bounded raw floor opening was detected.';
		if (rawGap > maxGap) return `Unavailable: raw floor gap ${rawGap.toFixed(2)} m exceeds the ${maxGap.toFixed(2)} m confirmation bound.`;
		return 'Unavailable: this is not a navigation-place boundary eligible for manual portal certification.';
	}

	function edgeReviewMessage(candidate: any) {
		if (candidate.status === 'checking') return 'Checking collision, clearance, and portal eligibility…';
		if (candidate.status === 'submitting') return 'Adding this direct link to the durable graph edit queue…';
		if (candidate.status === 'ready') return 'Collision check passed. Confirm to queue the direct place link.';
		if (candidate.status === 'opening_confirmation') return 'No automatic portal was found. The bounded raw opening still needs an explicit passability confirmation.';
		return candidate.check?.message ?? candidate.check?.reason ?? 'The segment is not certified safe and cannot be added.';
	}

	function generateEpisodes(writeMode: "append" | "replace_scene" = "append") {
		if (navigationState.navigationSupport || navigationState.adaptiveNavigation) navigationActions.onGenerateRouteMotionEpisodes?.(writeMode);
		else navigationActions.onGenerateEpisodes?.(writeMode);
	}

	function chooseEpisode(id: string) {
		navigationActions.onLoadEpisode?.(id);
		// Keep the inline collection open: selecting an episode is a comparison
		// action, not a navigation away from the Episodes workflow.
	}

	onMount(() => {
		const escape = (event: KeyboardEvent) => {
			if (event.key === 'Escape') {
				episodeBrowserOpen = false;
			}
		};
		window.addEventListener('keydown', escape);
		return () => {
			window.removeEventListener('keydown', escape);
		};
	});
</script>

<div class="paths-inspector">
	<header class="inspector-heading">
		<div>
			<p>Navigation</p>
			<h2>Navigation Support v4</h2>
		</div>
		<div class="inspector-status">
			{#if navigationProgress}
				<span class="operation-status" aria-live="polite" title={navigationProgress.label}>
					<span>{navigationProgress.label}</span>
					<strong>{navigationProgress.percent}%</strong>
				</span>
			{/if}
			<span class:ready={supportReady} class="state-chip">{supportReady ? 'Ready' : navigationState.hasGraph ? 'Review' : 'Setup'}</span>
		</div>
	</header>
	<SegmentedControl items={tabs} value={tab} ariaLabel="Navigation inspector section" onchange={(value) => tab = value as NavigationInspectorTab} />
	{#if supportBlocker}
		<div class="blocker-overview" role="alert">
			<header><strong>{blockerGroups.length} strict blocker group{blockerGroups.length === 1 ? '' : 's'}</strong><button class="button button-ghost" onclick={showSupportBlockers}>Show all</button></header>
				{#each blockerGroups as group, index (`overview:${group.id ?? group.kind ?? 'blocker'}:${index}`)}
					<button class="blocker-overview-row" onclick={showSupportBlockers}><span>{index + 1}</span><strong>{group.place_edge_id ?? group.portal_id ?? group.blueprint_id ?? blockerGroupLabel(group)}</strong><small>{group.source && group.target ? `${group.source} ↔ ${group.target}` : group.structural_backbone ? 'Structural connector' : `${group.blocked_blueprint_ids?.length ?? 0} route(s)`}</small></button>
			{/each}
		</div>
	{/if}

	{#if tab === 'setup'}
		<InspectorSection title="Robot footprint">
			<div class="form-grid">
				<label>Wall / collision radius (m)<input type="number" min="0.05" max="2" step="0.05" value={navigationState.robotRadius} oninput={(event) => navigationActions.onSetRobotRadius?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
				<label>Extra wall buffer (m)<input type="number" min="0" max="2" step="0.05" value={navigationState.minClearance} oninput={(event) => navigationActions.onSetMinClearance?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
			</div>
			<p class="help">Effective wall clearance: <strong>{(Number(navigationState.robotRadius) + Number(navigationState.minClearance) + 0.03).toFixed(2)} m</strong> <span class="muted">(includes 0.03 m raster epsilon)</span></p>
			{#if navigationState.clearanceRebuildRequired}
				<div class="clearance-pending">
					<p class="help warn">Changed clearance is pending. Existing links still use the saved <strong>{Number(navigationState.activePlaceGraphRobotRadius).toFixed(2)} m + {Number(navigationState.activePlaceGraphSafetyMargin).toFixed(2)} m</strong> contract until Place Graph is regenerated.</p>
					<button class="button button-subtle" onclick={() => navigationActions.onRequestBuildGraph?.()}>Rebuild Place Graph at {Number(navigationState.robotRadius).toFixed(2)} m</button>
				</div>
			{:else if navigationState.hasGraph}
				<p class="help">Saved Place Graph uses this clearance contract.</p>
			{/if}
		</InspectorSection>

		<InspectorSection title="Traversable grid">
			<label class="field">Resolution (m)<input type="number" min="0.01" step="0.01" value={navigationState.resolution} oninput={(event) => navigationActions.onSetResolution?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
			{#if navigationState.mapResult}
				<div class="inline-summary"><Check size={15} /> Grid ready · {navigationState.mapResult.cell_count ?? '—'} cells · {Math.round(Number(navigationState.mapResult.traversable_ratio ?? 0) * 100)}% walkable</div>
			{/if}
			<button class="button button-subtle" disabled={!navigationState.caps?.buildMap?.enabled || navigationState.buildingMap} title={navigationState.caps?.buildMap?.reason} onclick={() => navigationActions.onBuildMap?.()}>
				{navigationState.buildingMap ? 'Building grid…' : navigationState.hasMap ? 'Rebuild grid' : 'Build grid'}
			</button>
		</InspectorSection>

		<InspectorSection title="Place graph">
			<div class="form-grid">
				<label>Max places<input type="number" min="1" value={navigationState.maxNodes} oninput={(event) => navigationActions.onSetMaxNodes?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
				<label>Place spacing (m)<input type="number" min="0.5" step="0.05" value={navigationState.minNodeSpacing} oninput={(event) => navigationActions.onSetMinNodeSpacing?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
			</div>
			{#if navigationState.buildingGraph}
				<div class="progress-row"><span>{navigationSupportProgressLabel(navigationState.graphBuildProgress?.stage)}</span><ProgressBar value={Math.round(Number(navigationState.graphBuildProgress?.progress ?? 0) * 100)} showValue /></div>
			{:else if navigationState.navigationSupport?.place_graph}
				<div class="inline-summary"><Check size={15} /> {navigationState.navigationSupport.place_graph.nodes?.length ?? 0} places · {navigationState.navigationSupport.place_graph.edges?.length ?? 0} safe links</div>
			{/if}
			{#if navigationState.hasGraph}
				<label class="support-lateral-band">
					<input
						type="checkbox"
						checked={navigationState.buildGraphFromScratch ?? false}
						disabled={navigationState.buildingGraph}
						onchange={(event) => navigationActions.onSetBuildGraphFromScratch?.((event.currentTarget as HTMLInputElement).checked)}
					/>
					<span>Rebuild from scratch (discard manually added nodes/edges)</span>
				</label>
				{#if navigationState.buildGraphFromScratch}
					<p class="help warn">This drops every manually placed node/link and edit-history hint. The new sample will not reseed around them.</p>
				{/if}
			{/if}
			<button class={navigationState.buildGraphFromScratch ? "button button-danger" : "button button-subtle"} disabled={!navigationState.caps?.buildGraph?.enabled || navigationState.buildingGraph} title={navigationState.caps?.buildGraph?.reason} onclick={() => navigationActions.onRequestBuildGraph?.()}>
				{navigationState.buildingGraph ? 'Building Place Graph…' : navigationState.buildGraphFromScratch ? 'Rebuild Place Graph from scratch' : navigationState.hasGraph ? 'Rebuild Place Graph' : 'Build Place Graph'}
			</button>
		</InspectorSection>

		<InspectorSection title="Blueprint catalogue">
			<p class="help">Create a new all-Proposed review set from the current Place Graph. Manual nodes and repaired links stay in place; the existing catalogue is archived.</p>
			{#if confirmBlueprintRegenerate}
				<div class="clearance-pending">
					<p class="help warn">This replaces the current Blueprint statuses and invalidates any completed support plan. It does not rebuild the grid or erase manual graph edits.</p>
					<div class="action-row"><button class="button button-ghost" onclick={() => confirmBlueprintRegenerate = false}>Cancel</button><button class="button button-danger" disabled={navigationState.regeneratingBlueprints} onclick={() => { confirmBlueprintRegenerate = false; navigationActions.onRegenerateBlueprintCatalog?.(); }}>{navigationState.regeneratingBlueprints ? 'Regenerating…' : 'Regenerate blueprints'}</button></div>
				</div>
			{:else}
				<button class="button button-subtle" disabled={!navigationState.navigationSupport?.place_graph || navigationState.regeneratingBlueprints} onclick={() => confirmBlueprintRegenerate = true}>{navigationState.regeneratingBlueprints ? 'Regenerating…' : 'Regenerate blueprints'}</button>
			{/if}
		</InspectorSection>

		<InspectorSection title="Boundary repair">
			<p class="help">Repair disconnected safe areas directly on the canvas. The selected tool stays active until its pair is complete or you return to Select.</p>
			<div class="repair-tool-grid" aria-label="Boundary repair tools">
				<button class:active={navigationState.pathsMode === 'place_node'} class="button button-subtle" onclick={() => setRepairTool('place_node')}><MapPin size={15} /> Place node</button>
				<button class:active={navigationState.pathsMode === 'add_edge'} class="button button-subtle" onclick={() => setRepairTool('add_edge')}><Link2 size={15} /> Add link</button>
				<button class:active={navigationState.pathsMode === 'inspect_edge'} class="button button-subtle" onclick={() => setRepairTool('inspect_edge')}><ScanLine size={15} /> Inspect link</button>
				<button class:active={navigationState.pathsMode === 'remove_edge'} class="button button-subtle" onclick={() => setRepairTool('remove_edge')}><CircleX size={15} /> Remove link</button>
				<button class:active={navigationState.pathsMode === 'remove_node'} class="button button-subtle" onclick={() => setRepairTool('remove_node')}><Trash2 size={15} /> Remove nodes</button>
			</div>
			{#if repairToolHint()}
				<p class="mode-hint">{repairToolHint()}</p>
			{/if}
			{#if navigationState.pathsMode === 'place_node' && navigationState.placeNodeFeedback}
				<p class:ok={navigationState.placeNodeFeedback.tone === 'ok'} class:error={navigationState.placeNodeFeedback.tone === 'error'} class="node-placement-feedback" role="status" aria-live="polite">{navigationState.placeNodeFeedback.message}</p>
			{/if}
			{#if navigationState.pathsMode === 'remove_node'}
				<div class="remove-node-controls">
					<div class="form-grid"><label>Overlap margin (m)<input type="number" min="0" max="2" step="0.05" value={navigationState.removeMarginM} oninput={(event) => navigationActions.onSetRemoveMargin?.(Number((event.currentTarget as HTMLInputElement).value))} /></label><label>Pass-under height (m)<input type="number" min="0" max="3" step="0.1" value={navigationState.removePassHeightM} oninput={(event) => navigationActions.onSetRemovePassHeight?.(Number((event.currentTarget as HTMLInputElement).value))} /></label></div>
					<div class="action-row"><button class="button button-ghost" disabled={Boolean(navigationState.navigationSupport) || !navigationState.caps?.findOverlapping?.enabled || navigationState.findingOverlapping} onclick={() => navigationActions.onFindOverlapping?.()}>{navigationState.findingOverlapping ? 'Finding…' : 'Find overlapping'}</button><button class="button button-danger" disabled={!navigationState.removeSelectionCount || !navigationState.caps?.removeNodes?.enabled || navigationState.removingNodes} onclick={() => navigationActions.onRemoveSelectedNodes?.()}>{navigationState.removingNodes ? 'Removing…' : `Remove ${navigationState.removeSelectionCount ?? 0}`}</button><button class="button button-ghost" disabled={!navigationState.removeSelectionCount} onclick={() => navigationActions.onClearRemoveSelection?.()}>Clear</button></div>
				</div>
			{/if}
			{#if repairGuides.length}
				<div class="repair-guide-copy"><strong>{repairGuides.length} disconnected boundary {repairGuides.length === 1 ? 'guide' : 'guides'}</strong><span>Check the visible opening before creating any direct place link.</span></div>
				<div class="repair-guide-list">
					{#each repairGuides as guide (guide.guide_id)}
						<div class:active={navigationState.activePlaceRepairGuideId === guide.guide_id} class="repair-guide-row"><span><strong>Component {guide.component_index} · {guide.component_size} nodes</strong><small>{guide.main_node_id} ↔ {guide.detached_node_id} · {Number(guide.straight_line_distance_m).toFixed(2)} m</small></span><button class="button button-ghost" disabled={navigationState.edgeCheckPending} onclick={() => navigationActions.onInspectPlaceRepairGuide?.(guide)}>{navigationState.edgeCheckPending ? 'Checking…' : 'Show + check'}</button></div>
					{/each}
				</div>
			{/if}
			{#if edgeReviewQueue.length}
				<div class="edge-review-queue" aria-live="polite">
					<header><strong>Edge addition queue · {edgeReviewQueue.length}</strong><span>Review each candidate before it changes the graph.</span></header>
					{#each edgeReviewQueue as candidate (candidate.candidate_id)}
						<div class:ready={candidate.status === 'ready'} class:opening={candidate.status === 'opening_confirmation'} class:blocked={candidate.status === 'blocked'} class:submitting={candidate.status === 'submitting'} class="edge-review-queue-row">
							<div><strong>{candidate.source} ↔ {candidate.target}</strong><span>{edgeReviewMessage(candidate)}</span>{#if candidate.check?.manual_opening_eligible}<small>Wall cells {candidate.check?.wall_run_cells ?? 0} · raw gap {Number(candidate.check?.raw_gap_m ?? 0).toFixed(2)} m · hazard {candidate.check?.hazard_crossing ? 'yes' : 'no'}</small>{/if}</div>
							<div class="action-row">
								{#if candidate.status === 'ready'}<button class="button button-subtle" onclick={() => navigationActions.onConfirmEdgeReview?.(candidate.candidate_id)}>Confirm add</button>{/if}
								{#if candidate.status === 'opening_confirmation'}<button class="button button-subtle" onclick={() => navigationActions.onConfirmEdgeReview?.(candidate.candidate_id)}>Confirm opening</button>{/if}
								{#if candidate.status !== 'submitting'}<button class="button button-ghost" onclick={() => navigationActions.onCancelEdgeReview?.(candidate.candidate_id)}>{candidate.status === 'blocked' ? 'Dismiss' : 'Cancel'}</button>{/if}
							</div>
						</div>
					{/each}
				</div>
			{/if}
			{#if navigationState.edgeCheckResult}
				<div class:ok={navigationState.edgeCheckResult.would_connect} class="edge-review"><strong>{navigationState.edgeCheckResult.source} ↔ {navigationState.edgeCheckResult.target}</strong><span>{navigationState.edgeCheckResult.would_connect ? 'Collision check passed — direct link can be added.' : navigationState.edgeCheckResult.reason ?? 'Boundary requires review.'}</span>{#if navigationState.edgeCheckResult.reason === 'not_certified_doorway'}<div class="edge-metrics"><span>Wall cells <strong>{navigationState.edgeCheckResult.wall_run_cells ?? 0}</strong></span><span>Raw gap <strong>{Number(navigationState.edgeCheckResult.raw_gap_m ?? 0).toFixed(2)} m</strong></span><span>Hazard <strong>{navigationState.edgeCheckResult.hazard_crossing ? 'yes' : 'no'}</strong></span></div><p class:eligible={navigationState.edgeCheckResult.manual_opening_eligible} class="certification-hint">{openingCertificationHint(navigationState.edgeCheckResult)}</p>{/if}<div class="action-row"><button class="button button-subtle" disabled={!navigationState.edgeCheckResult.would_connect} onclick={() => navigationActions.onAddEdgeAnyway?.()}>Add direct link</button>{#if navigationState.edgeCheckResult.manual_opening_eligible}<button class="button button-ghost" onclick={() => navigationActions.onQueueOpeningCertification?.()}>Queue opening confirmation</button>{/if}<button class="button button-ghost" onclick={() => navigationActions.onDismissEdgeCheck?.()}>Dismiss</button></div></div>
			{/if}
		</InspectorSection>

		<details class="advanced" bind:open={advancedOpen}>
			<summary><Settings2 size={15} /> Advanced geometry tools <ChevronDown size={14} /></summary>
			<div class="advanced-body">
				<p class="help">Review destructive or legacy actions here. They never run automatically.</p>
				<button class="button button-subtle" disabled={!navigationState.hasScene || navigationState.navigationBlockersLoading} onclick={() => navigationActions.onScanNavigationBlockers?.()}>{navigationState.navigationBlockersLoading ? 'Scanning blockers…' : 'Scan large blockers'}</button>
				{#if navigationState.navigationBlockersScanned && navigationState.navigationBlockerCandidates?.length}
					<div class="compact-list">
						{#each navigationState.navigationBlockerCandidates as candidate (candidate.object_id)}
							<label><input type="checkbox" checked={navigationState.selectedNavigationBlockerIds?.has(String(candidate.object_id))} onchange={(event) => navigationActions.onToggleNavigationBlocker?.(String(candidate.object_id), (event.currentTarget as HTMLInputElement).checked)} /> <span>{candidate.label}</span><small>{candidate.footprint_area_m2} m²</small></label>
						{/each}
					</div>
					<button class="button button-danger" disabled={!navigationState.selectedNavigationBlockerIds?.size} onclick={() => navigationActions.onRemoveSelectedNavigationBlockers?.()}>Remove selected ({navigationState.selectedNavigationBlockerIds?.size ?? 0})</button>
				{/if}
				{#if !navigationState.navigationSupport}
					<button class="button button-subtle" disabled={!navigationState.caps?.rebuildEdges?.enabled || navigationState.rebuildingEdges} onclick={() => navigationActions.onRebuildEdges?.()}>{navigationState.rebuildingEdges ? 'Rebuilding legacy edges…' : 'Rebuild legacy graph edges'}</button>
				{/if}
			</div>
		</details>
	{/if}

	{#if tab === 'routes'}
		<InspectorSection title={`Route blueprints · ${blueprints.length}`}>
			<div class="route-filters">
				<label class="search"><Search size={15} /><input placeholder="Find route blueprint" bind:value={routeQuery} /></label>
				<select aria-label="Route status" bind:value={routeStatus}><option value="all">All states</option><option value="proposed">Proposed</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select>
			</div>
			<div class="node-find">
				<label class="search"><MapPin size={15} /><input placeholder="Find node (57 or vp_000057)" bind:value={nodeQuery} onkeydown={(event) => { if (event.key === 'Enter') findNode(); }} /></label>
				<button class="button button-subtle" disabled={!navigationState.hasGraph || !nodeQuery.trim()} onclick={findNode}>Find node</button>
			</div>
			{#if nodeFindMessage}<p class="node-find-message">{nodeFindMessage}</p>{/if}
			{#if navigationState.navigationSupport?.route_blueprints}
				<button class:active={navigationState.pathsMode === 'blueprint_pair'} class="button button-subtle route-create-canvas" onclick={startBlueprintPair}><CircleDotDashed size={16} /> {navigationState.pathsMode === 'blueprint_pair' ? 'Click start and goal places on the canvas' : 'Add route on canvas'}</button>
				<div class="collection" aria-label="Route blueprint collection">
					{#each filteredBlueprints as route (route.blueprint_id)}
						<div class:selected={navigationState.activeBlueprintId === route.blueprint_id} class:approved={route.status === 'approved'} class:proposed={route.status === 'proposed'} class:rejected={route.status === 'rejected'} class="collection-row">
							<button class="route-select" title={`${route.blueprint_id} · ${route.status}`} onclick={() => chooseRoute(route.blueprint_id)}><span class={`route-status ${route.status}`} aria-hidden="true"></span><strong>{route.blueprint_id}</strong><small>{route.start_anchor_id} → {route.goal_anchor_id}</small><em>{Number(route.place_path_distance_m ?? 0).toFixed(1)} m</em></button>
							<div class="route-toggles" aria-label={`Review ${route.blueprint_id}`}>
								<button class:active={route.status === 'approved'} class="icon-button approve" aria-label={`Approve ${route.blueprint_id}`} aria-pressed={route.status === 'approved'} title="Approve" onclick={() => setRouteStatus(route.blueprint_id, 'approved', route.status)}><CircleCheck size={16} /></button>
								<button class:active={route.status === 'rejected'} class="icon-button reject" aria-label={`Reject ${route.blueprint_id}`} aria-pressed={route.status === 'rejected'} title="Reject" onclick={() => setRouteStatus(route.blueprint_id, 'rejected', route.status)}><CircleX size={16} /></button>
								<button class="icon-button delete" aria-label={`Delete ${route.blueprint_id}`} title="Delete" onclick={() => navigationActions.onDeleteBlueprint?.(route.blueprint_id)}><Trash2 size={15} /></button>
							</div>
						</div>
					{/each}
					{#if filteredBlueprints.length === 0}<p class="empty">No route blueprints match this filter.</p>{/if}
				</div>
			{:else}<p class="empty">Build a Place Graph to create reviewable routes.</p>{/if}
		</InspectorSection>
		{#if selectedBlueprint}
			<InspectorSection title="Selected route">
				<div class="selected-route"><Route size={17} /><div><strong>{selectedBlueprint.blueprint_id}</strong><span>{selectedBlueprint.start_anchor_id} → {selectedBlueprint.goal_anchor_id} · {Number(selectedBlueprint.place_path_distance_m ?? 0).toFixed(1)} m</span></div></div>
				<p class="help">Selecting a route highlights its place-graph path in the canvas. Approval is intentionally in the overflow action so the review pass remains concise.</p>
			</InspectorSection>
		{/if}
	{/if}

	{#if tab === 'support'}
		<InspectorSection title="Sweep coverage ladder">
			<p class="help">Each rung selects a growing subset of the same certified L0 plan and contains the rung below it, so a sweep resumes upward without re-rendering. Prepare a rung, then render it.</p>
			<div class="coverage-ladder">
				{#each navigationState.supportCoverageLevels ?? [] as level (level.level_id)}
					{@const active = level.level_id === navigationState.supportCoverageLevelId}
					{@const views = Number(level.summary?.selected_view_count ?? 0)}
					{@const hours = Number(level.summary?.gpu_time_estimate_hours_per_polar_camera_variant ?? 0)}
					{@const share = Number(level.summary?.selected_fraction ?? 0)}
					<div class:active class:ready={level.current} class="coverage-rung">
						<button class="rung-pick" onclick={() => navigationActions.onSetSupportCoverageLevel?.(level.level_id)}>
							<strong>{level.label ?? level.level_id}</strong>
							{#if level.current}
								<span>{views.toLocaleString()} views · {(share * 100).toFixed(0)}% of L0 · {hours.toFixed(1)} GPU h</span>
							{:else if level.stale_reason === 'episodes_changed'}
								<span class="warn">Stale — episodes changed since this was prepared. Prepare again.</span>
							{:else if level.stale_reason === 'support_rebuilt'}
								<span class="warn">Stale — support graph was rebuilt. Prepare again.</span>
							{:else}
								<span class="muted">budget unknown until prepared</span>
							{/if}
						</button>
						<div class="rung-actions">
							{#if level.current}
								<span class="rung-state">Ready</span>
							{:else if level.prepared}
								<button class="button button-ghost" disabled={navigationState.supportCoveragePreparing || !supportReady} onclick={() => navigationActions.onPrepareSupportCoverageLevel?.(level.level_id)}>{navigationState.supportCoveragePreparing ? 'Preparing…' : 'Re-prepare'}</button>
							{:else}
								<button class="button button-ghost" disabled={navigationState.supportCoveragePreparing || !supportReady} onclick={() => navigationActions.onPrepareSupportCoverageLevel?.(level.level_id)}>{navigationState.supportCoveragePreparing ? 'Preparing…' : 'Prepare'}</button>
							{/if}
							<button class="button button-subtle" disabled={!level.current || navigationState.sweepSubmissionInFlight} onclick={() => { navigationActions.onSetSupportCoverageLevel?.(level.level_id); confirmRenderSubmit = true; }}>Render</button>
						</div>
					</div>
				{:else}
					<p class="help">Build Navigation Support to see the coverage ladder.</p>
				{/each}
			</div>
		</InspectorSection>

		<InspectorSection title="Coverage workflow">
			<label class="support-algorithm">
				<span>Support network algorithm</span>
				<select
					value={supportAlgorithm}
					disabled={supportActionBusy}
					onchange={(event) => navigationActions.onSetSupportAlgorithm?.((event.currentTarget as HTMLSelectElement).value)}
				>
					<option value="global_executable_network_v2">Global executable v2 · Experimental</option>
					<option value="production_v1">Production v1 · Current</option>
				</select>
			</label>
			<div class:experimental={supportAlgorithm === 'global_executable_network_v2'} class="algorithm-note">
				<strong>{supportAlgorithm === 'global_executable_network_v2' ? 'Raw → consolidate → stitch' : 'Current production normalizer'}</strong>
				<span>Active artifact: {activeSupportAlgorithm === 'global_executable_network_v2' ? 'Global executable v2' : 'Production v1'}. Analyze and Build always use the selected algorithm together.</span>
			</div>
			<label class="support-lateral-band">
				<input
					type="checkbox"
					checked={navigationState.supportLateralBand ?? true}
					disabled={supportActionBusy}
					onchange={(event) => navigationActions.onSetSupportLateralBand?.((event.currentTarget as HTMLInputElement).checked)}
				/>
				<span>Lateral band (one side lane per side of a blueprint's straight runs)</span>
			</label>
			{#if navigationState.supportLateralBand ?? true}
				<label class="field">Switch interval (support poses between side-lane switches)<input
					type="number" min="1"
					value={navigationState.supportLateralSwitchInterval ?? 3}
					disabled={supportActionBusy}
					oninput={(event) => navigationActions.onSetSupportLateralSwitchInterval?.(Number((event.currentTarget as HTMLInputElement).value))}
				/></label>
			{/if}
			<div class="metric-grid"><MetricCard label="Approved routes" value={approvedCount} tone={approvedCount ? 'success' : 'warning'} /><MetricCard label="Support poses" value={analysisSummary?.support_pose_count ?? navigationState.navigationSupport?.observation_plan?.summary?.support_pose_count ?? '—'} /><MetricCard label="Native views" value={analysisSummary?.polar_observation_count ?? navigationState.navigationSupport?.observation_plan?.summary?.polar_observation_count ?? '—'} /><MetricCard label="Lateral poses" value={analysisSummary?.lateral_pose_count ?? navigationState.navigationSupport?.observation_plan?.summary?.lateral_pose_count ?? '—'} /></div>
			<p class="help">Manually added place edges are always included in the executable trunk, whether or not they belong to an approved route.</p>
			<div class="action-row support-workflow-actions">
				<button class="button button-subtle" disabled={!canAnalyzeSupport} onclick={() => navigationActions.onAnalyzeSupportGraph?.()}>{supportActionBusy ? 'Working…' : supportAnalysisReady ? 'Re-analyze support' : 'Analyze support'}</button>
				<button class="button button-primary" disabled={!canBuildSupport} title={supportAnalysisReady ? 'Materialize the current successful analysis.' : 'Run Analyze support successfully before building.'} onclick={() => navigationActions.onBuildSupportGraph?.()}>Build Navigation Support</button>
			</div>
			{#if !supportAnalysisReady && !navigationState.supportAnalysisStale && !supportBlocker}
				<p class="help">Analyze validates the currently approved routes. Build becomes available only for that successful, current analysis.</p>
			{/if}
			{#if navigationState.supportAnalysisStale}<div class="analysis-stale"><strong>Review edits staged</strong><span>The blocker list remains visible for batch review. Re-analyze once after your last approve / propose / reject change.</span><button class="button button-subtle" onclick={() => navigationActions.onAnalyzeSupportGraph?.()}>Re-analyze once</button></div>{/if}
			{#if analysisSummary}<p class="help">Analysis estimates {analysisSummary.polar_batch_count ?? '—'} K=4 polar batches before building the immutable support plan.</p>{:else if supportBlocker}
				<div class="support-blocker" role="alert">
					<strong>Support build blocked</strong>
					<span>{supportBlocker.message ?? supportBlocker.error ?? 'Analysis found a blocked corridor. Repair or unapprove the listed route before building.'}</span>
					{#if supportBlocker.complete === false}<small class="warning">The scan stopped at a global precondition; resolve it before treating this as a complete blocker list.</small>{/if}
					{#each blockerGroups as group, index (`${group.id ?? group.kind ?? 'blocker'}:${index}`)}
						<div class="support-blocker-group">
							<header><strong>{blockerGroupLabel(group)}</strong><span>Group {index + 1}</span></header>
							{#if group.blueprint_id}<small>Route blueprint · <code>{group.blueprint_id}</code></small>{/if}
							{#if group.place_edge_id}<small>Place link · <code>{group.place_edge_id}</code>{#if group.source && group.target} · {group.source} ↔ {group.target}{/if}</small>{/if}
							{#if group.blueprint_id && group.source && group.target}<small>Reviewed route · {group.source} → {group.target} · {group.place_edge_ids?.length ?? 0} certified place edge{group.place_edge_ids?.length === 1 ? '' : 's'}</small>{/if}
							{#if group.distance_m != null}<small>Certified place-edge length · {Number(group.distance_m).toFixed(2)} m{#if group.collision_free != null} · collision certificate: {group.collision_free ? 'present' : 'missing'}{/if}</small>{/if}
							{#if group.structural_backbone}<div class="structural-blocker"><strong>{group.ownership === 'automatic_coverage_backbone' ? 'Automatic coverage backbone' : 'Structural backbone connector'}</strong><span>This edge has no route-blueprint owner. Repair the Place Graph corridor; do not unapprove unrelated routes.</span></div>{/if}
							{#if group.portal_id}<small>Portal · <code>{group.portal_id}</code></small>{/if}
							<p>{group.message ?? group.error}</p>
							{#if group.source && group.target}<div class="action-row"><button class="button button-subtle" onclick={() => navigationActions.onInspectSupportBlocker?.(group)}>{group.blueprint_id ? 'Inspect approved route' : 'Inspect corridor on canvas'}</button><button class="button button-ghost" onclick={() => navigationActions.onFindGraphNode?.(String(group.source))}>{group.blueprint_id ? 'Find route start' : 'Find source'}</button><button class="button button-ghost" onclick={() => navigationActions.onFindGraphNode?.(String(group.target))}>{group.blueprint_id ? 'Find route goal' : 'Find target'}</button></div>{/if}
							{#if group.blocked_blueprint_ids?.length}
								<div class="blocked-blueprints"><span>Dependent approved routes:</span>{#each group.blocked_blueprint_ids as blueprintId}<button class="button button-ghost" onclick={() => reviewBlockingRoute(String(blueprintId))}>{blueprintId}</button>{/each}</div>
								<button class="button button-subtle" onclick={() => navigationActions.onReturnBlockedBlueprintsToReview?.(group.blocked_blueprint_ids.map(String))}>Return this group to Proposed</button>
							{/if}
						</div>
					{/each}
					<div class="action-row"><button class="button button-subtle" onclick={reviewBlockingRoutes}>Review {blockedBlueprintIds.length || 'the'} blocker{blockedBlueprintIds.length === 1 ? '' : 's'}</button>{#if blockedBlueprintIds.length}<button class="button button-danger" onclick={() => navigationActions.onReturnBlockedBlueprintsToReview?.(blockedBlueprintIds)}>Return all {blockedBlueprintIds.length} to Proposed</button>{/if}</div>
				</div>
			{:else}<p class="help">Approve a route, then analyze its pose and native-view coverage.</p>{/if}
			{#if supportReady}<div class="inline-summary"><Check size={15} /> Navigation Support is built and ready to render.</div>{/if}
		</InspectorSection>
	{/if}

	{#if tab === 'episodes'}
		<InspectorSection title="Episode split">
			<div class="metric-grid"><MetricCard label="Train" value={episodeState.splitCounts?.train ?? 0} /><MetricCard label="Val seen" value={episodeState.splitCounts?.val_seen ?? 0} /><MetricCard label="Val unseen" value={episodeState.splitCounts?.val_unseen ?? 0} /></div>
			<label class="field">Route scope
				<select
					value={episodeState.episodeRouteScope ?? 'blueprint'}
					disabled={episodeGenerationBusy}
					onchange={(event) => navigationActions.onSetEpisodeRouteScope?.((event.currentTarget as HTMLSelectElement).value)}
				>
					<option value="blueprint">Blueprint corridor only</option>
					<option value="blueprint_band">Blueprint corridor + lateral band</option>
					<option value="global">Global (whole executable graph)</option>
				</select>
			</label>
			<label class="field">Minimum episode length (m)<input
				type="number" min="0" step="0.5"
				value={episodeState.episodeMinDistanceM ?? 5}
				disabled={episodeGenerationBusy}
				oninput={(event) => navigationActions.onSetEpisodeMinDistanceM?.(Number((event.currentTarget as HTMLInputElement).value))}
			/></label>
			<p class="help">Exact travelled distance (sum of each move_forward transition's own length), not an estimate from action count. 0 disables the floor.</p>
			<label class="field">Max detour ratio<input
				type="number" min="0" step="0.1"
				value={episodeState.episodeMaxDetourRatio ?? 1.5}
				disabled={episodeGenerationBusy}
				oninput={(event) => navigationActions.onSetEpisodeMaxDetourRatio?.(Number((event.currentTarget as HTMLInputElement).value))}
			/></label>
			<p class="help">Drops an episode that walks more than this multiple of the free-space shortest path — the sign that the graph never materialised its direct route. 0 disables it.</p>
			<label class="field">Episode pairs this operation<input type="number" min="1" value={episodeState.episodeCount} disabled={episodeGenerationBusy} oninput={(event) => navigationActions.onSetEpisodeCount?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
			<div class="action-row">
				<button class="button button-subtle" disabled={episodeGenerationBusy || (Boolean(navigationState.navigationSupport) && !supportReady)} onclick={() => generateEpisodes("append")}>{episodeGenerationBusy ? `Generating ${episodeState.episodePlanProgress?.planned ?? 0}/${episodeState.episodePlanProgress?.target ?? episodeState.episodeCount}` : `Add ${episodeState.episodeCount} episodes`}</button>
				<button class="button button-danger" disabled={episodeGenerationBusy || (Boolean(navigationState.navigationSupport) && !supportReady)} onclick={() => confirmEpisodeReplace = true}>Generate new {episodeState.episodeCount} episodes</button>
				<button class="button button-ghost" disabled={episodeGenerationBusy} aria-expanded={episodeBrowserOpen} onclick={() => episodeBrowserOpen = !episodeBrowserOpen}><FileStack size={16} /> {episodeBrowserOpen ? "Hide browse" : `Browse ${episodeState.total ?? episodeState.episodes?.length ?? 0}`}</button>
			</div>
			{#if confirmEpisodeReplace}
				<div class="episode-replace-confirm" role="alert">
					<strong>Replace {episodeState.total ?? episodeState.episodes?.length ?? 0} current scene episode(s)?</strong>
					<span>Only episode manifests are replaced. Observations, rendered outputs, and render ledger entries remain.</span>
					<div class="action-row"><button class="button button-ghost" onclick={() => confirmEpisodeReplace = false}>Cancel</button><button class="button button-danger" onclick={() => { confirmEpisodeReplace = false; generateEpisodes("replace_scene"); }}>Replace with {episodeState.episodeCount} new episodes</button></div>
				</div>
			{/if}
			{#if episodeState.staleEpisodeReport}<p class:warn={(episodeState.staleEpisodeReport.stale_count ?? 0) > 0} class="help">{episodeState.staleEpisodeReport.stale_count ?? 0} stale of {episodeState.staleEpisodeReport.checked ?? 0} checked.</p>{/if}
			<div class="action-row"><button class="button button-ghost" disabled={!episodeState.episodes?.length || episodeState.validatingEpisodes} onclick={() => navigationActions.onValidateEpisodes?.()}>{episodeState.validatingEpisodes ? 'Validating…' : 'Validate graph references'}</button>{#if (episodeState.staleEpisodeReport?.stale_count ?? 0) > 0}<button class="button button-danger" onclick={() => navigationActions.onPruneStaleEpisodes?.()}>Remove stale</button>{/if}</div>
			{#if episodeBrowserOpen}
				<div class="episode-browser" aria-label="Browse navigation episodes">
					<header><div><p>Browse episodes</p><strong>{episodeState.total ?? episodeState.episodes?.length ?? 0} in this scene</strong></div><span>Scroll to compare</span></header>
					<label class="search"><Search size={15} /><input placeholder="Find episode" value={episodeState.episodeSearch} oninput={(event) => navigationActions.onSetEpisodeSearch?.((event.currentTarget as HTMLInputElement).value)} /></label>
					<div class="episode-browser-list">{#each episodeState.filteredEpisodes ?? [] as episode (episode.episode_id)}<button class:selected={episodeState.selectedEpisodeId === episode.episode_id} onclick={() => chooseEpisode(episode.episode_id)}><span><strong>{episode.episode_id}</strong><small>{episode.split ?? 'unsplit'} · {episode.navigation_mode ?? 'trajectory'}</small><small class="episode-metrics">{episode.distinct_node_count ?? episode.path_length ?? '—'} nodes · {typeof episode.path_distance_m === 'number' ? `${episode.path_distance_m.toFixed(2)} m` : '— m'}{#if typeof episode.path_distance_m === 'number' && episode.path_distance_m < 5}<em class="short"> under 5 m</em>{/if}</small></span>{#if episode.hazard_collision}<span class="warning">Hazard</span>{/if}</button>{:else}<p class="empty">No episodes for this scene.</p>{/each}</div>
					{#if episodeState.nextCursor}<button class="button button-subtle" onclick={() => navigationActions.onLoadMoreEpisodes?.()}>Load next 100</button>{/if}
				</div>
			{/if}
		</InspectorSection>
	{/if}

	<footer class="sticky-action">
		{#if confirmRenderSubmit}
			{@const rung = navigationState.supportCoverageLevel}
			{@const views = Number(rung?.summary?.selected_view_count ?? navigationState.navigationSupport?.observation_plan?.summary?.polar_observation_count ?? 0)}
			{@const hours = Number(rung?.summary?.gpu_time_estimate_hours_per_polar_camera_variant ?? navigationState.navigationSupport?.observation_plan?.summary?.gpu_time_estimate_hours_per_polar_camera_variant ?? 0)}
			<div class="submit-confirm">
				<strong>Submit {views.toLocaleString()} views for rendering?</strong>
				{#if rung?.current}
					<span>Coverage level <strong>{rung.label ?? rung.level_id}</strong> · about {hours.toFixed(1)} GPU hours per polar camera variant.</span>
				{:else}
					<span class="warn">No coverage level is prepared, so this submits the <strong>complete L0 plan</strong> — about {hours.toFixed(1)} GPU hours per polar camera variant. Prepare a level in Support to render a subset instead.</span>
				{/if}
				<div class="action-row">
					<button class="button button-ghost" onclick={() => confirmRenderSubmit = false}>Cancel</button>
					<button class="button button-danger" onclick={() => { confirmRenderSubmit = false; navigationActions.onRenderNavigationSupport?.(); }}>Submit render</button>
				</div>
			</div>
		{:else}
			<div><strong>{primary.label}</strong><span>{primary.description}</span></div>
			<button class="button button-primary" disabled={primary.disabled} onclick={runPrimary}>{primary.label}</button>
		{/if}
	</footer>
</div>

<style>
	.coverage-rung .warn { color: var(--warning, #b45309); }

	.coverage-ladder { display: flex; flex-direction: column; gap: 6px; }
	.coverage-rung { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border: 1px solid var(--border, #e5e7eb); border-radius: 8px; }
	.coverage-rung.active { border-color: var(--accent, #2563eb); }
	.coverage-rung.ready .rung-state { color: var(--success, #15803d); font-weight: 600; }
	.rung-pick { flex: 1; display: flex; flex-direction: column; align-items: flex-start; gap: 2px; background: none; border: 0; padding: 0; text-align: left; cursor: pointer; }
	.rung-pick span { font-size: 0.85em; color: var(--text-muted, #6b7280); font-variant-numeric: tabular-nums; }
	.rung-actions { display: flex; align-items: center; gap: 6px; }

	.submit-confirm { display: flex; flex-direction: column; gap: 8px; width: 100%; }
	.submit-confirm .warn { color: var(--warning, #b45309); }

	.episode-metrics { color: var(--text-muted, #6b7280); font-variant-numeric: tabular-nums; }
	.episode-metrics .short { color: var(--warning, #b45309); font-style: normal; font-weight: 600; }

	.paths-inspector { display: grid; min-width: 0; gap: 0; padding: 0 var(--space-4) 5.75rem; overflow-x: hidden; }
	.inspector-heading { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-4) 0 var(--space-3); } .inspector-heading > div:first-child { min-width: 0; }
	p { margin: 0; } .inspector-heading p, .episode-browser p { color: var(--muted); font-size: var(--font-size-2xs); font-weight: var(--font-weight-bold); letter-spacing: var(--letter-spacing-wide); text-transform: uppercase; } h2 { margin: 3px 0 0; color: var(--text); font-size: var(--font-size-lg); }
	.inspector-status { display: flex; min-width: 0; flex: 0 1 auto; align-items: center; justify-content: flex-end; gap: 6px; } .operation-status { display: grid; grid-template-columns: minmax(0, 1fr) auto; min-width: 0; max-width: 11rem; gap: 5px; align-items: center; padding: 4px 7px; border-radius: var(--radius-pill); background: var(--brand-container); color: var(--brand-strong); font-size: var(--font-size-2xs); font-weight: var(--font-weight-semibold); } .operation-status span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .operation-status strong { font-size: inherit; font-variant-numeric: tabular-nums; }
	.state-chip { flex: 0 0 auto; padding: 4px 8px; border-radius: var(--radius-pill); background: var(--warning-container); color: var(--warning-strong); font-size: var(--font-size-2xs); font-weight: var(--font-weight-bold); } .state-chip.ready { background: var(--success-container); color: var(--success-strong); }
	.form-grid, .metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); } .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
	label.field, .form-grid label { display: grid; min-width: 0; gap: 5px; color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); } input, select { width: 100%; min-width: 0; box-sizing: border-box; min-height: 2.25rem; padding: 0 8px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--panel); color: var(--text); }
	.help { color: var(--muted-strong); font-size: var(--font-size-xs); line-height: 1.45; } .help.warn, .warning { color: var(--warning-strong); } .clearance-pending { display: grid; gap: 7px; padding: 8px; border: 1px solid var(--warning); border-radius: var(--radius-sm); background: var(--warning-container); } .clearance-pending .help { margin: 0; }
	.analysis-stale { display: grid; gap: 5px; margin-top: var(--space-2); padding: 9px; border: 1px solid var(--brand); border-radius: var(--radius-sm); background: var(--brand-container); color: var(--brand-strong); font-size: var(--font-size-xs); line-height: 1.4; } .analysis-stale span { color: var(--muted-strong); } .analysis-stale .button { justify-self: start; min-height: 1.85rem; padding: 3px 7px; font-size: var(--font-size-2xs); } .support-blocker { display: grid; gap: 7px; padding: 10px; border: 1px solid var(--warning); border-radius: var(--radius-sm); background: var(--warning-container); color: var(--muted-strong); font-size: var(--font-size-xs); line-height: 1.4; } .support-blocker > strong { color: var(--warning-strong); } .support-blocker small { color: var(--muted-strong); } .support-blocker code { overflow-wrap: anywhere; font-size: var(--font-size-2xs); } .support-blocker-group { display: grid; min-width: 0; gap: 6px; padding: 8px; border: 1px solid color-mix(in srgb, var(--warning) 55%, var(--panel-border)); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--panel) 68%, transparent); } .support-blocker-group header { display: flex; min-width: 0; align-items: baseline; justify-content: space-between; gap: 8px; } .support-blocker-group header strong { min-width: 0; color: var(--text); font-size: var(--font-size-xs); } .support-blocker-group header span { flex: 0 0 auto; color: var(--muted); font-size: var(--font-size-2xs); } .support-blocker-group p { margin: 0; color: var(--muted-strong); } .blocked-blueprints { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 5px; } .blocked-blueprints > span { color: var(--muted-strong); } .blocked-blueprints .button { min-height: 1.75rem; padding: 3px 6px; font-size: var(--font-size-2xs); }
	.support-algorithm { display: grid; min-width: 0; gap: 5px; color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); } .support-algorithm select { min-width: 0; width: 100%; }
	.support-lateral-band { display: flex; align-items: center; gap: 7px; color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); } .support-lateral-band input { width: auto; min-height: 0; }
	.algorithm-note { display: grid; min-width: 0; gap: 3px; padding: 8px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-2); color: var(--muted-strong); font-size: var(--font-size-2xs); line-height: 1.4; } .algorithm-note strong { color: var(--text); font-size: var(--font-size-xs); } .algorithm-note span { overflow-wrap: anywhere; } .algorithm-note.experimental { border-color: color-mix(in srgb, var(--brand) 45%, var(--panel-border)); background: var(--brand-container); }
	.inline-summary { display: flex; align-items: center; gap: 6px; color: var(--success-strong); font-size: var(--font-size-xs); } .progress-row { display: grid; gap: 6px; color: var(--muted-strong); font-size: var(--font-size-xs); }
	.advanced { border-bottom: 1px solid var(--panel-border); padding: var(--space-3) 0; } .advanced summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--muted-strong); cursor: pointer; font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); list-style: none; } .advanced summary::-webkit-details-marker { display: none; } .advanced-body { display: grid; gap: var(--space-2); padding-top: var(--space-3); }
	.repair-tool-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); } .repair-tool-grid button { display: inline-flex; min-width: 0; align-items: center; justify-content: center; gap: 5px; font-size: var(--font-size-xs); white-space: nowrap; } .repair-tool-grid button:last-child { grid-column: 1 / -1; } .repair-tool-grid button.active { border-color: var(--brand); background: var(--brand-container); color: var(--brand-strong); } .mode-hint { padding: 8px; border-radius: var(--radius-sm); background: var(--brand-container); color: var(--brand-strong); font-size: var(--font-size-xs); line-height: 1.4; } .node-placement-feedback { padding: 8px; border: 1px solid var(--warning); border-radius: var(--radius-sm); background: var(--warning-container); color: var(--warning-strong); font-size: var(--font-size-xs); line-height: 1.4; } .node-placement-feedback.ok { border-color: var(--success); background: var(--success-container); color: var(--success-strong); } .node-placement-feedback.error { border-color: var(--danger); background: var(--danger-container); color: var(--danger-strong); } .remove-node-controls { display: grid; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-2); } .repair-guide-copy { display: grid; gap: 2px; color: var(--muted-strong); font-size: var(--font-size-xs); } .repair-guide-list { display: grid; gap: var(--space-2); } .repair-guide-row { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: var(--space-2); padding: 8px; border: 1px solid var(--warning); border-radius: var(--radius-sm); background: var(--warning-container); } .repair-guide-row.active { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand-container); } .repair-guide-row > span { display: grid; min-width: 0; gap: 2px; } .repair-guide-row strong, .repair-guide-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .repair-guide-row strong { color: var(--text); font-size: var(--font-size-xs); } .repair-guide-row small { color: var(--muted-strong); font-size: var(--font-size-2xs); } .repair-guide-row button { flex: 0 0 auto; } .edge-review { display: grid; gap: 5px; padding: 9px; border: 1px solid var(--warning); border-radius: var(--radius-sm); background: var(--warning-container); color: var(--muted-strong); font-size: var(--font-size-xs); } .edge-review.ok { border-color: var(--success); background: var(--success-container); } .edge-metrics { display: flex; flex-wrap: wrap; gap: 4px; } .edge-metrics span { padding: 3px 5px; border-radius: 4px; background: color-mix(in srgb, var(--panel) 60%, transparent); font-size: var(--font-size-2xs); } .certification-hint { color: var(--warning-strong); font-size: var(--font-size-xs); line-height: 1.4; } .certification-hint.eligible { color: var(--success-strong); }
	.compact-list { display: grid; max-height: 11rem; overflow-y: auto; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); } .compact-list label { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 7px; align-items: center; padding: 7px; border-bottom: 1px solid var(--panel-border); font-size: var(--font-size-xs); } .compact-list label:last-child { border-bottom: 0; } .compact-list span, .compact-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.edge-result { display: grid; gap: 6px; padding: 9px; border-radius: var(--radius-sm); background: var(--surface-2); color: var(--muted-strong); font-size: var(--font-size-xs); } .edge-review-queue { display: grid; gap: 7px; padding: 9px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-2); } .edge-review-queue > header { display: grid; gap: 2px; } .edge-review-queue > header strong { color: var(--text); font-size: var(--font-size-xs); } .edge-review-queue > header span { color: var(--muted-strong); font-size: var(--font-size-2xs); } .edge-review-queue-row { display: grid; gap: 7px; padding: 8px; border: 1px solid var(--panel-border); border-left: 3px solid var(--muted); border-radius: var(--radius-sm); background: var(--panel); } .edge-review-queue-row > div:first-child { display: grid; min-width: 0; gap: 3px; } .edge-review-queue-row strong, .edge-review-queue-row span, .edge-review-queue-row small { overflow-wrap: anywhere; } .edge-review-queue-row strong { color: var(--text); font-size: var(--font-size-xs); } .edge-review-queue-row span, .edge-review-queue-row small { color: var(--muted-strong); font-size: var(--font-size-2xs); line-height: 1.35; } .edge-review-queue-row.ready { border-left-color: var(--success); } .edge-review-queue-row.opening { border-left-color: var(--warning); background: var(--warning-container); } .edge-review-queue-row.blocked { border-left-color: var(--danger); background: var(--danger-container); } .edge-review-queue-row.submitting { border-left-color: var(--brand); background: var(--brand-container); }
	.route-filters { display: grid; grid-template-columns: minmax(0, 1fr) 7.5rem; gap: var(--space-2); } .route-create-canvas { display: inline-flex; width: 100%; align-items: center; justify-content: center; gap: 6px; } .route-create-canvas.active { border-color: var(--brand); background: var(--brand-container); color: var(--brand-strong); }
	.search { display: flex; align-items: center; min-width: 0; gap: 6px; padding: 0 8px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); color: var(--muted); } .search input { border: 0; padding: 0; }
	.collection { display: grid; max-height: 18rem; overflow-y: auto; border: 1px solid var(--panel-border); border-radius: var(--radius-md); } .collection-row { display: flex; min-width: 0; align-items: center; border-bottom: 1px solid var(--panel-border); border-left: 3px solid var(--panel-border); } .collection-row:last-child { border-bottom: 0; } .collection-row.approved { border-left-color: var(--success); background: color-mix(in srgb, var(--success-container) 52%, transparent); } .collection-row.proposed { border-left-color: var(--warning); background: color-mix(in srgb, var(--warning-container) 42%, transparent); } .collection-row.rejected { border-left-color: var(--danger); opacity: .68; } .collection-row.selected { background: var(--brand-container); box-shadow: inset 3px 0 0 var(--brand); } .route-select { display: grid; grid-template-columns: auto auto minmax(0, 1fr) auto; flex: 1; min-width: 0; gap: 6px; align-items: center; padding: 7px 5px 7px 6px; border: 0; background: transparent; color: var(--text); text-align: left; cursor: pointer; line-height: 1.15; } .route-select strong, .route-select small, .route-select em { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .route-select strong { font-size: var(--font-size-xs); } .route-select small, .route-select em { color: var(--muted); font-size: 10px; font-style: normal; } .route-status { width: 8px; height: 8px; border-radius: 50%; box-shadow: 0 0 0 2px var(--panel); background: var(--muted); } .route-status.approved { background: var(--success); } .route-status.proposed { background: var(--warning); } .route-status.rejected { background: var(--danger); }
	.route-toggles { display: flex; flex: 0 0 auto; align-items: center; gap: 1px; padding-right: 4px; } .icon-button { display: grid; width: 1.75rem; height: 1.75rem; place-items: center; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--muted-strong); cursor: pointer; } .icon-button:hover { background: var(--hover-bg); } .icon-button.approve.active { background: var(--success-container); color: var(--success-strong); } .icon-button.reject.active { background: var(--danger-container); color: var(--danger-strong); } .icon-button.delete:hover { color: var(--danger-strong); }
	.selected-route { display: flex; min-width: 0; gap: 8px; padding: 10px; border-radius: var(--radius-sm); background: var(--brand-container); color: var(--brand-strong); } .selected-route > div { display: grid; min-width: 0; gap: 2px; } .selected-route span { overflow: hidden; color: var(--muted-strong); font-size: var(--font-size-xs); text-overflow: ellipsis; white-space: nowrap; }
	.action-row { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; } .action-row button { display: inline-flex; align-items: center; gap: 6px; }
	.sticky-action { position: sticky; z-index: 10; bottom: 0; display: flex; gap: var(--space-2); align-items: center; justify-content: space-between; margin: var(--space-3) calc(-1 * var(--space-4)) 0; padding: 12px var(--space-4); border-top: 1px solid var(--panel-border); background: color-mix(in srgb, var(--panel) 94%, transparent); box-shadow: 0 -8px 20px color-mix(in srgb, var(--panel) 86%, transparent); backdrop-filter: blur(12px); } .sticky-action > div { display: grid; min-width: 0; gap: 2px; } .sticky-action strong { font-size: var(--font-size-sm); } .sticky-action span { overflow: hidden; color: var(--muted); font-size: var(--font-size-2xs); text-overflow: ellipsis; white-space: nowrap; } .sticky-action button { flex: 0 0 auto; }
	.empty { padding: var(--space-3); color: var(--muted); font-size: var(--font-size-xs); text-align: center; }
	.episode-replace-confirm { display: grid; min-width: 0; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--danger); border-radius: var(--radius-sm); background: var(--danger-container); color: var(--muted-strong); font-size: var(--font-size-xs); line-height: 1.4; } .episode-replace-confirm strong { color: var(--danger-strong); } .episode-browser { display: grid; min-width: 0; gap: var(--space-2); margin-top: var(--space-3); padding: var(--space-3); border: 1px solid var(--panel-border); border-radius: var(--radius-md); background: var(--surface-2); } .episode-browser header { display: flex; align-items: start; justify-content: space-between; gap: var(--space-2); } .episode-browser header > div { display: grid; gap: 2px; min-width: 0; } .episode-browser header strong { color: var(--text); font-size: var(--font-size-sm); } .episode-browser header > span { flex: 0 0 auto; color: var(--muted); font-size: var(--font-size-2xs); } .episode-browser-list { display: grid; align-content: start; max-height: min(22rem, 42dvh); overflow-y: auto; overflow-x: hidden; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--panel); } .episode-browser-list button { display: flex; min-width: 0; justify-content: space-between; gap: 8px; padding: 9px; border: 0; border-bottom: 1px solid var(--panel-border); background: transparent; color: var(--text); text-align: left; cursor: pointer; } .episode-browser-list button:last-child { border-bottom: 0; } .episode-browser-list button.selected { background: var(--brand-container); } .episode-browser-list button > span:first-child { display: grid; min-width: 0; gap: 2px; } .episode-browser-list strong, .episode-browser-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .episode-browser-list small { color: var(--muted); font-size: var(--font-size-2xs); }
	.blocker-overview { display: grid; gap: 4px; margin: var(--space-3) 0 0; padding: 8px; border: 1px solid var(--warning); border-radius: var(--radius-sm); background: var(--warning-container); } .blocker-overview header { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--warning-strong); font-size: var(--font-size-xs); } .blocker-overview header .button { min-height: 1.75rem; padding: 3px 6px; font-size: var(--font-size-2xs); } .blocker-overview-row { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: 6px; row-gap: 1px; width: 100%; padding: 5px; border: 0; border-radius: 5px; background: color-mix(in srgb, var(--panel) 68%, transparent); color: var(--text); text-align: left; cursor: pointer; } .blocker-overview-row:hover { background: var(--panel); } .blocker-overview-row > span { grid-row: span 2; display: grid; width: 1.25rem; height: 1.25rem; place-items: center; border-radius: 50%; background: var(--warning); color: var(--panel); font-size: var(--font-size-2xs); font-weight: var(--font-weight-bold); } .blocker-overview-row strong, .blocker-overview-row small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .blocker-overview-row strong { font-size: var(--font-size-2xs); } .blocker-overview-row small { color: var(--muted-strong); font-size: 10px; } .structural-blocker { display: grid; gap: 2px; padding: 7px; border-radius: var(--radius-sm); background: var(--brand-container); color: var(--brand-strong); } .structural-blocker strong { font-size: var(--font-size-xs); } .structural-blocker span { font-size: var(--font-size-2xs); line-height: 1.35; } .node-find { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-2); margin-top: var(--space-2); } .node-find-message { margin: 5px 0 0; color: var(--muted-strong); font-size: var(--font-size-2xs); }
	@media (max-width: 1440px) { .metric-grid { grid-template-columns: 1fr; } .route-filters { grid-template-columns: 1fr; } }
</style>
