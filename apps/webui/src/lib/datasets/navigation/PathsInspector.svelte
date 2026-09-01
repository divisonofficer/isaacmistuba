<script lang="ts">
	import { onMount } from 'svelte';
	import { Check, ChevronDown, CircleCheck, CircleX, CircleDotDashed, FileStack, Link2, MapPin, Route, ScanLine, Search, Settings2, Trash2 } from '@lucide/svelte';
	import { InspectorSection, MetricCard, ProgressBar, SegmentedControl } from '$lib/components';
	import { navigationSupportProgressLabel } from '$lib/datasets/services/graphService';
	import { filterBlueprints, primaryNavigationAction, supportAnalysisSummary, type NavigationInspectorTab } from './navigationPresentation';
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
	let episodeBrowserOpen = $state(false);
	let advancedOpen = $state(false);

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
	const supportReady = $derived(Boolean(navigationState.supportReady));
	const analysisSummary = $derived(supportAnalysisSummary(navigationState.supportAnalysis));
	const primary = $derived(primaryNavigationAction({ ...navigationState, supportReady }));

	function runPrimary() {
		if (primary.disabled) return;
		if (primary.id === 'build-grid') navigationActions.onBuildMap?.();
		else if (primary.id === 'build-place-graph') navigationActions.onRequestBuildGraph?.();
		else if (primary.id === 'analyze-support') navigationActions.onAnalyzeSupportGraph?.();
		else if (primary.id === 'build-support') navigationActions.onBuildSupportGraph?.();
		else navigationActions.onRenderNavigationSupport?.();
	}

	function chooseRoute(id: string) {
		navigationActions.onSelectBlueprint?.(id);
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

	function generateEpisodes() {
		if (navigationState.navigationSupport || navigationState.adaptiveNavigation) navigationActions.onGenerateRouteMotionEpisodes?.();
		else navigationActions.onGenerateEpisodes?.();
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
		<span class:ready={supportReady} class="state-chip">{supportReady ? 'Ready' : navigationState.hasGraph ? 'Review' : 'Setup'}</span>
	</header>
	<SegmentedControl items={tabs} value={tab} ariaLabel="Navigation inspector section" onchange={(value) => tab = value as NavigationInspectorTab} />

	{#if tab === 'setup'}
		<InspectorSection title="Robot footprint">
			<div class="form-grid">
				<label>Robot radius (m)<input type="number" min="0" max="2" step="0.05" value={navigationState.robotRadius} oninput={(event) => navigationActions.onSetRobotRadius?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
				<label>Min clearance (m)<input type="number" min="0" max="2" step="0.05" value={navigationState.minClearance} oninput={(event) => navigationActions.onSetMinClearance?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
			</div>
			<p class="help">Inflated clearance: <strong>{(Number(navigationState.robotRadius) + Number(navigationState.minClearance)).toFixed(2)} m</strong></p>
		</InspectorSection>

		<InspectorSection title="Traversable grid">
			<label class="field">Resolution (m)<input type="number" min="0.01" step="0.01" value={navigationState.resolution} oninput={(event) => navigationActions.onSetResolution?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
			{#if navigationState.mapResult}
				<div class="inline-summary"><Check size={15} /> Grid ready · {navigationState.mapResult.cell_count ?? '—'} cells · {Math.round(Number(navigationState.mapResult.traversable_ratio ?? 0) * 100)}% walkable</div>
			{/if}
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
			{#if navigationState.edgeCheckResult}
				<div class:ok={navigationState.edgeCheckResult.would_connect} class="edge-review"><strong>{navigationState.edgeCheckResult.source} ↔ {navigationState.edgeCheckResult.target}</strong><span>{navigationState.edgeCheckResult.would_connect ? 'Collision check passed — direct link can be added.' : navigationState.edgeCheckResult.reason ?? 'Boundary requires review.'}</span>{#if navigationState.edgeCheckResult.reason === 'not_certified_doorway'}<div class="edge-metrics"><span>Wall cells <strong>{navigationState.edgeCheckResult.wall_run_cells ?? 0}</strong></span><span>Raw gap <strong>{Number(navigationState.edgeCheckResult.raw_gap_m ?? 0).toFixed(2)} m</strong></span><span>Hazard <strong>{navigationState.edgeCheckResult.hazard_crossing ? 'yes' : 'no'}</strong></span></div><p class:eligible={navigationState.edgeCheckResult.manual_opening_eligible} class="certification-hint">{openingCertificationHint(navigationState.edgeCheckResult)}</p>{/if}<div class="action-row"><button class="button button-subtle" disabled={!navigationState.edgeCheckResult.would_connect} onclick={() => navigationActions.onAddEdgeAnyway?.()}>Add direct link</button>{#if navigationState.edgeCheckResult.manual_opening_eligible}<button class="button button-ghost" onclick={() => navigationActions.onCertifyVisibleOpening?.()}>Confirm opening</button>{/if}<button class="button button-ghost" onclick={() => navigationActions.onDismissEdgeCheck?.()}>Dismiss</button></div></div>
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
				<label class="search"><Search size={15} /><input placeholder="Find route or place" bind:value={routeQuery} /></label>
				<select aria-label="Route status" bind:value={routeStatus}><option value="all">All states</option><option value="proposed">Proposed</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select>
			</div>
			{#if navigationState.navigationSupport?.route_blueprints}
				<button class:active={navigationState.pathsMode === 'blueprint_pair'} class="button button-subtle route-create-canvas" onclick={startBlueprintPair}><CircleDotDashed size={16} /> {navigationState.pathsMode === 'blueprint_pair' ? 'Click start and goal places on the canvas' : 'Add route on canvas'}</button>
				<div class="collection" aria-label="Route blueprint collection">
					{#each filteredBlueprints as route (route.blueprint_id)}
						<div class:selected={navigationState.activeBlueprintId === route.blueprint_id} class="collection-row">
							<button class="route-select" onclick={() => chooseRoute(route.blueprint_id)}><span class={`route-status ${route.status}`}></span><strong>{route.blueprint_id}</strong><small>{route.start_anchor_id} → {route.goal_anchor_id}</small><em>{Number(route.place_path_distance_m ?? 0).toFixed(1)} m</em></button>
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
		<InspectorSection title="Coverage workflow">
			<div class="metric-grid"><MetricCard label="Approved routes" value={approvedCount} tone={approvedCount ? 'success' : 'warning'} /><MetricCard label="Support poses" value={analysisSummary?.support_pose_count ?? navigationState.navigationSupport?.observation_plan?.summary?.support_pose_count ?? '—'} /><MetricCard label="Native views" value={analysisSummary?.polar_observation_count ?? navigationState.navigationSupport?.observation_plan?.summary?.polar_observation_count ?? '—'} /></div>
			{#if analysisSummary}<p class="help">Analysis estimates {analysisSummary.polar_batch_count ?? '—'} K=4 polar batches before building the immutable support plan.</p>{:else if navigationState.supportAnalysis?.ok === false}<p class="help warn">{navigationState.supportAnalysis?.analysis?.message ?? navigationState.supportAnalysis?.analysis?.error ?? 'Analysis found a blocked corridor. Repair or unapprove the listed route before building.'}</p>{:else}<p class="help">Approve a route, then analyze its pose and native-view coverage.</p>{/if}
			{#if supportReady}<div class="inline-summary"><Check size={15} /> Navigation Support is built and ready to render.</div>{/if}
		</InspectorSection>
	{/if}

	{#if tab === 'episodes'}
		<InspectorSection title="Episode split">
			<div class="metric-grid"><MetricCard label="Train" value={episodeState.splitCounts?.train ?? 0} /><MetricCard label="Val seen" value={episodeState.splitCounts?.val_seen ?? 0} /><MetricCard label="Val unseen" value={episodeState.splitCounts?.val_unseen ?? 0} /></div>
			<label class="field">Episode pairs<input type="number" min="1" value={episodeState.episodeCount} oninput={(event) => navigationActions.onSetEpisodeCount?.(Number((event.currentTarget as HTMLInputElement).value))} /></label>
			<div class="action-row"><button class="button button-subtle" disabled={Boolean(navigationState.navigationSupport) && !supportReady} onclick={generateEpisodes}>{episodeState.episodePlanProgress ? `Generating ${episodeState.episodePlanProgress.planned ?? 0}/${episodeState.episodePlanProgress.target ?? episodeState.episodeCount}` : 'Generate episodes'}</button><button class="button button-ghost" aria-expanded={episodeBrowserOpen} onclick={() => episodeBrowserOpen = !episodeBrowserOpen}><FileStack size={16} /> {episodeBrowserOpen ? 'Hide browse' : `Browse ${episodeState.total ?? episodeState.episodes?.length ?? 0}`}</button></div>
			{#if episodeState.staleEpisodeReport}<p class:warn={(episodeState.staleEpisodeReport.stale_count ?? 0) > 0} class="help">{episodeState.staleEpisodeReport.stale_count ?? 0} stale of {episodeState.staleEpisodeReport.checked ?? 0} checked.</p>{/if}
			<div class="action-row"><button class="button button-ghost" disabled={!episodeState.episodes?.length || episodeState.validatingEpisodes} onclick={() => navigationActions.onValidateEpisodes?.()}>{episodeState.validatingEpisodes ? 'Validating…' : 'Validate graph references'}</button>{#if (episodeState.staleEpisodeReport?.stale_count ?? 0) > 0}<button class="button button-danger" onclick={() => navigationActions.onPruneStaleEpisodes?.()}>Remove stale</button>{/if}</div>
			{#if episodeBrowserOpen}
				<div class="episode-browser" aria-label="Browse navigation episodes">
					<header><div><p>Browse episodes</p><strong>{episodeState.total ?? episodeState.episodes?.length ?? 0} in this scene</strong></div><span>Scroll to compare</span></header>
					<label class="search"><Search size={15} /><input placeholder="Find episode" value={episodeState.episodeSearch} oninput={(event) => navigationActions.onSetEpisodeSearch?.((event.currentTarget as HTMLInputElement).value)} /></label>
					<div class="episode-browser-list">{#each episodeState.filteredEpisodes ?? [] as episode (episode.episode_id)}<button class:selected={episodeState.selectedEpisodeId === episode.episode_id} onclick={() => chooseEpisode(episode.episode_id)}><span><strong>{episode.episode_id}</strong><small>{episode.split ?? 'unsplit'} · {episode.navigation_mode ?? 'trajectory'}</small></span>{#if episode.hazard_collision}<span class="warning">Hazard</span>{/if}</button>{:else}<p class="empty">No episodes for this scene.</p>{/each}</div>
					{#if episodeState.nextCursor}<button class="button button-subtle" onclick={() => navigationActions.onLoadMoreEpisodes?.()}>Load next 100</button>{/if}
				</div>
			{/if}
		</InspectorSection>
	{/if}

	<footer class="sticky-action"><div><strong>{primary.label}</strong><span>{primary.description}</span></div><button class="button button-primary" disabled={primary.disabled} onclick={runPrimary}>{primary.label}</button></footer>
</div>

<style>
	.paths-inspector { display: grid; min-width: 0; gap: 0; padding: 0 var(--space-4) 5.75rem; overflow-x: hidden; }
	.inspector-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-4) 0 var(--space-3); }
	p { margin: 0; } .inspector-heading p, .episode-browser p { color: var(--muted); font-size: var(--font-size-2xs); font-weight: var(--font-weight-bold); letter-spacing: var(--letter-spacing-wide); text-transform: uppercase; } h2 { margin: 3px 0 0; color: var(--text); font-size: var(--font-size-lg); }
	.state-chip { flex: 0 0 auto; padding: 4px 8px; border-radius: var(--radius-pill); background: var(--warning-container); color: var(--warning-strong); font-size: var(--font-size-2xs); font-weight: var(--font-weight-bold); } .state-chip.ready { background: var(--success-container); color: var(--success-strong); }
	.form-grid, .metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); } .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
	label.field, .form-grid label { display: grid; min-width: 0; gap: 5px; color: var(--muted-strong); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); } input, select { width: 100%; min-width: 0; box-sizing: border-box; min-height: 2.25rem; padding: 0 8px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--panel); color: var(--text); }
	.help { color: var(--muted-strong); font-size: var(--font-size-xs); line-height: 1.45; } .help.warn, .warning { color: var(--warning-strong); }
	.inline-summary { display: flex; align-items: center; gap: 6px; color: var(--success-strong); font-size: var(--font-size-xs); } .progress-row { display: grid; gap: 6px; color: var(--muted-strong); font-size: var(--font-size-xs); }
	.advanced { border-bottom: 1px solid var(--panel-border); padding: var(--space-3) 0; } .advanced summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--muted-strong); cursor: pointer; font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); list-style: none; } .advanced summary::-webkit-details-marker { display: none; } .advanced-body { display: grid; gap: var(--space-2); padding-top: var(--space-3); }
	.repair-tool-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); } .repair-tool-grid button { display: inline-flex; min-width: 0; align-items: center; justify-content: center; gap: 5px; font-size: var(--font-size-xs); white-space: nowrap; } .repair-tool-grid button:last-child { grid-column: 1 / -1; } .repair-tool-grid button.active { border-color: var(--brand); background: var(--brand-container); color: var(--brand-strong); } .mode-hint { padding: 8px; border-radius: var(--radius-sm); background: var(--brand-container); color: var(--brand-strong); font-size: var(--font-size-xs); line-height: 1.4; } .remove-node-controls { display: grid; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--surface-2); } .repair-guide-copy { display: grid; gap: 2px; color: var(--muted-strong); font-size: var(--font-size-xs); } .repair-guide-list { display: grid; gap: var(--space-2); } .repair-guide-row { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: var(--space-2); padding: 8px; border: 1px solid var(--warning); border-radius: var(--radius-sm); background: var(--warning-container); } .repair-guide-row.active { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand-container); } .repair-guide-row > span { display: grid; min-width: 0; gap: 2px; } .repair-guide-row strong, .repair-guide-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .repair-guide-row strong { color: var(--text); font-size: var(--font-size-xs); } .repair-guide-row small { color: var(--muted-strong); font-size: var(--font-size-2xs); } .repair-guide-row button { flex: 0 0 auto; } .edge-review { display: grid; gap: 5px; padding: 9px; border: 1px solid var(--warning); border-radius: var(--radius-sm); background: var(--warning-container); color: var(--muted-strong); font-size: var(--font-size-xs); } .edge-review.ok { border-color: var(--success); background: var(--success-container); } .edge-metrics { display: flex; flex-wrap: wrap; gap: 4px; } .edge-metrics span { padding: 3px 5px; border-radius: 4px; background: color-mix(in srgb, var(--panel) 60%, transparent); font-size: var(--font-size-2xs); } .certification-hint { color: var(--warning-strong); font-size: var(--font-size-xs); line-height: 1.4; } .certification-hint.eligible { color: var(--success-strong); }
	.compact-list { display: grid; max-height: 11rem; overflow-y: auto; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); } .compact-list label { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 7px; align-items: center; padding: 7px; border-bottom: 1px solid var(--panel-border); font-size: var(--font-size-xs); } .compact-list label:last-child { border-bottom: 0; } .compact-list span, .compact-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.edge-result { display: grid; gap: 6px; padding: 9px; border-radius: var(--radius-sm); background: var(--surface-2); color: var(--muted-strong); font-size: var(--font-size-xs); }
	.route-filters { display: grid; grid-template-columns: minmax(0, 1fr) 7.5rem; gap: var(--space-2); } .route-create-canvas { display: inline-flex; width: 100%; align-items: center; justify-content: center; gap: 6px; } .route-create-canvas.active { border-color: var(--brand); background: var(--brand-container); color: var(--brand-strong); }
	.search { display: flex; align-items: center; min-width: 0; gap: 6px; padding: 0 8px; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); color: var(--muted); } .search input { border: 0; padding: 0; }
	.collection { display: grid; max-height: 18rem; overflow-y: auto; border: 1px solid var(--panel-border); border-radius: var(--radius-md); } .collection-row { display: flex; min-width: 0; align-items: center; border-bottom: 1px solid var(--panel-border); } .collection-row:last-child { border-bottom: 0; } .collection-row.selected { background: var(--brand-container); } .route-select { display: grid; grid-template-columns: auto auto minmax(0, 1fr) auto; flex: 1; min-width: 0; gap: 6px; align-items: center; padding: 7px 5px 7px 9px; border: 0; background: transparent; color: var(--text); text-align: left; cursor: pointer; line-height: 1.15; } .route-select strong, .route-select small, .route-select em { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .route-select strong { font-size: var(--font-size-xs); } .route-select small, .route-select em { color: var(--muted); font-size: 10px; font-style: normal; } .route-status { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); } .route-status.approved { background: var(--success); } .route-status.proposed { background: var(--warning); } .route-status.rejected { background: var(--danger); }
	.route-toggles { display: flex; flex: 0 0 auto; align-items: center; gap: 1px; padding-right: 4px; } .icon-button { display: grid; width: 1.75rem; height: 1.75rem; place-items: center; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--muted-strong); cursor: pointer; } .icon-button:hover { background: var(--hover-bg); } .icon-button.approve.active { background: var(--success-container); color: var(--success-strong); } .icon-button.reject.active { background: var(--danger-container); color: var(--danger-strong); } .icon-button.delete:hover { color: var(--danger-strong); }
	.selected-route { display: flex; min-width: 0; gap: 8px; padding: 10px; border-radius: var(--radius-sm); background: var(--brand-container); color: var(--brand-strong); } .selected-route > div { display: grid; min-width: 0; gap: 2px; } .selected-route span { overflow: hidden; color: var(--muted-strong); font-size: var(--font-size-xs); text-overflow: ellipsis; white-space: nowrap; }
	.action-row { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; } .action-row button { display: inline-flex; align-items: center; gap: 6px; }
	.sticky-action { position: sticky; z-index: 10; bottom: 0; display: flex; gap: var(--space-2); align-items: center; justify-content: space-between; margin: var(--space-3) calc(-1 * var(--space-4)) 0; padding: 12px var(--space-4); border-top: 1px solid var(--panel-border); background: color-mix(in srgb, var(--panel) 94%, transparent); box-shadow: 0 -8px 20px color-mix(in srgb, var(--panel) 86%, transparent); backdrop-filter: blur(12px); } .sticky-action > div { display: grid; min-width: 0; gap: 2px; } .sticky-action strong { font-size: var(--font-size-sm); } .sticky-action span { overflow: hidden; color: var(--muted); font-size: var(--font-size-2xs); text-overflow: ellipsis; white-space: nowrap; } .sticky-action button { flex: 0 0 auto; }
	.empty { padding: var(--space-3); color: var(--muted); font-size: var(--font-size-xs); text-align: center; }
	.episode-browser { display: grid; min-width: 0; gap: var(--space-2); margin-top: var(--space-3); padding: var(--space-3); border: 1px solid var(--panel-border); border-radius: var(--radius-md); background: var(--surface-2); } .episode-browser header { display: flex; align-items: start; justify-content: space-between; gap: var(--space-2); } .episode-browser header > div { display: grid; gap: 2px; min-width: 0; } .episode-browser header strong { color: var(--text); font-size: var(--font-size-sm); } .episode-browser header > span { flex: 0 0 auto; color: var(--muted); font-size: var(--font-size-2xs); } .episode-browser-list { display: grid; align-content: start; max-height: min(22rem, 42dvh); overflow-y: auto; overflow-x: hidden; border: 1px solid var(--panel-border); border-radius: var(--radius-sm); background: var(--panel); } .episode-browser-list button { display: flex; min-width: 0; justify-content: space-between; gap: 8px; padding: 9px; border: 0; border-bottom: 1px solid var(--panel-border); background: transparent; color: var(--text); text-align: left; cursor: pointer; } .episode-browser-list button:last-child { border-bottom: 0; } .episode-browser-list button.selected { background: var(--brand-container); } .episode-browser-list button > span:first-child { display: grid; min-width: 0; gap: 2px; } .episode-browser-list strong, .episode-browser-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .episode-browser-list small { color: var(--muted); font-size: var(--font-size-2xs); }
	@media (max-width: 1440px) { .metric-grid { grid-template-columns: 1fr; } .route-filters { grid-template-columns: 1fr; } }
</style>
