import { defineConfig } from 'vite';

export default defineConfig({
  esbuild: { jsx: 'automatic' },
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true, headers: { origin: 'http://127.0.0.1:8765' } } } },
  build: { target: 'es2022', chunkSizeWarningLimit: 650 },
});
