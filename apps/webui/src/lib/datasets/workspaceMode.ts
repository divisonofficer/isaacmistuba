/**
 * The dataset editor has one workspace mode.  The right rail is contextual
 * presentation of that mode; it is not a second navigation state.
 */
export type WorkspaceMode = 'map' | 'objects' | 'paths' | 'sensors' | 'lights' | 'preview' | 'export';

export type InspectorKind =
	| 'scene'
	| 'selected'
	| 'paths'
	| 'sensors'
	| 'lights'
	| 'preview'
	| 'export';

export function resolveInspectorKind(mode: WorkspaceMode, hasSelection: boolean): InspectorKind {
	if (mode === 'map' || mode === 'objects') return hasSelection ? 'selected' : 'scene';
	return mode;
}
