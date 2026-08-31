import { describe, expect, it } from 'vitest';
import { resolveInspectorKind } from '../workspaceMode';

describe('resolveInspectorKind', () => {
	it('keeps object selection contextual only in map/object workspaces', () => {
		expect(resolveInspectorKind('map', false)).toBe('scene');
		expect(resolveInspectorKind('objects', true)).toBe('selected');
		expect(resolveInspectorKind('paths', true)).toBe('paths');
	});
});
