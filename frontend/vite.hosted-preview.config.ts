import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist-hosted-preview',
    rollupOptions: {
      input: fileURLToPath(new URL('./hosted-preview.html', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api/preview/v1': process.env.DOCCHECK_PREVIEW_API_TARGET ?? 'http://127.0.0.1:18037',
    },
  },
});
