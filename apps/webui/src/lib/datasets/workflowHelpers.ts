/**
 * Pure workflow readiness state machine for the OpticalNav dataset authoring pipeline.
 * No state dependencies — all context is passed in via WorkflowInput.
 */

export interface WorkflowInput {
	selectedProjectId: string;
	hasScene: boolean;
	hasAuthoringMap: boolean;
	hasAuthoringContent: boolean;
	hasPersistedAuthoringMap: boolean;
	authoringMapDirty: boolean;
	currentScene: any | null;
	hasMap: boolean;
	hasGraph: boolean;
	hasEpisodes: boolean;
	renderSceneSynced: boolean;
	renderConfigReady: boolean;
	validationReport: any | null;
	validationPassed: boolean;
}

export interface WorkflowResult {
	step: string;
	status: 'needs_input' | 'ready' | 'blocked' | 'failed';
	message: string;
	action: string;
	tab: string;
	kind: string;
}

/** Compute the next actionable step in the dataset authoring workflow. */
export function computeWorkflowReadiness(input: WorkflowInput): WorkflowResult {
	const {
		selectedProjectId, hasScene, hasAuthoringMap, hasAuthoringContent,
		hasPersistedAuthoringMap, authoringMapDirty, currentScene,
		hasMap, hasGraph, hasEpisodes, renderSceneSynced, renderConfigReady,
		validationReport, validationPassed,
	} = input;

	if (!selectedProjectId) {
		return {
			step: 'Project',
			status: 'needs_input',
			message: 'Create or select an OpticalNav project.',
			action: 'Create Project',
			tab: 'scene',
			kind: 'create_project',
		};
	}
	if (!hasScene) {
		return {
			step: 'Scene',
			status: 'needs_input',
			message: 'Add a scene before editing navigation overlays.',
			action: 'Add Scene',
			tab: 'scene',
			kind: 'add_scene',
		};
	}
	if (!hasAuthoringMap || !hasAuthoringContent) {
		return {
			step: 'Map Overlay',
			status: 'needs_input',
			message: 'Create a visible 2D map overlay with traversable, hazard, and goal layers.',
			action: 'Create Map Overlay',
			tab: 'scene',
			kind: 'create_overlay',
		};
	}
	if (!hasPersistedAuthoringMap || authoringMapDirty) {
		return {
			step: 'Map Overlay',
			status: 'ready',
			message: 'Save the edited overlay so backend compile/map/graph steps use the same source of truth.',
			action: 'Save Map Overlay',
			tab: 'scene',
			kind: 'save_overlay',
		};
	}
	if (!currentScene?.annotation_ok || currentScene?.sync_status?.annotation_stale) {
		return {
			step: 'Annotation',
			status: 'ready',
			message: currentScene?.sync_status?.annotation_stale
				? 'Map overlay changed after annotation compile. Compile again.'
				: 'Compile the map overlay into scene_annotation.json.',
			action: 'Compile Annotation',
			tab: 'scene',
			kind: 'compile_annotation',
		};
	}
	if (!hasMap || currentScene?.sync_status?.traversable_map_stale) {
		return {
			step: 'Traversable Map',
			status: 'ready',
			message: currentScene?.sync_status?.traversable_map_stale
				? 'Annotation changed after map build. Rebuild the traversable grid.'
				: 'Build the traversable grid from the compiled annotation.',
			action: 'Build Traversable Map',
			tab: 'plan',
			kind: 'build_map',
		};
	}
	if (!hasGraph || currentScene?.sync_status?.viewpoint_graph_stale) {
		return {
			step: 'Viewpoint Graph',
			status: 'ready',
			message: currentScene?.sync_status?.viewpoint_graph_stale
				? 'Traversable map changed after graph build. Rebuild the viewpoint graph.'
				: 'Build the panoramic viewpoint graph from the traversable map.',
			action: 'Build Viewpoint Graph',
			tab: 'plan',
			kind: 'build_graph',
		};
	}
	if (!hasEpisodes) {
		return {
			step: 'Episodes',
			status: 'ready',
			message: 'Generate graph episodes from the cached viewpoint graph.',
			action: 'Generate Graph Episodes',
			tab: 'plan',
			kind: 'plan_graph_episodes',
		};
	}
	if (!renderSceneSynced) {
		return {
			step: 'Render Scene Sync',
			status: 'ready',
			message: 'Sync editor overlays into render-scene artifacts before sensor sweep.',
			action: 'Sync Render Scene',
			tab: 'scene',
			kind: 'sync_render_scene',
		};
	}
	if (!renderConfigReady) {
		return {
			step: 'Sensor Sweep',
			status: 'blocked',
			message: 'Render-scene artifacts are synced, but scene state and camera spec are missing.',
			action: 'Configure Sensor Sweep',
			tab: 'render',
			kind: 'configure_render',
		};
	}
	if (!validationReport) {
		return {
			step: 'Validation',
			status: 'ready',
			message: 'Validate dataset structure before export.',
			action: 'Validate Dataset',
			tab: 'review',
			kind: 'validate',
		};
	}
	if (!validationPassed) {
		return {
			step: 'Validation',
			status: 'failed',
			message: 'Validation failed. Review errors before export.',
			action: 'Review Validation',
			tab: 'review',
			kind: 'review_validation',
		};
	}
	return {
		step: 'Export',
		status: 'ready',
		message: 'Dataset is validated and ready for packaging.',
		action: 'Export Dataset',
		tab: 'review',
		kind: 'export',
	};
}
