/**
 * Viewpoint graph build, load, and edit service.
 * Wraps API calls — no state management.
 * The buildGraph function uses WebSocket for progress via a callback.
 */

import {
	buildOpticalNavViewpointGraph,
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
}

export interface BuildGraphProgress {
	status: string;
	stage: string;
	progress: number;
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

export async function addGraphNode(
	projectId: string,
	sceneId: string,
	x: number,
	z: number,
	headingCount: number
) {
	return addOpticalNavGraphNode(projectId, sceneId, { x, y: z, heading_count: headingCount });
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
	params: CheckEdgeParams
) {
	return checkOpticalNavGraphEdge(projectId, sceneId, {
		source, target,
		robot_radius_m: params.robotRadiusM,
		max_edge_length_m: params.maxEdgeLengthM,
	});
}

export async function addEdge(
	projectId: string,
	sceneId: string,
	source: string,
	target: string
) {
	return addOpticalNavGraphEdge(projectId, sceneId, { source, target });
}

export interface GraphEditOp {
	client_op_id?: string;
	type: 'add_edge' | 'delete_edge';
	source?: string;
	target?: string;
	edge_id?: string;
}

export async function editGraph(
	projectId: string,
	sceneId: string,
	clientBatchId: string,
	ops: GraphEditOp[]
) {
	return editOpticalNavGraph(projectId, sceneId, {
		client_batch_id: clientBatchId,
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
