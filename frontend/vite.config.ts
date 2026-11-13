import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    fs: {
      allow: [
        fileURLToPath(new URL('.', import.meta.url)),
        fileURLToPath(new URL('../contracts/check-result.v1.synthetic.json', import.meta.url)),
        fileURLToPath(new URL('../docs/synthetic/nrt-89/inputs.json', import.meta.url)),
      ],
    },
    proxy: {
      '/health': process.env.DOCCHECK_API_TARGET ?? 'http://127.0.0.1:8000',
      '/api': process.env.DOCCHECK_API_TARGET ?? 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.test.{ts,tsx}', 'tests/integration/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/setup.ts'],
  },
});
