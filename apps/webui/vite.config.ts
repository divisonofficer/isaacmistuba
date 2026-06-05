import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, type ProxyOptions } from 'vite';

declare const process: {
	env: Record<string, string | undefined>;
};

// Matches RENDER_DAEMON_PORT default in run_control_plane_dev.sh
const DAEMON_HOST = process.env.RENDER_DAEMON_HOST ?? '127.0.0.1';
const DAEMON_PORT = process.env.RENDER_DAEMON_PORT ?? '8765';
const DAEMON = `http://${DAEMON_HOST}:${DAEMON_PORT}`;

const proxyOptions = {
	target: DAEMON,
	changeOrigin: true,
	secure: false
} satisfies ProxyOptions;

const wsProxyOptions = {
	target: DAEMON.replace('http://', 'ws://'),
	changeOrigin: true,
	secure: false,
	ws: true,
} satisfies ProxyOptions;

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		host: '0.0.0.0',  // WSL2에서 Windows 브라우저로 접근 가능
		proxy: {
			'/api/ws': wsProxyOptions,
			'/api': proxyOptions,
			'/jobs/': proxyOptions,
			'/isaac/session': proxyOptions,
			'/isaac/capture': proxyOptions,
			'/isaac/render': proxyOptions,
			'/health': proxyOptions,
			'/render': proxyOptions,
			'/artifacts': proxyOptions,
			'/static/tailwind.css': proxyOptions
		}
	}
});
