/**
 * Viewpoint graph build, load, and edit service.
 * Wraps API calls — no state management.
 * The buildGraph function uses WebSocket for progress via a callback.
 */

import {
	buildOpticalNavViewpointGraph,
	buildAdaptiveRouteMotion,
	buildNavigationSupportPlaceGraph,
	getNavigationSupport,
	getNavigationSupportBlueprints,
	regenerateNavigationSupportBlueprints,
	editNavigationSupportBlueprints,
	deleteNavigationSupportBlueprint,
	analyzeNavigationSupport,
	buildNavigationSupport,
	prepareNavigationSupportObservationExpansion,
	getAdaptiveRouteMotion,
	getOpticalNavViewpointGraph,
	graphBuildProgressWsUrl,
	addOpticalNavGraphNode,
	rebuildOpticalNavGraphEdges,
	deleteOpticalNavGraphNode,
	deleteOpticalNavGraphNodes,
	fetchOpticalNavOverlappingGraphNodes,
	checkOpticalNavGraphEdge,
	addOpticalNavGraphEdge,
	editOpticalNavGraph,
	deleteOpticalNavGraphEdge,
	regenerateOpticalNavGraphRegion,
} from '$lib/api';

export type NavigationSupportAlgorithm = 'production_v1' | 'global_executable_network_v2';

export interface BuildGraphParams {
	maxNodes: number;
	headingCount: number;
	minNodeSpacingM: number;
	robotRadiusM: number;
	minClearanceM: number;
	kNeighbors: number;
	maxEdgeLengthM: number;
	resolution: number;
	seed: number;
	/** Required only when replacing an already materialized V4 support graph. */
	confirmSupportInvalidation?: boolean;
	/** Discard every manually added node/edge and edit-history hint instead of carrying them into the new sample. */
	fromScratch?: boolean;
}

export interface BuildGraphProgress {
	status: string;
	stage: string;
	progress: number;
	detail?: Record<string, unknown>;
}

export function routeMotionProgressLabel(stage?: string): string {
	return {
		anchor_grid: 'Preparing clearance grid',
		anchor_nodes: 'Sampling sparse anchors',
		anchor_edges: 'Certifying anchor edges',
		route_motion: 'Preparing shared action graph',
		anchor_spanner: 'Selecting connected anchor backbone',
		portal_grid: 'Restoring certified portal corridors',
		request_catalogue: 'Building route coverage catalogue',
		request_selection: 'Selecting coverage routes',
		action_lattice: 'Expanding 0.25 m action lattice',
		action_backbone: 'Pruning shared action backbone',
		action_states: 'Building 15° action states',
		validation: 'Validating collision-free transitions',
		observation_plan: 'Planning selective observations',
		sidecars: 'Writing route-motion sidecars',
		complete: 'Route Motion complete',
		done: 'Route Motion complete',
		error: 'Route Motion failed',
	}[stage ?? ''] ?? (stage ? `Building: ${stage}` : 'Starting Route Motion build');
}

export function navigationSupportProgressLabel(stage?: string): string {
	return {
		place_grid: 'Preparing place graph grid',
		place_nodes: 'Sampling sparse places',
		place_edges: 'Certifying place topology',
		blueprint_catalogue: 'Proposing reviewable routes',
		support_prepare: 'Preparing approved corridors',
		support_trunk: 'Selecting major trunks',
		support_lanes: 'Expanding 0.25 m directed lanes',
		support_patches: 'Certifying local turn patches',
		action_states: 'Building 15° action states',
		observation_plan: 'Planning native observations',
		complete: 'Navigation Support complete',
		done: 'Navigation Support complete',
		error: 'Navigation Support failed',
	}[stage ?? ''] ?? (stage ? `Building: ${stage}` : 'Starting Navigation Support');
}

export interface RebuildRegionParams {
	bbox: number[];
	maxNodes: number;
	minNodeSpacingM: number;
	robotRadiusM: number;
	minClearanceM: number;
	headingCount: number;
	seed: number;
}

export interface CheckEdgeParams {
	robotRadiusM: number;
	maxEdgeLengthM: number;
}

/** Load the viewpoint graph JSON for a scene. */
export async function fetchGraph(projectId: string, sceneId: string) {
	return getOpticalNavViewpointGraph(projectId, sceneId);
}

/**
 * Build the viewpoint graph with real-time progress via WebSocket.
 * The onProgress callback is called with each progress update.
 */
export async function buildGraph(
	projectId: string,
	sceneId: string,
	params: BuildGraphParams,
	onProgress: (p: BuildGraphProgress) => void
) {
	let ws: WebSocket | null = null;
	try {
		ws = new WebSocket(graphBuildProgressWsUrl(projectId, sceneId));
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data);
				if (msg?.status === 'building') onProgress(msg);
			} catch {}
		};
		ws.onerror = () => {};
	} catch {}

	try {
		return await buildOpticalNavViewpointGraph(projectId, sceneId, {
			max_nodes: params.maxNodes,
			heading_count: params.headingCount,
			min_node_spacing_m: params.minNodeSpacingM,
			robot_radius_m: params.robotRadiusM,
			min_clearance_m: params.minClearanceM,
			k_neighbors: params.kNeighbors,
			max_edge_length_m: params.maxEdgeLengthM,
			resolution: params.resolution,
			seed: params.seed,
		});
	} finally {
		if (ws) { try { ws.close(); } catch {} }
	}
}

/** Build v3 anchor + shared action backbone + selective observation sidecars. */
export async function buildAdaptiveNavigation(
	projectId: string,
	sceneId: string,
	params: BuildGraphParams,
	onProgress: (p: BuildGraphProgress) => void
) {
	let ws: WebSocket | null = null;
	try {
		ws = new WebSocket(graphBuildProgressWsUrl(projectId, sceneId));
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data);
				if (msg?.status === 'building') onProgress(msg);
			} catch {}
		};
		ws.onerror = () => {};
	} catch {}

	try {
		return await buildAdaptiveRouteMotion(projectId, sceneId, {
			max_anchor_nodes: params.maxNodes,
			heading_count: 24,
			min_node_spacing_m: params.minNodeSpacingM,
			robot_radius_m: params.robotRadiusM,
			min_clearance_m: params.minClearanceM,
			k_neighbors: params.kNeighbors,
			max_edge_length_m: params.maxEdgeLengthM,
			resolution: params.resolution,
			seed: params.seed,
			// Preserve a certified connected core and expose unsafe terminals for
			// repair.  The server never turns this into an unchecked bridge edge.
			unreachable_terminal_policy: 'defer',
		});
	} finally {
		if (ws) { try { ws.close(); } catch {} }
	}
}

export async function fetchAdaptiveNavigation(projectId: string, sceneId: string) {
	return getAdaptiveRouteMotion(projectId, sceneId);
}

async function withNavigationProgress<T>(
	projectId: string,
	sceneId: string,
	onProgress: (p: BuildGraphProgress) => void,
	request: () => Promise<T>,
): Promise<T> {
	let ws: WebSocket | null = null;
	try {
		ws = new WebSocket(graphBuildProgressWsUrl(projectId, sceneId));
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data);
				if (msg?.status === 'building') onProgress(msg);
			} catch {}
		};
		ws.onerror = () => {};
	} catch {}
	try {
		return await request();
	} finally {
		if (ws) { try { ws.close(); } catch {} }
	}
}

/** Stage 1: sparse 12-heading topology and proposed, non-executable routes. */
export async function buildNavigationSupportPlace(
	projectId: string,
	sceneId: string,
	params: BuildGraphParams,
	onProgress: (p: BuildGraphProgress) => void,
) {
	return withNavigationProgress(projectId, sceneId, onProgress, () =>
		buildNavigationSupportPlaceGraph(projectId, sceneId, {
			max_nodes: params.maxNodes,
			heading_count: 12,
			min_node_spacing_m: params.minNodeSpacingM,
			robot_radius_m: params.robotRadiusM,
			min_clearance_m: params.minClearanceM,
			k_neighbors: params.kNeighbors,
			max_edge_length_m: params.maxEdgeLengthM,
			resolution: params.resolution,
			seed: params.seed,
			confirm_support_invalidation: Boolean(params.confirmSupportInvalidation),
			from_scratch: Boolean(params.fromScratch),
		}),
	);
}

export async function fetchNavigationSupport(projectId: string, sceneId: string) {
	return getNavigationSupport(projectId, sceneId);
}

export async function fetchNavigationSupportBlueprints(projectId: string, sceneId: string) {
	return getNavigationSupportBlueprints(projectId, sceneId);
}

/** Create a fresh proposal catalogue without rebuilding the repaired Place Graph. */
export async function regenerateNavigationSupportBlueprintCatalog(
	projectId: string,
	sceneId: string,
	confirmSupportInvalidation = false,
) {
	return regenerateNavigationSupportBlueprints(projectId, sceneId, {
		confirm_support_invalidation: confirmSupportInvalidation,
	});
}

export async function setNavigationSupportBlueprintStatus(
	projectId: string, sceneId: string, blueprintId: string, status: 'proposed' | 'approved' | 'rejected',
) {
	return editNavigationSupportBlueprints(projectId, sceneId, { action: 'status', blueprint_id: blueprintId, status });
}

/** Move every blueprint in one current review state to another atomically. */
export async function setAllProposedNavigationSupportBlueprints(
	projectId: string, sceneId: string, status: 'approved' | 'rejected',
) {
	return editNavigationSupportBlueprints(projectId, sceneId, { action: 'status_all', status });
}

/** Reopen a bulk approval without touching explicitly rejected routes. */
export async function resetApprovedNavigationSupportBlueprints(projectId: string, sceneId: string) {
	return editNavigationSupportBlueprints(projectId, sceneId, {
		action: 'status_all', from_status: 'approved', status: 'proposed',
	});
}

export async function createNavigationSupportBlueprint(
	projectId: string, sceneId: string, startAnchorId: string, goalAnchorId: string, scenario = 'goal_only', approved = false,
) {
	return editNavigationSupportBlueprints(projectId, sceneId, {
		action: 'create', start_anchor_id: startAnchorId, goal_anchor_id: goalAnchorId, scenario, approved,
	});
}

export async function removeNavigationSupportBlueprint(projectId: string, sceneId: string, blueprintId: string) {
	return deleteNavigationSupportBlueprint(projectId, sceneId, blueprintId);
}

/** Lateral-band knobs for Stage 3, layered on top of the selected algorithm. */
export interface NavigationSupportOptions {
	lateralBandEnabled?: boolean;
	lateralSwitchIntervalSteps?: number;
}

function navigationSupportPayload(algorithm: NavigationSupportAlgorithm, options?: NavigationSupportOptions) {
	const payload: Record<string, unknown> = { support_algorithm: algorithm };
	if (options?.lateralBandEnabled !== undefined) payload.lateral_band_enabled = options.lateralBandEnabled;
	if (options?.lateralSwitchIntervalSteps !== undefined) payload.lateral_switch_interval_steps = options.lateralSwitchIntervalSteps;
	return payload;
}

/** Stage 3 dry-run: reports pose/view/batch cost without writing sidecars. */
export async function analyzeNavigationSupportGraph(
	projectId: string,
	sceneId: string,
	onProgress: (p: BuildGraphProgress) => void,
	algorithm: NavigationSupportAlgorithm = 'production_v1',
	options?: NavigationSupportOptions,
) {
	return withNavigationProgress(projectId, sceneId, onProgress, () =>
		analyzeNavigationSupport(projectId, sceneId, navigationSupportPayload(algorithm, options)),
	);
}

/** Stage 3 write: collision-certified lanes, action states, and render allow-list. */
export async function buildNavigationSupportGraph(
	projectId: string,
	sceneId: string,
	onProgress: (p: BuildGraphProgress) => void,
	algorithm: NavigationSupportAlgorithm = 'production_v1',
	options?: NavigationSupportOptions,
) {
	return withNavigationProgress(projectId, sceneId, onProgress, () =>
		buildNavigationSupport(projectId, sceneId, navigationSupportPayload(algorithm, options)),
	);
}

/** Prepare an add-only native heading context sidecar without rebuilding support lanes. */
export async function prepareNavigationSupportExpansion(
	projectId: string,
	sceneId: string,
	levelId: string,
) {
	return prepareNavigationSupportObservationExpansion(projectId, sceneId, { level_id: levelId });
}

export async function addGraphNode(
	projectId: string,
	sceneId: string,
	x: number,
	z: number,
	headingCount: number,
	graphScope: 'legacy' | 'navigation_place' = 'legacy',
	confirmSupportInvalidation = false,
) {
	return addOpticalNavGraphNode(projectId, sceneId, {
		x, y: z, heading_count: headingCount, graph_scope: graphScope,
		confirm_support_invalidation: Boolean(confirmSupportInvalidation),
	});
}

export async function deleteGraphNode(projectId: string, sceneId: string, nodeId: string) {
	return deleteOpticalNavGraphNode(projectId, sceneId, nodeId);
}

/** Re-run edge building over the current node set (keeps auto + manual nodes). */
export async function rebuildGraphEdges(projectId: string, sceneId: string) {
	return rebuildOpticalNavGraphEdges(projectId, sceneId, {});
}

/** Batch-remove multiple viewpoint nodes (and their incident edges) in one request. */
export async function deleteGraphNodes(projectId: string, sceneId: string, nodeIds: string[], reason?: string) {
	return deleteOpticalNavGraphNodes(projectId, sceneId, nodeIds, reason);
}

/** Auto-detect node_ids that overlap scene objects, for review before removal. */
export async function findOverlappingNodes(
	projectId: string,
	sceneId: string,
	opts?: { marginM?: number; includeWalls?: boolean; robotHeightM?: number }
): Promise<string[]> {
	const res = await fetchOpticalNavOverlappingGraphNodes(projectId, sceneId, opts);
	return (res?.node_ids as string[]) ?? [];
}

export async function checkEdge(
	projectId: string,
	sceneId: string,
	source: string,
	target: string,
	params: CheckEdgeParams,
	graphScope: 'legacy' | 'navigation_place' = 'legacy',
) {
	return checkOpticalNavGraphEdge(projectId, sceneId, {
		source, target,
		robot_radius_m: params.robotRadiusM,
		max_edge_length_m: params.maxEdgeLengthM,
		graph_scope: graphScope,
	});
}

export async function addEdge(
	projectId: string,
	sceneId: string,
	source: string,
	target: string,
	graphScope: 'legacy' | 'navigation_place' = 'legacy',
) {
	return addOpticalNavGraphEdge(projectId, sceneId, { source, target, graph_scope: graphScope });
}

export interface GraphEditOp {
	client_op_id?: string;
	type: 'add_edge' | 'delete_edge' | 'add_node' | 'delete_node';
	source?: string;
	target?: string;
	edge_id?: string;
	node_id?: string;
	x?: number;
	y?: number;
	/** Explicit user confirmation for a wall-free, short missing portal threshold. */
	certify_opening?: boolean;
}

export async function editGraph(
	projectId: string,
	sceneId: string,
	clientBatchId: string,
	ops: GraphEditOp[],
	graphScope: 'legacy' | 'navigation_place' = 'legacy',
	confirmSupportInvalidation = false,
) {
	return editOpticalNavGraph(projectId, sceneId, {
		client_batch_id: clientBatchId,
		graph_scope: graphScope,
		confirm_support_invalidation: Boolean(confirmSupportInvalidation),
		ops: ops as unknown as Array<Record<string, unknown>>,
	});
}

export async function deleteEdge(projectId: string, sceneId: string, edgeId: string) {
	return deleteOpticalNavGraphEdge(projectId, sceneId, edgeId);
}

export async function rebuildRegion(
	projectId: string,
	sceneId: string,
	params: RebuildRegionParams
) {
	return regenerateOpticalNavGraphRegion(projectId, sceneId, {
		bbox: params.bbox as [number, number, number, number],
		max_nodes: params.maxNodes,
		min_node_spacing_m: params.minNodeSpacingM,
		robot_radius_m: params.robotRadiusM,
		min_clearance_m: params.minClearanceM,
		heading_count: params.headingCount,
		seed: params.seed,
	});
}
