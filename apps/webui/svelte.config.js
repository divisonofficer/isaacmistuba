import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter({
			pages: '../../modules/mitsuba_converter/src/mitsuba_converter/static/app',
			assets: '../../modules/mitsuba_converter/src/mitsuba_converter/static/app',
			fallback: 'index.html'
		}),
		paths: { base: '' }
	}
};

export default config;
