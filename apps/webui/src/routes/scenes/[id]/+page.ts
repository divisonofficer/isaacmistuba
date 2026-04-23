import type { PageLoad } from './$types';
export const load: PageLoad = ({ params }) => ({
	title: params.id,
	subtitle: 'Scene detail',
	sceneId: params.id
});
