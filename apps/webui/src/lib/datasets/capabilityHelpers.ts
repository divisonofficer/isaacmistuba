/**
 * Pure capability resolver for the OpticalNav dataset editor.
 *
 * Centralizes every button's enable/disable decision in ONE place (mirroring the
 * pattern of computeWorkflowReadiness) so the conditions can't drift apart between
 * components, and so each disabled button can surface WHY via `reason`.
 *
 * No state dependencies — all context is passed in via CapabilityInput. Button
 * gating reads `caps.X.enabled` for `disabled={!caps.X.enabled}` and `caps.X.reason`
 * for `title={caps.X.reason}` (empty string when enabled).
 */

export interface CapabilityInput {
	selectedProjectId: string;
	hasScene: boolean;
	hasMap: boolean;
	hasGraph: boolean;
	hasEpisodes: boolean;
	renderSceneSynced: boolean;
	renderConfigReady: boolean;
	validationPassed: boolean;
	// A user mutation is running (build/save/export/…). Loads do NOT set this, so
	// data loading never disables the whole UI.
	actionInFlight: boolean;
	// Per-action work-in-progress flags (block re-entry of that specific action).
	buildingMap: boolean;
	buildingGraph: boolean;
	rebuildingEdges: boolean;
	renderingViewpoint: boolean;
	validatingEpisodes: boolean;
	findingOverlapping: boolean;
	removingNodes: boolean;
	probeRendering: boolean;
	renderSceneStatsLoading: boolean;
	// Context for individual buttons.
	removeSelectionCount: number;
	emitterEnabledCount: number;
	emitterDetectedCount: number;
	currentSceneId: string;
	onlyCompleted: boolean;
	exportableEpisodeCount: number;
	selectedNodeIsCustom: boolean;
	episodeNodesAvailable: boolean;
	hotCameraPose: any | null;
	failedJobCount: number;
}

export interface Capability {
	enabled: boolean;
	/** First failing precondition, or '' when enabled. Shown as a tooltip. */
	reason: string;
}

export type CapabilityName =
	| 'saveMap' | 'addScene' | 'editAnnotation' | 'perturbation'
	| 'buildMap' | 'buildGraph' | 'rebuildEdges' | 'findOverlapping' | 'removeNodes'
	| 'generateEpisodes' | 'validateEpisodes' | 'renderSweepNode' | 'renderSweepAll'
	| 'renderEpisodePath' | 'runProbe' | 'validate' | 'export' | 'saveLights'
	| 'enableEmitters' | 'refreshBatch' | 'retryFailed' | 'refreshStats';

export type Capabilities = Record<CapabilityName, Capability>;

/** Build a Capability from a list of [failingCondition, reason] gates. */
function gate(checks: Array<[boolean, string]>): Capability {
	for (const [failing, reason] of checks) {
		if (failing) return { enabled: false, reason };
	}
	return { enabled: true, reason: '' };
}

export function computeCapabilities(i: CapabilityInput): Capabilities {
	const noProject: [boolean, string] = [!i.selectedProjectId, 'Select a project first'];
	const noScene: [boolean, string] = [!i.hasScene, 'Add a scene first'];
	const busy: [boolean, string] = [i.actionInFlight, 'Another action is running'];

	return {
		saveMap: gate([noProject, noScene, busy]),
		addScene: gate([noProject, busy]),
		editAnnotation: gate([noProject, noScene, busy]),
		perturbation: gate([noScene, busy]),

		buildMap: gate([noProject, noScene, [i.buildingMap, 'Building map…']]),
		buildGraph: gate([noProject, [!i.hasMap, 'Build the traversable map first'], [i.buildingGraph, 'Building graph…']]),
		rebuildEdges: gate([[!i.hasGraph, 'Build the viewpoint graph first'], [i.rebuildingEdges, 'Rebuilding edges…']]),
		findOverlapping: gate([[!i.hasGraph, 'Build the viewpoint graph first'], [i.findingOverlapping, 'Searching…']]),
		removeNodes: gate([[i.removeSelectionCount <= 0, 'Select nodes to remove'], [i.removingNodes, 'Removing…']]),

		generateEpisodes: gate([noProject, [!i.hasGraph, 'Build the viewpoint graph first'], busy]),
		validateEpisodes: gate([noProject, [!i.hasGraph, 'Build the viewpoint graph first'], [i.validatingEpisodes, 'Checking…']]),

		renderSweepNode: gate([
			noProject,
			[!i.renderSceneSynced, 'Sync the render scene first'],
			[!i.selectedNodeIsCustom && !i.hasGraph, 'Build the viewpoint graph first'],
			[!i.renderConfigReady, 'Load/complete the render config first'],
			[i.renderingViewpoint, 'Rendering…'],
		]),
		renderSweepAll: gate([
			noProject,
			[!i.renderSceneSynced, 'Sync the render scene first'],
			[!i.hasGraph, 'Build the viewpoint graph first'],
			[!i.renderConfigReady, 'Load/complete the render config first'],
			busy,
		]),
		renderEpisodePath: gate([
			noProject,
			[!i.renderSceneSynced, 'Sync the render scene first'],
			[!i.hasGraph, 'Build the viewpoint graph first'],
			[!i.renderConfigReady, 'Load/complete the render config first'],
			[!i.episodeNodesAvailable, 'Select an episode with a path'],
			busy,
		]),
		runProbe: gate([[!i.hotCameraPose, 'Place a hot camera in the 3D view'], [i.probeRendering, 'Rendering…']]),

		validate: gate([noProject, [!i.hasEpisodes, 'Generate episodes first'], busy]),
		export: gate([
			noProject,
			[!i.hasEpisodes, 'Generate episodes first'],
			[!i.currentSceneId, 'Select a scene first'],
			[i.onlyCompleted && i.exportableEpisodeCount === 0, 'No completed episodes to export'],
			busy,
		]),

		saveLights: gate([noScene, busy]),
		enableEmitters: gate([[i.emitterEnabledCount >= i.emitterDetectedCount, 'All emitters already enabled']]),

		refreshBatch: gate([busy]),
		retryFailed: gate([[i.failedJobCount <= 0, 'No failed jobs'], busy]),
		refreshStats: gate([[i.renderSceneStatsLoading, 'Refreshing…']]),
	};
}
