<script lang="ts">
	interface Props {
		hasScene: boolean;
		hasMap: boolean;
		hasGraph: boolean;
		hasEpisodes: boolean;
		selectedProjectId: string;
		sceneId: string;
		episodesCount: number;
		splitCounts: any;
		currentScene: any;
		graphPayloadSummary: any;
		headingCount: number;
		selectedEpisodeSummary: any;
		validationReport: any;
		evaluationReport: any;
		exportPath: string;
	}

	let {
		hasScene, hasMap, hasGraph, hasEpisodes,
		selectedProjectId, sceneId, episodesCount, splitCounts,
		currentScene, graphPayloadSummary, headingCount,
		selectedEpisodeSummary, validationReport, evaluationReport, exportPath,
	}: Props = $props();
</script>

<section class="rail-section">
	<div class="rail-title">OpticalNav Status</div>
	<div class="rail-readiness">
		<span class:ready={hasScene}>Scene</span>
		<span class:ready={hasMap}>Map</span>
		<span class:ready={hasGraph}>Graph</span>
		<span class:ready={hasEpisodes}>Episodes</span>
	</div>
</section>

<section class="rail-section">
	<div class="rail-title">Project</div>
	<dl class="rail-kv">
		<div><dt>ID</dt><dd>{selectedProjectId || 'No project'}</dd></div>
		<div><dt>Scene</dt><dd>{sceneId || '-'}</dd></div>
		<div><dt>Episodes</dt><dd>{episodesCount}</dd></div>
		<div><dt>Splits</dt><dd>{Object.keys(splitCounts).length ? JSON.stringify(splitCounts) : '-'}</dd></div>
	</dl>
</section>

{#if currentScene}
	<section class="rail-section">
		<div class="rail-title">Scene Artifacts</div>
		<dl class="rail-kv">
			<div><dt>Map overlay</dt><dd>{currentScene.authoring_map_exists ? 'ready' : 'missing'}</dd></div>
			<div><dt>USD</dt><dd>{currentScene.usd_ref || 'not attached'}</dd></div>
			<div><dt>Annotation</dt><dd>{currentScene.annotation_ok ? 'valid' : 'needs check'}</dd></div>
			<div><dt>Render scene</dt><dd>{currentScene.sync_status?.render_scene ?? '-'}</dd></div>
			<div><dt>Isaac stage</dt><dd>{currentScene.sync_status?.isaac_stage ?? '-'}</dd></div>
			<div><dt>Map</dt><dd>{currentScene.map_exists ? 'ready' : 'missing'}</dd></div>
			<div><dt>Graph</dt><dd>{currentScene.viewpoint_graph_exists ? 'ready' : 'missing'}</dd></div>
		</dl>
	</section>
{/if}

{#if graphPayloadSummary || currentScene?.viewpoint_graph}
	<section class="rail-section">
		<div class="rail-title">Viewpoint Graph</div>
		<dl class="rail-kv">
			<div><dt>Nodes</dt><dd>{graphPayloadSummary?.node_count ?? currentScene?.viewpoint_graph?.node_count ?? '-'}</dd></div>
			<div><dt>Edges</dt><dd>{graphPayloadSummary?.edge_count ?? currentScene?.viewpoint_graph?.edge_count ?? '-'}</dd></div>
			<div><dt>Headings</dt><dd>{graphPayloadSummary?.heading_count ?? currentScene?.viewpoint_graph?.heading_count ?? headingCount}</dd></div>
			<div><dt>Hazard edges</dt><dd>{graphPayloadSummary?.hazard_edge_count ?? currentScene?.viewpoint_graph?.hazard_edge_count ?? '-'}</dd></div>
		</dl>
	</section>
{/if}

{#if selectedEpisodeSummary}
	<section class="rail-section">
		<div class="rail-title">Selected Episode</div>
		<dl class="rail-kv">
			<div><dt>ID</dt><dd>{selectedEpisodeSummary.episode_id}</dd></div>
			<div><dt>Mode</dt><dd>{selectedEpisodeSummary.mode}</dd></div>
			<div><dt>Split</dt><dd>{selectedEpisodeSummary.split}</dd></div>
			<div><dt>Path nodes</dt><dd>{selectedEpisodeSummary.path_nodes}</dd></div>
			<div><dt>Refs</dt><dd>{selectedEpisodeSummary.observation_refs}</dd></div>
		</dl>
	</section>
{/if}

{#if validationReport || evaluationReport || exportPath}
	<section class="rail-section">
		<div class="rail-title">Review Output</div>
		<dl class="rail-kv">
			<div><dt>Validation</dt><dd>{validationReport ? (validationReport.ok === false ? 'failed' : 'complete') : '-'}</dd></div>
			<div><dt>Success</dt><dd>{evaluationReport?.metrics?.success_rate ?? '-'}</dd></div>
			<div><dt>SPL</dt><dd>{evaluationReport?.metrics?.spl ?? '-'}</dd></div>
			<div><dt>Export</dt><dd>{exportPath || '-'}</dd></div>
		</dl>
	</section>
{/if}

<style>
	.rail-readiness {
			display: grid;
			grid-template-columns: 1fr 1fr;
			gap: var(--space-2);
		}

	.rail-readiness span {
			border: 1px solid var(--panel-border);
			border-radius: var(--radius-sm);
			background: var(--surface-1);
			color: var(--muted-strong);
			padding: var(--space-2);
			text-align: center;
		}

	.rail-readiness span.ready {
			border-color: var(--tool-traversable);
			background: var(--tool-traversable-soft);
			color: var(--tool-traversable);
		}

	.rail-kv {
			display: grid;
			gap: var(--space-2);
			margin: 0;
		}

	.rail-kv div {
			display: grid;
			grid-template-columns: 88px minmax(0, 1fr);
			gap: var(--space-2);
			align-items: start;
		}

	.rail-kv dt {
			color: var(--muted);
			font-size: var(--font-size-xs);
		}

	.rail-kv dd {
			margin: 0;
			min-width: 0;
			overflow-wrap: anywhere;
			font-size: var(--font-size-xs);
			color: var(--text);
		}
</style>
