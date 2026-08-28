import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

const backend = process.env.IR_VIEWER_BACKEND ?? 'http://127.0.0.1:8780';

export default defineConfig({
  plugins: [svelte()],
  // The shared project mount can exceed the host's low inotify watch quota.
  // Polling keeps the standalone viewer usable without requiring sysctl access.
  server: {
    watch: { usePolling: true, interval: 700 },
    proxy: { '/api': { target: backend, changeOrigin: true } }
  },
  build: { outDir: 'dist', emptyOutDir: true }
});
