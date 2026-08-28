export const MITSUBA_FROZEN_VIEWER = {
	label: 'Mitsuba Frozen',
	port: 8767,
	description: 'Mitsuba CUDA path tracing recorded and replayed through Dr.Jit freeze'
} as const;

export function liveViewerHost(
	override: string | null | undefined,
	hostname: string
): string {
	const explicit = override?.trim();
	return explicit || `${hostname}:${MITSUBA_FROZEN_VIEWER.port}`;
}
