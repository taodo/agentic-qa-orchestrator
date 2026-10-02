import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  // Host-only proxy setting: never exposed as a frontend environment variable.
  const target = loadEnv(mode, process.cwd(), 'VITE_API_PROXY_TARGET').VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    envPrefix: 'PUBLIC_',
    server: { host: '127.0.0.1', proxy: { '/api/v1': { target, changeOrigin: true } } },
    test: { environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], restoreMocks: true },
  };
});
