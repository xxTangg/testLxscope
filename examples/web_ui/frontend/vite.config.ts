import path from 'path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import svgr from 'vite-plugin-svgr';

const agentscopeApiTarget = process.env.AGENTSCOPE_API_TARGET ?? 'http://127.0.0.1:8000';

export default defineConfig({
	plugins: [react(), tailwindcss(), svgr()],
	build: {
		// Deployments also run on Chromium 102 (Qaxbrowser).
		target: ['chrome102', 'edge102', 'firefox114', 'safari16.4', 'ios16.4'],
	},
	server: {
		proxy: {
			'/api': {
				target: agentscopeApiTarget,
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/api/, ''),
			},
		},
	},
	resolve: {
		alias: {
			'@': path.resolve(__dirname, './src'),
			'next/navigation': path.resolve(__dirname, './src/lib/next-navigation-shim.ts'),
		},
	},
	optimizeDeps: {
		include: ['mime-types'],
	},
});
